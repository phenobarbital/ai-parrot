---
type: Wiki Overview
title: 'TASK-953: Harden JiraToolkit error messages for LLM consumption'
id: doc:sdd-tasks-completed-task-953-jiratoolkit-error-hardening-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: When JiraToolkit tool methods fail (connection errors, HTTP 401/403, timeouts),
relates_to:
- concept: mod:parrot.auth.exceptions
  rel: mentions
- concept: mod:parrot.tools.manager
  rel: mentions
- concept: mod:parrot_tools.jiratoolkit
  rel: mentions
---

# TASK-953: Harden JiraToolkit error messages for LLM consumption

**Feature**: FEAT-139 — Jira Analyst System Prompt Hardening
**Spec**: `sdd/specs/jira-analyst-systemprompt-hardening.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

When JiraToolkit tool methods fail (connection errors, HTTP 401/403, timeouts),
the exceptions currently bubble up as raw Python errors. The LLM receives a
generic error message like `"ConnectionError: ..."` or `"JIRAError: ..."` without
any guidance on how to respond. This causes the LLM to fall back on training data
and hallucinate plausible Jira ticket information.

This task wraps common failure modes with clear, LLM-facing error messages that
explicitly instruct the LLM not to fabricate data. This is independent of the
prompt layer changes (TASK-950/951/952) and can be implemented in parallel.

Implements spec Module 4 (JiraToolkit Error Message Hardening).

---

## Scope

- Add a helper method or decorator in JiraToolkit to wrap common exceptions with
  LLM-friendly error messages
- Wrap the following failure modes:
  1. **Connection errors** (ConnectionError, requests.ConnectionError, socket errors)
     → `{"error": "Jira is unreachable (connection failed). Do NOT invent or guess any Jira data. Report this error to the user.", "type": "connection_error"}`
  2. **Timeout errors** (asyncio.TimeoutError, requests.Timeout)
     → `{"error": "Jira request timed out. Do NOT invent or guess any Jira data. Report this error to the user.", "type": "timeout"}`
  3. **HTTP 401/403** (JIRAError with status 401 or 403)
     → `{"error": "Jira credentials are expired or invalid (HTTP <status>). Ask the user to re-authorize. Do NOT use cached or remembered ticket data.", "type": "auth_error"}`
  4. **AuthorizationRequired** message enhancement — update the messages in
     `_pre_execute` (lines 859, 873, 889) to include anti-fabrication text
  5. **Generic JIRA API errors** — catch-all for other JIRAError exceptions
     → `{"error": "Jira API error: <message>. Do NOT invent data to compensate. Report this error.", "type": "api_error"}`
- Write unit tests for each error type

**NOT in scope**: Prompt layer changes (TASK-950/951/952), retry logic, token refresh.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY | Add error wrapping to tool methods and _pre_execute |
| `packages/ai-parrot-tools/tests/test_jiratoolkit_errors.py` | CREATE | Unit tests for error messages |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
from jira import JIRA  # line 46
from parrot.tools.manager import ToolManager  # line 51
from parrot.auth.exceptions import AuthorizationRequired  # line 52
from .toolkit import AbstractToolkit  # line 53
from .decorators import tool_schema, requires_permission  # line 54

# Standard library (already imported in jiratoolkit.py)
import asyncio  # line 33
import logging  # line 32
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
class JiraToolkit(AbstractToolkit):  # line 609
    auth_type: str  # line ~620
    server_url: str  # line ~618
    request_timeout: int  # (used at line 1490)
    jira: JIRA  # the underlying client instance
    logger: logging.Logger  # inherited from AbstractToolkit

    async def _pre_execute(self, tool_name: str, **kwargs) -> None:  # line 845
        # Raises AuthorizationRequired at lines 859, 873, 889
        # Messages to update:
        # line 862: "Permission context is required for Jira OAuth 2.0 (3LO)..."
        # line 874: "Cannot resolve Jira credentials without a user_id."
        # line 892: "Please authorize your Jira account to use this tool."

    async def jira_get_issue(self, issue: str, ...) -> Dict:  # line 1159
        # Uses asyncio.to_thread(_run) — no explicit error handling
        # _run() calls self.jira.issue(issue, ...)

    async def jira_create_issue(self, ...) -> Dict:  # line 1366
        # Has asyncio.TimeoutError handling at line 1492-1496
        # Pattern to follow for timeout wrapping

    async def jira_search_issues(self, jql: str, ...) -> Dict:  # line 2189
        # Uses asyncio.to_thread for JIRA API calls

    def _probe_auth_sync(self) -> Dict[str, Any]:  # line 1776
        # Already returns structured error dict with "authenticated" and "error" keys
        # Good pattern to follow for error responses

# packages/ai-parrot/src/parrot/auth/exceptions.py
class AuthorizationRequired(Exception):  # line 12
    def __init__(self, tool_name, message, auth_url=None, provider="unknown", scopes=None)
```

