# TASK-2498: `OntologyLegalWikiStore` read-only adapter + pluggable wiki backend seam (R16)

**Feature**: FEAT-449 — Legal Librarian Answer Layer
**Spec**: `sdd/specs/legal-librarian-answer-layer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2493, TASK-2494, TASK-2496
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 (R16). FEAT-450 federation is merged; this task exposes the
legal ontology tenant as a **read-only wiki namespace** (`legal::…`) by
implementing `BaseWikiStore` over the tenant's collections + the
`legal_articulos_view`, and adds a minimal, additive backend-registration
seam in core (`register_wiki_backend`) so a satellite package can plug in
without core importing `parrot_tools`.

> **Verified gap (not in the spec)**: `WikiNamespaceConfig.backend` is
> `Literal["sqlite", "memory", "arangodb"]` and its `_check_exactly_one_source`
> validator **forces `backend = "arangodb"` whenever `database` is set**
> (`project.py:218,253-254`). The spec's dispatch condition
> `cfg.backend != "arangodb" and cfg.backend in _EXTRA_BACKENDS` can therefore
> never be true today. This task MUST widen the type and only force
> `"arangodb"` when the user left the default — see Scope.

---

## Scope

- Core `wiki/store.py` (additive): module-level `_EXTRA_BACKENDS: dict[str, Callable[..., BaseWikiStore]]`,
  `register_wiki_backend(name, factory) -> None`; in `create_wiki_store`
  immediately before the final `ValueError`:
  `if backend in _EXTRA_BACKENDS: return _EXTRA_BACKENDS[backend](storage_dir=storage_dir, wiki_name=wiki_name, **kwargs)`.
  Update the `ValueError` text to mention registered extras.
- Core `wiki/project.py`: `WikiNamespaceConfig.backend: str` (keep the
  three known values documented; validate that it is either one of the
  built-ins or a name that MAY be registered later — do not import the
  registry at validation time). Change the validator to
  `if self.database and self.backend in ("sqlite", "memory"): backend = "arangodb"`
  so an explicit `backend: ontology_legal` on a `database` entry survives.
  Behavior for existing configs (no `backend` key + `database`) is unchanged.
- Core `wiki/federation.py::open_namespace_store`, `kind == "database"` branch,
  BEFORE `_open_arango`: import the store module (`from parrot.knowledge.wiki
  import store as wiki_store`) and dispatch when `cfg.backend != "arangodb"
  and cfg.backend in wiki_store._EXTRA_BACKENDS` with
  `storage_dir=None, wiki_name=name, database=cfg.database or "",
  arango_params=resolve_arango_params(_arango_config_for(cfg)), read_only=read_only`,
  then `await _assert_plane_readable(store)`; return `(store, None)`.
  Unknown non-arangodb backend on a `database` entry ⇒ `ValueError` naming it.
- Satellite `parrot_tools/legal/wiki_store.py`: `class OntologyLegalWikiStore(BaseWikiStore)`
  implementing ALL 16 abstract methods per the spec §3 M7 mapping table
  (writes raise `NotImplementedError("ontology_legal namespace is read-only")`;
  `search_vector` returns `[]` and never raises; `search_fts` = the
  `search_articles` AQL (read from the merged legal ontology's
  `traversal_patterns`) with `as_of = today` + `passes_token_guard`
  (TASK-2496), projected to the stub shape; `neighbors` over
  `modifica`/`deroga`/`pertenece_a`; `stats`; lint methods return `[]`).
  `@classmethod factory(cls, *, storage_dir=None, wiki_name, database, arango_params, read_only=True, **_)`
  — verifies the database and `articulo` collection exist, never provisions,
  raises `FileNotFoundError` when absent (so `_skip_for` classifies it as
  unbuilt). Mirror `arango_store.py:282-330` (`_connect_existing`) for the
  no-provision connect.
- `parrot_tools/legal/__init__.py`: `register_wiki_backend("ontology_legal", OntologyLegalWikiStore.factory)`
  at import time (guard the core import so the satellite still imports if
  the wiki package is unavailable).
- Tests: `test_wiki_store_read_only`, `test_wiki_store_search_fts_stub_shape`
  (fake AQL executor), `test_register_wiki_backend_dispatch` (core:
  `create_wiki_store(backend="x")` calls the registered factory; unknown
  still `ValueError`; `sqlite`/`memory`/`arangodb` untouched),
  `test_namespace_config_keeps_explicit_backend` (core: `database` +
  `backend: ontology_legal` survives; `database` alone ⇒ `arangodb`),
  `test_open_namespace_store_dispatches_extra_backend` (core, factory
  monkeypatched into `_EXTRA_BACKENDS`), `test_factory_raises_when_unbuilt`.

**NOT in scope**: MCP tool changes, `wikitoolkit` CLI changes, any
embedding; the end-to-end federation test against Arango (TASK-2499).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | MODIFY | `_EXTRA_BACKENDS`, `register_wiki_backend`, dispatch in `create_wiki_store` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | MODIFY | `WikiNamespaceConfig.backend: str` + validator fix |
| `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py` | MODIFY | extra-backend dispatch in `kind == "database"` |
| `packages/ai-parrot-tools/src/parrot_tools/legal/wiki_store.py` | CREATE | `OntologyLegalWikiStore` |
| `packages/ai-parrot-tools/src/parrot_tools/legal/__init__.py` | MODIFY | import-time registration |
| `packages/ai-parrot/tests/knowledge/wiki/test_extra_backends.py` | CREATE | core seam tests |
| `packages/ai-parrot-tools/tests/legal/test_wiki_store.py` | CREATE | adapter tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-08-27 against `dev`.

### Verified Imports
```python
from parrot.knowledge.wiki.store import BaseWikiStore, create_wiki_store       # store.py:289,1369
from parrot.knowledge.wiki.federation import open_namespace_store               # federation.py:340
from parrot.knowledge.wiki.project import WikiNamespaceConfig, resolve_arango_params  # project.py (~:180, :481)
from parrot_tools.legal.boe.queries import passes_token_guard                   # TASK-2496
```

### Existing Signatures to Use
```python
# wiki/store.py:289-378 — BaseWikiStore ABC, 16 abstract async methods:
upsert_pages(pages) -> int; add_edges(edges) -> int; replace_source_slice(...); delete_page(concept_id) -> bool
upsert_embedding(...); get_page(concept_id, include_body=...) ; list_pages(category, limit, origin)
search_fts(query, category, limit); search_vector(embedding, limit); neighbors(concept_id, rel, direction)
dump_pages() -> list[dict]; dump_edges() -> list[dict]; stats() -> dict
orphan_sources() -> list[str]; broken_edges() -> list[dict]; missing_bodies() -> list[str]
def _assert_writable(self) -> None   # :382
# READ :289-378 for the exact parameter names/defaults of each — copy them verbatim.

