# TASK-501: Fix YAML agent definition vector store key mismatch

**Feature**: chatbot-rag-api-integration
**Spec**: `sdd/specs/chatbot-rag-api-integration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-500
**Assigned-to**: unassigned

---

## Context

> When bots are loaded from YAML agent definitions, the vector store config is
> passed through two paths with a **key mismatch**:
>
> 1. `_parse_agent_definition()` stores it as `merged_args['vector_store_config']`
>    but does NOT set `use_vectorstore=True`.
> 2. `AgentDefinition.instantiate()` pops `vector_store` (not `vector_store_config`)
>    from kwargs — so it never finds the config from path 1.
>
> TASK-500's auto-detection fix in `configure()` is the safety net, but this task
> fixes the registry to propagate the flag correctly so bots are initialized with
> the right state from the start.
>
> Implements spec Module 2.

---

## Scope

- In `AgentRegistry._parse_agent_definition()` (~line 640-642): when `config.vector_store` is present, also set `merged_args['use_vectorstore'] = True`.
- In `AgentDefinition.instantiate()` (~line 130): also check for `vector_store_config` key when extracting vector store conf (handle both `vector_store` and `vector_store_config` keys).
- Write unit tests for both fixes.

**NOT in scope**: Changing `configure()` (that's TASK-500). Changing the HTTP handler. Changing the StoreConfig model.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/registry/registry.py` | MODIFY | Fix `_parse_agent_definition()` (~line 640) and `AgentDefinition.instantiate()` (~line 130) |
| `packages/ai-parrot/tests/registry/test_vector_store_propagation.py` | CREATE | Unit tests |

---

## Implementation Notes

### Fix 1: `_parse_agent_definition()` (~line 640)

```python
# Current (broken):
if config.vector_store:
    merged_args['vector_store_config'] = config.vector_store.dict()

# Fixed:
if config.vector_store:
    merged_args['vector_store_config'] = config.vector_store.dict()
    merged_args['use_vectorstore'] = True
```

### Fix 2: `AgentDefinition.instantiate()` (~line 130)

```python
# Current (broken):
vector_store_conf = merged_kwargs.pop('vector_store', None)

# Fixed — check both keys:
vector_store_conf = merged_kwargs.pop('vector_store', None) or merged_kwargs.pop('vector_store_config', None)
```

### Key Constraints
- Must preserve backwards compatibility with both key names
- The `instantiate()` fix at lines 163-168 already correctly applies the config and sets `_use_vector = True` — it just never fires because it doesn't find the config
- After the fix, the `_apply_store_config()` + `_use_vector = True` path in `instantiate()` will fire correctly

### References in Codebase
- `packages/ai-parrot/src/parrot/registry/registry.py:125-170` — AgentDefinition.instantiate()
- `packages/ai-parrot/src/parrot/registry/registry.py:620-650` — _parse_agent_definition()
- `packages/ai-parrot/src/parrot/interfaces/vector.py:25-40` — _apply_store_config()

---

## Acceptance Criteria

- [ ] YAML agent definition with `vector_store:` section produces a bot with `_use_vector = True`
- [ ] `AgentDefinition.instantiate()` finds vector store config regardless of key name (`vector_store` or `vector_store_config`)
- [ ] Existing bots that use `vector_store` key directly still work
- [ ] All existing tests pass

---

## Test Specification

```python
# packages/ai-parrot/tests/registry/test_vector_store_propagation.py
import pytest
from unittest.mock import patch, MagicMock


class TestParseAgentDefinitionVectorStore:
    """Test that _parse_agent_definition propagates use_vectorstore."""

    def test_vector_store_sets_use_vectorstore(self):
        """When vector_store is in YAML config, use_vectorstore must be True."""
        # Create a mock AgentConfig with vector_store
        # Verify merged_args contains use_vectorstore=True
        pass

    def test_no_vector_store_no_flag(self):
        """When no vector_store in config, use_vectorstore should not be set."""
        pass


class TestAgentDefinitionInstantiate:
    """Test AgentDefinition handles both key names."""

    def test_instantiate_with_vector_store_key(self):
        """Should find config under 'vector_store' key."""
        pass

    def test_instantiate_with_vector_store_config_key(self):
        """Should find config under 'vector_store_config' key."""
        pass
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/chatbot-rag-api-integration.spec.md` for full context
2. **Check dependencies** — verify TASK-500 is completed
3. **Update status** in `tasks/.index.json` → `"in-progress"`
4. **Implement** the two fixes in `registry.py` and write the tests
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-501-fix-registry-vector-store-propagation.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-04-01
**Notes**: Fixed both issues:
1. `create_agent_factory()` now sets `use_vectorstore=True` AND uses `dataclasses.asdict()` instead of `.dict()` (StoreConfig is a dataclass, not Pydantic model).
2. `BotMetadata.get_instance()` now handles both `vector_store` and `vector_store_config` keys with `or` fallback.
All 5 registry tests pass.

**Deviations from spec**: Fixed an additional pre-existing bug — `config.vector_store.dict()` fails because StoreConfig is a dataclass. Replaced with `dataclasses.asdict(config.vector_store)`.
