## Summary

`_SummaryBaseModel` declared 11 fields with only one default (`fuelConsumption`). The Toyota `/v1/trips` endpoint currently returns only 4 of them at the histogram summary level: `length`, `duration`, `averageSpeed`, `fuelConsumption`. `CustomEndpointBaseModel`'s `invalid_to_none` wrapper then silently converted every partially-populated summary to `None`, masking real API data and eventually crashing the downstream aggregators with `TypeError` or `AttributeError`.

Verified against a live account by dumping the raw `/v1/trips` JSON: histogram summaries contain only the 4 fields above, while the model rejects the payload because the other 7 are missing. This is the failure mode reported in pytoyoda/ha_toyota#278.

## Changes

Two logical commits:

1. **`fix: give every _SummaryBaseModel field a None default`** (root cause). Adds `default=None` to every numeric and list field. Pydantic can now parse partial payloads instead of failing validation and falling through to `invalid_to_none`.

2. **`fix: harden weekly/yearly/daily/monthly summary aggregation against None`** (defensive follow-up, covers the case where Toyota really does omit a field on a given day):
   - `_SummaryBaseModel.__add__` uses `add_with_none` for every numeric field (matching the existing `fuel_consumption` path) and guards `countries.extend`, `max`, and the average calculation against `None`.
   - `_generate_weekly_summaries` and `_generate_yearly_summaries` no longer emit `Summary(None, ...)` objects when every histogram or month in a period has `summary=None`; they skip the period. The downstream `Summary.distance` computed field accesses `self._summary.length` on `None` and raises `AttributeError` on sensor read otherwise.
   - `_generate_daily_summaries` and `_generate_monthly_summaries` filter `None`-summary entries out of the output list.

## Tests

Adds `tests/unit_tests/test_models/test_trips.py`:
- Parsing regression for the current 4-field API payload.
- `__add__` with missing fields on either operand and on both.
- Existing `other is None` no-op path as a guard.

`poetry run pytest` is green (114 passed, up from 109). `poetry run pre-commit run --all-files` is clean.

## Verification on a live account

Installed this branch in a Home Assistant container against an account stuck on the `TypeError` since the API started returning partial payloads. After the fix, `sensor.rav4_current_day_statistics` and peers populate with real kilometre values (for example `268.3 km` for the current week, `4769.1 km` for the current year). Midnight local transition also behaves correctly: the day sensor goes to `unknown` before the first trip of the new day, which matches historical upstream behaviour for the "no data yet" state.

## Out of scope

`_SummaryBaseModel.__add__` computes `average_speed = (self.average_speed + other.average_speed) / 2.0`. That is not a true running average; the last operand gets weighted equally with the whole accumulator. Pre-existing, unrelated to the crash, left untouched to keep this PR focused.

Addresses pytoyoda/ha_toyota#278.
