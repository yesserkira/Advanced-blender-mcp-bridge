"""Transaction manager — group operations in one undo checkpoint."""

import bpy

from ..capabilities import register_capability


class TransactionManager:
    """Manages named transactions for grouping undo steps."""

    def __init__(self):
        self._active: dict[str, dict] = {}

    def begin(self, args: dict) -> dict:
        """Begin a new transaction.

        Args:
            args: {"transaction_id": str}
        """
        transaction_id = args.get("transaction_id")
        if not transaction_id:
            raise ValueError("transaction_id is required")

        if transaction_id in self._active:
            raise ValueError(
                f"Transaction '{transaction_id}' is already active"
            )

        bpy.ops.ed.undo_push(message=f"AI:transaction.begin:{transaction_id}")

        self._active[transaction_id] = {
            "started_at": __import__("time").time(),
            "op_count": 0,
        }

        return {"transaction_id": transaction_id, "status": "active"}

    def commit(self, args: dict) -> dict:
        """Commit an active transaction.

        Args:
            args: {"transaction_id": str}
        """
        transaction_id = args.get("transaction_id")
        if not transaction_id:
            raise ValueError("transaction_id is required")

        if transaction_id not in self._active:
            raise ValueError(
                f"Transaction '{transaction_id}' is not active"
            )

        info = self._active.pop(transaction_id)

        bpy.ops.ed.undo_push(message=f"AI:transaction.commit:{transaction_id}")

        return {
            "transaction_id": transaction_id,
            "status": "committed",
            "op_count": info["op_count"],
        }

    def rollback(self, args: dict) -> dict:
        """Rollback an active transaction by undoing to the begin checkpoint.

        Args:
            args: {"transaction_id": str}
        """
        transaction_id = args.get("transaction_id")
        if not transaction_id:
            raise ValueError("transaction_id is required")

        if transaction_id not in self._active:
            raise ValueError(
                f"Transaction '{transaction_id}' is not active"
            )

        self._active.pop(transaction_id)

        # Undo back to the begin checkpoint
        bpy.ops.ed.undo()

        return {"transaction_id": transaction_id, "status": "rolled_back"}


_manager = TransactionManager()

register_capability("transaction.begin", _manager.begin)
register_capability("transaction.commit", _manager.commit)
register_capability("transaction.rollback", _manager.rollback)
