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

// vscode.lm.registerMcpServerDefinitionProvider was added in 1.99.
// We feature-detect at runtime so the extension still loads on slightly older
// builds, just without auto-registration.
type LmApi = typeof vscode.lm & {
  registerMcpServerDefinitionProvider?: (
    id: string,
    provider: BlenderMcpProvider,
  ) => vscode.Disposable;
};

export class BlenderMcpProvider {
  private readonly _onDidChange = new vscode.EventEmitter<void>();
  readonly onDidChangeMcpServerDefinitions = this._onDidChange.event;

  constructor(
    private readonly _channel: vscode.OutputChannel,
    private readonly _approval: ApprovalServer,
  ) {}

  /** Trigger a re-query (e.g. after settings change). */
  refresh(): void {
    this._onDidChange.fire();
  }

  // VS Code 1.99 API surface:
  //   provideMcpServerDefinitions(): Promise<McpServerDefinition[]>
  //   resolveMcpServerDefinition?(server, token): McpServerDefinition
  async provideMcpServerDefinitions(): Promise<unknown[]> {
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
    const token = (cfg.get<string>('token') ?? '').trim();
    if (token) {
      env['BLENDER_MCP_TOKEN'] = token;
    }
    const host = (cfg.get<string>('host') ?? '127.0.0.1').trim();
    const port = cfg.get<number>('port') ?? 9876;
    env['BLENDER_MCP_URL'] = `ws://${host}:${port}`;

    // Plumb the approval endpoint through env so the MCP server discovers it
    // without needing to read the discovery file. (Discovery file still works
    // for users running the server outside VS Code.)
    if (this._approval.getPort() > 0) {
      env['BLENDER_MCP_APPROVAL_URL'] = this._approval.getBaseUrl();
      env['BLENDER_MCP_APPROVAL_CSRF'] = this._approval.getCsrf();
    }

    // Build the definition. We use a structural object instead of importing
    // the (possibly-missing) class so we stay compile-safe across versions.
    const def = {
      label: 'Blender MCP',
      command: pythonPath,
      args: ['-m', serverModule],
      env,
    };

    this._channel.appendLine(
      `MCP provider: registered "blender" -> ${pythonPath} -m ${serverModule}`,
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
      const data = JSON.parse(fs.readFileSync(file, 'utf-8')) as {
        servers?: Record<string, unknown>;
      };
      if (data.servers && Object.prototype.hasOwnProperty.call(data.servers, 'blender')) {
        return true;
      }
    } catch (e) {
      channel.appendLine(`MCP provider: failed to parse ${file}: ${(e as Error).message}`);
    }
  }
  return false;
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
  const provider = new BlenderMcpProvider(channel, approval);
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

  return { provider, disposable };
}
