# TASK-3631: DelegateToolNode + factory

**Feature**: FEAT-590 — Tool-Call Delegate
**Spec**: `sdd/specs/tool-call-delegate.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3626, TASK-3627, TASK-3630
**Assigned-to**: unassigned

---

## Context

Spec Module 5, part 2: the executor for a `DelegatePlanNode`. It overrides only
the hooks TASK-3630 added to `PlanToolNode`, so everything from dispatch
onward is the inherited path: retries, receipts, `ToolManager.execute_tool`,
working-memory storage and fan-out.

"The delegate proposes and code disposes." An accepted proposal must
dispatch exactly as a `PlanToolNode` would (AC8), and a rejected one must
**never** reach `execute_tool` (AC9b).

---

## Scope

- Add `DelegateRejectedError(ToolExecutionError)` and `DelegateEscalation(DelegateRejectedError)`.
- Add `DelegateToolNode(PlanToolNode)` with fields `plan_node: DelegatePlanNode`, `delegates: Tuple[Any, ...]` and `trace_sink: Optional[Any]`. It overrides:
  - `_template_source()` → `{"instruction": ..., "facts": ...}`
  - `_action_label()` → `"delegate:" + "|".join(tools)`
  - `_is_escalation(exc)` → `isinstance(exc, DelegateEscalation)`
  - `_invoke(...)`: the full flow and gate in the spec M5 skeleton, in the exact gate order
- Wire the three `on_reject` outcomes: `fail`, `retry_backend` (walk the chain, skipping delegates whose `max_tools < len(tools)`) and `escalate`.
- `DelegateBackendError` counts as a rejection (verdict `backend_error`).
- Record one `DelegateTrace` per proposal (including each `retry_backend` hop) when a sink is configured. A sink failure never fails the node.
- Add `make_delegate_node_factory(...)`, mirroring `make_tool_node_factory`.
- Write tests covering every verdict and `on_reject` path.

**NOT in scope**: the backends (TASK-3632/3633); flow wiring (TASK-3635); the end-to-end plan run (TASK-3636).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/plan/delegate/node.py` | CREATE | Node, errors, factory |
| `packages/ai-parrot/tests/bots/flows/plan/test_delegate_node.py` | CREATE | Gate / on_reject / trace tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.flows.plan.models import ArtifactRef, DelegatePlanNode        # TASK-3626
from parrot.bots.flows.plan.node import PlanToolNode, ToolExecutionError, _Attempt   # node.py:108,90,887 (+ hooks from TASK-3630)
from parrot.bots.flows.plan.guards import PlanGuard, compile_guard            # guards.py:70,128 (evaluate(..., extra=) from TASK-3630)
from parrot.bots.flows.plan.delegate.protocol import (                        # TASK-3627
    DelegateBackendError, DelegateTrace, ToolCallProposal, ToolSpec, tool_specs,
)
```

### Existing Signatures to Use
```python
# plan/node.py (after TASK-3630)
class PlanToolNode:
    plan_node: PlanNode; tool_manager: Any; working_memory: Any; permission_context: Optional[Any]
    plan_run_id: Optional[str]; step_mapping: Dict[str, str]; dependencies: Set[str]; successors: Set[str]
    _guard: Optional[PlanGuard] = PrivateAttr(...)              # compiled from plan_node.when in model_post_init (line 148)
    def model_post_init(self, __context: Any) -> None           # line 148
    def _resolve_args(self, value, prior, bodies, *, item=None, index=None) -> Any   # line 361 (sync)
    def _template_source(self) -> Any; def _action_label(self) -> str
    async def _invoke(self, prior, bodies, *, item=None, index=None) -> _Attempt
    def _is_escalation(self, exc: BaseException) -> bool
    async def _call_with_retry(self, args, *, index=None, tool=None) -> _Attempt
def make_tool_node_factory(tool_manager, working_memory, *, permission_context=None, plan_run_id=None, step_mapping=None)  # line 1072 — pattern to mirror
# guards.py
class PlanGuard: def evaluate(self, artifacts, statuses=None, errors=0, extra=None) -> bool
# tools/abstract.py
class AbstractTool:
    args_schema: Type[BaseModel]                                    # line 298
    delegate_safe: bool = False                                     # TASK-3625
    def validate_args(self, **kwargs) -> BaseModel                   # line 719 — raises ValueError on invalid
