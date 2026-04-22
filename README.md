# Home Assistant contributions

Public portfolio of Home Assistant-adjacent work: integration bug fixes, dashboard patterns, reusable Claude Code skills, and accumulated lessons from debugging custom integrations.

## Integration fixes

| Integration | Status | Upstream PR / issue | Lives in |
|---|---|---|---|
| pymammotion (work_zone stale read) | Maintainer merged equivalent fix | [Mammotion-HA#365](https://github.com/mikey0000/Mammotion-HA/issues/365) | [`integrations/pymammotion/`](integrations/pymammotion/) |
| pytoyoda (summary schema drift) | PR open | [pytoyoda/pytoyoda#249](https://github.com/pytoyoda/pytoyoda/pull/249), [ha_toyota#278](https://github.com/pytoyoda/ha_toyota/issues/278) | [`integrations/pytoyoda/`](integrations/pytoyoda/) |
| ha_toyota (`_run_pytoyoda_sync` memory leak, ~500 KB per pytoyoda call) | PR open, reporter confirmed | [pytoyoda/ha_toyota#283](https://github.com/pytoyoda/ha_toyota/pull/283), [ha_toyota#282](https://github.com/pytoyoda/ha_toyota/issues/282) | [`integrations/pytoyoda/memory-leak-fix.md`](integrations/pytoyoda/memory-leak-fix.md) |

## Dashboards

| Pattern | Skill | Lives in |
|---|---|---|
| Unified-look section card (tiles + bubble-card + entities over an opacity 40% section background) | [`skills/ha-section-card/`](skills/ha-section-card/) | [`dashboards/section-cards/`](dashboards/section-cards/) |

## Claude Code skills

| Skill | What it does |
|---|---|
| [`skills/ha-section-card/`](skills/ha-section-card/) | Build a Home Assistant dashboard section card following a consistent unified-look design pattern. Uses Bubble-Card + card-mod + reusable Bubble-Card modules. |
| [`skills/ha-integration-fix/`](skills/ha-integration-fix/) | End-to-end workflow to diagnose and fix a bug in an HA custom integration: fork, reproduce, patch, test, PR, and post a workaround comment on the integration issue. |

## Reading order for a new bug

1. [`LESSONS.md`](LESSONS.md) - cross-cutting patterns from past fixes worth revisiting before diving in.
2. [`references/cheatsheet.md`](references/cheatsheet.md) - HA operations that come up repeatedly (restart, log extraction, container shell, config entry reload).
3. [`references/ha-api.md`](references/ha-api.md) - REST + WebSocket endpoints, token locations.
4. [`integrations/_template/`](integrations/_template/) - skeleton to copy when starting a new integration investigation.

## Notes

All commands reference `<ha-host>` and `<ha-vm-id>` instead of real hostnames / VM IDs. Substitute your own values. Commands assume an HA OS setup on a Proxmox VM with the QEMU guest agent; adapt paths if you run HA differently.
