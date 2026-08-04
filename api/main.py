import base64
import binascii
import copy
import csv
import hashlib
import hmac
import io
import ipaddress
import json
import os
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager, contextmanager
from datetime import date, timedelta
from pathlib import Path

from fastapi import Cookie, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, model_validator


DB_PATH = Path(os.environ.get("FITNESS_DB_PATH", "/data/fitness/fitness.db"))
FRONTEND_DIST = Path(os.environ.get("FRONTEND_DIST", "/app/frontend/dist"))
SESSION_COOKIE = "fitness_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30
SESSION_MAX_PER_USER = max(1, int(os.environ.get("FITNESS_SESSION_MAX_PER_USER", "10")))
LOGIN_WINDOW_SECONDS = 600
LOGIN_IP_FAILURE_LIMIT = 8
LOGIN_USERNAME_DELAY_THRESHOLD = 8
LOGIN_ATTEMPT_RETENTION_SECONDS = max(LOGIN_WINDOW_SECONDS, int(os.environ.get("FITNESS_LOGIN_ATTEMPT_RETENTION_SECONDS", str(60 * 60 * 24 * 7))))
PIN_ITERATIONS = 260_000
PIN_PATTERN = r"^[0-9]{6,12}$"
NOTE_MAX_LENGTH = 1000
WORKOUT_SET_MAX_COUNT = 200
SET_WEIGHT_MAX_LBS = 2000
DASHBOARD_CACHE_SECONDS = max(0, int(os.environ.get("FITNESS_DASHBOARD_CACHE_SECONDS", "30")))
DASHBOARD_PR_LIMIT = 12
RECENT_EXERCISE_LIMIT = 12
WEEKLY_MUSCLE_TARGET_SETS = max(1, int(os.environ.get("FITNESS_WEEKLY_MUSCLE_TARGET_SETS", "10")))
DEFAULT_REST_SECONDS = 120
DEFAULT_REPS = 8
SQLITE_TIMEOUT_SECONDS = 30
GOALS_NO_TARGET_DATE_SORT = "9999-12-31"
REQUEST_BODY_MAX_BYTES = max(0, int(os.environ.get("FITNESS_REQUEST_BODY_MAX_BYTES", str(1024 * 1024))))
MUSCLE_OPTION_ORDER = [
    "Chest",
    "Back",
    "Shoulders",
    "Quads",
    "Hamstrings",
    "Glutes",
    "Calves",
    "Biceps",
    "Triceps",
    "Abs",
    "Core",
    "Adductors",
    "Abductors",
    "Forearms",
    "Lower Back",
    "Traps",
    "Obliques",
]
MUSCLE_OPTIONS = set(MUSCLE_OPTION_ORDER)
STABILIZER_MUSCLE_OPTIONS = {"Abs", "Core", "Lower Back", "Obliques", "Traps", "Forearms"}
MUSCLE_VOLUME_ROLE_ORDER = {"primary": 0, "secondary": 1, "stabilizer": 2}
EQUIPMENT_OPTIONS = {
    "Barbell",
    "Dumbbells",
    "Cables",
    "Machine",
    "Bodyweight",
    "Kettlebell",
    "Bands",
    "EZ Bar",
    "Trap Bar",
    "Smith Machine",
}
COMMON_PINS = {
    "000000",
    "111111",
    "112233",
    "121212",
    "123123",
    "123456",
    "1234567",
    "12345678",
    "123456789",
    "222222",
    "333333",
    "444444",
    "555555",
    "654321",
    "666666",
    "777777",
    "888888",
    "987654",
    "999999",
}
E1RM_REP_DIVISOR = 30.0
COOKIE_SECURE = os.environ.get("FITNESS_COOKIE_SECURE", "false").lower() not in {"0", "false", "no"}
ENABLE_API_DOCS = os.environ.get("FITNESS_ENABLE_API_DOCS", "false").lower() in {"1", "true", "yes"}
TRUSTED_PROXY_CONFIG = os.environ.get("FITNESS_TRUSTED_PROXIES", "")
PIN_PEPPER_ENV = os.environ.get("FITNESS_PIN_PEPPER", "")
PIN_PEPPER_FILE = Path(os.environ.get("FITNESS_PIN_PEPPER_FILE", str(DB_PATH.with_name(f"{DB_PATH.name}.pepper"))))
PIN_PEPPER_CACHE: bytes | None = None
DASHBOARD_CACHE: dict[tuple[int, int], tuple[float, dict]] = {}
APP_STARTED_AT = int(time.time())
ALLOWED_TABLES = {"schema_migrations", "users", "sessions", "login_attempts", "exercises", "workouts", "workout_sets", "body_measurements", "goals", "user_settings"}
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}
STRENGTH_STANDARD_RATIOS = {
    "Barbell Bench Press": [(1.0, "bodyweight bench"), (1.25, "strong bench"), (1.5, "advanced bench"), (2.0, "elite bench")],
    "Incline Barbell Press": [(0.75, "bodyweight-relative press"), (1.0, "strong press"), (1.25, "advanced press"), (1.5, "elite press")],
    "Overhead Press": [(0.5, "bodyweight-relative press"), (0.75, "strong press"), (1.0, "advanced press"), (1.25, "elite press")],
    "Back Squat": [(1.0, "bodyweight squat"), (1.5, "strong squat"), (2.0, "advanced squat"), (2.5, "elite squat")],
    "Front Squat": [(0.8, "bodyweight-relative squat"), (1.25, "strong squat"), (1.75, "advanced squat"), (2.25, "elite squat")],
    "Deadlift": [(1.25, "bodyweight-plus deadlift"), (1.75, "strong deadlift"), (2.25, "advanced deadlift"), (3.0, "elite deadlift")],
    "Sumo Deadlift": [(1.25, "bodyweight-plus deadlift"), (1.75, "strong deadlift"), (2.25, "advanced deadlift"), (3.0, "elite deadlift")],
    "Trap-Bar Deadlift": [(1.25, "bodyweight-plus deadlift"), (1.75, "strong deadlift"), (2.25, "advanced deadlift"), (3.0, "elite deadlift")],
}


def is_sequential_pin(pin: str) -> bool:
    if len(pin) < 3:
        return False
    deltas = {int(pin[idx + 1]) - int(pin[idx]) for idx in range(len(pin) - 1)}
    return deltas in ({1}, {-1})


def validate_strong_pin(pin: str) -> str:
    if pin in COMMON_PINS or len(set(pin)) == 1 or is_sequential_pin(pin):
        raise ValueError("PIN must not be common, repeated, or sequential")
    return pin


class StrongPinMixin(BaseModel):
    @field_validator("pin", check_fields=False)
    @classmethod
    def pin_must_be_strong(cls, pin: str) -> str:
        return validate_strong_pin(pin)


class ExerciseIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    primary_muscle: str = Field(min_length=1, max_length=60)
    equipment: str = Field(min_length=1, max_length=80)
    secondary_muscles: list[str] = Field(default_factory=list, max_length=6)
    aliases: list[str] = Field(default_factory=list, max_length=12)
    notes: str | None = Field(default=None, max_length=NOTE_MAX_LENGTH)

    @field_validator("primary_muscle")
    @classmethod
    def primary_muscle_must_be_known(cls, value: str) -> str:
        if value not in MUSCLE_OPTIONS:
            raise ValueError("primary_muscle must be a supported muscle group")
        return value

    @field_validator("equipment")
    @classmethod
    def equipment_must_be_known(cls, value: str) -> str:
        if value not in EQUIPMENT_OPTIONS:
            raise ValueError("equipment must be a supported equipment type")
        return value

    @field_validator("secondary_muscles")
    @classmethod
    def secondary_muscles_must_be_known(cls, values: list[str]) -> list[str]:
        unknown = [value for value in values if value not in MUSCLE_OPTIONS]
        if unknown:
            raise ValueError(f"secondary_muscles contains unsupported muscle groups: {unknown}")
        return values

    @field_validator("aliases")
    @classmethod
    def aliases_must_be_short(cls, values: list[str]) -> list[str]:
        aliases = []
        for value in values:
            alias = value.strip()
            if not alias:
                continue
            if len(alias) > 80:
                raise ValueError("aliases must be 80 characters or fewer")
            if alias.lower() not in {item.lower() for item in aliases}:
                aliases.append(alias)
        return aliases


class ExerciseUpdateIn(ExerciseIn):
    is_archived: bool = False


class SetIn(BaseModel):
    exercise_id: int
    weight_lbs: float = Field(ge=0, le=SET_WEIGHT_MAX_LBS)
    reps: int = Field(ge=1, le=200)
    rpe: float | None = Field(default=None, ge=1, le=10)
    weight_mode: str = Field(default="external", pattern=r"^(external|bodyweight|added|assisted)$")
    duration_seconds: int | None = Field(default=None, ge=0, le=86400)
    set_type: str = Field(default="working", pattern=r"^(working|warmup|drop|failure|amrap)$")
    group_label: str | None = Field(default=None, max_length=40)
    rest_seconds: int | None = Field(default=None, ge=0, le=3600)
    tempo: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=NOTE_MAX_LENGTH)


class WorkoutIn(BaseModel):
    workout_date: date
    title: str | None = Field(default=None, max_length=140)
    bodyweight_lbs: float | None = Field(default=None, ge=30, le=1000)
    notes: str | None = Field(default=None, max_length=NOTE_MAX_LENGTH)
    sets: list[SetIn] = Field(min_length=1, max_length=WORKOUT_SET_MAX_COUNT)

    @field_validator("workout_date")
    @classmethod
    def workout_date_must_not_be_future(cls, value: date) -> date:
        if value > date.today():
            raise ValueError("workout_date cannot be in the future")
        if value < date.today() - timedelta(days=3650):
            raise ValueError("workout_date is too far in the past")
        return value


class MeasurementIn(BaseModel):
    measured_date: date
    bodyweight_lbs: float | None = Field(default=None, ge=30, le=1000)
    waist_in: float | None = Field(default=None, ge=0, le=200)
    chest_in: float | None = Field(default=None, ge=0, le=200)
    hip_in: float | None = Field(default=None, ge=0, le=200)
    arm_in: float | None = Field(default=None, ge=0, le=100)
    thigh_in: float | None = Field(default=None, ge=0, le=100)
    photo_url: str | None = Field(default=None, max_length=500)
    notes: str | None = None


class GoalIn(BaseModel):
    kind: str = Field(pattern=r"^(one_rep_max|bodyweight)$")
    exercise_id: int | None = None
    target_value_lbs: float = Field(gt=0, le=SET_WEIGHT_MAX_LBS)
    target_date: date | None = None
    notes: str | None = Field(default=None, max_length=NOTE_MAX_LENGTH)

    @model_validator(mode="after")
    def exercise_required_for_strength_goal(self):
        if self.kind == "one_rep_max" and not self.exercise_id:
            raise ValueError("exercise_id is required for one_rep_max goals")
        if self.kind == "bodyweight":
            self.exercise_id = None
            if self.target_value_lbs > 1000:
                raise ValueError("bodyweight goal must be 1000 lb or less")
        return self


class SettingsIn(BaseModel):
    unit: str = Field(default="lb", pattern=r"^(lb|kg)$")
    default_rest_seconds: int = Field(default=DEFAULT_REST_SECONDS, ge=0, le=3600)
    default_reps: int = Field(default=DEFAULT_REPS, ge=1, le=200)
    theme: str = Field(default="system", pattern=r"^(system|dark|light)$")
    reminder_enabled: bool = False
    reminder_hour: int = Field(default=18, ge=0, le=23)


class AuthSetupIn(StrongPinMixin):
    username: str = Field(min_length=2, max_length=40, pattern=r"^[a-zA-Z0-9_.-]+$")
    display_name: str | None = Field(default=None, max_length=80)
    pin: str = Field(pattern=PIN_PATTERN)


class LoginIn(BaseModel):
    username: str = Field(min_length=2, max_length=40, pattern=r"^[a-zA-Z0-9_.-]+$")
    pin: str = Field(pattern=PIN_PATTERN)


class UserCreateIn(StrongPinMixin):
    username: str = Field(min_length=2, max_length=40, pattern=r"^[a-zA-Z0-9_.-]+$")
    display_name: str | None = Field(default=None, max_length=80)
    pin: str = Field(pattern=PIN_PATTERN)
    role: str = Field(default="user", pattern=r"^(admin|user)$")


class UserUpdateIn(BaseModel):
    username: str = Field(min_length=2, max_length=40, pattern=r"^[a-zA-Z0-9_.-]+$")
    display_name: str | None = Field(default=None, max_length=80)
    role: str = Field(pattern=r"^(admin|user)$")
    is_active: bool = True


class PinResetIn(StrongPinMixin):
    pin: str = Field(pattern=PIN_PATTERN)


class PinChangeIn(BaseModel):
    current_pin: str = Field(pattern=PIN_PATTERN)
    new_pin: str = Field(pattern=PIN_PATTERN)

    @field_validator("new_pin")
    @classmethod
    def new_pin_must_be_strong(cls, pin: str) -> str:
        return validate_strong_pin(pin)

    @model_validator(mode="after")
    def new_pin_must_differ(self):
        if self.current_pin == self.new_pin:
            raise ValueError("new PIN must differ from current PIN")
        return self


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str
    role: str
    is_active: bool
    created_at: str
    updated_at: str
    last_login_at: str | None = None


class ExerciseOut(BaseModel):
    id: int
    name: str
    primary_muscle: str
    equipment: str
    secondary_muscles: list[str]
    aliases: list[str]
    notes: str | None = None
    is_archived: bool = False
    updated_at: str


