import { strict as assert } from 'node:assert';
import * as vscode from 'vscode';

import { init, getSecretToken, setSecretToken, onSecretTokenChanged } from '../src/secretToken';

// ---------------------------------------------------------------------------
// secretToken
// ---------------------------------------------------------------------------

describe('secretToken', () => {
  // Build a fake ExtensionContext with a SecretStorage stub.
  function makeFakeContext(): vscode.ExtensionContext {
    const create = (global as unknown as Record<string, () => unknown>)._createSecretStorage;
    const secrets = create() as vscode.SecretStorage;
    return {
      secrets,
      subscriptions: [] as vscode.Disposable[],
    } as unknown as vscode.ExtensionContext;
  }

  it('getSecretToken returns empty string before init', () => {
    // Module-level cache starts empty.
    assert.equal(getSecretToken(), '');
  });

  it('init reads existing secret into cache', async () => {
    const ctx = makeFakeContext();
    // Pre-populate the secret store.
    await ctx.secrets.store('blenderMcp.token', 'preexisting');
    await init(ctx);
    assert.equal(getSecretToken(), 'preexisting');
  });

  it('setSecretToken updates cache and fires event', async () => {
    const ctx = makeFakeContext();
    await init(ctx);

    let fired = false;
    const sub = onSecretTokenChanged(() => { fired = true; });

    await setSecretToken('new-tok');
    assert.equal(getSecretToken(), 'new-tok');
    assert.ok(fired, 'onSecretTokenChanged should have fired');

    sub.dispose();
  });

  it('setSecretToken with empty string clears the token', async () => {
    const ctx = makeFakeContext();
    await init(ctx);
    await setSecretToken('something');
    await setSecretToken('');
    assert.equal(getSecretToken(), '');
  });
});
