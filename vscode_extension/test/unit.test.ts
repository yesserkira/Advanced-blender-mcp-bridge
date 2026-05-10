// Unit tests for pure helpers. Run with `npm test`.
//
// The vscode module is stubbed via test/setup.js (loaded before this file).

import { strict as assert } from 'node:assert';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';

import {
  isPidAlive,
  connectionFilePath,
  readConnectionFile,
  resolveConnection,
  isRemoteHost,
} from '../src/connectionConfig';
import { stripJsonComments } from '../src/mcpProvider';

// ---------------------------------------------------------------------------
// isPidAlive
// ---------------------------------------------------------------------------

describe('isPidAlive', () => {
  it('returns true for the current process', () => {
    assert.equal(isPidAlive(process.pid), true);
  });

  it('returns false for non-positive values', () => {
    assert.equal(isPidAlive(0), false);
    assert.equal(isPidAlive(-1), false);
    assert.equal(isPidAlive(NaN), false);
  });

  it('returns false for an obviously dead pid (very high)', () => {
    // PIDs above 2^22 are not reachable on any platform we target.
    assert.equal(isPidAlive(99_999_999), false);
  });
});

// ---------------------------------------------------------------------------
// connectionFilePath
// ---------------------------------------------------------------------------

describe('connectionFilePath', () => {
  it('lives under the user home', () => {
    const p = connectionFilePath();
    assert.ok(p.startsWith(os.homedir()));
    assert.ok(p.endsWith(path.join('.blender_mcp', 'connection.json')));
  });
});

// ---------------------------------------------------------------------------
// readConnectionFile / resolveConnection (with temp HOME)
// ---------------------------------------------------------------------------

describe('readConnectionFile + resolveConnection', () => {
  let tmpHome: string;
  let originalHome: string | undefined;

  beforeEach(() => {
    tmpHome = fs.mkdtempSync(path.join(os.tmpdir(), 'bmcp-test-'));
    originalHome = process.env.HOME;
    process.env.HOME = tmpHome;
    if (process.platform === 'win32') {
      process.env.USERPROFILE = tmpHome;
    }
    // Force os.homedir() cache to refresh.
    delete process.env.BLENDER_MCP_TOKEN;
    (global as { _clearMockConfig?: () => void })._clearMockConfig?.();
  });

  afterEach(() => {
    process.env.HOME = originalHome;
    fs.rmSync(tmpHome, { recursive: true, force: true });
  });

  function writeConnFile(data: object): void {
    const dir = path.join(tmpHome, '.blender_mcp');
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, 'connection.json'), JSON.stringify(data));
  }

  it('returns undefined when file is missing', () => {
    assert.equal(readConnectionFile(), undefined);
  });

  it('returns undefined when JSON is malformed', () => {
    const dir = path.join(tmpHome, '.blender_mcp');
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, 'connection.json'), '{not json');
    assert.equal(readConnectionFile(), undefined);
  });

  it('returns data when pid is alive', () => {
    writeConnFile({ host: '127.0.0.1', port: 9876, token: 't', pid: process.pid });
    const r = readConnectionFile();
    assert.ok(r);
    assert.equal(r!.token, 't');
  });

  it('returns undefined when pid is dead', () => {
    writeConnFile({ host: '127.0.0.1', port: 9876, token: 't', pid: 99_999_999 });
    assert.equal(readConnectionFile(), undefined);
  });

  it('returns data when pid field is absent (older add-on)', () => {
    writeConnFile({ host: '127.0.0.1', port: 9876, token: 't' });
    const r = readConnectionFile();
    assert.equal(r?.token, 't');
  });

  it('resolveConnection: file > env when both present (live file wins)', () => {
    // Regression: a stale BLENDER_MCP_TOKEN env var must NOT silently
    // override a fresh connection.json. Blender rewrites the file on every
    // start; the env var typically lingers from an earlier session.
    writeConnFile({ token: 'fileTok', pid: process.pid });
    process.env.BLENDER_MCP_TOKEN = 'envTok';
    const r = resolveConnection();
    assert.equal(r.token, 'fileTok');
    assert.equal(r.source, 'file');
    assert.equal(r.blenderRunning, true);
  });

  it('resolveConnection: env wins when no live connection file', () => {
    // Headless / CI case: no Blender pidfile, env var is the only signal.
    process.env.BLENDER_MCP_TOKEN = 'envTok';
    const r = resolveConnection();
    assert.equal(r.token, 'envTok');
    assert.equal(r.source, 'env');
    assert.equal(r.blenderRunning, false);
  });

  it('resolveConnection: file beats setting when env empty', () => {
    writeConnFile({ token: 'fileTok', pid: process.pid });
    (global as { _setMockConfig?: (k: string, v: unknown) => void })
      ._setMockConfig?.('blenderMcp.token', 'settingTok');
    const r = resolveConnection();
    assert.equal(r.token, 'fileTok');
    assert.equal(r.source, 'file');
    assert.equal(r.blenderRunning, true);
  });

  it('resolveConnection: stale file falls through to setting', () => {
    writeConnFile({ token: 'fileTok', pid: 99_999_999 });
    (global as { _setMockConfig?: (k: string, v: unknown) => void })
      ._setMockConfig?.('blenderMcp.token', 'settingTok');
    const r = resolveConnection();
    assert.equal(r.token, 'settingTok');
    assert.equal(r.source, 'setting');
  });

  it('resolveConnection: nothing configured → source=none', () => {
    const r = resolveConnection();
    assert.equal(r.token, '');
    assert.equal(r.source, 'none');
    assert.equal(r.blenderRunning, false);
  });
});

