# TASK-906: Implement parrot/stores/parents/factory.py

**Feature**: FEAT-133 — DB-Persisted Reranker & Parent-Searcher Config for AI Bots
**Spec**: `sdd/specs/bot-reranker-and-parent-searcher-config.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Bots loaded from the DB need a way to instantiate an
`AbstractParentSearcher` from a JSONB config dict. This task creates the
factory + tests. Implements spec section 3 / Module 2.

Sequencing nuance: the parent-searcher factory takes the bot's already-built
`store` as a kwarg (mandatory for `type=in_table`). The manager will call this
factory AFTER `bot.configure(app)`. That sequencing is handled by TASK-908;
this task only delivers the factory.

---

## Scope

- Create `packages/ai-parrot/src/parrot/stores/parents/factory.py` exposing
  `create_parent_searcher(config: dict, *, store: AbstractStore) -> Optional[AbstractParentSearcher]`.
- Internal builder `_build_in_table(config, store)`.
- Module-level `PARENT_SEARCHER_TYPES` registry mapping `type` → builder.
- Empty-dict guard returns `None`.
- Missing or unknown `type` raises `ConfigError`.
- `store=None` for a type that requires it raises `ConfigError`.
- Unit tests at `packages/ai-parrot/tests/stores/parents/test_factory.py`.

**NOT in scope**:
- New parent-searcher implementations.
- BotManager wiring (TASK-908).
- Reading or interpreting the `expand_to_parent` flag — the factory does not
  forward it to the searcher; the manager forwards it as a separate kwarg
  to the bot constructor.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/stores/parents/factory.py` | CREATE | `create_parent_searcher` + builder + registry |
| `packages/ai-parrot/tests/stores/parents/test_factory.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Verified 2026-04-29
from typing import Callable, Optional
from parrot.exceptions import ConfigError                            # exceptions.py:45
from parrot.stores.parents.abstract import AbstractParentSearcher    # parents/abstract.py:20
from parrot.stores.abstract import AbstractStore
# Heavy imports — keep INSIDE the builder:
#   from parrot.stores.parents.in_table import InTableParentSearcher  # in_table.py:64
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/stores/parents/in_table.py:83
class InTableParentSearcher(AbstractParentSearcher):
    def __init__(self, store: AbstractStore) -> None: ...

# packages/ai-parrot/src/parrot/stores/parents/abstract.py:20
class AbstractParentSearcher(ABC): ...
```

### Does NOT Exist
- ❌ `parrot.stores.parents.factory` — to be created by this task.
- ❌ `InTableParentSearcher.__init__(config=..., store=...)` — the constructor
  takes `store` only, no config kwarg.
- ❌ Any `expand_to_parent` attribute on `InTableParentSearcher` — the flag
  lives on the bot (`AbstractBot.expand_to_parent`), NOT on the searcher.

---

## Implementation Notes

### Reference signature (from spec §2)
```python
def create_parent_searcher(
    config: dict,
    *,
    store: AbstractStore,
) -> Optional[AbstractParentSearcher]:
    """Instantiate a parent searcher from a config dict.

    Empty dict ⇒ returns None.
    Missing or unknown 'type' ⇒ raises ConfigError.
    type that needs a store while store is None ⇒ raises ConfigError.
    """
```

### Config shape (spec §2)
```jsonc
{
  "type": "in_table",
  "expand_to_parent": true   // NOT consumed here — the manager forwards it
                             // to the bot constructor.
}
```

### Key Constraints
- Builder for `type=in_table` MUST require `store is not None` and raise
  `ConfigError("in_table parent searcher requires store")` otherwise.
- Lazy import `InTableParentSearcher` inside the builder.
- Google-style docstrings + full type hints.
- `logger = logging.getLogger(__name__)`.

### References in Codebase
- `parrot/rerankers/__init__.py:30-50` — lazy-import pattern.
- `parrot/stores/parents/in_table.py:64-90` — `InTableParentSearcher` ctor.

---

## Acceptance Criteria

- [ ] `parrot.stores.parents.factory.create_parent_searcher` exists with the
  signature above.
- [ ] `create_parent_searcher({}, store=fake_store)` returns `None`.
- [ ] `create_parent_searcher({"type": "in_table"}, store=fake_store)`
  returns an `InTableParentSearcher` instance.
- [ ] `create_parent_searcher({"type": "in_table"}, store=None)` raises
  `ConfigError` matching `"requires store"`.
- [ ] `create_parent_searcher({"type": "magic"}, store=fake_store)` raises
  `ConfigError` matching `"unknown parent searcher type"`.
- [ ] `create_parent_searcher({}, store=fake_store)` returning None does
  NOT consult the registry (empty-dict guard short-circuits).
- [ ] All unit tests pass:
  `pytest packages/ai-parrot/tests/stores/parents/test_factory.py -v`.
- [ ] `ruff check packages/ai-parrot/src/parrot/stores/parents/factory.py` clean.
- [ ] Maps to spec AC4.

---

## Test Specification

```python
# packages/ai-parrot/tests/stores/parents/test_factory.py
import pytest
from parrot.exceptions import ConfigError
from parrot.stores.parents.factory import create_parent_searcher


class FakeStore:
    """Stand-in for AbstractStore — minimal shape, no DB."""
    pass


@pytest.fixture
def fake_store():
    return FakeStore()


def test_empty_config_returns_none(fake_store):
    assert create_parent_searcher({}, store=fake_store) is None


def test_in_table_returns_instance(fake_store):
    s = create_parent_searcher({"type": "in_table"}, store=fake_store)
    from parrot.stores.parents.in_table import InTableParentSearcher
    assert isinstance(s, InTableParentSearcher)
    assert s.store is fake_store


def test_in_table_requires_store():
    with pytest.raises(ConfigError, match="requires store"):
        create_parent_searcher({"type": "in_table"}, store=None)


def test_missing_type_raises(fake_store):
    with pytest.raises(ConfigError, match="missing 'type'"):
        create_parent_searcher({"expand_to_parent": True}, store=fake_store)


def test_unknown_type_raises(fake_store):
    with pytest.raises(ConfigError, match="unknown parent searcher type"):
        create_parent_searcher({"type": "magic"}, store=fake_store)
```

---

## Agent Instructions

1. Read spec section 3 (Module 2).
2. Verify the Codebase Contract.
3. Update `tasks/.index.json` → `"in-progress"`.
4. Implement `factory.py` with lazy import for `InTableParentSearcher`.
5. Add tests, run them green.
6. `ruff check packages/ai-parrot/src/parrot/stores/parents/factory.py`.
7. Move this file to `tasks/completed/` and update the index.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (SDD Worker)
**Date**: 2026-04-29
**Notes**: Created `parrot/stores/parents/factory.py` with `create_parent_searcher()`, `_build_in_table()`, and `PARENT_SEARCHER_TYPES` registry. Lazy import for `InTableParentSearcher` inside builder. Empty-dict guard short-circuits before store check. Created `tests/stores/parents/test_factory.py` with 8 tests (all passed). ruff clean.

**Deviations from spec**: none
