---
type: Wiki Overview
title: 'TASK-1404: GrantGuard (Governor)'
id: doc:sdd-tasks-completed-task-1404-grant-guard-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The `GrantGuard` is the decision engine ("Governor") that sits between the
relates_to:
- concept: mod:parrot.auth.grants
  rel: mentions
- concept: mod:parrot.auth.permission
  rel: mentions
- concept: mod:parrot.human.manager
  rel: mentions
- concept: mod:parrot.human.models
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
---

# TASK-1404: GrantGuard (Governor)

**Feature**: FEAT-211 — Tool Grants & Bounded Approval Windows
**Spec**: `sdd/specs/FEAT-211-tool-grants-bounded-approval.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1403
**Assigned-to**: unassigned

---

## Context

> Spec Module 2: GrantGuard (the Governor).

The `GrantGuard` is the decision engine ("Governor") that sits between the
agent's tool call and the actual tool execution. Given a tool, its parameters,
and a permission context, it decides: **allow** (active grant exists), **approve**
(request HITL approval via `HumanInteractionManager` and open a bounded window),
or **deny** (no grant, no channel — fail-closed).

This task adds `GrantGuard` and `GuardDecision` to the same `grants.py` file
created by TASK-1403. It reuses the existing HITL infrastructure
(`HumanInteractionManager`, `InteractionType.APPROVAL`) — no new approval
mechanism is created.

---

## Scope

- Add to `packages/ai-parrot/src/parrot/auth/grants.py`:
  - `GuardDecision(BaseModel)` — result of `authorize()`: `allowed: bool`,
    `reason: str`, `grant: Optional[Grant]`.
  - `GrantGuard` — the Governor class:
    - `__init__(store, human_manager=None, config=None)`.
    - `async def authorize(*, tool, parameters, permission_context) -> GuardDecision`:
      1. Check `tool.routing_meta.get("requires_grant")` — if not set, allow
         immediately (non-gated tool).
      2. Resolve scope: `routing_meta.get("grant_scope", f"tool:{tool.name}")`.
      3. Resolve owner: `permission_context.user_id` (or fallback).
      4. Query `store.is_allowed(owner, scope)` — if True, allow.
      5. If False and `human_manager` is set → request HITL approval.
      6. If approved → `store.grant(owner, scope, window=...)` → allow.
      7. If rejected or no `human_manager` → deny (fail-closed).
- Write unit tests in `packages/ai-parrot/tests/tools/test_grants.py` (append
  to file created by TASK-1403).

**NOT in scope**:
- Grant models / GrantStore (TASK-1403 — already done)
- ToolManager integration (TASK-1405)
- Auth exports wiring (TASK-1406)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/grants.py` | MODIFY | Add GuardDecision, GrantGuard |
| `packages/ai-parrot/tests/tools/test_grants.py` | MODIFY | Add GrantGuard unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.

### Verified Imports
```python
# From TASK-1403 (will exist by the time this task runs):
from parrot.auth.grants import Grant, GrantConfig, GrantStore, InMemoryGrantStore

# HITL infrastructure — VERIFIED in the actual codebase:
from parrot.human.manager import HumanInteractionManager  # verified: human/manager.py:51
from parrot.human.models import (
    HumanInteraction,         # verified: human/models.py:380
    InteractionType,          # verified: human/models.py:60  (APPROVAL = "approval" at :66)
    InteractionResult,        # verified: human/models.py:498
    InteractionStatus,        # verified: human/models.py:71  (COMPLETED = "completed")
)

# Permission context:
from parrot.auth.permission import PermissionContext  # verified: auth/permission.py:80

# Tool types (for type hints in authorize()):
from parrot.tools.abstract import AbstractTool  # verified: tools/abstract.py:81
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/human/manager.py:283
class HumanInteractionManager:
    async def request_human_input(
        self,
        interaction: HumanInteraction,
        channel: str = "telegram",
    ) -> InteractionResult:
        # BLOCKING — waits on asyncio.Future until human responds or timeout
        ...

# packages/ai-parrot/src/parrot/human/models.py:380
class HumanInteraction(BaseModel):
    interaction_id: str          # auto-generated if not provided
    interaction_type: InteractionType
    question: str
    timeout: float = 7200.0      # seconds before timeout
    default_response: Any = None # returned on timeout
    severity: str = "medium"
    policy_id: str | None = None

# packages/ai-parrot/src/parrot/human/models.py:498
class InteractionResult(BaseModel):
    interaction_id: str
    status: InteractionStatus   # COMPLETED, TIMEOUT, etc.
    consolidated_value: Any     # bool for APPROVAL type

# packages/ai-parrot/src/parrot/auth/permission.py:80
@dataclass
class PermissionContext:
    session: UserSession
    @property
    def user_id(self) -> str: ...  # delegates to session.user_id

# packages/ai-parrot/src/parrot/tools/abstract.py:81
class AbstractTool(EventEmitterMixin, ABC):
    name: str                         # tool name
    routing_meta: Dict                # line 100/140 — per-instance dict
```