class WorkoutSetOut(BaseModel):
    id: int
    exercise_id: int
    exercise_name: str
    primary_muscle: str
    equipment: str
    set_number: int
    weight_lbs: float
    weight_mode: str = "external"
    effective_weight_lbs: float
    reps: int
    rpe: float | None = None
    duration_seconds: int | None = None
    set_type: str = "working"
    group_label: str | None = None
    rest_seconds: int | None = None
    tempo: str | None = None
    notes: str | None = None
    updated_at: str
    volume_lbs: float
    estimated_1rm: float


class WorkoutOut(BaseModel):
    id: int
    workout_date: str
    title: str | None = None
    bodyweight_lbs: float | None = None
    notes: str | None = None
    set_count: int
    volume_lbs: float
    sets: list[WorkoutSetOut] = []


class MeasurementOut(BaseModel):
    id: int
    measured_date: str
    bodyweight_lbs: float | None = None
    waist_in: float | None = None
    chest_in: float | None = None
    hip_in: float | None = None
    arm_in: float | None = None
    thigh_in: float | None = None
    photo_url: str | None = None
    notes: str | None = None
    created_at: str


class GoalOut(BaseModel):
    id: int
    kind: str
    exercise_id: int | None = None
    exercise_name: str | None = None
    target_value_lbs: float
    target_date: str | None = None
    notes: str | None = None
    created_at: str
    updated_at: str


class SettingsOut(SettingsIn):
    updated_at: str


def row_to_dict(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in row.keys()}


def invalidate_dashboard_cache(user_id: int | None = None):
    if user_id is None:
        DASHBOARD_CACHE.clear()
        return
    for key in [key for key in DASHBOARD_CACHE if key[0] == user_id]:
        DASHBOARD_CACHE.pop(key, None)


def cached_dashboard(user_id: int, days: int) -> dict | None:
    if DASHBOARD_CACHE_SECONDS <= 0:
        return None
    cached = DASHBOARD_CACHE.get((user_id, days))
    if not cached:
        return None
    expires_at, payload = cached
    if expires_at <= time.monotonic():
        DASHBOARD_CACHE.pop((user_id, days), None)
        return None
    return copy.deepcopy(payload)


def store_dashboard_cache(user_id: int, days: int, payload: dict) -> dict:
    if DASHBOARD_CACHE_SECONDS > 0:
        DASHBOARD_CACHE[(user_id, days)] = (time.monotonic() + DASHBOARD_CACHE_SECONDS, copy.deepcopy(payload))
    return payload


def estimate_1rm(weight_lbs: float, reps: int) -> float:
    if reps <= 1:
        return round(weight_lbs, 1)
    return round(weight_lbs * (1 + reps / E1RM_REP_DIVISOR), 1)


def estimated_1rm_sql(weight_expr: str, reps_expr: str) -> str:
    return f"CASE WHEN {reps_expr} <= 1 THEN {weight_expr} ELSE {weight_expr} * (1 + {reps_expr} / {E1RM_REP_DIVISOR}) END"


def volume(weight_lbs: float, reps: int) -> float:
    return round(weight_lbs * reps, 1)


def effective_weight(weight_lbs: float, weight_mode: str = "external", bodyweight_lbs: float | None = None) -> float:
    bodyweight = bodyweight_lbs or 0
    if weight_mode == "bodyweight":
        return round(bodyweight, 1)
    if weight_mode == "added":
        return round(bodyweight + weight_lbs, 1)
    if weight_mode == "assisted":
        return round(max(bodyweight - weight_lbs, 0), 1)
    return round(weight_lbs, 1)


def effective_weight_sql(weight_expr: str = "ws.weight_lbs", mode_expr: str = "ws.weight_mode", bodyweight_expr: str = "w.bodyweight_lbs") -> str:
    bodyweight = f"COALESCE({bodyweight_expr}, 0)"
    return (
        "CASE "
        f"WHEN COALESCE({mode_expr}, 'external') = 'bodyweight' THEN {bodyweight} "
        f"WHEN COALESCE({mode_expr}, 'external') = 'added' THEN {bodyweight} + {weight_expr} "
        f"WHEN COALESCE({mode_expr}, 'external') = 'assisted' THEN MAX({bodyweight} - {weight_expr}, 0) "
        f"ELSE {weight_expr} END"
    )


def strength_standard_label(exercise_name: str, ratio: float | None) -> str | None:
    if ratio is None:
        return None
    label = "below bodyweight"
    if ratio >= 1:
        label = "bodyweight+"
    for threshold, threshold_label in STRENGTH_STANDARD_RATIOS.get(exercise_name, []):
        if ratio >= threshold:
            label = threshold_label
    return label


def format_week_label(week_start: str) -> str:
    start = date.fromisoformat(week_start)
    end = start.fromordinal(start.toordinal() + 6)
    if start.month == end.month:
        return f"{start.strftime('%b')} {start.day}-{end.day}"
    return f"{start.strftime('%b')} {start.day}-{end.strftime('%b')} {end.day}"


def secondary_muscle_volume_role(muscle: str) -> str:
    return "stabilizer" if muscle in STABILIZER_MUSCLE_OPTIONS else "secondary"


def current_streak_days(training_days: set[str]) -> int:
    streak = 0
    cursor = date.today()
    while cursor.isoformat() in training_days:
        streak += 1
        cursor = cursor - timedelta(days=1)
    return streak


def weekly_muscle_targets(muscle_volume: list[dict]) -> list[dict]:
    current_week = (date.today() - timedelta(days=date.today().weekday())).isoformat()
    current_sets = {
        row["muscle"]: int(row.get("sets") or 0)
        for row in muscle_volume
        if row.get("week_start") == current_week
    }
    return [
        {
            "muscle": muscle,
            "sets": current_sets.get(muscle, 0),
            "target_sets": WEEKLY_MUSCLE_TARGET_SETS,
            "remaining_sets": max(WEEKLY_MUSCLE_TARGET_SETS - current_sets.get(muscle, 0), 0),
            "status": "met" if current_sets.get(muscle, 0) >= WEEKLY_MUSCLE_TARGET_SETS else "under",
        }
        for muscle in MUSCLE_OPTION_ORDER
    ]


def normalize_username(username: str) -> str:
    return username.strip().lower()


def parse_trusted_proxies(value: str):
    proxies = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            proxies.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            continue
    return proxies


TRUSTED_PROXIES = parse_trusted_proxies(TRUSTED_PROXY_CONFIG)


def is_trusted_proxy(host: str | None) -> bool:
    if not host:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(address in proxy for proxy in TRUSTED_PROXIES)


def encode_bytes(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def decode_bytes(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"))


def get_pin_pepper() -> bytes:
    global PIN_PEPPER_CACHE
    if PIN_PEPPER_ENV:
        return PIN_PEPPER_ENV.encode("utf-8")
    if PIN_PEPPER_CACHE is not None:
        return PIN_PEPPER_CACHE
    PIN_PEPPER_FILE.parent.mkdir(parents=True, exist_ok=True)
    if PIN_PEPPER_FILE.exists():
        secret = PIN_PEPPER_FILE.read_text(encoding="utf-8").strip()
    else:
        secret = secrets.token_urlsafe(48)
        PIN_PEPPER_FILE.write_text(f"{secret}\n", encoding="utf-8")
        PIN_PEPPER_FILE.chmod(0o600)
    if not secret:
        raise RuntimeError("PIN pepper is empty")
    PIN_PEPPER_CACHE = secret.encode("utf-8")
    return PIN_PEPPER_CACHE


def pin_hash_input(pin: str, peppered: bool = True) -> bytes:
    value = pin.encode("utf-8")
    if not peppered:
        return value
    return value + b"\0" + get_pin_pepper()


def hash_pin(pin: str, salt: bytes | None = None, peppered: bool = True) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin_hash_input(pin, peppered), salt, PIN_ITERATIONS)
    return encode_bytes(salt), encode_bytes(digest)


def verify_pin_status(pin: str, salt_b64: str, hash_b64: str) -> tuple[bool, bool]:
    try:
        salt = decode_bytes(salt_b64)
    except (binascii.Error, UnicodeEncodeError, ValueError):
        return False, False
    _, candidate = hash_pin(pin, salt)
    if hmac.compare_digest(candidate, hash_b64):
        return True, False
    _, legacy_candidate = hash_pin(pin, salt, peppered=False)
    if hmac.compare_digest(legacy_candidate, hash_b64):
        return True, True
    return False, False


def verify_pin(pin: str, salt_b64: str, hash_b64: str) -> bool:
    ok, _ = verify_pin_status(pin, salt_b64, hash_b64)
    return ok


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def prune_expired_sessions(conn: sqlite3.Connection, now: int | None = None):
    conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now or int(time.time()),))


def is_sqlite_busy_error(exc: sqlite3.OperationalError) -> bool:
    message = str(exc).lower()
    return "database is locked" in message or "database table is locked" in message or "database is busy" in message


