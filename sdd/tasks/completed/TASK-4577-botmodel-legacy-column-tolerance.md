# TASK-4577: Restore BotModel legacy-column tolerance via a kwargs fold

**Feature**: FEAT-716 — models-bots-fixes
**Spec**: `sdd/specs/models-bots-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:e949b22a9681` (ledger, severity major) — "BotModel lost its
legacy-column tolerance: hydration raises on model_name/embedding_model (4 red tests)"

---

## Context

`BotModel` declares `Meta.strict = True`, so a row hydrated from an `ai_bots`
table that still carries the pre-fold columns (`model_name`, `temperature`,
`max_tokens`, `top_k`, `top_p`, `embedding_model`) raises
`BotModel.__init__() got an unexpected keyword argument 'model_name'`.
Commit `fd6748e669` deleted both the legacy `Field` declarations and the
`__post_init__` folding block; the fold migrations are applied on `dev` but
pending on staging/prod — exactly where the tolerance is needed.

This task implements spec §2 / Module 1: restore the tolerance at the
**kwargs** level so the dropped columns are never re-declared as model fields
(spec §7 Known Risks — `asyncdb` would put a re-declared column into the
`INSERT ... RETURNING` clause and break every environment where the fold
migration already dropped it).

---

## Scope

- Add `_fold_legacy_bot_columns(kwargs: dict) -> None` and
  `_tolerate_legacy_columns(model_cls: type) -> type` to
  `packages/ai-parrot/src/parrot/models/bots.py`, plus the two legacy-name
  constants.
- Apply `@_tolerate_legacy_columns` to `class BotModel`.
- Add the two regression tests of spec §4 to
  `packages/ai-parrot/tests/handlers/test_bot_model_fields.py`.

**NOT in scope**: re-declaring any legacy column as a `Field`; editing
`__post_init__`'s validation logic; `to_bot_config()`; the fold migrations;
`ChatbotUsage` / `ChatbotFeedback` / `PromptLibrary` / `create_bot`; the
reverse drift direction (`toolkit_config` missing on an un-migrated table).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/bots.py` | MODIFY | add `functools.wraps` import, the two constants, the two helpers, and the class decorator on `BotModel` |
| `packages/ai-parrot/tests/handlers/test_bot_model_fields.py` | MODIFY | add the two regression tests (AC5, caller-dict immutability) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.models.bots import BotModel           # verified: packages/ai-parrot/src/parrot/models/bots.py:25
from parrot.handlers.models.bots import BotModel  # verified re-export: packages/ai-parrot-server/src/parrot/handlers/models/bots.py:9
from datamodel import Field                       # verified: packages/ai-parrot/src/parrot/models/bots.py:14
from asyncdb.models import Model                  # verified: packages/ai-parrot/src/parrot/models/bots.py:15
from functools import wraps                       # stdlib
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/models/bots.py
from typing import List, Optional                  # line 9
# Chatbot Model:                                   # line 24
class BotModel(Model):                             # line 25
    name: str = Field(required=True)               # line 108
    model_config: dict = Field(                    # line 163
    vector_store_config: dict = Field(             # line 200
    def __post_init__(self) -> None:               # line 259
        super(BotModel, self).__post_init__()      # line 260 (unique in file)
        if self.model_config is None:              # line 262
    class Meta:                                    # line 361
        strict = True                              # line 367
```

```python
# packages/ai-parrot/tests/handlers/test_bot_model_fields.py
from parrot.handlers.models.bots import BotModel                      # line 12
def test_no_legacy_columns_leaves_model_config_untouched() -> None:   # line 118 (last test in file)
```

### Does NOT Exist

- ~~`BotModel.model_name`~~, ~~`.temperature`~~, ~~`.max_tokens`~~, ~~`.top_k`~~,
  ~~`.top_p`~~, ~~`.embedding_model`~~ — removed by `fd6748e669`; verified absent
  from `BotModel.__fields__`. **Do not re-add them.**
- ~~`Field(..., exclude=True)`~~ / ~~`Field(..., persist=False)`~~ — datamodel
  0.11.0 has no declare-but-never-persist marker.
