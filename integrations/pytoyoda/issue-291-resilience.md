# Issue #291 follow-ups: per-endpoint resilience + smart-strategy hardening

[ha_toyota#291](https://github.com/pytoyoda/ha_toyota/issues/291) was filed 2026-04-28 a day after `ha_toyota v2.3.0` shipped. The reporter (sciurius) couldn't set the integration up at all - "Failed to set up" on every restart. Two other users chimed in (Nickduino, LukasVogel123) with similar-sounding "smart refresh broken" symptoms but very different log signatures. A fourth user (Paja-git) confirmed the third sub-pattern.

Triaging the thread surfaced **three distinct bugs** that needed three different fixes. Worth writing up for two reasons: the empirical-falsification dataset is itself the deliverable, and the way the per-endpoint and smart-strategy fixes interlock as a coherent resilience story is genuinely interesting design work.

| Bucket | Symptom | Fix | Tester confirmation |
|---|---|---|---|
| **1. `GET /climate-settings` persistent 500** | Setup fails because the climate fetch raises and aborts `Vehicle.update()`. | [pytoyoda#258](https://github.com/pytoyoda/pytoyoda/pull/258) draft - `optional=True` flag on `EndpointDefinition`. Failures on optional endpoints are caught + recorded, the cycle continues. | sciurius "BINGO!" 2026-04-29 |
| **2. `POST /refresh-status` 500** | Wake POST 5xx. Counters never advance, entities go stale. | [ha_toyota#295](https://github.com/pytoyoda/ha_toyota/pull/295) draft - wrap the POST in try/except, collapse failure paths, bare GET fallback, service-call bypass for both disable forms, auto-clear on success. | Awaiting @Nickduino + @LukasVogel123 fork-test |
| **3. Wrong capability flag (= [#246](https://github.com/pytoyoda/ha_toyota/issues/246))** | `features.climate_start_engine: False` but `/climate-settings` returns data, so no climate entity created in HA even though endpoint works. | Open. Switching the gate to `extended_capabilities.climate_capable` would help D (Paja-git). B (AYGO X) is a sub-case needing MyT-app disambiguation. | n/a (no PR yet) |

This file walks through Buckets 1 and 2 - the two PRs already in flight. The 4-vehicle empirical dataset is at [`climate-endpoint-dataset.html`](https://toyota-probe.ledenyi.com/) (live mirror) and [`climate-endpoint-dataset.md`](../../home-assistant/integrations/pytoyoda/climate-endpoint-dataset.md) (local source).

## Bucket 1 - per-endpoint optional flag (pytoyoda#258)

### The empirical falsification

Sciurius reported the integration fails to set up; every other user on #291 had a working integration with degraded behaviour. The diagnostic probe revealed that his `GET /v1/global/remote/climate-settings` returns HTTP 500 (`responseCode: ONE-GLOBAL-RS-40000`, `"Command execution interrupted"`) on every retry, deterministically. Other endpoints on the same account return 200 cleanly.

Initial hypothesis: some capability flag predicts the failure. If we can find it, we can pre-flight-check and skip the call. Built a 4-vehicle dataset to test. Result:

| Vehicle | `climate_start_engine` | `climate_capable` | `/climate-settings` outcome |
|---|---|---|---|
| A (RAV4 '19) | F | F | 200 with empty payload |
| B (AYGO X '22) | F | F | 200 with populated payload |
| C (sciurius Corolla '23) | **T** | **T** | **500 persistent** |
| D (Paja-git Lexus NX '21, post-renewal) | F | T | 200 with populated payload |

Falsified hypotheses, in order:

1. `climate_capable: False` predicts the 500. **No** - C has it True.
2. Any single climate flag predicts the 500. **No** - C has every climate flag True.
3. The 500 is intermittent. **No** - 3/3 consistent with deterministic error code.
4. The endpoint shape is wrong (extra header, missing param). **No** - probed by removing the VIN header; gateway returns 403 with explicit `"Missing required field: vin"`. Pytoyoda's request shape matches the official Toyota app exactly.

Conclusion: the 500 is server-side account state (subscription, account migration, region, gateway-level provisioning), with no client-visible flag predicting it. Subsequent observation: D's renewal of an expired Smart Car subscription flipped his `/climate-settings` from 200-empty to 200-populated overnight - confirming subscription state is one of the axes for SOME accounts, but doesn't explain C (whose subscription is presumably active given other features work).

### The fix

If no client flag predicts the failure, no pre-flight gate works. The right shape is to make the failure non-fatal at the library layer.

`Vehicle.update()` iterates a list of endpoint definitions, fetching each in turn. Pre-fix, any single endpoint raising aborts the loop and the whole vehicle's data is unavailable. Added `optional: bool = False` to `EndpointDefinition`:

- Default `False` preserves existing behaviour - failures on truly required endpoints (vehicle list, fundamental status) still propagate.
- Marked `climate_settings` and `climate_status` as `optional=True`. On exception, the failure is caught, recorded in `Vehicle._endpoint_errors[name]`, the previous payload is cleared from `_endpoint_data` (so `vehicle.climate_settings` returns None instead of stale data), and the loop continues to fetch the rest.

Why a library-side fix and not a wrapper-side catch:

- Single source of truth: which endpoints are "optional" lives next to where they're defined.
- Affects every consumer of pytoyoda equally; the integration only needs a manifest pin bump to opt in.
- Endpoints that should never be silently swallowed (vehicle list, login) keep `optional=False`.

### Validation

- 119 unit tests pre-existed; added 6 new tests covering the optional path: required-failure-propagates, optional-failure-swallowed-and-recorded, errors-reset-each-cycle, skip-doesnt-record-as-error, only-filter-still-respects-optional, optional-failure-clears-stale-data.
- Live regression test on a healthy account (RAV4 + AYGO X, neither 500s): integration sets up cleanly, all entities populate, no behavioural change for the success path.
- Tester confirmation: sciurius pip-installed the fork branch, restarted HA, integration set up successfully on his persistent-500 account ("BINGO!").

### Gemini follow-up

Gemini code-assist flagged two medium-priority concerns on the original commit, both legit and addressed in a follow-up:

- Stale data on failure: original code kept the previous-cycle's `_endpoint_data[name]` entry on caught exception, so downstream getters returned old data instead of None. Fix: pop the entry on caught failure.
- Tuple brittleness: `_endpoint_collect` stored 3-tuples `(name, function, optional)` instead of `EndpointDefinition` objects directly. Refactor: store the dataclass.

## Bucket 2 - smart-strategy resilience (ha_toyota#295)

### Two simultaneous symptoms, one missing try/except

Nickduino reported persistent 500s on `POST /v1/global/remote/refresh-status` flooding his log every coordinator cycle. The smart-strategy soft/hard-disable logic from [`smart-status-refresh.md`](smart-status-refresh.md) (PR #286, v2.3.0) was supposed to handle exactly this case - vehicles that don't support the wake POST should auto-disable after N consecutive failures and fall back to the legacy bare GET path. But:

- His `<alias>_status_refresh_state` sensor stayed `active` indefinitely. Auto-disable never fired.
- His parking-location entity stayed frozen at "home" while the car was actually away on someone else's drive. Entities went stale.

Two distinct symptoms. Tracing the call path revealed both came from a single missing try/except around the POST in `_execute_post_then_get`:

```
DataUpdateCoordinator
  -> async_get_vehicle_data
    -> for each vehicle:
      try:
        -> _refresh_one_vehicle:
          # Phase 1: vehicle.update(skip=["status"])  - SUCCEEDS, mutates vehicle._endpoint_data
          # Decision: returns POST_THEN_GET
          -> _enact_decision -> _execute_post_then_get:
            -> vehicle.refresh_status()  # POST raises 5xx after pytoyoda retries exhaust
            # ❌ no try/except wrap; exception propagates out

          # ↓ ↓ ↓ NEVER RUNS ↓ ↓ ↓
          # Counter increments live INSIDE _enact_decision, gated on
          # `return_code != "000000"` - 5xx exception path bypasses them.
          # Bookkeeping (trips manager, movement, diag state) skipped.
          # `return VehicleData(...)` skipped.

        last_good_per_vin[vin] = vehicle_data  # ❌ never runs
      except (ToyotaApiError, ...):
        # Coordinator's outer catch fires, serves the previous cycle's
        # cached VehicleData. Phase 1's fresh data is lost.
```

So:

- **Symptom A (no auto-disable)**: `consecutive_post_rejections` is advanced inside the `if return_code != "000000":` branch, which a 5xx exception path never reaches. Counter stuck at 0 forever.
- **Symptom B (entities go stale)**: Phase 1 already had fresh telemetry / location / climate data in `vehicle._endpoint_data`, but the propagating exception skipped the caller's `last_good_per_vin[vin] = vehicle_data` line at the coordinator level. The cache layer never sees the fresh data; entities serve the previous cycle's snapshot.

### The bundle

What started as a one-line fix grew into four behavioural changes after ideating with the user:

1. **Wrap the POST + collapse failure paths**. `contextlib.suppress` for the same exception set the Layer 2 poll loop already catches. Exception path falls through to the existing Layer 1 failure branch (treated like a non-`000000` returnCode). Single accounting block instead of two duplicates.
2. **Bare GET fallback on Layer 1 failure**. Issue `vehicle.update(only=["status"])` - same call as the legacy `HARD_DISABLED` path - so /status entities still refresh in cycles before auto-disable kicks in.
3. **Service-call bypass for both HARD_DISABLED forms**. The previous code blocked service calls when either disable flag was set. The new code lets explicit service-call invocations through both `HARD_DISABLED_AUTO` (one-button recovery: refresh button -> POST -> on success, auto-clear the flag -> back to ACTIVE) and `HARD_DISABLED_USER` (matches HA convention everywhere else: polling toggle stops the cadence, manual calls still work; users can disable the strategy and drive POSTs from their own automations).
4. **Auto-clear `auto_disabled_status_refresh` on POST success**. A successful POST proves the gateway can process the endpoint; the assumption that triggered auto-disable is falsified. Lift the flag automatically. Recovery becomes one button-press instead of two-save options-flow toggle.

### State machine

| State | Trigger | What runs this cycle | Recovery |
|---|---|---|---|
| ACTIVE | default | full strategy, POST + GET as decided | n/a |
| SOFT_DISABLED_UNREACHABLE | `consecutive_failed_wakes` hit configurable threshold (default 3); in-memory only, doesn't survive HA restart | POST suppressed; GET still runs (so externally-warmed cache can lift the soft-disable) | `on_occurrence_advanced(...)` from any source (modem auto-report, MyT app activity, legacy GET) clears it |
| HARD_DISABLED_AUTO | `consecutive_post_rejections` hit hardcoded threshold 2; persisted in config-entry options, survives HA restart | bare GET legacy path (status data still flows) | (a) options-flow toggle OFF/ON, (b) **service call bypass + auto-clear on POST success** (new in this PR) |
| HARD_DISABLED_USER | user toggled `enable_status_refresh: False` | bare GET legacy path | options-flow toggle ON. Service call bypasses (new in this PR) but does NOT auto-flip the toggle. |

### Cadence vs capability split

Pre-PR semantics of `enable_status_refresh: False` conflated two things: "stop the automatic cadence" and "lock out the endpoint capability entirely". HA convention everywhere else (sensor platforms, integrations with polling) is the first one only - explicit service calls always go through. The PR aligns ha_toyota with that convention. Users who want true lock-out can simply not invoke the service. Doc updates land in `const.py` and `services.yaml` to reflect the new framing.

### Validation

- 28 pre-existing unit tests pass; added 3 new tests covering the strategy semantics: `service_call_bypasses_hard_disabled_auto`, `service_call_bypasses_hard_disabled_user`, `user_disable_blocks_non_service_triggers`.
- Live regression test on a healthy account (mine, RAV4 + AYGO X - neither 500s on `/refresh-status`): integration sets up cleanly via the combined-with-recent-trips branch, both vehicles `status_refresh_state = active`, no errors, recent-trips intact.
- Failure-path validation pending - requires testers whose vehicles' gateways actually 500 on `/refresh-status`. @Nickduino + @LukasVogel123 are the two known cases on #293; gist `c2ab349b` carries fork-install instructions, awaiting their results.

### Gemini follow-up

Gemini code-assist flagged two medium-priority concerns, both legit and addressed:

- Guard `async_update_entry` against re-entrance: a service-call retry that still 500s would otherwise re-persist an already-True flag every cycle and trigger redundant listener-driven reloads.
- Widen the bare-GET fallback's exception suppression to match the POST's set: `httpx.ConnectTimeout`, `httpcore.ConnectTimeout`, `asyncio.TimeoutError` added. Protects bookkeeping when the gateway is shaky enough that even the fallback times out.

## What this story illustrates

A single user-reported issue can mask three distinct bugs. The triage method: probe each reporter's specific symptoms, build a multi-data-point dataset that disambiguates them, then fix each as its own PR. The four-vehicle dataset turned what could have been a months-long thread of "fix one thing, break another" into three orthogonal fixes that ship independently.

The two-symptom-from-one-fix pattern in Bucket 2 is also worth internalising: when an integration has a "fetch many endpoints, then do bookkeeping at the end" structure, **each fetch must be isolated**. An exception in one fetch must not skip bookkeeping derived from a previous successful fetch in the same cycle. The retain-on-transient-failure layer at the coordinator level is too coarse to fix this alone; per-fetch try/except matters.

## Live artefacts

- **Dataset (HTML)**: https://toyota-probe.ledenyi.com/ - browsable 4-vehicle comparison.
- **Test fork install gists**:
  - [`260a93164a60defaa318f12d2cde9341`](https://gist.github.com/nledenyi/260a93164a60defaa318f12d2cde9341) - pytoyoda fork for Bucket 1 (sciurius confirmed).
  - [`c2ab349b506955efc9baa7320d1ffae8`](https://gist.github.com/nledenyi/c2ab349b506955efc9baa7320d1ffae8) - ha_toyota fork for Bucket 2 (testers pending).
- **Diagnostic probe**: [`2e8a08af6014713384eef9db05fd3562`](https://gist.github.com/nledenyi/2e8a08af6014713384eef9db05fd3562) - dumps the full feature-flag set + tries climate endpoints; what generated the 4-vehicle dataset.
