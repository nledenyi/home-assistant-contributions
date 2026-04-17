# HA operations cheatsheet

## Check HA is alive

```bash
curl -sS --max-time 5 -o /dev/null -w "%{http_code}\n" http://<ha-host>:8123/manifest.json
```

## Restart HA Core (different paths)

- From host via MCP: `ha-mcp ha_restart(confirm=True)` or `ha_call_service(homeassistant.restart)`.
- From host via supervisor CLI: `sudo qm guest exec <ha-vm-id> -- ha core restart`.
- From HA UI: Developer Tools -> YAML -> "Restart Home Assistant".
- From HA container shell: `ha core restart`.

Wait for readiness:

```bash
until curl -sf -o /dev/null http://<ha-host>:8123/manifest.json; do sleep 5; done
```

## Reload one integration without full restart

```bash
curl -sS -X POST -H "Authorization: Bearer $TOKEN" \
  http://<ha-host>:8123/api/config/config_entries/entry/<entry_id>/reload
```

Or via the ha-mcp: `mcp__ha__ha_set_integration_enabled(entry_id, enabled=False)` then `True`. That one needs a restart to pick up the change.

## Pip-install a forked Python client into HA Core

```bash
sudo qm guest exec <ha-vm-id> -- docker exec homeassistant pip install \
  --force-reinstall --no-deps \
  "git+https://github.com/<user>/<package>@<branch>"
```

`--no-deps` is critical. See LESSONS.md.

## Inspect HA logs

Short recent tail (supervisor-filtered):

```bash
sudo qm guest exec <ha-vm-id> -- ha core logs 2>&1 | tail -100
```

Full container stderr (includes tracebacks):

```bash
sudo qm guest exec <ha-vm-id> -- docker logs --tail 500 homeassistant 2>&1
```

Filter for one integration:

```bash
sudo qm guest exec <ha-vm-id> -- docker logs homeassistant 2>&1 | grep -iE '<domain>|<package>'
```

## Find a config entry ID

```bash
# From host
claude mcp call ha ha_get_integration domain=<domain>
# Or via REST
curl -sS -H "Authorization: Bearer $TOKEN" \
  http://<ha-host>:8123/api/config/config_entries/entry | \
  python3 -c "import json,sys;[print(e['entry_id'], e['domain'], e['title']) for e in json.load(sys.stdin)]" | \
  grep <domain>
```

Config entries are also stored at `/config/.storage/core.config_entries` (JSON, readable inside the container).

## Find integration credentials

```bash
sudo qm guest exec <ha-vm-id> -- docker exec homeassistant \
  python3 -c "import json;d=json.load(open('/config/.storage/core.config_entries'));print([e for e in d['data']['entries'] if e['domain']=='<domain>'])"
```

## Dump Lovelace dashboard config

```python
# Via WebSocket, authenticated:
{"id": 1, "type": "lovelace/config", "url_path": "<dashboard-url-path>"}
```

Or: `ha-mcp ha_config_get_dashboard(url_path=...)`.

## HA raw log file

There is no persistent `/config/home-assistant.log` under recent HA OS.
Only `/config/home-assistant.log.fault` exists and is usually empty
except after crashes. Use `docker logs` for real-time tracebacks.

## VM-level recovery when HA is hung

```bash
sudo qm status <ha-vm-id>        # confirm running
sudo qm reboot <ha-vm-id>        # ACPI reboot (needs guest agent)
sudo qm reset <ha-vm-id>         # hard reset (doesn't need agent)
```
