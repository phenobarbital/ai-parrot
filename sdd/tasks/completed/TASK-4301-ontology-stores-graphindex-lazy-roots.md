# TASK-4301: Lazy ontology, stores and graphindex package roots

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4300
**Assigned-to**: unassigned

---

## Context

Spec §3 M1. `ontology/__init__.py:2-7` eagerly imports `.mixin` (reaches `parrot.auth`); `stores/__init__.py:5` imports `.abstract` whose line 7 is `from navconfig.logging import logging`; `graphindex/__init__.py:16-61` eagerly imports communities/export_html/signals/persist_sqlite/projection/sqlite_reader/odoo_code. All three become PEP 562 roots.

---

## Scope

- `ontology/__init__.py`: lazy root with identical `__all__`.
- `stores/__init__.py`: keep `__path__ = extend_path(...)` and `supported_stores` eager; `AbstractStore` lazy.
- `graphindex/__init__.py`: move every eager re-export except `schema` (cheap pydantic models) into `_LAZY_ATTRS`; cache in `globals()`; add `__dir__`.
- Tests: names resolve; expensive submodules absent after importing the cheap ones; `supported_stores` unchanged (incl. `lancedb`); `wiki.documents` does not import `aiohttp` at module import (regression for documents.py:583).

**NOT in scope**: Removing framework imports from the graph modules themselves (M2/M6/M7 tasks); renaming `OntologyGraphStore` (TASK-4328).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/__init__.py` | MODIFY | PEP 562 root |
| `packages/ai-parrot/src/parrot/stores/__init__.py` | MODIFY | PEP 562 root, extend_path eager |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/__init__.py` | MODIFY | eager exports → _LAZY_ATTRS |
| `packages/ai-parrot/tests/knowledge/test_lazy_package_roots.py` | CREATE | root behaviour tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cf6316096` on 2026-10-14. Re-verify before writing code.

### Verified Imports
```python
from parrot.knowledge.ontology.schema import EnrichedContext, MergedOntology, ResolvedIntent, TenantContext  # schema.py — re + pydantic only
from parrot.stores.abstract import AbstractStore  # stores/abstract.py (navconfig.logging at :7)
```

### Existing Signatures to Use
```python
# ontology/__init__.py:2-7 eager: cache, graph_store(:3), intent, mixin(:5), schema, tenant; __all__ :9-19
# stores/__init__.py: :1 from pkgutil import extend_path; :3 __path__ = extend_path(__path__, __name__); :5 AbstractStore; :8 supported_stores = {...}
# graphindex/__init__.py: eager :16-61; __all__ :63-111; _LAZY_ATTRS :118-130; __getattr__ :133 (no caching, no __dir__)
# wiki/__init__.py:56-120 — the precedent (cached __getattr__ + __dir__)
```

### Does NOT Exist
- ~~a cheap `parrot.stores.models` import path today — it executes `stores/__init__.py` until this lands~~
- ~~`graphindex.__dir__` (added here)~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/ontology/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/stores/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/graphindex/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/test_lazy_package_roots.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/schema.py#TenantContext",
    "sym:packages/ai-parrot/src/parrot/stores/abstract.py#AbstractStore"
  ]
}
```

---

## Implementation Notes

`extend_path` must stay eager or `ai-parrot-embeddings` PEP 420 backends stop resolving. `schema` exports in graphindex stay eager (pure models) — everything else goes lazy. Do not change what any name resolves to.

### Key Constraints
- Async-first; Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; strict type hints; 120 cols.
- Never import `requests`/`httpx`/`langchain`; no `print`. Hard cuts for renamed internals (no external consumers).
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. Convert ontology root — *why*: `ontology.schema` importers pay for `.mixin` today.
2. Convert stores root keeping extend_path/supported_stores eager — *why*: namespace merge + dispatch map must not change.
3. Move graphindex eager exports into `_LAZY_ATTRS`, add caching + `__dir__` — *why*: `import parrot.knowledge.graphindex` must stop loading communities/export/etc.
4. Write the tests using the probe — *why*: prove absence, not just presence.