@contextmanager
def db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=SQLITE_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        yield conn
        conn.commit()
    except HTTPException:
        conn.commit()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    pin_salt TEXT NOT NULL,
    pin_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    is_active INTEGER NOT NULL DEFAULT 1,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    ip TEXT NOT NULL,
    success INTEGER NOT NULL DEFAULT 0,
    attempted_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS exercises (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    primary_muscle TEXT NOT NULL,
    secondary_muscles TEXT NOT NULL DEFAULT '[]',
    aliases TEXT NOT NULL DEFAULT '[]',
    equipment TEXT NOT NULL,
    notes TEXT,
    is_archived INTEGER NOT NULL DEFAULT 0,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS workouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    workout_date DATE NOT NULL,
    title TEXT,
    bodyweight_lbs REAL,
    notes TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS workout_sets (
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
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (workout_id) REFERENCES workouts(id) ON DELETE CASCADE,
    FOREIGN KEY (exercise_id) REFERENCES exercises(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS body_measurements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    measured_date DATE NOT NULL,
    bodyweight_lbs REAL,
    waist_in REAL,
    chest_in REAL,
    hip_in REAL,
    arm_in REAL,
    thigh_in REAL,
    photo_url TEXT,
    notes TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    exercise_id INTEGER,
    target_value_lbs REAL NOT NULL,
    target_date DATE,
    notes TEXT,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (exercise_id) REFERENCES exercises(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS user_settings (
    user_id INTEGER PRIMARY KEY,
    unit TEXT NOT NULL DEFAULT 'lb',
    default_rest_seconds INTEGER NOT NULL DEFAULT 120,
    default_reps INTEGER NOT NULL DEFAULT 8,
    theme TEXT NOT NULL DEFAULT 'system',
    reminder_enabled INTEGER NOT NULL DEFAULT 0,
    reminder_hour INTEGER NOT NULL DEFAULT 18,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, expires_at);
CREATE INDEX IF NOT EXISTS idx_login_attempts_lookup ON login_attempts(username, ip, attempted_at);
CREATE INDEX IF NOT EXISTS idx_sets_workout ON workout_sets(workout_id, set_number);
CREATE INDEX IF NOT EXISTS idx_sets_exercise ON workout_sets(exercise_id, id);
CREATE INDEX IF NOT EXISTS idx_exercises_muscle ON exercises(primary_muscle, name);
CREATE INDEX IF NOT EXISTS idx_body_measurements_user_date ON body_measurements(user_id, measured_date DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_goals_user_kind ON goals(user_id, kind, target_date);
"""


SEEDED_EXERCISES = [
    ("Barbell Bench Press", "Chest", "Barbell", ["Triceps", "Shoulders"]),
    ("Dumbbell Bench Press", "Chest", "Dumbbells", ["Triceps", "Shoulders"]),
    ("Incline Dumbbell Press", "Chest", "Dumbbells", ["Shoulders", "Triceps"]),
    ("Supine Press Machine", "Chest", "Machine", ["Triceps", "Shoulders"]),
    ("Pec Fly Machine", "Chest", "Machine", ["Shoulders"]),
    ("Cable Fly", "Chest", "Cables", ["Shoulders"]),
    ("Push-Up", "Chest", "Bodyweight", ["Triceps", "Shoulders"]),
    ("Decline Bench Press", "Chest", "Barbell", ["Triceps", "Shoulders"]),
    ("Incline Barbell Press", "Chest", "Barbell", ["Shoulders", "Triceps"]),
    ("Machine Chest Press", "Chest", "Machine", ["Triceps", "Shoulders"]),
    ("Hammer Strength Chest Press", "Chest", "Machine", ["Triceps", "Shoulders"]),
    ("Chest Dip", "Chest", "Bodyweight", ["Triceps", "Shoulders"]),
    ("Weighted Dip", "Chest", "Bodyweight", ["Triceps", "Shoulders"]),
    ("Assisted Dip Machine", "Chest", "Machine", ["Triceps", "Shoulders"]),
    ("Cable Crossover", "Chest", "Cables", ["Shoulders"]),
    ("Dumbbell Pullover", "Chest", "Dumbbells", ["Back"]),
    ("Barbell Row", "Back", "Barbell", ["Biceps"]),
    ("Dumbbell Row", "Back", "Dumbbells", ["Biceps"]),
    ("Seated Cable Row", "Back", "Cables", ["Biceps"]),
    ("Lat Pulldown", "Back", "Cables", ["Biceps"]),
    ("Pull-Up", "Back", "Bodyweight", ["Biceps"]),
    ("Chin-Up", "Back", "Bodyweight", ["Biceps"]),
    ("Assisted Pull-Up Machine", "Back", "Machine", ["Biceps"]),
    ("Inverted Row", "Back", "Bodyweight", ["Biceps"]),
    ("Pendlay Row", "Back", "Barbell", ["Biceps"]),
    ("Machine Row", "Back", "Machine", ["Biceps"]),
    ("Seal Row", "Back", "Barbell", ["Biceps"]),
    ("Meadows Row", "Back", "Barbell", ["Biceps"]),
    ("Single-Arm Cable Row", "Back", "Cables", ["Biceps"]),
    ("T-Bar Row", "Back", "Machine", ["Biceps"]),
    ("Chest-Supported Row", "Back", "Machine", ["Biceps"]),
    ("Nautilus Pullover", "Back", "Machine", ["Chest"]),
    ("Straight-Arm Pulldown", "Back", "Cables", ["Chest"]),
    ("Close-Grip Underhand Pulldown", "Back", "Cables", ["Biceps"]),
    ("Overhead Press", "Shoulders", "Barbell", ["Triceps"]),
    ("Machine Shoulder Press", "Shoulders", "Machine", ["Triceps"]),
    ("Dumbbell Shoulder Press", "Shoulders", "Dumbbells", ["Triceps"]),
    ("Arnold Press", "Shoulders", "Dumbbells", ["Triceps"]),
    ("Landmine Press", "Shoulders", "Barbell", ["Chest", "Triceps"]),
    ("Lateral Raise", "Shoulders", "Dumbbells", []),
    ("Cable Lateral Raise", "Shoulders", "Cables", []),
    ("Machine Lateral Raise", "Shoulders", "Machine", []),
    ("Rear Delt Fly", "Shoulders", "Machine", ["Back"]),
    ("Reverse Pec Deck", "Shoulders", "Machine", ["Back"]),
    ("Face Pull", "Shoulders", "Cables", ["Back"]),
    ("Dumbbell Shrug", "Traps", "Dumbbells", ["Back"]),
    ("Barbell Shrug", "Traps", "Barbell", ["Back"]),
    ("Upright Row", "Shoulders", "Barbell", ["Back"]),
    ("Back Squat", "Quads", "Barbell", ["Glutes", "Hamstrings"]),
    ("Front Squat", "Quads", "Barbell", ["Glutes", "Core"]),
    ("Goblet Squat", "Quads", "Kettlebell", ["Glutes", "Core"]),
    ("Hack Squat", "Quads", "Machine", ["Glutes", "Hamstrings"]),
    ("Smith Machine Squat", "Quads", "Smith Machine", ["Glutes", "Hamstrings"]),
    ("Pendulum Squat", "Quads", "Machine", ["Glutes", "Hamstrings"]),
    ("Belt Squat", "Quads", "Machine", ["Glutes", "Hamstrings"]),
    ("Bulgarian Split Squat", "Quads", "Dumbbells", ["Glutes", "Hamstrings"]),
    ("Walking Lunge", "Quads", "Dumbbells", ["Glutes", "Hamstrings"]),
    ("Step-Up", "Quads", "Dumbbells", ["Glutes", "Hamstrings"]),
    ("Leg Press", "Quads", "Machine", ["Glutes", "Hamstrings"]),
    ("Leg Extension", "Quads", "Machine", []),
    ("Deadlift", "Hamstrings", "Barbell", ["Glutes", "Back", "Lower Back"]),
    ("Sumo Deadlift", "Hamstrings", "Barbell", ["Glutes", "Back", "Adductors"]),
    ("Trap-Bar Deadlift", "Hamstrings", "Trap Bar", ["Glutes", "Back", "Quads"]),
    ("Deficit Deadlift", "Hamstrings", "Barbell", ["Glutes", "Back", "Lower Back"]),
    ("Rack Pull", "Back", "Barbell", ["Hamstrings", "Glutes", "Lower Back"]),
    ("Romanian Deadlift", "Hamstrings", "Barbell", ["Glutes", "Back"]),
    ("Good Morning", "Lower Back", "Barbell", ["Hamstrings", "Glutes"]),
    ("Nordic Hamstring Curl", "Hamstrings", "Bodyweight", ["Glutes"]),
    ("Lying Leg Curl", "Hamstrings", "Machine", []),
    ("Prone Hamstring Curl", "Hamstrings", "Machine", []),
    ("Seated Hamstring Curl", "Hamstrings", "Machine", []),
    ("Hip Thrust", "Glutes", "Barbell", ["Hamstrings"]),
    ("Glute Bridge", "Glutes", "Barbell", ["Hamstrings"]),
    ("Cable Glute Kickback", "Glutes", "Cables", ["Hamstrings"]),
    ("Cable Pull-Through", "Glutes", "Cables", ["Hamstrings", "Lower Back"]),
    ("Glute-Ham Raise", "Hamstrings", "Machine", ["Glutes", "Lower Back"]),
    ("Hip Abduction Machine", "Abductors", "Machine", ["Glutes"]),
    ("Hip Adduction Machine", "Adductors", "Machine", []),
    ("Back Extension", "Lower Back", "Bodyweight", ["Glutes", "Hamstrings"]),
    ("Hyperextension", "Lower Back", "Bodyweight", ["Glutes", "Hamstrings"]),
    ("Reverse Hyper", "Lower Back", "Machine", ["Glutes", "Hamstrings"]),
    ("Calf Raise", "Calves", "Machine", []),
    ("Standing Calf Raise", "Calves", "Machine", []),
    ("Seated Calf Raise", "Calves", "Machine", []),
    ("Toe Press", "Calves", "Machine", []),
    ("Barbell Curl", "Biceps", "Barbell", []),
    ("Dumbbell Curl", "Biceps", "Dumbbells", []),
    ("Cable Curl", "Biceps", "Cables", []),
    ("Preacher Curl", "Biceps", "Barbell", []),
    ("Machine Preacher Curl", "Biceps", "Machine", []),
    ("Incline Dumbbell Curl", "Biceps", "Dumbbells", []),
    ("Hammer Curl", "Biceps", "Dumbbells", []),
    ("Concentration Curl", "Biceps", "Dumbbells", []),
    ("Spider Curl", "Biceps", "Dumbbells", []),
    ("EZ-Bar Curl", "Biceps", "EZ Bar", []),
    ("Reverse Curl", "Forearms", "EZ Bar", ["Biceps"]),
    ("Wrist Curl", "Forearms", "Dumbbells", []),
    ("Reverse Wrist Curl", "Forearms", "Dumbbells", []),
    ("Triceps Pushdown", "Triceps", "Cables", []),
    ("Rope Triceps Pushdown", "Triceps", "Cables", []),
    ("Skull Crusher", "Triceps", "Barbell", []),
    ("Close-Grip Bench Press", "Triceps", "Barbell", ["Chest", "Shoulders"]),
    ("JM Press", "Triceps", "Barbell", ["Chest"]),
    ("Bench Dip", "Triceps", "Bodyweight", ["Chest", "Shoulders"]),
    ("Triceps Kickback", "Triceps", "Dumbbells", []),
    ("Overhead Triceps Extension", "Triceps", "Dumbbells", []),
    ("Cable Crunch", "Abs", "Cables", ["Core"]),
    ("Machine Crunch", "Abs", "Machine", ["Core"]),
    ("Decline Crunch", "Abs", "Bodyweight", ["Core"]),
    ("Weighted Crunch", "Abs", "Dumbbells", ["Core"]),
    ("Reverse Crunch", "Abs", "Bodyweight", ["Core"]),
    ("Hanging Leg Raise", "Abs", "Bodyweight", ["Core"]),
    ("Captain's Chair Leg Raise", "Abs", "Bodyweight", ["Core"]),
    ("Ab Wheel Rollout", "Abs", "Bodyweight", ["Core"]),
    ("Plank", "Core", "Bodyweight", []),
    ("Side Plank", "Core", "Bodyweight", ["Abs"]),
    ("Pallof Press", "Core", "Cables", ["Abs"]),
    ("Russian Twist", "Obliques", "Bodyweight", ["Abs"]),
    ("Wood Chopper", "Obliques", "Cables", ["Abs"]),
    ("Cable Side Bend", "Obliques", "Cables", ["Abs"]),
    ("Dead Bug", "Core", "Bodyweight", ["Abs"]),
    ("Bird Dog", "Core", "Bodyweight", []),
    ("Hollow Body Hold", "Core", "Bodyweight", ["Abs"]),
    ("Farmer Carry", "Core", "Dumbbells", ["Back", "Shoulders"]),
    ("Kettlebell Swing", "Glutes", "Kettlebell", ["Hamstrings", "Lower Back"]),
    ("Band Pull-Apart", "Shoulders", "Bands", ["Back"]),
    ("Box Jump", "Quads", "Bodyweight", ["Glutes", "Calves"]),
    ("Clean", "Back", "Barbell", ["Quads", "Glutes", "Shoulders"]),
    ("Snatch", "Back", "Barbell", ["Quads", "Glutes", "Shoulders"]),
    ("Jerk", "Shoulders", "Barbell", ["Triceps", "Quads"]),
]


EXERCISE_NOTES = {
    "Assisted Pull-Up Machine": "Use only enough assistance to complete clean reps; start each rep from a full hang and drive elbows toward your ribs.",
    "Ab Wheel Rollout": "Brace hard before rolling out, keep ribs down, and stop the range before the low back sags.",
    "Back Extension": "Hinge at the hips instead of overextending the spine; squeeze glutes at the top.",
    "Bird Dog": "Reach opposite arm and leg while keeping hips square and low back still.",
    "Box Jump": "Land softly with the full foot on the box, stand tall, and step down between reps.",
    "Cable Pull-Through": "Let the hips travel back, keep arms long, and finish by driving glutes through without leaning back.",
    "Dead Bug": "Press low back gently into the floor and move slowly while exhaling through each extension.",
    "Face Pull": "Pull toward eye level with elbows high, then rotate thumbs back to bias rear delts and external rotators.",
    "Farmer Carry": "Stand tall, brace, and walk without leaning; use controlled steps and even grip pressure.",
    "Goblet Squat": "Hold the bell tight to the chest, keep torso tall, and let knees track over toes.",
    "Good Morning": "Keep a soft knee bend and neutral spine; hinge until hamstrings limit the range, then drive hips forward.",
    "Hip Abduction Machine": "Keep hips planted and use controlled reps; avoid bouncing the stack open.",
    "Hip Adduction Machine": "Sit tall, control the inward squeeze, and pause briefly without letting the stack slam.",
    "Hip Thrust": "Tuck ribs down, drive through midfoot/heel, and finish with glutes rather than low-back extension.",
    "Kettlebell Swing": "Make it a hip snap, not a squat; the bell floats from hip power while arms stay relaxed.",
    "Landmine Press": "Press up and forward on the landmine arc while keeping ribs down and shoulder blade moving naturally.",
    "Pallof Press": "Stand square to the cable, brace, and press straight out without letting the torso rotate.",
    "Romanian Deadlift": "Push hips back with a neutral spine, keep the bar close, and stop when hamstrings reach a strong stretch.",
    "Trap-Bar Deadlift": "Brace, push the floor away, and keep handles level so hips and chest rise together.",
    "Wood Chopper": "Rotate through the upper back and hips under control; keep arms long and avoid yanking with the shoulders.",
}

EXERCISE_ALIASES = {
    "Deadlift": ["Dead Lift"],
    "Overhead Press": ["OHP", "Standing Press", "Military Press"],
    "Romanian Deadlift": ["RDL"],
    "Trap-Bar Deadlift": ["Hex Bar Deadlift"],
    "Pec Fly Machine": ["Pec Deck", "Chest Fly Machine"],
    "Lat Pulldown": ["Pulldown"],
    "Barbell Row": ["Bent-Over Row"],
    "Dumbbell Shoulder Press": ["DB Shoulder Press"],
    "EZ-Bar Curl": ["EZ Curl"],
    "Cable Glute Kickback": ["Glute Kickback"],
    "Hip Abduction Machine": ["Abductor Machine"],
    "Hip Adduction Machine": ["Adductor Machine"],
    "Back Squat": ["Squat"],
    "Pull-Up": ["Pullup"],
    "Chin-Up": ["Chinup"],
}


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if table not in ALLOWED_TABLES:
        raise ValueError(f"unknown table: {table}")
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def backfill_orphaned_workouts(conn: sqlite3.Connection):
    admin = conn.execute(
        "SELECT id FROM users WHERE role = 'admin' AND is_active = 1 ORDER BY id LIMIT 1"
    ).fetchone()
    if not admin:
        return
    conn.execute("UPDATE workouts SET user_id = ? WHERE user_id IS NULL", (admin["id"],))


def dedupe_case_duplicate_exercises(conn: sqlite3.Connection):
    rows = conn.execute("SELECT id, name FROM exercises ORDER BY LOWER(name), id").fetchall()
    seen: set[str] = set()
    for row in rows:
        name = row["name"].strip()
        key = name.lower()
        if key not in seen:
            seen.add(key)
            continue
        suffix = row["id"]
        candidate = f"{name} ({suffix})"
        while candidate.lower() in seen:
            suffix += 1
            candidate = f"{name} ({suffix})"
        conn.execute("UPDATE exercises SET name = ? WHERE id = ?", (candidate, row["id"]))
        seen.add(candidate.lower())


def migration_add_workout_user_id(conn: sqlite3.Connection):
    if "user_id" not in table_columns(conn, "workouts"):
        conn.execute("ALTER TABLE workouts ADD COLUMN user_id INTEGER")


def migration_add_workout_bodyweight(conn: sqlite3.Connection):
    if "bodyweight_lbs" not in table_columns(conn, "workouts"):
        conn.execute("ALTER TABLE workouts ADD COLUMN bodyweight_lbs REAL")


def migration_add_workout_set_metadata(conn: sqlite3.Connection):
    workout_set_columns = table_columns(conn, "workout_sets")
    if "set_type" not in workout_set_columns:
        conn.execute("ALTER TABLE workout_sets ADD COLUMN set_type TEXT NOT NULL DEFAULT 'working'")
    if "group_label" not in workout_set_columns:
        conn.execute("ALTER TABLE workout_sets ADD COLUMN group_label TEXT")
    if "rest_seconds" not in workout_set_columns:
        conn.execute("ALTER TABLE workout_sets ADD COLUMN rest_seconds INTEGER")
    if "tempo" not in workout_set_columns:
        conn.execute("ALTER TABLE workout_sets ADD COLUMN tempo TEXT")


def migration_add_workouts_user_date_index(conn: sqlite3.Connection):
    conn.execute("CREATE INDEX IF NOT EXISTS idx_workouts_user_date ON workouts(user_id, workout_date DESC, id DESC)")


def migration_add_exercise_name_nocase_index(conn: sqlite3.Connection):
    dedupe_case_duplicate_exercises(conn)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_exercises_name_nocase ON exercises(name COLLATE NOCASE)")


def migration_drop_redundant_workouts_date_index(conn: sqlite3.Connection):
    conn.execute("DROP INDEX IF EXISTS idx_workouts_date")


def workout_sets_exercise_fk_delete_rule(conn: sqlite3.Connection) -> str | None:
    for row in conn.execute("PRAGMA foreign_key_list(workout_sets)").fetchall():
        if row["from"] == "exercise_id" and row["table"] == "exercises":
            return row["on_delete"]
    return None


def migration_rebuild_workout_sets_exercise_fk(conn: sqlite3.Connection):
    if workout_sets_exercise_fk_delete_rule(conn) == "RESTRICT":
        return
    has_updated_at = "updated_at" in table_columns(conn, "workout_sets")
    conn.execute("DROP TABLE IF EXISTS workout_sets_new")
    conn.execute(
        """
        CREATE TABLE workout_sets_new (
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
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (workout_id) REFERENCES workouts(id) ON DELETE CASCADE,
            FOREIGN KEY (exercise_id) REFERENCES exercises(id) ON DELETE RESTRICT
        )
        """
    )
    conn.execute(
        f"""
        INSERT INTO workout_sets_new
        (id, workout_id, exercise_id, set_number, weight_lbs, weight_mode, reps, rpe, duration_seconds, set_type, group_label, rest_seconds, tempo, notes, updated_at, created_at)
        SELECT id, workout_id, exercise_id, set_number, weight_lbs, 'external', reps, rpe, NULL, set_type, group_label, rest_seconds, tempo, notes,
               COALESCE({'updated_at' if has_updated_at else 'created_at'}, created_at, CURRENT_TIMESTAMP) AS updated_at,
               created_at
        FROM workout_sets
        """
    )
    conn.execute("DROP TABLE workout_sets")
    conn.execute("ALTER TABLE workout_sets_new RENAME TO workout_sets")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sets_workout ON workout_sets(workout_id, set_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sets_exercise ON workout_sets(exercise_id, id)")


def migration_add_audit_timestamps(conn: sqlite3.Connection):
    user_columns = table_columns(conn, "users")
    if "updated_at" not in user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN updated_at DATETIME")
        conn.execute("UPDATE users SET updated_at = COALESCE(created_at, CURRENT_TIMESTAMP)")
    if "last_login_at" not in user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN last_login_at DATETIME")
    exercise_columns = table_columns(conn, "exercises")
    if "updated_at" not in exercise_columns:
        conn.execute("ALTER TABLE exercises ADD COLUMN updated_at DATETIME")
        conn.execute("UPDATE exercises SET updated_at = COALESCE(created_at, CURRENT_TIMESTAMP)")
    workout_set_columns = table_columns(conn, "workout_sets")
    if "updated_at" not in workout_set_columns:
        conn.execute("ALTER TABLE workout_sets ADD COLUMN updated_at DATETIME")
        conn.execute("UPDATE workout_sets SET updated_at = COALESCE(created_at, CURRENT_TIMESTAMP)")


def migration_reclassify_cable_crunch_abs(conn: sqlite3.Connection):
    conn.execute(
        """
        UPDATE exercises
        SET primary_muscle = 'Abs',
            secondary_muscles = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE name = 'Cable Crunch' AND primary_muscle = 'Core'
        """,
        (json.dumps(["Core"]),),
    )


def migration_add_exercise_aliases(conn: sqlite3.Connection):
    if "aliases" not in table_columns(conn, "exercises"):
        conn.execute("ALTER TABLE exercises ADD COLUMN aliases TEXT NOT NULL DEFAULT '[]'")


def migration_add_bodyweight_set_fields(conn: sqlite3.Connection):
    workout_set_columns = table_columns(conn, "workout_sets")
    if "weight_mode" not in workout_set_columns:
        conn.execute("ALTER TABLE workout_sets ADD COLUMN weight_mode TEXT NOT NULL DEFAULT 'external'")
    if "duration_seconds" not in workout_set_columns:
        conn.execute("ALTER TABLE workout_sets ADD COLUMN duration_seconds INTEGER")


def migration_add_goals(conn: sqlite3.Connection):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            kind TEXT NOT NULL,
            exercise_id INTEGER,
            target_value_lbs REAL NOT NULL,
            target_date DATE,
            notes TEXT,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (exercise_id) REFERENCES exercises(id) ON DELETE SET NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_goals_user_kind ON goals(user_id, kind, target_date)")


def migration_add_user_settings(conn: sqlite3.Connection):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER PRIMARY KEY,
            unit TEXT NOT NULL DEFAULT 'lb',
            default_rest_seconds INTEGER NOT NULL DEFAULT 120,
            default_reps INTEGER NOT NULL DEFAULT 8,
            theme TEXT NOT NULL DEFAULT 'system',
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )


def migration_add_reminder_settings(conn: sqlite3.Connection):
    columns = table_columns(conn, "user_settings")
    if "reminder_enabled" not in columns:
        conn.execute("ALTER TABLE user_settings ADD COLUMN reminder_enabled INTEGER NOT NULL DEFAULT 0")
    if "reminder_hour" not in columns:
        conn.execute("ALTER TABLE user_settings ADD COLUMN reminder_hour INTEGER NOT NULL DEFAULT 18")


def migration_backfill_null_audit_timestamps(conn: sqlite3.Connection):
    if "updated_at" in table_columns(conn, "users"):
        conn.execute("UPDATE users SET updated_at = COALESCE(created_at, CURRENT_TIMESTAMP) WHERE updated_at IS NULL")
    if "updated_at" in table_columns(conn, "exercises"):
        conn.execute("UPDATE exercises SET updated_at = COALESCE(created_at, CURRENT_TIMESTAMP) WHERE updated_at IS NULL")
    if "updated_at" in table_columns(conn, "workout_sets"):
        conn.execute("UPDATE workout_sets SET updated_at = COALESCE(created_at, CURRENT_TIMESTAMP) WHERE updated_at IS NULL")


def parse_aliases(value: str | None) -> list[str]:
    try:
        aliases = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(aliases, list):
        return []
    return [str(alias).strip() for alias in aliases if str(alias).strip()]


def append_exercise_aliases(conn: sqlite3.Connection, exercise_id: int, aliases: list[str]):
    row = conn.execute("SELECT aliases FROM exercises WHERE id = ?", (exercise_id,)).fetchone()
    if not row:
        return
    merged = parse_aliases(row["aliases"])
    seen = {alias.casefold() for alias in merged}
    for alias in aliases:
        normalized = alias.strip()
        if normalized and normalized.casefold() not in seen:
            merged.append(normalized)
            seen.add(normalized.casefold())
    conn.execute("UPDATE exercises SET aliases = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (json.dumps(merged), exercise_id))


def apply_seeded_exercise_aliases(conn: sqlite3.Connection):
    for name, aliases in EXERCISE_ALIASES.items():
        row = conn.execute("SELECT id FROM exercises WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
        if row:
            append_exercise_aliases(conn, row["id"], aliases)


def merge_duplicate_exercise_name(conn: sqlite3.Connection, canonical_name: str, duplicate_name: str):
    canonical = conn.execute("SELECT id FROM exercises WHERE name = ? COLLATE NOCASE", (canonical_name,)).fetchone()
    if not canonical:
        return
    duplicate_rows = conn.execute(
        """
        SELECT id, name, aliases
        FROM exercises
        WHERE name = ? COLLATE NOCASE
          AND id != ?
        """,
        (duplicate_name, canonical["id"]),
    ).fetchall()
    for duplicate in duplicate_rows:
        conn.execute("UPDATE workout_sets SET exercise_id = ? WHERE exercise_id = ?", (canonical["id"], duplicate["id"]))
        conn.execute("UPDATE goals SET exercise_id = ? WHERE exercise_id = ?", (canonical["id"], duplicate["id"]))
        append_exercise_aliases(conn, canonical["id"], [duplicate["name"], *parse_aliases(duplicate["aliases"])])
        conn.execute("DELETE FROM exercises WHERE id = ?", (duplicate["id"],))


def migration_merge_dead_lift_into_deadlift(conn: sqlite3.Connection):
    merge_duplicate_exercise_name(conn, "Deadlift", "Dead Lift")


MIGRATIONS = (
    (1, "add_workout_user_id", migration_add_workout_user_id),
    (2, "add_workout_bodyweight", migration_add_workout_bodyweight),
    (3, "add_workout_set_metadata", migration_add_workout_set_metadata),
    (4, "add_workouts_user_date_index", migration_add_workouts_user_date_index),
    (5, "add_exercise_name_nocase_index", migration_add_exercise_name_nocase_index),
    (6, "drop_redundant_workouts_date_index", migration_drop_redundant_workouts_date_index),
    (7, "rebuild_workout_sets_exercise_fk", migration_rebuild_workout_sets_exercise_fk),
    (8, "add_audit_timestamps", migration_add_audit_timestamps),
    (9, "reclassify_cable_crunch_abs", migration_reclassify_cable_crunch_abs),
    (10, "add_exercise_aliases", migration_add_exercise_aliases),
    (11, "add_bodyweight_set_fields", migration_add_bodyweight_set_fields),
    (12, "add_goals", migration_add_goals),
    (13, "add_user_settings", migration_add_user_settings),
    (14, "add_reminder_settings", migration_add_reminder_settings),
    (15, "backfill_null_audit_timestamps", migration_backfill_null_audit_timestamps),
    (16, "merge_dead_lift_into_deadlift", migration_merge_dead_lift_into_deadlift),
)


def run_schema_migrations(conn: sqlite3.Connection):
    applied = {
        row["version"]
        for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
    }
    for version, name, migrate in MIGRATIONS:
        if version in applied:
            continue
        migrate(conn)
        conn.execute(
            "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
            (version, name),
        )


def init_db():
    with db() as conn:
        conn.executescript(SCHEMA)
        run_schema_migrations(conn)
        backfill_orphaned_workouts(conn)
        prune_expired_sessions(conn)

        conn.executemany(
            """
            INSERT OR IGNORE INTO exercises (name, primary_muscle, equipment, secondary_muscles, aliases)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (name, muscle, equipment, json.dumps(secondaries), json.dumps(EXERCISE_ALIASES.get(name, [])))
                for name, muscle, equipment, secondaries in SEEDED_EXERCISES
            ],
        )
        conn.execute("UPDATE exercises SET primary_muscle = 'Traps' WHERE name = 'Dumbbell Shrug'")
        conn.execute("UPDATE exercises SET equipment = 'Smith Machine' WHERE name = 'Smith Machine Squat'")
        conn.executemany(
            """
            UPDATE exercises
            SET notes = ?
            WHERE name = ?
              AND (notes IS NULL OR TRIM(notes) = '')
            """,
            [(notes, name) for name, notes in EXERCISE_NOTES.items()],
        )
        conn.executemany(
            """
            UPDATE exercises
            SET aliases = ?
            WHERE name = ?
              AND (aliases IS NULL OR aliases = '[]')
            """,
            [(json.dumps(aliases), name) for name, aliases in EXERCISE_ALIASES.items()],
        )
        apply_seeded_exercise_aliases(conn)
        migration_merge_dead_lift_into_deadlift(conn)
        migration_backfill_null_audit_timestamps(conn)


def user_from_row(row: sqlite3.Row) -> UserOut:
    d = row_to_dict(row)
    d["is_active"] = bool(d["is_active"])
    return UserOut(**d)


def exercise_from_row(row: sqlite3.Row) -> ExerciseOut:
    d = row_to_dict(row)
    try:
        d["secondary_muscles"] = json.loads(d.get("secondary_muscles") or "[]")
    except json.JSONDecodeError:
        d["secondary_muscles"] = []
    try:
        d["aliases"] = json.loads(d.get("aliases") or "[]")
    except json.JSONDecodeError:
        d["aliases"] = []
    d["is_archived"] = bool(d["is_archived"])
    return ExerciseOut(**d)


def set_from_row(row: sqlite3.Row) -> WorkoutSetOut:
    d = row_to_dict(row)
    d["weight_mode"] = d.get("weight_mode") or "external"
    d["effective_weight_lbs"] = effective_weight(d["weight_lbs"], d["weight_mode"], d.get("bodyweight_lbs"))
    d["volume_lbs"] = volume(d["effective_weight_lbs"], d["reps"])
    d["estimated_1rm"] = estimate_1rm(d["effective_weight_lbs"], d["reps"])
    return WorkoutSetOut(**d)


def users_exist(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT EXISTS(SELECT 1 FROM users)").fetchone()[0] == 1


def active_admin_count(conn: sqlite3.Connection) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1"
    ).fetchone()[0]


def would_remove_last_active_admin(conn: sqlite3.Connection, user_id: int, next_role: str | None = None, next_is_active: bool | None = None) -> bool:
    row = conn.execute("SELECT role, is_active FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row or row["role"] != "admin" or not row["is_active"]:
        return False
    role = next_role if next_role is not None else row["role"]
    is_active = next_is_active if next_is_active is not None else bool(row["is_active"])
    return (role != "admin" or not is_active) and active_admin_count(conn) <= 1


def create_user(conn: sqlite3.Connection, payload: UserCreateIn | AuthSetupIn, role: str = "user") -> UserOut:
    username = normalize_username(payload.username)
    display_name = (payload.display_name or username).strip()
    salt, pin_digest = hash_pin(payload.pin)
    try:
        cur = conn.execute(
            """
            INSERT INTO users (username, display_name, pin_salt, pin_hash, role)
            VALUES (?, ?, ?, ?, ?)
            """,
            (username, display_name, salt, pin_digest, role),
        )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="username already exists")
    row = conn.execute(
        "SELECT id, username, display_name, role, is_active, created_at, updated_at, last_login_at FROM users WHERE id = ?",
        (cur.lastrowid,),
    ).fetchone()
    if role == "admin":
        backfill_orphaned_workouts(conn)
    return user_from_row(row)


def issue_session(conn: sqlite3.Connection, user_id: int) -> str:
    now = int(time.time())
    prune_expired_sessions(conn, now)
    raw_token = secrets.token_urlsafe(32)
    conn.execute(
        """
        INSERT INTO sessions (user_id, token_hash, expires_at, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, hash_session_token(raw_token), now + SESSION_MAX_AGE, now),
    )
    conn.execute(
        """
        DELETE FROM sessions
        WHERE user_id = ?
          AND id NOT IN (
            SELECT id
            FROM sessions
            WHERE user_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
          )
        """,
        (user_id, user_id, SESSION_MAX_PER_USER),
    )
    return raw_token


def set_session_cookie(response: Response, token: str):
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="strict",
        secure=COOKIE_SECURE,
        path="/",
    )


def clear_session_cookie(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")


def read_session_user(conn: sqlite3.Connection, token: str | None) -> UserOut | None:
    prune_expired_sessions(conn)
    if not token:
        return None
    row = conn.execute(
        """
        SELECT u.id, u.username, u.display_name, u.role, u.is_active, u.created_at
             , u.updated_at, u.last_login_at
        FROM sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.token_hash = ? AND s.expires_at > ? AND u.is_active = 1
        """,
        (hash_session_token(token), int(time.time())),
    ).fetchone()
    return user_from_row(row) if row else None


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded and is_trusted_proxy(request.client.host if request.client else None):
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def login_ip_is_limited(conn: sqlite3.Connection, ip: str) -> bool:
    now = int(time.time())
    since = now - LOGIN_WINDOW_SECONDS
    failures = conn.execute(
        """
        SELECT COUNT(*)
        FROM login_attempts
        WHERE success = 0
          AND attempted_at >= ?
          AND ip = ?
        """,
        (since, ip),
    ).fetchone()[0]
    return failures >= LOGIN_IP_FAILURE_LIMIT


def login_account_delay_seconds(conn: sqlite3.Connection, username: str) -> float:
    now = int(time.time())
    since = now - LOGIN_WINDOW_SECONDS
    failures = conn.execute(
        """
        SELECT COUNT(*)
        FROM login_attempts
        WHERE success = 0
          AND attempted_at >= ?
          AND username = ?
        """,
        (since, username),
    ).fetchone()[0]
    if failures < LOGIN_USERNAME_DELAY_THRESHOLD:
        return 0.0
    return min(2.0, 0.25 * (failures - (LOGIN_USERNAME_DELAY_THRESHOLD - 1)))


def prune_login_attempts(conn: sqlite3.Connection, now: int | None = None):
    cutoff = (now or int(time.time())) - LOGIN_ATTEMPT_RETENTION_SECONDS
    conn.execute("DELETE FROM login_attempts WHERE attempted_at < ?", (cutoff,))


def prune_login_attempts_standalone():
    with db() as conn:
        prune_login_attempts(conn)


def record_login_attempt(username: str, ip: str, success: bool):
    with db() as conn:
        now = int(time.time())
        conn.execute(
            "INSERT INTO login_attempts (username, ip, success, attempted_at) VALUES (?, ?, ?, ?)",
            (username, ip, int(success), now),
        )


def require_user(fitness_session: str | None = Cookie(default=None)) -> UserOut:
    with db() as conn:
        user = read_session_user(conn, fitness_session)
        if not user:
            raise HTTPException(status_code=401, detail="login required")
        return user


def require_admin(user: UserOut = Depends(require_user)) -> UserOut:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="admin required")
    return user


def fetch_or_create_settings(conn: sqlite3.Connection, user_id: int) -> SettingsOut:
    row = conn.execute(
        "SELECT unit, default_rest_seconds, default_reps, theme, reminder_enabled, reminder_hour, updated_at FROM user_settings WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if row is None:
        conn.execute("INSERT OR IGNORE INTO user_settings (user_id) VALUES (?)", (user_id,))
        row = conn.execute(
            "SELECT unit, default_rest_seconds, default_reps, theme, reminder_enabled, reminder_hour, updated_at FROM user_settings WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    return SettingsOut(**row_to_dict(row))


def wipe_user_data(conn: sqlite3.Connection, user_id: int):
    workout_ids = [row["id"] for row in conn.execute("SELECT id FROM workouts WHERE user_id = ?", (user_id,)).fetchall()]
    if workout_ids:
        placeholders = ",".join(["?"] * len(workout_ids))
        conn.execute(f"DELETE FROM workout_sets WHERE workout_id IN ({placeholders})", tuple(workout_ids))
    conn.execute("DELETE FROM workouts WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM body_measurements WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM goals WHERE user_id = ?", (user_id,))


def fetch_workout(conn: sqlite3.Connection, workout_id: int, user_id: int) -> WorkoutOut:
    effective = effective_weight_sql()
    workout = conn.execute(
        f"""
        SELECT w.id, w.workout_date, w.title, w.bodyweight_lbs, w.notes,
               COUNT(ws.id) AS set_count,
               COALESCE(SUM(CASE WHEN COALESCE(ws.set_type, 'working') != 'warmup' THEN ROUND(({effective}) * ws.reps, 1) ELSE 0 END), 0) AS volume_lbs
        FROM workouts w
        LEFT JOIN workout_sets ws ON ws.workout_id = w.id
        WHERE w.id = ? AND w.user_id = ?
        GROUP BY w.id
        """,
        (workout_id, user_id),
    ).fetchone()
    if not workout:
        raise HTTPException(status_code=404, detail="workout not found")
    set_rows = conn.execute(
        """
        SELECT ws.*, w.bodyweight_lbs, e.name AS exercise_name, e.primary_muscle, e.equipment
        FROM workout_sets ws
        JOIN workouts w ON w.id = ws.workout_id
        JOIN exercises e ON e.id = ws.exercise_id
        WHERE ws.workout_id = ?
        ORDER BY ws.id
        """,
        (workout_id,),
    ).fetchall()
    return WorkoutOut(**row_to_dict(workout), sets=[set_from_row(r) for r in set_rows])


def validate_workout_exercises(conn: sqlite3.Connection, payload: WorkoutIn):
    exercise_ids = [s.exercise_id for s in payload.sets]
    unique_ids = sorted(set(exercise_ids))
    placeholders = ",".join(["?"] * len(unique_ids))
    found = conn.execute(
        f"SELECT id FROM exercises WHERE id IN ({placeholders})",
        tuple(unique_ids),
    ).fetchall()
    found_ids = {r["id"] for r in found}
    missing = sorted(set(exercise_ids) - found_ids)
    if missing:
        raise HTTPException(status_code=400, detail=f"unknown exercise ids: {missing}")


def replace_workout_sets(conn: sqlite3.Connection, workout_id: int, sets: list[SetIn]):
    conn.execute("DELETE FROM workout_sets WHERE workout_id = ?", (workout_id,))
    exercise_counts: dict[int, int] = {}
    for s in sets:
        exercise_counts[s.exercise_id] = exercise_counts.get(s.exercise_id, 0) + 1
        conn.execute(
            """
            INSERT INTO workout_sets
            (workout_id, exercise_id, set_number, weight_lbs, weight_mode, reps, rpe, duration_seconds, set_type, group_label, rest_seconds, tempo, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (workout_id, s.exercise_id, exercise_counts[s.exercise_id], s.weight_lbs, s.weight_mode, s.reps, s.rpe, s.duration_seconds, s.set_type, s.group_label, s.rest_seconds, s.tempo, s.notes),
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="JournalGym",
    docs_url="/docs" if ENABLE_API_DOCS else None,
    redoc_url="/redoc" if ENABLE_API_DOCS else None,
    openapi_url="/openapi.json" if ENABLE_API_DOCS else None,
    lifespan=lifespan,
)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.environ.get("FITNESS_CORS_ALLOW_ORIGINS", "").split(",")
        if origin.strip()
    ],
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["content-type"],
    allow_credentials=True,
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    try:
        if REQUEST_BODY_MAX_BYTES > 0 and request.method in {"POST", "PUT", "PATCH"}:
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > REQUEST_BODY_MAX_BYTES:
                        response = Response("request body too large", status_code=413)
                    else:
                        response = await call_next(request)
                except ValueError:
                    response = await call_next(request)
            else:
                response = await call_next(request)
        else:
            response = await call_next(request)
    except sqlite3.OperationalError as exc:
        if not is_sqlite_busy_error(exc):
            raise
        response = Response("database temporarily busy", status_code=503)
    if request.url.path == "/service-worker.js":
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Service-Worker-Allowed"] = "/"
    for header, value in SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    return response


@app.get("/api/health", include_in_schema=False)
def health():
    with db() as conn:
        conn.execute("SELECT 1").fetchone()
    return {"status": "ok", "database": "ok"}


@app.get("/api/metrics", include_in_schema=False)
def metrics():
    with db() as conn:
        return {
            "status": "ok",
            "uptime_seconds": max(0, int(time.time()) - APP_STARTED_AT),
            "users": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
            "workouts": conn.execute("SELECT COUNT(*) FROM workouts").fetchone()[0],
            "workout_sets": conn.execute("SELECT COUNT(*) FROM workout_sets").fetchone()[0],
            "exercises": conn.execute("SELECT COUNT(*) FROM exercises").fetchone()[0],
        }


@app.get("/api/auth/me")
def auth_me(fitness_session: str | None = Cookie(default=None)):
    with db() as conn:
        return {
            "setup_required": not users_exist(conn),
            "user": read_session_user(conn, fitness_session),
        }


@app.post("/api/auth/setup")
def auth_setup(payload: AuthSetupIn, response: Response):
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if users_exist(conn):
            raise HTTPException(status_code=409, detail="setup already completed")
        user = create_user(conn, payload, role="admin")
        token = issue_session(conn, user.id)
        set_session_cookie(response, token)
    return {"user": user, "setup_required": False}


@app.post("/api/auth/login")
def auth_login(payload: LoginIn, request: Request, response: Response):
    username = normalize_username(payload.username)
    ip = client_ip(request)
    prune_login_attempts_standalone()
    with db() as conn:
        if not users_exist(conn):
            raise HTTPException(status_code=409, detail="setup required")
        if login_ip_is_limited(conn, ip):
            raise HTTPException(status_code=429, detail="too many failed attempts")
        delay = login_account_delay_seconds(conn, username)
        if delay:
            time.sleep(delay)
        row = conn.execute(
            """
            SELECT id, username, display_name, pin_salt, pin_hash, role, is_active, created_at, updated_at, last_login_at
            FROM users
            WHERE username = ?
            """,
            (username,),
        ).fetchone()
        ok = False
        needs_pin_rehash = False
        if row and row["is_active"]:
            ok, needs_pin_rehash = verify_pin_status(payload.pin, row["pin_salt"], row["pin_hash"])
        record_login_attempt(username, ip, ok)
        if not ok:
            raise HTTPException(status_code=401, detail="invalid username or pin")
        if needs_pin_rehash:
            salt, pin_digest = hash_pin(payload.pin)
            conn.execute(
                "UPDATE users SET pin_salt = ?, pin_hash = ?, last_login_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (salt, pin_digest, row["id"]),
            )
        else:
            conn.execute(
                "UPDATE users SET last_login_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (row["id"],),
            )
        token = issue_session(conn, row["id"])
        set_session_cookie(response, token)
        user = user_from_row(conn.execute(
            "SELECT id, username, display_name, role, is_active, created_at, updated_at, last_login_at FROM users WHERE id = ?",
            (row["id"],),
        ).fetchone())
    return {"user": user, "setup_required": False}


@app.post("/api/auth/logout")
def auth_logout(response: Response, fitness_session: str | None = Cookie(default=None)):
    if fitness_session:
        with db() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (hash_session_token(fitness_session),))
    clear_session_cookie(response)
    return {"status": "logged out"}


@app.post("/api/auth/logout-all")
def auth_logout_all(response: Response, user: UserOut = Depends(require_user)):
    with db() as conn:
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user.id,))
    clear_session_cookie(response)
    return {"status": "logged out"}


