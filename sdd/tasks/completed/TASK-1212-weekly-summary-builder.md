# TASK-1212: Implement `_build_weekly_summary` pure function

**Feature**: FEAT-180 — GitHub Repository Weekly Activity Report
**Spec**: `sdd/specs/github-repo-weekly-activity-report.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1211
**Assigned-to**: unassigned

---

## Context

The orchestrator (TASK-1215) needs raw stats reshaped into a small,
testable view object that the renderers (TASK-1213, TASK-1214) can
consume. Implements spec §3 Module 3 and the `WeeklyActivitySummary`
data model from §2.

This is a **pure function** — no I/O, no LLM, deterministic given
inputs. The unit tests for this module are the cheapest to write and
the most important to get right.

---

## Scope

- Add the `WeeklyActivitySummary` Pydantic model (and internal
  `_ContributorWindowSummary`) to `parrot/bots/github_reviewer.py`
  with exact fields from spec §2 Data Models.
- Implement `GitHubReviewer._build_weekly_summary(contributors,
  code_freq, *, threshold_weeks, top_n=10, now=None)` returning a
  `WeeklyActivitySummary`. Pure function — no `self.logger`, no API
  calls, no Telegram calls. (`top_n` truncates the active list; silent
  list stays uncapped.)
- Week alignment: pick the most recently **completed** GitHub-aligned
  week (Sunday 00:00 UTC start) strictly before `now` (defaults to
  `datetime.now(timezone.utc)`).
- Silent detection: a contributor is silent if their last `threshold_weeks`
  weekly slices (most-recent first) all have `commits == 0`.
- Deltas: `prev_total_*` come from the week immediately before the
  current window — use `WeeklyCodeFrequency` for adds/dels totals
  (more reliable than summing contributors, which can include backfill).
- Sort `contributors_active` by `commits_this_week` desc, then by
  `additions + deletions` desc as tiebreaker, then `login`.
- Sort `contributors_silent` by `weeks_silent` desc, then `login`.

**NOT in scope**:

- Telegram delivery or any I/O (TASK-1215).
- HTML rendering (TASK-1213) or LLM prose (TASK-1214).
- Network calls or stats retries (TASK-1210/1211).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/github_reviewer.py` | MODIFY | Add Pydantic models near top (after `PRReviewResult`); add `_build_weekly_summary` static or instance method on `GitHubReviewer`. |
| `packages/ai-parrot/tests/bots/test_github_reviewer.py` | MODIFY | New `TestBuildWeeklySummary` class with unit tests. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# packages/ai-parrot/src/parrot/bots/github_reviewer.py — at top:
from datetime import datetime, timezone, timedelta   # `timedelta` is NEW
from typing import Any, Dict, List, Literal, Optional, Tuple, Union  # already present
from pydantic import BaseModel, Field                # already present

# From TASK-1211:
from parrot_tools.gittoolkit import (
    ContributorStats,            # NEW import
    ContributorWeek,             # NEW import
    GitToolkit,
    WeeklyCodeFrequency,         # NEW import
)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/github_reviewer.py

class PRReviewResult(BaseModel):     # line 101
    ...

class GitHubReviewer(Agent):         # line 153
    model = GoogleModel.GEMINI_3_FLASH_PREVIEW   # line 200
    repository: str                  # set in __init__
    jira_project: str                # set in __init__
```

```python
# packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py (from TASK-1211)

class ContributorWeek(BaseModel):
    week_start: datetime            # tz-aware UTC, week starts Sunday 00:00
    additions: int
    deletions: int
    commits: int

class ContributorStats(BaseModel):
    login: Optional[str]
    avatar_url: Optional[str] = None
    total_commits: int
    weeks: List[ContributorWeek]

class WeeklyCodeFrequency(BaseModel):
    week_start: datetime
    additions: int
    deletions: int                  # already absolute (non-negative)
