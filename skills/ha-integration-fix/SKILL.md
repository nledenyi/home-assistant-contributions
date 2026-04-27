---
name: ha-integration-fix
description: Drive a Home Assistant custom-integration bug fix end to end - fork the upstream Python client, reproduce, patch, test, open the PR, and post a workaround comment on the integration issue. Use when the user has an HA integration that is crashing or misbehaving and wants to patch it upstream. Examples - "the Toyota integration is broken", "pytoyoda has a bug, can you fix it", "fix the pymammotion issue".
argument-hint: "[integration-name or issue-url]"
---

# HA integration bug fix workflow

Reference playbook for fixing a bug in an HA custom integration. Most
HACS integrations are thin HA wrappers around a separately-published
Python client (e.g. `ha_toyota` -> `pytoyoda`, `Mammotion-HA` ->
`pymammotion`). The PR almost always goes to the client repo. The issue
usually lives on the integration repo. Keep that asymmetry in mind.

See `/home/claude/home-assistant/LESSONS.md` for gotchas. See
`/home/claude/home-assistant/integrations/_template/` for the folder
structure to bootstrap.

## Step 0. Orient

1. Confirm the user's actual goal (reported bug vs something else).
2. Find the integration in `/home/claude/home-assistant/references/hacs-installed.md`
   to get the repo names and client package name.
3. Check if there is already a folder at
   `/home/claude/home-assistant/integrations/<name>/`. If yes, read its README and
   `notes.md` first - this may be a continuation, not a new fix.

## Step 1. Research before coding

**Dump the raw API payload before assuming the bug is "no data" from the
remote API.** Many HA client libraries use pydantic with silent
fallback wrappers (e.g. `CustomEndpointBaseModel.invalid_to_none`) that
convert schema-mismatch failures to `None`. The crash you see may be
downstream of schema drift.

- Open the integration issue on GitHub. Read all comments - is it
  widespread? Is the maintainer already responding? Is there a fix in
  flight?
- Search the client repo's open PRs for the same area.
- Check when the maintainer last committed. If very recent, file an
  issue with your diagnosis instead of a PR. Let them move first.
- If you decide to continue: copy `/home/claude/home-assistant/integrations/_template/`
  to `/home/claude/home-assistant/integrations/<name>/` and fill the README.

### Read the actual code that produced historical negative results

When prior PRs / issue comments report "we tried X and it didn't work,"
do not trust the conclusion - read the request code that produced the
negative result. Especially common: a feature gets concluded "unsupported"
because someone called the endpoint with the wrong request shape (empty
body, missing required header, wrong method). The conclusion then
propagates across years of issue comments.

Example pattern: an upstream PR submits a `POST /endpoint` with an empty
body and gets a 500 response, concludes "endpoint unsupported," closes
the PR. A later attempt with the documented body shape succeeds. If you
find yourself agreeing with a previous "it does not work" verdict,
spend 10 minutes inspecting the actual HTTP request before signing off.

### Common "symptom treatment" patterns to watch for

Integrations frequently accumulate patches that silence a warning
rather than fix the underlying cause. `git blame` the suspect code
before writing a fix - the commit message usually names the warning
the author was trying to dismiss, which gives you both the diplomatic
framing for your PR and a clearer picture of the real bug.

Two patterns I've repeatedly seen:

1. **The HA blocking-call watchdog antipattern.**
   HA logs `Detected blocking call to <X> inside the event loop` when
   anything synchronous (SSL cert load, file read, `socket.getaddrinfo`)
   runs on the main event loop. A common "fix" is to wrap the offending
   async call in `hass.async_add_executor_job(
   asyncio.new_event_loop().run_until_complete, coro)` or an inner
   `_run_sync` helper. This silences the warning by moving the blocking
   call to a thread, but at the cost of a fresh event loop + fresh
   httpx client + fresh SSL context + fresh connection pool **per
   call**. Those short-lived structures leak small amounts of state
   when torn down. Over thousands of refresh cycles it's a clear RSS
   ramp.
   Correct fix: either pre-create the SSL context / httpx client in an
   executor **once** at `async_setup_entry` and reuse it, or (better)
   share HA's shared `httpx.AsyncClient` via
   `homeassistant.helpers.httpx_client.get_async_client(hass)` and
   teach the underlying client library to accept an externally-supplied
   client.

2. **Swallowing exceptions to silence noisy error logs** — often hides
   the real retry path the integration should have had. Fix retry
   policy upstream, don't hide the error.

## Step 1b. Learn the repo's conventions before coding