# wiki/store.py:1369-1426
def create_wiki_store(storage_dir: str | Path, wiki_name: str = "", backend: str = "sqlite", **kwargs) -> BaseWikiStore
#   :1404 sqlite  :1406 memory  :1412 arangodb  :1423 raise ValueError(...)

# wiki/project.py
class WikiNamespaceConfig(BaseModel):
    backend: Literal["sqlite", "memory", "arangodb"] = Field(default="sqlite", ...)   # :218  ← widen
    database: str | None                                                              # :221
    @model_validator(mode="after") _check_exactly_one_source                          # :240-255 (:253-254 forces arangodb)
    @property kind -> Literal["path","store","database","vault"]                      # :258

# wiki/federation.py
async def _assert_plane_readable(store: BaseWikiStore) -> None                        # :135
def _arango_config_for(cfg: WikiNamespaceConfig) -> WikiProjectConfig                 # :188
async def _open_arango(*, arango_params, database, wiki_name, text_analyzer, timeout, read_only)  # :286
async def open_namespace_store(name, cfg, *, base_dir, read_only=True, arango_timeout=...)      # :340
#   kind == "database" branch at :395-404
def _skip_for(name, cfg, exc) -> NamespaceSkip                                         # :407 (FileNotFoundError ⇒ unbuilt)

