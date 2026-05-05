"""Test transaction tools through BlenderWS client."""

import pytest

from blender_mcp.blender_client import BlenderWS, BlenderError


@pytest.mark.asyncio
async def test_transaction_begin(fake_blender):
    """transaction.begin should return active status."""
    fake_blender._handlers["transaction.begin"] = lambda args: {
        "transaction_id": args["transaction_id"],
        "status": "active",
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call("transaction.begin", {
            "transaction_id": "txn-001",
        })
        assert result["transaction_id"] == "txn-001"
        assert result["status"] == "active"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_transaction_commit(fake_blender):
    """transaction.commit should return committed status with op_count."""
    fake_blender._handlers["transaction.commit"] = lambda args: {
        "transaction_id": args["transaction_id"],
        "status": "committed",
        "op_count": 3,
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call("transaction.commit", {
            "transaction_id": "txn-001",
        })
        assert result["transaction_id"] == "txn-001"
        assert result["status"] == "committed"
        assert result["op_count"] == 3
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_transaction_rollback(fake_blender):
    """transaction.rollback should return rolled_back status."""
    fake_blender._handlers["transaction.rollback"] = lambda args: {
        "transaction_id": args["transaction_id"],
        "status": "rolled_back",
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call("transaction.rollback", {
            "transaction_id": "txn-001",
        })
        assert result["transaction_id"] == "txn-001"
        assert result["status"] == "rolled_back"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_transaction_unknown_op(fake_blender):
    """Calling transaction.begin without a handler should return NOT_FOUND."""
    del fake_blender._handlers["transaction.begin"]
    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        with pytest.raises(BlenderError) as exc_info:
            await client.call("transaction.begin", {"transaction_id": "x"})
        assert exc_info.value.code == "NOT_FOUND"
    finally:
        await client.close()