// ---------------------------------------------------------------------------
// stripJsonComments
// ---------------------------------------------------------------------------

describe('stripJsonComments', () => {
  it('strips line comments', () => {
    const out = stripJsonComments('{"a":1} // trailing');
    // Comments are blanked (not removed) so offsets align.
    assert.equal(JSON.parse(out.trim()).a, 1);
  });

  it('strips block comments', () => {
    const out = stripJsonComments('{"a":/* hi */1}');
    assert.equal(JSON.parse(out).a, 1);
  });

  it('preserves comment-like content inside strings', () => {
    const out = stripJsonComments('{"a":"//not a comment"}');
    assert.equal(JSON.parse(out).a, '//not a comment');
  });

  it('handles escaped quotes inside strings', () => {
    const out = stripJsonComments('{"a":"he said \\"hi\\""}');
    assert.equal(JSON.parse(out).a, 'he said "hi"');
  });

  it('handles multiline block comments', () => {
    const out = stripJsonComments('{"a":1,/*\n  comment\n*/"b":2}');
    const parsed = JSON.parse(out) as { a: number; b: number };
    assert.equal(parsed.a, 1);
    assert.equal(parsed.b, 2);
  });

  it('preserves single-quoted strings', () => {
    // JSONC technically only allows double quotes but stripJsonComments
    // should leave single-quoted runs alone (don't peek inside them).
    const out = stripJsonComments("{'a':1}");
    assert.equal(out, "{'a':1}");
  });
});

// ---------------------------------------------------------------------------
// isRemoteHost (Phase 9)
// ---------------------------------------------------------------------------

describe('isRemoteHost', () => {
  it('treats 127.0.0.0/8, ::1, localhost as loopback', () => {
    for (const h of ['127.0.0.1', '127.1.2.3', '127.255.255.254', '::1', 'localhost', 'LOCALHOST', '0:0:0:0:0:0:0:1']) {
      assert.equal(isRemoteHost(h), false, `expected ${h} loopback`);
    }
  });
  it('treats public IPs and DNS names as remote', () => {
    for (const h of ['10.0.0.1', '192.168.1.5', 'blender-host.local', 'example.com', '203.0.113.4']) {
      assert.equal(isRemoteHost(h), true, `expected ${h} remote`);
    }
  });
  it('treats 0.0.0.0 as remote (clients should never dial it)', () => {
    assert.equal(isRemoteHost('0.0.0.0'), true);
  });
  it('returns false for empty/undefined input', () => {
    assert.equal(isRemoteHost(''), false);
    assert.equal(isRemoteHost(undefined), false);
    assert.equal(isRemoteHost(null), false);
  });
});

// ---------------------------------------------------------------------------
// resolveConnection edge cases
// ---------------------------------------------------------------------------

describe('resolveConnection edge cases', () => {
  let tmpHome: string;
  let originalHome: string | undefined;

  beforeEach(() => {
    tmpHome = fs.mkdtempSync(path.join(os.tmpdir(), 'bmcp-edge-'));
    originalHome = process.env.HOME;
    process.env.HOME = tmpHome;
    if (process.platform === 'win32') {
      process.env.USERPROFILE = tmpHome;
    }
    delete process.env.BLENDER_MCP_TOKEN;
    (global as { _clearMockConfig?: () => void })._clearMockConfig?.();
  });

  afterEach(() => {
    process.env.HOME = originalHome;
    fs.rmSync(tmpHome, { recursive: true, force: true });
  });

  function writeConnFile(data: object): void {
    const dir = path.join(tmpHome, '.blender_mcp');
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, 'connection.json'), JSON.stringify(data));
  }

  it('uses host/port from connection file', () => {
    writeConnFile({ host: '10.0.0.5', port: 1234, token: 'tok', pid: process.pid });
    const r = resolveConnection();
    assert.equal(r.host, '10.0.0.5');
    assert.equal(r.port, 1234);
  });

  it('defaults host to 127.0.0.1 and port to 9876 when missing', () => {
    const r = resolveConnection();
    assert.equal(r.host, '127.0.0.1');
    assert.equal(r.port, 9876);
  });

  it('env token ignored when a live connection file exists', () => {
    // Live file always wins over env. To exercise the env-only path,
    // see the headless test above (no connection file present).
    writeConnFile({ host: '10.0.0.5', port: 1234, token: 'fileTok', pid: process.pid });
    process.env.BLENDER_MCP_TOKEN = 'envTok';
    const r = resolveConnection();
    assert.equal(r.token, 'fileTok');
    assert.equal(r.source, 'file');
    assert.equal(r.host, '10.0.0.5');
    assert.equal(r.port, 1234);
  });
});
