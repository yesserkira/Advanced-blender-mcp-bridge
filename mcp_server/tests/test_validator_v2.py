"""Unit tests for the v2.0 AST validator (no Blender required).

These import only `safety/validator.py` from the add-on package; bpy is not
needed since the validator uses only `ast`.
"""

import importlib
import importlib.util
import pathlib
import sys

import pytest

# Load the validator module directly without importing the full add-on
# (which would try to import bpy).
_validator_path = pathlib.Path(__file__).resolve().parents[2] / "blender_addon" / "safety" / "validator.py"
spec = importlib.util.spec_from_file_location("_v2_validator", _validator_path)
validator = importlib.util.module_from_spec(spec)
sys.modules["_v2_validator"] = validator
spec.loader.exec_module(validator)


@pytest.mark.parametrize("code", [
    "x = 1 + 2",
    "import bpy\nimport mathutils",
    "import json\nimport pathlib\nimport re",
    "import collections, itertools, functools",
    "from pathlib import Path\np = Path('.')",
    "import colorsys\nh, s, v = colorsys.rgb_to_hsv(1, 0, 0)",
    "for i in range(10):\n    print(i)",
    "result = [x*2 for x in range(5)]",
])
def test_safe_mode_accepts(code):
    ok, reason = validator.validate_python(code, mode="safe")
    assert ok, reason


@pytest.mark.parametrize("code", [
    "import os",
    "import sys",
    "import subprocess",
    "import socket",
    "import ctypes",
    "from os import path",
    "eval('1+1')",
    "exec('x=1')",
    "compile('x', '<s>', 'exec')",
    "__import__('os')",
    "x.__class__.__bases__",
    "open('/etc/passwd').read()",
])
def test_safe_mode_rejects(code):
    ok, reason = validator.validate_python(code, mode="safe")
    assert not ok, f"should reject: {code}"


def test_trusted_mode_accepts_anything_parseable():
    ok, _ = validator.validate_python("import os\nos.system('echo hi')", mode="trusted")
    assert ok is True


def test_trusted_mode_still_rejects_syntax_errors():
    ok, _ = validator.validate_python("def +", mode="trusted")
    assert ok is False


def test_dunder_name_allowed():
    ok, _ = validator.validate_python("name = __name__", mode="safe")
    assert ok is True
