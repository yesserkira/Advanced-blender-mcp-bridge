"""Auto-register the Blender MCP server with supported AI clients.

Goal: a user who installed the Blender add-on + this Python package should
not have to hand-edit a single JSON file. They run::

    blender-mcp-install            # interactive — prompts which clients
    blender-mcp-install --all      # write to every detected client
    blender-mcp-install --client claude cursor
    blender-mcp-install --print    # print snippets, don't write

This module is intentionally dependency-free (stdlib only) so it works in
any Python environment, including ones the AI client itself spawns.

Each client gets a ``blender`` server entry pointing at the same launch
command (``blender-mcp``). Token + URL are auto-discovered at runtime from
``~/.blender_mcp/connection.json`` written by the Blender add-on, so
nothing secret is written to client configs.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import dataclass
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Client registry
# ---------------------------------------------------------------------------

# Each client has:
#   name     — human label
#   path()   — returns the absolute config file path (or None if N/A here)
#   shape    — "mcpServers" (Claude/Cursor/Cline/Windsurf) or "vscode"
#              (uses "servers" with type:"stdio")
#   detect() — heuristic that says "this client looks installed"

@dataclass
class ClientSpec:
    key: str
    name: str
    path: Callable[[], str | None]
    shape: str  # "mcpServers" | "vscode"
    detect: Callable[[], bool]


def _appdata() -> str:
    return os.environ.get("APPDATA") or os.path.expanduser("~/AppData/Roaming")


def _home() -> str:
    return os.path.expanduser("~")


def _claude_path() -> str | None:
    if sys.platform == "win32":
        return os.path.join(_appdata(), "Claude", "claude_desktop_config.json")
    if sys.platform == "darwin":
        return os.path.join(
            _home(), "Library", "Application Support", "Claude",
            "claude_desktop_config.json",
        )
    return os.path.join(_home(), ".config", "Claude", "claude_desktop_config.json")


def _cursor_path() -> str | None:
    return os.path.join(_home(), ".cursor", "mcp.json")


def _cline_path() -> str | None:
    if sys.platform == "win32":
        return os.path.join(
            _appdata(), "Code", "User", "globalStorage",
            "saoudrizwan.claude-dev", "settings", "cline_mcp_settings.json",
        )
    if sys.platform == "darwin":
        return os.path.join(
            _home(), "Library", "Application Support", "Code", "User",
            "globalStorage", "saoudrizwan.claude-dev", "settings",
            "cline_mcp_settings.json",
        )
    return os.path.join(
        _home(), ".config", "Code", "User", "globalStorage",
        "saoudrizwan.claude-dev", "settings", "cline_mcp_settings.json",
    )


def _vscode_path() -> str | None:
    if sys.platform == "win32":
        return os.path.join(_appdata(), "Code", "User", "mcp.json")
    if sys.platform == "darwin":
        return os.path.join(
            _home(), "Library", "Application Support", "Code", "User", "mcp.json",
        )
    return os.path.join(_home(), ".config", "Code", "User", "mcp.json")


def _windsurf_path() -> str | None:
    return os.path.join(_home(), ".codeium", "windsurf", "mcp_config.json")


def _continue_path() -> str | None:
    return os.path.join(_home(), ".continue", "config.json")


def _exists_parent(p: str | None) -> bool:
    if not p:
        return False
    return os.path.isdir(os.path.dirname(p))


CLIENTS: list[ClientSpec] = [
    ClientSpec("claude", "Claude Desktop",
               lambda: _claude_path(), "mcpServers",
               lambda: _exists_parent(_claude_path())),
    ClientSpec("cursor", "Cursor",
               lambda: _cursor_path(), "mcpServers",
               lambda: _exists_parent(_cursor_path()) or os.path.isdir(
                   os.path.join(_home(), ".cursor"))),
    ClientSpec("cline", "Cline (VS Code)",
               lambda: _cline_path(), "mcpServers",
               lambda: _exists_parent(_cline_path())),
    ClientSpec("vscode", "VS Code (built-in MCP)",
               lambda: _vscode_path(), "vscode",
               lambda: _exists_parent(_vscode_path())),
    ClientSpec("windsurf", "Windsurf",
               lambda: _windsurf_path(), "mcpServers",
               lambda: _exists_parent(_windsurf_path())),
    ClientSpec("continue", "Continue",
               lambda: _continue_path(), "mcpServers",
               lambda: _exists_parent(_continue_path())),
]


# ---------------------------------------------------------------------------
# Launch-command resolution
# ---------------------------------------------------------------------------

def resolve_launch_command() -> tuple[str, list[str]]:
    """Pick the best command to launch ``blender-mcp`` on this machine.

    Priority:
      1. ``blender-mcp`` on PATH (installed via pipx / uv tool / pip).
      2. ``uvx blender-mcp`` if ``uvx`` is on PATH.
      3. ``python -m blender_mcp.server`` using the current interpreter.
    """
    direct = shutil.which("blender-mcp")
    if direct:
        return (direct, [])
    uvx = shutil.which("uvx")
    if uvx:
        return (uvx, ["blender-mcp"])
    return (sys.executable, ["-m", "blender_mcp.server"])


# ---------------------------------------------------------------------------
# Snippet builder
# ---------------------------------------------------------------------------

def build_server_entry(shape: str, command: str, args: list[str]) -> dict[str, Any]:
    """Return the per-client server entry for the given config shape."""
    if shape == "vscode":
        return {
            "type": "stdio",
            "command": command,
            "args": args,
        }
    # default mcpServers shape (Claude / Cursor / Cline / Windsurf)
    return {
        "command": command,
        "args": args,
    }


def container_key(shape: str) -> str:
    return "servers" if shape == "vscode" else "mcpServers"


# ---------------------------------------------------------------------------
# Patch a single config file
# ---------------------------------------------------------------------------

def patch_config(
    path: str,
    shape: str,
    command: str,
    args: list[str],
    server_name: str = "blender",
    backup: bool = True,
) -> dict[str, Any]:
    """Idempotently merge our server entry into ``path``.

    - Creates the file (and parent dirs) if missing.
    - Preserves all other servers/keys.
    - Writes a ``.bak`` once before overwriting (if file existed and
      ``backup`` is True).
    - Returns ``{"path", "action": "created"|"updated"|"unchanged",
      "backup": bool}``.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)

    existed = os.path.exists(path)
    data: dict[str, Any] = {}
    if existed:
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read().strip()
            data = json.loads(raw) if raw else {}
            if not isinstance(data, dict):
                raise ValueError(
                    f"Config root is {type(data).__name__}, expected object"
                )
        except (json.JSONDecodeError, ValueError) as e:
            raise RuntimeError(
                f"Cannot parse existing config at {path}: {e}"
            ) from e

    key = container_key(shape)
    container = data.get(key)
    if not isinstance(container, dict):
        container = {}
        data[key] = container

    new_entry = build_server_entry(shape, command, args)
    old_entry = container.get(server_name)

    if old_entry == new_entry:
        return {"path": path, "action": "unchanged", "backup": False}

    container[server_name] = new_entry

    wrote_backup = False
    if existed and backup:
        bak = path + ".bak"
        try:
            shutil.copy2(path, bak)
            wrote_backup = True
        except OSError:
            pass

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    return {
        "path": path,
        "action": "updated" if existed else "created",
        "backup": wrote_backup,
    }


