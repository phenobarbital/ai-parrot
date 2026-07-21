---
type: Wiki Overview
title: 'TASK-1277: Manager — action-failure fix + advance_chain public + severity/hours
  selection'
id: doc:sdd-tasks-completed-task-1277-manager-advance-chain-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Implements §3 module **C4**. Heart of the V1 completion: fixes the'
---

# TASK-1277: Manager — action-failure fix + advance_chain public + severity/hours selection

**Feature**: FEAT-194 — HITL Multi-Tier Escalation Policy
**Spec**: `sdd/specs/hitl-escalation-tier.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1274
**Assigned-to**: unassigned

---

## Context

Implements §3 module **C4**. Heart of the V1 completion: fixes the
silent-failure bug in `_escalate_to_next_tier`, exposes
`advance_chain` as a public method for channels (TASK-1279) and the
web handler (TASK-1285), and wires `select_starting_tier` so severity
and business-hours skip the right tiers.

---

## Scope

- Fix the action-failure path in `_escalate_to_next_tier`
  (manager.py:733-740): when `action.execute()` raises **or** returns
  a dict with `error=True`, emit a log warning, do NOT resolve the
  future with empty metadata; instead recurse to the next tier
  (`await self._escalate_to_next_tier(interaction, channel)`). If the
  chain is exhausted while every tier keeps failing, terminate via
  `_finish_with_timeout`.
- Add `async def advance_chain(self, interaction_id: str, cause: Literal["timeout","reject","business_hours_off","action_failed"]) -> None`
  — public entry point. Loads the interaction from Redis, dispatches
  to the next tier per cause. For `cause="business_hours_off"`, skips
  the current tier without dispatching its action.
- In `request_human_input`, before the first dispatch, when
  `interaction.policy` is set:
  - Call `policy.select_starting_tier(interaction.severity, datetime.now(tz=UTC))`.
  - If a starting tier is returned and its `level > interaction.current_tier_level`,
    set `current_tier_level = starting.level - 1` so the existing
    advance call lands on it.
  - If no tier is currently applicable, resolve immediately with
    `_finish_with_timeout` (chain exhausted at start).
- Update `_escalate_to_next_tier` to also check
  `tier.business_hours` at tier-entry and skip (call self recursively)
  when off-hours.
- Update Redis TTL formula on persistence: use
  `max(interaction.timeout, sum(t.timeout for t in (interaction.policy.tiers if interaction.policy else [])) + 60)`
  capped at 24h, so multi-tier chains don't expire mid-flight.

**NOT in scope**: Reject-button channel rendering (TASK-1279). Web HITL
reject route (TASK-1285). Event emission (TASK-1280 — but expose
clear hook points / TODO markers so TASK-1280 can drop them in).
RejectIntentDetector wiring (TASK-1278 — done in a separate task that
modifies `receive_response`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/human/manager.py` | MODIFY | Fix `_escalate_to_next_tier` failure path; add `advance_chain`; wire `select_starting_tier`; update Redis TTL |
| `packages/ai-parrot/tests/test_human_manager.py` | MODIFY | Add tests for failure-advance, advance_chain by cause, severity-driven starting tier, off-hours skip |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Existing in manager.py:
from .actions.notify import NotifyAction                   # manager.py:12
from .actions.ticket import TicketAction                   # manager.py:13
from .channels.base import HumanChannel                    # manager.py:14
from .models import (
    ConsensusMode, EscalationActionType, EscalationPolicy,
    HumanInteraction, HumanResponse, InteractionResult,
    InteractionStatus, TimeoutAction,
)                                                          # manager.py:15-24
# NEW (from TASK-1274):
from .models import Severity, BusinessHours
from datetime import datetime, timezone
```

### Existing Signatures to Use

```python
# parrot/human/manager.py:60-76 — current __init__
class HumanInteractionManager:
    def __init__(self, channels=None, redis_url=None) -> None:
        # ...
        self._actions: Dict[EscalationActionType, Any] = {
            EscalationActionType.TICKET: TicketAction(),
            EscalationActionType.NOTIFY: NotifyAction(),
        }
        self._policies: Dict[str, EscalationPolicy] = {}

# parrot/human/manager.py:192-262 — request_human_input (long-polling)
async def request_human_input(self, interaction, channel="telegram") -> InteractionResult: ...

# parrot/human/manager.py:660-696 — _handle_timeout
async def _handle_timeout(self, interaction, channel) -> None:
    # branches: ESCALATE → _escalate_to_next_tier or _escalate; RETRY → _retry;
    # else → _build_timeout_result + resolve future/rehydrate

# parrot/human/manager.py:698-780 — _escalate_to_next_tier (CURRENT IMPL with BUG)
async def _escalate_to_next_tier(self, interaction, channel) -> None:
    # ... picks next_tier ...
    if next_tier.action_type in self._actions:
        action = self._actions[next_tier.action_type]
        try:
            action_metadata = await action.execute(interaction, next_tier)
        except Exception:
            self.logger.exception(...)
            # BUG: falls through with action_metadata = {} — fix here.
    # ...

# parrot/human/manager.py:782-790 — _finish_with_timeout
async def _finish_with_timeout(self, interaction) -> None: ...

# parrot/human/manager.py:101-106 — _persist_interaction (TTL formula here)
async def _persist_interaction(self, interaction) -> None:
    ttl = int(interaction.timeout) + 60   # CURRENT — to be extended