@app.put("/api/auth/pin", response_model=UserOut)
def change_own_pin(payload: PinChangeIn, response: Response, user: UserOut = Depends(require_user)):
    with db() as conn:
        row = conn.execute(
            """
            SELECT id, username, display_name, pin_salt, pin_hash, role, is_active, created_at, updated_at, last_login_at
            FROM users
            WHERE id = ? AND is_active = 1
            """,
            (user.id,),
        ).fetchone()
        if not row or not verify_pin(payload.current_pin, row["pin_salt"], row["pin_hash"]):
            raise HTTPException(status_code=401, detail="invalid current pin")
        salt, pin_digest = hash_pin(payload.new_pin)
        conn.execute(
            "UPDATE users SET pin_salt = ?, pin_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (salt, pin_digest, user.id),
        )
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user.id,))
        token = issue_session(conn, user.id)
        set_session_cookie(response, token)
        updated = conn.execute(
            "SELECT id, username, display_name, role, is_active, created_at, updated_at, last_login_at FROM users WHERE id = ?",
            (user.id,),
        ).fetchone()
    return user_from_row(updated)


@app.get("/api/settings", response_model=SettingsOut)
def get_settings(user: UserOut = Depends(require_user)):
    with db() as conn:
        return fetch_or_create_settings(conn, user.id)


