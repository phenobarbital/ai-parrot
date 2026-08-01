# TASK-2024: Guardrails Core — Stages, Verdicts, ABC, Context, and Streaming Contract

**Feature**: FEAT-396 — Unified Guardrails Infrastructure
**Spec**: `sdd/specs/guardrails-infrastructure.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundation task for FEAT-396. It creates the
`parrot/bots/guardrails/` subpackage and defines the core data models,
enums, the `Guardrail` ABC, the `GuardrailContext` carrier, and the
`StreamingGuardrail` adapter contract. Every subsequent task in this
feature depends on these types.

Implements: Spec §2 (Data Models), §3 Module 1 (partial — models only).

---

## Scope

- Create `parrot/bots/guardrails/__init__.py` with public exports.
- Create `parrot/bots/guardrails/base.py`:
  - `GuardrailStage` enum (INPUT, TOOL_OUTPUT, OUTPUT, OUTPUT_STREAM).
  - `GuardrailAction` enum (PASS, TRANSFORM, FLAG, BLOCK).
  - `GuardrailResult` Pydantic model (action, content, report, reason).
  - `GuardrailContext` Pydantic model (stage, agent_name, user_id,
    session_id, method, tool_name, extras).
  - `Guardrail` ABC with: `name`, `stages`, `priority` (default bands:
    sanitizers 0–99, transformers 100–199, observers 200+), `on_error`
    (`fail_open`/`fail_closed`), abstract `async check(content, ctx) →
    GuardrailResult`.
- Create `parrot/bots/guardrails/streaming.py`:
  - `StreamingGuardrail` ABC with `feed(chunk) → str` and `flush() → str`.
- Write unit tests for all models and enums.

**NOT in scope**: pipeline execution logic (TASK-2025), registry/config
(TASK-2026), built-in plugins (TASK-2027–2030).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/guardrails/__init__.py` | CREATE | Package init with public exports |
| `parrot/bots/guardrails/base.py` | CREATE | Enums, result model, context model, Guardrail ABC |
| `parrot/bots/guardrails/streaming.py` | CREATE | StreamingGuardrail ABC |
| `tests/unit/test_guardrails_core_models.py` | CREATE | Unit tests for all models/enums/ABCs |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field       # already a core dependency
from abc import ABC, abstractmethod         # stdlib
from enum import Enum                       # stdlib
from typing import Optional, Literal        # stdlib
```

### Existing Signatures to Use
```python
# No existing guardrails code — this task creates the foundation.
# Structural sibling: parrot/bots/mixins/ (packaging convention)
```

### Does NOT Exist
- ~~`parrot.bots.guardrails`~~ — created by this task
- ~~`GuardrailStage` / `GuardrailAction` / `Guardrail`~~ — created by this task
- ~~Any existing guardrails abstraction in the repo~~ — only provider
  params in `clients/bedrock.py:79-80,444`

---

## Implementation Notes

### Pattern to Follow
```python
# Follow the Pydantic + Enum pattern used throughout parrot:
class GuardrailStage(str, Enum):
    INPUT = "input"
    TOOL_OUTPUT = "tool_output"
    OUTPUT = "output"
    OUTPUT_STREAM = "output_stream"

class Guardrail(ABC):
    name: str
    stages: set[GuardrailStage]
    priority: int
    on_error: Literal["fail_open", "fail_closed"] = "fail_open"

    @abstractmethod
    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult: ...
