# TASK-2028: Input Migration — Replace _sanitize_question + PromptPipeline with INPUT Pipeline

**Feature**: FEAT-396 — Unified Guardrails Infrastructure
**Spec**: `sdd/specs/guardrails-infrastructure.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-2024, TASK-2025, TASK-2026, TASK-2027
**Assigned-to**: unassigned

---

## Context

This is the highest-risk task in FEAT-396. It replaces the three
`_sanitize_question` call sites and `PromptPipeline` invocations in
`BaseBot` with the INPUT `GuardrailPipeline`, and removes the eager
pytector loading from `AbstractBot.__init__`. The `_sanitize_question`
method body has already moved into `PromptInjectionGuardrail`
(TASK-2027); this task handles the seam wiring and cleanup.

Two invariants are non-negotiable:
1. Sanitized/transformed text binds only to `prompt_for_llm` — the
   canonical `question` stays clean for memory/events/vector retrieval.
2. BLOCK produces the same canned `AIMessage`/string shapes the
   injection path produces today.

Also wraps existing `PromptPipeline` middlewares as a legacy TRANSFORM
guardrail and migrates the two registration sites.

Implements: Spec §3 Module 2 (wiring), completing `guardrails-input-migration`.

---

## Scope

- Modify `parrot/bots/base.py`:
  - Replace the three `_sanitize_question` + catch blocks
    (`:625/632`, `:997/1004`, `:1641/1648`) with INPUT pipeline
    invocation via `self._guardrail_pipelines[GuardrailStage.INPUT].run()`.
  - Preserve the `prompt_for_llm` invariant: pipeline output binds to
    `prompt_for_llm`, not to `question`.
  - Preserve canned `AIMessage`/string responses on BLOCK (same shapes
    as current `PromptInjectionException` catches).
  - Replace the three `PromptPipeline` invocations (`:641`, `:1017`,
    `:1657`) — they fold into the INPUT pipeline via a legacy wrapper.
  - Fix the `ask_stream` context `method:'ask'` copy-paste near `:1663`
    → `method:'ask_stream'`.
- Modify `parrot/bots/abstract.py`:
  - Remove `PYTECTOR_ENABLED` constant (`:63`) and
    `_get_shared_injection_detector()` (`:78-95`) — moved to the plugin.
  - Remove the eager detector loading block (`:675-684`).
  - Remove `self._framework_sanitizer` and `self._injection_detector`
    assignments (`:672-684`).
  - Keep `_sanitize_question` as a thin delegate (calls INPUT pipeline)
    for any external callers, marked `@deprecated`.
  - Keep `self._prompt_pipeline` property for compat — wrap as a legacy
    TRANSFORM guardrail added to the INPUT pipeline.
- Create `parrot/bots/guardrails/builtin/legacy_pipeline.py`:
  - `LegacyPipelineGuardrail(Guardrail)` — wraps a `PromptPipeline`
    as a TRANSFORM guardrail on INPUT stage, priority 150 (transformer
    band). Delegates to `PromptPipeline.apply()`.
- Migrate the two `PromptPipeline` registration sites:
  - `bots/search.py:120-122` → register through guardrails config or
    legacy wrapper.
  - `skills/mixin.py:179-185` → same.
- Write behavioral-compat golden tests (captured BEFORE touching seams).
- Write integration tests for the full INPUT pipeline path.

**NOT in scope**: output seams (TASK-2029), moderation (TASK-2030).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/base.py` | MODIFY | Replace 3 input sites + 3 pipeline sites |
| `parrot/bots/abstract.py` | MODIFY | Remove eager pytector load, keep thin compat |
| `parrot/bots/guardrails/builtin/legacy_pipeline.py` | CREATE | PromptPipeline wrapper |
| `parrot/bots/search.py` | MODIFY | Migrate pipeline registration |
| `parrot/skills/mixin.py` | MODIFY | Migrate pipeline registration |
| `tests/unit/test_guardrails_input_migration.py` | CREATE | Behavioral compat + integration |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# bots/base.py:23
from ..security import PromptInjectionException

# bots/abstract.py:63,78
PYTECTOR_ENABLED = importlib.util.find_spec("pytector") is not None
def _get_shared_injection_detector(): ...

# bots/middleware.py:23,8
from parrot.bots.middleware import PromptPipeline, PromptMiddleware
```

### Existing Signatures to Use
```python
# bots/base.py — input sites (3 pairs: sanitize + catch):
#   invoke: _sanitize_question :625 / PromptInjectionException catch :632
#   ask:    _sanitize_question :997 / catch :1004
#   ask_stream: _sanitize_question :1641 / catch :1648
# PromptPipeline runs:
#   invoke: :641 / ask: :1017 / ask_stream: :1657

# bots/abstract.py — detector loading to remove:
#   PYTECTOR_ENABLED :63
#   _get_shared_injection_detector() :78-95
#   self._framework_sanitizer :672-674
#   if PYTECTOR_ENABLED: self._injection_detector :675-684

# bots/abstract.py — _sanitize_question to keep as delegate:
#   :1836-1942

# bots/search.py — PromptPipeline registration:
#   :120-122

# skills/mixin.py — PromptPipeline registration:
#   :179-185

# bots/abstract.py — _prompt_pipeline property:
#   :716-720 (getter/setter)

