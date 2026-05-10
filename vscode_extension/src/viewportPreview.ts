import * as vscode from 'vscode';
import * as crypto from 'crypto';
import * as fs from 'fs/promises';
import { wsRequest } from './wsClient';
import { resolveConnection } from './connectionConfig';

// ---------------------------------------------------------------------------
// ViewportPreviewPanel
// ---------------------------------------------------------------------------

export class ViewportPreviewPanel {
  static currentPanel: ViewportPreviewPanel | undefined;

  private readonly _panel: vscode.WebviewPanel;
  private _timer: ReturnType<typeof setInterval> | undefined;
  private _autoRefreshSeconds = 0;
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
      async (msg: { command: string; seconds?: number; data?: string }) => {
        if (msg.command === 'refresh') {
          await this.refreshScreenshot();
        } else if (msg.command === 'startAutoRefresh' && msg.seconds) {
          this._autoRefreshSeconds = msg.seconds;
          this.startAutoRefresh(msg.seconds);
        } else if (msg.command === 'stopAutoRefresh') {
          this._autoRefreshSeconds = 0;
          this.stopAutoRefresh();
        } else if (msg.command === 'savePng' && msg.data) {
          await this.savePngToDisk(msg.data);
        } else if (msg.command === 'showOutput') {
          await vscode.commands.executeCommand('blenderMcp.showOutput');
        }
      },
      undefined,
      this._disposables,
    );

    // Pause polling when the panel is hidden so we don't keep waking Blender.
    this._panel.onDidChangeViewState(() => {
      if (this._panel.visible) {
        if (this._autoRefreshSeconds > 0 && !this._timer) {
          this.startAutoRefresh(this._autoRefreshSeconds);
        }
      } else if (this._timer) {
        // Stop the timer but remember the user's chosen interval so we can
        // resume on next reveal without losing their preference.
        clearInterval(this._timer);
        this._timer = undefined;
      }
    }, null, this._disposables);

    // Clean up on dispose
    this._panel.onDidDispose(() => this.dispose(), null, this._disposables);

    // Auto-refresh from configuration
    const config = vscode.workspace.getConfiguration('blenderMcp.viewportPreview');
    if (config.get<boolean>('enabled', false)) {
      const interval = config.get<number>('intervalSeconds', 5);
      this._autoRefreshSeconds = interval;
      this.startAutoRefresh(interval);
    }
  }

  private async savePngToDisk(dataUrl: string): Promise<void> {
    const m = /^data:image\/png;base64,(.+)$/.exec(dataUrl);
    if (!m) { return; }
    const target = await vscode.window.showSaveDialog({
      filters: { 'PNG image': ['png'] },
      saveLabel: 'Save viewport screenshot',
      defaultUri: vscode.Uri.file(`viewport-${Date.now()}.png`),
    });
    if (!target) { return; }
    try {
      const buf = Buffer.from(m[1], 'base64');
      await vscode.workspace.fs.writeFile(target, buf);
      void vscode.window.showInformationMessage(`Saved ${target.fsPath}`);
    } catch (err: unknown) {
      void vscode.window.showErrorMessage(
        `Failed to save PNG: ${(err as Error).message}`,
      );
    }
  }

  async refreshScreenshot(): Promise<void> {
    const { host, port, token } = resolveConnection();

    if (!token) {
      this._panel.webview.postMessage({
        command: 'error',
        message:
          'No auth token found. Start the Blender add-on (it writes ~/.blender_mcp/connection.json), ' +
          'or set BLENDER_MCP_TOKEN, or paste the token into the blenderMcp.token setting.',
      });
      return;
    }

    const id = `preview-${crypto.randomBytes(4).toString('hex')}`;
    // Phase 1: ask the add-on to write the PNG to a local cache file and
    // return its path instead of base64-encoding through the WS frame.
    // Saves ~1.3× payload size and one round of base64 encode + decode for
    // 800×600 PNGs (typical preview ~50–200 KB).
    const payload = JSON.stringify({
      id,
      op: 'render.viewport_screenshot',
      args: { w: 800, h: 600, transport: 'file' },
      auth: token,
    });

    try {
      const response = await wsRequest(host, port, payload);

      if (!response.ok || !response.result) {
        const errMsg = response.error?.message ?? 'Unknown error from Blender';
        this._panel.webview.postMessage({ command: 'error', message: errMsg });
        return;
      }

      const result = response.result as Record<string, unknown>;
      let b64: string | undefined;

      const imagePath = result['image_path'] as string | undefined;
      if (imagePath) {
        // transport="file" — read the PNG straight off disk. Local-only, the
        // add-on writes to %LOCALAPPDATA%\BlenderMCP\renders\.
        try {
          const buf = await fs.readFile(imagePath);
          b64 = buf.toString('base64');
        } catch (err: unknown) {
          this._panel.webview.postMessage({
            command: 'error',
            message:
              `Could not read screenshot at ${imagePath}: ${(err as Error).message}`,
          });
          return;
        }
      } else {
        // transport="base64" fallback — older add-on, or stdio MCP client mode.
        b64 = result['image_base64'] as string | undefined;
      }

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
      cursor: zoom-in;
    }
    #viewport.zoomed {
      max-width: none;
      cursor: zoom-out;
    }
    #status {
      margin-top: 4px;
      opacity: 0.7;
      font-size: 0.9em;
    }
    #errorPanel {
      display: none;
      margin-top: 8px;
      padding: 10px;
      border: 1px solid var(--vscode-inputValidation-errorBorder, #c33);
      background: var(--vscode-inputValidation-errorBackground, rgba(204,51,51,0.1));
      border-radius: 4px;
    }
    #errorPanel.visible { display: block; }
    #errorPanel .err-msg { color: var(--vscode-errorForeground); margin: 0 0 8px; }
    #errorPanel .err-actions { display: flex; gap: 8px; }
    .error { color: var(--vscode-errorForeground); }
  </style>
