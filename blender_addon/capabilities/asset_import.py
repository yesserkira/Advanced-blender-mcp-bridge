"""Asset import capability with path-jail validation."""

from pathlib import Path

import bpy

from . import register_capability

SUPPORTED_FORMATS = {
    ".fbx": "import_scene.fbx",
    ".obj": "wm.obj_import",
    ".glb": "import_scene.gltf",
    ".gltf": "import_scene.gltf",
    ".stl": "import_mesh.stl",
}


def import_asset(args: dict) -> dict:
    """Import a 3D asset file into Blender.

    Args:
        args: {
            "path": str - path to the asset file (required)
            "format": str|None - format override (auto-detected from extension)
            "location": [float, float, float] - optional position
            "scale": float - scale factor (default 1.0)
            "_allowed_roots": [str] - injected by MCP server for path-jail
        }
    """
    path_str = args.get("path")
    if not path_str:
        raise ValueError("'path' is required")

    resolved = Path(path_str).resolve()

    # Validate file exists
    if not resolved.is_file():
        raise ValueError(f"File not found: {resolved}")

    # Determine format
    ext = args.get("format")
    if ext:
        if not ext.startswith("."):
            ext = f".{ext}"
        ext = ext.lower()
    else:
        ext = resolved.suffix.lower()

    if ext not in SUPPORTED_FORMATS:
        raise ValueError(
            f"Unsupported format: {ext}. "
            f"Supported: {', '.join(sorted(SUPPORTED_FORMATS.keys()))}"
        )

    # Path-jail: check against allowed roots
    allowed_roots = args.get("_allowed_roots", [])
    if allowed_roots:
        resolved_str = str(resolved)
        if not any(resolved_str.startswith(str(Path(root).resolve())) for root in allowed_roots):
            raise ValueError(
                f"Path '{resolved}' is outside allowed roots: "
                f"{', '.join(allowed_roots)}"
            )

    location = args.get("location")
    scale = args.get("scale", 1.0)

    # Push undo checkpoint
    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:asset.import:{cmd_id}")

    # Record objects before import
    before = set(bpy.data.objects.keys())

    # Call the appropriate import operator
    op_path = SUPPORTED_FORMATS[ext]
    parts = op_path.split(".")
    op_module = getattr(bpy.ops, parts[0])
    op_fn = getattr(op_module, parts[1])
    op_fn(filepath=str(resolved))

    # Find new objects
    after = set(bpy.data.objects.keys())
    new_objects = list(after - before)

    # Apply location and scale to imported objects
    for obj_name in new_objects:
        obj = bpy.data.objects.get(obj_name)
        if obj is None:
            continue
        if location and len(location) == 3:
            obj.location = tuple(location)
        if scale != 1.0:
            obj.scale = (scale, scale, scale)

    return {
        "imported_objects": new_objects,
        "format": ext,
        "path": str(resolved),
    }


register_capability("asset.import", import_asset)
