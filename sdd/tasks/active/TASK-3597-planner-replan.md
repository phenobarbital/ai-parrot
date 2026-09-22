# TASK-3597: `PlanPlanner.replan` / `repair_delta` — one delta call, at most one correction

**Feature**: FEAT-585 — Plan-then-Execute Hardening
**Spec**: `sdd/specs/plan-then-execute-hardening.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3590
**Assigned-to**: unassigned

---

## Context

Implements the planner half of spec §3 **Module 5** and AC2 / AC8 (planner-call bounds).

`PlanPlanner` (`tools/execution_plan/planner.py:127`) authors and structurally repairs a
**whole** `ExecutionPlan`; its `_parse_plan` expects an `ExecutionPlan` document
(`:243-258`). Runtime repair needs a separate path that asks for a `PlanDelta` (replacement
nodes only, restricted to the eligible ids), makes exactly **one** call, and on a malformed or
invalid delta makes at most **one** structural correction call with the same eligible ids and
rules. Both prompts receive only the original plan, a bounded manifest/error summary and the
allowlisted tool descriptions — never artifact bodies. Do not route a `PlanDelta` through the
existing `repair()`.

---

## Scope

- Extend `PlanPlanner` in `packages/ai-parrot/src/parrot/tools/execution_plan/planner.py` with
  `replan(plan, manifest, *, eligible_node_ids)`, `repair_delta(delta_json, report, *, plan,
  eligible_node_ids)`, `_delta_prompt(...)`, `_delta_repair_prompt(...)`, `_parse_delta(text)`
  and the module constant `_DELTA_RULES`. Add `PlanDelta` to `__all__` re-exports only if
  needed (it lives in `models.py`).
- Write `packages/ai-parrot/tests/tools/execution_plan/test_delta_planner.py`
  (spec §4 `test_delta_structural_correction` — planner side).

**NOT in scope**:
- Eligibility/merge/validation (TASK-3596); attempt accounting and the correction loop's
  *policy* (TASK-3601 decides whether to call `repair_delta`; this task only provides the method).
- Changing `author()`, `repair()`, `_call()` or `_parse_plan()`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/execution_plan/planner.py` | MODIFY | Add delta authoring/correction methods and prompts |
| `packages/ai-parrot/tests/tools/execution_plan/test_delta_planner.py` | CREATE | Scripted-client tests for call counts, prompt contents, parse errors |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `3028213ee` on 2026-09-21.

