import importlib
import os
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient


class AuthTransactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["FITNESS_DB_PATH"] = os.path.join(self.tmp.name, "fitness.db")
        os.environ["FITNESS_PIN_PEPPER_FILE"] = os.path.join(self.tmp.name, "pin.pepper")
        os.environ["FITNESS_COOKIE_SECURE"] = "false"
        os.environ.pop("FITNESS_PIN_PEPPER", None)
        os.environ.pop("FITNESS_ENABLE_API_DOCS", None)
        os.environ.pop("FITNESS_SESSION_MAX_PER_USER", None)
        os.environ.pop("FITNESS_LOGIN_ATTEMPT_RETENTION_SECONDS", None)

        import api.main

        self.main = importlib.reload(api.main)
        self.main.init_db()
        self.client = TestClient(self.main.app)
        self.client.post(
            "/api/auth/setup",
            json={"username": "admin", "display_name": "Admin", "pin": "482759"},
        )

    def tearDown(self):
        os.environ.pop("FITNESS_PIN_PEPPER_FILE", None)
        self.tmp.cleanup()

    def test_failed_login_attempt_is_committed(self):
        response = self.client.post(
            "/api/auth/login",
            json={"username": "admin", "pin": "000000"},
        )

        self.assertEqual(response.status_code, 401)
        with self.main.db() as conn:
            attempts = conn.execute(
                "SELECT username, success FROM login_attempts WHERE username = ?",
                ("admin",),
            ).fetchall()
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["success"], 0)

    def test_successful_login_attempt_survives_later_login_failure(self):
        with patch.object(self.main, "issue_session", side_effect=RuntimeError("session failed")):
            with self.assertRaises(RuntimeError):
                self.client.post("/api/auth/login", json={"username": "admin", "pin": "482759"})

        with self.main.db() as conn:
            attempts = conn.execute(
                "SELECT username, success FROM login_attempts WHERE username = ?",
                ("admin",),
            ).fetchall()
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["success"], 1)

    def test_db_commits_before_http_exception(self):
        with self.assertRaises(HTTPException):
            with self.main.db() as conn:
                conn.execute(
                    "INSERT INTO login_attempts (username, ip, success, attempted_at) VALUES (?, ?, ?, ?)",
                    ("admin", "127.0.0.1", 0, 1),
                )
                raise HTTPException(status_code=400, detail="intentional")

        with self.main.db() as conn:
            count = conn.execute("SELECT COUNT(*) FROM login_attempts").fetchone()[0]
        self.assertEqual(count, 1)

    def test_api_docs_are_disabled_by_default(self):
        self.assertEqual(self.client.get("/docs").status_code, 404)
        self.assertEqual(self.client.get("/openapi.json").status_code, 404)

    def test_login_username_uses_same_constraints_as_user_creation(self):
        too_short = self.client.post("/api/auth/login", json={"username": "a", "pin": "000000"})
        invalid_chars = self.client.post("/api/auth/login", json={"username": "bad user", "pin": "000000"})

        self.assertEqual(too_short.status_code, 422)
        self.assertEqual(invalid_chars.status_code, 422)

    def test_setup_rechecks_under_write_lock(self):
        response = self.client.post(
            "/api/auth/setup",
            json={"username": "other", "display_name": "Other", "pin": "482751"},
        )

        self.assertEqual(response.status_code, 409)

    def test_successful_login_sets_last_login_timestamp(self):
        self.client.post("/api/auth/logout")
        response = self.client.post("/api/auth/login", json={"username": "admin", "pin": "482759"})

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.json()["user"]["last_login_at"])
        with self.main.db() as conn:
            row = conn.execute(
                "SELECT last_login_at, updated_at FROM users WHERE username = ?",
                ("admin",),
            ).fetchone()
        self.assertIsNotNone(row["last_login_at"])
        self.assertIsNotNone(row["updated_at"])

    def test_pin_change_requires_new_pin_to_differ(self):
        response = self.client.put(
            "/api/auth/pin",
            json={"current_pin": "482759", "new_pin": "482759"},
        )

        self.assertEqual(response.status_code, 422)

    def test_username_failures_only_apply_soft_delay(self):
        now = 1_800_000_000
        with self.main.db() as conn:
            for idx in range(8):
                conn.execute(
                    "INSERT INTO login_attempts (username, ip, success, attempted_at) VALUES (?, ?, ?, ?)",
                    ("admin", f"192.0.2.{idx}", 0, now),
                )

        with self.main.db() as conn:
            self.assertFalse(self.main.login_ip_is_limited(conn, "198.51.100.10"))
            self.assertGreater(self.main.login_account_delay_seconds(conn, "admin"), 0)

    def test_ip_failures_apply_hard_limit(self):
        now = 1_800_000_000
        with self.main.db() as conn:
            for idx in range(8):
                conn.execute(
                    "INSERT INTO login_attempts (username, ip, success, attempted_at) VALUES (?, ?, ?, ?)",
                    (f"user{idx}", "198.51.100.10", 0, now),
                )

        with self.main.db() as conn:
            self.assertTrue(self.main.login_ip_is_limited(conn, "198.51.100.10"))

    def test_old_login_attempts_are_pruned_during_login(self):
        old_attempt_at = int(time.time()) - self.main.LOGIN_ATTEMPT_RETENTION_SECONDS - 10
        with self.main.db() as conn:
            conn.execute(
                "INSERT INTO login_attempts (username, ip, success, attempted_at) VALUES (?, ?, ?, ?)",
                ("admin", "203.0.113.10", 0, old_attempt_at),
            )

        response = self.client.post("/api/auth/login", json={"username": "admin", "pin": "000000"})

        self.assertEqual(response.status_code, 401)
        with self.main.db() as conn:
            old_count = conn.execute(
                "SELECT COUNT(*) FROM login_attempts WHERE ip = ?",
                ("203.0.113.10",),
            ).fetchone()[0]
            new_count = conn.execute(
                "SELECT COUNT(*) FROM login_attempts WHERE username = ?",
                ("admin",),
            ).fetchone()[0]
        self.assertEqual(old_count, 0)
        self.assertEqual(new_count, 1)

    def test_weak_pins_are_rejected_for_setup_create_reset_and_change(self):
        with self.assertRaises(ValueError):
            self.main.AuthSetupIn(username="root", display_name="Root", pin="123456")

        repeated = self.client.post(
            "/api/users",
            json={"username": "weak1", "display_name": "Weak One", "pin": "111111", "role": "user"},
        )
        sequential = self.client.post(
            "/api/users",
            json={"username": "weak2", "display_name": "Weak Two", "pin": "654321", "role": "user"},
        )
        common = self.client.post(
            "/api/users",
            json={"username": "weak3", "display_name": "Weak Three", "pin": "121212", "role": "user"},
        )

        self.assertEqual(repeated.status_code, 422)
        self.assertEqual(sequential.status_code, 422)
        self.assertEqual(common.status_code, 422)

        created = self.client.post(
            "/api/users",
            json={"username": "strong", "display_name": "Strong", "pin": "482751", "role": "user"},
        ).json()
        reset = self.client.put(f"/api/users/{created['id']}/pin", json={"pin": "987654"})
        change = self.client.put(
            "/api/auth/pin",
            json={"current_pin": "482759", "new_pin": "123123"},
        )

        self.assertEqual(reset.status_code, 422)
        self.assertEqual(change.status_code, 422)

    def test_new_pin_hashes_use_application_pepper(self):
        with self.main.db() as conn:
            row = conn.execute(
                "SELECT pin_salt, pin_hash FROM users WHERE username = ?",
                ("admin",),
            ).fetchone()

        salt = self.main.decode_bytes(row["pin_salt"])
        _, legacy_digest = self.main.hash_pin("482759", salt, peppered=False)

        self.assertNotEqual(row["pin_hash"], legacy_digest)
        self.assertTrue(os.path.exists(os.environ["FITNESS_PIN_PEPPER_FILE"]))

    def test_legacy_unpeppered_pin_hash_is_upgraded_on_login(self):
        salt, legacy_digest = self.main.hash_pin("482751", peppered=False)
        with self.main.db() as conn:
            conn.execute(
                """
                INSERT INTO users (username, display_name, pin_salt, pin_hash, role)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("legacy", "Legacy", salt, legacy_digest, "user"),
            )

        response = self.client.post("/api/auth/login", json={"username": "legacy", "pin": "482751"})

        self.assertEqual(response.status_code, 200)
        with self.main.db() as conn:
            row = conn.execute(
                "SELECT pin_salt, pin_hash FROM users WHERE username = ?",
                ("legacy",),
            ).fetchone()
        self.assertTrue(self.main.verify_pin("482751", row["pin_salt"], row["pin_hash"]))
        self.assertNotEqual(row["pin_hash"], legacy_digest)

    def test_changing_own_pin_revokes_existing_sessions(self):
        with self.main.db() as conn:
            user_id = conn.execute("SELECT id FROM users WHERE username = ?", ("admin",)).fetchone()[0]
            extra_token = self.main.issue_session(conn, user_id)
            old_hashes = {
                row["token_hash"]
                for row in conn.execute("SELECT token_hash FROM sessions WHERE user_id = ?", (user_id,)).fetchall()
            }
            old_hashes.add(self.main.hash_session_token(extra_token))

        response = self.client.put(
            "/api/auth/pin",
            json={"current_pin": "482759", "new_pin": "482753"},
        )

        self.assertEqual(response.status_code, 200)
        with self.main.db() as conn:
            new_hashes = {
                row["token_hash"]
                for row in conn.execute("SELECT token_hash FROM sessions WHERE user_id = ?", (user_id,)).fetchall()
            }
        self.assertEqual(len(new_hashes), 1)
        self.assertTrue(old_hashes.isdisjoint(new_hashes))

    def test_admin_pin_reset_revokes_target_user_sessions(self):
        created = self.client.post(
            "/api/users",
            json={"username": "member", "display_name": "Member", "pin": "482751", "role": "user"},
        ).json()
        with self.main.db() as conn:
            self.main.issue_session(conn, created["id"])
            self.main.issue_session(conn, created["id"])

        response = self.client.put(f"/api/users/{created['id']}/pin", json={"pin": "482753"})

        self.assertEqual(response.status_code, 200)
        with self.main.db() as conn:
            count = conn.execute("SELECT COUNT(*) FROM sessions WHERE user_id = ?", (created["id"],)).fetchone()[0]
        self.assertEqual(count, 0)

    def test_logout_all_devices_revokes_every_session_for_current_user(self):
        with self.main.db() as conn:
            user_id = conn.execute("SELECT id FROM users WHERE username = ?", ("admin",)).fetchone()[0]
            self.main.issue_session(conn, user_id)
            self.main.issue_session(conn, user_id)

        response = self.client.post("/api/auth/logout-all")

        self.assertEqual(response.status_code, 200)
        with self.main.db() as conn:
            count = conn.execute("SELECT COUNT(*) FROM sessions WHERE user_id = ?", (user_id,)).fetchone()[0]
        self.assertEqual(count, 0)
        self.assertIsNone(self.client.get("/api/auth/me").json()["user"])

    def test_session_issue_caps_sessions_per_user(self):
        with self.main.db() as conn:
            user_id = conn.execute("SELECT id FROM users WHERE username = ?", ("admin",)).fetchone()[0]
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            tokens = [self.main.issue_session(conn, user_id) for _ in range(self.main.SESSION_MAX_PER_USER + 2)]
            hashes = {
                row["token_hash"]
                for row in conn.execute("SELECT token_hash FROM sessions WHERE user_id = ?", (user_id,)).fetchall()
            }

        self.assertEqual(len(hashes), self.main.SESSION_MAX_PER_USER)
        self.assertNotIn(self.main.hash_session_token(tokens[0]), hashes)
        self.assertNotIn(self.main.hash_session_token(tokens[1]), hashes)
        self.assertIn(self.main.hash_session_token(tokens[-1]), hashes)

    def test_expired_sessions_are_pruned_during_auth_checks(self):
        expired_token = "expired-token"
        with self.main.db() as conn:
            user_id = conn.execute("SELECT id FROM users WHERE username = ?", ("admin",)).fetchone()[0]
            conn.execute(
                "INSERT INTO sessions (user_id, token_hash, expires_at, created_at) VALUES (?, ?, ?, ?)",
                (user_id, self.main.hash_session_token(expired_token), 1, 1),
            )

        response = self.client.get("/api/auth/me")

        self.assertEqual(response.status_code, 200)
        with self.main.db() as conn:
            count = conn.execute("SELECT COUNT(*) FROM sessions WHERE token_hash = ?", (self.main.hash_session_token(expired_token),)).fetchone()[0]
        self.assertEqual(count, 0)

    def test_user_management_guards_last_admin(self):
        admin = self.client.get("/api/users").json()[0]
        demote = self.client.put(
            f"/api/users/{admin['id']}",
            json={"username": "admin", "display_name": "Admin", "role": "user", "is_active": True},
        )
        self.assertEqual(demote.status_code, 400)

        created = self.client.post(
            "/api/users",
            json={"username": "coach", "display_name": "Coach", "pin": "482751", "role": "admin"},
        ).json()
        updated = self.client.put(
            f"/api/users/{created['id']}",
            json={"username": "coach2", "display_name": "Coach Two", "role": "user", "is_active": False},
        )

        self.assertEqual(updated.status_code, 200)
        body = updated.json()
        self.assertEqual(body["username"], "coach2")
        self.assertEqual(body["display_name"], "Coach Two")
        self.assertEqual(body["role"], "user")
        self.assertFalse(body["is_active"])

    def test_delete_user_without_workouts(self):
        created = self.client.post(
            "/api/users",
            json={"username": "temp", "display_name": "Temp", "pin": "482751", "role": "user"},
        ).json()

        deleted = self.client.delete(f"/api/users/{created['id']}")

        self.assertEqual(deleted.status_code, 200)
        usernames = [user["username"] for user in self.client.get("/api/users").json()]
        self.assertNotIn("temp", usernames)


if __name__ == "__main__":
    unittest.main()
