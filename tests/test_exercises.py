import importlib
import os
import tempfile
import unittest

from fastapi.testclient import TestClient


class ExerciseApiTests(unittest.TestCase):
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

    def tearDown(self):
        self.tmp.cleanup()

    def test_update_and_archive_exercise(self):
        exercise = self.client.get("/api/exercises").json()[0]

        updated = self.client.put(
            f"/api/exercises/{exercise['id']}",
            json={
                "name": f"{exercise['name']} Updated",
                "primary_muscle": "Chest",
                "equipment": "Machine",
                "secondary_muscles": ["Triceps"],
                "aliases": ["test press", "TP"],
                "notes": "edited",
                "is_archived": False,
            },
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["equipment"], "Machine")
        self.assertEqual(updated.json()["aliases"], ["test press", "TP"])
        self.assertIsNotNone(updated.json()["updated_at"])

        archived = self.client.put(
            f"/api/exercises/{exercise['id']}",
            json={
                "name": updated.json()["name"],
                "primary_muscle": "Chest",
                "equipment": "Machine",
                "secondary_muscles": ["Triceps"],
                "aliases": updated.json()["aliases"],
                "notes": "edited",
                "is_archived": True,
            },
        )
        self.assertEqual(archived.status_code, 200)
        self.assertTrue(archived.json()["is_archived"])
        visible_ids = {row["id"] for row in self.client.get("/api/exercises").json()}
        self.assertNotIn(exercise["id"], visible_ids)

    def test_non_admin_cannot_mutate_shared_exercise_catalog(self):
        self.client.post(
            "/api/users",
            json={"username": "member", "display_name": "Member", "pin": "482751", "role": "user"},
        )
        self.client.post("/api/auth/logout")
        self.client.post("/api/auth/login", json={"username": "member", "pin": "482751"})
        exercise = self.client.get("/api/exercises").json()[0]

        created = self.client.post(
            "/api/exercises",
            json={
                "name": "Member Only Lift",
                "primary_muscle": "Chest",
                "equipment": "Machine",
                "secondary_muscles": [],
                "notes": "",
            },
        )
        updated = self.client.put(
            f"/api/exercises/{exercise['id']}",
            json={
                "name": exercise["name"],
                "primary_muscle": exercise["primary_muscle"],
                "equipment": exercise["equipment"],
                "secondary_muscles": exercise["secondary_muscles"],
                "notes": exercise["notes"],
                "is_archived": False,
            },
        )

        self.assertEqual(created.status_code, 403)
        self.assertEqual(updated.status_code, 403)

    def test_exercise_names_are_case_insensitive_unique(self):
        exercise = next(row for row in self.client.get("/api/exercises").json() if row["name"] == "Cable Crunch")

        created = self.client.post(
            "/api/exercises",
            json={
                "name": "cable crunch",
                "primary_muscle": "Abs",
                "equipment": "Cables",
                "secondary_muscles": [],
                "notes": "",
            },
        )
        other = next(row for row in self.client.get("/api/exercises").json() if row["id"] != exercise["id"])
        updated = self.client.put(
            f"/api/exercises/{other['id']}",
            json={
                "name": "CABLE CRUNCH",
                "primary_muscle": other["primary_muscle"],
                "equipment": other["equipment"],
                "secondary_muscles": other["secondary_muscles"],
                "notes": other["notes"],
                "is_archived": False,
            },
        )

        self.assertEqual(created.status_code, 409)
        self.assertEqual(updated.status_code, 409)
        self.assertEqual(exercise["name"], "Cable Crunch")

    def test_exercise_muscle_and_equipment_are_server_validated(self):
        bad_muscle = self.client.post(
            "/api/exercises",
            json={
                "name": "Banana Press",
                "primary_muscle": "Banana",
                "equipment": "Machine",
                "secondary_muscles": [],
                "notes": "",
            },
        )
        bad_equipment = self.client.post(
            "/api/exercises",
            json={
                "name": "Chair Press",
                "primary_muscle": "Chest",
                "equipment": "Chair",
                "secondary_muscles": [],
                "notes": "",
            },
        )

        self.assertEqual(bad_muscle.status_code, 422)
        self.assertEqual(bad_equipment.status_code, 422)

    def test_secondary_muscles_are_server_validated(self):
        bad_secondary = self.client.post(
            "/api/exercises",
            json={
                "name": "Mystery Pull",
                "primary_muscle": "Back",
                "equipment": "Cables",
                "secondary_muscles": ["Banana"],
                "notes": "",
            },
        )
        too_many = self.client.post(
            "/api/exercises",
            json={
                "name": "Everything Pull",
                "primary_muscle": "Back",
                "equipment": "Cables",
                "secondary_muscles": ["Chest", "Shoulders", "Biceps", "Triceps", "Core", "Abs", "Traps"],
                "notes": "",
            },
        )

        self.assertEqual(bad_secondary.status_code, 422)
        self.assertEqual(too_many.status_code, 422)

    def test_exercise_notes_have_max_length(self):
        response = self.client.post(
            "/api/exercises",
            json={
                "name": "Verbose Press",
                "primary_muscle": "Chest",
                "equipment": "Machine",
                "secondary_muscles": [],
                "notes": "x" * (self.main.NOTE_MAX_LENGTH + 1),
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_seeded_missing_staples_exist(self):
        names = {row["name"] for row in self.client.get("/api/exercises").json()}
        for expected in [
            "Deadlift",
            "Sumo Deadlift",
            "Trap-Bar Deadlift",
            "Chin-Up",
            "Goblet Squat",
            "Good Morning",
            "Hip Abduction Machine",
            "Wrist Curl",
            "Assisted Pull-Up Machine",
        ]:
            self.assertIn(expected, names)

    def test_seeded_exercise_cues_are_exposed(self):
        exercises = {row["name"]: row for row in self.client.get("/api/exercises").json()}

        self.assertIn("Pallof Press", exercises)
        self.assertIn("torso rotate", exercises["Pallof Press"]["notes"])
        self.assertIn("hamstrings", exercises["Romanian Deadlift"]["notes"])

    def test_seeded_exercise_aliases_are_exposed(self):
        exercises = {row["name"]: row for row in self.client.get("/api/exercises").json()}

        self.assertIn("Dead Lift", exercises["Deadlift"]["aliases"])
        self.assertIn("OHP", exercises["Overhead Press"]["aliases"])
        self.assertIn("RDL", exercises["Romanian Deadlift"]["aliases"])
        self.assertIn("Pec Deck", exercises["Pec Fly Machine"]["aliases"])

    def test_dead_lift_typo_exercise_is_merged_into_deadlift(self):
        deadlift = next(row for row in self.client.get("/api/exercises").json() if row["name"] == "Deadlift")
        typo = self.client.post(
            "/api/exercises",
            json={
                "name": "Dead Lift",
                "primary_muscle": "Hamstrings",
                "equipment": "Barbell",
                "secondary_muscles": ["Glutes"],
                "aliases": ["DL typo"],
                "notes": "",
            },
        ).json()
        created = self.client.post(
            "/api/workouts",
            json={
                "workout_date": "2026-05-17",
                "title": "Pull",
                "sets": [{"exercise_id": typo["id"], "weight_lbs": 315, "reps": 3}],
            },
        ).json()

        with self.main.db() as conn:
            self.main.migration_merge_dead_lift_into_deadlift(conn)

        detail = self.client.get(f"/api/workouts/{created['id']}").json()
        exercises = {row["name"]: row for row in self.client.get("/api/exercises?include_archived=true").json()}
        self.assertEqual(detail["sets"][0]["exercise_id"], deadlift["id"])
        self.assertEqual(detail["sets"][0]["exercise_name"], "Deadlift")
        self.assertNotIn("Dead Lift", exercises)
        self.assertIn("Dead Lift", exercises["Deadlift"]["aliases"])
        self.assertIn("DL typo", exercises["Deadlift"]["aliases"])

    def test_abs_and_core_seed_taxonomy_is_distinct(self):
        exercises = {row["name"]: row for row in self.client.get("/api/exercises").json()}

        self.assertEqual(exercises["Cable Crunch"]["primary_muscle"], "Abs")
        self.assertIn("Core", exercises["Cable Crunch"]["secondary_muscles"])
        self.assertEqual(exercises["Pallof Press"]["primary_muscle"], "Core")
        self.assertIn("Abs", exercises["Pallof Press"]["secondary_muscles"])


if __name__ == "__main__":
    unittest.main()
