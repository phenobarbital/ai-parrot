# TASK-2085: Per-model output-token clamping

**Feature**: FEAT-405 — Nova (AWS Bedrock) Dispatcher & Per-Agent Usage Report
**Spec**: `sdd/specs/novaclient-dev-loop.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2084
**Assigned-to**: unassigned

---

## Context

Implements **Module 4** of the spec. Verified Bedrock output ceilings differ
sharply per model — MiniMax M2.5 **8K**, Kimi K2.5 **16K**, GLM-5 128K, Claude
Opus 5 128K — while `LLMCodeDispatchProfile.max_tokens` allows up to 32768
(`models/llm.py:24`). A profile asking for more than a model can return would be
rejected by Bedrock mid-run.

Resolved in the spec (Q5): **clamp with a warning, never reject.** Runs must not
fail on a configuration nobody deliberately chose; the operator gets a log line
naming the model, the requested value and the effective one.

Note the "exceeds 32768" direction is unreachable in the shipped configuration —
only the dev seat uses `LLMCodeDispatchProfile`, and both its candidate models
(MiniMax 8K, Kimi 16K) sit well below that bound. Clamping only ever clamps down.

---

## Scope

- Add `MODEL_MAX_OUTPUT_TOKENS: dict[str, int]` covering the verified ceilings.
- Apply the clamp where the effective `max_tokens` is computed for a dispatch,
  logging a warning naming model / requested / effective when it takes effect.
- Emit **no** warning when the requested value is already within the ceiling.
- Unknown models (absent from the map) are passed through unclamped.
- Write unit tests.

**NOT in scope**: raising `LLMCodeDispatchProfile.max_tokens`'s `le=32768` bound
(explicitly rejected — clamp only); rejecting/raising on over-ask; the dispatcher
loop itself (TASK-2086).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/models/nova.py` | MODIFY | Add `MODEL_MAX_OUTPUT_TOKENS` + an `effective_max_tokens()` helper |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/nova.py` | MODIFY | Apply the clamp when building completion args (create the file if TASK-2086 has not landed yet — coordinate) |
| `packages/ai-parrot/tests/flows/dev_loop/test_nova_clamping.py` | CREATE | Unit tests |

> **Ordering note**: this task and TASK-2086 both touch `dispatchers/nova.py`.
> They run sequentially in the same worktree (`per-spec` isolation). If TASK-2086
> has already landed, extend its `_completion_args`; if not, put the clamp helper
> in `models/nova.py` and have TASK-2086 call it.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.flows.dev_loop.models.nova import NovaCodeDispatchProfile  # created by TASK-2084
from parrot.clients.factory import LLMFactory   # verified: clients/factory.py; "nova" at line 96
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/models/llm.py:24
max_tokens: int = Field(default=4096, ge=256, le=32768)   # the inherited bound — DO NOT WIDEN

# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/moonshot.py:47
# — precedent for computing per-model completion args and warning about model quirks
def _completion_args(self, profile, tools) -> Dict[str, Any]:
    args: Dict[str, Any] = {
        "tools": tools, "tool_choice": "auto",
        "parallel_tool_calls": False, "max_tokens": profile.max_tokens,
    }
    _provider, model = LLMFactory.parse_llm_string(profile.llm)   # line 69
    ...
    self.logger.warning("Moonshot model %s reasons unconditionally; ...", model)  # line 73
    return args
```

`LLMFactory.parse_llm_string(profile.llm) -> (provider, model)` is the verified
way to recover the bare model id from a `"nova:<model>"` string
(`dispatchers/moonshot.py:69`).

### Verified output ceilings (AWS model cards, 2026-08-03)

```text
minimax.minimax-m2.5    8_192     (context 196K)
moonshotai.kimi-k2.5   16_384     (context 256K)
zai.glm-5             131_072     (context 200K)
anthropic.claude-opus-5  131_072   (context 1M)
```

### Does NOT Exist

- ~~`MODEL_MAX_OUTPUT_TOKENS`~~ — this task introduces it
- ~~A per-model cap anywhere in the codebase today~~ — no dispatcher clamps output tokens
- ~~`profile.effective_max_tokens`~~ — not a field; compute it, do not assume it exists
- ~~A `max_output_tokens` field on any existing profile~~ — the field is `max_tokens`