### Does NOT Exist
- ~~`JiraToolkit._handle_connection_error()`~~ — no such method; must be created or error
  handling added inline
- ~~`JiraToolkit._wrap_error()`~~ — no such method
- ~~`from jira.exceptions import JIRAError`~~ — verify the actual import path; the jira
  package may use `jira.JIRAError` or `jira.exceptions.JIRAError`
- ~~`JiraToolkit.error_handler`~~ — no such attribute

---

## Implementation Notes

### Pattern to Follow
```python
# Follow the existing timeout handling at jira_create_issue (line 1487-1496):
try:
    obj = await asyncio.wait_for(
        asyncio.to_thread(_run),
        timeout=self.request_timeout + 5,
    )
except asyncio.TimeoutError as exc:
    raise TimeoutError(...) from exc

# For error wrapping, add a common wrapper approach.
# Option A: A private method that catches and wraps exceptions:
def _jira_error_response(self, exc: Exception, operation: str) -> Dict[str, Any]:
    """Convert a JIRA/connection exception to an LLM-friendly error dict."""
    ...

# Option B: A decorator applied to tool methods
# Option A is simpler and recommended.
```

### Key Constraints
- The `jira` package's exception class: verify the import. It is likely
  `from jira.exceptions import JIRAError` or `from jira import JIRAError`.
  Run `grep -rn "JIRAError" .venv/lib/*/jira/` or check `jira.__init__`.
- Tool methods that currently let exceptions bubble up (like `jira_get_issue`)
  need try/except wrappers. Only wrap the `asyncio.to_thread(_run)` call.
- Return error dicts (not raise) for handled failures — this is what the LLM
  sees as tool output. The `ToolManager` at line 1185-1186 raises ValueError
  if `ToolResult.status == "error"`, but raw dicts returned by toolkit methods
  pass through as tool output.
- The `AuthorizationRequired` messages at lines 862, 874, 892 should be enhanced
  to include "Do NOT invent or guess any Jira data" text. These messages become
  the `error` field in the `ToolResult` returned by `ToolManager`.
