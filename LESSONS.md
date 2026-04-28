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

This does silence the warning - the blocking call now happens in a
thread, off the main loop - but at the cost of a fresh event loop +
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

### Manifest pin coordination across the fork → upstream → release lifecycle

When a feature requires changes in **both** layers (rare but real), the
manifest pin in `<wrapper>/manifest.json:requirements` becomes the
synchronisation point between the two PRs. Standard pattern:

```json
"requirements": ["pytoyoda>=5.1.0,<6.0", "arrow"]
```

Lifecycle:

| Stage | Client repo | Wrapper repo | What testers do |
|---|---|---|---|
| Both PRs open | PR open against `main` | PR open against `main`, manifest pinned to current PyPI release | Need fork install for both halves |
| Client PR merges | Merged into `main`; PyPI release not yet cut | Wrapper PR still uses `git+main` install for client side | Fork install for both halves |
| Client release cut | New PyPI version (e.g. `X.Y+1.0`) tagged + uploaded | **Bump manifest pin to `>=X.Y+1.0`** in the wrapper PR | Fork install simplifies: client is now stock PyPI, only wrapper needs fork |
| Wrapper PR merges | (already done) | New wrapper version on HACS | Stock everything; fork install obsolete |

**Footgun: a client release that's incompatible with the stock
wrapper.** If the client release contains a behavioural change that
the stock wrapper can't tolerate (e.g. a persistent `httpx.AsyncClient`
that the stock wrapper's per-call event-loop helper closes out from
under), then **shipping the client release before merging the matching
wrapper change creates a regression on auto-update**. Anyone whose HA
satisfies the new client pin from PyPI but still runs the stock
wrapper crashes at runtime.

Mitigation, in priority order:

0. **Write a compatibility note in the client PR description.** Before
   any of the runtime mitigations, the cheapest gate is documenting
   the cross-repo coupling in the PR body where the maintainer can see
   it. Format: a short "Compatibility" section listing the wrapper PRs
   that need to be merged before this client release ships, with a
   recommendation to coordinate timing. We didn't write one for
   pytoyoda#252 and that's how the regression hit users; the maintainer
   merged + released the same day in good faith without that context.
1. **Coordinate the merges**: open the wrapper PR before cutting the
   client release; prefer to merge the wrapper PR same-day or sooner.
2. **If you can't coordinate**, the wrapper PR stays open and ready
   while the client release sits on PyPI; surface the regression on
   the integration's open issues so other users (and the maintainers)
   see the urgency without being privately nudged.
3. **Provide a fork-install gist** for users who hit the regression
   and want a working install today. The pytoyoda half becomes "just
   upgrade from PyPI"; only the wrapper half is the fork swap.

