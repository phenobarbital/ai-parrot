# TASK-4989: PricingPolicy — subscription seats report $0 + equivalent_usd

**Feature**: FEAT-783 — Unified usage & cost metrics per SDD spec
**Spec**: `sdd/specs/unified-usage.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4987
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9, U4, AC-13. A plan/subscription seat must not inflate a spec with money
that was never spent: it reports `usd = 0.0` with list price as `equivalent_usd`. The
policy is **derived, not configured**. The emitter states it on the event (`pricing_policy`),
and the subscriber applies it to the single cost computed at the origin.

---

## Scope

- Create `observability/cost/policy.py` with `PolicyKind`, `PricingPolicy` and `apply()` (exact semantics below).
- Add `pricing_policy: Optional[str]` to `AfterClientCallEvent` (`None` ≡ `"billed"`).
- Add `pricing_policy: Optional[str]` and `equivalent_usd: Optional[float]` to `UsageRecord`.
- In `UsageRecordingSubscriber._on_client_after`, after cost resolution: when the policy is `subscription`, set `cost_usd=0.0` and `equivalent_usd=<list price>`. **The cumulative cost must accumulate the post-policy value (0.0)**.
- In `ClaudeCodeDispatcher._emit_usage_event`, derive the Claude seat's policy (FILL IN below).
- Tests.

**NOT in scope**: the codex seat's policy (TASK-4993 sets it from `auth_mode`/`plan_type`); budget enforcement (spec Non-Goal U5).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/cost/policy.py` | CREATE | `PricingPolicy` |
| `packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py` | MODIFY | `pricing_policy` field |
| `packages/ai-parrot/src/parrot/observability/recorders/models.py` | MODIFY | `pricing_policy`, `equivalent_usd` |
| `packages/ai-parrot/src/parrot/observability/recorders/subscriber.py` | MODIFY | Apply policy |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py` | MODIFY | Derive Claude seat policy |
| `packages/ai-parrot/tests/unit/observability/test_pricing_policy.py` | CREATE | Tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.observability.cost.calculator import PricedCost   # created by TASK-4987
```

### Existing Signatures to Use
```python
# recorders/subscriber.py _on_client_after (:94): cost_usd = resolve_event_cost(event, self._cost); then
#   with self._lock: self._cumulative_cost_usd += cost_usd   (:104-108) — policy must apply BEFORE this
# dispatchers/claude.py _emit_usage_event (:977) builds AfterClientCallEvent; TASK-4986 added cache/cost kwargs after source_name="claude-code"
# ClaudeCodeDispatchProfile is the `profile` argument (read its fields with grep before deriving)
```

### Does NOT Exist
- ~~`parrot.observability.cost.policy`~~ — this task creates it
- ~~a configured per-seat policy table~~ — policy is DERIVED (U4); never add a config knob
- ~~`UsageRecord.equivalent_usd`~~ — this task creates it

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/observability/cost/policy.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/observability/recorders/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/observability/recorders/subscriber.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/observability/test_pricing_policy.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/observability/recorders/subscriber.py#UsageRecordingSubscriber",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py#ClaudeCodeDispatcher._emit_usage_event"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `apply()` takes the already-computed `usd` and returns `(usd, equivalent_usd)`. It must never call the calculator (FEAT-710 G5).
- `estimate` = an unpriced or derived figure: `(usd, None)` passthrough, flagged by the policy kind on the record.
- Unknown policy strings fall back to `billed`, with one debug log.

---

## Implementation Blueprint

