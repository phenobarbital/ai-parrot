---
type: Wiki Overview
title: 'TASK-1534: ConfirmationGuard core lifecycle'
id: doc:sdd-tasks-completed-task-1534-confirmation-guard-core-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The governor itself (spec §2 Overview + New Public Interfaces, §3 Module
  1).
relates_to:
- concept: mod:parrot.auth.confirmation
  rel: mentions
- concept: mod:parrot.core.exceptions
  rel: mentions
- concept: mod:parrot.human
  rel: mentions
- concept: mod:parrot.human.manager
  rel: mentions
- concept: mod:parrot.human.models
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
---

# TASK-1534: ConfirmationGuard core lifecycle

**Feature**: FEAT-235 — HITL Tool-Call Confirmation
**Spec**: `sdd/specs/hitl-confirmation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1533
**Assigned-to**: unassigned

---

## Context

The governor itself (spec §2 Overview + New Public Interfaces, §3 Module 1).
Mirrors `GrantGuard.authorize()` (`parrot/auth/grants.py:378`). Implements the
confirm-before-execute lifecycle: routing_meta gate → window check → HITL ask
(APPROVAL × BLOCK/SUSPEND) → result mapping → fail-closed. Briefing rendering and
edit-before-execute land in TASK-1535; here, use a minimal raw briefing and the
APPROVAL interaction only.

---

## Scope

- Add `ConfirmationGuard` to `parrot/auth/confirmation.py`:
  - `__init__(self, store: ConfirmationWindowStore, human_manager=None, config=None)`
    (mirror `GrantGuard.__init__`, grants.py:360).
  - `async def confirm(self, *, tool, parameters, permission_context=None) -> ConfirmationDecision`.
  - Lifecycle:
    1. If `not tool.routing_meta.get("requires_confirmation")` →
       `ConfirmationDecision(allowed=True, status="not_required", reason=..., parameters=parameters)`.
    2. Resolve `owner` from `permission_context` (mirror how `GrantGuard` derives the
       owner — see grants.py `authorize`); compute `args_hash` via
       `compute_args_hash(parameters)`. Read effective window from
       `tool.routing_meta.get("confirm_window_seconds", self.config.window_seconds)`.
       If `await store.is_confirmed(owner, tool.name, args_hash)` → allow.
    3. Fail-closed: if `self.human_manager is None` →
       `allowed=False, status="cancelled", reason="confirmation required but no human manager"`.
    4. Build a raw briefing string (`<tool.name> with param=value ...`) — TASK-1535
       will replace this with the template renderer.
    5. Ask via `HumanInteractionManager`:
       - `InteractionType.APPROVAL`, `timeout=self.config.approval_timeout`.
       - `WaitStrategy.BLOCK` → `await human_manager.request_human_input(interaction, channel=...)`.
       - `WaitStrategy.SUSPEND` → `await human_manager.request_human_input_async(...)`
         then `raise HumanInteractionInterrupt(...)`.
       - Read the desired wait strategy from `tool.routing_meta.get("wait_strategy")`
         (default `WaitStrategy.BLOCK`).
    6. Map `InteractionResult`: approved → `allowed=True, status="confirmed"`,
       record the window if `window_seconds > 0`; rejected → `cancelled`;
       `result.timed_out` → `timeout`.
- Unit tests in `packages/ai-parrot/tests/test_confirmation_guard.py` with a stub
  `HumanInteractionManager`.

**NOT in scope**: briefing templates / FORM / edit re-validation (TASK-1535);
ToolManager wiring (TASK-1536); decorator/spawn (TASK-1537); exports (TASK-1538).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/confirmation.py` | MODIFY | Add `ConfirmationGuard` |
| `packages/ai-parrot/tests/test_confirmation_guard.py` | CREATE | Unit tests with stub manager |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.human.manager import HumanInteractionManager        # human/manager.py:51
from parrot.human.models import (
    InteractionType, WaitStrategy, HumanInteraction, InteractionResult,
)                                                                # human/models.py
from parrot.core.exceptions import HumanInteractionInterrupt     # core/exceptions.py:12
from parrot.tools.abstract import AbstractTool                   # tools/abstract.py:81
```

### Existing Signatures to Use
```python
# parrot/auth/grants.py  (mirror this method)
class GrantGuard:                                                # line 338
    def __init__(self, store, human_manager=None, config=None) -> None: ...   # line 360
    async def authorize(self, *, tool, parameters, permission_context=None) -> GuardDecision: ...  # 378
    # gate:   if not tool.routing_meta.get("requires_grant"): return allowed   # line 398
    # window: tool.routing_meta.get("grant_window_seconds", self.config.window_seconds)  # 460

