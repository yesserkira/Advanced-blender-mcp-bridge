// Shared resolver for the Blender MCP add-on connection (host / port / token).
//
// Priority order:
//   1. BLENDER_MCP_TOKEN env var (with blenderMcp.host/.port from settings)
//   2. ~/.blender_mcp/connection.json written by the Blender add-on at start
//      (rejected as stale if it carries a `pid` that's no longer alive).
//      A fresh connection.json reflects the token Blender is *actually*
//      listening for right now, so it beats any persisted user token.
//   3. SecretStorage entry (paste-once persistent token, used when Blender
//      doesn't write a pidfile e.g. user runs --background or uses a fixed
//      token in preferences)
//   4. blenderMcp.token / blenderMcp.host / blenderMcp.port settings
//      (deprecated — the migration in extension.ts moves it into SecretStorage)
//
// The resolver returns a richer shape than just {host,port,token}: callers
// also get `source` and `blenderRunning` so the UI can distinguish
// "Blender not running" from "no token configured" from "Blender running but
// connection refused" — three states that look the same at the WS level.

import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import { getSecretToken } from './secretToken';

export type ConnectionSource = 'env' | 'secret' | 'file' | 'setting' | 'none';

export interface ResolvedConnection {
  host: string;
  port: number;
  token: string;
  /** Where the token came from. `'none'` ⇒ no token available anywhere. */
  source: ConnectionSource;
  /**
   * True when we resolved from a fresh `connection.json` whose `pid` is
   * still alive. False otherwise (no file, stale file, or token from env /
   * setting where we have no way to tell).
   */
  blenderRunning: boolean;
}

interface ConnectionFile {
  host?: string;
  port?: number;
  token?: string;
  pid?: number;
  started_at?: string;
}

export function connectionFilePath(): string {
  return path.join(os.homedir(), '.blender_mcp', 'connection.json');
}

/**
 * Return true when `host` resolves to anything other than the loopback
 * interface. Used by the UI to surface a remote-bind warning and by
 * activation to require an explicit user ack before registering an MCP
 * provider that points at a non-loopback Blender.
 *
 * Recognised loopback aliases: 127.0.0.0/8 literals, ::1, localhost.
 * 0.0.0.0 is treated as remote on the receiving side — clients should
 * never *connect* to 0.0.0.0; if we see it in connection.json the user
 * has misconfigured their Blender add-on.
 */
export function isRemoteHost(host: string | undefined | null): boolean {
  if (!host) return false;
  const h = host.trim().toLowerCase();
  if (h === 'localhost' || h === '::1' || h === '0:0:0:0:0:0:0:1') return false;
  if (h === '0.0.0.0') return true;
  // 127.0.0.0/8 — any 127.x.y.z is loopback on every modern OS
  if (/^127(\.\d{1,3}){3}$/.test(h)) return false;
  return true;
}

/**
 * Read and parse `~/.blender_mcp/connection.json`. Returns `undefined` if the
 * file doesn't exist, can't be parsed, or carries a dead PID (stale file
 * left behind after a Blender crash — graceful shutdown removes the file).
 */
export function readConnectionFile(): ConnectionFile | undefined {
  const filePath = connectionFilePath();
  let raw: string;
  try {
    raw = fs.readFileSync(filePath, 'utf-8');
  } catch {
    return undefined;
  }
  let data: ConnectionFile;
  try {
    data = JSON.parse(raw) as ConnectionFile;
  } catch {
    return undefined;
  }
  if (typeof data.pid === 'number' && !isPidAlive(data.pid)) {
    return undefined;
  }
  return data;
}

/** Cross-platform liveness check for a pid (true = alive or unknown-with-perm-error). */
export function isPidAlive(pid: number): boolean {
  if (!Number.isInteger(pid) || pid <= 0) {
    return false;
  }
  try {
    process.kill(pid, 0);
    return true;
  } catch (e: unknown) {
    const err = e as NodeJS.ErrnoException;
    // EPERM means the process exists but we can't signal it (different user).
    return err.code === 'EPERM';
  }
}

