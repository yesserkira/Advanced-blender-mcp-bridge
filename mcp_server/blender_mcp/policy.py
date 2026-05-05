"""Policy engine for the MCP server.

Loads .blendermcp.json from the workspace and enforces tool/path/resource restrictions.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger("blender_mcp.policy")

_DEFAULT_POLICY = {
    "allowed_tools": None,  # None = all allowed
    "denied_tools": [],
    "allowed_roots": [],
    "max_polys": 1_000_000,
    "max_resolution": 4096,
    "snapshot_threshold": 5,
    "confirm_required": ["execute_python", "delete_object"],
    "rate_limit": {
        "mutating_ops_per_10s": 50,
    },
}


class PolicyDenied(Exception):
    """Raised when a tool call is denied by policy."""

    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message)
        self.hint = hint


class Policy:
    """Runtime policy loaded from .blendermcp.json."""

    def __init__(self, config: dict | None = None):
        cfg = dict(_DEFAULT_POLICY)
        if config:
            cfg.update(config)

        self.allowed_tools: list[str] | None = cfg.get("allowed_tools")
        self.denied_tools: list[str] = cfg.get("denied_tools", [])
        self.allowed_roots: list[str] = cfg.get("allowed_roots", [])
        self.max_polys: int = cfg.get("max_polys", 1_000_000)
        self.max_resolution: int = cfg.get("max_resolution", 4096)
        self.snapshot_threshold: int = cfg.get("snapshot_threshold", 5)
        self.confirm_required: list[str] = cfg.get("confirm_required", [])
        self.rate_limit: dict = cfg.get("rate_limit", {"mutating_ops_per_10s": 50})

    @classmethod
    def load(cls, path: str | None = None) -> "Policy":
        """Load policy from a JSON file path.

        If path is None or file doesn't exist, returns default policy.
        """
        if not path:
            return cls()

        p = Path(path)
        if not p.is_file():
            logger.info("No policy file at %s, using defaults", path)
            return cls()

        try:
            with open(p, "r", encoding="utf-8") as f:
                config = json.load(f)
            logger.info("Loaded policy from %s", path)
            return cls(config)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load policy from %s: %s", path, e)
            return cls()

    def require(self, tool_name: str):
        """Check if a tool is allowed. Raises PolicyDenied if not."""
        if tool_name in self.denied_tools:
            raise PolicyDenied(
                f"Tool '{tool_name}' is denied by policy",
                hint="Remove from denied_tools in .blendermcp.json",
            )

        if self.allowed_tools is not None and tool_name not in self.allowed_tools:
            raise PolicyDenied(
                f"Tool '{tool_name}' is not in the allowed list",
                hint="Add to allowed_tools in .blendermcp.json",
            )

    def confirm_required_for(self, tool_name: str) -> bool:
        """Check if a tool requires user confirmation."""
        return tool_name in self.confirm_required

    def validate_path(self, path_str: str) -> Path:
        """Resolve and validate a file path against allowed roots.

        Returns the resolved Path if valid.
        Raises PolicyDenied if outside allowed roots.
        """
        resolved = Path(path_str).resolve()

        if not self.allowed_roots:
            return resolved

        for root in self.allowed_roots:
            root_resolved = Path(root).resolve()
            try:
                resolved.relative_to(root_resolved)
                return resolved
            except ValueError:
                continue

        raise PolicyDenied(
            f"Path '{resolved}' is outside allowed roots",
            hint=f"Allowed roots: {', '.join(self.allowed_roots)}",
        )

    def check_poly_count(self, count: int):
        """Raise PolicyDenied if poly count exceeds limit."""
        if count > self.max_polys:
            raise PolicyDenied(
                f"Polygon count {count} exceeds limit of {self.max_polys}",
                hint="Increase max_polys in .blendermcp.json",
            )

    def check_resolution(self, w: int, h: int):
        """Raise PolicyDenied if resolution exceeds limit."""
        if w > self.max_resolution or h > self.max_resolution:
            raise PolicyDenied(
                f"Resolution {w}x{h} exceeds limit of {self.max_resolution}",
                hint="Increase max_resolution in .blendermcp.json",
            )