```

### Does NOT Exist
- ~~`ToolDefinition.validate_args`~~ / ~~`ToolDefinition.args_schema`~~: for a `ToolDefinition`, validate by shape only (required keys present, no unknown keys, against `input_schema["properties"]` / `["required"]`).
- ~~`PlanToolNode._accept`~~ or any existing gate helper: the gate is new here.
- ~~Truncating an over-long instruction~~: it must be rejected (`input_too_long`, AC6).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/bots/flows/plan/delegate/node.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/bots/flows/plan/test_delegate_node.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/flows/plan/node.py#PlanToolNode",
    "sym:packages/ai-parrot/src/parrot/bots/flows/plan/node.py#make_tool_node_factory",
    "sym:packages/ai-parrot/src/parrot/bots/flows/plan/guards.py#PlanGuard.evaluate",
    "sym:packages/ai-parrot/src/parrot/tools/abstract.py#AbstractTool.validate_args"
  ]
}
```

---

## Implementation Notes

### Gate order (spec M5, §8 Q-S8 — do not reorder)
1. **input_too_long**: the resolved instruction plus rendered facts exceeds `delegate.max_input_chars`. Checked **before** calling the delegate.
2. **backend_error**: `DelegateBackendError` from `propose_call`.
3. **declined**: `proposal.name is None`.
4. **unknown_tool**: `proposal.name not in node.tools`.
5. **invalid_args**: any of
   - a key not in the tool schema's `properties`
   - a missing required key
   - `validate_args(**arguments)` raising (AbstractTool only)
6. **side_effect_denied**: a runtime re-check against the **live** tool object: `getattr(tool, "delegate_safe", False) or (node.allow_side_effects and self.allow_delegate_side_effects)`.
7. **confidence gate**:
   - skipped entirely when `node.min_confidence is None`
   - `confidence is None` → **unscored** (reject)
   - `confidence < min` → **low_confidence**
8. **guard_false**: `accept_when` evaluates false. The activation is the usual one plus `extra={"proposal": {"name", "arguments", "confidence"}}`.

On accept, dispatch the **original** `proposal.arguments` (not a model dump) via `self._call_with_retry(args, index=index, tool=proposal.name)`. `execute_tool` then coerces exactly once (design-research S5).

### on_reject
- `fail` → raise `DelegateRejectedError(f"{verdict}: …")`.
- `retry_backend` → try the next delegate in `self.delegates` whose `max_tools >= len(node.tools)` (spec §7). Each hop records its own trace. When the chain is exhausted → `DelegateRejectedError`.
- `escalate` → raise `DelegateEscalation(f"escalate: {verdict}: …")`. The inherited fan-out/single paths (TASK-3630) record it and never abort.

### Key constraints
- The node carries a host flag `allow_delegate_side_effects: bool = False` (a field, set by the factory). Plan text can never set it.
- `accept_when` is compiled once in `model_post_init` (store it in a new `PrivateAttr`). Call `super().model_post_init` first.
- The trace's `final_call` is `{"name", "arguments"}` only for an accepted proposal. Traces never enter `FlowContext` or the `ArtifactRef` (AC10).

---

## Implementation Blueprint

### Steps (in order)
1. Write the errors and the class with its fields and hook overrides — *why*: minimal surface over the TASK-3630 hooks.
2. Implement `_invoke` + `_gate` + `_propose_with_chain` — *why*: gate order and `on_reject` per the notes above.
3. Implement `make_delegate_node_factory` — *why*: TASK-3635 plugs it into `build_plan_flow`.
4. Write the tests.

