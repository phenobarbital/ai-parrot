# TASK-2025: Guardrails Pipeline — Ordered Execution, BLOCK Short-Circuit, Error Contract, Telemetry

**Feature**: FEAT-396 — Unified Guardrails Infrastructure
**Spec**: `sdd/specs/guardrails-infrastructure.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2024
**Assigned-to**: unassigned

---

## Context

The `GuardrailPipeline` is the execution engine that runs guardrails in
priority order, handles BLOCK short-circuit, accumulates FLAG reports,
enforces per-guardrail error contracts (`fail_open`/`fail_closed`), stamps
processed content for idempotency, and emits telemetry. This is the core
runtime for all four stages.

Implements: Spec §2 (pipeline behavior), §3 Module 1 (pipeline.py).

---

## Scope

- Create `parrot/bots/guardrails/pipeline.py`:
  - `PipelineOutcome` model: final content, blocked flag + reason,
    accumulated flag reports dict, list of telemetry entries.
  - `GuardrailPipeline` class:
    - `add(guardrail)` — insert sorted by priority.
    - `has_guardrails` property — empty pipeline short-circuits.
    - `async run(content, ctx) → PipelineOutcome`:
      - Execute guardrails in priority order (lower first).
      - BLOCK short-circuits: discard prior TRANSFORMs, return canned
        blocked outcome with reason.
      - TRANSFORM: replace content for subsequent guardrails.
      - FLAG: accumulate reports under guardrail name.
      - PASS: continue.
      - Per-guardrail exception handling: `fail_open` → log warning,
        continue; `fail_closed` → convert to BLOCK.
      - Idempotency stamping: processed-content marker prevents double
        transformation (follows `_already_scrubbed` precedent).
      - Telemetry: record (guardrail name, stage, action, duration_ms)
        per guardrail; emit via FEAT-176 observers if available.
- Write comprehensive unit tests.

**NOT in scope**: registry/config coercion (TASK-2026), built-in plugins
(TASK-2027–2030), bot wiring.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/guardrails/pipeline.py` | CREATE | Pipeline execution engine |
| `parrot/bots/guardrails/__init__.py` | MODIFY | Add pipeline exports |
| `tests/unit/test_guardrails_pipeline.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# From TASK-2024 (created in this feature):
from parrot.bots.guardrails.base import (
    Guardrail, GuardrailStage, GuardrailAction,
    GuardrailResult, GuardrailContext,
)

# Idempotency precedent:
from parrot.security.redaction import _already_scrubbed  # security/redaction.py:122

# Logging:
import logging
```

### Existing Signatures to Use
```python
# security/redaction.py:122
def _already_scrubbed(text: str) -> bool:
    ...

# Guardrail ABC (created by TASK-2024):
# parrot/bots/guardrails/base.py
class Guardrail(ABC):
    name: str
    stages: set[GuardrailStage]
    priority: int
    on_error: Literal["fail_open", "fail_closed"]
    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult: ...
```

### Does NOT Exist
- ~~`GuardrailPipeline`~~ — created by this task
- ~~`PipelineOutcome`~~ — created by this task
- ~~Any existing output chain or response pipeline~~ — `PromptPipeline`
  is input-only (`bots/middleware.py:23`)
- ~~Blocking semantics in `PromptPipeline`~~ — exceptions swallowed
  (`middleware.py:42-45`)

---

## Implementation Notes

### Pattern to Follow
```python
class GuardrailPipeline:
    def __init__(self):
        self._guardrails: list[Guardrail] = []

    def add(self, guardrail: Guardrail) -> None:
        self._guardrails.append(guardrail)
        self._guardrails.sort(key=lambda g: g.priority)

    @property
    def has_guardrails(self) -> bool:
        return len(self._guardrails) > 0

    async def run(self, content: str, ctx: GuardrailContext) -> PipelineOutcome:
        # Priority-ordered; BLOCK short-circuits; per-guardrail try/except
        ...
```

### Key Constraints
- BLOCK discards prior TRANSFORMs — the outcome carries the canned
  reason, never the offending content.
- FLAG reports accumulate as `dict[str, dict]` keyed by guardrail name.
- Telemetry entries: (name, stage, action, duration_ms) — **never content**.
- Empty pipeline (`not has_guardrails`) returns immediately with
  unmodified content — zero overhead.
- Idempotency: implement a content-stamping mechanism similar to
  `_already_scrubbed` to prevent double transformation.

---

## Acceptance Criteria

- [ ] `GuardrailPipeline` executes guardrails in priority order
- [ ] BLOCK short-circuits the chain and discards prior TRANSFORMs
- [ ] `fail_open` → warn + continue; `fail_closed` → BLOCK
- [ ] Multiple FLAG reports accumulate under distinct guardrail names
- [ ] Idempotency stamping prevents double transformation
- [ ] Empty pipeline returns immediately with no overhead
- [ ] Telemetry entries carry name/stage/action/duration, never content
- [ ] All tests pass: `pytest tests/unit/test_guardrails_pipeline.py -v`
- [ ] No linting errors: `ruff check parrot/bots/guardrails/`

