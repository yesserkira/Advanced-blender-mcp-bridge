"""Phase 1 — render transport contract tests.

Two layers:

1. **Server-tool surface** (uses the WS+FakeBlenderServer fixture): asserts
   that ``transport`` is forwarded to the add-on op and the response shape
   differs as documented (``image_base64`` vs ``image_path``).

2. **Add-on helper** (imports ``blender_addon.capabilities.render`` directly
   with ``bpy`` stubbed): exercises the real ``_emit_image`` and
   ``gc_render_cache`` logic — atomic write, sha256-keyed dedupe, cache cap.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import os
import sys
import types
from pathlib import Path

import pytest

os.environ.setdefault("BLENDER_MCP_TOKEN", "test")
os.environ.setdefault("BLENDER_MCP_URL", "ws://127.0.0.1:19876")

from blender_mcp import server  # noqa: E402


# ---------------------------------------------------------------------------
# Layer 1 — server tool surface, through FakeBlenderServer
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_singletons(monkeypatch, fake_blender):
    monkeypatch.setenv("BLENDER_MCP_TOKEN", "test")
    monkeypatch.setenv(
        "BLENDER_MCP_URL", f"ws://{fake_blender.host}:{fake_blender.port}",
    )
    server._bl = None
    server._policy = None
    yield
    if server._bl is not None:
        try:
            import asyncio
            asyncio.get_event_loop().run_until_complete(server._bl.close())
        except Exception:
            pass
        server._bl = None
    server._policy = None


@pytest.mark.asyncio
async def test_viewport_screenshot_default_is_base64():
    out = await server.viewport_screenshot(width=128, height=128)
    assert "image_base64" in out
    assert "image_path" not in out
    assert out["mime"] == "image/png"


@pytest.mark.asyncio
async def test_viewport_screenshot_file_returns_path():
    out = await server.viewport_screenshot(
        width=128, height=128, transport="file",
    )
    assert "image_path" in out
    assert "image_base64" not in out
    assert out["image_sha256"]


@pytest.mark.asyncio
async def test_render_region_honors_transport():
    out = await server.render_region(
        x=0, y=0, w=64, h=64, transport="file",
    )
    assert "image_path" in out
    assert "image_base64" not in out


@pytest.mark.asyncio
async def test_bake_preview_honors_transport():
    out = await server.bake_preview(
        material="Mat", w=64, h=64, transport="file",
    )
    assert "image_path" in out
    assert "image_base64" not in out


@pytest.mark.asyncio
async def test_invalid_transport_rejected():
    with pytest.raises(ValueError, match="transport"):
        await server.viewport_screenshot(transport="rest")


# ---------------------------------------------------------------------------
# Layer 2 — add-on helper, with bpy stubbed
# ---------------------------------------------------------------------------


@pytest.fixture
def render_module(monkeypatch, tmp_path):
    """Import blender_addon.capabilities.render with bpy + register stubbed.

    Redirects %LOCALAPPDATA% to ``tmp_path`` so the cache lives in a
    test-scoped directory.
    """
    bpy_stub = types.ModuleType("bpy")
    monkeypatch.setitem(sys.modules, "bpy", bpy_stub)

    pkg_stub = types.ModuleType("blender_addon")
    pkg_caps_stub = types.ModuleType("blender_addon.capabilities")
    pkg_caps_stub.register_capability = lambda name, fn: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "blender_addon", pkg_stub)
    monkeypatch.setitem(sys.modules, "blender_addon.capabilities", pkg_caps_stub)

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    src = (
        Path(__file__).resolve().parent.parent.parent
        / "blender_addon" / "capabilities" / "render.py"
    )
    spec = importlib.util.spec_from_file_location(
        "blender_addon.capabilities.render", src,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # Make the relative ``from . import register_capability`` resolve to the
    # stub package we already inserted into sys.modules above.
    sys.modules["blender_addon.capabilities.render"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_emit_image_base64_mode(render_module):
    png = b"\x89PNG\r\n\x1a\nfake-pixels"
    out = render_module._emit_image(png, "base64", {"width": 32, "height": 32})
    assert out["mime"] == "image/png"
    assert out["size_bytes"] == len(png)
    assert out["image_sha256"] == hashlib.sha256(png).hexdigest()
    assert base64.b64decode(out["image_base64"]) == png
    assert "image_path" not in out


def test_emit_image_file_mode_writes_disk(render_module, tmp_path):
    png = b"\x89PNG\r\n\x1a\nfile-mode-bytes"
    out = render_module._emit_image(png, "file", {"width": 32, "height": 32})
    assert "image_base64" not in out
    p = Path(out["image_path"])
    assert p.exists()
    assert p.read_bytes() == png
    assert p.parent == tmp_path / "BlenderMCP" / "renders"
    assert p.name == hashlib.sha256(png).hexdigest() + ".png"


def test_emit_image_file_mode_dedupes_identical_bytes(render_module):
    png = b"identical bytes for dedupe"
    out1 = render_module._emit_image(png, "file", {"width": 1, "height": 1})
    out2 = render_module._emit_image(png, "file", {"width": 1, "height": 1})
    assert out1["image_path"] == out2["image_path"]
    p = Path(out1["image_path"])
    assert p.exists()
    assert not p.with_suffix(".png.tmp").exists()


def test_gc_render_cache_caps_to_max_files(render_module):
    paths = []
    for i in range(5):
        out = render_module._emit_image(
            f"png-bytes-{i}".encode(), "file", {"width": 1, "height": 1},
        )
        paths.append(Path(out["image_path"]))

    deleted = render_module.gc_render_cache(max_files=2)
    assert deleted == 3
    surviving = [p for p in paths if p.exists()]
    assert len(surviving) == 2


def test_gc_render_cache_handles_empty_dir(render_module):
    n = render_module.gc_render_cache()
    assert n == 0
