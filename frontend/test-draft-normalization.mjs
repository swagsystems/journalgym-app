import assert from 'node:assert/strict';
import { normalizeWorkoutDraftValue } from './src/draftLogic.js';

let counter = 0;
const createSetId = () => `set-${++counter}`;
const baseWorkout = {
  workout_date: '2026-05-16',
  title: '',
  bodyweight_lbs: '',
  notes: '',
  sets: [{ client_id: 'base-set', exercise_id: '', weight_lbs: '', weight_mode: 'external', reps: '', notes: '' }],
};

const normalized = normalizeWorkoutDraftValue(
  {
    workout_date: '2026-05-15',
    title: null,
    bodyweight_lbs: 181.5,
    notes: undefined,
    sets: [
      { exercise_id: 12, weight_lbs: 135, reps: 5 },
      { client_id: 'kept', exercise_id: '', weight_lbs: '', reps: '', rpe: 8, set_type: 'drop', group_label: 'A', rest_seconds: 90, tempo: '3-1-1', notes: 'tempo' },
    ],
  },
  baseWorkout,
  createSetId,
);

assert.equal(normalized.workout_date, '2026-05-15');
assert.equal(normalized.title, '');
assert.equal(normalized.bodyweight_lbs, 181.5);
assert.equal(normalized.notes, '');
assert.equal(normalized.sets[0].client_id, 'set-1');
assert.equal(normalized.sets[0].exercise_id, 12);
assert.equal(normalized.sets[1].client_id, 'kept');
assert.equal(normalized.sets[1].rpe, undefined);
assert.equal(normalized.sets[1].duration_seconds, undefined);
assert.equal(normalized.sets[1].set_type, undefined);
assert.equal(normalized.sets[1].group_label, undefined);
assert.equal(normalized.sets[1].rest_seconds, undefined);
assert.equal(normalized.sets[1].tempo, undefined);
assert.equal(normalized.sets[1].notes, 'tempo');

const fallback = normalizeWorkoutDraftValue(null, baseWorkout, createSetId);
assert.deepEqual(fallback, baseWorkout);
