# TASK-4392: Register `"helixdb"` in every FEAT-540 backend registry (exclusive)

**Feature**: FEAT-670 — HelixDB graph provider
**Spec**: `sdd/specs/helixdb-provider.spec.md` (§3 Module 4 "registrations" half, §2 Integration Points, AC2, AC3, AC4, AC7, AC19, AC27)
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4377, TASK-4378, TASK-4379, TASK-4384, TASK-4388, TASK-4386, TASK-4391
**Assigned-to**: unassigned

---

## Context

FEAT-670 never branches on `backend == "helixdb"`: every HelixDB backend is plugged into a
FEAT-540 registry (spec v0.3 "register, never branch"). The classes exist once their tasks land
(`HelixWikiStore` TASK-4376/4377, `HelixSourceBackend` TASK-4378, `resolve_helix_params` TASK-4379,
`HelixPersistence` TASK-4383/4384, `HelixOntologyGraphStore` TASK-4387/4388, `helix` traversal compiler
TASK-4386). This task adds exactly **one row per registry** plus the `register_all()` helper, so
`backend: helixdb` resolves through `create_wiki_store`, `open_namespace_store`, `is_built()`,
`create_source_backend`, `create_graph_persistence`, `persistence_for_project` and
`create_ontology_graph_store` without any per-site edit.

