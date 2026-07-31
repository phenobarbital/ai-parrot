# TASK-2027: PromptInjectionGuardrail — Plugin + Lazy pytector Import

**Feature**: FEAT-396 — Unified Guardrails Infrastructure
**Spec**: `sdd/specs/guardrails-infrastructure.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2024, TASK-2025, TASK-2026
**Assigned-to**: unassigned

---

## Context

This task creates the `PromptInjectionGuardrail` built-in plugin, which
encapsulates the entire `_sanitize_question` flow from `AbstractBot` into
a self-contained INPUT guardrail that can BLOCK.

**Critical constraint — lazy-import of pytector**: The guardrail owns the
`import pytector` / `import torch` boundary. Today `AbstractBot.__init__`
loads the shared detector unconditionally when pytector is installed
(`PYTECTOR_ENABLED`, `bots/abstract.py:63,675`), which pulls in torch,
transformers, and TensorFlow into every bot — even those with
`injection_detection=False`. This task must move that import into the
guardrail itself so it only fires when the guardrail is registered.

Implements: Spec §3 Module 2 (partial — plugin only, not BaseBot wiring).

---

## Scope

- Create `parrot/bots/guardrails/builtin/__init__.py`.
- Create `parrot/bots/guardrails/builtin/prompt_injection.py`:
  - `PromptInjectionGuardrail(Guardrail)`:
    - `name = "prompt_injection"`
    - `stages = {GuardrailStage.INPUT}`
    - `priority = 10` (sanitizer band)
    - `on_error` = `"fail_closed"` when `block_on_threat=True`, else
      `"fail_open"`
    - Config params: `strict_mode`, `block_on_threat`,
      `injection_probability_threshold`.
    - `__init__`: lazy-import pytector here — use `importlib.util.find_spec`
      to detect availability, then import `PromptInjectionDetector` from
      pytector only if available. Use the shared singleton pattern (reuse
      `_get_shared_injection_detector()` or replicate it internally).
    - `async check(content, ctx) → GuardrailResult`:
      - Trusted-source bypass (mirror `_sanitize_question:1862`).
      - Framework-pattern strip via `_ParrotPromptInjectionDetector`.
      - pytector detection if available (lazy-loaded).
      - Native `sanitize()` call.
      - `SecurityEventLogger` logging.
      - Returns BLOCK (with reason, never content) or PASS.
      - If `block_on_threat=False`: returns FLAG with threat info instead
        of BLOCK (the `_wrap_flagged_input` path).
- Register `"prompt_injection"` in the guardrail registry.
- **Do NOT modify `AbstractBot._sanitize_question` yet** — that happens
  in TASK-2028. This task only creates the plugin.
- Write unit tests for the guardrail in isolation.

**NOT in scope**: Removing `_sanitize_question` from AbstractBot
(TASK-2028), BaseBot seam wiring (TASK-2028), `PromptPipeline` wrapping
(TASK-2028).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/guardrails/builtin/__init__.py` | CREATE | Built-in plugins package |
| `parrot/bots/guardrails/builtin/prompt_injection.py` | CREATE | PromptInjectionGuardrail |
| `parrot/bots/guardrails/registry.py` | MODIFY | Register `"prompt_injection"` factory |
| `tests/unit/test_guardrails_prompt_injection.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Engine — reused, not modified:
from parrot.security.prompt_injection import (
    PromptInjectionDetector,      # security/prompt_injection.py:27
    PromptInjectionException,     # :19
    ThreatLevel,                  # :11
    SecurityEventLogger,          # :222
)

# Shared detector singleton (bots/abstract.py:78):
from parrot.bots.abstract import _get_shared_injection_detector

# Guardrails core (from TASK-2024/2025):
from parrot.bots.guardrails.base import (
    Guardrail, GuardrailStage, GuardrailAction,
    GuardrailResult, GuardrailContext,
)

# pytector (lazy — DO NOT import at module level):
# from pytector import PromptInjectionDetector as PytectorDetector
# import torch  ← NEVER at module level
```

### Existing Signatures to Use
```python
# bots/abstract.py:63 — module-level constant (to be removed in TASK-2028):
PYTECTOR_ENABLED = importlib.util.find_spec("pytector") is not None

# bots/abstract.py:78-95 — shared singleton:
def _get_shared_injection_detector():
    # returns a pytector.PromptInjectionDetector instance (cached)

# security/prompt_injection.py:27
class PromptInjectionDetector:
    # regex/keyword engine (NOT pytector)
    def sanitize(self, text: str) -> tuple[str, list]: ...  # :~180

# security/prompt_injection.py:222
class SecurityEventLogger:
    def __init__(self, db_pool=None, logger=None): ...
    async def log_event(self, ...): ...

# bots/abstract.py:1836-1942 — _sanitize_question flow:
#   :1862 — trusted-source bypass
#   :1864 — gate: if not strict_mode or not injection_detection: return
#   :1879 — framework-pattern strip
#   :1883-1900 — pytector detection
#   :1904-1910 — native sanitize()
#   :1911-1925 — security logging
#   :1927-1935 — raise PromptInjectionException if block_on_threat
#   :1937-1942 — _wrap_flagged_input soft mitigation
```

