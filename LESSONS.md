# Lessons learned

Append-only log of cross-cutting patterns from HA integration work. If a
lesson only applies to one integration, keep it in that integration's
`README.md` or `notes.md` instead.

## Debugging workflow

### Dump the raw API payload before assuming "no data"

Symptoms that look like "the remote API has no data for this account"
often turn out to be pydantic silently converting real payloads to
`None`. When a response-parsing library (pytoyoda's
`CustomEndpointBaseModel` wraps every field in `invalid_to_none`, making
schema mismatches invisible. Similar wrappers exist in many HA
integrations.

Bypass the parser and dump the raw HTTP response first. If the raw JSON
has data that the parsed objects don't, the bug is in the schema, not
the API.

Script template: [`integrations/pytoyoda/probes/probe_toyota3.py`](integrations/pytoyoda/probes/probe_toyota3.py)
calls the underlying controller directly and prints the raw dict.

### Symptom treatment vs root cause

First instinct on a traceback is to fix the line that crashed. On
pytoyoda I did this for three commits (None-safe `__add__`, skip None
summaries in four aggregators) before realising the data was there and
the schema was stale. The defensive changes ended up valuable but they
were band-aids. The root-cause fix was one commit.

Next time: when a crash looks like "the data is None", verify that the
data really is None at the source before writing None-handling code.

### Probe scripts can rate-limit the coordinator's session

Running multiple probe scripts against a cloud integration in quick
succession can cause the vendor's API to rate-limit or invalidate HA's
long-lived session. Seen with pytoyoda: after 5 back-to-back
`MyT(...).login()` calls from different venvs, Toyota's API started
returning `429 { responseCode: "APIGW-403", description: "Unauthorized" }`
to HA's coordinator. HA's entities all went unavailable ~15-20 minutes
after the probe session.

Mitigations:
- Reuse a single auth session across probes when possible (keep a
  `MyT` client alive and call multiple methods on it).
- Space probe runs out by at least a few minutes if re-auth is
  unavoidable.
- Recovery: reload the integration's config entry (either via UI or
  `POST /api/config/config_entries/entry/{id}/reload`). That forces
  fresh credentials and the coordinator recovers on the next tick.

### HA qm guest agent dies under HA Core restart storms

After 4 rapid `ha_restart` calls in a row, the QEMU guest agent inside
the HA VM stops responding. `qm guest exec <ha-vm-id> -- ...` returns "guest agent
is not running" indefinitely. Recovery: `sudo qm reset <ha-vm-id>` (hard
reset). HA recovers cleanly, takes ~2 minutes.

Prevention: pace HA restarts. Pip-install all iterations into the
container, then restart once. Not once per commit.

## PR workflow for HACS-installed Python dependency bugs

### Two-layer architecture

HACS integrations (e.g. `ha_toyota`, `Mammotion-HA`) pip-install a
separate Python client package (e.g. `pytoyoda`, `pymammotion`). The bug
is usually in the client package, not the HA integration. PR targets
the client package repo, not the `ha_*` integration repo.

Cross-reference the integration-repo issue from the PR body. Post a
comment on the integration issue with the workaround + PR link, since
affected users watch the integration issue, not the client repo.

### Installing a forked client into HA without breaking HA itself

```bash
pip install --force-reinstall --no-deps \
  "git+https://github.com/<user>/<package>@<branch>"
```

`--no-deps` is critical. Without it, pip resolves the forked package's
`pyproject.toml` ranges and bumps `httpx`, `pydantic`, `pyjwt`, etc. to
versions that conflict with Home Assistant's hard pins (e.g. HA wants
`PyJWT==2.10.1` exactly). The integration still runs but HA's own
subsystems break.

The default-config install spec in `custom_components/<domain>/manifest.json`
gets satisfied by the forked post-release version (e.g.
`5.0.0.post1.dev0+abc1234` satisfies `>=5.0.0,<6.0`), so HA won't
auto-reinstall on next startup.

### Conventional Commits + branch naming

- Branch: `bug/<short-desc>` or `feature/<short-desc>` per most repos'
  `CONTRIBUTING.md`.
- Commit titles: `fix: <lowercase imperative>` for bug fixes. Matches
  what codeowners tend to use in these repos.
- One logical change per commit. If you have a root-cause fix and
  defensive hardening, make them two commits, not one.

### Pre-PR checklist

1. Rebase on the target repo's main.
2. `poetry install` (or `uv sync`, depending on the project).
3. `poetry run pre-commit run --files <changed files>`. The ruff
   `select = ["ALL"]` config in these repos will flag docstring style,
   comment formatting, and long lines. Let it auto-format, amend.
