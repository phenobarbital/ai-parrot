---
type: Wiki Overview
title: 'TASK-1387: Ephemeral ownership generalization'
id: doc:sdd-tasks-completed-task-1387-ephemeral-ownership-generalization-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The ephemeral agent subsystem (FEAT-149) currently hardcodes ownership to
relates_to:
- concept: mod:parrot.manager.ephemeral
  rel: mentions
---

# TASK-1387: Ephemeral ownership generalization

**Feature**: FEAT-208 — Spawn Ephemeral Sub-Agent Tool
**Spec**: `sdd/specs/FEAT-208-spawn-ephemeral-subagent-tool.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Implements Module 1 of FEAT-208 (§3).

The ephemeral agent subsystem (FEAT-149) currently hardcodes ownership to
`user_id: int`. For an agent to own its sub-agents, we need a typed ownership
model: `owner_id: str` + `owner_kind: Literal["user","agent"]`.

The refactor must be **additive** — `user_id: int` stays as a backward-compatible
alias so the HTTP handler (`EphemeralUserAgentHandler`) and FEAT-149 tests
continue to work untouched.

---

## Scope

- Add `owner_id: str` and `owner_kind: OwnerKind` fields to `EphemeralAgentStatus`.
- Add a `OwnerKind = Literal["user", "agent"]` type alias.
- Keep `user_id: int` as a computed/aliased property for `owner_kind == "user"`.
- Implement a `model_validator` or `__init__` override so that constructing with
  `user_id=42` auto-populates `owner_id="42"` + `owner_kind="user"` (backward compat).
- Update `EphemeralRegistry.get()` to resolve by `(chatbot_id, owner_id)` instead
  of only `(chatbot_id, user_id)`. Preserve the `user_id` code path via the alias.
- Update `EphemeralRegistry.get_all_for_user()` to filter by `owner_id` (or keep a
  compat wrapper that converts `user_id: int → owner_id: str`).
- Write unit tests for both agent-owner and user-owner (alias) paths.

**NOT in scope**: changes to `BotManager` methods (that's TASK-1388), changes to
the HTTP handler, or the `SpawnSubAgentTool`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/manager/ephemeral.py` | MODIFY | Add `OwnerKind`, `owner_id`, `owner_kind`; update `EphemeralRegistry.get()` and `get_all_for_user()` |
| `packages/ai-parrot-server/tests/test_ephemeral_ownership.py` | CREATE | Unit tests for the ownership generalization |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use these exact imports, class names, and method signatures.

### Verified Imports
```python
from parrot.manager.ephemeral import (
    EphemeralAgentStatus,   # verified: ephemeral.py:75
    EphemeralRegistry,      # verified: ephemeral.py:106
    EphemeralPhase,         # verified: ephemeral.py:43
    _warm_up,               # verified: ephemeral.py:232
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/manager/ephemeral.py

EphemeralPhase = Literal["creating", "warming", "ready", "error"]   # line 43

class EphemeralAgentStatus(BaseModel):                   # line 75
    chatbot_id: str                                      # line 91
    user_id: int                                         # line 92  (← generalize to owner_id/owner_kind)
    phase: EphemeralPhase = "creating"                   # line 93
    progress: Dict[str, str] = Field(default_factory=dict)
    error: Optional[str] = None
    created_at: datetime                                 # line 96
    expires_at: datetime                                 # line 97
    rag_mode: Optional[Literal["pageindex", "vector"]] = None

class EphemeralRegistry:                                 # line 106
    async def register(self, status: EphemeralAgentStatus) -> None  # line 135
    def get(self, chatbot_id: str, user_id: int) -> Optional[EphemeralAgentStatus]  # line 150
    def get_all_for_user(self, user_id: int) -> List[EphemeralAgentStatus]  # line 175
    async def remove(self, chatbot_id: str) -> bool      # line 186
    def get_expired(self) -> List[str]                   # line 202
```

### Does NOT Exist
- ~~`EphemeralAgentStatus.owner_id`~~ — does not exist yet; this task adds it.
- ~~`EphemeralAgentStatus.owner_kind`~~ — does not exist yet; this task adds it.
- ~~`OwnerKind`~~ — type alias does not exist yet; this task creates it.
- ~~`EphemeralRegistry.get_by_owner()`~~ — no such method; generalize existing `get()`.

---

## Implementation Notes

### Pattern to Follow
Use Pydantic `model_validator(mode="before")` to normalize the legacy `user_id: int`
constructor path into the new `owner_id`/`owner_kind` fields:

```python
OwnerKind = Literal["user", "agent"]

class EphemeralAgentStatus(BaseModel):
    chatbot_id: str
    owner_id: str
    owner_kind: OwnerKind = "user"
    # ... existing fields ...

    @model_validator(mode="before")
    @classmethod
    def _normalize_owner(cls, values):
        # If user_id is provided (legacy path), convert to owner_id/owner_kind
        if "user_id" in values and "owner_id" not in values:
            values["owner_id"] = str(values.pop("user_id"))
            values.setdefault("owner_kind", "user")
        return values

    @property
    def user_id(self) -> Optional[int]:
        """Backward-compatible alias for owner_kind == 'user'."""
        if self.owner_kind == "user":
            return int(self.owner_id)
        return None
```

### Key Constraints
- `user_id` property must still work for `owner_kind == "user"` (handler + tests).
- `EphemeralRegistry.get()` signature should accept `owner_id: str` as primary,
  with an overload or normalization for `user_id: int` callers.
- All existing tests must continue to pass without modification.

---

## Acceptance Criteria

- [ ] `EphemeralAgentStatus(chatbot_id="x", owner_id="agent:p", owner_kind="agent", ...)` works
- [ ] `EphemeralAgentStatus(chatbot_id="x", user_id=42, ...)` still works (alias)
- [ ] `.user_id` property returns `int` for `owner_kind=="user"`, `None` for `"agent"`
- [ ] `EphemeralRegistry.get(chatbot_id, owner_id="agent:p")` resolves agent-owned status
- [ ] `EphemeralRegistry.get(chatbot_id, user_id=42)` still resolves (backward compat)
- [ ] Existing FEAT-149 tests pass: `pytest packages/ai-parrot-server/tests/ -k ephemeral -v`
- [ ] New tests pass: `pytest packages/ai-parrot-server/tests/test_ephemeral_ownership.py -v`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/test_ephemeral_ownership.py
import pytest
from datetime import datetime, timedelta
from parrot.manager.ephemeral import (
    EphemeralAgentStatus, EphemeralRegistry, OwnerKind,
)


@pytest.fixture
def registry():
    return EphemeralRegistry()


class TestEphemeralAgentStatusOwnership:
    def test_create_with_agent_owner(self):
        status = EphemeralAgentStatus(
            chatbot_id="sub-001",
            owner_id="agent:parent-123",
            owner_kind="agent",
            created_at=datetime.now(),
            expires_at=datetime.now() + timedelta(seconds=300),
        )
        assert status.owner_id == "agent:parent-123"
        assert status.owner_kind == "agent"
        assert status.user_id is None

    def test_create_with_user_id_compat(self):
        status = EphemeralAgentStatus(
            chatbot_id="sub-002",
            user_id=42,
            created_at=datetime.now(),
            expires_at=datetime.now() + timedelta(seconds=300),
        )
        assert status.owner_id == "42"
        assert status.owner_kind == "user"
        assert status.user_id == 42


class TestEphemeralRegistryOwnership:
    @pytest.mark.asyncio
    async def test_get_by_agent_owner(self, registry):
        status = EphemeralAgentStatus(
            chatbot_id="sub-003",
            owner_id="agent:parent-456",
            owner_kind="agent",
            created_at=datetime.now(),
            expires_at=datetime.now() + timedelta(seconds=300),
        )
        await registry.register(status)
        found = registry.get("sub-003", owner_id="agent:parent-456")
        assert found is not None
        assert found.owner_kind == "agent"

    @pytest.mark.asyncio
    async def test_get_by_user_id_compat(self, registry):
        status = EphemeralAgentStatus(
            chatbot_id="sub-004",
            user_id=99,
            created_at=datetime.now(),
            expires_at=datetime.now() + timedelta(seconds=300),
        )
        await registry.register(status)
        found = registry.get("sub-004", user_id=99)
        assert found is not None
        assert found.user_id == 99
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-208-spawn-ephemeral-subagent-tool.spec.md` §1-§3 (M1)
2. **Check dependencies** — none; this is the first task
3. **Verify the Codebase Contract** — confirm all line numbers and signatures above
4. **Update status** in `sdd/tasks/index/spawn-ephemeral-subagent-tool.json` → `"in-progress"`
5. **Implement** the ownership generalization
6. **Run**: `pytest packages/ai-parrot-server/tests/ -k ephemeral -v`
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/`
9. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-06-01
**Notes**: Added `OwnerKind = Literal["user","agent"]` type alias, generalized
`EphemeralAgentStatus` with `owner_id: str` + `owner_kind: OwnerKind` fields and
a `model_validator(mode="before")` that converts legacy `user_id: int` →
`owner_id/owner_kind="user"`. Added `user_id` backward-compat property.
Updated `EphemeralRegistry.get()` to accept `user_id: int` (positional, legacy)
or `owner_id: str` (keyword). Updated `get_all_for_user()` to filter by
`owner_kind=="user"` and `owner_id == str(user_id)`. Removed unused `timedelta`
import flagged by ruff. 14 new tests, all passing.

**Deviations from spec**: none
