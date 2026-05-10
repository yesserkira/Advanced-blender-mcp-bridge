"""End-to-end smoke test that simulates exactly what the VS Code extension does
when it spawns the MCP server child process.

We don't go through Copilot Chat itself — that's outside our control. Instead
we replicate the JSON-RPC handshake (initialize + tools/list) directly over
stdio, with the same env vars that mcpProvider.ts plumbs through. If this
works, Copilot Chat in Agent mode will work.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PY = REPO / "mcp_server" / ".venv" / "Scripts" / "python.exe"
if not PY.exists():
    PY = REPO / "mcp_server" / ".venv" / "bin" / "python"


def main() -> int:
    if not PY.exists():
        print(f"FAIL: venv python not found at {PY}", file=sys.stderr)
        return 2

    env = {
        **os.environ,
        # Same vars mcpProvider.ts injects:
        "BLENDER_MCP_TOKEN": "smoke-test-token",
        "BLENDER_MCP_URL": "ws://127.0.0.1:9876",
        "BLENDER_MCP_APPROVAL_URL": "http://127.0.0.1:54321",
        "BLENDER_MCP_APPROVAL_CSRF": "smoke-csrf",
    }

    print(f"spawn: {PY} -m blender_mcp.server")
    proc = subprocess.Popen(
        [str(PY), "-m", "blender_mcp.server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=str(REPO / "mcp_server"),
    )

    def send(payload: dict) -> None:
        line = (json.dumps(payload) + "\n").encode("utf-8")
        assert proc.stdin is not None
        proc.stdin.write(line)
        proc.stdin.flush()

    def recv() -> dict | None:
        assert proc.stdout is not None
        # MCP servers respond with one JSON object per line.
        line = proc.stdout.readline()
        if not line:
            return None
        return json.loads(line.decode("utf-8"))

    try:
        # 1. initialize
        send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "smoke", "version": "0"},
                },
            }
        )
        init = recv()
        if not init or "result" not in init:
            print(f"FAIL: bad initialize response: {init}")
            return 3
        info = init["result"].get("serverInfo", {})
        print(f"server: {info.get('name', '?')} {info.get('version', '?')}")

        # 2. notifications/initialized (one-way)
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})

        # 3. tools/list
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools_resp = recv()
        if not tools_resp or "result" not in tools_resp:
            print(f"FAIL: bad tools/list response: {tools_resp}")
            return 4

        tools = tools_resp["result"].get("tools", [])
        names = sorted(t["name"] for t in tools)
        print(f"tools advertised: {len(names)}")
        for n in names:
            print(f"  - {n}")

        # Sanity: must include the v2.1 additions
        required = {"create_checkpoint", "list_checkpoints", "restore_checkpoint",
                    "execute_python", "delete_object", "create_objects"}
        missing = required - set(names)
        if missing:
            print(f"FAIL: missing tools: {missing}")
            return 5

        # v2.2: every tool must carry annotations, and the read-only/destructive
        # hints must match what tool_meta says.
        by_name = {t["name"]: t for t in tools}
        expect_read_only = {"ping", "query", "list", "describe_api",
                            "get_property", "scene_diff", "list_assets",
                            "list_checkpoints", "viewport_screenshot",
                            "render_region", "bake_preview", "get_audit_log"}
        expect_destructive = {"delete_object", "execute_python",
                              "restore_checkpoint", "remove_modifier"}
        ann_failures: list[str] = []
        for n in expect_read_only:
            ann = by_name.get(n, {}).get("annotations") or {}
            if not ann.get("readOnlyHint"):
                ann_failures.append(f"{n} should be readOnlyHint=True, got {ann}")
        for n in expect_destructive:
            ann = by_name.get(n, {}).get("annotations") or {}
            if not ann.get("destructiveHint"):
                ann_failures.append(f"{n} should be destructiveHint=True, got {ann}")
        if ann_failures:
            print("FAIL: annotation mismatches:")
            for line in ann_failures:
                print(f"  {line}")
            return 6
        print(f"annotations: {sum(1 for t in tools if t.get('annotations'))}/{len(tools)} tools annotated")

        # 4. resources/list
        send({"jsonrpc": "2.0", "id": 3, "method": "resources/list"})
        res_resp = recv()
        if not res_resp or "result" not in res_resp:
            print(f"FAIL: bad resources/list response: {res_resp}")
            return 7
        resources = res_resp["result"].get("resources", [])
        uris = sorted(r["uri"] for r in resources)
        print(f"resources advertised: {len(uris)}")
        for u in uris:
            print(f"  - {u}")
        expect_uris = {"blender://scene/current", "blender://scene/summary"}
        if not expect_uris.issubset(set(uris)):
            print(f"FAIL: missing resources: {expect_uris - set(uris)}")
            return 8

        # NOTE: skipping resources/read here. The handler calls into Blender;
        # without a real Blender running, BlenderWS would retry forever.
        # tests/test_resources.py covers the round-trip via the fake WS server.

        print("\nOK: MCP server spawned, initialized, listed tools.")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        # Drain stderr for diagnostics if anything went wrong above.
        if proc.stderr:
            err = proc.stderr.read().decode("utf-8", errors="replace")
            if err.strip():
                print("\n--- server stderr ---")
                print(err)


if __name__ == "__main__":
    sys.exit(main())
