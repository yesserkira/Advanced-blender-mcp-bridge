// Virtual document provider for showing a single audit-log entry's full
// arguments / metadata as JSON in a read-only editor tab.

import * as vscode from 'vscode';

export const AUDIT_PEEK_SCHEME = 'blender-mcp-audit';

const _store = new Map<string, string>();

export function registerAuditPeek(context: vscode.ExtensionContext): void {
  const provider: vscode.TextDocumentContentProvider = {
    provideTextDocumentContent(uri) {
      return _store.get(uri.toString()) ?? '(entry not found)';
    },
  };
  context.subscriptions.push(
    vscode.workspace.registerTextDocumentContentProvider(AUDIT_PEEK_SCHEME, provider),
  );
}

/** Open a virtual doc for the given audit entry. Returns the URI used. */
export async function openAuditEntry(entry: Record<string, unknown>): Promise<vscode.Uri> {
  const op = String(entry['op'] ?? 'entry');
  const ts = String(entry['ts'] ?? Date.now());
  const safeOp = op.replace(/[^a-z0-9._-]/gi, '_');
  const uri = vscode.Uri.parse(
    `${AUDIT_PEEK_SCHEME}:/${safeOp}-${encodeURIComponent(ts)}.json`,
  );
  _store.set(uri.toString(), JSON.stringify(entry, null, 2));
  const doc = await vscode.workspace.openTextDocument(uri);
  await vscode.languages.setTextDocumentLanguage(doc, 'json');
  await vscode.window.showTextDocument(doc, { preview: true });
  return uri;
}