Before touching the code, read:

1. **`CONTRIBUTING.md`** at the repo root (and `.github/CONTRIBUTING.md`,
   `docs/CONTRIBUTING.md`). Typical signal: required tooling (poetry,
   uv, pre-commit), branch naming pattern (`bug/`, `fix/`, `feature/`),
   test command, whether PRs need an issue first.
2. **`.github/PULL_REQUEST_TEMPLATE.md`** if it exists - copy the
   structure for your PR body later.
3. **`.github/ISSUE_TEMPLATE/`** - reveals how the maintainer
   categorises bug vs feature reports; useful when writing the issue
   comment and the PR cross-reference.
4. **`pyproject.toml`** / **`setup.cfg`** / **`.pre-commit-config.yaml`** -
   the actual lint/format rules you have to pass. Check `tool.ruff`
   for `select = ["ALL"]` (very strict), codespell dictionaries, mypy
   strictness.

**If there is no `CONTRIBUTING.md`**, study the 10-20 most recent
merged PRs to infer the conventions from practice:

```bash
gh pr list --repo <org>/<repo> --state merged --limit 20 \
  --json number,title,author --jq '.[] | "\(.author.login): \(.title)"'
```

Filter out bot PRs (renovate, dependabot, github-actions). Look at
human-authored PRs for:

- **Title style**: Conventional Commits (`fix:`, `feat:`, `chore:`)?
  Sentence case vs lowercase? Imperative vs past tense?
- **Commit count per PR**: squash-merged (one commit) or
  merge-commit (multiple commits kept)? If squash, only the PR title
  matters for history. If merge-commit, each commit message should
  be clean.
- **Body format**: Do merged PRs include a Summary / Changes / Tests
  section? Paste-quoted tracebacks? Screenshots?
- **Branch naming**: inspect `pr.headRefName` via
  `gh pr view <num> --repo <org>/<repo> --json headRefName`.
- **Test expectations**: do merged fix-PRs add regression tests? If
  yes, add one for your bug too.

If the codeowners (`CODEOWNERS` file or `codeowners:` in manifest)
have recent PRs, prioritise their style - they're the reviewers.

Document what you find in the integration folder's `notes.md` so the
next fix in the same repo doesn't require re-discovery.

## Step 2. Reproduce locally

- Find the credentials for the integration:
  `sudo qm guest exec 101 -- docker exec homeassistant python3 -c
  "import json;print([e for e in
  json.load(open('/config/.storage/core.config_entries'))['data']['entries']
  if e['domain']=='<domain>'])"`
- Write a probe script under `<folder>/probes/` that calls the client
  library and dumps what the user sees. Use `os.environ["X_USER"]` for
  credentials so the script is shareable.
- Also write a probe that calls the underlying HTTP controller directly
  and dumps raw JSON, bypassing pydantic. Compare the two to confirm
  whether the bug is in the schema or in the server.
- Install the client in a throwaway venv so you can iterate without
  touching the HA container yet:
  `python3 -m venv /tmp/<pkg>_probe && /tmp/<pkg>_probe/bin/pip
  install "<pkg>"`.

## Step 3. Fork + branch

```bash
export GH_TOKEN=$(grep -oP 'https://[^:]+:\K[^@]+' /nvme-storage/docker_data/aquamap/src/.git/config)
gh repo fork <org>/<package> --clone=false
cd /tmp && git clone "https://$GH_TOKEN@github.com/nledenyi/<package>.git"
cd /tmp/<package>
git checkout -b bug/<short-desc>
```

Branch naming is usually enforced in `CONTRIBUTING.md`. Common
patterns: `bug/<desc>`, `feature/<desc>`, `fix/<desc>`. Check the
contributing doc before pushing.

## Step 4. Fix

- Make the minimal change that fixes the root cause. Resist the urge to
  also clean up unrelated nits in the same commit.
- If you find multiple bugs (common), split them into separate logical
  commits: root-cause fix first, defensive hardening second.
- Use Conventional Commits titles (`fix:`, `feat:`, `chore:`, etc.)
  when the repo's merged history uses them. Check `git log` on main.
- No em dashes in commit messages (replace with regular dash). No AI
  slop ("Let me...", "I'll now..."), no emoji.

## Step 4a. For large feature deliveries: live deploy + real-world validation BEFORE the PR

When the change is bigger than a single-bug fix - new endpoints, new
strategy logic, new entities, options-flow additions - the linear
"fork → patch → test → PR" sequence underfits. Add an iteration loop:

