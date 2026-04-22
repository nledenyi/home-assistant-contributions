# ha_toyota memory leak - diagnosis and fix

Separate issue from the schema-drift fix in this folder. Tracked upstream at [ha_toyota#282](https://github.com/pytoyoda/ha_toyota/issues/282) (opened by `@alpy-nz` after they confirmed, in comments on [#278](https://github.com/pytoyoda/ha_toyota/issues/278), that HA Core RSS grew while the integration was enabled and went flat when they disabled it, with and without the schema-drift fix applied). Fix landed as PR [pytoyoda/ha_toyota#283](https://github.com/pytoyoda/ha_toyota/pull/283); the reporter confirmed it eliminates the ramp on their install before the PR was opened.

## TL;DR

- **Where the leak lives**: `custom_components/toyota/__init__.py`, specifically the `_run_pytoyoda_sync` helper added in PR [ha_toyota#171](https://github.com/pytoyoda/ha_toyota/pull/171) ("Avoid blocking calls") on 2025-10-02.
- **Rate**: ~500 KB per pytoyoda call. With 2 vehicles and default 6-min polling that's ~11 calls per refresh, ~110 calls/hour, ~**60 MB/hour** → **~1.4 GB/day**. With a 15-min workaround interval: ~25 MB/hour → **~600 MB/day**. Matches the ramp curve `@alpy-nz` reported.
- **Root cause**: `_run_pytoyoda_sync` creates a fresh `asyncio.new_event_loop()` per pytoyoda call. Each new loop brings up a new `httpx.AsyncClient` (pytoyoda's `controller.py` constructs one per request inside `async with`), which in turn creates a new SSL context, new DNS resolver, new connection pool. Tearing all of that down repeatedly leaves small amounts of non-reclaimed state behind (OpenSSL session cache, httpcore transports, asyncio internals). The process RSS grows linearly while the integration is polling.
- **Why it was written that way**: to silence HA's "Detected blocking call to `load_verify_locations` inside the event loop" watchdog warning. The warning itself is genuine (`httpx.AsyncClient()` construction triggers synchronous CA-bundle load), but moving the entire async call chain into throwaway event loops was the wrong layer to fix it.
- **Fix**: delete `_run_pytoyoda_sync` and `_sync_login`, replace every `hass.async_add_executor_job(_run_pytoyoda_sync, X)` with direct `await X`. Net: +13 / -55 lines in one file, no behavior change, no API change.
- **Trade-off**: the original blocking-call warning returns at setup time. Quieter than the leak (a one-time warning vs continuous memory growth); permanent fix is a coordinated pytoyoda + ha_toyota change to share a single `httpx.AsyncClient` across requests (future work).

## Diagnosis

The leak was reported by one user on an open issue where a different fix (schema drift) was being landed. Two corroborating data points in the thread:

- `@alpy-nz`: "memory use seems to be increasing ... flattens out when disabled."
- Same user, clarifying: "saw the same memory increase when the integration was in use and no fix applied."

That second line is decisive: the leak pre-dates the schema-drift fix, so the two are independent. First step was to walk the schema-drift PR diff and confirm nothing in it retains references or accumulates state. It doesn't - the new code uses `model_copy(deep=True)` and short-lived copies that are dereferenced as each `+=` completes.

Second step was git blame on `custom_components/toyota/__init__.py`. The `_run_pytoyoda_sync` wrapper and `_sync_login` pattern are both recent and deliberate, introduced in ha_toyota PR [#171](https://github.com/pytoyoda/ha_toyota/pull/171) with the explicit rationale:

> *"The Home Assistant warning 'Detected blocking call to load_verify_locations inside the event loop' should no longer appear, because all HTTP/SSL calls are now correctly executed in executor threads instead of blocking the main event loop."*

Python's `ssl.load_verify_locations` reads the CA bundle from disk - a synchronous file I/O - which HA's event-loop watchdog flags as a blocking call when it happens on the main loop. The PR moved every pytoyoda call into an executor thread wrapped in a fresh `asyncio.new_event_loop()`, which does silence the warning but in a way that allocates and tears down a complete networking stack per call. SSL context, connection pool, DNS resolver, asyncio internals - each short-lived, each retaining small amounts of non-reclaimed memory on close.

## Measurement

Goal: **prove the leak exists in nledenyi's HA, then prove the fix eliminates it** - empirical evidence to back the PR.

The measurement lives in a stub-driven harness that samples HA Core's RSS every 120 seconds and toggles Toyota coordinator refreshes between phases. Each run has two phases:

| Phase | Duration | Coordinator refreshes | What we learn |
|---|---|---|---|
| Baseline | 60 min | none | HA RSS floor without Toyota work |
| Test | 180 min | triggered every 15 min | HA RSS trend with Toyota work |

(My install runs with `pref_disable_polling=true` on the Toyota config entry and drives refreshes externally via `homeassistant.update_entity` because the integration's default 6-min interval triggers Toyota's API rate limiter. The per-refresh workload is the same as the stock integration; only the cadence differs.)

If the leak is real and in the Toyota code path, test-phase slope will exceed baseline-phase slope by a statistically distinguishable margin. If the leak is elsewhere (or a measurement artifact), both phases slope the same way.

### Pre-fix run

| Phase | n | first-5 avg | last-5 avg | drift | σ | slope |
|---|---|---|---|---|---|---|
| Baseline | 30 | 2664.9 MB | 2660.9 MB | **-4.0 MB** | 6.8 MB | -2.5 MB/h |
| Test | 90 | 2670.0 MB | 2738.3 MB | **+68.3 MB** | 23.1 MB | +24.8 MB/h |

Net Toyota-attributable leak rate: **+27 MB/hour at 15-min polling**. Extrapolated to 6-min polling: ~60 MB/hour, consistent with `@alpy-nz`'s ramp curve.

### Post-fix run (after replacing `_run_pytoyoda_sync` with direct `await`)

| Phase | n | first-5 avg | last-5 avg | drift | σ | slope |
|---|---|---|---|---|---|---|
| Baseline | 30 | 1140.0 MB | 1160.9 MB | **+20.9 MB** | 12.2 MB | +26.5 MB/h |
| Test | 90 | 1155.2 MB | 1190.6 MB | **+35.3 MB** | 13.8 MB | +9.1 MB/h |

Baseline drift is HA still finishing startup (the HA restart that installed the patch was ~17 min before baseline started). The key signal is that the **test phase grows SLOWER than the baseline phase** - test slope 9.1 MB/h, baseline slope 26.5 MB/h. That's the opposite of what a continued Toyota leak would produce.

Bin-by-bin view of the post-fix test phase shows decelerating growth, typical of asymptotic warmup toward steady state:

| 30-min bin | RSS | delta |
|---|---|---|
| 0-30 | 1158.9 MB | - |
| 30-60 | 1166.7 MB | +7.8 |
| 60-90 | 1166.3 MB | -0.4 |
| 90-120 | 1175.4 MB | +9.1 |
| 120-150 | 1177.2 MB | +1.8 |
| 150-180 | 1180.5 MB | +3.3 |

Compare to pre-fix test phase which was linear (~13-17 MB per 30-min bin, steady across the window).

### Verdict

- **Leak confirmed** at ~27 MB/hour at 15-min polling, ~60 MB/hour at the default 6-min.
- **Fix validated** at measurement precision. Post-fix Toyota-attributable leak rate indistinguishable from zero within the 4-hour window.
- **No functional regression**: the odometer sensor populated with fresh data (78052.0 km) through the patched code path immediately after restart.

## The fix

Diff: [+13 / -55 in `custom_components/toyota/__init__.py`](https://github.com/nledenyi/ha_toyota/compare/main...bug/memory-leak-direct-await).

```python
# Before - every pytoyoda call wrapped
def _run_pytoyoda_sync(coro: Coroutine) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

vehicles = await asyncio.wait_for(
    hass.async_add_executor_job(_run_pytoyoda_sync, client.get_vehicles()),
    15,
)
# ...same pattern for vehicle.update(), get_current_*_summary()...

# After - direct await, no thread pool, no new event loop
vehicles = await asyncio.wait_for(client.get_vehicles(), 15)
# ...same for all other pytoyoda calls...
```

The login path's `_sync_login` helper is removed analogously. `MyT(...)` construction is moved out of `hass.async_add_executor_job` (the constructor does no I/O, only stores fields).

## Known limitation - and the follow-up plan

My fix removes the event-loop churn, which removes the leak. It does **not** address the underlying blocking call that motivated the original wrapper. HA's watchdog will log `load_verify_locations` warnings when pytoyoda's httpx clients are first constructed during setup and during subsequent refreshes.

Two separate, coordinated changes would eliminate both problems permanently:

1. **Shared `httpx.AsyncClient`** (spans `pytoyoda` + `ha_toyota`). Teach pytoyoda's `MyT` / `Controller` to accept an externally-supplied `httpx.AsyncClient`. In ha_toyota, pass `homeassistant.helpers.httpx_client.get_async_client(hass)` at setup. One client, one SSL context, reused for the lifetime of the config entry. No blocking call after setup, HTTP keep-alive reuses TCP connections, and plausibly reduces Toyota's 429 rate-limit triggers because we stop opening fresh TLS sessions per request.

2. **Retry policy with backoff in pytoyoda**. Currently a 429 propagates immediately to HA as `UpdateFailed` and sensors go `unavailable` for one refresh cycle. Exponential backoff with `Retry-After` support inside pytoyoda would let the client self-heal transient rate limits without disturbing HA.

Both are out of scope for the memory-leak PR - they touch different concerns and deserve their own review loops. The leak is the immediate user-visible pain point; everything else can land after.

## Cross-links

- Full investigation journey (with git blame, rate-limit rabbit hole, and measurement methodology): this file.
- Workaround for reporters who want to test the fork before it's merged: [`ha_toyota-282-comment.md`](ha_toyota-282-comment.md).
- PR body as submitted: [`ha_toyota-282-PR-body.md`](ha_toyota-282-PR-body.md).
- Schema-drift fix, separate concern: [`README.md`](README.md), [`PR-249-body.md`](PR-249-body.md).
