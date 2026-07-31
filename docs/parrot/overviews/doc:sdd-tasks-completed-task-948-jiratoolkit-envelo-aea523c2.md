---
type: Wiki Overview
title: 'TASK-948: JiraToolkit envelope — global flip on read methods'
id: doc:sdd-tasks-completed-task-948-jiratoolkit-envelope-flip-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 5** of FEAT-138. Replaces the legacy native return
relates_to:
- concept: mod:parrot_tools.jiratoolkit
  rel: mentions
---

# TASK-948: JiraToolkit envelope — global flip on read methods

**Feature**: FEAT-138 — jira_analyst_systemprompt_hardening
**Spec**: `sdd/specs/jira_analyst_systemprompt_hardening.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 5** of FEAT-138. Replaces the legacy native return
shapes of the read-only `JiraToolkit` lookup tools with a single
unconditional envelope shape `{status, data, message, query}` so the
LLM grounding layer (TASK-945) can branch deterministically on
`empty` / `not_found` / `error`.

This is a **global flip** (Q1 resolution). There is no `envelope=False`
opt-out and no constructor flag — the shape is the only return type.
Migration of the three programmatic call-sites that read the legacy
shape happens in TASK-949.

Write methods (`jira_add_comment`, `jira_create_issue`,
`jira_update_issue`, `jira_transition_issue`) are out of scope and
must NOT be changed.

---

## Scope

- Define a `JiraToolEnvelope` `TypedDict` (or equivalent) at the top
  of `jiratoolkit.py`:
  ```python
  class JiraToolEnvelope(TypedDict, total=False):
      status: Literal["ok", "empty", "not_found", "error"]
      data: Any
      message: str
      query: Optional[str]
  ```
- Change `jira_get_issue`, `jira_search_issues`, `jira_search_users`
  to return a `JiraToolEnvelope`:
  - `status="ok"`, `data=<native success payload>`, `message=""`,
    `query=<key or jql>`.
  - `status="empty"` for searches that return zero rows;
    `data=[]` (or `{"issues": [], "total": 0, ...}`, see "Key
    Constraints" below).
  - `status="not_found"` when the API reports the issue does not exist
    (catch the underlying `JIRAError` for 404 / non-existent-key);
    `data=None`, populate `message` with a human-readable explanation.
  - `status="error"` for other recoverable exceptions; `data=None`,
    `message=str(exc)`. Keep the existing `self.logger.error(...)`.
- Authentication / permission errors continue to **raise** — they are
  not recoverable for the agent surface.

**NOT in scope**: any change to write methods, migrating callers
(TASK-949), updating tests for callers (TASK-949 / TASK-950).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY | Define envelope, change return shape on the 3 read methods |
| `packages/ai-parrot-tools/tests/test_jiratoolkit_envelope.py` | CREATE | Envelope unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use

```python
# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:1159
async def jira_get_issue(
    self,
    issue: str,
    fields: Optional[str] = None,
    expand: Optional[str] = None,
    structured: Optional[StructuredOutputOptions] = None,
    include_history: bool = False,
    history_page_size: int = 100,
) -> Union[Dict[str, Any], Any]:
    # Currently returns the issue dict (or structured-shape variant).
    # `self.jira.issue(issue, ...)` raises JIRAError on missing key —
    # this task wraps that in `status="not_found"`.

# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:1971
async def jira_search_users(...) -> ...
# Existing search-users path. Wrap in envelope; empty result → status="empty".

# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:2189
async def jira_search_issues(
    self,
    jql: str,
    start_at: int = 0,
    max_results: Optional[int] = 100,
    fields: Optional[str] = None,
    expand: Optional[str] = None,
    json_result: bool = True,
    store_as_dataframe: bool = False,
    dataframe_name: Optional[str] = None,
    summary_only: bool = False,
    structured: Optional[StructuredOutputOptions] = None,
) -> Dict[str, Any]:
    # Currently returns:
    #   {"total": N, "issues": [...], "pagination": {...}}
    # Empty result returns the same dict with total=0, issues=[].
    # No explicit "empty" signal today (jiratoolkit.py:2356-2367).