### Does NOT Exist
- ~~`GrantGuard`~~ — **does not exist yet**. This task creates it.
- ~~`GuardDecision`~~ — does not exist yet.
- ~~`BeforeToolCallEvent` veto capability~~ — lifecycle events are OBSERVATIONAL,
  NOT veto-capable. The guard MUST live in `execute_tool`, not in an event handler.
- ~~`tool.requires_grant` attribute~~ — tools have NO such attribute. The flag
  lives in `tool.routing_meta["requires_grant"]`, a dict key, not a class attribute.
- ~~`HumanInteractionManager.approve()`~~ — no such method. Use `request_human_input()`.

---

## Implementation Notes

### Pattern to Follow
```python
class GuardDecision(BaseModel):
    allowed: bool
    reason: str
    grant: Grant | None = None

class GrantGuard:
    def __init__(
        self,
        store: GrantStore,
        human_manager: HumanInteractionManager | None = None,
        config: GrantConfig | None = None,
    ) -> None:
        self.store = store
        self.human_manager = human_manager
        self.config = config or GrantConfig()
        self.logger = logging.getLogger(__name__)

    async def authorize(
        self,
        *,
        tool: AbstractTool,
        parameters: dict,
        permission_context: PermissionContext | None = None,
    ) -> GuardDecision:
        # 1. Non-gated tool → allow immediately
        if not tool.routing_meta.get("requires_grant"):
            return GuardDecision(allowed=True, reason="tool does not require grant")

        # 2. Resolve scope + owner
        scope = tool.routing_meta.get("grant_scope", f"tool:{tool.name}")
        owner = permission_context.user_id if permission_context else "anonymous"

        # 3. Check existing grant
        if await self.store.is_allowed(owner, scope):
            return GuardDecision(allowed=True, reason="active grant covers scope")

        # 4. Request HITL approval (or fail-closed)
        if self.human_manager is None:
            return GuardDecision(allowed=False, reason="no grant and no approval channel (fail-closed)")

        # ... request approval, handle result ...
```

### Key Constraints
- `authorize()` must be **idempotent for the decision**: calling it twice within
  the window for the same (owner, scope) should return `allowed=True` on the
  second call without re-requesting HITL approval.
- The `HumanInteraction` payload must use `InteractionType.APPROVAL` and set
  `timeout` from `config.approval_timeout`, `default_response=False` (deny on
  timeout → fail-closed).
- `channel` for HITL comes from `config.default_channel` (or could be overridden
  via `permission_context.channel` if present).
- The scope resolution (step 2) uses `routing_meta["grant_scope"]` if present,
  otherwise defaults to `f"tool:{tool.name}"`.
- If `permission_context` is None, use `"anonymous"` as owner_id.
- Window seconds: read from `routing_meta.get("grant_window_seconds", config.window_seconds)`.

### References in Codebase
- `packages/ai-parrot/src/parrot/human/manager.py:283` — `request_human_input` (HITL entry point)
- `packages/ai-parrot/src/parrot/human/models.py:66` — `InteractionType.APPROVAL`
- `packages/ai-parrot/src/parrot/auth/permission.py:80` — `PermissionContext` with `user_id` property

---

## Acceptance Criteria

