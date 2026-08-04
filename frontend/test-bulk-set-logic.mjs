import assert from 'node:assert/strict';
import { parseBulkSetEntry } from './src/bulkSetLogic.js';

assert.deepEqual(parseBulkSetEntry('3x8 @135'), { count: 3, reps: '8', weight: '135' });
assert.deepEqual(parseBulkSetEntry('4×10×50'), { count: 4, reps: '10', weight: '50' });
assert.deepEqual(parseBulkSetEntry('2 x 12'), { count: 2, reps: '12', weight: '' });
assert.throws(() => parseBulkSetEntry('0x8 @135'), /count/);
assert.throws(() => parseBulkSetEntry('4×10×50 rpe 8'), /Use count/);
assert.throws(() => parseBulkSetEntry('three sets'), /Use count/);

console.log('bulk set parser ok');
