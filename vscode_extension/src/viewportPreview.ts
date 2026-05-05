import * as vscode from 'vscode';
import * as net from 'net';
import * as crypto from 'crypto';

// ---------------------------------------------------------------------------
// Minimal WebSocket client (RFC 6455) — single request/response, text frames
// ---------------------------------------------------------------------------

interface WsResponse {
  ok: boolean;
  result?: Record<string, unknown>;
  error?: { code: string; message: string };
}

function wsRequest(
  host: string,
  port: number,
  payload: string,
  timeoutMs = 15_000,
): Promise<WsResponse> {
  return new Promise((resolve, reject) => {
    const key = crypto.randomBytes(16).toString('base64');
    const socket = net.createConnection({ host, port }, () => {
      const req = [
        `GET / HTTP/1.1`,
        `Host: ${host}:${port}`,
        `Upgrade: websocket`,
        `Connection: Upgrade`,
        `Sec-WebSocket-Key: ${key}`,
        `Sec-WebSocket-Version: 13`,
        ``,
        ``,
      ].join('\r\n');
      socket.write(req);
    });

    let upgraded = false;
    let headerBuf = Buffer.alloc(0);
    let frameBuf = Buffer.alloc(0);
    let messageSent = false;

    const timer = setTimeout(() => {
      socket.destroy();
      reject(new Error('WebSocket request timed out'));
    }, timeoutMs);

    socket.on('data', (chunk: Buffer) => {
      if (!upgraded) {
        headerBuf = Buffer.concat([headerBuf, chunk]);
        const headerEnd = headerBuf.indexOf('\r\n\r\n');
        if (headerEnd === -1) { return; }

        const headerStr = headerBuf.subarray(0, headerEnd).toString();
        if (!headerStr.includes('101')) {
          clearTimeout(timer);
          socket.destroy();
          reject(new Error(`WebSocket upgrade failed: ${headerStr.split('\r\n')[0]}`));
          return;
        }

        upgraded = true;
        const remaining = headerBuf.subarray(headerEnd + 4);
        headerBuf = Buffer.alloc(0);

        // Send the payload as a masked text frame
        if (!messageSent) {
          messageSent = true;
          socket.write(encodeTextFrame(payload));
        }

        if (remaining.length > 0) {
          frameBuf = Buffer.concat([frameBuf, remaining]);
          tryParseFrame();
        }
      } else {
        frameBuf = Buffer.concat([frameBuf, chunk]);
        tryParseFrame();
      }
    });

    function tryParseFrame(): void {
      const result = decodeFrame(frameBuf);
      if (!result) { return; }

      clearTimeout(timer);
      // Send a close frame and tear down
      socket.write(encodeCloseFrame());
      socket.end();

      try {
        resolve(JSON.parse(result) as WsResponse);
      } catch {
        reject(new Error('Invalid JSON in WebSocket response'));
      }
    }

    socket.on('error', (err) => {
      clearTimeout(timer);
      reject(err);
    });

    socket.on('close', () => {
      clearTimeout(timer);
    });
  });
}

/** Encode a UTF-8 string as a masked WebSocket text frame. */
function encodeTextFrame(text: string): Buffer {
  const data = Buffer.from(text, 'utf8');
  const len = data.length;

  let header: Buffer;
  if (len < 126) {
    header = Buffer.alloc(2);
    header[0] = 0x81; // FIN + TEXT
    header[1] = 0x80 | len; // MASK bit + length
  } else if (len < 65536) {
    header = Buffer.alloc(4);
    header[0] = 0x81;
    header[1] = 0x80 | 126;
    header.writeUInt16BE(len, 2);
  } else {
    header = Buffer.alloc(10);
    header[0] = 0x81;
    header[1] = 0x80 | 127;
    // Write 64-bit length (upper 32 bits = 0 for any reasonable payload)
    header.writeUInt32BE(0, 2);
    header.writeUInt32BE(len, 6);
  }

  const mask = crypto.randomBytes(4);
  const masked = Buffer.alloc(len);
  for (let i = 0; i < len; i++) {
    masked[i] = data[i] ^ mask[i % 4];
  }

  return Buffer.concat([header, mask, masked]);
}

/** Encode a WebSocket close frame (masked, no payload). */
function encodeCloseFrame(): Buffer {
  const mask = crypto.randomBytes(4);
  return Buffer.concat([Buffer.from([0x88, 0x80]), mask]);
}

/**
 * Attempt to decode a single unmasked text frame from the buffer.
 * Returns the payload string or undefined if the buffer is incomplete.
 * Server→client frames are unmasked per RFC 6455.
 */
