"""Command dispatcher.

Routes incoming commands to registered capability functions.
"""

import inspect

from ..capabilities import OP_REGISTRY


def dispatch(cmd: dict, progress_callback=None):
    """Dispatch a command to its registered capability.

    Args:
        cmd: Dict with 'op' and 'args' keys.
        progress_callback: Optional progress reporter for ops that support it.

    Returns:
        Result from the capability function.

    Raises:
        ValueError: If 'op' is missing or unknown.
    """
    op = cmd.get("op")
    if not op:
        raise ValueError("Missing 'op' field in command")

    fn = OP_REGISTRY.get(op)
    if fn is None:
        raise ValueError(f"Unknown operation: {op}")

    args = cmd.get("args", {})

    # Forward progress_callback to functions that accept it
    if progress_callback is not None:
        sig = inspect.signature(fn)
        if "progress_callback" in sig.parameters:
            return fn(args, progress_callback=progress_callback)

    return fn(args)
