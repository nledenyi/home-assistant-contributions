# work_zone stuck across multi-zone mowing sessions

## Problem

`MowingDevice.location.work_zone` can get pinned to a stale value - either `0` (sensor shows "Not working" while the mower is actively cutting) or the previous zone hash (sensor stays on the old area after the mower has moved on). There are two bugs in `pymammotion/data/model/device.py` that interact to cause this.

This is the root cause behind Mammotion-HA#365.

## Reproducer

Tested on `pymammotion 0.6.7` and verified the same code path exists on `main` / `0.6.10` (`device.py` is identical for this function).

1. Have at least two mapped areas where B is only reachable by transiting through A.
2. Mow area A, let the mower return to dock. `work_area` clears correctly.
3. Start a task targeting area B. The mower leaves the dock, crosses A, starts cutting B.
4. `work_area` stays at "Not working" for the entire B session.

Single-zone or dock-adjacent sessions usually dodge the bug because the state transition is sharp enough that only one frame is affected. This is probably why it has gone unnoticed - most simple setups never trigger the prolonged transit-then-work frame sequence.

## Root cause

### Bug 1 - stale cached `sys_status` in `update_report_data`

The ternary that decides whether to write `work_zone` reads `self.report_data.dev.sys_status`, but `self.report_data.update(...)` runs at the **end** of the function:

```python
if location.zone_hash:                                        # bug 2
    self.location.work_zone = (
        location.zone_hash
        if self.report_data.dev.sys_status == WorkMode.MODE_WORKING  # reads OLD value
        else 0
    )
...
self.report_data.update(toapp_report_data.to_dict(...))       # update happens HERE
```

So any frame that represents a transition into `MODE_WORKING` reads the pre-transition value, falls into the `else` branch, and writes `work_zone = 0`. On the next frame it could self-correct, but bug 2 often prevents that.

### Bug 2 - `if zone_hash:` guard blocks clearing

Both `update_report_data` and `run_state_update` wrap the `work_zone` assignment in `if zone_hash:`. When `zone_hash == 0` (mower between zones, edge-of-zone noise, transit frame), the entire assignment is skipped. This means `work_zone` can never be cleared back to 0 through this path.

Once bug 1 writes the wrong value, recovery requires a frame that simultaneously has `zone_hash != 0` AND cached `sys_status == MODE_WORKING`. That recovery window is easy to miss.

### How they interact in the multi-zone repro

1. Mower finishes area A, docks. Cached `sys_status` = idle/charging, `work_zone` = 0.
2. User starts task for area B. Mower transits through A, generating frames with a non-WORKING mode and varying `zone_hash`.
3. First frame with `sys_status = MODE_WORKING` and `zone_hash = B` arrives. Bug 1 reads the cached (stale) sys_status, writes `work_zone = 0`.
4. Subsequent rapid-state frames may carry `zone_hash = 0` (position noise, edge of zone), and bug 2's guard skips them entirely.
5. There is no periodic heartbeat that re-asserts `work_zone`, so it stays stuck for the rest of the session.

`run_state_update` has the same pair of bugs plus a structural issue: it reads `self.report_data.dev.sys_status` for its ternary, but `run_state_update` never updates that cache. So rapid-state decisions are always coupled to the report channel's lag.

## Fix

I have a tested branch at [`nledenyi/PyMammotion@fix/work-zone-stale-read`](https://github.com/nledenyi/PyMammotion/tree/fix/work-zone-stale-read) if you want to use it as a starting point or as a PR. The changes:

1. In `update_report_data`, read `sys_status` from the incoming `ReportInfoData` instead of the cached copy:
   ```python
   new_sys_status = (
       toapp_report_data.dev.sys_status
       if toapp_report_data.dev is not None
       else self.report_data.dev.sys_status
   )
   ```

2. Drop the `if location.zone_hash:` / `if self.mowing_state.zone_hash:` guards. Assign unconditionally so `work_zone = 0` frames actually stick.

3. In `run_state_update`, mirror `self.mowing_state.zone_hash` directly instead of gating on the report channel's cached `sys_status`.

4. (Minor) Loosen the `real_pos_y != 0` guard to `real_pos_y != 0 or real_pos_x != 0` so a frame sitting exactly on the y-axis origin doesn't skip the whole block.

## Testing done

Tested on a live Home Assistant deployment (Yuka mower, `pymammotion` built from the fix branch, installed as `0.6.7.post1`) for 3 days. Covered:

- Single-zone sessions from dock - start and stop transitions work correctly
- Multi-zone sessions with transit through a previously-mowed area - the exact repro scenario above now shows the correct zone throughout
- Zone transitions during transit show brief intermediate states (expected - the mower genuinely enters the transit zone briefly)

No regressions observed in adjacent fields (position, orientation, firmware reporting).

Happy to open a PR from the branch if that's preferred.

---

*Disclosure: investigation and code were AI-assisted (Claude); testing was done manually on a real mower over 3 days.*