@app.put("/api/settings", response_model=SettingsOut)
def update_settings(payload: SettingsIn, user: UserOut = Depends(require_user)):
    with db() as conn:
        conn.execute(
            """
            INSERT INTO user_settings (user_id, unit, default_rest_seconds, default_reps, theme, reminder_enabled, reminder_hour, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
              unit = excluded.unit,
              default_rest_seconds = excluded.default_rest_seconds,
              default_reps = excluded.default_reps,
              theme = excluded.theme,
              reminder_enabled = excluded.reminder_enabled,
              reminder_hour = excluded.reminder_hour,
              updated_at = CURRENT_TIMESTAMP
            """,
            (user.id, payload.unit, payload.default_rest_seconds, payload.default_reps, payload.theme, int(payload.reminder_enabled), payload.reminder_hour),
        )
        return fetch_or_create_settings(conn, user.id)


@app.delete("/api/account/data")
def wipe_own_data(user: UserOut = Depends(require_user)):
    with db() as conn:
        wipe_user_data(conn, user.id)
    invalidate_dashboard_cache(user.id)
    return {"status": "wiped"}


@app.delete("/api/account")
def delete_own_account(response: Response, user: UserOut = Depends(require_user)):
    with db() as conn:
        if would_remove_last_active_admin(conn, user.id, next_is_active=False):
            raise HTTPException(status_code=400, detail="cannot remove the last active admin")
        wipe_user_data(conn, user.id)
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user.id,))
        conn.execute("DELETE FROM user_settings WHERE user_id = ?", (user.id,))
        cur = conn.execute("DELETE FROM users WHERE id = ?", (user.id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="user not found")
    invalidate_dashboard_cache(user.id)
    clear_session_cookie(response)
    return {"status": "deleted"}


@app.get("/api/users", response_model=list[UserOut])
def list_users(_: UserOut = Depends(require_admin)):
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id, username, display_name, role, is_active, created_at, updated_at, last_login_at
            FROM users
            ORDER BY role = 'admin' DESC, display_name COLLATE NOCASE
            """
        ).fetchall()
    return [user_from_row(r) for r in rows]


@app.post("/api/users", response_model=UserOut)
def add_user(payload: UserCreateIn, _: UserOut = Depends(require_admin)):
    with db() as conn:
        return create_user(conn, payload, role=payload.role)


@app.put("/api/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, payload: UserUpdateIn, _: UserOut = Depends(require_admin)):
    username = normalize_username(payload.username)
    display_name = (payload.display_name or username).strip()
    with db() as conn:
        if would_remove_last_active_admin(conn, user_id, payload.role, payload.is_active):
            raise HTTPException(status_code=400, detail="cannot remove the last active admin")
        try:
            cur = conn.execute(
                """
                UPDATE users
                SET username = ?, display_name = ?, role = ?, is_active = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (username, display_name, payload.role, int(payload.is_active), user_id),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail="username already exists")
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="user not found")
        if not payload.is_active:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        row = conn.execute(
            "SELECT id, username, display_name, role, is_active, created_at, updated_at, last_login_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    return user_from_row(row)


@app.put("/api/users/{user_id}/pin", response_model=UserOut)
def reset_user_pin(user_id: int, payload: PinResetIn, _: UserOut = Depends(require_admin)):
    with db() as conn:
        salt, pin_digest = hash_pin(payload.pin)
        cur = conn.execute(
            "UPDATE users SET pin_salt = ?, pin_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (salt, pin_digest, user_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="user not found")
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        row = conn.execute(
            "SELECT id, username, display_name, role, is_active, created_at, updated_at, last_login_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    return user_from_row(row)


@app.delete("/api/users/{user_id}")
def delete_user(user_id: int, _: UserOut = Depends(require_admin)):
    with db() as conn:
        if would_remove_last_active_admin(conn, user_id, next_is_active=False):
            raise HTTPException(status_code=400, detail="cannot remove the last active admin")
        workout_count = conn.execute("SELECT COUNT(*) FROM workouts WHERE user_id = ?", (user_id,)).fetchone()[0]
        if workout_count:
            raise HTTPException(status_code=409, detail="user has workouts; deactivate instead")
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        cur = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="user not found")
    return {"status": "deleted"}


@app.get("/api/exercises", response_model=list[ExerciseOut])
def list_exercises(include_archived: bool = False, _: UserOut = Depends(require_user)):
    with db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM exercises
            WHERE (? OR is_archived = 0)
            ORDER BY primary_muscle, name
            """,
            (int(include_archived),),
        ).fetchall()
    return [exercise_from_row(r) for r in rows]


@app.post("/api/exercises", response_model=ExerciseOut)
def create_exercise(payload: ExerciseIn, _: UserOut = Depends(require_admin)):
    with db() as conn:
        try:
            cur = conn.execute(
                """
                INSERT INTO exercises (name, primary_muscle, equipment, secondary_muscles, aliases, notes)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.name.strip(),
                    payload.primary_muscle.strip(),
                    payload.equipment.strip(),
                    json.dumps(payload.secondary_muscles),
                    json.dumps(payload.aliases),
                    payload.notes,
                ),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail="exercise already exists")
        row = conn.execute("SELECT * FROM exercises WHERE id = ?", (cur.lastrowid,)).fetchone()
    invalidate_dashboard_cache()
    return exercise_from_row(row)


