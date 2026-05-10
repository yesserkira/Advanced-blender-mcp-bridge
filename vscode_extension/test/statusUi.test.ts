import { strict as assert } from 'node:assert';

import {
  disconnectShortLabel,
  disconnectFullText,
  McpTreeProvider,
  StatusController,
} from '../src/statusUi';
import * as vscode from 'vscode';

// ---------------------------------------------------------------------------
// disconnectShortLabel
// ---------------------------------------------------------------------------

describe('disconnectShortLabel', () => {
  it('returns "No token" for no-token', () => {
    assert.equal(disconnectShortLabel('no-token'), 'No token');
  });

  it('returns "Blender not running" for blender-stopped', () => {
    assert.equal(disconnectShortLabel('blender-stopped'), 'Blender not running');
  });

  it('returns "Auth failed" for auth-failed', () => {
    assert.equal(disconnectShortLabel('auth-failed'), 'Auth failed');
  });

  it('returns "Connection refused" for refused', () => {
    assert.equal(disconnectShortLabel('refused'), 'Connection refused');
  });

  it('returns "Disconnected" for unknown', () => {
    assert.equal(disconnectShortLabel('unknown'), 'Disconnected');
  });
});

// ---------------------------------------------------------------------------
// disconnectFullText
// ---------------------------------------------------------------------------

describe('disconnectFullText', () => {
  it('mentions BLENDER_MCP_TOKEN for no-token', () => {
    assert.ok(disconnectFullText('no-token').includes('BLENDER_MCP_TOKEN'));
  });

  it('mentions connection.json for blender-stopped', () => {
    assert.ok(disconnectFullText('blender-stopped').includes('connection.json'));
  });

  it('mentions Copy Token for auth-failed', () => {
    assert.ok(disconnectFullText('auth-failed').includes('Copy Token'));
  });

  it('mentions WS server for refused', () => {
    assert.ok(disconnectFullText('refused').includes('WS server'));
  });

  it('returns empty string for unknown', () => {
    assert.equal(disconnectFullText('unknown'), '');
  });
});

// ---------------------------------------------------------------------------
// McpTreeProvider — tree structure
// ---------------------------------------------------------------------------

describe('McpTreeProvider tree structure', () => {
  let status: StatusController;
  let tree: McpTreeProvider;

  // Minimal ExtensionContext stub for the tree provider.
  const fakeContext = {
    subscriptions: [] as vscode.Disposable[],
    extensionPath: '',
    globalState: (global as Record<string, unknown>)._globalState as vscode.Memento,
  } as unknown as vscode.ExtensionContext;

  beforeEach(() => {
    const g = global as unknown as Record<string, (() => void) | undefined>;
    g._clearGlobalState?.();
    g._clearMockConfig?.();

    // StatusController requires an ExtensionContext — stub what it needs.
    status = new StatusController(fakeContext);
    tree = new McpTreeProvider(status, fakeContext);
  });

  afterEach(() => {
    status.stop();
  });

  it('root returns 5 groups', () => {
    const roots = tree.getChildren(undefined);
    assert.equal(roots.length, 5);
  });

  it('root group labels include Connection, Quick Actions, Snippets, Tool Usage, Recent Activity', () => {
    const roots = tree.getChildren(undefined);
    const labels = roots.map((r) => (r as vscode.TreeItem).label);
    assert.ok(labels.some((l) => typeof l === 'string' && l.includes('Connection')));
    assert.ok(labels.some((l) => l === 'Quick Actions'));
    assert.ok(labels.some((l) => typeof l === 'string' && l.includes('Snippet')));
    assert.ok(labels.some((l) => l === 'Tool Usage'));
    assert.ok(labels.some((l) => typeof l === 'string' && l.includes('Recent Activity')));
  });

  it('getTreeItem returns the same item', () => {
    const roots = tree.getChildren(undefined);
    assert.equal(tree.getTreeItem(roots[0]), roots[0]);
  });

  it('audit filter works', () => {
    tree.setAuditFilter('ping');
    assert.equal(tree.getAuditFilter(), 'ping');
    tree.setAuditFilter('');
    assert.equal(tree.getAuditFilter(), '');
  });

  it('findAuditEntry returns undefined when audit is empty', () => {
    assert.equal(tree.findAuditEntry('ping', '2026-05-06T10:00:00Z'), undefined);
  });

  it('refresh fires onDidChangeTreeData', (done) => {
    tree.onDidChangeTreeData(() => {
      done();
    });
    tree.refresh();
  });
});