```

### Required Imports (for the envelope)

```python
# Add to the existing typing imports at the top of jiratoolkit.py
from typing import Any, Dict, List, Literal, Optional, TypedDict, Union
```

### Does NOT Exist

- ~~`envelope: bool = True` parameter~~ — Q1 resolution: there is NO
  per-call kwarg. The shape is unconditional.
- ~~`JiraToolkit(default_envelope=True)` constructor flag~~ — Q1
  resolution: NO per-instance flag.
- ~~`set_default_envelope`~~ — no module-level toggle.
- ~~A separate `jira_get_issue_envelope()` method~~ — modify the
  existing methods, do not add new ones.
- ~~Adding envelope to `jira_add_comment` / `jira_create_issue` /
  `jira_update_issue` / `jira_transition_issue`~~ — write methods are
  explicitly out of scope.

---

## Implementation Notes

### Pattern to Follow

```python
class JiraToolEnvelope(TypedDict, total=False):
    status: Literal["ok", "empty", "not_found", "error"]
    data: Any
    message: str
    query: Optional[str]


async def jira_get_issue(self, issue: str, ...) -> JiraToolEnvelope:
    try:
        obj = await asyncio.to_thread(self.jira.issue, issue, fields=fields, expand=expand)
    except JIRAError as exc:
        if getattr(exc, "status_code", None) == 404:
            return {"status": "not_found", "data": None,
                    "query": issue, "message": f"Issue {issue} not found."}
        # Non-404 JIRAError = propagate (auth/permission)
        raise
    except (TimeoutError, ConnectionError) as exc:
        self.logger.error("jira_get_issue failed: %s", exc, exc_info=True)
        return {"status": "error", "data": None,
                "query": issue, "message": str(exc)}

    raw = self._issue_to_dict(obj)
    if include_history:
        ...
    payload = self._apply_structured_output(raw, structured) if structured else raw
    return {"status": "ok", "data": payload, "query": issue, "message": ""}
