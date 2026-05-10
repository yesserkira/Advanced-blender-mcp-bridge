import { strict as assert } from 'node:assert';

import {
  isTransientError,
  encodeTextFrame,
  decodeFrame,
} from '../src/wsClient';

// ---------------------------------------------------------------------------
// isTransientError
// ---------------------------------------------------------------------------

describe('isTransientError', () => {
  it('returns true for ECONNREFUSED', () => {
    const err = Object.assign(new Error('connect ECONNREFUSED'), { code: 'ECONNREFUSED' });
    assert.equal(isTransientError(err), true);
  });

  it('returns true for ETIMEDOUT', () => {
    const err = Object.assign(new Error('timed out'), { code: 'ETIMEDOUT' });
    assert.equal(isTransientError(err), true);
  });

  it('returns true for ECONNRESET', () => {
    const err = Object.assign(new Error('reset'), { code: 'ECONNRESET' });
    assert.equal(isTransientError(err), true);
  });

  it('returns true for timeout message', () => {
    assert.equal(isTransientError(new Error('WebSocket request timed out')), true);
  });

  it('returns false for non-Error values', () => {
    assert.equal(isTransientError('string'), false);
    assert.equal(isTransientError(null), false);
    assert.equal(isTransientError(undefined), false);
    assert.equal(isTransientError(42), false);
  });

  it('returns false for generic errors', () => {
    assert.equal(isTransientError(new Error('something else')), false);
  });

  it('returns false for auth errors', () => {
    const err = Object.assign(new Error('auth failed'), { code: 'AUTH' });
    assert.equal(isTransientError(err), false);
  });
});

// ---------------------------------------------------------------------------
// encodeTextFrame / decodeFrame round-trip
// ---------------------------------------------------------------------------

describe('WebSocket frame encode/decode', () => {
  it('round-trips a short message (< 126 bytes)', () => {
    const msg = 'hello';
    const frame = encodeTextFrame(msg);
    // The frame is masked (client → server), but decodeFrame handles
    // unmasked frames (server → client). Build an unmasked frame manually
    // to test decodeFrame.
    const unmasked = buildUnmaskedTextFrame(msg);
    const result = decodeFrame(unmasked);
    assert.ok(result);
    assert.equal(result!.text, msg);
    assert.equal(result!.rest.length, 0);
  });

  it('decodes a medium-length message (126–65535 bytes)', () => {
    const msg = 'A'.repeat(300);
    const unmasked = buildUnmaskedTextFrame(msg);
    const result = decodeFrame(unmasked);
    assert.ok(result);
    assert.equal(result!.text, msg);
  });

  it('returns undefined for incomplete buffer', () => {
    assert.equal(decodeFrame(Buffer.alloc(0)), undefined);
    assert.equal(decodeFrame(Buffer.from([0x81])), undefined);
  });

  it('returns undefined for close frame (opcode 0x8)', () => {
    const close = Buffer.from([0x88, 0x00]);
    assert.equal(decodeFrame(close), undefined);
  });

  it('encodeTextFrame produces a valid masked frame', () => {
    const frame = encodeTextFrame('test');
    // First byte: 0x81 (FIN + text opcode)
    assert.equal(frame[0], 0x81);
    // Second byte: 0x80 | length (masked bit set)
    assert.equal(frame[1] & 0x80, 0x80);
    const payloadLen = frame[1] & 0x7f;
    assert.equal(payloadLen, 4);
  });

  it('preserves rest bytes after the frame', () => {
    const msg = 'hi';
    const frame = buildUnmaskedTextFrame(msg);
    const extra = Buffer.from([0xDE, 0xAD]);
    const combined = Buffer.concat([frame, extra]);
    const result = decodeFrame(combined);
    assert.ok(result);
    assert.equal(result!.text, msg);
    assert.equal(result!.rest.length, 2);
    assert.equal(result!.rest[0], 0xDE);
  });
});

/**
 * Helper: build an unmasked WebSocket text frame (as a server would send).
 * decodeFrame expects unmasked frames from the server side.
 */
function buildUnmaskedTextFrame(text: string): Buffer {
  const data = Buffer.from(text, 'utf8');
  const len = data.length;
  let header: Buffer;
  if (len < 126) {
    header = Buffer.alloc(2);
    header[0] = 0x81; // FIN + text
    header[1] = len;
  } else if (len < 65536) {
    header = Buffer.alloc(4);
    header[0] = 0x81;
    header[1] = 126;
    header.writeUInt16BE(len, 2);
  } else {
    header = Buffer.alloc(10);
    header[0] = 0x81;
    header[1] = 127;
    header.writeUInt32BE(0, 2);
    header.writeUInt32BE(len, 6);
  }
  return Buffer.concat([header, data]);
}
