"""Execute arbitrary Python with AST validation (gated capability)."""

import re
import traceback

import bpy

from . import register_capability
from ..safety.validator import validate_python

MAX_TIMEOUT = 30.0


def _extract_failed_line(code: str, exc: Exception) -> dict | None:
    """Parse the traceback to find the failed line in user code.

    Returns {"line": int, "text": str} or None.
    """
    tb_text = traceback.format_exc()
    # Look for lines like: File "<string>", line 3
    match = re.search(r'File "<string>", line (\d+)', tb_text)
    if match:
        lineno = int(match.group(1))
        lines = code.splitlines()
        if 1 <= lineno <= len(lines):
            return {"line": lineno, "text": lines[lineno - 1]}
    return None


def _suggest_fix(exc: Exception) -> str | None:
    """Return a short suggestion based on common error patterns."""
    msg = str(exc)
    exc_type = type(exc).__name__

    if exc_type == "NameError":
        return "Did you mean to use bpy.data.X or mathutils.X? Only bpy, mathutils, bmesh, math are available."
    if exc_type == "AttributeError":
        return "Check bpy API docs for the correct attribute name for your Blender version."
    if exc_type == "TypeError":
        if "argument" in msg or "positional" in msg:
            return "Check the function signature — wrong number or type of arguments."
        return "Check the types of values you are passing."
    if exc_type == "KeyError":
        return "Available keys can be found via bpy.data.*.keys() or collection.keys()."
    if exc_type == "IndexError":
        return "Check the collection length first with len() before indexing."
    if exc_type == "ValueError":
        return "Check that the value is in the expected range or format."
    if exc_type == "RuntimeError":
        return "This may be a Blender context issue — ensure the correct context/mode is active."

    return None


def exec_python(args: dict) -> dict:
    """Execute validated Python code in a restricted environment.

    Args:
        args: {
            "code": str - Python source code to execute
            "timeout": float - max execution time (default 10, max 30)
        }
    """
    code = args.get("code")
    if not code:
        raise ValueError("code is required")

    timeout = args.get("timeout", 10.0)
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ValueError("timeout must be a positive number")
    if timeout > MAX_TIMEOUT:
        raise ValueError(f"timeout must not exceed {MAX_TIMEOUT}")

    # Step 1: AST validation — last line of defense
    valid, reason = validate_python(code)
    if not valid:
        raise ValueError(f"Code validation failed: {reason}")

    # Step 2: Push undo checkpoint
    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:exec.python:{cmd_id}")

    # Step 3: Prepare restricted globals — allow safe builtins only.
    # The AST validator already blocks dangerous calls (eval, exec, open, etc.)
    # but we also remove them from builtins as defence-in-depth.
    import builtins as _builtins
    _denied = {
        "eval", "exec", "compile", "open", "getattr", "setattr",
        "delattr", "globals", "locals", "vars", "dir", "type",
        "__import__", "input", "breakpoint", "memoryview",
        "exit", "quit",
    }
    _safe_builtins = {
        k: v for k, v in _builtins.__dict__.items()
        if not k.startswith("_") and k not in _denied
    }
    restricted_globals = {
        "bpy": bpy,
        "mathutils": __import__("mathutils"),
        "bmesh": __import__("bmesh"),
        "math": __import__("math"),
        "__builtins__": _safe_builtins,
    }

    # Step 4: Execute
    try:
        exec(code, restricted_globals, {})
    except Exception as e:
        return {
            "executed": False,
            "error": str(e),
            "error_type": type(e).__name__,
            "traceback": traceback.format_exc(),
            "failed_line": _extract_failed_line(code, e),
            "suggestion": _suggest_fix(e),
        }

    # Step 5: Return success
    return {
        "executed": True,
        "lines": len(code.splitlines()),
    }


register_capability("exec.python", exec_python)