@app.put("/api/exercises/{exercise_id}", response_model=ExerciseOut)
def update_exercise(exercise_id: int, payload: ExerciseUpdateIn, _: UserOut = Depends(require_admin)):
    with db() as conn:
        try:
            cur = conn.execute(
                """
                UPDATE exercises
                SET name = ?, primary_muscle = ?, equipment = ?, secondary_muscles = ?, aliases = ?, notes = ?, is_archived = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    payload.name.strip(),
                    payload.primary_muscle.strip(),
                    payload.equipment.strip(),
                    json.dumps(payload.secondary_muscles),
                    json.dumps(payload.aliases),
                    payload.notes,
                    int(payload.is_archived),
                    exercise_id,
                ),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail="exercise already exists")
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="exercise not found")
        row = conn.execute("SELECT * FROM exercises WHERE id = ?", (exercise_id,)).fetchone()
    invalidate_dashboard_cache()
    return exercise_from_row(row)


@app.get("/api/exercises/last-performed")
def last_performed_exercises(user: UserOut = Depends(require_user)):
    with db() as conn:
        rows = conn.execute(
            """
            SELECT ws.exercise_id, w.id AS workout_id, w.workout_date, w.title, w.bodyweight_lbs,
                   ws.weight_lbs, COALESCE(ws.weight_mode, 'external') AS weight_mode,
                   ws.reps, ws.rpe, ws.duration_seconds
            FROM workout_sets ws
            JOIN workouts w ON w.id = ws.workout_id
            WHERE w.user_id = ?
            ORDER BY ws.exercise_id, w.workout_date DESC, w.id DESC, ws.set_number
            """,
            (user.id,),
        ).fetchall()
    by_exercise = {}
    for row in rows:
        exercise_id = row["exercise_id"]
        current = by_exercise.get(exercise_id)
        if current and current["workout_id"] != row["workout_id"]:
            continue
        if not current:
            current = {
                "exercise_id": exercise_id,
                "workout_id": row["workout_id"],
                "workout_date": row["workout_date"],
                "title": row["title"],
                "sets": [],
            }
            by_exercise[exercise_id] = current
        current["sets"].append({
            "weight_lbs": row["weight_lbs"],
            "weight_mode": row["weight_mode"],
            "effective_weight_lbs": effective_weight(row["weight_lbs"], row["weight_mode"], row["bodyweight_lbs"]),
            "reps": row["reps"],
            "rpe": row["rpe"],
            "duration_seconds": row["duration_seconds"],
        })
    return list(by_exercise.values())


@app.get("/api/workouts", response_model=list[WorkoutOut])
def list_workouts(
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    q: str = Query(default="", max_length=120),
    user: UserOut = Depends(require_user),
):
    with db() as conn:
        effective = effective_weight_sql()
        search = q.strip()
        search_clause = ""
        params: list[object] = [user.id]
        if search:
            search_clause = """
              AND (
                w.title LIKE ?
                OR w.notes LIKE ?
                OR EXISTS (
                  SELECT 1
                  FROM workout_sets ws_search
                  JOIN exercises e_search ON e_search.id = ws_search.exercise_id
                  WHERE ws_search.workout_id = w.id
                    AND e_search.name LIKE ?
                )
              )
            """
            needle = f"%{search}%"
            params.extend([needle, needle, needle])
        params.extend([limit, offset])
        rows = conn.execute(
            f"""
            SELECT w.id, w.workout_date, w.title, w.bodyweight_lbs, w.notes,
                   COUNT(ws.id) AS set_count,
                   COALESCE(SUM(CASE WHEN COALESCE(ws.set_type, 'working') != 'warmup' THEN ROUND(({effective}) * ws.reps, 1) ELSE 0 END), 0) AS volume_lbs
            FROM workouts w
            LEFT JOIN workout_sets ws ON ws.workout_id = w.id
            WHERE w.user_id = ?
            {search_clause}
            GROUP BY w.id
            ORDER BY w.workout_date DESC, w.id DESC
            LIMIT ? OFFSET ?
            """,
            tuple(params),
        ).fetchall()
    return [WorkoutOut(**row_to_dict(r), sets=[]) for r in rows]


@app.get("/api/workouts/{workout_id}", response_model=WorkoutOut)
def get_workout(workout_id: int, user: UserOut = Depends(require_user)):
    with db() as conn:
        return fetch_workout(conn, workout_id, user.id)


@app.post("/api/workouts", response_model=WorkoutOut)
def create_workout(payload: WorkoutIn, user: UserOut = Depends(require_user)):
    with db() as conn:
        validate_workout_exercises(conn, payload)
        cur = conn.execute(
            """
            INSERT INTO workouts (user_id, workout_date, title, bodyweight_lbs, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user.id, payload.workout_date.isoformat(), payload.title, payload.bodyweight_lbs, payload.notes),
        )
        workout_id = cur.lastrowid
        replace_workout_sets(conn, workout_id, payload.sets)
        workout = fetch_workout(conn, workout_id, user.id)
    invalidate_dashboard_cache(user.id)
    return workout


@app.put("/api/workouts/{workout_id}", response_model=WorkoutOut)
def update_workout(workout_id: int, payload: WorkoutIn, user: UserOut = Depends(require_user)):
    with db() as conn:
        validate_workout_exercises(conn, payload)
        cur = conn.execute(
            """
            UPDATE workouts
            SET workout_date = ?, title = ?, bodyweight_lbs = ?, notes = ?
            WHERE id = ? AND user_id = ?
            """,
            (payload.workout_date.isoformat(), payload.title, payload.bodyweight_lbs, payload.notes, workout_id, user.id),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="workout not found")
        replace_workout_sets(conn, workout_id, payload.sets)
        workout = fetch_workout(conn, workout_id, user.id)
    invalidate_dashboard_cache(user.id)
    return workout


@app.delete("/api/workouts/{workout_id}")
def delete_workout(workout_id: int, user: UserOut = Depends(require_user)):
    with db() as conn:
        cur = conn.execute("DELETE FROM workouts WHERE id = ? AND user_id = ?", (workout_id, user.id))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="workout not found")
    invalidate_dashboard_cache(user.id)
    return {"status": "deleted"}


@app.get("/api/body-measurements", response_model=list[MeasurementOut])
def list_body_measurements(limit: int = Query(default=24, ge=1, le=200), user: UserOut = Depends(require_user)):
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id, measured_date, bodyweight_lbs, waist_in, chest_in, hip_in, arm_in, thigh_in,
                   photo_url, notes, created_at
            FROM body_measurements
            WHERE user_id = ?
            ORDER BY measured_date DESC, id DESC
            LIMIT ?
            """,
            (user.id, limit),
        ).fetchall()
    return [MeasurementOut(**row_to_dict(r)) for r in rows]


@app.post("/api/body-measurements", response_model=MeasurementOut)
def create_body_measurement(payload: MeasurementIn, user: UserOut = Depends(require_user)):
    with db() as conn:
        cur = conn.execute(
            """
            INSERT INTO body_measurements
            (user_id, measured_date, bodyweight_lbs, waist_in, chest_in, hip_in, arm_in, thigh_in, photo_url, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user.id,
                payload.measured_date.isoformat(),
                payload.bodyweight_lbs,
                payload.waist_in,
                payload.chest_in,
                payload.hip_in,
                payload.arm_in,
                payload.thigh_in,
                payload.photo_url,
                payload.notes,
            ),
        )
        row = conn.execute(
            """
            SELECT id, measured_date, bodyweight_lbs, waist_in, chest_in, hip_in, arm_in, thigh_in,
                   photo_url, notes, created_at
            FROM body_measurements
            WHERE id = ? AND user_id = ?
            """,
            (cur.lastrowid, user.id),
        ).fetchone()
    invalidate_dashboard_cache(user.id)
    return MeasurementOut(**row_to_dict(row))


