"""Append-only JSONL audit log.

Logs every command to %LOCALAPPDATA%\\BlenderMCP\\audit-YYYY-MM-DD.log.
Rotates at 10 MB.
"""

import hashlib
import json
import os
import time
from datetime import datetime, timezone

_MAX_SIZE = 10 * 1024 * 1024  # 10 MB

_log_dir = None
_current_file = None
_current_path = None


def _get_log_dir() -> str:
    global _log_dir
    if _log_dir is None:
        base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        _log_dir = os.path.join(base, "BlenderMCP")
        os.makedirs(_log_dir, exist_ok=True)
    return _log_dir


def _get_log_file():
    global _current_file, _current_path

    log_dir = _get_log_dir()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = os.path.join(log_dir, f"audit-{today}.log")

    # Check rotation
    if _current_path == path and _current_file is not None:
        try:
            size = os.path.getsize(path)
            if size >= _MAX_SIZE:
                _current_file.close()
                # Rotate: rename with timestamp suffix
                rotated = path + f".{int(time.time())}"
                os.rename(path, rotated)
                _current_file = open(path, "a", encoding="utf-8")
                _current_path = path
        except OSError:
            pass
        return _current_file

    # Close old file if different day
    if _current_file is not None:
        try:
            _current_file.close()
        except OSError:
            pass

    _current_file = open(path, "a", encoding="utf-8")
    _current_path = path
    return _current_file


def _hash_args(args: dict) -> str:
    """SHA-256 of args JSON (deterministic)."""
    raw = json.dumps(args, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def log_command(op: str, args: dict, ok: bool, elapsed_ms: int,
                undo_id: str | None = None):
    """Log a command execution to the audit log.

    Never logs secrets (auth tokens, raw code beyond hash).
    """
    # Strip auth from args if accidentally passed
    safe_args = {k: v for k, v in args.items() if k != "auth"}

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "op": op,
        "args_sha256": _hash_args(safe_args),
        "ok": ok,
        "elapsed_ms": elapsed_ms,
    }
    if undo_id:
        entry["undo_id"] = undo_id

    try:
        f = _get_log_file()
        f.write(json.dumps(entry) + "\n")
        f.flush()
    except Exception:
        pass  # Never crash on logging failure


def close():
    """Close the current log file."""
    global _current_file, _current_path
    if _current_file:
        try:
            _current_file.close()
        except OSError:
            pass
        _current_file = None
        _current_path = None
