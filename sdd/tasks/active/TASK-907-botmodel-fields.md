# TASK-907: Add reranker_config + parent_searcher_config to BotModel

**Feature**: FEAT-133 — DB-Persisted Reranker & Parent-Searcher Config for AI Bots
**Spec**: `sdd/specs/bot-reranker-and-parent-searcher-config.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`BotModel` (`packages/ai-parrot/src/parrot/handlers/models/bots.py`) is the
datamodel mirror of `navigator.ai_bots`. It must declare the two new
JSONB-backed fields so values can be loaded, serialized, and roundtripped
through the handler endpoints. Implements spec section 3 / Module 4.

---

## Scope

- Add two `dict` fields to `BotModel`, immediately after `vector_store_config`
  (line 208 area):
  - `reranker_config` with `default_factory=dict`, `required=False`,
    `ui_help` referencing FEAT-126.
  - `parent_searcher_config` with `default_factory=dict`, `required=False`,
    `ui_help` referencing FEAT-128.
- Extend `BotModel.to_bot_config()` (line 304) to include both keys in the
  returned dict.

**NOT in scope**:
- Validation of `type` values inside the dicts — happens at factory call time
  (TASK-905, TASK-906).
- DDL changes — TASK-904.
- Manager / handler wiring — TASK-908 / TASK-910.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/handlers/models/bots.py` | MODIFY | Add fields + extend `to_bot_config` |
| `packages/ai-parrot/tests/handlers/test_bot_model_fields.py` | CREATE | Light field-presence + roundtrip test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already present in models/bots.py — no new imports needed
from datamodel import Model, Field      # used by BotModel
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/handlers/models/bots.py:208
vector_store_config: dict = Field(
    default_factory=dict,
    required=False,
    ui_help="The bot's vector store configuration."
)

# packages/ai-parrot/src/parrot/handlers/models/bots.py:304
def to_bot_config(self) -> dict:
    """Convert model instance to bot configuration dictionary."""
    return {
        ...
        'vector_store_config': self.vector_store_config,         # line 330
        ...
    }
```

### Does NOT Exist
- ❌ `BotModel.reranker_config` — to be added.
- ❌ `BotModel.parent_searcher_config` — to be added.
- ❌ Any Pydantic validator on these dicts — out of scope (validation is
  deferred to factory call time per spec §3 Module 6).

---

## Implementation Notes

### Required field declarations (verbatim per spec §3 Module 4)
```python
reranker_config: dict = Field(
    default_factory=dict,
    required=False,
    ui_help="The bot's reranker config (FEAT-126). See sdd/specs/bot-reranker-and-parent-searcher-config.spec.md.",
)
parent_searcher_config: dict = Field(
    default_factory=dict,
    required=False,
    ui_help="The bot's parent-searcher config (FEAT-128).",
)
```

### `to_bot_config()` change
Add inside the returned dict (after `vector_store_config`):
```python
'reranker_config':        self.reranker_config,
'parent_searcher_config': self.parent_searcher_config,
```

### Key Constraints
- Place the new fields IMMEDIATELY AFTER `vector_store_config` to keep the
  retrieval-config block contiguous.
- Use `default_factory=dict` (not `default={}`) so each instance gets its
  own dict, not a shared mutable.
- `enable_vector_store` / `disable_vector_store` helpers (line 365+) MUST
  remain unchanged.

### References in Codebase
- `models/bots.py:208` — pattern: `vector_store_config` declaration.
- `models/bots.py:304-341` — `to_bot_config` body.

---

## Acceptance Criteria

- [ ] `BotModel.reranker_config` and `BotModel.parent_searcher_config` exist
  with `default_factory=dict`, `required=False`, and informative `ui_help`.
- [ ] `BotModel().reranker_config == {}` and is independent across instances
  (mutating one does not affect a second `BotModel()`).
- [ ] `BotModel().to_bot_config()` returns a dict containing both keys with
  values equal to the model's fields.
- [ ] Roundtrip: `BotModel(**existing_payload)` succeeds when payload omits
  the two keys (back-compat) and when it includes them.
- [ ] `pytest packages/ai-parrot/tests/handlers/test_bot_model_fields.py -v`
  passes.
- [ ] `ruff check packages/ai-parrot/src/parrot/handlers/models/bots.py` clean.
- [ ] Maps to spec AC2.

---

## Test Specification

```python
# packages/ai-parrot/tests/handlers/test_bot_model_fields.py
from parrot.handlers.models.bots import BotModel


def test_default_empty_dicts():
    m = BotModel(name="t1")
    assert m.reranker_config == {}
    assert m.parent_searcher_config == {}


def test_independent_default_dicts():
    m1 = BotModel(name="t1")
    m2 = BotModel(name="t2")
    m1.reranker_config["type"] = "llm"
    assert m2.reranker_config == {}


def test_to_bot_config_contains_new_keys():
    cfg = BotModel(name="t1").to_bot_config()
    assert "reranker_config" in cfg
    assert "parent_searcher_config" in cfg
    assert cfg["reranker_config"] == {}
    assert cfg["parent_searcher_config"] == {}


def test_payload_with_configs_roundtrips():
    payload = {
        "name": "t1",
        "reranker_config": {"type": "llm"},
        "parent_searcher_config": {"type": "in_table", "expand_to_parent": True},
    }
    m = BotModel(**payload)
    assert m.reranker_config == {"type": "llm"}
    assert m.parent_searcher_config["expand_to_parent"] is True
```

---

## Agent Instructions

1. Read spec section 3 (Module 4).
2. Verify the Codebase Contract by reading `models/bots.py:200-345`.
3. Update `tasks/.index.json` → `"in-progress"`.
4. Add the two fields and extend `to_bot_config()`.
5. Add the test file, run `pytest` until green.
6. `ruff check` the modified file.
7. Move this file to `tasks/completed/` and update the index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