---

## Test Specification

```python
# tests/unit/test_guardrails_pipeline.py
import pytest
from parrot.bots.guardrails.base import (
    Guardrail, GuardrailStage, GuardrailAction,
    GuardrailResult, GuardrailContext,
)
from parrot.bots.guardrails.pipeline import GuardrailPipeline


# Stub guardrails for testing
class PassGuardrail(Guardrail):
    name = "pass_guard"
    stages = {GuardrailStage.INPUT}
    priority = 100
    on_error = "fail_open"
    async def check(self, content, ctx):
        return GuardrailResult(action=GuardrailAction.PASS)


class TransformGuardrail(Guardrail):
    name = "transform_guard"
    stages = {GuardrailStage.INPUT}
    priority = 50
    on_error = "fail_open"
    async def check(self, content, ctx):
        return GuardrailResult(action=GuardrailAction.TRANSFORM, content=content.upper())


class BlockGuardrail(Guardrail):
    name = "block_guard"
    stages = {GuardrailStage.INPUT}
    priority = 10
    on_error = "fail_closed"
    async def check(self, content, ctx):
        return GuardrailResult(action=GuardrailAction.BLOCK, reason="blocked")


class FlagGuardrail(Guardrail):
    name = "flag_guard"
    stages = {GuardrailStage.OUTPUT}
    priority = 200
    on_error = "fail_open"
    async def check(self, content, ctx):
        return GuardrailResult(action=GuardrailAction.FLAG, report={"score": 0.9})


class RaisingGuardrail(Guardrail):
    name = "raises"
    stages = {GuardrailStage.INPUT}
    priority = 50
    on_error = "fail_open"
    async def check(self, content, ctx):
        raise RuntimeError("boom")


@pytest.fixture
def ctx():
    return GuardrailContext(stage=GuardrailStage.INPUT, agent_name="test")


class TestPipelineOrdering:
    @pytest.mark.asyncio
    async def test_priority_order(self, ctx):
        pipeline = GuardrailPipeline()
        pipeline.add(PassGuardrail())
        pipeline.add(TransformGuardrail())
        outcome = await pipeline.run("hello", ctx)
        assert outcome.content == "HELLO"


class TestPipelineBlock:
    @pytest.mark.asyncio
    async def test_block_shortcircuits(self, ctx):
        pipeline = GuardrailPipeline()
        pipeline.add(BlockGuardrail())
        pipeline.add(TransformGuardrail())
        outcome = await pipeline.run("hello", ctx)
        assert outcome.blocked is True
        assert outcome.content != "HELLO"


class TestPipelineErrorContract:
    @pytest.mark.asyncio
    async def test_fail_open_continues(self, ctx):
        pipeline = GuardrailPipeline()
        pipeline.add(RaisingGuardrail())
        pipeline.add(PassGuardrail())
        outcome = await pipeline.run("hello", ctx)
        assert outcome.blocked is False

    @pytest.mark.asyncio
    async def test_fail_closed_blocks(self, ctx):
        g = RaisingGuardrail()
        g.on_error = "fail_closed"
        pipeline = GuardrailPipeline()
        pipeline.add(g)
        outcome = await pipeline.run("hello", ctx)
        assert outcome.blocked is True


class TestPipelineFlagAccumulation:
    @pytest.mark.asyncio
    async def test_flags_accumulate(self):
        ctx = GuardrailContext(stage=GuardrailStage.OUTPUT, agent_name="test")
        pipeline = GuardrailPipeline()
        pipeline.add(FlagGuardrail())
        outcome = await pipeline.run("text", ctx)
        assert "flag_guard" in outcome.flag_reports


class TestPipelineIdempotency:
    @pytest.mark.asyncio
    async def test_double_run_idempotent(self, ctx):
        pipeline = GuardrailPipeline()
        pipeline.add(TransformGuardrail())
        outcome1 = await pipeline.run("hello", ctx)
        outcome2 = await pipeline.run(outcome1.content, ctx)
        assert outcome1.content == outcome2.content


class TestPipelineEmpty:
    @pytest.mark.asyncio
    async def test_empty_no_overhead(self, ctx):
        pipeline = GuardrailPipeline()
        assert not pipeline.has_guardrails
        outcome = await pipeline.run("hello", ctx)
        assert outcome.content == "hello"
        assert outcome.blocked is False
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/guardrails-infrastructure.spec.md` §2
2. **Check dependencies** — TASK-2024 must be in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm TASK-2024 types exist
4. **Update status** in `sdd/tasks/index/guardrails-infrastructure.json` → `"in-progress"`
5. **Implement** following the scope above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2025-guardrails-pipeline.md`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
