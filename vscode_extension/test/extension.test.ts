import { strict as assert } from 'node:assert';

import { getOutputChannel, deactivate } from '../src/extension';

// ---------------------------------------------------------------------------
// extension exports
// ---------------------------------------------------------------------------

describe('getOutputChannel', () => {
  it('returns an object with appendLine', () => {
    const ch = getOutputChannel();
    assert.ok(typeof ch.appendLine === 'function');
  });

  it('returns the same channel on repeated calls', () => {
    const a = getOutputChannel();
    const b = getOutputChannel();
    assert.equal(a, b);
  });
});

describe('deactivate', () => {
  it('does not throw', () => {
    assert.doesNotThrow(() => deactivate());
  });
});
