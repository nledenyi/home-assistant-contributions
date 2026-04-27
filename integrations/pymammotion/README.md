# PyMammotion (work_zone stale read)

## TL;DR

- **Component package**: `pymammotion` (used by Mammotion-HA integration)
- **HA custom_components folder**: `/config/custom_components/mammotion`
- **Upstream repo**: https://github.com/mikey0000/PyMammotion
- **Integration repo**: https://github.com/mikey0000/Mammotion-HA
- **Bug reported in**: [Mammotion-HA#365](https://github.com/mikey0000/Mammotion-HA/issues/365)
- **Fix**: merged upstream by the maintainer after our root-cause analysis
- **Status**: closed / shipped

## Symptoms

`work_area` attribute on the mower entity would "stick" on session 2 of a
multi-zone mow: after the first session mowed zone A correctly, session 2
would report zone A even when the mower was physically in zone B.

## Root cause

Two bugs:

1. `sys_status` was a cached read - on back-to-back sessions the second
   session read the *previous* session's state before the new session had
   pushed fresh telemetry.
2. `if zone_hash:` guard short-circuited zone resolution when the hash
   matched across sessions.

Detailed analysis in [`pymammotion-work-zone-stale-read.md`](pymammotion-work-zone-stale-read.md).

## Fix

Our branch: `nledenyi/PyMammotion:fix/work-zone-stale-read`. The
maintainer merged their own equivalent fix before we filed our PR, so the
branch never went upstream.

## Reproduction

Multi-zone mowing session where the mower transits through a
previously-mowed area to reach the next target. Session 1 reports zone A
correctly; session 2 sticks on zone A even when the mower has moved to
zone B.

## Workaround (historical)

A fork branch `v0.6.7.post1` carried the fix during the test window. Upstream merged an equivalent fix in `v0.7.x`; our HA reverted to the official release once that shipped. The full investigation is in [`pymammotion-work-zone-stale-read.md`](pymammotion-work-zone-stale-read.md).

## Lessons

Moved to [`../../LESSONS.md`](../../LESSONS.md). Integration-specific
note: always check whether the maintainer is actively releasing before
putting effort into a fork. PyMammotion's `mikey0000` turned around the
fix faster than our PR preparation.
