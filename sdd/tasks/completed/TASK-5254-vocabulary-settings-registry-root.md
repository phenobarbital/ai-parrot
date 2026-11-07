# TASK-5254: Vocabulary settings, backend registry and lazy package root

**Feature**: FEAT-824 — Ontology backend: PostgreSQL OntologyStore + SurrealDB programme
**Spec**: `sdd/specs/ontology-backend.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5253
**Assigned-to**: unassigned

---

## Context

Spec Module 3, second half. Adds the `ONTOLOGY_*` settings resolver, the name-keyed backend
registry (`create_ontology_store`) and the package root `__init__.py` with the **complete** lazy
export table, so no later task edits `__init__.py` and importing the package loads neither
`asyncpg` nor `rdflib` (spec §7 "Import ceilings").

---

## Scope

- `vocabulary/settings.py` — `OntologyStoreSettings`, `resolve_ontology_settings` (spec lines 704–718;
  keys and defaults from the spec §2 settings table, lines 525–534).
- `vocabulary/backends.py` — `VocabularyBackendSpec`, `register_vocabulary_backend`,
  `vocabulary_backend_names`, `create_ontology_store`, with built-ins registered at import:
  `postgres` → `parrot.knowledge.ontology.vocabulary.postgres_store:_create_postgres`
  (extra `ontology-store`), `snapshot` → `parrot.knowledge.ontology.vocabulary.snapshot:_create_snapshot`
  (extra `ontology-store`). Factories are imported only on first use.
- `vocabulary/__init__.py` — PEP 562 lazy root exposing the spec §2 "New Public Interfaces" names
  plus the exceptions and `OntologyStoreSettings`/`resolve_ontology_settings`.
- Tests: `test_vocabulary_settings.py`, `test_vocabulary_backends.py`, `test_vocabulary_import.py`.

**NOT in scope**: the `postgres_store` / `snapshot` / `publisher` modules (later tasks — the lazy
table may name them before they exist; the tests must not resolve those names).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/settings.py` | CREATE | settings resolver |
| `packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/backends.py` | CREATE | registry |
| `packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/__init__.py` | CREATE | lazy root |
| `packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_vocabulary_settings.py` | CREATE | precedence + schema-name |
| `packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_vocabulary_backends.py` | CREATE | registry behaviour |
| `packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_vocabulary_import.py` | CREATE | import is light |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.project import resolve_setting   # verified: parrot/knowledge/wiki/project.py:864 — import INSIDE the function
from parrot._imports import lazy_import                     # verified: parrot/_imports.py:110 (used by graphindex/backends.py:15)
from parrot.knowledge.ontology.vocabulary.contracts import OntologyStore            # TASK-5253
from parrot.knowledge.ontology.vocabulary.exceptions import VocabularyError         # TASK-5253
# tests:
from ..._support.import_probe import run_import_probe   # verified: packages/ai-parrot/tests/knowledge/_support/import_probe.py:55
```

### Existing Signatures to Use
```python
# parrot/knowledge/wiki/project.py:864
def resolve_setting(key: str, *, default: Any = None, explicit: Any = None,
                    project_defaults: Mapping[str, Any] | None = None) -> Any:
    # explicit → os.environ → navconfig → project_defaults → default; None = "not provided"

# parrot/_imports.py:110
def lazy_import(module_path: str, package_name: str | None = None, extra: str | None = None) -> ModuleType

# parrot/knowledge/graphindex/backends.py   (PATTERN ONLY — do not import graphindex, spec §7 "Sequencing")
class GraphBackendSpec(BaseModel): name; factory ("module:callable"); required_options; capabilities; extra  # :22
def graph_backend_spec(name) -> GraphBackendSpec  # :62 — ValueError "Unknown graph backend 'x'; known: a, b"
def _import_factory(spec) -> Any                   # :80 — missing third-party module → lazy_import(missing, extra=spec.extra)

# parrot/knowledge/graphindex/pg_schema.py:30-48   (PATTERN ONLY)
_VALID_SCHEMA_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")

