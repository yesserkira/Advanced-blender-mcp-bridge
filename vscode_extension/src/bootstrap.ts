// Bootstrap helpers: install the bundled Blender add-on into Blender's user
// scripts directory, and auto-detect a Python interpreter that has the
// `blender_mcp` package installed.
//
// Both are exposed as commands wired in extension.ts; both also feed the
// setup walkthrough.

import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import * as cp from 'child_process';
import AdmZip from 'adm-zip';

// ---------------------------------------------------------------------------
// Add-on installer
// ---------------------------------------------------------------------------

export interface AddonVersion {
  major: number;
  minor: number;
  patch: number;
}

export function parseVersionString(s: string): AddonVersion | undefined {
  const m = /^(\d+)\.(\d+)\.(\d+)/.exec(s.trim());
  if (!m) { return undefined; }
  return { major: +m[1], minor: +m[2], patch: +m[3] };
}

export function compareVersions(a: AddonVersion, b: AddonVersion): number {
  return (a.major - b.major) || (a.minor - b.minor) || (a.patch - b.patch);
}

function vstr(v: AddonVersion): string { return `${v.major}.${v.minor}.${v.patch}`; }

/** Read bundled addon version from resources/blender_mcp_addon.version.txt. */
function bundledAddonVersion(extensionPath: string): AddonVersion | undefined {
  const f = path.join(extensionPath, 'resources', 'blender_mcp_addon.version.txt');
  try {
    return parseVersionString(fs.readFileSync(f, 'utf-8'));
  } catch {
    return undefined;
  }
}

function bundledAddonZipPath(extensionPath: string): string {
  return path.join(extensionPath, 'resources', 'blender_mcp_addon.zip');
}

/**
 * Parse `bl_info["version"]` tuple from a Blender add-on `__init__.py`.
 * Returns undefined if the file or tuple can't be parsed.
 */
export function readInstalledAddonVersion(addonInitPath: string): AddonVersion | undefined {
  let raw: string;
  try {
    raw = fs.readFileSync(addonInitPath, 'utf-8');
  } catch {
    return undefined;
  }
  // Match: "version": (2, 6, 0)  — accepts whitespace and double/single quotes.
  const m = /["']version["']\s*:\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)/.exec(raw);
  if (!m) { return undefined; }
  return { major: +m[1], minor: +m[2], patch: +m[3] };
}

/**
 * Per-OS Blender user-config root. Inside this we expect one or more
 * version-numbered directories ("4.2", "4.3", ...) each containing
 * `scripts/addons/`.
 */
function blenderUserConfigRoot(): string | undefined {
  if (process.platform === 'win32') {
    const appdata = process.env['APPDATA'];
    return appdata ? path.join(appdata, 'Blender Foundation', 'Blender') : undefined;
  }
  if (process.platform === 'darwin') {
    return path.join(os.homedir(), 'Library', 'Application Support', 'Blender');
  }
  return path.join(os.homedir(), '.config', 'blender');
}

interface BlenderInstall {
  version: string;          // "4.2"
  scriptsDir: string;       // <root>/4.2/scripts
  addonsDir: string;        // <root>/4.2/scripts/addons
}

/** Discover all installed Blender versions on this machine. */
function discoverBlenderInstalls(): BlenderInstall[] {
  const root = blenderUserConfigRoot();
  if (!root || !fs.existsSync(root)) { return []; }
  const out: BlenderInstall[] = [];
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    if (!entry.isDirectory()) { continue; }
    if (!/^\d+\.\d+$/.test(entry.name)) { continue; }
    const scriptsDir = path.join(root, entry.name, 'scripts');
    out.push({
      version: entry.name,
      scriptsDir,
      addonsDir: path.join(scriptsDir, 'addons'),
    });
  }
  // Newest version first.
  out.sort((a, b) => -a.version.localeCompare(b.version, undefined, { numeric: true }));
  return out;
}

export async function installAddonIntoBlender(
  context: vscode.ExtensionContext,
  channel: vscode.OutputChannel,
): Promise<void> {
  const bundledVer = bundledAddonVersion(context.extensionPath);
  const zipPath = bundledAddonZipPath(context.extensionPath);
  if (!bundledVer || !fs.existsSync(zipPath)) {
    void vscode.window.showErrorMessage(
      'Blender MCP: bundled add-on not found in this extension. ' +
      'Reinstall the .vsix from the latest release.',
    );
    return;
  }

  const installs = discoverBlenderInstalls();
  if (installs.length === 0) {
    void vscode.window.showErrorMessage(
      'Blender MCP: no Blender installation detected. Install Blender 4.2+ ' +
      'and run it once so it creates its user config directory.',
    );
    return;
  }

  let target: BlenderInstall;
  if (installs.length === 1) {
    target = installs[0];
  } else {
    const pick = await vscode.window.showQuickPick(
      installs.map((i) => ({ label: `Blender ${i.version}`, description: i.addonsDir, install: i })),
      { title: 'Install Blender MCP add-on \u2014 pick a Blender version', ignoreFocusOut: true },
    );
    if (!pick) { return; }
    target = pick.install;
  }

  fs.mkdirSync(target.addonsDir, { recursive: true });

  // Compare against existing installation.
  const installedInit = path.join(target.addonsDir, 'blender_mcp', '__init__.py');
  const installedVer = readInstalledAddonVersion(installedInit);
  if (installedVer) {
    const cmp = compareVersions(installedVer, bundledVer);
    if (cmp > 0) {
      void vscode.window.showErrorMessage(
        `Blender MCP: refusing to downgrade. Installed v${vstr(installedVer)} ` +
        `is newer than bundled v${vstr(bundledVer)}.`,
      );
      return;
    }
    const verb = cmp === 0 ? 'Reinstall' : 'Upgrade';
    const detail = cmp === 0
      ? `Reinstall v${vstr(bundledVer)} on top of itself?`
      : `Upgrade from v${vstr(installedVer)} to v${vstr(bundledVer)}?`;
    const confirm = await vscode.window.showInformationMessage(
      `Blender MCP add-on already installed for Blender ${target.version}.`,
      { modal: true, detail },
      verb,
    );
    if (confirm !== verb) { return; }
  }

  try {
    const zip = new AdmZip(zipPath);
    zip.extractAllTo(target.addonsDir, /* overwrite */ true);
    channel.appendLine(
      `Installed Blender MCP add-on v${vstr(bundledVer)} \u2192 ${target.addonsDir}`,
    );
  } catch (err: unknown) {
    void vscode.window.showErrorMessage(
      `Blender MCP: failed to extract add-on zip: ${(err as Error).message}`,
    );
    return;
  }

  await vscode.window.showInformationMessage(
    `Blender MCP add-on v${vstr(bundledVer)} installed for Blender ${target.version}.`,
    {
      detail:
        'Open Blender \u2192 Edit \u2192 Preferences \u2192 Add-ons, search for ' +
        '"Blender MCP Bridge", and enable it. The add-on will start a local ' +
        'WebSocket server and write ~/.blender_mcp/connection.json.'
    },
    'OK',
  );

  await context.globalState.update('blenderMcp.addonInstalled', true);
}

