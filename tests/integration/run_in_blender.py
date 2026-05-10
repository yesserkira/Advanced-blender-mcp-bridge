"""Headless Blender integration harness.

Intended to be invoked as:

    blender --background --factory-startup --python tests/integration/run_in_blender.py -- [pytest_args...]

What it does:
1. Adds the workspace root to sys.path so blender_addon and mcp_server are importable.
2. Loads all capability modules into the OP_REGISTRY (no WebSocket server is
   started — integration tests call dispatch() directly to keep the harness
   simple and deterministic).
3. Runs pytest against tests/integration/, exits with pytest's return code.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _bootstrap() -> None:
    here = Path(__file__).resolve()
    repo_root = here.parents[2]
    # Prepend repo root and mcp_server so imports work without install.
    for p in (repo_root, repo_root / "mcp_server"):
        sp = str(p)
        if sp not in sys.path:
            sys.path.insert(0, sp)

    # Vendor path for the add-on (websockets etc.)
    vendor = repo_root / "blender_addon" / "vendor"
    if vendor.is_dir():
        sys.path.insert(0, str(vendor))

    # Force the addon's capability registry to load. We do NOT call
    # blender_addon.register() because that wires up UI panels & preferences
    # which require a fuller Blender context than --background gives us.
    from blender_addon.capabilities import load_all  # type: ignore
    load_all()


def main() -> int:
    _bootstrap()

    # Forward argv after the "--" sentinel to pytest. Blender swallows
    # everything before "--".
    try:
        sep = sys.argv.index("--")
        pytest_args = sys.argv[sep + 1:]
    except ValueError:
        pytest_args = []

    integ_dir = Path(__file__).resolve().parent
    if not pytest_args:
        pytest_args = [str(integ_dir), "-v", "--tb=short"]

    import pytest  # type: ignore

    return pytest.main(pytest_args)


if __name__ == "__main__":
    rc = main()
    # Blender ignores sys.exit on some platforms; use os._exit to be safe.
    os._exit(rc if isinstance(rc, int) else 1)
