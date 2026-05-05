"""Policy engine for the MCP server.

Loads .blendermcp.json from the workspace and enforces tool/path/resource restrictions.
"""

import json
import logging
from pathlib import Path

from .rate_limit import TokenBucket

logger = logging.getLogger("blender_mcp.policy")

# Tools that observe Blender state without changing it. Excluded from the
# mutating-rate-limiter so a status panel polling `ping` cannot be throttled.
# NOTE: keep in sync with @mcp.tool() definitions in server.py.
READ_ONLY_TOOLS: frozenset[str] = frozenset(
    {
        "ping",
        "query",
        "list",
        "describe_api",
        "get_audit_log",
        "get_property",
        "list_assets",
        "viewport_screenshot",
        "scene_diff",
        "list_checkpoints",
    }
)

def is_mutating(tool_name: str) -> bool:
    """True if calling `tool_name` may modify the Blender scene."""
    return tool_name not in READ_ONLY_TOOLS


_DEFAULT_POLICY = {
    "allowed_tools": None,  # None = all allowed
    "denied_tools": [],
    "allowed_roots": [],
    "max_polys": 1_000_000,
    "max_resolution": 4096,
    "snapshot_threshold": 5,
    "confirm_required": ["execute_python", "delete_object"],
    "rate_limit": {
        "mutating_ops_per_window": 50,
        "window_seconds": 10.0,
    },
}


class PolicyDenied(Exception):
    """Raised when a tool call is denied by policy."""

    def __init__(self, message: str, hint: str | None = None, code: str = "POLICY_DENIED"):
        super().__init__(message)
        self.hint = hint
        self.code = code


class RateLimitDenied(PolicyDenied):
    """Raised when the mutating-ops token bucket is empty."""

    def __init__(self, tool: str, capacity: int, window_seconds: float, retry_after: float):
        super().__init__(
            f"Rate limit exceeded for '{tool}': max {capacity} mutating ops per "
            f"{window_seconds:.1f}s. Retry after ~{retry_after:.2f}s.",
            hint=f"Wait ~{retry_after:.2f}s, or raise rate_limit.mutating_ops_per_window in .blendermcp.json.",
            code="RATE_LIMIT",
        )
        self.tool = tool
        self.retry_after = retry_after


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
        self.rate_limit: dict = cfg.get(
            "rate_limit",
            {"mutating_ops_per_window": 50, "window_seconds": 10.0},
        )
        # Backwards-compat: accept legacy "mutating_ops_per_10s" key.
        if "mutating_ops_per_10s" in self.rate_limit and "mutating_ops_per_window" not in self.rate_limit:
            self.rate_limit["mutating_ops_per_window"] = self.rate_limit["mutating_ops_per_10s"]
            self.rate_limit.setdefault("window_seconds", 10.0)
        self._bucket: TokenBucket | None = None

    def get_rate_limiter(self) -> TokenBucket:
        """Lazily create a TokenBucket sized from policy.rate_limit."""
        if self._bucket is None:
            cap = int(self.rate_limit.get("mutating_ops_per_window", 50))
            window = float(self.rate_limit.get("window_seconds", 10.0))
            self._bucket = TokenBucket(capacity=max(1, cap), window_seconds=max(0.1, window))
        return self._bucket

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
        """Check if a tool is allowed. Raises PolicyDenied / RateLimitDenied if not."""
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

        # Rate-limit mutating tools.
        if is_mutating(tool_name):
            bucket = self.get_rate_limiter()
            allowed, retry_after = bucket.take(1)
            if not allowed:
                raise RateLimitDenied(
                    tool=tool_name,
                    capacity=bucket.capacity,
                    window_seconds=bucket.window_seconds,
                    retry_after=retry_after,
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


# ---------------------------------------------------------------------------
# Polygon estimation for create_objects / primitive specs
# ---------------------------------------------------------------------------


# Approximate polygon counts for Blender primitives at default subdivision.
# Sources: Blender docs / measured. Used purely as an *upper-bound estimate*
# so the model can't sneak a 10M-poly mesh past the policy by lying about it.
_PRIMITIVE_POLY_ESTIMATES: dict[str, int] = {
    "cube": 6,
    "plane": 1,
    "circle": 32,
    "uv_sphere": 960,        # 32 segments x 16 rings (default)
    "sphere": 960,
    "ico_sphere": 320,       # subdivisions=2 default
    "icosphere": 320,
    "cylinder": 96,          # 32 verts x 2 caps + 32 sides
    "cone": 64,
    "torus": 576,            # 12 minor x 48 major (default)
    "monkey": 968,            # Suzanne
    "suzanne": 968,
    "grid": 100,             # 10x10 default
    "light": 0,
    "camera": 0,
    "empty": 0,
    "armature": 0,
}

# Conservative multiplier for known mesh modifiers that grow geometry.
_MODIFIER_MULTIPLIERS: dict[str, float] = {
    "SUBSURF": 4.0,           # one level ~4x faces
    "SUBDIVISION_SURFACE": 4.0,
    "MULTIRES": 4.0,
    "MIRROR": 2.0,
    "ARRAY": 1.0,             # multiplied by count below
    "BEVEL": 1.5,
    "SOLIDIFY": 2.0,
    "REMESH": 2.0,
}


def _estimate_one(spec: dict) -> int:
    """Estimate polygons for a single create_objects spec."""
    if not isinstance(spec, dict):
        return 0
    kind = str(spec.get("kind") or spec.get("type") or "").lower().replace(" ", "_")
    base = _PRIMITIVE_POLY_ESTIMATES.get(kind, 100)  # unknown -> small default
    mods = spec.get("modifiers") or []
    if isinstance(mods, list):
        for m in mods:
            if not isinstance(m, dict):
                continue
            mtype = str(m.get("type", "")).upper()
            mult = _MODIFIER_MULTIPLIERS.get(mtype, 1.0)
            if mtype == "SUBSURF" or mtype == "SUBDIVISION_SURFACE" or mtype == "MULTIRES":
                # Power-of-4 by level (capped at level 4 to avoid silly numbers).
                props = m.get("properties") or {}
                level = int(props.get("levels", props.get("render_levels", 1)) or 1)
                level = max(0, min(level, 4))
                mult = 4.0 ** level
            elif mtype == "ARRAY":
                props = m.get("properties") or {}
                count = int(props.get("count", 2) or 2)
                mult = max(1.0, float(count))
            base = int(base * mult)
    return base


def estimate_polys(specs: list[dict]) -> int:
    """Estimate total polygons for a list of create_objects specs."""
    if not isinstance(specs, list):
        return 0
    return sum(_estimate_one(s) for s in specs)