@app.delete("/api/body-measurements/{measurement_id}")
def delete_body_measurement(measurement_id: int, user: UserOut = Depends(require_user)):
    with db() as conn:
        cur = conn.execute("DELETE FROM body_measurements WHERE id = ? AND user_id = ?", (measurement_id, user.id))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="measurement not found")
    invalidate_dashboard_cache(user.id)
    return {"status": "deleted"}


@app.get("/api/goals", response_model=list[GoalOut])
def list_goals(user: UserOut = Depends(require_user)):
    with db() as conn:
        rows = conn.execute(
            """
            SELECT g.id, g.kind, g.exercise_id, e.name AS exercise_name, g.target_value_lbs,
                   g.target_date, g.notes, g.created_at, g.updated_at
            FROM goals g
            LEFT JOIN exercises e ON e.id = g.exercise_id
            WHERE g.user_id = ?
            ORDER BY COALESCE(g.target_date, ?), g.created_at DESC
            """,
            (user.id, GOALS_NO_TARGET_DATE_SORT),
        ).fetchall()
    return [GoalOut(**row_to_dict(r)) for r in rows]


@app.post("/api/goals", response_model=GoalOut)
def create_goal(payload: GoalIn, user: UserOut = Depends(require_user)):
    with db() as conn:
        if payload.exercise_id is not None:
            exists = conn.execute(
                "SELECT 1 FROM exercises WHERE id = ? AND is_archived = 0",
                (payload.exercise_id,),
            ).fetchone()
            if not exists:
                raise HTTPException(status_code=400, detail="exercise not found")
        cur = conn.execute(
            """
            INSERT INTO goals (user_id, kind, exercise_id, target_value_lbs, target_date, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user.id,
                payload.kind,
                payload.exercise_id,
                payload.target_value_lbs,
                payload.target_date.isoformat() if payload.target_date else None,
                payload.notes,
            ),
        )
        row = conn.execute(
            """
            SELECT g.id, g.kind, g.exercise_id, e.name AS exercise_name, g.target_value_lbs,
                   g.target_date, g.notes, g.created_at, g.updated_at
            FROM goals g
            LEFT JOIN exercises e ON e.id = g.exercise_id
            WHERE g.id = ? AND g.user_id = ?
            """,
            (cur.lastrowid, user.id),
        ).fetchone()
    invalidate_dashboard_cache(user.id)
    return GoalOut(**row_to_dict(row))


@app.delete("/api/goals/{goal_id}")
def delete_goal(goal_id: int, user: UserOut = Depends(require_user)):
    with db() as conn:
        cur = conn.execute("DELETE FROM goals WHERE id = ? AND user_id = ?", (goal_id, user.id))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="goal not found")
    invalidate_dashboard_cache(user.id)
    return {"status": "deleted"}


def export_bundle(conn: sqlite3.Connection, user_id: int) -> dict:
    workouts = conn.execute(
        """
        SELECT id, workout_date, title, bodyweight_lbs, notes
        FROM workouts
        WHERE user_id = ?
        ORDER BY workout_date, id
        """,
        (user_id,),
    ).fetchall()
    workout_rows = []
    for workout in workouts:
        sets = conn.execute(
            """
            SELECT e.name AS exercise_name, e.primary_muscle, e.equipment,
                   ws.weight_lbs, COALESCE(ws.weight_mode, 'external') AS weight_mode,
                   ws.reps, ws.rpe, ws.duration_seconds, ws.set_type, ws.group_label,
                   ws.rest_seconds, ws.tempo, ws.notes
            FROM workout_sets ws
            JOIN exercises e ON e.id = ws.exercise_id
            WHERE ws.workout_id = ?
            ORDER BY ws.id
            """,
            (workout["id"],),
        ).fetchall()
        row = row_to_dict(workout)
        row["sets"] = [row_to_dict(s) for s in sets]
        workout_rows.append(row)
    measurements = conn.execute(
        """
        SELECT measured_date, bodyweight_lbs, waist_in, chest_in, hip_in, arm_in, thigh_in, photo_url, notes
        FROM body_measurements
        WHERE user_id = ?
        ORDER BY measured_date, id
        """,
        (user_id,),
    ).fetchall()
    goals = conn.execute(
        """
        SELECT g.kind, e.name AS exercise_name, g.target_value_lbs, g.target_date, g.notes
        FROM goals g
        LEFT JOIN exercises e ON e.id = g.exercise_id
        WHERE g.user_id = ?
        ORDER BY COALESCE(g.target_date, ?), g.id
        """,
        (user_id, GOALS_NO_TARGET_DATE_SORT),
    ).fetchall()
    return {
        "version": 1,
        "workouts": workout_rows,
        "body_measurements": [row_to_dict(r) for r in measurements],
        "goals": [row_to_dict(r) for r in goals],
        "settings": fetch_or_create_settings(conn, user_id).model_dump(),
    }


def exercise_id_for_import(conn: sqlite3.Connection, row: dict) -> int:
    name = str(row.get("exercise_name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="import set missing exercise_name")
    existing = conn.execute("SELECT id FROM exercises WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
    if existing:
        return existing["id"]
    primary_muscle = str(row.get("primary_muscle") or "").strip()
    equipment = str(row.get("equipment") or "").strip()
    if primary_muscle not in MUSCLE_OPTIONS:
        raise HTTPException(status_code=400, detail=f"unsupported import primary_muscle: {primary_muscle or 'missing'}")
    if equipment not in EQUIPMENT_OPTIONS:
        raise HTTPException(status_code=400, detail=f"unsupported import equipment: {equipment or 'missing'}")
    cur = conn.execute(
        """
        INSERT INTO exercises (name, primary_muscle, equipment, secondary_muscles)
        VALUES (?, ?, ?, ?)
        """,
        (
            name,
            primary_muscle,
            equipment,
            "[]",
        ),
    )
    return cur.lastrowid


def optional_exercise_id_for_import(conn: sqlite3.Connection, name: str | None) -> int | None:
    exercise_name = str(name or "").strip()
    if not exercise_name:
        return None
    existing = conn.execute("SELECT id FROM exercises WHERE name = ? COLLATE NOCASE", (exercise_name,)).fetchone()
    if existing:
        return existing["id"]
    raise HTTPException(status_code=400, detail=f"import goal exercise not found: {exercise_name}")


@app.get("/api/export.json")
def export_json(user: UserOut = Depends(require_user)):
    with db() as conn:
        return export_bundle(conn, user.id)


@app.get("/api/export.csv")
def export_csv(user: UserOut = Depends(require_user)):
    with db() as conn:
        bundle = export_bundle(conn, user.id)
    stream = io.StringIO()
    writer = csv.DictWriter(
        stream,
        fieldnames=["workout_date", "title", "bodyweight_lbs", "exercise_name", "set_type", "group_label", "rest_seconds", "tempo", "weight_mode", "weight_lbs", "reps", "duration_seconds", "rpe", "notes"],
    )
    writer.writeheader()
    for workout in bundle["workouts"]:
        for set_row in workout["sets"]:
            writer.writerow({
                "workout_date": workout["workout_date"],
                "title": workout["title"] or "",
                "bodyweight_lbs": workout["bodyweight_lbs"] or "",
                "exercise_name": set_row["exercise_name"],
                "set_type": set_row["set_type"] or "working",
                "group_label": set_row["group_label"] or "",
                "rest_seconds": set_row["rest_seconds"] or "",
                "tempo": set_row["tempo"] or "",
                "weight_mode": set_row["weight_mode"] or "external",
                "weight_lbs": set_row["weight_lbs"],
                "reps": set_row["reps"],
                "duration_seconds": set_row["duration_seconds"] or "",
                "rpe": set_row["rpe"] or "",
                "notes": set_row["notes"] or "",
            })
    return Response(
        stream.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="fitness-export.csv"'},
    )


@app.post("/api/import.json")
def import_json(payload: dict, user: UserOut = Depends(require_user)):
    imported_workouts = 0
    imported_measurements = 0
    imported_goals = 0
    imported_settings = 0
    with db() as conn:
        for workout in payload.get("workouts") or []:
            workout_payload = WorkoutIn(
                workout_date=workout.get("workout_date"),
                title=workout.get("title"),
                bodyweight_lbs=workout.get("bodyweight_lbs"),
                notes=workout.get("notes"),
                sets=[
                    SetIn(
                        exercise_id=exercise_id_for_import(conn, set_row),
                        weight_lbs=set_row.get("weight_lbs"),
                        weight_mode=set_row.get("weight_mode") or "external",
                        reps=set_row.get("reps"),
                        duration_seconds=set_row.get("duration_seconds"),
                        rpe=set_row.get("rpe"),
                        set_type=set_row.get("set_type") or "working",
                        group_label=set_row.get("group_label"),
                        rest_seconds=set_row.get("rest_seconds"),
                        tempo=set_row.get("tempo"),
                        notes=set_row.get("notes"),
                    )
                    for set_row in workout.get("sets") or []
                ],
            )
            validate_workout_exercises(conn, workout_payload)
            cur = conn.execute(
                """
                INSERT INTO workouts (user_id, workout_date, title, bodyweight_lbs, notes)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    user.id,
                    workout_payload.workout_date.isoformat(),
                    workout_payload.title,
                    workout_payload.bodyweight_lbs,
                    workout_payload.notes,
                ),
            )
            replace_workout_sets(conn, cur.lastrowid, workout_payload.sets)
            imported_workouts += 1
        for measurement in payload.get("body_measurements") or []:
            measurement_payload = MeasurementIn(**measurement)
            conn.execute(
                """
                INSERT INTO body_measurements
                (user_id, measured_date, bodyweight_lbs, waist_in, chest_in, hip_in, arm_in, thigh_in, photo_url, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user.id,
                    measurement_payload.measured_date.isoformat(),
                    measurement_payload.bodyweight_lbs,
                    measurement_payload.waist_in,
                    measurement_payload.chest_in,
                    measurement_payload.hip_in,
                    measurement_payload.arm_in,
                    measurement_payload.thigh_in,
                    measurement_payload.photo_url,
                    measurement_payload.notes,
                ),
            )
            imported_measurements += 1
        for goal in payload.get("goals") or []:
            goal_payload = GoalIn(
                kind=goal.get("kind"),
                exercise_id=optional_exercise_id_for_import(conn, goal.get("exercise_name")),
                target_value_lbs=goal.get("target_value_lbs"),
                target_date=goal.get("target_date"),
                notes=goal.get("notes"),
            )
            conn.execute(
                """
                INSERT INTO goals (user_id, kind, exercise_id, target_value_lbs, target_date, notes)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    user.id,
                    goal_payload.kind,
                    goal_payload.exercise_id,
                    goal_payload.target_value_lbs,
                    goal_payload.target_date.isoformat() if goal_payload.target_date else None,
                    goal_payload.notes,
                ),
            )
            imported_goals += 1
        if isinstance(payload.get("settings"), dict):
            settings_payload = SettingsIn(**payload["settings"])
            conn.execute(
                """
                INSERT INTO user_settings (user_id, unit, default_rest_seconds, default_reps, theme, reminder_enabled, reminder_hour, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                  unit = excluded.unit,
                  default_rest_seconds = excluded.default_rest_seconds,
                  default_reps = excluded.default_reps,
                  theme = excluded.theme,
                  reminder_enabled = excluded.reminder_enabled,
                  reminder_hour = excluded.reminder_hour,
                  updated_at = CURRENT_TIMESTAMP
                """,
                (
                    user.id,
                    settings_payload.unit,
                    settings_payload.default_rest_seconds,
                    settings_payload.default_reps,
                    settings_payload.theme,
                    int(settings_payload.reminder_enabled),
                    settings_payload.reminder_hour,
                ),
            )
            imported_settings = 1
    if imported_workouts or imported_measurements or imported_goals:
        invalidate_dashboard_cache(user.id)
    return {"imported_workouts": imported_workouts, "imported_measurements": imported_measurements, "imported_goals": imported_goals, "imported_settings": imported_settings}


