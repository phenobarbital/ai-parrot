---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [botmodel, schema-drift, ledger-fix]
---

# Feature Specification: Restore BotModel legacy-column tolerance (without re-declaring the columns)

**Feature ID**: FEAT-716
**Date**: 2026-10-22
**Author**: agent:sdd-fix
**Status**: approved
**Target version**: current

---

## 1. Motivation & Business Requirements

### Problem Statement

`BotModel` (`packages/ai-parrot/src/parrot/models/bots.py`) declares
`Meta.strict = True`. A row hydrated from an `ai_bots` table that still carries
the **pre-fold** LLM-tuning columns (`model_name`, `temperature`, `max_tokens`,
`top_k`, `top_p`) or the pre-fold `embedding_model` column arrives as unexpected
keyword arguments and raises:

```
BotModel.__init__() got an unexpected keyword argument 'model_name'
```

The tolerance used to exist: commit `fd6748e669` ("fix botmodel") deleted both
the six legacy `Field` declarations and the `__post_init__` folding block. The
fold migrations (`sdd/migrations/FEAT-fold-legacy-llm-columns.sql`,
`sdd/migrations/FEAT-fold-embedding-model-into-vector-store-config.sql`) are
applied on `dev` but **pending on staging/prod** — exactly the environments
that still need the tolerance.

`packages/ai-parrot/tests/handlers/test_bot_model_fields.py` still encodes the
expected behaviour: 4 tests are red on `origin/dev` (`2ab46ff16`).

Ledger issue: `issue:e949b22a9681` (major, bug).

### Goals

- Hydrating a `BotModel` from a row that still has the legacy columns must not
  raise under `Meta.strict = True`.
- Legacy LLM-tuning values must fold into the canonical `model_config` JSONB
  (and `model_name` must also be mirrored to the `model` key), never
  overwriting an explicitly supplied `model_config` key.
- A legacy `embedding_model` value must fold into
  `vector_store_config['embedding_model']`.
- The tolerance must NOT re-introduce the six legacy columns as model fields,
  because an environment where the fold migrations already ran would then
  break on write (see §7 Known Risks).

### Non-Goals (explicitly out of scope)

- Running or changing the fold migrations.
- Touching `ChatbotUsage`, `ChatbotFeedback`, `PromptLibrary` or `create_bot`.
- The reverse drift direction (`column "toolkit_config" does not exist` on an
  un-migrated table) — a separate concern, not this feature.
- Any change to `to_bot_config()` output.

---

## 2. Architectural Design

### Overview

Fold the legacy keys out of the constructor keyword arguments **before** the
dataclass-generated `__init__` sees them, instead of declaring them as fields.

A module-level class decorator, applied to `BotModel`, wraps the generated
`__init__`: it pops the legacy keys from `**kwargs`, merges their non-null
values into the `model_config` / `vector_store_config` keyword arguments
(`setdefault` semantics, so an explicit value always wins), and then delegates
to the original `__init__`.

The decorator runs *after* `ModelMeta` has built the dataclass, so the
generated `__init__` still exists — defining `__init__` in the class body is
NOT an option: `dataclasses.dataclass(init=True)` skips generation when
`__init__` is already in `cls.__dict__`, which breaks all field initialization
(verified empirically: `TypeError: Model.__init__() got an unexpected keyword
argument 'name'`).

### Component Diagram

