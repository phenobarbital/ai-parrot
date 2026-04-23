# TASK-846: Create NvidiaModel enum

**Feature**: FEAT-122 — Nvidia Client
**Spec**: `sdd/specs/nvidia-client.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The `NvidiaClient` needs a canonical enum of tested Nvidia-NIM model slugs
so callers can write `NvidiaModel.KIMI_K2_THINKING` instead of hard-coded
strings. This task creates the `parrot.models.nvidia` module hosting that
enum. Implements Module 1 of the spec (§3 Module Breakdown).

No Pydantic wrappers are needed — Nvidia's response shape is the OpenAI
Chat Completion shape and is already covered by existing `AIMessage` /
`CompletionUsage` models.

---

## Scope

- Create `packages/ai-parrot/src/parrot/models/nvidia.py`.
- Define a `NvidiaModel(str, Enum)` with the 9 tested model slugs listed
  in the spec (Moonshot Kimi K2 family, Minimax M2.x, Mistral Mamba
  Codestral, DeepSeek V3.1 Terminus, Qwen 3.5, Z-AI GLM 5.1).
- Add a Google-style module docstring and class docstring.

**NOT in scope**:
- Creating `NvidiaClient` (that is TASK-847).
- Factory registration (TASK-848).
- Unit tests (TASK-849).
- Embedding models (`nv-embed-*`) — explicit non-goal per spec §1.
- Pydantic usage / generation-stats models — explicit non-goal per spec §1.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/nvidia.py` | CREATE | `NvidiaModel(str, Enum)` with 9 tested slugs |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Only stdlib imports are needed for this task.

### Verified Imports
```python
from enum import Enum   # stdlib — always available
```

### Existing Signatures to Use
Nothing to extend. This is a greenfield module.

Reference pattern (do NOT import, just mimic the style):
```python
# packages/ai-parrot/src/parrot/models/openrouter.py:11
class OpenRouterModel(str, Enum):
    """Common OpenRouter model identifiers."""
    DEEPSEEK_R1 = "deepseek/deepseek-r1"
    DEEPSEEK_V3 = "deepseek/deepseek-chat"
    ...
```

### Does NOT Exist
- ~~`parrot.models.nvidia`~~ — being created by this task.
- ~~`NvidiaUsage` / `NvidiaGenerationStats`~~ — not in scope; Nvidia has no
  generation-stats endpoint. Do NOT add these.
- ~~`NvidiaEmbeddingModel`~~ — embeddings are a non-goal.
- ~~`parrot/models/nvidia/__init__.py` (subpackage)~~ — this is a single file,
  not a subpackage. Mirror `parrot/models/openrouter.py` / `groq.py`.
- ~~`from pydantic import BaseModel`~~ — no Pydantic models in this task.

---

## Implementation Notes

### Pattern to Follow
Mirror `packages/ai-parrot/src/parrot/models/openrouter.py` lines 1–23:
module docstring, imports from stdlib only (`from enum import Enum`),
a `(str, Enum)` class with each model as an attribute-style member.

### Exact content (required enum members)
The nine slugs, in exactly these strings, grouped with comments:
- Moonshot AI:
  - `KIMI_K2_THINKING = "moonshotai/kimi-k2-thinking"`
  - `KIMI_K2_INSTRUCT_0905 = "moonshotai/kimi-k2-instruct-0905"`
  - `KIMI_K2_5 = "moonshotai/kimi-k2.5"`
- Minimax:
  - `MINIMAX_M2_5 = "minimaxai/minimax-m2.5"`
  - `MINIMAX_M2_7 = "minimaxai/minimax-m2.7"`
- Mistral:
  - `MAMBA_CODESTRAL_7B = "mistralai/mamba-codestral-7b-v0.1"`
- DeepSeek:
  - `DEEPSEEK_V3_1_TERMINUS = "deepseek-ai/deepseek-v3.1-terminus"`
- Qwen:
  - `QWEN3_5_397B = "qwen/qwen3.5-397b-a17b"`
- Z-AI (reasoning-capable):
  - `GLM_5_1 = "z-ai/glm-5.1"`

### Key Constraints
- `class NvidiaModel(str, Enum)` — string-valued so the bare member can
  interchange with raw slugs in OpenAI SDK calls.
- PEP 8 compliant.
- Google-style docstring on the class explaining that `.value` is what the
  SDK accepts.
- No external imports. No runtime side effects.

### References in Codebase
- `packages/ai-parrot/src/parrot/models/openrouter.py` — template.
- `packages/ai-parrot/src/parrot/models/groq.py` — another simple enum example.

---

## Acceptance Criteria

- [ ] File `packages/ai-parrot/src/parrot/models/nvidia.py` exists.
- [ ] `from parrot.models.nvidia import NvidiaModel` works.
- [ ] `NvidiaModel` is a `(str, Enum)` subclass (so `NvidiaModel.GLM_5_1 == "z-ai/glm-5.1"` is True).
- [ ] All 9 members present with the exact slugs listed in the spec.
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/models/nvidia.py`.
- [ ] No new runtime dependencies introduced.

---

## Test Specification

Tests for this enum are combined with the client tests in TASK-849
(`test_nvidia_model_enum_values`). No dedicated test file is needed.

Smoke check the implementing agent SHOULD run before closing the task:
```python
# from repo root with venv activated
python -c "
from parrot.models.nvidia import NvidiaModel
assert NvidiaModel.KIMI_K2_THINKING.value == 'moonshotai/kimi-k2-thinking'
assert NvidiaModel.GLM_5_1.value == 'z-ai/glm-5.1'
assert len(list(NvidiaModel)) == 9
print('ok')
"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context.
2. **Check dependencies** — none; this is the first task.
3. **Verify the Codebase Contract** — confirm `parrot/models/openrouter.py`
   still shows the `(str, Enum)` pattern before copying it.
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID.
5. **Implement** exactly the 9 members in §Implementation Notes. Do not
   add extra models, aliases, helpers, or Pydantic classes.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `tasks/completed/TASK-846-nvidia-model-enum.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
