// Status bar + activity-bar tree view for the Blender MCP add-on.
// Owns a single connection-state poller and exposes refresh commands.

import * as vscode from 'vscode';
import { call as wsCall } from './wsClient';
import { loadSnippets, groupByCategory, type Snippet } from './snippets';
import * as telemetry from './telemetry';
import {
  resolveConnection as getConfig,
  pokeConnectionWatcher,
  isRemoteHost,
  type ResolvedConnection,
} from './connectionConfig';

type ConnectionState = 'connected' | 'connecting' | 'disconnected';

/**
 * Why we're disconnected. Lets the UI render "Blender not running" vs
 * "Token missing" vs "Connection refused" instead of one generic error.
 */
type DisconnectReason =
  | 'no-token'         // resolver returned source='none'
  | 'blender-stopped'  // had token from file, but pid is dead OR ping refused
  | 'refused'          // had token, but ping refused/timed out
  | 'auth-failed'      // ping returned ok=false (bad token)
  | 'unknown';

interface AuditEntry {
  ts: string;
  op: string;
  ok: boolean;
  elapsed_ms: number;
  args_sha256?: string;
  undo_id?: string;
}

/** Subset of the `ping` response we care about for the tooltip. */
interface PingTelemetry {
  blender_version?: string;
  scene?: string;
  active_camera?: string;
  active_object?: string;
  object_count?: number;
  material_count?: number;
  units?: string;
  render_engine?: string;
}

// ---------------------------------------------------------------------------
// Status bar
// ---------------------------------------------------------------------------

export class StatusController {
  private readonly item: vscode.StatusBarItem;
  private timer: ReturnType<typeof setInterval> | undefined;
  private state: ConnectionState = 'disconnected';
  private disconnectReason: DisconnectReason = 'unknown';
  private lastLatencyMs = 0;
  private telemetry: PingTelemetry | undefined;
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
  getDisconnectReason(): DisconnectReason { return this.disconnectReason; }
  getLatency(): number { return this.lastLatencyMs; }
  getTelemetry(): PingTelemetry | undefined { return this.telemetry; }