</head>
<body>
  <div class="toolbar">
    <button id="btnRefresh">&#8635; Refresh</button>
    <button id="btnSave" disabled>&#128190; Save PNG</button>
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
  <div id="errorPanel">
    <p class="err-msg" id="errMsg"></p>
    <div class="err-actions">
      <button id="btnRetry">Retry</button>
      <button id="btnShowOutput">Show Output</button>
    </div>
  </div>

  <script nonce="${nonce}">
    const vscode = acquireVsCodeApi();
    const img = document.getElementById('viewport');
    const status = document.getElementById('status');
    const btnRefresh = document.getElementById('btnRefresh');
    const btnSave = document.getElementById('btnSave');
    const btnRetry = document.getElementById('btnRetry');
    const btnShowOutput = document.getElementById('btnShowOutput');
    const chkAuto = document.getElementById('chkAuto');
    const numInterval = document.getElementById('numInterval');
    const errorPanel = document.getElementById('errorPanel');
    const errMsg = document.getElementById('errMsg');

    let lastImageData = null;

    function clearError() {
      errorPanel.classList.remove('visible');
      errMsg.textContent = '';
    }
    function showError(text) {
      errMsg.textContent = text;
      errorPanel.classList.add('visible');
      status.textContent = '';
    }

    btnRefresh.addEventListener('click', () => {
      vscode.postMessage({ command: 'refresh' });
      status.textContent = 'Requesting…';
      clearError();
    });

    btnRetry.addEventListener('click', () => {
      vscode.postMessage({ command: 'refresh' });
      status.textContent = 'Retrying…';
      clearError();
    });

    btnShowOutput.addEventListener('click', () => {
      vscode.postMessage({ command: 'showOutput' });
    });

    btnSave.addEventListener('click', () => {
      if (lastImageData) {
        vscode.postMessage({ command: 'savePng', data: lastImageData });
      }
    });

    img.addEventListener('click', () => {
      img.classList.toggle('zoomed');
    });

    chkAuto.addEventListener('change', () => {
      if (chkAuto.checked) {
        const sec = parseInt(numInterval.value, 10) || 5;
        vscode.postMessage({ command: 'startAutoRefresh', seconds: sec });
        status.textContent = 'Auto-refresh started (' + sec + 's)';
        clearError();
      } else {
        vscode.postMessage({ command: 'stopAutoRefresh' });
        status.textContent = 'Auto-refresh stopped.';
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
        lastImageData = msg.data;
        btnSave.disabled = false;
        status.textContent = 'Last refresh: ' + new Date().toLocaleTimeString();
        clearError();
      } else if (msg.command === 'error') {
        showError(msg.message);
      }
    });
  </script>
</body>
</html>`;
}