1. **TDD a pure-function core** for any decision logic (state machine
   / strategy / scheduler). Keep it side-effect-free so unit tests
   exercise every branch without booting HA.
2. **Mock-API harness** that simulates the upstream API contract.
   Tests against the mock can run thousands of cycles in seconds; the
   real API stays on the integration's natural cadence floor.
3. **Live deploy on your own HA**, even before the PR. Several classes
   of bug only surface in a live coordinator: device objects recreated
   per cycle wiping per-call state, cycle-vs-cache age interaction,
   options-flow string-vs-list type bugs, translation cache lag.
4. **Real-world trigger validation**. If the strategy reacts to
   physical events (driving, parking, locking), validate by actually
   doing those things and checking the integration's response.
   Synthesise as much as you can in tests, but at least one real-world
   pass before the PR earns reviewer trust.
5. **Iterate freely with separate commits during the live phase**.
   You will discover bugs on day one of soak. Land each fix as its
   own commit so the rollback story stays clean. Squash before PR
   (Step 7b).

Skip this entire sub-section for single-line bug fixes; it's overkill.

## Step 4b. For perf/leak bugs: before-and-after measurement

If the bug is about memory, CPU, or request-rate rather than a
functional crash, design the measurement before you write the fix. A
fix is only credible if you can show a signal in controlled conditions.

Typical shape for a memory-leak investigation:

1. **Identify one easily-toggled knob** that makes the integration do
   more or less work. For cloud-polling integrations this is usually
   the refresh interval or an automation that wraps the coordinator's
   update call.
2. **Write a stub harness** that captures output without triggering
   side effects. For RSS measurement, sample
   `ps -eo rss,comm --sort=-rss | awk 'NR==2 {print $1}'` inside the
   HA VM every 60-120s.
3. **Two-phase sampler**: 60 min with the knob OFF (baseline), 180 min
   with the knob ON (test). Hard automation toggles at phase boundary,
   same sample cadence in both phases.
4. **Run detached** (nohup + disown) so the harness survives Claude
   session disconnects. Write to a log file.
5. **Analyse**: linear regression on the test phase slope minus
   baseline slope = the leak rate attributable to the toggle.
   Per-30-min bin averages to rule out asymptotic warmup vs linear
   leak.
6. **Repeat post-fix** with the same harness. Success criterion:
   test slope ≈ baseline slope, or test decelerates (asymptotic
   warmup after restart) rather than grows linearly.

Wait for HA Core RSS to stabilise before starting the sampler (three
consecutive samples within 30 MB is a reasonable stability check).
Fresh-restart HA shows ~1-1.5 GB RSS that ramps to ~2-3 GB as
integrations finish loading, which will contaminate a baseline
sampled too early.

**Do not skip this step and claim a fix works based on "the code
looks right now".** Empirical proof is what earns you the PR review.

## Step 5. Test

```bash
# In the cloned repo (usually with poetry or uv):
poetry install
poetry run pre-commit run --files <changed files>   # fix anything it flags
poetry run pytest
```

Add a regression test that would fail on main before the fix. This is
the single best signal the maintainer looks at during review.

## Step 6. Install the fork into HA and verify

```bash
sudo qm guest exec 101 -- docker exec homeassistant pip install \
  --force-reinstall --no-deps \
  "git+https://github.com/nledenyi/<package>@bug/<short-desc>"
```

`--no-deps` is critical to avoid upgrading other HA-pinned packages
(httpx, pydantic, pyjwt). See LESSONS.md.

**Caveat: `--no-deps` skips legitimately-new transitive deps** that
the fork might have added since the last release. Symptom: after
install, `ModuleNotFoundError: No module named '<dep>'` on first
import. Example from 2026-04-27: pytoyoda 5.1.0 added `hishel` as a
new dep that 5.0.0 didn't have; upgrades with `--no-deps` left HA
without it.

The fix is to list the new dep explicitly alongside:

```bash
pip install --force-reinstall --no-deps \
  "git+https://github.com/nledenyi/<package>@<branch>" \
  "<new-transitive-dep>>=<version>"
```

To detect this proactively before users hit it, diff the fork's
`pyproject.toml` requirements against the last released version's
on PyPI - any addition in the fork's list needs to be installed
explicitly in the gist instructions.

**Critical gotcha after pip install**: `pip install --force-reinstall`
updates files on disk but does NOT reload modules already imported into
the running HA Core process. If your custom integration holds a
reference to a class from the upgraded package
(`from pkg.x import Foo`), it keeps calling the OLD `Foo`. Symptom:
new method signatures raise `TypeError: unexpected kwarg`, OR (worse)
the old behaviour runs silently and your fix appears to do nothing.

