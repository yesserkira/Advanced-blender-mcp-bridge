// Programmatic MCP server registration for Copilot Chat (Agent mode).
//
// Implements vscode.McpServerDefinitionProvider so users get the Blender MCP
// server registered automatically once they install this extension and point
// `blenderMcp.pythonPath` at a Python interpreter that has `blender_mcp`
// installed. No more hand-editing `.vscode/mcp.json`.

import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import type { ApprovalServer } from './approval';
import {
  resolveConnection,
  startConnectionWatcher,
  onConnectionFileChanged,
  isRemoteHost,
} from './connectionConfig';
import { onSecretTokenChanged } from './secretToken';

// vscode.lm.registerMcpServerDefinitionProvider was added in 1.99.
// We feature-detect at runtime so the extension still loads on slightly older
// builds, just without auto-registration.
type LmApi = typeof vscode.lm & {
  registerMcpServerDefinitionProvider?: (
    id: string,
    provider: BlenderMcpProvider,
  ) => vscode.Disposable;
};

// vscode.McpStdioServerDefinition is also 1.99+. Reference it loosely so the
// module loads on older VS Code builds where the symbol is absent.
type VscodeWithMcp = typeof vscode & {
  McpStdioServerDefinition?: new (
    label: string,
    command: string,
    args?: string[],
    env?: Record<string, string | number | null>,
    version?: string,
  ) => unknown;
};

export class BlenderMcpProvider {
  private readonly _onDidChange = new vscode.EventEmitter<void>();
  readonly onDidChangeMcpServerDefinitions = this._onDidChange.event;

  constructor(
    private readonly _channel: vscode.OutputChannel,
    private readonly _approval: ApprovalServer,
    private readonly _context?: vscode.ExtensionContext,
  ) { }

  /** Trigger a re-query (e.g. after settings change). */
  refresh(): void {
    this._onDidChange.fire();
  }

  // VS Code 1.99 API surface:
  //   provideMcpServerDefinitions(token): Promise<McpServerDefinition[]>
  //   resolveMcpServerDefinition?(server, token): McpServerDefinition
  async provideMcpServerDefinitions(
    _token?: vscode.CancellationToken,
  ): Promise<unknown[]> {
    const cfg = vscode.workspace.getConfiguration('blenderMcp');
    const pythonPath = (cfg.get<string>('pythonPath') ?? '').trim();
    const serverModule = (cfg.get<string>('serverModule') ?? 'blender_mcp.server').trim();

    if (!pythonPath) {
      this._channel.appendLine(
        'MCP provider: blenderMcp.pythonPath is empty; skipping registration. ' +
        'Set it to the python.exe inside your venv (e.g. .../mcp_server/.venv/Scripts/python.exe).',
      );
      return [];
    }

    if (!fs.existsSync(pythonPath)) {
      this._channel.appendLine(
        `MCP provider: configured pythonPath does not exist: ${pythonPath}`,
      );
      void vscode.window.showWarningMessage(
        `Blender MCP: pythonPath not found: ${pythonPath}`,
      );
      return [];
    }

    if (workspaceMcpJsonDefinesBlender(this._channel)) {
      this._channel.appendLine(
        'MCP provider: workspace .vscode/mcp.json already defines a "blender" ' +
        'server; skipping programmatic registration to avoid duplicates.',
      );
      return [];
    }

    const env: Record<string, string> = {};
    const { host, port, token: resolvedToken } = resolveConnection();

    // Phase 9: refuse to register the MCP provider against a non-loopback
    // Blender host unless the user has explicitly acknowledged that host.
    // The ack lives in globalState keyed by host so a per-host opt-in is
    // remembered, but a brand-new remote target always re-prompts.
    if (isRemoteHost(host)) {
      const ackKey = `blenderMcp.remoteAck:${host}`;
      const acked = this._context?.globalState.get<boolean>(ackKey, false) ?? false;
      if (!acked) {
        this._channel.appendLine(
          `MCP provider: refusing to register against remote host ${host} ` +
          `until the user acknowledges via "Blender MCP: Acknowledge remote host".`,
        );
        // Best-effort, non-modal nudge. We don't await — provider activation
        // must stay non-blocking. The user can also run the command manually.
        void vscode.window
          .showWarningMessage(
            `Blender MCP is configured to connect to a non-loopback host (${host}). ` +
            `Acknowledge the risks before the MCP server is enabled.`,
            'Acknowledge remote host',
          )
          .then((choice) => {
            if (choice === 'Acknowledge remote host') {
              void vscode.commands.executeCommand('blenderMcp.acknowledgeRemoteHost');
            }
          });
        return [];
      }
    }

    if (resolvedToken) {
      env['BLENDER_MCP_TOKEN'] = resolvedToken;
    } else {
      this._channel.appendLine(
        'MCP provider: no token found (env BLENDER_MCP_TOKEN, ~/.blender_mcp/connection.json, ' +
        'or blenderMcp.token setting). MCP server will be registered but unauthenticated until ' +
        'Blender starts.',
      );
    }
    env['BLENDER_MCP_URL'] = `ws://${host}:${port}`;

    // Plumb the approval endpoint through env so the MCP server discovers it
    // without needing to read the discovery file. (Discovery file still works
    // for users running the server outside VS Code.)
    if (this._approval.getPort() > 0) {
      env['BLENDER_MCP_APPROVAL_URL'] = this._approval.getBaseUrl();
      env['BLENDER_MCP_APPROVAL_CSRF'] = this._approval.getCsrf();
    }

    // VS Code's McpServerDefinition is a discriminated union; downstream code
    // uses `instanceof` to pick stdio-vs-http transport. Construct the real
    // class instance whenever it's available, fall back to a plain object on
    // pre-1.99 builds (where the provider API doesn't exist either, so this
    // path is unreachable in practice).
    const v = vscode as VscodeWithMcp;
    const Ctor = v.McpStdioServerDefinition;
    const ext = vscode.extensions.getExtension('blendervscode.blender-mcp-bridge');
    const version = (ext?.packageJSON?.version as string | undefined) ?? undefined;

    let def: unknown;
    if (Ctor) {
      def = new Ctor('Blender MCP', pythonPath, ['-m', serverModule], env, version);
    } else {
      def = {
        label: 'Blender MCP',
        command: pythonPath,
        args: ['-m', serverModule],
        env,
        version,
      };
    }

    this._channel.appendLine(
      `MCP provider: registered "blender" -> ${pythonPath} -m ${serverModule}` +
      (Ctor ? '' : ' (fallback object — McpStdioServerDefinition class missing)'),
    );
    return [def];
  }
}