- Preserve existing behavior: the `_pre_execute` must still raise
  `AuthorizationRequired` (not return a dict) — the ToolManager catches this.
  Only enhance the `message` parameter.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:1487-1496` — existing timeout pattern
- `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:1776-1819` — _probe_auth_sync error dict
- `packages/ai-parrot/src/parrot/tools/manager.py:1199-1216` — AuthorizationRequired handling
- `packages/ai-parrot/src/parrot/auth/exceptions.py:12-53` — AuthorizationRequired class

---

## Acceptance Criteria

- [ ] Connection errors return dict with clear "do not invent data" message
- [ ] Timeout errors return dict with clear "do not invent data" message
- [ ] HTTP 401/403 errors return dict with "credentials expired" + "do not use cached data" message
- [ ] `AuthorizationRequired` messages in `_pre_execute` include anti-fabrication text
- [ ] Generic JIRA API errors return structured error dict
- [ ] Error dicts include a `"type"` field for error classification
- [ ] Existing tool behavior is preserved for successful calls
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/test_jiratoolkit_errors.py -v`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/test_jiratoolkit_errors.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestJiraToolkitErrorMessages:
    """Test that JiraToolkit wraps errors with LLM-friendly messages."""

    @pytest.fixture
    def toolkit(self):
        """Create a JiraToolkit with mocked JIRA client."""
        from parrot_tools.jiratoolkit import JiraToolkit
        tk = JiraToolkit.__new__(JiraToolkit)
        tk.auth_type = "token_auth"
        tk.server_url = "https://test.atlassian.net"
        tk.jira = MagicMock()
        tk.logger = MagicMock()
        tk.request_timeout = 30
        tk._tool_manager = None
        tk.default_project = "TEST"
        return tk

    @pytest.mark.asyncio
    async def test_connection_error_message(self, toolkit):
        """Connection error returns LLM-friendly error dict."""
        toolkit.jira.issue.side_effect = ConnectionError("Connection refused")
        result = await toolkit.jira_get_issue("TEST-1")
        assert isinstance(result, dict)
        assert "error" in result
        assert "invent" in result["error"].lower() or "fabricat" in result["error"].lower()
        assert result.get("type") == "connection_error"

    @pytest.mark.asyncio
    async def test_auth_error_message(self, toolkit):
        """HTTP 401 returns auth-specific error message."""
        # Simulate JIRAError with 401 status
        from jira.exceptions import JIRAError
        toolkit.jira.issue.side_effect = JIRAError(status_code=401, text="Unauthorized")
        result = await toolkit.jira_get_issue("TEST-1")
        assert isinstance(result, dict)
        assert "error" in result
        assert "expired" in result["error"].lower() or "invalid" in result["error"].lower()
        assert result.get("type") == "auth_error"

    @pytest.mark.asyncio
    async def test_pre_execute_auth_message_includes_anti_fabrication(self, toolkit):
        """AuthorizationRequired message includes anti-fabrication text."""
        toolkit.auth_type = "oauth2_3lo"
        toolkit.credential_resolver = AsyncMock()
        toolkit.credential_resolver.resolve.return_value = None
        toolkit.credential_resolver.get_auth_url.return_value = "https://auth.example.com"
        toolkit._OAUTH_SCOPES = ["read:jira-work"]
        toolkit._client_cache = {}
        toolkit._CLIENT_CACHE_MAX_SIZE = 100

        from parrot.auth.exceptions import AuthorizationRequired
        with pytest.raises(AuthorizationRequired) as exc_info:
            await toolkit._pre_execute(
                "jira_get_issue",
                _permission_context=MagicMock(user_id="u1", channel="telegram"),
            )
        assert "invent" in exc_info.value.message.lower() or "fabricat" in exc_info.value.message.lower()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/jira-analyst-systemprompt-hardening.spec.md`
2. **This task has NO dependencies** — it can start immediately
3. **Verify JIRAError import** — run `python -c "from jira.exceptions import JIRAError; print(JIRAError)"` to confirm the import path
4. **Read the existing timeout handling** — `jiratoolkit.py:1487-1496`
5. **Read _pre_execute** — `jiratoolkit.py:845-916`
6. **Identify all tool methods** that need error wrapping — grep for `async def jira_`
7. **Implement** the error wrapping
8. **Test** each error type
9. **Move this file** to `tasks/completed/` and update index

---

## Completion Note

Completed 2026-05-01 by sdd-worker (FEAT-139 autonomous run).

Implementation:
- Added `_jira_error_response()` helper that classifies exceptions into
  `timeout`, `connection_error`, `auth_error`, or `api_error` and returns
  structured dicts with explicit anti-fabrication instructions.
- Key fix: `TimeoutError` check placed BEFORE `OSError` check because
  `TimeoutError` is a subclass of `OSError` in Python 3.
- Wrapped `jira_get_issue` with try/except so errors surface as structured
  dicts instead of propagating as raw exceptions.
- Updated all three `_pre_execute` `AuthorizationRequired` messages with
  anti-fabrication text ("Do NOT invent or guess any Jira data").
- 14 tests added covering all error types, the helper directly, and the
  `_pre_execute` anti-fabrication messages — all pass.

Committed: `feat(jira-analyst-systemprompt-hardening): TASK-953 — Harden JiraToolkit error messages for LLM consumption`

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
