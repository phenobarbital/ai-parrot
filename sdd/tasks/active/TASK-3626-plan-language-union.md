# TASK-3626: Plan-language discriminated union (DelegatePlanNode)

**Feature**: FEAT-590 — Tool-Call Delegate
**Spec**: `sdd/specs/tool-call-delegate.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec Module 3 and §2 "Plan language: discriminated union". `ExecutionPlan.nodes`
is `List[PlanNode]` today, and `PlanNode` requires `tool` and forbids extra
fields, so a `"type": "delegate"` node can't be expressed. This task splits
the shared fields into `_PlanNodeBase` and adds `DelegatePlanNode` plus the
`AnyPlanNode` union. Every existing plan must still parse, and the
`plan_fingerprint` of a tool-only plan must stay **byte-identical** (G7/AC2).
If it changed, every checkpointed FEAT-585 run would fail to resume with
`policy_mismatch`.

---

## Scope

- Move the shared `PlanNode` fields and the `_check_node` rules into `_PlanNodeBase`.
- Add `PlanNode.type: Literal["tool"] = Field(default="tool", exclude=True)`.
- Add `DelegatePlanNode` with the fields in spec M3. Its `referenced_nodes()` covers `instruction`, `facts` values and `for_each.source`.
- Add `tool_names()` to both models. Add `_node_kind` and the `AnyPlanNode` union. `ExecutionPlan.nodes: List[AnyPlanNode]`, and `ExecutionPlan.node()` returns `AnyPlanNode`.
- Add `ArtifactRef.escalated: int = 0`.
- Export `DelegatePlanNode` and `AnyPlanNode` from `parrot.bots.flows.plan` and add them to `models.__all__`.
- Write tests, including a frozen-hash fingerprint test.

**NOT in scope**: validator, compiler, allowlist or repair changes (TASK-3628/3629); any node execution (TASK-3630/3631). Do **not** add any other defaulted field to `PlanNode`: each one changes fingerprints.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/plan/models.py` | MODIFY | `_PlanNodeBase`, `PlanNode.type`, `DelegatePlanNode`, `AnyPlanNode`, `ArtifactRef.escalated` |
| `packages/ai-parrot/src/parrot/bots/flows/plan/__init__.py` | MODIFY | Export the new models |
| `packages/ai-parrot/tests/bots/flows/plan/test_delegate_models.py` | CREATE | Union, back-compat, fingerprint tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag, model_validator  # pydantic 2.12.5 in venv
from typing import Annotated, Any, Dict, List, Literal, Optional, Union
from parrot.bots.flows.plan.models import ARTIFACT_REF_RE, NODE_REF_RE, _iter_strings, _IDENT_RE, _STORE_KEY_VAR_RE  # models.py:64,66,511,70,68
from parrot.tools.execution_plan.runs import plan_fingerprint  # verified: packages/ai-parrot/src/parrot/tools/execution_plan/runs.py:71
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/plan/models.py
from typing import Any, Dict, List, Literal, Optional                          # line 46 (add Annotated, Union)
from pydantic import BaseModel, ConfigDict, Field, model_validator             # line 48 (add Discriminator, Tag)
class ForEach(BaseModel): ...  source_node property line 166
class PlanNode(BaseModel):                     # line 173; model_config extra="forbid" line 203
    id: str; tool: str; args: Dict[str, Any]; store_as: str; depends_on: List[str]; when: Optional[str]
    for_each: Optional[ForEach]; facets: FacetSpec; timeout: Optional[float]; retry: RetryPolicy; description: Optional[str]  # lines 205-215
    @model_validator(mode="after") def _check_node(self) -> "PlanNode"   # line 217-240
    def referenced_nodes(self) -> set[str]                               # line 242-254 (scans self.args + for_each.source)
class ExecutionPlan(BaseModel):                # line 268
    nodes: List[PlanNode] = Field(..., min_length=1)                     # line 298  <-- anchor
    def node(self, node_id: str) -> PlanNode                             # line 388
class ArtifactRef(BaseModel):                  # line 406
    tracking_degraded: bool = False                                      # line 447  <-- anchor
