# TASK-3257: Lazy `ontology` + `stores` package roots and lazy `aiohttp` in `wiki/documents.py`

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3256
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 1, second step**. After TASK-3256 removes gateway #1
(`parrot.auth`), two eager package roots still tax every graph import:

- `parrot/knowledge/ontology/__init__.py` eagerly imports `.mixin`
  (`OntologyRAGMixin`), `.cache`, `.graph_store`, `.intent`, `.tenant`. Every
  `from parrot.knowledge.ontology.schema import …` (nine call sites in
  `graphindex/`) executes that root. `ontology.schema` itself imports only
  `re`, `datetime`, `typing`, `pydantic` — measured floor 124 modules, today 1600.
- `parrot/stores/__init__.py` eagerly imports `.abstract.AbstractStore`, whose
  line 7 `from navconfig.logging import logging` (plus `..conf`) costs the
  whole 826 modules of `from parrot.stores.models import Document`.
- `parrot/knowledge/wiki/documents.py:26` imports `aiohttp` at module level for
  one fetch path (`DocumentAcquirer._download`, lines 545-600).

Implements spec §4 `test_ontology_root_lazy`, `test_stores_root_lazy`,
`test_documents_aiohttp_lazy`, and activates the `ontology.schema` ceiling
case created by TASK-3256 (spec §5 AC 2: ≤ 240 modules).

---

## Scope

