Root cause: schema drift in the `/v1/trips` endpoint. Toyota currently returns only 4 of the 11 fields that `_SummaryBaseModel` expects at the histogram summary level (`length`, `duration`, `averageSpeed`, `fuelConsumption`). `CustomEndpointBaseModel`'s `invalid_to_none` wrapper silently converts every partial summary to `None`, which then crashes the downstream weekly/yearly aggregators with the `TypeError` in the traceback.

Upstream fix: pytoyoda/pytoyoda#249

Verified on Home Assistant 2026.4.2 with pytoyoda 5.0.0 and a two-vehicle account. After the patch, day/week/month/year statistics sensors populate with real kilometre values.

### Workaround until a new pytoyoda release ships

Until the PR is merged and released, you can pin Home Assistant to the fork branch manually:

1. Open a shell inside the Home Assistant Core container. On Home Assistant OS:
   ```
   docker exec -it homeassistant /bin/bash
   ```
   The SSH add-on or the Terminal add-on also work.

2. Install the patched pytoyoda from the PR branch:
   ```
   pip install --force-reinstall --no-deps \
     "git+https://github.com/nledenyi/pytoyoda@bug/summary-none-handling"
   ```
   `--no-deps` is important so the other Home Assistant-pinned packages (httpx, pydantic, pyjwt, etc.) are not bumped.

3. Restart Home Assistant (Developer Tools, YAML tab, "Restart Home Assistant", or `ha core restart` from a shell).

Once the fix is merged and a new `pytoyoda` is released, revert to the published version:
```
pip install --force-reinstall "pytoyoda>=5.0.0,<6.0"
```

Happy to rework the upstream PR if the maintainers want the scope trimmed or split further.