```

### Does NOT Exist

- ~~`isoweekday()`-based Monday-Sunday alignment~~ — GitHub aligns weeks
  Sunday 00:00 UTC; do not assume ISO weeks.
- ~~`datetime.timedelta(weeks=1)` then matching by equality~~ — beware
  DST edge cases. Compare via timestamp / `tz=timezone.utc` only.
- ~~`pydantic.field_validator` on a private model~~ — keep validators
  out; this is a value object.
- ~~`itertools.groupby` on unsorted weeks~~ — GitHub returns weeks
  chronologically, but do not rely on it without an explicit sort.

---

## Implementation Notes

### Pattern to Follow

```python
class _ContributorWindowSummary(BaseModel):
    login: str
    commits_this_week: int
    additions: int
    deletions: int
    weeks_silent: int  # 0 if active in the last completed week


class WeeklyActivitySummary(BaseModel):
    repository: str
    period_start: datetime         # Sunday 00:00 UTC of the reporting week
    period_end: datetime           # Sunday 00:00 UTC of the FOLLOWING week
    contributors_active: List[_ContributorWindowSummary]
    contributors_silent: List[_ContributorWindowSummary]
    total_commits: int
    total_additions: int
    total_deletions: int
    prev_total_commits: int
    prev_total_additions: int
    prev_total_deletions: int


def _build_weekly_summary(
    self,
    contributors: List[ContributorStats],
    code_freq: List[WeeklyCodeFrequency],
    *,
    threshold_weeks: int,
    top_n: int = 10,
    now: Optional[datetime] = None,
) -> WeeklyActivitySummary:
    """Reshape raw stats into a WeeklyActivitySummary for rendering."""
    now = now or datetime.now(timezone.utc)
    # Most recent Sunday 00:00 UTC strictly BEFORE `now`. GitHub's
    # `week_start` is Sunday-aligned, so we just pick the latest
    # week_start from contributors that is < now.
    ...
```

### Algorithm sketch

1. **Find the current week's `period_start`**: from each
   `ContributorStats.weeks`, gather `w.week_start` values; pick the
   max that is `< now`. (If contributors is empty, derive from
   `code_freq` the same way; if that's also empty, raise — empty repo.)
2. `period_end = period_start + timedelta(days=7)`.
3. `prev_period_start = period_start - timedelta(days=7)`.
4. **Per contributor**:
   - Find week slice matching `period_start` → `commits_this_week`,
     `additions`, `deletions`. Default to zeros if not present.
   - Count `weeks_silent`: starting from `period_start` and walking
     backwards in `weeks` (sorted by `week_start` desc), count
     consecutive slices with `commits == 0`. If the contributor has no
     slice at `period_start`, count it as a silent week.
   - Skip contributors with `login is None` (anonymous bucket — out of
     scope for this v1; document in completion note).
5. Build active list: contributors with `commits_this_week > 0`,
   sorted as in §Scope, capped to `top_n`.
6. Build silent list: contributors with `weeks_silent >= threshold_weeks`,
   sorted as in §Scope. **No top_n cap.**
7. **Totals**: sum `commits` and adds/dels from contributors for the
   current week; prev totals from `code_freq` at `prev_period_start`
   (with zero fallback if missing).
8. Return the populated `WeeklyActivitySummary`.

### Key Constraints

- **Pure**: no `self.logger` calls, no I/O, no Telegram, no mutation of
  `self.*`. Reads `self.repository` for the `repository` field only.
- **Deterministic**: passing the same `now` argument MUST produce the
  same output for the same inputs.
- **Idempotent**: safe to call twice.
- **No dependence on `GitToolkit` instance**: takes already-fetched
  data structures.

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/github_reviewer.py:84-117` —
  existing Pydantic models (`Discrepancy`, `PRReviewResult`) as style
  reference.
- `packages/ai-parrot/src/parrot/bots/github_reviewer.py:922` —
  `_parse_iso8601` shows the existing UTC datetime convention.

---

## Acceptance Criteria

- [ ] `WeeklyActivitySummary` and `_ContributorWindowSummary` are added
      as Pydantic models with fields exactly per spec §2.
- [ ] `_build_weekly_summary` exists as a method on `GitHubReviewer`
      and is **pure** (no I/O, no logger calls, no Telegram).
- [ ] Given a fixed `now`, picks the GitHub-aligned Sunday week strictly
      before it.