- [ ] `GrantGuard.authorize()` allows immediately for tools without `requires_grant`.
- [ ] With active grant, `authorize()` allows without calling HITL.
- [ ] Without grant + human_manager approves → creates grant window, allows.
- [ ] Second call within window does NOT re-request HITL approval.
- [ ] HITL rejection → `GuardDecision(allowed=False)`, no grant created.
- [ ] No human_manager + no grant → fail-closed (`allowed=False`).
- [ ] Timeout on HITL → denied (default_response=False → fail-closed).
- [ ] All tests pass: `pytest packages/ai-parrot/tests/tools/test_grants.py -v -k "guard"`.
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/auth/grants.py`.

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/test_grants.py (append to existing)
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.auth.grants import (
    Grant, GrantConfig, InMemoryGrantStore, GrantGuard, GuardDecision,
)
from parrot.human.models import InteractionResult, InteractionStatus, InteractionType


def _make_tool(name="pulumi_apply", requires_grant=True, **extra_meta):
    tool = MagicMock()
    tool.name = name
    tool.routing_meta = {"requires_grant": requires_grant, **extra_meta}
    return tool


def _make_pctx(user_id="user-1"):
    pctx = MagicMock()
    pctx.user_id = user_id
    pctx.channel = "telegram"
    return pctx


def _approve_manager():
    m = MagicMock()
    async def _req(interaction, channel="telegram"):
        return InteractionResult(
            interaction_id=interaction.interaction_id,
            status=InteractionStatus.COMPLETED,
            consolidated_value=True,
        )
    m.request_human_input = AsyncMock(side_effect=_req)
    return m


def _reject_manager():
    m = MagicMock()
    async def _req(interaction, channel="telegram"):
        return InteractionResult(
            interaction_id=interaction.interaction_id,
            status=InteractionStatus.COMPLETED,
            consolidated_value=False,
        )
    m.request_human_input = AsyncMock(side_effect=_req)
    return m


@pytest.mark.asyncio
class TestGrantGuard:
    async def test_non_gated_tool_allowed(self):
        """Tool without requires_grant passes through immediately."""
        store = InMemoryGrantStore()
        guard = GrantGuard(store)
        tool = _make_tool(requires_grant=False)
        decision = await guard.authorize(tool=tool, parameters={}, permission_context=None)
        assert decision.allowed is True

    async def test_allows_with_active_grant(self):
        """Existing active grant → allowed without HITL."""
        store = InMemoryGrantStore()
        await store.grant("user-1", "tool:pulumi_apply",
                          granted_by="admin", window_seconds=900)
        guard = GrantGuard(store)
        decision = await guard.authorize(
            tool=_make_tool(), parameters={},
            permission_context=_make_pctx(),
        )
        assert decision.allowed is True

    async def test_requests_approval_then_grants(self):
        """No grant + approve → creates grant, allows; 2nd call no re-ask."""
        store = InMemoryGrantStore()
        hm = _approve_manager()
        guard = GrantGuard(store, human_manager=hm)
        pctx = _make_pctx()
        tool = _make_tool()

        d1 = await guard.authorize(tool=tool, parameters={}, permission_context=pctx)
        assert d1.allowed is True
        assert hm.request_human_input.call_count == 1

        # Second call within window — no re-ask
        d2 = await guard.authorize(tool=tool, parameters={}, permission_context=pctx)
        assert d2.allowed is True
        assert hm.request_human_input.call_count == 1  # still 1

    async def test_denied_on_reject(self):
        """HITL rejects → denied, no grant created."""
        store = InMemoryGrantStore()
        hm = _reject_manager()
        guard = GrantGuard(store, human_manager=hm)

        decision = await guard.authorize(
            tool=_make_tool(), parameters={},
            permission_context=_make_pctx(),
        )
        assert decision.allowed is False
        assert await store.is_allowed("user-1", "tool:pulumi_apply") is False

    async def test_failclosed_no_channel(self):
        """requires_grant + no grant + no human_manager → fail-closed."""
        store = InMemoryGrantStore()
        guard = GrantGuard(store, human_manager=None)

        decision = await guard.authorize(
            tool=_make_tool(), parameters={},
            permission_context=_make_pctx(),
        )
        assert decision.allowed is False
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-211-tool-grants-bounded-approval.spec.md` for full context
2. **Check dependencies** — verify TASK-1403 is completed (grants.py exists with Grant/GrantStore)
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm `parrot/auth/grants.py` exists with `Grant`, `GrantStore`, `InMemoryGrantStore`
   - Confirm `HumanInteractionManager.request_human_input` signature at `human/manager.py:283`
   - Confirm `InteractionType.APPROVAL` at `human/models.py:66`
4. **Update status** in `sdd/tasks/index/tool-grants-bounded-approval.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1404-grant-guard.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-06-01
**Notes**: Added `GuardDecision` and `GrantGuard` to `grants.py` (same file as
TASK-1403, as specified). `GrantGuard.authorize()` implements the full
allow/approve/deny logic with HITL via `HumanInteractionManager`. 8 guard tests
pass. Imports use `TYPE_CHECKING` where needed to avoid circular imports.

**Deviations from spec**: None.

**Deviations from spec**: none | describe if any
