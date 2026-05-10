import { strict as assert } from 'node:assert';

import { AUDIT_PEEK_SCHEME, openAuditEntry } from '../src/auditPeek';

// ---------------------------------------------------------------------------
// auditPeek
// ---------------------------------------------------------------------------

describe('AUDIT_PEEK_SCHEME', () => {
  it('is a non-empty string', () => {
    assert.equal(typeof AUDIT_PEEK_SCHEME, 'string');
    assert.ok(AUDIT_PEEK_SCHEME.length > 0);
  });

  it('equals blender-mcp-audit', () => {
    assert.equal(AUDIT_PEEK_SCHEME, 'blender-mcp-audit');
  });
});

describe('openAuditEntry', () => {
  it('returns a URI with the audit peek scheme', async () => {
    const entry = { op: 'ping', ts: '2026-05-06T12:00:00Z', ok: true, elapsed_ms: 5 };
    const uri = await openAuditEntry(entry);
    assert.equal(uri.scheme, AUDIT_PEEK_SCHEME);
  });

  it('sanitizes the op name in the URI path', async () => {
    const entry = { op: 'scene.create_primitive', ts: '2026-05-06T12:00:00Z' };
    const uri = await openAuditEntry(entry);
    // Dots are allowed, slashes/special chars are replaced with underscore.
    assert.ok(uri.path.includes('scene.create_primitive'));
  });

  it('encodes the timestamp in the URI', async () => {
    const ts = '2026-05-06T12:00:00Z';
    const entry = { op: 'test', ts };
    const uri = await openAuditEntry(entry);
    const uriStr = uri.toString();
    assert.ok(uriStr.includes(encodeURIComponent(ts)));
  });

  it('handles missing op/ts gracefully', async () => {
    const entry = { foo: 'bar' };
    const uri = await openAuditEntry(entry);
    // Should default to 'entry' for op.
    assert.ok(uri.path.includes('entry'));
  });
});