### `packages/ai-parrot/src/parrot/bots/flows/plan/delegate/node.py` (CREATE)
```python
"""``DelegateToolNode`` — a runtime-decided tool call inside an ExecutionPlan (FEAT-590).

The delegate proposes; code disposes. Everything from dispatch onward is the
inherited ``PlanToolNode`` path (retries, receipts, execute_tool, storage).
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Set, Tuple

from pydantic import Field, PrivateAttr

from ..guards import PlanGuard, compile_guard
from ..models import ArtifactRef, DelegatePlanNode
from ..node import PlanToolNode, ToolExecutionError, _Attempt
from .protocol import DelegateBackendError, DelegateTrace, ToolCallProposal, tool_specs

__all__ = ("DelegateEscalation", "DelegateRejectedError", "DelegateToolNode", "make_delegate_node_factory")

logger = logging.getLogger(__name__)


class DelegateRejectedError(ToolExecutionError):
    """The proposal failed the accept gate and ``on_reject`` did not recover it."""


class DelegateEscalation(DelegateRejectedError):
    """``on_reject='escalate'`` — always recorded, message prefixed ``escalate:``."""


class DelegateToolNode(PlanToolNode):
    """Execute one :class:`DelegatePlanNode`."""

    plan_node: DelegatePlanNode  # type: ignore[assignment] — narrowed field
    delegates: Tuple[Any, ...] = Field(default_factory=tuple)
    trace_sink: Optional[Any] = None
    allow_delegate_side_effects: bool = False

    _accept_guard: Optional[PlanGuard] = PrivateAttr(default=None)

    def model_post_init(self, __context: Any) -> None:
        """Compile ``accept_when`` once, after the base compiles ``when``."""
        super().model_post_init(__context)
        object.__setattr__(self, "_accept_guard", compile_guard(self.plan_node.accept_when))

    def _template_source(self) -> Any:
        return {"instruction": self.plan_node.instruction, "facts": dict(self.plan_node.facts)}

    def _action_label(self) -> str:
        return "delegate:" + "|".join(self.plan_node.tools)

    def _is_escalation(self, exc: BaseException) -> bool:
        return isinstance(exc, DelegateEscalation)

    async def _invoke(
        self,
        prior: Mapping[str, ArtifactRef],
        bodies: Mapping[str, Any],
        *,
        item: Any = None,
        index: Optional[int] = None,
    ) -> _Attempt:
        """Resolve → budget → propose → gate → dispatch (or apply on_reject)."""
        resolved = self._resolve_args(self._template_source(), prior, bodies, item=item, index=index)
        instruction: str = str(resolved["instruction"])
        facts: Dict[str, str] = {k: str(v) for k, v in resolved["facts"].items()}
        specs = tool_specs(self.tool_manager, self.plan_node.tools)
        proposal, verdict = await self._propose_with_chain(instruction, facts, specs, prior, index)
        if verdict != "accepted":
            message = f"{verdict}: node {self.node_id!r} proposal {proposal.name!r} rejected"
            if self.plan_node.on_reject == "escalate":
                raise DelegateEscalation(f"escalate: {message}")
            raise DelegateRejectedError(message)
        return await self._call_with_retry(dict(proposal.arguments), index=index, tool=proposal.name)

    async def _propose_with_chain(
        self, instruction: str, facts: Dict[str, str], specs: Sequence[Any],
        prior: Mapping[str, ArtifactRef], index: Optional[int],
    ) -> Tuple[ToolCallProposal, str]:
        """Walk the delegate chain per on_reject; trace every hop. Returns (last proposal, verdict)."""
        # FILL IN: candidates = self.delegates[:1] unless on_reject == "retry_backend" (then all with
        #   max_tools >= len(tools)); per delegate: input_too_long check → propose_call (DelegateBackendError →
        #   synthetic ToolCallProposal(name=None, backend=d.backend_name, latency_ms=0.0), verdict backend_error)
        #   → verdict = self._gate(proposal, prior); await self._trace(...); stop at "accepted"
        raise NotImplementedError

    def _gate(self, proposal: ToolCallProposal, prior: Mapping[str, ArtifactRef]) -> str:
        """Return the verdict string for ``proposal`` (order fixed by spec M5 / §8 Q-S8)."""
        # FILL IN: steps 3–8 of "Gate order"; accept_when via self._accept_guard.evaluate(
        #   artifacts, statuses, failures, extra={"proposal": {...}}) mirroring PlanToolNode._guard_allows
        raise NotImplementedError

    async def _trace(self, **fields: Any) -> None:
        """Record one DelegateTrace; never raises."""
        if self.trace_sink is None:
            return
        try:
            await self.trace_sink.record(DelegateTrace(plan_run_id=self.plan_run_id, node_id=self.node_id, **fields))
        except Exception as exc:  # noqa: BLE001 - AC10: a trace failure never fails the node
            self.logger.warning("Node %r: delegate trace failed: %s", self.node_id, exc)


def make_delegate_node_factory(
    tool_manager: Any,
    working_memory: Any,
    delegates: Sequence[Any],
    *,
    trace_sink: Optional[Any] = None,
    allow_delegate_side_effects: bool = False,
    permission_context: Optional[Any] = None,
    plan_run_id: Optional[str] = None,
    step_mapping: Optional[Mapping[str, str]] = None,
) -> Callable[[Any, Set[str], Set[str]], DelegateToolNode]:
    """Build the ``node_factories["delegate"]`` callable (mirror of make_tool_node_factory)."""
    chain = tuple(delegates)
    mapping = dict(step_mapping or {})

    def factory(node_def: Any, deps: Set[str], succs: Set[str]) -> DelegateToolNode:
        return DelegateToolNode(
            node_id=node_def.id,
            plan_node=DelegatePlanNode.model_validate(node_def.config),
            tool_manager=tool_manager,
            working_memory=working_memory,
            dependencies=set(deps or ()),
            successors=set(succs or ()),
            permission_context=permission_context,
            plan_run_id=plan_run_id,
            step_mapping=mapping,
            delegates=chain,
            trace_sink=trace_sink,
            allow_delegate_side_effects=allow_delegate_side_effects,
        )

    return factory
```
**Why this shape**: gating is split into small methods so each verdict is unit-testable. `specs` is built once per call. `tool_specs` raises `KeyError` for a tool removed after validation, and that surfaces as a node error, which is correct. `_resolve_args` on the `{"instruction","facts"}` dict reuses the exact `PlanToolNode` placeholder semantics.

