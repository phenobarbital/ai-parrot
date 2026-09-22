# TASK-3596: Delta eligibility, merge and validation (`repair.py`)

**Feature**: FEAT-585 — Plan-then-Execute Hardening
**Spec**: `sdd/specs/plan-then-execute-hardening.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3590, TASK-3593
**Assigned-to**: unassigned

---

## Context

Implements the validator half of spec §3 **Module 5** and goal **D2** / AC7.

A `PlanDelta` is deliberately not a standalone plan: a replacement may depend on a
successful node that is not in the delta (finding R5). So the delta is **merged** into the
original node set, the resulting `ExecutionPlan` is validated with the frozen
`validate_with_allowlist` (`catalog.py:145`), and the toolkit-specific invariants are
checked on top: only eligible ids (explicit error refs, recorded hard failures, never
dispatched nodes of a terminal failed/partial run), no new/duplicate ids, no ok/skipped/partial
replacement, `store_as` / `depends_on` / fan-out identity preserved, no key collision with
successful artifacts, no plan-level metadata change, and the allowlist intersected with
current host policy (never widened).

---

## Scope

- Create `packages/ai-parrot/src/parrot/tools/execution_plan/repair.py` with
  `eligible_repair_nodes(run)`, `merge_delta(plan, delta)`, `validate_delta(delta, *, run,
  tool_manager, allowed_tools)`, and `protected_node_ids(run)`.
- Write `packages/ai-parrot/tests/tools/execution_plan/test_delta_validation.py`
  (spec §4 `test_delta_validation`, `test_delta_dependency_on_success`, `test_partial_is_not_error`,
  and the M5 part of `test_scope_and_policy_rejection`).

**NOT in scope**:
- Planner prompts / `PlanPlanner.replan` (TASK-3597).
- Executing the merged plan or seeding completed nodes (TASK-3601).
- Any change to `bots/flows/plan/validator.py` (AC1).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/execution_plan/repair.py` | CREATE | Eligibility, merge, validation |
| `packages/ai-parrot/tests/tools/execution_plan/test_delta_validation.py` | CREATE | Validation matrix |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `3028213ee` on 2026-09-21.

### Verified Imports
```python
from parrot.bots.flows.plan import ArtifactRef, ExecutionPlan, PlanNode              # verified: plan/__init__.py:23,25,29
from parrot.bots.flows.plan.validator import ValidationIssue, ValidationReport        # verified: validator.py:48, :70
from parrot.tools.execution_plan.catalog import validate_with_allowlist               # verified: catalog.py:145
from parrot.tools.execution_plan.models import PlanDelta, PlanRun                     # TASK-3590
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/execution_plan/catalog.py:145
def validate_with_allowlist(plan: ExecutionPlan, tool_manager: Optional[Any], allowed_tools: Optional[Sequence[str]] = None,
                            *, check_guards: bool = True) -> ValidationReport
# packages/ai-parrot/src/parrot/bots/flows/plan/validator.py
@dataclass class ValidationIssue: node_id: Optional[str]; code: str; message: str; severity: str = "error"   # :48-66
@dataclass class ValidationReport: issues: List[ValidationIssue]; .errors; .warnings; .ok (no errors); __str__   # :70-98
# packages/ai-parrot/src/parrot/bots/flows/plan/models.py
class PlanNode: id, tool, args, store_as, depends_on: List[str], when, for_each: Optional[ForEach], facets, timeout, retry, description  # :173-216
class ForEach: source (str), select, skip_existing, on_item_error, ... ; source_node property (:166)                                   # :111-170
class ExecutionPlan: name, objective, nodes: List[PlanNode] (min 1), metadata: PlanMetadata; extra="forbid"                          # :268-300
class ArtifactRef: node_id, keys: List[str], status Literal[ok|skipped|partial|error], errors, versions                              # :406-447
# packages/ai-parrot/src/parrot/tools/execution_plan/models.py (TASK-3590)
class PlanDelta: nodes: List[PlanNode] (nonempty, unique ids)
class PlanRun: metadata.plan (effective ExecutionPlan), metadata.allowed_tools: List[str], status, refs: List[ArtifactRef], dispatched_node_ids
```

