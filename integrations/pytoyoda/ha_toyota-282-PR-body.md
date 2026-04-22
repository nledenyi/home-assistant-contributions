# PR title
`fix: eliminate event-loop churn that leaks ~500 KB per pytoyoda call`

# PR body

## Environment

- HA Core 2026.4.2 (reproduced on a HAOS 17.2 VM per [#282](https://github.com/pytoyoda/ha_toyota/issues/282))
- pytoyoda 5.0.0 (including the #249 schema-drift branch installed for testing)
- 2-vehicle account on the Toyota EU community integration

## Current behaviour

HA Core's RSS grows linearly while the Toyota integration is polling, and plateaus when the integration is disabled. Reported by @alpy-nz in #282 with a screenshot showing a clean ramp-then-flat curve. I reproduced it on a second HA install; see "Measurement" below.

## Root cause

`custom_components/toyota/__init__.py` wraps every `pytoyoda` call in:

```python
def _run_pytoyoda_sync(coro: Coroutine) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
```

...and invokes it via `hass.async_add_executor_job(_run_pytoyoda_sync, X)` for `client.get_vehicles`, `vehicle.update`, and the four `vehicle.get_current_*_summary` methods. For a 2-vehicle account that's ~11 fresh `asyncio.new_event_loop()` instances per coordinator refresh.

Each new event loop causes pytoyoda to construct a fresh `httpx.AsyncClient` inside `async with` (the `with` scope is bound to the throwaway loop), which triggers a fresh SSL context + CA-bundle load + DNS resolver + connection pool, all of which are torn down when the loop closes. A small amount of non-reclaimed state remains each cycle (OpenSSL session entries, httpcore transport objects, asyncio internals), and it accumulates linearly over time.

The wrapper was introduced in #171 to silence HA's "Detected blocking call to `load_verify_locations` inside the event loop" watchdog warning. The warning itself is legitimate (`httpx.AsyncClient()` construction loads the CA bundle synchronously), but relocating the entire async call chain into throwaway event loops trades the warning for the leak.

## Measurement

Reproduced on my own HA install by sampling HA Core RSS every 120 seconds in two phases: a 60-min **baseline** with no Toyota coordinator refreshes firing, followed by a 180-min **test** with refreshes driven at a 15-min interval via `homeassistant.update_entity`. (My install runs the coordinator with `pref_disable_polling=true` and a 15-min external trigger because the default 360s interval hits Toyota's API rate limiter on my account; either way the per-refresh workload is the same as the integration's default.)

**Pre-fix** (original `_run_pytoyoda_sync`):

| Phase | Duration | Refreshes | Drift | Slope |
|---|---|---|---|---|
| Baseline | 60 min | none | -4 MB | -2.5 MB/h |
| Test | 180 min | every 15 min | +68 MB | +24.8 MB/h |

Net Toyota-attributable leak rate: **+27 MB/hour at 15-min refresh**. Extrapolated to the integration's default 360s refresh: ~60 MB/hour → ~1.4 GB/day, which matches @alpy-nz's screenshot slope.

**Post-fix** (this PR applied, otherwise identical setup):

| Phase | Duration | Refreshes | Drift | Slope |
|---|---|---|---|---|
| Baseline | 60 min | none | +21 MB | +26.5 MB/h |
| Test | 180 min | every 15 min | +35 MB | +9.1 MB/h |

The post-fix baseline drift is HA finishing its normal startup ramp (HA had only been up ~17 min when the phase started), not a continuing leak. The test phase grows **slower** than the baseline — the opposite of what a persistent leak would produce. Per-30-min bins in the test phase show decelerating growth consistent with asymptotic warmup to steady state.

## Expected behaviour

`pytoyoda.client.MyT` exposes an async public API. `DataUpdateCoordinator.update_method` is expected to be a coroutine function and runs in HA's main event loop. Calling those coroutines directly with `await` is the documented pattern. No new event loop needed, no executor thread needed.

## Proposed change

Remove `_run_pytoyoda_sync` and the `_sync_login` inner helper. Replace every `hass.async_add_executor_job(_run_pytoyoda_sync, X)` with `await X`. Move `MyT(...)` construction out of `hass.async_add_executor_job` (the constructor does no I/O).

Diff: `+13 / -55` lines in `custom_components/toyota/__init__.py`. No other files touched, no dependency changes, no API changes.

## Known regression and follow-up plan

This PR reintroduces the `load_verify_locations` blocking-call warning at setup time and again whenever pytoyoda constructs a new `httpx.AsyncClient` during a refresh (which it does inside `async with` per request in `pytoyoda/controller.py`).

The warning is noisy but not fatal; the memory leak was continuous and would eventually OOM. Trade is clearly in favour of this change.

Permanent fix for the blocking call needs a coordinated change across both repos so pytoyoda accepts an externally-supplied `httpx.AsyncClient`, and ha_toyota passes `homeassistant.helpers.httpx_client.get_async_client(hass)` at setup. That eliminates the warning, reuses TCP/TLS via HTTP keep-alive (which also plausibly reduces the 429 rate-limit rate by avoiding fresh TLS sessions), and is the standard HA integration pattern. I'll open it as a separate PR against pytoyoda once this lands.

## Tests

`poetry run pre-commit run --all-files` clean on the branch (see commit SHA below).

No new unit tests — the change is a deletion of plumbing with no new code path to cover. End-to-end validation via the measurement above.

## Checklist

- [x] Conforms to branch naming (`bug/...`) per CONTRIBUTING.md
- [x] `poetry run pre-commit run --all-files` clean
- [x] Tested end-to-end on HA Core 2026.4.2 with a 2-vehicle account
- [x] Before/after RSS trace reproduces the reported leak and shows it eliminated
- [x] No functional regression — odometer sensor populated correctly post-patch

Addresses #282.
