"""Persistent checkpoint storage for the Blender MCP add-on.

Saves a copy of the current .blend (via bpy.ops.wm.save_as_mainfile copy=True)
plus a JSON sidecar describing the action that triggered it. Lets users
recover from an AI mistake even after closing Blender.

Layout:
    %LOCALAPPDATA%\\BlenderMCP\\checkpoints\\<sha256(filepath)[:12]>\\
        <iso-utc-ts>-<label>.blend
        <iso-utc-ts>-<label>.json   (metadata)

The path-and-metadata machinery is pure stdlib so it can be unit-tested
without Blender. Functions that touch bpy are isolated behind try/except so
the module imports cleanly under pytest.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("blender_mcp.checkpoints")

DEFAULT_KEEP = 20
LABEL_MAX_LEN = 40

# Reserved Windows device names; creating a file with these stems fails or
# silently succeeds in odd ways. Sanitise label to avoid them on every OS so
# the storage layout is portable.
_WINDOWS_RESERVED: frozenset[str] = frozenset(
    {"CON", "PRN", "NUL", "AUX"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


@dataclass(frozen=True)
class CheckpointEntry:
    """Lightweight record of one saved checkpoint."""

    label: str
    timestamp: str  # ISO 8601 UTC, second precision, safe for filenames
    blend_path: str
    meta_path: str
    size_bytes: int
    source_blend: str | None
    note: str | None


def checkpoints_root() -> Path:
    """Top-level checkpoint directory, OS-specific."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "BlenderMCP" / "checkpoints"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "BlenderMCP" / "checkpoints"
    xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(xdg) / "blender-mcp" / "checkpoints"


def project_dir(source_blend: str | None) -> Path:
    """Per-source-file subdirectory.

    `source_blend == None` (unsaved scene) maps to a stable "untitled" bucket.
    """
    key = source_blend or "<untitled>"
    digest = hashlib.sha256(key.encode("utf-8", errors="replace")).hexdigest()[:12]
    return checkpoints_root() / digest


def _safe_label(label: str | None) -> str:
    raw = (label or "checkpoint").strip()
    cleaned = "".join(c if (c.isalnum() or c in "-_") else "-" for c in raw)
    cleaned = cleaned.strip("-") or "checkpoint"
    cleaned = cleaned[:LABEL_MAX_LEN]
    if cleaned.upper() in _WINDOWS_RESERVED:
        cleaned = f"{cleaned}_ck"
    return cleaned


def _timestamp() -> str:
    # Microsecond precision avoids collisions on rapid back-to-back saves.
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")


def build_paths(source_blend: str | None, label: str | None) -> tuple[Path, Path, str, str]:
    """Compute (blend_path, meta_path, label, timestamp) for a new checkpoint.

    On the rare chance two calls land in the same microsecond, append a short
    counter suffix to keep filenames unique.
    """
    label_safe = _safe_label(label)
    pdir = project_dir(source_blend)
    for attempt in range(8):
        ts = _timestamp()
        if attempt:
            ts = f"{ts}-{attempt}"
        blend = pdir / f"{ts}-{label_safe}.blend"
        meta = pdir / f"{ts}-{label_safe}.json"
        if not blend.exists() and not meta.exists():
            return blend, meta, label_safe, ts
    # Extreme fallback: nanosecond from time.time_ns()
    import time as _time

    ts = f"{_timestamp()}-{_time.time_ns()}"
    return (
        pdir / f"{ts}-{label_safe}.blend",
        pdir / f"{ts}-{label_safe}.json",
        label_safe,
        ts,
    )