# wiki/arango_store.py — read-only connect pattern to mirror (no provisioning):
#   initialize() read_only branch :282-286 → _connect_existing() :306-330
#   search_fts AQL/stub shape :857-878  {concept_id,node_id,title,category,summary,source_id,token_count,score}
```

### Does NOT Exist
- ~~`create_wiki_store(backend="ontology_legal")`~~ — closed set today; this task opens it via the registry.
- ~~`WikiNamespaceConfig.backend` accepting non-built-in values~~ — Literal today; widened here.
- ~~Core importing `parrot_tools`~~ — forbidden direction; registration happens in the satellite at import time.
- ~~`search_vector` raising / any embedding path~~ — returns `[]` (R14).
- ~~Provisioning (`initialize_tenant`, view creation) from the adapter~~ — never; it verifies and reads only.
- ~~`wiki_pages`/`wiki_edges` collections in the legal tenant~~ — the adapter projects `norma`/`articulo`/edge collections; there is no wiki plane to open with `ArangoDBWikiStore`.

---

## Implementation Notes

### Pattern to Follow
```python
# core store.py (additive)
_EXTRA_BACKENDS: dict[str, Callable[..., "BaseWikiStore"]] = {}

def register_wiki_backend(name: str, factory: Callable[..., "BaseWikiStore"]) -> None:
    """Register a satellite-provided wiki backend (FEAT-449 M7)."""
    _EXTRA_BACKENDS[name] = factory
```
```python
# federation.py — inside kind == "database", before _open_arango
if cfg.backend != "arangodb":
    factory = wiki_store._EXTRA_BACKENDS.get(cfg.backend)
    if factory is None:
        raise ValueError(f"namespace {name!r}: unknown database backend {cfg.backend!r}")
    store = factory(storage_dir=None, wiki_name=name, database=cfg.database or "",
                    arango_params=resolve_arango_params(_arango_config_for(cfg)), read_only=read_only)
    await _assert_plane_readable(store)
    return store, None
```

### Key Constraints
- `sqlite`/`memory`/`arangodb` behavior byte-for-byte unchanged; existing wiki
  tests (`packages/ai-parrot/tests/knowledge/wiki/`) must pass untouched.
- Adapter AQL for `get_page` uses the same in-force predicate as
  `article_in_force` (`valid_from <= today`, `valid_to == null OR > today`).
- `summary` = first 280 chars of in-force text; `token_count = len(text) // 4`;
  `node_id = articulo_key`; `category = "articulo"`; `source_id = norma_ref`.
- Use `AsyncDB("arangodb", params=...)` via the same driver the wiki store
  uses; read `arango_store.py:163-200` for constructor/param handling.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py` — read-only connect + FTS AQL
- `packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_namespaces.py` — namespace test style
- `docs/runbooks/jira-issues-namespace.md` — how a namespace is registered/queried (for the docstring example)

---

## Acceptance Criteria

- [ ] `create_wiki_store("/tmp/x", backend="ontology_legal")` invokes the registered factory once `parrot_tools.legal` is imported; unknown backend still raises `ValueError`
- [ ] `WikiNamespaceConfig(database="legal_x", backend="ontology_legal").backend == "ontology_legal"`; `WikiNamespaceConfig(database="legal_x").backend == "arangodb"`
- [ ] `open_namespace_store` dispatches to the extra backend for `kind == "database"` and returns `(store, None)`; `arangodb` path unchanged
- [ ] All write methods raise `NotImplementedError`; `search_vector` returns `[]`
- [ ] `search_fts` stubs contain exactly the keys `{concept_id, node_id, title, category, summary, source_id, token_count, score}`
- [ ] Factory raises `FileNotFoundError` when the database or `articulo` collection is missing
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/wiki/ packages/ai-parrot-tools/tests/legal/ -v`
- [ ] `ruff check` on all touched files

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_extra_backends.py
import pytest
from parrot.knowledge.wiki import store as wiki_store
from parrot.knowledge.wiki.project import WikiNamespaceConfig


