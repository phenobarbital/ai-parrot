# TASK-2029: SecretsGuardrail + OUTPUT/TOOL_OUTPUT Pipeline Wiring

**Feature**: FEAT-396 — Unified Guardrails Infrastructure
**Spec**: `sdd/specs/guardrails-infrastructure.spec.md`
**Status**: done
**Completed**: 2026-08-01T10:32:49+00:00
**Verification**: verified
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2024, TASK-2025, TASK-2026
**Assigned-to**: unassigned

---

## Context

This task creates the `SecretsGuardrail` built-in plugin (wrapping the
existing `OutputScrubber`) and wires the TOOL_OUTPUT, OUTPUT, and
OUTPUT_STREAM pipelines into the bot seams. It also folds the
channel-egress scrub (`bots/base.py:1445`, limited to 4 chat modes) into
the OUTPUT pipeline for all output modes.

Implements: Spec §3 Module 3 (`guardrails-output-plugins`).

This task is **parallel** with TASK-2027/2028 — it touches disjoint files
(tool hook, `get_response`, `ask_stream` output path vs input path).

---

## Scope

- Create `parrot/bots/guardrails/builtin/secrets.py`:
  - `SecretsGuardrail(Guardrail)`:
    - `name = "secrets"`
    - `stages = {GuardrailStage.TOOL_OUTPUT, GuardrailStage.OUTPUT}`
    - `priority = 10` (sanitizer band — always first)
    - `on_error = "fail_open"` (mirror FEAT-252 non-fatal contract)
    - `async check(content, ctx) → GuardrailResult`:
      - Delegates to `OutputScrubber.scrub()`.
      - Idempotency: respects `_already_scrubbed`.
      - Returns TRANSFORM with scrubbed content, or PASS if unchanged.
- Register `"secrets"` in the guardrail registry.
- Modify `parrot/tools/abstract.py`:
  - The FEAT-252 hook (`:784-810`) delegates to the TOOL_OUTPUT pipeline
    instead of calling `_default_scrubber()` directly.
  - `enable_redaction` semantics unchanged — the `SecretsGuardrail` is
    only registered when `enable_redaction=True` (handled by TASK-2026
    config mapping).
- Modify `parrot/bots/abstract.py` `get_response()` (`:3461`):
  - After producing the response, run the OUTPUT pipeline.
- Modify `parrot/bots/base.py` `ask_stream`:
  - Wrap chunk yields through registered `StreamingGuardrail` adapters.
  - Run OUTPUT pipeline on the final `AIMessage` at stream close.
  - Fold the channel-egress scrub (`:1442-1445`, 4 modes only) into the
    OUTPUT pipeline for ALL output modes.
- Document sockets for FEAT-324/325 plugins (reserved registry names).
- Write unit + integration tests.

**NOT in scope**: input seams (TASK-2028), moderation (TASK-2030),
FEAT-324/325 plugin implementations.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/guardrails/builtin/secrets.py` | CREATE | SecretsGuardrail plugin |
| `parrot/bots/guardrails/registry.py` | MODIFY | Register `"secrets"` factory |
| `parrot/tools/abstract.py` | MODIFY | Delegate FEAT-252 hook to TOOL_OUTPUT pipeline |
| `parrot/bots/abstract.py` | MODIFY | Run OUTPUT pipeline in `get_response()` |
| `parrot/bots/base.py` | MODIFY | OUTPUT_STREAM in ask_stream + fold channel egress |
| `tests/unit/test_guardrails_secrets.py` | CREATE | Unit tests |
| `tests/integration/test_guardrails_output.py` | CREATE | Integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Engine — reused, not modified:
from parrot.security.redaction import (
    OutputScrubber,         # security/redaction.py:149
    ScrubPolicy,            # :128
    _already_scrubbed,      # :122
)

# tools/abstract.py:63
def _default_scrubber(): ...

# Guardrails core (from TASK-2024/2025):
from parrot.bots.guardrails.base import (
    Guardrail, GuardrailStage, GuardrailAction,
    GuardrailResult, GuardrailContext,
)
from parrot.bots.guardrails.pipeline import GuardrailPipeline
```

### Existing Signatures to Use
```python
# tools/abstract.py — FEAT-252 hook:
#   :783-810 — gated `if self.enable_redaction:` (:784)
#   _default_scrubber() :63
#   tool attr enable_redaction :155

# bots/abstract.py — get_response:
#   def get_response(...) :3461

# bots/base.py — channel egress:
#   _BOT_EGRESS_SCRUBBER :60-61 (module-level singleton)
#   applied :1442-1445 (TELEGRAM/MSTEAMS/SLACK/WHATSAPP only)

# bots/base.py — ask_stream final message:
#   :1846 area — final AIMessage yield

# security/redaction.py:
#   OutputScrubber.scrub(text) → str  :149
#   _already_scrubbed(text) → bool    :122
#   ScrubPolicy (frozen dataclass)    :128

# enable_redaction stamping chain:
#   tools/manager.py:593-594,655-656,1448-1449
```

