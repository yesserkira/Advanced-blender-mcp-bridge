"""Checkpoint capabilities — save/list/restore .blend snapshots."""

from __future__ import annotations

from typing import Any

from . import register_capability
from ..safety import checkpoints


def _source_blend() -> str | None:
    try:
        import bpy  # type: ignore

        return bpy.data.filepath or None
    except Exception:
        return None


def _create(args: dict) -> dict[str, Any]:
    label = args.get("label")
    note = args.get("note")
    return checkpoints.save_checkpoint(label=label, note=note)


def _list(args: dict) -> dict[str, Any]:
    source = args.get("source") if args else None
    if source is None:
        source = _source_blend()
    entries = [checkpoints.entry_to_dict(e) for e in checkpoints.list_checkpoints(source)]
    return {"ok": True, "source": source, "checkpoints": entries}


def _restore(args: dict) -> dict[str, Any]:
    blend_path = args.get("blend_path")
    if not isinstance(blend_path, str) or not blend_path:
        return {"ok": False, "error": "missing_arg", "message": "'blend_path' is required"}
    return checkpoints.restore_checkpoint(blend_path)


register_capability("checkpoint.create", _create)
register_capability("checkpoint.list", _list)
register_capability("checkpoint.restore", _restore)