# parrot/human/manager.py:354-362 — get_result
async def get_result(self, interaction_id) -> Optional[InteractionResult]: ...
```

### Does NOT Exist

- ~~`manager.advance_chain`~~ — to be added by this task.
- ~~`EscalationCause` enum~~ — use `Literal["timeout","reject","business_hours_off","action_failed"]`.
- ~~`hitl.tier.action_failed` event emission~~ — TASK-1280 will add it;
  this task only emits the warning log + advances. Leave a TODO comment
  marking the emission point.
- ~~Cross-channel correlation~~ — out of scope.

---

## Implementation Notes

### Pattern to Follow

```python
async def advance_chain(self, interaction_id: str, cause: str) -> None:
    interaction = await self._load_interaction(interaction_id)
    if interaction is None:
        self.logger.debug("advance_chain: unknown id %s", interaction_id)
        return
    # Use same code path as timeout-driven advance but parameterise the cause
    # for logging / future event emission (TASK-1280).
    await self._escalate_to_next_tier(interaction, channel="<derived>", cause=cause)
```

### Key Constraints

- Pure-async, no blocking calls.
- Recursive `_escalate_to_next_tier` calls must respect a max depth =
  `len(policy.tiers)` to avoid runaway in case of bug; raise/abort if
  exceeded.
- Mutating `interaction.current_tier_level` before re-dispatch must be
  persisted to Redis BEFORE the dispatch so a crash mid-dispatch doesn't
  lose the cursor.
- `select_starting_tier` is called with `datetime.now(timezone.utc)` —
  document the UTC assumption so `BusinessHours` comparisons use the
  same baseline.
- TTL update applies to BOTH the initial persistence (request_human_input)
  AND every status update (`_update_status`).

### References in Codebase

- `parrot/human/manager.py:660-696` — `_handle_timeout` already
  contains the policy / legacy branching pattern; reuse the dispatch
  table approach.
- Spec §7 Known Risks → "Action-failure silent continuation".

---

## Acceptance Criteria

- [ ] When `action.execute()` raises, the manager advances to the next
  tier instead of resolving with empty metadata.
- [ ] When `action.execute()` returns a dict with `error=True`, same
  advance behaviour as raising.
- [ ] When all tiers fail (chain exhausted while every action errors),
  the interaction resolves via `_finish_with_timeout`.
- [ ] `manager.advance_chain(id, cause="reject")` advances the tier
  exactly like a timeout-driven advance.
- [ ] `manager.advance_chain(id, cause="business_hours_off")` skips the
  current tier without dispatching its action.
- [ ] `request_human_input` honours `select_starting_tier` when the
  interaction's `policy` is set and `severity != NORMAL` or any tier
  has `min_severity` / `business_hours`.
- [ ] When `severity=CRITICAL`, lower tiers are skipped per policy.
- [ ] When the picked starting tier's business hours don't include
  `now`, the manager moves to the next applicable tier (or terminates).
- [ ] Redis TTL is at least
  `sum(t.timeout for t in policy.tiers) + 60` (capped at 24h).
- [ ] Existing legacy callers (no policy, only `escalation_targets`)
  still work through the `_escalate` fallback path.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/test_human_manager.py -v`.

---

## Test Specification

```python
# packages/ai-parrot/tests/test_human_manager.py — new tests
class TestActionFailureAdvances:
    async def test_action_exception_advances_to_next_tier(self): ...
    async def test_action_error_dict_advances_to_next_tier(self): ...
    async def test_all_tiers_fail_terminates_cleanly(self): ...

class TestAdvanceChainPublic:
    async def test_advance_chain_reject_picks_next_tier(self): ...
    async def test_advance_chain_business_hours_off_skips_current(self): ...

class TestStartingTierSelection:
    async def test_severity_critical_skips_lower_tiers(self): ...
    async def test_off_hours_starting_tier_skipped(self): ...
    async def test_no_applicable_tier_terminates(self): ...

class TestRedisTtlMultiTier:
    async def test_ttl_covers_sum_of_tier_timeouts(self): ...
```

---

## Agent Instructions

1. Read spec §3 C4, §7 Known Risks (action-failure section), §6.
2. Verify TASK-1274 completed (`Severity`, `BusinessHours`,
   `select_starting_tier` available).
3. Verify line numbers in Codebase Contract are still current; update
   the contract first if they drifted.
4. Implement; leave TODO markers for TASK-1280 event emission points.
5. Move to completed, update index.

---

## Completion Note

Implemented 2026-05-21 by sdd-worker (FEAT-194).

- `_escalate_to_next_tier` rewritten with depth guard (prevents infinite loops), business-hours skip, and action-failure detection (error=True dict OR exception → recurse to next tier).
- `advance_chain(interaction_id, cause)` public method added: loads interaction from Redis, checks resolved state, cancels existing timeout task, calls `_escalate_to_next_tier`.
- `_resolve_interaction_policy()` wired to call `policy.select_starting_tier(severity, now)`, setting `current_tier_level = starting_tier.level - 1`.
- `_compute_ttl(interaction)` computes multi-tier TTL formula capped at 86400s.
- TODO markers left at tier-transition event emission points for TASK-1280.
- 9 new tests added to `test_human_manager.py`; all 46 tests pass.
