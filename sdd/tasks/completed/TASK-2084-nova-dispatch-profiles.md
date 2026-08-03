# TASK-2084: Nova dispatch profiles (code, adversarial, mechanical)

**Feature**: FEAT-405 — Nova (AWS Bedrock) Dispatcher & Per-Agent Usage Report
**Spec**: `sdd/specs/novaclient-dev-loop.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2083
**Assigned-to**: unassigned

---

## Context

Implements **Module 2** of the spec. The three Nova seats have different shapes
and therefore need three profiles: a tool-using development profile (MiniMax M2.5
over the `bedrock-mantle` OpenAI-compatible endpoint), a **no-tools** adversarial
review profile (Claude Opus 5 over Converse), and a **no-tools** mechanical
profile (Claude Haiku 4.5) for PR summary text.

The adversarial profile being tool-free is the security property: read-only holds
because the model is never handed a tool, not because enforcement code is correct.

`dev_loop/models/` is a per-client package (split landed as `a50567f39`), so this
task adds one module beside `models/moonshot.py` and `models/zai.py`.

---

## Scope

- Create `dev_loop/models/nova.py` with:
  - `NovaCodeDispatchProfile(LLMCodeDispatchProfile)` — dev seat, default model
    `minimax.minimax-m2.5`, with a `_sync_llm_with_model` validator mirroring
    `MoonshotCodeDispatchProfile`.
  - `NovaAdversarialReviewProfile(BaseModel)` — Claude Opus 5, **no tool fields**,
    plus `review_scope` / `review_base` / `review_commit` / `max_diff_chars`.
  - `NovaMechanicalProfile(BaseModel)` — Claude Haiku 4.5, short output, timeout.
- Export all three from `dev_loop/models/__init__.py`.
- Write unit tests.

**NOT in scope**: the `MODEL_MAX_OUTPUT_TOKENS` clamping map and clamp logic
(TASK-2085); dispatchers (TASK-2086/2087); `DevAgentBackend` or `build_dispatcher`
wiring (TASK-2088).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/models/nova.py` | CREATE | The three profiles |
| `packages/ai-parrot/src/parrot/flows/dev_loop/models/__init__.py` | MODIFY | Export the three profiles (import + `__all__`) |
| `packages/ai-parrot/tests/flows/dev_loop/test_nova_profiles.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.flows.dev_loop.models.llm import LLMCodeDispatchProfile
# verified: packages/ai-parrot/src/parrot/flows/dev_loop/models/llm.py:10
from pydantic import BaseModel, Field, model_validator
from typing import Literal
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/models/llm.py
class LLMCodeDispatchProfile(BaseModel):                              # line 10
    subagent: Literal["sdd-worker"] = "sdd-worker"                    # line 18
    llm: str = "nvidia:moonshotai/kimi-k2-instruct-0905"              # line 19
    sandbox: Literal["workspace-write"] = "workspace-write"           # line 20
    approval_policy: Literal["never"] = "never"                       # line 21
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)        # line 22
    max_turns: int = Field(default=24, ge=1, le=100)                  # line 23
    max_tokens: int = Field(default=4096, ge=256, le=32768)           # line 24
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)           # line 25
    command_timeout_seconds: int = Field(default=300, ge=1, le=3600)  # line 26
    allowed_commands: List[str] = Field(default_factory=lambda: [...])# line 27
    enable_thinking: bool = Field(default=False)                      # line 43
    clear_thinking: bool = False                                      # line 47

# packages/ai-parrot/src/parrot/flows/dev_loop/models/moonshot.py — THE PATTERN TO COPY
class MoonshotCodeDispatchProfile(LLMCodeDispatchProfile):            # line 10
    model: str = Field(default="kimi-k3", description="...")          # line 21
    llm: str = "moonshot:kimi-k3"                                     # line 25
    max_tokens: int = Field(default=8192, ge=256, le=131072)          # line 41

    @model_validator(mode="after")                                    # line 43
    def _sync_llm_with_model(self) -> "MoonshotCodeDispatchProfile":  # line 44
        """Derive ``llm`` from ``model`` unless the caller set ``llm`` explicitly."""
        if "llm" not in self.model_fields_set:                        # line 46
            self.llm = f"moonshot:{self.model}"                       # line 47
        return self

# packages/ai-parrot/src/parrot/flows/dev_loop/models/__init__.py
# exports DevAgentBackend (line 29) and lists names in __all__ (line 93)
```

### Verified model ids (AWS model cards, 2026-08-03)

```text
dev seat         minimax.minimax-m2.5                          (max output 8K,  no prefix)
adversarial      us.anthropic.claude-opus-5                    (max output 128K, geo prefix)
mechanical       us.anthropic.claude-haiku-4-5-20251001-v1:0   (geo prefix)
also available   moonshotai.kimi-k2.5 (16K, no prefix), zai.glm-5 (128K, no prefix)
```

### Does NOT Exist

- ~~`parrot.flows.dev_loop.models.nova`~~ — this task creates it
- ~~`NovaCodeDispatchProfile`~~ / ~~`NovaAdversarialReviewProfile`~~ / ~~`NovaMechanicalProfile`~~ — created here
- ~~`MODEL_MAX_OUTPUT_TOKENS`~~ — TASK-2085 introduces it; do not add it here
- ~~`CodexAdversarialReviewProfile` as a base class~~ — it exists (`code_review.py` imports it) but is Codex-shaped; `NovaAdversarialReviewProfile` is a fresh `BaseModel`, NOT a subclass of it
- ~~A `subagent` field on the adversarial/mechanical profiles~~ — `subagent` belongs to CLI-agent profiles; Nova review seats have none

