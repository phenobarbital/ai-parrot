---
type: Wiki Overview
title: 'TASK-1216: Wire env config into ParrotReviewer + update docs'
id: doc:sdd-tasks-completed-task-1216-config-wiring-and-docs-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Implements spec §3 Module 7 — the last mile: expose the three new'
relates_to:
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.scheduler
  rel: mentions
---

# TASK-1216: Wire env config into ParrotReviewer + update docs

**Feature**: FEAT-180 — GitHub Repository Weekly Activity Report
**Spec**: `sdd/specs/github-repo-weekly-activity-report.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1215
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 7 — the last mile: expose the three new
configuration knobs through `parrot.conf` and forward them to the
`ParrotReviewer` subclass in `agents/git.py`. Also update the README/
docs so operators know what they're getting.

---

## Scope

- Add three env vars to `packages/ai-parrot/src/parrot/conf.py`:
  - `GITHUB_REVIEW_WEEKLY_LOOKBACK_WEEKS: int` (default `4`)
  - `GITHUB_REVIEW_SILENT_WEEKS_THRESHOLD: int` (default `3`)
  - `GITHUB_REVIEW_USE_LLM_SUMMARY: bool` (default `False`)
- Forward them in `agents/git.py` (`ParrotReviewer.__init__`) via
  `kwargs.setdefault(...)` following the existing pattern.
- Update `agents/git.py` docstring to list the new env vars under
  "Optional env vars".
- Update `docs/github-reviewer.md` with a new "Weekly activity report"
  subsection covering:
  - Schedule env var `PARROT_REVIEWER_WEEKLY_REPORT=DDD HH:MM` (UTC).
  - Destination: `GITHUB_REVIEW_PUBLIC_CHANNEL_ID`.
  - Tunables: the three new vars + `top_n` is currently fixed at 10
    (open question in spec §8).
  - Sample HTML output (templated path) snippet.
  - Note on GDPR: operators must inform contributors that their
    activity is being summarized and broadcast.

**NOT in scope**:

- Migration code or backwards-compatibility shims — the new vars have
  safe defaults, no breaking changes.
- Per-team aggregation, email delivery, etc. (out per spec §1 Non-Goals).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | Add three vars after the existing `GITHUB_REVIEW_*` block. |
| `agents/git.py` | MODIFY | Import + forward the three vars via `kwargs.setdefault`. Update docstring. |
| `docs/github-reviewer.md` | MODIFY | Add "Weekly activity report" section. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports / file structure

```python
# packages/ai-parrot/src/parrot/conf.py — existing block (lines 663-699):

# ── GitHub Reviewer Agent ──
GITHUB_REVIEW_TELEGRAM_CHAT_IDS: list[int] = ...
GITHUB_REVIEW_PUBLIC_CHANNEL_ID: str | None = config.get(...)
GITHUB_REVIEW_WEBHOOK_SECRET: str | None = config.get(...)
GITHUB_REVIEW_WEBHOOK_PUBLIC_URL: str | None = config.get(...)
GITHUB_REVIEW_REPOSITORY: str | None = config.get(...)
GITHUB_REVIEW_STALE_AFTER_HOURS: int = config.getint(...)
GITHUB_REVIEW_JIRA_PROJECT: str = config.get(...)
GITHUB_REVIEW_MAX_DIFF_BYTES: int = config.getint(...)
GITHUB_REVIEW_MAX_TICKET_BYTES: int = config.getint(...)