def list_checkpoints(source_blend: str | None) -> list[CheckpointEntry]:
    """List checkpoints for a given source file, newest first."""
    pdir = project_dir(source_blend)
    if not pdir.is_dir():
        return []
    entries: list[CheckpointEntry] = []
    for meta_file in sorted(pdir.glob("*.json"), reverse=True):
        try:
            data = json.loads(meta_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("skipping unreadable checkpoint meta %s: %s", meta_file, exc)
            continue
        blend_path = Path(data.get("blend_path", ""))
        if not blend_path.is_file():
            continue
        try:
            size = blend_path.stat().st_size
        except OSError:
            size = 0
        entries.append(
            CheckpointEntry(
                label=str(data.get("label", "")),
                timestamp=str(data.get("timestamp", "")),
                blend_path=str(blend_path),
                meta_path=str(meta_file),
                size_bytes=size,
                source_blend=data.get("source_blend"),
                note=data.get("note"),
            )
        )
    return entries


def write_metadata(
    meta_path: Path,
    *,
    label: str,
    timestamp: str,
    blend_path: Path,
    source_blend: str | None,
    note: str | None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Write the JSON sidecar describing a checkpoint."""
    payload: dict[str, Any] = {
        "label": label,
        "timestamp": timestamp,
        "blend_path": str(blend_path),
        "source_blend": source_blend,
        "note": note,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        payload["extra"] = extra
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def prune(source_blend: str | None, keep: int = DEFAULT_KEEP) -> list[Path]:
    """Delete oldest checkpoints beyond `keep`. Returns removed blend paths."""
    if keep < 1:
        keep = 1
    entries = list_checkpoints(source_blend)
    if len(entries) <= keep:
        return []
    removed: list[Path] = []
    for entry in entries[keep:]:
        for p in (Path(entry.blend_path), Path(entry.meta_path)):
            try:
                p.unlink()
            except OSError as exc:
                log.warning("failed to remove %s: %s", p, exc)
        removed.append(Path(entry.blend_path))
    return removed


def entry_to_dict(entry: CheckpointEntry) -> dict[str, Any]:
    return asdict(entry)


# ---------------------------------------------------------------------------
# Blender-side helpers (only callable inside Blender)
# ---------------------------------------------------------------------------


def save_checkpoint(label: str | None, note: str | None = None) -> dict[str, Any]:
    """Save the current Blender file as a checkpoint copy. Requires bpy."""
    try:
        import bpy  # type: ignore
    except ImportError:
        return {"ok": False, "error": "bpy_unavailable", "message": "save_checkpoint can only run inside Blender"}

    source_blend = bpy.data.filepath or None
    blend, meta, label_safe, ts = build_paths(source_blend, label)
    blend.parent.mkdir(parents=True, exist_ok=True)
    try:
        # copy=True saves a snapshot without changing bpy.data.filepath.
        bpy.ops.wm.save_as_mainfile(filepath=str(blend), copy=True, compress=True)
    except RuntimeError as exc:
        return {"ok": False, "error": "save_failed", "message": str(exc)}
    if not blend.is_file():
        return {"ok": False, "error": "save_failed", "message": "blend file not written"}
    write_metadata(
        meta,
        label=label_safe,
        timestamp=ts,
        blend_path=blend,
        source_blend=source_blend,
        note=note,
    )
    pruned = prune(source_blend)
    return {
        "ok": True,
        "label": label_safe,
        "timestamp": ts,
        "blend_path": str(blend),
        "size_bytes": blend.stat().st_size,
        "pruned": [str(p) for p in pruned],
    }


def restore_checkpoint(blend_path: str) -> dict[str, Any]:
    """Load a checkpoint .blend file, replacing the current scene. Requires bpy."""
    try:
        import bpy  # type: ignore
    except ImportError:
        return {"ok": False, "error": "bpy_unavailable", "message": "restore_checkpoint can only run inside Blender"}

    p = Path(blend_path)
    if not p.is_file():
        return {"ok": False, "error": "not_found", "message": f"checkpoint not found: {blend_path}"}
    # Verify the path lives under our checkpoints root (prevent path traversal).
    try:
        p.resolve().relative_to(checkpoints_root().resolve())
    except (ValueError, OSError):
        return {"ok": False, "error": "outside_checkpoint_root", "message": "refusing to load file outside the checkpoint directory"}
    try:
        bpy.ops.wm.open_mainfile(filepath=str(p))
    except RuntimeError as exc:
        return {"ok": False, "error": "open_failed", "message": str(exc)}
    return {"ok": True, "loaded": str(p)}