# parrot/human/manager.py
class HumanInteractionManager:                                   # line 51
    async def request_human_input(self, interaction, channel) -> InteractionResult: ...        # 321 (BLOCK)
    async def request_human_input_async(self, interaction, channel, schedule_timeout=False) -> str: ...  # 502 (SUSPEND)

# parrot/human/models.py
class InteractionType(str, Enum): ... APPROVAL = "approval"      # line 66
class WaitStrategy(str, Enum): BLOCK="block"; SUSPEND="suspend"  # line 31
class HumanInteraction(BaseModel):                              # line 380
    question: str; interaction_type: InteractionType
    timeout: float = 7200.0                                     # line 398
class InteractionResult(BaseModel):                            # line 498
    status: InteractionStatus                                  # line 502
    consolidated_value: Any = None                             # line 504
    timed_out: bool = False                                     # line 505

# parrot/tools/abstract.py
class AbstractTool(EventEmitterMixin, ABC):                    # line 81
    name: str                                                  # tool name used as window key
    routing_meta: Dict                                         # per-instance, line 140
```

### Does NOT Exist
- ~~`InteractionType.CONFIRM`~~ — use `APPROVAL`. Members: FREE_TEXT, SINGLE_CHOICE,
  MULTI_CHOICE, APPROVAL, FORM (human/models.py:60-67).
- ~~`HumanInteractionManager.ask()` / `.confirm()`~~ — only `request_human_input`
  (BLOCK) and `request_human_input_async` (SUSPEND) exist.
- ~~`tool.routing_meta["confirmation_required"]`~~ — the key is `requires_confirmation`.
- ~~`HumanInteractionInterrupt` under `parrot.human`~~ — it lives at
  `parrot.core.exceptions:12`.

---

## Implementation Notes

### Pattern to Follow
`GrantGuard.authorize()` and `_request_approval()` (grants.py:378, 429) — copy the
owner-resolution, the early-return-on-no-meta gate, the fail-closed branch, and the
BLOCK/SUSPEND split. Map the HITL result to a decision instead of minting a grant.

### Key Constraints
- Async throughout; `self.logger = logging.getLogger(__name__)`; log allow/deny.
- Determine `consolidated_value` truthiness for APPROVAL (Yes/True → approved).
  Check exactly how the APPROVAL interaction reports its boolean in
  `human/models.py` / `human/manager.py` before assuming — verify, don't guess.
- Inspect the real signature of `request_human_input` / `request_human_input_async`
  in `human/manager.py` for the exact `channel` kwarg name before calling.

### References in Codebase
- `parrot/auth/grants.py:338-540` — guard + HITL approval pattern.
- `parrot/human/tool.py:344-365` — BLOCK vs SUSPEND dispatch reference.
- `agents/expense_approval.py:302-349` — SUSPEND + `HumanInteractionInterrupt` usage.

---

## Acceptance Criteria

- [ ] `from parrot.auth.confirmation import ConfirmationGuard` works.
- [ ] Tool without `requires_confirmation` → `allowed=True, status="not_required"`, no HITL call.
- [ ] BLOCK + approve → `allowed=True, status="confirmed"`.
- [ ] BLOCK + reject → `allowed=False, status="cancelled"`.
- [ ] Timeout → `allowed=False, status="timeout"`.
- [ ] SUSPEND → calls `request_human_input_async` and raises `HumanInteractionInterrupt`.
- [ ] No `human_manager` + `requires_confirmation` → `allowed=False, status="cancelled"` (fail-closed).
- [ ] Window hit (within `confirm_window_seconds`, same args_hash) → allowed, no HITL call.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/test_confirmation_guard.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/auth/confirmation.py`

---

## Test Specification
```python
# packages/ai-parrot/tests/test_confirmation_guard.py
import pytest
from parrot.auth.confirmation import ConfirmationGuard, InMemoryConfirmationWindowStore

class _FakeManager:
    def __init__(self, result): self._result = result; self.calls = 0
    async def request_human_input(self, interaction, channel=None):
        self.calls += 1; return self._result

# build an AbstractTool stub with routing_meta={"requires_confirmation": True}
# assert each branch above. Verify _FakeManager.calls == 0 for not_required + window hit.
```

---

## Agent Instructions
1. Read spec §2/§6. 2. Verify the contract (esp. APPROVAL boolean + channel kwarg).
3. Index → `in-progress`. 4. Implement + verify. 5. Move to completed, index → `done`, note.

---

## Completion Note
**Completed by**: SDD Worker (Claude Sonnet 4.6)
**Date**: 2026-06-12
**Notes**: ConfirmationGuard.confirm() implemented in confirmation.py with full
BLOCK/SUSPEND paths, window check, fail-closed. All 9 guard unit tests pass.
APPROVAL type used (consolidated_value is bool). channel kwarg verified in
manager.py:283. SUSPEND raises HumanInteractionInterrupt as specified.
**Deviations from spec**: none
