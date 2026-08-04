import React, { useEffect, useId, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Activity,
  ArrowLeft,
  BarChart3,
  CalendarDays,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  Copy,
  Dumbbell,
  HelpCircle,
  History,
  KeyRound,
  ListChecks,
  LogOut,
  Play,
  Plus,
  RefreshCw,
  Save,
  Search,
  Shield,
  StickyNote,
  Target,
  Trash2,
  Trophy,
  UserPlus,
  X,
} from 'lucide-react';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { API, api } from './apiClient.js';
import { parseBulkSetEntry } from './bulkSetLogic.js';
import { normalizeWorkoutDraftValue } from './draftLogic.js';
import './styles.css';

const WORKOUT_DRAFTS_KEY = 'fitnessWorkoutDrafts:v2';
const ACTIVE_WORKOUT_DRAFT_KEY = 'fitnessWorkoutActiveDraft:v1';
const WORKOUT_TEMPLATES_KEY = 'fitnessWorkoutTemplates:v1';
const UNIT_PREF_KEY = 'fitnessUnits:v1';
const DRAFT_LIMIT = 12;
const DRAFT_AUTOSAVE_DELAY_MS = 600;
const WORKOUT_PAGE_SIZE = 12;
const DEFAULT_REST_SECONDS = 120;
const DEFAULT_REPS = 8;
const PRIORITY_EXERCISE_LIMIT = 8;
const DASHBOARD_PR_DISPLAY_LIMIT = 12;
const PROGRESSION_POINT_DISPLAY_LIMIT = 12;
const MEASUREMENT_DISPLAY_LIMIT = 8;
const PICKER_PAGE_SIZE = 12;
const REST_PRESETS_SECONDS = [60, 120, 180];
const PIN_PATTERN = /^[0-9]{6,12}$/;
const KG_PER_LB = 0.45359237;
const E1RM_REP_DIVISOR = 30;
const MUSCLES = ['Chest', 'Back', 'Shoulders', 'Quads', 'Hamstrings', 'Glutes', 'Calves', 'Biceps', 'Triceps', 'Abs', 'Core', 'Adductors', 'Abductors', 'Forearms', 'Lower Back', 'Traps', 'Obliques'];
const MUSCLE_OPTION_LABELS = {
  Abs: 'Abs (trunk flexion)',
  Core: 'Core (bracing/stability)',
  Obliques: 'Obliques (rotation/side bend)',
};
const MUSCLE_HINTS = {
  Abs: 'Abs: rectus-abdominis and trunk-flexion work such as crunches and leg raises.',
  Core: 'Core: bracing, anti-rotation, carries, and stability drills such as planks and Pallof presses.',
  Obliques: 'Obliques: rotation and side-bend work such as wood choppers and side bends.',
};
const FOCUSABLE_SELECTOR = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
const EQUIPMENT = ['Barbell', 'Dumbbells', 'Cables', 'Machine', 'Bodyweight', 'Kettlebell', 'Bands', 'EZ Bar', 'Trap Bar', 'Smith Machine'];
const EMPTY_DASHBOARD = { weekly: [], volume_by_muscle: [], prs: [], recent_exercises: [], training_days: [], current_streak_days: 0, muscle_targets: [] };
const WORKOUT_TITLE_PRESETS = ['Push', 'Pull', 'Legs', 'Upper', 'Lower', 'Chest & Back'];
const REP_PRESETS = ['6', '8', '10', '12', '15'];
const SET_TYPES = [
  ['working', 'Working'],
  ['warmup', 'Warm-up'],
  ['drop', 'Drop'],
  ['failure', 'Failure'],
  ['amrap', 'AMRAP'],
];
const WEIGHT_MODES = [
  ['external', 'External load'],
  ['bodyweight', 'Bodyweight'],
  ['added', 'Bodyweight + added'],
  ['assisted', 'Bodyweight - assist'],
];
const CHART_COLORS = {
  grid: 'var(--chart-grid)',
  axis: 'var(--chart-axis)',
  panel: 'var(--chart-panel)',
  border: 'var(--chart-border)',
  primary: '#0f9f96',
  secondary: '#e97612',
  weeklySets: '#479f3d',
  weeklySetsFill: '#479f3d33',
  weeklyWorkouts: '#e97612',
  weeklyWorkoutsFill: '#e9761230',
  musclePalette: ['#4fd1c5', '#f6ad55', '#8bdb81', '#fc8181', '#90cdf4', '#d6bcfa', '#f687b3', '#fbd38d', '#68d391', '#b794f4'],
};
const CHART_TOOLTIP_STYLE = { background: CHART_COLORS.panel, border: `1px solid ${CHART_COLORS.border}` };
const CHART_AXIS_LABEL_STYLE = { fill: CHART_COLORS.axis };
const MUSCLE_VOLUME_ROLES = [
  ['all', 'All'],
  ['primary', 'Primary'],
  ['secondary', 'Secondary'],
  ['stabilizer', 'Stabilizer'],
];
const VALID_ROUTES = new Set(['home', 'start-workout', 'edit-workout']);

function formatLocalDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function today() {
  return formatLocalDate(new Date());
}

function daysAgo(days) {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return formatLocalDate(date);
}

function weekKey(date = new Date()) {
  const todayAtMidnight = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const monday = new Date(todayAtMidnight);
  const mondayOffset = (todayAtMidnight.getDay() + 6) % 7;
  monday.setDate(todayAtMidnight.getDate() - mondayOffset);
  return `${monday.getFullYear()}-${String(monday.getMonth() + 1).padStart(2, '0')}-${String(monday.getDate()).padStart(2, '0')}`;
}

function formatLastPerformed(row, unit) {
  if (!row?.sets?.length) return '';
  const sets = row.sets
    .slice(0, 4)
    .map((set) => `${formatWeight(set.effective_weight_lbs ?? set.weight_lbs, unit)} x ${set.reps}`)
    .join(', ');
  return `${row.workout_date}: ${sets}`;
}

function sortUsers(rows) {
  return [...rows].sort((a, b) => {
    if (a.role !== b.role) return a.role === 'admin' ? -1 : 1;
    return a.display_name.localeCompare(b.display_name, undefined, { sensitivity: 'base' });
  });
}

