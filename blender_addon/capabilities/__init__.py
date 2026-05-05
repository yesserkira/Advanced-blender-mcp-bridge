"""Capability registry.

Each capability module registers its ops here on import.
"""

from typing import Callable

OP_REGISTRY: dict[str, Callable] = {}


def register_capability(op: str, fn: Callable):
    """Register a capability function under the given operation name."""
    OP_REGISTRY[op] = fn


def _register_builtins():
    """Register built-in capabilities (ping, etc.)."""
    register_capability("ping", lambda args: "pong")


_register_builtins()


def load_all():
    """Import all capability modules to populate the registry."""
    from . import scene  # noqa: F401
    from . import mesh  # noqa: F401
    from . import render  # noqa: F401
