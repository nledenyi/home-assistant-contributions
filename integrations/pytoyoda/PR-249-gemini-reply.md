Thanks for the review. Both points addressed in b6442a5:

1. `_generate_weekly_summaries` and `_generate_yearly_summaries` now capture `build_hdc = add_with_none(build_hdc, histogram.hdc)`. Nice catch, genuine pre-existing bug that would have silently lost hybrid-data for every day after the first in a period.

2. Rewrote both `_SummaryBaseModel.__add__` and `_HDCModel.__add__` to return a new instance via `model_copy(deep=True)`. Existing `a += b` callers still work because Python falls back to `a = a.__add__(b)` when `__iadd__` is absent. Added a test that pins the non-mutation guarantee so it doesn't regress.
