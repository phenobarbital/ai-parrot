# TASK-2630: Adaptive-thinking support in BedrockConverseBase

**Feature**: FEAT-482 — Complementary (Collaborative) Research for the Dev Flow
**Spec**: `sdd/specs/devflow-complementary-research.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **spec §3 Module 3**. Fixes a latent defect in a **shared client**.

`BedrockConverseBase` emits exactly one extended-thinking shape
(`bedrock.py:831-835`):

```python
additional_fields["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
```

That shape is **removed and returns HTTP 400** on Claude Opus 5, Claude Fable 5,
Opus 4.8/4.7 and Sonnet 5. Those models use adaptive thinking
(`{"type": "adaptive"}`) plus `output_config.effort`. Amazon Nova and older
Anthropic models still accept `budget_tokens`.

This defect predates FEAT-482 and is not caused by it — it became **reachable**
when Bedrock's `us.anthropic.*` per-account use-case form was cleared, making
`us.anthropic.claude-opus-5` a selectable model id across every Bedrock seat.
Fixing it here prevents each of those seats from tripping over it independently.

⚠️ **This task edits a shared client used far beyond dev-flow.** Keep the change
narrow and strictly additive.

---

## Scope

- Teach `BedrockConverseBase` to select the correct thinking shape per model:
  - modern Anthropic (Opus 5, Fable 5, Opus 4.8, Opus 4.7, Sonnet 5) →
    `{"type": "adaptive"}`, with effort carried via `output_config.effort`
  - everything else (Amazon Nova, older Anthropic) → the existing
    `{"type": "enabled", "budget_tokens": N}`
- Apply the same selection in **both** `ask()` (`bedrock.py:699`, thinking applied
  at `:831-835`) and `ask_stream()` (`:1056`, thinking at `:1130-1132`) — they
  build the field independently today.
- Add a small, testable predicate (e.g. `_requires_adaptive_thinking(model_id)`)
  rather than inlining the model list at both call sites.
- Unit tests, including the **no-regression** test below.

**NOT in scope**: any FEAT-482 partner/coordinator/node code; changing default
models anywhere; touching `NovaAdversarialReviewDispatcher`; adding
`output_config.effort` plumbing beyond what the adaptive shape requires.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/bedrock.py` | MODIFY | Per-model thinking shape in `ask()` + `ask_stream()` |
| `packages/ai-parrot/tests/clients/test_bedrock_thinking.py` | CREATE | Shape-selection + no-regression tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.clients.bedrock import BedrockConverseBase   # bedrock.py:114
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/bedrock.py
class BedrockConverseBase(AbstractClient):                           # line 114
    def __init__(...)                                                # line 130
    def _translate_model(self, model: Optional[str]) -> str:         # line 348
    async def ask(                                                   # line 699
        ...,
        thinking_budget: Optional[int] = None,                       # line 715
    )
    async def ask_stream(...)                                        # line 1056
        thinking_budget: Optional[int] = None,                       # line 1070

# THE EXACT CODE TO CHANGE — ask(), bedrock.py:830-835:
        additional_fields: Dict[str, Any] = {}
        if thinking_budget:
            additional_fields["thinking"] = {
                "type": "enabled",
                "budget_tokens": thinking_budget,
            }
        if prompt_cache:
            additional_fields["promptCaching"] = {"cachePoint": {"type": "default"}}
        if additional_fields:
            payload["additionalModelRequestFields"] = additional_fields

# THE SECOND SITE — ask_stream(), bedrock.py:1130-1132:
        if thinking_budget:
            ... {"thinking": {"type": "enabled", "budget_tokens": thinking_budget}}

# Reference for existing per-model predicates in this same file:
def rejects_sampling_params(model_id: str) -> bool:                  # line 72
    # Follow this shape for _requires_adaptive_thinking().

# Model ids that require the ADAPTIVE shape (from catalog.py:230-247 + spec §6):
#   us.anthropic.claude-opus-5, global.anthropic.claude-fable-5,
#   and the Opus 4.8 / Opus 4.7 / Sonnet 5 equivalents.
# Model ids that KEEP budget_tokens:
#   us.amazon.nova-2-lite-v1:0, us.amazon.nova-pro-v1:0,
#   us.anthropic.claude-haiku-4-5-20251001-v1:0 and older.
```

### Does NOT Exist

- ~~any adaptive-thinking support in `BedrockConverseBase`~~ — the string
  `"adaptive"` does not appear in `bedrock.py` today. This task introduces it.
- ~~`_requires_adaptive_thinking`~~ — new; model it on `rejects_sampling_params`
  (`bedrock.py:72`).
- ~~a shared helper that both `ask()` and `ask_stream()` already call for thinking~~ —
  they build `additionalModelRequestFields` **independently**. Both sites must change.
- ~~`output_config` support on the Converse payload~~ — verify how (and whether)
  Bedrock Converse accepts effort for these models **before** adding it; do not
  invent a payload key. If it cannot be expressed, emit the bare
  `{"type": "adaptive"}` and note the limitation in the completion note.

---

## Implementation Notes

### Pattern to Follow

```python
# bedrock.py:72 — existing per-model predicate, mirror this shape
def rejects_sampling_params(model_id: str) -> bool:
    ...

def _requires_adaptive_thinking(model_id: str) -> bool:
    """True when the model rejects `budget_tokens` and needs `{"type": "adaptive"}`."""
```

### Key Constraints

- **Strictly additive.** A `thinking_budget` call against a Nova model must produce a
  byte-identical Bedrock payload to today. This is the single most important
  property of this task and is an explicit acceptance criterion.
- Match on the model id **after** `_translate_model()` (`bedrock.py:348`) so both
  bare and region-prefixed ids resolve correctly.
- Keep the predicate list in one place; do not duplicate it at the two call sites.
- `thinking_budget` remains the caller-facing parameter name for backwards
  compatibility — callers passing it against a modern Anthropic model should get
  adaptive thinking, not an error.

### References in Codebase

- `packages/ai-parrot/src/parrot/clients/bedrock.py:72` — predicate style.
- `packages/ai-parrot/src/parrot/clients/bedrock.py:986-988` — the reasoning-signature
  preservation this must not disturb.

---

## Acceptance Criteria

- [ ] Opus 5 / Fable 5 / Opus 4.8 / Opus 4.7 / Sonnet 5 emit `{"type": "adaptive"}` and never `budget_tokens`
- [ ] **No regression**: a Nova model with `thinking_budget=N` produces a byte-identical payload to pre-change behavior
- [ ] Both `ask()` and `ask_stream()` are covered
- [ ] `thinking_budget=None` still emits no `thinking` field at all
- [ ] `reasoningContent` signature preservation (`bedrock.py:986-988`) is untouched
- [ ] All tests pass: `pytest packages/ai-parrot/tests/clients/test_bedrock_thinking.py -v`
- [ ] Existing Bedrock tests still pass: `pytest packages/ai-parrot/tests/clients/ -k bedrock -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/clients/bedrock.py`

---

## Test Specification

```python
import pytest
from parrot.clients.bedrock import BedrockConverseBase


class TestThinkingShapeSelection:
    @pytest.mark.parametrize("model", [
        "us.anthropic.claude-opus-5",
        "global.anthropic.claude-fable-5",
    ])
    def test_adaptive_shape_for_modern_anthropic(self, model):
        """Modern Anthropic models get {"type": "adaptive"}, never budget_tokens."""

    @pytest.mark.parametrize("model", [
        "us.amazon.nova-2-lite-v1:0",
        "us.amazon.nova-pro-v1:0",
    ])
    def test_budget_tokens_unchanged_for_nova(self, model):
        """NO-REGRESSION GUARD: payload is byte-identical to pre-change behavior."""

    def test_no_thinking_field_when_budget_none(self):
        """thinking_budget=None => no `thinking` key in additionalModelRequestFields."""

    def test_ask_stream_uses_same_selection(self):
        """ask_stream() applies the identical per-model shape as ask()."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§3 Module 3, §7 Known Risks).
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** — re-read `bedrock.py:820-840` and `:1125-1140`
   before editing; confirm the two thinking sites are still independent.
4. **Confirm the Bedrock payload shape for adaptive thinking** against real
   documentation before writing it. Do NOT guess a payload key. If you cannot
   confirm how effort is expressed on Converse, emit the bare adaptive shape and
   say so in the completion note.
5. **Update status** in `sdd/tasks/index/devflow-complementary-research.json` → `"in-progress"`.
6. **Implement** — strictly additive.
7. **Verify** all acceptance criteria, especially the no-regression guard.
8. **Move this file** to `sdd/tasks/completed/TASK-2630-bedrock-adaptive-thinking.md`.
9. **Update index** → `"done"`.
10. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