### Does NOT Exist
- ~~`SecretsGuardrail`~~ — created by this task
- ~~An output/response transform chain~~ — `PromptPipeline` is input-only
- ~~Channel-egress scrub for all modes~~ — today limited to 4 chat modes
  (TELEGRAM, MSTEAMS, SLACK, WHATSAPP at `:1442-1445`)
- ~~FEAT-324 PII guardrail~~ — socket reserved, not implemented
- ~~FEAT-398 groundedness guardrail~~ — socket reserved, not implemented

---

## Implementation Notes

### Key Constraints
- `SecretsGuardrail` must produce identical scrub results to the current
  `OutputScrubber` for the same inputs — no behavioral change.
- The `enable_redaction` gating is preserved: `SecretsGuardrail` is only
  registered when `enable_redaction=True` (config mapping in TASK-2026).
- Tool-seam delegation: the TOOL_OUTPUT pipeline replaces the direct
  `_default_scrubber()` call; the pipeline may contain additional
  guardrails in the future (PII, etc.).
- Channel-egress extension: the OUTPUT pipeline now applies to ALL output
  modes, not just the 4 chat modes. This is a deliberate behavior
  extension documented in the spec (§2, last paragraph).
- `_BOT_EGRESS_SCRUBBER` singleton can be removed if the OUTPUT pipeline
  covers its use case — or kept as a fallback.
- Ordering: secrets always runs first (priority 10, sanitizer band).

### References in Codebase
- `tools/abstract.py:783-810` — tool seam to modify
- `bots/abstract.py:3461` — get_response seam
- `bots/base.py:1442-1445` — channel egress to fold in
- `bots/base.py:1846` — ask_stream final message
- `security/redaction.py:122,149` — engine to wrap

---

## Acceptance Criteria

- [ ] `SecretsGuardrail` wraps `OutputScrubber` with identical semantics
- [ ] Registered as `"secrets"` in the guardrail registry
- [ ] TOOL_OUTPUT pipeline replaces direct `_default_scrubber()` in tool hook
- [ ] OUTPUT pipeline runs in `get_response()`
- [ ] `ask_stream` runs streaming adapters per-chunk and OUTPUT at close
- [ ] Channel-egress scrub extended to all output modes (not just 4)
- [ ] `enable_redaction=False` → no secrets guardrail registered → identical
      to today's behavior
- [ ] FEAT-324/325 registry names reserved with "not yet implemented" error
- [ ] Scrub failure is non-fatal (fail_open)
- [ ] All tests pass
- [ ] No linting errors

---

## Test Specification

```python
# tests/unit/test_guardrails_secrets.py
import pytest
from parrot.bots.guardrails.builtin.secrets import SecretsGuardrail
from parrot.bots.guardrails.base import GuardrailStage, GuardrailAction, GuardrailContext


@pytest.fixture
def guardrail():
    return SecretsGuardrail()

@pytest.fixture
def ctx():
    return GuardrailContext(stage=GuardrailStage.TOOL_OUTPUT, agent_name="test")


class TestSecretsGuardrail:
    @pytest.mark.asyncio
    async def test_scrubs_secrets(self, guardrail, ctx):
        result = await guardrail.check("API_KEY=sk-1234abc", ctx)
        assert result.action == GuardrailAction.TRANSFORM
        assert "sk-1234abc" not in result.content

    @pytest.mark.asyncio
    async def test_clean_text_passes(self, guardrail, ctx):
        result = await guardrail.check("hello world", ctx)
        assert result.action == GuardrailAction.PASS

    @pytest.mark.asyncio
    async def test_idempotent(self, guardrail, ctx):
        result1 = await guardrail.check("KEY=secret123", ctx)
        result2 = await guardrail.check(result1.content, ctx)
        assert result1.content == result2.content

    def test_fail_open(self, guardrail):
        assert guardrail.on_error == "fail_open"

    def test_priority_sanitizer_band(self, guardrail):
        assert guardrail.priority < 100
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §2 (output seams), §3 Module 3
2. **Read** `tools/abstract.py:783-810`, `bots/abstract.py:3461`,
   `bots/base.py:1442-1445,1846`
3. **Check dependencies** — TASK-2024, 2025, 2026 must be completed
4. **Implement** in order: SecretsGuardrail → tool hook → get_response →
   ask_stream → channel egress fold-in → tests
5. **Run existing test suite** for compat
6. **Move + update index** → `"done"`

---

## Completion Note

Implemented as specified. `builtin/secrets.py` adds `SecretsGuardrail`,
registered as `"secrets"`; OUTPUT pipeline wired into
`abstract.py::get_response()` and OUTPUT_STREAM/TOOL_OUTPUT wired into
`bots/base.py` and `tools/abstract.py` (FEAT-252 hook delegation).
Follow-up commit `345471413` (adversarial code review) hardened the
TOOL_OUTPUT/OUTPUT_STREAM wiring further. Verified by `/sdd-done`:
commit `3b799b9ae` found, all 7 listed files present.
