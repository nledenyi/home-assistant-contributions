# pytoyoda + ha_toyota: smart status refresh + cache-expiry mitigation

The third track on this account, distinct from the two earlier tracks
([summary schema drift](README.md#schema-drift-fix-ha_toyota278--pytoyoda249)
and [memory leak](memory-leak-fix.md)).

## At a glance

| | |
|---|---|
| Component | `pytoyoda` (Python client) + `ha_toyota` (HA custom integration) |
| Tracking issues | [ha_toyota#87](https://github.com/pytoyoda/ha_toyota/issues/87), [#137](https://github.com/pytoyoda/ha_toyota/issues/137), [#157](https://github.com/pytoyoda/ha_toyota/issues/157), [#168](https://github.com/pytoyoda/ha_toyota/issues/168), [#190](https://github.com/pytoyoda/ha_toyota/issues/190), [#229](https://github.com/pytoyoda/ha_toyota/issues/229), [#281](https://github.com/pytoyoda/ha_toyota/issues/281), [#284](https://github.com/pytoyoda/ha_toyota/issues/284), [pytoyoda#161](https://github.com/pytoyoda/pytoyoda/issues/161) |
| Status | **PRs open as of 2026-04-26**: [pytoyoda#252](https://github.com/pytoyoda/pytoyoda/pull/252) + [ha_toyota#286](https://github.com/pytoyoda/ha_toyota/pull/286), both ready-for-review. Implemented, deployed live on a 2-vehicle account, validated on a real drive, soaking clean. |
| Fork branches | [`nledenyi/pytoyoda:rate-limit-resilience`](https://github.com/nledenyi/pytoyoda/tree/rate-limit-resilience) (head `2b4a1d4`, logical-commit chain, lint-clean and pytest-green), [`nledenyi/ha_toyota:rate-limit-resilience`](https://github.com/nledenyi/ha_toyota/tree/rate-limit-resilience) (head `55c96c3` post-Gemini-fix, logical-commit chain) |
| Public engagement | **Install gist v2** [772fd3d68a445313fec56fae430b8f01](https://gist.github.com/nledenyi/772fd3d68a445313fec56fae430b8f01) (2026-04-27), older root-cause gist [239ee99cfb171bc57a5027bb270a322a](https://gist.github.com/nledenyi/239ee99cfb171bc57a5027bb270a322a) (2026-04-25), and 2026-04-27 follow-up comments on [#281](https://github.com/pytoyoda/ha_toyota/issues/281#issuecomment-4323214244), [#282](https://github.com/pytoyoda/ha_toyota/issues/282#issuecomment-4323217406), [#284](https://github.com/pytoyoda/ha_toyota/issues/284#issuecomment-4323219409), [#278](https://github.com/pytoyoda/ha_toyota/issues/278#issuecomment-4323222323) plus the earlier first-analysis comments on [#281](https://github.com/pytoyoda/ha_toyota/issues/281#issuecomment-4316677107) and [#284](https://github.com/pytoyoda/ha_toyota/issues/284#issuecomment-4316675909) |

## Symptoms

The umbrella complaint across the linked issues is the same: **lock /
door / window / hood state shows stuck-stale values** (sometimes for
hours, sometimes days). When the cache happens to be empty entirely
(e.g. fresh integration install), every door/window/lock binary sensor
falsely renders as `open` / `unlocked` because of a separate null-render
bug ([#87](https://github.com/pytoyoda/ha_toyota/issues/87)). On top of
that, periodic `429 APIGW-403 "Unauthorized"` errors flood the HA log
even at modest poll cadences.

## Root cause (and the road to it)

The simple "burst rate limiter" model that explained the easy 429s
([per-endpoint serialisation](README.md) fixed those last week) does
NOT explain stuck-stale lock state. We went through five wrong
hypotheses over an afternoon before landing on the right one.

The `GET /v1/global/remote/status` endpoint reads a **server-side
cache**, not a live device. The cache is populated only via:

1. The vehicle's modem auto-reporting (fires primarily on park
   transitions, not continuously during driving)
2. An explicit `POST /v1/global/remote/refresh-status` to wake the
   modem and request a populate

Without one of those, the cache stays at its last value indefinitely.
A `GET` against an empty/stale cache returns `429+APIGW-403` even though
no rate limit has actually been exceeded - the gateway uses the same
error envelope it uses for the burst limiter.

The Toyota Android app uses both endpoints in a two-stage pattern:
POST to wake, then poll GET until `occurrence_date` advances. Pytoyoda
historically only implemented the GET. That's the gap.

For the full hypothesis-elimination chronology, see the wiki:
`/nvme-storage/docker_data/syncthing/vault/ApoObsidian/wiki/http-429-investigation-methodology.md`
(case study at the bottom).

## Fix

### pytoyoda side

- New endpoint constant `VEHICLE_GLOBAL_REMOTE_REFRESH_STATUS_ENDPOINT`
- New `Api.refresh_vehicle_status(vin)` method, sends `POST` with the
  required four-field body `{deviceId, deviceType, guid, vin}`. Returns
  a `RefreshStatusResponseModel`; success is `payload.return_code ==
  "000000"`. Without the body the gateway returns 500 - this is the
  trap [pytoyoda#77](https://github.com/pytoyoda/pytoyoda/pull/77) and
  [ha_toyota#302](https://github.com/pytoyoda/ha_toyota/pull/302) fell
  into when they tried this endpoint with an empty body and concluded
  it was unsupported.
- New `Vehicle.refresh_status()` thin wrapper.
- New `Vehicle.update(skip=..., only=...)` parameters so callers can
  fetch a subset of endpoints. Used by the integration's smart strategy
  to fetch `/status` separately from the rest of the sweep.

### ha_toyota side: smart-refresh strategy

A pure-function decision tree (`refresh_strategy.py`) gates WHEN to
issue the wake POST. Every cycle, per VIN, one of four actions:

| Action | When | What |
|---|---|---|
| `POST_THEN_GET` | `just_stopped` (odometer delta detected then stationary), `service_call`, `idle_wake`, in-progress followup window | POST `/refresh-status`, then poll GET `/status` for up to 25 s until `occurrence_date` advances |
| `GET_ONLY` | `cache_stale` (cache > N min old), `cache_empty` (first cycle ever) | Just GET; no wake |
| `SERVE_FROM_CACHE` | Cache fresh, no triggers | Re-inject the previous cycle's `/status` payload into the new `Vehicle` (each cycle gets a fresh `Vehicle`); LockStatus serves the cached value |
| `HARD_DISABLED` | User toggle off, OR auto-disabled after 2 Layer 1 rejections from the gateway | Fall through to a single legacy `/status` GET, swallow failures |

Wake POSTs come in pairs by default (configurable 1-5): one on the
just-stopped cycle, one on the next cycle. Cycle-count based, not
wall-clock based - polling-interval-agnostic.

### Bundled fix: ha_toyota#87 null-render

The same PR fixes a long-standing rendering bug. Old code used
`not getattr(getattr(...), 'closed', None)` for door/window/lock
inversion. When the field is missing (`None`), `not None == True`, so
sensors falsely rendered `open` / `unlocked`. Replaced with an
`_inv_or_none(value)` helper that returns `None if value is None else
not value`, applied across all 15 binary_sensor lambdas. HA renders
`None` as `unknown`, which is the right answer when we genuinely have
no data.

### New entities

- 1 button per vehicle: `button.<alias>_refresh_vehicle_status`
- 2 new diagnostic sensors per vehicle: `..._status_last_reported_by_car`
  (timestamp = the gateway cache's `occurrence_date`) and
  `..._status_refresh_state` (enum: active / soft_disabled_unreachable
  / hard_disabled_auto / hard_disabled_user)
- 1 new HA service `toyota.refresh_vehicle_status` for use in
  automations

### New options-flow toggles

7 new options under Settings → Integrations → Toyota → Configure:
master switch, opt-in idle wake (off by default), idle wake interval
(4-72 h), failed-wake threshold for soft-disable (1-10), max cache age
before forced GET (5-180 min), polling interval (5-60 min), wake POSTs
per stop event (1-5).

## Real-drive validation (2026-04-25)

After the deploy, drove the test RAV4 ~15 min. Strategy timeline played
out exactly per design:

```
13:59:45  trigger=currently_moving        (caught the 7 km odometer delta)
14:05:53  trigger=just_stopped            POST -> 000000  (occ 12:18 -> 17:09:29)
14:18:09  trigger=just_stopped_followup   POST -> 000000  (occ 17:09 -> 17:21:55)
```

End-to-end. Both wake POSTs accepted. Cache layer kept lock state
stable across SERVE_FROM_CACHE cycles in between.

## Empirical findings worth recording

Three observations from the live deploy that contradict assumptions
made earlier in the investigation:

1. **A bare GET reads stale cache, period.** Manual physical activity
   (door open + close on a parked car) does NOT propagate to the
   gateway cache. ECU events go nowhere; only modem reports do.
2. **Toyota's modem auto-reports on park, not during driving.**
   Mid-drive bare GETs return stale cache. Post-stop bare GETs return
   fresh data ~30 s old. Implication: a "GET first, conditional POST"
   optimisation is possible (skip the wake if the cache is already
   warm) but not yet implemented; logged for after the soak.
3. **The wake POST does NOT eliminate all 429s.** Some remain
   stochastically even after a successful wake and fresh cache. The
   original docs ("returns 429 - no rate limit was actually exceeded")
   were too strong; the README was reworded to hedge: "frequently
   returns 429, often without obvious correlation to call rate."

## Design refinements after observing the strategy live

Two changes landed post-real-drive (now in `d3c3e12`), both motivated
by what we saw rather than what we'd planned:

- **Cycle-count followup** instead of a 12-min wall-clock deadline.
  The original "12 min between the two POSTs" was a guess. Cycle-count
  is simpler, polling-interval-agnostic, and exposed as a config
  option `post_count_per_stop` (default 2, range 1-5).
- **No GETs during driving when cache is fresh.** Original strategy
  GET'd `/status` every cycle while driving. Lock/door/window state is
  static during a drive; data we DO want (odometer, fuel, location)
  comes from telemetry/location endpoints we already fetch. Refreshing
  `/status` mid-drive just adds 429-risk for no observable benefit.
  Dropped `currently_moving` from the should_get OR-chain.

Combined effect on a typical daily-driven car at 6-min polling: 2 wake
POSTs per stop event + occasional GETs, vs. the original spec's 2 wake
POSTs + ~12 GETs over the same drive cycle. About 6× reduction in
`/status` traffic per drive event.

## What's deferred

Not blocking the PR; logged for later:

- **GET-first conditional POST** for any wake-eligible trigger. If the
  GET already shows fresh cache (modem auto-reported on park), skip
  the POST. Halves wake POSTs in normal operation. Bigger refactor;
  soak the current shape first.
- **Time-bounding the `just_stopped` trigger** under coarse polling.
  With 1h polling, just-stopped fires up to 1h late. Discussed and
  decided against - the polling interval IS the user's aggressiveness
  knob, and `post_count_per_stop=1` covers the use case for users on
  coarse polling. Adding a hidden time-bound heuristic on top would
  reduce the user's agency.

## Files in this directory

This write-up doesn't ship a separate cheatsheet because the README and
the integration's options-flow UI carry the user-facing documentation.
For methodology context see:

- `/home/claude/home-assistant/integrations/pytoyoda/rate-limit-remediation-plan.md`
  (Addenda 1-6 = the full design spec)
- `/nvme-storage/docker_data/syncthing/vault/ApoObsidian/wiki/toyota-api-behavior.md`
  (the cache-expiry section)
- `/nvme-storage/docker_data/syncthing/vault/ApoObsidian/wiki/http-429-investigation-methodology.md`
  (the hypothesis-elimination methodology, lessons 9-12 from this
  track)