- ~~a class-body `BotModel.__init__`~~ — `dataclasses.dataclass(init=True)`
  (`datamodel/abstract.py:462`) skips generating `__init__` when one already
  exists in the class body, which breaks field initialization. The wrapper
  MUST be applied as a class decorator, after class creation.
- ~~`BotModel.add_field()`~~ — raises `TypeError` on a strict model
  (`datamodel/base.py:68-71`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/models/bots.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/handlers/test_bot_model_fields.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/models/bots.py#BotModel",
    "sym:packages/ai-parrot/src/parrot/models/bots.py#BotModel.__post_init__"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- `_fold_legacy_bot_columns` mutates the `kwargs` dict in place but must COPY a
  caller-supplied `model_config` / `vector_store_config` before adding keys.
- `setdefault` semantics: an explicitly supplied JSONB key always wins.
- `model_name` is written under BOTH `model_name` and `model` (callers read either).
- Tolerate `model_config=None` / `vector_store_config=None` in the kwargs —
  `__post_init__` normalizes `None` to `{}` afterwards.
- No-op fast path when no legacy key is present, so
  `test_no_legacy_columns_leaves_model_config_untouched` keeps passing.
- Keep the explanatory comment: future readers must know why the columns are
  deliberately NOT fields.
- 120-column lines, Google-style docstrings, `black` formatting.

### References in Codebase

- `fd6748e669` — the commit that removed the previous (field-based) implementation.
- `.venv/lib/python3.12/site-packages/asyncdb/drivers/pg.py:1296-1348` — proof that
  every model column lands in the `RETURNING` clause.
- `.venv/lib/python3.12/site-packages/datamodel/abstract.py:462` — the `dataclass()`
  call that would be bypassed by a class-body `__init__`.

---

## Implementation Blueprint

### Steps (in order)

1. Add `from functools import wraps` to the imports — *why*: the wrapper must keep
   the generated `__init__`'s metadata.
2. Insert the constants and the two helpers immediately above `# Chatbot Model:`
   (line 24) — *why*: the decorator must be defined before the class statement.
3. Decorate `class BotModel(Model):` with `@_tolerate_legacy_columns` — *why*: it
   runs after `ModelMeta` built the dataclass `__init__`.
4. Append the two regression tests to the test file — *why*: AC5 pins "no new
   column", and the caller-dict test pins the copy-on-write semantics.

### `packages/ai-parrot/src/parrot/models/bots.py` (MODIFY — imports)

```python
# occurrences: 1 (verified: grep -c 'from typing import List, Optional' packages/ai-parrot/src/parrot/models/bots.py)
# AFTER — insert below `from typing import List, Optional` (verified: bots.py:9)
from functools import wraps
```

**Why**: `wraps` is the only new import; everything else the helpers need is a builtin.

### `packages/ai-parrot/src/parrot/models/bots.py` (MODIFY — helpers + decorator)

```python
# occurrences: 1 (verified: grep -c '^# Chatbot Model:' packages/ai-parrot/src/parrot/models/bots.py)
# BEFORE — insert above `# Chatbot Model:` (verified: bots.py:24)

# --- Legacy-column tolerance (schema drift) --------------------------------
# The canonical home for all LLM tuning is the ``model_config`` JSONB column,
# and the embedding model lives at ``vector_store_config['embedding_model']``.
# Older ``navigator.ai_bots`` tables still carry the pre-fold standalone
# columns, and a row hydrated from such a table reaches ``BotModel`` as
# unexpected keyword arguments, which ``Meta.strict = True`` rejects.
#
# They are folded out of ``**kwargs`` instead of being declared as fields on
# purpose: a declared column is emitted in the driver's
# ``INSERT ... RETURNING`` clause even when its value is skipped, so an
# environment that already ran the fold migrations would fail every write with
# ``column "model_name" does not exist``. Run
# ``sdd/migrations/FEAT-fold-legacy-llm-columns.sql`` and
# ``sdd/migrations/FEAT-fold-embedding-model-into-vector-store-config.sql``
# to retire the columns in an environment that still has them.
_LEGACY_LLM_COLUMNS = ("model_name", "temperature", "max_tokens", "top_k", "top_p")
_LEGACY_EMBEDDING_COLUMN = "embedding_model"


def _fold_legacy_bot_columns(kwargs: dict) -> None:
    """Fold the legacy ``ai_bots`` columns found in *kwargs* into the canonical JSONB.

    Mutates *kwargs* in place: every non-null legacy LLM-tuning scalar is moved
    into ``model_config`` (``model_name`` is mirrored to the ``model`` key as
    well, since callers read either), and ``embedding_model`` is moved into
    ``vector_store_config['embedding_model']``. An explicitly supplied JSONB key
    always wins, and a caller-owned dict is copied rather than mutated.

    Args:
        kwargs: The keyword arguments about to be passed to ``BotModel.__init__``.
    """
    legacy = {name: kwargs.pop(name, None) for name in _LEGACY_LLM_COLUMNS}
    embedding_model = kwargs.pop(_LEGACY_EMBEDDING_COLUMN, None)
    if not any(value is not None for value in legacy.values()) and not embedding_model:
        return

    model_config = dict(kwargs.get("model_config") or {})
    for key, value in legacy.items():
        if value is not None:
            model_config.setdefault(key, value)
    if legacy["model_name"] is not None:
        model_config.setdefault("model", legacy["model_name"])
    kwargs["model_config"] = model_config

    if embedding_model:
        vector_store_config = dict(kwargs.get("vector_store_config") or {})
        vector_store_config.setdefault("embedding_model", embedding_model)
        kwargs["vector_store_config"] = vector_store_config


def _tolerate_legacy_columns(model_cls: type) -> type:
    """Wrap ``model_cls.__init__`` so legacy columns fold instead of raising.

    Must be applied as a class decorator — i.e. after ``ModelMeta`` generated
    the dataclass ``__init__`` — because ``dataclasses.dataclass(init=True)``
    skips generating ``__init__`` when the class body already defines one.

    Args:
        model_cls: The strict datamodel class to make tolerant.

    Returns:
        The same class, with a folding ``__init__`` wrapper installed.
    """
    original_init = model_cls.__init__

    @wraps(original_init)
    def __init__(self, *args, **kwargs) -> None:  # noqa: N807
        _fold_legacy_bot_columns(kwargs)
        original_init(self, *args, **kwargs)

    model_cls.__init__ = __init__
    return model_cls

```

**Why this shape**: implements spec §2 Overview verbatim. The decorator placement
and the "no new field" rule are the two things that must NOT change — they are
AC5 and the mitigation for spec §7's write-path risk. `setdefault` is what makes
AC3/AC4 ("explicit wins") true.

### `packages/ai-parrot/src/parrot/models/bots.py` (MODIFY — decorate the class)

```python
# occurrences: 1 (verified: grep -c '^class BotModel(Model):' packages/ai-parrot/src/parrot/models/bots.py)
# REPLACE the line `class BotModel(Model):` (verified: bots.py:25) with:
@_tolerate_legacy_columns
class BotModel(Model):
```

**Why**: the only wiring step; everything else in the class is untouched.

### `packages/ai-parrot/tests/handlers/test_bot_model_fields.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'def test_no_legacy_columns_leaves_model_config_untouched' packages/ai-parrot/tests/handlers/test_bot_model_fields.py)
# AFTER — append below the body of `test_no_legacy_columns_leaves_model_config_untouched` (verified: test_bot_model_fields.py:118)


