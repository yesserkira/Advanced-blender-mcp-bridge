# Remote Blender hosts

> **TL;DR.** Don't expose the Blender add-on directly on a network. Use SSH
> port forwarding so VS Code still connects to `127.0.0.1` and the only thing
> on the wire is encrypted SSH traffic.

The Blender MCP Bridge is built around a security model that assumes the
Blender add-on, the MCP server, and VS Code all run on the **same machine**
and talk over loopback. Loopback is unreachable from the network, so a
stolen auth token can't be replayed by an attacker who only has network
access.

If you need to drive Blender on a different machine (a render box, a
beefy workstation, a Linux VM) the supported pattern is **SSH port
forwarding**. The Bridge will refuse to opt you into anything else by
default — you have to flip multiple switches in the Blender add-on AND
acknowledge a per-host warning in VS Code.

---

## Recommended: SSH port forwarding (no add-on changes needed)

On the machine running VS Code:

```bash
ssh -N -L 9876:127.0.0.1:9876 user@blender-host
```

Now `127.0.0.1:9876` on your laptop forwards through the encrypted SSH
tunnel to `127.0.0.1:9876` on `blender-host`. From the Bridge's point of
view nothing changed: it still talks to a loopback address with the
default token discovery flow.

Pros:

* No add-on configuration changes — the Blender server stays bound to
  `127.0.0.1` on the remote host.
* Authentication piggybacks on SSH keys; the auth token never travels
  in cleartext.
* Works through firewalls and NAT as long as you can SSH.
* Survives token rotation — the Bridge re-reads `~/.blender_mcp/connection.json`.

Caveat: you have to copy `~/.blender_mcp/connection.json` from the
remote host to your local machine (or share the home directory) so the
Bridge can discover the token. If your SSH user has a different home
directory, use `BLENDER_MCP_TOKEN` env var instead.

---

## Discouraged: bind Blender to 0.0.0.0

If you really must bind the add-on directly to a network interface, the
Bridge requires **two** explicit opt-ins on the Blender side and a
**third** acknowledgement in VS Code.

### 1. Blender add-on

1. Preferences → Add-ons → **Blender MCP Bridge**.
2. Change **Bind Host** from "Loopback (secure)" to **"All interfaces (REMOTE)"**.
3. The risk box appears. Tick **Allow remote bind**.
4. Click **I understand the risks**. The auth token is rotated immediately;
   restart the server so the new token is loaded.

If you skip any of these, `effective_bind_host()` silently downgrades to
`127.0.0.1` — and so does `ws_server.start()` as a defence-in-depth check.

### 2. VS Code extension

Either the connection file or `BLENDER_MCP_URL` must point at the remote
host (e.g. `ws://blender-host.local:9876`). On activation the extension:

* Detects the non-loopback host via `isRemoteHost()`.
* Refuses to register the MCP provider until you run **"Blender MCP:
  Acknowledge Remote Host"** and click through the modal warning.
* Stores the acknowledgement under `globalState['blenderMcp.remoteAck:<host>']`,
  so a different remote host re-prompts.
* Surfaces a "⚠ Remote host" item in the MCP Bridge view; clicking it
  toggles the acknowledgement.

Run **"Blender MCP: Revoke Remote Host Acknowledgement"** to clear the opt-in.

### 3. MCP server policy

The MCP server (`blender_mcp.policy`) adds two more knobs:

```json
{
  "allowed_remote_hosts": ["blender-host.local"],
  "require_tls": true
}
```

* `allowed_remote_hosts: null` (default) → no extra check beyond the
  Blender / VS Code gates above.
* `allowed_remote_hosts: []` → loopback only; reject every remote URL.
  This is what `examples/policies/strict.json` ships with.
* `allowed_remote_hosts: ["a.example", "b.example"]` → allow only those
  hosts, in addition to loopback.
* `require_tls: true` → reject plain `ws://` for non-loopback hosts.
  Use `wss://` (terminate TLS via stunnel, nginx, Caddy, or land an SSH
  tunnel on loopback and connect to that).

`Policy.validate_connection_url()` runs at MCP-client construction time,
so a forbidden URL fails fast with a `PolicyDenied` error before any
Blender call is attempted.

---

## What stays loopback even in remote mode

* **Approval HTTP endpoint** in the VS Code extension. It mints
  approvals for local user actions — it must never be reachable from
  the network. The check in `approval.ts._handleRequest()` enforces
  this regardless of how Blender is bound.
* **`~/.blender_mcp/connection.json`** is written with `0600` perms so
  other local users on a shared machine can't read the token.

---

## Threats you accept by going remote

| Threat | Loopback | Remote (raw `ws://`) | Remote (`wss://` or SSH) |
|---|---|---|---|
| Token sniffed on LAN | n/a | **yes** | no |
| Anyone reaching host:port can drive Blender | no | **yes** | only with token |
| Token replay across a Wi-Fi rejoin | n/a | **yes** | no |
| Compromised intermediate router can run Python in Blender | n/a | **yes** | no |

Nothing in the Bridge can paper over a misconfigured network. Treat the
remote opt-in as "I have read the docs and accept that this auth token
is now equivalent to a network-exposed shell on the Blender host."
