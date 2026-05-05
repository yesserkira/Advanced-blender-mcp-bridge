"""Visual feedback: viewport screenshot, render region, bake preview."""

from __future__ import annotations

import base64
import os
import tempfile

import bpy

from . import register_capability

MAX_RESOLUTION = 4096


def _read_png_b64(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def viewport_screenshot(args: dict, progress_callback=None) -> dict:
    """Capture the viewport via OpenGL render and return PNG bytes (base64).

    Args:
        args: {
            "w": int (default 1024, max 4096),
            "h": int (default 1024, max 4096),
            "view_camera": str | None (camera name to render from),
            "shading": "WIREFRAME"|"SOLID"|"MATERIAL"|"RENDERED" | None,
            "show_overlays": bool (default False),
        }
    """
    w = int(args.get("w", 1024))
    h = int(args.get("h", 1024))
    if w < 1 or w > MAX_RESOLUTION or h < 1 or h > MAX_RESOLUTION:
        raise ValueError(f"w/h must be 1..{MAX_RESOLUTION}")

    scene = bpy.context.scene
    saved = {
        "x": scene.render.resolution_x,
        "y": scene.render.resolution_y,
        "pct": scene.render.resolution_percentage,
        "fmt": scene.render.image_settings.file_format,
        "path": scene.render.filepath,
        "camera": scene.camera,
    }

    view_cam_name = args.get("view_camera")
    if view_cam_name:
        cam = bpy.data.objects.get(view_cam_name)
        if cam is None or cam.type != "CAMERA":
            raise ValueError(f"camera '{view_cam_name}' not found")
        scene.camera = cam

    shading = args.get("shading")
    show_overlays = bool(args.get("show_overlays", False))

    saved_shading = None
    saved_overlays = None
    ov = _find_view3d_context()
    space = ov["space_data"] if ov else None
    if space is not None:
        if shading is not None:
            saved_shading = space.shading.type
            space.shading.type = shading
        saved_overlays = space.overlay.show_overlays
        space.overlay.show_overlays = show_overlays

    try:
        scene.render.resolution_x = w
        scene.render.resolution_y = h
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format = "PNG"

        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp_path = tmp.name
        tmp.close()
        scene.render.filepath = tmp_path

        if progress_callback:
            progress_callback(20, "rendering viewport")

        ov = _find_view3d_context()
        if ov is None:
            # No VIEW_3D editor open: fall back to a scene-camera OpenGL render
            # which doesn't require a 3D editor.
            bpy.ops.render.opengl(write_still=True, view_context=False)
        else:
            with bpy.context.temp_override(**ov):
                bpy.ops.render.opengl(write_still=True, view_context=True)
        if progress_callback:
            progress_callback(80, "encoding")

        png_bytes = _read_png_b64(tmp_path)
        return {
            "image_base64": base64.b64encode(png_bytes).decode("ascii"),
            "mime": "image/png",
            "width": w,
            "height": h,
            "size_bytes": len(png_bytes),
        }
    finally:
        scene.render.resolution_x = saved["x"]
        scene.render.resolution_y = saved["y"]
        scene.render.resolution_percentage = saved["pct"]
        scene.render.image_settings.file_format = saved["fmt"]
        scene.render.filepath = saved["path"]
        scene.camera = saved["camera"]
        if space is not None:
            if saved_shading is not None:
                space.shading.type = saved_shading
            if saved_overlays is not None:
                space.overlay.show_overlays = saved_overlays
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


register_capability("render.viewport_screenshot", viewport_screenshot)


def _find_view3d_space():
    for area in bpy.context.screen.areas:
        if area.type == "VIEW_3D":
            for sp in area.spaces:
                if sp.type == "VIEW_3D":
                    return sp
    return None


def _find_view3d_context():
    """Locate (window, screen, area, region, space) for a VIEW_3D editor.

    Returns a dict suitable for bpy.context.temp_override(**kwargs).
    Returns None if no VIEW_3D area is open in any window.
    """
    wm = bpy.context.window_manager
    for window in wm.windows:
        screen = window.screen
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            region = next(
                (r for r in area.regions if r.type == "WINDOW"), None
            )
            space = next(
                (s for s in area.spaces if s.type == "VIEW_3D"), None
            )
            if region is not None and space is not None:
                return {
                    "window": window,
                    "screen": screen,
                    "area": area,
                    "region": region,
                    "space_data": space,
                }
    return None


# ---------------------------------------------------------------------------
# render_region — focused engine render of a small region
# ---------------------------------------------------------------------------


def render_region(args: dict, progress_callback=None) -> dict:
    """Render a small region of the scene with the configured engine.

    Args:
        args: {
            "x": int, "y": int, "w": int, "h": int   (in pixels, image-space)
            "samples": int (default 32),
            "engine": "CYCLES" | "BLENDER_EEVEE" | "BLENDER_EEVEE_NEXT" | None,
            "camera": str | None,
        }
    """
    x = int(args.get("x", 0))
    y = int(args.get("y", 0))
    w = int(args.get("w", 256))
    h = int(args.get("h", 256))
    samples = int(args.get("samples", 32))
    engine = args.get("engine")
    cam_name = args.get("camera")

    if w < 1 or h < 1 or w > MAX_RESOLUTION or h > MAX_RESOLUTION:
        raise ValueError("w/h out of range")

    scene = bpy.context.scene
    render = scene.render
    saved = {
        "x": render.resolution_x, "y": render.resolution_y,
        "pct": render.resolution_percentage,
        "use_border": render.use_border,
        "use_crop": render.use_crop_to_border,
        "min_x": render.border_min_x, "min_y": render.border_min_y,
        "max_x": render.border_max_x, "max_y": render.border_max_y,
        "engine": render.engine,
        "fmt": render.image_settings.file_format,
        "path": render.filepath,
        "samples_cycles": getattr(scene.cycles, "samples", None) if hasattr(scene, "cycles") else None,
        "samples_eevee": getattr(scene.eevee, "taa_render_samples", None) if hasattr(scene, "eevee") else None,
        "camera": scene.camera,
    }

    if cam_name:
        cam = bpy.data.objects.get(cam_name)
        if cam is None or cam.type != "CAMERA":
            raise ValueError(f"camera '{cam_name}' not found")
        scene.camera = cam

    # Use full output resolution as the canvas; border defines what is rendered
    full_w = max(saved["x"], x + w)
    full_h = max(saved["y"], y + h)

    try:
        if engine:
            render.engine = engine
        render.resolution_x = full_w
        render.resolution_y = full_h
        render.resolution_percentage = 100
        render.use_border = True
        render.use_crop_to_border = True
        render.border_min_x = x / full_w
        render.border_min_y = 1.0 - (y + h) / full_h
        render.border_max_x = (x + w) / full_w
        render.border_max_y = 1.0 - y / full_h

        if render.engine == "CYCLES" and hasattr(scene, "cycles"):
            scene.cycles.samples = samples
        elif "EEVEE" in render.engine and hasattr(scene, "eevee"):
            scene.eevee.taa_render_samples = samples

        render.image_settings.file_format = "PNG"
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp_path = tmp.name
        tmp.close()
        render.filepath = tmp_path

        if progress_callback:
            progress_callback(10, "rendering region")
        bpy.ops.render.render(write_still=True)
        if progress_callback:
            progress_callback(90, "encoding")

        png_bytes = _read_png_b64(tmp_path)
        return {
            "image_base64": base64.b64encode(png_bytes).decode("ascii"),
            "mime": "image/png",
            "x": x, "y": y, "w": w, "h": h,
            "samples": samples,
            "engine": render.engine,
            "size_bytes": len(png_bytes),
        }
    finally:
        render.resolution_x = saved["x"]
        render.resolution_y = saved["y"]
        render.resolution_percentage = saved["pct"]
        render.use_border = saved["use_border"]
        render.use_crop_to_border = saved["use_crop"]
        render.border_min_x = saved["min_x"]
        render.border_min_y = saved["min_y"]
        render.border_max_x = saved["max_x"]
        render.border_max_y = saved["max_y"]
        render.engine = saved["engine"]
        render.image_settings.file_format = saved["fmt"]
        render.filepath = saved["path"]
        scene.camera = saved["camera"]
        if saved["samples_cycles"] is not None and hasattr(scene, "cycles"):
            scene.cycles.samples = saved["samples_cycles"]
        if saved["samples_eevee"] is not None and hasattr(scene, "eevee"):
            scene.eevee.taa_render_samples = saved["samples_eevee"]
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


register_capability("render.region", render_region)


# ---------------------------------------------------------------------------
# bake_preview — render a material onto a temporary plane
# ---------------------------------------------------------------------------


def bake_preview(args: dict) -> dict:
    """Render a quick preview of a material on a temporary plane.

    Args:
        args: {"material": str, "w": int (default 256), "h": int (default 256)}
    """
    mat_name = args.get("material")
    w = int(args.get("w", 256))
    h = int(args.get("h", 256))
    if w < 16 or w > 1024 or h < 16 or h > 1024:
        raise ValueError("w/h must be 16..1024")
    mat = bpy.data.materials.get(mat_name)
    if mat is None:
        raise ValueError(f"material '{mat_name}' not found")

    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:bake_preview:{cmd_id}")

    # Build a hidden mini-scene
    preview_scene = bpy.data.scenes.new(f"_mat_preview_{cmd_id}")
    saved_scene = bpy.context.window.scene
    bpy.context.window.scene = preview_scene
    try:
        bpy.ops.mesh.primitive_plane_add(size=2, location=(0, 0, 0))
        plane = bpy.context.active_object
        plane.data.materials.append(mat)

        # Light + camera
        light_data = bpy.data.lights.new("PreviewSun", "SUN")
        light_data.energy = 3.0
        light_obj = bpy.data.objects.new("PreviewSun", light_data)
        light_obj.location = (2, -2, 4)
        light_obj.rotation_euler = (0.7, 0.0, 0.7)
        preview_scene.collection.objects.link(light_obj)

        cam_data = bpy.data.cameras.new("PreviewCam")
        cam_data.lens = 50
        cam_obj = bpy.data.objects.new("PreviewCam", cam_data)
        cam_obj.location = (0, 0, 3)
        cam_obj.rotation_euler = (0, 0, 0)
        preview_scene.collection.objects.link(cam_obj)
        preview_scene.camera = cam_obj

        preview_scene.render.resolution_x = w
        preview_scene.render.resolution_y = h
        preview_scene.render.resolution_percentage = 100
        preview_scene.render.image_settings.file_format = "PNG"
        if hasattr(preview_scene, "eevee"):
            preview_scene.eevee.taa_render_samples = 16
        # Prefer EEVEE for speed if available
        for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
            try:
                preview_scene.render.engine = engine
                break
            except Exception:
                continue

        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp_path = tmp.name
        tmp.close()
        preview_scene.render.filepath = tmp_path

        bpy.ops.render.render(write_still=True)
        png_bytes = _read_png_b64(tmp_path)

        return {
            "image_base64": base64.b64encode(png_bytes).decode("ascii"),
            "mime": "image/png",
            "material": mat.name,
            "width": w,
            "height": h,
        }
    finally:
        bpy.context.window.scene = saved_scene
        try:
            bpy.data.scenes.remove(preview_scene, do_unlink=True)
        except Exception:
            pass
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


register_capability("render.bake_preview", bake_preview)
