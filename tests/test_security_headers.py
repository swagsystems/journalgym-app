import sqlite3
import importlib
import os
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from fastapi.testclient import TestClient


class SecurityHeaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["FITNESS_DB_PATH"] = os.path.join(self.tmp.name, "fitness.db")
        os.environ["FITNESS_COOKIE_SECURE"] = "false"
        os.environ["FITNESS_REQUEST_BODY_MAX_BYTES"] = "64"

        import api.main

        self.main = importlib.reload(api.main)
        self.main.init_db()
        self.client = TestClient(self.main.app)

    def tearDown(self):
        os.environ.pop("FITNESS_REQUEST_BODY_MAX_BYTES", None)
        self.tmp.cleanup()

    def test_security_headers_are_added(self):
        response = self.client.get("/api/health")

        self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["referrer-policy"], "same-origin")
        self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])
        self.assertIn("camera=()", response.headers["permissions-policy"])

    def test_health_checks_database(self):
        response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "database": "ok"})

    def test_oversized_request_body_is_rejected(self):
        response = self.client.post(
            "/api/auth/setup",
            content=b"x" * 65,
            headers={"content-type": "application/json"},
        )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.text, "request body too large")

    def test_sqlite_locked_errors_return_service_unavailable(self):
        @contextmanager
        def locked_db():
            raise sqlite3.OperationalError("database is locked")
            yield

        with patch.object(self.main, "db", locked_db):
            response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.text, "database temporarily busy")
        self.assertEqual(response.headers["x-frame-options"], "DENY")


if __name__ == "__main__":
    unittest.main()