export function resolveConnection(): ResolvedConnection {
  const cfg = vscode.workspace.getConfiguration('blenderMcp');
  const cfgHost = cfg.get<string>('host', '127.0.0.1');
  const cfgPort = cfg.get<number>('port', 9876);
  const envToken = process.env['BLENDER_MCP_TOKEN'] ?? '';

  // Priority: connection.json (live, alive-pid) > env > secret > setting.
  //
  // The file wins over env when Blender is currently running because the
  // file is rewritten on every Blender start and reflects the *current*
  // session's token. A stale env var (left from a previous Blender run)
  // would otherwise silently override a fresh token and produce
  // "AUTH failed" with no obvious cause. See:
  // https://github.com/.../issues/<token-rotation-bug>
  const conn = readConnectionFile();
  if (conn?.token) {
    return {
      host: conn.host ?? cfgHost,
      port: conn.port ?? cfgPort,
      token: conn.token,
      source: 'file',
      // readConnectionFile() returns undefined for stale-pid files, so by
      // the time we reach here the pid (if present) is alive. If no pid was
      // written (older add-on), we conservatively report true — worst case
      // matches the pre-pid-stamping UX.
      blenderRunning: true,
    };
  }

  if (envToken) {
    return {
      host: cfgHost,
      port: cfgPort,
      token: envToken,
      source: 'env',
      // Env-token mode: we can't infer Blender liveness from a pidfile.
      // The status poller will discover the truth via ping.
      blenderRunning: false,
    };
  }

  const secretToken = getSecretToken();
  if (secretToken) {
    return {
      host: cfgHost,
      port: cfgPort,
      token: secretToken,
      source: 'secret',
      blenderRunning: false,
    };
  }

  const settingToken = cfg.get<string>('token', '');
  return {
    host: cfgHost,
    port: cfgPort,
    token: settingToken,
    source: settingToken ? 'setting' : 'none',
    blenderRunning: false,
  };
}

// ---------------------------------------------------------------------------
// Connection-file watcher
// ---------------------------------------------------------------------------
//
// Two ways the file can change underfoot:
//   1. Blender (re)starts → writes connection.json with a new token/pid.
//   2. Blender exits gracefully → removes the file.
//   3. Blender crashes → file remains but pid is dead (caught by readConnectionFile).
//
// `fs.watch()` is unreliable on Windows network drives and WSL bind-mounts:
// events are sometimes lost. We belt-and-braces with a `pokeConnectionWatcher()`
// helper the status poller calls every few seconds — if mtime changed since
// last check we fire the event manually.

const _emitter = new vscode.EventEmitter<void>();
/** Fires whenever the connection file is created, modified, or deleted. */
export const onConnectionFileChanged: vscode.Event<void> = _emitter.event;

let _lastMtimeMs = -1;
let _watcher: fs.FSWatcher | undefined;

function _checkMtime(): boolean {
  let mtimeMs: number;
  try {
    mtimeMs = fs.statSync(connectionFilePath()).mtimeMs;
  } catch {
    mtimeMs = 0; // file missing
  }
  if (mtimeMs !== _lastMtimeMs) {
    _lastMtimeMs = mtimeMs;
    return true;
  }
  return false;
}

/**
 * Re-check the connection file's mtime; fire the change event if it moved.
 * Cheap (one stat call) — safe to invoke on every status poll.
 */
export function pokeConnectionWatcher(): void {
  if (_checkMtime()) {
    _emitter.fire();
  }
}

/**
 * Start watching `~/.blender_mcp/` for connection.json changes. Returns a
 * disposable that closes the watcher. Safe to call once at activation.
 */
export function startConnectionWatcher(): vscode.Disposable {
  // Seed the mtime so the first poke after activation doesn't fire spuriously.
  _checkMtime();
  try {
    const dir = path.dirname(connectionFilePath());
    fs.mkdirSync(dir, { recursive: true });
    _watcher = fs.watch(dir, (_evt, filename) => {
      if (filename === 'connection.json' || filename === null) {
        // Re-stat to update _lastMtimeMs and de-dup against the poll path.
        if (_checkMtime()) {
          _emitter.fire();
        }
      }
    });
  } catch {
    // best-effort — pokeConnectionWatcher() still self-heals on every poll
  }
  return new vscode.Disposable(() => {
    if (_watcher) {
      _watcher.close();
      _watcher = undefined;
    }
  });
}
