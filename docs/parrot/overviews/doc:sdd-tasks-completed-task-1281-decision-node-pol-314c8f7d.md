---
type: Wiki Overview
title: 'TASK-1281: HumanDecisionNode policy + severity ctor kwargs'
id: doc:sdd-tasks-completed-task-1281-decision-node-policy-kwargs-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements §3 module **C8**. Today `HumanDecisionNode` (the flow-node
---

# TASK-1281: HumanDecisionNode policy + severity ctor kwargs

**Feature**: FEAT-194 — HITL Multi-Tier Escalation Policy
**Spec**: `sdd/specs/hitl-escalation-tier.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1274
**Assigned-to**: unassigned

---

## Context

Implements §3 module **C8**. Today `HumanDecisionNode` (the flow-node
counterpart of `HumanTool`) cannot participate in policy-driven
escalations — flows are stuck with single-hop legacy behaviour. Adds
parity with the LLM-side `policy_id` plumbing.

---

## Scope

- Add `escalation_policy_id: Optional[str] = None` and
  `severity: Severity = Severity.NORMAL` ctor kwargs to
  `HumanDecisionNode.__init__`.
- In `ask` (the node's main coroutine called by `FlowNode.execute`),
  when building the `HumanInteraction`, propagate `policy_id` and
  `severity` onto the interaction.
- When `interaction_config` is provided and *also* has `policy_id` /
  `severity`, the constructor-level kwargs win (explicit > inherited),
  to keep the override pattern consistent with how `target_humans`
  works today on this class.
- Update docstring with a usage example.

**NOT in scope**: Channel rendering, manager changes, doc updates
to the example file (TASK-1286).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/human/node.py` | MODIFY | Add `escalation_policy_id` and `severity` ctor kwargs; propagate to built interaction |
| `packages/ai-parrot/tests/human/test_decision_node_policy.py` | CREATE | Built interaction carries policy_id + severity |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Existing in node.py:
from .models import (
    ConsensusMode, HumanInteraction, InteractionResult,
    InteractionStatus, InteractionType,
)                                                          # node.py:7-13
# New (from TASK-1274):
from .models import Severity
```

### Existing Signatures to Use

```python
# parrot/human/node.py:78-100 — current __init__
class HumanDecisionNode:
    is_configured: bool = True                                   # line 76
    def __init__(
        self,
        name: str,
        manager: Any,
        interaction_config: Optional[HumanInteraction] = None,
        *,
        channel: str = "telegram",
        target_humans: Optional[List[str]] = None,
        consensus_mode: ConsensusMode = ConsensusMode.FIRST_RESPONSE,
        source_agent: Optional[str] = None,
        source_flow: Optional[str] = None,
    ) -> None: ...

# parrot/human/node.py:106-221 — ask
async def ask(self, question: str = "", **kwargs: Any) -> Any: ...
```

### Does NOT Exist

- ~~`HumanDecisionNode.escalation_policy_id`~~ — to be added.
- ~~`HumanDecisionNode.severity`~~ — to be added.
- ~~A full `escalation_policy` object on the node~~ — only the `policy_id`
  string is exposed (the policy itself lives in `manager._policies`).

---

## Implementation Notes

### Pattern to Follow

Mirror the override pattern already present for `target_humans` on this
class: ctor kwarg stored as instance attribute; consumed during
`ask` when building the interaction; precedence over any value
inherited from `interaction_config`.

```python
def __init__(self, ..., escalation_policy_id=None, severity=Severity.NORMAL):
    # ...
    self.escalation_policy_id = escalation_policy_id
    self.severity = severity

# In ask():
if self.interaction_config is not None:
    interaction = self.interaction_config.model_copy(update={
        "interaction_id": str(uuid4()),
        "source_node": self._name,
        # ...existing overrides...
        "policy_id": self.escalation_policy_id or self.interaction_config.policy_id,
        "severity": self.severity if self.severity != Severity.NORMAL else self.interaction_config.severity,
    })
else:
    interaction = HumanInteraction(
        question=...,
        # ...
        policy_id=self.escalation_policy_id,
        severity=self.severity,
    )
```

### Key Constraints

- Backwards compatible: existing nodes constructed without the new
  kwargs continue to work (defaults are None / NORMAL).
- `is_configured = True` class attr unchanged (FSM contract).

### References in Codebase

- `parrot/human/node.py:106-221` — `ask` method (handles
  `interaction_config` precedence).

---

## Acceptance Criteria

- [ ] `HumanDecisionNode(escalation_policy_id="hr", severity=Severity.HIGH)` constructs.
- [ ] Built `HumanInteraction` carries `policy_id="hr"` and `severity=Severity.HIGH`.
- [ ] When `interaction_config.policy_id="x"` AND ctor `escalation_policy_id="hr"`,
  the built interaction uses `"hr"` (ctor wins).
- [ ] When neither ctor nor config sets `policy_id`, built interaction has `policy_id=None`.
- [ ] Existing tests on `HumanDecisionNode` (without the new kwargs)
  continue to pass.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/human/test_decision_node_policy.py -v`.

---

## Test Specification

```python
# tests/human/test_decision_node_policy.py
async def test_built_interaction_carries_policy_id_and_severity(): ...
async def test_ctor_kwarg_wins_over_interaction_config(): ...
async def test_back_compat_no_new_kwargs(): ...
```

---

## Agent Instructions

1. Read spec §3 C8.
2. Verify TASK-1274 completed.
3. Implement, test.
4. Move to completed.

---

## Completion Note

Implemented 2026-05-22 by sdd-worker (FEAT-194).

- Added `escalation_policy_id: Optional[str] = None` and `severity: Severity = Severity.NORMAL` constructor kwargs to `HumanDecisionNode`.
- Stored as `self.escalation_policy_id` and `self.severity` instance attributes.
- In `ask()` with `interaction_config`: constructor kwargs win over config values using explicit precedence logic (`policy_id`: None check; `severity`: NORMAL-as-sentinel check so config's non-NORMAL value wins when ctor uses default).
- In `ask()` without config: `policy_id=self.escalation_policy_id, severity=self.severity` passed directly to `HumanInteraction`.
- 5 tests all pass: ctor kwargs propagate, ctor wins over config, config used when no ctor override, back-compat (no kwargs), bare construction attributes.
