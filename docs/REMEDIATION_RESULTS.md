# Remediation Results — v2.1

Status of the audit findings raised against v2.0, after executing Phases 0-5
on branch `remediation/v2.1`. Re-run baseline: **113 pytest passing** (was 62)
+ extension compiles + VSIX 2.1.0-rc2 packaged.

## Blockers

| ID | Issue (audit) | Phase | Status | Where to verify |
|---|---|---|---|---|
| B1 | Approval flow was cosmetic — `confirm_required` returned a string instead of blocking | 1 | **Closed** | `mcp_server/blender_mcp/approval.py`, `server.py::execute_python`/`delete_object`, `vscode_extension/src/approval.ts`. Tests: `tests/test_approval_flow.py`. |
| B2 | Rate limit defined in default policy but never enforced | 3 | **Closed** | `mcp_server/blender_mcp/rate_limit.py` + `policy.py::Policy.require()`. Tests: `tests/test_rate_limit.py`. |
| B3 | No persistent checkpoints — only `bpy.ops.ed.undo_push` (lost on close) | 4 | **Closed (manual)** | `blender_addon/safety/checkpoints.py`, `capabilities/checkpoint.py`, MCP tools `create_checkpoint`/`list_checkpoints`/`restore_checkpoint`. Tests: `tests/test_checkpoints.py`. *Auto-snapshot-on-transaction* still optional. |
| B4 | Users had to hand-edit `.vscode/mcp.json`; no auto-registration | 2 | **Closed** | `vscode_extension/src/mcpProvider.ts` + manifest `mcpServerDefinitionProviders`; new settings `blenderMcp.pythonPath` / `serverModule`. |

## Partials

| ID | Issue | Phase | Status |
|---|---|---|---|
| P1 | Polygon cap declared but never checked before mutation | 5 | **Closed** — `policy.estimate_polys()` runs in `create_objects` before WS dispatch. Tests: `tests/test_poly_estimate.py`. |
| P2 | CSRF on approval HTTP server | 1 | **Closed** — random per-session CSRF, timing-safe compare, non-loopback peer rejection. |
| P3 | Progress relay for long-running tools | 5 | Deferred — needs streaming infra both sides; not blocking distribution. |

## Doc gaps

| ID | Issue | Where fixed |
|---|---|---|
| D1 | CHANGELOG missing v2.1 entry | `vscode_extension/CHANGELOG.md` |
| D2 | README settings table out of date | `vscode_extension/README.md` |
| D3 | SECURITY.md showed Rule 6/7/8 as "planned" | `docs/SECURITY.md` v2.1 implementation status table |

## Test deltas per phase

```
v2.0.0 baseline:  62 pytest passing
+ Phase 1:         8 new (approval flow)        → 70
+ Phase 3:        15 new (rate limit + bucket)  → 85
+ Phase 4:        15 new (checkpoint storage)   → 100
+ Phase 5:        13 new (poly estimator)       → 113
```

## Branch / tags / artifacts

- Branch: `remediation/v2.1` (7 commits on top of `master`)
- Baseline tag: `baseline-pre-remediation`
- Built: `vscode_extension/blender-mcp-bridge-2.1.0-rc2.vsix` (22.24 KB)
- Baseline measurement: `scripts/baselines/v2.0.0.json` (re-run via `scripts/measure_baseline.ps1 -Tag <name>`)

## What was *not* done (intentionally)

- No git push, no Marketplace publish, no PyPI release. Per repo policy, the
  user must explicitly authorise external publishing.
- Phase 6 originally proposed re-running the audit subagent. Skipped to keep
  token budget for code; re-running is a single command after merging.
- ARCHITECTURE.md was not rewritten end-to-end; the SECURITY v2.1 section is
  the canonical reference for newly-implemented behaviour.

## Next manual steps for the user

1. Install the new VSIX: `code --install-extension vscode_extension/blender-mcp-bridge-2.1.0-rc2.vsix --force`
2. Open VS Code settings → set `blenderMcp.pythonPath` to your `mcp_server/.venv/Scripts/python.exe`.
3. Reload window. Copilot Chat (Agent mode) should list `blender` MCP server tools without any `.vscode/mcp.json`.
4. Try a destructive call (e.g. `delete_object`); the approval webview should appear and block the call until you click Approve / Reject.