`ha core restart` (via `mcp__ha__ha_restart(confirm=True)`) is usually
enough - it restarts the Python process and busts `sys.modules`.
`config_entries.reload` is NOT enough - it re-runs
`async_setup_entry` against the still-cached modules.

If `ha core restart` does NOT pick up your fix:

1. **Verify the install actually landed where HA imports from.**
   `pip show <pkg>` reports the *Location* path, but that may be
   user-site (`/home/homeassistant/.local/lib/python3.14/site-packages`)
   which is not on HA's import path. Confirm by importing inside the
   container:

   ```sh
   docker exec homeassistant python3 -c "import pkg, pkg.module; print(pkg.__file__)"
   ```

   If the path is user-site or differs from your expected install
   location, re-install with elevated perms or `--target` aimed at
   HA's actual site-packages:

   ```sh
   docker exec -u 0 homeassistant pip install --force-reinstall --no-deps \
     "git+https://github.com/<fork>@<branch>"
   ```

2. **Escalate to a VM reboot only if (1) checks out and the symptom
   persists.** `qm reboot 101` is reliable but heavy; almost never
   needed in practice for a Python dep swap. Reaches for it when the
   venv is in a weird half-state from prior failed installs.

Restart HA: `ha-mcp ha_restart(confirm=True)`. Wait for
`curl -sf http://192.168.1.58:8123/manifest.json` to return 200.
Pace restarts - more than 3 in rapid succession kills the VM guest
agent.

Verify the sensors/entities populate with real values. If there's a
time-dependent state (e.g. midnight reset), monitor through it with the
`Monitor` tool.

## Step 7. Open the PR

1. Force-push the cleaned branch to your fork.
2. Draft the PR body in a file under
   `/home/claude/home-assistant/integrations/<name>/PR-body.md`. Show it to the
   user for review before posting.
3. Use `gh pr create --body-file` (not `--body` inline) so markdown
   renders correctly.
4. Title in Conventional Commits. Reference the integration-repo issue
   as `<org>/<integration-repo>#<num>` (cross-repo syntax). You cannot
   auto-close cross-repo issues with keywords.

### Stacked PRs against an external upstream

If your branch depends on another open PR (your own or someone else's)
in the same upstream repo, the GitHub PR base ref can NOT point at the
dependency's branch - it must point at the upstream's main branch
because that's where the PR will eventually merge.

The pattern is:

1. Open the PR against upstream `main`.
2. Include the dependency PR's commits inline at the bottom of your
   branch (rebase / cherry-pick onto the dependency's tip locally,
   then push). Reviewers see your commits PLUS the dependency's
   commits in the diff. That's expected for a stacked PR awaiting
   merge order.
3. Once the dependency merges, rebase your branch onto fresh main:
   the dependency's commits drop out of the diff automatically (they
   exist in main now), and the PR diff narrows to just your
   commits.
4. Communicate the merge order in the PR description with a `> [!NOTE]`
   block: "depends on #X, please merge after". Do NOT try to gate it
   via the base ref - GitHub does not enforce that for cross-PR
   dependencies in the same repo.

Counter-example: don't literally rebase your feature branch onto
the dependency's branch and expect GitHub to "stack" them. The PR's
base ref stays at upstream main, so the diff balloons to include both
PRs' commits with no signal to the reviewer that some of those commits
are from the other PR. Confuses reviewers and looks like scope creep.

If you accidentally rebase onto the dependency branch, revert with
`git reset --hard <pre-rebase-sha>` and force-push.

When the dependency PR is also yours and you can't keep two branches
in sync without manual rebases, accept the rebases. They're cheap
relative to the cost of an unreviewable diff.

## Step 7b. Pre-PR cleanup pass (iterative-feature work only)

Skip if your branch is already a single clean commit; this section is
for branches that grew through live deploy and iteration.

### Audit your prose for evidence backing

Read every claim in the README, options-flow descriptions, commit
messages, PR body. For each one, ask: **do I have direct evidence for
this, or am I generalising from a hypothesis?** Replace speculative
language with hedged language:

- "always returns X unless Y" → "frequently returns X, often
  uncorrelated with Y"
- "this fixes the issue" → "this aims to address the issue"
- "the modem stays responsive briefly after parking" (speculation) →
  "captures state the user changes shortly after stopping" (observed)

