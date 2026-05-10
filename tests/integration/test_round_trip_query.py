"""Headless: ping + describe_api round-trip."""

from __future__ import annotations

from conftest import call


def test_ping():
    out = call("ping", {})
    assert out == "pong"


def test_describe_api_returns_op_list():
    out = call("describe_api", {})
    assert isinstance(out, dict)
    text = repr(out)
    assert "create_objects" in text
    assert "geonodes" in text
