import importlib
import os
import tempfile
import unittest
from datetime import date, timedelta

from fastapi.testclient import TestClient


class WorkoutApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["FITNESS_DB_PATH"] = os.path.join(self.tmp.name, "fitness.db")
        os.environ["FITNESS_COOKIE_SECURE"] = "false"

        import api.main

        self.main = importlib.reload(api.main)
        self.main.init_db()
        self.client = TestClient(self.main.app)
        self.client.post(
            "/api/auth/setup",
            json={"username": "admin", "display_name": "Admin", "pin": "482759"},
        )
        exercises = self.client.get("/api/exercises").json()
        self.exercise_id = exercises[0]["id"]
        self.exercise_muscle = exercises[0]["primary_muscle"]

    def tearDown(self):
        self.tmp.cleanup()

    def test_update_workout_replaces_sets(self):
        created = self.client.post(
            "/api/workouts",
            json={
                "workout_date": "2026-05-15",
                "title": "Push",
                "bodyweight_lbs": 182.4,
                "notes": "original",
                "sets": [
                    {"exercise_id": self.exercise_id, "weight_lbs": 100, "reps": 5, "set_type": "warmup", "group_label": "A1", "rest_seconds": 90, "tempo": "3-1-1"},
                    {"exercise_id": self.exercise_id, "weight_lbs": 105, "reps": 3},
                ],
            },
        ).json()

        response = self.client.put(
            f"/api/workouts/{created['id']}",
            json={
                "workout_date": "2026-05-16",
                "title": "Updated Push",
                "notes": "edited",
                "sets": [
                    {"exercise_id": self.exercise_id, "weight_lbs": 115, "reps": 4},
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        updated = response.json()
        self.assertEqual(updated["workout_date"], "2026-05-16")
        self.assertEqual(updated["title"], "Updated Push")
        self.assertEqual(updated["bodyweight_lbs"], None)
        self.assertEqual(updated["set_count"], 1)
        self.assertEqual(updated["sets"][0]["weight_lbs"], 115)
        self.assertEqual(updated["sets"][0]["reps"], 4)
        self.assertEqual(updated["sets"][0]["set_type"], "working")
        self.assertIsNone(updated["sets"][0]["rpe"])
        self.assertIsNone(updated["sets"][0]["duration_seconds"])
        self.assertIsNone(updated["sets"][0]["rest_seconds"])
        self.assertIsNone(updated["sets"][0]["tempo"])

    def test_warmup_sets_do_not_count_for_prs_or_volume(self):
        self.client.post(
            "/api/workouts",
            json={
                "workout_date": "2026-05-15",
                "title": "Warmups",
                "sets": [
                    {"exercise_id": self.exercise_id, "weight_lbs": 500, "reps": 1, "set_type": "warmup", "rest_seconds": 90, "tempo": "3-1-1"},
                    {"exercise_id": self.exercise_id, "weight_lbs": 100, "reps": 5, "set_type": "working", "group_label": "A1"},
                ],
            },
        )

        workout = self.client.get("/api/workouts").json()[0]
        dashboard = self.client.get("/api/dashboard").json()
        progression = self.client.get(f"/api/exercises/{self.exercise_id}/progression").json()

        self.assertEqual(workout["volume_lbs"], 500)
        self.assertEqual(dashboard["prs"][0]["weight_lbs"], 100)
        self.assertEqual(progression["stats"]["best_estimated_1rm"], self.main.estimate_1rm(100, 5))
        detail = self.client.get(f"/api/workouts/{workout['id']}").json()
        self.assertEqual(detail["sets"][0]["rest_seconds"], 90)
        self.assertEqual(detail["sets"][0]["tempo"], "3-1-1")

    def test_bodyweight_sets_use_effective_weight_for_volume_and_prs(self):
        pullup_id = next(row["id"] for row in self.client.get("/api/exercises").json() if row["name"] == "Pull-Up")
        created = self.client.post(
            "/api/workouts",
            json={
                "workout_date": "2026-05-16",
                "bodyweight_lbs": 180,
                "sets": [
                    {
                        "exercise_id": pullup_id,
                        "weight_lbs": 0,
                        "weight_mode": "bodyweight",
                        "reps": 10,
                        "duration_seconds": 45,
                        "rpe": 8,
                    }
                ],
            },
        )

        self.assertEqual(created.status_code, 200)
        detail = created.json()
        self.assertEqual(detail["sets"][0]["effective_weight_lbs"], 180)
        self.assertEqual(detail["sets"][0]["duration_seconds"], 45)
        self.assertEqual(detail["volume_lbs"], 1800)
        dashboard = self.client.get("/api/dashboard").json()
        pr = next(row for row in dashboard["prs"] if row["exercise_id"] == pullup_id)
        self.assertEqual(pr["effective_weight_lbs"], 180)
        self.assertGreater(pr["estimated_1rm"], 0)

    def test_exercise_history_lists_every_set(self):
        self.client.post(
            "/api/workouts",
            json={
                "workout_date": "2026-05-16",
                "sets": [
                    {"exercise_id": self.exercise_id, "weight_lbs": 100, "reps": 5},
                    {"exercise_id": self.exercise_id, "weight_lbs": 105, "reps": 3, "rpe": 8},
                ],
            },
        )

        history = self.client.get(f"/api/exercises/{self.exercise_id}/history").json()

        self.assertEqual(len(history), 2)
        self.assertEqual([row["weight_lbs"] for row in history], [105, 100])
        self.assertEqual(history[0]["estimated_1rm"], self.main.estimate_1rm(105, 3))

    def test_workout_history_search_matches_title_notes_and_exercise(self):
        self.client.post(
            "/api/workouts",
            json={
                "workout_date": "2026-05-16",
                "title": "Heavy Push",
                "notes": "felt fast",
                "sets": [{"exercise_id": self.exercise_id, "weight_lbs": 100, "reps": 5}],
            },
        )

        by_title = self.client.get("/api/workouts?q=heavy").json()
        by_notes = self.client.get("/api/workouts?q=fast").json()
        exercise_name = next(row["name"] for row in self.client.get("/api/exercises").json() if row["id"] == self.exercise_id)
        by_exercise = self.client.get(f"/api/workouts?q={exercise_name.split()[0]}").json()
        empty = self.client.get("/api/workouts?q=doesnotexist").json()

        self.assertEqual(len(by_title), 1)
        self.assertEqual(len(by_notes), 1)
        self.assertEqual(len(by_exercise), 1)
        self.assertEqual(empty, [])

    def test_dashboard_includes_training_days(self):
        self.client.post(
            "/api/workouts",
            json={
                "workout_date": "2026-05-16",
                "sets": [{"exercise_id": self.exercise_id, "weight_lbs": 100, "reps": 5}],
            },
        )

        dashboard = self.client.get("/api/dashboard").json()

        self.assertIn({"workout_date": "2026-05-16", "workouts": 1}, dashboard["training_days"])
        self.assertIn("current_streak_days", dashboard)

    def test_dashboard_includes_weekly_muscle_targets(self):
        workout_date = date.today().isoformat()
        self.client.post(
            "/api/workouts",
            json={
                "workout_date": workout_date,
                "sets": [
                    {"exercise_id": self.exercise_id, "weight_lbs": 45, "reps": 5, "set_type": "warmup"},
                    {"exercise_id": self.exercise_id, "weight_lbs": 100, "reps": 5},
                    {"exercise_id": self.exercise_id, "weight_lbs": 105, "reps": 5},
                ],
            },
        )

        dashboard = self.client.get("/api/dashboard").json()
        target = next(row for row in dashboard["muscle_targets"] if row["muscle"] == self.exercise_muscle)

        self.assertEqual(target["sets"], 2)
        self.assertEqual(target["target_sets"], self.main.WEEKLY_MUSCLE_TARGET_SETS)
        self.assertEqual(target["remaining_sets"], self.main.WEEKLY_MUSCLE_TARGET_SETS - 2)
        self.assertEqual(target["status"], "under")

    def test_goals_track_strength_and_bodyweight_progress(self):
        goal_date = (date.today() + timedelta(days=90)).isoformat()
        self.client.post(
            "/api/workouts",
            json={
                "workout_date": date.today().isoformat(),
                "sets": [{"exercise_id": self.exercise_id, "weight_lbs": 100, "reps": 5}],
            },
        )
        self.client.post(
            "/api/body-measurements",
            json={"measured_date": date.today().isoformat(), "bodyweight_lbs": 185},
        )

        strength_goal = self.client.post(
            "/api/goals",
            json={
                "kind": "one_rep_max",
                "exercise_id": self.exercise_id,
                "target_value_lbs": 150,
                "target_date": goal_date,
                "notes": "test peak",
            },
        ).json()
        self.client.post(
            "/api/goals",
            json={"kind": "bodyweight", "target_value_lbs": 180, "target_date": goal_date},
        )

        goals = self.client.get("/api/goals").json()
        dashboard_goals = self.client.get("/api/dashboard").json()["active_goals"]
        strength = next(row for row in dashboard_goals if row["id"] == strength_goal["id"])
        bodyweight = next(row for row in dashboard_goals if row["kind"] == "bodyweight")

        self.assertEqual(len(goals), 2)
        self.assertEqual(strength["target_date"], goal_date)
        self.assertEqual(strength["current_value_lbs"], self.main.estimate_1rm(100, 5))
        self.assertEqual(strength["status"], "tracking")
        self.assertEqual(bodyweight["current_value_lbs"], 185)
        self.assertEqual(bodyweight["delta_lbs"], -5)

        deleted = self.client.delete(f"/api/goals/{strength_goal['id']}")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(len(self.client.get("/api/goals").json()), 1)

    def test_user_settings_persist_and_export(self):
        defaults = self.client.get("/api/settings").json()
        self.assertEqual(defaults["unit"], "lb")
        updated = self.client.put(
            "/api/settings",
            json={"unit": "kg", "default_rest_seconds": 180, "default_reps": 10, "theme": "dark", "reminder_enabled": True, "reminder_hour": 19},
        ).json()

        exported = self.client.get("/api/export.json").json()

        self.assertEqual(updated["unit"], "kg")
        self.assertEqual(updated["reminder_hour"], 19)
        self.assertEqual(self.client.get("/api/settings").json()["default_reps"], 10)
        self.assertEqual(exported["settings"]["default_rest_seconds"], 180)
        self.assertEqual(exported["settings"]["reminder_enabled"], True)

    def test_account_self_service_wipes_data_and_protects_last_admin(self):
        self.client.post(
            "/api/workouts",
            json={
                "workout_date": date.today().isoformat(),
                "sets": [{"exercise_id": self.exercise_id, "weight_lbs": 100, "reps": 5}],
            },
        )
        self.client.post(
            "/api/body-measurements",
            json={"measured_date": date.today().isoformat(), "bodyweight_lbs": 185},
        )
        self.client.post(
            "/api/goals",
            json={"kind": "one_rep_max", "exercise_id": self.exercise_id, "target_value_lbs": 150},
        )

        wiped = self.client.delete("/api/account/data")
        dashboard = self.client.get("/api/dashboard").json()
        protected = self.client.delete("/api/account")

        self.assertEqual(wiped.status_code, 200)
        self.assertEqual(self.client.get("/api/workouts").json(), [])
        self.assertEqual(self.client.get("/api/body-measurements").json(), [])
        self.assertEqual(self.client.get("/api/goals").json(), [])
        self.assertEqual(dashboard["weekly"], [])
        self.assertEqual(protected.status_code, 400)

    def test_metrics_reports_non_sensitive_counts(self):
        metrics = self.client.get("/api/metrics").json()

        self.assertEqual(metrics["status"], "ok")
        self.assertIn("uptime_seconds", metrics)
        self.assertGreaterEqual(metrics["users"], 1)
        self.assertGreaterEqual(metrics["exercises"], 1)

    def test_non_admin_can_delete_own_account(self):
        self.client.post(
            "/api/users",
            json={"username": "user2", "display_name": "User Two", "pin": "583920", "role": "user"},
        )
        self.client.post("/api/auth/logout")
        self.client.post("/api/auth/login", json={"username": "user2", "pin": "583920"})

        deleted = self.client.delete("/api/account")
        auth = self.client.get("/api/auth/me").json()

        self.assertEqual(deleted.status_code, 200)
        self.assertIsNone(auth["user"])

    def test_workout_volume_matches_sum_of_rounded_set_volumes(self):
        created = self.client.post(
            "/api/workouts",
            json={
                "workout_date": "2026-05-15",
                "title": "Rounding",
                "sets": [
                    {"exercise_id": self.exercise_id, "weight_lbs": 0.14, "reps": 1},
                    {"exercise_id": self.exercise_id, "weight_lbs": 0.14, "reps": 1},
                ],
            },
        ).json()

        listed = self.client.get("/api/workouts").json()[0]
        detail = self.client.get(f"/api/workouts/{created['id']}").json()

        self.assertEqual([row["volume_lbs"] for row in detail["sets"]], [0.1, 0.1])
        self.assertIsNotNone(detail["sets"][0]["updated_at"])
        self.assertEqual(listed["volume_lbs"], 0.2)
        self.assertEqual(detail["volume_lbs"], 0.2)

    def test_workout_bodyweight_round_trips(self):
        created = self.client.post(
            "/api/workouts",
            json={
                "workout_date": "2026-05-15",
                "title": "Weigh In",
                "bodyweight_lbs": 181.2,
                "sets": [{"exercise_id": self.exercise_id, "weight_lbs": 100, "reps": 5}],
            },
        )

        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.json()["bodyweight_lbs"], 181.2)
        listed = self.client.get("/api/workouts").json()
        self.assertEqual(listed[0]["bodyweight_lbs"], 181.2)

    def test_future_workout_dates_are_rejected(self):
        future = (date.today() + timedelta(days=1)).isoformat()
        response = self.client.post(
            "/api/workouts",
            json={
                "workout_date": future,
                "title": "Future",
                "sets": [{"exercise_id": self.exercise_id, "weight_lbs": 100, "reps": 5}],
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_workout_list_supports_offset_pagination(self):
        for day in range(1, 5):
            self.client.post(
                "/api/workouts",
                json={
                    "workout_date": f"2026-05-{day:02d}",
                    "title": f"Workout {day}",
                    "sets": [{"exercise_id": self.exercise_id, "weight_lbs": 100, "reps": 5}],
                },
            )

        first_page = self.client.get("/api/workouts?limit=2").json()
        second_page = self.client.get("/api/workouts?limit=2&offset=2").json()

        self.assertEqual([row["title"] for row in first_page], ["Workout 4", "Workout 3"])
        self.assertEqual([row["title"] for row in second_page], ["Workout 2", "Workout 1"])

    def test_set_numbers_reset_per_exercise_and_preserve_entry_order(self):
        exercises = self.client.get("/api/exercises").json()
        first_exercise = exercises[0]["id"]
        second_exercise = exercises[1]["id"]
        created = self.client.post(
            "/api/workouts",
            json={
                "workout_date": "2026-05-15",
                "title": "Alternating",
                "sets": [
                    {"exercise_id": first_exercise, "weight_lbs": 100, "reps": 5},
                    {"exercise_id": second_exercise, "weight_lbs": 50, "reps": 8},
                    {"exercise_id": first_exercise, "weight_lbs": 105, "reps": 5},
                    {"exercise_id": second_exercise, "weight_lbs": 55, "reps": 8},
                ],
            },
        ).json()

        detail = self.client.get(f"/api/workouts/{created['id']}").json()

        self.assertEqual([row["exercise_id"] for row in detail["sets"]], [first_exercise, second_exercise, first_exercise, second_exercise])
        self.assertEqual([row["set_number"] for row in detail["sets"]], [1, 1, 2, 2])

    def test_workout_and_set_notes_have_max_length(self):
        long_note = "x" * (self.main.NOTE_MAX_LENGTH + 1)
        workout_note = self.client.post(
            "/api/workouts",
            json={
                "workout_date": "2026-05-15",
                "title": "Long Workout",
                "notes": long_note,
                "sets": [{"exercise_id": self.exercise_id, "weight_lbs": 100, "reps": 5}],
            },
        )
        set_note = self.client.post(
            "/api/workouts",
            json={
                "workout_date": "2026-05-15",
                "title": "Long Set",
                "sets": [{"exercise_id": self.exercise_id, "weight_lbs": 100, "reps": 5, "notes": long_note}],
            },
        )

        self.assertEqual(workout_note.status_code, 422)
        self.assertEqual(set_note.status_code, 422)

    def test_workout_set_count_has_max_length(self):
        response = self.client.post(
            "/api/workouts",
            json={
                "workout_date": "2026-05-15",
                "title": "Too Many Sets",
                "sets": [
                    {"exercise_id": self.exercise_id, "weight_lbs": 100, "reps": 5}
                    for _ in range(self.main.WORKOUT_SET_MAX_COUNT + 1)
                ],
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_set_weight_has_max_value(self):
        response = self.client.post(
            "/api/workouts",
            json={
                "workout_date": "2026-05-15",
                "title": "Impossible Weight",
                "sets": [{"exercise_id": self.exercise_id, "weight_lbs": self.main.SET_WEIGHT_MAX_LBS + 1, "reps": 5}],
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_dashboard_uses_readable_week_labels(self):
        self.client.post(
            "/api/workouts",
            json={
                "workout_date": "2026-05-15",
                "title": "Week Label",
                "sets": [{"exercise_id": self.exercise_id, "weight_lbs": 100, "reps": 5}],
            },
        )

        dashboard = self.client.get("/api/dashboard").json()

        self.assertEqual(dashboard["weekly"][0]["week"], "2026-05-11")
        self.assertEqual(dashboard["weekly"][0]["week_start"], "2026-05-11")
        self.assertEqual(dashboard["weekly"][0]["week_end"], "2026-05-17")
        self.assertEqual(dashboard["weekly"][0]["week_label"], "May 11-17")
        self.assertEqual(dashboard["volume_by_muscle"][0]["week_label"], "May 11-17")

    def test_dashboard_muscle_volume_includes_role_buckets(self):
        exercise = self.client.post(
            "/api/exercises",
            json={
                "name": "Role Bucket Press",
                "primary_muscle": "Chest",
                "equipment": "Barbell",
                "secondary_muscles": ["Triceps", "Core"],
                "aliases": [],
                "notes": "",
            },
        ).json()
        self.client.post(
            "/api/workouts",
            json={
                "workout_date": "2026-05-15",
                "title": "Role Buckets",
                "sets": [{"exercise_id": exercise["id"], "weight_lbs": 100, "reps": 5}],
            },
        )

        dashboard = self.client.get("/api/dashboard").json()
        rows = {
            (row["muscle"], row["role"]): row
            for row in dashboard["volume_by_muscle"]
            if row["week"] == "2026-05-11"
        }

        self.assertEqual(rows[("Chest", "primary")]["volume_lbs"], 500)
        self.assertEqual(rows[("Triceps", "secondary")]["volume_lbs"], 500)
        self.assertEqual(rows[("Core", "stabilizer")]["volume_lbs"], 500)
        self.assertEqual(rows[("Chest", "primary")]["sets"], 1)

    def test_progression_includes_bodyweight_strength_context(self):
        bench_id = next(row["id"] for row in self.client.get("/api/exercises").json() if row["name"] == "Barbell Bench Press")
        self.client.post(
            "/api/workouts",
            json={
                "workout_date": "2026-05-15",
                "title": "Bench Day",
                "bodyweight_lbs": 200,
                "sets": [{"exercise_id": bench_id, "weight_lbs": 200, "reps": 1}],
            },
        )
        self.client.post(
            "/api/body-measurements",
            json={"measured_date": "2026-05-16", "bodyweight_lbs": 195},
        )

        progression = self.client.get(f"/api/exercises/{bench_id}/progression").json()

        self.assertEqual(progression["stats"]["latest_bodyweight_lbs"], 195)
        self.assertEqual(progression["stats"]["latest_bodyweight_date"], "2026-05-16")
        self.assertEqual(progression["stats"]["bodyweight_ratio"], 1.03)
        self.assertEqual(progression["stats"]["strength_standard"], "bodyweight bench")

    def test_body_measurements_are_user_scoped(self):
        created = self.client.post(
            "/api/body-measurements",
            json={
                "measured_date": "2026-05-16",
                "bodyweight_lbs": 181.2,
                "waist_in": 32.5,
                "photo_url": "https://example.test/progress.jpg",
                "notes": "morning",
            },
        )

        self.assertEqual(created.status_code, 200)
        row = created.json()
        self.assertEqual(row["bodyweight_lbs"], 181.2)
        self.assertEqual(row["waist_in"], 32.5)
        self.assertEqual(row["photo_url"], "https://example.test/progress.jpg")

        rows = self.client.get("/api/body-measurements").json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], row["id"])

        deleted = self.client.delete(f"/api/body-measurements/{row['id']}")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self.client.get("/api/body-measurements").json(), [])

    def test_json_export_and_import_round_trip(self):
        self.client.post(
            "/api/workouts",
            json={
                "workout_date": "2026-05-15",
                "title": "Export Me",
                "bodyweight_lbs": 181.2,
                "sets": [{"exercise_id": self.exercise_id, "weight_lbs": 100, "reps": 5}],
            },
        )
        self.client.post(
            "/api/body-measurements",
            json={"measured_date": "2026-05-15", "bodyweight_lbs": 181.2, "waist_in": 32.5},
        )

        bundle = self.client.get("/api/export.json").json()
        self.assertEqual(bundle["version"], 1)
        self.assertEqual(bundle["workouts"][0]["title"], "Export Me")
        self.assertIn("exercise_name", bundle["workouts"][0]["sets"][0])
        csv_response = self.client.get("/api/export.csv")
        self.assertIn("exercise_name", csv_response.text)

        imported = self.client.post("/api/import.json", json=bundle)
        self.assertEqual(imported.status_code, 200)
        self.assertEqual(imported.json()["imported_workouts"], 1)
        self.assertEqual(imported.json()["imported_measurements"], 1)

    def test_one_rep_max_formula_matches_python_and_sql(self):
        self.client.post(
            "/api/workouts",
            json={
                "workout_date": "2026-05-15",
                "title": "Heavy Single",
                "sets": [
                    {"exercise_id": self.exercise_id, "weight_lbs": 300, "reps": 1},
                ],
            },
        )

        dashboard = self.client.get("/api/dashboard").json()
        progression = self.client.get(f"/api/exercises/{self.exercise_id}/progression").json()

        self.assertEqual(self.main.estimate_1rm(300, 1), 300)
        self.assertEqual(dashboard["prs"][0]["estimated_1rm"], 300)
        self.assertEqual(progression["points"][0]["best_estimated_1rm"], 300)
        self.assertEqual(progression["stats"]["best_estimated_1rm"], 300)
        self.assertEqual(progression["stats"]["max_reps"], 1)
        self.assertEqual(progression["stats"]["total_sets"], 1)
        self.assertEqual(progression["stats"]["last_trained"], "2026-05-15")

    def test_pr_detection_deduplicates_ties(self):
        for workout_date in ("2026-05-15", "2026-05-16"):
            self.client.post(
                "/api/workouts",
                json={
                    "workout_date": workout_date,
                    "title": "Tie Day",
                    "sets": [
                        {"exercise_id": self.exercise_id, "weight_lbs": 100, "reps": 5},
                        {"exercise_id": self.exercise_id, "weight_lbs": 100, "reps": 5},
                    ],
                },
            )

        dashboard = self.client.get("/api/dashboard").json()
        exercise_prs = [
            pr for pr in dashboard["prs"]
            if pr["exercise_id"] == self.exercise_id and pr["estimated_1rm"] == self.main.estimate_1rm(100, 5)
        ]
        self.assertEqual(len(exercise_prs), 1)
        self.assertEqual(exercise_prs[0]["workout_date"], "2026-05-15")

    def test_dashboard_uses_recent_exercises_key_for_last_trained_order(self):
        exercises = self.client.get("/api/exercises").json()
        older_exercise_id = exercises[0]["id"]
        recent_exercise_id = exercises[1]["id"]
        self.client.post(
            "/api/workouts",
            json={
                "workout_date": "2026-05-14",
                "title": "Older",
                "sets": [{"exercise_id": older_exercise_id, "weight_lbs": 100, "reps": 5}],
            },
        )
        self.client.post(
            "/api/workouts",
            json={
                "workout_date": "2026-05-16",
                "title": "Recent",
                "sets": [{"exercise_id": recent_exercise_id, "weight_lbs": 100, "reps": 5}],
            },
        )

        dashboard = self.client.get("/api/dashboard").json()

        self.assertNotIn("top_exercises", dashboard)
        self.assertEqual(dashboard["recent_exercises"][0]["id"], recent_exercise_id)
        self.assertEqual(dashboard["recent_exercises"][0]["last_trained"], "2026-05-16")

    def test_dashboard_cache_reuses_reads_until_workout_write(self):
        exercises = self.client.get("/api/exercises").json()
        older_exercise_id = exercises[0]["id"]
        recent_exercise_id = exercises[1]["id"]
        self.client.post(
            "/api/workouts",
            json={
                "workout_date": "2026-05-14",
                "title": "Older",
                "sets": [{"exercise_id": older_exercise_id, "weight_lbs": 100, "reps": 5}],
            },
        )
        first = self.client.get("/api/dashboard").json()
        self.assertEqual(first["recent_exercises"][0]["id"], older_exercise_id)

        with self.main.db() as conn:
            cur = conn.execute(
                "INSERT INTO workouts (user_id, workout_date, title) VALUES (?, ?, ?)",
                (1, "2026-05-16", "Direct"),
            )
            conn.execute(
                """
                INSERT INTO workout_sets (workout_id, exercise_id, set_number, weight_lbs, reps)
                VALUES (?, ?, ?, ?, ?)
                """,
                (cur.lastrowid, recent_exercise_id, 1, 100, 5),
            )

        cached = self.client.get("/api/dashboard").json()
        self.assertEqual(cached["recent_exercises"][0]["id"], older_exercise_id)

        self.client.post(
            "/api/workouts",
            json={
                "workout_date": "2026-05-16",
                "title": "Invalidate",
                "sets": [{"exercise_id": recent_exercise_id, "weight_lbs": 100, "reps": 5}],
            },
        )
        refreshed = self.client.get("/api/dashboard").json()
        self.assertEqual(refreshed["recent_exercises"][0]["id"], recent_exercise_id)

    def test_dashboard_prs_are_limited_to_rendered_count(self):
        exercises = self.client.get("/api/exercises").json()[: self.main.DASHBOARD_PR_LIMIT + 3]
        for idx, exercise in enumerate(exercises):
            self.client.post(
                "/api/workouts",
                json={
                    "workout_date": f"2026-05-{idx + 1:02d}",
                    "title": f"PR {idx}",
                    "sets": [{"exercise_id": exercise["id"], "weight_lbs": 100 + idx, "reps": 5}],
                },
            )

        dashboard = self.client.get("/api/dashboard").json()

        self.assertEqual(len(dashboard["prs"]), self.main.DASHBOARD_PR_LIMIT)

    def test_last_performed_returns_latest_workout_sets(self):
        self.client.post(
            "/api/workouts",
            json={
                "workout_date": "2026-05-14",
                "title": "Old",
                "sets": [{"exercise_id": self.exercise_id, "weight_lbs": 95, "reps": 8}],
            },
        )
        self.client.post(
            "/api/workouts",
            json={
                "workout_date": "2026-05-16",
                "title": "Latest",
                "sets": [
                    {"exercise_id": self.exercise_id, "weight_lbs": 105, "reps": 5},
                    {"exercise_id": self.exercise_id, "weight_lbs": 110, "reps": 3},
                ],
            },
        )

        rows = self.client.get("/api/exercises/last-performed").json()
        row = next(item for item in rows if item["exercise_id"] == self.exercise_id)
        self.assertEqual(row["workout_date"], "2026-05-16")
        self.assertEqual(len(row["sets"]), 2)
        self.assertEqual(row["sets"][0]["weight_lbs"], 105)


if __name__ == "__main__":
    unittest.main()
