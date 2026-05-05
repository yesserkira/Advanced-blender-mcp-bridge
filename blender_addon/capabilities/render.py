"""Render / viewport screenshot capability."""

import base64
import os
import tempfile

import bpy

from . import register_capability

MAX_RESOLUTION = 4096


def render_viewport_screenshot(args: dict, progress_callback=None) -> dict:
    """Capture the viewport as a PNG image and return as base64.

    Args:
        args: {
            "w": int - width in pixels (default 1024, max 4096)
            "h": int - height in pixels (default 1024, max 4096)
        }
        progress_callback: Optional callable(percent: int, message: str) -> None
            for streaming progress events.
    """
    w = args.get("w", 1024)
    h = args.get("h", 1024)

    if not isinstance(w, int) or not isinstance(h, int):
        raise ValueError("w and h must be integers")
    if w < 1 or w > MAX_RESOLUTION or h < 1 or h > MAX_RESOLUTION:
        raise ValueError(f"w and h must be between 1 and {MAX_RESOLUTION}")

    # Use opengl render to capture viewport
    # Save current render settings
    scene = bpy.context.scene
    old_x = scene.render.resolution_x
    old_y = scene.render.resolution_y
    old_pct = scene.render.resolution_percentage
    old_format = scene.render.image_settings.file_format
    old_path = scene.render.filepath

    try:
        scene.render.resolution_x = w
        scene.render.resolution_y = h
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format = "PNG"

        if progress_callback:
            progress_callback(10, "Setting up render")

        # Create temp file for the render
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp_path = tmp.name
        tmp.close()

        scene.render.filepath = tmp_path

        if progress_callback:
            progress_callback(50, "Rendering")

        # Render viewport (opengl)
        bpy.ops.render.opengl(write_still=True)

        if progress_callback:
            progress_callback(90, "Encoding")

        # Read and encode
        with open(tmp_path, "rb") as f:
            png_bytes = f.read()

        result = {
            "image_base64": base64.b64encode(png_bytes).decode("ascii"),
            "mime": "image/png",
            "width": w,
            "height": h,
            "size_bytes": len(png_bytes),
        }

        if progress_callback:
            progress_callback(100, "Done")

        return result
    finally:
        # Restore settings
        scene.render.resolution_x = old_x
        scene.render.resolution_y = old_y
        scene.render.resolution_percentage = old_pct
        scene.render.image_settings.file_format = old_format
        scene.render.filepath = old_path

        # Clean up temp file
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


register_capability("render.viewport_screenshot", render_viewport_screenshot)