# Channel egress scrub singleton:
#   bots/base.py:60-61 (_BOT_EGRESS_SCRUBBER)
#   bots/base.py:1442-1445 (applied to 4 chat modes only)
```

### Does NOT Exist
- ~~`LegacyPipelineGuardrail`~~ — created by this task
- ~~Any existing guardrails wiring in BaseBot~~ — `_guardrail_pipelines`
  was added to AbstractBot.__init__ by TASK-2026 but not yet used in seams
- ~~`method: 'ask_stream'` context~~ — currently hardcoded as `'ask'`
  near `:1663` (known bug, fixed in this task)

---

## Implementation Notes

### Golden Test Strategy
Before modifying ANY seam, capture golden outputs:
```python
# For each of invoke/ask/ask_stream:
# 1. Clean input → expected response (no guardrail modification)
# 2. Injection input → expected canned AIMessage (blocked)
# 3. Input with PromptPipeline middleware → expected transform
```
Then assert the new pipeline produces identical results.

### Key Constraints
- **`prompt_for_llm` invariant**: the canonical `question` variable
  must NEVER be overwritten by guardrail output — only `prompt_for_llm`
  receives the transformed content. Memory, events, and vector retrieval
  read `question`.
- **Canned response shapes**: BLOCK must produce the exact same
  `AIMessage` structure as today's `PromptInjectionException` catches
  (`:632`, `:1004`, `:1648`).
- **`_sanitize_question` kept as thin delegate**: external code or
  subclasses may call it; keep the method but internally delegate to
  the INPUT pipeline.
- **`_prompt_pipeline` property kept**: the getter/setter at `:716-720`
  stays for compat; setting it wraps the pipeline as a
  `LegacyPipelineGuardrail` into the INPUT pipeline.

### References in Codebase
- `bots/base.py:625-650` — invoke input path
- `bots/base.py:997-1020` — ask input path
- `bots/base.py:1641-1665` — ask_stream input path
- `bots/abstract.py:1836-1942` — _sanitize_question (now delegated)

---

## Acceptance Criteria

- [ ] Three `_sanitize_question` call sites replaced with INPUT pipeline
- [ ] Three `PromptPipeline` invocations folded into INPUT pipeline
- [ ] `prompt_for_llm` invariant preserved (golden tests)
- [ ] BLOCK produces identical canned `AIMessage` shapes (golden tests)
- [ ] `PYTECTOR_ENABLED` and eager detector loading removed from `abstract.py`
- [ ] `_sanitize_question` kept as thin delegate, marked deprecated
- [ ] `_prompt_pipeline` property kept, wraps as legacy guardrail
- [ ] Both `PromptPipeline` registration sites migrated
- [ ] `ask_stream` method context fixed from `'ask'` to `'ask_stream'`
- [ ] Importing `BasicAgent` with `injection_detection=False` does NOT
      load pytector/torch/transformers/TF
- [ ] Existing test suite passes unchanged with default config
- [ ] All new tests pass
- [ ] No linting errors

---

## Test Specification

```python
# tests/unit/test_guardrails_input_migration.py
import pytest
from unittest.mock import AsyncMock, patch

# Golden tests: capture behavior BEFORE migration, assert AFTER
class TestInvokeInputGolden:
    @pytest.mark.asyncio
    async def test_clean_input_unchanged(self):
        """invoke() with clean input produces same response."""
        ...

    @pytest.mark.asyncio
    async def test_blocked_input_canned_response(self):
        """invoke() with injection input produces same canned AIMessage."""
        ...

class TestAskInputGolden:
    @pytest.mark.asyncio
    async def test_clean_input_unchanged(self):
        ...

    @pytest.mark.asyncio
    async def test_blocked_input_canned_response(self):
        ...

class TestAskStreamInputGolden:
    @pytest.mark.asyncio
    async def test_clean_input_unchanged(self):
        ...

    @pytest.mark.asyncio
    async def test_blocked_input_canned_response(self):
        ...

    @pytest.mark.asyncio
    async def test_method_context_is_ask_stream(self):
        """ask_stream passes method='ask_stream', not 'ask'."""
        ...

class TestLegacyPipelineWrapper:
    @pytest.mark.asyncio
    async def test_prompt_pipeline_applied_via_guardrail(self):
        """Existing PromptPipeline middlewares still transform input."""
        ...

class TestPromptForLlmInvariant:
    @pytest.mark.asyncio
    async def test_question_not_modified(self):
        """The canonical question stays clean; only prompt_for_llm changes."""
        ...

class TestLazyImportBoundary:
    def test_basic_agent_no_torch(self):
        """BasicAgent(injection_detection=False) does not import torch."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §2 (seam integration), §3 Module 2, §7 (patterns)
2. **Read** `bots/base.py:620-665, 990-1025, 1635-1670` for the three sites
3. **Read** `bots/abstract.py:63-95, 672-685, 1836-1942` for the code to remove/delegate
4. **BEFORE modifying any seam**: capture golden test outputs
5. **Check dependencies** — TASK-2024–2027 must be completed
6. **Implement** in order: golden captures → LegacyPipelineGuardrail →
   abstract.py cleanup → base.py seam replacement → registration migration
7. **Run full existing test suite** to verify compat
8. **Move + update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
