# pytoyoda / ha_toyota fixes

Two independent bugs surfaced by the same community-reported thread:

1. **Summary schema drift** in `pytoyoda`: `TypeError` / `AttributeError` crashes when Toyota's `/v1/trips` returns partial payloads. See below.
2. **Memory leak** in `ha_toyota`: the `_run_pytoyoda_sync` wrapper allocates a fresh asyncio event loop per call, leaking ~500 KB per invocation. Separate issue, separate PR. See [`memory-leak-fix.md`](memory-leak-fix.md) for the full walk-through (diagnosis, git blame, measurement methodology, patch, validation).

| Fix | Repo | Branch | Tracking issue | PR state |
|---|---|---|---|---|
| Summary schema drift | pytoyoda | [`bug/summary-none-handling`](https://github.com/nledenyi/pytoyoda/tree/bug/summary-none-handling) | [ha_toyota#278](https://github.com/pytoyoda/ha_toyota/issues/278) | [pytoyoda#249](https://github.com/pytoyoda/pytoyoda/pull/249) open, CI green, awaiting review |
| Memory leak | ha_toyota | [`bug/memory-leak-direct-await`](https://github.com/nledenyi/ha_toyota/tree/bug/memory-leak-direct-await) | [ha_toyota#282](https://github.com/pytoyoda/ha_toyota/issues/282) | PR draft ready, locally validated; see [`ha_toyota-282-PR-body.md`](ha_toyota-282-PR-body.md) |

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

See [`PR-249-body.md`](PR-249-body.md) for the full PR description.

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

See [`ha_toyota-278-comment.md`](ha_toyota-278-comment.md) for the
user-facing workaround posted to the issue. Short version:

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

## Lessons

Cross-cutting lessons moved to [`../../LESSONS.md`](../../LESSONS.md).
The key integration-specific one: when a pydantic-based API client
returns "no data", always dump the raw HTTP payload before assuming the
API is broken. Silent validation-fallback wrappers can mask live data.