A reviewer will catch overclaims faster than an underclaim, and an
overclaim that gets contradicted in a comment hurts the PR's
credibility.

### Options-flow / UX rendering review with the user

If the PR adds or changes config options, sit with the user looking at
the rendered HA options form (Settings → Devices & Services →
&lt;Integration&gt; → Configure). Catch:

- Field ordering: most fundamental cadence knob first
- Labels: ambiguous ("Refresh cache if older") → scoped ("Refresh
  status cache if older")
- Descriptions: scope ("only the /v1/global/remote/status endpoint
  covers door/window/lock/hood; other data is fetched every cycle
  regardless"), dependencies ("when this option is OFF, the four
  options below have no effect"), evidence-backed rationale
- Conditional fields: collapse "boolean toggle + sub-interval" into a
  single field where 0 = disabled. HA's options-flow has no clean
  toggle-with-sub-field widget; the dependency only lives in the
  description.
- Translation cache lag: HA caches options-form translations at
  startup. After updating en.json, restart HA Core and re-open the
  form to confirm the new labels render.
- **`selector.NumberSelector` returns `float`**, even with `step=1`
  and `mode=BOX`. If your code uses the value for list slicing
  (`existing[:max]`), `range(max)`, or anything `__index__`-sensitive,
  it crashes with `TypeError: slice indices must be integers`. Coerce
  to `int` at every read site:

  ```python
  max_recent_trips: int = int(
      entry.options.get(CONF_MAX_RECENT_TRIPS, DEFAULT_MAX_RECENT_TRIPS)
  )
  ```

  Multiple read sites = multiple casts. Don't try to defend deeper in
  the integration; trust the type signature once it crosses the
  boundary. `vol.All(selector.NumberSelector(...), vol.Coerce(int))`
  in the schema is an alternative but easier to forget on
  schema additions.

### Commit squash with --force-with-lease

Iterative live-deploy work creates many small "found a bug at runtime"
commits. Reviewers want the polished feature, not the discovery story.
Squash before opening the PR:

```bash
git fetch origin <branch>                       # refresh local origin/ ref
git reset --soft <base-of-feature>              # keep all diffs staged
git commit -m "<final feature commit message>"  # write the polished version
git push --force-with-lease="<branch>:<sha>" origin <branch>
```

`--force-with-lease=<branch>:<sha>` is safer than `--force`: rejects
the push if origin moved since you last fetched. Important if anyone
else might have pushed; cheap insurance even when no one else is
contributing. Plain `--force` is fine if you're certain you're the
only contributor.

If the squash drops uncommitted-but-intended changes (working-tree
edits made between the last commit and the soft-reset), `git status`
will show them. Re-stage and `git commit --amend` before pushing.

## Step 8. Comment on the integration issue

1. Draft the comment under
   `/home/claude/home-assistant/integrations/<name>/<issue-slug>-comment.md`. Show
   to the user for review.
2. Include: root cause summary, link to the upstream PR, install-the-
   fork workaround for affected users, offer to rework if maintainer
   wants scope changed.
3. `gh issue comment <num> --repo <org>/<integration-repo> --body-file <path>`

## Step 9. Update the catalogue

1. Update `/home/claude/home-assistant/README.md` with a row for this fix.
2. Update `/home/claude/home-assistant/integrations/<name>/README.md` with final PR
   links and status.
3. If new cross-cutting lessons came up, append to `LESSONS.md`.

## Before you claim done

- [ ] PR is open, CI is green (or at least all checks started).
- [ ] Issue comment posted with workaround and PR link.
- [ ] HA container running the forked branch, verified working end to
      end (not just the crash fix - the sensors actually show the data
      they're supposed to).
- [ ] All artefacts under `/home/claude/home-assistant/integrations/<name>/`.
- [ ] Catalogue updated.
- [ ] No credentials committed (check probes for embedded usernames /
      passwords / tokens).

## Don'ts

- Don't run `ha core restart` more than 2-3 times in rapid succession
  (guest agent dies, needs `qm reset 101`).
- Don't commit with `--amend` if pre-commit fails mid-sequence; fix
  and create a new commit (standard Claude Code guidance, extra
  important here because HA rebuilds take minutes).
- Don't skip the raw-API probe. It's the single most common reason
  people waste hours on the wrong layer.
- Don't open the PR without the user's explicit go-ahead. Their
  per-PR review of the body text is the final gate.
- Don't delete the fork branch after merge - the workaround comment's
  pip install URL still needs to resolve for users on older HA versions.