---

## Implementation Notes

### Pattern to Follow

```python
# Copy the shape of models/moonshot.py:10-48 for NovaCodeDispatchProfile:
class NovaCodeDispatchProfile(LLMCodeDispatchProfile):
    """Declarative profile consumed by ``NovaCodeDispatcher.dispatch()``."""

    model: str = Field(default="minimax.minimax-m2.5", description="...")
    llm: str = "nova:minimax.minimax-m2.5"

    @model_validator(mode="after")
    def _sync_llm_with_model(self) -> "NovaCodeDispatchProfile":
        if "llm" not in self.model_fields_set:
            self.llm = f"nova:{self.model}"
        return self
```

### Key Constraints

- **`NovaAdversarialReviewProfile` must expose NO tool configuration** — no
  `tools`, no `allowed_commands`, no `sandbox`. Read-only by construction.
- Keep `max_tokens` on `NovaCodeDispatchProfile` within the inherited
  `ge=256, le=32768` bound. Per-model clamping is TASK-2085's job, not a wider
  bound here.
- Pydantic v2 (`model_validator(mode="after")`, `model_fields_set`).
- Google-style docstrings on every class and field description.

### References in Codebase

- `packages/ai-parrot/src/parrot/flows/dev_loop/models/moonshot.py` — closest precedent
- `packages/ai-parrot/src/parrot/flows/dev_loop/models/zai.py` — second example of the same shape
- `packages/ai-parrot/src/parrot/flows/dev_loop/models/__init__.py` — export style

---

## Acceptance Criteria

- [ ] `from parrot.flows.dev_loop.models import NovaCodeDispatchProfile, NovaAdversarialReviewProfile, NovaMechanicalProfile` works
- [ ] `NovaCodeDispatchProfile(model="moonshotai.kimi-k2.5").llm == "nova:moonshotai.kimi-k2.5"`
- [ ] An explicitly-set `llm` is **not** overwritten by the validator
- [ ] `NovaAdversarialReviewProfile` has no field named `tools`, `allowed_commands`, `sandbox`, or `subagent`
- [ ] Default models match the verified ids above
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_nova_profiles.py -v` passes
- [ ] `ruff check` + `mypy` clean on the new/changed files

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_nova_profiles.py
import pytest
from parrot.flows.dev_loop.models import (
    NovaAdversarialReviewProfile,
    NovaCodeDispatchProfile,
    NovaMechanicalProfile,
)


class TestNovaCodeDispatchProfile:
    def test_default_model_is_minimax(self):
        assert NovaCodeDispatchProfile().model == "minimax.minimax-m2.5"

    def test_llm_derived_from_model(self):
        p = NovaCodeDispatchProfile(model="moonshotai.kimi-k2.5")
        assert p.llm == "nova:moonshotai.kimi-k2.5"

    def test_explicit_llm_not_overwritten(self):
        p = NovaCodeDispatchProfile(model="minimax.minimax-m2.5", llm="nova:custom")
        assert p.llm == "nova:custom"

    def test_max_tokens_within_inherited_bound(self):
        with pytest.raises(ValueError):
            NovaCodeDispatchProfile(max_tokens=99_999)


class TestNovaAdversarialReviewProfile:
    def test_default_model_is_opus5(self):
        assert NovaAdversarialReviewProfile().model == "us.anthropic.claude-opus-5"

    @pytest.mark.parametrize("forbidden", ["tools", "allowed_commands", "sandbox", "subagent"])
    def test_exposes_no_tool_configuration(self, forbidden):
        """Read-only by construction — the profile cannot carry tools."""
        assert forbidden not in NovaAdversarialReviewProfile.model_fields

    def test_has_diff_truncation_bound(self):
        assert NovaAdversarialReviewProfile().max_diff_chars > 0


class TestNovaMechanicalProfile:
    def test_default_model_is_haiku(self):
        assert "haiku" in NovaMechanicalProfile().model

    def test_output_is_short(self):
        assert NovaMechanicalProfile().max_tokens <= 8192
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§2 Data Models, Module 2)
2. **Check dependencies** — verify TASK-2083 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm `LLMCodeDispatchProfile`'s fields and line numbers in `models/llm.py`
   - Confirm `MoonshotCodeDispatchProfile`'s validator shape in `models/moonshot.py`
   - If anything has changed, update the contract FIRST, then implement
4. **Update status** in `sdd/tasks/index/novaclient-dev-loop.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2084-nova-dispatch-profiles.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Sonnet 5)
**Date**: 2026-08-03
**Notes**: Created `dev_loop/models/nova.py` with `NovaCodeDispatchProfile`
(subclasses `LLMCodeDispatchProfile`, `_sync_llm_with_model` validator mirroring
`MoonshotCodeDispatchProfile`, default `model="minimax.minimax-m2.5"`,
`llm="nova:minimax.minimax-m2.5"`), `NovaAdversarialReviewProfile` (fresh
`BaseModel`, default `model="us.anthropic.claude-opus-5"`, no tool fields),
and `NovaMechanicalProfile` (fresh `BaseModel`, default
`model="us.anthropic.claude-haiku-4-5-20251001-v1:0"`). Exported all three
from `models/__init__.py` (import + `__all__`). 18 unit tests in
`test_nova_profiles.py`, all pass; `ruff check` clean; no new mypy errors.

**Deviations from spec**: none.
