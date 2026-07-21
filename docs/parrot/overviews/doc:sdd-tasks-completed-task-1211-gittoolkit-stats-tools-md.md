---
type: Wiki Overview
title: 'TASK-1211: Add three stats tools to GitToolkit with typed Pydantic returns'
id: doc:sdd-tasks-completed-task-1211-gittoolkit-stats-tools-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: With the polling helper from TASK-1210 in place, expose three new
relates_to:
- concept: mod:parrot_tools.gittoolkit
  rel: mentions
---

# TASK-1211: Add three stats tools to GitToolkit with typed Pydantic returns

**Feature**: FEAT-180 — GitHub Repository Weekly Activity Report
**Spec**: `sdd/specs/github-repo-weekly-activity-report.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1210
**Assigned-to**: unassigned

---

## Context

With the polling helper from TASK-1210 in place, expose three new
read-only tools on `GitToolkit` that wrap GitHub's `/stats/*`
endpoints. Implements spec §3 Module 2 and §2 Data Models.

These are the tools the weekly report (TASK-1215) and any other agent
or human-driven workflow will use to query repository activity.

---

## Scope

- Add three Pydantic models in `gittoolkit.py`: `ContributorWeek`,
  `ContributorStats`, `WeeklyCodeFrequency` (exact shape per spec §2
  Data Models).
- Add three Pydantic `*Input` schemas (one per tool) following the
  existing `GetPullRequestDiffInput` pattern.
- Add three `@tool_schema`-decorated async methods, each with a sync
  `_*_sync` worker invoked via `asyncio.to_thread`:
  - `get_contributor_stats(repository=None) -> List[ContributorStats]`
  - `get_weekly_commit_activity(repository=None) -> List[Dict[str, Any]]`
  - `get_code_frequency(repository=None) -> List[WeeklyCodeFrequency]`
- All three call `_get_stats_with_polling` (TASK-1210) to handle 202.
- Convert GitHub Unix-epoch week timestamps (`w`) to timezone-aware
  `datetime` objects in UTC.
- Handle `author == None` in the contributors response (commits whose
  email is not linked to a GitHub account) — set `login=None` and
  `avatar_url=None`, do not crash.
- Unit tests cover: typed return shapes, anonymous author handling, the
  raw shape of `/stats/code_frequency` (`[[week, adds, dels], ...]`)
  parsed correctly.

**NOT in scope**:

- Aggregating across contributors or computing deltas (TASK-1212).
- Filtering bots / outside contributors (spec §1 Non-Goals).
- Any new top-level dependency.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py` | MODIFY | Add Pydantic models, input schemas, sync workers, async tool methods. Extend `__all__` if relevant. |
| `packages/ai-parrot-tools/tests/test_gittoolkit_stats.py` | MODIFY | Append tests for the three new tools (the file was created in TASK-1210). |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Already at the top of gittoolkit.py — do not duplicate:
import asyncio
import os
import requests
from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field
from .base import AbstractToolkit, tool_schema   # mirror existing import

# Add only what's new:
from datetime import datetime, timezone
```

### Existing Signatures to Use

```python
# packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py

class GitToolkit(AbstractToolkit):  # line 253

    def _resolve_repository(            # line 570
        self, repository: Optional[str]
    ) -> str: ...

    def _resolve_token(self) -> str:    # line 578

    @staticmethod
    def _get_stats_with_polling(        # ADDED by TASK-1210
        url: str,
        token: str,
        *,
        max_retries: int = 6,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
    ) -> requests.Response: ...

# Pattern to copy verbatim (existing tool with sync worker):
@tool_schema(GetPullRequestDiffInput)           # line 660
async def get_pull_request_diff(                # line 661
    self,
    pr_number: int,
    repository: Optional[str] = None,
    max_bytes: int = 50_000,
) -> Dict[str, Any]:
    return await asyncio.to_thread(             # line 669
        self._get_pull_request_diff_sync, repository, pr_number, max_bytes
    )

def _get_pull_request_diff_sync(...):           # line 631
    repo = self._resolve_repository(repository)
    token = self._resolve_token()
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    ...
```

### GitHub API shapes (verified against GitHub REST docs — copy-paste safe)

```python
# GET /repos/{owner}/{repo}/stats/contributors → 200 OK
# Body: List[ContributorRaw]
{
    "author": {"login": "alice", "id": 1, "avatar_url": "https://..."} | None,
    "total": 27,
    "weeks": [
        {"w": 1716422400, "a": 100, "d": 20, "c": 4},  # epoch Sunday 00:00 UTC
        ...
    ]
}

# GET /repos/{owner}/{repo}/stats/commit_activity → 200 OK
# Body: 52 entries, each:
{
    "days": [0, 3, 26, 20, 39, 1, 0],   # Sun-Sat counts
    "total": 89,
    "week": 1336280400                  # epoch Sunday 00:00 UTC
}

# GET /repos/{owner}/{repo}/stats/code_frequency → 200 OK
# Body: List[List[int, int, int]]
[
    [1302998400, 1124, -435],           # [week_epoch, adds, dels (negative)]
    ...
]
```

### Does NOT Exist

- ~~`ContributorStats.model_validate_json` magic conversion from raw
  GitHub payload~~ — Pydantic v2 does NOT auto-translate
  `{w, a, d, c}` keys to `{week_start, additions, deletions, commits}`.
  You must build the model manually inside `_get_contributor_stats_sync`.
- ~~`GitToolkit.list_contributors`~~ — not a real method; do not assume
  it exists for fallback.
- ~~`datetime.fromtimestamp(epoch)`~~ without `tz=timezone.utc` —
  always pass `tz=timezone.utc` so the resulting datetime is aware.

---

## Implementation Notes

### Pattern to Follow

```python
class ContributorWeek(BaseModel):
    week_start: datetime
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
    deletions: int


class GetContributorStatsInput(BaseModel):
    repository: Optional[str] = Field(default=None, description="owner/name")


class GetCommitActivityInput(BaseModel):
    repository: Optional[str] = Field(default=None, description="owner/name")


class GetCodeFrequencyInput(BaseModel):
    repository: Optional[str] = Field(default=None, description="owner/name")


def _get_contributor_stats_sync(
    self, repository: Optional[str]
) -> List[ContributorStats]:
    repo = self._resolve_repository(repository)
    token = self._resolve_token()
    url = f"https://api.github.com/repos/{repo}/stats/contributors"
    response = self._get_stats_with_polling(url, token)
    raw = response.json() or []
    result: List[ContributorStats] = []
    for entry in raw:
        author = entry.get("author") or {}
        weeks = [
            ContributorWeek(
                week_start=datetime.fromtimestamp(w["w"], tz=timezone.utc),
                additions=int(w.get("a", 0)),
                deletions=int(w.get("d", 0)),
                commits=int(w.get("c", 0)),
            )
            for w in entry.get("weeks", [])
        ]
        result.append(
            ContributorStats(
                login=author.get("login"),
                avatar_url=author.get("avatar_url"),
                total_commits=int(entry.get("total", 0)),
                weeks=weeks,
            )
        )
    return result


@tool_schema(GetContributorStatsInput)
async def get_contributor_stats(
    self, repository: Optional[str] = None
) -> List[ContributorStats]:
    """Return per-contributor weekly stats for the repository."""
    return await asyncio.to_thread(
        self._get_contributor_stats_sync, repository
    )
```

Apply the same pattern to `get_weekly_commit_activity` (return raw dicts —
no Pydantic model since it's secondary) and `get_code_frequency`.

For `_get_code_frequency_sync`, remember the GitHub format is a list of
3-int arrays where the deletions value is **negative**; coerce to
absolute value in the model field if you want, OR store as returned (be
consistent and document). **Recommendation**: store deletions as
**absolute / non-negative** for ergonomic downstream use, matching the
spec's `_ContributorWindowSummary.deletions: int >= 0` expectation.

### Key Constraints

- **Tool name discoverability**: the methods land on the LLM tool
  manifest via `@tool_schema`; their docstrings become the tool
  description. Write a one-line description per spec §1 Goals.
- **Timezone**: all `datetime` fields in returned models MUST be
  timezone-aware UTC (`tz=timezone.utc`).
- **No top-level new deps** — `requests` and `pydantic` already in use.
- **Anonymous author**: `entry["author"] is None` → `login=None`,
  `avatar_url=None`. Do not skip the contributor; downstream code can
  decide whether to bucket them.

### References in Codebase

- `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:660-671` —
  copy this `@tool_schema + async + asyncio.to_thread` pattern.
- `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:631-658` —
  copy the sync-worker structure (`_resolve_repository` →
  `_resolve_token` → URL → `_request`/`_get_stats_with_polling` → parse).

---

## Acceptance Criteria

- [ ] `ContributorWeek`, `ContributorStats`, `WeeklyCodeFrequency` exist
      as Pydantic models with the exact field names from spec §2.
- [ ] Three `@tool_schema`-decorated async methods exist with matching
      `*Input` schemas.
- [ ] Each method delegates to a sync worker via `asyncio.to_thread`.
- [ ] All three workers use `_get_stats_with_polling` for the HTTP call.
- [ ] Datetimes returned are timezone-aware UTC.
- [ ] Contributors with `author == None` produce a `ContributorStats`
      with `login=None`, not a crash.
- [ ] `WeeklyCodeFrequency.deletions` is non-negative.
- [ ] Unit tests cover: typed shapes, anonymous author, code frequency
      negative→positive conversion, raw GitHub payload parsing.
- [ ] All tests pass:
      `pytest packages/ai-parrot-tools/tests/test_gittoolkit_stats.py -v`.
- [ ] No regression in existing GitToolkit tests:
      `pytest packages/ai-parrot-tools/tests/test_gittoolkit.py -v` if
      present.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/test_gittoolkit_stats.py — appended

import asyncio
from datetime import datetime, timezone
from unittest.mock import patch

from parrot_tools.gittoolkit import (
    ContributorStats, ContributorWeek, GitToolkit, WeeklyCodeFrequency,
)


def _toolkit() -> GitToolkit:
    return GitToolkit(
        default_repository="owner/repo",
        github_token="tok",
    )


class TestGetContributorStats:
    def test_parses_weeks(self):
        canned = [{
            "author": {"login": "alice", "avatar_url": "x"},
            "total": 27,
            "weeks": [
                {"w": 1716422400, "a": 100, "d": 20, "c": 4},
                {"w": 1715817600, "a": 200, "d": 50, "c": 7},
            ],
        }]
        with patch.object(
            GitToolkit, "_get_stats_with_polling"
        ) as m:
            m.return_value.json.return_value = canned
            out = asyncio.run(_toolkit().get_contributor_stats())
        assert len(out) == 1
        assert out[0].login == "alice"
        assert out[0].total_commits == 27
        assert out[0].weeks[0].week_start == datetime(
            2024, 5, 23, 0, 0, tzinfo=timezone.utc
        )
        assert out[0].weeks[0].commits == 4

    def test_anonymous_author(self):
        canned = [{
            "author": None,
            "total": 3,
            "weeks": [{"w": 1716422400, "a": 5, "d": 0, "c": 1}],
        }]
        with patch.object(GitToolkit, "_get_stats_with_polling") as m:
            m.return_value.json.return_value = canned
            out = asyncio.run(_toolkit().get_contributor_stats())
        assert out[0].login is None


class TestGetCodeFrequency:
    def test_normalizes_deletions_to_positive(self):
        canned = [[1716422400, 100, -45]]
        with patch.object(GitToolkit, "_get_stats_with_polling") as m:
            m.return_value.json.return_value = canned
            out = asyncio.run(_toolkit().get_code_frequency())
        assert out[0].additions == 100
        assert out[0].deletions == 45  # absolute
        assert out[0].week_start.tzinfo is timezone.utc
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/github-repo-weekly-activity-report.spec.md` —
   §2 Data Models, §3 Module 2, §7 Risks.
2. **Check dependencies** — TASK-1210 must be `done` in
   `sdd/tasks/index/github-repo-weekly-activity-report.json`.
3. **Verify the Codebase Contract** — re-grep `_resolve_repository` and
   `_resolve_token` line numbers; verify TASK-1210's helper exists.
4. **Update status** in the index → `"in-progress"` with your session ID.
5. **Implement** following the pattern in Implementation Notes.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
