---
type: Wiki Overview
title: 'TASK-1210: Implement `_get_stats_with_polling` helper in GitToolkit'
id: doc:sdd-tasks-completed-task-1210-gittoolkit-stats-polling-helper-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: GitHub's `/stats/*` endpoints (used by Module 2 of the spec) are
relates_to:
- concept: mod:parrot_tools.gittoolkit
  rel: mentions
---

# TASK-1210: Implement `_get_stats_with_polling` helper in GitToolkit

**Feature**: FEAT-180 — GitHub Repository Weekly Activity Report
**Spec**: `sdd/specs/github-repo-weekly-activity-report.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

GitHub's `/stats/*` endpoints (used by Module 2 of the spec) are
**asynchronous** server-side: the first request after a cold cache
returns `202 Accepted` with an empty body and triggers a background
compute job, then subsequent requests return `200 OK` with the actual
data. Without retry logic, the very first weekly report after a
Navigator restart would consistently see empty data.

This task adds a single private helper that all three stats tools will
share. Implements spec §3 Module 1 and §7 "GitHub `/stats/*` async"
risk mitigation.

---

## Scope

- Add a private sync helper `_get_stats_with_polling(url, token, *,
  max_retries=6, initial_delay=1.0, max_delay=60.0)` to
  `GitToolkit`. Returns the `requests.Response` on `200`, raises
  `GitToolkitError` if `max_retries` consecutive `202`s are seen, raises
  immediately on any other non-200 status.
- Exponential backoff with cap: delays follow
  `min(initial_delay * 2 ** attempt, max_delay)`. With defaults that is
  1, 2, 4, 8, 16, 32, 60, 60… seconds (total budget ~123 s for 6 retries).
- Time between retries via `time.sleep(...)` — this helper is sync and
  called from inside `asyncio.to_thread` wrappers (matches the rest of
  the toolkit).
- Add unit tests covering: immediate 200, two 202 then 200, max-retry
  exhaustion, and a non-202 non-200 (e.g. 404) bypassing the loop.

**NOT in scope**:

- Wrapping the helper in async methods (that lives in TASK-1211).
- Importing the helper from `GitHubReviewer` (that lives in TASK-1215).
- Changing the existing `_request` semantics — the helper internally
  uses `requests.request(...)` directly rather than `_request` because
  `_request` raises on any non-`expected` status, which is incompatible
  with treating 202 as "keep trying."

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py` | MODIFY | Add `_get_stats_with_polling` as a static method on `GitToolkit`, placed near `_request` (~line 395). |
| `packages/ai-parrot-tools/tests/test_gittoolkit_stats.py` | CREATE | Unit tests for the helper. New file. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py — top of file already has:
import asyncio
import os
import time            # ADD this if not already imported
import requests        # verified: present at module top

from .base import AbstractToolkit, tool_schema  # whichever the existing imports use
# (do NOT introduce new top-level imports beyond `time`)
```

### Existing Signatures to Use

```python
# packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py

class GitToolkitError(RuntimeError):  # line 38

class GitToolkit(AbstractToolkit):    # line 253

    @staticmethod
    def _request(                     # line 395 — DO NOT call from the helper
        method: str,
        url: str,
        token: str,
        *,
        expected: int,
        **kwargs: Any,
    ) -> requests.Response: ...
```

The new helper mirrors `_request`'s parameter style (method, url, token,
keyword-only options) but treats 202 as a retry signal instead of an
error.

### Reference patterns

Header construction inside the helper must match `_request`:

```python
headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/vnd.github+json",
    "User-Agent": "parrot-gittoolkit",
}
```

### Does NOT Exist

- ~~`requests.get_with_retry`~~ — `requests` has no built-in retry; we
  implement our own.
- ~~`urllib3.util.retry.Retry` wired into `requests.Session`~~ — out of
  scope for this task; would over-engineer a single-purpose helper.
- ~~`asyncio.sleep` inside the helper~~ — this is a sync helper called
  via `asyncio.to_thread`; use `time.sleep`.

---

## Implementation Notes

### Pattern to Follow

```python
@staticmethod
def _get_stats_with_polling(
    url: str,
    token: str,
    *,
    max_retries: int = 6,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
) -> requests.Response:
    """Fetch a /stats/* endpoint with GitHub's 202→200 retry protocol.

    GitHub returns 202 while it computes the stats in the background and
    200 once the data is ready. This helper keeps polling until it sees
    200, gives up after `max_retries` consecutive 202s, and raises
    immediately on any other non-200 status.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "parrot-gittoolkit",
    }
    for attempt in range(max_retries + 1):
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code == 200:
            return response
        if response.status_code != 202:
            raise GitToolkitError(
                f"GitHub stats call to {url} failed with status "
                f"{response.status_code}: {response.text}"
            )
        if attempt == max_retries:
            break
        delay = min(initial_delay * (2 ** attempt), max_delay)
        time.sleep(delay)
    raise GitToolkitError(
        f"GitHub stats call to {url} returned 202 after "
        f"{max_retries + 1} attempts; giving up."
    )
```

### Key Constraints

- **Sync, not async** — called from within `asyncio.to_thread` by the
  tools in TASK-1211. Do not introduce `async def`.
- **No coupling to `_request`** — its raise-on-non-expected behaviour
  conflicts with treating 202 as transient.
- **Bounded total budget** — with defaults, ~63 s max wall-clock (sum of
  `1+2+4+8+16+32 = 63`).
- **Logger noise** — the helper itself should not log; the caller logs
  the final outcome. This keeps unit tests clean.

### References in Codebase

- `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:395` —
  `_request` is the parameter-style reference (mirror keyword-only
  args).
- `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:38` —
  `GitToolkitError` exception class.

---

## Acceptance Criteria

- [ ] `GitToolkit._get_stats_with_polling` exists as a `@staticmethod`.
- [ ] Returns the `requests.Response` immediately on `200`.
- [ ] Retries up to `max_retries` times on consecutive `202`, sleeping
      with exponential backoff capped at `max_delay`.
- [ ] Raises `GitToolkitError` after exhausting retries.
- [ ] Raises `GitToolkitError` immediately on any status other than
      200/202.
- [ ] Unit tests in `packages/ai-parrot-tools/tests/test_gittoolkit_stats.py`
      cover: immediate 200, 202→200, 202×N→giveup, 404 short-circuit.
- [ ] No changes to existing `_request` behaviour.
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/test_gittoolkit_stats.py -v`.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/test_gittoolkit_stats.py
from unittest.mock import patch, MagicMock
import pytest

from parrot_tools.gittoolkit import GitToolkit, GitToolkitError


def _mk_response(status_code: int, body: str = "") -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.text = body
    r.json.return_value = {} if body == "" else None
    return r


class TestStatsPolling:
    def test_returns_immediately_on_200(self):
        with patch("parrot_tools.gittoolkit.requests.get") as m:
            m.return_value = _mk_response(200, '{"ok": true}')
            resp = GitToolkit._get_stats_with_polling(
                "https://api.github.com/x", "tok", initial_delay=0.01
            )
            assert resp.status_code == 200
            assert m.call_count == 1

    def test_handles_202_then_200(self):
        with patch("parrot_tools.gittoolkit.requests.get") as m, \
             patch("parrot_tools.gittoolkit.time.sleep"):
            m.side_effect = [
                _mk_response(202), _mk_response(202), _mk_response(200, "[]"),
            ]
            resp = GitToolkit._get_stats_with_polling(
                "https://api.github.com/x", "tok", initial_delay=0.01
            )
            assert resp.status_code == 200
            assert m.call_count == 3

    def test_gives_up_after_max_retries(self):
        with patch("parrot_tools.gittoolkit.requests.get") as m, \
             patch("parrot_tools.gittoolkit.time.sleep"):
            m.return_value = _mk_response(202)
            with pytest.raises(GitToolkitError, match="returned 202 after"):
                GitToolkit._get_stats_with_polling(
                    "https://api.github.com/x", "tok",
                    max_retries=2, initial_delay=0.01,
                )
            assert m.call_count == 3  # max_retries + 1 initial

    def test_non_202_non_200_short_circuits(self):
        with patch("parrot_tools.gittoolkit.requests.get") as m:
            m.return_value = _mk_response(404, "Not Found")
            with pytest.raises(GitToolkitError, match="failed with status 404"):
                GitToolkit._get_stats_with_polling(
                    "https://api.github.com/x", "tok", initial_delay=0.01
                )
            assert m.call_count == 1
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/github-repo-weekly-activity-report.spec.md` —
   focus on §3 Module 1, §6 Codebase Contract, §7 Known Risks.
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** — confirm `GitToolkitError` is at line 38
   and `_request` at line 395 of `gittoolkit.py`. Confirm `requests` is
   already imported at the top.
4. **Update status** in `sdd/tasks/index/github-repo-weekly-activity-report.json`
   → `"in-progress"` with your session ID.
5. **Implement** the helper per the Implementation Notes pattern.
6. **Write tests** in the new file.
7. **Verify** all acceptance criteria are met.
8. **Move this file** to `sdd/tasks/completed/TASK-1210-gittoolkit-stats-polling-helper.md`.
9. **Update index** → `"done"`.
10. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