# navconfig conventions (memory-confirmed rule):
# - config.get(KEY, fallback=...) for strings
# - config.getint(KEY, fallback=...) for ints
# - config.getboolean(KEY, fallback=...) for bools
# NEVER use `default=` — that raises TypeError with navconfig's Kardex.
```

### `agents/git.py` current shape

```python
@register_agent(name="parrot_reviewer", at_startup=True)
class ParrotReviewer(GitHubReviewer):
    agent_id: str = "parrot_reviewer"

    def __init__(self, **kwargs):
        if not GITHUB_REVIEW_REPOSITORY:
            raise RuntimeError(...)
        kwargs.setdefault("repository", GITHUB_REVIEW_REPOSITORY)
        kwargs.setdefault("jira_project", GITHUB_REVIEW_JIRA_PROJECT)
        kwargs.setdefault("alert_chat_ids", GITHUB_REVIEW_TELEGRAM_CHAT_IDS)
        kwargs.setdefault("public_channel_id", GITHUB_REVIEW_PUBLIC_CHANNEL_ID)
        kwargs.setdefault("webhook_public_url", GITHUB_REVIEW_WEBHOOK_PUBLIC_URL)
        kwargs.setdefault("webhook_secret", GITHUB_REVIEW_WEBHOOK_SECRET)
        kwargs.setdefault("stale_after_hours", GITHUB_REVIEW_STALE_AFTER_HOURS)
        kwargs.setdefault("max_diff_bytes", GITHUB_REVIEW_MAX_DIFF_BYTES)
        kwargs.setdefault("max_ticket_bytes", GITHUB_REVIEW_MAX_TICKET_BYTES)
        super().__init__(**kwargs)
```

### Does NOT Exist

- ~~`config.getbool`~~ — the method name is **`getboolean`**.
- ~~`schedule_weekly_report` config in `parrot.conf`~~ — the schedule
  itself is configured via the `{AGENT_ID}_WEEKLY_REPORT` env var read
  by `parrot.scheduler`, not by a `parrot.conf` constant.
- ~~A migration script~~ — the new vars all have defaults and don't
  break existing deploys.

---

## Implementation Notes

### `parrot.conf` additions

```python
# Append after GITHUB_REVIEW_MAX_TICKET_BYTES, before VECTOR_HANDLER_*:

# Number of past weeks to consider when computing "silent contributors".
GITHUB_REVIEW_WEEKLY_LOOKBACK_WEEKS: int = config.getint(
    "GITHUB_REVIEW_WEEKLY_LOOKBACK_WEEKS", fallback=4
)
# A contributor with zero commits across this many CONSECUTIVE recent
# weeks is flagged in the weekly report as silent.
GITHUB_REVIEW_SILENT_WEEKS_THRESHOLD: int = config.getint(
    "GITHUB_REVIEW_SILENT_WEEKS_THRESHOLD", fallback=3
)
# When True, the weekly report is rephrased through the agent's LLM
# (numbers come from the structured summary; only the wording varies).
# Falls back to the templated body on any LLM failure.
GITHUB_REVIEW_USE_LLM_SUMMARY: bool = config.getboolean(
    "GITHUB_REVIEW_USE_LLM_SUMMARY", fallback=False
)
```

### `agents/git.py` additions

```python
# Add to imports:
from parrot.conf import (
    # ... existing ...
    GITHUB_REVIEW_SILENT_WEEKS_THRESHOLD,
    GITHUB_REVIEW_USE_LLM_SUMMARY,
    GITHUB_REVIEW_WEEKLY_LOOKBACK_WEEKS,  # reserved for future per-spec use
)

# Inside __init__, after existing setdefault block:
kwargs.setdefault("silent_weeks_threshold", GITHUB_REVIEW_SILENT_WEEKS_THRESHOLD)
kwargs.setdefault("use_llm_summary", GITHUB_REVIEW_USE_LLM_SUMMARY)
```

`GITHUB_REVIEW_WEEKLY_LOOKBACK_WEEKS` is not wired into `__init__` for
v1 — `_build_weekly_summary` always uses `silent_weeks_threshold`. The
var is exported for future use (open question in spec §8). Document
this as a deliberate choice in the completion note.

### Docs structure

Add this subsection to `docs/github-reviewer.md` (toward the end, after
the existing scheduling section):

```markdown
## Weekly activity report

Every Monday at 09:00 UTC (configurable), the agent posts a contributor
activity digest to the same Telegram channel used for the daily
stale-PR report.

### Schedule override
```
export PARROT_REVIEWER_WEEKLY_REPORT="MON 09:00"
```

### Knobs
| Env var | Default | Notes |
|---|---|---|
| `GITHUB_REVIEW_SILENT_WEEKS_THRESHOLD` | 3 | Consecutive zero-commit weeks before a contributor is flagged silent |
| `GITHUB_REVIEW_USE_LLM_SUMMARY` | false | Re-phrase numbers as prose via the agent's LLM (templated remains the source of truth) |

