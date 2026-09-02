# TASK-2719: Tests — Assert Fable in catalog and research_primary_models in /api/config

**Feature**: FEAT-494 — select-model-dev-flow-ideation-model
**Spec**: `sdd/specs/select-model-dev-flow-ideation-model.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2717, TASK-2718
**Assigned-to**: unassigned

---

## Context

TASK-2717 and TASK-2718 add new capabilities (Fable in the catalog,
`research_primary_models` in the server payload). This task adds targeted
regression-guarding tests in two existing test files to ensure the new keys
and models are present and remain correct going forward.

This task implements spec §3 Module 3.

---

## Scope

**In `packages/ai-parrot/tests/flows/dev_flow/test_server_dev_model_plan.py`**
(class `TestConfigPayload`):
- Add `test_research_primary_models_in_config_payload`: assert
  `defaults.model_plan.research_primary_models` is present and is a list.
- Add `test_fable_in_research_primary_models`: assert both
  `"claude-fable-5-1"` and `"claude-fable-5"` are in that list.
- Add `test_opus_still_in_research_primary_models`: assert `"claude-opus-5"`
  is still in the list (no regression).

**In `packages/ai-parrot/tests/flows/dev_loop/test_catalog.py`**:
- Add `test_research_primary_role_in_catalog_payload`: assert
  `catalog_payload()["roles"]["research_primary"]` is a non-empty list.
- Add `test_claude_code_is_research_primary_backend`: assert `"claude-code"`
  in `catalog_payload()["roles"]["research_primary"]`.
- Add `test_fable_in_claude_code_backend_models`: assert `"claude-fable-5-1"`
  and `"claude-fable-5"` are in the `claude-code` entry's `models` list
  from `catalog_payload()["backends"]`.

**NOT in scope**:
- `catalog.py` or `server_dev.py` implementation changes (TASK-2717, TASK-2718).
- Testing `dev.html` (browser-level testing is not in scope for this feature).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/flows/dev_flow/test_server_dev_model_plan.py` | MODIFY | Add 3 new test methods to `TestConfigPayload` |
| `packages/ai-parrot/tests/flows/dev_loop/test_catalog.py` | MODIFY | Add 3 new test functions |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# test_server_dev_model_plan.py — existing imports at top of file (verified: line 1-21)
from __future__ import annotations
import asyncio
import importlib.util
from pathlib import Path
from typing import Any
import pytest
from parrot.bots.flows.core.result import FlowResult
from parrot.bots.flows.core.types import FlowStatus
from parrot.flows.dev_flow.model_plan import DevFlowModelPlan
from parrot.flows.dev_flow.runner import DevFlowRunner

# test_catalog.py — check existing imports before modifying
# (read the file to confirm; the pattern will match test_server_dev_model_plan.py style)
from parrot.flows.dev_loop.catalog import catalog_payload
# verified: packages/ai-parrot/tests/flows/dev_loop/test_catalog.py:27
```

### Existing Signatures to Use

```python
# test_server_dev_model_plan.py — existing fixtures (lines 34-89)
@pytest.fixture(scope="module")
def server_dev():
    return _load_module("dev_flow_server_dev_plan", "server_dev.py")

@pytest.fixture
def make_client(server_dev, aiohttp_client):
    # Returns an async factory: await make_client() → aiohttp test client
    ...

# TestConfigPayload class (line 141) — existing async methods
@pytest.mark.asyncio
class TestConfigPayload:
    async def test_config_carries_plan_defaults(self, make_client): ...
    async def test_config_lists_selectable_backends(self, make_client): ...
    # ← new test methods go here, same signature pattern

# /api/config response shape (verified via existing tests):
# payload["defaults"]["model_plan"]["research_primary"]  → str
# payload["defaults"]["model_plan"]["pool_backends"]     → list[str]
# payload["backends"]                                    → list[dict] with .id, .models, etc.
# payload["roles"]                                       → dict (from catalog_payload)

