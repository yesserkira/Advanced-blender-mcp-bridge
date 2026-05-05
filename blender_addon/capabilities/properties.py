"""Generic RNA property setter / getter.

Accepts a Python-style attribute path rooted in `bpy.data` or `bpy.context`,
parses it via AST (no arbitrary expressions allowed), and assigns the value.

Examples:
    set_property("bpy.data.scenes['Scene'].cycles.samples", 256)
    set_property("bpy.data.objects['Cube'].location", [1, 0, 0])
    set_property("bpy.context.scene.render.resolution_x", 1920)
"""

from __future__ import annotations

import ast

import bpy

from . import register_capability


_ROOTS = {"bpy"}


class _PathError(ValueError):
    pass


def _eval_path(node: ast.AST):
    """Walk a restricted AST node and return the current Python object.

    Allowed forms:
        bpy
        <prev>.attr
        <prev>['name'] / <prev>[123]
        <prev>.attr['name']
    """
    if isinstance(node, ast.Name):
        if node.id not in _ROOTS:
            raise _PathError(f"Only {sorted(_ROOTS)} roots are allowed (got '{node.id}')")
        return bpy
    if isinstance(node, ast.Attribute):
        target = _eval_path(node.value)
        return getattr(target, node.attr)
    if isinstance(node, ast.Subscript):
        target = _eval_path(node.value)
        slice_node = node.slice
        if isinstance(slice_node, ast.Constant):
            return target[slice_node.value]
        raise _PathError("Subscript must be a string or int constant")
    raise _PathError(f"Disallowed AST node: {type(node).__name__}")


def _split_assign(path: str) -> tuple[ast.AST, str | None, ast.AST | None]:
    """Parse 'a.b.c' or 'a.b[x]' returning (parent_node, attr_or_None, sub_or_None)."""
    expr = ast.parse(path, mode="eval").body
    if isinstance(expr, ast.Attribute):
        return expr.value, expr.attr, None
    if isinstance(expr, ast.Subscript):
        return expr.value, None, expr.slice
    raise _PathError("path must end with .attr or [key]")


def _coerce_for_target(parent, attr, value):
    """Coerce value if assigning to a vector-like RNA property."""
    try:
        cur = getattr(parent, attr)
    except Exception:
        return value
    cls_name = type(cur).__name__
    if cls_name in {"Vector", "Color", "Euler", "Quaternion"} and isinstance(value, (list, tuple)):
        try:
            return type(cur)(value)
        except Exception:
            return tuple(value)
    if cls_name == "bpy_prop_array" and isinstance(value, (list, tuple)):
        return tuple(value)
    return value


def set_property(args: dict) -> dict:
    """Set an arbitrary RNA property by Python-style path.

    Args:
        args: {"path": str, "value": Any}
    """
    path = args.get("path")
    if not path:
        raise ValueError("'path' is required")
    if "value" not in args:
        raise ValueError("'value' is required")
    value = args["value"]

    try:
        parent_node, attr, sub = _split_assign(path)
        parent = _eval_path(parent_node)
    except SyntaxError as e:
        raise ValueError(f"Invalid path syntax: {e}")
    except _PathError as e:
        raise ValueError(str(e))

    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:set_property:{cmd_id}")

    if attr is not None:
        coerced = _coerce_for_target(parent, attr, value)
        setattr(parent, attr, coerced)
    else:
        if not isinstance(sub, ast.Constant):
            raise ValueError("subscript key must be a constant")
        parent[sub.value] = value

    # Read back for confirmation
    try:
        if attr is not None:
            new_val = getattr(parent, attr)
        else:
            new_val = parent[sub.value]
        from .query import to_jsonable
        return {"path": path, "value": to_jsonable(new_val)}
    except Exception:
        return {"path": path, "value": "<set>"}


register_capability("set_property", set_property)


def get_property(args: dict) -> dict:
    """Read an arbitrary RNA property.

    Args:
        args: {"path": str}
    """
    path = args.get("path")
    if not path:
        raise ValueError("'path' is required")
    try:
        expr = ast.parse(path, mode="eval").body
        value = _eval_path(expr)
    except _PathError as e:
        raise ValueError(str(e))
    from .query import to_jsonable
    return {"path": path, "value": to_jsonable(value)}


register_capability("get_property", get_property)