def test_register_wiki_backend_dispatch(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setitem(wiki_store._EXTRA_BACKENDS, "fake", lambda **kw: calls.append(kw) or object())
    wiki_store.create_wiki_store(tmp_path, wiki_name="w", backend="fake", database="d")
    assert calls[0]["wiki_name"] == "w" and calls[0]["database"] == "d"
    with pytest.raises(ValueError):
        wiki_store.create_wiki_store(tmp_path, backend="nope")


def test_namespace_config_keeps_explicit_backend():
    assert WikiNamespaceConfig(database="legal_x", backend="ontology_legal").backend == "ontology_legal"
    assert WikiNamespaceConfig(database="legal_x").backend == "arangodb"
```

```python
# packages/ai-parrot-tools/tests/legal/test_wiki_store.py
import pytest
from parrot_tools.legal.wiki_store import OntologyLegalWikiStore

STUB_KEYS = {"concept_id", "node_id", "title", "category", "summary", "source_id", "token_count", "score"}

async def test_wiki_store_read_only(fake_legal_wiki_store):
    with pytest.raises(NotImplementedError):
        await fake_legal_wiki_store.upsert_pages([])
    assert await fake_legal_wiki_store.search_vector([0.1] * 8, limit=5) == []

async def test_wiki_store_search_fts_stub_shape(fake_legal_wiki_store):
    rows = await fake_legal_wiki_store.search_fts("tres meses", category=None, limit=5)
    assert rows and set(rows[0]) == STUB_KEYS
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§3 M7 mapping table, §7 "Federation seam scope-creep") and the **verified gap** note at the top of this task
2. **Check dependencies** — TASK-2493, TASK-2494, TASK-2496 completed
3. **Verify the Codebase Contract** — read `store.py:289-390`, `project.py:180-270`, `federation.py:340-425`, `arango_store.py:163-330` before coding
4. **Update status** in `sdd/tasks/index/legal-librarian-answer-layer.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2498-legal-wiki-namespace-adapter.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-27
**Notes**:
- `wiki/store.py`: added `_EXTRA_BACKENDS` registry + `register_wiki_backend()`,
  and dispatch in `create_wiki_store` immediately before the final
  `ValueError` (whose message now lists registered extras too).
- `wiki/project.py`: widened `WikiNamespaceConfig.backend` from
  `Literal["sqlite","memory","arangodb"]` to `str` (per the task's
  "verified gap"), and changed `_check_exactly_one_source`'s validator
  to `if self.database and self.backend in ("sqlite","memory"):` before
  forcing `"arangodb"` — an explicit non-built-in backend on a `database`
  entry now survives. Existing `database`-only configs (no explicit
  `backend`) are unaffected: default `backend="sqlite"` still gets forced
  to `"arangodb"`.
- `wiki/federation.py`: `open_namespace_store`'s `kind == "database"`
  branch now checks `cfg.backend != "arangodb"` first and dispatches to
  `wiki_store._EXTRA_BACKENDS[cfg.backend]` (raising `ValueError` naming
  the namespace + unknown backend), calling `_assert_plane_readable`
  (a no-op for non-`SQLiteWikiStore` instances) before returning
  `(store, None)`; the `arangodb` path is byte-for-byte unchanged
  (falls through to the pre-existing `_open_arango` call).
- `parrot_tools/legal/wiki_store.py` (NEW): `OntologyLegalWikiStore(BaseWikiStore)`
  implements all 16 abstract methods. Write methods raise
  `NotImplementedError("ontology_legal namespace is read-only")`;
  `search_vector` always returns `[]` (never raises, R14). `get_page`/
  `list_pages` embed the in-force temporal filter directly in AQL
  (`valid_from <= @as_of`, `valid_to == null OR valid_to > @as_of` —
  same predicate as `article_in_force`), never in Python. `search_fts`
  REUSES `search_articles()` (TASK-2496) rather than duplicating its AQL
  — one source of truth for the BM25 + token-guard pattern. `neighbors`/
  `dump_edges` walk the three typed edge collections
  (`modifica`/`deroga`/`pertenece_a`). `stats` counts normas/articulos/
  versions/in-force-versions. Lint methods (`orphan_sources`/
  `broken_edges`/`missing_bodies`) return `[]` per spec ("wiki lint
  semantics do not apply to a projected corpus").
- `factory()`/`initialize()` mirror `arango_store.py:282-330`'s
  no-provision connect: probe `_system` for database existence, then
  connect to the target db and check the `articulo` collection exists —
  `FileNotFoundError` on either miss. Internally, once connected, the
  store constructs an `OntologyGraphStore` + a `TenantContext` (merged
  legal ontology resolved via `TenantOntologyManager`, same as
  `conftest.py`'s `legal_tenant_ctx` fixture) and reuses `article_in_force`
  semantics / `execute_traversal` for all reads — NEVER calls
  `initialize_tenant` (which would provision).
- `parrot_tools/legal/__init__.py`: registers `"ontology_legal"` at
  import time, guarded with `try/except ImportError` so the package still
  imports if the core wiki plane is unavailable.
- Core seam tests (`packages/ai-parrot/tests/knowledge/wiki/test_extra_backends.py`,
  9 tests): registry dispatch, unknown-backend `ValueError`, built-ins
  untouched, `WikiNamespaceConfig` explicit-backend survival vs.
  database-only-forces-arangodb, `open_namespace_store` dispatch + unknown
  backend error.
- Adapter tests (`packages/ai-parrot-tools/tests/legal/test_wiki_store.py`,
  13 tests): read-only refusals, `search_vector` empty, `search_fts` stub
  shape (exactly the 8 spec'd keys), `get_page` (with/without body,
  missing), `list_pages` (both categories, category filter), `neighbors`,
  lint no-ops, `stats`, and factory `FileNotFoundError` when the target
  database doesn't exist (monkeypatches `sys.modules["asyncdb"]` so
  `initialize()`'s local `from asyncdb import AsyncDB` resolves to a fake
  probe reporting the database absent — no real network dependency).
  Uses a purpose-built `FakeLegalStore` double (not the shared
  `FakeGraphStore` in `conftest.py` — kept local to this test file since
  it needed several NEW AQL shapes specific to this adapter, and
  extending the shared fake a third time risked growing it into an
  unmaintainable AQL-sniffing pile).
- `pytest packages/ai-parrot/tests/knowledge/wiki/ -v` → 223 passed (9
  new + 214 pre-existing; 2 pre-existing failures in
  `test_installer_mcp.py` confirmed unrelated via `git stash` baseline
  comparison). `pytest packages/ai-parrot-tools/tests/legal/ -v` → 139
  passed (13 new + 126 from prior tasks). `ruff check` on every touched/
  created file: zero NEW issues versus the pre-edit baseline (verified
  via before/after diff on `store.py`, which carries pre-existing SIM117/
  UP045 noise unrelated to this task).

**Deviations from spec**: two, both discovered while resolving genuine
implementation-detail ambiguities the task itself flagged or left open:
1. **`WikiNamespaceConfig.backend` widening + validator change** —
   REQUIRED per the task's own "Verified gap (not in the spec)" note at
   the top; implemented exactly as instructed
   (`if self.database and self.backend in ("sqlite","memory"):`).
2. **`factory()` synchronicity vs. "raises FileNotFoundError when absent."**
   The task's Codebase Contract instructs mirroring
   `arango_store.py:282-330`'s `_connect_existing` (an ASYNC, no-provision
   connect) inside a factory the task also describes as raising
   `FileNotFoundError` directly. But BOTH call sites that invoke the
   registered factory — `create_wiki_store`'s dispatch (`store.py`) and
   `open_namespace_store`'s new dispatch (`federation.py`) — call it
   WITHOUT `await` (confirmed by the task's own given core test:
   `wiki_store.create_wiki_store(tmp_path, wiki_name="w", backend="fake",
   database="d")`, no `await`, with a plain synchronous `lambda` as the
   registered factory). A synchronous factory cannot itself run an async
   network probe (worse, `open_namespace_store` is itself a coroutine, so
   `asyncio.run()` inside a sync factory it calls would raise
   "cannot be called from a running event loop"). Resolved by keeping
   `factory()` synchronous and non-connecting — EXACTLY like
   `ArangoDBWikiStore.__init__` — and moving verification into
   `initialize()` (async, lazy, called by every read method via
   `_ensure_init()`), which is where `FileNotFoundError` actually raises.
   This is the same deferred-connection contract every other backend in
   this file already follows; no interface change, no test contradicted.
