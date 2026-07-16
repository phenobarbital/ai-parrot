---
type: Wiki Overview
title: 'TASK-1692: Z.ai model registry — add GLM-5.2, bump ZaiClient defaults, tighten
  SDK pin'
id: doc:sdd-tasks-completed-task-1692-zai-model-registry-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module 1 of FEAT-269 (spec §3). GLM-5.2 is Z.ai's new coding flagship but
  is
relates_to:
- concept: mod:parrot.clients.zai
  rel: mentions
- concept: mod:parrot.models.zai
  rel: mentions
---

# TASK-1692: Z.ai model registry — add GLM-5.2, bump ZaiClient defaults, tighten SDK pin

**Feature**: FEAT-269 — Z.ai Code Dispatcher for the Dev Loop (GLM-5.2)
**Spec**: `sdd/specs/zai-client-code.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Module 1 of FEAT-269 (spec §3). GLM-5.2 is Z.ai's new coding flagship but is
absent from the `ZaiModel` enum (which tops out at `glm-5.1`) and from
`THINKING_CAPABLE_ZAI_MODELS`. Everything downstream (the new
`ZaiCodeDispatchProfile` default and the dispatcher's thinking-capability
warning) keys off this registry. The user also decided (spec §8, resolved) to
bump `ZaiClient`'s class default model to `glm-5.2` and tighten the `zai-sdk`
pin to `>=0.2.3` (no upgrade needed — 0.2.3 is installed and is the latest on
PyPI; the pin change is documentation value only).

---

## Scope

- Add `GLM_5_2 = "glm-5.2"` to the `ZaiModel` enum (place it before `GLM_5_1`,
  keeping the newest-first ordering of the 5.x block).
- Add `ZaiModel.GLM_5_2.value` to `THINKING_CAPABLE_ZAI_MODELS`.
- In `ZaiClient`, change `model` and `_default_model` class attributes from
  `ZaiModel.GLM_5_1.value` to `ZaiModel.GLM_5_2.value`. Leave
  `_lightweight_model` unchanged.
- In `packages/ai-parrot/pyproject.toml`, change both `"zai-sdk>=0.2.2"`
  occurrences (lines 376 and 388) to `"zai-sdk>=0.2.3"`.

**NOT in scope**: `ZaiCodeDispatchProfile` (TASK-1693), `ZaiCodeDispatcher`
(TASK-1694), any change to `ZaiClient` methods/logic, tests beyond a smoke
import (full tests land in TASK-1696), the repo-root `pyproject.toml` (its
`zai` extra just forwards to `ai-parrot[zai]` — no version pinned there).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/zai.py` | MODIFY | Add `GLM_5_2` enum member + thinking-capable set entry |
| `packages/ai-parrot/src/parrot/clients/zai.py` | MODIFY | Bump `model` / `_default_model` class attrs to GLM_5_2 |
| `packages/ai-parrot/pyproject.toml` | MODIFY | `zai-sdk>=0.2.2` → `>=0.2.3` (2 occurrences: lines 376, 388) |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-07-03 against `dev`.

### Verified Imports
```python
from parrot.models.zai import ZaiModel, THINKING_CAPABLE_ZAI_MODELS  # models/zai.py:4,34
from parrot.clients.zai import ZaiClient                             # clients/zai.py:22
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/zai.py
class ZaiModel(str, Enum):                        # line 4
    GLM_5_1 = "glm-5.1"                           # line 11 — newest member today
    GLM_5 = "glm-5"                               # line 12
    ...
THINKING_CAPABLE_ZAI_MODELS = frozenset({         # line 34
    ZaiModel.GLM_5_1.value,                       # line 36 — add GLM_5_2 alongside
    ...
})

# packages/ai-parrot/src/parrot/clients/zai.py
class ZaiClient(AbstractClient):                  # line 22
    model: str = ZaiModel.GLM_5_1.value           # line 27 — change to GLM_5_2
    _default_model: str = ZaiModel.GLM_5_1.value  # line 28 — change to GLM_5_2
    _lightweight_model: str = ZaiModel.GLM_4_5_FLASH_FREE.value  # line 29 — DO NOT change

# packages/ai-parrot/pyproject.toml
# line 375-376:  zai = [\n    "zai-sdk>=0.2.2"
# line 388:      "zai-sdk>=0.2.2",   (inside the `all` extra)
```

