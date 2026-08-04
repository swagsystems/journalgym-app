export function normalizeWorkoutDraftValue(value, baseWorkout, createSetId) {
  if (!value || typeof value !== 'object') return baseWorkout;
  const sets = Array.isArray(value.sets) && value.sets.length
    ? value.sets.map((set) => ({
        client_id: set?.client_id || createSetId(),
        exercise_id: set?.exercise_id || '',
        weight_lbs: set?.weight_lbs || '',
        weight_mode: set?.weight_mode || 'external',
        reps: set?.reps || '',
        notes: set?.notes || '',
      }))
    : baseWorkout.sets;
  return {
    workout_date: value.workout_date || baseWorkout.workout_date,
    title: value.title || '',
    bodyweight_lbs: value.bodyweight_lbs || '',
    notes: value.notes || '',
    sets,
  };
}