### `packages/ai-parrot/tests/bots/flows/plan/test_delegate_node.py` (CREATE)
```python
"""FEAT-590 M5: DelegateToolNode gate, on_reject, traces."""
from __future__ import annotations

import pytest
from pydantic import BaseModel

from parrot.bots.flows.plan.delegate import DelegateBackendError, ToolCallProposal
from parrot.bots.flows.plan.delegate.node import DelegateRejectedError, DelegateToolNode, make_delegate_node_factory
from parrot.bots.flows.plan.models import DelegatePlanNode, ForEach
from ._delegate_fakes import FakeDelegate, FakeTool, FakeToolManager
from .test_node import _Ctx, _WorkingMemory


class _Url(BaseModel):
    url: str


def _proposal(name, args=None, confidence=0.9, backend="fake") -> ToolCallProposal:
    return ToolCallProposal(name=name, arguments=args or {}, confidence=confidence, backend=backend, latency_ms=1.0)


@pytest.mark.asyncio
async def test_delegate_accept_dispatches_proposed_tool() -> None: ...   # FILL IN (AC8: manager.calls == [(name, args)])
@pytest.mark.parametrize("verdict", ["declined", "unknown_tool", "invalid_args", "side_effect_denied",
                                     "low_confidence", "unscored", "guard_false", "input_too_long", "backend_error"])
@pytest.mark.asyncio
async def test_delegate_gate_verdicts(verdict: str) -> None: ...          # FILL IN: DelegateRejectedError + trace verdict
@pytest.mark.asyncio
async def test_rejected_proposal_never_dispatches() -> None: ...         # FILL IN (AC9b)
@pytest.mark.asyncio
async def test_extra_arg_keys_rejected() -> None: ...                    # FILL IN
@pytest.mark.asyncio
async def test_side_effect_rechecked_at_dispatch() -> None: ...          # FILL IN (AC9c: flip FakeTool.delegate_safe after construction)
@pytest.mark.asyncio
async def test_confidence_gate_unscored() -> None: ...                   # FILL IN (AC7: min unset → any; min set + None → unscored)
@pytest.mark.asyncio
async def test_on_reject_retry_backend_uses_next_delegate() -> None: ... # FILL IN (+ skip delegate with max_tools < len(tools))
@pytest.mark.asyncio
async def test_on_reject_escalate_recorded_even_with_skip() -> None: ... # FILL IN (for_each on_item_error="skip" → escalated count)
@pytest.mark.asyncio
async def test_single_node_escalate_returns_error_ref() -> None: ...     # FILL IN
@pytest.mark.asyncio
async def test_trace_per_proposal() -> None: ...                         # FILL IN (one trace per hop; failing sink tolerated)
def test_factory_binds_chain_and_host_flag() -> None: ...               # FILL IN
```

### FILL IN checklist
- [ ] `_propose_with_chain`: chain, budget and backend-error handling; bounded by AC6/AC9/AC10
- [ ] `_gate`: steps 3–8 in order; bounded by §8 Q-S8 and design-research S5/S6
- [ ] Every test body

---

## Acceptance Criteria

- [ ] AC6, AC7, AC8, AC9, AC9b, AC9c, AC10 hold (each has a test above)
- [ ] `DelegateToolNode` inherits dispatch/storage (no `execute_tool` call in `delegate/node.py`)
- [ ] `ruff check` is clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/flows/plan/test_delegate_node.py -q`
- `pytest packages/ai-parrot/tests/bots/flows/plan/test_node.py -q`

---

## Test Specification

See the test file block above.

---

## Agent Instructions

Standard.

---

## Completion Note

*(Agent fills this in when done)*