/** Return true if the workspace already declares a `blender` MCP server. */
function workspaceMcpJsonDefinesBlender(channel: vscode.OutputChannel): boolean {
  for (const folder of vscode.workspace.workspaceFolders ?? []) {
    const file = path.join(folder.uri.fsPath, '.vscode', 'mcp.json');
    if (!fs.existsSync(file)) {
      continue;
    }
    try {
      const raw = stripJsonComments(fs.readFileSync(file, 'utf-8'));
      const data = JSON.parse(raw) as {
        servers?: Record<string, unknown>;
      };
      if (data.servers && Object.prototype.hasOwnProperty.call(data.servers, 'blender')) {
        return true;
      }
    } catch (e: unknown) {
      channel.appendLine(`MCP provider: failed to parse ${file}: ${(e as Error).message}`);
    }
  }
  return false;
}

/**
 * Strip // line comments and /* block *\/ comments from a JSONC string while
 * preserving the original character offsets (so JSON.parse error messages
 * still point at meaningful columns). Quoted strings are left untouched.
 */
export function stripJsonComments(text: string): string {
  let out = '';
  let i = 0;
  const n = text.length;
  let inString = false;
  let stringQuote = '"';
  while (i < n) {
    const ch = text[i];
    const next = i + 1 < n ? text[i + 1] : '';
    if (inString) {
      out += ch;
      if (ch === '\\' && i + 1 < n) {
        out += text[i + 1];
        i += 2;
        continue;
      }
      if (ch === stringQuote) {
        inString = false;
      }
      i += 1;
      continue;
    }
    if (ch === '"' || ch === "'") {
      inString = true;
      stringQuote = ch;
      out += ch;
      i += 1;
      continue;
    }
    if (ch === '/' && next === '/') {
      // Skip to end of line, preserving newlines for offset alignment.
      while (i < n && text[i] !== '\n') {
        out += ' ';
        i += 1;
      }
      continue;
    }
    if (ch === '/' && next === '*') {
      out += '  ';
      i += 2;
      while (i < n && !(text[i] === '*' && i + 1 < n && text[i + 1] === '/')) {
        out += text[i] === '\n' ? '\n' : ' ';
        i += 1;
      }
      if (i < n) {
        out += '  ';
        i += 2;
      }
      continue;
    }
    out += ch;
    i += 1;
  }
  return out;
}

/**
 * Register the provider with VS Code if the API exists.
 * Returns a disposable, or undefined when the API is unavailable.
 */
export function registerBlenderMcpProvider(
  context: vscode.ExtensionContext,
  channel: vscode.OutputChannel,
  approval: ApprovalServer,
): { provider: BlenderMcpProvider; disposable: vscode.Disposable | undefined } {
  const provider = new BlenderMcpProvider(channel, approval, context);
  const lm = vscode.lm as LmApi;
  if (typeof lm.registerMcpServerDefinitionProvider !== 'function') {
    channel.appendLine(
      'MCP provider: vscode.lm.registerMcpServerDefinitionProvider not available ' +
      'in this VS Code build; falling back to manual .vscode/mcp.json setup.',
    );
    return { provider, disposable: undefined };
  }
  const disposable = lm.registerMcpServerDefinitionProvider('blenderMcp.provider', provider);
  context.subscriptions.push(disposable);

  // Re-fire registration when relevant settings change.
  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (
        e.affectsConfiguration('blenderMcp.pythonPath') ||
        e.affectsConfiguration('blenderMcp.serverModule') ||
        e.affectsConfiguration('blenderMcp.token') ||
        e.affectsConfiguration('blenderMcp.host') ||
        e.affectsConfiguration('blenderMcp.port')
      ) {
        provider.refresh();
      }
    }),
  );

  // Watch ~/.blender_mcp/connection.json so when the user starts (or stops)
  // Blender after VS Code is already running, the MCP server registration is
  // re-fired with the freshly written token. The watcher itself lives in
  // connectionConfig.ts; we just subscribe.
  context.subscriptions.push(startConnectionWatcher());
  context.subscriptions.push(onConnectionFileChanged(() => {
    channel.appendLine('MCP provider: connection.json changed; refreshing registration.');
    provider.refresh();
  }));
  context.subscriptions.push(onSecretTokenChanged(() => {
    channel.appendLine('MCP provider: secret token changed; refreshing registration.');
    provider.refresh();
  }));

  return { provider, disposable };
}
