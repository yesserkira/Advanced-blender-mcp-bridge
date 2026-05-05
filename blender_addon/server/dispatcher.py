"""Command dispatcher.

Routes incoming commands to registered capability functions.
"""

from ..capabilities import OP_REGISTRY


def dispatch(cmd: dict):
    """Dispatch a command to its registered capability.

    Args:
        cmd: Dict with 'op' and 'args' keys.

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
    return fn(args)