def test_legacy_columns_are_not_model_fields() -> None:
    """The legacy names are tolerated as kwargs but must never become columns.

    A declared column is emitted in the driver's ``INSERT ... RETURNING``
    clause, which would break every environment where the fold migrations
    already dropped it.
    """
    for name in ("model_name", "temperature", "max_tokens", "top_k", "top_p", "embedding_model"):
        assert name not in BotModel.__fields__
        assert name not in BotModel.__columns__


def test_legacy_fold_does_not_mutate_caller_dict() -> None:
    """Folding a legacy column must not mutate the caller's model_config dict."""
    caller_config = {"temperature": 0.9}
    m = BotModel(name="legacy", model_name="gemini-2.5-pro", model_config=caller_config)
    assert caller_config == {"temperature": 0.9}
    assert m.model_config["model_name"] == "gemini-2.5-pro"
    assert m.model_config["temperature"] == 0.9
```

**Why**: AC5 and the copy-on-write constraint are the two facts the pre-existing
tests do not cover.

### FILL IN checklist

- [ ] none — every block is complete as written.

---

## Acceptance Criteria

- [ ] AC1 — `pytest packages/ai-parrot/tests/handlers/test_bot_model_fields.py -q`
      fully green (13 passed; was 4 failed / 7 passed).
- [ ] AC2 — the six legacy kwargs construct a `BotModel` without raising and land
      in `model_config` (plus the `model` mirror).
- [ ] AC3 — an explicit `model_config` key is not overwritten by its legacy column.
- [ ] AC4 — `embedding_model` folds into `vector_store_config["embedding_model"]`.
- [ ] AC5 — no legacy name appears in `BotModel.__fields__` / `__columns__`.
- [ ] AC6 — `ruff check` clean on both changed files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/handlers/test_bot_model_fields.py -q`

