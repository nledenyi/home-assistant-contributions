# pytoyoda / ha_toyota fixes

Two independent bugs surfaced by the same community-reported thread:

1. **Summary schema drift** in `pytoyoda`: `TypeError` / `AttributeError` crashes when Toyota's `/v1/trips` returns partial payloads. See below.
2. **Memory leak** in `ha_toyota`: the `_run_pytoyoda_sync` wrapper allocates a fresh asyncio event loop per call, leaking ~500 KB per invocation. Separate issue, separate PR. See [`memory-leak-fix.md`](memory-leak-fix.md) for the full walk-through (diagnosis, git blame, measurement methodology, patch, validation).

| Fix | Repo | Branch | Tracking issue | PR state |
|---|---|---|---|---|
| Summary schema drift | pytoyoda | [`bug/summary-none-handling`](https://github.com/nledenyi/pytoyoda/tree/bug/summary-none-handling) | [ha_toyota#278](https://github.com/pytoyoda/ha_toyota/issues/278) | [pytoyoda#249](https://github.com/pytoyoda/pytoyoda/pull/249) **MERGED** 2026-04-27 11:24Z by deejay1. Competing minimal patch [pytoyoda#251](https://github.com/pytoyoda/pytoyoda/pull/251) auto-closed via overlap. |
| Memory leak | ha_toyota | [`bug/memory-leak-direct-await`](https://github.com/nledenyi/ha_toyota/tree/bug/memory-leak-direct-await) | [ha_toyota#282](https://github.com/pytoyoda/ha_toyota/issues/282) | [ha_toyota#283](https://github.com/pytoyoda/ha_toyota/pull/283) open, **approved**. Reporter @alpy-nz and @Paja-git both confirmed fix; @arhimidis64 reports residual ramp in their specific install, memray follow-up identified the residual cause (per-request httpx client) which is fixed in pytoyoda#252 (merged). |
| Rate-limit resilience | pytoyoda | `rate-limit-resilience` (now in upstream main) | [ha_toyota#281](https://github.com/pytoyoda/ha_toyota/issues/281), [#284](https://github.com/pytoyoda/ha_toyota/issues/284) | [pytoyoda#252](https://github.com/pytoyoda/pytoyoda/pull/252) **MERGED** 2026-04-27 11:47Z by deejay1. 5 commits: persistent httpx client, retry-with-backoff, serialised endpoint fetch, `Vehicle.refresh_status()` POST + `update(skip=, only=)`, off-loop SSL context. **Released as pytoyoda v5.1.0** on PyPI 2026-04-27 12:04Z. |
| Smart status-refresh strategy + #87 null-render | ha_toyota | `rate-limit-resilience` | [ha_toyota#87](https://github.com/pytoyoda/ha_toyota/issues/87), [#137](https://github.com/pytoyoda/ha_toyota/issues/137), [#157](https://github.com/pytoyoda/ha_toyota/issues/157), [#168](https://github.com/pytoyoda/ha_toyota/issues/168), [#190](https://github.com/pytoyoda/ha_toyota/issues/190), [#229](https://github.com/pytoyoda/ha_toyota/issues/229), [#284](https://github.com/pytoyoda/ha_toyota/issues/284) | [ha_toyota#286](https://github.com/pytoyoda/ha_toyota/pull/286) open, ready-for-review, manifest pin bumped to `pytoyoda>=5.1.0` (commit `2d63b2c`). Per-VIN per-cycle decision tree, retain-on-transient-failure, options-flow, 5 new diagnostic sensors, fault isolation, endpoint-tagged 429 logs. See [`smart-status-refresh.md`](smart-status-refresh.md). |
| Recent-trips sensor | ha_toyota + pytoyoda | `feat/recent-trips-sensor` + `feat/get-recent-trips` | [pytoyoda#244](https://github.com/pytoyoda/pytoyoda/issues/244) | [pytoyoda#253](https://github.com/pytoyoda/pytoyoda/pull/253) draft (`Vehicle.get_recent_trips()`); ha_toyota PR not yet pushed - soaking. New per-vehicle "Recent trips" sensor with rolling cache + delta-fetch on stop events. |

---

## Schema-drift fix (ha_toyota#278 / pytoyoda#249)

- **Component package**: `pytoyoda` (used by Toyota EU community HA integration)
- **HA custom_components folder**: `/config/custom_components/toyota`
- **Upstream repo**: https://github.com/pytoyoda/pytoyoda
- **Integration repo**: https://github.com/pytoyoda/ha_toyota
- **Bug reported in**: [ha_toyota#278](https://github.com/pytoyoda/ha_toyota/issues/278)
- **Fix PR**: [pytoyoda/pytoyoda#249](https://github.com/pytoyoda/pytoyoda/pull/249)
- **Status**: PR open, workaround documented in the issue comment
- **Fork branch**: `nledenyi/pytoyoda:bug/summary-none-handling`

## Symptoms

Every entity on the account goes `unavailable` in HA. Log shows
`TypeError: unsupported operand type(s) for +=: 'NoneType' and 'NoneType'`
in `_generate_weekly_summaries` or `_generate_yearly_summaries`. After
the defensive commits, the next failure mode is
`AttributeError: 'NoneType' object has no attribute 'length'` in
`Summary.distance`, with sensors stuck on `unavailable` or flipping to
`unknown` but never showing kilometres.

## Root cause

Schema drift. Toyota's `/v1/trips` currently returns only 4 of the 11
fields `_SummaryBaseModel` expects at the histogram summary level
(`length`, `duration`, `averageSpeed`, `fuelConsumption`). Every field
except `fuelConsumption` lacked `default=None`, so partial payloads
failed validation. `CustomEndpointBaseModel` wraps fields with
`invalid_to_none`, which silently nulled the entire summary. The crashes
were downstream consequences, not the real problem.

The raw API always contained real data (hundreds of km / month). The
model was rejecting it.

## Fix

Two commits on `bug/summary-none-handling`:

1. Give every `_SummaryBaseModel` field a `None` default. Root cause
   fix - lets Pydantic parse partial payloads.
2. Harden weekly/yearly/daily/monthly aggregation against `None`
   field values. Defensive follow-up covering the case where Toyota
   really does omit a day.

See [pytoyoda#249](https://github.com/pytoyoda/pytoyoda/pull/249) for the full PR description (merged 2026-04-27).

## Reproduction

See [`probes/probe_toyota.py`](probes/probe_toyota.py) and
[`probes/probe_toyota3.py`](probes/probe_toyota3.py). Credentials are
pulled from `$TOYOTA_USER` / `$TOYOTA_PASS` environment variables.

`probe_toyota.py` lists vehicles and dumps parsed summary/histograms for
the current month (shows the bug as "all None" pre-fix, real numbers
post-fix).

`probe_toyota3.py` dumps the raw JSON from the underlying HTTP endpoint,
bypassing pydantic. This was the smoking gun: the API returns real data
while the model drops it.

`probe_midnight.py` exercises the midnight local-time reset to verify
the day sensor transitions cleanly to the "no trips yet today" state.

`probe_quick.py` is a one-shot health check: logs in, fetches both
vehicles, prints `fuel/range/odo`. Useful when HA entities go
unavailable and you want to know whether the Toyota API itself is
down or HA's session has just gotten invalidated. Run with:

```bash
TOYOTA_USER=... TOYOTA_PASS=... /tmp/pytoyoda_probe/bin/python3 probe_quick.py
```

**Caveat:** run this sparingly. Each invocation is a fresh
`MyT(...).login()`, and stacking several in quick succession has
rate-limited HA's long-lived session in practice (see LESSONS.md).

## Workaround

User-facing workaround posted to [ha_toyota#278](https://github.com/pytoyoda/ha_toyota/issues/278). Short version:

```bash
docker exec -it homeassistant /bin/bash
pip install --force-reinstall --no-deps \
  "git+https://github.com/nledenyi/pytoyoda@bug/summary-none-handling"
ha core restart
```

`--no-deps` matters - without it, pip bumps `pyjwt`/`pydantic`/`httpx`
to newer versions that conflict with HA's pins.

## Out of scope (flagged in PR)

`_SummaryBaseModel.__add__` computes
`average_speed = (self.average_speed + other.average_speed) / 2.0`,
which is not a true running average. Pre-existing, unrelated to the
crash.

## Competing PR

A minimal patch for the same crash was posted independently as
[pytoyoda#251](https://github.com/pytoyoda/pytoyoda/pull/251). Both
PRs target the same `TypeError`, but they differ in scope:

- **#251** wraps the two `build_summary += x` calls with `add_with_none`. Stops the crash.
- **#249** stops the crash the same way in effect, plus the root cause that produces the `None` summaries in the first place: Toyota's `/v1/trips` only returns 4 of the 11 `_SummaryBaseModel` fields, so `invalid_to_none` silently drops the whole summary. Adds `default=None` on each field, rewrites `__add__` to return a new instance instead of mutating `self`, fixes a second latent bug where `add_with_none(build_hdc, ...)`'s return value was discarded, and ships a unit test for the partial-payload case.

I flagged the overlap on #251 so reviews didn't step on each other. Maintainer chose to merge #249 (broader) and #251 was auto-closed.

## Lessons

Cross-cutting lessons moved to [`../../LESSONS.md`](../../LESSONS.md).
The key integration-specific one: when a pydantic-based API client
returns "no data", always dump the raw HTTP payload before assuming the
API is broken. Silent validation-fallback wrappers can mask live data.
