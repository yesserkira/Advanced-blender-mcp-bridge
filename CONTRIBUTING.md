See [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) for the full contributor guide,
including environment setup, coding style, testing, and release process.

## Quick start

```bash
# Clone
git clone <repo-url>
cd BlenderVscode

# MCP server (Python 3.11+)
cd mcp_server
uv pip install -e ".[dev]"
uv run pytest -q

# VS Code extension (Node 18+)
cd ../vscode_extension
npm ci
npm run compile

# Add-on lint
ruff check blender_addon --ignore E402
```

## Reporting issues

Please use the GitHub issue templates and include:

- Blender version, OS, Python version
- MCP server / VS Code extension version
- Reproduction steps and expected vs. actual behaviour
- Relevant logs (with secrets redacted)

## Security

For security-sensitive issues, do **not** open a public issue — see [SECURITY.md](SECURITY.md).
