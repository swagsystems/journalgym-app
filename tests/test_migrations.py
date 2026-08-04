import importlib
import os
import sqlite3
import tempfile
import unittest


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "fitness.db")
        os.environ["FITNESS_DB_PATH"] = self.db_path
        os.environ["FITNESS_COOKIE_SECURE"] = "false"

    def tearDown(self):
        self.tmp.cleanup()

    def test_orphaned_workouts_backfill_to_first_admin(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                pin_salt TEXT NOT NULL,
                pin_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE workouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workout_date DATE NOT NULL,
                title TEXT,
                bodyweight_lbs REAL,
                notes TEXT,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO users (username, display_name, pin_salt, pin_hash, role)
            VALUES ('admin', 'Admin', 'salt', 'hash', 'admin');
            INSERT INTO workouts (workout_date, title) VALUES ('2026-05-15', 'Legacy');
            """
        )
        conn.commit()
        conn.close()

        import api.main

        main = importlib.reload(api.main)
        main.init_db()

        conn = sqlite3.connect(self.db_path)
        row = conn.execute("SELECT user_id FROM workouts WHERE title = 'Legacy'").fetchone()
        conn.close()
        self.assertEqual(row[0], 1)

    def test_schema_migrations_are_recorded_once(self):
        import api.main

        main = importlib.reload(api.main)
        main.init_db()
        main.init_db()

        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version"
        ).fetchall()
        conn.close()

        self.assertEqual(
            rows,
            [(version, name) for version, name, _ in main.MIGRATIONS],
        )

    def test_audit_timestamp_columns_are_added(self):
        import api.main

        main = importlib.reload(api.main)
        main.init_db()

        conn = sqlite3.connect(self.db_path)
        user_columns = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        exercise_columns = {row[1] for row in conn.execute("PRAGMA table_info(exercises)").fetchall()}
        set_columns = {row[1] for row in conn.execute("PRAGMA table_info(workout_sets)").fetchall()}
        conn.close()

        self.assertIn("updated_at", user_columns)
        self.assertIn("last_login_at", user_columns)
        self.assertIn("updated_at", exercise_columns)
        self.assertIn("updated_at", set_columns)

    def test_null_audit_timestamps_are_backfilled_for_existing_columns(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                pin_salt TEXT NOT NULL,
                pin_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                is_active INTEGER NOT NULL DEFAULT 1,
                updated_at DATETIME,
                last_login_at DATETIME,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE exercises (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                primary_muscle TEXT NOT NULL,
                secondary_muscles TEXT NOT NULL DEFAULT '[]',
                aliases TEXT NOT NULL DEFAULT '[]',
                equipment TEXT NOT NULL,
                notes TEXT,
                is_archived INTEGER NOT NULL DEFAULT 0,
                updated_at DATETIME,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE workouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                workout_date DATE NOT NULL,
                title TEXT,
                bodyweight_lbs REAL,
                notes TEXT,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE workout_sets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workout_id INTEGER NOT NULL,
                exercise_id INTEGER NOT NULL,
                set_number INTEGER NOT NULL,
                weight_lbs REAL NOT NULL,
                weight_mode TEXT NOT NULL DEFAULT 'external',
                reps INTEGER NOT NULL,
                rpe REAL,
                duration_seconds INTEGER,
                set_type TEXT NOT NULL DEFAULT 'working',
                group_label TEXT,
                rest_seconds INTEGER,
                tempo TEXT,
                notes TEXT,
                updated_at DATETIME,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO users (username, display_name, pin_salt, pin_hash, role, updated_at)
            VALUES ('admin', 'Admin', 'salt', 'hash', 'admin', NULL);
            INSERT INTO exercises (name, primary_muscle, equipment, updated_at)
            VALUES ('Legacy Lift', 'Chest', 'Barbell', NULL);
            INSERT INTO workouts (id, workout_date, title) VALUES (1, '2026-05-17', 'Legacy');
            INSERT INTO workout_sets (workout_id, exercise_id, set_number, weight_lbs, reps, updated_at)
            VALUES (1, 1, 1, 100, 5, NULL);
            """
        )
        conn.commit()
        conn.close()

        import api.main

        main = importlib.reload(api.main)
        main.init_db()

        conn = sqlite3.connect(self.db_path)
        null_counts = [
            conn.execute(f"SELECT COUNT(*) FROM {table} WHERE updated_at IS NULL").fetchone()[0]
            for table in ("users", "exercises", "workout_sets")
        ]
        migration = conn.execute(
            "SELECT 1 FROM schema_migrations WHERE name = 'backfill_null_audit_timestamps'"
        ).fetchone()
        conn.close()

        self.assertEqual(null_counts, [0, 0, 0])
        self.assertIsNotNone(migration)

    def test_redundant_workout_date_index_is_removed(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            """
            CREATE TABLE workouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                workout_date DATE NOT NULL,
                title TEXT,
                bodyweight_lbs REAL,
                notes TEXT,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX idx_workouts_date ON workouts(workout_date DESC, id DESC);
            """
        )
        conn.commit()
        conn.close()

        import api.main

        main = importlib.reload(api.main)
        main.init_db()

        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name = 'idx_workouts_date'"
        ).fetchone()
        conn.close()

        self.assertIsNone(row)

    def test_workout_sets_exercise_fk_is_explicit_restrict_and_preserves_rows(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(
            """
            CREATE TABLE exercises (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                primary_muscle TEXT NOT NULL,
                secondary_muscles TEXT NOT NULL DEFAULT '[]',
                equipment TEXT NOT NULL,
                notes TEXT,
                is_archived INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE workouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                workout_date DATE NOT NULL,
                title TEXT,
                bodyweight_lbs REAL,
                notes TEXT,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE workout_sets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workout_id INTEGER NOT NULL,
                exercise_id INTEGER NOT NULL,
                set_number INTEGER NOT NULL,
                weight_lbs REAL NOT NULL,
                reps INTEGER NOT NULL,
                rpe REAL,
                set_type TEXT NOT NULL DEFAULT 'working',
                group_label TEXT,
                rest_seconds INTEGER,
                tempo TEXT,
                notes TEXT,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (workout_id) REFERENCES workouts(id) ON DELETE CASCADE,
                FOREIGN KEY (exercise_id) REFERENCES exercises(id)
            );
            INSERT INTO exercises (name, primary_muscle, equipment) VALUES ('Legacy Lift', 'Chest', 'Barbell');
            INSERT INTO workouts (workout_date, title) VALUES ('2026-05-15', 'Legacy');
            INSERT INTO workout_sets (workout_id, exercise_id, set_number, weight_lbs, reps)
            VALUES (1, 1, 1, 100, 5);
            """
        )
        conn.commit()
        conn.close()

        import api.main

        main = importlib.reload(api.main)
        main.init_db()

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        delete_rule = main.workout_sets_exercise_fk_delete_rule(conn)
        set_count = conn.execute("SELECT COUNT(*) FROM workout_sets WHERE exercise_id = 1").fetchone()[0]
        conn.close()

        self.assertEqual(delete_rule, "RESTRICT")
        self.assertEqual(set_count, 1)

    def test_cable_crunch_reclassification_runs_as_recorded_migration(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            """
            CREATE TABLE exercises (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                primary_muscle TEXT NOT NULL,
                secondary_muscles TEXT NOT NULL DEFAULT '[]',
                equipment TEXT NOT NULL,
                notes TEXT,
                is_archived INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO exercises (name, primary_muscle, equipment, secondary_muscles)
            VALUES ('Cable Crunch', 'Core', 'Cables', '[]');
            """
        )
        conn.commit()
        conn.close()

        import api.main

        main = importlib.reload(api.main)
        main.init_db()

        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT primary_muscle, secondary_muscles FROM exercises WHERE name = 'Cable Crunch'"
        ).fetchone()
        migration = conn.execute(
            "SELECT 1 FROM schema_migrations WHERE name = 'reclassify_cable_crunch_abs'"
        ).fetchone()
        conn.close()

        self.assertEqual(row[0], "Abs")
        self.assertEqual(row[1], '["Core"]')
        self.assertIsNotNone(migration)


if __name__ == "__main__":
    unittest.main()