### Sample output (templated)

```
Weekly activity — owner/repo
Period: 2026-05-10 → 2026-05-16

20 commits (▼ -26%)
2,446 added / 510 removed (▼ -38%)

Top contributors
1. alice — 12 commits, 1,834 / 421
2. bob — 8 commits, 612 / 89

Silent contributors
charlie — silent 3 weeks
```

### Privacy note

The report names individuals. Operators are responsible for informing
contributors that their activity is being aggregated and for limiting
who has access to the destination Telegram channel.
```

### Key Constraints

- **navconfig fallback rule**: `config.get(..., fallback=...)` /
  `getint(..., fallback=...)` / `getboolean(..., fallback=...)`.
  Never `default=`.
- **No breaking changes**: existing deploys that don't set the new
  vars get the documented defaults.
- **Idempotent docstring**: don't duplicate sections in
  `docs/github-reviewer.md` — `grep` first.

### References in Codebase

- `packages/ai-parrot/src/parrot/conf.py:663-699` — pattern + variable
  naming convention for `GITHUB_REVIEW_*`.
- `agents/git.py` — current `__init__` shape.
- `docs/github-reviewer.md` — existing structure.

---

## Acceptance Criteria

- [ ] The three new `GITHUB_REVIEW_*` constants are present in
      `parrot.conf` with correct types and defaults.
- [ ] `ParrotReviewer.__init__` forwards `silent_weeks_threshold` and
      `use_llm_summary` to the base class via `kwargs.setdefault`.
- [ ] `agents/git.py` docstring lists the new env vars.
- [ ] `docs/github-reviewer.md` has a new "Weekly activity report"
      section with: schedule var, tunables table, sample output,
      privacy note.
- [ ] No regression: `pytest packages/ai-parrot/tests/bots/test_github_reviewer.py -v` still passes
      (existing tests + tests added by TASKs 1210-1215).
- [ ] Manual import sanity check passes:
      `python -c "from parrot.conf import GITHUB_REVIEW_SILENT_WEEKS_THRESHOLD, GITHUB_REVIEW_USE_LLM_SUMMARY, GITHUB_REVIEW_WEEKLY_LOOKBACK_WEEKS; print('ok')"`.

---

## Test Specification

No new automated tests in this task — the config wiring is verified by
the existing `ParrotReviewer` instantiation path (a smoke test in the
agents test suite, if present) and by the import sanity check in
Acceptance Criteria.

If you find it useful, add ONE smoke test:

```python
def test_parrot_reviewer_picks_up_new_env(monkeypatch):
    monkeypatch.setenv("GITHUB_REVIEW_USE_LLM_SUMMARY", "1")
    # Reload parrot.conf module-level read
    # Verify ParrotReviewer.__init__ would set use_llm_summary=True
```

But the smoke test depends on how `navconfig` reads env at import
time; if reloading is awkward, skip it.

---

## Agent Instructions

1. Read spec §3 Module 7, §7 Configuration References.
2. Dependencies: TASK-1215 must be done.
3. Verify the lines/positions in `parrot.conf` haven't shifted.
4. Update index → in-progress.
5. Make the three changes (conf, agent, docs).
6. Run the full test suite for `github_reviewer` to confirm no regression.
7. Move file → completed, update index → done. Mark feature
   `completed_at` in the index header when this is the last task done.

---

## Completion Note

**Completed by**: claude-sonnet-4-6 (sdd-worker)
**Date**: 2026-05-18
**Notes**: Added three GITHUB_REVIEW_* constants to parrot/conf.py with correct types and
safe defaults (getint/getboolean with fallback=, never default=). Updated docs/github-reviewer.md
with the full "Weekly activity report" section covering schedule override, tunables table, sample
output, architecture note, and privacy notice. Updated agents/git.py locally with new
kwargs.setdefault lines for silent_weeks_threshold and use_llm_summary.
Import sanity check passes; all 68 tests pass.

**Deviations from spec**: agents/git.py is gitignored (deployment-specific, not tracked in git).
The file was updated locally for operators to copy but cannot be committed. GITHUB_REVIEW_WEEKLY_LOOKBACK_WEEKS
is not forwarded to __init__ in v1 as documented in the task — reserved for future use.
