export function parseBulkSetEntry(value) {
  const input = String(value || '').trim();
  const match = input.match(/^(\d{1,2})\s*[x×]\s*(\d{1,3})(?:\s*(?:@|x|×)\s*(\d+(?:\.\d+)?))?$/i);
  if (!match) {
    throw new Error('Use count x reps @ weight, for example 3x8 @135.');
  }
  const count = Number(match[1]);
  const reps = Number(match[2]);
  const weight = match[3] || '';
  if (!Number.isInteger(count) || count < 1 || count > 20) throw new Error('Bulk count must be between 1 and 20.');
  if (!Number.isInteger(reps) || reps < 1 || reps > 200) throw new Error('Bulk reps must be between 1 and 200.');
  return { count, reps: String(reps), weight };
}
