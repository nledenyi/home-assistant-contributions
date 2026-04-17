# PyMammotion `work_zone` stale-read bug

**Date:** 2026-04-05
**Repo:** https://github.com/mikey0000/PyMammotion
**File:** `pymammotion/data/model/device.py`
**Symptom seen:** `sensor.yuka_<mower-id>_work_area` in Home Assistant stuck at
`"Not working"` for 3+ hours while the mower was actively mowing, even though
other mower entities (`sensor.*_area`, `sensor.*_progress`,
`sensor.*_elapsed_time`, `sensor.*_battery`, etc.) were updating normally.

## Related existing issue

[mikey0000/Mammotion-HA#365 "Work area showing when not mowing (Luba2AWD1000)"](https://github.com/mikey0000/Mammotion-HA/issues/365)
describes the inverse manifestation: `work_area` stays populated with the last
known zone even after the mower leaves the area. Same root cause.

## Data flow

1. HA sensor `work_area` is defined in
   `mikey0000/Mammotion-HA/custom_components/mammotion/sensor.py`:
   ```python
   value_fn=lambda coordinator, mower_data: str(
       coordinator.get_area_entity_name(mower_data.location.work_zone)
       or "Not working"
   )
   ```
2. `coordinator.get_area_entity_name(area_hash)` returns `None` when
   `area_hash == 0`, which is why the sensor shows `"Not working"`.
3. `mower_data.location.work_zone` is maintained by PyMammotion in two places
   in `pymammotion/data/model/device.py`:
   - `update_report_data()` — processes `ReportInfoData` messages
   - `run_state_update()` — processes `SystemRapidStateTunnelMsg` messages

## The code (main branch as of 2026-04-05)

### `update_report_data` (around line 108-145)

```python
def update_report_data(self, toapp_report_data: ReportInfoData) -> None:
    """Set report data for the mower."""

    # adjust for vision models
    if (rtk := toapp_report_data.rtk) and (mqtt_rtk := rtk.mqtt_rtk_info) and self.location.RTK.latitude == 0 and self.location.RTK.longitude == 0:
        self.location.RTK.longitude = math.radians(mqtt_rtk.longitude)
        self.location.RTK.latitude = math.radians(mqtt_rtk.latitude)


    coordinate_converter = CoordinateConverter(self.location.RTK.latitude, self.location.RTK.longitude)
    for index, location in enumerate(toapp_report_data.locations):
        if index == 0 and location.real_pos_y != 0:
            self.location.position_type = location.pos_type
            self.location.orientation = int(location.real_toward / 10000)
            self.location.device = coordinate_converter.enu_to_lla(
                parse_double(location.real_pos_y, 4.0), parse_double(location.real_pos_x, 4.0)
            )
            self.map.invalidate_maps(location.bol_hash)
            if location.zone_hash:                                         # ← Bug #2
                self.location.work_zone = (
                    location.zone_hash
                    if self.report_data.dev.sys_status == WorkMode.MODE_WORKING  # ← Bug #1
                    else 0
                )

    if toapp_report_data.fw_info:
        self.update_device_firmwares(toapp_report_data.fw_info)

    if (
        toapp_report_data.work
        and (toapp_report_data.work.area >> 16) == 0
        and toapp_report_data.work.path_hash == 0
    ):
        self.work.zone_hashs = []
        self.map.current_mow_path = {}
        self.map.generated_mow_path_geojson = {}

    self.report_data.update(toapp_report_data.to_dict(casing=betterproto2.Casing.SNAKE))  # ← update happens AFTER the check
```

### `run_state_update` (around line 147-160)

```python
def run_state_update(self, rapid_state: SystemRapidStateTunnelMsg) -> None:
    """Set lat long, work zone of RTK and robot."""
    coordinate_converter = CoordinateConverter(self.location.RTK.latitude, self.location.RTK.longitude)
    self.mowing_state = RapidState().from_raw(rapid_state.rapid_state_data)
    self.location.position_type = self.mowing_state.pos_type
    self.location.orientation = int(self.mowing_state.toward / 10000)
    self.location.device = coordinate_converter.enu_to_lla(
        parse_double(self.mowing_state.pos_y, 4.0), parse_double(self.mowing_state.pos_x, 4.0)
    )
    if self.mowing_state.zone_hash:                                        # ← Bug #2
        self.location.work_zone = (
            self.mowing_state.zone_hash
            if self.report_data.dev.sys_status == WorkMode.MODE_WORKING    # ← Bug #1 (also racy)
            else 0
        )
```

`RapidState` (in `pymammotion/data/model/rapid_state.py`) does NOT carry a
`sys_status`/mode field of its own; the only source of mode info for this code
path is the cached `self.report_data.dev.sys_status`.

## Bug #1: stale `sys_status` in `update_report_data`

`update_report_data` reads `self.report_data.dev.sys_status` to decide whether
the mower is working — but this field holds the **previous** report's value.
The actual update to `self.report_data` happens at the very end of the function,
*after* the work_zone assignment has already run:

```python
self.report_data.update(toapp_report_data.to_dict(casing=betterproto2.Casing.SNAKE))
```

### Race that produces the stuck-at-zero state

1. Mower is docked/charging: `self.report_data.dev.sys_status == MODE_CHARGING`
   (or `MODE_IDLE`), `self.location.work_zone == 0`.
2. User starts a mowing task. The first incoming `ReportInfoData` contains
   `sys_status = MODE_WORKING` AND `locations[0].zone_hash = <hash>`.
3. `update_report_data` runs:
   - `if location.zone_hash:` → **true**
   - `self.report_data.dev.sys_status == WorkMode.MODE_WORKING` → **false**
     (reads the pre-update value, still `MODE_CHARGING`)
   - Writes `self.location.work_zone = 0` ❌
4. `self.report_data.update(...)` fires at the end — now `sys_status` is
   `MODE_WORKING`, but `work_zone` is already 0.
5. On subsequent reports, the stuck state persists because the Mammotion
   protocol does not stamp `zone_hash` on every `locations[0]` frame (frames
   without a zone_hash hit Bug #2 below).

## Bug #2: `if <some>.zone_hash:` guard prevents clearing

Both code paths wrap the assignment in `if <some>.zone_hash:`. When `zone_hash`
arrives as 0 (mower left the zone, returning to dock, transient frame), the
`else 0` branch inside the ternary **never executes**, so `work_zone` stays
pinned to the last non-zero value it had.

This is the bug behind Mammotion-HA#365. The mower enters Area A →
`work_zone = A` is written. The mower then exits Area A to traverse → new
reports arrive with `zone_hash = 0`, but the guard skips the assignment, so
the work_area sensor stays showing Area A.

## Bug #3 (minor): `real_pos_y != 0` guard in `update_report_data`

The whole `locations[0]` block only runs when `real_pos_y != 0`. For any frame
where the position happens to be exactly on the y-axis origin (floating-point
zero from Mammotion's `parse_double(raw, 4.0)`), everything in that block —
orientation, position, and work_zone — gets skipped. Less severe but worth
fixing while touching this function.

## Proposed fix

```python
def update_report_data(self, toapp_report_data: ReportInfoData) -> None:
    """Set report data for the mower."""
    ...
    # Read sys_status from the INCOMING data, not the stale cached copy.
    # self.report_data.update(...) runs at the end of this function, so
    # self.report_data.dev.sys_status still reflects the previous report here.
    new_sys_status = (
        toapp_report_data.dev.sys_status
        if toapp_report_data.dev is not None
        else self.report_data.dev.sys_status
    )

    coordinate_converter = CoordinateConverter(
        self.location.RTK.latitude, self.location.RTK.longitude
    )
    for index, location in enumerate(toapp_report_data.locations):
        if index == 0 and (location.real_pos_y != 0 or location.real_pos_x != 0):
            self.location.position_type = location.pos_type
            self.location.orientation = int(location.real_toward / 10000)
            self.location.device = coordinate_converter.enu_to_lla(
                parse_double(location.real_pos_y, 4.0),
                parse_double(location.real_pos_x, 4.0),
            )
            self.map.invalidate_maps(location.bol_hash)
            # Mirror the current zone unconditionally. When the mower isn't in
            # a zone (zone_hash == 0) or isn't MODE_WORKING, clear it. Drop the
            # `if location.zone_hash:` guard so transitions back to 0 stick.
            self.location.work_zone = (
                location.zone_hash
                if new_sys_status == WorkMode.MODE_WORKING
                else 0
            )
    ...
    self.report_data.update(toapp_report_data.to_dict(casing=betterproto2.Casing.SNAKE))


def run_state_update(self, rapid_state: SystemRapidStateTunnelMsg) -> None:
    """Set lat long, work zone of RTK and robot."""
    coordinate_converter = CoordinateConverter(
        self.location.RTK.latitude, self.location.RTK.longitude
    )
    self.mowing_state = RapidState().from_raw(rapid_state.rapid_state_data)
    self.location.position_type = self.mowing_state.pos_type
    self.location.orientation = int(self.mowing_state.toward / 10000)
    self.location.device = coordinate_converter.enu_to_lla(
        parse_double(self.mowing_state.pos_y, 4.0),
        parse_double(self.mowing_state.pos_x, 4.0),
    )
    # Rapid state carries the current zone directly; don't gate on a
    # potentially-stale cached sys_status from the report channel. Mammotion
    # stamps zero when the mower isn't in a zone, so mirror it verbatim.
    self.location.work_zone = self.mowing_state.zone_hash
```

## Verification plan

After patching PyMammotion in a running Home Assistant instance:

1. Start a mowing task. Within one rapid-state poll cycle
   `sensor.yuka_<mower-id>_work_area` should transition from `"Not working"` to
   the area name, NOT stay on `"Not working"`.
2. When the mower finishes and docks, the sensor should return to
   `"Not working"` within one poll cycle, NOT stay pinned on the last area.
3. During a session where the mower transits between two mapped areas, the
   sensor should update to reflect the currently-being-mowed area, with a
   brief pass through `"Not working"` during the between-zones transit.

## Observed repro (2026-04-05, same-day two-session test)

User ran two mowing sessions on an unpatched (0.6.7) install on the same day:

- **Session 1** — dock straight into area A, cut, return to dock. `work_area`
  updated correctly throughout.
- **Session 2** — dock, transit *through* already-mowed area A to reach area B,
  cut B, return to dock. `work_area` stayed pinned at `"Not working"` for the
  entire ~3 hours of the session.

This is the cleanest natural repro of the combined bug #1 + bug #2 interaction:

1. Session 1 ends cleanly. Cached `report_data.dev.sys_status` flips to
   idle/charging, `work_zone` gets cleared to 0 on the last non-WORKING report.
2. Session 2 begins. The mower traverses A, generating a stream of frames with
   sys_status set to some transit/travel mode (NOT `MODE_WORKING`) and
   zone_hash varying between `A` (inside A) and `0` (edges/transitions):
   - `update_report_data` frames keep cached sys_status pinned at the transit
     value. Their ternary resolves to `else 0` so `work_zone = 0` (no change).
   - `run_state_update` rapid-state frames read **cached** sys_status (still
     non-WORKING) and resolve to `else 0` too. `run_state_update` never
     updates cached sys_status, so rapid-state can't self-repair the cache.
3. Mower enters B and starts cutting. First `update_report_data` with
   `sys_status = MODE_WORKING, zone_hash = B` arrives. Bug #1 reads cached
   sys_status (still the transit value from step 2) and writes `work_zone = 0`.
   Cached sys_status only flips to WORKING at the **end** of this function.
4. Recovery requires a *subsequent* frame with `zone_hash != 0` while cached
   sys_status is already WORKING. If the next few rapid-state frames happen
   to carry `zone_hash = 0` (position noise, edge-of-zone moment, whatever),
   bug #2's `if zone_hash:` guard eats them and the assignment is skipped
   entirely. `work_zone` stays 0.
5. There is no periodic heartbeat that re-asserts `work_zone`, so once the
   recovery window is missed it stays stuck at 0 for the rest of the session.

### Why session 1 always works and session 2 can fail

Session 1's dock-to-cut transition is sharp: the cached sys_status flips from
idle to WORKING across a single pair of frames, with `zone_hash = A`
throughout. Bug #1 costs exactly one flicker frame, the second frame writes
`work_zone = A`, done.

Session 2 introduces a prolonged non-WORKING window (transit through A) that
keeps feeding the cache a "wrong" sys_status right up until the moment the
mower enters B. The first WORKING+zone frame for B always races against bug
#1, and there's no guarantee that the recovery frame dodges bug #2's guard.

### Practical repro recipe

- Need at least two mapped areas where area B is only reachable by crossing
  area A (or any other non-dock transit that generates non-WORKING frames).
- Mow area A first so it's the "previous" zone.
- Then start a task that targets area B. `work_area` will stay at
  `"Not working"` for the whole B session.

Single-zone sessions and dock-adjacent sessions tend to dodge the bug, which
is why it's been living in the code undetected: most simple setups never
trigger the transit-then-work frame sequence.

### What the patch does for this repro

- `new_sys_status = toapp_report_data.dev.sys_status` kills the stale-cache
  race on the WORKING transition in step 3. The first B-cutting frame now
  correctly writes `work_zone = B`.
- Dropping the `if zone_hash:` guard means every transit frame with
  `zone_hash = 0` also writes 0 (a no-op when already 0, but critically, it
  means a recovery frame never gets silently skipped).
- `run_state_update` now mirrors `self.mowing_state.zone_hash` verbatim, so
  rapid-state is no longer coupled to the report channel's cached sys_status.
  It can no longer be poisoned by the report-data lag at all.