It is **exclusive** (`parallel: false`): the four registry tables live in files other tasks edit
(`wiki/store.py` also gets TASK-4391's dump surface; `helix/__init__.py` is edited by TASK-4374 and TASK-4386).

FEAT-540 is merged (`6fd231dc2`); its real API differs from the spec skeleton in four places — see
Implementation Notes → "Spec drift". Follow the real code.

---

## Scope

- Add the `"helixdb"` row to `_BUILTIN_WIKI_BACKENDS` in `wiki/store.py` with `kind="server"`, a lazy
  factory path, a namespace `resolve_options` adapter and an `is_built` hook path (both new private
  functions in `wiki/store.py`).
- Register `"helixdb"` in `wiki/sources_backend.py` with a lazy factory that bridges the async
  `HelixSourceBackend` to the synchronous contract.
- Add the `GraphBackendSpec(name="helixdb", …)` row to the built-in loop of `graphindex/backends.py`
  with `required_options=("settings_factory",)`, `capabilities=("incremental", "history")`,
  `extra="helixdb"` and a `project_options` mapper (new private function in `backends.py`).
- Register `"helixdb"` in `ontology/contracts.py` with a lazy factory function.
- Add `register_all()` to `parrot/knowledge/helix/__init__.py` (idempotent re-registration of the graph,
  ontology and source rows + the `helix` traversal compiler; asserts the built-in wiki row).
- Write `tests/knowledge/helix/test_registrations.py` (spec §4 `test_registry_accepts_helixdb`,
  `test_helix_backend_kind_server`, `test_graph_backend_registration`, `test_create_wiki_store_helixdb_dispatch`).

**NOT in scope**:
- `helix_*` fields / `resolve_helix_params` on `WikiProjectConfig` (TASK-4379).
- Any `Literal`, `click.Choice`, `is_built()` body, `open_namespace_store` or `persistence_for_project`
  edit — FEAT-540 already made them registry-driven.
- `SourceCollectionManager` / `wiki/cli.py::_open_sources` (they pass only `manager`, `arango_db`,
  `arango_store`; see drift item 4 — follow-up, not this task).
- `register_query_validator("helix", …)` — deliberately absent (spec §3 M8: LLM-dynamic queries fail closed).
- Any edit to `wiki/arango_store.py`, `graphindex/persist_arango.py`, `ontology/graph_store.py` (AC16).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | MODIFY | `_helix_namespace_options`, `_helix_is_built`, one `"helixdb"` `WikiBackendSpec` row |
| `packages/ai-parrot/src/parrot/knowledge/wiki/sources_backend.py` | MODIFY | `_create_helix_backend` + `register_source_backend("helixdb", …)` |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/backends.py` | MODIFY | `_helix_project_options` + one `GraphBackendSpec` row |
| `packages/ai-parrot/src/parrot/knowledge/ontology/contracts.py` | MODIFY | `_create_helixdb_ontology_store` + `register_ontology_backend("helixdb", …)` |
| `packages/ai-parrot/src/parrot/knowledge/helix/__init__.py` | MODIFY | `register_all()` |
| `packages/ai-parrot/tests/knowledge/helix/test_registrations.py` | CREATE | registry tests |

---

## Codebase Contract (Anti-Hallucination)

Verified 2026-10-16 on `dev` @ `1c239a5ca` (FEAT-540 merged).

### Verified Imports
```python
from parrot.knowledge.wiki.store import (            # wiki/store.py
    WikiBackendSpec,          # :539  (name, kind: Literal["local","server"], factory: Any, resolve_options: Any, is_built: str|None, extra: str|None)
    wiki_backend_names,       # :648
    wiki_backend_spec,        # :653
    resolve_wiki_backend,     # :683
    is_server_backend,        # :692
    create_wiki_store,        # :2809
)
from parrot.knowledge.wiki.sources_backend import (  # wiki/sources_backend.py
    register_source_backend,      # :87  (name, factory) — factory must return a SYNC backend
    create_source_backend,        # :98
    AsyncSourceBackendBridge,     # :280 — wraps an async backend in the sync contract
    SourceManifestBackend,        # :50
)
from parrot.knowledge.graphindex.backends import (   # graphindex/backends.py
    GraphBackendSpec,             # :22 (name, factory: str, required_options, capabilities, extra, project_options: str|None)
    register_graph_backend,       # :46
    graph_backend_names,          # :55
    graph_backend_spec,           # :60
    create_graph_persistence,     # :95 (async)
)
from parrot.knowledge.graphindex.protocols import GraphPersistence, IncrementalPersistence  # protocols.py:103, :155
from parrot.knowledge.ontology.contracts import (    # ontology/contracts.py
    GraphDocumentStore,           # :26
    OntologyTraversalStore,       # :106
    register_ontology_backend,    # :172 (name, factory)
    create_ontology_graph_store,  # :182 (sync)
)
from parrot.knowledge.wiki.runtime import persistence_for_project  # wiki/runtime.py:34 (async; calls project_options(config, root, tenant))
from parrot.knowledge.wiki.project import WikiProjectConfig, WikiNamespaceConfig  # project.py:574, :186
# created by dependency tasks (verify they exist before starting):
from parrot.knowledge.wiki.project import resolve_helix_params             # TASK-4379: (config, *, root=None) -> HelixSettings
from parrot.knowledge.helix.settings import HelixSettings, HelixMode       # TASK-4372 (HelixSettings.with_database(name))
from parrot.knowledge.wiki.helix_store import HelixWikiStore, helix_wiki_store_factory  # TASK-4376
from parrot.knowledge.wiki.helix_sources import HelixSourceBackend         # TASK-4378 (__init__(settings))
from parrot.knowledge.graphindex.persist_helix import HelixPersistence, create_helix_persistence  # TASK-4383/4384
from parrot.knowledge.ontology.helix_graph_store import HelixOntologyGraphStore, create_helix_ontology_store  # TASK-4387/4388
from parrot.knowledge.ontology.traversal_spec import register_traversal_compiler, traversal_compiler_dialects  # TASK-4385
from parrot.knowledge.helix.traversal import compile_helix_traversal       # TASK-4386
```

### Existing Signatures to Use
```python
# wiki/store.py
_BUILTIN_WIKI_BACKENDS: dict[str, WikiBackendSpec] = {           # :609
    "postgres": WikiBackendSpec(name="postgres", kind="server", factory=_make_postgres, resolve_options=_no_options),  # :613
}
def _no_options(cfg: Any) -> dict[str, Any]: ...                 # :604
def _lazy(target: Any) -> Any                                     # :673 — resolves "module:attr" strings

# wiki/project.py
def is_built(self, root: Path) -> bool:                           # :793 — spec.is_built ("module:attr") wins, called hook(self, root); else kind=="server" -> True
def resolve_setting(key, *, default=None, explicit=None, project_defaults=None) -> Any   # :849

# wiki/federation.py:418-429 — namespace with kind=="database" and backend != "arangodb":
#   resolver = wiki_store._lazy(spec.resolve_options); options = dict(resolver(cfg))   # cfg is a WikiNamespaceConfig
#   store = factory(storage_dir=None, wiki_name=name, read_only=read_only, **options)

# wiki/runtime.py:70-83 — persistence_for_project:
#   if config.backend in graph_backend_names() and spec.project_options:
#       mapper = getattr(import_module(module), attr); options = dict(mapper(config, root, tenant))

# wiki/sources.py:157 — SourceCollectionManager passes create_source_backend(backend, manager=self, arango_db=..., arango_store=...)
```

### Does NOT Exist
- ~~`_BUILTIN_ONTOLOGY_BACKENDS` / a built-in ontology table~~ — `create_ontology_graph_store` hard-codes `"arangodb"` (`contracts.py:198-202`); a row = `register_ontology_backend(...)` at module import.
- ~~`register_source_backend(..., kind=/extra=)`~~ — `(name, factory)` only.
- ~~`WikiBackendSpec.extra` being read anywhere~~ — informational only; the missing-extra error comes from TASK-4373's `lazy_import` guard.
- ~~`resolve_helix_params` usable as `resolve_options`~~ — it returns `HelixSettings`, `resolve_options` must return a `dict` from a `WikiNamespaceConfig` (drift 1).
- ~~`register_query_validator("helix", …)`~~ — must stay absent.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/store.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/sources_backend.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/graphindex/backends.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/ontology/contracts.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/helix/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/helix/test_registrations.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#WikiBackendSpec",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#wiki_backend_spec",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#create_wiki_store",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/sources_backend.py#register_source_backend",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/sources_backend.py#AsyncSourceBackendBridge",
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/backends.py#GraphBackendSpec",
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/backends.py#register_graph_backend",
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/backends.py#create_graph_persistence",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/contracts.py#register_ontology_backend",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/contracts.py#create_ontology_graph_store",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/runtime.py#persistence_for_project",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiProjectConfig.is_built"
  ]
}
```

---

## Implementation Notes

### Spec drift (FEAT-540 real API vs spec §3 M4 skeleton) — follow the real code
1. **`resolve_options`** is called as `resolver(cfg)` with a **`WikiNamespaceConfig`** and must return a
   factory-kwargs `dict` (`federation.py:418-429`). The spec's
   `resolve_options="parrot.knowledge.wiki.project:resolve_helix_params"` cannot work (wrong argument type,
   returns `HelixSettings`). Use a new adapter `_helix_namespace_options(cfg) -> {"database": cfg.database}`.
2. **`is_built` hook** exists (`WikiBackendSpec.is_built: str | None`, consumed at `project.py:806`), called
   `hook(config, root)` with the **`WikiProjectConfig`**. Point it at `_helix_is_built` in `wiki/store.py`.
3. **No ontology built-in table**: register at import time of `ontology/contracts.py` through a lazy wrapper.
4. **Sources**: `SourceCollectionManager` only forwards `manager`, `arango_db`, `arango_store`
   (`sources.py:157-162`) and `wiki/cli.py::_open_sources` (`:540-564`) falls back to `json` for any backend
   other than sqlite/arangodb. The helix factory therefore accepts `helix_settings=` **or** derives settings from
   a `HelixWikiStore` passed as `arango_store` (it has `.settings`), else raises `ValueError`. Wiring the CLI so
   `backend: helixdb` gets Helix-backed sources is a follow-up — record it in the Completion Note and open a ledger
   issue (`wikitoolkit ledger open --kind feature_gap --severity minor --discovered-from spec:FEAT-670 …`).
5. **`required_options`**: spec §2 says `("settings",)`, §3 M4 says `("settings_factory",)`; the M7 factory takes
   `settings_factory` → use `("settings_factory",)`. Capabilities add `"history"` (AC27, `GraphHistoryTransfer`).

### Key Constraints
- Every factory path is a **lazy string** (or a function that imports lazily): importing `wiki/store.py`,
  `graphindex/backends.py`, `ontology/contracts.py` or `sources_backend.py` must never import `helixdb` or any
  `helix_*` module (spec §7 "an unselected backend costs no import"). Test it with `sys.modules`.
- `register_all()` is idempotent (dict assignment) and must not import the SDK either.
- `_helix_is_built` returns `True` in server mode, and `(settings.root / settings.database).exists()` in embedded
  mode (spec §3 M4 comment; `settings.root` = `<storage_dir>/helix`, set by `resolve_helix_params`).

### References in Codebase
- `wiki/store.py:575-601` — `_make_arangodb` / `_make_postgres` lazy-import pattern.
- `wiki/sources_backend.py:369-375` — `_create_arango_backend` (bridge pattern).
- `graphindex/backends.py:187-191` — lazy `_create_sqlite`.

---

## Implementation Blueprint

### Steps (in order)
1. Verify every dependency symbol above exists (`grep -n`) — *why*: this task only wires names; a missing name is a dependency not done.
2. Edit `wiki/store.py` (adapters + row) — *why*: AC1/AC2/AC19 route through this row.
3. Edit `sources_backend.py`, `backends.py`, `contracts.py` — *why*: AC2 sources, AC4, AC7.
4. Add `register_all()` to `helix/__init__.py` — *why*: spec §3 M4 programmatic re-registration.
5. Write tests; run validation commands.

### `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c -F 'def _no_options(cfg: Any) -> dict[str, Any]:' wiki/store.py) — line 604
# AFTER — insert below the whole `_no_options` function (its `return {}` line), before `_BUILTIN_WIKI_BACKENDS`:


def _helix_namespace_options(cfg: Any) -> dict[str, Any]:
    """Factory options for a federated ``helixdb`` namespace (``WikiNamespaceConfig``).

    Connection settings (``HELIXDB_URL`` / ``HELIXDB_API_KEY`` / ``HELIXDB_MODE``) resolve from the
    environment inside the factory; the namespace only names the database.
    """
    database = getattr(cfg, "database", None)
    return {"database": database} if database else {}


def _helix_is_built(config: Any, root: Path) -> bool:
    """``is_built`` hook of the ``helixdb`` row: server planes always count as built.

    Embedded mode probes ``<storage_dir>/helix/<database>`` (spec §3 M4).
    """
    from parrot.knowledge.helix.settings import HelixMode  # lazy: no helix import unless selected
    from parrot.knowledge.wiki.project import resolve_helix_params

    settings = resolve_helix_params(config, root=root)
    if settings.mode != HelixMode.EMBEDDED or settings.root is None:
        return True
    return (Path(settings.root) / settings.database).exists()
```
```python
# occurrences: 1 (verified: grep -c -F '    "postgres": WikiBackendSpec(name="postgres", kind="server", factory=_make_postgres, resolve_options=_no_options),' wiki/store.py) — line 613
# AFTER — insert below that line, inside the dict literal:
    "helixdb": WikiBackendSpec(
        name="helixdb",
        kind="server",
        factory="parrot.knowledge.wiki.helix_store:helix_wiki_store_factory",
        resolve_options=_helix_namespace_options,
        is_built="parrot.knowledge.wiki.store:_helix_is_built",
        extra="helixdb",
    ),
```
**Why this shape**: `resolve_wiki_backend` already `_lazy()`-resolves string factories (`:683-689`), so the store
module is imported only on selection. Also update the `create_wiki_store` docstring `backend:` paragraph (`:2823-2827`)
to mention `"helixdb"` — docstring only, no branch.

### `packages/ai-parrot/src/parrot/knowledge/wiki/sources_backend.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c -F 'register_source_backend("arangodb", _create_arango_backend)' wiki/sources_backend.py) — line 380
# BEFORE that line (after _create_arango_backend, line ~375) insert:
def _create_helix_backend(**options: Any) -> SourceManifestBackend:
    """Lazily import the HelixDB manifest backend (FEAT-670) and bridge it to the sync contract.

    Settings come from ``helix_settings`` or from a ``HelixWikiStore`` handed over as ``arango_store``
    (``SourceCollectionManager`` forwards only ``manager`` / ``arango_db`` / ``arango_store``).
    """
    import inspect

    from parrot.knowledge.wiki.helix_sources import HelixSourceBackend

    settings = options.get("helix_settings") or getattr(options.get("arango_store"), "settings", None)
    if settings is None:
        raise ValueError("sources backend 'helixdb' requires helix_settings= (or a HelixWikiStore as arango_store=)")
    backend = HelixSourceBackend(settings)
    if inspect.iscoroutinefunction(getattr(backend, "list_sources", None)):
        return AsyncSourceBackendBridge(backend)
    return backend