# catalog_payload() return shape (packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py:524-541):
# {
#   "backends": [...],
#   "roles": {"development": [...], "judge": [...], ... },
#   "adversarial_backend": str,
#   ...
# }
```

### Does NOT Exist

- ~~`payload["defaults"]["model_plan"]["research_primary_models"]`~~ — does NOT exist until TASK-2718 is implemented; this test asserts it DOES exist post-implementation.
- ~~`catalog_payload()["roles"]["research_primary"]`~~ — does NOT exist until TASK-2717 is implemented; this test asserts it DOES exist post-implementation.
- ~~`TestConfigPayload.test_research_primary_models_in_config_payload`~~ — not yet in the file; this task adds it.

---

## Implementation Notes

### Pattern to Follow

Follow the existing `TestConfigPayload` async test pattern exactly:

```python
@pytest.mark.asyncio
class TestConfigPayload:
    # ... existing tests ...

    async def test_research_primary_models_in_config_payload(self, make_client):
        client = await make_client()
        plan = (await (await client.get("/api/config")).json())["defaults"]["model_plan"]
        assert "research_primary_models" in plan
        assert isinstance(plan["research_primary_models"], list)

    async def test_fable_in_research_primary_models(self, make_client):
        client = await make_client()
        plan = (await (await client.get("/api/config")).json())["defaults"]["model_plan"]
        assert "claude-fable-5-1" in plan["research_primary_models"]
        assert "claude-fable-5" in plan["research_primary_models"]

    async def test_opus_still_in_research_primary_models(self, make_client):
        client = await make_client()
        plan = (await (await client.get("/api/config")).json())["defaults"]["model_plan"]
        assert "claude-opus-5" in plan["research_primary_models"]
```

For `test_catalog.py`, follow the existing test function pattern (not a class):

```python
def test_research_primary_role_in_catalog_payload():
    payload = catalog_payload()
    assert "research_primary" in payload["roles"]
    assert len(payload["roles"]["research_primary"]) > 0

def test_claude_code_is_research_primary_backend():
    payload = catalog_payload()
    assert "claude-code" in payload["roles"]["research_primary"]

def test_fable_in_claude_code_backend_models():
    payload = catalog_payload()
    cc = next((b for b in payload["backends"] if b["id"] == "claude-code"), None)
    assert cc is not None, "claude-code backend not in catalog payload"
    assert "claude-fable-5-1" in cc["models"]
    assert "claude-fable-5" in cc["models"]
```

### Key Constraints

- Read `test_catalog.py` before editing to confirm whether tests are in a class
  or at module level, and whether `catalog_payload` is called with args. Use
  the existing pattern in that file.
- All new `TestConfigPayload` tests must be `async def` (the class is
  `@pytest.mark.asyncio`).
- Use the existing `make_client` fixture — do NOT create new fixture functions.

### References in Codebase

- `packages/ai-parrot/tests/flows/dev_flow/test_server_dev_model_plan.py:141-189` — `TestConfigPayload`
- `packages/ai-parrot/tests/flows/dev_loop/test_catalog.py` — existing catalog tests
- `packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py:507-541` — `catalog_payload()`

---

## Acceptance Criteria

- [ ] 3 new test methods added to `TestConfigPayload` in `test_server_dev_model_plan.py`.
- [ ] 3 new test functions added to `test_catalog.py`.
- [ ] `pytest packages/ai-parrot/tests/flows/dev_flow/test_server_dev_model_plan.py -v` — all pass.
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_catalog.py -v` — all pass.
- [ ] No existing tests broken.

---

## Test Specification

The test bodies are described in "Implementation Notes → Pattern to Follow" above.
The six new tests cover: presence of `research_primary_models` key, Fable ids in
that list, Opus not regressed, `research_primary` role in catalog, `claude-code`
in that role, Fable in claude-code backend models.

---

## Agent Instructions

When you pick up this task:

1. **Confirm TASK-2717 and TASK-2718 are in `sdd/tasks/completed/`.**
2. **Read `test_catalog.py`** to identify the existing import pattern and
   whether tests are class-based or module-level.
3. **Read `test_server_dev_model_plan.py` lines 141-189** to confirm `TestConfigPayload`
   class and `make_client` fixture shape before editing.
4. Add the 3 new async test methods to `TestConfigPayload`.
5. Add the 3 new test functions to `test_catalog.py`.
6. Run both test files and confirm all pass.
7. Commit: `test(FEAT-494): assert Fable in catalog and research_primary_models in config`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