function decodeFrame(buf: Buffer): string | undefined {
  if (buf.length < 2) { return undefined; }

  const byte1 = buf[0];
  const byte2 = buf[1];
  const isFin = (byte1 & 0x80) !== 0;
  const opcode = byte1 & 0x0f;
  const hasMask = (byte2 & 0x80) !== 0;
  let payloadLen = byte2 & 0x7f;
  let offset = 2;

  // Skip non-text frames (close=0x8, ping=0x9, pong=0xa)
  if (opcode === 0x8) { return undefined; }

  if (payloadLen === 126) {
    if (buf.length < 4) { return undefined; }
    payloadLen = buf.readUInt16BE(2);
    offset = 4;
  } else if (payloadLen === 127) {
    if (buf.length < 10) { return undefined; }
    payloadLen = buf.readUInt32BE(6); // ignore upper 32 bits
    offset = 10;
  }

  if (hasMask) { offset += 4; }

  if (buf.length < offset + payloadLen) { return undefined; }

  const payload = buf.subarray(offset, offset + payloadLen);

  if (!isFin) { return undefined; } // we only handle single-frame messages

  return payload.toString('utf8');
}

// ---------------------------------------------------------------------------
// ViewportPreviewPanel
// ---------------------------------------------------------------------------

export class ViewportPreviewPanel {
  static currentPanel: ViewportPreviewPanel | undefined;

  private readonly _panel: vscode.WebviewPanel;
  private _timer: ReturnType<typeof setInterval> | undefined;
  private readonly _disposables: vscode.Disposable[] = [];

  static createOrShow(context: vscode.ExtensionContext): ViewportPreviewPanel {
    if (ViewportPreviewPanel.currentPanel) {
      ViewportPreviewPanel.currentPanel._panel.reveal(vscode.ViewColumn.Beside);
      return ViewportPreviewPanel.currentPanel;
    }

    const panel = vscode.window.createWebviewPanel(
      'blenderViewport',
      'Blender Viewport',
      vscode.ViewColumn.Beside,
      { enableScripts: true, retainContextWhenHidden: true },
    );

    const instance = new ViewportPreviewPanel(context, panel);
    ViewportPreviewPanel.currentPanel = instance;
    return instance;
  }

  private constructor(
    _context: vscode.ExtensionContext,
    panel: vscode.WebviewPanel,
  ) {
    this._panel = panel;

    const nonce = crypto.randomBytes(16).toString('hex');
    this._panel.webview.html = getPreviewHtml(this._panel.webview, nonce);

    // Handle messages from the webview
    this._panel.webview.onDidReceiveMessage(
      async (msg: { command: string; seconds?: number }) => {
        if (msg.command === 'refresh') {
          await this.refreshScreenshot();
        } else if (msg.command === 'startAutoRefresh' && msg.seconds) {
          this.startAutoRefresh(msg.seconds);
        } else if (msg.command === 'stopAutoRefresh') {
          this.stopAutoRefresh();
        }
      },
      undefined,
      this._disposables,
    );

    // Clean up on dispose
    this._panel.onDidDispose(() => this.dispose(), null, this._disposables);

    // Auto-refresh from configuration
    const config = vscode.workspace.getConfiguration('blenderMcp.viewportPreview');
    if (config.get<boolean>('enabled', false)) {
      const interval = config.get<number>('intervalSeconds', 5);
      this.startAutoRefresh(interval);
    }
  }

  async refreshScreenshot(): Promise<void> {
    const config = vscode.workspace.getConfiguration('blenderMcp');
    const host = config.get<string>('host', '127.0.0.1');
    const port = config.get<number>('port', 9876);
    const token =
      process.env['BLENDER_MCP_TOKEN'] ??
      config.get<string>('token', '');

    if (!token) {
      this._panel.webview.postMessage({
        command: 'error',
        message: 'No auth token configured. Set BLENDER_MCP_TOKEN or blenderMcp.token.',
      });
      return;
    }

    const id = `preview-${crypto.randomBytes(4).toString('hex')}`;
    const payload = JSON.stringify({
      id,
      op: 'render.viewport_screenshot',
      args: { w: 800, h: 600 },
      auth: token,
    });

    try {
      const response = await wsRequest(host, port, payload);

      if (!response.ok || !response.result) {
        const errMsg = response.error?.message ?? 'Unknown error from Blender';
        this._panel.webview.postMessage({ command: 'error', message: errMsg });
        return;
      }

      const b64 = response.result['image_base64'] as string | undefined;
      if (!b64) {
        this._panel.webview.postMessage({
          command: 'error',
          message: 'No image data in response',
        });
        return;
      }

      this._panel.webview.postMessage({
        command: 'updateImage',
        data: `data:image/png;base64,${b64}`,
      });
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      this._panel.webview.postMessage({ command: 'error', message });
    }
  }

