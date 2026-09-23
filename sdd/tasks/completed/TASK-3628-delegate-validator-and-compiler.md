# TASK-3628: Delegate-aware validator and compiler

**Feature**: FEAT-590 — Tool-Call Delegate
**Spec**: `sdd/specs/tool-call-delegate.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3625, TASK-3626, TASK-3627
**Assigned-to**: unassigned

---

## Context

Spec Module 4, part 1: static, zero-token validation of delegate nodes (G3,
AC4, AC5) and their compilation to `NodeDefinition(type="delegate")` (AC3).
It also adds `ensure_delegate_node_registered`, the mirror of
`ensure_tool_node_registered`. Allowlist and repair are TASK-3629.

---

## Scope

- `validate_plan(..., delegates=None, allow_delegate_side_effects=False)`. For each `DelegatePlanNode`, emit these issue codes:
  - `unknown_tool` (with a "did you mean" hint)
  - `duplicate_delegate_tools`
  - `no_delegate_configured`
  - `too_many_delegate_tools`
  - `delegate_side_effect`
  - `bad_accept_when`
- `_check_tool` is skipped for delegate nodes. `_check_paths`, `_check_guard` (on `when`) and `_check_for_each` run unchanged for both kinds.
- `to_flow_definition`: `type=DELEGATE_NODE_TYPE` for delegate nodes, plus label and metadata per spec M4.
- Add `DELEGATE_NODE_TYPE = "delegate"` and `ensure_delegate_node_registered(node_cls)`.
- Export both from `parrot.bots.flows.plan`.
- Write tests.

**NOT in scope**: `catalog.check_allowlist`, `repair.validate_delta` (TASK-3629); toolkit wiring (TASK-3635).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/plan/validator.py` | MODIFY | Delegate rules + new kwargs |
| `packages/ai-parrot/src/parrot/bots/flows/plan/compile.py` | MODIFY | `type="delegate"` + registration helper |
| `packages/ai-parrot/src/parrot/bots/flows/plan/__init__.py` | MODIFY | Export `DELEGATE_NODE_TYPE`, `ensure_delegate_node_registered` |
| `packages/ai-parrot/tests/bots/flows/plan/test_delegate_validation.py` | CREATE | One test per issue code + compile tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.flows.plan.models import DelegatePlanNode, ExecutionPlan, PlanNode       # DelegatePlanNode from TASK-3626
from parrot.bots.flows.plan.guards import GuardCompilationError, compile_guard            # guards.py:35
from parrot.bots.flows.plan.delegate.protocol import ToolCallDelegate                     # TASK-3627 (type hint only)
from parrot.bots.flows.flow.flow import NODE_REGISTRY, register_node                      # flow.py:133,158 (lazy import inside the function, as compile.py:145 does)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/plan/validator.py
def validate_plan(plan, tool_manager=None, *, check_guards: bool = True) -> ValidationReport   # line 112  <-- anchor
    # per-node loop lines 149-154:
    #     _check_tool(node, tool_manager, report)     <-- anchor (line 150)
    #     _check_paths(node, report)
    #     if check_guards: _check_guard(node, plan, known_ids, published, report)
    #     _check_for_each(node, plan, report)
