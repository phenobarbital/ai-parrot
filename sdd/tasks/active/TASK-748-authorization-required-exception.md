# TASK-748: AuthorizationRequired Exception + ToolManager Handling

**Feature**: FEAT-107 — Jira OAuth 2.0 (3LO) Per-User Authentication
**Spec**: `sdd/specs/FEAT-107-jira-oauth2-3lo.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-747
**Assigned-to**: unassigned

---

## Context

Module 2 of the spec. When a toolkit's `_pre_execute()` detects that a user hasn't authorized, it raises `AuthorizationRequired`. This task defines that exception and modifies `ToolManager.execute_tool()` to catch it and convert it to a structured `ToolResult` with `status='authorization_required'`.

This allows the LLM to receive an actionable auth URL rather than an opaque error.

---

## Scope

- Create `AuthorizationRequired` exception class in `parrot/auth/exceptions.py`.
- Modify `ToolManager.execute_tool()` to catch `AuthorizationRequired` and return a `ToolResult(status='authorization_required', success=False, metadata={auth_url, provider, scopes})`.
- Export `AuthorizationRequired` from `parrot.auth.__init__`.
- Write unit tests.

**NOT in scope**: `CredentialResolver` (TASK-750), `JiraOAuthManager` (TASK-751), any Jira-specific logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/exceptions.py` | CREATE | AuthorizationRequired exception |
| `packages/ai-parrot/src/parrot/auth/__init__.py` | MODIFY | Export AuthorizationRequired |
| `packages/ai-parrot/src/parrot/tools/manager.py` | MODIFY | Catch AuthorizationRequired in execute_tool |
| `packages/ai-parrot/tests/unit/test_auth_required.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.manager import ToolManager  # verified: packages/ai-parrot/src/parrot/tools/manager.py:202
from parrot.tools.abstract import ToolResult, AbstractTool  # verified: packages/ai-parrot/src/parrot/tools/abstract.py:36,71
from parrot.auth import PermissionContext, UserSession  # verified: packages/ai-parrot/src/parrot/auth/__init__.py:29
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/manager.py:1123
async def execute_tool(
    self,
    tool_name: str,
    parameters: Dict[str, Any],
    permission_context: Optional["PermissionContext"] = None,
) -> Any:
    # Lines 1151-1200: try/except block catches generic Exception
    # Currently does NOT catch AuthorizationRequired — this task adds it
    # The except block at line 1196 catches Exception and re-raises

# packages/ai-parrot/src/parrot/tools/abstract.py:36
class ToolResult(BaseModel):
    success: bool = Field(default=True)
    status: str = Field(default="success")
    result: Any = Field(...)
    error: Optional[str] = Field(default=None)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    files: Optional[list] = Field(default_factory=list)
    images: Optional[list] = Field(default_factory=list)
    voice_text: Optional[str] = Field(default=None)
    display_data: Optional[Dict[str, Any]] = Field(default=None)
```

### Does NOT Exist
- ~~`parrot.auth.exceptions`~~ — module does NOT exist yet (this task creates it)
- ~~`AuthorizationRequired`~~ — exception does NOT exist yet (this task creates it)
- ~~ToolManager catching `AuthorizationRequired`~~ — not implemented yet (this task adds it)

---

## Implementation Notes

### Exception Design
```python
# packages/ai-parrot/src/parrot/auth/exceptions.py
class AuthorizationRequired(Exception):
    """Raised when a toolkit needs user authorization before operating.

    ToolManager catches this and converts it to a ToolResult with
    status='authorization_required'.
    """
    def __init__(
        self,
        tool_name: str,
        message: str,
        auth_url: str | None = None,
        provider: str = "unknown",
        scopes: list[str] | None = None,
    ):
        super().__init__(message)
        self.tool_name = tool_name
        self.message = message
        self.auth_url = auth_url
        self.provider = provider
        self.scopes = scopes or []
```

### ToolManager Integration
Add a specific `except AuthorizationRequired` BEFORE the generic `except Exception` in `execute_tool()` (around line 1196):

```python
except AuthorizationRequired as auth_exc:
    self.logger.info(
        f"Authorization required for tool {tool_name}: {auth_exc.provider}"
    )
    return ToolResult(
        success=False,
        status='authorization_required',
        result=None,
        error=auth_exc.message,
        metadata={
            "auth_url": auth_exc.auth_url,
            "provider": auth_exc.provider,
            "scopes": auth_exc.scopes,
            "tool_name": auth_exc.tool_name,
        }
    )
```

### Key Constraints
- The `except AuthorizationRequired` must come before `except Exception` to avoid being swallowed.
- Import `AuthorizationRequired` at the top of `manager.py` using a conditional or direct import.

---

## Acceptance Criteria

- [ ] `AuthorizationRequired` exception exists in `parrot.auth.exceptions`
- [ ] Exported from `parrot.auth.__init__`
- [ ] `ToolManager.execute_tool()` catches it and returns `ToolResult(status='authorization_required')`
- [ ] `ToolResult.metadata` contains `auth_url`, `provider`, `scopes`, `tool_name`
- [ ] Generic exceptions still propagate normally (no regression)
- [ ] `ToolResult(status='forbidden')` handling is unchanged
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/test_auth_required.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/test_auth_required.py
import pytest
from parrot.auth.exceptions import AuthorizationRequired
from parrot.tools.abstract import ToolResult


class TestAuthorizationRequired:
    def test_exception_attributes(self):
        exc = AuthorizationRequired(
            tool_name="jira_create_issue",
            message="Jira authorization required",
            auth_url="https://auth.atlassian.com/authorize?...",
            provider="jira",
            scopes=["read:jira-work", "write:jira-work"],
        )
        assert exc.tool_name == "jira_create_issue"
        assert exc.auth_url.startswith("https://")
        assert exc.provider == "jira"
        assert "read:jira-work" in exc.scopes

    def test_exception_defaults(self):
        exc = AuthorizationRequired(
            tool_name="some_tool",
            message="Auth needed",
        )
        assert exc.provider == "unknown"
        assert exc.scopes == []
        assert exc.auth_url is None

    def test_exception_is_catchable(self):
        with pytest.raises(AuthorizationRequired):
            raise AuthorizationRequired(
                tool_name="test", message="test"
            )
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-107-jira-oauth2-3lo.spec.md` for full context
2. **Check dependencies** — verify TASK-747 is in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm `ToolManager.execute_tool()` exception handling at line ~1196
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-748-authorization-required-exception.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any
