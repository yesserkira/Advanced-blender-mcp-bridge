"""Command dispatcher.

Routes incoming commands to registered capability functions.

v2.0: batch protocol — when args contains an "items" list, the handler is
called once per item under a single undo checkpoint, and results are
returned as {"batch": True, "count": N, "results": [...], "errors": [...]}.
"""

import inspect

import bpy

from ..capabilities import OP_REGISTRY


def _run(fn, args, progress_callback):
    sig = inspect.signature(fn)
    if progress_callback is not None and "progress_callback" in sig.parameters:
        return fn(args, progress_callback=progress_callback)
    return fn(args)


def dispatch(cmd: dict, progress_callback=None, dry_run: bool = False):
    """Dispatch a command to its registered capability.

    Args:
        cmd: Dict with 'op' and 'args' keys.
        progress_callback: Optional progress reporter for ops that support it.
        dry_run: When True, mutating capabilities should return their planned
                 effect (`{"dry_run": True, "would": [...]}`) instead of
                 applying changes. The flag is forwarded to handlers via
                 args["__dry_run"]; capabilities that don't honour it simply
                 execute normally (safe default — explicit allow-list of
                 dry-run-aware ops is in capabilities/_dryrun.py).
    """
    op = cmd.get("op")
    if not op:
        raise ValueError("Missing 'op' field in command")

    fn = OP_REGISTRY.get(op)
    if fn is None:
        raise ValueError(f"Unknown operation: {op}")

    args = cmd.get("args", {}) or {}
    if dry_run and isinstance(args, dict):
        # Don't mutate caller's dict; copy + flag.
        args = dict(args)
        args["__dry_run"] = True

    # Batch mode: args = {"items": [...], "common": {...}}
    items = args.get("items") if isinstance(args, dict) else None
    if isinstance(items, list):
        common = args.get("common") or {}
        cmd_id = args.get("_cmd_id", "batch")
        if not dry_run:
            try:
                bpy.ops.ed.undo_push(message=f"AI:batch:{op}:n={len(items)}:{cmd_id}")
            except Exception:
                pass
        results: list = []
        errors: list = []
        for i, item in enumerate(items):
            merged = dict(common)
            if isinstance(item, dict):
                merged.update(item)
            else:
                merged["value"] = item
            merged.setdefault("_cmd_id", f"{cmd_id}.{i}")
            if dry_run:
                merged["__dry_run"] = True
            try:
                results.append(_run(fn, merged, None))
            except Exception as e:
                errors.append({"index": i, "error": str(e), "type": type(e).__name__})
        return {
            "batch": True,
            "op": op,
            "dry_run": dry_run,
            "count": len(items),
            "ok_count": len(results),
            "error_count": len(errors),
            "results": results,
            "errors": errors,
        }

    return _run(fn, args, progress_callback)

