import * as vscode from 'vscode';
import * as http from 'http';
import * as crypto from 'crypto';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ApprovalRequest {
  tool: string;
  args: Record<string, unknown>;
  code?: string;
  request_id: string;
}

interface ApprovalResult {
  approved: boolean;
  remember_session: boolean;
}

// ---------------------------------------------------------------------------
// ApprovalServer — HTTP listener on 127.0.0.1 for MCP approval requests
// ---------------------------------------------------------------------------

export class ApprovalServer {
  private readonly _context: vscode.ExtensionContext;
  private _server: http.Server | null = null;
  private _sessionApprovals: Set<string> = new Set();

  constructor(context: vscode.ExtensionContext) {
    this._context = context;
  }

  /** Start the HTTP approval server. Returns the actual bound port. */
  async start(port: number = 0): Promise<number> {
    return new Promise<number>((resolve, reject) => {
      const server = http.createServer((req, res) => {
        this._handleRequest(req, res);
      });

      server.on('error', reject);

      // SECURITY: bind to loopback only — never 0.0.0.0
      server.listen(port, '127.0.0.1', () => {
        const addr = server.address();
        if (addr && typeof addr !== 'string') {
          this._server = server;
          resolve(addr.port);
        } else {
          server.close();
          reject(new Error('Failed to get server address'));
        }
      });
    });
  }

  /** Stop the HTTP server. */
  async stop(): Promise<void> {
    return new Promise<void>((resolve) => {
      if (this._server) {
        this._server.close(() => resolve());
        this._server = null;
      } else {
        resolve();
      }
    });
  }

  private _handleRequest(req: http.IncomingMessage, res: http.ServerResponse): void {
    // Only accept POST /approve
    if (req.method !== 'POST' || req.url !== '/approve') {
      res.writeHead(404, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Not found' }));
      return;
    }

    // Validate Content-Type
    const contentType = req.headers['content-type'] ?? '';
    if (!contentType.includes('application/json')) {
      res.writeHead(415, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Content-Type must be application/json' }));
      return;
    }

    const chunks: Buffer[] = [];
    req.on('data', (chunk: Buffer) => chunks.push(chunk));
    req.on('end', () => {
      void this._processBody(chunks, res);
    });
  }

  private async _processBody(chunks: Buffer[], res: http.ServerResponse): Promise<void> {
    let body: ApprovalRequest;
    try {
      body = JSON.parse(Buffer.concat(chunks).toString('utf-8')) as ApprovalRequest;
    } catch {
      res.writeHead(400, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Invalid JSON' }));
      return;
    }

    // Validate required fields
    if (!body.request_id || typeof body.request_id !== 'string') {
      res.writeHead(400, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'request_id is required and must be a non-empty string' }));
      return;
    }
    if (!body.tool || typeof body.tool !== 'string') {
      res.writeHead(400, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'tool is required' }));
      return;
    }

    // Check session auto-approvals
    if (this._sessionApprovals.has(body.tool)) {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ approved: true, remember_session: true }));
      return;
    }

    // Show approval webview and wait for user decision
    try {
      const result = await ApprovalPanel.createOrShow(this._context, body);

      if (result.remember_session) {
        this._sessionApprovals.add(body.tool);
      }

      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({
        approved: result.approved,
        remember_session: result.remember_session,
      }));
    } catch {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Internal error' }));
    }
  }
}

// ---------------------------------------------------------------------------
// ApprovalPanel — VS Code webview for approve / reject UI
// ---------------------------------------------------------------------------

class ApprovalPanel {
  private static readonly viewType = 'blenderMcpApproval';

  private readonly _panel: vscode.WebviewPanel;
  private readonly _disposables: vscode.Disposable[] = [];

  private constructor(panel: vscode.WebviewPanel) {
    this._panel = panel;
  }

  static createOrShow(
    context: vscode.ExtensionContext,
    data: ApprovalRequest,
  ): Promise<ApprovalResult> {
    const column = vscode.ViewColumn.Beside;

    const panel = vscode.window.createWebviewPanel(
      ApprovalPanel.viewType,
      'Blender MCP: Approve Action?',
      column,
      {
        enableScripts: true,
        localResourceRoots: [],
      },
    );

    const approvalPanel = new ApprovalPanel(panel);
    panel.webview.html = getWebviewContent(panel.webview, data.tool, data.args, data.code);

    return new Promise<ApprovalResult>((resolve) => {
      let resolved = false;

      // Listen for messages from the webview
      panel.webview.onDidReceiveMessage(
        (message: { command: string }) => {
          if (resolved) {
            return;
          }
          resolved = true;

          let result: ApprovalResult;
          switch (message.command) {
            case 'approve':
              result = { approved: true, remember_session: false };
              break;
            case 'approve_session':
              result = { approved: true, remember_session: true };
              break;
            case 'reject':
            default:
              result = { approved: false, remember_session: false };
              break;
          }

          panel.dispose();
          resolve(result);
        },
        null,
        approvalPanel._disposables,
      );

      // Treat panel close as reject
      panel.onDidDispose(
        () => {
          approvalPanel._dispose();
          if (!resolved) {
            resolved = true;
            resolve({ approved: false, remember_session: false });
          }
        },
        null,
        approvalPanel._disposables,
      );
    });
  }

