# TASK-2109: Add `TOOL_CALL` Guardrail Stage

**Feature**: FEAT-406 — PBAC Guardrails
**Spec**: `sdd/specs/pbac-guardrails.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The FEAT-396 guardrails infrastructure defines pipeline stages (INPUT, TOOL_OUTPUT,
OUTPUT, OUTPUT_STREAM) but has no **pre-execution** stage for tool calls. FEAT-406
needs a `TOOL_CALL` stage so that policy-based guardrails can intercept a tool
invocation *before* it executes — before GrantGuard, before ConfirmationGuard, and
before the tool body runs.

This is the foundational task: it adds the enum member and verifies that the
existing `build_pipelines_from_config()` automatically creates a pipeline for it
(it iterates `GuardrailStage`, so adding a member is sufficient). The empty
pipeline must short-circuit with zero overhead.

Implements spec §3 Module 1.

---

## Scope

- Add `TOOL_CALL = "tool_call"` to `GuardrailStage` enum with a docstring line.
- Verify `build_pipelines_from_config()` returns a pipeline keyed to `TOOL_CALL`
  (no code change needed in `config.py` — it iterates the enum at lines 100–102).
- Write unit tests confirming: (a) the member exists, (b) pipelines are built for
  it, (c) an empty TOOL_CALL pipeline short-circuits (`has_guardrails == False`).

**NOT in scope**: the `PBACToolCallGuardrail` itself (TASK-2110), the ToolManager
hook (TASK-2111), or any bot wiring.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/guardrails/base.py` | MODIFY | Add `TOOL_CALL` member to `GuardrailStage` |
| `packages/ai-parrot/tests/bots/guardrails/test_tool_call_stage.py` | CREATE | Unit tests for the new stage |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.guardrails import (          # bots/guardrails/__init__.py:14-25
    GuardrailStage, GuardrailPipeline,
    build_pipelines_from_config,
)
from parrot.bots.guardrails.base import GuardrailStage  # base.py:15
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/guardrails/base.py:15
class GuardrailStage(str, Enum):
    INPUT = "input"                    # line 24
    TOOL_OUTPUT = "tool_output"        # line 25
    OUTPUT = "output"                  # line 26
    OUTPUT_STREAM = "output_stream"    # line 27  ← TOOL_CALL goes here

# packages/ai-parrot/src/parrot/bots/guardrails/config.py:100-102
pipelines: dict[GuardrailStage, GuardrailPipeline] = {
    stage: GuardrailPipeline(on_telemetry=on_telemetry) for stage in GuardrailStage
}

# packages/ai-parrot/src/parrot/bots/guardrails/pipeline.py:122
class GuardrailPipeline:
    @property
    def has_guardrails(self) -> bool        # line 122
    async def run(self, content: str, ctx: GuardrailContext) -> PipelineOutcome  # line 138
    # empty short-circuit at line 149
```

### Does NOT Exist
- ~~`GuardrailStage.TOOL_CALL`~~ — does not exist yet; this task introduces it.
- ~~`GuardrailStage.PRE_EXECUTION`~~ — not a member; use `TOOL_CALL`.

---

## Implementation Notes

### Pattern to Follow
Add the new member after `OUTPUT_STREAM`, with a one-line docstring entry:
```python
class GuardrailStage(str, Enum):
    """...
        TOOL_CALL: Before tool execution; intercepts the call before guards/body.
    """
    INPUT = "input"
    TOOL_OUTPUT = "tool_output"
    OUTPUT = "output"
    OUTPUT_STREAM = "output_stream"
    TOOL_CALL = "tool_call"
```

### Key Constraints
- The enum iteration in `config.py:100-102` means NO changes to `config.py` are
  needed — adding the member is sufficient for a pipeline to be created.
- Existing tests must still pass — the new member must not break any enum
  iteration, serialization, or pipeline resolution in the existing codebase.

### References in Codebase
- `packages/ai-parrot/src/parrot/bots/guardrails/pipeline.py` — empty pipeline short-circuit (line 149)
- `packages/ai-parrot/src/parrot/bots/guardrails/config.py` — pipeline-per-stage (line 100)

---

## Acceptance Criteria

- [ ] `GuardrailStage.TOOL_CALL == "tool_call"` exists
- [ ] `build_pipelines_from_config()` returns a pipeline for `GuardrailStage.TOOL_CALL`
- [ ] Empty TOOL_CALL pipeline has `has_guardrails == False` and short-circuits
- [ ] All existing guardrail tests pass: `pytest packages/ai-parrot/tests/bots/guardrails/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/bots/guardrails/base.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/guardrails/test_tool_call_stage.py
import pytest
from parrot.bots.guardrails import (
    GuardrailStage, build_pipelines_from_config,
)


def test_tool_call_stage_member():
    assert GuardrailStage.TOOL_CALL == "tool_call"
    assert GuardrailStage.TOOL_CALL.value == "tool_call"


def test_build_pipelines_includes_tool_call():
    pipelines = build_pipelines_from_config()
    assert GuardrailStage.TOOL_CALL in pipelines


def test_empty_tool_call_pipeline_zero_overhead():
    pipelines = build_pipelines_from_config()
    pipeline = pipelines[GuardrailStage.TOOL_CALL]
    assert not pipeline.has_guardrails
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** — confirm `GuardrailStage` enum at `base.py:15`
4. **Update status** in `sdd/tasks/index/pbac-guardrails.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2109-tool-call-guardrail-stage.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any