---

## Implementation Notes

### Pattern to Follow

```python
MODEL_MAX_OUTPUT_TOKENS: dict[str, int] = {
    "minimax.minimax-m2.5": 8_192,
    "moonshotai.kimi-k2.5": 16_384,
    "zai.glm-5": 131_072,
    "anthropic.claude-opus-5": 131_072,
}


def effective_max_tokens(model: str, requested: int, logger) -> int:
    """Clamp ``requested`` to ``model``'s verified ceiling (never raise)."""
    ceiling = MODEL_MAX_OUTPUT_TOKENS.get(model)
    if ceiling is None or requested <= ceiling:
        return requested
    logger.warning(
        "Model %s caps output at %d tokens; clamping requested %d.",
        model, ceiling, requested,
    )
    return ceiling
```

### Key Constraints

- **Clamp, never raise.** A profile over the ceiling must still run.
- Match on the **bare** model id (strip any `nova:` prefix via
  `LLMFactory.parse_llm_string`, and any geo prefix if present).
- No warning on the happy path — the log must stay quiet for normal runs.
- Unknown model → return `requested` unchanged, no warning (unknown ≠ wrong).

### References in Codebase

- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/moonshot.py:47-80` —
  per-model quirk handling inside `_completion_args`, including a `self.logger.warning`
- `packages/ai-parrot/src/parrot/flows/dev_loop/models/llm.py:24` — the bound not to widen

---

## Acceptance Criteria

- [ ] `MODEL_MAX_OUTPUT_TOKENS` contains the four verified ceilings above
- [ ] A MiniMax dispatch requesting 32768 uses an effective 8192 **and warns**
- [ ] A Kimi dispatch requesting 32768 uses an effective 16384 **and warns**
- [ ] A request at or below the ceiling passes through unchanged with **no warning**
- [ ] An unknown model passes through unclamped with no warning
- [ ] The warning names model, requested and effective values
- [ ] `LLMCodeDispatchProfile.max_tokens` still declares `le=32768` — **not widened**
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_nova_clamping.py -v` passes
- [ ] `ruff check` + `mypy` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_nova_clamping.py
import logging
import pytest
from parrot.flows.dev_loop.models.llm import LLMCodeDispatchProfile
from parrot.flows.dev_loop.models.nova import (
    MODEL_MAX_OUTPUT_TOKENS, effective_max_tokens,
)


@pytest.fixture
def logger():
    return logging.getLogger("test-clamp")


class TestClamping:
    def test_clamp_minimax_to_8192(self, logger, caplog):
        with caplog.at_level(logging.WARNING):
            assert effective_max_tokens("minimax.minimax-m2.5", 32_768, logger) == 8_192
        assert any("8192" in r.message % r.args if r.args else "8192" in r.message
                   for r in caplog.records) or caplog.records

    def test_clamp_kimi_to_16384(self, logger):
        assert effective_max_tokens("moonshotai.kimi-k2.5", 32_768, logger) == 16_384

    def test_no_clamp_when_under_ceiling(self, logger, caplog):
        with caplog.at_level(logging.WARNING):
            assert effective_max_tokens("minimax.minimax-m2.5", 4_096, logger) == 4_096
        assert not caplog.records, "happy path must not warn"

    def test_unknown_model_passes_through(self, logger, caplog):
        with caplog.at_level(logging.WARNING):
            assert effective_max_tokens("some.future-model", 32_768, logger) == 32_768
        assert not caplog.records


class TestProfileBoundUnchanged:
    def test_profile_bound_not_widened(self):
        """The le=32768 bound must survive — clamping replaced widening."""
        field = LLMCodeDispatchProfile.model_fields["max_tokens"]
        assert any(getattr(m, "le", None) == 32_768 for m in field.metadata)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (Module 4, §7 Known Risks — "Per-model output caps")
2. **Check dependencies** — verify TASK-2084 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm `LLMFactory.parse_llm_string` exists and its return shape
   - Confirm whether `dispatchers/nova.py` already exists (TASK-2086 ordering)
   - If anything has changed, update the contract FIRST, then implement
4. **Update status** in `sdd/tasks/index/novaclient-dev-loop.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2085-per-model-output-clamping.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
