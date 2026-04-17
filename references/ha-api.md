# HA API quick reference

## Base URL + token

- **Base URL**: `http://<ha-host>:8123`
- **Long-lived access token**: `claude mcp get ha` (extract `HOMEASSISTANT_TOKEN` from the env block) or read the system's MCP config.
- **Auth header**: `Authorization: Bearer <token>`

## REST endpoints that come up repeatedly

| Purpose | Method + path |
|---|---|
| Sanity ping (no auth) | `GET /manifest.json` |
| Entity state | `GET /api/states/{entity_id}` |
| Call a service | `POST /api/services/{domain}/{service}` body: `{...service_data}` |
| Restart HA Core | `POST /api/services/homeassistant/restart` (also available via `ha-mcp` `ha_restart`) |
| List config entries (integrations) | `GET /api/config/config_entries/entry` |
| Reload one integration | `POST /api/config/config_entries/entry/{entry_id}/reload` |
| Disable/enable integration | `POST /api/config/config_entries/entry/{entry_id}/disable` with `{"disabled_by": "user" | null}` |
| Start a new config flow | `POST /api/config/config_entries/flow` body: `{"handler": "<domain>"}` |
| Continue a flow | `POST /api/config/config_entries/flow/{flow_id}` body: `{...step input...}` |

## WebSocket (`ws://<ha-host>:8123/api/websocket`)

Auth handshake:

```json
// Server sends
{"type": "auth_required", ...}
// Client sends
{"type": "auth", "access_token": "<token>"}
// Server sends
{"type": "auth_ok", ...}
```

Lovelace config:

```json
{"id": 1, "type": "lovelace/config", "url_path": "lovelace-playground"}
```

Supervisor passthrough:

```json
{"id": 2, "type": "supervisor/api", "endpoint": "/ingress/session", "method": "post"}
```

## Shell into HA Core container

```bash
sudo qm guest exec <ha-vm-id> -- docker exec homeassistant <cmd>
```

Interactive:

```bash
sudo ssh <pve-host>  # or pct exec if LXC
# then from inside the HA VM:
docker exec -it homeassistant /bin/bash
```

## Supervisor CLI (`ha` command)

```bash
sudo qm guest exec <ha-vm-id> -- ha <cmd>
```

Useful:

- `ha core info`
- `ha core restart` / `ha core stop` / `ha core start`
- `ha core logs` (stdout of HA Core container, truncated)
- `ha addons list`
- `ha addons restart <slug>`
- `ha supervisor logs`

## When the guest agent dies

If `qm guest exec <ha-vm-id>` returns "QEMU guest agent is not running", you
cannot exec into the VM via qm. Fallback: `sudo qm reset <ha-vm-id>` (hard
ACPI reset). HA recovers cleanly in ~2 minutes.

Prevention: pace HA Core restarts. Don't restart more than 2-3 times in
rapid succession.
