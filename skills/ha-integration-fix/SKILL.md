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
2. Find the integration in `~/home-assistant/references/hacs-installed.md`
   to get the repo names and client package name.
3. Check if there is already a folder at
   `~/home-assistant/integrations/<name>/`. If yes, read its README and
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
- If you decide to continue: copy `~/home-assistant/integrations/_template/`
  to `~/home-assistant/integrations/<name>/` and fill the README.

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
  `sudo qm guest exec <ha-vm-id> -- docker exec homeassistant python3 -c
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
sudo qm guest exec <ha-vm-id> -- docker exec homeassistant pip install \
  --force-reinstall --no-deps \
  "git+https://github.com/nledenyi/<package>@bug/<short-desc>"
```

`--no-deps` is critical. See LESSONS.md.

Restart HA: `ha-mcp ha_restart(confirm=True)`. Wait for
`curl -sf http://<ha-host>:8123/manifest.json` to return 200.
Pace restarts - more than 3 in rapid succession kills the VM guest
agent.

Verify the sensors/entities populate with real values. If there's a
time-dependent state (e.g. midnight reset), monitor through it with the
`Monitor` tool.

## Step 7. Open the PR

1. Force-push the cleaned branch to your fork.
2. Draft the PR body in a file under
   `~/home-assistant/integrations/<name>/PR-body.md`. Show it to the
   user for review before posting.
3. Use `gh pr create --body-file` (not `--body` inline) so markdown
   renders correctly.
4. Title in Conventional Commits. Reference the integration-repo issue
   as `<org>/<integration-repo>#<num>` (cross-repo syntax). You cannot
   auto-close cross-repo issues with keywords.

## Step 8. Comment on the integration issue

1. Draft the comment under
   `~/home-assistant/integrations/<name>/<issue-slug>-comment.md`. Show
   to the user for review.
2. Include: root cause summary, link to the upstream PR, install-the-
   fork workaround for affected users, offer to rework if maintainer
   wants scope changed.
3. `gh issue comment <num> --repo <org>/<integration-repo> --body-file <path>`

## Step 9. Update the catalogue

1. Update `~/home-assistant/README.md` with a row for this fix.
2. Update `~/home-assistant/integrations/<name>/README.md` with final PR
   links and status.
3. If new cross-cutting lessons came up, append to `LESSONS.md`.

## Before you claim done

- [ ] PR is open, CI is green (or at least all checks started).
- [ ] Issue comment posted with workaround and PR link.
- [ ] HA container running the forked branch, verified working end to
      end (not just the crash fix - the sensors actually show the data
      they're supposed to).
- [ ] All artefacts under `~/home-assistant/integrations/<name>/`.
- [ ] Catalogue updated.
- [ ] No credentials committed (check probes for embedded usernames /
      passwords / tokens).

## Don'ts

- Don't run `ha core restart` more than 2-3 times in rapid succession
  (guest agent dies, needs `qm reset <ha-vm-id>`).
- Don't commit with `--amend` if pre-commit fails mid-sequence; fix
  and create a new commit (standard Claude Code guidance, extra
  important here because HA rebuilds take minutes).
- Don't skip the raw-API probe. It's the single most common reason
  people waste hours on the wrong layer.
- Don't open the PR without the user's explicit go-ahead. Their
  per-PR review of the body text is the final gate.
- Don't delete the fork branch after merge - the workaround comment's
  pip install URL still needs to resolve for users on older HA versions.