@app.get("/api/dashboard")
def dashboard(days: int = Query(default=180, ge=7, le=1825), user: UserOut = Depends(require_user)):
    cached = cached_dashboard(user.id, days)
    if cached is not None:
        return cached
    with db() as conn:
        effective = effective_weight_sql()
        current_e1rm = estimated_1rm_sql(effective, "ws.reps")
        weekly_sets = conn.execute(
            f"""
            SELECT date(w.workout_date, '-' || ((CAST(strftime('%w', w.workout_date) AS INTEGER) + 6) % 7) || ' days') AS week,
                   SUM(CASE WHEN COALESCE(ws.set_type, 'working') != 'warmup' THEN 1 ELSE 0 END) AS sets,
                   COUNT(DISTINCT w.id) AS workouts,
                   ROUND(SUM(CASE WHEN COALESCE(ws.set_type, 'working') != 'warmup' THEN ({effective}) * ws.reps ELSE 0 END), 1) AS volume_lbs
            FROM workouts w
            JOIN workout_sets ws ON ws.workout_id = w.id
            WHERE w.user_id = ?
              AND w.workout_date >= date('now', ?)
            GROUP BY week
            ORDER BY week
            """,
            (user.id, f"-{days} days"),
        ).fetchall()

        volume_by_muscle = conn.execute(
            f"""
            SELECT date(w.workout_date, '-' || ((CAST(strftime('%w', w.workout_date) AS INTEGER) + 6) % 7) || ' days') AS week,
                   e.primary_muscle,
                   e.secondary_muscles,
                   ROUND(SUM(CASE WHEN COALESCE(ws.set_type, 'working') != 'warmup' THEN ({effective}) * ws.reps ELSE 0 END), 1) AS volume_lbs,
                   SUM(CASE WHEN COALESCE(ws.set_type, 'working') != 'warmup' THEN 1 ELSE 0 END) AS sets
            FROM workouts w
            JOIN workout_sets ws ON ws.workout_id = w.id
            JOIN exercises e ON e.id = ws.exercise_id
            WHERE w.user_id = ?
              AND w.workout_date >= date('now', ?)
            GROUP BY week, e.id
            ORDER BY week, e.primary_muscle
            """,
            (user.id, f"-{days} days"),
        ).fetchall()

        prs = conn.execute(
            f"""
            WITH ranked_prs AS (
                SELECT e.id AS exercise_id, e.name AS exercise_name, e.primary_muscle,
                       w.workout_date, ws.weight_lbs, COALESCE(ws.weight_mode, 'external') AS weight_mode,
                       ROUND({effective}, 1) AS effective_weight_lbs,
                       ws.reps, ws.id AS set_id,
                       ROUND({current_e1rm}, 1) AS estimated_1rm,
                       ROW_NUMBER() OVER (
                           PARTITION BY ws.exercise_id
                           ORDER BY {current_e1rm} DESC, w.workout_date ASC, ws.id ASC
                       ) AS pr_rank
                FROM workout_sets ws
                JOIN workouts w ON w.id = ws.workout_id
                JOIN exercises e ON e.id = ws.exercise_id
                WHERE w.user_id = ?
                  AND ({effective}) > 0
                  AND COALESCE(ws.set_type, 'working') != 'warmup'
              )
            SELECT exercise_id, exercise_name, primary_muscle, workout_date, weight_lbs, weight_mode, effective_weight_lbs, reps, estimated_1rm
            FROM ranked_prs
            WHERE pr_rank = 1
            ORDER BY workout_date DESC, estimated_1rm DESC, set_id DESC
            LIMIT ?
            """,
            (user.id, DASHBOARD_PR_LIMIT),
        ).fetchall()

        recent_exercises = conn.execute(
            """
            SELECT e.id, e.name, e.primary_muscle, COUNT(ws.id) AS set_count,
                   MAX(w.workout_date) AS last_trained
            FROM exercises e
            JOIN workout_sets ws ON ws.exercise_id = e.id
            JOIN workouts w ON w.id = ws.workout_id
            WHERE w.user_id = ?
            GROUP BY e.id
            ORDER BY last_trained DESC, set_count DESC
            LIMIT ?
            """,
            (user.id, RECENT_EXERCISE_LIMIT),
        ).fetchall()
        training_days = conn.execute(
            """
            SELECT workout_date, COUNT(*) AS workouts
            FROM workouts
            WHERE user_id = ?
              AND workout_date >= date('now', ?)
            GROUP BY workout_date
            ORDER BY workout_date
            """,
            (user.id, f"-{days} days"),
        ).fetchall()
        goals = conn.execute(
            """
            SELECT g.id, g.kind, g.exercise_id, e.name AS exercise_name, g.target_value_lbs,
                   g.target_date, g.notes, g.created_at, g.updated_at
            FROM goals g
            LEFT JOIN exercises e ON e.id = g.exercise_id
            WHERE g.user_id = ?
            ORDER BY COALESCE(g.target_date, ?), g.created_at DESC
            """,
            (user.id, GOALS_NO_TARGET_DATE_SORT),
        ).fetchall()
        goal_e1rms = conn.execute(
            f"""
            SELECT ws.exercise_id, ROUND(MAX({current_e1rm}), 1) AS current_value_lbs
            FROM workout_sets ws
            JOIN workouts w ON w.id = ws.workout_id
            WHERE w.user_id = ?
              AND ({effective}) > 0
              AND COALESCE(ws.set_type, 'working') != 'warmup'
            GROUP BY ws.exercise_id
            """,
            (user.id,),
        ).fetchall()
        latest_bodyweight = conn.execute(
            """
            SELECT bodyweight_lbs
            FROM body_measurements
            WHERE user_id = ? AND bodyweight_lbs IS NOT NULL
            ORDER BY measured_date DESC, id DESC
            LIMIT 1
            """,
            (user.id,),
        ).fetchone()

    weekly = []
    for row in weekly_sets:
        item = row_to_dict(row)
        item["week_start"] = item["week"]
        item["week_end"] = date.fromisoformat(item["week_start"]).fromordinal(date.fromisoformat(item["week_start"]).toordinal() + 6).isoformat()
        item["week_label"] = format_week_label(item["week_start"])
        weekly.append(item)
    muscle_volume_index = {}
    def add_muscle_volume(week: str, muscle: str, role: str, volume_lbs: float, sets: int):
        if not muscle:
            return
        key = (week, muscle, role)
        if key not in muscle_volume_index:
            muscle_volume_index[key] = {"week": week, "muscle": muscle, "role": role, "volume_lbs": 0.0, "sets": 0}
        muscle_volume_index[key]["volume_lbs"] += volume_lbs or 0
        muscle_volume_index[key]["sets"] += sets or 0

    for row in volume_by_muscle:
        item = row_to_dict(row)
        volume_lbs = item["volume_lbs"] or 0
        sets = item["sets"] or 0
        add_muscle_volume(item["week"], item["primary_muscle"], "primary", volume_lbs, sets)
        try:
            secondary_muscles = json.loads(item.get("secondary_muscles") or "[]")
        except json.JSONDecodeError:
            secondary_muscles = []
        for muscle in secondary_muscles:
            if muscle == item["primary_muscle"]:
                continue
            add_muscle_volume(item["week"], muscle, secondary_muscle_volume_role(muscle), volume_lbs, sets)
    muscle_volume = []
    for item in sorted(
        muscle_volume_index.values(),
        key=lambda row: (row["week"], MUSCLE_VOLUME_ROLE_ORDER.get(row["role"], 99), MUSCLE_OPTION_ORDER.index(row["muscle"]) if row["muscle"] in MUSCLE_OPTIONS else 99, row["muscle"]),
    ):
        item["volume_lbs"] = round(item["volume_lbs"], 1)
        item["week_start"] = item["week"]
        item["week_label"] = format_week_label(item["week_start"])
        muscle_volume.append(item)
    training_day_rows = [row_to_dict(r) for r in training_days]
    training_day_set = {row["workout_date"] for row in training_day_rows}
    e1rm_by_exercise = {row["exercise_id"]: row["current_value_lbs"] for row in goal_e1rms}
    latest_bodyweight_lbs = latest_bodyweight["bodyweight_lbs"] if latest_bodyweight else None
    active_goals = []
    for row in goals:
        item = row_to_dict(row)
        current_value = latest_bodyweight_lbs if item["kind"] == "bodyweight" else e1rm_by_exercise.get(item["exercise_id"])
        delta = None if current_value is None else round(item["target_value_lbs"] - current_value, 1)
        item["current_value_lbs"] = current_value
        item["delta_lbs"] = delta
        if current_value is None:
            item["status"] = "pending"
        elif item["kind"] == "bodyweight":
            item["status"] = "met" if abs(delta) <= 0.5 else "tracking"
        else:
            item["status"] = "met" if delta <= 0 else "tracking"
        active_goals.append(item)

    return store_dashboard_cache(user.id, days, {
        "weekly": weekly,
        "volume_by_muscle": muscle_volume,
        "prs": [row_to_dict(r) for r in prs],
        "recent_exercises": [row_to_dict(r) for r in recent_exercises],
        "training_days": training_day_rows,
        "current_streak_days": current_streak_days(training_day_set),
        "muscle_targets": weekly_muscle_targets([row for row in muscle_volume if row["role"] == "primary"]),
        "active_goals": active_goals,
    })


@app.get("/api/exercises/{exercise_id}/progression")
def exercise_progression(exercise_id: int, user: UserOut = Depends(require_user)):
    with db() as conn:
        exercise = conn.execute("SELECT * FROM exercises WHERE id = ?", (exercise_id,)).fetchone()
        if not exercise:
            raise HTTPException(status_code=404, detail="exercise not found")
        effective = effective_weight_sql()
        current_e1rm = estimated_1rm_sql(effective, "ws.reps")
        rows = conn.execute(
            f"""
            SELECT w.workout_date,
                   MAX(ws.weight_lbs) AS max_weight_lbs,
                   MAX(ws.reps) AS max_reps,
                   ROUND(AVG(ws.rpe), 1) AS average_rpe,
                   ROUND(MAX({current_e1rm}), 1) AS best_estimated_1rm,
                   ROUND(SUM(CASE WHEN COALESCE(ws.set_type, 'working') != 'warmup' THEN ({effective}) * ws.reps ELSE 0 END), 1) AS volume_lbs,
                   COUNT(ws.id) AS sets
            FROM workout_sets ws
            JOIN workouts w ON w.id = ws.workout_id
            WHERE ws.exercise_id = ?
              AND w.user_id = ?
              AND COALESCE(ws.set_type, 'working') != 'warmup'
            GROUP BY w.id
            ORDER BY w.workout_date
            """,
            (exercise_id, user.id),
        ).fetchall()
        stats = conn.execute(
            f"""
            SELECT ROUND(MAX({current_e1rm}), 1) AS best_estimated_1rm,
                   MAX(ws.weight_lbs) AS max_weight_lbs,
                   MAX(ws.reps) AS max_reps,
                   ROUND(AVG(ws.rpe), 1) AS average_rpe,
                   ROUND(SUM(CASE WHEN COALESCE(ws.set_type, 'working') != 'warmup' THEN ({effective}) * ws.reps ELSE 0 END), 1) AS total_volume_lbs,
                   COUNT(ws.id) AS total_sets,
                   COUNT(DISTINCT w.id) AS workout_count,
                   MAX(w.workout_date) AS last_trained
            FROM workout_sets ws
            JOIN workouts w ON w.id = ws.workout_id
            WHERE ws.exercise_id = ?
              AND w.user_id = ?
              AND COALESCE(ws.set_type, 'working') != 'warmup'
            """,
            (exercise_id, user.id),
        ).fetchone()
        bodyweight = conn.execute(
            """
            SELECT measured_date, bodyweight_lbs
            FROM (
                SELECT measured_date, bodyweight_lbs, 0 AS source_order
                FROM body_measurements
                WHERE user_id = ?
                  AND bodyweight_lbs IS NOT NULL
                UNION ALL
                SELECT workout_date AS measured_date, bodyweight_lbs, 1 AS source_order
                FROM workouts
                WHERE user_id = ?
                  AND bodyweight_lbs IS NOT NULL
            )
            ORDER BY measured_date DESC, source_order ASC
            LIMIT 1
            """,
            (user.id, user.id),
        ).fetchone()
    stats_dict = row_to_dict(stats)
    latest_bodyweight = bodyweight["bodyweight_lbs"] if bodyweight else None
    best_e1rm = stats_dict.get("best_estimated_1rm")
    ratio = round(best_e1rm / latest_bodyweight, 2) if best_e1rm and latest_bodyweight else None
    stats_dict.update(
        {
            "latest_bodyweight_lbs": latest_bodyweight,
            "latest_bodyweight_date": bodyweight["measured_date"] if bodyweight else None,
            "bodyweight_ratio": ratio,
            "strength_standard": strength_standard_label(exercise["name"], ratio),
        }
    )
    return {
        "exercise": exercise_from_row(exercise).model_dump(),
        "points": [row_to_dict(r) for r in rows],
        "stats": stats_dict,
    }


@app.get("/api/exercises/{exercise_id}/history")
def exercise_history(exercise_id: int, limit: int = Query(default=200, ge=1, le=1000), user: UserOut = Depends(require_user)):
    with db() as conn:
        if not conn.execute("SELECT id FROM exercises WHERE id = ?", (exercise_id,)).fetchone():
            raise HTTPException(status_code=404, detail="exercise not found")
        rows = conn.execute(
            """
            SELECT w.id AS workout_id, w.workout_date, w.title, w.bodyweight_lbs,
                   ws.id AS set_id, ws.set_number, ws.weight_lbs,
                   COALESCE(ws.weight_mode, 'external') AS weight_mode,
                   ws.reps, ws.rpe, ws.duration_seconds, COALESCE(ws.set_type, 'working') AS set_type,
                   ws.group_label, ws.rest_seconds, ws.tempo, ws.notes
            FROM workout_sets ws
            JOIN workouts w ON w.id = ws.workout_id
            WHERE ws.exercise_id = ?
              AND w.user_id = ?
            ORDER BY w.workout_date DESC, w.id DESC, ws.id DESC
            LIMIT ?
            """,
            (exercise_id, user.id, limit),
        ).fetchall()
    history = []
    for row in rows:
        item = row_to_dict(row)
        item["effective_weight_lbs"] = effective_weight(item["weight_lbs"], item["weight_mode"], item["bodyweight_lbs"])
        item["volume_lbs"] = volume(item["effective_weight_lbs"], item["reps"])
        item["estimated_1rm"] = estimate_1rm(item["effective_weight_lbs"], item["reps"])
        history.append(item)
    return history


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)


@app.get("/service-worker.js", include_in_schema=False)
def service_worker() -> FileResponse:
    path = FRONTEND_DIST / "service-worker.js"
    response = FileResponse(path, media_type="application/javascript")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Service-Worker-Allowed"] = "/"
    return response


if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