# AFTER line 380 append:
register_source_backend("helixdb", _create_helix_backend)
```

### `packages/ai-parrot/src/parrot/knowledge/graphindex/backends.py` (MODIFY)
```python
# Anchor 1 — occurrences: 1 (verified: grep -c -F 'async def _create_null(**_: Any) -> GraphPersistence:' graphindex/backends.py)
# BEFORE `async def _create_null` insert:
def _helix_project_options(config: Any, root: Path, tenant_id: str) -> dict[str, Any]:
    """Map a ``backend: helixdb`` wiki project to ``create_helix_persistence`` options (FEAT-670 M4).

    One HelixDB database per tenant: ``gi_<tenant_id>`` (spec §2 Tenancy, resolved Q7).
    """
    from parrot.knowledge.wiki.project import resolve_helix_params  # lazy: backends.py imports no wiki code

    base = resolve_helix_params(config, root=root)

    def settings_factory(ctx: Any) -> Any:
        return base.with_database(f"gi_{getattr(ctx, 'tenant_id', None) or tenant_id}")

    return {"settings_factory": settings_factory}
```
```python
# Anchor 2 — `):` occurs 5 times; use the unique 2-line context (verified: grep -c -F '        extra="arangodb",' graphindex/backends.py → 1, line 251):
#         extra="arangodb",
#     ),
# AFTER `    ),` that closes the arangodb spec (line 252), still inside the `for _spec in (...)` tuple:
    GraphBackendSpec(
        name="helixdb",
        factory=f"{_BASE}.persist_helix:create_helix_persistence",
        required_options=("settings_factory",),
        capabilities=("incremental", "history"),
        extra="helixdb",
        project_options=f"{_BASE}.backends:_helix_project_options",
    ),
