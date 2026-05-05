// Status bar + activity-bar tree view for the Blender MCP add-on.
// Owns a single connection-state poller and exposes refresh commands.

import * as vscode from 'vscode';
import { call as wsCall } from './wsClient';

type ConnectionState = 'connected' | 'connecting' | 'disconnected';

interface AuditEntry {
  ts: string;
  op: string;
  ok: boolean;
  elapsed_ms: number;
  args_sha256?: string;
  undo_id?: string;
}

function getConfig(): { host: string; port: number; token: string } {
  const cfg = vscode.workspace.getConfiguration('blenderMcp');
  return {
    host: cfg.get<string>('host', '127.0.0.1'),
    port: cfg.get<number>('port', 9876),
    token:
      process.env['BLENDER_MCP_TOKEN'] ?? cfg.get<string>('token', ''),
  };
}

// ---------------------------------------------------------------------------
// Status bar
// ---------------------------------------------------------------------------

export class StatusController {
  private readonly item: vscode.StatusBarItem;
  private timer: ReturnType<typeof setInterval> | undefined;
  private state: ConnectionState = 'disconnected';
  private lastLatencyMs = 0;
  private listeners: Array<(s: ConnectionState) => void> = [];

  constructor(context: vscode.ExtensionContext) {
    this.item = vscode.window.createStatusBarItem(
      vscode.StatusBarAlignment.Left,
      100,
    );
    this.item.command = 'blenderMcp.showStatus';
    this.render();
    this.item.show();
    context.subscriptions.push(this.item);
    context.subscriptions.push(
      vscode.workspace.onDidChangeConfiguration((e) => {
        if (e.affectsConfiguration('blenderMcp')) {
          void this.poll();
        }
      }),
    );
  }

  start(intervalMs = 5000): void {
    void this.poll();
    this.timer = setInterval(() => void this.poll(), intervalMs);
  }

  stop(): void {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = undefined;
    }
  }

  onChange(cb: (s: ConnectionState) => void): void {
    this.listeners.push(cb);
  }

  getState(): ConnectionState { return this.state; }
  getLatency(): number { return this.lastLatencyMs; }

  async poll(): Promise<void> {
    const cfg = getConfig();
    if (!cfg.token) {
      this.setState('disconnected');
      return;
    }
    this.setState('connecting');
    const t0 = Date.now();
    try {
      const resp = await wsCall({ ...cfg, op: 'ping', timeoutMs: 4000 });
      this.lastLatencyMs = Date.now() - t0;
      if (resp.ok) {
        this.setState('connected');
      } else {
        this.setState('disconnected');
      }
    } catch {
      this.setState('disconnected');
    }
  }

  private setState(s: ConnectionState): void {
    if (this.state === s) {
      this.render();
      return;
    }
    this.state = s;
    this.render();
    for (const cb of this.listeners) { cb(s); }
  }

  private render(): void {
    const tag =
      this.state === 'connected'
        ? `$(circle-filled) Blender MCP`
        : this.state === 'connecting'
          ? `$(sync~spin) Blender MCP`
          : `$(circle-outline) Blender MCP`;
    this.item.text = tag;
    this.item.tooltip =
      this.state === 'connected'
        ? `Connected (${this.lastLatencyMs} ms ping)\nClick to open Blender MCP view`
        : this.state === 'connecting'
          ? 'Reconnecting...'
          : 'Disconnected — click to retry';
    if (this.state === 'connected') {
      this.item.backgroundColor = undefined;
    } else if (this.state === 'connecting') {
      this.item.backgroundColor = new vscode.ThemeColor(
        'statusBarItem.warningBackground',
      );
    } else {
      this.item.backgroundColor = new vscode.ThemeColor(
        'statusBarItem.errorBackground',
      );
    }
  }
}

// ---------------------------------------------------------------------------
// Tree view
// ---------------------------------------------------------------------------

class StatusItem extends vscode.TreeItem {
  constructor(label: string, description?: string, tooltip?: string,
    icon?: string, contextValue?: string) {
    super(label);
    if (description) { this.description = description; }
    if (tooltip) { this.tooltip = tooltip; }
    if (icon) { this.iconPath = new vscode.ThemeIcon(icon); }
    if (contextValue) { this.contextValue = contextValue; }
    this.collapsibleState = vscode.TreeItemCollapsibleState.None;
  }
}

class GroupItem extends vscode.TreeItem {
  constructor(label: string, public readonly children: vscode.TreeItem[]) {
    super(label, vscode.TreeItemCollapsibleState.Expanded);
    this.contextValue = 'group';
  }
}

