# Security Policy

The full threat model and hardening guide lives in
[docs/SECURITY.md](docs/SECURITY.md). For network/remote deployment,
see [docs/REMOTE.md](docs/REMOTE.md).

## Supported versions

Security fixes are applied to the latest minor release on the `main` branch.
Older releases are best-effort.

## Reporting a vulnerability

**Please do not open a public GitHub issue for security reports.**

Use GitHub's private vulnerability reporting:

1. Open the repository's **Security** tab.
2. Click **Report a vulnerability**.
3. Provide a clear description, reproduction steps, affected version(s), and
   any suggested mitigation.

If you cannot use GitHub's private reporting, contact the maintainers via the
e-mail address listed in the repository's `CODEOWNERS` or `.github/` metadata.
We aim to acknowledge new reports within 7 days.

## Scope

In scope:

- The Blender add-on (`blender_addon/`)
- The MCP server (`mcp_server/`)
- The VS Code extension (`vscode_extension/`)
- Bundled configuration examples and policies (`examples/`)

Out of scope:

- Third-party MCP clients (Claude Desktop, Cursor, Cline, …) themselves
- The Blender Python API (`bpy`) and the Blender process itself
- User-supplied `execute_python` payloads (the add-on documents this risk
  explicitly; see [docs/SECURITY.md](docs/SECURITY.md))

## Disclosure

We follow coordinated disclosure: a fix is prepared and released before the
report is made public. Reporters who request credit will be acknowledged in
the release notes.