Real example (2026-04-27): pytoyoda#252 (client) merged 11:47Z, released
as v5.1.0 on PyPI 12:04Z. ha_toyota#283 (wrapper, removes the per-call
event-loop helper) was approved but not yet merged at that point.
pytoyoda 5.1.0's persistent httpx client + stock ha_toyota's wrapper =
`RuntimeError: Event loop is closed` on the second cycle for any user
who auto-updated. ha_toyota#283 merged later the same evening
(17:14Z), so `main` is fixed, but the latest tagged ha_toyota release
remained v2.2.2 (March, pre-#283); HACS users on auto-update still
landed in the broken combo until a new release tag was cut.
Fork-install gist (mitigation #3) was the bridge in the meantime. The
missed compatibility note (mitigation #0) was the root cause of how
widely the regression hit before the wrapper merge caught up.

### `--no-deps` is the right safety flag, but it's a knife edge

When installing a forked Python client into HA Core's pip env,
`--no-deps` is the default safety choice: it stops pip from
"upgrading" packages HA pins (`httpx`, `pydantic`, `pyjwt`, etc.) to
versions that conflict with HA's other integrations.

The flip side: if the **fork itself** added a new transitive dependency
since the previous release, `--no-deps` skips it. Symptom on first
import: `ModuleNotFoundError: No module named '<dep>'`. Real example:
pytoyoda 5.1.0 added `hishel` as a new dep (cache layer for the
persistent httpx client) that 5.0.0 didn't have; users upgrading with
`--no-deps` ended up missing it.

Fix is to list the new dep explicitly alongside the install:

```bash
pip install --upgrade --no-deps "<package>>=<new-version>" "<new-dep>>=<version>"
```

To detect proactively, diff the fork's `pyproject.toml`
`[tool.poetry.dependencies]` (or `[project.dependencies]`) against
the last released version's on PyPI. Anything NEW on the fork side is
a candidate to add explicitly to install instructions.

## HAOS-specific debugging

### py-spy doesn't work on HAOS, memray does

HA Core's container runs on Alpine Linux with musl libc. py-spy's bundled
libunwind is glibc-linked; `apk add libunwind` does NOT fix it (wheel
expects specific-hashed `.so` names Alpine doesn't provide).

Use memray instead - a native Python profiler that works cleanly on
CPython 3.14 + Alpine. Gives you file:line resolution for "where is my
process holding memory" questions that RSS sampling can't answer.

See [`references/memray-on-haos.md`](references/memray-on-haos.md) for the
full recipe, including the `memray detach <PID>` (not `--stop`) gotcha for
stopping an indefinite attach.

### `OptionsFlow.config_entry` is read-only in HA 2024.11+

Many older tutorials show `def __init__(self, config_entry):
self.config_entry = config_entry`. Since HA 2024.11, that raises
`AttributeError: property has no setter`. Omit `__init__` entirely; the
base class wires it. `async_get_options_flow(cls, config_entry)` returns
the options-flow instance with NO argument.

### entity_id slug is computed BEFORE translations load

Relying on `translation_key=` alone for entity friendly names gives
correct display strings but degenerate entity_ids like `sensor.rav4`,
`sensor.rav4_2`, `sensor.rav4_3`. The slug is generated from `name=` at
registration time; translations haven't loaded yet. Always set BOTH
`name=` (ASCII fallback for the slug) AND `translation_key=` (for the
localized runtime display).

### Disable/enable a config entry does not re-import config_flow

If you're iterating on `config_flow.py`, the disable/enable cycle runs
`async_setup_entry` again but the config_flow module is already cached in
Python. You need a full `ha core restart` to bust the cache. Symptom: you
edit the schema, click Configure, still see the old form.

### ANY module under `custom_components/<name>/` is cached across reloads

Generalisation of the config_flow case: Python's import cache
(`sys.modules`) holds every imported module for the process lifetime.
`config_entries.async_reload(entry_id)` calls `async_unload_entry` then
`async_setup_entry` from the ALREADY-IMPORTED module. It does not
reimport. So edits to `__init__.py`, `sensor.py`, `entity.py`,
`config_flow.py`, etc. all require a full `ha core restart`.

Symptom to watch for when this bites mid-iteration: the sensor-level
behaviour of a change lands correctly (because sensor.py has been
reimported by the reload path you expected), but the coordinator-level
behaviour silently runs the old code. You see half a fix work and half
not, and can't explain why. Restart HA and try again.

Mitigation: keep a restart in your mental deploy loop for any edit
outside of YAML configuration. When pair-debugging with an in-container
edit via `docker cp`, prefer `ha core restart` over `reload config entry`
unless you've confirmed the specific file you edited isn't module-cached.

### Persist coordinator state in `hass.data` to survive options-flow reloads

If `async_setup_entry` creates a closure with state you want preserved
across reloads (e.g. a per-VIN cache, per-entity diagnostic dict, the
"last good" snapshot for a retain-on-transient feature), putting it in
local variables inside `async_setup_entry` means the state is wiped
every time the user toggles an option in the UI. The options-flow
handler calls `async_reload` which re-enters `async_setup_entry` with
a fresh closure.

Put it in `hass.data[DOMAIN][f"{entry.entry_id}_aux"]` (any key other
than `entry.entry_id` itself, which gets popped by `async_unload_entry`).
The new closure re-discovers the dict via `setdefault`.

Failure mode before this fix: user toggles retain on/off during a
rate-limit-penalty window → reload clears cache → first refresh after
reload has nothing to serve and nothing to retry from → integration
stuck in `setup_retry` loop until the remote API cools off. With
`hass.data` persistence, the cache survives and first refresh can
continue serving from it.

### Per-vehicle fault isolation pattern for multi-device coordinators

When a `DataUpdateCoordinator`'s update method fetches N devices in a
loop and one fails, the natural `raise UpdateFailed` propagates to ALL
of N's entities being flipped `unavailable`. Fine if the devices are
truly coupled (same connection) but wrong when each device is
independently reachable (two different vehicles on an account, two
plugs on the same cloud API).

Pattern:
1. Loop over the N devices with a per-device try/except.
2. On success: append fresh `VehicleData(...)`.
3. On failure: append a STUB `VehicleData(data=<device_obj>,
   last_successful_fetch=None, last_error_code=<code>, ...)`. Stub keeps
   the index-to-device mapping stable across the refresh.
4. Override `ToyotaBaseEntity.available` to return False when
   `vd["last_successful_fetch"] is None and not vd["is_cached"]` - the
   stub test. Data sensors for the failed device render unavailable;
   sensors for the successful device stay fresh.
5. Diagnostic sensors (last_error, last_success, last_code) override
   `available` back to True - those MUST stay visible exactly when
   their device fails, to explain why.
6. After the loop, if NO device has fresh data AND NO cache exists
   anywhere, THEN raise `UpdateFailed` - that matches upstream "all
   unavailable when entire fleet is down" behaviour for the truly
   total-failure case.

Critical trap: if you don't append a stub for failed devices, the list
shrinks. Sensors initialised with `vehicle_index = N` then read
`coordinator.data[N]` and either `IndexError` or read a DIFFERENT
device's data at that shifted index. The symptom is "aygo's odometer
suddenly shows rav4's value" - a hard bug to track down.

### Commit-semantics for per-device state written mid-refresh

If the refresh function updates a shared state dict before knowing
whether the whole refresh will succeed, and then raises UpdateFailed
later in the loop, the state writes are observable but the corresponding
data never lands in `coordinator.data`. User sees incoherent combinations
like "entity unavailable AND last successful fetch 3 minutes ago."

Fix: only write to shared state at the END of the refresh function,
after you know the refresh is committing. Use local variables or a
temporary list during the loop, then merge to shared state once you
pass the last raise point. Treat the shared state with the same commit
semantics as `coordinator.data`: both updated iff the whole refresh
succeeds.

### Coordinator-recreated objects need an explicit cache layer

`DataUpdateCoordinator` with a refresh function that calls
`client.get_vehicles()` (or any equivalent fetch-by-list pattern) gets
**fresh device objects on every cycle**. If the device class holds
internal state populated by per-endpoint `update()` calls
(`_endpoint_data` dict in pytoyoda's case), that state is wiped between
cycles. A "skip this endpoint, serve cached" branch in your refresh
logic then has nothing to serve - downstream sensors flip to `unknown`.

Fix: cache the parsed response in `hass.data[DOMAIN][...]_diag` keyed
by VIN, and re-inject into the new device object's `_endpoint_data`
on cycles where you decide to skip the fetch. Symptom (lock sensors
flipping to `unknown` between Toyota fetches) wasted ~30 minutes of
debugging before the obvious "Vehicle is fresh per cycle" insight
clicked.

### `pip install --force-reinstall` while HA Core is running doesn't reload imported modules

If you `docker exec homeassistant pip install --force-reinstall <pkg>`
while HA Core is running, the package files on disk are updated but
**any module already imported into the running Python process keeps
the old code**. Custom integrations holding references to classes
from the upgraded package (e.g. `from pkg.x import Foo`) will continue
calling the old `Foo`, even if you restart HA Core afterwards (because
HA Core in HAOS is a long-lived Python process, not a fresh container
boot).

Symptom: new methods raise `TypeError: unexpected kwarg`, OR (worse)
the old method runs silently and your changes have no observable
effect. Spent ~25 minutes on this before realising.

Fix: full container/VM reboot after upgrading a Python dep that's
already imported. `qm reboot <vmid>` or `Settings → System → Restart →
Restart Host`. HA Core restart alone is NOT enough.

### Service handler `device_id` arrives as a string OR a list

When a service is registered with a target spec like
`target: device: integration: toyota`, HA calls the handler with
`call.data["device_id"]` as a **list** of device IDs. But when a
service is invoked from code with `data={"device_id": "<id>"}`, the
handler gets a **bare string**. `list(string)` iterates characters,
not "single-item list" - which is a silent bug if your handler does
`device_ids = list(call.data.get("device_id") or [])` and your button
entity passes a string.

Fix: defensive normalization in the handler:

```python
raw = call.data.get("device_id") or []
device_ids = [raw] if isinstance(raw, str) else list(raw)
```

And on the call side, prefer passing a list:
`{"device_id": [device.id]}` rather than `{"device_id": device.id}`.

### Cycle-count beats wall-clock for recurring schedule logic

Initial design used a `next_due_at = now + timedelta(minutes=12)`
deadline to schedule a follow-up event. Brittle when the polling
interval changed: with 6-min polling the followup fired at the second
cycle after the trigger; with 60-min polling it fired at the next
cycle (well past the deadline) - inconsistent.

Switched to a counter: `remaining_cycles = N - 1`, decrement on each
cycle that fires. Always exactly N cycles regardless of interval. The
wall-clock spacing varies with polling, but that turned out to be
fine - the original 12-min figure was a guess, not a hard requirement.

General principle: when you find yourself reasoning about
"approximately N cycles into the future," prefer a counter over a
deadline. Counters compose with variable polling intervals and avoid
deadline-vs-interval-skew bugs.

### Don't refresh static-during-X data on every X cycle

Original integration design refreshed `/v1/global/remote/status` (lock
/ door / window state) every coordinator cycle, including during a
drive. But that data is essentially static during a drive - locked,
windows up, hood closed. The data that DOES change while driving
(odometer, fuel, location) lives on different endpoints which are
already fetched. So the per-cycle `/status` GET while driving is
~40 useless calls on a 4-hour drive at 6-min polling, each one a
chance for a transient 429.

Same pattern recurs: be deliberate about which endpoints to poll
under which device states. A blanket "fetch everything every cycle"
is comfortable but wasteful and amplifies upstream API failures.

### Trust the user's polling config; resist hidden time-bound heuristics

After observing that "just_stopped" detection fires later under
coarse polling (up to one cycle late), the temptation arose to
time-bound the trigger - "skip the wake POST if the detected stop
is older than 15 minutes." Considered and rejected.

Reasoning: the user's polling interval IS their aggressiveness knob.
If they set 1h polling, they're explicitly accepting "late detection."
A hidden time-bound heuristic on top creates implicit behavior that
doesn't appear anywhere in their config - harder to reason about,
harder to debug, reduces user agency.

When there's a config knob that already covers the use case, expose
related knobs (in this case `post_count_per_stop` so coarse-polling
users can opt for a single POST) and trust the user's combination,
rather than overriding it with internal heuristics. The user's
mental model stays clean: "I set N-min polling, I get N-min cadence."