# packages/ai-parrot/src/parrot/bots/flows/plan/__init__.py
from .models import (ArtifactRef, ExecutionManifest, ExecutionPlan, FacetSpec, ForEach, PlanMetadata, PlanNode, RetryPolicy)  # lines 22-31
__all__ = (...)                                                          # lines 46-78, alphabetical-ish tuple
# packages/ai-parrot/src/parrot/tools/execution_plan/runs.py:71
def plan_fingerprint(plan: ExecutionPlan) -> str   # sha256(json.dumps(plan.model_dump(mode="json"), sort_keys=True, separators=(",",":")))
```

### Does NOT Exist
- ~~`PlanNode.type`~~, ~~`DelegatePlanNode`~~, ~~`AnyPlanNode`~~, ~~`_PlanNodeBase`~~, ~~`_node_kind`~~, ~~`tool_names()`~~, ~~`ArtifactRef.escalated`~~: all created here.
- ~~A field-name discriminator (`Field(discriminator="type")`)~~: it does NOT work here, because it requires the tag to be present in the input and legacy plans have no `type`. Use a callable `Discriminator(_node_kind)`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/bots/flows/plan/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/bots/flows/plan/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/bots/flows/plan/test_delegate_models.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/flows/plan/models.py#PlanNode",
    "sym:packages/ai-parrot/src/parrot/bots/flows/plan/models.py#ExecutionPlan",
    "sym:packages/ai-parrot/src/parrot/bots/flows/plan/models.py#ArtifactRef",
    "sym:packages/ai-parrot/src/parrot/tools/execution_plan/runs.py#plan_fingerprint"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The fingerprint test's expected hash MUST be computed on the **unmodified**
  code (step 1) and hard-coded. Computing it after the change would make the
  test tautological.
- `_node_kind` must handle both dicts (JSON input) and model instances
  (programmatic `ExecutionPlan(nodes=[PlanNode(...)])`).
- The existing `tests/bots/flows/plan/test_plan.py` and `tests/tools/execution_plan/` suites must pass **unmodified** (AC11).

---

## Implementation Blueprint

### Steps (in order)
1. **Before editing anything**, compute the fingerprint of the fixture plan in the test block below with the current code, and paste the hex digest into `_FROZEN_FINGERPRINT` — *why*: AC2 needs a pre-feature reference value.
2. Refactor `PlanNode` into `_PlanNodeBase` + `PlanNode` — *why*: shared fields and validation for both node kinds (spec M3).
3. Add `DelegatePlanNode`, `_node_kind`, `AnyPlanNode`; switch `ExecutionPlan.nodes` and `node()` — *why*: plans without `type` parse as tool nodes.
4. Add `ArtifactRef.escalated` — *why*: TASK-3630/3631 report escalations (spec §2 "Escalation").
5. Export from `plan/__init__.py`; write the tests.

### `packages/ai-parrot/src/parrot/bots/flows/plan/models.py` (MODIFY) — node models
```python
# occurrences: 1 (verified: grep -c 'class PlanNode(BaseModel):' packages/ai-parrot/src/parrot/bots/flows/plan/models.py)
# REPLACE the whole `class PlanNode(BaseModel):` body (models.py:173-254) with:
class _PlanNodeBase(BaseModel):
    """Fields and rules shared by every executable plan node.

    Attributes: see :class:`PlanNode` (moved verbatim; docstring kept there).
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    store_as: str
    depends_on: List[str] = Field(default_factory=list)
    when: Optional[str] = None
    for_each: Optional[ForEach] = None
    facets: FacetSpec = Field(default_factory=FacetSpec)
    timeout: Optional[float] = Field(default=None, gt=0.0)
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    description: Optional[str] = None

    @model_validator(mode="after")
    def _check_node(self) -> "_PlanNodeBase":
        # FILL IN: move the body of PlanNode._check_node (models.py:218-240) here unchanged
        return self

    def _template_strings(self) -> List[str]:
        """String leaves that may carry placeholders; overridden per kind."""
        return []

    def referenced_nodes(self) -> set[str]:
        """Node ids referenced through placeholders or ``for_each``."""
        found: set[str] = set()
        for text in self._template_strings():
            found.update(ARTIFACT_REF_RE.findall(text))
            found.update(NODE_REF_RE.findall(text))
        if self.for_each is not None:
            found.add(self.for_each.source_node)
        return found

    def tool_names(self) -> frozenset[str]:
        """Every tool this node may dispatch."""
        raise NotImplementedError


class PlanNode(_PlanNodeBase):
    """A single deterministic tool invocation (or fan-out of invocations).

    # FILL IN: keep the original Attributes docstring (models.py:174-201) verbatim, plus:
        type: Always ``"tool"``. Excluded from dumps so ``plan_fingerprint``
            of tool-only plans is unchanged (FEAT-590 AC2).
    """

    type: Literal["tool"] = Field(default="tool", exclude=True)
    tool: str
    args: Dict[str, Any] = Field(default_factory=dict)

    def _template_strings(self) -> List[str]:
        return list(_iter_strings(self.args))

    def tool_names(self) -> frozenset[str]:
        return frozenset({self.tool})
```
**Why**: `_iter_strings` is defined at the bottom of the module (line 511). It's resolved at call time, so the forward use is fine. The field order changes only the Python class layout. `model_dump` is key-sorted inside `plan_fingerprint`, so it doesn't affect the hash.

### `packages/ai-parrot/src/parrot/bots/flows/plan/models.py` (MODIFY) — delegate node + union
```python
# AFTER the new PlanNode class (still before `class PlanMetadata`):
class DelegatePlanNode(_PlanNodeBase):
    """A runtime-decided tool call proposed by a ``ToolCallDelegate`` (FEAT-590).

    Attributes:
        type: Always ``"delegate"`` (serialised — it is the discriminator).
        instruction: Template text for the delegate; same placeholders as args.
        facts: Short runtime facts; values are templates too.
        tools: Candidate tools (1..delegate.max_tools, checked by the validator).
        min_confidence: Threshold; when set, an unscored (``None``) proposal is rejected.
        accept_when: Optional CEL guard over ``ctx.proposal.*`` plus the usual activation.
        on_reject: ``fail`` | ``retry_backend`` | ``escalate``.
        allow_side_effects: Permit non-``delegate_safe`` tools (host must also allow).
    """

    type: Literal["delegate"] = "delegate"
    instruction: str = Field(..., min_length=1)
    facts: Dict[str, str] = Field(default_factory=dict)
    tools: List[str] = Field(..., min_length=1)
    min_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    accept_when: Optional[str] = None
    on_reject: Literal["fail", "retry_backend", "escalate"] = "fail"
    allow_side_effects: bool = False

    def _template_strings(self) -> List[str]:
        return [self.instruction, *self.facts.values()]

    def tool_names(self) -> frozenset[str]:
        return frozenset(self.tools)


def _node_kind(value: Any) -> str:
    """Discriminator: the ``type`` tag, defaulting to ``"tool"`` when absent."""
    # FILL IN: dict → value.get("type", "tool"); else getattr(value, "type", "tool")
    raise NotImplementedError


AnyPlanNode = Annotated[
    Union[Annotated[PlanNode, Tag("tool")], Annotated[DelegatePlanNode, Tag("delegate")]],
    Discriminator(_node_kind),
]
```
**Why**: spec M3 skeleton verbatim. Duplicate names in `tools` are rejected by the validator (TASK-3628), not here, so the planner model gets a correctable issue instead of a parse error.

### `packages/ai-parrot/src/parrot/bots/flows/plan/models.py` (MODIFY) — ExecutionPlan / ArtifactRef / imports
```python
# occurrences: 1 (verified: grep -c '    nodes: List\[PlanNode\] = Field(..., min_length=1)' models.py)
# REPLACE line 298 with:
    nodes: List[AnyPlanNode] = Field(..., min_length=1)
# ExecutionPlan.node() (line 388): change the return annotation to AnyPlanNode; body unchanged.
# occurrences: 1 (verified: grep -c '    tracking_degraded: bool = False' models.py)
# AFTER — insert below `    tracking_degraded: bool = False` (models.py:447):
    escalated: int = 0
# In ArtifactRef's docstring add: "escalated: Items a delegate node escalated (on_reject='escalate'); FEAT-590."
# Imports (lines 46, 48): add Annotated, Union to typing; Discriminator, Tag to pydantic.
# __all__ (line 50): add "AnyPlanNode", "DelegatePlanNode".
```
**Why**: `escalated` defaults to 0. It does change `ArtifactRef` dumps, but ArtifactRefs are not part of `plan_fingerprint`.

### `packages/ai-parrot/src/parrot/bots/flows/plan/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from .models import (' packages/ai-parrot/src/parrot/bots/flows/plan/__init__.py)
# In the `from .models import (` block (lines 22-31) add: AnyPlanNode, DelegatePlanNode
# In __all__ add: "AnyPlanNode", "DelegatePlanNode"
```

### `packages/ai-parrot/tests/bots/flows/plan/test_delegate_models.py` (CREATE)
```python
"""FEAT-590: plan-language discriminated union."""
from __future__ import annotations

import pytest

from parrot.bots.flows.plan.models import ArtifactRef, DelegatePlanNode, ExecutionPlan, ForEach, PlanNode
from parrot.tools.execution_plan.runs import plan_fingerprint

# Computed on the pre-FEAT-590 code (step 1). NEVER recompute after the change.
_FROZEN_FINGERPRINT = "FILL-IN-HEX-DIGEST"

_LEGACY_PLAN = {
    "name": "legacy",
    "objective": "back-compat",
    "nodes": [
        {"id": "list", "tool": "s3_filter_reports", "args": {"prefix": "p/"}, "store_as": "listing"},
        {"id": "fetch", "tool": "s3_get", "args": {"key": "{item}"}, "store_as": "r_{index}",
         "depends_on": ["list"], "for_each": {"source": "{artifacts.list}", "select": "keys[]"}},
    ],
}


def test_plan_without_type_parses_as_tool() -> None:
    plan = ExecutionPlan.model_validate(_LEGACY_PLAN)
    assert all(isinstance(n, PlanNode) for n in plan.nodes)


def test_tool_plan_fingerprint_unchanged() -> None:
    assert plan_fingerprint(ExecutionPlan.model_validate(_LEGACY_PLAN)) == _FROZEN_FINGERPRINT


def test_delegate_node_roundtrip() -> None:
    """dump → validate keeps type='delegate' and every delegate field."""
    # FILL IN


def test_delegate_referenced_nodes_include_instruction_and_facts() -> None:
    """A {nodes.x.output} in instruction or facts without depends_on → ValueError."""
    # FILL IN


def test_delegate_store_as_for_each_rules() -> None:
    """Inherited rule: for_each requires a per-item store_as key."""
    # FILL IN


def test_tool_names() -> None:
    # FILL IN: PlanNode → {tool}; DelegatePlanNode → set(tools)


def test_artifact_ref_escalated_default() -> None:
    assert ArtifactRef(node_id="x").escalated == 0
```

### FILL IN checklist
- [ ] `_FROZEN_FINGERPRINT`: computed BEFORE editing (AC2)
- [ ] `_PlanNodeBase._check_node`: body moved verbatim
- [ ] `PlanNode` docstring: original attributes kept
- [ ] `_node_kind`: dict and instance paths
- [ ] Test bodies marked FILL IN

---

## Acceptance Criteria

- [ ] AC2: legacy plans parse, and the tool-only fingerprint equals the frozen value
- [ ] `ExecutionPlan` accepts mixed tool + delegate nodes, and dumps keep `type` only for delegate nodes
- [ ] Existing plan and execution_plan suites pass unmodified (AC11)
- [ ] `ruff check` is clean on changed files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/flows/plan/test_delegate_models.py -q`
- `pytest packages/ai-parrot/tests/bots/flows/plan/test_plan.py -q`
- `pytest packages/ai-parrot/tests/tools/execution_plan/test_run_models.py -q`
- `pytest packages/ai-parrot/tests/tools/execution_plan/test_checkpoint_resume.py -q`

---

## Test Specification

See the test file block above.

---

## Agent Instructions

Standard. Remember step 1 happens before any edit.

---

## Completion Note

*(Agent fills this in when done)*