  startAutoRefresh(intervalSeconds: number): void {
    this.stopAutoRefresh();
    if (intervalSeconds < 1) { intervalSeconds = 1; }
    this._timer = setInterval(() => {
      void this.refreshScreenshot();
    }, intervalSeconds * 1000);
  }

  stopAutoRefresh(): void {
    if (this._timer !== undefined) {
      clearInterval(this._timer);
      this._timer = undefined;
    }
  }

  dispose(): void {
    ViewportPreviewPanel.currentPanel = undefined;
    this.stopAutoRefresh();
    for (const d of this._disposables) { d.dispose(); }
    this._panel.dispose();
  }
}

// ---------------------------------------------------------------------------
// Webview HTML
// ---------------------------------------------------------------------------

export function getPreviewHtml(
  _webview: vscode.Webview,
  nonce: string,
): string {
  return /* html */ `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta
    http-equiv="Content-Security-Policy"
    content="default-src 'none'; img-src data:; style-src 'nonce-${nonce}'; script-src 'nonce-${nonce}';"
  />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Blender Viewport</title>
  <style nonce="${nonce}">
    body {
      margin: 0;
      padding: 8px;
      background: var(--vscode-editor-background);
      color: var(--vscode-editor-foreground);
      font-family: var(--vscode-font-family);
      font-size: var(--vscode-font-size);
    }
    .toolbar {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 8px;
    }
    button {
      background: var(--vscode-button-background);
      color: var(--vscode-button-foreground);
      border: none;
      padding: 4px 12px;
      cursor: pointer;
      border-radius: 2px;
    }
    button:hover {
      background: var(--vscode-button-hoverBackground);
    }
    label { cursor: pointer; }
    #viewport {
      max-width: 100%;
      border: 1px solid var(--vscode-panel-border);
      display: block;
    }
    #status {
      margin-top: 4px;
      opacity: 0.7;
      font-size: 0.9em;
    }
    .error { color: var(--vscode-errorForeground); }
  </style>
</head>
<body>
  <div class="toolbar">
    <button id="btnRefresh">&#8635; Refresh</button>
    <label>
      <input type="checkbox" id="chkAuto" />
      Auto-refresh
    </label>
    <label>
      every
      <input
        type="number" id="numInterval" value="5" min="1" max="60"
        style="width:50px"
      />s
    </label>
  </div>
  <img id="viewport" alt="Viewport preview — click Refresh" />
  <div id="status">Not yet refreshed.</div>

  <script nonce="${nonce}">
    const vscode = acquireVsCodeApi();
    const img = document.getElementById('viewport');
    const status = document.getElementById('status');
    const btnRefresh = document.getElementById('btnRefresh');
    const chkAuto = document.getElementById('chkAuto');
    const numInterval = document.getElementById('numInterval');

    btnRefresh.addEventListener('click', () => {
      vscode.postMessage({ command: 'refresh' });
      status.textContent = 'Requesting…';
      status.className = '';
    });

    chkAuto.addEventListener('change', () => {
      if (chkAuto.checked) {
        const sec = parseInt(numInterval.value, 10) || 5;
        vscode.postMessage({ command: 'startAutoRefresh', seconds: sec });
        status.textContent = 'Auto-refresh started (' + sec + 's)';
        status.className = '';
      } else {
        vscode.postMessage({ command: 'stopAutoRefresh' });
        status.textContent = 'Auto-refresh stopped.';
        status.className = '';
      }
    });

    numInterval.addEventListener('change', () => {
      if (chkAuto.checked) {
        const sec = parseInt(numInterval.value, 10) || 5;
        vscode.postMessage({ command: 'startAutoRefresh', seconds: sec });
      }
    });

    window.addEventListener('message', (event) => {
      const msg = event.data;
      if (msg.command === 'updateImage') {
        img.src = msg.data;
        status.textContent = 'Last refresh: ' + new Date().toLocaleTimeString();
        status.className = '';
      } else if (msg.command === 'error') {
        status.textContent = 'Error: ' + msg.message;
        status.className = 'error';
      }
    });
  </script>
</body>
</html>`;
}
