# Remediation Plan — Closing the Audit Gaps

> **Source:** Codebase audit dated 2026-05-05. See [DISTRIBUTION_PLAN.md](DISTRIBUTION_PLAN.md) for the
> downstream packaging/distribution work that depends on this plan completing first.
>
> **Goal:** Close every functional gap, stale doc, and security hole identified in the audit,
> so the v2.x release is *honestly* production-ready before we package and distribute it.
>
> **Status:** Plan ratified 2026-05-05. Implementation **not started**.

---

## Table of Contents
1. [Audit Findings — Recap](#1-audit-findings--recap)
2. [Severity & Sequencing](#2-severity--sequencing)
3. [Workstreams](#3-workstreams)
4. [Per-Workstream Detail](#4-per-workstream-detail)
5. [Acceptance Gates](#5-acceptance-gates)
6. [Documentation Reconciliation](#6-documentation-reconciliation)
7. [Test Strategy](#7-test-strategy)
8. [Open Items](#8-open-items)
9. [Sequencing With Distribution Plan](#9-sequencing-with-distribution-plan)

---

## 1. Audit Findings — Recap

The audit identified **4 real blockers**, **3 partial features**, and **3 documentation gaps**.

### Blockers (functional bugs)

| # | Issue | Impact |
|---|-------|--------|
| **B1** | **Approval flow is cosmetic** — Approve/Reject webview renders, but the result never reaches the MCP server to unblock the waiting AI call. | `execute_python` and `delete_object` cannot actually be approved by the user. The "confirmation gate" is a soft block only. |
| **B2** | **No DoS protection** — `rate_limit` defined in policy schema but never enforced. | A runaway AI session can fire 1000 ops/sec and freeze Blender. |
| **B3** | **No persistent checkpoints** — `transaction` only uses in-memory diffs; `.blendermcp/snapshots/` from the plan was never built. | Blender crash mid-transaction = work lost; no way to roll back across sessions. |
| **B4** | **No programmatic MCP registration** — Extension does not register itself as an MCP server provider; users must hand-edit `.vscode/mcp.json`. | Blocks the entire S1–S5 distribution plan; users get a status-bar UI with no actual MCP tools. |

### Partial Features

| # | Issue | Impact |
|---|-------|--------|
| **P1** | **Polygon cap not enforced** — `max_polys` defined in policy, never checked. | Plan claims protection that doesn't exist. |
| **P2** | **Progress streaming defined but not wired** — `progress_callback` param exists in render code; MCP tools never emit progress events. | Long renders look frozen to the AI; no UX feedback. |
| **P3** | **CSRF on approval HTTP server** — Loopback listener accepts POSTs with no token validation. | Local malware on the box can spoof approvals. (Low-medium risk; loopback only.) |

### Documentation Gaps

| # | Issue |
|---|-------|
| **D1** | `docs/PLAN.md` claims tasks T-411, T-503, §14.6, §14.7, §14.8 are "done" — they aren't. |
| **D2** | `docs/PLAN.md` mentions `build_geonodes` and `set_material_node_graph` as separate tools; they're unified under `build_nodes` (cleaner, but plan stale). |
| **D3** | README implies one-command install; reality requires Blender add-on install + Python venv + manual MCP config. |

---

## 2. Severity & Sequencing

Rule: **functional correctness first, security hardening second, polish third.**

| Order | Workstream | Why this order |
|-------|------------|----------------|
| **W1** | Fix B1 — Approval result flow | Without this, the security model has a hole the user can SEE. Highest-priority correctness issue. |
| **W2** | Fix B4 — Programmatic MCP registration | Unblocks the entire distribution plan. Pure VS Code-side work, parallelizable with W1. |
| **W3** | Fix B2 — Rate limiting enforcement | Closes a real DoS hole. Server-side, low risk. |
| **W4** | Fix B3 — Persistent checkpoint snapshots | Larger scope. Needs file-format design (`.blend` vs JSON state). |
| **W5** | Fix P1, P2, P3 — Partial features | Smaller fixes, batched together. |
| **W6** | D1, D2, D3 — Documentation reconciliation | Last because content depends on what shipped above. |

W1 + W2 can run in parallel (different files, different layers). W3, W4 follow.

---

## 3. Workstreams

| ID | Title | Effort | Files Touched |
|----|-------|--------|---------------|
| **W1** | Approval result flow (B1) | 1 day | `mcp_server/server.py`, `mcp_server/blender_client.py`, `vscode_extension/src/approval.ts`, `blender_addon/server/main_thread.py` (optional) |
| **W2** | Programmatic MCP registration (B4) | 4 hrs | `vscode_extension/src/mcpProvider.ts` (new), `vscode_extension/src/extension.ts`, `vscode_extension/package.json` |
| **W3** | Rate limiting (B2) | 4 hrs | `mcp_server/policy.py`, `mcp_server/server.py` (decorator) |
| **W4** | Persistent checkpoints (B3) | 1 day | `blender_addon/safety/checkpoints.py` (new), `blender_addon/capabilities/composer.py` (transaction op), `mcp_server/server.py` (new tools `checkpoint_list`, `checkpoint_restore`) |
| **W5** | Partial-feature cleanup (P1, P2, P3) | half day | `blender_addon/capabilities/{mesh,composer}.py` (poly cap), `mcp_server/server.py` (progress relay), `vscode_extension/src/approval.ts` (CSRF token) |
| **W6** | Documentation reconciliation (D1–D3) | 2 hrs | `docs/PLAN.md`, `README.md`, `docs/ARCHITECTURE.md` (refresh §threading + §undo to match code) |

**Total: ~3.5 working days** before distribution work (S1–S5) can start with confidence.

---

## 4. Per-Workstream Detail

### W1 — Approval Result Flow (Fix B1)

**Goal:** When the AI calls `execute_python`, the call blocks until the user clicks Approve or Reject in the VS Code webview.

#### Current state (broken)
```
AI → MCP server (execute_python) → policy check
   → returns {"error": "CONFIRM_REQUIRED"} immediately
   → AI gets error, gives up or asks user
   ❌ Webview is shown but result is never collected
```

#### Target state
```
AI → MCP server (execute_python)
   → policy says confirm_required
   → MCP server posts to extension's approval HTTP endpoint
   → extension shows webview, user clicks Approve/Reject
   → extension responds to MCP server's request with decision
   → MCP server forwards approved call to Blender; or returns CONFIRM_DENIED
```

#### Implementation
1. **Discovery:** MCP server needs to know the extension's HTTP port. Two options:
   - **A.** Extension writes port to a known location (e.g., `%LOCALAPPDATA%\BlenderMCP\approval-port.txt`). Server reads on first need.
   - **B.** Pass port via env var `BLENDER_MCP_APPROVAL_URL` set by the extension when spawning the MCP server. **Preferred** — explicit, no race conditions, scoped to the spawned process.
2. **Server side** (`mcp_server/blender_mcp/approval.py`, new):
   - `async def request_approval(tool, args, code=None, timeout=120) -> bool`
   - POSTs to `${BLENDER_MCP_APPROVAL_URL}/request` with JSON `{request_id, tool, args, code, timeout}`
   - Long-poll waits for response or timeout
   - Returns `True` (approved), `False` (rejected), raises `TimeoutError` on no answer
3. **Server tool integration** (`mcp_server/blender_mcp/server.py`):
   - In `execute_python` and `delete_object`: if `policy.confirm_required_for(tool)` and `BLENDER_MCP_APPROVAL_URL` is set, call `await request_approval(...)`. If denied, return `{"error": "CONFIRM_DENIED", "message": "User rejected"}`. If no approval URL configured, fall back to current behavior (return CONFIRM_REQUIRED — caller handles).
4. **Extension side** (`vscode_extension/src/approval.ts`):
   - Add POST `/request` route — receives `{request_id, tool, args, code, timeout}`, opens webview, awaits user click, responds with `{approved: bool, remember?: "session"}`.
   - Implement session memory: if `remember: "session"`, cache approval for `(tool, args_sha256)` for the session.
   - Add CSRF token: extension generates per-process token, includes in `BLENDER_MCP_APPROVAL_URL` (e.g., `http://127.0.0.1:PORT?token=...`); server includes in request header; rejects mismatch. (This also solves **P3**.)

**Acceptance:** AI calls `execute_python({code: "print(1)"})` → VS Code webview pops up → user clicks Approve → call completes successfully → AI sees `{executed: true, ...}`. User clicks Reject → AI sees `{error: "CONFIRM_DENIED"}`.

---

### W2 — Programmatic MCP Registration (Fix B4)

**Goal:** Installing the VSIX is sufficient to expose `blender` tools in Copilot Chat. No `.vscode/mcp.json` needed.

#### Implementation
1. **New file `vscode_extension/src/mcpProvider.ts`:**
   - Export `BlenderMcpProvider implements vscode.McpServerDefinitionProvider<vscode.McpStdioServerDefinition>`.
   - `provideMcpServerDefinitions()` returns `[new vscode.McpStdioServerDefinition('blender', pythonPath, ['-m', 'blender_mcp.server'], envVars)]`.
   - `resolveMcpServerDefinition()` injects token from SecretStorage (or settings, until W3 of distribution-plan S3 lands) and `BLENDER_MCP_APPROVAL_URL` from the running approval server.
2. **`vscode_extension/src/extension.ts`:**
   - In `activate()`: `vscode.lm.registerMcpServerDefinitionProvider('blenderMcp.provider', new BlenderMcpProvider(context, status, approvalServer))`.
   - Watch for setting changes (`pythonPath`, `port`) and call `provider.refresh()` to invalidate.
3. **`vscode_extension/package.json`:**
   - Add `contributes.mcpServerDefinitionProviders: [{ id: "blenderMcp.provider", label: "Blender MCP" }]`.
   - Add settings:
     - `blenderMcp.pythonPath` (string, default `""` → uses bundled in S2; until then user supplies path).
     - `blenderMcp.serverModule` (string, default `blender_mcp.server`).
4. **Backwards compat:** if user already has `.vscode/mcp.json`, both will register `blender`. VS Code shows duplicate entries. **Solution:** detect duplicate via well-known label and skip ours, or document that users should delete the manual file. (Lean: prefer detection.)

**Acceptance:** Open a fresh VS Code window with NO folder open → install VSIX → set `blenderMcp.pythonPath` in user settings → Copilot Chat Agent mode lists `blender` tool group within 5 seconds.

---

### W3 — Rate Limiting (Fix B2)

**Goal:** A single MCP connection cannot exceed N mutating ops per window. Read ops are unrestricted.

#### Implementation
1. **Classify tools** as MUTATING vs READ_ONLY in `mcp_server/blender_mcp/policy.py`:
   - READ_ONLY: `ping`, `query`, `list`, `describe_api`, `get_property`, `get_audit_log`, `scene_diff`, `viewport_screenshot`, `render_region`, `bake_preview`, `list_assets`.
   - MUTATING: everything else.
2. **Token-bucket** in `policy.py`:
   - `class RateLimiter: def __init__(self, max_per_window: int, window_seconds: float = 10.0)`.
   - Method `check() -> None | float` (None = OK, float = retry-after seconds).
   - Per-process singleton (one MCP-server instance = one connection).
3. **Decorator** in `server.py`:
   - `def rate_limited(tool: str): ...` — checks if tool is MUTATING; if so, calls `RateLimiter.check()`. On rejection: returns `{"error": "RATE_LIMITED", "message": "...", "retry_after_seconds": X}`.
   - Apply to all MUTATING tools.
4. **Configurable** via `policy["rate_limit"]["mutating_ops_per_window"]` (default 50) and `policy["rate_limit"]["window_seconds"]` (default 10.0). Set to 0 to disable.

**Acceptance:** Spam `create_primitive` 100× in 5 sec via a script → first ~50 succeed, rest return `RATE_LIMITED` with retry-after; after window resets, ops succeed again. `query` calls in same window unaffected.

---

### W4 — Persistent Checkpoints (Fix B3)

**Goal:** Before any `transaction` step, snapshot the affected datablocks to disk so user can restore even if Blender crashes.

#### Approach decision: full `.blend` snapshot vs JSON snapshot

| Option | Pros | Cons |
|--------|------|------|
| **A.** Save full `.blend` (`bpy.ops.wm.save_as_mainfile(copy=True)`) before each transaction | Truly atomic, restores everything | 50+ MB per checkpoint; slow; touches the user's save state |
| **B.** Library-write only the touched datablocks (`bpy.data.libraries.write(filepath, datablocks)`) | Small files, focused | Can't restore deleted parents/relations cleanly |
| **C.** JSON state snapshot (extends current in-memory diff) | Tiny, fast | Can't restore mesh data — only properties/transforms |

**Recommendation: B (library-write).** Targeted, fast, and `bpy.data.libraries.write` is a real Blender API. Use C as a *complement* for high-frequency property tweaks.

#### Implementation
1. **`blender_addon/safety/checkpoints.py`** (new):
   - `class Checkpoint: id, ts, label, file_path, datablock_refs`.
   - `def create(label: str, datablocks: list[bpy.types.ID]) -> Checkpoint` — writes to `%LOCALAPPDATA%\BlenderMCP\checkpoints\<scene-name>\<ts>-<label>.blend`.
   - `def list() -> list[Checkpoint]` — scan dir, parse filenames.
   - `def restore(checkpoint_id: str)` — link the datablocks back from the `.blend` file, replacing current.
   - `def prune(keep_last_n: int = 20)` — auto-trim old checkpoints.
2. **`blender_addon/capabilities/composer.py`:**
   - In `transaction()`: before executing steps, infer affected objects from the steps; call `Checkpoint.create("transaction-pre", affected_objects)`. Store checkpoint id in result.
3. **`mcp_server/blender_mcp/server.py`:**
   - New tool `list_checkpoints() -> list[dict]` (calls `audit.read`-style with checkpoint capability).
   - New tool `restore_checkpoint(checkpoint_id: str) -> dict` (gated by policy, requires confirmation).
4. **Policy:**
   - `policy["checkpoints"]["max_keep"]` (default 20).
   - `policy["checkpoints"]["enabled"]` (default true).
   - `restore_checkpoint` added to `confirm_required` by default.

**Acceptance:** Run a `transaction` → `list_checkpoints` returns ≥1 entry → kill Blender → reopen → `restore_checkpoint(id)` brings back the pre-transaction state.

---

### W5 — Partial-Feature Cleanup (P1, P2, P3)

**Three small fixes batched together.**

#### P1 — Polygon cap enforcement
- In `blender_addon/capabilities/mesh.py:create_primitive`, after primitive creation, count `len(obj.data.polygons)` and raise if > `policy.max_polys` (need to thread the policy value to the add-on; currently policy lives only in MCP server).
- **Cleaner:** enforce at **MCP server** layer for `create_primitive` and `create_objects` by inspecting the requested size/segments BEFORE calling Blender. Server already has policy; this avoids cross-process policy sync.
- Decision: enforce server-side via heuristic checks; let add-on operate as before.

#### P2 — Progress streaming
- `mcp_server/blender_mcp/blender_client.py` already skips progress frames. Change to: when a `BLENDER_MCP_PROGRESS_HOOK` env var is set (extension provides URL), POST progress frames to it.
- Extension subscribes; tree view shows `🟡 render_region (32%)` for in-flight long ops.
- Optional polish — only do if W1's HTTP plumbing makes it cheap.

#### P3 — Approval server CSRF
- Already covered by W1's CSRF token mechanism. **Marked done if W1 completes.**

**Acceptance:** Asking AI to `create_primitive(kind="ico_sphere", size=10000, subdivisions=12)` returns `RESOURCE_LIMIT` error; long render shows progress in sidebar.

---

### W6 — Documentation Reconciliation (D1, D2, D3)

#### D1 — `docs/PLAN.md`
- Mark T-411 as **partial** (in-memory diff only) until W4 lands.
- Mark T-503 as **partial** (UI only) until W1 lands.
- Mark §14.6 (rate limit) as **partial** until W3 lands.
- Mark §14.7 (resource caps) as **partial** until W5 P1 lands.
- Mark §14.8 (checkpoints) as **partial** until W4 lands.
- Update change log with v2.1 entries as each workstream completes.

#### D2 — Tool naming
- Replace mentions of `build_geonodes` / `set_material_node_graph` with `build_nodes` (the actual unified tool).

#### D3 — README
- Replace any "one command install" claims with the honest 3-step setup until distribution-plan S2 ships the bundled runtime.
- Add a clear "What works today / What's coming" section.

**Acceptance:** Re-run the audit subagent on the same prompt; "Plan vs reality" mismatches table is empty.

---

## 5. Acceptance Gates

Each gate is a single E2E test; runs against real Blender + spawned MCP server + VS Code Insiders headless if possible.

| Gate | Workstream | Test |
|------|------------|------|
| **AG1** | W1 | AI calls `execute_python({code: 'print(1)'})` → webview opens → tester clicks Approve → AI receives success result. Repeat with Reject → CONFIRM_DENIED. |
| **AG2** | W2 | Fresh VS Code window, no folder open, VSIX installed, `blenderMcp.pythonPath` set → Copilot Chat Agent mode lists `blender.ping` and call returns `pong`. |
| **AG3** | W3 | 100 calls to `create_primitive` in 5 s → ≥40 receive `RATE_LIMITED`; `query` calls succeed in same window. |
| **AG4** | W4 | Run `transaction` with 3 steps → `list_checkpoints` returns 1 entry → modify scene → `restore_checkpoint(id)` reverts modifications. |
| **AG5** | W5 P1 | Call `create_primitive(kind='ico_sphere', subdivisions=12)` → returns `RESOURCE_LIMIT`. |
| **AG6** | W5 P3 | Send POST to extension's `/request` endpoint without CSRF token → 403 Forbidden. |
| **AG7** | W6 | Re-run audit prompt → "Plan vs reality" gaps section is empty. |

All gates green → tag **v2.1.0**.

---

## 6. Documentation Reconciliation

Status tracking added to `docs/PLAN.md` change log. Each workstream completion adds an entry like:

```markdown
| 2026-MM-DD | W1 | done | Approval flow now end-to-end (HTTP + CSRF) |
| 2026-MM-DD | W2 | done | Extension auto-registers MCP server provider |
```

`README.md` gets a new "Status & Capabilities" section after W1–W5 land, summarizing what genuinely works.

---

## 7. Test Strategy

Current state: ~30 unit tests in `mcp_server/tests/`, no real-Blender integration.

**Add for v2.1:**
- `tests/test_rate_limit.py` — bucket math + decorator behavior (W3).
- `tests/test_approval_flow.py` — fake HTTP server fixture, simulate user click (W1).
- `tests/integration/` — new directory, runs Blender headless via `blender --background --python script.py` to exercise W4 checkpoints + transactions end-to-end. Mark `@pytest.mark.integration`, opt-in via `pytest -m integration`.
- VS Code extension: add `vscode_extension/src/test/` using `@vscode/test-electron` to launch a real VS Code instance, install VSIX, assert MCP provider registers (W2).

**Coverage target:** maintain ≥80% on `policy.py`, `approval.py`; integration tests for W1, W4 mandatory.

---

## 8. Open Items

> Decisions / clarifications needed mid-implementation. None blocking start.

1. **Checkpoint storage location** — `%LOCALAPPDATA%\BlenderMCP\checkpoints\` keyed by scene name? By `.blend` file path hash? (W4)
2. **Rate-limit window** — fixed 10s vs sliding window? Token bucket vs leaky bucket? (W3)
3. **Approval timeout default** — 60s reasonable? Should it match the tool's own timeout? (W1)
4. **MCP provider duplicate detection** — auto-skip if user has `.vscode/mcp.json` defining `blender`, or rename the bundled one to `blender (extension)`? (W2)
5. **Progress streaming** — keep optional (W5 P2) or drop since AI clients rarely surface progress events? Decision: drop unless trivially cheap once W1 ships.

---

## 9. Sequencing With Distribution Plan

```
Today
  │
  ▼
W1 (Approval flow) ─┐
                    ├─► Both ship → v2.1.0 milestone
W2 (MCP register) ──┘
  │
  ▼
W3 (Rate limit) ────► v2.1.1
  │
  ▼
W4 (Checkpoints) ───► v2.2.0
  │
  ▼
W5 (Cleanup) ───────► v2.2.1
  │
  ▼
W6 (Docs) ──────────► docs in sync with code
  │
  ▼
*** START DISTRIBUTION PLAN ***
S1 (already mostly done by W2) ─► S2 (bundle Python) ─► S3 (SecretStorage)
                                          │
                                          ▼
                              S4 (wizard + bundled add-on)
                                          │
                                          ▼
                              S5 (CI + release) ─► v3.0.0 distributable
```

**W2 effectively becomes S1** — when W2 lands, S1 of the distribution plan is complete. No duplicated work.

---

## TL;DR

> **3.5 days of focused work** closes every functional gap the audit found, after which
> the codebase is *honestly* what `docs/PLAN.md` claims it is, and the
> distribution plan can proceed without false promises.

Suggested start: **W1 (approval flow) and W2 (MCP registration) in parallel.** Largest functional & UX wins first.

---

*End of remediation plan. Last updated 2026-05-05.*
