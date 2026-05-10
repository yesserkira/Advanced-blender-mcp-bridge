"""Test the Policy engine."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from blender_mcp.policy import Policy, PolicyDenied


class TestPolicyRequire:
    def test_default_policy_allows_all(self):
        policy = Policy()
        # Should not raise
        policy.require("get_scene_info")
        policy.require("create_primitive")
        policy.require("viewport_screenshot")

    def test_denied_tool_raises(self):
        policy = Policy({"denied_tools": ["execute_python"]})
        with pytest.raises(PolicyDenied) as exc_info:
            policy.require("execute_python")
        assert "denied by policy" in str(exc_info.value)
        assert exc_info.value.hint is not None

    def test_allowed_list_restricts(self):
        policy = Policy({"allowed_tools": ["ping", "get_scene_info"]})
        policy.require("ping")  # OK
        policy.require("get_scene_info")  # OK

        with pytest.raises(PolicyDenied):
            policy.require("create_primitive")

    def test_denied_takes_precedence_over_allowed(self):
        policy = Policy({
            "allowed_tools": ["execute_python"],
            "denied_tools": ["execute_python"],
        })
        with pytest.raises(PolicyDenied):
            policy.require("execute_python")


class TestPolicyConfirm:
    def test_confirm_required_default(self):
        policy = Policy()
        # Phase 9.1: defaults flipped to permissive (match official Blender MCP).
        # execute_python no longer requires per-call approval; users opt back in
        # via policy.confirm_required.
        assert policy.confirm_required_for("execute_python") is False
        assert policy.confirm_required_for("delete_object") is True
        assert policy.confirm_required_for("ping") is False

    def test_confirm_required_custom(self):
        policy = Policy({"confirm_required": ["create_primitive"]})
        assert policy.confirm_required_for("create_primitive") is True
        assert policy.confirm_required_for("execute_python") is False


class TestPolicyPath:
    def test_path_no_roots_allows_all(self):
        policy = Policy({"allowed_roots": []})
        # Should not raise
        result = policy.validate_path(os.path.abspath("."))
        assert result.is_absolute()

    def test_path_inside_root_allowed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_resolved = str(Path(tmpdir).resolve())
            policy = Policy({"allowed_roots": [tmpdir]})
            inner = os.path.join(tmpdir, "subdir", "file.txt")
            result = policy.validate_path(inner)
            assert str(result).startswith(tmpdir_resolved)

    def test_path_outside_root_denied(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            policy = Policy({"allowed_roots": [tmpdir]})
            outside = os.path.abspath(os.path.join(tmpdir, "..", "outside.txt"))
            with pytest.raises(PolicyDenied) as exc_info:
                policy.validate_path(outside)
            assert "outside allowed roots" in str(exc_info.value)

    def test_path_traversal_denied(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            policy = Policy({"allowed_roots": [tmpdir]})
            traversal = os.path.join(tmpdir, "..", "..", "etc", "passwd")
            with pytest.raises(PolicyDenied):
                policy.validate_path(traversal)


class TestPolicyResourceCaps:
    def test_poly_count_within_limit(self):
        policy = Policy({"max_polys": 1000})
        policy.check_poly_count(999)  # OK

    def test_poly_count_exceeds_limit(self):
        policy = Policy({"max_polys": 1000})
        with pytest.raises(PolicyDenied):
            policy.check_poly_count(1001)

    def test_resolution_within_limit(self):
        policy = Policy({"max_resolution": 4096})
        policy.check_resolution(4096, 4096)  # OK

    def test_resolution_exceeds_limit(self):
        policy = Policy({"max_resolution": 4096})
        with pytest.raises(PolicyDenied):
            policy.check_resolution(8192, 4096)


class TestPolicyLoad:
    def test_load_from_file(self):
        config = {
            "allowed_tools": ["ping"],
            "denied_tools": ["execute_python"],
            "max_polys": 500,
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(config, f)
            f.flush()
            policy = Policy.load(f.name)

        assert policy.allowed_tools == ["ping"]
        assert policy.denied_tools == ["execute_python"]
        assert policy.max_polys == 500
        os.unlink(f.name)

    def test_load_missing_file_returns_default(self):
        policy = Policy.load("/nonexistent/path.json")
        assert policy.allowed_tools is None
        assert policy.max_polys == 1_000_000

    def test_load_none_returns_default(self):
        policy = Policy.load(None)
        assert policy.allowed_tools is None


class TestPolicyConnectionUrl:
    def test_loopback_always_allowed(self):
        # Even with strict allow-list, loopback URLs pass.
        p = Policy({"allowed_remote_hosts": []})
        for url in ("ws://127.0.0.1:9876", "ws://localhost:1", "ws://127.10.20.30:80", "ws://[::1]:9876"):
            p.validate_connection_url(url)

    def test_default_allows_remote(self):
        Policy().validate_connection_url("ws://blender.example:9876")

    def test_empty_allow_list_blocks_remote(self):
        p = Policy({"allowed_remote_hosts": []})
        with pytest.raises(PolicyDenied) as exc:
            p.validate_connection_url("ws://10.0.0.1:9876")
        assert exc.value.code == "POLICY_REMOTE_HOST_DENIED"

    def test_explicit_allow_list_permits_named_host(self):
        p = Policy({"allowed_remote_hosts": ["blender.local"]})
        p.validate_connection_url("ws://blender.local:9876")
        with pytest.raises(PolicyDenied):
            p.validate_connection_url("ws://other.host:9876")

    def test_require_tls_blocks_plain_remote(self):
        p = Policy({"require_tls": True})
        with pytest.raises(PolicyDenied) as exc:
            p.validate_connection_url("ws://blender.local:9876")
        assert exc.value.code == "POLICY_REQUIRE_TLS"
        # wss is fine
        p.validate_connection_url("wss://blender.local:9876")
        # And loopback never needs TLS
        p.validate_connection_url("ws://127.0.0.1:9876")

    def test_unknown_scheme_rejected(self):
        with pytest.raises(PolicyDenied):
            Policy().validate_connection_url("http://blender.local:9876")
