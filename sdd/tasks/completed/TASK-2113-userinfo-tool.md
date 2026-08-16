# TASK-2113: `UserinfoTool`

**Feature**: FEAT-406 — PBAC Guardrails
**Spec**: `sdd/specs/pbac-guardrails.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2112
**Assigned-to**: unassigned

---

## Context

Agents need a way to query the current user's structured profile — for display,
for reasoning about the user's role/permissions, and for injecting into prompts.
`UserinfoTool` is a standard `AbstractTool` that returns the session user's
`EmployeeProfile` as JSON.

Identity always comes from the session/`PermissionContext` — never from an
LLM-supplied argument (security invariant). The tool is activated per-agent via
standard tool registration.

Implements spec §3 Module 5.

---

## Scope

- Create `UserinfoTool(AbstractTool)` in `packages/ai-parrot/src/parrot/tools/userinfo.py`:
  - `name = "userinfo"`
  - Accepts a `UserInfoService` instance at construction
  - `async def _execute(self, **kwargs) -> Any`:
    - Get `user_id` from session/`PermissionContext` (passed via `execute()`'s
      `permission_context` or stored on the tool)
    - Ignore any LLM-supplied `user_id` argument (security invariant)
    - Call `UserInfoService.get_profile(user_id)`
    - Return profile as JSON dict; if `None` → structured "profile unavailable" result
  - Docstring describes the tool for the LLM: "Get the current user's profile information"
- Write unit tests

**NOT in scope**: Registering in any bot's default tool set, PBAC attribute
enrichment (TASK-2114), or modifying `UserInfo`/`UserProfileKB`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/userinfo.py` | CREATE | `UserinfoTool` |
| `packages/ai-parrot/tests/tools/test_userinfo_tool.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.abstract import AbstractTool        # tools/abstract.py:233
from parrot.tools.result import ToolResult             # tools/result.py
from parrot.auth.userinfo import UserInfoService, EmployeeProfile  # TASK-2112 creates this
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/abstract.py:233
class AbstractTool(EventEmitterMixin, ABC):
    name: str                                          # tool name for LLM
    description: str                                   # docstring becomes LLM description
    async def _execute(self, **kwargs) -> Any          # line 471 (abstract work method)
    async def execute(self, *args, **kwargs) -> ToolResult  # line 719 (outer wrapper)
    # execute() handles permission_context, Layer-2 resolver, redaction, etc.

# packages/ai-parrot/src/parrot/tools/result.py
class ToolResult(BaseModel):
    success: bool
    status: str              # "success", "forbidden", "error", etc.
    error: str | None = None
    result: Any = None
```

### Does NOT Exist
- ~~`parrot/tools/userinfo.py`~~ — does not exist; this task creates it.
- ~~`UserinfoTool`~~ — does not exist anywhere.
- ~~`AbstractTool.permission_context`~~ — not a direct attribute; it's passed via `execute()` kwargs.
- ~~`AbstractTool.session_user_id`~~ — not a real attribute; identity comes from `permission_context`.
- ~~`parrot/tools/result.py`~~ — does not exist; `ToolResult` is defined in
  `tools/abstract.py:198`, not a separate `result.py` module.

**Codebase Contract corrections (verified 2026-08-04)**:
1. `from parrot.tools.result import ToolResult` is stale — `ToolResult` lives
   in `parrot.tools.abstract` (`class ToolResult(BaseModel)`, line 198); no
   `tools/result.py` module exists.
2. **Identity threading**: `AbstractTool.execute()` pops `_permission_context`
   from kwargs (line 735) and stores it on the instance as
   `self._current_pctx` (line 770, reset to `None` in a `finally` at line
   1023) BEFORE dispatching to `_execute()` — so `_execute(**kwargs)` never
   receives `_permission_context` in its own kwargs at all (confirmed by
   reading `execute()` end-to-end). The task's suggested
   `kwargs.get("_permission_context_user_id")` pattern does not exist;
   `self._current_pctx` (a `PermissionContext | None`, whose `.user_id`
   property already exists — `auth/permission.py:129-131`) is the real,
   verified access point.
3. With the default `args_schema = AbstractToolArgsSchema` (no fields
   declared), `validate_args()` (`tools/abstract.py:628-630`) returns a bare
   `AbstractToolArgsSchema()` regardless of what kwargs were passed, and
   `_execute()` is dispatched with the resulting **empty** `resolved_kwargs`
   (`.model_dump()` of a model with no fields) — i.e. `UserinfoTool` never
   even sees whatever arguments the LLM supplied, an even stronger form of
   the "ignore any LLM-supplied identity argument" security invariant than
   defensively checking a kwarg. `UserinfoTool` intentionally leaves
   `args_schema` at its default for this reason.

