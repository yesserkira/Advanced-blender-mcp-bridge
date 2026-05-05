"""Execute Python with optional AST validation (gated capability).

v2.0:
- Honors `exec_mode` preference: "safe" runs the AST validator; "trusted"
  skips validation entirely (auth token still required).
- Sandbox builtins broadened to make AI-generated scripts ergonomic.
- A real `import` mechanism is exposed so that allowed modules (per
  `safety/validator.ALLOWED_MODULES`) can actually be imported at runtime.
"""

import builtins as _builtins
import re
import traceback

import bpy

from . import register_capability
from ..safety.validator import (
    ALLOWED_MODULES,
    DENIED_MODULES,
    validate_python,
)

MAX_TIMEOUT = 30.0


_DENIED_BUILTINS = frozenset({
    "eval", "exec", "compile", "__import__",
    "input", "breakpoint", "exit", "quit",
    "open",  # use pathlib if needed
    "globals", "vars",
})


def _build_safe_import():
    real_import = _builtins.__import__

    def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        root = name.split(".")[0]
        if root in DENIED_MODULES:
            raise ImportError(f"Import of '{name}' is denied by sandbox")
        if root not in ALLOWED_MODULES:
            raise ImportError(
                f"Import of '{name}' is not allowed in safe mode "
                f"(switch to 'trusted' mode or use one of the allowed roots)"
            )
        return real_import(name, globals, locals, fromlist, level)

    return _safe_import


def _build_safe_builtins(mode: str) -> dict:
    if mode == "trusted":
        return _builtins.__dict__
    safe = {
        k: v
        for k, v in _builtins.__dict__.items()
        if not k.startswith("_") and k not in _DENIED_BUILTINS
    }
    safe["__import__"] = _build_safe_import()
    safe["__name__"] = "<sandbox>"
    return safe


def _get_exec_mode() -> str:
    try:
        addon = bpy.context.preferences.addons.get("blender_addon")
        if addon is not None:
            return getattr(addon.preferences, "exec_mode", "safe") or "safe"
    except Exception:
        pass
    return "safe"


def _extract_failed_line(code: str) -> dict | None:
    tb_text = traceback.format_exc()
    match = re.search(r'File "<sandbox>", line (\d+)', tb_text) or \
        re.search(r'File "<string>", line (\d+)', tb_text)
    if match:
        lineno = int(match.group(1))
        lines = code.splitlines()
        if 1 <= lineno <= len(lines):
            return {"line": lineno, "text": lines[lineno - 1]}
    return None


def _suggest_fix(exc: Exception) -> str | None:
    msg = str(exc)
    exc_type = type(exc).__name__
    if exc_type == "NameError":
        return "Did you forget to assign the variable, or use a wrong identifier?"
    if exc_type == "AttributeError":
        return "Check the bpy API for the correct attribute on this Blender version."
    if exc_type == "TypeError":
        if "argument" in msg or "positional" in msg:
            return "Check the function signature — wrong number or type of arguments."
        return "Check the types of values you are passing."
    if exc_type == "KeyError":
        return "Available keys: bpy.data.*.keys() / collection.keys()."
    if exc_type == "IndexError":
        return "Check the collection length first with len() before indexing."
    if exc_type == "ValueError":
        return "Check that the value is in the expected range or format."
    if exc_type == "RuntimeError":
        return "Likely a Blender context issue — ensure correct mode/area is active."
    if exc_type == "ImportError":
        return "Module is not in the sandbox allowlist; switch exec_mode to 'trusted' to import any module."
    return None


def exec_python(args: dict) -> dict:
    """Execute Python code in the configured sandbox.

    Args:
        args: {
            "code": str,
            "timeout": float (default 10, max 30),
            "mode": "safe"|"trusted"|None  (per-call override; falls back to prefs)
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

    mode = args.get("mode") or _get_exec_mode()
    if mode not in ("safe", "trusted"):
        raise ValueError("mode must be 'safe' or 'trusted'")

    valid, reason = validate_python(code, mode=mode)
    if not valid:
        raise ValueError(f"Code validation failed: {reason}")

    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:exec.python:{cmd_id}")

    safe_builtins = _build_safe_builtins(mode)
    restricted_globals = {
        "bpy": bpy,
        "mathutils": __import__("mathutils"),
        "bmesh": __import__("bmesh"),
        "math": __import__("math"),
        "__builtins__": safe_builtins,
        "__name__": "<sandbox>",
    }
    sandbox_locals: dict = {}

    try:
        compiled = _builtins.compile(code, "<sandbox>", "exec")
        # IMPORTANT: pass the same dict for both globals and locals so that
        # top-level def's see top-level vars (Python scoping rules treat the
        # two-dict form as "module body" and functions then can't see the
        # caller's locals). Using one dict makes this behave like a normal
        # module / REPL session, which is what users expect.
        _builtins.exec(compiled, restricted_globals)
        # Collect any "user" names the script defined (skip dunder/builtin keys
        # that were preset, so result_preview reflects script outputs).
        sandbox_locals = {
            k: v for k, v in restricted_globals.items()
            if k not in {"bpy", "mathutils", "bmesh", "math",
                         "__builtins__", "__name__"} and not k.startswith("__")
        }
    except Exception as e:
        return {
            "executed": False,
            "mode": mode,
            "error": str(e),
            "error_type": type(e).__name__,
            "traceback": traceback.format_exc(),
            "failed_line": _extract_failed_line(code),
            "suggestion": _suggest_fix(e),
        }

    result_preview = None
    if sandbox_locals:
        last_key = list(sandbox_locals.keys())[-1]
        try:
            v = sandbox_locals[last_key]
            result_preview = {
                "name": last_key,
                "type": type(v).__name__,
                "repr": repr(v)[:300],
            }
        except Exception:
            pass

    return {
        "executed": True,
        "mode": mode,
        "lines": len(code.splitlines()),
        "result_preview": result_preview,
    }


register_capability("exec.python", exec_python)
