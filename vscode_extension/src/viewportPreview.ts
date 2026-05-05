import * as vscode from 'vscode';
import * as crypto from 'crypto';
import { wsRequest } from './wsClient';

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