### Does NOT Exist
- ~~`ExecutionPlan.replace_node()` / `.with_nodes()`~~ — build a new `ExecutionPlan(**plan.model_dump(), nodes=merged)`; models are plain Pydantic.
- ~~`ValidationReport(ok=...)`~~ — `ok` is a property; construct with `ValidationReport(issues=[...])`.
- ~~a `ValidationIssue.severity` Literal~~ — it is a plain `str`; use `"error"`.
- ~~`PlanDelta.plan` / `.metadata`~~ — a delta has only `nodes`; plan-level changes are impossible by type.
- ~~`ArtifactRef.status == "failed"`~~ — the literal is `"error"`; `"partial"` is NOT eligible (D2, spec §1 Non-Goals last bullet).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/tools/execution_plan/repair.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/tools/execution_plan/test_delta_validation.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/execution_plan/catalog.py#validate_with_allowlist",
    "sym:packages/ai-parrot/src/parrot/bots/flows/plan/validator.py#ValidationReport",
    "sym:packages/ai-parrot/src/parrot/bots/flows/plan/validator.py#ValidationIssue",
    "sym:packages/ai-parrot/src/parrot/bots/flows/plan/models.py#ExecutionPlan",
    "sym:packages/ai-parrot/src/parrot/bots/flows/plan/models.py#PlanNode"
  ]
}
```

---

## Implementation Notes

### Key Constraints (spec §2 "Repair validation")
- **Eligible ids** = ids whose ref has `status == "error"` (explicit error refs AND synthesized
  hard-failure/blocked refs — both are `status="error"` after `project_run`) **only if**
  `run.status in ("failed", "partial")`. A `running` or `completed` run has no eligible ids.
  `partial` refs are never eligible.
- **Protected ids** = every plan node id not eligible (ok / skipped / partial).
- `validate_delta` issue codes (all `severity="error"`, `node_id` set where applicable):
  `delta_new_id`, `delta_protected_id`, `delta_store_as_changed`, `delta_depends_on_changed`,
  `delta_for_each_identity_changed` (added/removed `for_each`, or changed `source`/`select`/`skip_existing`
  key mapping), `delta_key_collision` (a replacement `store_as` equals a **successful** ref's key),
  `delta_tool_not_allowed` (tool ∉ `run.metadata.allowed_tools ∩ allowed_tools`), plus every issue
  the frozen `validate_with_allowlist(merged, tool_manager, effective_allowlist)` returns.
- `merge_delta` replaces in **original order**, never appends; a delta id absent from the plan
  is an error surfaced by `validate_delta` (merge itself raises `ValueError` on unknown id so it
  cannot be called unvalidated).
- The planner may change `tool`, `args`, `facets`/select, `when`, `retry`, `timeout`, `description`.

### References in Codebase
- `catalog.py:113-142` `check_allowlist` — issue construction idiom (`ValidationIssue(node_id=..., code="tool_not_allowed", ...)`).
- `toolkit.py:352-359` — how `partial` vs `failed` run status is derived (partial is terminal but NOT repairable by reclassification).

---

## Implementation Blueprint

### Steps (in order)
1. `eligible_repair_nodes` + `protected_node_ids` — *why*: every other check is expressed against these two sets.
2. `merge_delta` — *why*: validation runs over the merged plan; merge must be pure and order-preserving.
3. `validate_delta` — *why*: toolkit invariants first (cheap, exact), then the frozen validator over the merged plan.
4. Tests — *why*: `test_partial_is_not_error` is the D2 guard the spec singles out.

### `packages/ai-parrot/src/parrot/tools/execution_plan/repair.py` (CREATE)
```python
"""Runtime delta eligibility, merge and validation (FEAT-585 M5, goal D2)."""
from __future__ import annotations

from typing import Any, Dict, FrozenSet, List, Sequence

from parrot.bots.flows.plan import ArtifactRef, ExecutionPlan, PlanNode
from parrot.bots.flows.plan.validator import ValidationIssue, ValidationReport

from .catalog import validate_with_allowlist
from .models import PlanDelta, PlanRun

__all__ = ("eligible_repair_nodes", "merge_delta", "protected_node_ids", "validate_delta")
_REPAIRABLE_RUN_STATUSES = frozenset({"failed", "partial"})


def eligible_repair_nodes(run: PlanRun) -> FrozenSet[str]:
    """Return explicit errors and terminal undispatched IDs, excluding partial/ok/skipped."""
    if run.status not in _REPAIRABLE_RUN_STATUSES:
        return frozenset()
    return frozenset(ref.node_id for ref in run.refs if ref.status == "error")


def protected_node_ids(run: PlanRun) -> FrozenSet[str]:
    """Every node that must not be replaced or re-executed."""
    eligible = eligible_repair_nodes(run)
    return frozenset(node.id for node in run.metadata.plan.nodes if node.id not in eligible)


def merge_delta(plan: ExecutionPlan, delta: PlanDelta) -> ExecutionPlan:
    """Replace existing IDs in original order; never add IDs or change plan metadata."""
    replacements: Dict[str, PlanNode] = {node.id: node for node in delta.nodes}
    unknown = set(replacements) - {node.id for node in plan.nodes}
    if unknown:
        raise ValueError(f"delta names ids not in the plan: {sorted(unknown)}")
    merged = [replacements.get(node.id, node) for node in plan.nodes]
    return ExecutionPlan(name=plan.name, objective=plan.objective, nodes=merged, metadata=plan.metadata)


