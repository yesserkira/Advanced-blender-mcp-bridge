"""Test execute_python tool through BlenderWS client."""

import pytest

from blender_mcp.blender_client import BlenderWS, BlenderError


@pytest.mark.asyncio
async def test_exec_python_success(fake_blender):
    """exec.python with valid code should return executed=True."""
    fake_blender._handlers["exec.python"] = lambda args: {
        "executed": True,
        "lines": len(args["code"].splitlines()),
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call("exec.python", {
            "code": "bpy.ops.mesh.primitive_cube_add()",
        })
        assert result["executed"] is True
        assert result["lines"] == 1
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_exec_python_failure(fake_blender):
    """exec.python with runtime error should return executed=False."""
    fake_blender._handlers["exec.python"] = lambda args: {
        "executed": False,
        "error": "NameError: name 'undefined_var' is not defined",
        "traceback": "Traceback ...",
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call("exec.python", {
            "code": "undefined_var",
        })
        assert result["executed"] is False
        assert "error" in result
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_exec_python_with_timeout(fake_blender):
    """exec.python should accept timeout parameter."""
    fake_blender._handlers["exec.python"] = lambda args: {
        "executed": True,
        "lines": 1,
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call("exec.python", {
            "code": "x = 1",
            "timeout": 5.0,
        })
        assert result["executed"] is True
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_exec_python_unknown_op(fake_blender):
    """Calling exec.python without a handler should return NOT_FOUND."""
    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        with pytest.raises(BlenderError) as exc_info:
            await client.call("exec.python", {"code": "x = 1"})
        assert exc_info.value.code == "NOT_FOUND"
    finally:
        await client.close()
