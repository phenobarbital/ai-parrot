---
type: Wiki Overview
title: 'TASK-1776: Add `infographic` Field to `FlowResult`'
id: doc:sdd-tasks-completed-task-1776-flowresult-infographic-field-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: field on `FlowResult`.
relates_to:
- concept: mod:parrot.bots.flows.core.result
  rel: mentions
- concept: mod:parrot.tools.infographic_toolkit
  rel: mentions
---

# TASK-1776: Add `infographic` Field to `FlowResult`

**Feature**: FEAT-308 — AgentCrew ResultAgent End-of-Flow Multi-Tab Infographic Node
**Spec**: `sdd/specs/agentcrew-node-infographic.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Spec §3 Module 5. `FlowResult` is a dataclass returned by every
> `AgentCrew.run_*()` mode. This task adds an optional `infographic` field
> (default `None`) as the **last** field so existing positional/keyword
> construction and `build_*` helpers are unaffected. When the
> `_finalize_infographic` step (TASK-1779) succeeds, it populates this
> field with an `InfographicRenderResult`.

---

## Scope

- Add `infographic: Optional[InfographicRenderResult] = None` as the **last**
  field on `FlowResult`.
- Expose it in `to_dict()` / serialization if present.
- Write unit test: `test_flowresult_infographic_field`.

**NOT in scope**: Populating the field (that's Module 4 / TASK-1779). Modifying `NodeResult`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/core/result.py` | MODIFY | Add `infographic` field to `FlowResult` |
| `tests/unit/test_flowresult_infographic.py` | CREATE | Unit test for new field |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.flows.core.result import FlowResult, NodeResult  # result.py:273 / :39
from parrot.tools.infographic_toolkit import InfographicRenderResult  # infographic_toolkit.py:91
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/core/result.py

@dataclass                                                              # L272
class FlowResult:                                                       # L273
    output: Any                                                         # L288 (no default)
    responses: Dict[str, Any] = field(default_factory=dict)            # L291
    summary: str = ""                                                   # L294
    nodes: List[NodeExecutionInfo] = field(default_factory=list)       # L297
    execution_log: List[Dict[str, Any]] = field(default_factory=list)  # L300
    total_time: float = 0.0                                            # L303
    status: FlowStatus = FlowStatus.COMPLETED                          # L306
    errors: Dict[str, str] = field(default_factory=dict)               # L309
    metadata: Dict[str, Any] = field(default_factory=dict)             # L312
    # ← new `infographic` field goes here (LAST position)

# packages/ai-parrot/src/parrot/tools/infographic_toolkit.py
class InfographicRenderResult(BaseModel):                              # L91
    artifact_id: Optional[str] = None
    html_url: Optional[str] = None
    html_inline: Optional[str] = None                                  # None when >= 50 KB
    template_name: str
    theme: str
    data_variables: List[str]
    enhanced: bool
```

### Does NOT Exist
- ~~`FlowResult.infographic`~~ — does **not** exist yet; this task adds it.
- ~~`FlowResult.to_dict()`~~ — check if this method exists; if not, serialization may go through `asdict()`.

---

## Implementation Notes

### Pattern to Follow
```python
# Add as the LAST field with a default — preserves positional construction
@dataclass
class FlowResult:
    output: Any
    # ... existing fields ...
    metadata: Dict[str, Any] = field(default_factory=dict)             # existing last field
    infographic: Optional["InfographicRenderResult"] = None            # NEW — always last
```

### Key Constraints
- Use a forward reference string `"InfographicRenderResult"` or `TYPE_CHECKING`
  import to avoid circular imports (infographic_toolkit imports from models,
  result.py should not create a hard import cycle).
- The field MUST be the last field with a default value.
- Check if `FlowResult` has a `to_dict()` method — if so, include `infographic`
  in the output (serialize as dict via `.model_dump()` when not None).

---

## Acceptance Criteria

- [ ] `FlowResult(output="test")` still works (no positional breakage)
- [ ] `FlowResult(output="test").infographic is None` (default)
- [ ] `FlowResult(output="test", infographic=render_result).infographic` returns the result
- [ ] Serialization includes `infographic` when set, omits or nulls when not
- [ ] No circular import errors
- [ ] Unit test passes: `pytest tests/unit/test_flowresult_infographic.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/bots/flows/core/result.py`

---

## Test Specification

```python
# tests/unit/test_flowresult_infographic.py
import pytest
from parrot.bots.flows.core.result import FlowResult


class TestFlowResultInfographicField:
    def test_default_is_none(self):
        """FlowResult default infographic is None."""
        r = FlowResult(output="hello")
        assert r.infographic is None

    def test_positional_construction_unaffected(self):
        """Existing positional args still work without infographic."""
        r = FlowResult("hello")
        assert r.output == "hello"
        assert r.infographic is None

    def test_set_infographic(self):
        """infographic field accepts an InfographicRenderResult."""
        from parrot.tools.infographic_toolkit import InfographicRenderResult
        fake = InfographicRenderResult(
            template_name="crew_report", theme="light",
            data_variables=[], enhanced=False,
        )
        r = FlowResult(output="hello", infographic=fake)
        assert r.infographic is fake
        assert r.infographic.template_name == "crew_report"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agentcrew-node-infographic.spec.md` §3 Module 5
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — confirm `FlowResult` still ends at `metadata` and has no `infographic` field
4. **Check for `to_dict()` or serialization methods** on `FlowResult`
5. **Implement** the new field with a safe import strategy
6. **Write and run** unit tests
7. **Update status** and move to completed when done

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-07-14
**Notes**: Added `infographic: Optional["InfographicRenderResult"] = None` as
the last dataclass field, using a `TYPE_CHECKING`-guarded import to avoid a
hard import cycle. `to_dict()` now serialises it via `.model_dump()` when set,
`None` otherwise. Corrected a stale Codebase Contract detail: the task doc
claimed `InfographicRenderResult.artifact_id`/`.html_url` are
`Optional[str] = None`; verified at `infographic_toolkit.py:97-98` both are
REQUIRED (`str`, no default) — tests construct the model with those fields
populated. 5 unit tests pass, ruff clean.

**Deviations from spec**: none (Codebase Contract correction noted above, no
behavioral deviation)