# parrot/knowledge/ontology/__init__.py:5-56 — _LAZY_ATTRS dict + __all__ + __getattr__ caching in globals() + __dir__
# packages/ai-parrot/tests/knowledge/_support/import_probe.py:55
def run_import_probe(module: str, *, forbidden: tuple[str, ...] = FORBIDDEN) -> ImportProbeResult  # .error, .has(name)
```

### Does NOT Exist
- ~~`create_ontology_store` as async~~ — it is **sync** (spec line 732); unlike `create_graph_persistence`.
- ~~`parrot.knowledge.ontology.vocabulary.postgres_store` / `.snapshot` / `.publisher`~~ — later tasks;
  never import them at module level here.
- ~~a module-level `import asyncpg` / `import rdflib` / `import numpy`~~ — forbidden in these three files.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/settings.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/backends.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_vocabulary_settings.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_vocabulary_backends.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_vocabulary_import.py", "action": "CREATE"}
  ],
  "contract_symbols": ["sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#resolve_setting", "sym:packages/ai-parrot/src/parrot/_imports.py#lazy_import"]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. `settings.py` — *why*: resolved at call time, never at import (FEAT-520 convention).
2. `backends.py` with the two built-ins — *why*: registry by name, never `if backend ==` (spec §7).
3. `__init__.py` lazy table — *why*: written once with every public name so later tasks never edit it.
4. Tests; ruff; run the import-ceiling suites from the Validation Commands.

### `.../vocabulary/settings.py` (CREATE)
```python
"""ONTOLOGY_* settings for the vocabulary store, resolved at call time (FEAT-824)."""
from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel

_VALID_SCHEMA_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")


class OntologyStoreSettings(BaseModel):
    """Resolved ONTOLOGY_* settings (spec §2 settings table)."""

    backend: str = "postgres"
    dsn: str | None = None
    schema_name: str = "ontology_store"
    embedding_dim: int = 1024
    ann_index_kind: str = "hnsw"
    snapshot_dir: Path = Path("~/.parrot/ontology")
    snapshot_url: str | None = None
    default_lang: str = "es"


def resolve_ontology_settings(*, backend: str | None = None, dsn: str | None = None,
                              schema: str | None = None) -> OntologyStoreSettings:
    """Resolve settings via resolve_setting (explicit → env → navconfig → default).

    Raises:
        ValueError: when the schema name is not a plain SQL identifier, or ann_index_kind is not hnsw|ivfflat.
    """
    from parrot.knowledge.wiki.project import resolve_setting  # verified: wiki/project.py:864; lazy on purpose

    # FILL IN: resolve each key (ONTOLOGY_BACKEND, ONTOLOGY_PG_DSN, ONTOLOGY_PG_SCHEMA,
    #          ONTOLOGY_EMBEDDING_DIM (int), ONTOLOGY_ANN_INDEX_KIND, ONTOLOGY_SNAPSHOT_DIR
    #          (Path, expanduser), ONTOLOGY_SNAPSHOT_URL, ONTOLOGY_DEFAULT_LANG); validate the
    #          schema name with _VALID_SCHEMA_NAME and ann kind ∈ {hnsw, ivfflat}.
    raise NotImplementedError
```

### `.../vocabulary/backends.py` (CREATE)
```python
"""Name-keyed registry of vocabulary-store backends with lazy factories (FEAT-824)."""
from __future__ import annotations

import importlib
from typing import Any

from pydantic import BaseModel

from parrot._imports import lazy_import  # verified: parrot/_imports.py:110
from parrot.knowledge.ontology.vocabulary.contracts import OntologyStore


class VocabularyBackendSpec(BaseModel):
    """Registry entry — same shape as GraphBackendSpec (graphindex/backends.py:22)."""

    name: str
    factory: str
    required_options: tuple[str, ...] = ()
    extra: str | None = None


_REGISTRY: dict[str, VocabularyBackendSpec] = {}


def register_vocabulary_backend(spec: VocabularyBackendSpec) -> None:
    """Register or replace a backend spec. Built-ins: 'postgres', 'snapshot'."""
    _REGISTRY[spec.name] = spec


def vocabulary_backend_names() -> tuple[str, ...]:
    """Registered names in registration order."""
    return tuple(_REGISTRY)


def create_ontology_store(backend: str | None = None, **options: Any) -> OntologyStore:
    """Build a store; backend defaults to the ONTOLOGY_BACKEND setting.

    Raises:
        ValueError: unknown backend (message lists known names) or a missing required option.
        ImportError: a driver is absent; the message names the extra.
    """
    # FILL IN: resolve backend via resolve_ontology_settings when None; look up the spec;
    #          check required_options; import factory as graphindex/backends.py:_import_factory does
    #          (missing non-parrot module → lazy_import(missing, extra=spec.extra)); return factory(**options).
    raise NotImplementedError


register_vocabulary_backend(VocabularyBackendSpec(
    name="postgres", factory="parrot.knowledge.ontology.vocabulary.postgres_store:_create_postgres",
    extra="ontology-store"))
