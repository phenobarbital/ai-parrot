---
type: Wiki Overview
title: 'TASK-1765: NodeResult.to_dict() — safe per-agent result serialisation'
id: doc:sdd-tasks-completed-task-1765-noderesult-to-dict-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 1** of FEAT-306. `NodeResult` (the per-agent execution
  record) has
relates_to:
- concept: mod:parrot.bots.flows.core.result
  rel: mentions
- concept: mod:parrot.models.crew
  rel: mentions
---

# TASK-1765: NodeResult.to_dict() — safe per-agent result serialisation

**Feature**: FEAT-306 — Crew Per-Agent Result Persistence & Deterministic Execution Document
**Spec**: `sdd/specs/crew-per-agent-result-persistence.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 1** of FEAT-306. `NodeResult` (the per-agent execution record) has
`to_text()` for FAISS vectorization but NO structured serialisation. Per-agent persistence
(TASK-1767) and the consolidated document (TASK-1768) both need a JSON-safe
`NodeResult.to_dict()` that never raises, regardless of what the agent returned
(DataFrame, arbitrary object, dict, etc.).

---

## Scope

- Implement a module-level helper `_serialise_result_value(value: Any) -> Any` in
  `packages/ai-parrot/src/parrot/bots/flows/core/result.py`:
  - `str | int | float | bool | None` → pass through.
  - `dict` / `list` → recursively serialised (each value passed through the helper).
  - `pandas.DataFrame` (lazy import, same pattern as `to_text()` line 107-122) → bounded
    string preview: shape + columns + `df.head(10).to_string()`. Never the full frame.
  - Anything else → `str(value)`.
  - MUST NOT raise for any input.
- Implement `NodeResult.to_dict(self) -> Dict[str, Any]` returning:
  `node_id`, `node_name`, `agent_id`, `agent_name` (alias values), `task`,
  `result` (via `_serialise_result_value`), `metadata` (via helper, per-value),
  `execution_time`, `timestamp` (`.isoformat()`), `parent_execution_id`, `execution_id`.
  Do NOT include `ai_message` (raw LLM object, not JSON-safe; explicitly excluded).
- Write unit tests in `tests/bots/flows/core/test_result_serialisation.py` (NEW).

**NOT in scope**: `CrewExecutionDocument` (TASK-1768), persistence methods (TASK-1767),
any change to `FlowResult.to_dict()`, `NodeExecutionInfo`, or `to_text()`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/core/result.py` | MODIFY | Add `_serialise_result_value()` helper + `NodeResult.to_dict()` |
| `tests/bots/flows/core/test_result_serialisation.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use these exact references. Verify anything not listed before using it.

### Verified Imports
```python
from parrot.bots.flows.core.result import NodeResult  # verified: result.py:39 (module import path used by memory.py:14)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/core/result.py
@dataclass
class NodeResult:                                   # line 39
    node_id: str                                    # line 63
    node_name: str
    task: str
    result: Any
    ai_message: Optional[Any] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    execution_time: float = 0.0
    timestamp: datetime                             # line 70 — tz-aware UTC default
    parent_execution_id: Optional[str] = None
    execution_id: str                               # line 72 — uuid4 default PER NODE

    @property
    def agent_id(self) -> str: ...                  # line 77 — alias of node_id
    @property
    def agent_name(self) -> str: ...                # line 82 — alias of node_name
    def to_text(self) -> str: ...                   # line 88 — DataFrame lazy-import pattern at 107-122
```

### Does NOT Exist
- ~~`NodeResult.to_dict()`~~ — THIS TASK creates it; nothing to extend.
- ~~`NodeResult.model_dump()`~~ — NodeResult is a dataclass, NOT Pydantic.
- ~~`dataclasses.asdict()` as the implementation~~ — do not use it: it would deep-copy
  `result`/`ai_message` and raise on non-copyable objects; hand-build the dict.
- ~~`parrot.models.crew.AgentResult.to_dict()`~~ — legacy class, do not touch or import.

---

## Implementation Notes

### Pattern to Follow
```python
# Lazy pandas import — copy from result.py:107-122 (to_text)
try:
    from pandas import DataFrame
    if isinstance(value, DataFrame):
        return (f"DataFrame {value.shape[0]}x{value.shape[1]} "
                f"cols=[{', '.join(map(str, value.columns))}]\n{value.head(10).to_string()}")
except ImportError:
    pass
```

### Key Constraints
- `to_dict()` must NEVER raise — final fallback is `str(value)` wrapped in try/except.
- Google-style docstrings + strict type hints.
- The output must survive `json.dumps(d, default=str)` without error for all test inputs.

### References in Codebase
- `packages/ai-parrot/src/parrot/bots/flows/core/result.py:88-155` — `to_text()` type-dispatch pattern.
- `packages/ai-parrot/src/parrot/bots/flows/core/result.py:244-264` — `NodeExecutionInfo.to_dict()` hand-built dict style.

---

## Acceptance Criteria

- [ ] `NodeResult.to_dict()` returns all fields listed in Scope with correct types
- [ ] DataFrame result → bounded string preview (≤ 10 rows), no raise
- [ ] Arbitrary non-serialisable object → `str()` fallback, no raise
- [ ] `json.dumps(node_result.to_dict(), default=str)` succeeds for every test input
- [ ] All tests pass: `pytest tests/bots/flows/core/test_result_serialisation.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/bots/flows/core/result.py`

---

## Test Specification

```python
# tests/bots/flows/core/test_result_serialisation.py
import json
import pytest
from parrot.bots.flows.core.result import NodeResult


def _mk(result):
    return NodeResult(node_id="a1", node_name="Agent One", task="do x", result=result)


class TestNodeResultToDict:
    def test_primitive_passthrough(self):
        d = _mk({"k": [1, "two", None]}).to_dict()
        assert d["result"] == {"k": [1, "two", None]}
        assert d["node_id"] == "a1" and d["agent_id"] == "a1"
        json.dumps(d)  # JSON-safe without default=str

    def test_timestamp_isoformat(self):
        d = _mk("ok").to_dict()
        assert isinstance(d["timestamp"], str) and "T" in d["timestamp"]

    def test_dataframe_bounded_preview(self):
        pd = pytest.importorskip("pandas")
        df = pd.DataFrame({"x": range(100)})
        d = _mk(df).to_dict()
        assert isinstance(d["result"], str) and "100" in d["result"]

    def test_arbitrary_object_fallback(self):
        class Weird:
            def __repr__(self): return "<weird>"
        d = _mk(Weird()).to_dict()
        assert d["result"] == "<weird>"

    def test_ai_message_excluded(self):
        r = _mk("ok"); r.ai_message = object()
        assert "ai_message" not in r.to_dict()
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/crew-per-agent-result-persistence.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1765-noderesult-to-dict.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-14
**Notes**: Added `_serialise_result_value()` module-level helper and
`NodeResult.to_dict()` in `result.py`, following the `to_text()` lazy
pandas-import pattern. 8 unit tests added in
`tests/bots/flows/core/test_result_serialisation.py`, all passing.
`ruff check` clean.

**Deviations from spec**: none
