# TASK-2030: ModerationGuardrail — Reference Interface + Stub Backend

**Feature**: FEAT-396 — Unified Guardrails Infrastructure
**Spec**: `sdd/specs/guardrails-infrastructure.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2024, TASK-2025, TASK-2026
**Assigned-to**: unassigned

---

## Context

This task creates the `ModerationGuardrail` reference interface with a
stub backend. The goal is to prove that the guardrails infrastructure
supports content moderation as a first-class plugin — concrete backends
(OpenAI moderation API, local classifiers, keyword lists) are explicit
follow-ups, not part of this feature.

Implements: Spec §3 Module 4 (`guardrails-moderation-reference`).

---

## Scope

- Create `parrot/bots/guardrails/builtin/moderation.py`:
  - `ModerationPolicy(BaseModel)`:
    - `categories: list[str]` — moderation categories to check.
    - `threshold: float = 0.8` — score above which action triggers.
    - `action: Literal["flag", "block"] = "flag"` — default is observe.
  - `ModerationBackend(Protocol)`:
    - `async def classify(self, text: str) -> dict[str, float]` — returns
      category → score mapping.
  - `StubModerationBackend`:
    - Always returns `{}` (allow-all). Logs the call shape for testing.
  - `ModerationGuardrail(Guardrail)`:
    - `name = "moderation"`
    - `stages = {GuardrailStage.INPUT, GuardrailStage.OUTPUT}`
    - `priority = 50` (sanitizer band, after prompt injection)
    - `on_error`: `"fail_closed"` when `action="block"`, else `"fail_open"`
    - Config: accepts `ModerationPolicy` + `ModerationBackend`.
    - `async check(content, ctx) → GuardrailResult`:
      - Calls `backend.classify(content)`.
      - Compares scores to policy threshold per category.
      - Returns FLAG (with report) or BLOCK depending on `policy.action`.
      - Returns PASS if no category exceeds threshold.
- Register `"moderation"` in the guardrail registry.
- Document in module docstring that concrete backends are follow-ups.
- Write unit tests against the stub backend.

**NOT in scope**: concrete moderation backends, keyword-list filtering,
OpenAI moderation API integration, external service calls.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/guardrails/builtin/moderation.py` | CREATE | ModerationGuardrail + Protocol + Stub |
| `parrot/bots/guardrails/registry.py` | MODIFY | Register `"moderation"` factory |
| `tests/unit/test_guardrails_moderation.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Guardrails core (from TASK-2024):
from parrot.bots.guardrails.base import (
    Guardrail, GuardrailStage, GuardrailAction,
    GuardrailResult, GuardrailContext,
)

# Pydantic + typing:
from pydantic import BaseModel, Field
from typing import Protocol, Literal
```

### Existing Signatures to Use
```python
# Guardrail ABC (from TASK-2024):
class Guardrail(ABC):
    name: str
    stages: set[GuardrailStage]
    priority: int
    on_error: Literal["fail_open", "fail_closed"]
    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult: ...
```

### Does NOT Exist
- ~~Content-moderation code in the repo~~ — all `moderate` hits are
  `SecurityLevel.MODERATE` in command/python sanitizers; no toxicity or
  content_filter anywhere
- ~~`ModerationGuardrail`~~ — created by this task
- ~~`ModerationBackend`~~ — created by this task
- ~~Any OpenAI moderation API integration~~ — explicit follow-up
- ~~Any keyword-list or classifier-based moderation~~ — explicit follow-up

---

## Implementation Notes

### Pattern to Follow
```python
class ModerationBackend(Protocol):
    async def classify(self, text: str) -> dict[str, float]:
        """Return {category: score} for the input text."""
        ...

class StubModerationBackend:
    """Allow-all reference backend. Logs call shape for testing."""
    async def classify(self, text: str) -> dict[str, float]:
        return {}

class ModerationGuardrail(Guardrail):
    name = "moderation"
    stages = {GuardrailStage.INPUT, GuardrailStage.OUTPUT}
    priority = 50

    def __init__(self, policy: ModerationPolicy | None = None,
                 backend: ModerationBackend | None = None):
        self.policy = policy or ModerationPolicy()
        self.backend = backend or StubModerationBackend()
        self.on_error = "fail_closed" if self.policy.action == "block" else "fail_open"
```

### Key Constraints
- The stub backend is intentionally trivial — it exists to prove the
  interface works, not to provide real moderation.
- `ModerationPolicy` is a Pydantic model (like `GroundednessPolicy`
  and `ScrubPolicy` precedents).
- The module docstring must explicitly state that concrete backends are
  follow-up features.
- No new runtime dependencies.

---

## Acceptance Criteria

- [ ] `ModerationGuardrail` implements `Guardrail` ABC
- [ ] `ModerationBackend` protocol defines `classify()` method
- [ ] `StubModerationBackend` returns `{}` (allow-all)
- [ ] Policy threshold/action logic correct: scores above threshold →
      FLAG or BLOCK based on `policy.action`
- [ ] Registered as `"moderation"` in the guardrail registry
- [ ] Module docstring documents backends as follow-ups
- [ ] All tests pass: `pytest tests/unit/test_guardrails_moderation.py -v`
- [ ] No linting errors
- [ ] No new runtime dependencies