register_vocabulary_backend(VocabularyBackendSpec(
    name="snapshot", factory="parrot.knowledge.ontology.vocabulary.snapshot:_create_snapshot",
    extra="ontology-store"))
```

### `.../vocabulary/__init__.py` (CREATE)
```python
"""Ontology vocabulary store: versioned RDF vocabularies on PostgreSQL with SQLite snapshots (FEAT-824)."""
from typing import Any

_P = "parrot.knowledge.ontology.vocabulary"
_LAZY_ATTRS: dict[str, str] = {
    **{n: f"{_P}.contracts" for n in (
        "OntologyStore", "OntologyPublisher", "ConceptRef", "Resolution", "PublishResult", "StoreStatus",
        "OntologyContent", "VersionContent", "PublishDiff", "ValidationIssue", "ClosureRow")},
    **{n: f"{_P}.exceptions" for n in (
        "VocabularyError", "OntologyNotFound", "OntologyVersionNotFound", "OntologyValidationError",
        "PublishConflict")},
    **{n: f"{_P}.backends" for n in (
        "create_ontology_store", "register_vocabulary_backend", "VocabularyBackendSpec", "vocabulary_backend_names")},
    "OntologyStoreSettings": f"{_P}.settings",
    "resolve_ontology_settings": f"{_P}.settings",
    "PostgresOntologyStore": f"{_P}.postgres_store",
    "PostgresOntologyPublisher": f"{_P}.publisher",
    "SnapshotOntologyStore": f"{_P}.snapshot",
}
__all__ = sorted(_LAZY_ATTRS)


def __getattr__(name: str) -> Any:
    """Resolve a public export on first access and cache it (pattern: parrot/knowledge/ontology/__init__.py:30)."""
    # FILL IN: copy the body of parrot/knowledge/ontology/__init__.py:__getattr__ (lines 42-50).
    raise NotImplementedError


def __dir__() -> list[str]:
    """Expose lazy exports to ``dir()``."""
    return sorted(set(globals()) | set(__all__))
```

### Tests (CREATE) — required cases
```python
# test_vocabulary_settings.py
def test_settings_precedence(monkeypatch): ...      # explicit > env > default; ONTOLOGY_PG_SCHEMA honoured
def test_bad_schema_name_rejected(): ...            # resolve_ontology_settings(schema="Bad-Name") → ValueError
# test_vocabulary_backends.py
def test_builtin_names(): ...                       # vocabulary_backend_names()[:2] == ("postgres", "snapshot")
def test_registry_unknown_backend(): ...            # create_ontology_store("nope") → ValueError naming known backends
def test_registered_fake_backend(): ...             # register a spec pointing at a test-module factory; it is built
# test_vocabulary_import.py
from ..._support.import_probe import run_import_probe
def test_package_import_is_light():
    result = run_import_probe("parrot.knowledge.ontology.vocabulary")
    assert result.error is None
    assert not result.has("asyncpg") and not result.has("rdflib") and not result.has("numpy")
```

### FILL IN checklist
- [ ] `resolve_ontology_settings` body.
- [ ] `create_ontology_store` body.
- [ ] `__getattr__` body.
- [ ] test bodies.

---

## Acceptance Criteria

- [ ] `create_ontology_store("nope")` raises `ValueError` naming the known backends.
- [ ] Importing `parrot.knowledge.ontology.vocabulary` loads neither `asyncpg`, `rdflib` nor `numpy`.
- [ ] `test_lazy_package_roots.py` and `test_import_ceilings.py` still pass.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_vocabulary_settings.py -q`
- `pytest packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_vocabulary_backends.py -q`
- `pytest packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_vocabulary_import.py -q`
- `pytest packages/ai-parrot/tests/knowledge/test_lazy_package_roots.py -q`
- `pytest packages/ai-parrot/tests/knowledge/test_import_ceilings.py -q`

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-5253 is `done`.
2. Verify the Codebase Contract; mark `in-progress`; implement from the blueprint.
3. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`; commit only the listed files.
4. Close with `parrot sdd task close TASK-5254 ontology-backend verified`; fill in the Completion Note.

---

## Completion Note

Seat: gpt-5.6-sol · Backend: codex · Attempts: 1 · Duration: 252s. Merge-tier validation green.

**Completed by**: sdd-worker (coder: gpt-5.6-sol)
**Date**: 2026-11-07
**Notes**:

**Deviations from spec**: none