// ---------------------------------------------------------------------------
// Python interpreter detection
// ---------------------------------------------------------------------------

interface PythonCandidate {
  /** Absolute path to the python executable. */
  path: string;
  /** Where we found it (used for the quick-pick description). */
  origin: string;
  /** True if `import blender_mcp` succeeds on this interpreter. */
  hasBlenderMcp: boolean;
}

function venvPythonExe(venvDir: string): string {
  return process.platform === 'win32'
    ? path.join(venvDir, 'Scripts', 'python.exe')
    : path.join(venvDir, 'bin', 'python');
}

function checkBlenderMcpImport(pythonPath: string): boolean {
  try {
    const r = cp.spawnSync(pythonPath, ['-c', 'import blender_mcp'], {
      timeout: 5000,
      windowsHide: true,
    });
    return r.status === 0;
  } catch {
    return false;
  }
}

export function detectPythonInterpreter(): PythonCandidate[] {
  const seen = new Set<string>();
  const out: PythonCandidate[] = [];
  const consider = (p: string, origin: string): void => {
    const norm = path.normalize(p);
    if (seen.has(norm) || !fs.existsSync(norm)) { return; }
    seen.add(norm);
    out.push({ path: norm, origin, hasBlenderMcp: checkBlenderMcpImport(norm) });
  };

  for (const folder of vscode.workspace.workspaceFolders ?? []) {
    consider(venvPythonExe(path.join(folder.uri.fsPath, 'mcp_server', '.venv')),
      'workspace mcp_server/.venv');
    consider(venvPythonExe(path.join(folder.uri.fsPath, '.venv')),
      'workspace .venv');
  }

  // System python(s) on PATH \u2014 only count those that actually have blender_mcp.
  const sysCmd = process.platform === 'win32' ? 'where' : 'which';
  for (const exe of ['python', 'python3', 'py']) {
    try {
      const r = cp.spawnSync(sysCmd, [exe], { encoding: 'utf-8', windowsHide: true });
      if (r.status !== 0) { continue; }
      for (const line of r.stdout.split(/\r?\n/)) {
        const trimmed = line.trim();
        if (trimmed) { consider(trimmed, `system ${exe}`); }
      }
    } catch {
      /* ignore */
    }
  }

  // Sort: workspace venvs with blender_mcp first, then anything with blender_mcp,
  // then the rest.
  out.sort((a, b) => {
    const score = (c: PythonCandidate) =>
      (c.hasBlenderMcp ? 2 : 0) + (c.origin.startsWith('workspace') ? 1 : 0);
    return score(b) - score(a);
  });
  return out;
}

export async function detectAndSetPythonPath(
  channel: vscode.OutputChannel,
): Promise<void> {
  const candidates = detectPythonInterpreter();
  if (candidates.length === 0) {
    void vscode.window.showWarningMessage(
      'Blender MCP: no Python interpreter found. Install the mcp_server ' +
      'package into a venv and set blenderMcp.pythonPath manually.',
    );
    return;
  }

  let pick: PythonCandidate | undefined;
  if (candidates.length === 1) {
    pick = candidates[0];
  } else {
    const choice = await vscode.window.showQuickPick(
      candidates.map((c) => ({
        label: c.path,
        description: c.origin,
        detail: c.hasBlenderMcp ? '\u2713 has blender_mcp installed' : '\u2717 blender_mcp not importable',
        candidate: c,
      })),
      {
        title: 'Pick a Python interpreter for the MCP server',
        ignoreFocusOut: true,
      },
    );
    pick = choice?.candidate;
  }
  if (!pick) { return; }

  if (!pick.hasBlenderMcp) {
    const proceed = await vscode.window.showWarningMessage(
      `Selected interpreter does not have blender_mcp installed:\n${pick.path}`,
      {
        modal: true,
        detail: 'You\'ll need to run `pip install -e .` inside mcp_server/ on this venv before the MCP server can start.'
      },
      'Set anyway',
    );
    if (proceed !== 'Set anyway') { return; }
  }

  await vscode.workspace.getConfiguration('blenderMcp').update(
    'pythonPath', pick.path, vscode.ConfigurationTarget.Global,
  );
  channel.appendLine(`Set blenderMcp.pythonPath = ${pick.path}`);
  void vscode.window.showInformationMessage(
    `Blender MCP: pythonPath set to ${pick.path}`,
  );
}