- Convert `packages/ai-parrot/src/parrot/knowledge/ontology/__init__.py` to a
  PEP 562 lazy root (same shape as TASK-3256's `parrot/auth/__init__.py`):
  `_LAZY_ATTRS` map, `__getattr__`, `__dir__`; `__all__` unchanged.
- Convert `packages/ai-parrot/src/parrot/stores/__init__.py`: keep
  `from pkgutil import extend_path` + `__path__ = extend_path(...)` and
  `supported_stores` **eager**; make `AbstractStore` lazy; add `__all__ = ["AbstractStore", "supported_stores"]`.
- Move `import aiohttp` in `wiki/documents.py` from module level into
  `DocumentAcquirer._download` (first statement of the body).
- Remove the `xfail` mark from the `ontology.schema` case in
  `packages/ai-parrot/tests/knowledge/test_import_ceilings.py`.
- Append `test_ontology_root_lazy`, `test_stores_root_lazy`,
  `test_documents_aiohttp_lazy` to `packages/ai-parrot/tests/knowledge/test_lazy_package_roots.py`.

**NOT in scope**:
- `parrot/stores/abstract.py` (its navconfig import stays; only the root stops paying it).
- `graphindex/extractors/loader.py` / `graphindex/loader.py` `parrot.stores.models` imports — TASK-3266.
- `graphindex/persist.py` `OntologyGraphStore` import — TASK-3267.
- The `graphindex`, `graphindex.builder`, `wiki.cli` ceiling cases — TASK-3268.
- Any change to `ontology/mixin.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/__init__.py` | MODIFY | PEP 562 lazy root |
| `packages/ai-parrot/src/parrot/stores/__init__.py` | MODIFY | PEP 562 lazy `AbstractStore`; `extend_path` + `supported_stores` stay eager |
| `packages/ai-parrot/src/parrot/knowledge/wiki/documents.py` | MODIFY | `import aiohttp` moves inside `_download` |
| `packages/ai-parrot/tests/knowledge/test_import_ceilings.py` | MODIFY | un-xfail `ontology.schema` |
| `packages/ai-parrot/tests/knowledge/test_lazy_package_roots.py` | MODIFY | add three tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.knowledge.ontology.schema import TenantContext, MergedOntology   # schema.py (imports: re, datetime, typing, pydantic)
from parrot.knowledge.ontology import OntologyRAGMixin                       # via root today; ontology/mixin.py
from parrot.stores import AbstractStore, supported_stores                    # stores/__init__.py:5,8
from parrot.stores.models import Document                                    # stores/models.py:19
import importlib                                                             # stdlib
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/ontology/__init__.py  — EAGER today (whole file)
"""Ontological Graph RAG — composable ontology-driven retrieval augmented generation."""  # line 1
from .cache import OntologyCache                                          # line 2
from .graph_store import OntologyGraphStore                               # line 3
from .intent import OntologyIntentResolver                                # line 4
from .mixin import OntologyRAGMixin                                       # line 5  ← the expensive one
from .schema import EnrichedContext, MergedOntology, ResolvedIntent, TenantContext  # line 6
from .tenant import TenantOntologyManager                                 # line 7
__all__ = ["OntologyCache", "OntologyGraphStore", "OntologyIntentResolver",
           "OntologyRAGMixin", "TenantOntologyManager", "EnrichedContext",
           "MergedOntology", "ResolvedIntent", "TenantContext"]           # lines 9-19

# packages/ai-parrot/src/parrot/stores/__init__.py  — EAGER today (whole file)
from pkgutil import extend_path                                           # line 1
__path__ = extend_path(__path__, __name__)                                # line 3  ← MUST stay eager (PEP 420 merge with ai-parrot-embeddings)
from .abstract import AbstractStore                                       # line 5  ← make lazy
supported_stores = {"postgres": "PgVectorStore", "milvus": "MilvusStore", "kb": "KnowledgeBaseStore",
    "faiss_store": "FaissStore", "arango": "ArangoStore", "bigquery": "BigQueryStore",
    "lancedb": "LanceDBStore"}                                            # lines 8-16

# packages/ai-parrot/src/parrot/stores/abstract.py
from navconfig.logging import logging                                     # line 7  ← the whole 826-module cost
from ..conf import (EMBEDDING_DEFAULT_MODEL)                              # line 8

# packages/ai-parrot/src/parrot/stores/models.py
from ..models.stores import SearchResult, StoreConfig                     # line 16 (parrot.models root = 244 modules, no heavy pkg)
class Document(BaseModel):                                                # line 19

# packages/ai-parrot/src/parrot/knowledge/wiki/documents.py
import aiohttp                                                            # line 26  ← make lazy
from parrot.knowledge.graphindex.extractors.loader import PLAIN_TEXT_EXTENSIONS  # module-level parrot import
class DocumentAcquisitionError(Exception): ...                            # line 146
class DocumentAcquirer: ...                                               # line 454
    async def _download(self, url: str) -> tuple[Path, str]:             # line 545
        timeout = aiohttp.ClientTimeout(total=self.fetch_timeout)         # line 568
        aiohttp.ClientSession(timeout=timeout) as session,                # line 573
        except (aiohttp.ClientError, TimeoutError) as exc:                # line 595
```

Measured (2026-09-15): `ontology.schema` 1600 modules; `stores.models` 826 (navconfig, parrot.conf, redis, asyncpg); `parrot.models` 244 (no heavy).

### Does NOT Exist
- ~~`__all__` in `parrot/stores/__init__.py`~~ — does not exist today; this task adds it.
- ~~A dependency-free `parrot.stores.models` today~~ — importing it executes the eager root until this task lands.
- ~~`parrot/knowledge/__init__.py` imports~~ — the file has no imports; not a gateway.
- ~~Tests for `wiki/documents.py` `_download`~~ — none found under `packages/*/tests`; do not look for a fixture to reuse.
- ~~`ontology/schema.py` importing framework code~~ — do not touch it.

---

## Implementation Notes

### Key Constraints
- **`extend_path` stays first and eager** — otherwise `parrot.stores.pgvector` etc. from `ai-parrot-embeddings` stop resolving (spec §7).
- `ontology/__init__.py` is imported by non-graph code (`OntologyRAGMixin`, `TenantOntologyManager` consumers): laziness must not change what they get (spec §7).
- `from parrot.stores import *` semantics: with `__all__` added, star-import yields `AbstractStore` (resolved through `__getattr__`) and `supported_stores` — same public set as before.
- In `_download`, the local `import aiohttp` must precede the `try:` so the `except (aiohttp.ClientError, …)` clause can reference the name.
- If `test_documents_aiohttp_lazy` still sees `aiohttp` loaded, find the chain with `python -X importtime -c "import parrot.knowledge.wiki.documents" 2>&1 | grep -n aiohttp` and report it — do not paper over it.

### References in Codebase
- TASK-3256's `packages/ai-parrot/src/parrot/auth/__init__.py` — the lazy-root shape to mirror.
- `packages/ai-parrot/src/parrot/knowledge/wiki/__init__.py:44-116` — original precedent.

---

## Implementation Blueprint

### Steps (in order)
1. Add the three failing tests to `test_lazy_package_roots.py` and un-xfail `ontology.schema` — *why*: TDD against the gate.
2. Rewrite `ontology/__init__.py` as a lazy root — *why*: `.mixin` is the expensive eager import (spec gateway table).
3. Rewrite `stores/__init__.py` keeping `extend_path` + `supported_stores` eager — *why*: namespace merge must keep working.
4. Move `import aiohttp` into `_download` — *why*: spec gateway #4.
5. Run `pytest packages/ai-parrot/tests/knowledge/test_import_ceilings.py packages/ai-parrot/tests/knowledge/test_lazy_package_roots.py packages/ai-parrot/tests/knowledge/test_ontology_*.py packages/ai-parrot/tests/knowledge/graphindex -q` and a stores smoke (`pytest packages/ai-parrot-embeddings/tests -q -k "import or registry"` if present) — *why*: non-graph consumers of both roots.

### `packages/ai-parrot/src/parrot/knowledge/ontology/__init__.py` (MODIFY — full rewrite, 19 lines today)
```python
# occurrences: 1 (verified: grep -c '^from .mixin import OntologyRAGMixin$' packages/ai-parrot/src/parrot/knowledge/ontology/__init__.py)
"""Ontological Graph RAG — composable ontology-driven retrieval augmented generation."""
import importlib
from typing import Any

# Name -> defining submodule (PEP 562 lazy root, FEAT-540). Importing
# ``parrot.knowledge.ontology.schema`` no longer executes ``.mixin``.
_LAZY_ATTRS: dict[str, str] = {
    "OntologyCache": ".cache",
    "OntologyGraphStore": ".graph_store",
    "OntologyIntentResolver": ".intent",
    "OntologyRAGMixin": ".mixin",
    "TenantOntologyManager": ".tenant",
    "EnrichedContext": ".schema",
    "MergedOntology": ".schema",
    "ResolvedIntent": ".schema",
    "TenantContext": ".schema",
}

__all__ = [
    "OntologyCache",
    "OntologyGraphStore",
    "OntologyIntentResolver",
    "OntologyRAGMixin",
    "TenantOntologyManager",
    "EnrichedContext",
    "MergedOntology",
    "ResolvedIntent",
    "TenantContext",
]


def __getattr__(name: str) -> Any:
    """Resolve a public export lazily on first attribute access (PEP 562).

    Args:
        name: Attribute requested on the package.

    Returns:
        The object defined in the owning submodule.

    Raises:
        AttributeError: If ``name`` is not a public export.
    """
    module_path = _LAZY_ATTRS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module_path, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Expose lazy exports to ``dir()`` and IDE completion."""
    return sorted(set(globals()) | set(__all__))
```
**Why this shape**: identical `__all__` (order preserved) and identical objects; only the time of import changes (spec §7).

### `packages/ai-parrot/src/parrot/stores/__init__.py` (MODIFY — full rewrite, 16 lines today)
```python
# occurrences: 1 (verified: grep -c '^from .abstract import AbstractStore$' packages/ai-parrot/src/parrot/stores/__init__.py)
from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)

import importlib  # noqa: E402
from typing import Any  # noqa: E402

# from .postgres import PgVectorStore
supported_stores = {
    "postgres": "PgVectorStore",
    "milvus": "MilvusStore",
    "kb": "KnowledgeBaseStore",
    "faiss_store": "FaissStore",
    "arango": "ArangoStore",
    "bigquery": "BigQueryStore",
    "lancedb": "LanceDBStore",
}

# ``AbstractStore`` is lazy (PEP 562, FEAT-540): ``.abstract`` imports
# navconfig + parrot.conf, which ``parrot.stores.models`` must not pay.
_LAZY_ATTRS: dict[str, str] = {"AbstractStore": ".abstract"}

__all__ = ["AbstractStore", "supported_stores"]


def __getattr__(name: str) -> Any:
    """Resolve ``AbstractStore`` lazily on first access (PEP 562).

    Args:
        name: Attribute requested on the package.

    Returns:
        The resolved object.

    Raises:
        AttributeError: If ``name`` is not a lazy export.
    """
    module_path = _LAZY_ATTRS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module_path, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Expose lazy exports to ``dir()``."""
    return sorted(set(globals()) | set(__all__))
```
**Why this shape**: `extend_path` must run before anything else (spec §7 gotcha); `supported_stores` is a cheap dict consumers read at import time.

### `packages/ai-parrot/src/parrot/knowledge/wiki/documents.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^import aiohttp$' packages/ai-parrot/src/parrot/knowledge/wiki/documents.py)
# DELETE — line 26 `import aiohttp`
#
# occurrences: 1 (verified: grep -c 'timeout = aiohttp.ClientTimeout(total=self.fetch_timeout)' packages/ai-parrot/src/parrot/knowledge/wiki/documents.py)
# BEFORE — insert above `        timeout = aiohttp.ClientTimeout(total=self.fetch_timeout)` (verified: documents.py:568)
        # Lazy (FEAT-540): aiohttp is needed only for URL fetches, not for
        # importing the documents module on the CLI / hook path.
        import aiohttp
```
**Why**: spec gateway #4; the `except (aiohttp.ClientError, TimeoutError)` at :595 still sees the local name.

### `packages/ai-parrot/tests/knowledge/test_import_ceilings.py` (MODIFY)
```python
# occurrences: 1 (verified after TASK-3256: grep -c 'lands in TASK-3257' packages/ai-parrot/tests/knowledge/test_import_ceilings.py)
# REPLACE the `ontology.schema` param with:
    pytest.param("import parrot.knowledge.ontology.schema", 240, id="ontology.schema"),
```

### `packages/ai-parrot/tests/knowledge/test_lazy_package_roots.py` (MODIFY — append)
```python
def test_ontology_root_lazy() -> None:
    """``OntologyRAGMixin`` still resolves from the package; importing ``schema`` alone skips ``.mixin``."""
    # FILL IN: child 1 — `import parrot.knowledge.ontology.schema`; assert
    # 'parrot.knowledge.ontology.mixin' not in sys.modules. Child 2 (or same child after) —
    # `from parrot.knowledge.ontology import OntologyRAGMixin, TenantContext` resolves and
    # `OntologyRAGMixin is parrot.knowledge.ontology.mixin.OntologyRAGMixin` — bounded by spec §4.
    raise NotImplementedError


def test_stores_root_lazy() -> None:
    """``AbstractStore`` resolves; ``supported_stores`` unchanged; ``stores.models`` skips navconfig."""
    # FILL IN: child — `from parrot.stores.models import Document`; assert 'navconfig' and
    # 'parrot.stores.abstract' not in sys.modules; then `from parrot.stores import AbstractStore,
    # supported_stores`; assert the 7 keys of supported_stores (postgres, milvus, kb, faiss_store,
    # arango, bigquery, lancedb) — bounded by stores/__init__.py:8-16 today.
    raise NotImplementedError


def test_documents_aiohttp_lazy() -> None:
    """Importing ``wiki.documents`` leaves ``aiohttp`` out of ``sys.modules``."""
    # FILL IN: child — `import parrot.knowledge.wiki.documents`; assert 'aiohttp' not in
    # sys.modules. "The fetch path still works": run `DocumentAcquirer._download` against a
    # local aiohttp test server (`aiohttp.test_utils` / `aiohttp.web` on 127.0.0.1, in-process,
    # pytest-asyncio) and assert the returned temp file holds the served bytes — bounded by
    # spec §4 and "no external network in CI".
    raise NotImplementedError
```

### FILL IN checklist
- [ ] `test_ontology_root_lazy` — subprocess assertions; bounded by spec §4.
- [ ] `test_stores_root_lazy` — subprocess assertions + 7 `supported_stores` keys; bounded by stores/__init__.py today.
- [ ] `test_documents_aiohttp_lazy` — subprocess assertion; fetch path smoke without network; bounded by spec §4 / no network in CI.
- [ ] If `ontology.schema` exceeds 240 modules, report the chain (`-X importtime`) — ESCALATE, never raise the ceiling.

---

## Addendum — repo-root `tests/` tree (review, 2026-09-15)

Note: the repo-root `tests/` tree (run by CI) imports `parrot.knowledge.ontology` / `parrot.stores` package roots in many files (`git ls-files tests | xargs grep -lE "parrot\.knowledge\.ontology|from parrot\.stores"`). Run that selection too; laziness must not change what they receive.

---

## Acceptance Criteria

- [ ] `import parrot.knowledge.ontology.schema` loads **≤ 240** modules and no FORBIDDEN package (spec §5 AC 2) — `test_import_ceilings[ontology.schema]` passes without xfail
- [ ] `from parrot.knowledge.ontology import OntologyRAGMixin, TenantOntologyManager, TenantContext` still works (same objects)
- [ ] `from parrot.stores import AbstractStore` and `from parrot.stores.pgvector import …` (if `ai-parrot-embeddings` installed) still resolve
- [ ] `from parrot.stores.models import Document` loads no `navconfig`
- [ ] `import parrot.knowledge.wiki.documents` does not load `aiohttp`
- [ ] `pytest packages/ai-parrot/tests/knowledge/test_import_ceilings.py packages/ai-parrot/tests/knowledge/test_lazy_package_roots.py packages/ai-parrot/tests/knowledge/graphindex packages/ai-parrot/tests/knowledge/test_ontology_mixin.py -q` passes
- [ ] `ruff check` clean on the five changed files
- [ ] Repo-root consumers of the ontology/stores roots pass (run the grep-selected files from `tests/`)

---

## Test Specification

See the appended test block above; minimum set: `test_import_ceilings[ontology.schema]`,
`test_ontology_root_lazy`, `test_stores_root_lazy`, `test_documents_aiohttp_lazy`.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-3256 must be in `sdd/tasks/completed/` (you edit files it created)
3. **Verify the Codebase Contract** — re-grep anchors; if `ontology/__init__.py` or `stores/__init__.py` gained names, add them to the lazy maps
4. **Update status** in `sdd/tasks/index/graphindex-core-seams.json` → `"in-progress"`
5. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:`
6. In a worktree, run tests with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src`
7. **Verify** all acceptance criteria
8. **Move this file** to `sdd/tasks/completed/TASK-3257-ontology-stores-lazy-roots.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** (include before/after counts for `ontology.schema` and `stores.models`)

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