---

## Test Specification

No new test file: the 4 red tests in
`packages/ai-parrot/tests/handlers/test_bot_model_fields.py` are the gate, and the
two tests in the blueprint above are appended to that same file.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug models-bots-fixes --feature-id FEAT-716`)
2. **Read the spec** at `sdd/specs/models-bots-fixes.spec.md`
3. **Check dependencies** — none
4. **Verify the Codebase Contract** before writing code; fix the contract first if stale
5. **Update status** to `"in-progress"` in `sdd/tasks/index/models-bots-fixes.json`
6. **Implement** the blueprint blocks verbatim
7. **Verify** every AC — run the Validation Command with
   `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the two files this task lists
9. **Close** with `scripts/sdd/close_task.sh TASK-4577 models-bots-fixes verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: agent:sdd-fix (Claude Code session 778adf37)
**Date**: 2026-10-22
**Notes**: Implemented the blueprint verbatim. `_LEGACY_LLM_COLUMNS` /
`_LEGACY_EMBEDDING_COLUMN`, `_fold_legacy_bot_columns()` and
`_tolerate_legacy_columns()` were inserted above `# Chatbot Model:`, `wraps` was
added to the imports, and `@_tolerate_legacy_columns` now decorates `BotModel`.
Two regression tests were appended to
`packages/ai-parrot/tests/handlers/test_bot_model_fields.py`.

Evidence:
- `pytest packages/ai-parrot/tests/handlers/test_bot_model_fields.py -q` →
  **13 passed** (baseline at `2ab46ff16` was 4 failed / 7 passed). AC1 ✅
- AC2 `BotModel(name='x', model_name='m', temperature=0.1, max_tokens=8192,
  top_k=41, top_p=0.9).model_config` →
  `{'model_name': 'm', 'temperature': 0.1, 'max_tokens': 8192, 'top_k': 41,
  'top_p': 0.9, 'model': 'm'}` ✅
- AC3 explicit `model_config={'model_name': 'gemini-2.5-flash'}` survives a
  `model_name='gpt-4.5'` kwarg ✅
- AC4 `embedding_model` folds into `vector_store_config['embedding_model']`, and
  an explicit `vector_store_config['embedding_model']` wins ✅
- AC5 none of the six legacy names is in `BotModel.__fields__`,
  `BotModel.__columns__`, or `BotModel.model(dialect='sql')` ✅
- AC6 `ruff check` clean on both files ✅
- Blast radius: 33 passed / 3 skipped (ai-parrot BotModel consumers) and
  24 passed (ai-parrot-server, incl. the FEAT-621 `test_storage_gates.py` AC17
  "ai_bots untouched" gate).

Known gotcha hit while validating: a bare `pytest` inside a worktree cannot
import `parrot.utils.types` / `parrot.utils.parsers.toml` — the Cython `.so`
files exist only in the main checkout. They were copied into the worktree
(gitignored, not committed).

**Deviations from spec**: none.

Note for a future reader: `black --check` still reports this file as needing a
reformat. That deviation is **pre-existing** (a stray blank line after the
imports, verified by running `black --check` on `HEAD:…/bots.py`), untouched by
this task, and deliberately not fixed so the diff stays minimal. `ruff check` —
the lint gate — is clean.