# ---------------------------------------------------------------------------
# Top-level install entry point
# ---------------------------------------------------------------------------

def install(
    selected_keys: list[str] | None = None,
    *,
    print_only: bool = False,
    server_name: str = "blender",
) -> list[dict[str, Any]]:
    """Install the server entry into one or more clients.

    Args:
        selected_keys: list of client keys (e.g. ['claude','cursor']).
            ``None`` means "all detected clients".
        print_only: if True, return a result list with ``"action": "print"``
            and the would-be JSON, without touching disk.

    Returns: list of per-client result dicts.
    """
    command, args = resolve_launch_command()

    if selected_keys is None:
        targets = [c for c in CLIENTS if c.detect()]
    else:
        wanted = {k.lower() for k in selected_keys}
        targets = [c for c in CLIENTS if c.key in wanted]

    results: list[dict[str, Any]] = []
    for client in targets:
        path = client.path()
        if not path:
            results.append({
                "client": client.key, "name": client.name,
                "action": "skipped", "reason": "no config path on this OS",
            })
            continue

        snippet = {
            container_key(client.shape): {
                server_name: build_server_entry(client.shape, command, args),
            }
        }

        if print_only:
            results.append({
                "client": client.key, "name": client.name, "path": path,
                "action": "print", "snippet": snippet,
            })
            continue

        try:
            r = patch_config(path, client.shape, command, args, server_name)
            r["client"] = client.key
            r["name"] = client.name
            results.append(r)
        except Exception as e:  # noqa: BLE001
            results.append({
                "client": client.key, "name": client.name, "path": path,
                "action": "error", "error": str(e),
            })
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _format_result(r: dict[str, Any]) -> str:
    name = r.get("name", r.get("client", "?"))
    action = r.get("action", "?")
    if action == "print":
        return f"\n--- {name} ({r['path']}) ---\n" + json.dumps(
            r["snippet"], indent=2
        )
    if action == "error":
        return f"  [ERROR] {name}: {r.get('error')}"
    if action == "skipped":
        return f"  [skip ] {name}: {r.get('reason')}"
    bak = " (.bak written)" if r.get("backup") else ""
    return f"  [{action:>7}] {name} -> {r.get('path')}{bak}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="blender-mcp-install",
        description="Register the Blender MCP server with supported AI clients.",
    )
    parser.add_argument(
        "--client", "-c", action="append", default=None,
        choices=[c.key for c in CLIENTS],
        help="Specific client(s) to install into (repeatable). "
             "Default: all detected clients.",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Install into every supported client, even if not detected.",
    )
    parser.add_argument(
        "--print", dest="print_only", action="store_true",
        help="Print the JSON snippet for each client without writing.",
    )
    parser.add_argument(
        "--server-name", default="blender",
        help="Name to register under (default: 'blender').",
    )
    parser.add_argument(
        "--list-clients", action="store_true",
        help="List supported clients and detection status, then exit.",
    )
    args = parser.parse_args(argv)

    if args.list_clients:
        print("Supported AI clients:\n")
        for c in CLIENTS:
            mark = "detected" if c.detect() else "not detected"
            print(f"  {c.key:<10} {c.name:<25} [{mark}]  {c.path()}")
        return 0

    if args.all:
        keys = [c.key for c in CLIENTS]
    else:
        keys = args.client  # may be None => auto-detect

    results = install(
        selected_keys=keys,
        print_only=args.print_only,
        server_name=args.server_name,
    )

    if not results:
        print("No supported AI clients detected.")
        print("Re-run with --all to write configs anyway, or --list-clients "
              "to see what's checked.")
        return 1

    print(f"Blender MCP launch command: {' '.join([resolve_launch_command()[0], *resolve_launch_command()[1]])}\n")
    for r in results:
        print(_format_result(r))

    if not args.print_only:
        print("\nDone. Restart the affected client(s) and start a fresh chat.")
        print("Token is auto-discovered from ~/.blender_mcp/connection.json "
              "while Blender is running with the add-on enabled.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