### Steps (in order)
1. Create `policy.py`.
2. Add the event field (below TASK-4987's `price_valid_from`) and the record fields (in the FEAT-783 counter block).
3. Apply the policy in the subscriber before the cumulative sum, so a subscription run never raises `cumulative_cost_usd`.
4. Set the Claude seat's policy in `claude.py`.
5. Tests.

### `packages/ai-parrot/src/parrot/observability/cost/policy.py` (CREATE)
```python
"""PricingPolicy — derived per-seat cost policy (FEAT-783 M9, U4)."""
from __future__ import annotations

import logging
from typing import Literal, Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)

PolicyKind = Literal["billed", "subscription", "estimate"]
_KINDS: frozenset[str] = frozenset({"billed", "subscription", "estimate"})


class PricingPolicy(BaseModel):
    """Per-seat cost policy, DERIVED not configured: codex reports auth_mode/plan_type,
    the Claude Agent SDK reports a plan seat."""

    kind: PolicyKind = "billed"

    @classmethod
    def from_label(cls, label: Optional[str]) -> "PricingPolicy":
        """Parse an event's ``pricing_policy``; None/unknown -> billed."""
        if label is None:
            return cls()
        if label not in _KINDS:
            logger.debug("unknown pricing_policy %r; treating as billed", label)
            return cls()
        return cls(kind=label)  # type: ignore[arg-type]

    def apply(self, usd: Optional[float]) -> tuple[Optional[float], Optional[float]]:
        """Return (usd, equivalent_usd). A subscription seat reports usd=0.0 with list price as
        equivalent_usd, so a plan-based run never inflates a spec with money never spent."""
        # FILL IN: subscription -> (0.0, usd) [even when usd is None -> (0.0, None)];
        # billed/estimate -> (usd, None) — bounded by AC-13
        raise NotImplementedError
```
**Note**: the spec skeleton types `apply(priced: PricedCost)`. This blueprint takes the already-resolved `usd` instead, because the subscriber holds a float (from `resolve_event_cost`), not a `PricedCost`. Keep `PricedCost` support as an overload only if a caller needs it. Record the deviation in the Completion Note.

### Subscriber (MODIFY)
```python
# subscriber.py _on_client_after — directly AFTER `cost_usd = resolve_event_cost(event, self._cost)` (1 occurrence):
        from parrot.observability.cost.policy import PricingPolicy  # noqa: PLC0415

        policy = PricingPolicy.from_label(getattr(event, "pricing_policy", None))
        cost_usd, equivalent_usd = policy.apply(cost_usd)
# and add to the UsageRecord(...) kwargs:
            pricing_policy=policy.kind,
            equivalent_usd=equivalent_usd,
```

### `claude.py` (MODIFY)
```python
# in _emit_usage_event's AfterClientCallEvent(...), after the TASK-4986 kwargs:
                    pricing_policy=self._claude_pricing_policy(profile),
# new method:
    def _claude_pricing_policy(self, profile: ClaudeCodeDispatchProfile) -> Optional[str]:
        """FEAT-783 U4: derive billed vs subscription for the Agent SDK seat."""
        # FILL IN: subscription when the SDK runs on a plan login (no ANTHROPIC_API_KEY in the dispatch env /
        # profile auth mode says so — grep the profile + SDK options for the real field); billed when an API key is used;
        # None when undeterminable — bounded by U4 (derived, never configured)
        return None
```

### `test_pricing_policy.py` (CREATE)
```python
"""FEAT-783 AC-13 — subscription seat reports $0 + equivalent_usd."""
import pytest

from parrot.observability.cost.policy import PricingPolicy


def test_subscription_zeroes_usd_and_keeps_list_price() -> None:
    assert PricingPolicy(kind="subscription").apply(1.25) == (0.0, 1.25)


def test_billed_and_estimate_passthrough() -> None:
    # FILL IN
    ...


@pytest.mark.asyncio
async def test_subscriber_cumulative_excludes_subscription_cost() -> None:
    # FILL IN: priced event with pricing_policy="subscription" -> record.cost_usd == 0.0, equivalent_usd > 0,
    # cumulative_cost_usd == 0.0
    ...
```

### FILL IN checklist
- [ ] `apply` semantics; bounded by AC-13
- [ ] Claude plan detection; bounded by U4
- [ ] Test bodies

---

## Acceptance Criteria

- [ ] AC-13: a subscription seat reports `usd = 0.0` with list price as `equivalent_usd`.
- [ ] Cumulative cost excludes subscription spend; `test_cost_computed_once.py` still passes.

## Validation Commands
- `pytest packages/ai-parrot/tests/unit/observability/test_pricing_policy.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_usage_subscriber.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_cost_computed_once.py -q`

## Test Specification
See blueprint.

## Agent Instructions
Six files only. `PYTHONPATH=packages/ai-parrot/src`.

## Completion Note
_(filled at close)_
