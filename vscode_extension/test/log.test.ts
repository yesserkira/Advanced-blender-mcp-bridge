import { strict as assert } from 'node:assert';

import { init, error, warn, info, debug } from '../src/log';

// ---------------------------------------------------------------------------
// log — level-filtered output
// ---------------------------------------------------------------------------

describe('log level filtering', () => {
  let lines: string[];
  const fakeChannel = {
    appendLine(msg: string) { lines.push(msg); },
    append() { },
    show() { },
    dispose() { },
  };

  beforeEach(() => {
    lines = [];
    init(fakeChannel as never);
    const g = global as unknown as Record<string, (...args: unknown[]) => void>;
    g._clearMockConfig?.();
  });

  afterEach(() => {
    const g = global as unknown as Record<string, (...args: unknown[]) => void>;
    g._clearMockConfig?.();
  });

  it('info level: error/warn/info pass, debug is suppressed', () => {
    // Default level is 'info'.
    error('e1');
    warn('w1');
    info('i1');
    debug('d1');
    assert.equal(lines.length, 3, 'debug should be suppressed at info level');
    assert.ok(lines[0].includes('ERROR'));
    assert.ok(lines[1].includes('WARN'));
    assert.ok(lines[2].includes('INFO'));
  });

  it('debug level: all messages pass', () => {
    const g = global as unknown as Record<string, (...args: unknown[]) => void>;
    g._setMockConfig('blenderMcp.logLevel', 'debug');

    error('e');
    warn('w');
    info('i');
    debug('d');
    assert.equal(lines.length, 4);
    assert.ok(lines[3].includes('DEBUG'));
  });

  it('error level: only errors pass', () => {
    const g = global as unknown as Record<string, (...args: unknown[]) => void>;
    g._setMockConfig('blenderMcp.logLevel', 'error');

    error('e');
    warn('w');
    info('i');
    debug('d');
    assert.equal(lines.length, 1);
    assert.ok(lines[0].includes('ERROR'));
  });

  it('warn level: error and warn pass', () => {
    const g = global as unknown as Record<string, (...args: unknown[]) => void>;
    g._setMockConfig('blenderMcp.logLevel', 'warn');

    error('e');
    warn('w');
    info('i');
    debug('d');
    assert.equal(lines.length, 2);
  });

  it('messages include timestamp and level tag', () => {
    info('hello');
    assert.ok(/\[\d{2}:\d{2}:\d{2}\.\d{3}\]/.test(lines[0]), 'should have timestamp');
    assert.ok(lines[0].includes('INFO'));
    assert.ok(lines[0].includes('hello'));
  });
});