- [ ] Marks a contributor as `silent` when their last `threshold_weeks`
      slices show `commits == 0`.
- [ ] Sorts active by commits desc, then adds+dels desc, then login.
- [ ] Sorts silent by `weeks_silent` desc, then login.
- [ ] `top_n` truncates active; silent is uncapped.
- [ ] Anonymous contributors (`login is None`) are excluded from both
      lists.
- [ ] Computes `prev_total_*` from `code_freq` at
      `period_start - timedelta(days=7)`.
- [ ] Unit tests cover: week alignment with frozen now; silent flagging
      at exactly the threshold and one below; delta computation;
      anonymous exclusion; top_n cap; empty contributors raises a
      sensible error or returns zeroed-out object (pick one and test).
- [ ] All tests pass:
      `pytest packages/ai-parrot/tests/bots/test_github_reviewer.py::TestBuildWeeklySummary -v`.
- [ ] No regression in the existing 42 tests.

---

## Test Specification

```python
# tests/bots/test_github_reviewer.py — appended

from datetime import datetime, timezone, timedelta
from parrot.bots.github_reviewer import (
    GitHubReviewer,
    WeeklyActivitySummary,
)
from parrot_tools.gittoolkit import (
    ContributorStats, ContributorWeek, WeeklyCodeFrequency,
)


# Sunday 2026-05-10 00:00 UTC and surrounding weeks
W_PREV = datetime(2026, 5, 10, tzinfo=timezone.utc)
W_CURR = datetime(2026, 5, 17, tzinfo=timezone.utc)
NOW = datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc)  # Monday after W_CURR


def _stats(login, weeks):
    return ContributorStats(
        login=login,
        total_commits=sum(w.commits for w in weeks),
        weeks=weeks,
    )

def _week(start, c, a=0, d=0):
    return ContributorWeek(week_start=start, additions=a, deletions=d, commits=c)


class TestBuildWeeklySummary:
    def test_picks_completed_week_before_now(self):
        r = _MinimalReviewer()
        r._build_weekly_summary = GitHubReviewer._build_weekly_summary
        contributors = [_stats("alice", [_week(W_CURR, 5, 100, 20)])]
        code_freq = [WeeklyCodeFrequency(week_start=W_CURR, additions=100, deletions=20)]
        summary = r._build_weekly_summary(contributors, code_freq,
                                          threshold_weeks=3, now=NOW)
        assert summary.period_start == W_CURR
        assert summary.period_end == W_CURR + timedelta(days=7)
        assert summary.total_commits == 5

    def test_flags_silent_at_threshold(self):
        weeks = [_week(W_CURR - timedelta(days=7 * i), 0) for i in range(3)]
        contributors = [_stats("charlie", weeks)]
        # ... assert charlie in summary.contributors_silent with weeks_silent==3

    def test_excludes_anonymous(self):
        contributors = [_stats(None, [_week(W_CURR, 5)])]
        # ... assert summary.contributors_active == []

    def test_top_n_truncates(self):
        contributors = [_stats(f"u{i}", [_week(W_CURR, 30 - i)]) for i in range(15)]
        # ... assert len(summary.contributors_active) == 10

    def test_delta_from_code_freq(self):
        code_freq = [
            WeeklyCodeFrequency(week_start=W_CURR, additions=100, deletions=20),
            WeeklyCodeFrequency(week_start=W_PREV, additions=300, deletions=80),
        ]
        # ... assert summary.prev_total_additions == 300
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — §2 Data Models, §3 Module 3, §7 Known Risks
   (especially "Week alignment").
2. **Check dependencies** — TASK-1211 must be done; Pydantic models from
   `parrot_tools.gittoolkit` must be importable.
3. **Verify the Codebase Contract** — confirm `ContributorStats` etc.
   exist after TASK-1211.
4. **Update status** → in-progress.
5. **Implement** the models + the pure function.
6. **Verify** acceptance criteria (especially the determinism: passing
   the same `now` twice must return equal `WeeklyActivitySummary`).
7. **Move file** to `sdd/tasks/completed/`. **Update index** → done.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
