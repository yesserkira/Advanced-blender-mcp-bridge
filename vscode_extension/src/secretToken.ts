// SecretStorage-backed token cache.
//
// SecretStorage is async-only, but `resolveConnection()` is sync (it's called
// from many UI hot paths). We bridge that by loading the secret eagerly into
// a module-local cache during activation, then exposing a sync getter.
// Writes go straight to SecretStorage and update the cache atomically.
//
// Key namespace: `blenderMcp.token` — same name as the deprecated setting,
// distinct keyspace because SecretStorage is its own backend.

import * as vscode from 'vscode';

const SECRET_KEY = 'blenderMcp.token';

let _store: vscode.SecretStorage | undefined;
let _cached: string = '';
const _emitter = new vscode.EventEmitter<void>();

/** Fires when the secret token is written or cleared. */
export const onSecretTokenChanged: vscode.Event<void> = _emitter.event;

/**
 * Initialize the adapter. Reads the secret into the cache and subscribes to
 * cross-window changes (SecretStorage propagates writes between windows).
 * Safe to call once at activation.
 */
export async function init(context: vscode.ExtensionContext): Promise<void> {
  _store = context.secrets;
  _cached = (await _store.get(SECRET_KEY)) ?? '';
  context.subscriptions.push(
    _store.onDidChange(async (e) => {
      if (e.key === SECRET_KEY) {
        _cached = (await _store!.get(SECRET_KEY)) ?? '';
        _emitter.fire();
      }
    }),
  );
  context.subscriptions.push(_emitter);
}

/** Sync getter — returns the cached secret token (or '' if none). */
export function getSecretToken(): string {
  return _cached;
}

/** Write a new secret token (or empty string to clear). */
export async function setSecretToken(value: string): Promise<void> {
  if (!_store) { throw new Error('secretToken.init() not called'); }
  if (value) {
    await _store.store(SECRET_KEY, value);
  } else {
    await _store.delete(SECRET_KEY);
  }
  _cached = value;
  _emitter.fire();
}
