"""Capability registry. Modules register ops via register_capability()."""

from typing import Callable

OP_REGISTRY: dict[str, Callable] = {}


def register_capability(op: str, fn: Callable):
    OP_REGISTRY[op] = fn


def _register_builtins():
    register_capability("ping", lambda args: "pong")


_register_builtins()


def load_all():
    """Import all capability modules to populate the registry."""
    from . import scene       # noqa: F401  object.transform / delete
    from . import mesh        # noqa: F401  mesh.create_primitive
    from . import query       # noqa: F401  query / list / describe_api / audit.read
    from . import properties  # noqa: F401  set_property / get_property
    from . import operator    # noqa: F401  call_operator
    from . import modifier    # noqa: F401  add_modifier / remove_modifier
    from . import nodes       # noqa: F401  build_nodes / assign_material
    from . import composer    # noqa: F401  create_objects / transaction / apply_to_selection
    from . import animation   # noqa: F401  set_keyframe
    from . import render      # noqa: F401  render.viewport_screenshot / region / bake_preview
    from . import assets      # noqa: F401  import_asset / link_blend / list_assets
    from . import diff        # noqa: F401  scene_diff / snapshot_clear
    from . import exec_python # noqa: F401  exec.python
