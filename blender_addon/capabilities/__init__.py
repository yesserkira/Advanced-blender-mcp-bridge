"""Capability registry. Modules register ops via register_capability()."""

from typing import Callable

OP_REGISTRY: dict[str, Callable] = {}


def register_capability(op: str, fn: Callable):
    OP_REGISTRY[op] = fn


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
    from . import checkpoint  # noqa: F401  checkpoint.create / list / restore
    from . import snapshot    # noqa: F401  scene.snapshot
    from . import geonodes    # noqa: F401  geonodes.* (v2.2)
    from . import geonodes_presets  # noqa: F401  geonodes.list_presets / get_preset
    from . import rename      # noqa: F401  rename (v2.4)
    from . import scene_context  # noqa: F401  scene.context (v2.4)
    from . import spatial     # noqa: F401  spatial helpers (v2.4)
    from . import selection   # noqa: F401  select / deselect_all / set_active (v2.5)
    from . import object_ops  # noqa: F401  duplicate_object / set_visibility / set_parent (v2.5)
    from . import collections  # noqa: F401  collection management (v2.5)
    # ---- Tier-1 capability batch (v3.0) -----------------------------------
    from . import datablocks    # noqa: F401  create_light/camera/text/curve/empty/armature/image
    from . import mode          # noqa: F401  set_mode (atomic mode switch with validation)
    from . import constraints   # noqa: F401  add_constraint / remove_constraint / list_constraints
    from . import vertex_groups # noqa: F401  vertex group create/remove/list/set_weights
    from . import shape_keys    # noqa: F401  add/remove/set/list shape keys
    from . import mesh_edit     # noqa: F401  bmesh DSL (mesh_edit) + mesh_read