  async poll(): Promise<void> {
    // Cheap mtime check — self-heal if fs.watch missed an event.
    pokeConnectionWatcher();
    const cfg = getConfig();
    if (!cfg.token) {
      this.disconnectReason = 'no-token';
      this.setState('disconnected');
      return;
    }
    this.setState('connecting');
    const t0 = Date.now();
    try {
      const resp = await wsCall({
        host: cfg.host, port: cfg.port, token: cfg.token,
        // ``scene.context`` is the addon's canonical liveness probe — it
        // returns the rich PingTelemetry payload (blender_version,
        // active_object, scene name, etc.) that the tooltip below
        // already consumes. The literal op ``ping`` was removed from the
        // addon in v1.1.0 and now returns BLENDER_ERROR; calling it here
        // would mask a healthy connection as ``refused``.
        op: 'scene.context', timeoutMs: 4000, retries: 1,
      });
      this.lastLatencyMs = Date.now() - t0;
      if (resp.ok) {
        this.disconnectReason = 'unknown';
        // ping returns a rich payload (see .github/copilot-instructions.md);
        // cache it so the tooltip can show scene context.
        this.telemetry = (resp.result ?? undefined) as PingTelemetry | undefined;
        this.setState('connected');
      } else if (resp.error?.code === 'AUTH') {
        this.disconnectReason = 'auth-failed';
        this.setState('disconnected');
      } else {
        this.disconnectReason = 'refused';
        this.setState('disconnected');
      }
    } catch {
      // Differentiate: if our token came from connection.json but Blender's
      // pid is gone (file went stale between resolveConnection and ping),
      // re-resolve to pick that up. Otherwise it's a refused connection.
      const recheck = getConfig();
      this.disconnectReason =
        recheck.source === 'none' ? 'no-token'
          : (cfg.source === 'file' && !recheck.blenderRunning) ? 'blender-stopped'
            : 'refused';
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
        ? connectedTooltip(this.lastLatencyMs, this.telemetry)
        : this.state === 'connecting'
          ? 'Reconnecting...'
          : disconnectTooltip(this.disconnectReason);
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

function disconnectTooltip(reason: DisconnectReason): string {
  switch (reason) {
    case 'no-token':
      return 'No auth token configured.\nClick to set one.';
    case 'blender-stopped':
      return 'Blender is not running (or the MCP add-on is stopped).\n' +
        'Start Blender and enable the Blender MCP Bridge add-on.';
    case 'auth-failed':
      return 'Authentication failed — token mismatch.\n' +
        'Re-copy the token from Blender preferences.';
    case 'refused':
      return 'Connection refused — Blender is running but the WS server is not.\n' +
        'Open Blender → Preferences → Add-ons → Blender MCP Bridge → Start.';
    case 'unknown':
    default:
      return 'Disconnected — click to retry.';
  }
}

function connectedTooltip(latencyMs: number, t: PingTelemetry | undefined): string {
  const lines = [`Connected (${latencyMs} ms ping)`];
  if (t) {
    if (t.blender_version) {
      lines.push(`Blender ${t.blender_version}` +
        (t.render_engine ? `  •  ${t.render_engine}` : '') +
        (t.units ? `  •  ${t.units}` : ''));
    }
    if (t.scene) {
      const counts = [
        typeof t.object_count === 'number' ? `${t.object_count} obj` : '',
        typeof t.material_count === 'number' ? `${t.material_count} mat` : '',
      ].filter(Boolean).join(', ');
      lines.push(`Scene: ${t.scene}${counts ? `  (${counts})` : ''}`);
    }
    if (t.active_object) { lines.push(`Active: ${t.active_object}`); }
  }
  lines.push('Click to open Blender MCP view');
  return lines.join('\n');
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
  private auditFilter: string = '';

  // Telemetry: cached summaries, last-write timestamp.
  private summaries: telemetry.DailySummary[] = [];
  private lastTelemetryWriteMs = 0;

  constructor(
    private readonly status: StatusController,
    private readonly context?: vscode.ExtensionContext,
  ) {
    status.onChange(() => this._onDidChange.fire(undefined));
  }

  refresh(): void {
    this._onDidChange.fire(undefined);
  }

  setAuditFilter(text: string): void {
    this.auditFilter = text.trim();
    this._onDidChange.fire(undefined);
  }

  getAuditFilter(): string { return this.auditFilter; }

  /** Look up an audit entry by op+ts (used by the peek command). */
  findAuditEntry(op: string, ts: string): AuditEntry | undefined {
    return this.audit.find((e) => e.op === op && e.ts === ts);
  }

  async refreshAuditLog(): Promise<void> {
    if (this.fetchingAudit) { return; }
    this.fetchingAudit = true;
    this.auditError = undefined;
    this._onDidChange.fire(undefined);
    const cfg = getConfig();
    if (!cfg.token) {
      this.auditError = cfg.source === 'none'
        ? 'No auth token configured'
        : 'Token unavailable';
      this.audit = [];
      this.fetchingAudit = false;
      this._onDidChange.fire(undefined);
      return;
    }
    try {
      const resp = await wsCall({
        host: cfg.host, port: cfg.port, token: cfg.token,
        op: 'audit.read', args: { limit: 50 }, timeoutMs: 8000,
      });
      if (resp.ok && resp.result && Array.isArray(resp.result['entries'])) {
        this.audit = resp.result['entries'] as AuditEntry[];
        // Write telemetry summary if enabled and at least 60s since last write.
        // Fire-and-forget — never block the UI on disk.
        const tcfg = vscode.workspace.getConfiguration('blenderMcp');
        if (tcfg.get<boolean>('telemetry.enabled', false)) {
          const now = Date.now();
          if (now - this.lastTelemetryWriteMs >= 60_000) {
            this.lastTelemetryWriteMs = now;
            void this._writeTelemetry();
          }
        }
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
        this.snippetsGroup(),
        this.telemetryGroup(),
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
          : disconnectShortLabel(this.status.getDisconnectReason());
    const stateTooltip =
      state === 'disconnected' ? disconnectFullText(this.status.getDisconnectReason())
        : undefined;
    const items: vscode.TreeItem[] = [
      new StatusItem('Status', stateLabel, stateTooltip, stateIcon),
      new StatusItem('URL', `ws://${cfg.host}:${cfg.port}`, undefined, 'globe'),
      tokenItem(cfg),
    ];
    if (isRemoteHost(cfg.host)) {
      const ackKey = `blenderMcp.remoteAck:${cfg.host}`;
      const acked = this.context?.globalState.get<boolean>(ackKey, false) ?? false;
      const item = new StatusItem(
        '⚠ Remote host',
        acked ? `${cfg.host} (acknowledged — click to revoke)` : `${cfg.host} (NOT acknowledged — click to acknowledge)`,
        acked
          ? 'The MCP server is enabled against this non-loopback Blender host. Click to revoke the acknowledgement.'
          : 'The MCP server is disabled until you acknowledge this non-loopback Blender host. Click to review the risks and acknowledge.',
        'warning',
      );
      item.command = {
        command: acked ? 'blenderMcp.revokeRemoteHost' : 'blenderMcp.acknowledgeRemoteHost',
        title: acked ? 'Revoke remote host acknowledgement' : 'Acknowledge remote host',
      };
      items.push(item);
    }
    return new GroupItem('Connection', items);
  }

  private actionsGroup(): GroupItem {
    return new GroupItem('Quick Actions', [
      cmdItem('Set Auth Token', 'key', 'blenderMcp.setToken'),
      cmdItem('Take Viewport Screenshot', 'device-camera',
        'blenderMcp.showViewportPreview'),
      cmdItem('Refresh Audit Log', 'refresh',
        'blenderMcp.refreshAuditLog'),
      cmdItem('Reconnect', 'sync', 'blenderMcp.reconnect'),
      cmdItem('Show Output Channel', 'output', 'blenderMcp.showOutput'),
    ]);
  }

  private snippetsGroup(): GroupItem {
    if (!this.context) {
      return new GroupItem('Snippets', []);
    }
    const all = loadSnippets(this.context);
    if (all.length === 0) {
      return new GroupItem('Snippets', [
        new StatusItem('No snippets', 'Bundled snippets failed to load', undefined, 'warning'),
      ]);
    }
    const items: vscode.TreeItem[] = [];
    for (const [category, list] of groupByCategory(all)) {
      // Lightweight category header so users can scan the list.
      const header = new vscode.TreeItem(category);
      header.contextValue = 'snippetCategory';
      header.iconPath = new vscode.ThemeIcon('symbol-folder');
      items.push(header);
      for (const s of list) {
        items.push(snippetItem(s));
      }
    }
    return new GroupItem(`Snippets (${all.length})`, items);
  }

  private telemetryGroup(): GroupItem {
    const cfg = vscode.workspace.getConfiguration('blenderMcp');
    if (!cfg.get<boolean>('telemetry.enabled', false)) {
      const item = new StatusItem(
        'Telemetry disabled',
        'Click to enable',
        'Local-only usage summaries — opt-in.',
        'eye-closed',
      );
      item.command = {
        command: 'workbench.action.openSettings',
        title: 'Open settings',
        arguments: ['blenderMcp.telemetry.enabled'],
      };
      return new GroupItem('Tool Usage', [item]);
    }
    // Lazy-load summaries the first time the group is rendered.
    if (this.summaries.length === 0) {
      void telemetry.readSummaries(telemetry.summariesDir()).then((s) => {
        if (s.length > 0) { this.summaries = s; this._onDidChange.fire(undefined); }
      });
    }
    const today = new Date().toISOString().slice(0, 10);
    const todaySummary = this.summaries.find((s) => s.date === today);
    const last7 = this.summaries.slice(0, 7);

    const items: vscode.TreeItem[] = [];
    const todayHeader = new vscode.TreeItem('Today');
    todayHeader.iconPath = new vscode.ThemeIcon('calendar');
    items.push(todayHeader);
    if (todaySummary) {
      for (const t of telemetry.topOps(todaySummary, 5)) {
        const total = t.ok + t.err;
        const avg = total > 0 ? Math.round(t.total_ms / total) : 0;
        const item = new vscode.TreeItem(t.op);
        item.description = `${t.ok}/${total} \u00b7 avg ${avg}ms`;
        item.iconPath = new vscode.ThemeIcon(t.err > 0 ? 'warning' : 'check');
        items.push(item);
      }
    } else {
      const empty = new vscode.TreeItem('No activity today');
      empty.iconPath = new vscode.ThemeIcon('dash');
      items.push(empty);
    }

    const weekHeader = new vscode.TreeItem('Last 7 days');
    weekHeader.iconPath = new vscode.ThemeIcon('graph');
    items.push(weekHeader);
    if (last7.length > 0) {
      for (const t of telemetry.topOps(last7, 5)) {
        const total = t.ok + t.err;
        const avg = total > 0 ? Math.round(t.total_ms / total) : 0;
        const item = new vscode.TreeItem(t.op);
        item.description = `${t.ok}/${total} \u00b7 avg ${avg}ms`;
        item.iconPath = new vscode.ThemeIcon(t.err > 0 ? 'warning' : 'check');
        items.push(item);
      }
    } else {
      const empty = new vscode.TreeItem('No activity yet');
      empty.iconPath = new vscode.ThemeIcon('dash');
      items.push(empty);
    }

    const open = new vscode.TreeItem('Open telemetry folder');
    open.iconPath = new vscode.ThemeIcon('folder-opened');
    open.command = {
      command: 'blenderMcp.telemetry.openFolder',
      title: 'Open telemetry folder',
    };
    items.push(open);
    return new GroupItem('Tool Usage', items);
  }

  /**
   * Background write: aggregate the current `audit` cache into per-day
   * summaries and persist them. Errors are logged via console only —
   * telemetry must never disrupt the UI.
   */
  private async _writeTelemetry(): Promise<void> {
    try {
      const summaries = telemetry.aggregate(this.audit as telemetry.AuditEntry[]);
      if (summaries.length === 0) { return; }
      await telemetry.writeSummaries(telemetry.summariesDir(), summaries);
      this.summaries = summaries;
      this._onDidChange.fire(undefined);
    } catch (err: unknown) {
      console.warn('[blender-mcp] telemetry write failed:', err);
    }
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
    const filter = this.auditFilter.toLowerCase();
    const filtered = filter
      ? this.audit.filter((e) => e.op.toLowerCase().includes(filter))
      : this.audit;
    const items = filtered.slice(0, 50).map((e) => {
      const t = new vscode.TreeItem(e.op);
      t.description = `${e.elapsed_ms} ms`;
      t.iconPath = new vscode.ThemeIcon(e.ok ? 'check' : 'x');
      t.tooltip = `${e.ts}\n${e.op} ${e.ok ? 'OK' : 'FAIL'}  ${e.elapsed_ms} ms${e.args_sha256 ? `\nargs#${e.args_sha256}` : ''
        }`;
      // Click to peek the full entry as JSON.
      t.command = {
        command: 'blenderMcp.audit.showEntry',
        title: 'Show audit entry',
        arguments: [e.op, e.ts],
      };
      return t;
    });
    const label = filter
      ? `Recent Activity (${filtered.length}/${this.audit.length}, filter: ${this.auditFilter})`
      : `Recent Activity (${this.audit.length})`;
    return new GroupItem(label, items);
  }
}

function cmdItem(label: string, icon: string, command: string): vscode.TreeItem {
  const t = new vscode.TreeItem(label);
  t.iconPath = new vscode.ThemeIcon(icon);
  t.command = { command, title: label };
  return t;
}

function snippetItem(s: Snippet): vscode.TreeItem {
  const t = new vscode.TreeItem(s.label);
  t.tooltip = s.description ?? s.prompt.slice(0, 200);
  t.iconPath = new vscode.ThemeIcon('comment-discussion');
  t.contextValue = 'blenderMcpSnippet';
  t.command = {
    command: 'blenderMcp.snippet.run',
    title: 'Send to Copilot Chat',
    arguments: [s.id],
  };
  return t;
}

function tokenItem(cfg: ResolvedConnection): StatusItem {
  const sourceLabel: Record<string, string> = {
    env: 'env BLENDER_MCP_TOKEN',
    file: '~/.blender_mcp/connection.json',
    secret: 'VS Code SecretStorage',
    setting: 'blenderMcp.token setting (deprecated)',
    none: 'not set',
  };
  const item = new StatusItem(
    'Token',
    cfg.token
      ? `${cfg.token.slice(0, 4)}\u2026${cfg.token.slice(-4)} (${cfg.source})`
      : 'NOT SET — click to set',
    cfg.token
      ? `Source: ${sourceLabel[cfg.source]}`
      : 'Click to paste your Blender auth token',
    cfg.token ? 'key' : 'warning',
  );
  if (!cfg.token) {
    item.command = { command: 'blenderMcp.setToken', title: 'Set Token' };
  }
  return item;
}

export function disconnectShortLabel(reason: DisconnectReason): string {
  switch (reason) {
    case 'no-token': return 'No token';
    case 'blender-stopped': return 'Blender not running';
    case 'auth-failed': return 'Auth failed';
    case 'refused': return 'Connection refused';
    default: return 'Disconnected';
  }
}

export function disconnectFullText(reason: DisconnectReason): string {
  switch (reason) {
    case 'no-token':
      return 'Set BLENDER_MCP_TOKEN, run the Blender add-on, or use the ' +
        '"Set Auth Token" command.';
    case 'blender-stopped':
      return 'Start Blender and enable the Blender MCP Bridge add-on. The ' +
        'add-on writes ~/.blender_mcp/connection.json on startup.';
    case 'auth-failed':
      return 'Token mismatch. Re-copy from Blender → Preferences → Add-ons ' +
        '→ Blender MCP Bridge → Copy Token.';
    case 'refused':
      return 'Blender appears to be running but its WS server is not. Open ' +
        'the add-on preferences and click Start.';
    default:
      return '';
  }
}
