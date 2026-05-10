import * as vscode from 'vscode';
import * as http from 'http';
import * as crypto from 'crypto';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';

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
  private _server: http.Server | null = null;
  private _sessionApprovals: Set<string> = new Set();
  private _csrf: string = '';
  private _port: number = 0;
  private _discoveryFile: string | null = null;

  // ---- rate limiting ------------------------------------------------------
  // Token bucket per remote address. Loopback only, so this is purely
  // defence-in-depth against a runaway local client (or an exploit that
  // tries to brute-force CSRF). Cap is generous for normal use.
  private static readonly RATE_BURST = 5;       // tokens
  private static readonly RATE_REFILL_MS = 1000; // 1 token per second
  private _buckets: Map<string, { tokens: number; ts: number }> = new Map();

  /** Returns true if the request from `peer` is allowed to proceed. */
  private _checkRate(peer: string): boolean {
    const now = Date.now();
    const bucket = this._buckets.get(peer) ?? { tokens: ApprovalServer.RATE_BURST, ts: now };
    const elapsed = now - bucket.ts;
    const refill = Math.floor(elapsed / ApprovalServer.RATE_REFILL_MS);
    if (refill > 0) {
      bucket.tokens = Math.min(ApprovalServer.RATE_BURST, bucket.tokens + refill);
      bucket.ts = now;
    }
    if (bucket.tokens <= 0) {
      this._buckets.set(peer, bucket);
      return false;
    }
    bucket.tokens -= 1;
    this._buckets.set(peer, bucket);
    // Cheap eviction: keep map small.
    if (this._buckets.size > 64) {
      const cutoff = now - 60_000;
      for (const [k, v] of this._buckets) {
        if (v.ts < cutoff) { this._buckets.delete(k); }
      }
    }
    return true;
  }

  constructor() { }

  /** Get the CSRF token (random per session). */
  getCsrf(): string { return this._csrf; }
  /** Get the bound port. */
  getPort(): number { return this._port; }
  /** Get http://127.0.0.1:PORT base URL. */
  getBaseUrl(): string { return `http://127.0.0.1:${this._port}`; }

  /** Start the HTTP approval server. Returns the actual bound port. */
  async start(port: number = 0): Promise<number> {
    this._csrf = crypto.randomBytes(32).toString('hex');
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
          this._port = addr.port;
          this._writeDiscovery();
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
    this._removeDiscovery();
    return new Promise<void>((resolve) => {
      if (this._server) {
        this._server.close(() => resolve());
        this._server = null;
      } else {
        resolve();
      }
    });
  }

  /** Write discovery file for the MCP server to find this approval endpoint. */
  private _writeDiscovery(): void {
    try {
      const dir = approvalDiscoveryDir();
      fs.mkdirSync(dir, { recursive: true });
      // Clean up any stale files (dead pid)
      this._cleanStaleDiscovery(dir);
      const file = path.join(dir, 'approval.json');
      const data = {
        url: this.getBaseUrl(),
        csrf: this._csrf,
        pid: process.pid,
        started_at: new Date().toISOString(),
      };
      fs.writeFileSync(file, JSON.stringify(data, null, 2), { encoding: 'utf-8', mode: 0o600 });
      this._discoveryFile = file;
    } catch {
      // best-effort
    }
  }

  private _removeDiscovery(): void {
    if (this._discoveryFile) {
      try { fs.unlinkSync(this._discoveryFile); } catch { /* ignore */ }
      this._discoveryFile = null;
    }
  }

  private _cleanStaleDiscovery(dir: string): void {
    try {
      const file = path.join(dir, 'approval.json');
      if (!fs.existsSync(file)) { return; }
      const raw = fs.readFileSync(file, 'utf-8');
      const data = JSON.parse(raw) as { pid?: number };
      if (typeof data.pid === 'number' && !isPidAlive(data.pid)) {
        fs.unlinkSync(file);
      }
    } catch {
      // ignore — will be overwritten
    }
  }

  private _handleRequest(req: http.IncomingMessage, res: http.ServerResponse): void {
    // SECURITY: reject non-loopback peers (defence in depth — we already bind 127.0.0.1).
    //
    // Phase 9 note: even when the user has opted into a *remote Blender host*
    // (i.e. the WebSocket add-on inside Blender binds to 0.0.0.0), this HTTP
    // approval endpoint MUST stay loopback-only. It exists to confirm
    // approvals coming from the local MCP server process, which always runs
    // on the same machine as VS Code. Loosening this check would let any
    // network-reachable peer mint approvals on the user's behalf.
    const peer = req.socket.remoteAddress ?? '';
    if (peer && peer !== '127.0.0.1' && peer !== '::1' && peer !== '::ffff:127.0.0.1') {
      res.writeHead(403, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Forbidden: loopback only' }));
      return;
    }

    // SECURITY: per-peer rate limit (token bucket).
    if (!this._checkRate(peer || 'unknown')) {
      res.writeHead(429, {
        'Content-Type': 'application/json',
        'Retry-After': '1',
      });
      res.end(JSON.stringify({ error: 'Too many requests' }));
      return;
    }

    // Only accept POST /approve
    if (req.method !== 'POST' || req.url !== '/approve') {
      res.writeHead(404, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Not found' }));
      return;
    }

    // SECURITY: CSRF check
    const csrf = (req.headers['x-csrf'] ?? '') as string;
    if (!this._csrf || !timingSafeEqualStr(csrf, this._csrf)) {
      res.writeHead(403, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Invalid CSRF token' }));
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
    // SECURITY: require unguessable request_id so an attacker can't replay
    // approvals for an arbitrary action by guessing the id.
    if (body.request_id.length < 16) {
      res.writeHead(400, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'request_id must be at least 16 characters' }));
      return;
    }
    if (!body.tool || typeof body.tool !== 'string') {
      res.writeHead(400, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'tool is required' }));
      return;
    }

    // Session approval cache key combines tool + sha256(args) so a different
    // argument shape (e.g. different code) re-prompts.
    const argsKey = sessionKey(body.tool, body.args ?? {});
    if (this._sessionApprovals.has(argsKey)) {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ approved: true, remember_session: true }));
      return;
    }

    // Show approval webview and wait for user decision
    try {
      const result = await ApprovalPanel.createOrShow(body);

      if (result.remember_session) {
        this._sessionApprovals.add(argsKey);
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

  private readonly _disposables: vscode.Disposable[] = [];

  private constructor() { }

  static createOrShow(
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

    const approvalPanel = new ApprovalPanel();
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

/** Discovery-file directory shared with the MCP server. */
export function approvalDiscoveryDir(): string {
  if (process.platform === 'win32') {
    const base = process.env['LOCALAPPDATA'] ?? path.join(os.homedir(), 'AppData', 'Local');
    return path.join(base, 'BlenderMCP');
  }
  if (process.platform === 'darwin') {
    return path.join(os.homedir(), 'Library', 'Application Support', 'BlenderMCP');
  }
  const xdg = process.env['XDG_RUNTIME_DIR'] ?? path.join(os.homedir(), '.local', 'state');
  return path.join(xdg, 'blender-mcp');
}

/** Constant-time string compare to avoid timing leaks on CSRF check. */
function timingSafeEqualStr(a: string, b: string): boolean {
  const ab = Buffer.from(a, 'utf-8');
  const bb = Buffer.from(b, 'utf-8');
  if (ab.length !== bb.length) { return false; }
  return crypto.timingSafeEqual(ab, bb);
}

/** Cross-platform liveness check for a pid (true = alive or unknown). */
function isPidAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (e: unknown) {
    const err = e as NodeJS.ErrnoException;
    return err.code === 'EPERM'; // exists but we can't signal
  }
}

/** Stable session-cache key combining tool name and a hash of args. */
function sessionKey(tool: string, args: Record<string, unknown>): string {
  const json = JSON.stringify(args, Object.keys(args).sort());
  const h = crypto.createHash('sha256').update(json).digest('hex').slice(0, 16);
  return `${tool}:${h}`;
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

  // Code preview: collapse long scripts to first 3 lines (or 500 chars on
  // a single very-long line) with a toggle to reveal the rest. Keeps the
  // approval modal compact for typical execute_python payloads.
  const PREVIEW_LINES = 3;
  const PREVIEW_MAX_CHARS = 500;
  let codeSection = '';
  if (code) {
    const lines = code.split('\n');
    const totalLines = lines.length;
    let truncated = false;
    let previewText: string;
    if (totalLines > PREVIEW_LINES) {
      previewText = lines.slice(0, PREVIEW_LINES).join('\n');
      truncated = true;
    } else {
      previewText = code;
    }
    if (previewText.length > PREVIEW_MAX_CHARS) {
      previewText = previewText.slice(0, PREVIEW_MAX_CHARS) + '\u2026';
      truncated = true;
    }
    const bannerText = truncated
      ? `Showing first ${Math.min(PREVIEW_LINES, totalLines)} of ${totalLines} lines &mdash; review full code before approving`
      : 'This action will execute Python code in Blender';
    const fullBlock = truncated
      ? `<pre class="code-block code-full hidden" id="codeFull"><code>${escapeHtml(code)}</code></pre>`
      : '';
    const toggleRow = truncated
      ? `<div class="code-actions">
          <button type="button" class="btn-link" id="toggleCodeBtn" aria-expanded="false" aria-controls="codeFull">Show full code</button>
          <button type="button" class="btn-link" id="copyCodeBtn">Copy to clipboard</button>
        </div>`
      : `<div class="code-actions">
          <button type="button" class="btn-link" id="copyCodeBtn">Copy to clipboard</button>
        </div>`;
    codeSection = `<div class="warning-banner">
        <span class="warning-icon">\u26A0\uFE0F</span>
        <strong>${bannerText}</strong>
      </div>
      <h3>Python Code</h3>
      <pre class="code-block code-preview" id="codePreview"><code>${escapeHtml(previewText)}</code></pre>
      ${fullBlock}
      ${toggleRow}`;
  }

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
    .code-full.hidden,
    .code-preview.hidden {
      display: none;
    }
    .code-actions {
      display: flex;
      gap: 12px;
      margin-top: 6px;
    }
    .btn-link {
      background: none;
      border: none;
      padding: 0;
      color: var(--vscode-textLink-foreground);
      font-size: 12px;
      cursor: pointer;
      text-decoration: underline;
    }
    .btn-link:hover {
      color: var(--vscode-textLink-activeForeground);
    }
    .copy-flash {
      color: var(--vscode-charts-green);
      text-decoration: none;
      cursor: default;
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

    const toggleBtn = document.getElementById('toggleCodeBtn');
    if (toggleBtn) {
      toggleBtn.addEventListener('click', () => {
        const full = document.getElementById('codeFull');
        const preview = document.getElementById('codePreview');
        if (!full || !preview) { return; }
        const expanded = !full.classList.contains('hidden');
        if (expanded) {
          full.classList.add('hidden');
          preview.classList.remove('hidden');
          toggleBtn.textContent = 'Show full code';
          toggleBtn.setAttribute('aria-expanded', 'false');
        } else {
          full.classList.remove('hidden');
          preview.classList.add('hidden');
          toggleBtn.textContent = 'Hide full code';
          toggleBtn.setAttribute('aria-expanded', 'true');
        }
      });
    }

    const copyBtn = document.getElementById('copyCodeBtn');
    if (copyBtn) {
      copyBtn.addEventListener('click', async () => {
        // Pull raw text from the (possibly hidden) full block when present,
        // otherwise the preview block. textContent reverses HTML entity
        // escaping so we get the original source back.
        const src = document.getElementById('codeFull') || document.getElementById('codePreview');
        if (!src) { return; }
        try {
          await navigator.clipboard.writeText(src.textContent || '');
          const original = copyBtn.textContent;
          copyBtn.textContent = 'Copied!';
          copyBtn.classList.add('copy-flash');
          setTimeout(() => {
            copyBtn.textContent = original;
            copyBtn.classList.remove('copy-flash');
          }, 1500);
        } catch {
          copyBtn.textContent = 'Copy failed';
        }
      });
    }
  </script>
</body>
</html>`;
}
