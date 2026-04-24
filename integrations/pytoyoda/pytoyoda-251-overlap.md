# pytoyoda PR #251 overlap comment

Posted 2026-04-24 to [pytoyoda/pytoyoda#251](https://github.com/pytoyoda/pytoyoda/pull/251) to flag that the competing minimal patch and our PR #249 target the same bug.

---

Heads up: this and #249 target the same TypeError (#278 and #279 are duplicates of each other). They're not mergeable together as-is.

Quick comparison for whoever reviews:

- **#251** wraps the two `build_summary += x` calls with `add_with_none`. Fixes the crash.
- **#249** fixes the crash the same way in effect, plus the root cause that produces the `None` summaries in the first place: Toyota's `/v1/trips` only returns 4 of the 11 `_SummaryBaseModel` fields, so `invalid_to_none` silently drops the whole summary. Adds `default=None` on each field, rewrites `__add__` to return a new instance instead of mutating `self`, fixes a second latent bug where `add_with_none(build_hdc, ...)`'s return value was discarded, and ships a unit test for the partial-payload case.

Happy to rebase #249 on whatever you prefer, or close it in favour of #251 if you'd rather ship the small patch first and address the data-loss behaviour separately. Just flagging so reviews don't step on each other.
