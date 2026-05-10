# Blender MCP Bridge

A local, secure bridge that lets AI chat agents inside VS Code (Copilot Chat, Claude Desktop, Cursor, Cline, Continue) inspect and modify a running Blender scene through MCP tool calls.

[![CI](https://img.shields.io/badge/CI-passing-brightgreen.svg)](.github/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Blender 4.2+](https://img.shields.io/badge/Blender-4.2%2B-orange.svg)](https://www.blender.org/)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-support-FFDD00.svg?logo=buy-me-a-coffee&logoColor=black)](https://www.buymeacoffee.com/yesserkiraa)

## Components

- **blender_addon/** — Blender add-on. Runs a WebSocket server on `127.0.0.1`, executes `bpy` ops on the main thread.
- **mcp_server/** — Python MCP server. Exposes typed tools to AI clients, validates, applies policy, forwards to add-on.
- **vscode_extension/** — Optional TypeScript extension. Approval webview, viewport preview, output channel.

## Requirements

- Blender 4.2 LTS or newer
- Python 3.11+
- VS Code 1.99+ (for built-in MCP support)
- `uv` or `pip` for MCP server dependencies

## Quick Start

1. Install the Blender add-on: copy `blender_addon/` to Blender's `scripts/addons/` or install via `.zip`.
2. Enable "Blender MCP Bridge" in Blender Preferences → Add-ons.
3. Copy the auth token from the MCP panel in Blender's N-panel.
4. Install the MCP server: `cd mcp_server && uv pip install -e .`
5. Configure VS Code: see `.vscode/mcp.json` or `examples/vscode_mcp.json`.

## Security & remote hosts

The default deployment is loopback-only. See [docs/SECURITY.md](docs/SECURITY.md)
for the threat model, and [docs/REMOTE.md](docs/REMOTE.md) before exposing
Blender on a network — SSH port forwarding is the supported pattern.

To report a vulnerability, see [SECURITY.md](SECURITY.md).

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) and the
[Code of Conduct](CODE_OF_CONDUCT.md). For deeper architecture context, read
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## License

MIT — see [LICENSE](LICENSE).

## Support the project

If this project saves you time or you'd like to help fund continued development,
you can [buy me a coffee ☕]([https://www.buymeacoffee.com/yesserkiraa](https://www.patreon.com/posts/advanced-blender-157884874?utm_medium=clipboard_copy&utm_source=copyLink&utm_campaign=postshare_creator&utm_content=join_link)). Every bit
helps and is hugely appreciated — thank you!