  private _dispose(): void {
    for (const d of this._disposables) {
      d.dispose();
    }
    this._disposables.length = 0;
  }
}

// ---------------------------------------------------------------------------
// Webview HTML generation
// ---------------------------------------------------------------------------

function getNonce(): string {
  return crypto.randomBytes(16).toString('base64');
}

function escapeHtml(unsafe: string): string {
  return unsafe
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

export function getWebviewContent(
  webview: vscode.Webview,
  tool: string,
  args: Record<string, unknown>,
  code?: string,
): string {
  const nonce = getNonce();
  const argsJson = escapeHtml(JSON.stringify(args, null, 2));
  const toolName = escapeHtml(tool);

  const codeSection = code
    ? `<div class="warning-banner">
        <span class="warning-icon">⚠️</span>
        <strong>This action will execute Python code in Blender</strong>
      </div>
      <h3>Python Code</h3>
      <pre class="code-block"><code>${escapeHtml(code)}</code></pre>`
    : '';

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="Content-Security-Policy"
        content="default-src 'none'; style-src ${webview.cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}';">
  <title>Approve Action</title>
  <style>
    body {
      font-family: var(--vscode-font-family);
      color: var(--vscode-foreground);
      background-color: var(--vscode-editor-background);
      padding: 16px;
      margin: 0;
    }
    .card {
      border: 1px solid var(--vscode-panel-border);
      border-radius: 6px;
      padding: 20px;
      max-width: 640px;
      margin: 0 auto;
    }
    h2 {
      margin-top: 0;
      color: var(--vscode-foreground);
    }
    h3 {
      margin-bottom: 8px;
      color: var(--vscode-descriptionForeground);
    }
    .tool-name {
      font-family: var(--vscode-editor-font-family);
      background: var(--vscode-textCodeBlock-background);
      padding: 2px 6px;
      border-radius: 3px;
      font-size: 1.1em;
    }
    pre {
      background: var(--vscode-textCodeBlock-background);
      border: 1px solid var(--vscode-panel-border);
      border-radius: 4px;
      padding: 12px;
      overflow-x: auto;
      font-family: var(--vscode-editor-font-family);
      font-size: var(--vscode-editor-font-size);
      line-height: 1.4;
      white-space: pre-wrap;
      word-wrap: break-word;
    }
    .warning-banner {
      background: var(--vscode-inputValidation-warningBackground);
      border: 1px solid var(--vscode-inputValidation-warningBorder);
      border-radius: 4px;
      padding: 10px 14px;
      margin: 16px 0 8px;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .warning-icon {
      font-size: 1.2em;
    }
    .button-row {
      display: flex;
      gap: 8px;
      margin-top: 20px;
      flex-wrap: wrap;
    }
    button {
      padding: 8px 16px;
      border: none;
      border-radius: 4px;
      cursor: pointer;
      font-family: var(--vscode-font-family);
      font-size: 13px;
      font-weight: 500;
    }
    .btn-approve {
      background: var(--vscode-button-background);
      color: var(--vscode-button-foreground);
    }
    .btn-approve:hover {
      background: var(--vscode-button-hoverBackground);
    }
    .btn-reject {
      background: var(--vscode-button-secondaryBackground);
      color: var(--vscode-button-secondaryForeground);
    }
    .btn-reject:hover {
      background: var(--vscode-button-secondaryHoverBackground);
    }
    .btn-session {
      background: transparent;
      color: var(--vscode-textLink-foreground);
      border: 1px solid var(--vscode-textLink-foreground);
    }
    .btn-session:hover {
      background: var(--vscode-textLink-foreground);
      color: var(--vscode-editor-background);
    }
  </style>
</head>
<body>
  <div class="card">
    <h2>Approve Action?</h2>
    <p>The AI wants to call: <span class="tool-name">${toolName}</span></p>

    <h3>Arguments</h3>
    <pre><code>${argsJson}</code></pre>

    ${codeSection}

    <div class="button-row">
      <button class="btn-approve" id="approveBtn">Approve</button>
      <button class="btn-reject" id="rejectBtn">Reject</button>
      <button class="btn-session" id="sessionBtn">Approve for Session</button>
    </div>
  </div>

  <script nonce="${nonce}">
    const vscode = acquireVsCodeApi();

    document.getElementById('approveBtn').addEventListener('click', () => {
      vscode.postMessage({ command: 'approve' });
    });
    document.getElementById('rejectBtn').addEventListener('click', () => {
      vscode.postMessage({ command: 'reject' });
    });
    document.getElementById('sessionBtn').addEventListener('click', () => {
      vscode.postMessage({ command: 'approve_session' });
    });
  </script>
</body>
</html>`;
}
