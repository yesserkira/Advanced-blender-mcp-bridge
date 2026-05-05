import * as vscode from 'vscode';
import { ApprovalServer } from './approval';
import { ViewportPreviewPanel } from './viewportPreview';
import { McpTreeProvider, StatusController } from './statusUi';
import { registerBlenderMcpProvider } from './mcpProvider';

let outputChannel: vscode.OutputChannel | undefined;

export function getOutputChannel(): vscode.OutputChannel {
  if (!outputChannel) {
    outputChannel = vscode.window.createOutputChannel('Blender MCP');
  }
  return outputChannel;
}

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  const channel = getOutputChannel();
  channel.appendLine('Blender MCP Bridge v2.0 activated.');

  // ----- status bar + tree view --------------------------------------------
  const status = new StatusController(context);
  const tree = new McpTreeProvider(status);
  const treeView = vscode.window.createTreeView('blenderMcpView', {
    treeDataProvider: tree,
    showCollapseAll: true,
  });
  context.subscriptions.push(treeView);
  status.start(5000);
  context.subscriptions.push({ dispose: () => status.stop() });
  status.onChange((s) => { if (s === 'connected') { void tree.refreshAuditLog(); } });

  // ----- commands ----------------------------------------------------------
  context.subscriptions.push(
    vscode.commands.registerCommand('blenderMcp.showOutput', () => channel.show(true)),
    vscode.commands.registerCommand('blenderMcp.showStatus', async () => {
      await vscode.commands.executeCommand('workbench.view.extension.blenderMcp');
    }),
    vscode.commands.registerCommand('blenderMcp.reconnect', async () => {
      await status.poll();
      await tree.refreshAuditLog();
    }),
    vscode.commands.registerCommand('blenderMcp.refreshAuditLog', async () => {
      await tree.refreshAuditLog();
    }),
    vscode.commands.registerCommand('blenderMcp.showViewportPreview', () => {
      const panel = ViewportPreviewPanel.createOrShow(context);
      void panel.refreshScreenshot();
    }),
  );

  // ----- approval server (kept from v1) ------------------------------------
  const config = vscode.workspace.getConfiguration('blenderMcp');
  const approvalServer = new ApprovalServer(context);
  try {
    const port = await approvalServer.start(config.get('approvalServer.port', 0));
    channel.appendLine(`Approval server listening on port ${port}`);
  } catch (err) {
    channel.appendLine(`Failed to start approval server: ${err}`);
  }
  context.subscriptions.push({ dispose: () => { void approvalServer.stop(); } });

  // ----- programmatic MCP server registration (Copilot Chat / Agent mode) ---
  const { provider } = registerBlenderMcpProvider(context, channel, approvalServer);
  // Trigger an initial refresh now that approval server has a port.
  provider.refresh();

  context.subscriptions.push(channel);
}

export function deactivate(): void {
  if (outputChannel) {
    outputChannel.dispose();
    outputChannel = undefined;
  }
}