---

## Test Specification

```python
# tests/unit/test_guardrails_moderation.py
import pytest
from parrot.bots.guardrails.builtin.moderation import (
    ModerationGuardrail, ModerationPolicy, StubModerationBackend,
    ModerationBackend,
)
from parrot.bots.guardrails.base import (
    GuardrailStage, GuardrailAction, GuardrailContext,
)


@pytest.fixture
def ctx():
    return GuardrailContext(stage=GuardrailStage.INPUT, agent_name="test")


class TestStubBackend:
    @pytest.mark.asyncio
    async def test_allow_all(self):
        backend = StubModerationBackend()
        result = await backend.classify("any text")
        assert result == {}


class TestModerationPolicy:
    def test_defaults(self):
        policy = ModerationPolicy()
        assert policy.threshold == 0.8
        assert policy.action == "flag"


class TestModerationGuardrail:
    @pytest.mark.asyncio
    async def test_stub_passes_everything(self, ctx):
        guardrail = ModerationGuardrail()
        result = await guardrail.check("hello", ctx)
        assert result.action == GuardrailAction.PASS

    @pytest.mark.asyncio
    async def test_flag_on_threshold(self, ctx):
        class MockBackend:
            async def classify(self, text):
                return {"hate": 0.9}
        guardrail = ModerationGuardrail(
            policy=ModerationPolicy(categories=["hate"], action="flag"),
            backend=MockBackend(),
        )
        result = await guardrail.check("hateful content", ctx)
        assert result.action == GuardrailAction.FLAG
        assert "hate" in result.report

    @pytest.mark.asyncio
    async def test_block_on_threshold(self, ctx):
        class MockBackend:
            async def classify(self, text):
                return {"violence": 0.95}
        guardrail = ModerationGuardrail(
            policy=ModerationPolicy(categories=["violence"], action="block", threshold=0.9),
            backend=MockBackend(),
        )
        result = await guardrail.check("violent content", ctx)
        assert result.action == GuardrailAction.BLOCK
        assert result.reason is not None

    @pytest.mark.asyncio
    async def test_below_threshold_passes(self, ctx):
        class MockBackend:
            async def classify(self, text):
                return {"hate": 0.3}
        guardrail = ModerationGuardrail(
            policy=ModerationPolicy(categories=["hate"], threshold=0.8),
            backend=MockBackend(),
        )
        result = await guardrail.check("mild text", ctx)
        assert result.action == GuardrailAction.PASS

    def test_on_error_depends_on_action(self):
        g_flag = ModerationGuardrail(policy=ModerationPolicy(action="flag"))
        assert g_flag.on_error == "fail_open"
        g_block = ModerationGuardrail(policy=ModerationPolicy(action="block"))
        assert g_block.on_error == "fail_closed"


class TestRegistration:
    def test_registered(self):
        from parrot.bots.guardrails.registry import build_guardrails
        # Factory exists (may use stub backend by default)
        guardrails = build_guardrails(["moderation"])
        assert len(guardrails) == 1
        assert guardrails[0].name == "moderation"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §2 (data models), §3 Module 4
2. **Check dependencies** — TASK-2024, 2025, 2026 must be completed
3. **Verify the Codebase Contract** — confirm no existing moderation code
4. **Implement** following the scope above
5. **Verify** all acceptance criteria
6. **Move + update index** → `"done"`

---

## Completion Note

Implemented `builtin/moderation.py` exactly per scope: `ModerationPolicy`
(Pydantic model — `categories: list[str]`, `threshold: float = 0.8`,
`action: Literal["flag","block"] = "flag"`, validated via a `pattern`
constraint), `ModerationBackend` (`Protocol` with `async classify(text) ->
dict[str, float]`), `StubModerationBackend` (always returns `{}`, logs
call shape by length only — never content), `ModerationGuardrail`
(`name="moderation"`, `stages={INPUT, OUTPUT}`, `priority=50`, `on_error`
= `fail_closed` iff `policy.action=="block"`). `check()` calls
`backend.classify(content)`, filters scores to only categories present in
`policy.categories` (a backend may legitimately return categories the
policy doesn't track — those are ignored, covered by
`test_category_not_in_policy_is_ignored`), compares against
`policy.threshold`, and returns PASS / FLAG (report = triggered
category→score dict) / BLOCK (reason = `"moderation:<sorted,categories>"`,
never content) per `policy.action`.

`registry.py` needed no modification — TASK-2026 already pre-registered
`"moderation"` via a lazy factory pointing at this exact module/class path,
the same pattern already established by TASK-2027 (`prompt_injection`) and
TASK-2029 (`secrets`).

14 tests added (stub backend allow-all, policy defaults + validation,
name/priority/stages, default-backend-is-stub, PASS/FLAG/BLOCK paths,
category-filtering, multi-category report, `on_error` selection,
registry resolution by name and by policy dict) — all passing together
with TASK-2024-2029 (126 total across the full guardrails + FEAT-252
containment suites). `ruff check parrot/bots/guardrails/` clean. No new
runtime dependencies (Pydantic + stdlib `typing.Protocol` only, both
already core deps).

This closes FEAT-396 — all 7 tasks (TASK-2024 through TASK-2030) are
now `"done"`.