### `packages/ai-parrot/src/parrot/knowledge/ontology/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from .mixin import OntologyRAGMixin' parrot/knowledge/ontology/__init__.py)
# AFTER/AT — anchor `from .mixin import OntologyRAGMixin` (verified: __init__.py:5)
# REPLACE lines 2-7 with a lazy map (keep __all__ :9-19 unchanged):
_LAZY_ATTRS: dict[str, str] = {
    "OntologyCache": "parrot.knowledge.ontology.cache",
    "OntologyGraphStore": "parrot.knowledge.ontology.graph_store",
    "OntologyIntentResolver": "parrot.knowledge.ontology.intent",
    "OntologyRAGMixin": "parrot.knowledge.ontology.mixin",
    "TenantOntologyManager": "parrot.knowledge.ontology.tenant",
    "EnrichedContext": "parrot.knowledge.ontology.schema",
    "MergedOntology": "parrot.knowledge.ontology.schema",
    "ResolvedIntent": "parrot.knowledge.ontology.schema",
    "TenantContext": "parrot.knowledge.ontology.schema",
}
# FILL IN: __getattr__ (cached) + __dir__ exactly as in parrot/auth/__init__.py (TASK-4300)
```
**Why**: Same pattern as the auth root; `OntologyGraphStore` stays exported under its current name until TASK-4328 adds `ArangoOntologyGraphStore`.

### `packages/ai-parrot/src/parrot/stores/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from .abstract import AbstractStore' parrot/stores/__init__.py)
# AFTER/AT — anchor `from .abstract import AbstractStore` (verified: __init__.py:5)
# REPLACE line 5 only; lines 1-3 (extend_path) and the supported_stores dict stay as they are:
def __getattr__(name: str):
    """Lazy AbstractStore (PEP 562) — stores/abstract.py:7 imports navconfig."""
    if name == "AbstractStore":
        from .abstract import AbstractStore

        globals()[name] = AbstractStore
        return AbstractStore
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
# FILL IN: add __all__ (AbstractStore, supported_stores) and __dir__ if the module has none today
```
**Why**: The 826-module cost is a single line (`abstract.py:7`); everything else in the root is cheap and must stay eager.

### `packages/ai-parrot/src/parrot/knowledge/graphindex/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence' parrot/knowledge/graphindex/__init__.py)
# AFTER/AT — anchor `from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence` (verified: __init__.py:53)
# REMOVE the eager imports of signals/communities/export_html/persist_sqlite/projection/sqlite_reader/odoo_code
# (lines ~31-61) and ADD their names to _LAZY_ATTRS (:118-130), e.g.:
#   "SQLitePersistence": "parrot.knowledge.graphindex.persist_sqlite",
#   "SQLiteGraphReader": "parrot.knowledge.graphindex.sqlite_reader",
#   "OdooCodeExtractor": "parrot.knowledge.graphindex.extractors.odoo_code",
#   "detect_communities": "parrot.knowledge.graphindex.communities", ...
# FILL IN: one entry per removed name — bounded by __all__ (:63-111) staying identical
# CHANGE __getattr__ (:133) to cache: globals()[name] = value; ADD __dir__ returning sorted(set(globals()) | set(__all__))
```
**Why**: Keep the `schema` import block (:16-29) eager — pure pydantic models every consumer needs.

### `packages/ai-parrot/tests/knowledge/test_lazy_package_roots.py` (CREATE)
```python
"""Lazy package roots (FEAT-540 M1)."""
import parrot.knowledge.graphindex as gi
import parrot.knowledge.ontology as ont
import parrot.stores as stores

from ._support.import_probe import run_import_probe


def test_roots_resolve_every_export() -> None:
    for mod in (gi, ont):
        for name in mod.__all__:
            assert getattr(mod, name) is not None, (mod.__name__, name)
    assert stores.AbstractStore is not None


def test_supported_stores_unchanged() -> None:
    assert "lancedb" in stores.supported_stores  # FILL IN: compare against the full dict captured from dev


def test_schema_import_skips_mixin_and_navconfig() -> None:
    # FILL IN: probe 'parrot.knowledge.ontology.schema'; assert 'parrot.knowledge.ontology.mixin' and 'parrot.stores.abstract' absent
    ...


def test_documents_defers_aiohttp() -> None:
    # FILL IN: probe 'parrot.knowledge.wiki.documents'; assert 'aiohttp' absent
    ...
```
**Why**: Absence assertions run in fresh interpreters through the probe.

### FILL IN checklist
- [ ] ontology root `__getattr__`/`__dir__`
- [ ] graphindex `_LAZY_ATTRS` entries for every removed eager name; bounded by identical `__all__`
- [ ] the three probe-based absence tests

---

## Acceptance Criteria

- [ ] `parrot.knowledge.ontology.schema` import no longer loads `ontology.mixin` or `stores.abstract`
- [ ] every `__all__` name of graphindex/ontology resolves; `supported_stores` identical
- [ ] `parrot.stores` namespace merge still exposes satellite backends (`from parrot.stores.pgvector import ...` unchanged)

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/test_lazy_package_roots.py -q`
- `pytest packages/ai-parrot/tests/knowledge/test_ontology_schema.py -q`

---

## Test Specification

```python
# see test_lazy_package_roots.py block
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug graphindex-core-seams --feature-id FEAT-540 --spec sdd/specs/graphindex-core-seams.spec.md --index sdd/tasks/index/graphindex-core-seams.json`)
2. **Read the spec** (`sdd/specs/graphindex-core-seams.spec.md`) — at least §2 and the module this task implements
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/graphindex-core-seams.json`
4. **Verify the Codebase Contract** — re-run `grep -c` for every anchor in the blueprint; a changed count means the
   anchor moved: re-locate it and fix the blueprint line before editing. A count of 0 means drift — stop and report.
5. **Update status** → `"in-progress"` (`started_at`) and commit only the index file
6. **Implement** from the Implementation Blueprint, completing every `# FILL IN:`; never change a fixed signature or path
7. **Validate** — `ruff check --fix <changed files>` and the Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src` (worktrees: the shared venv points at the main checkout)
8. **Commit code** — stage only the files listed above (never `git add .` / `-A`)
9. **Close** with `scripts/sdd/close_task.sh TASK-4301 graphindex-core-seams verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: codex gpt-5.6-terra, consolidated by sdd-worker
**Date**: 2026-10-15
**Notes**: Lazy PEP 562 roots for ontology, stores and graphindex packages + test_lazy_package_roots.py; no review corrections (coder-review recorded). Verification is `partial`: the engine merge-tier sandbox cannot reach Postgres and has pre-existing reds, so it is not recorded as green. With GRAPHINDEX_PG_DSN on local docker-postgres-1, tests/knowledge + tests/embeddings show no failure that is not also on clean origin/dev (3 tests/embeddings reds are pre-existing).

**Deviations from spec**: none