### Verified Imports
```python
# Already imported in planner.py (lines 24-36): json, logging, re, typing (Any, Dict, List, Sequence, Type, Union),
# pydantic.ValidationError, ExecutionPlan, ValidationReport, AbstractClient, SUPPORTED_CLIENTS, LLMFactory, ToolCatalogEntry
from parrot.bots.flows.plan import ExecutionManifest      # verified: plan/__init__.py:24 — new import this task adds
from typing import FrozenSet                               # new
from .models import PlanDelta                              # TASK-3590 — new import (models.py imports nothing from planner: no cycle)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/execution_plan/planner.py
_PLANNING_RULES = """..."""                                              # :40-53 — module constant; add _DELTA_RULES below it
class PlanAuthoringError(RuntimeError)                                    # :56
class PlanPlanner:                                                        # :127
    def __init__(self, planner_llm, catalog: Sequence[ToolCatalogEntry])  # :136 — self.client, self.catalog, self.logger
    async def author(self, objective: str) -> ExecutionPlan               # :151
    async def repair(self, plan_json: Dict[str, Any], report: ValidationReport) -> ExecutionPlan   # :174 — expects ExecutionPlan JSON; DO NOT reuse for deltas
    async def _call(self, prompt: str) -> str                             # :198 — exactly one client call, temperature=0.0
    def _authoring_prompt(self, objective) -> str (:208); def _repair_prompt(self, plan_json, report) -> str (:218)
    def _render_catalog(self) -> str                                      # :229
    def _parse_plan(self, response_text: str) -> ExecutionPlan            # :243 — json.loads + ExecutionPlan.model_validate; raises PlanAuthoringError
def _extract_json_text(text: str) -> str                                  # :261 — strips ``` fences
def _response_text(response: Any) -> str                                  # :270
# tests: packages/ai-parrot/tests/tools/execution_plan/test_planner.py:37-60 `_FakeClient(AbstractClient)` scripted ask(); TASK-3593 adds
#        `_recovery_fakes.ScriptedPlannerClient` with a `calls` list — prefer it.
```

### Does NOT Exist
- ~~`PlanPlanner.replan` / `.repair_delta` / `._parse_delta`~~ — new in this task.
- ~~`AbstractClient.ask(structured_output=PlanDelta)`~~ as the parse path — the module deliberately parses itself (`planner.py:14-20` docstring); keep that.
- ~~`ExecutionManifest.errors`~~ — errors live per-ref in `ArtifactRef.errors`; build the bounded summary from `manifest.artifacts`.
- ~~artifact bodies anywhere in a prompt~~ — only `ArtifactRef` fields (node_id, status, errors[:300], keys) may be rendered.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/tools/execution_plan/planner.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/tools/execution_plan/test_delta_planner.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/execution_plan/planner.py#PlanPlanner",
    "sym:packages/ai-parrot/src/parrot/tools/execution_plan/planner.py#PlanPlanner._call",
    "sym:packages/ai-parrot/src/parrot/tools/execution_plan/planner.py#PlanPlanner._parse_plan",
    "sym:packages/ai-parrot/src/parrot/tools/execution_plan/planner.py#PlanAuthoringError"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `replan` = exactly one `_call`; `repair_delta` = exactly one `_call`. Neither loops.
- Both prompts embed: `_DELTA_RULES`, the catalog, `PlanDelta.model_json_schema()`, the
  original plan JSON, the eligible ids (sorted), and a bounded error summary
  (`node_id: status — errors[0][:300]` for each non-ok ref). Never `keys`' contents.
- `_parse_delta` raises `PlanAuthoringError` on non-JSON or `PlanDelta` validation failure, and
  also when any returned node id ∉ `eligible_node_ids` (cheap pre-check; the full invariant
  check is TASK-3596's `validate_delta`).
- Bound the manifest summary to the first 20 non-ok refs and 300 chars per error.

### References in Codebase
- `planner.py:208-227` — prompt composition style to mirror.
- `planner.py:243-258` — parse/raise idiom to mirror for `_parse_delta`.

---

## Implementation Blueprint

### Steps (in order)
1. Add `_DELTA_RULES` and the `PlanDelta` / `ExecutionManifest` imports — *why*: the rules text is what tells the model it may only return replacements.
2. Add `_parse_delta` — *why*: `_parse_plan` validates the wrong model.
3. Add `_delta_prompt`, `_delta_repair_prompt`, `replan`, `repair_delta` — *why*: two methods, two prompts, two single calls.
4. Tests with `ScriptedPlannerClient` — *why*: call counting is the AC8 evidence.

### `packages/ai-parrot/src/parrot/tools/execution_plan/planner.py` (MODIFY — rules constant)
```python
# occurrences: 1 (verified: grep -c '^class PlanAuthoringError' packages/ai-parrot/src/parrot/tools/execution_plan/planner.py)
# BEFORE — insert ABOVE `class PlanAuthoringError(RuntimeError):` (verified: planner.py:56)
_DELTA_RULES = """\
You are repairing a FAILED ExecutionPlan at runtime. Respond with a PlanDelta: ONLY the
replacement nodes, keyed by their EXISTING ids. Rules:
- You may replace ONLY the node ids listed as eligible. Never add a node, never rename one,
  never return a node whose id is not eligible.
- For each replacement keep `id`, `store_as`, `depends_on` and any `for_each`
  source/select/skip_existing EXACTLY as in the original. You may change `tool`, `args`,
  `facets`, `when`, `timeout`, `retry`, `description`.
- Successful nodes are NOT re-executed; a replacement may still depend on them.
- Never invent a tool not in the catalog."""
```
**Why**: the model-facing statement of D2; the validator enforces it afterwards.

### `packages/ai-parrot/src/parrot/tools/execution_plan/planner.py` (MODIFY — methods)
```python
# occurrences: 1 (verified: grep -c '    # ── LLM call ─' packages/ai-parrot/src/parrot/tools/execution_plan/planner.py)
# BEFORE — insert ABOVE the `    # ── LLM call ───...` section header inside PlanPlanner (verified: planner.py:196)
    async def replan(self, plan: ExecutionPlan, manifest: ExecutionManifest, *, eligible_node_ids: FrozenSet[str]) -> PlanDelta:
        """Make one planner call for replacements only; raise on malformed output."""
        self.logger.info("Replanning %r: %d eligible node(s)", plan.name, len(eligible_node_ids))
        text = await self._call(self._delta_prompt(plan, manifest, eligible_node_ids))
        return self._parse_delta(text, eligible_node_ids)

    async def repair_delta(self, delta_json: Dict[str, Any], report: ValidationReport, *, plan: ExecutionPlan,
                           eligible_node_ids: FrozenSet[str]) -> PlanDelta:
        """Make one structural correction call, retaining runtime delta restrictions."""
        self.logger.info("Correcting delta for %r: %d issue(s)", plan.name, len(report.issues))
        text = await self._call(self._delta_repair_prompt(plan, delta_json, report, eligible_node_ids))
        return self._parse_delta(text, eligible_node_ids)

    def _delta_prompt(self, plan: ExecutionPlan, manifest: ExecutionManifest, eligible: FrozenSet[str]) -> str:
        return (
            f"{_DELTA_RULES}\n\nTool catalog:\n{self._render_catalog()}\n\n"
            f"PlanDelta JSON Schema:\n{json.dumps(PlanDelta.model_json_schema())}\n\n"
            f"Original plan:\n{json.dumps(plan.model_dump(mode='json'))}\n\n"
            f"Eligible node ids: {sorted(eligible)}\n\nFailures:\n{self._render_failures(manifest)}\n\n"
            "Respond with ONLY the PlanDelta JSON document — no prose, no markdown code fences."
        )

    def _delta_repair_prompt(self, plan: ExecutionPlan, delta_json: Dict[str, Any], report: ValidationReport,
                             eligible: FrozenSet[str]) -> str:
        # FILL IN: same header as _delta_prompt (rules, catalog, schema, original plan, eligible ids) followed by
        # "The following delta failed validation:" + json.dumps(delta_json) + "Validation report:" + str(report)
        # and the same closing instruction — bounded by "with the same eligible IDs and validation rules".
        raise NotImplementedError

    def _render_failures(self, manifest: ExecutionManifest) -> str:
        """Bounded per-node failure summary — statuses and truncated messages, never bodies."""
        lines = [f"- {ref.node_id}: {ref.status}" + (f" — {ref.errors[0][:300]}" if ref.errors else "")
                 for ref in manifest.artifacts if ref.status != "ok"]
        return "\n".join(lines[:20]) or "(no per-node failures recorded)"

    def _parse_delta(self, response_text: str, eligible: FrozenSet[str]) -> PlanDelta:
        """Parse one planner response into a PlanDelta restricted to eligible ids."""
        text = _extract_json_text(response_text)
        try:
            document = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PlanAuthoringError(f"Planner delta was not valid JSON: {exc}. Response started with: {response_text[:200]!r}") from exc
        try:
            delta = PlanDelta.model_validate(document)
        except ValidationError as exc:
            raise PlanAuthoringError(f"Planner delta failed PlanDelta validation: {exc}") from exc
        stray = {node.id for node in delta.nodes} - eligible
        if stray:
            raise PlanAuthoringError(f"Planner delta names non-eligible node ids: {sorted(stray)}")
        return delta