---

## Implementation Notes

### Pattern to Follow
Mirror existing simple tools (e.g. tools in `parrot/tools/`):
```python
import logging
from typing import Any
from parrot.tools.abstract import AbstractTool

logger = logging.getLogger(__name__)

class UserinfoTool(AbstractTool):
    """Get the current user's profile information.

    Returns the session user's structured profile as JSON including
    name, email, job code, department, groups, and manager info.
    """
    name = "userinfo"

    def __init__(self, service, **kwargs):
        super().__init__(**kwargs)
        self._service = service
        self.logger = logging.getLogger(__name__)

    async def _execute(self, **kwargs) -> Any:
        # Identity from session, never from LLM argument
        user_id = kwargs.get("_permission_context_user_id")
        # or however permission_context is threaded through
        if user_id is None:
            return {"status": "unavailable", "message": "No session user identified"}
        profile = await self._service.get_profile(user_id)
        if profile is None:
            return {"status": "unavailable", "message": "Profile not found"}
        return profile.model_dump(mode="json")
```

### Key Constraints
- Identity MUST come from session/`PermissionContext`, never from an LLM argument
- The tool should have no input parameters exposed to the LLM (or parameters that are ignored)
- Missing profile → structured "unavailable" result, never an exception
- JSON output must match `EmployeeProfile` schema

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/abstract.py` — AbstractTool base class
- `packages/ai-parrot/src/parrot/auth/userinfo.py` — UserInfoService (created by TASK-2112)

---

## Acceptance Criteria

- [ ] `UserinfoTool` class exists in `parrot/tools/userinfo.py`
- [ ] Tool ignores any LLM-supplied identity argument; uses session user
- [ ] Returns valid JSON matching `EmployeeProfile` schema
- [ ] Missing profile → structured "profile unavailable" result, no exception
- [ ] All tests pass: `pytest packages/ai-parrot/tests/tools/test_userinfo_tool.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/tools/userinfo.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/test_userinfo_tool.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.auth.userinfo import EmployeeProfile, ManagerRef


class TestUserinfoTool:
    async def test_userinfo_tool_session_identity_only(self):
        """Tool ignores any LLM-supplied identity argument; uses session user."""

    async def test_userinfo_tool_json_output(self):
        """Returns valid JSON matching EmployeeProfile schema."""

    async def test_userinfo_tool_missing_profile(self):
        """Missing profile → structured unavailable result, no exception."""

    async def test_userinfo_tool_no_session(self):
        """No session/permission_context → structured unavailable result."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-2112 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — read `tools/abstract.py` to confirm how `permission_context` is threaded
4. **Update status** in `sdd/tasks/index/pbac-guardrails.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2113-userinfo-tool.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-04
**Notes**: Implemented `UserinfoTool(AbstractTool)` in `tools/userinfo.py`.
Identity is read exclusively from `self._current_pctx` (set by
`AbstractTool.execute()` from `_permission_context`, never from kwargs);
`args_schema` intentionally left at its `AbstractToolArgsSchema` default so
`execute()`'s own validation strips any LLM-supplied arguments before
`_execute()` is even called — a stronger guarantee than defensively
ignoring a kwarg. Missing session or missing profile row both return a
structured `{"status": "unavailable", "message": ...}` dict, never an
exception. Class docstring doubles as the LLM-facing tool description
(`AbstractTool.__init__`'s existing `self.description = description or
self.__class__.__doc__ or ...` convention). 6 new unit tests (direct
`_execute()` + full `execute()` wrapper paths, JSON round-trip through
`EmployeeProfile`, missing profile, no session, LLM-supplied-kwarg
ignored) pass; full guardrails/grants/confirmation regression suite (176
tests) passes; `ruff check` clean.

**Deviations from spec**: `ToolResult` import corrected — it lives in
`parrot.tools.abstract` (line 198), not a `parrot.tools.result` module
(which does not exist). Identity access corrected from the task's
suggested `kwargs.get("_permission_context_user_id")` to
`self._current_pctx.user_id` — the real, verified mechanism
`AbstractTool.execute()` uses to thread the permission context to
`_execute()` (confirmed by reading `execute()` end-to-end: it pops
`_permission_context` from kwargs and stores it as `self._current_pctx`
before dispatch, resetting it to `None` afterward). Both documented in the
task's corrected Codebase Contract section above before implementing.
