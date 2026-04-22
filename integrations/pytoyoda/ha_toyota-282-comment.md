# Comment to post on ha_toyota#282

@alpy-nz thanks for opening the dedicated issue. I reproduced the leak on my own HA and have a working patch. Numbers and patch link below; happy to have you test the fork before I open the PR.

### Reproduction on my side

Same setup (HAOS, HA Core 2026.4.2, 2-vehicle account). Sampled HA Core RSS every 2 minutes in two phases, with Toyota coordinator refreshes toggled off then on:

- **60 min, no refreshes**: RSS flat, -4 MB drift, σ 7 MB.
- **180 min, refresh every 15 min**: RSS climbs linearly +68 MB, slope **24.8 MB/hour**.

(My install uses `pref_disable_polling=true` + a 15-min external trigger because the stock 6-min interval trips Toyota's rate limiter. Per-refresh workload is the same as the default integration, only the cadence differs.)

Extrapolated to the default 6-min interval that's ~60 MB/hour, which matches the slope on your screenshot.

### Root cause

`custom_components/toyota/__init__.py` has a `_run_pytoyoda_sync` wrapper that creates a fresh `asyncio.new_event_loop()` on every call to pytoyoda. With 2 vehicles that's ~11 new loops per coordinator refresh. Each loop brings up a new `httpx.AsyncClient` → new SSL context → new connection pool, and tears them down when the loop closes. Python's OpenSSL bindings and httpx's transports leak small amounts of state across short-lived loops, and it accumulates linearly.

The wrapper was added in #171 to silence HA's "Detected blocking call to `load_verify_locations` inside the event loop" warning, which is real (httpx triggers a CA-bundle disk read when constructing its client). Moving pytoyoda into throwaway event loops did silence the warning but in a way that created worse side effects.

### The fix

Delete the wrapper. `pytoyoda` is already fully async, and HA's coordinator runs in HA's main event loop - there's no reason to route through a new loop in an executor thread. Replace every `hass.async_add_executor_job(_run_pytoyoda_sync, X)` with `await X`. Same for the `_sync_login` helper. `MyT(...)` construction moves out of the executor (it does no I/O).

Diff: +13 / −55 lines in one file. No dependency or behaviour changes.

### Validation

Post-patch, re-ran the same baseline/test sampler:

- **60 min, no refreshes**: +21 MB drift, slope +26.5 MB/h (HA was still finishing startup ramp).
- **180 min, refresh every 15 min**: +35 MB drift, slope +9.1 MB/h.

The test phase grows *slower* than the baseline phase, and per-30-min bins in the test phase show decelerating growth (+7.8, -0.4, +9.1, +1.8, +3.3 MB). That's the signature of asymptotic warmup, not a leak.

Odometer sensor populates correctly through the patched code path (78052.0 km in my case).

### Try it before it's merged

The patch is on my fork at `nledenyi/ha_toyota` branch `bug/memory-leak-direct-await`. Since ha_toyota is HACS-installed (or manually dropped into `/config/custom_components/toyota`) rather than a pip package, you replace just the one file:

```bash
# Open a shell inside the HA Core container. On HA OS:
#   Settings > Add-ons > SSH & Web Terminal > start, then:
docker exec -it homeassistant /bin/bash

cd /config/custom_components/toyota

# Back up the current version (so you can roll back if anything goes sideways)
cp __init__.py __init__.py.pre-leakfix.bak

# Pull the patched version from my fork
curl -fsSL "https://raw.githubusercontent.com/nledenyi/ha_toyota/bug/memory-leak-direct-await/custom_components/toyota/__init__.py" \
  -o __init__.py

exit

# Restart HA so the new file is loaded (Developer Tools > YAML > Restart Home Assistant, or:)
ha core restart
```

### What to expect after installing

- **Memory**: flat. You can re-run your screenshot experiment: let HA run for a few hours with the integration enabled and watch the RSS curve level off instead of ramping.
- **Functionality**: sensors populate as before; no entity changes, no config changes.
- **Log**: HA's watchdog will start logging `Detected blocking call to load_verify_locations` warnings again at setup and whenever pytoyoda constructs a new `httpx.AsyncClient`. Expected and noted - that's the original symptom that #171 tried to suppress. Noisy but not fatal, and a clearly better trade than a continuous memory leak. A proper fix for that warning is a follow-up PR that needs a coordinated pytoyoda + ha_toyota change so we can share a single `httpx.AsyncClient` across requests; that will also reduce TLS handshake load and plausibly the 429 rate-limit rate.

### Rollback

```bash
docker exec -it homeassistant /bin/bash
cd /config/custom_components/toyota
cp __init__.py.pre-leakfix.bak __init__.py
exit
ha core restart
```

If you can confirm the memory curve is flat on your install, I'll open the PR and reference this comment.