def _check_tool(node: PlanNode, tool_manager, report) -> None                                   # line 159 (reads node.tool / node.args)
def _closest(name: str, candidates) -> Optional[str]                                            # line 376
@dataclass(frozen=True) class ValidationIssue: node_id, code, message, severity="error"         # line 48
# packages/ai-parrot/src/parrot/bots/flows/plan/compile.py
PLAN_NODE_TYPE = "tool"                                                                          # line 33
def to_flow_definition(plan) -> Any                                                              # line 38; loop `for plan_node in plan.nodes:` line 71
#   NodeDefinition(id=..., type=PLAN_NODE_TYPE, label=plan_node.description or plan_node.tool,
#                  max_retries=..., config=node_config(plan_node), metadata={"plan": plan.name, "tool": plan_node.tool})  lines 72-80
def ensure_tool_node_registered(node_cls: Any) -> None                                           # line 133-154 (pattern to mirror)
# AbstractTool.delegate_safe: bool = False — TASK-3625. ToolDefinition has NO such attribute → getattr(tool, "delegate_safe", False).
```

### Does NOT Exist
- ~~`validate_plan(..., delegates=...)`~~ before this task.
- ~~`DELEGATE_NODE_TYPE`~~ / ~~`ensure_delegate_node_registered`~~: created here.
- ~~`TemplateResolutionError`~~ in `plan/`: it's a crew concept (`crew/tool_node.py:74`). Don't import it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/bots/flows/plan/validator.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/bots/flows/plan/compile.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/bots/flows/plan/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/bots/flows/plan/test_delegate_validation.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/flows/plan/validator.py#validate_plan",
    "sym:packages/ai-parrot/src/parrot/bots/flows/plan/validator.py#_check_tool",
    "sym:packages/ai-parrot/src/parrot/bots/flows/plan/compile.py#to_flow_definition",
    "sym:packages/ai-parrot/src/parrot/bots/flows/plan/compile.py#ensure_tool_node_registered"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- All checks run before returning. The planner model gets every issue in one pass.
- The side-effect rule: a tool is allowed iff `getattr(tool, "delegate_safe", False)` is true, **or** (`node.allow_side_effects` **and** `allow_delegate_side_effects`). The host flag comes from toolkit config, never from plan text (design-research S6).
- `too_many_delegate_tools` checks `delegates[0].max_tools`, the primary. Fallbacks with a smaller `max_tools` are skipped at run time (TASK-3631), not rejected here.
- Plans without delegate nodes produce exactly the same report as before. Existing tests stay green.

---

## Implementation Blueprint

### Steps (in order)
1. Extend `validate_plan`'s signature and loop — *why*: spec M4 skeleton; kwargs only, so existing callers are unaffected.
2. Add `_check_delegate` — *why*: holds all the delegate issue codes in one place.
3. Update `to_flow_definition` and add the registration helper — *why*: AC3.
4. Export and test.

### `packages/ai-parrot/src/parrot/bots/flows/plan/validator.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def validate_plan(' packages/ai-parrot/src/parrot/bots/flows/plan/validator.py)
# REPLACE the signature at validator.py:112-117 with:
def validate_plan(
    plan: ExecutionPlan,
    tool_manager: Optional[ToolManagerLike] = None,
    *,
    check_guards: bool = True,
    delegates: Optional[Sequence[Any]] = None,
    allow_delegate_side_effects: bool = False,
) -> ValidationReport:
    # docstring: add Args for delegates ("ordered ToolCallDelegate chain; [0] sets max_tools")
    #            and allow_delegate_side_effects ("host policy; plan text cannot grant it").

# occurrences: 1 (verified: grep -c '        _check_tool(node, tool_manager, report)' validator.py)
# REPLACE `        _check_tool(node, tool_manager, report)` (validator.py:150) with:
        if isinstance(node, DelegatePlanNode):
            _check_delegate(node, tool_manager, delegates, allow_delegate_side_effects, check_guards, report)
        else:
            _check_tool(node, tool_manager, report)

# NEW function, below _check_tool:
def _check_delegate(
    node: DelegatePlanNode,
    tool_manager: Optional[ToolManagerLike],
    delegates: Optional[Sequence[Any]],
    allow_side_effects_host: bool,
    check_guards: bool,
    report: ValidationReport,
) -> None:
    """Delegate-node rules (FEAT-590 spec M4): tools, ceiling, side effects, accept_when."""
    if len(set(node.tools)) != len(node.tools):
        report.issues.append(ValidationIssue(node.id, "duplicate_delegate_tools", f"'tools' repeats names: {node.tools}."))
    if not delegates:
        report.issues.append(ValidationIssue(node.id, "no_delegate_configured",
            "Plan contains a delegate node but no ToolCallDelegate is configured on this toolkit."))
    # FILL IN: too_many_delegate_tools vs delegates[0].max_tools (skip when no delegates);
    #   per name: unknown_tool with _closest hint (skip when tool_manager is None);
    #   delegate_side_effect per the rule in Key Constraints (message names the tool and both switches);
    #   bad_accept_when via compile_guard when check_guards and node.accept_when — bounded by AC4/AC5
```
**Why**: imports — add `DelegatePlanNode` to the `.models` import (line 27) and `Any` is already in `typing` (line 24). `unknown_tool` reuses the existing code string so planner prompts treat it identically.

### `packages/ai-parrot/src/parrot/bots/flows/plan/compile.py` (MODIFY)
```python
# PLAN_NODE_TYPE line 33 — AFTER it add:
DELEGATE_NODE_TYPE = "delegate"
# __all__: add "DELEGATE_NODE_TYPE", "ensure_delegate_node_registered"

# occurrences: 1 (verified: grep -c '    for plan_node in plan.nodes:' compile.py)
# In the loop body (compile.py:72-80) compute kind-specific values instead of reading plan_node.tool:
        tools = sorted(plan_node.tool_names())
        is_delegate = getattr(plan_node, "type", "tool") == DELEGATE_NODE_TYPE
        node_type = DELEGATE_NODE_TYPE if is_delegate else PLAN_NODE_TYPE
        label = plan_node.description or (("delegate:" + "|".join(tools)) if is_delegate else plan_node.tool)
        metadata = {"plan": plan.name, "tools": tools} if is_delegate else {"plan": plan.name, "tool": plan_node.tool}
        # FILL IN: pass node_type/label/metadata into the existing NodeDefinition(...) call; keep max_retries/config
#   — the tool-node branch must produce EXACTLY the previous NodeDefinition (existing tests compare it).

# occurrences: 1 (verified: grep -c 'def ensure_tool_node_registered(node_cls: Any) -> None:' compile.py)
# AFTER ensure_tool_node_registered (compile.py:133-154) add:
def ensure_delegate_node_registered(node_cls: Any) -> None:
    """Register ``node_cls`` under ``"delegate"`` in ``NODE_REGISTRY``, once.

    Mirror of :func:`ensure_tool_node_registered`: idempotent, raises when a
    different class already owns the name.
    """
    # FILL IN: same body as ensure_tool_node_registered with DELEGATE_NODE_TYPE
```
**Why**: `node_config(plan_node)` needs no change. `model_dump` keeps `type="delegate"` for delegate nodes and drops it for tool nodes (TASK-3626). Delegate nodes carry no `tool` metadata key; `metadata["tools"]` is used instead.

### `packages/ai-parrot/src/parrot/bots/flows/plan/__init__.py` (MODIFY)
```python
# In `from .compile import (` (lines 13-19) add DELEGATE_NODE_TYPE, ensure_delegate_node_registered; add both to __all__.
```

### `packages/ai-parrot/tests/bots/flows/plan/test_delegate_validation.py` (CREATE)
```python
"""FEAT-590 M4: delegate validator rules + compiler."""
from __future__ import annotations

import pytest
from pydantic import BaseModel

from parrot.bots.flows.plan import DELEGATE_NODE_TYPE, ensure_delegate_node_registered, to_flow_definition, validate_plan
from parrot.bots.flows.plan.models import DelegatePlanNode, ExecutionPlan, PlanNode
from ._delegate_fakes import FakeDelegate, FakeTool, FakeToolManager


class _UrlArgs(BaseModel):
    url: str


def _plan(**delegate_kw) -> ExecutionPlan:
    # FILL IN: one tool node "src" + one DelegatePlanNode "pick" depending on it
    raise NotImplementedError


@pytest.mark.parametrize("code", ["unknown_tool", "duplicate_delegate_tools", "no_delegate_configured",
                                  "too_many_delegate_tools", "delegate_side_effect", "bad_accept_when"])
def test_validator_delegate_rules(code: str) -> None: ...   # FILL IN: one arrangement per code
def test_side_effects_need_node_and_host() -> None: ...     # FILL IN (AC5: either flag alone → still an error)
def test_tool_only_plan_report_unchanged() -> None: ...     # FILL IN (no delegate kwargs, legacy plan → same issues)
def test_compile_emits_delegate_type() -> None: ...         # FILL IN (type/label/metadata['tools'])
def test_ensure_delegate_node_registered_idempotent() -> None: ...  # FILL IN (second call no-op; foreign class raises; clean NODE_REGISTRY after)
```

### FILL IN checklist
- [ ] `_check_delegate` remaining codes; bounded by AC4/AC5
- [ ] `to_flow_definition` tool branch byte-identical
- [ ] `ensure_delegate_node_registered` body
- [ ] Tests (restore `NODE_REGISTRY` in the registration test, e.g. `monkeypatch.delitem`)

---

## Acceptance Criteria

- [ ] AC4: every delegate issue code is reported in one pass
- [ ] AC5: the side-effect rule needs both the node and host flags
- [ ] AC3 (compile half): delegate nodes compile to `type="delegate"`
- [ ] The existing `test_plan.py` passes unmodified
- [ ] `ruff check` is clean on changed files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/flows/plan/test_delegate_validation.py -q`
- `pytest packages/ai-parrot/tests/bots/flows/plan/test_plan.py -q`

---

## Test Specification

See the test file block above.

---

## Agent Instructions

Standard.

---

## Completion Note

Implemented by coder seat `gpt-5.6-terra` (codex), attempt_uid
`7f1a63c4f5354675b35f178366766470`. Merged clean; `black` lint reported 0
errors/residuals. Reviewed and recorded (`coder-review:ad99b06767861d9022b50773`,
no corrections needed).

**Validation**: re-verified directly by the orchestrator post-merge, combined with
TASK-3627/3630/3632/3633's own test files — 68 passed, 2 skipped (integration tests
gated on live backends).

**Merge-tier validation deviation (disclosed):** same as prior tasks this feature —
the feature-wide `coder_run_validation` (tier=merge) sweep remains environmentally
blocked (`issue:c3c59277ef77`). This task is closed on its own directly-verified
scoped test evidence.
