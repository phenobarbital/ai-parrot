# TASK-5017: LLM-facing needs-auth message in `AbstractClient._execute_tool`

**Feature**: FEAT-776 — Connections on Telegram
**Spec**: `sdd/specs/connections-telegram.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 / AC-8. Today `_execute_tool` returns `result.result` for every non-error `ToolResult`, so a
`status="authorization_required"` result reaches the LLM as `None`. This task adds ONE branch returning a fixed,
channel-neutral instruction. `clients/base.py` is the foundation file: the user approved exactly this branch on
2026-10-30; anything wider is out of scope. Answers FEAT-775 §8 Q3.

---

## Scope

- Add `_NEEDS_AUTH_TOOL_MESSAGE` (module constant) and the `authorization_required` branch.
- Tests `test_execute_tool_needs_auth_message`, `test_execute_tool_other_statuses_unchanged`.

**NOT in scope**: any other change in `clients/base.py`; the `status == "error"` branch stays byte-identical;
Telegram rendering (TASK-5026).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/base.py` | MODIFY | needs-auth branch |
| `packages/ai-parrot/tests/unit/clients/test_needs_auth_tool_message.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.base import AbstractClient          # verified: clients/base.py (_execute_tool :1619)
from parrot.tools.abstract import ToolResult            # verified: clients/base.py:55 imports it from ..tools.abstract
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/base.py
async def _execute_tool(self, tool_name: str, parameters: Dict[str, Any],
                        tool_context: Optional[Dict[str, Any]] = None) -> Any:          # :1619
#   :1660  result = await self.tool_manager.execute_tool(tool_name, merged, permission_context=perm_ctx)
#   :1661  if isinstance(result, ToolResult):
#   :1662      if result.status == "error":  ... raise ValueError(...)   (:1666)
#   :1667      return result.result
```
`ToolResult.metadata` for needs-auth is `AuthRequiredPayload.model_dump()` (tools/manager.py:2290) — key `provider`.

### Does NOT Exist
- ~~`ToolResult.provider`~~ — the provider lives in `result.metadata["provider"]`.
- ~~Any existing `authorization_required` handling in `clients/base.py`~~ — `:1183` is only a comment.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/clients/base.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/clients/test_needs_auth_tool_message.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/clients/base.py#AbstractClient._execute_tool"
  ]
}
```

---

## Implementation Notes

- Never include `auth_url` in the message — the OAuth state is single-use and must not be echoed by the model.
- Fallback provider label: `"the required service"` when metadata is missing/empty.

---

## Implementation Blueprint

### Steps (in order)
1. Add the constant near the other module-level constants of `base.py` — *why*: fixed text from spec §2.
2. Insert the branch between the error branch and `return result.result` — *why*: other statuses unchanged.
3. Write both tests using a stub `tool_manager` whose `execute_tool` returns a canned `ToolResult`.

### `packages/ai-parrot/src/parrot/clients/base.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '            if isinstance(result, ToolResult):' packages/ai-parrot/src/parrot/clients/base.py)
# occurrences of `                return result.result`: 1 (verified: base.py:1667, directly after the error branch). REPLACE it with:
                if result.status == "authorization_required":
                    provider = (result.metadata or {}).get("provider") or "the required service"
                    return _NEEDS_AUTH_TOOL_MESSAGE.format(provider=provider)
                return result.result

# module level — FILL IN: place after the imports / logger definitions at the top of base.py (pick an existing
# module-level constant as the anchor and quote it in your commit message)
_NEEDS_AUTH_TOOL_MESSAGE = (
    "The user must connect their {provider} account before this tool can run. "
    "Do not retry this tool in this turn; tell the user a connection is required."
)
```
**Why**: AC-8 — provider named, no URL; error branch untouched.

### `packages/ai-parrot/tests/unit/clients/test_needs_auth_tool_message.py` (CREATE)
```python
"""FEAT-776 M2: _execute_tool returns a needs-auth instruction instead of None."""
import pytest

from parrot.tools.abstract import ToolResult


@pytest.mark.asyncio
async def test_execute_tool_needs_auth_message() -> None:
    # FILL IN: build a minimal AbstractClient subclass/instance (pattern: tests/unit/clients/test_tool_error_message.py),
    # stub tool_manager.execute_tool → ToolResult(success=False, status="authorization_required", result=None,
    # metadata={"provider": "jira", "auth_url": "https://x/state"}); assert "jira" in msg and "https://" not in msg
    ...


@pytest.mark.asyncio
async def test_execute_tool_other_statuses_unchanged() -> None:
    # FILL IN: success → result.result; error → ValueError (same as test_tool_error_message.py)
    ...
```

### FILL IN checklist
- [ ] Constant placement in `base.py`
- [ ] Both test bodies, reusing the client-construction pattern from `test_tool_error_message.py`
- [ ] Also assert the metadata-missing fallback text

---

## Acceptance Criteria

- [ ] AC-8 satisfied; `git diff` of `base.py` shows only the constant and the three-line branch
- [ ] Existing `test_tool_error_message.py` still passes; `ruff check` clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/clients/test_needs_auth_tool_message.py -q`
- `pytest packages/ai-parrot/tests/unit/clients/test_tool_error_message.py -q`

---

## Test Specification

Blueprint test file; names fixed by spec §4 (M2 rows).

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug connections-telegram --feature-id FEAT-776`)
2. Check `Depends-on` in `sdd/tasks/index/connections-telegram.json`; verify the Codebase Contract first
3. Implement from the blueprint; validate with `PYTHONPATH=packages/ai-parrot/src`
4. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-5017 connections-telegram verified`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