export class McpTreeProvider
  implements vscode.TreeDataProvider<vscode.TreeItem> {
  private _onDidChange = new vscode.EventEmitter<vscode.TreeItem | undefined>();
  readonly onDidChangeTreeData = this._onDidChange.event;

  private audit: AuditEntry[] = [];
  private auditError: string | undefined;
  private fetchingAudit = false;

  constructor(private readonly status: StatusController) {
    status.onChange(() => this._onDidChange.fire(undefined));
  }

  refresh(): void {
    this._onDidChange.fire(undefined);
  }

  async refreshAuditLog(): Promise<void> {
    if (this.fetchingAudit) { return; }
    this.fetchingAudit = true;
    this.auditError = undefined;
    this._onDidChange.fire(undefined);
    const cfg = getConfig();
    if (!cfg.token) {
      this.auditError = 'No auth token configured';
      this.audit = [];
      this.fetchingAudit = false;
      this._onDidChange.fire(undefined);
      return;
    }
    try {
      const resp = await wsCall({
        ...cfg, op: 'audit.read', args: { limit: 50 }, timeoutMs: 8000,
      });
      if (resp.ok && resp.result && Array.isArray(resp.result['entries'])) {
        this.audit = resp.result['entries'] as AuditEntry[];
      } else if (resp.error) {
        this.auditError = `${resp.error.code}: ${resp.error.message}`;
      } else {
        this.auditError = 'Unexpected response shape';
      }
    } catch (err: unknown) {
      this.auditError = err instanceof Error ? err.message : String(err);
    } finally {
      this.fetchingAudit = false;
      this._onDidChange.fire(undefined);
    }
  }

  getTreeItem(element: vscode.TreeItem): vscode.TreeItem { return element; }

  getChildren(element?: vscode.TreeItem): vscode.TreeItem[] {
    if (!element) {
      return [
        this.connectionGroup(),
        this.actionsGroup(),
        this.auditGroup(),
      ];
    }
    if (element instanceof GroupItem) {
      return element.children;
    }
    return [];
  }

  private connectionGroup(): GroupItem {
    const cfg = getConfig();
    const state = this.status.getState();
    const stateIcon =
      state === 'connected' ? 'pass-filled'
        : state === 'connecting' ? 'sync'
          : 'error';
    const stateLabel =
      state === 'connected' ? `Connected (${this.status.getLatency()} ms)`
        : state === 'connecting' ? 'Reconnecting...'
          : 'Disconnected';
    return new GroupItem('Connection', [
      new StatusItem('Status', stateLabel, undefined, stateIcon),
      new StatusItem('URL', `ws://${cfg.host}:${cfg.port}`, undefined, 'globe'),
      new StatusItem(
        'Token',
        cfg.token
          ? `${cfg.token.slice(0, 4)}\u2026${cfg.token.slice(-4)}`
          : 'NOT SET',
        cfg.token ? 'Token loaded from env or settings' : 'Set BLENDER_MCP_TOKEN or blenderMcp.token',
        cfg.token ? 'key' : 'warning',
      ),
    ]);
  }

  private actionsGroup(): GroupItem {
    return new GroupItem('Quick Actions', [
      cmdItem('Take Viewport Screenshot', 'device-camera',
        'blenderMcp.showViewportPreview'),
      cmdItem('Refresh Audit Log', 'refresh',
        'blenderMcp.refreshAuditLog'),
      cmdItem('Reconnect', 'sync', 'blenderMcp.reconnect'),
      cmdItem('Show Output Channel', 'output', 'blenderMcp.showOutput'),
    ]);
  }

  private auditGroup(): GroupItem {
    if (this.fetchingAudit) {
      return new GroupItem('Recent Activity (loading...)', []);
    }
    if (this.auditError) {
      return new GroupItem('Recent Activity', [
        new StatusItem('Error', this.auditError, this.auditError, 'error'),
      ]);
    }
    if (this.audit.length === 0) {
      return new GroupItem('Recent Activity', [
        new StatusItem('No entries yet', 'Click Refresh', undefined, 'info'),
      ]);
    }
    const items = this.audit.slice(0, 50).map((e) => {
      const t = new vscode.TreeItem(e.op);
      t.description = `${e.elapsed_ms} ms`;
      t.iconPath = new vscode.ThemeIcon(e.ok ? 'check' : 'x');
      t.tooltip = `${e.ts}\n${e.op} ${e.ok ? 'OK' : 'FAIL'}  ${e.elapsed_ms} ms${e.args_sha256 ? `\nargs#${e.args_sha256}` : ''
        }`;
      return t;
    });
    return new GroupItem(`Recent Activity (${this.audit.length})`, items);
  }
}

function cmdItem(label: string, icon: string, command: string): vscode.TreeItem {
  const t = new vscode.TreeItem(label);
  t.iconPath = new vscode.ThemeIcon(icon);
  t.command = { command, title: label };
  return t;
}
