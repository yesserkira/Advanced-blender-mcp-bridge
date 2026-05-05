"""AST-based Python code validator for execute_python.

This is the LAST LINE OF DEFENSE against malicious code execution.
See docs/SECURITY.md §Rule 4 for the full threat model.
"""

import ast

# Modules that MUST be denied — any import of these is rejected.
DENIED_MODULES = frozenset({
    "os", "sys", "subprocess", "socket", "ctypes", "importlib",
    "builtins", "pathlib", "shutil", "signal", "multiprocessing",
    "threading", "http", "urllib", "requests", "io",
})

# Built-in function names that MUST be denied when called.
DENIED_CALLS = frozenset({
    "eval", "exec", "compile", "open", "getattr", "setattr",
    "delattr", "globals", "locals", "vars", "dir", "type",
    "__import__", "input", "breakpoint", "memoryview",
})

# Modules that are explicitly allowed to be imported.
ALLOWED_MODULES = frozenset({
    "bpy", "mathutils", "bmesh", "math",
})


def validate_python(code: str) -> tuple[bool, str | None]:
    """Validate Python source code for safety.

    Returns:
        (True, None) if the code passes all checks.
        (False, reason) if the code is rejected.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return (False, f"Syntax error: {e}")

    for node in ast.walk(tree):
        # Check imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                module_root = alias.name.split(".")[0]
                if module_root in DENIED_MODULES:
                    return (False, f"Import of '{alias.name}' is denied")
                if module_root not in ALLOWED_MODULES:
                    return (False, f"Import of '{alias.name}' is not allowed")

        elif isinstance(node, ast.ImportFrom):
            if node.module:
                module_root = node.module.split(".")[0]
                if module_root in DENIED_MODULES:
                    return (False, f"Import from '{node.module}' is denied")
                if module_root not in ALLOWED_MODULES:
                    return (False, f"Import from '{node.module}' is not allowed")

        # Check __dunder__ attribute access
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__") and node.attr.endswith("__"):
                return (
                    False,
                    f"Access to dunder attribute '{node.attr}' is denied",
                )

        # Check denied function calls
        elif isinstance(node, ast.Call):
            func = node.func
            # Direct call: eval(...), exec(...), etc.
            if isinstance(func, ast.Name) and func.id in DENIED_CALLS:
                return (False, f"Call to '{func.id}()' is denied")
            # Attribute call: obj.__import__(...) etc.
            if isinstance(func, ast.Attribute) and func.attr in DENIED_CALLS:
                return (False, f"Call to '.{func.attr}()' is denied")

    return (True, None)
