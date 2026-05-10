"""Tests for blender_mcp.installer — config patching + idempotency."""

from __future__ import annotations

import json

import pytest

from blender_mcp import installer


def test_build_server_entry_mcpservers_shape():
    e = installer.build_server_entry("mcpServers", "blender-mcp", [])
    assert e == {"command": "blender-mcp", "args": []}


def test_build_server_entry_vscode_shape():
    e = installer.build_server_entry("vscode", "blender-mcp", [])
    assert e == {"type": "stdio", "command": "blender-mcp", "args": []}


def test_container_key():
    assert installer.container_key("vscode") == "servers"
    assert installer.container_key("mcpServers") == "mcpServers"


def test_resolve_launch_command_returns_tuple():
    cmd, args = installer.resolve_launch_command()
    assert isinstance(cmd, str) and cmd
    assert isinstance(args, list)


def test_patch_creates_file_when_missing(tmp_path):
    p = tmp_path / "nested" / "config.json"
    r = installer.patch_config(
        str(p), "mcpServers", "blender-mcp", [], server_name="blender",
    )
    assert r["action"] == "created"
    assert r["backup"] is False
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data == {"mcpServers": {"blender": {"command": "blender-mcp", "args": []}}}


def test_patch_preserves_existing_servers(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({
        "mcpServers": {
            "other": {"command": "other-cmd", "args": ["x"]},
        },
        "unrelated": {"keep": True},
    }), encoding="utf-8")

    r = installer.patch_config(
        str(p), "mcpServers", "blender-mcp", [],
    )
    assert r["action"] == "updated"
    assert r["backup"] is True
    assert (p.parent / "config.json.bak").exists()

    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["mcpServers"]["other"] == {"command": "other-cmd", "args": ["x"]}
    assert data["mcpServers"]["blender"] == {"command": "blender-mcp", "args": []}
    assert data["unrelated"] == {"keep": True}


def test_patch_is_idempotent(tmp_path):
    p = tmp_path / "config.json"
    installer.patch_config(str(p), "mcpServers", "blender-mcp", [])
    r2 = installer.patch_config(str(p), "mcpServers", "blender-mcp", [])
    assert r2["action"] == "unchanged"
    assert r2["backup"] is False


def test_patch_vscode_shape_uses_servers_key(tmp_path):
    p = tmp_path / "mcp.json"
    installer.patch_config(str(p), "vscode", "blender-mcp", [])
    data = json.loads(p.read_text(encoding="utf-8"))
    assert "servers" in data
    assert "mcpServers" not in data
    assert data["servers"]["blender"]["type"] == "stdio"


def test_patch_rejects_non_object_root(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("[]", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Cannot parse"):
        installer.patch_config(str(p), "mcpServers", "blender-mcp", [])


def test_patch_rejects_invalid_json(tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Cannot parse"):
        installer.patch_config(str(p), "mcpServers", "blender-mcp", [])


def test_patch_handles_empty_file(tmp_path):
    p = tmp_path / "empty.json"
    p.write_text("", encoding="utf-8")
    r = installer.patch_config(str(p), "mcpServers", "blender-mcp", [])
    assert r["action"] == "updated"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert "blender" in data["mcpServers"]


def test_patch_replaces_container_if_wrong_type(tmp_path):
    """If `mcpServers` is somehow a list, we replace it (don't crash)."""
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"mcpServers": ["unexpected"]}), encoding="utf-8")
    r = installer.patch_config(str(p), "mcpServers", "blender-mcp", [])
    assert r["action"] == "updated"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert isinstance(data["mcpServers"], dict)
    assert "blender" in data["mcpServers"]


def test_install_print_only_does_not_write(tmp_path, monkeypatch):
    # Force claude detection to ON, point its config at tmp_path.
    fake = tmp_path / "claude" / "claude_desktop_config.json"
    fake.parent.mkdir(parents=True)
    monkeypatch.setattr(installer, "_claude_path", lambda: str(fake))

    results = installer.install(selected_keys=["claude"], print_only=True)
    assert len(results) == 1
    assert results[0]["action"] == "print"
    assert "snippet" in results[0]
    assert not fake.exists()


def test_install_writes_only_to_selected_clients(tmp_path, monkeypatch):
    fake_claude = tmp_path / "claude" / "config.json"
    fake_cursor = tmp_path / "cursor" / "mcp.json"
    fake_claude.parent.mkdir(parents=True)
    fake_cursor.parent.mkdir(parents=True)
    monkeypatch.setattr(installer, "_claude_path", lambda: str(fake_claude))
    monkeypatch.setattr(installer, "_cursor_path", lambda: str(fake_cursor))

    results = installer.install(selected_keys=["claude"])
    assert len(results) == 1
    assert results[0]["client"] == "claude"
    assert fake_claude.exists()
    assert not fake_cursor.exists()


def test_cli_list_clients_runs(capsys):
    rc = installer.main(["--list-clients"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Claude Desktop" in out
    assert "Cursor" in out
    assert "VS Code" in out


def test_cli_print_only_emits_json(tmp_path, monkeypatch, capsys):
    fake = tmp_path / "claude" / "config.json"
    fake.parent.mkdir(parents=True)
    monkeypatch.setattr(installer, "_claude_path", lambda: str(fake))

    rc = installer.main(["--client", "claude", "--print"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Claude Desktop" in out
    assert '"blender"' in out
    assert not fake.exists()
