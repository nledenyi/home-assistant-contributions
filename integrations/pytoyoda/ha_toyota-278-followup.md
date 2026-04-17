@sciurius The `ONE-GLOBAL-RS-40000` error is a separate issue from the TypeError this PR addresses. It indicates Toyota has rate-limited or invalidated Home Assistant's session token, usually because the coordinator retried auth too often after the original crash. Recovery without restarting HA:

- Settings > Devices & Services > Toyota EU community integration > three-dot menu > Reload.

That forces a fresh login with the stored credentials. After the upstream pytoyoda fix lands and the integration stops crashing on refresh, you shouldn't hit this cycle again.

---

@arhimidis64 Can you share:

1. The exact error in your HA log (Settings > System > Logs, filter for `toyota`)?
2. Output of `pip show pytoyoda` after running the install command, to confirm the fork was picked up (should report `5.0.0.post4.dev0+...` or similar, not just `5.0.0`).
3. Whether you restarted Home Assistant after the `pip install` (the change doesn't apply until restart).

Most common failure I've seen so far is pip pulling the git URL but HA still loading the cached `5.0.0` because the container wasn't restarted.

If you are on Home Assistant OS and don't have `docker exec` on the host, the install is easiest via the SSH & Web Terminal add-on:

1. Settings > Add-ons > SSH & Web Terminal > Start (install first if you haven't).
2. Open the add-on's Web UI (or the Terminal entry in the sidebar if enabled).
3. Drop into the HA Core container:
   ```
   docker exec -it homeassistant /bin/bash
   ```
4. Run the same pip install command from the workaround block above, then `exit` and restart HA from Developer Tools > YAML > "Restart Home Assistant" (or `ha core restart` from that same shell).
