# PR Draft: Fix `work_zone` stale-read and zone-hash guard

**Target:** `mikey0000/PyMammotion@main`
**Head:** `nledenyi/PyMammotion@fix/work-zone-stale-read`
**Status:** DRAFT — hold until multi-day HA test confirms the fix.

---

## Title

`fix(device): correct work_zone tracking across mowing state transitions`

Alternative if a shorter title is preferred:

`fix: work_zone stuck across multi-zone sessions`

---

## Body

### Summary

`MowingDevice.location.work_zone` can get pinned to a stale value (either `0`
or the previous zone hash) across mowing state transitions. The root cause is
a pair of bugs in `pymammotion/data/model/device.py` that interact. This PR
fixes both and decouples `run_state_update` from the report channel's cache.

Closes mikey0000/Mammotion-HA#365 (inverse manifestation of the same bug).

### Symptoms

Two manifestations, same root cause:

1. **Stuck at zero ("Not working")** — mower is actively cutting area B but
   the HA `work_area` sensor stays at `"Not working"` for the entire session.
   Reproduces reliably when the mower transits through a previously-mowed
   area A to reach area B (confirmed in a live two-session test on
   `pymammotion 0.6.7`).
2. **Stuck on previous area** — mower finishes area A and leaves it, but the
   sensor keeps reporting area A. Reported as mikey0000/Mammotion-HA#365.

### Root cause

In `MowingDevice.update_report_data`:

```python
if location.zone_hash:                                        # bug #2
    self.location.work_zone = (
        location.zone_hash
        if self.report_data.dev.sys_status == WorkMode.MODE_WORKING  # bug #1
        else 0
    )
...
self.report_data.update(toapp_report_data.to_dict(...))       # cache update happens HERE
```

**Bug #1 — stale cached `sys_status`.** The ternary reads
`self.report_data.dev.sys_status`, but `self.report_data.update(...)` runs at
the **end** of the function. So any frame that represents a transition *into*
`MODE_WORKING` reads the pre-transition value, falls into the `else` branch,
and writes `work_zone = 0`. Usually self-corrects on the next frame, but see
bug #2.

**Bug #2 — `if zone_hash:` guard.** When `zone_hash == 0` (mower between
zones, edge-of-zone noise, transit frame) the entire assignment is skipped,
so `work_zone` cannot be cleared back to 0. Once it's stuck, only a frame
that simultaneously has `zone_hash != 0` AND cached `sys_status == MODE_WORKING`
can un-stick it. That recovery window is easy to miss.

`run_state_update` has the same two bugs plus a structural problem: it reads
`self.report_data.dev.sys_status` for its ternary, but `run_state_update`
itself never updates that cache. So rapid-state decisions are coupled to the
report channel's lag, which can be arbitrarily stale.

### Reproducer

Unpatched `pymammotion` (verified on `0.6.7` and `main`/`0.6.10` — `device.py`
is byte-identical between the two tags for this function):

1. Have at least two mapped areas where B is reachable only by transiting
   through A (or any setup that produces a prolonged non-`MODE_WORKING`
   phase between dock and cut).
2. Mow area A, let the mower return to dock. `work_area` clears correctly.
3. Start a task targeting area B. The mower leaves the dock, crosses A, and
   starts cutting B.
4. `work_area` stays at `"Not working"` for the entire B session.

Single-zone or dock-adjacent sessions usually dodge the bug because the
transition to `MODE_WORKING` is sharp enough that bug #1 costs only one
flicker frame that bug #2 doesn't intercept. Which is why this has been
living in the code undetected.

### Fix

1. In `update_report_data`, read `sys_status` from the incoming
   `ReportInfoData` instead of the cached copy:

   ```python
   new_sys_status = (
       toapp_report_data.dev.sys_status
       if toapp_report_data.dev is not None
       else self.report_data.dev.sys_status
   )
   ```

2. Drop the `if location.zone_hash:` / `if self.mowing_state.zone_hash:`
   guards. Assign unconditionally so `work_zone = 0` frames stick and
   recovery frames are never silently skipped.

3. In `run_state_update`, mirror `self.mowing_state.zone_hash` verbatim. The
   rapid-state tunnel already carries the current zone directly, so gating
   on a potentially-stale cached `sys_status` from the report channel was
   always the wrong call.

4. (Minor, bundled) Loosen the `real_pos_y != 0` guard in
   `update_report_data` to `real_pos_y != 0 or real_pos_x != 0`, so a frame
   that happens to sit exactly on the y-axis origin doesn't skip the whole
   location/orientation/work_zone update block.

### Behavior after the patch

For the transit repro above:

- `Not working` → `A` (while cutting A, if the session visits A)
- `A` → `Not working` (during transit between A and B)
- `Not working` → `B` (as soon as the mower enters B and starts cutting)
- `B` → `Not working` (when returning to dock)

All transitions land within one report/rapid-state cycle.

### Testing

Tested on a live Home Assistant deployment (Yuka, `pymammotion` built from
this branch, installed as `0.6.7.post1` via a pinned git requirement) for
[N days — fill in after user's multi-day test]. Covered:

- [ ] Single-zone session from dock, start and stop transitions
- [ ] Multi-zone session with transit through a previously-mowed area
- [ ] Pause/resume mid-session
- [ ] Manual return-to-dock mid-session

No regressions observed in adjacent fields (`location.device`,
`location.orientation`, `location.position_type`, firmware reporting).

### Notes

- `device.py` has no existing unit tests; this change is verified against a
  live mower. Happy to add a regression test if there's a preferred pattern
  for mocking `ReportInfoData` / `SystemRapidStateTunnelMsg` in the project.
- Ruff (`select = ["ALL"]`, line-length 120) and the project's pre-commit
  hooks pass on the patched file.
- The fix is functionally conservative: it does not change any control-flow
  outside the `work_zone` assignment, and preserves every other side effect
  (`invalidate_maps`, `position_type`, `orientation`, firmware updates, work
  area/path hash cleanup).

---

## Pre-PR checklist (do before opening)

- [ ] Multi-day HA test confirms fix for both the stuck-at-zero and
      stuck-on-previous-area cases
- [ ] `uv run ruff check pymammotion/data/model/device.py` clean
- [ ] `uv run ruff format --check pymammotion/data/model/device.py` clean
- [ ] `uv run pre-commit run --files pymammotion/data/model/device.py` clean
- [ ] Rebase `fix/work-zone-stale-read` on latest upstream `main` just before
      opening the PR (avoid conflicts with any recent `device.py` churn)
- [ ] Squash the commits on the branch into one clean commit with a
      conventional-commit-style message matching the PR title
- [ ] Mention the Discord thread (if there is one) or link this PR in the
      Mammotion-HA#365 issue thread for visibility
- [ ] Fill in the "Tested on ... for N days" line in the PR body with the
      actual duration and sessions covered