def validate_delta(delta: PlanDelta, *, run: PlanRun, tool_manager: Any, allowed_tools: Sequence[str]) -> ValidationReport:
    """Validate merged topology and tool policy plus protected-node/key invariants."""
    plan = run.metadata.plan
    original: Dict[str, PlanNode] = {node.id: node for node in plan.nodes}
    eligible, protected = eligible_repair_nodes(run), protected_node_ids(run)
    effective_allowlist = sorted(set(run.metadata.allowed_tools) & set(allowed_tools))   # never widened
    successful_keys = {key for ref in run.refs if ref.status == "ok" for key in ref.keys}
    issues: List[ValidationIssue] = []
    for node in delta.nodes:
        if node.id not in original:
            issues.append(ValidationIssue(node_id=node.id, code="delta_new_id", message="delta may not add nodes"))
            continue
        if node.id in protected:
            issues.append(ValidationIssue(node_id=node.id, code="delta_protected_id", message="node is ok/skipped/partial; not repairable"))
        # FILL IN: compare node vs original[node.id] for store_as / depends_on / for_each identity
        # (added-removed, source, select, skip_existing) → delta_store_as_changed / delta_depends_on_changed /
        # delta_for_each_identity_changed; store_as in successful_keys → delta_key_collision;
        # node.tool not in effective_allowlist → delta_tool_not_allowed — bounded by spec §2 "Preserve each
        # replacement node's store_as, dependency list and fan-out identity".
    if issues:
        return ValidationReport(issues=issues)
    merged = merge_delta(plan, delta)
    return validate_with_allowlist(merged, tool_manager, effective_allowlist)
```
**Why this shape**: eligibility is derived from `run.refs` (which `project_run` synthesizes
for hard failures and blocked nodes as `status="error"`), so "explicit errors, recorded hard
failures and never dispatched nodes" are one predicate. Merge-then-validate keeps full
dependency/facet validation without touching the frozen validator (R5).

### `packages/ai-parrot/tests/tools/execution_plan/test_delta_validation.py` (CREATE)
```python
"""FEAT-585 M5 — delta eligibility/merge/validation matrix (D2, AC7)."""
from __future__ import annotations
import pytest
from parrot.bots.flows.plan import ArtifactRef, ExecutionPlan, ForEach, PlanNode
from parrot.tools.execution_plan.models import PlanDelta, PlanRun, PlanRunMetadata
from parrot.tools.execution_plan.repair import eligible_repair_nodes, merge_delta, validate_delta
from ._recovery_fakes import CountingToolManager

def _run(plan: ExecutionPlan, refs, *, status="failed", allowed=None) -> PlanRun: ...   # builds PlanRunMetadata + PlanRun

def test_eligible_is_error_only_on_terminal_failed_or_partial(): ...   # partial ref excluded; running run → empty
def test_partial_is_not_error(): ...                                   # a partial fan-out cannot be reclassified (D2)
def test_merge_preserves_order_and_metadata(): ...
def test_merge_rejects_unknown_id(): ...
@pytest.mark.parametrize("mutation,code", [...])                       # new id, protected id, store_as, depends_on, for_each identity, key collision, disallowed tool
def test_validate_delta_codes(mutation, code): ...
def test_delta_dependency_on_success_validates_without_listing_parent(): ...  # R5: delta omits ok parent; merged report.ok
def test_allowlist_is_intersected_not_widened(): ...                   # run allowed {a}, host allowed {a,b}; delta tool b → delta_tool_not_allowed
```

### FILL IN checklist
- [ ] `repair.py::validate_delta` — the per-node invariant comparisons; spec §2 repair paragraph
- [ ] `test_delta_validation.py` — `_run` helper and parametrized mutations

---

## Acceptance Criteria

- [ ] AC-1 — `eligible_repair_nodes` returns exactly the `status="error"` ids of a `failed`/`partial` run and `frozenset()` for `running`/`completed`; `partial` refs are never included (D2).
- [ ] AC-2 — `merge_delta` keeps original node order and `metadata`, replaces only listed ids, raises on unknown ids.
- [ ] AC-3 — `validate_delta` reports `delta_new_id`, `delta_protected_id`, `delta_store_as_changed`, `delta_depends_on_changed`, `delta_for_each_identity_changed`, `delta_key_collision`, `delta_tool_not_allowed` for the corresponding mutations, and `report.ok` for a valid delta whose parent is an omitted successful node (R5).
- [ ] AC-4 — The effective allowlist is `run.metadata.allowed_tools ∩ allowed_tools` (AC2 "allowlist-validated").
- [ ] `ruff check` clean.

## Validation Commands
- `pytest packages/ai-parrot/tests/tools/execution_plan/test_delta_validation.py -q`
- `pytest packages/ai-parrot/tests/tools/execution_plan/test_catalog.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. Read spec §1 goal D2 and Non-Goals, §2 "Repair validation, execution and concurrency", §3 Module 5.
2. Verify anchors, implement, run Validation Commands.
3. Move this file to `sdd/tasks/completed/`, update the per-spec index, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
