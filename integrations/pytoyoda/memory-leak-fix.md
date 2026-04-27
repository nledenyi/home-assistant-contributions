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

## Residual leak found after #283 - "Memory leak fix #2"

After #283 was approved, a few users (arhimidis64, Caros2017, mario-pranjic) reported that RSS still ramped on their installs. I could not reproduce on my own HA, so the diagnosis required environment-specific data: arhimidis64 captured a 30-min memray flamegraph using the [memray-on-haos guide](../../references/memray-on-haos.md) and shared it.

The flamegraph pointed at a different mechanism, one layer deeper than #283's wrapper:

- **78.7 MB allocated** under pytoyoda's `Vehicle.update().parallel_wrapper` in the trace
- **169,552 SSL contexts created** over the 30-min window, one per HTTP request
- Frame chain inside `request_raw`: `httpx.AsyncClient.__init__` -> `_init_transport` -> `HTTPTransport.__init__` -> `create_ssl_context`

Reading `pytoyoda/controller.py:361` directly confirmed the source:

```python
async with httpx.AsyncClient(timeout=self._timeout) as client:
    response = await client.request(...)
```

Every endpoint call constructs a fresh `httpx.AsyncClient` inside `async with`. Each construction allocates a new OpenSSL `SSL_CTX` (~1 MB+), and Python's OpenSSL bindings don't fully release these to the C heap until generational GC catches up. That's a slow-ramp leak that #283 didn't touch because it happens inside pytoyoda, not inside the `_run_pytoyoda_sync` wrapper.

The fix was already drafted as the "shared httpx.AsyncClient" follow-up below: a persistent `Controller._client` reused across requests. Now landed on the `rate-limit-resilience` branch and bundled into [pytoyoda#252](https://github.com/pytoyoda/pytoyoda/pull/252) (commit `78c17b3`). Side effect: the same change also reduces TLS handshake count from one-per-request to one-per-process-lifetime, which is genuinely net-positive even setting the leak aside.

Install instructions for testers in the [v2 install gist](https://gist.github.com/nledenyi/772fd3d68a445313fec56fae430b8f01).

## Original known limitation - and the follow-up plan (now closed)

My #283 fix removes the event-loop churn, which removes the wrapper-driven leak. It did **not** address the underlying blocking call that motivated the original wrapper, nor the per-request httpx client construction. HA's watchdog will still log `load_verify_locations` warnings when pytoyoda's httpx clients are first constructed during setup and during subsequent refreshes.

Two separate, coordinated changes would eliminate the remaining problems permanently. Both are now part of the [pytoyoda#252](https://github.com/pytoyoda/pytoyoda/pull/252) PR rather than separate follow-ups:

1. ✅ **Shared `httpx.AsyncClient`** (spans `pytoyoda` only - the integration doesn't need to inject one). pytoyoda's `Controller` now lazy-initialises a single `self._client` and reuses it for every request. One client, one SSL context, reused for the lifetime of the controller. No more per-request construction. **This is also the residual-leak fix above.**

2. ✅ **Retry policy with backoff in pytoyoda**. Now `(2, 4, 8)s` exponential backoff on 429 / 5xx in `controller.request_raw`, up to 3 retries (4 attempts total, ~14s worst-case wall time before giving up). 4xx client errors other than 429 still fail fast.

Both shipped together in #252's commits `78c17b3` and `88b3774` respectively.

## Cross-links

- Full investigation journey (with git blame, rate-limit rabbit hole, and measurement methodology): this file.
- The first PR ([ha_toyota#283](https://github.com/pytoyoda/ha_toyota/pull/283)): event-loop wrapper removal.
- The residual-leak follow-up ([pytoyoda#252](https://github.com/pytoyoda/pytoyoda/pull/252)) shipped as pytoyoda v5.1.0.
- Schema-drift fix, separate concern: [`README.md`](README.md).