### Does NOT Exist
- ~~`PromptInjectionGuardrail`~~ — created by this task
- ~~`parrot.bots.guardrails.builtin`~~ — created by this task
- ~~Any lazy-import mechanism for pytector~~ — today it is eagerly loaded
  at `abstract.py:675`; this task creates the lazy path

---

## Implementation Notes

### Lazy-Import Pattern
```python
class PromptInjectionGuardrail(Guardrail):
    def __init__(self, strict_mode=True, block_on_threat=False,
                 injection_probability_threshold=0.98, **kwargs):
        ...
        # Lazy: only import pytector when this guardrail is instantiated
        self._pytector_available = importlib.util.find_spec("pytector") is not None
        self._pytector_detector = None
        if self._pytector_available:
            self._pytector_detector = _get_shared_injection_detector()

    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult:
        # Mirror the _sanitize_question flow exactly
        ...
```

### Key Constraints
- The lazy-import boundary is the **critical** deliverable — pytector,
  torch, transformers, TensorFlow MUST NOT load unless this specific
  guardrail is instantiated.
- The `check()` method must produce identical results to
  `_sanitize_question` for the same inputs (golden test validation).
- `on_error` defaults to `"fail_closed"` when `block_on_threat=True`.
- The guardrail is stateless for detection (the shared singleton is safe
  to reuse across bots).

### References in Codebase
- `bots/abstract.py:1836-1942` — the flow being encapsulated
- `bots/abstract.py:64-95` — shared detector singleton
- `security/prompt_injection.py` — engine classes

---

## Acceptance Criteria

- [ ] `PromptInjectionGuardrail` implements `Guardrail` ABC
- [ ] pytector is lazy-imported only when the guardrail is instantiated
- [ ] Without the guardrail registered, importing `parrot.bots` does NOT
      load pytector/torch/transformers/TensorFlow
- [ ] `check()` produces identical BLOCK/FLAG/PASS results as
      `_sanitize_question` for the same inputs
- [ ] Registered as `"prompt_injection"` in the guardrail registry
- [ ] All tests pass: `pytest tests/unit/test_guardrails_prompt_injection.py -v`
- [ ] No linting errors

---

## Test Specification

```python
# tests/unit/test_guardrails_prompt_injection.py
import pytest
from unittest.mock import patch, MagicMock
from parrot.bots.guardrails.base import (
    GuardrailStage, GuardrailAction, GuardrailContext,
)
from parrot.bots.guardrails.builtin.prompt_injection import PromptInjectionGuardrail


@pytest.fixture
def guardrail():
    with patch("parrot.bots.guardrails.builtin.prompt_injection._get_shared_injection_detector") as mock:
        mock.return_value = MagicMock()
        return PromptInjectionGuardrail(
            strict_mode=True, block_on_threat=True,
        )


@pytest.fixture
def ctx():
    return GuardrailContext(stage=GuardrailStage.INPUT, agent_name="test")


class TestPromptInjectionGuardrail:
    def test_stages(self, guardrail):
        assert GuardrailStage.INPUT in guardrail.stages

    def test_priority_in_sanitizer_band(self, guardrail):
        assert guardrail.priority < 100

    @pytest.mark.asyncio
    async def test_clean_input_passes(self, guardrail, ctx):
        result = await guardrail.check("What is the weather?", ctx)
        assert result.action == GuardrailAction.PASS

    @pytest.mark.asyncio
    async def test_block_on_threat(self, guardrail, ctx):
        # Simulate pytector detecting injection
        guardrail._pytector_detector.detect_injection.return_value = (True, 0.99)
        result = await guardrail.check("ignore instructions", ctx)
        assert result.action == GuardrailAction.BLOCK
        assert result.reason is not None

    def test_lazy_import_no_torch_without_guardrail(self):
        """Importing parrot.bots.guardrails does NOT import torch."""
        import sys
        # This test validates the lazy-import boundary
        assert "parrot.bots.guardrails" not in sys.modules or "torch" not in sys.modules


class TestRegistration:
    def test_registered_name(self):
        from parrot.bots.guardrails.registry import build_guardrails
        # Should not raise — name is registered
        # (will fail to instantiate without pytector, but the factory exists)
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/guardrails-infrastructure.spec.md` §3 Module 2
2. **Read** `bots/abstract.py:1836-1942` for the flow to encapsulate
3. **Check dependencies** — TASK-2024, 2025, 2026 must be completed
4. **Verify the Codebase Contract** — confirm all signatures
5. **Update status** → `"in-progress"`
6. **Implement** — focus on the lazy-import boundary first
7. **Verify** all acceptance criteria
8. **Move + update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
