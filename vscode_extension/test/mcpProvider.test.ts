import { strict as assert } from 'node:assert';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import * as vscode from 'vscode';

import { BlenderMcpProvider } from '../src/mcpProvider';
import type { ApprovalServer } from '../src/approval';

// ---------------------------------------------------------------------------
// BlenderMcpProvider
// ---------------------------------------------------------------------------

describe('BlenderMcpProvider', () => {
  let tmpDir: string;
  let lines: string[];
  const fakeChannel = {
    appendLine(msg: string) { lines.push(msg); },
    append() { },
    show() { },
    dispose() { },
  } as unknown as vscode.OutputChannel;

  const fakeApproval = {
    getPort: () => 0,
    getBaseUrl: () => '',
    getCsrf: () => '',
  } as unknown as ApprovalServer;

  const g = global as unknown as Record<string, (...args: unknown[]) => void>;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'bmcp-prov-'));
    lines = [];
    g._clearMockConfig?.();
  });

  afterEach(() => {
    g._clearMockConfig?.();
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  it('returns empty when pythonPath is not set', async () => {
    // Default: pythonPath is empty
    const provider = new BlenderMcpProvider(fakeChannel, fakeApproval);
    const defs = await provider.provideMcpServerDefinitions();
    assert.equal(defs.length, 0);
    assert.ok(lines.some((l) => l.includes('pythonPath is empty')));
  });

  it('returns empty when pythonPath points to non-existent file', async () => {
    g._setMockConfig('blenderMcp.pythonPath', '/no/such/python');
    const provider = new BlenderMcpProvider(fakeChannel, fakeApproval);
    const defs = await provider.provideMcpServerDefinitions();
    assert.equal(defs.length, 0);
    assert.ok(lines.some((l) => l.includes('does not exist')));
  });

  it('returns a definition when pythonPath exists', async () => {
    // Create a dummy python executable
    const fakePython = path.join(tmpDir, 'python.exe');
    fs.writeFileSync(fakePython, '');
    g._setMockConfig('blenderMcp.pythonPath', fakePython);

    const provider = new BlenderMcpProvider(fakeChannel, fakeApproval);
    const defs = await provider.provideMcpServerDefinitions();
    assert.equal(defs.length, 1);
    assert.ok(lines.some((l) => l.includes('registered')));
  });

  it('uses custom serverModule from config', async () => {
    const fakePython = path.join(tmpDir, 'python.exe');
    fs.writeFileSync(fakePython, '');
    g._setMockConfig('blenderMcp.pythonPath', fakePython);
    g._setMockConfig('blenderMcp.serverModule', 'my_custom.server');

    const provider = new BlenderMcpProvider(fakeChannel, fakeApproval);
    const defs = await provider.provideMcpServerDefinitions();
    assert.equal(defs.length, 1);
    assert.ok(lines.some((l) => l.includes('my_custom.server')));
  });

  it('refresh fires onDidChangeMcpServerDefinitions', (done) => {
    const provider = new BlenderMcpProvider(fakeChannel, fakeApproval);
    provider.onDidChangeMcpServerDefinitions(() => done());
    provider.refresh();
  });

  it('blocks remote host without acknowledgement', async () => {
    const fakePython = path.join(tmpDir, 'python.exe');
    fs.writeFileSync(fakePython, '');
    g._setMockConfig('blenderMcp.pythonPath', fakePython);

    // Simulate a remote host in connection config by setting env
    const origHome = process.env.HOME;
    const fakeTmp = fs.mkdtempSync(path.join(os.tmpdir(), 'bmcp-remote-'));
    process.env.HOME = fakeTmp;
    if (process.platform === 'win32') {
      process.env.USERPROFILE = fakeTmp;
    }
    const connDir = path.join(fakeTmp, '.blender_mcp');
    fs.mkdirSync(connDir, { recursive: true });
    fs.writeFileSync(
      path.join(connDir, 'connection.json'),
      JSON.stringify({ host: '10.0.0.5', port: 9876, token: 'tok', pid: process.pid }),
    );

    const fakeContext = {
      subscriptions: [],
      globalState: (global as unknown as Record<string, unknown>)._globalState as vscode.Memento,
    } as unknown as vscode.ExtensionContext;

    const provider = new BlenderMcpProvider(fakeChannel, fakeApproval, fakeContext);
    const defs = await provider.provideMcpServerDefinitions();
    assert.equal(defs.length, 0);
    assert.ok(lines.some((l) => l.includes('refusing to register against remote host')));

    // Restore
    process.env.HOME = origHome;
    if (process.platform === 'win32') {
      process.env.USERPROFILE = origHome;
    }
    fs.rmSync(fakeTmp, { recursive: true, force: true });
  });
});