```
**Why**: `persistence_for_project` (runtime.py:70-83) consumes `project_options`; `create_graph_persistence` enforces
`required_options` and awaits async factories.

### `packages/ai-parrot/src/parrot/knowledge/ontology/contracts.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c -F '    raise ValueError(f"Unknown ontology graph backend {backend!r} — expected one of {known}")' ontology/contracts.py) — line 206, last line of the file
# AFTER — append at end of file:


def _create_helixdb_ontology_store(**options: Any) -> GraphDocumentStore:
    """Lazily build the HelixDB ontology store (FEAT-670 M8); no helix import until selected."""
    from parrot.knowledge.ontology.helix_graph_store import create_helix_ontology_store

    return create_helix_ontology_store(**options)


register_ontology_backend("helixdb", _create_helixdb_ontology_store)
```

### `packages/ai-parrot/src/parrot/knowledge/helix/__init__.py` (MODIFY)
```python
# Append after the existing exports / the TASK-4386 compiler registration (re-read the file first; its
# `__all__` gains "register_all").
def register_all() -> None:
    """Idempotently (re-)register every HelixDB backend row (tests / programmatic use, spec §3 M4).

    The wiki row is built into ``wiki/store.py`` and cannot be re-registered; it is asserted instead.
    """
    from parrot.knowledge.graphindex import backends as graph_backends
    from parrot.knowledge.ontology import contracts as ontology_contracts
    from parrot.knowledge.ontology.traversal_spec import register_traversal_compiler
    from parrot.knowledge.wiki import sources_backend
    from parrot.knowledge.wiki.store import wiki_backend_names

    from .traversal import compile_helix_traversal

    if "helixdb" not in wiki_backend_names():
        raise RuntimeError("built-in 'helixdb' WikiBackendSpec row missing from wiki/store.py")
    # FILL IN: re-register the "helixdb" GraphBackendSpec by re-reading graph_backends.graph_backend_spec("helixdb")
    #   and passing it to graph_backends.register_graph_backend — bounded by idempotence (same object, no import of persist_helix)
    ontology_contracts.register_ontology_backend("helixdb", ontology_contracts._create_helixdb_ontology_store)
    sources_backend.register_source_backend("helixdb", sources_backend._create_helix_backend)
    register_traversal_compiler("helix", compile_helix_traversal)
