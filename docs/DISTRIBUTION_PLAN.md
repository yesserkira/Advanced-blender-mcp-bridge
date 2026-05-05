# Distribution & Onboarding Plan — Blender MCP Bridge

> **Goal:** A user installs ONE file (`.vsix`) and gets a working Blender ⇄ VS Code AI chat
> bridge in under 2 minutes. Zero config files. Zero env vars. Zero pip installs. Works in
> any VS Code window — no folder open required.
>
> **Status:** Plan ratified 2026-05-05. Implementation **not started**. Pre-work pending.

---

## Table of Contents
1. [End-State Vision](#1-end-state-vision)
2. [The Three Components](#2-the-three-components)
3. [End-User Journey (Target)](#3-end-user-journey-target)
4. [Sprint Breakdown](#4-sprint-breakdown)
5. [Per-Sprint Detail](#5-per-sprint-detail)
6. [Failure-Mode Coverage](#6-failure-mode-coverage)
7. [Acceptance Gates](#7-acceptance-gates)
8. [Open Questions / Decisions Needed](#8-open-questions--decisions-needed)
9. [Pre-Work Checklist](#9-pre-work-checklist-before-s1)

---

## 1. End-State Vision

After all sprints land, the user experience is:

| Step | Action | Time |
|------|--------|------|
| 1 | Drag `blender-mcp-bridge-2.0.0.vsix` onto VS Code | 15 s |
| 2 | Welcome page → click **"Install Blender add-on for me"** | 10 s |
| 3 | Click **"Generate token"** → token copied to clipboard automatically | 2 s |
| 4 | Switch to Blender → paste token → click **Start Server** | 5 s |
| 5 | Click **"Test connection"** in Welcome page → ✅ green | 1 s |
| 6 | Open Copilot Chat → Agent mode → `blender` tools already listed | 0 s |

**Total: ~35 seconds.** No workspace required. No `.vscode/mcp.json`. No env vars. No pip install.

---

## 2. The Three Components

| # | Artifact | Owner | Distribution |
|---|----------|-------|--------------|
| **A** | Blender add-on (Python package) | `blender_addon/` | **Bundled inside the VSIX** as `resources/blender_addon.zip` |
| **B** | MCP server (Python stdio↔WS bridge) | `mcp_server/blender_mcp/` | **Bundled inside the VSIX** under `python_runtime/` (embedded Python + deps) |
| **C** | VS Code extension (TS) | `vscode_extension/` | The VSIX itself |

**Key insight:** B and A are bundled inside C. No separate downloads.

---

## 3. End-User Journey (Target)

### Welcome page on first install

```
┌──────────────────────────────────────────────────────────┐
│  🎨  Welcome to Blender MCP Bridge                       │
│                                                          │
│  Let your AI chat agents control Blender.                │
│                                                          │
│  Three steps to get started:                             │
│                                                          │
│  ⬜  1. Install the Blender add-on    [Install for me]   │
│  ⬜  2. Generate a connection token   [Generate]         │
│  ⬜  3. Test the connection           [Test]             │
│                                                          │
│  Need help? [Open documentation]                         │
└──────────────────────────────────────────────────────────┘
```

### Status bar (always visible)

```
● Blender MCP   12ms
```

### Sidebar (activity bar icon)

```
▼ CONNECTION
  ✔ Status: Connected (12 ms)
  🌐 URL: ws://127.0.0.1:9876
  🔑 Token: abc1…XYZ9   [🔄 Regenerate]   [📋 Copy]

▼ QUICK ACTIONS
  📷  Take Viewport Screenshot
  🔄  Refresh Audit Log
  🔌  Reconnect
  🚀  Launch Blender
  📋  Show Output Channel
  ❓  Open Documentation

▼ RECENT ACTIVITY (15)
  ✓ ping                 12 ms   2s ago
  ✓ create_objects       87 ms   1m ago
  ...
```

### Copilot Chat (Agent mode)

The `blender` tool group appears automatically — registered globally via
`vscode.lm.registerMcpServerDefinitionProvider`. Works in **every** workspace and
even with no folder open.

---

## 4. Sprint Breakdown

| Sprint | Phase | Effort | Outcome | Cumulative state |
|--------|-------|--------|---------|------------------|
| **S1** | Programmatic MCP registration | 2 hrs | Removes `.vscode/mcp.json` requirement; uses settings + SecretStorage for path/token | Dev no longer needs to open the folder |
| **S2** | Bundle Python runtime in VSIX | half day | VSIX self-contains the MCP server | Pure VSIX install works (Python no longer required on PATH) |
| **S3** | SecretStorage + token UX | half day | Token never lives in env vars or files; commands to regen/copy | Single source of truth for secrets |
| **S4** | First-run wizard + bundled add-on installer | half day | Dragging the VSIX is literally enough | Onboarding is one-click |
| **S5** | Welcome view + auto-recovery + CI | few hrs | Polish + GitHub Actions release pipeline | Shippable to marketplace |

**Total estimate: 2–3 working days.**

---

## 5. Per-Sprint Detail

### S1 — Programmatic MCP Server Registration

**Why first:** Highest leverage smallest change. Unblocks every later sprint by establishing
the new wiring. Removes the workspace-folder requirement immediately.

**Files to add:**
- `vscode_extension/src/mcpProvider.ts` — implements
  `vscode.McpServerDefinitionProvider`. Returns a `McpStdioServerDefinition` that
  spawns Python with `-m blender_mcp.server` and injects `BLENDER_MCP_TOKEN` env from
  SecretStorage (or settings during S1, before S3 introduces SecretStorage).

**Files to edit:**
- `vscode_extension/src/extension.ts` — register the provider in `activate()`.
- `vscode_extension/package.json` — add
  `contributes.mcpServerDefinitionProviders: [{ id: "blenderMcp.provider", label: "Blender MCP" }]`
  and new settings `blenderMcp.pythonPath` (default empty → use bundled later),
  `blenderMcp.serverModule` (default `blender_mcp.server`).

**Settings introduced (transitional):**
- `blenderMcp.pythonPath` — absolute path to python.exe (until S2 bundles one)
- `blenderMcp.serverModule` — module name; default `blender_mcp.server`
- `blenderMcp.token` — fallback if SecretStorage empty (deprecated in S3)

**Acceptance:**
- Open a fresh VS Code window with NO folder → status bar shows ● Connected once
  Python path is set in user settings.
- `Ctrl+Shift+P` → `MCP: List Servers` shows `blender (from Blender MCP Bridge)`.
- Tools appear in Copilot Chat Agent mode without any `.vscode/mcp.json`.
- Old workspace-scoped `.vscode/mcp.json` keeps working as a fallback.

**Out of scope for S1:** bundled Python, SecretStorage, wizards.

---

### S2 — Bundle Python Runtime Inside the VSIX

**Why:** Eliminates "user must have Python installed" friction. After S2 the VSIX is truly
self-contained.

**Files to add:**
- `vscode_extension/scripts/build_runtime.ps1` — fetches Python 3.12 embeddable for
  Windows, runs `pip install --target=python_runtime/Lib/site-packages mcp websockets keyring pip-licenses`,
  copies `mcp_server/blender_mcp/` next to it, then runs
  `pip-licenses --format=markdown --with-license-file --output-file=../THIRD_PARTY_NOTICES.md`.
- `vscode_extension/THIRD_PARTY_NOTICES.md` — generated, checked into VSIX (not git).
- `vscode_extension/.vscodeignore` — keep `python_runtime/` and `THIRD_PARTY_NOTICES.md` IN the VSIX.
- Build matrix later (S5): variants for win-x64, linux-x64. (macOS deferred — see §8.)

**Files to edit:**
- `vscode_extension/src/mcpProvider.ts` — if `blenderMcp.pythonPath` is empty, default to
  `path.join(context.extensionPath, 'python_runtime', process.platform === 'win32' ? 'python.exe' : 'bin/python3')`.
- `vscode_extension/package.json` — bump major version, update
  `scripts.package` to first call `npm run build:runtime`.

**Acceptance:**
- Fresh machine with NO Python on PATH installs the VSIX → status bar ● Connected.
- VSIX size < 30 MB (Windows variant).
- Smoke test: spawn `python_runtime/python.exe -m blender_mcp.server` returns clean stdio.

**Risk mitigation:**
- Fallback: if bundled Python fails to spawn, surface a one-click button that opens
  `blenderMcp.pythonPath` setting prefilled.

---

### S3 — SecretStorage + Token UX

**Why:** Eliminates token-in-env-var and token-in-settings. Proper VS Code secret handling.

**Files to add:**
- `vscode_extension/src/tokenStore.ts` — thin wrapper around
  `context.secrets.get/store/delete('blender-mcp-token')` plus token generation
  (`crypto.randomBytes(32).toString('base64url')`).

**Files to edit:**
- `vscode_extension/src/extension.ts` — register commands:
  - `blenderMcp.generateToken` — generates, stores, copies to clipboard, shows once
  - `blenderMcp.copyToken` — copies stored token to clipboard
  - `blenderMcp.regenerateToken` — confirm dialog → regen → copy
  - `blenderMcp.clearToken` — confirm → delete from secrets
- `vscode_extension/src/mcpProvider.ts` — read token from `tokenStore` instead of settings.
- `vscode_extension/src/statusUi.ts` — tree view "Token" item shows masked value with
  copy button; if missing, a big red "Generate Token" actionable item.
- `vscode_extension/package.json` — register the new commands; deprecate
  `blenderMcp.token` setting (kept for migration only).

**One-time migration:** on activation, if `blenderMcp.token` setting is non-empty AND
SecretStorage is empty, copy the value into SecretStorage and toast the user once
(*"Token migrated to secure storage. You can now clear the setting."*).

**Acceptance:**
- Token never appears in `settings.json`, `.env`, or workspace files.
- `Ctrl+Shift+P` → `Blender MCP: Show Token` requires user gesture.
- Tree view shows masked token (`abc1…XYZ9`).
- Reconnect succeeds after `Regenerate Token`.

---

### S4 — First-Run Wizard + Bundled Blender Add-on Installer

**Why:** Removes the only remaining manual steps (install add-on, paste token in Blender).

**Files to add:**
- `vscode_extension/resources/blender_addon.zip` — built by
  `scripts/build_addon_zip.ps1` from `blender_addon/` (excludes `__pycache__`,
  `vendor/.../tests`).
- `vscode_extension/src/wizard.ts` — webview-based welcome page with the 3-step UI.
- `vscode_extension/src/blenderInstaller.ts`:
  - `detectBlenderInstalls()` — scans `%APPDATA%\Blender Foundation\Blender\*\scripts\addons\`
    and `Program Files\Blender Foundation\Blender *`.
  - `installAddon(blenderVersion)` — extracts bundled zip into addons dir.
  - `launchBlender(path)` — `child_process.spawn` with detached + unref.

**Files to edit:**
- `vscode_extension/src/extension.ts` — on first activation
  (`globalState.get('firstRun') !== false`), open the wizard. Add command
  `blenderMcp.showWelcome`.
- `vscode_extension/package.json` — register `blenderMcp.showWelcome`,
  `blenderMcp.installBlenderAddon`, `blenderMcp.launchBlender`.

**Wizard flow (webview):**
1. Step 1: detected Blender installs listed; one-click install or browse.
2. Step 2: generate token (calls `blenderMcp.generateToken`); shows the token with
   copy button + "next" disabled until user confirms paste.
3. Step 3: ping test; on success, show celebration + link to "Try in Copilot Chat".

**Acceptance:**
- Fresh user with Blender already installed: 3 clicks from VSIX install to working ping.
- Detection finds Blender 3.6, 4.0, 4.1, 4.2, 4.3, 4.5 in standard locations.
- Add-on installation respects `bpy.app.binary_path`-style resolution for
  non-standard installs.

---

### S5 — Polish + CI/CD

**Why:** Makes it shippable.

**Files to add:**
- `vscode_extension/src/welcomeView.ts` — VS Code WelcomeView contribution shown in
  the activity bar when not connected.
- `.github/workflows/release.yml` — on tag `v*`:
  1. matrix-build runtimes for win-x64 and linux-x64 (macOS deferred)
  2. produces 2 platform-specific VSIX files (`blender-mcp-bridge-2.0.0-win32-x64.vsix`, `...-linux-x64.vsix`)
  3. attaches both to GitHub Release
  4. Marketplace publish step is *not* included until a publisher ID is registered (see §8).

**Files to edit:**
- `vscode_extension/package.json` — `extensionPack`/platform metadata.
- `vscode_extension/src/extension.ts` — auto-recovery: if `ping` fails 3× in 30s, toast
  with **[Launch Blender] [Open Settings]** buttons.

**Acceptance:**
- `git tag v2.0.0 && git push --tags` produces 2 VSIX assets on the release (win-x64, linux-x64).
- Users download from GitHub Releases and drag-install.
- (Marketplace listing + auto-update deferred until publisher ID registered — see §8.)

---

## 6. Failure-Mode Coverage

| Problem | Detection | Recovery UX |
|---------|-----------|-------------|
| Blender not running | `ping` timeout | Status bar red. Toast: *"Blender MCP add-on not reachable. [Launch Blender] [Help]"* |
| Wrong token | Auth error frame | Status bar red. Toast: *"Authentication failed. [Regenerate token]"* |
| Bundled Python missing/corrupt | spawn `ENOENT` | Toast: *"Repair extension"* → reinstall VSIX or fall back to settings path |
| Port 9876 in use | WS ECONNREFUSED but port shows LISTEN by foreign PID | Toast: *"Port in use by another process. Change port?"* |
| User pastes wrong token in Blender | server returns auth fail | Audit log shows AUTH_FAIL entries; tree view flags red |
| Embedded Python ABI mismatch (future Python upgrade) | spawn fails | Bundled-Python sanity check on activation, with repair link |
| Multiple Blender installs | detection returns >1 | Wizard quick-pick; remember choice in `globalState` |

---

## 7. Acceptance Gates

End-to-end check after each sprint. Each gate must pass before next sprint starts.

| Gate | Trigger | Pass criteria |
|------|---------|---------------|
| **G1** (after S1) | Install dev VSIX in fresh VS Code window with NO folder open | Status bar ● Connected within 5 s; `MCP: List Servers` shows `blender`; Copilot Agent mode lists `blender` tool group |
| **G2** (after S2) | Same as G1 on a fresh machine with NO Python in PATH | Same green outcome; `which python` returns nothing |
| **G3** (after S3) | Wipe `settings.json` of all `blenderMcp.*` keys; uninstall + reinstall VSIX | Wizard must offer to re-create token; no token strings appear anywhere on disk except SecretStorage |
| **G4** (after S4) | Fresh user with Blender installed but add-on NOT installed | Welcome page → 3 clicks → working ping |
| **G5** (after S5) | Push `v2.0.0` tag | 2 platform VSIX files (win-x64, linux-x64) appear on the GitHub Release within 10 min |

---

## 8. Open Questions / Decisions Needed

> Trimmed to essentials. Items previously listed (publisher ID, code signing, telemetry,
> macOS notarization, Python upgrade cadence) have been deferred or settled by policy:
>
> - **Marketplace publisher ID** — deferred. Distribute via GitHub Releases for v2.0.
> - **Code signing** — deferred. Revisit only if SmartScreen warnings become a support issue.
> - **Telemetry** — settled: **never. Zero telemetry, ever.**
> - **macOS notarization** — deferred. Ship Windows + Linux bundles first; macOS users
>   point `blenderMcp.pythonPath` at system Python until we get an Apple Developer ID.
> - **Python upgrade cadence** — non-decision. Stay on 3.12 until 3.13 is stable; then rebuild.
>
> Remaining real items:

1. **Bundled-dependency license notices** — *not a decision, a build task.* MIT / PSF /
   BSD licenses on `mcp`, `websockets`, `keyring`, and embedded CPython require we ship
   their notices. Auto-generate `THIRD_PARTY_NOTICES.md` in the S2 build script via
   `pip-licenses --format=markdown`. **No human decision needed.**

*(Add new questions here as they arise.)*

---

## 9. Pre-Work Checklist (Before S1)

> User has flagged "there is some stuff we need to work on for our plugin before we move on."
> List those items here as they come up. Do not start S1 until empty.

- [ ] _(user to fill)_
- [ ] _(user to fill)_
- [ ] _(user to fill)_

**Once this list is empty, say "go S1" and implementation begins.**

---

## Appendix A — File Map at End-State

```
vscode_extension/
├── package.json                         (updated: providers, commands, settings)
├── README.md
├── CHANGELOG.md
├── THIRD_PARTY_NOTICES.md               (auto-generated in S2)
├── media/
│   └── blender.svg
├── resources/
│   └── blender_addon.zip                (new in S4)
├── python_runtime/                      (new in S2; gitignored)
│   ├── python.exe
│   └── Lib/site-packages/{blender_mcp, mcp, websockets, keyring}/
├── scripts/
│   ├── build_runtime.ps1                (new in S2)
│   └── build_addon_zip.ps1              (new in S4)
├── src/
│   ├── extension.ts                     (S1, S3, S4 edits)
│   ├── mcpProvider.ts                   (NEW S1)
│   ├── tokenStore.ts                    (NEW S3)
│   ├── wizard.ts                        (NEW S4)
│   ├── blenderInstaller.ts              (NEW S4)
│   ├── welcomeView.ts                   (NEW S5)
│   ├── statusUi.ts                      (S3 edits)
│   ├── viewportPreview.ts
│   ├── approval.ts
│   └── wsClient.ts
└── out/  (compiled)

.github/workflows/
└── release.yml                          (NEW S5)
```

---

## Appendix B — Settings Reference (End-State)

| Key | Type | Default | Notes |
|-----|------|---------|-------|
| `blenderMcp.host` | string | `127.0.0.1` | WS host the server connects to |
| `blenderMcp.port` | number | `9876` | WS port |
| `blenderMcp.pythonPath` | string | `""` (uses bundled) | Override for advanced users |
| `blenderMcp.serverModule` | string | `blender_mcp.server` | Rarely changed |
| `blenderMcp.viewportPreview.enabled` | boolean | `false` | |
| `blenderMcp.viewportPreview.intervalSeconds` | number | `5` | |
| `blenderMcp.statusBar.pollSeconds` | number | `5` | |
| `blenderMcp.approvalServer.port` | number | `0` | |
| ~~`blenderMcp.token`~~ | string | _deprecated_ | Migrated to SecretStorage in S3 |

---

*End of plan. Last updated 2026-05-05.*