```

### Key Constraints
- Pydantic models for `GuardrailResult` and `GuardrailContext`.
- `Guardrail` itself is an ABC (not Pydantic) — it carries config
  attributes and an async `check()` method.
- Priority default bands: sanitizers 0–99, transformers 100–199,
  observers 200+. Document in docstring.
- `StreamingGuardrail.feed()` returns `""` while withholding (buffering).
- Strict type hints throughout; Google-style docstrings.

---

## Acceptance Criteria

- [ ] `parrot/bots/guardrails/` package importable
- [ ] All enums, models, ABCs match spec §2 data models exactly
- [ ] `GuardrailResult` validates action/content/report/reason constraints
- [ ] `StreamingGuardrail` ABC defines `feed()` and `flush()`
- [ ] All tests pass: `pytest tests/unit/test_guardrails_core_models.py -v`
- [ ] No linting errors: `ruff check parrot/bots/guardrails/`
- [ ] Imports work: `from parrot.bots.guardrails import Guardrail, GuardrailStage, GuardrailAction, GuardrailResult, GuardrailContext, StreamingGuardrail`

---

## Test Specification

```python
# tests/unit/test_guardrails_core_models.py
import pytest
from parrot.bots.guardrails.base import (
    GuardrailStage, GuardrailAction, GuardrailResult, GuardrailContext, Guardrail,
)
from parrot.bots.guardrails.streaming import StreamingGuardrail


class TestGuardrailStage:
    def test_enum_values(self):
        assert GuardrailStage.INPUT == "input"
        assert GuardrailStage.TOOL_OUTPUT == "tool_output"
        assert GuardrailStage.OUTPUT == "output"
        assert GuardrailStage.OUTPUT_STREAM == "output_stream"


class TestGuardrailAction:
    def test_enum_values(self):
        assert GuardrailAction.PASS == "pass"
        assert GuardrailAction.BLOCK == "block"


class TestGuardrailResult:
    def test_pass_result(self):
        r = GuardrailResult(action=GuardrailAction.PASS)
        assert r.content is None

    def test_transform_result(self):
        r = GuardrailResult(action=GuardrailAction.TRANSFORM, content="cleaned")
        assert r.content == "cleaned"

    def test_flag_result(self):
        r = GuardrailResult(action=GuardrailAction.FLAG, report={"score": 0.5})
        assert r.report["score"] == 0.5

    def test_block_result(self):
        r = GuardrailResult(action=GuardrailAction.BLOCK, reason="injection_detected")
        assert r.reason == "injection_detected"


class TestGuardrailContext:
    def test_minimal_context(self):
        ctx = GuardrailContext(stage=GuardrailStage.INPUT, agent_name="test")
        assert ctx.method == ""
        assert ctx.tool_name is None


class TestGuardrailABC:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            Guardrail()


class TestStreamingGuardrailABC:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            StreamingGuardrail()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/guardrails-infrastructure.spec.md` §2
2. **Check dependencies** — none; this is the first task
3. **Verify the Codebase Contract** — confirm `parrot/bots/guardrails/` does not exist yet
4. **Update status** in `sdd/tasks/index/guardrails-infrastructure.json` → `"in-progress"`
5. **Implement** following the scope and models above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2024-guardrails-core-models.md`
8. **Update index** → `"done"`

---

## Completion Note

Implemented exactly as scoped: `parrot/bots/guardrails/base.py` (`GuardrailStage`,
`GuardrailAction`, `GuardrailResult`, `GuardrailContext`, `Guardrail` ABC),
`parrot/bots/guardrails/streaming.py` (`StreamingGuardrail` ABC), and
`parrot/bots/guardrails/__init__.py` re-exporting all six public names. No
pipeline/registry/plugin logic added (out of scope for this task).

13 unit tests added in `tests/unit/test_guardrails_core_models.py`, all
passing (`pytest packages/ai-parrot/tests/unit/test_guardrails_core_models.py -v`).
`ruff check parrot/bots/guardrails/` clean (post `--fix` + manual `ClassVar`
annotations on two ad-hoc test-only Guardrail subclasses to satisfy RUF012).

Worktree note: the compiled Cython `.so` extensions (`parrot.utils.types`,
`parrot.utils.parsers.toml`, `parrot.yaml_rs`) are gitignored build
artifacts not present in a fresh worktree checkout; they were copied from
the main repo's `.venv`-matching build (cpython-311) to make `import parrot`
resolve locally for testing. No source files were touched by this — purely
a local test-environment workaround, not part of the commit.