### Does NOT Exist
- ~~`ZaiModel.GLM_5_2`~~ — this task creates it; nothing else references it yet
- ~~a `glm-5.2` entry anywhere in `THINKING_CAPABLE_ZAI_MODELS`~~ — created here
- ~~top-level `/parrot/` sources~~ — repo-root `parrot/` is a stale build
  artifact; live sources are under `packages/ai-parrot/src/parrot/`
- ~~`zai-sdk` version with GLM-5.2-specific features~~ — 0.2.3 already accepts
  `thinking` and `reasoning_effort`; no SDK code changes exist or are needed

---

## Implementation Notes

### Pattern to Follow
Match the existing enum block style exactly (models/zai.py:11-27) and the
existing frozenset entries (models/zai.py:35-52). Two-line change in
clients/zai.py — attribute values only.

### Key Constraints
- Pure additive/registry change; do NOT touch any method body.
- Keep the `*_FREE` members at the bottom of the enum (existing convention).
- pyproject: change ONLY the two `zai-sdk` version strings; no other deps.

### References in Codebase
- `packages/ai-parrot/src/parrot/models/zai.py` — the enum + set to edit
- `packages/ai-parrot/src/parrot/clients/zai.py:27-29` — the defaults to bump

---

## Acceptance Criteria

- [ ] `ZaiModel.GLM_5_2.value == "glm-5.2"` and `"glm-5.2" in THINKING_CAPABLE_ZAI_MODELS`
- [ ] `ZaiClient.model == "glm-5.2"` and `ZaiClient._default_model == "glm-5.2"`
- [ ] `ZaiClient._lightweight_model` unchanged (`glm-4.5-flash:free`)
- [ ] `grep -c "zai-sdk>=0.2.3" packages/ai-parrot/pyproject.toml` → 2; no `>=0.2.2` left
- [ ] Existing Z.ai client tests still pass:
      `pytest packages/ai-parrot/tests/ -k "zai" -v` (source `.venv/bin/activate` first)
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/models/zai.py packages/ai-parrot/src/parrot/clients/zai.py`

---

## Test Specification

> Full registry tests land in TASK-1696 (`test_glm_5_2_in_enum_and_thinking_capable`,
> `test_zai_client_default_model_is_glm_5_2`). For THIS task a smoke check suffices:

```python
# Run inline (not committed) after implementing:
from parrot.models.zai import ZaiModel, THINKING_CAPABLE_ZAI_MODELS
from parrot.clients.zai import ZaiClient
assert ZaiModel.GLM_5_2.value == "glm-5.2"
assert "glm-5.2" in THINKING_CAPABLE_ZAI_MODELS
assert ZaiClient.model == ZaiClient._default_model == "glm-5.2"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm line anchors still match; if code moved, update the contract FIRST
4. **Update status** in `sdd/tasks/index/zai-client-code.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1692-zai-model-registry.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-03
**Notes**: Added `ZaiModel.GLM_5_2 = "glm-5.2"` above `GLM_5_1` (newest-first
ordering preserved), added it to `THINKING_CAPABLE_ZAI_MODELS`, bumped
`ZaiClient.model` / `ZaiClient._default_model` to `glm-5.2` (left
`_lightweight_model` untouched), and tightened both `zai-sdk` pins in
`packages/ai-parrot/pyproject.toml` to `>=0.2.3`. Verified via inline smoke
script, `pytest packages/ai-parrot/tests/test_zai_client.py -v` (4 passed),
and `ruff check` on both modified source files (clean). All acceptance
criteria satisfied.

**Deviations from spec**: none