```

### `packages/ai-parrot/tests/knowledge/helix/test_registrations.py` (CREATE)
```python
"""FEAT-670 TASK-4392 — "helixdb" is a known name in every FEAT-540 registry (AC2/AC4/AC7/AC19/AC27)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from parrot.knowledge.graphindex.backends import graph_backend_names, graph_backend_spec
from parrot.knowledge.ontology import contracts
from parrot.knowledge.wiki import sources_backend
from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.store import is_server_backend, wiki_backend_names, wiki_backend_spec


def test_registry_accepts_helixdb() -> None:
    assert "helixdb" in wiki_backend_names()
    assert is_server_backend("helixdb")
    assert "helixdb" in graph_backend_names()
    assert "helixdb" in contracts._ONTOLOGY_BACKENDS
    assert "helixdb" in sources_backend._SOURCE_BACKENDS
    assert WikiProjectConfig(backend="helixdb").backend == "helixdb"


def test_graph_spec_capabilities() -> None:
    spec = graph_backend_spec("helixdb")
    assert spec.capabilities == ("incremental", "history")
    assert spec.required_options == ("settings_factory",)
    assert spec.project_options and spec.project_options.endswith(":_helix_project_options")


def test_registries_import_no_helix_module() -> None:
    """Importing the four registry modules never imports helixdb or a helix backend module."""
    code = (
        "import sys, parrot.knowledge.wiki.store, parrot.knowledge.graphindex.backends, "
        "parrot.knowledge.ontology.contracts, parrot.knowledge.wiki.sources_backend; "
        "bad=[m for m in sys.modules if m.startswith('helixdb') or 'helix_' in m or m.endswith('persist_helix')]; "
        "print(bad); sys.exit(1 if bad else 0)"
    )
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0


def test_helix_backend_kind_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HELIXDB_MODE", "server")
    assert WikiProjectConfig(backend="helixdb").is_built(tmp_path) is True
    # FILL IN: embedded mode — HELIXDB_MODE=embedded → is_built False until <storage>/helix/<database> exists, True after mkdir — bounded by AC19


def test_unknown_backend_still_names_registry() -> None:
    with pytest.raises(ValueError, match="helixdb"):
        wiki_backend_spec("nope")


# FILL IN: test_create_wiki_store_helixdb_dispatch (helix-memory: create_wiki_store(tmp, backend="helixdb", settings=helix_memory_settings) is a HelixWikiStore),
#   test_graph_backend_registration (create_graph_persistence("helixdb", settings_factory=…) → isinstance GraphPersistence and IncrementalPersistence;
#   persistence_for_project(WikiProjectConfig(backend="helixdb", wiki_name="w"), tmp) settings database == "gi_w"),
#   test_ontology_factory (create_ontology_graph_store("helixdb", settings_factory=…) is a GraphDocumentStore and OntologyTraversalStore, dialect "helix"),
#   test_missing_extra_names_extra (monkeypatch sys.modules["helixdb"]=None → error message contains "ai-parrot[helixdb]") — use the
#   helix_memory_settings fixture from tests/knowledge/helix/conftest.py (TASK-4373); bounded by AC1/AC3/AC4/AC7
```

### FILL IN checklist
- [ ] `helix/__init__.py::register_all` — graph re-registration without importing `persist_helix`; bounded by spec §7 lazy rule.
- [ ] `test_registrations.py::test_helix_backend_kind_server` embedded branch; bounded by AC19.
- [ ] `test_registrations.py` dispatch/factory/missing-extra tests; bounded by AC1/AC3/AC4/AC7.

---

## Acceptance Criteria

- [ ] AC2: `"helixdb"` is accepted by `WikiProjectConfig.backend` / namespaces / CLI choices purely via the row; `grep -rn '"helixdb"' packages/ai-parrot/src/parrot/knowledge/wiki/{models,cli,entity_cli,federation,sources,toolkit,sync}.py` returns nothing.
- [ ] AC3: selecting `helixdb` without the extra raises an error naming `ai-parrot[helixdb]`.
- [ ] AC4: `graph_backend_spec("helixdb")` exists; `persistence_for_project` (config `backend: helixdb`) yields `gi_<tenant>` settings.
- [ ] AC7: `create_ontology_graph_store("helixdb", …)` returns `HelixOntologyGraphStore`; no `helix` query validator registered.
- [ ] AC19: `is_built()` True in server mode; embedded probes `storage_dir/helix/<database>`.
- [ ] AC27 (part): `graph_backend_spec("helixdb").capabilities` includes `"history"`.
- [ ] Importing the four registry modules imports no helix module.
- [ ] `ruff check` clean on the five modified source files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/helix/test_registrations.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_wiki_config_registry.py -q`

---

## Test Specification

See the `test_registrations.py` block above: registry membership, capability tuple, lazy-import guard
(subprocess), `is_built` server/embedded, dispatch through `create_wiki_store` / `create_graph_persistence` /
`persistence_for_project` / `create_ontology_graph_store` on `helix-memory`, missing-extra message.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — `python -m scripts.sdd.ensure_worktree --slug helixdb-provider --feature-id FEAT-670`
2. **Read the spec** (§3 M4, §2 Integration Points) and this file's drift list.
3. **Check dependencies** — TASK-4377, 4378, 4379, 4384, 4386, 4388, 4391 must be `done` in `sdd/tasks/index/helixdb-provider.json`. This task is **exclusive** (`parallel: false`).
4. **Verify the Codebase Contract** — re-run every `grep -c -F` above; FEAT-633 may have moved `wiki/store.py` lines.
5. **Update status** → `"in-progress"`, commit only the index file.
6. **Implement** from the blueprint; complete every `# FILL IN:`.
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
8. **Commit the code** — stage only the six files listed.
9. **Close** with `scripts/sdd/close_task.sh TASK-4392 helixdb-provider verified`.
10. **Fill in the Completion Note** (include the sources-CLI follow-up ledger issue id), then commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