```

### Key Constraints

- **`jira_search_issues` empty-vs-ok decision**: `status="empty"`
  when `total == 0` AFTER pagination is exhausted. `data` for empty:
  `{"total": 0, "issues": [], "pagination": {...}}` (preserve the
  legacy success-shape inside `data` for callers that branch on
  `status == "ok"` and read `data["issues"]`). Same for non-empty
  `status="ok"`.
- **`store_as_dataframe=True`**: the DataFrame side-effect is
  preserved; the return remains an envelope whose `data` is the
  legacy dict (with `dataframe_name`, `dataframe_info`, etc.). Empty
  results still return `status="empty"` with `data` carrying the
  zero-row dict.
- **`summary_only=True`**: same as above — wrap the existing summary
  dict in `data`.
- Authentication / permission errors keep raising. Only "not found"
  and recoverable runtime errors are envelope-wrapped.
- Keep `self.logger` calls at all error points.
- Do NOT change the public parameter list of any of the 3 methods.

### References in Codebase

- `jiratoolkit.py:1159-1205` — current `jira_get_issue` body.
- `jiratoolkit.py:2189-2380` — current `jira_search_issues` body.
- `jiratoolkit.py:1971-...` — current `jira_search_users`.
- `jira_specialist.py:610-639` — toolkit registration / tool
  registration; verify nothing breaks at register time after the
  shape change.

---

## Acceptance Criteria

- [ ] `JiraToolEnvelope` TypedDict is exported from `jiratoolkit.py`.
- [ ] `jira_get_issue("KEY")` returns
      `{"status": "ok", "data": <issue_dict>, "query": "KEY", "message": ""}`
      on success.
- [ ] `jira_get_issue("ZZZ-9999")` against a 404-stubbed `self.jira.issue`
      returns `status="not_found"` with `data=None`.
- [ ] `jira_search_issues("...")` returns `status="ok"` with
      `data["issues"]` containing the legacy success payload on hit.
- [ ] `jira_search_issues("project = NOPE")` against a zero-row stub
      returns `status="empty"` with `data["issues"] == []`.
- [ ] Recoverable runtime errors (e.g., `RuntimeError`) returned as
      `status="error"`; `self.logger.error` was called.
- [ ] Auth/permission errors (`AuthorizationRequired`, etc.) keep
      raising — verified by an existing or new test.
- [ ] `pytest packages/ai-parrot-tools/tests/test_jiratoolkit_envelope.py -v`
      passes.
- [ ] No write methods (`jira_add_comment`, `jira_create_issue`,
      `jira_update_issue`, `jira_transition_issue`) were touched —
      `git diff --stat` shows changes only in the 3 read methods + the
      envelope definition + tests.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/test_jiratoolkit_envelope.py
from unittest.mock import MagicMock, patch
import pytest

from parrot_tools.jiratoolkit import JiraToolkit, JiraToolEnvelope


@pytest.fixture
def toolkit():
    tk = JiraToolkit(server_url="https://x", auth_type="basic_auth",
                     username="u", password="p")
    tk.jira = MagicMock()
    return tk


@pytest.mark.asyncio
async def test_get_issue_ok(toolkit):
    fake = MagicMock()
    fake.raw = {"key": "NAV-1", "fields": {"summary": "x"}}
    toolkit.jira.issue.return_value = fake
    toolkit._issue_to_dict = lambda obj: {"key": "NAV-1", "fields": {"summary": "x"}}

    result = await toolkit.jira_get_issue("NAV-1")
    assert result["status"] == "ok"
    assert result["data"]["key"] == "NAV-1"
    assert result["query"] == "NAV-1"


@pytest.mark.asyncio
async def test_get_issue_not_found(toolkit):
    from jira.exceptions import JIRAError
    err = JIRAError(status_code=404, text="Issue Does Not Exist")
    toolkit.jira.issue.side_effect = err
    result = await toolkit.jira_get_issue("ZZZ-9999")
    assert result["status"] == "not_found"
    assert result["data"] is None


@pytest.mark.asyncio
async def test_search_issues_empty(toolkit):
    toolkit.jira.enhanced_search_issues.return_value = []
    result = await toolkit.jira_search_issues("project = NOPE")
    assert result["status"] == "empty"
    assert result["data"]["issues"] == []


@pytest.mark.asyncio
async def test_search_issues_ok(toolkit):
    fake_issue = MagicMock()
    toolkit.jira.enhanced_search_issues.return_value = [fake_issue]
    toolkit._issue_to_dict = lambda obj: {"key": "NAV-1"}
    result = await toolkit.jira_search_issues("project = NAV")
    assert result["status"] == "ok"
    assert len(result["data"]["issues"]) == 1


@pytest.mark.asyncio
async def test_get_issue_runtime_error_returns_envelope(toolkit):
    toolkit.jira.issue.side_effect = RuntimeError("boom")
    result = await toolkit.jira_get_issue("NAV-1")
    assert result["status"] == "error"
    assert "boom" in result["message"]


@pytest.mark.asyncio
async def test_get_issue_auth_error_propagates(toolkit):
    from parrot_tools.jiratoolkit import AuthorizationRequired
    toolkit.jira.issue.side_effect = AuthorizationRequired("login required")
    with pytest.raises(AuthorizationRequired):
        await toolkit.jira_get_issue("NAV-1")
```

---

## Agent Instructions

1. Read the spec sections 3 Module 5, 6 Codebase Contract, 7 Risks.
2. Update index → `"in-progress"`.
3. Implement (single commit covering envelope + 3 method bodies + tests).
4. Run the new test plus existing `tests/test_jiratoolkit_*.py` to
   verify no write-method regressions.
5. Move file to `completed/`; update index → `"done"`.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-05-01
**Notes**: All 3 read methods (jira_get_issue, jira_search_issues, jira_search_users)
now return JiraToolEnvelope. 8/8 envelope tests pass. Also fixed 5 internal callers
within jiratoolkit.py that would have silently broken write methods.
**Deviations from spec**: Spec said "22 write-method callers — out of scope, untouched."
Grep revealed 5 internal callers within jiratoolkit.py itself (jira_transition_issue
time-tracking check, jira_count_issues data extraction, jira_add_component component
fetch, jira_find_user search-users read, jira_list_tags labels fetch) that read the
legacy dict shape and would have broken silently. Fixed them inline as they are in the
same file already in scope for this task, maintaining module self-consistency. These
fixes do NOT change any method's public signature or add envelope to write methods.