```
**Why this shape**: mirrors `author`/`repair`/`_parse_plan` one-to-one so behaviour is
predictable; `_render_failures` is the only place manifest data enters a prompt and it
renders `ArtifactRef` scalars only (§2 "never artifact bodies").

### `packages/ai-parrot/tests/tools/execution_plan/test_delta_planner.py` (CREATE)
```python
"""FEAT-585 M5 — PlanPlanner.replan / repair_delta call bounds and prompt contents."""
from __future__ import annotations
import json
import pytest
from parrot.bots.flows.plan import ArtifactRef, ExecutionManifest, ExecutionPlan, PlanNode
from parrot.tools.execution_plan.catalog import ToolCatalogEntry
from parrot.tools.execution_plan.models import PlanDelta
from parrot.tools.execution_plan.planner import PlanAuthoringError, PlanPlanner
from ._recovery_fakes import ScriptedPlannerClient

pytestmark = pytest.mark.asyncio

async def test_replan_makes_exactly_one_call_and_returns_delta(): ...
async def test_replan_prompt_contains_rules_eligible_ids_and_no_bodies(): ...   # "SECRET-BODY" stored value never appears in client.calls[0]
async def test_replan_rejects_non_eligible_ids(): ...                          # PlanAuthoringError
async def test_replan_rejects_non_json_and_invalid_delta(): ...
async def test_repair_delta_makes_exactly_one_call_with_report_text(): ...
async def test_failures_summary_is_bounded(): ...                              # 30 failed refs → 20 lines; 1000-char error → 300
```

### FILL IN checklist
- [ ] `planner.py::PlanPlanner._delta_repair_prompt` — body; §2 "one separate structural correction call"
- [ ] `test_delta_planner.py` — bodies

---

## Acceptance Criteria

- [ ] AC-1 — `replan` performs exactly one `ask()` and returns a `PlanDelta`; `repair_delta` performs exactly one more (AC8 "at most 2N planner calls").
- [ ] AC-2 — Prompts contain `_DELTA_RULES`, the sorted eligible ids, the original plan JSON and the `PlanDelta` schema; a stored artifact body string never appears in any prompt (AC2).
- [ ] AC-3 — Non-JSON, non-`PlanDelta` JSON and non-eligible ids each raise `PlanAuthoringError`.
- [ ] AC-4 — `author`, `repair`, `_call`, `_parse_plan` are unchanged (existing `test_planner.py` passes).
- [ ] `ruff check` clean.

## Validation Commands
- `pytest packages/ai-parrot/tests/tools/execution_plan/test_delta_planner.py -q`
- `pytest packages/ai-parrot/tests/tools/execution_plan/test_planner.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. Read spec §2 "Repair validation, execution and concurrency" (planner paragraph) and §3 Module 5.
2. Verify anchors, implement, run Validation Commands.
3. Move this file to `sdd/tasks/completed/`, update the per-spec index, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
