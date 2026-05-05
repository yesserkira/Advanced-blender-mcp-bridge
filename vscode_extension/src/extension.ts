import * as vscode from 'vscode';
import { ApprovalServer } from './approval';
import { ViewportPreviewPanel } from './viewportPreview';

let outputChannel: vscode.OutputChannel | undefined;

export function getOutputChannel(): vscode.OutputChannel {
  if (!outputChannel) {
    outputChannel = vscode.window.createOutputChannel('Blender MCP');
  }
  return outputChannel;
}

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  const channel = getOutputChannel();
  channel.appendLine('Blender MCP Bridge extension activated.');

  const showOutputCmd = vscode.commands.registerCommand(
    'blenderMcp.showOutput',
    () => {
      channel.show(true);
    }
  );
  context.subscriptions.push(showOutputCmd);

  // T-503: Approval server
  const config = vscode.workspace.getConfiguration('blenderMcp');
  const approvalServer = new ApprovalServer(context);
  try {
    const port = await approvalServer.start(config.get('approvalServer.port', 0));
    channel.appendLine(`Approval server listening on port ${port}`);
  } catch (err) {
    channel.appendLine(`Failed to start approval server: ${err}`);
  }
  context.subscriptions.push({ dispose: () => { void approvalServer.stop(); } });

  const approveCmd = vscode.commands.registerCommand(
    'blenderMcp.approveAction',
    () => {
      channel.appendLine('Approval server is running. Requests are handled automatically.');
      channel.show(true);
    }
  );
  context.subscriptions.push(approveCmd);

  // T-504: Viewport preview
  const previewCmd = vscode.commands.registerCommand(
    'blenderMcp.showViewportPreview',
    () => {
      ViewportPreviewPanel.createOrShow(context);
    }
  );
  context.subscriptions.push(previewCmd);

  context.subscriptions.push(channel);
}

export function deactivate(): void {
  if (outputChannel) {
    outputChannel.dispose();
    outputChannel = undefined;
  }
}