4. `poetry run pytest`. Existing suite must stay green.
5. Add a regression test that would fail on main before the fix.
6. Re-read your own commit messages for em dashes, AI-slop phrases,
   feature creep. Strip.
7. Force-push the cleaned branch.
8. `gh pr create` with a body file so the markdown formats correctly.
9. Cross-post a workaround on the downstream integration issue.

## Perf / leak fixes

### Empirical proof before claiming a fix works

If the bug is about memory, CPU, or request-rate rather than a
functional crash, **design the measurement before you write the fix**.
A one-sentence "the code now does X instead of Y" is not enough to
carry a review of a perf change.

Shape of a reliable memory-leak measurement:

- **One knob** that makes the integration do more or less work (usually
  the coordinator interval, or an automation wrapping
  `homeassistant.update_entity`).
- **Two phases, same sample cadence**: 60 min with knob OFF (baseline),
  180 min with knob ON (test). Sample every 120 s.
- **Run detached** (nohup + disown) so the sampler survives session
  disconnects. Write to a log file.
- **Stub the side effects**: if the sampler needs to toggle HA, use the
  REST API with a per-run config override, don't mutate your real
  setup. If you're measuring memory, disable the Telegram/email/RGB
  hooks (replace the senders with tee stubs) so re-runs don't spam.
- **Wait for HA to stabilise before starting**: three consecutive RSS
  samples within 30 MB is a good plateau check. Fresh-restart HA
  ramps from ~1 GB to ~2-3 GB as integrations finish loading; sampling
  too early gives a false "baseline drift".
- **Analyse with regression**: slope (MB/hour) of the test phase minus
  the baseline phase = leak rate attributable to the knob. Break into
  per-30-min bins to distinguish linear growth (leak) from decelerating
  growth (warmup tail).

Repeat the entire run post-fix. Success = test slope ≈ baseline slope,
or test phase decelerates across bins.

Real measurement from the pytoyoda leak investigation:

| phase | pre-fix | post-fix |
|---|---|---|
| baseline slope | -2.5 MB/h | +26.5 MB/h (HA warmup) |
| test slope | +24.8 MB/h | +9.1 MB/h |
| attributable leak | **+27 MB/h** | indistinguishable from zero |

### The HA blocking-call watchdog antipattern

HA logs `Detected blocking call to <X> inside the event loop` when
anything synchronous (SSL cert load, file read, `socket.getaddrinfo`)
runs on the main event loop. A common "fix" is to wrap the async call
chain in:

```python
def _run_sync(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

await hass.async_add_executor_job(_run_sync, my_async_call())
```

This does silence the warning — the blocking call now happens in a
thread, off the main loop — but at the cost of a fresh event loop +
fresh httpx client + fresh SSL context + fresh connection pool **per
call**. Those short-lived structures leak small amounts of state when
torn down. Over thousands of refresh cycles it's a visible RSS ramp.

Diagnostic signal: git blame the wrapper. If the commit message
mentions "blocking call", "avoid blocking", or names the specific HA
warning (`load_verify_locations`, `block_async_io`), you're looking at
this pattern.

**Correct fixes:**

1. If the blocking call is just the CA-bundle load, pre-create the SSL
   context / httpx client in an executor **once** at
   `async_setup_entry` and reuse it.
2. Better: share HA's pre-built `httpx.AsyncClient` via
   `homeassistant.helpers.httpx_client.get_async_client(hass)` and
   teach the underlying client library to accept it as a constructor
   arg.
3. Quickest fix for a leak PR: delete the wrapper, accept the warning
   returning at setup. Followup PR for the shared-client pattern.

## Project-management patterns

### Keep forks tidy

Delete the `fix/` branch after rebasing into `bug/`. GitHub shows stale
branches on your fork and they pollute the view for future contributors
reading from your profile.

### Let the maintainer move first when possible

PyMammotion's maintainer merged their own equivalent fix before we
opened our PR. We'd spent ~2 days on the fork. Next time, before
investing in a PR, check:

1. Maintainer's recent activity (commits / PRs merged in last 2-4
   weeks).
2. Whether a similar fix is already in a recent release that the user
   just hasn't upgraded to.
3. Whether there's an open PR from someone else already solving it.

If maintainer is responsive and the issue is known: a well-written
issue comment with diagnosis can be more useful than an unsolicited PR
and gets the fix shipped faster.

### When to fork + pin in HA vs wait for upstream

Fork + pin if:
- Bug breaks the integration entirely (blocks all entities).
- Maintainer is slow (no response in ~1 week).
- You can verify the fix on live hardware.

Just file an issue if:
- Bug is cosmetic or partial (integration mostly works).
- Maintainer is active (recent commits / responsive issues).
- You cannot reliably reproduce.
