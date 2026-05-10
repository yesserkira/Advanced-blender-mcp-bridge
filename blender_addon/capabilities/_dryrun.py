"""Dry-run helpers for mutating capabilities.

When a command arrives with `args["__dry_run"] = True`, the capability
returns a canonical "would do" report instead of mutating Blender state:

    {
      "dry_run": True,
      "op": <capability label>,
      "would": [<one entry per planned change>],
      "estimated_polys": <int, optional>,
      "warnings": [<str>],
    }

These helpers exist so every dry-run-aware capability returns the SAME shape
— Copilot/Claude can rely on the schema regardless of which tool is gated.
"""

from __future__ import annotations

from typing import Any

import bpy


# Approx polygon counts for primitives at default subdivision (kept in sync
# with mcp_server/blender_mcp/policy._PRIMITIVE_POLY_ESTIMATES).
_PRIM_POLYS = {
    "cube": 6, "plane": 1, "circle": 32,
    "sphere": 960, "uv_sphere": 960,
    "ico_sphere": 320, "icosphere": 320,
    "cylinder": 96, "cone": 64, "torus": 576,
    "monkey": 968, "grid": 100,
}


def is_dry_run(args: dict) -> bool:
    return bool(args.get("__dry_run"))


def estimate_polys(spec: dict) -> int:
    kind = (spec.get("kind") or "").lower()
    if kind in _PRIM_POLYS:
        # Account for size — rough scaling is irrelevant for poly count.
        return _PRIM_POLYS[kind]
    if kind in ("light", "camera", "empty"):
        return 0
    return 0


def would_create(spec: dict) -> dict:
    kind = spec.get("kind", "?")
    name = spec.get("name") or f"<{kind}>"
    entry = {
        "op": "create",
        "kind": kind,
        "name": name,
        "location": list(spec.get("location") or (0, 0, 0)),
    }
    polys = estimate_polys(spec)
    if polys:
        entry["estimated_polys"] = polys
    return entry


def would_modify(target: str, properties: dict | None = None) -> dict:
    return {
        "op": "modify",
        "target": target,
        "changes": dict(properties or {}),
    }


def would_delete(name: str) -> dict:
    obj = bpy.data.objects.get(name)
    return {
        "op": "delete",
        "target": name,
        "exists": obj is not None,
        "type": obj.type if obj is not None else None,
    }


def report(
    op: str,
    would: list[dict],
    *,
    warnings: list[str] | None = None,
) -> dict:
    """Bundle a uniform dry-run response."""
    total_polys = sum(int(w.get("estimated_polys") or 0) for w in would)
    out: dict[str, Any] = {
        "dry_run": True,
        "op": op,
        "would": would,
        "count": len(would),
    }
    if total_polys:
        out["estimated_polys"] = total_polys
    if warnings:
        out["warnings"] = warnings
    return out


__all__ = [
    "is_dry_run",
    "estimate_polys",
    "would_create",
    "would_modify",
    "would_delete",
    "report",
]
