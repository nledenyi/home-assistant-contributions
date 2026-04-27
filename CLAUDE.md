# What belongs in this repo

This is a **public portfolio** of Home Assistant work. Its purpose is to **demonstrate capability** to readers who skim, not to archive every artefact produced during the work. When deciding whether something earns a file here, the test is: *does this file show how I think, what I built, or what I learned, in a way the source URL alone wouldn't?*

## Belongs here

- **Methodology writeups**: how a bug was diagnosed, what the root cause turned out to be, how the fix was validated. The reader should be able to follow the reasoning even if the upstream PR is gone.
- **Architecture analyses**: design rationale for a non-trivial change (state machines, decision trees, data flow). Tables comparing what was measured vs what wasn't are gold.
- **Reusable artefacts**: Claude Code skills, integration-investigation templates, methodology references (cheatsheets, profiling guides), cross-cutting lessons distilled from multiple bugs.
- **Original investigation code**: probe scripts that ran during diagnosis. The fact that the script exists, takes credentials from env vars, and dumps a specific shape is itself a methodology signal.
- **Top-level navigation**: per-integration `README.md` table summarising the work + linking to the upstream PR / issue.

## Doesn't belong here

The work I posted to GitHub already lives at a stable URL. Duplicating it locally adds zero portfolio value and clutters the file tree. **Don't commit:**

- Posted issue comments, follow-up comments, roundup comments. Link to the GitHub comment permalink instead.
- Copies of PR bodies (open or merged). The PR URL is the canonical version.
- Drafts of comments / PRs that were eventually posted. Once posted, the GitHub copy is canonical; the draft has served its purpose.
- Gemini / Codacy / bot replies. The reply text is on the PR thread.
- Step-by-step iteration logs of "I did X, then Y, then Z" - that level of detail belongs in the working journal under `/home/claude/home-assistant/integrations/<name>/journal/`, not here.
- Anything that exists primarily because "I might want to grep it later" - keep those in the working tree, not the public portfolio.

If a draft contains an analysis or framing that's worth preserving (e.g. comparison of competing PRs, walk-through of why one approach beat another), the analysis belongs **inside the integration's writeup or README**, not as a standalone draft file.

## Self-check before adding a file

1. If the file content is mostly identical to a GitHub comment / PR body, link instead of duplicate.
2. If the file is named `*-comment.md`, `*-followup.md`, `*-roundup.md`, `*-PR-body.md`, `*-draft.md`, `*-gemini-reply.md`, that's a strong signal it doesn't belong here.
3. If the unique value is one paragraph of analysis embedded in an otherwise duplicate file, fold the paragraph into the per-integration README.

## When refreshing this repo

The trigger for updates is per `feedback_portfolio_refresh.md` in memory: after a notable HA contribution (PR fix, new skill, dashboard pattern, cross-cutting lesson). When refreshing:

- Update the per-integration `README.md` status / PR-table entry.
- Update the methodology writeup if the conclusion changed.
- Bump references to upstream PR / release state.
- **Don't** add a new copy of the comment you just posted - link to it from the existing writeup if relevant.
