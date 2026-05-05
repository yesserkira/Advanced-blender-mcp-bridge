"""Test the AST validator directly — no fake server needed.

This is a SECURITY-CRITICAL test suite. Every case here maps to a
real attack vector from docs/SECURITY.md.
"""

import sys
import os

# Add the project root so we can import the validator directly
sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "..", "blender_addon"),
)

from safety.validator import validate_python


# ---- MUST PASS (safe code) ----

class TestValidCodeAccepted:

    def test_bpy_ops_call(self):
        ok, reason = validate_python("bpy.ops.mesh.primitive_cube_add()")
        assert ok is True, f"Should pass but got: {reason}"

    def test_import_bpy(self):
        ok, reason = validate_python("import bpy")
        assert ok is True, f"Should pass but got: {reason}"

    def test_simple_expression(self):
        ok, reason = validate_python("x = 1 + 2")
        assert ok is True, f"Should pass but got: {reason}"

    def test_bpy_data_access(self):
        ok, reason = validate_python("bpy.data.objects['Cube'].location = (0,0,0)")
        assert ok is True, f"Should pass but got: {reason}"

    def test_import_mathutils(self):
        ok, reason = validate_python("import mathutils")
        assert ok is True, f"Should pass but got: {reason}"

    def test_import_bmesh(self):
        ok, reason = validate_python("import bmesh")
        assert ok is True, f"Should pass but got: {reason}"

    def test_import_math(self):
        ok, reason = validate_python("import math")
        assert ok is True, f"Should pass but got: {reason}"

    def test_from_mathutils_import(self):
        ok, reason = validate_python("from mathutils import Vector, Matrix")
        assert ok is True, f"Should pass but got: {reason}"

    def test_multiline_bpy_script(self):
        code = """
import bpy
obj = bpy.context.active_object
obj.location = (1, 2, 3)
obj.scale = (2, 2, 2)
"""
        ok, reason = validate_python(code)
        assert ok is True, f"Should pass but got: {reason}"

    def test_loop_over_objects(self):
        code = "for obj in bpy.data.objects:\n    obj.select_set(True)"
        ok, reason = validate_python(code)
        assert ok is True, f"Should pass but got: {reason}"


# ---- MUST FAIL (dangerous code) ----

class TestDangerousCodeRejected:

    def test_import_os(self):
        ok, reason = validate_python("import os")
        assert ok is False
        assert "os" in reason

    def test_import_subprocess(self):
        ok, reason = validate_python("import subprocess")
        assert ok is False
        assert "subprocess" in reason

    def test_import_sys(self):
        ok, reason = validate_python("import sys")
        assert ok is False
        assert "sys" in reason

    def test_import_socket(self):
        ok, reason = validate_python("import socket")
        assert ok is False
        assert "socket" in reason

    def test_import_ctypes(self):
        ok, reason = validate_python("import ctypes")
        assert ok is False
        assert "ctypes" in reason

    def test_import_shutil(self):
        ok, reason = validate_python("import shutil")
        assert ok is False
        assert "shutil" in reason

    def test_import_pathlib(self):
        ok, reason = validate_python("import pathlib")
        assert ok is False
        assert "pathlib" in reason

    def test_import_importlib(self):
        ok, reason = validate_python("import importlib")
        assert ok is False
        assert "importlib" in reason

    def test_import_builtins(self):
        ok, reason = validate_python("import builtins")
        assert ok is False
        assert "builtins" in reason

    def test_import_http(self):
        ok, reason = validate_python("import http")
        assert ok is False
        assert "http" in reason

    def test_import_urllib(self):
        ok, reason = validate_python("import urllib")
        assert ok is False
        assert "urllib" in reason

    def test_import_io(self):
        ok, reason = validate_python("import io")
        assert ok is False
        assert "io" in reason

    def test_import_multiprocessing(self):
        ok, reason = validate_python("import multiprocessing")
        assert ok is False
        assert "multiprocessing" in reason

    def test_import_threading(self):
        ok, reason = validate_python("import threading")
        assert ok is False
        assert "threading" in reason

    def test_import_signal(self):
        ok, reason = validate_python("import signal")
        assert ok is False
        assert "signal" in reason

    def test_from_os_import(self):
        ok, reason = validate_python("from os import system")
        assert ok is False
        assert "os" in reason

    def test_from_os_path_import(self):
        ok, reason = validate_python("from os.path import join")
        assert ok is False
        assert "os" in reason

    def test_call_eval(self):
        ok, reason = validate_python("eval('1+1')")
        assert ok is False
        assert "eval" in reason

    def test_call_exec(self):
        ok, reason = validate_python("exec('print(1)')")
        assert ok is False
        assert "exec" in reason

    def test_call_compile(self):
        ok, reason = validate_python("compile('x=1', '<>', 'exec')")
        assert ok is False
        assert "compile" in reason

    def test_call_open(self):
        ok, reason = validate_python("open('/etc/passwd')")
        assert ok is False
        assert "open" in reason

    def test_call___import__(self):
        ok, reason = validate_python("__import__('os')")
        assert ok is False
        assert "__import__" in reason

    def test_call_getattr(self):
        ok, reason = validate_python("getattr(obj, 'x')")
        assert ok is False
        assert "getattr" in reason

    def test_call_setattr(self):
        ok, reason = validate_python("setattr(obj, 'x', 1)")
        assert ok is False
        assert "setattr" in reason

    def test_call_delattr(self):
        ok, reason = validate_python("delattr(obj, 'x')")
        assert ok is False
        assert "delattr" in reason

    def test_call_globals(self):
        ok, reason = validate_python("globals()")
        assert ok is False
        assert "globals" in reason

    def test_call_locals(self):
        ok, reason = validate_python("locals()")
        assert ok is False
        assert "locals" in reason

    def test_call_vars(self):
        ok, reason = validate_python("vars()")
        assert ok is False
        assert "vars" in reason

    def test_call_dir(self):
        ok, reason = validate_python("dir()")
        assert ok is False
        assert "dir" in reason

    def test_call_type(self):
        ok, reason = validate_python("type(obj)")
        assert ok is False
        assert "type" in reason

    def test_dunder_class(self):
        ok, reason = validate_python("obj.__class__.__bases__")
        assert ok is False
        assert "dunder attribute" in reason

    def test_dunder_builtins(self):
        ok, reason = validate_python("x.__builtins__")
        assert ok is False
        assert "__builtins__" in reason

    def test_dunder_import(self):
        ok, reason = validate_python("x.__import__('os')")
        assert ok is False
        # Should be caught by either dunder check or call check
        assert ok is False

    def test_dunder_subclasses(self):
        ok, reason = validate_python("''.__class__.__subclasses__()")
        assert ok is False
        assert "dunder attribute" in reason

    def test_import_unknown_module(self):
        """Non-allowed modules should be rejected too."""
        ok, reason = validate_python("import pickle")
        assert ok is False
        assert "pickle" in reason


# ---- Syntax error handling ----

class TestSyntaxErrors:

    def test_syntax_error(self):
        ok, reason = validate_python("def foo(")
        assert ok is False
        assert "Syntax error" in reason

    def test_empty_code(self):
        ok, reason = validate_python("")
        assert ok is True  # empty code is syntactically valid

    def test_comment_only(self):
        ok, reason = validate_python("# just a comment")
        assert ok is True
