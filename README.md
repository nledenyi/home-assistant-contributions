# Home Assistant contributions

Public portfolio of Home Assistant-adjacent work: integration bug fixes, dashboard patterns, reusable Claude Code skills, and accumulated lessons from debugging custom integrations.

## Integration fixes

| Integration | Status | Upstream PR / issue | Lives in |
|---|---|---|---|
| pymammotion (work_zone stale read) | Maintainer merged equivalent fix | [Mammotion-HA#365](https://github.com/mikey0000/Mammotion-HA/issues/365) | [`integrations/pymammotion/`](integrations/pymammotion/) |
| pytoyoda (summary schema drift) | PR open (also bundled into #252) | [pytoyoda/pytoyoda#249](https://github.com/pytoyoda/pytoyoda/pull/249), [ha_toyota#278](https://github.com/pytoyoda/ha_toyota/issues/278) | [`integrations/pytoyoda/`](integrations/pytoyoda/) |
| ha_toyota (`_run_pytoyoda_sync` memory leak, ~500 KB per pytoyoda call) + residual per-request httpx client leak | #283 approved; residual fix bundled into #252 / #286 | [pytoyoda/ha_toyota#283](https://github.com/pytoyoda/ha_toyota/pull/283), [ha_toyota#282](https://github.com/pytoyoda/ha_toyota/issues/282) | [`integrations/pytoyoda/memory-leak-fix.md`](integrations/pytoyoda/memory-leak-fix.md) |
| pytoyoda + ha_toyota (smart status refresh + 429 resilience + #87 null-render fix) | **PRs open 2026-04-26**, ready-for-review, deployed live, validated on real drive | [pytoyoda#252](https://github.com/pytoyoda/pytoyoda/pull/252), [ha_toyota#286](https://github.com/pytoyoda/ha_toyota/pull/286). 9 issues mitigated across both repos: [#87](https://github.com/pytoyoda/ha_toyota/issues/87), [#137](https://github.com/pytoyoda/ha_toyota/issues/137), [#157](https://github.com/pytoyoda/ha_toyota/issues/157), [#168](https://github.com/pytoyoda/ha_toyota/issues/168), [#190](https://github.com/pytoyoda/ha_toyota/issues/190), [#229](https://github.com/pytoyoda/ha_toyota/issues/229), [#281](https://github.com/pytoyoda/ha_toyota/issues/281), [#284](https://github.com/pytoyoda/ha_toyota/issues/284), [pytoyoda#161](https://github.com/pytoyoda/pytoyoda/issues/161). Install gist for testing: [772fd3d6](https://gist.github.com/nledenyi/772fd3d68a445313fec56fae430b8f01) | [`integrations/pytoyoda/smart-status-refresh.md`](integrations/pytoyoda/smart-status-refresh.md) |

## Device writeups

| Device | Writeup | Summary |
|---|---|---|
| Viessmann Vitodens 100-W B1HG | [Gist](https://gist.github.com/nledenyi/78c081370cf557229b59ad27fff0b0fe) | Local OpenTherm control via ESP32 + ESPHome, bypassing the Viessmann cloud paywall. Wiring, OT message map, and HA climate entity setup. |

## Dashboards

| Pattern | Skill | Lives in |
|---|---|---|
| Unified-look section card (tiles + bubble-card + entities over an opacity 40% section background) | [`skills/ha-section-card/`](skills/ha-section-card/) | [`dashboards/section-cards/`](dashboards/section-cards/) |

## Claude Code skills

| Skill | What it does |
|---|---|
| [`skills/ha-section-card/`](skills/ha-section-card/) | Build a Home Assistant dashboard section card following a consistent unified-look design pattern. Uses Bubble-Card + card-mod + reusable Bubble-Card modules. |
| [`skills/ha-integration-fix/`](skills/ha-integration-fix/) | End-to-end workflow to diagnose and fix a bug in an HA custom integration: fork, reproduce, patch, test, PR, and post a workaround comment on the integration issue. |
| [`skills/ha-custom-card-development/`](skills/ha-custom-card-development/) | Build, test, and deploy a Lovelace custom card from scratch (TypeScript + Lit, single-file ES module). Covers Lovelace lifecycle contract, Lit reactivity, theming + accessibility, visual editor, dev/deploy workflow, HACS publishing. |

## Reading order for a new bug

1. [`LESSONS.md`](LESSONS.md) - cross-cutting patterns from past fixes worth revisiting before diving in.
2. [`references/cheatsheet.md`](references/cheatsheet.md) - HA operations that come up repeatedly (restart, log extraction, container shell, config entry reload).
3. [`references/ha-api.md`](references/ha-api.md) - REST + WebSocket endpoints, token locations.
4. [`references/memray-on-haos.md`](references/memray-on-haos.md) - allocation profiling a live HA process on HAOS (Alpine/musllinux).
5. [`integrations/_template/`](integrations/_template/) - skeleton to copy when starting a new integration investigation.

## Notes

All commands reference `<ha-host>` and `<ha-vm-id>` instead of real hostnames / VM IDs. Substitute your own values. Commands assume an HA OS setup on a Proxmox VM with the QEMU guest agent; adapt paths if you run HA differently.
