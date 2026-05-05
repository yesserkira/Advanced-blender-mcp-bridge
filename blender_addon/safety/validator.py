"""AST-based Python code validator for execute_python.

v2.0: 'safe' mode keeps a strict allow-list of modules that cannot escape
the Blender process; 'trusted' mode skips this validator entirely (auth
token still required). The user controls the mode in add-on preferences.

Truly dangerous primitives (process/network/filesystem-escape) remain
denied even in 'safe' mode. Modules that are useful to AI-generated
Blender scripts (pathlib, io, json, re, colorsys, etc.) are now allowed
because they cannot escape the Blender process on their own.
"""

import ast

# Modules that MUST be denied in safe mode — process/IO/network escape.
DENIED_MODULES = frozenset({
    "os", "sys", "subprocess", "socket", "ctypes", "importlib",
    "builtins", "shutil", "signal", "multiprocessing",
    "threading", "http", "urllib", "requests", "asyncio",
    "select", "selectors", "ssl", "ftplib", "telnetlib",
    "smtplib", "poplib", "imaplib", "nntplib", "xmlrpc",
    "webbrowser", "platform", "pwd", "grp", "winreg",
})

# Built-in function names denied at AST level (also stripped from globals).
DENIED_CALLS = frozenset({
    "eval", "exec", "compile", "__import__", "input", "breakpoint", "open",
})

# Allow-list of stdlib modules useful inside Blender scripts.
ALLOWED_MODULES = frozenset({
    # Blender core
    "bpy", "mathutils", "bmesh", "gpu", "blf", "bgl", "aud",
    # Math / data
    "math", "cmath", "statistics", "random", "decimal", "fractions",
    "numbers", "colorsys",
    # Containers / functional
    "collections", "itertools", "functools", "operator", "heapq",
    "bisect", "array", "queue", "copy", "weakref",
    # Strings / encoding / serialization
    "string", "re", "textwrap", "unicodedata", "codecs",
    "json", "base64", "binascii", "struct",
    # Filesystem (read/write through Blender's path-jail; no shell escape)
    "pathlib", "io", "tempfile", "glob", "fnmatch", "csv",
    # Time
    "time", "datetime", "calendar",
    # Typing / introspection / data classes
    "typing", "dataclasses", "enum", "types", "abc",
    # Hashing / UUID
    "hashlib", "uuid", "secrets",
    # Compression
    "zlib", "gzip", "bz2", "lzma", "zipfile", "tarfile",
    # XML / HTML (parse only — no requests)
    "html", "xml",
})


def validate_python(code: str, mode: str = "safe") -> tuple[bool, str | None]:
    """Validate Python source code for safety.

    Args:
        code: Python source to validate.
        mode: "safe" (default) runs all checks; "trusted" skips validation
              and only verifies the code parses.

    Returns:
        (True, None) if the code passes all checks.
        (False, reason) if the code is rejected.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return (False, f"Syntax error: {e}")

    if mode == "trusted":
        return (True, None)

    for node in ast.walk(tree):
        # Imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                module_root = alias.name.split(".")[0]
                if module_root in DENIED_MODULES:
                    return (False, f"Import of '{alias.name}' is denied")
                if module_root not in ALLOWED_MODULES:
                    return (False, f"Import of '{alias.name}' is not allowed in safe mode")

        elif isinstance(node, ast.ImportFrom):
            if node.module:
                module_root = node.module.split(".")[0]
                if module_root in DENIED_MODULES:
                    return (False, f"Import from '{node.module}' is denied")
                if module_root not in ALLOWED_MODULES:
                    return (False, f"Import from '{node.module}' is not allowed in safe mode")

        # Block dunder attribute escape (object.__class__.__bases__[0].__subclasses__())
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__") and node.attr.endswith("__"):
                # Allow harmless dunders that are commonly read in user code.
                _DUNDER_ALLOW = {"__name__", "__doc__", "__file__", "__module__"}
                if node.attr not in _DUNDER_ALLOW:
                    return (False, f"Access to dunder attribute '{node.attr}' is denied")

        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in DENIED_CALLS:
                return (False, f"Call to '{func.id}()' is denied")
            if isinstance(func, ast.Attribute) and func.attr in DENIED_CALLS:
                return (False, f"Call to '.{func.attr}()' is denied")

    return (True, None)