function numberOrZero(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function readUnitPreference() {
  try {
    return window.localStorage.getItem(UNIT_PREF_KEY) === 'kg' ? 'kg' : 'lb';
  } catch {
    return 'lb';
  }
}

function persistUnitPreference(unit) {
  try {
    window.localStorage.setItem(UNIT_PREF_KEY, unit);
  } catch {
    // Storage may be disabled.
  }
}

function toDisplayWeight(value, unit) {
  if (value === '' || value === null || value === undefined) return '';
  const pounds = Number(value);
  if (!Number.isFinite(pounds)) return '';
  const display = unit === 'kg' ? pounds * KG_PER_LB : pounds;
  return Number(display.toFixed(1)).toString();
}

function fromDisplayWeight(value, unit) {
  if (typeof value === 'string' && value.trim() === '') return '';
  if (value === '' || value === null || value === undefined) return '';
  const display = Number(value);
  if (!Number.isFinite(display)) return value;
  const pounds = unit === 'kg' ? display / KG_PER_LB : display;
  return Number(pounds.toFixed(1)).toString();
}

function formatWeight(value, unit) {
  const display = toDisplayWeight(value, unit);
  if (display === '') return '-';
  return `${Number(display).toLocaleString(undefined, { maximumFractionDigits: 1 })} ${unit}`;
}

function estimateOneRepMax(weight, reps) {
  const numericWeight = Number(weight);
  const numericReps = Number(reps);
  if (!Number.isFinite(numericWeight) || !Number.isFinite(numericReps) || numericWeight <= 0 || numericReps <= 0) return null;
  if (numericReps <= 1) return numericWeight;
  return numericWeight * (1 + numericReps / E1RM_REP_DIVISOR);
}

function effectiveSetWeight(set, workoutBodyweight = '') {
  const load = Number(set.weight_lbs || 0);
  const bodyweight = Number(workoutBodyweight || 0);
  if (set.weight_mode === 'bodyweight') return bodyweight;
  if (set.weight_mode === 'added') return bodyweight + load;
  if (set.weight_mode === 'assisted') return Math.max(bodyweight - load, 0);
  return load;
}

function formatBodyweightRatio(value) {
  const ratio = Number(value);
  if (!Number.isFinite(ratio)) return '-';
  return `${ratio.toFixed(2)}x`;
}

function muscleOptionLabel(muscle) {
  return MUSCLE_OPTION_LABELS[muscle] || muscle;
}

function toggleMuscleSelection(values = [], muscle) {
  return values.includes(muscle) ? values.filter((value) => value !== muscle) : [...values, muscle].slice(0, 6);
}

function parseAliases(value) {
  const seen = new Set();
  return value
    .split(',')
    .map((alias) => alias.trim())
    .filter((alias) => {
      const key = alias.toLowerCase();
      if (!alias || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
}

function formatAliases(aliases = []) {
  return aliases.join(', ');
}

function SkipLink() {
  return <a className="skip-link" href="#main-content">Skip to content</a>;
}

function scrollElementIntoView(element, options) {
  const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  element?.scrollIntoView({ ...options, behavior: reduced ? 'auto' : options?.behavior });
}

function useModalDialog(onClose) {
  const dialogRef = useRef(null);
  const previousFocusRef = useRef(null);

  useEffect(() => {
    previousFocusRef.current = document.activeElement;
    const dialog = dialogRef.current;
    const focusable = dialog ? Array.from(dialog.querySelectorAll(FOCUSABLE_SELECTOR)) : [];
    (focusable[0] || dialog)?.focus();

    function handleKeyDown(event) {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== 'Tab' || !dialog) return;
      const items = Array.from(dialog.querySelectorAll(FOCUSABLE_SELECTOR));
      if (!items.length) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      previousFocusRef.current?.focus?.();
    };
  }, [onClose]);

  function closeOnBackdrop(event) {
    if (event.target === event.currentTarget) onClose();
  }

  return { dialogRef, closeOnBackdrop };
}

function platePlan(targetDisplay, unit) {
  const target = Number(targetDisplay);
  if (!Number.isFinite(target) || target <= 0) return null;
  const bar = unit === 'kg' ? 20 : 45;
  const plates = unit === 'kg' ? [25, 20, 15, 10, 5, 2.5, 1.25] : [45, 35, 25, 10, 5, 2.5];
  let remaining = (target - bar) / 2;
  if (remaining < 0) return { bar, plates: [], remainder: remaining };
  const result = [];
  for (const plate of plates) {
    let count = 0;
    while (remaining + 0.001 >= plate) {
      count += 1;
      remaining = Number((remaining - plate).toFixed(3));
    }
    if (count) result.push({ plate, count });
  }
  return { bar, plates: result, remainder: Number(remaining.toFixed(2)) };
}

function announceRestComplete() {
  try {
    navigator.vibrate?.([220, 120, 220]);
  } catch {
    // Optional device support.
  }
  try {
    if (window.Notification?.permission === 'granted') {
      new Notification('Rest complete', { body: 'Next set is ready.', icon: '/icon.svg' });
    }
  } catch {
    // Browser may block notifications.
  }
  try {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext) return;
    const context = new AudioContext();
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.type = 'sine';
    oscillator.frequency.value = 880;
    gain.gain.value = 0.08;
    oscillator.connect(gain);
    gain.connect(context.destination);
    oscillator.start();
    oscillator.stop(context.currentTime + 0.25);
  } catch {
    // Audio cues are best-effort.
  }
}

function parseWorkoutSetNumber(value, label, { integer = false, min = 0, max = 10000 } = {}) {
  const normalized = typeof value === 'string' ? value.trim() : value;
  if (normalized === '' || normalized === null || normalized === undefined) throw new Error(`${label} is required.`);
  const number = Number(normalized);
  if (!Number.isFinite(number)) throw new Error(`${label} must be a number.`);
  if (integer && !Number.isInteger(number)) throw new Error(`${label} must be a whole number.`);
  if (number < min || number > max) throw new Error(`${label} must be between ${min} and ${max}.`);
  return number;
}

function parseOptionalNumber(value, label, options) {
  if ((typeof value === 'string' && value.trim() === '') || value === '' || value === null || value === undefined) return null;
  return parseWorkoutSetNumber(value, label, options);
}

function createDraftId() {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID();
  return `draft-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function createSetId() {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID();
  return `set-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function blankSet(overrides = {}) {
  return { client_id: createSetId(), exercise_id: '', weight_lbs: '', weight_mode: 'external', reps: '', notes: '', ...overrides };
}

function defaultWorkout() {
  return {
    workout_date: today(),
    title: '',
    bodyweight_lbs: '',
    notes: '',
    sets: [blankSet()],
  };
}

function defaultMeasurement() {
  return {
    measured_date: today(),
    bodyweight_lbs: '',
    waist_in: '',
    chest_in: '',
    hip_in: '',
    arm_in: '',
    thigh_in: '',
    photo_url: '',
    notes: '',
  };
}

function defaultGoal() {
  return {
    kind: 'one_rep_max',
    exercise_id: '',
    target_value_lbs: '',
    target_date: '',
    notes: '',
  };
}

function defaultSettings() {
  return {
    unit: 'lb',
    default_rest_seconds: DEFAULT_REST_SECONDS,
    default_reps: DEFAULT_REPS,
    theme: 'system',
    reminder_enabled: false,
    reminder_hour: 18,
  };
}

function workoutFromDetail(detail) {
  return normalizeWorkoutDraft({
    workout_date: detail?.workout_date,
    title: detail?.title || '',
    bodyweight_lbs: detail?.bodyweight_lbs === null || detail?.bodyweight_lbs === undefined ? '' : String(detail.bodyweight_lbs),
    notes: detail?.notes || '',
    sets: Array.isArray(detail?.sets) && detail.sets.length
      ? detail.sets.map((set) => ({
          client_id: createSetId(),
          exercise_id: String(set.exercise_id || ''),
          weight_lbs: set.weight_lbs === null || set.weight_lbs === undefined ? '' : String(set.weight_lbs),
          weight_mode: set.weight_mode || 'external',
          reps: set.reps === null || set.reps === undefined ? '' : String(set.reps),
          notes: set.notes || '',
        }))
      : defaultWorkout().sets,
  });
}

function normalizeWorkoutDraft(value) {
  const base = defaultWorkout();
  return normalizeWorkoutDraftValue(value, base, createSetId);
}

function countCompleteSets(workout) {
  return (workout.sets || []).filter((set) => set.exercise_id && (set.weight_mode === 'bodyweight' || set.weight_lbs !== '') && set.reps !== '').length;
}

function missingSetFields(set) {
  return [
    !set.exercise_id ? 'exercise' : '',
    set.weight_mode !== 'bodyweight' && set.weight_lbs === '' ? 'weight' : '',
    set.reps === '' ? 'reps' : '',
  ].filter(Boolean);
}

function describeWorkoutDraft(workout) {
  const title = workout.title?.trim();
  if (title) return title;
  const completeSets = countCompleteSets(workout);
  if (completeSets) return `${completeSets} complete ${completeSets === 1 ? 'set' : 'sets'}`;
  return 'Untitled workout';
}

function formatDraftSavedAt(value) {
  if (!value) return 'Draft ready';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Draft saved';
  return `Draft saved ${date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`;
}

function normalizeDraftRecord(value) {
  if (!value || typeof value !== 'object') return null;
  const workout = normalizeWorkoutDraft(value.workout || value);
  if (isEmptyWorkoutDraft(workout)) return null;
  const now = new Date().toISOString();
  return {
    id: value.id || createDraftId(),
    created_at: value.created_at || now,
    updated_at: value.updated_at || now,
    workout,
  };
}

function scopedStorageKey(baseKey, userId) {
  return userId ? `${baseKey}:user:${userId}` : baseKey;
}

function readStoredDrafts(userId = '') {
  try {
    const raw = window.localStorage.getItem(scopedStorageKey(WORKOUT_DRAFTS_KEY, userId));
    const parsed = raw ? JSON.parse(raw) : [];
    const rows = Array.isArray(parsed) ? parsed.map(normalizeDraftRecord).filter(Boolean) : [];
    if (rows.length) return rows.sort((a, b) => b.updated_at.localeCompare(a.updated_at)).slice(0, DRAFT_LIMIT);
  } catch {
    return [];
  }
  return [];
}

function persistDrafts(drafts, activeDraftId = '', userId = '') {
  try {
    window.localStorage.setItem(scopedStorageKey(WORKOUT_DRAFTS_KEY, userId), JSON.stringify(drafts));
    if (activeDraftId) {
      window.localStorage.setItem(scopedStorageKey(ACTIVE_WORKOUT_DRAFT_KEY, userId), activeDraftId);
    } else {
      window.localStorage.removeItem(scopedStorageKey(ACTIVE_WORKOUT_DRAFT_KEY, userId));
    }
  } catch {
    // Storage may be disabled; normal in-memory editing still works.
  }
}

function loadDraftState(userId = '') {
  const drafts = userId ? readStoredDrafts(userId) : [];
  let activeDraftId = '';
  try {
    activeDraftId = userId ? window.localStorage.getItem(scopedStorageKey(ACTIVE_WORKOUT_DRAFT_KEY, userId)) || '' : '';
  } catch {
    activeDraftId = '';
  }
  const active = drafts.find((draft) => draft.id === activeDraftId) || drafts[0];
  return {
    drafts,
    activeDraftId: active?.id || '',
    workout: active?.workout || defaultWorkout(),
  };
}

function readStoredTemplates(userId = '') {
  if (!userId) return [];
  try {
    const raw = window.localStorage.getItem(scopedStorageKey(WORKOUT_TEMPLATES_KEY, userId));
    const rows = raw ? JSON.parse(raw) : [];
    return Array.isArray(rows) ? rows.map(normalizeDraftRecord).filter(Boolean).slice(0, 20) : [];
  } catch {
    return [];
  }
}

function persistTemplates(templates, userId = '') {
  if (!userId) return;
  try {
    window.localStorage.setItem(scopedStorageKey(WORKOUT_TEMPLATES_KEY, userId), JSON.stringify(templates.slice(0, 20)));
  } catch {
    // Storage may be disabled.
  }
}

function clearWorkoutDraft(userId = '') {
  try {
    window.localStorage.removeItem(scopedStorageKey(ACTIVE_WORKOUT_DRAFT_KEY, userId));
    window.localStorage.removeItem(scopedStorageKey(WORKOUT_DRAFTS_KEY, userId));
    window.localStorage.removeItem(ACTIVE_WORKOUT_DRAFT_KEY);
  } catch {
    // Ignore storage failures.
  }
}

function currentRoute() {
  const route = window.location.hash.replace(/^#\/?/, '') || 'home';
  const normalized = route === 'quick-log' ? 'start-workout' : route;
  return VALID_ROUTES.has(normalized) ? normalized : 'not-found';
}

function isEmptyWorkoutDraft(workout) {
  const sets = workout.sets || [];
  const onlyEmptySet = sets.length === 1 && ['exercise_id', 'weight_lbs', 'reps', 'notes'].every((key) => !sets[0]?.[key]);
  return !workout.title && !workout.bodyweight_lbs && !workout.notes && onlyEmptySet;
}

function App() {
  const initialDraftState = useMemo(loadDraftState, []);
  const [auth, setAuth] = useState({ loading: true, setup_required: false, user: null });
  const [exercises, setExercises] = useState([]);
  const [workouts, setWorkouts] = useState([]);
  const [workoutSearch, setWorkoutSearch] = useState('');
  const [workoutHasMore, setWorkoutHasMore] = useState(false);
  const [workoutPageLoading, setWorkoutPageLoading] = useState(false);
  const [measurements, setMeasurements] = useState([]);
  const [dashboard, setDashboard] = useState(EMPTY_DASHBOARD);
  const [lastPerformed, setLastPerformed] = useState({});
  const [users, setUsers] = useState([]);
  const [selectedExerciseId, setSelectedExerciseId] = useState('');
  const [muscleVolumeRole, setMuscleVolumeRole] = useState('all');
  const [progression, setProgression] = useState(null);
  const [exerciseHistory, setExerciseHistory] = useState([]);
  const [errorState, setErrorState] = useState({ message: '', scope: 'global' });
  const [pinMessage, setPinMessage] = useState('');
  const [workoutMessage, setWorkoutMessage] = useState('');
  const [undoAction, setUndoAction] = useState(null);
  const [showPinForm, setShowPinForm] = useState(false);
  const [showDrafts, setShowDrafts] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [selectedWorkout, setSelectedWorkout] = useState(null);
  const [workoutDetailLoading, setWorkoutDetailLoading] = useState(false);
  const [editingWorkoutId, setEditingWorkoutId] = useState('');
  const [deletingWorkoutId, setDeletingWorkoutId] = useState('');
  const [dataLoading, setDataLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [pinSaving, setPinSaving] = useState(false);
  const [resetSavingUserId, setResetSavingUserId] = useState('');
  const [drafts, setDrafts] = useState(initialDraftState.drafts);
  const [templates, setTemplates] = useState([]);
  const [activeDraftId, setActiveDraftId] = useState(initialDraftState.activeDraftId);
  const [workout, setWorkout] = useState(initialDraftState.workout);
  const [unit, setUnit] = useState(readUnitPreference);
  const [restSeconds, setRestSeconds] = useState(DEFAULT_REST_SECONDS);
  const [restRemaining, setRestRemaining] = useState(0);
  const [restTargetAt, setRestTargetAt] = useState(0);
  const restAnnounceRef = useRef(false);
  const [route, setRoute] = useState(currentRoute);
  const [goalForm, setGoalForm] = useState(defaultGoal);
  const [settingsForm, setSettingsForm] = useState(defaultSettings);
  const [newExercise, setNewExercise] = useState({
    name: '',
    primary_muscle: 'Chest',
    equipment: 'Dumbbells',
    secondary_muscles: [],
    alias_text: '',
    notes: '',
  });
  const [measurementForm, setMeasurementForm] = useState(defaultMeasurement);
  const [newUser, setNewUser] = useState({
    username: '',
    display_name: '',
    pin: '',
    role: 'user',
  });
  const [pinForm, setPinForm] = useState({
    current_pin: '',
    new_pin: '',
    confirm_pin: '',
  });
  const [resetPins, setResetPins] = useState({});
  const [userEdits, setUserEdits] = useState({});
  const [draftCapNotice, setDraftCapNotice] = useState('');
  const draftPersistTimerRef = useRef(null);
  const error = errorState.message && (errorState.scope === 'global' || errorState.scope === route) ? errorState.message : '';

  function setError(message, scope = route) {
    setErrorState(message ? { message, scope } : { message: '', scope });
  }

  async function refreshAuth() {
    const state = await api('/auth/me');
    setAuth({ loading: false, setup_required: state.setup_required, user: state.user });
    return state;
  }

  async function load(options = {}) {
    const includeExercises = options.includeExercises !== false;
    setDataLoading(true);
    try {
      const entries = [
        ['workouts', api(`/workouts?limit=${WORKOUT_PAGE_SIZE}&offset=0&q=${encodeURIComponent(workoutSearch)}`)],
        ['dashboard', api('/dashboard?days=365')],
        ['lastPerformed', api('/exercises/last-performed')],
        ['measurements', api('/body-measurements?limit=24')],
        ['settings', api('/settings')],
      ];
      if (includeExercises) entries.unshift(['exercises', api('/exercises')]);
      const results = await Promise.allSettled(entries.map(([, request]) => request));
      let nextExercises = exercises;
      let nextDashboard = dashboard;
      let firstError = null;
      for (const [index, result] of results.entries()) {
        const key = entries[index][0];
        if (result.status === 'rejected') {
          firstError ||= result.reason;
          continue;
        }
        if (key === 'exercises') {
          nextExercises = result.value;
          setExercises(result.value);
        } else if (key === 'workouts') {
          setWorkouts(result.value);
          setWorkoutHasMore(result.value.length === WORKOUT_PAGE_SIZE);
        } else if (key === 'dashboard') {
          nextDashboard = result.value;
          setDashboard(result.value);
        } else if (key === 'lastPerformed') {
          setLastPerformed(Object.fromEntries(result.value.map((row) => [String(row.exercise_id), row])));
        } else if (key === 'measurements') {
          setMeasurements(result.value);
        } else if (key === 'settings') {
          setSettingsForm(result.value);
          setUnit(result.value.unit || 'lb');
          persistUnitPreference(result.value.unit || 'lb');
          setRestSeconds(result.value.default_rest_seconds || DEFAULT_REST_SECONDS);
        }
      }
      if (!selectedExerciseId) {
        const first = nextDashboard.recent_exercises?.[0]?.id || nextExercises[0]?.id || '';
        setSelectedExerciseId(first ? String(first) : '');
      }
      if (firstError) throw firstError;
    } finally {
      setDataLoading(false);
    }
  }

  async function loadMoreWorkouts() {
    if (workoutPageLoading || !workoutHasMore) return;
    setWorkoutPageLoading(true);
    setError('');
    try {
      const rows = await api(`/workouts?limit=${WORKOUT_PAGE_SIZE}&offset=${workouts.length}&q=${encodeURIComponent(workoutSearch)}`);
      setWorkouts((prev) => {
        const existing = new Set(prev.map((row) => row.id));
        return [...prev, ...rows.filter((row) => !existing.has(row.id))];
      });
      setWorkoutHasMore(rows.length === WORKOUT_PAGE_SIZE);
    } catch (e) {
      setError(e.message);
    } finally {
      setWorkoutPageLoading(false);
    }
  }

  async function loadUsers() {
    if (auth.user?.role !== 'admin') return;
    const rows = await api('/users');
    setUsers(rows);
  }

  async function searchWorkoutHistory(query) {
    setWorkoutSearch(query);
    setWorkoutPageLoading(true);
    setError('');
    try {
      const rows = await api(`/workouts?limit=${WORKOUT_PAGE_SIZE}&offset=0&q=${encodeURIComponent(query)}`);
      setWorkouts(rows);
      setWorkoutHasMore(rows.length === WORKOUT_PAGE_SIZE);
    } catch (e) {
      setError(e.message);
    } finally {
      setWorkoutPageLoading(false);
    }
  }

  useEffect(() => {
    refreshAuth().catch((e) => {
      setError(e.message);
      setAuth({ loading: false, setup_required: false, user: null });
    });
  }, []);

  useEffect(() => {
    function syncRoute() {
      setRoute(currentRoute());
    }
    window.addEventListener('hashchange', syncRoute);
    return () => window.removeEventListener('hashchange', syncRoute);
  }, []);

  useEffect(() => {
    setError('');
  }, [route]);

  useEffect(() => {
    document.documentElement.dataset.theme = settingsForm.theme || 'system';
  }, [settingsForm.theme]);

  useEffect(() => {
    if (!auth.user || !settingsForm.reminder_enabled) return undefined;
    function checkTrainingReminder() {
      const now = new Date();
      const reminderHour = Number(settingsForm.reminder_hour ?? 18);
      if (now.getHours() < reminderHour) return;
      const todayKey = formatLocalDate(now);
      const trainedToday = (dashboard.training_days || []).some((row) => row.workout_date === todayKey);
      if (trainedToday) return;
      const storageKey = `fitnessTrainReminder:${auth.user.id}:${todayKey}`;
      if (window.localStorage.getItem(storageKey)) return;
      window.localStorage.setItem(storageKey, 'sent');
      if ('Notification' in window && window.Notification.permission === 'granted') {
        new window.Notification('JournalGym', { body: 'No workout logged today.' });
      } else {
        setWorkoutMessage('No workout logged today.');
        setUndoAction(null);
      }
    }
    checkTrainingReminder();
    const timer = window.setInterval(checkTrainingReminder, 60_000);
    return () => window.clearInterval(timer);
  }, [auth.user?.id, settingsForm.reminder_enabled, settingsForm.reminder_hour, dashboard.training_days]);

  useEffect(() => {
    if (!auth.user) return;
    const draftState = loadDraftState(auth.user.id);
    setDrafts(draftState.drafts);
    setActiveDraftId(draftState.activeDraftId);
    setWorkout(draftState.workout);
    setTemplates(readStoredTemplates(auth.user.id));
    load().catch((e) => {
      if (e.status === 401) setAuth((prev) => ({ ...prev, user: null }));
      setError(e.message);
    });
  }, [auth.user?.id]);

  useEffect(() => {
    if (!auth.user) return undefined;
    if (draftPersistTimerRef.current) window.clearTimeout(draftPersistTimerRef.current);
    draftPersistTimerRef.current = window.setTimeout(() => {
      persistDrafts(drafts, activeDraftId, auth.user?.id);
      draftPersistTimerRef.current = null;
    }, DRAFT_AUTOSAVE_DELAY_MS);
    return () => {
      if (draftPersistTimerRef.current) window.clearTimeout(draftPersistTimerRef.current);
    };
  }, [drafts, activeDraftId, auth.user?.id]);

  useEffect(() => {
    if (!auth.user) return undefined;
    function handleShortcuts(event) {
      const tag = event.target?.tagName;
      const isTyping = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || event.target?.isContentEditable;
      if (isTyping || event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.key === '?' || event.key.toLowerCase() === 'h') {
        event.preventDefault();
        setShowHelp(true);
      } else if (route === 'home' && event.key.toLowerCase() === 'n') {
        event.preventDefault();
        drafts.length > 0 ? resumeDraft(activeDraftId || drafts[0]?.id, 'start-workout') : startNewDraft('start-workout');
      }
    }
    document.addEventListener('keydown', handleShortcuts);
    return () => document.removeEventListener('keydown', handleShortcuts);
  }, [auth.user?.id, route, activeDraftId, drafts]);

  useEffect(() => {
    loadUsers().catch((e) => setError(e.message));
  }, [auth.user?.id, auth.user?.role]);

  useEffect(() => {
    if (!restTargetAt) return undefined;
    function updateRemaining() {
      const remaining = Math.max(0, Math.ceil((restTargetAt - Date.now()) / 1000));
      setRestRemaining(remaining);
      if (remaining === 0) setRestTargetAt(0);
    }
    updateRemaining();
    const timer = window.setInterval(() => {
      updateRemaining();
    }, 1000);
    return () => window.clearInterval(timer);
  }, [restTargetAt]);

  useEffect(() => {
    if (restRemaining !== 0 || !restAnnounceRef.current) return;
    restAnnounceRef.current = false;
    announceRestComplete();
  }, [restRemaining]);

  useEffect(() => {
    if (!auth.user || !selectedExerciseId) return;
    Promise.all([
      api(`/exercises/${selectedExerciseId}/progression`),
      api(`/exercises/${selectedExerciseId}/history`),
    ])
      .then(([nextProgression, nextHistory]) => {
        setProgression(nextProgression);
        setExerciseHistory(nextHistory);
      })
      .catch((e) => setError(e.message));
  }, [auth.user?.id, selectedExerciseId]);

  useEffect(() => {
    if (editingWorkoutId) return;
    if (isEmptyWorkoutDraft(workout)) {
      if (activeDraftId) {
        setDrafts((prev) => {
          const next = prev.filter((draft) => draft.id !== activeDraftId);
          persistDrafts(next, '', auth.user?.id);
          return next;
        });
        setActiveDraftId('');
      } else {
        clearWorkoutDraft(auth.user?.id);
      }
    } else {
      const id = activeDraftId || createDraftId();
      const now = new Date().toISOString();
      setDrafts((prev) => {
        const existing = prev.find((draft) => draft.id === id);
        const nextDraft = {
          id,
          created_at: existing?.created_at || now,
          updated_at: now,
          workout,
        };
        const nextUncapped = [nextDraft, ...prev.filter((draft) => draft.id !== id)];
        if (!existing && nextUncapped.length > DRAFT_LIMIT) {
          setDraftCapNotice(`Draft limit is ${DRAFT_LIMIT}; the oldest draft was removed.`);
        }
        const next = nextUncapped.slice(0, DRAFT_LIMIT);
        return next;
      });
      if (!activeDraftId) setActiveDraftId(id);
    }
  }, [workout, activeDraftId, editingWorkoutId, auth.user?.id]);

  const exerciseOptions = useMemo(() => {
    return [...exercises].sort((a, b) => a.name.localeCompare(b.name));
  }, [exercises]);

  const priorityExerciseIds = useMemo(() => {
    const ids = [];
    for (const exercise of dashboard.recent_exercises || []) {
      const id = String(exercise.id);
      if (id && !ids.includes(id)) ids.push(id);
    }
    return ids.slice(0, PRIORITY_EXERCISE_LIMIT);
  }, [dashboard.recent_exercises]);

  const muscleVolume = useMemo(() => {
    const rows = {};
    for (const row of dashboard.volume_by_muscle || []) {
      if (muscleVolumeRole !== 'all' && row.role !== muscleVolumeRole) continue;
      rows[row.week] ||= { week: row.week, week_label: row.week_label || row.week };
      rows[row.week][row.muscle] = (rows[row.week][row.muscle] || 0) + row.volume_lbs;
    }
    return Object.values(rows);
  }, [dashboard, muscleVolumeRole]);

  const hasWorkoutDraft = drafts.length > 0;
  const currentWeek = useMemo(() => {
    return dashboard.weekly?.find((row) => row.week === weekKey()) || { sets: 0, volume_lbs: 0, workouts: 0 };
  }, [dashboard.weekly]);

  async function persistSettings(nextSettings) {
    const saved = await api('/settings', { method: 'PUT', body: JSON.stringify(nextSettings) });
    setSettingsForm(saved);
    setUnit(saved.unit || 'lb');
    persistUnitPreference(saved.unit || 'lb');
    setRestSeconds(saved.default_rest_seconds || DEFAULT_REST_SECONDS);
    return saved;
  }

  function changeUnit(nextUnit) {
    setUnit(nextUnit);
    persistUnitPreference(nextUnit);
    const nextSettings = { ...settingsForm, unit: nextUnit };
    setSettingsForm(nextSettings);
    persistSettings(nextSettings).catch((e) => setError(e.message));
  }

  function workoutWithSettingsDefaults() {
    return {
      ...defaultWorkout(),
      sets: [blankSet({ reps: settingsForm.default_reps ? String(settingsForm.default_reps) : '' })],
    };
  }

  function startRestTimer(seconds = restSeconds) {
    const nextSeconds = Number(seconds) || DEFAULT_REST_SECONDS;
    restAnnounceRef.current = true;
    setRestTargetAt(Date.now() + nextSeconds * 1000);
    setRestRemaining(nextSeconds);
    try {
      if (window.Notification?.permission === 'default') window.Notification.requestPermission();
    } catch {
      // Notification permission prompts are optional.
    }
  }

  function resetRestTimer() {
    restAnnounceRef.current = false;
    setRestTargetAt(0);
    setRestRemaining(0);
  }

  function navigate(nextRoute) {
    const hash = nextRoute === 'home' ? '' : `/${nextRoute}`;
    if (window.location.hash !== `#${hash}`) {
      window.location.hash = hash;
    }
    setError('');
    if (nextRoute !== 'home') setWorkoutMessage('');
  }

  function resumeDraft(id, nextRoute = 'start-workout') {
    const draft = drafts.find((row) => row.id === id);
    if (!draft) return;
    setActiveDraftId(id);
    setWorkout(draft.workout);
    persistDrafts(drafts, id, auth.user?.id);
    setShowDrafts(false);
    navigate(nextRoute);
  }

  function deleteDraft(id) {
    if (!window.confirm('Delete this draft?')) return;
    const deletedDraft = drafts.find((draft) => draft.id === id);
    if (!deletedDraft) return;
    setDraftCapNotice('');
    setDrafts((prev) => {
      const next = prev.filter((draft) => draft.id !== id);
      const nextActiveId = activeDraftId === id ? '' : activeDraftId;
      persistDrafts(next, nextActiveId, auth.user?.id);
      return next;
    });
    if (activeDraftId === id) {
      setActiveDraftId('');
      setWorkout(workoutWithSettingsDefaults());
    }
    setWorkoutMessage('Draft deleted.');
    setUndoAction({
      label: 'Undo',
      run: async () => {
        setDrafts((prev) => {
          const next = [deletedDraft, ...prev.filter((draft) => draft.id !== id)].slice(0, DRAFT_LIMIT);
          persistDrafts(next, deletedDraft.id, auth.user?.id);
          return next;
        });
        setActiveDraftId(deletedDraft.id);
        setWorkout(deletedDraft.workout);
        setWorkoutMessage('Draft restored.');
        setUndoAction(null);
      },
    });
  }

  function startNewDraft(nextRoute = 'start-workout') {
    setEditingWorkoutId('');
    setActiveDraftId('');
    setWorkout(workoutWithSettingsDefaults());
    setShowDrafts(false);
    navigate(nextRoute);
  }

  function startFromTemplate(templateId) {
    const template = templates.find((row) => row.id === templateId);
    if (!template) return;
    setEditingWorkoutId('');
    setActiveDraftId('');
    setWorkout({
      ...normalizeWorkoutDraft(template.workout),
      workout_date: today(),
    });
    navigate('start-workout');
  }

  function saveCurrentTemplate() {
    const name = window.prompt('Template name', workout.title || 'Workout Template');
    if (!name?.trim()) return;
    const template = normalizeDraftRecord({
      id: createDraftId(),
      workout: {
        ...workout,
        title: name.trim(),
        workout_date: today(),
      },
    });
    if (!template) return;
    setTemplates((prev) => {
      const next = [template, ...prev.filter((row) => row.id !== template.id)].slice(0, 20);
      persistTemplates(next, auth.user?.id);
      return next;
    });
    setWorkoutMessage('Template saved.');
  }

  function discardWorkoutDraft() {
    if (!window.confirm('Discard this workout draft?')) return;
    const discardedDraftId = activeDraftId;
    if (discardedDraftId) {
      setDrafts((prev) => {
        const next = prev.filter((draft) => draft.id !== discardedDraftId);
        persistDrafts(next, '', auth.user?.id);
        return next;
      });
    }
    setActiveDraftId('');
    setEditingWorkoutId('');
    setWorkout(workoutWithSettingsDefaults());
    setShowDrafts(false);
    setWorkoutMessage('Workout draft discarded.');
    setUndoAction(null);
    navigate('home');
  }

  function workoutPayloadFromState() {
    const payload = {
      workout_date: workout.workout_date,
      title: workout.title || null,
      bodyweight_lbs: parseOptionalNumber(workout.bodyweight_lbs, 'Bodyweight', { min: 30, max: 1000 }),
      notes: workout.notes || null,
      sets: workout.sets
        .filter((s) => s.exercise_id && (s.weight_mode === 'bodyweight' || s.weight_lbs !== '') && s.reps !== '')
        .map((s, index) => {
          const setLabel = `Set ${index + 1}`;
          const bodyweightOnly = s.weight_mode === 'bodyweight';
          return {
            exercise_id: Number(s.exercise_id),
            weight_lbs: bodyweightOnly && s.weight_lbs === '' ? 0 : parseWorkoutSetNumber(s.weight_lbs, `${setLabel} weight`, { min: 0, max: 2000 }),
            weight_mode: s.weight_mode || 'external',
            reps: parseWorkoutSetNumber(s.reps, `${setLabel} reps`, { integer: true, min: 1, max: 200 }),
            notes: s.notes || null,
          };
        }),
    };
    if (!payload.sets.length) throw new Error('Add at least one complete set.');
    return payload;
  }

  function workoutPayloadFromDetail(detail) {
    return {
      workout_date: detail.workout_date,
      title: detail.title || null,
      bodyweight_lbs: detail.bodyweight_lbs ?? null,
      notes: detail.notes || null,
      sets: (detail.sets || []).map((set) => ({
        exercise_id: set.exercise_id,
        weight_lbs: set.weight_lbs,
        weight_mode: set.weight_mode || 'external',
        reps: set.reps,
        notes: set.notes || null,
      })),
    };
  }

  function measurementPayloadFromState() {
    return {
      measured_date: measurementForm.measured_date,
      bodyweight_lbs: parseOptionalNumber(measurementForm.bodyweight_lbs, 'Bodyweight', { min: 30, max: 1000 }),
      waist_in: parseOptionalNumber(measurementForm.waist_in, 'Waist', { min: 0, max: 200 }),
      chest_in: parseOptionalNumber(measurementForm.chest_in, 'Chest', { min: 0, max: 200 }),
      hip_in: parseOptionalNumber(measurementForm.hip_in, 'Hip', { min: 0, max: 200 }),
      arm_in: parseOptionalNumber(measurementForm.arm_in, 'Arm', { min: 0, max: 100 }),
      thigh_in: parseOptionalNumber(measurementForm.thigh_in, 'Thigh', { min: 0, max: 100 }),
      photo_url: measurementForm.photo_url || null,
      notes: measurementForm.notes || null,
    };
  }

  function goalPayloadFromState() {
    const kind = goalForm.kind || 'one_rep_max';
    return {
      kind,
      exercise_id: kind === 'one_rep_max' ? Number(goalForm.exercise_id || selectedExerciseId) : null,
      target_value_lbs: parseWorkoutSetNumber(fromDisplayWeight(goalForm.target_value_lbs, unit), 'Goal target', { min: 1, max: kind === 'bodyweight' ? 1000 : 2000 }),
      target_date: goalForm.target_date || null,
      notes: goalForm.notes || null,
    };
  }

  async function openWorkoutDetail(id) {
    setError('');
    setWorkoutDetailLoading(true);
    try {
      const detail = await api(`/workouts/${id}`);
      setSelectedWorkout(detail);
    } catch (e) {
      setError(e.message);
    } finally {
      setWorkoutDetailLoading(false);
    }
  }

  async function startEditWorkout(id) {
    setError('');
    try {
      const detail = selectedWorkout?.id === id ? selectedWorkout : await api(`/workouts/${id}`);
      setEditingWorkoutId(String(id));
      setActiveDraftId('');
      setWorkout(workoutFromDetail(detail));
      setSelectedWorkout(null);
      navigate('edit-workout');
    } catch (e) {
      setError(e.message);
    }
  }

  async function repeatWorkout(id) {
    setError('');
    try {
      const detail = selectedWorkout?.id === id ? selectedWorkout : await api(`/workouts/${id}`);
      setEditingWorkoutId('');
      setActiveDraftId('');
      setWorkout({
        ...workoutFromDetail(detail),
        workout_date: today(),
      });
      setSelectedWorkout(null);
      navigate('start-workout');
    } catch (e) {
      setError(e.message);
    }
  }

  async function deleteWorkout(id) {
    if (!window.confirm('Delete this workout?')) return;
    setError('');
    setDeletingWorkoutId(String(id));
    try {
      const deletedDetail = selectedWorkout?.id === id ? selectedWorkout : await api(`/workouts/${id}`);
      await api(`/workouts/${id}`, { method: 'DELETE' });
      setSelectedWorkout(null);
      setWorkoutMessage('Workout deleted.');
      setUndoAction({
        label: 'Undo',
        run: async () => {
          await api('/workouts', { method: 'POST', body: JSON.stringify(workoutPayloadFromDetail(deletedDetail)) });
          await load({ includeExercises: false });
          setWorkoutMessage('Workout restored.');
          setUndoAction(null);
        },
      });
      await load({ includeExercises: false });
    } catch (e) {
      setError(e.message);
    } finally {
      setDeletingWorkoutId('');
    }
  }

  function updateSet(index, key, value) {
    setWorkout((prev) => {
      const sets = prev.sets.map((s, i) => (i === index ? { ...s, [key]: value } : s));
      return { ...prev, sets };
    });
  }

  function addSet(copyLast = true) {
    setWorkout((prev) => {
      const last = prev.sets[prev.sets.length - 1] || {};
      return {
        ...prev,
        sets: [
          ...prev.sets,
          copyLast
            ? { exercise_id: last.exercise_id || '', weight_lbs: last.weight_lbs || '', weight_mode: last.weight_mode || 'external', reps: last.reps || '', client_id: createSetId(), notes: '' }
            : blankSet({ reps: settingsForm.default_reps ? String(settingsForm.default_reps) : '' }),
        ],
      };
    });
  }

  function duplicateSet(index) {
    setWorkout((prev) => {
      const source = prev.sets[index] || prev.sets[prev.sets.length - 1] || {};
      const copied = { exercise_id: source.exercise_id || '', weight_lbs: source.weight_lbs || '', weight_mode: source.weight_mode || 'external', reps: source.reps || '', client_id: createSetId(), notes: '' };
      return {
        ...prev,
        sets: [
          ...prev.sets.slice(0, index + 1),
          copied,
          ...prev.sets.slice(index + 1),
        ],
      };
    });
  }

  function removeSet(index) {
    setWorkout((prev) => {
      if (prev.sets.length === 1) return prev;
      return { ...prev, sets: prev.sets.filter((_, i) => i !== index) };
    });
  }

  async function handleAuth(mode, payload) {
    setError('');
    try {
      const route = mode === 'setup' ? '/auth/setup' : '/auth/login';
      const state = await api(route, { method: 'POST', body: JSON.stringify(payload) });
      setAuth({ loading: false, setup_required: state.setup_required, user: state.user });
    } catch (e) {
      setError(e.message);
    }
  }

  function clearSignedInState() {
    setAuth({ loading: false, setup_required: false, user: null });
    setExercises([]);
    setWorkouts([]);
    setWorkoutSearch('');
    setWorkoutHasMore(false);
    setWorkoutPageLoading(false);
    setDashboard(EMPTY_DASHBOARD);
    setLastPerformed({});
    setProgression(null);
    setExerciseHistory([]);
    setSelectedExerciseId('');
    setSelectedWorkout(null);
    setEditingWorkoutId('');
    setTemplates([]);
    clearWorkoutDraft(auth.user?.id);
    setDrafts([]);
    setActiveDraftId('');
    setWorkout(workoutWithSettingsDefaults());
  }

  async function logout() {
    setError('');
    await api('/auth/logout', { method: 'POST' }).catch(() => null);
    clearSignedInState();
  }

  async function logoutAllDevices() {
    setError('');
    setPinMessage('');
    try {
      await api('/auth/logout-all', { method: 'POST' });
      clearSignedInState();
    } catch (e) {
      setError(e.message);
    }
  }

  async function changePin(e) {
    e.preventDefault();
    setError('');
    setPinMessage('');
    if (pinForm.new_pin !== pinForm.confirm_pin) {
      setError('New PINs do not match.');
      return;
    }
    if (pinForm.current_pin === pinForm.new_pin) {
      setError('New PIN must differ from current PIN.');
      return;
    }
    setPinSaving(true);
    try {
      await api('/auth/pin', {
        method: 'PUT',
        body: JSON.stringify({
          current_pin: pinForm.current_pin,
          new_pin: pinForm.new_pin,
        }),
      });
      setPinForm({ current_pin: '', new_pin: '', confirm_pin: '' });
      setPinMessage('PIN updated.');
      setShowPinForm(false);
    } catch (e) {
      setError(e.message);
    } finally {
      setPinSaving(false);
    }
  }

  async function saveWorkout(e, options = {}) {
    e.preventDefault();
    setSaving(true);
    setError('');
    setWorkoutMessage('');
    try {
      const payload = workoutPayloadFromState();
      const isEditing = Boolean(editingWorkoutId);
      await api(isEditing ? `/workouts/${editingWorkoutId}` : '/workouts', {
        method: isEditing ? 'PUT' : 'POST',
        body: JSON.stringify(payload),
      });
      const freshWorkout = workoutWithSettingsDefaults();
      const savedDraftId = activeDraftId;
      setDrafts((prev) => {
        const next = savedDraftId ? prev.filter((draft) => draft.id !== savedDraftId) : prev;
        persistDrafts(next, '', auth.user?.id);
        return next;
      });
      setActiveDraftId('');
      setEditingWorkoutId('');
      clearWorkoutDraft(auth.user?.id);
      setWorkout(freshWorkout);
      await load({ includeExercises: false });
      setWorkoutMessage(isEditing ? 'Workout updated.' : `Workout saved with ${payload.sets.length} ${payload.sets.length === 1 ? 'set' : 'sets'}.`);
      if (options.goHome) navigate('home');
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  async function saveExercise(e) {
    e.preventDefault();
    setError('');
    setWorkoutMessage('');
    try {
      const { alias_text, ...exercisePayload } = newExercise;
      const created = await api('/exercises', { method: 'POST', body: JSON.stringify({ ...exercisePayload, aliases: parseAliases(alias_text) }) });
      setExercises((prev) => [...prev, created]);
      setNewExercise({ name: '', primary_muscle: 'Chest', equipment: 'Dumbbells', secondary_muscles: [], alias_text: '', notes: '' });
      setWorkoutMessage(`Added exercise ${created.name}.`);
    } catch (e) {
      setError(e.message);
    }
  }

  async function updateExercise(exerciseId, payload) {
    setError('');
    try {
      const updated = await api(`/exercises/${exerciseId}`, { method: 'PUT', body: JSON.stringify(payload) });
      setExercises((prev) => {
        if (updated.is_archived) return prev.filter((exercise) => exercise.id !== updated.id);
        return prev.map((exercise) => (exercise.id === updated.id ? updated : exercise));
      });
      if (updated.is_archived && String(selectedExerciseId) === String(updated.id)) setSelectedExerciseId('');
    } catch (e) {
      setError(e.message);
    }
  }

  async function saveMeasurement(e) {
    e.preventDefault();
    setError('');
    try {
      const created = await api('/body-measurements', { method: 'POST', body: JSON.stringify(measurementPayloadFromState()) });
      setMeasurements((prev) => [created, ...prev].slice(0, 24));
      setMeasurementForm(defaultMeasurement());
      setDashboard(await api('/dashboard?days=365'));
      setWorkoutMessage('Measurement saved.');
    } catch (e) {
      setError(e.message);
    }
  }

  async function deleteMeasurement(id) {
    setError('');
    try {
      await api(`/body-measurements/${id}`, { method: 'DELETE' });
      setMeasurements((prev) => prev.filter((row) => row.id !== id));
      setDashboard(await api('/dashboard?days=365'));
    } catch (e) {
      setError(e.message);
    }
  }

  async function saveGoal(e) {
    e.preventDefault();
    setError('');
    try {
      await api('/goals', { method: 'POST', body: JSON.stringify(goalPayloadFromState()) });
      setGoalForm(defaultGoal());
      setDashboard(await api('/dashboard?days=365'));
      setWorkoutMessage('Goal saved.');
    } catch (e) {
      setError(e.message);
    }
  }

  async function saveSettings(e) {
    e.preventDefault();
    setError('');
    try {
      await persistSettings({
        unit: settingsForm.unit || 'lb',
        default_rest_seconds: Number(settingsForm.default_rest_seconds) || DEFAULT_REST_SECONDS,
        default_reps: Number(settingsForm.default_reps) || DEFAULT_REPS,
        theme: settingsForm.theme || 'system',
        reminder_enabled: Boolean(settingsForm.reminder_enabled),
        reminder_hour: Number(settingsForm.reminder_hour ?? 18),
      });
      if (settingsForm.reminder_enabled && 'Notification' in window && window.Notification.permission === 'default') {
        window.Notification.requestPermission().catch(() => null);
      }
      setWorkoutMessage('Settings saved.');
    } catch (err) {
      setError(err.message);
    }
  }

  async function wipeAccountData() {
    if (!window.confirm('Delete all workouts, measurements, and goals for your account?')) return;
    setError('');
    try {
      await api('/account/data', { method: 'DELETE' });
      await load({ includeExercises: false });
      setWorkoutMessage('Account data wiped.');
      setUndoAction(null);
    } catch (err) {
      setError(err.message);
    }
  }

  async function deleteOwnAccount() {
    if (!window.confirm('Delete your account and all of its data? This cannot be undone.')) return;
    setError('');
    try {
      await api('/account', { method: 'DELETE' });
      clearSignedInState();
      setAuth({ loading: false, setup_required: false, user: null });
    } catch (err) {
      setError(err.message);
    }
  }

  async function deleteGoal(id) {
    setError('');
    try {
      await api(`/goals/${id}`, { method: 'DELETE' });
      setDashboard(await api('/dashboard?days=365'));
    } catch (e) {
      setError(e.message);
    }
  }

  async function downloadData(format) {
    setError('');
    try {
      const res = await fetch(`${API}/export.${format}`, { credentials: 'include' });
      if (!res.ok) throw new Error(await res.text() || res.statusText);
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `fitness-export.${format}`;
      link.click();
      window.URL.revokeObjectURL(url);
    } catch (e) {
      setError(e.message);
    }
  }

  async function importDataFile(file) {
    if (!file) return;
    setError('');
    try {
      const payload = JSON.parse(await file.text());
      const result = await api('/import.json', { method: 'POST', body: JSON.stringify(payload) });
      await load();
      setWorkoutMessage(`Imported ${result.imported_workouts} workouts, ${result.imported_measurements} measurements, ${result.imported_goals || 0} goals, and ${result.imported_settings || 0} settings.`);
    } catch (e) {
      setError(e.message);
    }
  }

  async function saveUser(e) {
    e.preventDefault();
    setError('');
    setPinMessage('');
    try {
      const created = await api('/users', { method: 'POST', body: JSON.stringify(newUser) });
      setUsers((prev) => sortUsers([...prev, created]));
      setNewUser({ username: '', display_name: '', pin: '', role: 'user' });
      setPinMessage(`Added user ${created.display_name}.`);
    } catch (e) {
      setError(e.message);
    }
  }

  async function resetUserPin(e, user) {
    e.preventDefault();
    const pin = resetPins[user.id] || '';
    if (!PIN_PATTERN.test(pin)) {
      setError('PIN must be 6-12 digits.');
      return;
    }
    setError('');
    setPinMessage('');
    setResetSavingUserId(String(user.id));
    try {
      await api(`/users/${user.id}/pin`, { method: 'PUT', body: JSON.stringify({ pin }) });
      setResetPins((prev) => ({ ...prev, [user.id]: '' }));
      setPinMessage(`PIN reset for ${user.display_name}.`);
    } catch (e) {
      setError(e.message);
    } finally {
      setResetSavingUserId('');
    }
  }

  function userDraft(user) {
    return userEdits[user.id] || {
      username: user.username,
      display_name: user.display_name,
      role: user.role,
      is_active: user.is_active,
    };
  }

  function updateUserDraft(user, field, value) {
    setUserEdits((prev) => ({ ...prev, [user.id]: { ...userDraft(user), [field]: value } }));
  }

  async function saveUserEdit(e, user) {
    e.preventDefault();
    setError('');
    try {
      const updated = await api(`/users/${user.id}`, { method: 'PUT', body: JSON.stringify(userDraft(user)) });
      setUsers((prev) => sortUsers(prev.map((row) => (row.id === updated.id ? updated : row))));
      setUserEdits((prev) => {
        const next = { ...prev };
        delete next[user.id];
        return next;
      });
      setPinMessage(`Updated ${updated.display_name}.`);
    } catch (e) {
      setError(e.message);
    }
  }

  async function toggleUserActive(user) {
    const draft = { username: user.username, display_name: user.display_name, role: user.role, is_active: !user.is_active };
    setError('');
    try {
      const updated = await api(`/users/${user.id}`, { method: 'PUT', body: JSON.stringify(draft) });
      setUsers((prev) => sortUsers(prev.map((row) => (row.id === updated.id ? updated : row))));
    } catch (e) {
      setError(e.message);
    }
  }

  async function deleteUser(user) {
    if (!window.confirm(`Delete ${user.display_name}? Users with workouts must be deactivated instead.`)) return;
    setError('');
    try {
      await api(`/users/${user.id}`, { method: 'DELETE' });
      setUsers((prev) => prev.filter((row) => row.id !== user.id));
    } catch (e) {
      setError(e.message);
    }
  }

  if (auth.loading) {
    return (
      <>
        <SkipLink />
        <main id="main-content" className="auth-main">
          <div className="auth-panel">
            <Activity size={18} />
            <p>Loading</p>
          </div>
        </main>
      </>
    );
  }

  if (!auth.user) {
    return (
      <AuthGate
        setupRequired={auth.setup_required}
        error={error}
        onSubmit={handleAuth}
      />
    );
  }

  if (route === 'start-workout' || route === 'edit-workout') {
    const activeDraft = drafts.find((draft) => draft.id === activeDraftId);
    return (
      <>
        <WorkoutLogPage
          mode={route === 'edit-workout' ? 'edit' : 'start'}
          user={auth.user}
          workout={workout}
          draftSavedAt={activeDraft?.updated_at}
          draftCount={drafts.length}
          setWorkout={setWorkout}
          exerciseOptions={exerciseOptions}
          priorityExerciseIds={priorityExerciseIds}
          lastPerformed={lastPerformed}
          unit={unit}
          restSeconds={restSeconds}
          restRemaining={restRemaining}
          setRestSeconds={setRestSeconds}
          onStartRest={startRestTimer}
          onResetRest={resetRestTimer}
          saving={saving}
          error={error}
          updateSet={updateSet}
          addSet={addSet}
          duplicateSet={duplicateSet}
          removeSet={removeSet}
          onDrafts={() => setShowDrafts(true)}
          onSaveTemplate={saveCurrentTemplate}
          onSave={(e) => saveWorkout(e, { goHome: true })}
          onDiscard={discardWorkoutDraft}
          onBack={() => {
            setEditingWorkoutId('');
            setWorkout(workoutWithSettingsDefaults());
            navigate('home');
          }}
        />
        {showDrafts && (
          <DraftManager
            drafts={drafts}
            activeDraftId={activeDraftId}
            draftLimit={DRAFT_LIMIT}
            draftCapNotice={draftCapNotice}
            onClose={() => setShowDrafts(false)}
            onResume={(id) => resumeDraft(id, route)}
            onDelete={deleteDraft}
            onNew={() => startNewDraft(route)}
          />
        )}
      </>
    );
  }

  if (route === 'not-found') {
    return <NotFoundPage onHome={() => navigate('home')} />;
  }

  return (
    <>
      <SkipLink />
      <main id="main-content">
      <header className="topbar">
        <div>
          <h1>JournalGym</h1>
          <p>Strength log, progression, volume, and PRs.</p>
        </div>
        <div className="topbar-actions">
          <div className="status-pill">
            <Shield size={16} />
            <span>{auth.user.display_name}</span>
          </div>
          <button type="button" onClick={() => setShowPinForm((value) => !value)}>
            <KeyRound size={16} />
            PIN
          </button>
          <button type="button" onClick={() => setShowHelp(true)} aria-label="Help and about">
            <HelpCircle size={16} />
            Help
          </button>
          <div className="unit-toggle" role="group" aria-label="Units">
            {['lb', 'kg'].map((value) => (
              <button type="button" key={value} className={unit === value ? 'active' : ''} onClick={() => changeUnit(value)}>
                {value}
              </button>
            ))}
          </div>
          <button type="button" onClick={logout}>
            <LogOut size={16} />
            Logout
          </button>
        </div>
      </header>

      {restRemaining > 0 && <GlobalRestTimer remaining={restRemaining} onReset={resetRestTimer} />}

      {error && <div className="error" role="alert">{error}</div>}
      {pinMessage && <div className="success" role="status" aria-live="polite">{pinMessage}</div>}
      {workoutMessage && (
        <div className="success action-message" role="status" aria-live="polite">
          <span>{workoutMessage}</span>
          {undoAction && <button type="button" onClick={() => undoAction.run()}>{undoAction.label}</button>}
        </div>
      )}

      {showPinForm && (
        <form className="panel account-panel" onSubmit={changePin}>
          <div className="panel-head">
            <h2><KeyRound size={18} /> Change PIN</h2>
            <button type="button" onClick={() => setShowPinForm(false)}>Close</button>
          </div>
          <div className="pin-form">
            <label>Current PIN<input type="password" inputMode="numeric" value={pinForm.current_pin} onChange={(e) => setPinForm({ ...pinForm, current_pin: e.target.value })} placeholder="6-12 digits" /></label>
            <label>New PIN<input type="password" inputMode="numeric" value={pinForm.new_pin} onChange={(e) => setPinForm({ ...pinForm, new_pin: e.target.value })} placeholder="6-12 digits" /></label>
            <label>Confirm PIN<input type="password" inputMode="numeric" value={pinForm.confirm_pin} onChange={(e) => setPinForm({ ...pinForm, confirm_pin: e.target.value })} placeholder="6-12 digits" /></label>
            <button className="primary" disabled={pinSaving}><Save size={16} /> {pinSaving ? 'Saving' : 'Save'}</button>
            <button type="button" onClick={logoutAllDevices}><LogOut size={16} /> Log Out All Devices</button>
          </div>
        </form>
      )}

      <section className="metrics">
        {dataLoading && !dashboard.weekly?.length ? (
          Array.from({ length: 4 }).map((_, index) => <SkeletonCard key={index} className="metric skeleton-metric" />)
        ) : (
          <>
            <Metric icon={<Dumbbell size={18} />} label="Weekly Sets" value={currentWeek.sets || 0} />
            <Metric icon={<Target size={18} />} label="Weekly Volume" value={formatWeight(currentWeek.volume_lbs || 0, unit)} />
            <Metric icon={<CalendarDays size={18} />} label="Workouts This Week" value={currentWeek.workouts || 0} />
            <Metric icon={<Trophy size={18} />} label="Recent PRs" value={dashboard.prs?.length || 0} />
          </>
        )}
      </section>

      {!dataLoading && !workouts.length && (
        <FirstWorkoutPanel onStart={() => startNewDraft('start-workout')} />
      )}

      <section className="workspace">
        <LoggingChoicePanel
          hasDraft={hasWorkoutDraft}
          draftCount={drafts.length}
          onDrafts={() => setShowDrafts(true)}
          onStart={() => hasWorkoutDraft ? resumeDraft(activeDraftId || drafts[0]?.id, 'start-workout') : startNewDraft('start-workout')}
          templates={templates}
          onTemplate={startFromTemplate}
        />

        <ChartPanel title="Selected Exercise Strength Trend" forceOpenKey={selectedExerciseId} controls={
            <ExercisePicker
              className="chart-exercise-picker"
              label="Strength Trend Exercise"
              value={selectedExerciseId}
              exerciseOptions={exerciseOptions}
              priorityExerciseIds={priorityExerciseIds}
              lastPerformed={lastPerformed}
              unit={unit}
              showSelectedMeta={false}
              onChange={setSelectedExerciseId}
            />
          }>
          <ChartShell loading={dataLoading && !progression} empty={!progression?.points?.length}>
            <>
              <ExerciseProgressStats stats={progression?.stats} unit={unit} />
              <ResponsiveContainer width="100%" height={260}>
                <LineChart data={progression?.points || []}>
                  <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
                  <XAxis dataKey="workout_date" stroke={CHART_COLORS.axis} label={{ value: 'Workout date', position: 'insideBottom', offset: -2, ...CHART_AXIS_LABEL_STYLE }} />
                  <YAxis stroke={CHART_COLORS.axis} label={{ value: unit, angle: -90, position: 'insideLeft', ...CHART_AXIS_LABEL_STYLE }} />
                  <Tooltip formatter={(value, name) => [formatWeight(value, unit), name]} contentStyle={CHART_TOOLTIP_STYLE} />
                  <Legend />
                  <Line type="monotone" dataKey="best_estimated_1rm" name="Best estimated 1RM" stroke={CHART_COLORS.primary} strokeWidth={2} dot={{ r: 3 }} activeDot={{ r: 5 }} />
                  <Line type="monotone" dataKey="max_weight_lbs" name="Max weight" stroke={CHART_COLORS.secondary} strokeWidth={2} dot={{ r: 3 }} activeDot={{ r: 5 }} />
                </LineChart>
              </ResponsiveContainer>
              <ExerciseProgressTable points={progression?.points || []} unit={unit} />
              <ExerciseSetHistory rows={exerciseHistory} unit={unit} />
            </>
          </ChartShell>
        </ChartPanel>
      </section>

      <section className="charts">
        <ChartPanel title="Weekly Volume by Muscle" icon={<BarChart3 size={18} />} controls={
          <div className="unit-toggle muscle-role-toggle" role="group" aria-label="Muscle volume role">
            {MUSCLE_VOLUME_ROLES.map(([value, label]) => (
              <button type="button" key={value} className={muscleVolumeRole === value ? 'active' : ''} onClick={() => setMuscleVolumeRole(value)}>
                {label}
              </button>
            ))}
          </div>
        }>
          <ChartShell loading={dataLoading && !muscleVolume.length} empty={!muscleVolume.length}>
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={muscleVolume}>
                <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
                <XAxis dataKey="week_label" stroke={CHART_COLORS.axis} label={{ value: 'Week', position: 'insideBottom', offset: -2, ...CHART_AXIS_LABEL_STYLE }} />
                <YAxis stroke={CHART_COLORS.axis} label={{ value: `Volume (${unit})`, angle: -90, position: 'insideLeft', ...CHART_AXIS_LABEL_STYLE }} />
                <Tooltip formatter={(value, name) => [formatWeight(value, unit), name]} contentStyle={CHART_TOOLTIP_STYLE} />
                <Legend />
                {MUSCLES.map((m, i) => <Bar key={m} dataKey={m} name={muscleOptionLabel(m)} stackId="a" fill={CHART_COLORS.musclePalette[i % CHART_COLORS.musclePalette.length]} />)}
              </BarChart>
            </ResponsiveContainer>
          </ChartShell>
        </ChartPanel>

        <ChartPanel title="Weekly Sets and Workouts" icon={<History size={18} />}>
          <ChartShell loading={dataLoading && !dashboard.weekly?.length} empty={!dashboard.weekly?.length}>
            <ResponsiveContainer width="100%" height={280}>
              <AreaChart data={dashboard.weekly || []}>
                <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
                <XAxis dataKey="week_label" stroke={CHART_COLORS.axis} label={{ value: 'Week', position: 'insideBottom', offset: -2, ...CHART_AXIS_LABEL_STYLE }} />
                <YAxis stroke={CHART_COLORS.axis} label={{ value: 'Count', angle: -90, position: 'insideLeft', ...CHART_AXIS_LABEL_STYLE }} />
                <Tooltip formatter={(value, name) => [value, name]} contentStyle={CHART_TOOLTIP_STYLE} />
                <Legend />
                <Area type="monotone" dataKey="sets" name="Sets" stroke={CHART_COLORS.weeklySets} fill={CHART_COLORS.weeklySetsFill} strokeWidth={2} />
                <Area type="monotone" dataKey="workouts" name="Workouts" stroke={CHART_COLORS.weeklyWorkouts} fill={CHART_COLORS.weeklyWorkoutsFill} strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          </ChartShell>
        </ChartPanel>
      </section>

      <section className="bottom-grid">
        <TrainingHeatmapPanel dashboard={dashboard} />
        <MuscleTargetPanel dashboard={dashboard} />
        <WorkoutHistoryPanel
          workouts={workouts}
          search={workoutSearch}
          loading={workoutDetailLoading}
          dataLoading={dataLoading}
          onOpen={openWorkoutDetail}
          onRepeat={repeatWorkout}
          onEdit={startEditWorkout}
          onDelete={deleteWorkout}
          deletingWorkoutId={deletingWorkoutId}
          unit={unit}
          hasMore={workoutHasMore}
          pageLoading={workoutPageLoading}
          onLoadMore={loadMoreWorkouts}
          onSearch={searchWorkoutHistory}
        />
        <section className="panel">
          <div className="panel-head"><h2>Personal Records</h2></div>
          <div className="table-list">
            {(dashboard.prs || []).slice(0, DASHBOARD_PR_DISPLAY_LIMIT).map((pr, index) => (
              <div className="table-row" key={`${pr.exercise_id}-${pr.workout_date}-${pr.estimated_1rm}-${index}`}>
                <div><strong>{pr.exercise_name}</strong><span>{pr.workout_date} - {pr.primary_muscle}</span></div>
                <b>{formatWeight(pr.estimated_1rm, unit)}</b>
              </div>
            ))}
            {!dashboard.prs?.length && <p className="muted">PRs appear after workouts are logged.</p>}
          </div>
        </section>
      </section>

      {auth.user.role === 'admin' && (
        <>
          <form className="panel add-exercise-panel" onSubmit={saveExercise}>
            <div className="panel-head"><h2>Add Exercise</h2></div>
            <div className="fields">
              <label>Name<input value={newExercise.name} onChange={(e) => setNewExercise({ ...newExercise, name: e.target.value })} placeholder="Hack Squat" /></label>
              <label>Muscle<select value={newExercise.primary_muscle} onChange={(e) => setNewExercise({ ...newExercise, primary_muscle: e.target.value, secondary_muscles: newExercise.secondary_muscles.filter((muscle) => muscle !== e.target.value) })}>{MUSCLES.map((m) => <option key={m} value={m}>{muscleOptionLabel(m)}</option>)}</select></label>
              <label>Equipment<select value={newExercise.equipment} onChange={(e) => setNewExercise({ ...newExercise, equipment: e.target.value })}>{EQUIPMENT.map((m) => <option key={m}>{m}</option>)}</select></label>
            </div>
            {MUSCLE_HINTS[newExercise.primary_muscle] && <p className="muscle-hint">{MUSCLE_HINTS[newExercise.primary_muscle]}</p>}
            <MuscleCheckboxGroup
              label="Secondary Muscles"
              values={newExercise.secondary_muscles}
              primary={newExercise.primary_muscle}
              onChange={(values) => setNewExercise({ ...newExercise, secondary_muscles: values })}
            />
            <label className="exercise-notes-field">
              Aliases
              <input value={newExercise.alias_text} onChange={(e) => setNewExercise({ ...newExercise, alias_text: e.target.value })} placeholder="OHP, RDL, pec deck" />
            </label>
            <label className="exercise-notes-field">
              Notes
              <textarea value={newExercise.notes} onChange={(e) => setNewExercise({ ...newExercise, notes: e.target.value })} placeholder="Setup, range of motion, form cues" />
            </label>
            <button className="primary"><Plus size={16} /> Add Exercise</button>
          </form>

          <ExerciseCatalogPanel exercises={exerciseOptions} onSave={updateExercise} />
        </>
      )}

      <MeasurementPanel
        measurements={measurements}
        form={measurementForm}
        setForm={setMeasurementForm}
        onSave={saveMeasurement}
        onDelete={deleteMeasurement}
        unit={unit}
      />

      <GoalPanel
        goals={dashboard.active_goals || []}
        form={goalForm}
        setForm={setGoalForm}
        exerciseOptions={exerciseOptions}
        selectedExerciseId={selectedExerciseId}
        onSave={saveGoal}
        onDelete={deleteGoal}
        unit={unit}
      />

      <SettingsPanel form={settingsForm} setForm={setSettingsForm} onSave={saveSettings} />

      <AccountSelfServicePanel onWipeData={wipeAccountData} onDeleteAccount={deleteOwnAccount} onLogoutAll={logoutAllDevices} />

      <BackupPanel onDownload={downloadData} onImport={importDataFile} />

      {selectedWorkout && (
        <WorkoutDetailModal
          workout={selectedWorkout}
          onClose={() => setSelectedWorkout(null)}
          onRepeat={() => repeatWorkout(selectedWorkout.id)}
          onEdit={() => startEditWorkout(selectedWorkout.id)}
          onDelete={() => deleteWorkout(selectedWorkout.id)}
          deleting={deletingWorkoutId === String(selectedWorkout.id)}
          unit={unit}
        />
      )}

      {showDrafts && (
        <DraftManager
          drafts={drafts}
          activeDraftId={activeDraftId}
          draftLimit={DRAFT_LIMIT}
          draftCapNotice={draftCapNotice}
          onClose={() => setShowDrafts(false)}
          onResume={(id) => resumeDraft(id, 'start-workout')}
          onDelete={deleteDraft}
          onNew={() => startNewDraft('start-workout')}
        />
      )}

      {showHelp && <HelpAboutModal onClose={() => setShowHelp(false)} />}

      {auth.user.role === 'admin' && (
        <section className="panel users-panel">
          <div className="panel-head">
            <h2><UserPlus size={18} /> Users</h2>
            <span className="muted">{users.length} active</span>
          </div>
          <form className="user-form" onSubmit={saveUser}>
            <label>Username<input value={newUser.username} onChange={(e) => setNewUser({ ...newUser, username: e.target.value })} placeholder="alex" /></label>
            <label>Name<input value={newUser.display_name} onChange={(e) => setNewUser({ ...newUser, display_name: e.target.value })} placeholder="Alex" /></label>
            <label>PIN<input type="password" inputMode="numeric" value={newUser.pin} onChange={(e) => setNewUser({ ...newUser, pin: e.target.value })} placeholder="6-12 digits" /></label>
            <label>Role<select value={newUser.role} onChange={(e) => setNewUser({ ...newUser, role: e.target.value })}><option value="user">User</option><option value="admin">Admin</option></select></label>
            <button className="primary"><UserPlus size={16} /> Add</button>
          </form>
          <div className="user-list">
            {users.map((user) => {
              const draft = userDraft(user);
              return (
                <div className="user-row" key={user.id}>
                  <div>
                    <strong>{user.display_name}</strong>
                    <span>@{user.username} - {user.is_active ? 'active' : 'inactive'}</span>
                  </div>
                  <b>{user.role}</b>
                  <form className="user-edit-form" onSubmit={(e) => saveUserEdit(e, user)}>
                    <input value={draft.username} onChange={(e) => updateUserDraft(user, 'username', e.target.value)} aria-label={`Username for ${user.display_name}`} />
                    <input value={draft.display_name} onChange={(e) => updateUserDraft(user, 'display_name', e.target.value)} aria-label={`Display name for ${user.display_name}`} />
                    <select value={draft.role} onChange={(e) => updateUserDraft(user, 'role', e.target.value)} aria-label={`Role for ${user.display_name}`}>
                      <option value="user">User</option>
                      <option value="admin">Admin</option>
                    </select>
                    <button type="submit" className="primary"><Save size={15} /> Save</button>
                  </form>
                  <form className="user-reset-form" onSubmit={(e) => resetUserPin(e, user)}>
                    <input
                      type="password"
                      inputMode="numeric"
                      value={resetPins[user.id] || ''}
                      onChange={(e) => setResetPins((prev) => ({ ...prev, [user.id]: e.target.value }))}
                      placeholder="New PIN"
                      aria-label={`New PIN for ${user.display_name}`}
                    />
                    <button type="submit" className="icon-btn" disabled={resetSavingUserId === String(user.id)} aria-label={`Reset PIN for ${user.display_name}`}>
                      <KeyRound size={15} />
                    </button>
                  </form>
                  <div className="user-admin-actions">
                    <button type="button" onClick={() => toggleUserActive(user)}>{user.is_active ? 'Deactivate' : 'Activate'}</button>
                    <button type="button" className="danger-btn" onClick={() => deleteUser(user)}>Delete</button>
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      )}
      </main>
    </>
  );
}

function LoggingChoicePanel({ hasDraft, draftCount, onDrafts, onStart, templates = [], onTemplate }) {
  return (
    <section className="panel logging-choice">
      <div className="panel-head">
        <h2><Dumbbell size={18} /> Log Training</h2>
        {hasDraft && (
          <button type="button" className="draft-pill" onClick={onDrafts}>
            <ListChecks size={14} />
            {draftCount} {draftCount === 1 ? 'draft' : 'drafts'}
          </button>
        )}
      </div>
      <div className="log-actions">
        <button type="button" className="log-action primary-action" onClick={onStart}>
          <Play size={20} />
          <span>Start Workout</span>
          <small>Live session layout for adding sets as you train.</small>
        </button>
      </div>
      {!!templates.length && (
        <div className="template-list">
          {templates.slice(0, 6).map((template) => (
            <button type="button" key={template.id} onClick={() => onTemplate(template.id)}>
              <ListChecks size={15} />
              {template.workout.title || 'Template'}
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

function NotFoundPage({ onHome }) {
  return (
    <>
      <SkipLink />
      <main id="main-content" className="auth-main">
        <section className="auth-panel">
          <Activity size={18} />
          <div>
            <h1>Page Not Found</h1>
            <p className="muted">That route is not available.</p>
          </div>
          <button type="button" className="primary" onClick={onHome}><ArrowLeft size={16} /> Dashboard</button>
        </section>
      </main>
    </>
  );
}

function FirstWorkoutPanel({ onStart }) {
  return (
    <section className="panel first-workout-panel">
      <div>
        <h2><Dumbbell size={18} /> Log your first workout</h2>
        <p className="muted">Progress charts, PRs, and history fill in after the first saved session.</p>
      </div>
      <button type="button" className="primary" onClick={onStart}>
        <Play size={16} />
        Start Workout
      </button>
    </section>
  );
}

function WorkoutHistoryPanel({ workouts, search, loading, dataLoading, onOpen, onRepeat, onEdit, onDelete, deletingWorkoutId, unit, hasMore, pageLoading, onLoadMore, onSearch }) {
  const [query, setQuery] = useState(search || '');
  useEffect(() => {
    setQuery(search || '');
  }, [search]);
  function submitSearch(event) {
    event.preventDefault();
    onSearch(query.trim());
  }
  return (
    <section className="panel history-panel">
      <div className="panel-head">
        <h2><History size={18} /> Workout History</h2>
        <span className="muted">{workouts.length} shown</span>
      </div>
      <form className="history-search" onSubmit={submitSearch}>
        <label>
          Search
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Title, notes, exercise" />
        </label>
        <button type="submit"><Search size={15} /> Search</button>
        {search && <button type="button" onClick={() => onSearch('')}>Clear</button>}
      </form>
      <div className="table-list history-list">
        {dataLoading && !workouts.length && Array.from({ length: 4 }).map((_, index) => (
          <SkeletonCard key={index} className="history-row skeleton-row" />
        ))}
        {workouts.map((row) => (
          <article className="history-row" key={row.id}>
            <button type="button" className="history-main" onClick={() => onOpen(row.id)} disabled={loading}>
              <strong>{row.title || 'Untitled workout'}</strong>
              <span>{row.workout_date} - {row.set_count} {row.set_count === 1 ? 'set' : 'sets'} - {formatWeight(row.volume_lbs, unit)}</span>
            </button>
            <div className="history-actions">
              <button type="button" onClick={() => onRepeat(row.id)}><Copy size={14} /> Log Again</button>
              <button type="button" onClick={() => onEdit(row.id)}>Edit</button>
              <button type="button" className="danger-btn" onClick={() => onDelete(row.id)} disabled={deletingWorkoutId === String(row.id)}>
                {deletingWorkoutId === String(row.id) ? 'Deleting' : 'Delete'}
              </button>
            </div>
          </article>
        ))}
        {!workouts.length && <p className="muted">{search ? 'No workouts match that search.' : 'Saved workouts will appear here.'}</p>}
      </div>
      {hasMore && (
        <button type="button" className="wide-save" onClick={onLoadMore} disabled={pageLoading}>
          <ChevronDown size={16} /> {pageLoading ? 'Loading' : 'Load More'}
        </button>
      )}
    </section>
  );
}

function TrainingHeatmapPanel({ dashboard }) {
  const daysByDate = new Map((dashboard.training_days || []).map((row) => [row.workout_date, row.workouts]));
  const days = Array.from({ length: 56 }, (_, index) => {
    const d = new Date();
    d.setDate(d.getDate() - (55 - index));
    const key = formatLocalDate(d);
    return { date: key, workouts: daysByDate.get(key) || 0 };
  });
  return (
    <section className="panel heatmap-panel">
      <div className="panel-head">
        <h2><CalendarDays size={18} /> Consistency</h2>
        <span className="muted">{dashboard.current_streak_days || 0} day streak</span>
      </div>
      <div className="heatmap-grid" aria-label="Training days in the last 8 weeks">
        {days.map((day) => (
          <span
            key={day.date}
            className={day.workouts ? 'trained' : ''}
            title={`${day.date}: ${day.workouts} ${day.workouts === 1 ? 'workout' : 'workouts'}`}
            aria-label={`${day.date}: ${day.workouts} ${day.workouts === 1 ? 'workout' : 'workouts'}`}
          />
        ))}
      </div>
    </section>
  );
}

function MuscleTargetPanel({ dashboard }) {
  const targets = dashboard.muscle_targets || [];
  const undertrained = targets.filter((row) => row.status !== 'met' && row.sets > 0).slice(0, 6);
  const rows = undertrained.length ? undertrained : targets.filter((row) => row.status === 'met').slice(0, 6);
  return (
    <section className="panel muscle-target-panel">
      <div className="panel-head">
        <h2><Target size={18} /> Weekly Muscle Targets</h2>
        <span className="muted">{targets.filter((row) => row.status === 'met').length}/{targets.length || 0} met</span>
      </div>
      <div className="target-list">
        {rows.map((row) => {
          const percent = row.target_sets ? Math.min(100, Math.round((row.sets / row.target_sets) * 100)) : 0;
          return (
            <div className="target-row" key={row.muscle}>
              <div>
                <strong>{muscleOptionLabel(row.muscle)}</strong>
                <span>{row.sets}/{row.target_sets} sets{row.remaining_sets ? ` - ${row.remaining_sets} remaining` : ''}</span>
              </div>
              <span className={`target-meter ${row.status === 'met' ? 'met' : ''}`} aria-label={`${row.muscle} ${percent}% of weekly target`}>
                <span style={{ width: `${percent}%` }} />
              </span>
            </div>
          );
        })}
        {!rows.length && <p className="muted">Log working sets to track weekly muscle coverage.</p>}
      </div>
    </section>
  );
}

function WorkoutDetailModal({ workout, onClose, onRepeat, onEdit, onDelete, deleting, unit }) {
  const { dialogRef, closeOnBackdrop } = useModalDialog(onClose);
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={closeOnBackdrop}>
      <section ref={dialogRef} className="panel draft-modal workout-detail-modal" role="dialog" aria-modal="true" aria-labelledby="workout-detail-title" tabIndex={-1}>
        <div className="panel-head">
          <div>
            <h2 id="workout-detail-title"><History size={18} /> {workout.title || 'Untitled workout'}</h2>
            <p className="muted">{workout.workout_date} - {workout.set_count} {workout.set_count === 1 ? 'set' : 'sets'} - {formatWeight(workout.volume_lbs, unit)}</p>
          </div>
          <button type="button" onClick={onClose}>Close</button>
        </div>
        <div className="workout-set-list">
          {workout.sets.map((set) => (
            <article className="workout-set-row" key={set.id}>
              <div>
                <strong>{set.exercise_name}</strong>
                <span>{set.primary_muscle} - {set.equipment}</span>
                {set.notes && <span>{set.notes}</span>}
              </div>
              <b>
                {formatWeight(set.effective_weight_lbs ?? set.weight_lbs, unit)} x {set.reps}
                {set.weight_mode && set.weight_mode !== 'external' ? ` (${WEIGHT_MODES.find(([value]) => value === set.weight_mode)?.[1] || set.weight_mode})` : ''}
              </b>
            </article>
          ))}
        </div>
        {workout.notes && <p className="workout-notes">{workout.notes}</p>}
        <div className="modal-actions">
          <button type="button" className="primary" onClick={onRepeat}><Copy size={16} /> Log Again</button>
          <button type="button" className="primary" onClick={onEdit}>Edit</button>
          <button type="button" className="danger-btn" onClick={onDelete} disabled={deleting}>{deleting ? 'Deleting' : 'Delete'}</button>
        </div>
      </section>
    </div>
  );
}

function HelpAboutModal({ onClose }) {
  const { dialogRef, closeOnBackdrop } = useModalDialog(onClose);
  return (
    <div className="modal-backdrop" onMouseDown={closeOnBackdrop}>
      <section ref={dialogRef} className="panel draft-modal help-modal" role="dialog" aria-modal="true" aria-labelledby="help-title" tabIndex={-1}>
        <div className="panel-head">
          <h2 id="help-title"><HelpCircle size={18} /> Help / About</h2>
          <button type="button" onClick={onClose}>Close</button>
        </div>
        <div className="help-grid">
          <div>
            <strong>JournalGym</strong>
            <span>Strength logging, progression trends, body tracking, backups, and per-user settings.</span>
          </div>
          <div>
            <strong>Keyboard</strong>
            <span>H or ? opens help. N starts or resumes a workout from the dashboard.</span>
          </div>
          <div>
            <strong>Data</strong>
            <span>Backups include workouts, measurements, goals, and settings.</span>
          </div>
        </div>
      </section>
    </div>
  );
}

function ExerciseCatalogPanel({ exercises, onSave }) {
  const [selectedId, setSelectedId] = useState('');
  const selected = exercises.find((exercise) => String(exercise.id) === String(selectedId)) || exercises[0];
  const [draft, setDraft] = useState(null);

  useEffect(() => {
    if (!selectedId && exercises[0]) setSelectedId(String(exercises[0].id));
  }, [selectedId, exercises]);

  useEffect(() => {
    if (!selected) {
      setDraft(null);
      return;
    }
    setDraft({
      name: selected.name,
      primary_muscle: selected.primary_muscle,
      equipment: selected.equipment,
      secondary_muscles: selected.secondary_muscles || [],
      alias_text: formatAliases(selected.aliases || []),
      notes: selected.notes || '',
      is_archived: false,
    });
  }, [selected?.id]);

  if (!exercises.length) {
    return (
      <section className="panel exercise-catalog-panel">
        <div className="panel-head"><h2>Exercise Catalog</h2></div>
        <p className="muted">Add an exercise to manage the catalog.</p>
      </section>
    );
  }

  function submit(e) {
    e.preventDefault();
    if (!selected || !draft) return;
    const { alias_text, ...exercisePayload } = draft;
    onSave(selected.id, { ...exercisePayload, aliases: parseAliases(alias_text || '') });
  }

  return (
    <form className="panel exercise-catalog-panel" onSubmit={submit}>
      <div className="panel-head"><h2>Exercise Catalog</h2></div>
      <div className="exercise-edit-grid">
        <label>
          Exercise
          <select value={selected?.id || ''} onChange={(e) => setSelectedId(e.target.value)}>
            {exercises.map((exercise) => <option key={exercise.id} value={exercise.id}>{exercise.name}</option>)}
          </select>
        </label>
        <label>Name<input value={draft?.name || ''} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></label>
        <label>Muscle<select value={draft?.primary_muscle || 'Chest'} onChange={(e) => setDraft({ ...draft, primary_muscle: e.target.value, secondary_muscles: (draft?.secondary_muscles || []).filter((muscle) => muscle !== e.target.value) })}>{MUSCLES.map((m) => <option key={m} value={m}>{muscleOptionLabel(m)}</option>)}</select></label>
        <label>Equipment<select value={draft?.equipment || 'Dumbbells'} onChange={(e) => setDraft({ ...draft, equipment: e.target.value })}>{EQUIPMENT.map((m) => <option key={m}>{m}</option>)}</select></label>
      </div>
      {MUSCLE_HINTS[draft?.primary_muscle] && <p className="muscle-hint">{MUSCLE_HINTS[draft.primary_muscle]}</p>}
      <MuscleCheckboxGroup
        label="Secondary Muscles"
        values={draft?.secondary_muscles || []}
        primary={draft?.primary_muscle}
        onChange={(values) => setDraft({ ...draft, secondary_muscles: values })}
      />
      <label>Aliases<input value={draft?.alias_text || ''} onChange={(e) => setDraft({ ...draft, alias_text: e.target.value })} placeholder="OHP, RDL, pec deck" /></label>
      <label>Notes<textarea value={draft?.notes || ''} onChange={(e) => setDraft({ ...draft, notes: e.target.value })} placeholder="Exercise notes" /></label>
      <div className="modal-actions">
        <button className="primary" disabled={!draft?.name?.trim()}>Save Exercise</button>
        <button type="button" className="danger-btn" onClick={() => selected && draft && onSave(selected.id, { ...draft, is_archived: true })}>
          Archive
        </button>
      </div>
    </form>
  );
}

function MuscleCheckboxGroup({ label, values = [], primary = '', onChange }) {
  const selected = values.filter((muscle) => muscle !== primary);
  return (
    <fieldset className="muscle-checks">
      <legend>{label}</legend>
      <div>
        {MUSCLES.filter((muscle) => muscle !== primary).map((muscle) => {
          const checked = selected.includes(muscle);
          return (
            <label key={muscle}>
              <input
                type="checkbox"
                checked={checked}
                disabled={!checked && selected.length >= 6}
                onChange={() => onChange(toggleMuscleSelection(selected, muscle))}
              />
              {muscleOptionLabel(muscle)}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

function ExerciseProgressStats({ stats, unit }) {
  if (!stats) return null;
  const items = [
    ['Best e1RM', stats.best_estimated_1rm ? formatWeight(stats.best_estimated_1rm, unit) : '-'],
    ['Max Weight', stats.max_weight_lbs ? formatWeight(stats.max_weight_lbs, unit) : '-'],
    ['Rep PR', stats.max_reps || '-'],
    ['e1RM / BW', formatBodyweightRatio(stats.bodyweight_ratio)],
    ['BW Reference', stats.latest_bodyweight_lbs ? `${formatWeight(stats.latest_bodyweight_lbs, unit)}${stats.latest_bodyweight_date ? ` on ${stats.latest_bodyweight_date}` : ''}` : '-'],
    ['Ratio Band', stats.strength_standard || '-'],
    ['Total Volume', formatWeight(stats.total_volume_lbs || 0, unit)],
    ['Sets', stats.total_sets || 0],
    ['Last Trained', stats.last_trained || '-'],
  ];
  return (
    <div className="progress-stat-grid">
      {items.map(([label, value]) => (
        <div className="mini-stat" key={label}>
          <span>{label}</span>
          <strong>{value}</strong>
        </div>
      ))}
    </div>
  );
}

function ExerciseProgressTable({ points, unit }) {
  return (
    <div className="progress-table">
      <div className="progress-table-head">
        <span>Date</span>
        <span>Best e1RM</span>
        <span>Max Weight</span>
        <span>Max Reps</span>
        <span>Volume</span>
        <span>Sets</span>
      </div>
      {points.slice(-PROGRESSION_POINT_DISPLAY_LIMIT).reverse().map((point) => (
        <div className="progress-table-row" key={`${point.workout_date}-${point.best_estimated_1rm}-${point.volume_lbs}`}>
          <span>{point.workout_date}</span>
          <span>{formatWeight(point.best_estimated_1rm, unit)}</span>
          <span>{formatWeight(point.max_weight_lbs, unit)}</span>
          <span>{point.max_reps}</span>
          <span>{formatWeight(point.volume_lbs || 0, unit)}</span>
          <span>{point.sets}</span>
        </div>
      ))}
    </div>
  );
}

function ExerciseSetHistory({ rows, unit }) {
  if (!rows?.length) return null;
  return (
    <div className="progress-table exercise-history-table" aria-label="Exercise set history">
      <div className="progress-table-head">
        <span>Date</span>
        <span>Load</span>
        <span>Reps</span>
      </div>
      {rows.map((row) => (
        <div className="progress-table-row" key={row.set_id}>
          <span>{row.workout_date}</span>
          <span>{formatWeight(row.effective_weight_lbs ?? row.weight_lbs, unit)}</span>
          <span>{row.reps}</span>
        </div>
      ))}
    </div>
  );
}

function MeasurementPanel({ measurements, form, setForm, onSave, onDelete, unit }) {
  const latest = measurements.find((row) => row.bodyweight_lbs !== null && row.bodyweight_lbs !== undefined);
  return (
    <section className="panel measurement-panel">
      <div className="panel-head">
        <div>
          <h2><Activity size={18} /> Body Tracking</h2>
          {latest && <p className="muted">Latest bodyweight {formatWeight(latest.bodyweight_lbs, unit)} on {latest.measured_date}</p>}
        </div>
      </div>
      <form onSubmit={onSave}>
        <div className="measurement-grid">
          <label>Date<input type="date" value={form.measured_date} onChange={(e) => setForm({ ...form, measured_date: e.target.value })} /></label>
          <label>Bodyweight<input type="number" inputMode="decimal" min={unit === 'kg' ? '14' : '30'} max={unit === 'kg' ? '454' : '1000'} step="0.1" value={toDisplayWeight(form.bodyweight_lbs, unit)} onChange={(e) => setForm({ ...form, bodyweight_lbs: fromDisplayWeight(e.target.value, unit) })} placeholder={unit} /></label>
          <label>Waist<input type="number" inputMode="decimal" min="0" max="200" step="0.1" value={form.waist_in} onChange={(e) => setForm({ ...form, waist_in: e.target.value })} placeholder="in" /></label>
          <label>Chest<input type="number" inputMode="decimal" min="0" max="200" step="0.1" value={form.chest_in} onChange={(e) => setForm({ ...form, chest_in: e.target.value })} placeholder="in" /></label>
          <label>Hip<input type="number" inputMode="decimal" min="0" max="200" step="0.1" value={form.hip_in} onChange={(e) => setForm({ ...form, hip_in: e.target.value })} placeholder="in" /></label>
          <label>Arm<input type="number" inputMode="decimal" min="0" max="100" step="0.1" value={form.arm_in} onChange={(e) => setForm({ ...form, arm_in: e.target.value })} placeholder="in" /></label>
          <label>Thigh<input type="number" inputMode="decimal" min="0" max="100" step="0.1" value={form.thigh_in} onChange={(e) => setForm({ ...form, thigh_in: e.target.value })} placeholder="in" /></label>
          <label>Photo URL<input value={form.photo_url} onChange={(e) => setForm({ ...form, photo_url: e.target.value })} placeholder="https://..." /></label>
          <label className="measurement-notes">Notes<textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} placeholder="Morning check-in, conditions, notes" /></label>
        </div>
        <button className="primary"><Save size={16} /> Save Measurement</button>
      </form>
      <div className="table-list measurement-list">
        {measurements.slice(0, MEASUREMENT_DISPLAY_LIMIT).map((row) => (
          <div className="table-row" key={row.id}>
            <div>
              <strong>{row.measured_date}</strong>
              <span>{[
                row.bodyweight_lbs !== null && row.bodyweight_lbs !== undefined ? formatWeight(row.bodyweight_lbs, unit) : '',
                row.waist_in !== null && row.waist_in !== undefined ? `waist ${row.waist_in} in` : '',
                row.chest_in !== null && row.chest_in !== undefined ? `chest ${row.chest_in} in` : '',
                row.hip_in !== null && row.hip_in !== undefined ? `hip ${row.hip_in} in` : '',
                row.arm_in !== null && row.arm_in !== undefined ? `arm ${row.arm_in} in` : '',
                row.thigh_in !== null && row.thigh_in !== undefined ? `thigh ${row.thigh_in} in` : '',
              ].filter(Boolean).join(' - ') || 'Measurement logged'}</span>
              {row.photo_url && <a href={row.photo_url} target="_blank" rel="noreferrer">Progress photo</a>}
              {row.notes && <span>{row.notes}</span>}
            </div>
            <button type="button" className="danger-btn" onClick={() => onDelete(row.id)}>Delete</button>
          </div>
        ))}
        {!measurements.length && <p className="muted">Bodyweight, measurements, and progress photo links will appear here.</p>}
      </div>
    </section>
  );
}

function GoalPanel({ goals, form, setForm, exerciseOptions, selectedExerciseId, onSave, onDelete, unit }) {
  const isStrength = form.kind === 'one_rep_max';
  const selectedGoalExercise = form.exercise_id || selectedExerciseId || exerciseOptions[0]?.id || '';
  return (
    <section className="panel goal-panel">
      <div className="panel-head">
        <div>
          <h2><Target size={18} /> Goals</h2>
          <p className="muted">Track target 1RM, bodyweight, and date goals.</p>
        </div>
      </div>
      <form onSubmit={onSave} className="goal-form">
        <label>Type
          <select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
            <option value="one_rep_max">Target 1RM</option>
            <option value="bodyweight">Target Bodyweight</option>
          </select>
        </label>
        {isStrength && (
          <label>Exercise
            <select value={selectedGoalExercise} onChange={(e) => setForm({ ...form, exercise_id: e.target.value })}>
              {exerciseOptions.map((exercise) => <option key={exercise.id} value={exercise.id}>{exercise.name}</option>)}
            </select>
          </label>
        )}
        <label>Target
          <input inputMode="decimal" value={form.target_value_lbs} onChange={(e) => setForm({ ...form, target_value_lbs: e.target.value })} placeholder={unit} />
        </label>
        <label>Date
          <input type="date" value={form.target_date} onChange={(e) => setForm({ ...form, target_date: e.target.value })} />
        </label>
        <label className="goal-notes">Notes
          <input value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} placeholder="Meet prep, cut, bulk" />
        </label>
        <button className="primary"><Save size={16} /> Save Goal</button>
      </form>
      <div className="goal-list">
        {goals.map((goal) => (
          <div className="goal-row" key={goal.id}>
            <div>
              <strong>{goal.kind === 'bodyweight' ? 'Bodyweight' : goal.exercise_name || '1RM Goal'}</strong>
              <span>
                {goal.current_value_lbs ? `${formatWeight(goal.current_value_lbs, unit)} current - ` : ''}
                {formatWeight(goal.target_value_lbs, unit)} target{goal.target_date ? ` by ${goal.target_date}` : ''}
              </span>
              {goal.delta_lbs !== null && goal.delta_lbs !== undefined && (
                <span>{goal.status === 'met' ? 'Target met' : `${formatWeight(Math.abs(goal.delta_lbs), unit)} away`}</span>
              )}
            </div>
            <button type="button" className="icon-btn danger-icon" onClick={() => onDelete(goal.id)} aria-label="Delete goal">
              <Trash2 size={15} />
            </button>
          </div>
        ))}
        {!goals.length && <p className="muted">No saved goals.</p>}
      </div>
    </section>
  );
}

function SettingsPanel({ form, setForm, onSave }) {
  return (
    <section className="panel settings-panel">
      <div className="panel-head">
        <h2><Shield size={18} /> Settings</h2>
      </div>
      <form onSubmit={onSave} className="settings-form">
        <label>Units
          <select value={form.unit} onChange={(e) => setForm({ ...form, unit: e.target.value })}>
            <option value="lb">lb</option>
            <option value="kg">kg</option>
          </select>
        </label>
        <label>Default Rest
          <input inputMode="numeric" value={form.default_rest_seconds} onChange={(e) => setForm({ ...form, default_rest_seconds: e.target.value })} placeholder="seconds" />
        </label>
        <label>Default Reps
          <input inputMode="numeric" value={form.default_reps} onChange={(e) => setForm({ ...form, default_reps: e.target.value })} placeholder="reps" />
        </label>
        <label>Theme
          <select value={form.theme} onChange={(e) => setForm({ ...form, theme: e.target.value })}>
            <option value="system">System</option>
            <option value="dark">Dark</option>
            <option value="light">Light</option>
          </select>
        </label>
        <label className="settings-check">
          <input type="checkbox" checked={Boolean(form.reminder_enabled)} onChange={(e) => setForm({ ...form, reminder_enabled: e.target.checked })} />
          Train reminder
        </label>
        <label>Reminder Hour
          <input inputMode="numeric" min="0" max="23" value={form.reminder_hour} onChange={(e) => setForm({ ...form, reminder_hour: e.target.value })} placeholder="18" />
        </label>
        <button className="primary"><Save size={16} /> Save Settings</button>
      </form>
    </section>
  );
}

function AccountSelfServicePanel({ onWipeData, onDeleteAccount, onLogoutAll }) {
  return (
    <section className="panel account-self-service">
      <div className="panel-head">
        <h2><KeyRound size={18} /> Account</h2>
      </div>
      <div className="account-actions">
        <button type="button" onClick={onLogoutAll}><LogOut size={16} /> Log Out All Devices</button>
        <button type="button" className="danger-btn" onClick={onWipeData}><Trash2 size={16} /> Wipe My Data</button>
        <button type="button" className="danger-btn" onClick={onDeleteAccount}><Trash2 size={16} /> Delete My Account</button>
      </div>
    </section>
  );
}

function BackupPanel({ onDownload, onImport }) {
  return (
    <section className="panel backup-panel">
      <div className="panel-head">
        <h2><Save size={18} /> Data Backup</h2>
        <div className="panel-actions">
          <button type="button" onClick={() => onDownload('json')}>JSON</button>
          <button type="button" onClick={() => onDownload('csv')}>CSV</button>
        </div>
      </div>
      <label className="import-file">
        Import JSON
        <input type="file" accept="application/json,.json" onChange={(e) => onImport(e.target.files?.[0])} />
      </label>
    </section>
  );
}

function DraftManager({ drafts, activeDraftId, draftLimit, draftCapNotice, onClose, onResume, onDelete, onNew }) {
  const { dialogRef, closeOnBackdrop } = useModalDialog(onClose);
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={closeOnBackdrop}>
      <section ref={dialogRef} className="panel draft-modal" role="dialog" aria-modal="true" aria-labelledby="draft-manager-title" tabIndex={-1}>
        <div className="panel-head">
          <h2 id="draft-manager-title"><ListChecks size={18} /> Drafts</h2>
          <button type="button" onClick={onClose}>Close</button>
        </div>
        <p className="draft-limit-note">
          {draftCapNotice || `${drafts.length}/${draftLimit} draft slots used. New drafts beyond the limit remove the oldest saved draft.`}
        </p>
        <div className="draft-list">
          {drafts.map((draft) => {
            const completeSets = countCompleteSets(draft.workout);
            return (
              <article className="draft-row" key={draft.id}>
                <div>
                  <strong>{describeWorkoutDraft(draft.workout)}</strong>
                  <span>{draft.workout.workout_date} · {completeSets}/{draft.workout.sets.length} complete {draft.workout.sets.length === 1 ? 'set' : 'sets'}{draft.id === activeDraftId ? ' · active' : ''}</span>
                </div>
                <div className="draft-row-actions">
                  <button type="button" className="primary" onClick={() => onResume(draft.id)}>
                    <Play size={15} />
                    Resume
                  </button>
                  <button type="button" className="danger-btn" onClick={() => onDelete(draft.id)}>
                    <Trash2 size={15} />
                    Delete
                  </button>
                </div>
              </article>
            );
          })}
          {!drafts.length && <p className="muted">No saved drafts.</p>}
        </div>
        <button type="button" className="wide-save" onClick={onNew}>
          <Plus size={16} />
          New Draft
        </button>
      </section>
    </div>
  );
}

function WorkoutLogPage({
  mode,
  user,
  workout,
  draftSavedAt,
  draftCount,
  setWorkout,
  exerciseOptions,
  priorityExerciseIds,
  lastPerformed,
  unit,
  restSeconds,
  restRemaining,
  setRestSeconds,
  onStartRest,
  onResetRest,
  saving,
  error,
  updateSet,
  addSet,
  duplicateSet,
  removeSet,
  onDrafts,
  onSaveTemplate,
  onSave,
  onDiscard,
  onBack,
}) {
  const isStart = mode === 'start';
  const isEdit = mode === 'edit';
  const title = isEdit ? 'Edit Workout' : 'Start Workout';
  const saveLabel = isEdit ? 'Save Changes' : 'Save Workout';
  const topRef = useRef(null);
  const bottomRef = useRef(null);
  const [autoRest, setAutoRest] = useState(false);
  const [bulkEntry, setBulkEntry] = useState('');
  const [bulkMessage, setBulkMessage] = useState('');
  const completeSets = workout.sets.filter((set) => set.exercise_id && set.weight_lbs !== '' && set.reps !== '').length;
  const completionPercent = workout.sets.length ? Math.round((completeSets / workout.sets.length) * 100) : 0;
  const canSave = completeSets > 0;
  const totalVolume = workout.sets.reduce((sum, set) => {
    if (!set.exercise_id || (set.weight_mode !== 'bodyweight' && set.weight_lbs === '') || set.reps === '') return sum;
    const weight = effectiveSetWeight(set, workout.bodyweight_lbs);
    const reps = Number(set.reps);
    return Number.isFinite(weight) && Number.isFinite(reps) ? sum + weight * reps : sum;
  }, 0);
  function addSetAndMaybeRest(copyLast) {
    addSet(copyLast);
    if (autoRest) onStartRest(restSeconds);
  }
  function duplicateSetAndMaybeRest(index) {
    duplicateSet(index);
    if (autoRest) onStartRest(restSeconds);
  }
  function applyBulkEntry() {
    try {
      const parsed = parseBulkSetEntry(bulkEntry);
      let template = null;
      for (let index = workout.sets.length - 1; index >= 0; index -= 1) {
        if (workout.sets[index]?.exercise_id) {
          template = workout.sets[index];
          break;
        }
      }
      if (!template) throw new Error('Choose an exercise on a set before using bulk add.');
      const generated = Array.from({ length: parsed.count }, () => blankSet({
        exercise_id: template.exercise_id,
        weight_mode: template.weight_mode || 'external',
        weight_lbs: parsed.weight === '' ? template.weight_lbs : fromDisplayWeight(parsed.weight, unit),
        reps: parsed.reps,
      }));
      setWorkout((prev) => {
        const placeholder = prev.sets.length === 1 && prev.sets[0].exercise_id && prev.sets[0].reps === '' && prev.sets[0].weight_lbs === '';
        return { ...prev, sets: placeholder ? generated : [...prev.sets, ...generated] };
      });
      setBulkEntry('');
      setBulkMessage(`Added ${parsed.count} sets.`);
      if (autoRest) onStartRest(restSeconds);
    } catch (err) {
      setBulkMessage(err.message);
    }
  }
  return (
    <>
      <SkipLink />
      <main id="main-content" className={`log-page ${isStart ? 'start-flow' : 'edit-flow'}`}>
      <form className="log-shell" onSubmit={onSave}>
        <header className="log-top" ref={topRef}>
          <button type="button" className="icon-btn back-btn" onClick={onBack} aria-label="Back">
            <ArrowLeft size={19} />
          </button>
          <div>
            <h1>{title}</h1>
            <p>{user.display_name} · {completeSets}/{workout.sets.length} complete · {formatWeight(totalVolume, unit)} volume</p>
            {!isEdit && <span className="draft-save-status">{formatDraftSavedAt(draftSavedAt)}</span>}
            <span
              className="completion-bar"
              role="progressbar"
              aria-label="Sets complete"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={completionPercent}
              aria-valuetext={`${completionPercent}% sets complete`}
            >
              <span style={{ width: `${completionPercent}%` }} />
            </span>
          </div>
          <div className="log-top-actions">
            {draftCount > 0 && (
              <button type="button" className="icon-btn log-drafts-btn" onClick={onDrafts} aria-label="Open drafts">
                <ListChecks size={18} />
              </button>
            )}
            <button type="button" className="icon-btn jump-bottom-btn" onClick={() => scrollElementIntoView(bottomRef.current, { behavior: 'smooth', block: 'end' })} aria-label="Jump to workout controls">
              <ChevronDown size={18} />
            </button>
            <button className="primary save-top" disabled={saving || !canSave}>
              <Save size={16} />
              {saving ? 'Saving' : canSave ? (isEdit ? 'Update' : 'Save') : 'Need Set'}
            </button>
          </div>
        </header>

        {error && <div className="error" role="alert">{error}</div>}

        <section className="log-meta">
          <div className="date-field field-with-presets">
            <label>
              Date
              <input type="date" max={today()} value={workout.workout_date} onChange={(e) => setWorkout({ ...workout, workout_date: e.target.value })} />
            </label>
            <span className="field-presets">
              <button type="button" onClick={() => setWorkout({ ...workout, workout_date: today() })}>Today</button>
              <button type="button" onClick={() => setWorkout({ ...workout, workout_date: daysAgo(1) })}>Yesterday</button>
            </span>
          </div>
          <div className="title-field field-with-presets">
            <label>
              Title
              <input value={workout.title} onChange={(e) => setWorkout({ ...workout, title: e.target.value })} placeholder="Push, Pull, Legs..." />
            </label>
            <span className="field-presets">
              {WORKOUT_TITLE_PRESETS.map((title) => (
                <button type="button" key={title} onClick={() => setWorkout({ ...workout, title })}>{title}</button>
              ))}
            </span>
          </div>
          <label>
            Bodyweight
            <input type="number" inputMode="decimal" min={unit === 'kg' ? '14' : '30'} max={unit === 'kg' ? '454' : '1000'} step="0.1" value={toDisplayWeight(workout.bodyweight_lbs, unit)} onChange={(e) => setWorkout({ ...workout, bodyweight_lbs: fromDisplayWeight(e.target.value, unit) })} placeholder={unit} />
          </label>
        </section>

        <section className="log-sets">
          <div className="bulk-set-entry">
            <label>
              Bulk Sets
              <input value={bulkEntry} onChange={(e) => setBulkEntry(e.target.value)} placeholder="3x8 @135" />
            </label>
            <button type="button" onClick={applyBulkEntry}>Add Sets</button>
            {bulkMessage && <span>{bulkMessage}</span>}
          </div>
          {workout.sets.map((set, index) => (
            <SetEditor
              key={set.client_id || index}
              compact={!isStart}
              set={set}
              index={index}
              exerciseOptions={exerciseOptions}
              priorityExerciseIds={priorityExerciseIds}
              lastPerformed={lastPerformed}
              unit={unit}
              updateSet={updateSet}
              duplicateSet={duplicateSetAndMaybeRest}
              removeSet={removeSet}
              canRemove={workout.sets.length > 1}
            />
          ))}
        </section>

        <div className="log-bottom" ref={bottomRef}>
          <button type="button" className="jump-top-btn" onClick={() => scrollElementIntoView(topRef.current, { behavior: 'smooth', block: 'start' })}>
            <ChevronUp size={16} />
            Top
          </button>
          <div className="log-add-actions">
            <button type="button" onClick={() => addSetAndMaybeRest(true)}><Plus size={16} /> Copy Set</button>
            <button type="button" onClick={() => addSetAndMaybeRest(false)}><Plus size={16} /> Blank Set</button>
          </div>
          <button type="button" onClick={onSaveTemplate}><ListChecks size={16} /> Save as Template</button>
          <button type="button" className="danger-btn" onClick={onDiscard}><Trash2 size={16} /> Discard Workout</button>
          <RestTimer
            autoRest={autoRest}
            onAutoRestChange={setAutoRest}
            selectedSeconds={restSeconds}
            remaining={restRemaining}
            onSelectedSecondsChange={setRestSeconds}
            onStart={onStartRest}
            onReset={onResetRest}
          />
          <PlateCalculator unit={unit} />
          <OneRepMaxCalculator unit={unit} />
          <label className="notes-field">Notes<textarea value={workout.notes} onChange={(e) => setWorkout({ ...workout, notes: e.target.value })} placeholder="Session notes" /></label>
          <button className="primary wide-save" disabled={saving || !canSave}>
            <Save size={16} />
            {saving ? 'Saving' : canSave ? saveLabel : 'Need 1 Complete Set'}
          </button>
        </div>
      </form>
      </main>
    </>
  );
}

function RestTimer({ autoRest, onAutoRestChange, selectedSeconds, remaining, onSelectedSecondsChange, onStart, onReset }) {
  const minutes = String(Math.floor(remaining / 60)).padStart(2, '0');
  const seconds = String(remaining % 60).padStart(2, '0');
  const selectedMinutes = Math.floor(selectedSeconds / 60);

  return (
    <section className={`rest-timer ${remaining ? 'rest-active' : ''}`} aria-label="Rest timer">
      <div>
        <span>Rest</span>
        <strong>{minutes}:{seconds}</strong>
      </div>
      <div className="rest-actions">
        {REST_PRESETS_SECONDS.map((secondsOption) => (
          <button
            type="button"
            key={secondsOption}
            className={selectedSeconds === secondsOption ? 'active' : ''}
            onClick={() => {
              onSelectedSecondsChange(secondsOption);
              onStart(secondsOption);
            }}
          >
            {Math.floor(secondsOption / 60)}:00
          </button>
        ))}
        <button type="button" onClick={onReset}>Reset</button>
      </div>
      <label className="auto-rest-toggle">
        <input type="checkbox" checked={autoRest} onChange={(e) => onAutoRestChange(e.target.checked)} />
        Auto {selectedMinutes}:00 after add set
      </label>
    </section>
  );
}

function GlobalRestTimer({ remaining, onReset }) {
  const minutes = String(Math.floor(remaining / 60)).padStart(2, '0');
  const seconds = String(remaining % 60).padStart(2, '0');
  return (
    <section className="global-rest-timer" aria-label="Active rest timer">
      <div>
        <span>Rest</span>
        <strong>{minutes}:{seconds}</strong>
      </div>
      <button type="button" onClick={onReset}>Reset</button>
    </section>
  );
}

function PlateCalculator({ unit }) {
  const [target, setTarget] = useState(unit === 'kg' ? '100' : '185');
  const plan = platePlan(target, unit);

  useEffect(() => {
    setTarget(unit === 'kg' ? '100' : '185');
  }, [unit]);

  return (
    <section className="plate-calculator" aria-label="Plate calculator">
      <div className="plate-calculator-head">
        <strong>Plate Calculator</strong>
        <label>
          Target
          <input inputMode="decimal" value={target} onChange={(e) => setTarget(e.target.value)} placeholder={unit} />
        </label>
      </div>
      {plan && (
        <div className="plate-result">
          <span>{plan.bar} {unit} bar</span>
          {plan.plates.length ? (
            <strong>{plan.plates.map((row) => `${row.count} x ${row.plate}`).join(' + ')} per side</strong>
          ) : (
            <strong>No plates per side</strong>
          )}
          {Math.abs(plan.remainder) >= 0.01 && <span>{plan.remainder > 0 ? `${plan.remainder} ${unit} short per side` : 'Below bar weight'}</span>}
        </div>
      )}
    </section>
  );
}

function OneRepMaxCalculator({ unit }) {
  const [weight, setWeight] = useState(unit === 'kg' ? '100' : '185');
  const [reps, setReps] = useState('5');
  const weightLbs = Number(fromDisplayWeight(weight, unit));
  const e1rm = estimateOneRepMax(weightLbs, reps);
  const warmups = e1rm
    ? [
        ['40%', 0.4, '5'],
        ['55%', 0.55, '5'],
        ['70%', 0.7, '3'],
        ['80%', 0.8, '2'],
        ['90%', 0.9, '1'],
      ]
    : [];

  useEffect(() => {
    setWeight(unit === 'kg' ? '100' : '185');
  }, [unit]);

  return (
    <section className="one-rep-calculator" aria-label="One rep max calculator">
      <div className="plate-calculator-head">
        <strong>1RM & Warm-up</strong>
        <label>
          Weight
          <input inputMode="decimal" value={weight} onChange={(e) => setWeight(e.target.value)} placeholder={unit} />
        </label>
        <label>
          Reps
          <input inputMode="numeric" value={reps} onChange={(e) => setReps(e.target.value)} placeholder="reps" />
        </label>
      </div>
      {e1rm && (
        <div className="plate-result">
          <span>Estimated 1RM</span>
          <strong>{formatWeight(e1rm, unit)}</strong>
          <span>{warmups.map(([label, pct, warmupReps]) => `${label}: ${formatWeight(e1rm * pct, unit)} x ${warmupReps}`).join(' · ')}</span>
        </div>
      )}
    </section>
  );
}

function SetEditor({ compact, set, index, exerciseOptions, priorityExerciseIds, lastPerformed, unit, updateSet, duplicateSet, removeSet, canRemove }) {
  const [showNotes, setShowNotes] = useState(Boolean(set.notes));
  const missing = missingSetFields(set);
  const complete = missing.length === 0;
  function adjustWeight(delta) {
    const current = Number(set.weight_lbs);
    const next = Math.max(0, (Number.isFinite(current) ? current : 0) + delta);
    updateSet(index, 'weight_lbs', String(next));
  }
  return (
    <article className={`set-card ${compact ? 'compact-set' : ''} ${complete ? 'set-complete' : ''}`}>
      <div className="set-card-head">
        <strong>Set {index + 1}</strong>
        <div className="set-card-actions">
          {complete && <span className="set-status">Complete</span>}
          <button type="button" className="copy-set-btn" onClick={() => duplicateSet(index)}>
            <Copy size={14} />
            Copy
          </button>
          <button type="button" className={`icon-btn set-note-btn ${set.notes ? 'has-note' : ''}`} onClick={() => setShowNotes((value) => !value)} aria-label={`Set ${index + 1} notes`}>
            <StickyNote size={15} />
          </button>
          <button type="button" className="icon-btn danger-icon" onClick={() => removeSet(index)} disabled={!canRemove} aria-label={`Remove set ${index + 1}`}>
            <Trash2 size={15} />
          </button>
        </div>
      </div>
      <ExercisePicker
        value={set.exercise_id}
        exerciseOptions={exerciseOptions}
        priorityExerciseIds={priorityExerciseIds}
        lastPerformed={lastPerformed}
        unit={unit}
        onChange={(value) => updateSet(index, 'exercise_id', value)}
      />
      <div className="set-input-grid">
        <label>
          Load Mode
          <select value={set.weight_mode || 'external'} onChange={(e) => updateSet(index, 'weight_mode', e.target.value)}>
            {WEIGHT_MODES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <div className="weight-field field-with-presets">
          <label>
            {set.weight_mode === 'assisted' ? 'Assistance' : set.weight_mode === 'added' ? 'Added Weight' : 'Weight'}
            <input inputMode="decimal" value={toDisplayWeight(set.weight_lbs, unit)} onChange={(e) => updateSet(index, 'weight_lbs', fromDisplayWeight(e.target.value, unit))} placeholder={unit} />
          </label>
          <span className="weight-steppers">
            <button type="button" onClick={() => adjustWeight(unit === 'kg' ? -2.5 / KG_PER_LB : -5)}>{unit === 'kg' ? '-2.5' : '-5'}</button>
            <button type="button" onClick={() => adjustWeight(unit === 'kg' ? 2.5 / KG_PER_LB : 5)}>{unit === 'kg' ? '+2.5' : '+5'}</button>
          </span>
        </div>
        <div className="rep-field field-with-presets">
          <label>
            Reps
            <input inputMode="numeric" value={set.reps} onChange={(e) => updateSet(index, 'reps', e.target.value)} placeholder="reps" />
          </label>
          <span className="rep-presets">
            {REP_PRESETS.map((reps) => (
              <button type="button" key={reps} className={String(set.reps) === reps ? 'active' : ''} onClick={() => updateSet(index, 'reps', reps)}>{reps}</button>
            ))}
          </span>
        </div>
      </div>
      {showNotes && (
        <label className="set-notes-field">
          Set Notes
          <textarea value={set.notes} onChange={(e) => updateSet(index, 'notes', e.target.value)} placeholder="Form cue, partials..." />
        </label>
      )}
      {!complete && <p className="set-missing">Missing {missing.join(', ')}</p>}
    </article>
  );
}

function ExercisePicker({ value, exerciseOptions, priorityExerciseIds = [], lastPerformed = {}, unit, onChange, label = 'Exercise', className = '', showSelectedMeta = true }) {
  const selected = exerciseOptions.find((exercise) => String(exercise.id) === String(value));
  const selectedLast = selected ? formatLastPerformed(lastPerformed[String(selected.id)], unit) : '';
  const pickerId = useId();
  const resultsId = `${pickerId}-results`;
  const pickerRef = useRef(null);
  const inputRef = useRef(null);
  const [query, setQuery] = useState(selected?.name || '');
  const [open, setOpen] = useState(false);
  const [typedDismissPrimed, setTypedDismissPrimed] = useState(false);
  const [inputFocused, setInputFocused] = useState(false);
  const [visibleLimit, setVisibleLimit] = useState(PICKER_PAGE_SIZE);
  const [activeIndex, setActiveIndex] = useState(0);

  useEffect(() => {
    if (!open) setQuery(selected?.name || '');
  }, [selected?.id, selected?.name, open]);

  useEffect(() => {
    setVisibleLimit(PICKER_PAGE_SIZE);
  }, [query]);

  useEffect(() => {
    setActiveIndex(0);
  }, [query, open]);

  useEffect(() => {
    if (!open) return undefined;
    function handlePointerDown(event) {
      if (pickerRef.current?.contains(event.target)) return;
      if (query.trim() && inputFocused) {
        inputRef.current?.blur();
        setTypedDismissPrimed(true);
        return;
      }
      if (query.trim() && !typedDismissPrimed) {
        setTypedDismissPrimed(true);
        return;
      }
      setOpen(false);
      setTypedDismissPrimed(false);
    }
    document.addEventListener('pointerdown', handlePointerDown);
    return () => document.removeEventListener('pointerdown', handlePointerDown);
  }, [open, query, inputFocused, typedDismissPrimed]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    let rows;
    if (needle) {
      rows = exerciseOptions
        .map((exercise) => {
          const name = exercise.name.toLowerCase();
          const muscle = exercise.primary_muscle.toLowerCase();
          const equipment = exercise.equipment.toLowerCase();
          const secondary = (exercise.secondary_muscles || []).join(' ').toLowerCase();
          const savedAliases = (exercise.aliases || []).join(' ').toLowerCase();
          const notes = (exercise.notes || '').toLowerCase();
          const aliases = [
            savedAliases,
            muscle === 'abs' || secondary.includes('abs') ? 'ab abdominal abdominals rectus rectus abdominis' : '',
          ].join(' ');
          const searchable = `${name} ${muscle} ${equipment} ${secondary} ${notes} ${aliases}`;
          let score = 99;
          if (name.startsWith(needle)) score = 0;
          else if (name.includes(needle)) score = 1;
          else if (muscle.includes(needle)) score = 2;
          else if (secondary.includes(needle)) score = 3;
          else if (savedAliases.includes(needle)) score = 4;
          else if (equipment.includes(needle)) score = 5;
          else if (searchable.includes(needle)) score = 6;
          return { exercise, score };
        })
        .filter((row) => row.score < 99)
        .sort((a, b) => a.score - b.score || a.exercise.name.localeCompare(b.exercise.name))
        .map((row) => row.exercise);
    } else {
      const recent = priorityExerciseIds
        .map((id) => exerciseOptions.find((exercise) => String(exercise.id) === String(id)))
        .filter(Boolean);
      const recentSet = new Set(recent.map((exercise) => String(exercise.id)));
      rows = [
        ...recent,
        ...exerciseOptions.filter((exercise) => !recentSet.has(String(exercise.id))),
      ];
    }
    return rows;
  }, [exerciseOptions, query, priorityExerciseIds]);
  const visibleExercises = filtered.slice(0, visibleLimit);
  const hiddenCount = Math.max(0, filtered.length - visibleExercises.length);
  const clampedActiveIndex = Math.min(activeIndex, Math.max(visibleExercises.length - 1, 0));
  const activeExercise = visibleExercises[clampedActiveIndex];

  function choose(exercise) {
    onChange(String(exercise.id));
    setQuery(exercise.name);
    setOpen(false);
    setTypedDismissPrimed(false);
  }

  function clearSearch() {
    setQuery('');
    onChange('');
    setOpen(true);
    setTypedDismissPrimed(false);
    inputRef.current?.focus();
  }

  function handleSearchKeyDown(event) {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setOpen(true);
      setTypedDismissPrimed(false);
      setActiveIndex((index) => Math.min(index + 1, Math.max(visibleExercises.length - 1, 0)));
      return;
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      setOpen(true);
      setTypedDismissPrimed(false);
      setActiveIndex((index) => Math.max(index - 1, 0));
      return;
    }
    if (event.key === 'Enter' && open && activeExercise) {
      event.preventDefault();
      choose(activeExercise);
      return;
    }
    if (event.key === 'Escape' && open) {
      event.preventDefault();
      setOpen(false);
      setTypedDismissPrimed(false);
    }
  }

  return (
    <div className={`exercise-picker ${className}`.trim()} ref={pickerRef}>
      <label className="exercise-field">
        {label}
        <span className="search-input-wrap">
          <Search size={15} />
          <input
            ref={inputRef}
            type="text"
            role="combobox"
            aria-expanded={open}
            aria-autocomplete="list"
            aria-controls={resultsId}
            aria-activedescendant={open && activeExercise ? `${resultsId}-option-${activeExercise.id}` : undefined}
            value={query}
            onFocus={() => {
              setInputFocused(true);
              setOpen(true);
              setTypedDismissPrimed(false);
            }}
            onBlur={() => {
              setInputFocused(false);
              if (query.trim()) setTypedDismissPrimed(true);
            }}
            onChange={(e) => {
              setQuery(e.target.value);
              setOpen(true);
              setTypedDismissPrimed(false);
            }}
            onKeyDown={handleSearchKeyDown}
            placeholder="Search exercise"
            autoComplete="off"
          />
          {query && (
            <button type="button" className="search-clear-btn" onMouseDown={(e) => e.preventDefault()} onClick={clearSearch} aria-label="Clear exercise search">
              <X size={14} />
            </button>
          )}
        </span>
      </label>
      {open && (
        <div className="exercise-results" id={resultsId} role="listbox">
          <div className="exercise-results-label">
            {query.trim() ? 'Matches' : priorityExerciseIds.length ? 'Frequent first' : 'All exercises'}
            <span>{filtered.length} found</span>
          </div>
          {visibleExercises.map((exercise, resultIndex) => (
            <button
              type="button"
              id={`${resultsId}-option-${exercise.id}`}
              role="option"
              aria-selected={activeExercise?.id === exercise.id}
              className={activeExercise?.id === exercise.id ? 'active-result' : ''}
              key={exercise.id}
              onMouseEnter={() => setActiveIndex(resultIndex)}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => choose(exercise)}
            >
              <span>{exercise.name}</span>
              <small>
                {exercise.primary_muscle} - {exercise.equipment}
                {!!exercise.secondary_muscles?.length && ` - also ${exercise.secondary_muscles.join(', ')}`}
              </small>
              {exercise.notes && <small className="exercise-cue">{exercise.notes}</small>}
              {lastPerformed[String(exercise.id)] && <small>Last {formatLastPerformed(lastPerformed[String(exercise.id)], unit)}</small>}
            </button>
          ))}
          {hiddenCount > 0 && (
            <button type="button" className="show-more-results" onMouseDown={(e) => e.preventDefault()} onClick={() => setVisibleLimit((limit) => limit + PICKER_PAGE_SIZE)}>
              Show {PICKER_PAGE_SIZE} more ({hiddenCount} remaining)
            </button>
          )}
          {!filtered.length && <p className="muted">No exercises match.</p>}
        </div>
      )}
      {showSelectedMeta && selected?.notes && <p className="exercise-cue selected-cue">{selected.notes}</p>}
      {showSelectedMeta && selectedLast && <p className="last-performed">Last {selectedLast}</p>}
    </div>
  );
}

function AuthGate({ setupRequired, error, onSubmit }) {
  const [form, setForm] = useState({ username: '', display_name: '', pin: '' });
  const [saving, setSaving] = useState(false);
  const mode = setupRequired ? 'setup' : 'login';

  async function submit(e) {
    e.preventDefault();
    setSaving(true);
    await onSubmit(mode, form);
    setSaving(false);
  }

  return (
    <>
      <SkipLink />
      <main id="main-content" className="auth-main">
      <form className="auth-panel" onSubmit={submit}>
        <div className="auth-icon"><Shield size={20} /></div>
        <div>
          <h1>{setupRequired ? 'Set up JournalGym' : 'JournalGym'}</h1>
          <p className="muted">{setupRequired ? 'Create the first admin user.' : 'Sign in with your username and PIN.'}</p>
        </div>
        {error && <div className="error" role="alert">{error}</div>}
        <label>Username<input autoFocus value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} /></label>
        {setupRequired && (
          <label>Name<input value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} /></label>
        )}
        <label>PIN<input type="password" inputMode="numeric" value={form.pin} onChange={(e) => setForm({ ...form, pin: e.target.value })} placeholder="6-12 digits" /></label>
        <button className="primary" disabled={saving}>{saving ? 'Working' : setupRequired ? 'Create Admin' : 'Login'}</button>
      </form>
      </main>
    </>
  );
}

function SkeletonCard({ className = '' }) {
  return <div className={`skeleton-card ${className}`} aria-hidden="true" />;
}

function Metric({ icon, label, value }) {
  return (
    <div className="metric">
      {icon}
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ChartShell({ loading, empty, children }) {
  if (loading) return <SkeletonCard className="chart-skeleton" />;
  if (empty) return <div className="empty">Log workouts to populate this chart.</div>;
  return children;
}

function ChartPanel({ title, icon = null, controls = null, children, defaultOpen = true, forceOpenKey = null }) {
  const storageKey = `fitnessChartOpen:${title}`;
  const forceOpenSeenRef = useRef(forceOpenKey);
  const [open, setOpen] = useState(() => {
    try {
      const stored = window.localStorage.getItem(storageKey);
      return stored === null ? defaultOpen : stored === 'true';
    } catch {
      return defaultOpen;
    }
  });
  useEffect(() => {
    try {
      window.localStorage.setItem(storageKey, String(open));
    } catch {
      // Storage may be disabled.
    }
  }, [open, storageKey]);
  useEffect(() => {
    if (forceOpenSeenRef.current === forceOpenKey) return;
    forceOpenSeenRef.current = forceOpenKey;
    if (forceOpenKey !== null) setOpen(true);
  }, [forceOpenKey]);
  return (
    <section className="panel chart-panel">
      <div className="panel-head">
        <h2>{icon}{title}</h2>
        <div className="panel-actions">
          {controls}
          <button type="button" className="chart-toggle" onClick={() => setOpen((value) => !value)}>
            {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
            {open ? 'Hide' : 'Show'}
          </button>
        </div>
      </div>
      {open && <div className="chart-body">{children}</div>}
    </section>
  );
}

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <>
          <SkipLink />
          <main id="main-content" className="auth-main">
            <section className="auth-panel" role="alert">
              <Activity size={18} />
              <div>
                <h1>Something Went Wrong</h1>
                <p className="muted">{this.state.error.message || 'The app hit a rendering error.'}</p>
              </div>
              <button type="button" className="primary" onClick={() => window.location.reload()}>
                <RefreshCw size={16} /> Reload
              </button>
            </section>
          </main>
        </>
      );
    }
    return this.props.children;
  }
}

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>,
);

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/service-worker.js')
      .then((registration) => registration.update())
      .catch(() => {
        // PWA support is opportunistic; the app remains usable without registration.
      });
  });
}
