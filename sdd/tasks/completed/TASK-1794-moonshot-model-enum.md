# TASK-1794: MoonshotModel Enum and Constants

**Feature**: FEAT-311 — Moonshot Client (MoonshotClient)
**Spec**: `sdd/specs/moonshot-client-llm.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This task creates the model enum and capability constants for Moonshot/Kimi
models. It is the foundation for the MoonshotClient — all other tasks depend
on these definitions.

Implements spec §3 Module 1 and the Data Models section of §2.

---

## Scope

- Create `MoonshotModel` enum with all 7 model identifiers
- Define `K_SERIES_MODELS` frozenset (models that reject sampling params)
- Define `ALWAYS_THINKING_MODELS` frozenset (K2.7-code variants)
- Define `REASONING_EFFORT_MODELS` frozenset (K3)
- Define `THINKING_DICT_MODELS` frozenset (K2.6)
- Define `VISION_MODELS` frozenset (models with vision support)

**NOT in scope**: Client implementation, factory registration, tests (separate tasks)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/moonshot.py` | CREATE | Model enum and capability frozensets |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from enum import Enum  # stdlib
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/models/nvidia.py:11
# Pattern analog — this is how other providers define model enums
class NvidiaModel(str, Enum):
    KIMI_K2_THINKING = "moonshotai/kimi-k2-thinking"       # line 23
    KIMI_K2_INSTRUCT_0905 = "moonshotai/kimi-k2-instruct-0905"  # line 24
    KIMI_K2_5 = "moonshotai/kimi-k2.5"                     # line 25
```

### Does NOT Exist

- ~~`parrot.models.moonshot`~~ — does not exist yet; this task creates it
- ~~`MoonshotModel` in any `__init__.py`~~ — no export exists yet; Module 2 imports directly

---

## Implementation Notes

### Pattern to Follow

```python
# packages/ai-parrot/src/parrot/models/nvidia.py (full file, 42 lines)
# Follow this exact pattern: docstring on module, docstring on enum class,
# str-valued enum so members interchange with raw model strings.
from enum import Enum

class NvidiaModel(str, Enum):
    """Nvidia NIM-hosted model identifiers."""
    KIMI_K2_THINKING = "moonshotai/kimi-k2-thinking"
    ...
```

### Key Constraints

- Enum must inherit from `(str, Enum)` so values work directly as model strings
- All 7 models from the spec must be included
- frozensets use the `.value` of enum members for string matching in the client
- Module-level docstring explaining the file's purpose

### Model Categories

| Category | Models | Purpose |
|---|---|---|
| `K_SERIES_MODELS` | kimi-k3, kimi-k2.7-code, kimi-k2.7-code-highspeed, kimi-k2.6 | Strip sampling params |
| `ALWAYS_THINKING_MODELS` | kimi-k2.7-code, kimi-k2.7-code-highspeed | No thinking param needed |
| `REASONING_EFFORT_MODELS` | kimi-k3 | Uses `reasoning_effort` param |
| `THINKING_DICT_MODELS` | kimi-k2.6 | Uses `thinking` dict param |
| `VISION_MODELS` | kimi-k3, kimi-k2.7-code, kimi-k2.7-code-highspeed, kimi-k2.6, moonshot-v1-8k-vision-preview, moonshot-v1-128k-vision-preview | Vision-capable |

---

## Acceptance Criteria

- [ ] `MoonshotModel` enum has 7 members with correct string values
- [ ] All 5 frozensets defined with correct model membership
- [ ] File follows NvidiaModel pattern (module docstring, class docstring, `str, Enum`)
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/models/moonshot.py`
- [ ] Import works: `from parrot.models.moonshot import MoonshotModel`

---

## Test Specification

```python
# Inline verification — no separate test file needed for enum.
# The Module 4 test task covers enum value assertions.
from parrot.models.moonshot import (
    MoonshotModel, K_SERIES_MODELS, ALWAYS_THINKING_MODELS,
    REASONING_EFFORT_MODELS, THINKING_DICT_MODELS,
)

assert MoonshotModel.KIMI_K3.value == "kimi-k3"
assert MoonshotModel.KIMI_K2_7_CODE.value == "kimi-k2.7-code"
assert "kimi-k3" in K_SERIES_MODELS
assert "kimi-k2.7-code" in ALWAYS_THINKING_MODELS
assert "kimi-k3" in REASONING_EFFORT_MODELS
assert "kimi-k2.6" in THINKING_DICT_MODELS
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/moonshot-client-llm.spec.md` for full context
2. **Check dependencies** — this task has none
3. **Verify the Codebase Contract** — confirm `parrot/models/nvidia.py` still matches the pattern
4. **Implement** the enum and frozensets
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-1794-moonshot-model-enum.md`
7. **Update index** → `"done"`

---

## Completion Note

Implemented `packages/ai-parrot/src/parrot/models/moonshot.py` following the
`NvidiaModel` pattern exactly: `MoonshotModel(str, Enum)` with all 7 model
identifiers, plus `K_SERIES_MODELS`, `ALWAYS_THINKING_MODELS`,
`REASONING_EFFORT_MODELS`, `THINKING_DICT_MODELS`, and `VISION_MODELS`
frozensets built from the enum's `.value`s. Verified import, enum member
count (7), and frozenset membership via an inline script; `ruff check`
passes clean. No deviations from the spec/task contract.