```
BotModel(**row)
   │
   ├─ ModelMeta.__call__      (datamodel: alias handling)
   │
   ├─ _tolerate_legacy_columns wrapper  ← NEW
   │     └─ _fold_legacy_bot_columns(kwargs)
   │            legacy scalars ──→ kwargs["model_config"]
   │            embedding_model ──→ kwargs["vector_store_config"]
   │
   └─ dataclass __init__ ──→ BotModel.__post_init__ (unchanged)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `BotModel` | decorates | class decorator wraps the generated `__init__` |
| `BotModel.__post_init__` | unchanged | still normalizes `model_config` to `{}` |
| `parrot.handlers.models.bots` | re-export | inherits the behaviour, no edit needed |

### Data Models

No new models. Two module-level constants:

```python
_LEGACY_LLM_COLUMNS = ("model_name", "temperature", "max_tokens", "top_k", "top_p")
_LEGACY_EMBEDDING_COLUMN = "embedding_model"
```

### New Public Interfaces

None. Both helpers are module-private.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: legacy-column fold | yes | exact helper names, signatures, fold semantics and decorator placement fixed below | — |

### Module 1: Legacy-column fold for `BotModel`

- **Path**: `packages/ai-parrot/src/parrot/models/bots.py`
- **Responsibility**: Accept the pre-fold `ai_bots` columns as constructor
  kwargs and fold them into the canonical JSONB columns, without declaring
  them as model fields.
- **Depends on**: nothing new (`functools.wraps` from the stdlib).
- **Interface Skeleton** *(signatures + docstrings only)*:

  ```python
  # packages/ai-parrot/src/parrot/models/bots.py  (modifies; inserted above `class BotModel` at line 25)
  def _fold_legacy_bot_columns(kwargs: dict) -> None:
      """Pop the legacy ``ai_bots`` columns from *kwargs* into the canonical JSONB.

      Mutates *kwargs* in place: the legacy LLM-tuning scalars fold into
      ``model_config`` (``model_name`` is mirrored to ``model`` as well) and
      ``embedding_model`` folds into ``vector_store_config['embedding_model']``.
      An explicitly supplied JSONB key always wins; a caller-owned dict is
      copied rather than mutated. A no-op when no legacy key is present.
      """

  def _tolerate_legacy_columns(model_cls: type) -> type:
      """Wrap ``model_cls.__init__`` so legacy columns fold instead of raising.

      Applied as a class decorator, i.e. after ``ModelMeta`` generated the
      dataclass ``__init__``; declaring ``__init__`` in the class body would
      suppress that generation entirely.
      """
  ```

---

## 4. Test Specification

### Unit Tests

The 4 red tests in `packages/ai-parrot/tests/handlers/test_bot_model_fields.py`
already specify the behaviour and are the gate — no new test file is created.
Two regression tests are ADDED to the same file for the two facts the old
implementation did not cover:

| Test | Module | Description |
|---|---|---|
| `test_legacy_columns_do_not_raise_under_strict` | M1 | existing — the 6 legacy kwargs construct cleanly |
| `test_legacy_columns_fold_into_model_config` | M1 | existing — scalars backfill `model_config` + the `model` mirror |
| `test_explicit_model_config_wins_over_legacy_column` | M1 | existing — explicit JSONB key is not overwritten |
| `test_legacy_embedding_model_folds_into_vector_store_config` | M1 | existing — `embedding_model` backfills `vector_store_config` |
| `test_no_legacy_columns_leaves_model_config_untouched` | M1 | existing — no spurious keys without legacy columns |
| `test_legacy_columns_are_not_model_fields` | M1 | NEW — `"model_name" not in BotModel.__fields__` / `__columns__`, so generated SQL never names a dropped column |
| `test_legacy_fold_does_not_mutate_caller_dict` | M1 | NEW — the caller's `model_config` dict is not mutated by the fold |

### Integration Tests

None — this is a constructor-level change with no I/O.

### Validation Contract

tests:
- packages/ai-parrot/tests/handlers/test_bot_model_fields.py
markers: none

### Test Data / Fixtures

None — the tests construct `BotModel` directly.

---

## 5. Acceptance Criteria

- [ ] AC1 — `pytest packages/ai-parrot/tests/handlers/test_bot_model_fields.py`
      is fully green (was 4 failed / 7 passed at `2ab46ff16`).
- [ ] AC2 — `BotModel(name="x", model_name="m", temperature=0.1, max_tokens=8192,
      top_k=41, top_p=0.9)` does not raise, and `model_config` carries
      `model_name`, `temperature`, `max_tokens`, `top_k`, `top_p` plus the
      `model` mirror.
- [ ] AC3 — an explicit `model_config={"model_name": ...}` is NOT overwritten by
      the legacy `model_name` kwarg.
- [ ] AC4 — `embedding_model` folds into
      `vector_store_config["embedding_model"]` without clobbering an existing key.
- [ ] AC5 — none of the six legacy names appears in `BotModel.__fields__` or
      `BotModel.__columns__` (no new persisted column, so the generated
      `INSERT ... RETURNING` clause stays unchanged).
- [ ] AC6 — `ruff check` clean on the changed files.

---

## 6. Codebase Contract

> Verified against `origin/dev` = `2ab46ff16`.

### Verified Imports

```python
from parrot.models.bots import BotModel           # verified: packages/ai-parrot/src/parrot/models/bots.py:25
from parrot.handlers.models.bots import BotModel  # verified re-export: packages/ai-parrot-server/src/parrot/handlers/models/bots.py:9
from datamodel import Field                       # verified: bots.py:14
from asyncdb.models import Model                  # verified: bots.py:15
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/models/bots.py
class BotModel(Model):                             # line 25
    name: str = Field(required=True)               # line 108
    model_config: dict = Field(                    # line 163
    vector_store_config: dict = Field(             # line 200
    def __post_init__(self) -> None:               # line 259
        super(BotModel, self).__post_init__()      # line 260  (unique in file)
        if self.model_config is None:              # line 262
    class Meta:                                    # line 361
        strict = True                              # line 367
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_tolerate_legacy_columns` | `BotModel.__init__` | class decorator wrapping the generated `__init__` | `bots.py:25` |
| `_fold_legacy_bot_columns` | `model_config` / `vector_store_config` kwargs | dict `setdefault` on `**kwargs` | `bots.py:163`, `bots.py:200` |

### Does NOT Exist (Anti-Hallucination)

- ~~`BotModel.model_name`~~ / `temperature` / `max_tokens` / `top_k` / `top_p` /
  `embedding_model` — removed by `fd6748e669`; they are NOT fields and this
  feature must not re-add them.
- ~~`Field(..., exclude=True)`~~ / ~~`Field(..., persist=False)`~~ — datamodel
  0.11.0 has no "declare but never persist" marker; the pg driver puts every
  entry of `_model.columns()` into the `RETURNING` clause
  (`.venv/lib/python3.12/site-packages/asyncdb/drivers/pg.py:1296-1348`).
- ~~a class-body `BotModel.__init__`~~ — `dataclasses.dataclass(init=True)`
  (applied by `ModelMeta`, `datamodel/abstract.py:462`) skips generating
  `__init__` when one is already defined, which breaks field initialization.
- ~~`BotModel.add_field()`~~ — raises `TypeError` on a strict model
  (`datamodel/base.py:68-71`).

### Edit Sites (Blueprint Anchors)

> Verified against `2ab46ff16`.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/models/bots.py` | MODIFY | `# Chatbot Model:` immediately followed by `class BotModel(Model):` | `bots.py:24-25` | 1 |
| `packages/ai-parrot/src/parrot/models/bots.py` | MODIFY | `from typing import List, Optional` | `bots.py:9` | 1 |
| `packages/ai-parrot/tests/handlers/test_bot_model_fields.py` | MODIFY | `def test_no_legacy_columns_leaves_model_config_untouched() -> None:` | `test_bot_model_fields.py:118` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Google-style docstrings, strict type hints, 120-column lines, `black`
  formatting (`.claude/rules/codebase-conventions.md`).
- `functools.wraps` on the wrapper so the generated `__init__` metadata survives.
- Copy a caller-supplied JSONB dict before adding folded keys — never mutate
  the caller's object.
- Keep the explanatory comment that `fd6748e669` deleted: future readers must
  know the fold exists for un-migrated environments and why the columns are
  deliberately not fields.

### Known Risks / Gotchas

- **Re-declaring the columns is the trap.** `asyncdb`'s pg `_insert_` appends
  *every* model column to the `RETURNING` clause regardless of whether its
  value was skipped (`pg.py:1296-1348`), so a re-declared `model_name` would
  raise `column "model_name" does not exist` on `dev`/any environment where the
  fold migrations already dropped it — i.e. the exact failure direction already
  reported in production for `toolkit_config`. Mitigation: kwargs-level
  tolerance only; AC5 pins it.
- The fold must run before `ModelMeta.__call__` delegates to
  `type.__call__` → `__init__`. Wrapping `__init__` satisfies that; alias
  handling in `ModelMeta.__call__` (`datamodel/abstract.py:515`) runs first and
  does not touch these names (`BotModel.__aliases__` has no legacy entry).
- `BotModel.__post_init__` still coerces `model_config is None` to `{}`; the
  fold must therefore tolerate `model_config=None` in the kwargs.

### External Dependencies

None new.

---

## 8. Open Questions

None — behaviour is fully specified by the existing red tests.

---

## 9. Design Research Cross-Check

> Status: skipped (single-file restoration of previously-shipped behaviour,
> driven by 4 pre-existing red tests; no design space to explore).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-22 | agent:sdd-fix | Initial draft from `issue:e949b22a9681` |
