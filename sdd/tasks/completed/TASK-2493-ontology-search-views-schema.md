# TASK-2493: Declarative ArangoSearch views in the ontology schema (`search_views`)

**Feature**: FEAT-449 — Legal Librarian Answer Layer
**Spec**: `sdd/specs/legal-librarian-answer-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (R15). ArangoSearch views become first-class, **domain-agnostic**
ontology YAML configuration: declared under a new top-level `search_views:`
section, merged per tenant like `traversal_patterns`, and provisioned
idempotently at `initialize_tenant`. Today the ontology package has zero
ArangoSearch/`SEARCH` code — this task creates the first. No `legal` reference
may appear anywhere in this module; the legal declaration is TASK-2494.

Blocks TASK-2494 and TASK-2498.

---

## Scope

- `schema.py`: add `SearchViewField`, `SearchViewLink`, `SearchViewDef` (all
  `extra="forbid"`) exactly as spec §2 Data Models; add
  `search_views: dict[str, SearchViewDef] = Field(default_factory=dict)` to
  BOTH `OntologyDefinition` and `MergedOntology`. Dict key = view name.
- `merger.py`: merge `search_views` in `merge`, `merge_definitions`, and
  `merge_with_overlay` with a name-keyed union (later layer overrides a
  same-named view — whole-view replacement, not link-level merge). In
  `_validate_integrity`, mirror the `vectorize` check: every `link.entity`
  must be a merged entity name, and every `field.path` must match the
  one-level path grammar (`name` or `name[*].sub`); violations raise
  `OntologyIntegrityError` naming the view and the offending entity/path.
- `graph_store.py`: add `async def _ensure_views(self, db, ctx) -> None`
  and module-level helpers `_merge_link_field(fields, path)` and
  `_view_matches(existing, properties)`; call `_ensure_views` as **step 6**
  at the end of `initialize_tenant` (after named-graph creation). Update the
  `initialize_tenant` docstring step list. Drive `db._connection` directly
  (`views()`, `create_view()`, `view()`, `replace_view()`), NEVER the asyncdb
  `create_arangosearch_view()` wrapper (vendored bug — see contract).
  Failure posture: per-view `try/except` → `logger.warning` and continue.
- Spike (5 min, record result in Completion Note): confirm the `text_es`
  analyzer exists on the dev ArangoDB (`connection.analyzers()` or
  `arangosh`). If absent, note the fallback (create analyzer / `text_en`)
  for TASK-2494 — do not block this task on it.
- Unit tests in `packages/ai-parrot/tests/knowledge/ontology/`:
  `test_search_view_def_merge_and_validation`, `test_ensure_views_idempotent`
  (fake `db._connection` recording `create_view`/`replace_view` calls: create
  path, skip path on match, reconcile path on drift), path-grammar rejection.
- Confirm existing ontology YAMLs (`base`, `knowledge`, `field_services`, …)
  still load unchanged (`search_views` defaults to empty).

**NOT in scope**: the legal view declaration / `search_articles` pattern
(TASK-2494); any query helper (TASK-2496); wiki adapter (TASK-2498).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py` | MODIFY | 3 new models + `search_views` on `OntologyDefinition` and `MergedOntology` |
| `packages/ai-parrot/src/parrot/knowledge/ontology/merger.py` | MODIFY | union merge + integrity validation |
| `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py` | MODIFY | `_ensure_views`, `_merge_link_field`, `_view_matches`, step 6 |
| `packages/ai-parrot/src/parrot/knowledge/ontology/__init__.py` | MODIFY | export new schema models if the package re-exports schema symbols (check) |
| `packages/ai-parrot/tests/knowledge/ontology/test_search_views.py` | CREATE | merge/validation/provisioning tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-08-27 against `dev`.

### Verified Imports
```python
from parrot.knowledge.ontology.schema import (          # schema.py
    EntityDef,            # :40  (model_config extra="forbid" :63)
    TraversalPattern,     # :263
    OntologyDefinition,   # :300 (traversal_patterns :322; extra="forbid" :324)
    MergedOntology,       # :330 (traversal_patterns :350 — REQUIRED field, no default)
    TenantContext,        # :406
)
from parrot.knowledge.ontology.merger import OntologyMerger          # merger.py:26
from parrot.knowledge.ontology.exceptions import OntologyIntegrityError, OntologyMergeError  # exceptions.py:18,8
from parrot.knowledge.ontology.graph_store import OntologyGraphStore # graph_store.py:34
```

### Existing Signatures to Use
```python
# schema.py:330-360
class MergedOntology(BaseModel):
    name: str; version: str
    entities: dict[str, EntityDef]
    relations: dict[str, RelationDef]
    traversal_patterns: dict[str, TraversalPattern]
    layers: list[str]; merge_timestamp: datetime
    def get_entity_collections(self) -> list[str]     # :353
    def get_edge_collections(self) -> list[str]       # :357
# EntityDef has `.collection: str` and `.get_property_names()` (used at merger.py:428)

# merger.py — three merge entry points, each builds MergedOntology(...) explicitly:
def merge(self, yaml_paths: list[Path]) -> MergedOntology                 # :51  (constructs at :86)
def merge_definitions(self, ...) -> MergedOntology                        # :99  (constructs at :134)
def merge_with_overlay(self, ...) -> MergedOntology                       # :142 (constructs at :248)
def _merge_patterns(self, target, source) -> None                         # :377 (name-keyed union pattern to mirror)
def _validate_integrity(self, merged: MergedOntology) -> None             # :402 (vectorize check at :427-434)

# graph_store.py
class OntologyGraphStore:
    def __init__(self, arango_client: Any = None)                         # :50
    async def _get_db(self, ctx: TenantContext) -> Any                    # :54  (returns the asyncdb client after .use(ctx.arango_db))
    async def initialize_tenant(self, ctx: TenantContext) -> None         # :72  (named-graph creation ends ~:172 — add step 6 after)
    async def _ensure_index(self, db, collection, field) -> None          # :174 (documented NO-OP)
    async def execute_traversal(self, ctx, aql, bind_vars=None, collection_binds=None) -> list[dict]  # :193
#   collection loop uses:  logger.warning("Failed to create ...", ...) and continues  (:116, :148)

# wiki/arango_store.py — the shape to COPY (not import):
#   _view_properties  :343-356   {"links": {coll: {"analyzers": [...], "fields": {...}}}}
#   _create_pages_view :358-400  connection = self._db._connection
#                                existing = await connection.views()
#                                await connection.create_view(name=..., view_type="arangosearch", properties=...)
#                                await connection.replace_view(name, properties)
```

### Does NOT Exist
- ~~Any ArangoSearch view / `SEARCH` / analyzer code in `parrot/knowledge/ontology/`~~ — this task creates the first.
- ~~`OntologyDefinition.search_views` / `MergedOntology.search_views`~~ — created here.
- ~~`EntityDef.fts` or a per-entity view key~~ — views are declared at `OntologyDefinition` level, not on `EntityDef`.
- ~~`asyncdb.drivers.arangodb.create_arangosearch_view()` as a usable wrapper~~ — calls async `views()`/`create_view()` without `await`; raises `TypeError` against a real server. MUST drive `db._connection` directly.
- ~~`trackListPositions` handling~~ — not in v1; view match positions are never used for spans.
- ~~A working `_ensure_index` body~~ — it is a documented no-op; do not "fix" it here.

---

## Implementation Notes

### Pattern to Follow
```python
# graph_store.py — spec §3 M2 verbatim (adapt only if code drifted)
async def _ensure_views(self, db: Any, ctx: TenantContext) -> None:
    for view_name, view_def in ctx.ontology.search_views.items():
        properties: dict[str, Any] = {"links": {}}
        for link in view_def.links:
            entity = ctx.ontology.entities[link.entity]      # validated by merger
            fields: dict[str, Any] = {}
            for f in link.fields:
                _merge_link_field(fields, f.path)
            properties["links"][entity.collection] = {
                "analyzers": sorted({a for f in link.fields for a in f.analyzers}),
                "fields": fields,
            }
        try:
            connection = db._connection
            existing = await connection.views()
            if not any(v.get("name") == view_name for v in existing):
                await connection.create_view(name=view_name, view_type="arangosearch",
                                             properties=properties)
            elif not _view_matches(await connection.view(view_name), properties):
                await connection.replace_view(view_name, properties)
        except Exception as e:
            logger.warning("Failed to provision view '%s': %s", view_name, e)
```

Path grammar for `_merge_link_field`: `"titulo"` → `fields["titulo"] = {}`;
`"versions[*].text"` → `fields["versions"] = {"fields": {"text": {}}}`.
Exactly ONE nesting level; anything else ⇒ `ValueError` (raised at merge
time through `_validate_integrity`, not at provisioning).

`_view_matches`: compare the `links` sub-dict of the server's view
description against `properties["links"]` — analyzers as sorted lists,
fields structurally. Tolerate extra server-added keys (e.g.
`includeAllFields`, `storeValues`) — compare only what we declare.

### Key Constraints
- `ctx.ontology` is a `MergedOntology`; `search_views` must be a field with
  a default there (existing code constructs `MergedOntology(...)` in three
  places — adding a defaulted field keeps them valid, but pass it explicitly).
- Domain-agnostic: no `legal`, `articulo`, `text_es` literals in this module
  (tests may use them as sample data).
- `text_es` is the *default* analyzer in `SearchViewField.analyzers` per spec.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py:343-400` — view shape + reconcile-on-drift
- `packages/ai-parrot/src/parrot/knowledge/ontology/merger.py:377-434` — union + integrity patterns
- `packages/ai-parrot/tests/knowledge/ontology/test_merger_overlay.py` — merger test style

---

## Acceptance Criteria

- [ ] An ontology YAML with `search_views:` parses into `OntologyDefinition.search_views`; YAMLs without it still parse (all bundled defaults load)
- [ ] Merging two layers declaring the same view name yields the later layer's definition
- [ ] A view link naming an unknown entity raises `OntologyIntegrityError` mentioning the view name
- [ ] A field path with two nesting levels (`a[*].b[*].c`) is rejected at merge time
- [ ] `_ensure_views` on a fake connection: creates when absent, no-ops when matching, `replace_view` when links drift; a raising connection only logs a warning
- [ ] `initialize_tenant` calls `_ensure_views` after named-graph creation
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/ontology/ -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/ontology/`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/ontology/test_search_views.py
import pytest
from parrot.knowledge.ontology.schema import OntologyDefinition, SearchViewDef
from parrot.knowledge.ontology.merger import OntologyMerger
from parrot.knowledge.ontology.exceptions import OntologyIntegrityError
from parrot.knowledge.ontology.graph_store import OntologyGraphStore, _merge_link_field


def test_search_view_def_merge_and_validation(sample_layers):
    merged = OntologyMerger().merge_definitions(sample_layers)   # two layers, same view name
    assert list(merged.search_views["v"].links[0].fields[0].path) # later layer wins
    with pytest.raises(OntologyIntegrityError, match="v"):
        OntologyMerger().merge_definitions([layer_with_unknown_entity])


def test_link_field_path_grammar():
    fields = {}
    _merge_link_field(fields, "titulo"); _merge_link_field(fields, "versions[*].text")
    assert fields == {"titulo": {}, "versions": {"fields": {"text": {}}}}
    with pytest.raises(ValueError):
        _merge_link_field({}, "a[*].b[*].c")


class FakeConnection:
    def __init__(self, views=None): self._views = views or []; self.created = []; self.replaced = []
    async def views(self): return self._views
    async def view(self, name): return next(v for v in self._views if v["name"] == name)
    async def create_view(self, *, name, view_type, properties): self.created.append((name, properties))
    async def replace_view(self, name, properties): self.replaced.append((name, properties))


async def test_ensure_views_idempotent(ctx_with_view):
    store = OntologyGraphStore(arango_client=object())
    conn = FakeConnection()
    db = type("DB", (), {"_connection": conn})()
    await store._ensure_views(db, ctx_with_view)
    assert len(conn.created) == 1
    conn._views = [{"name": conn.created[0][0], **conn.created[0][1]}]
    await store._ensure_views(db, ctx_with_view)
    assert len(conn.created) == 1 and conn.replaced == []
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§2 Data Models, §3 M2, §6, §7)
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm the three `MergedOntology(...)` construction sites in `merger.py`
   - Read `wiki/arango_store.py:343-400` in full before writing `_ensure_views`
4. **Update status** in `sdd/tasks/index/legal-librarian-answer-layer.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2493-ontology-search-views-schema.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below — include the `text_es` spike result

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-27
**Notes**:
- `schema.py`: added `SearchViewField`/`SearchViewLink`/`SearchViewDef`
  (all `extra="forbid"`) exactly per spec §2; added
  `search_views: dict[str, SearchViewDef] = Field(default_factory=dict)`
  to both `OntologyDefinition` and `MergedOntology` (defaulted, but every
  `MergedOntology(...)` call site passes it explicitly per the contract
  note).
- `merger.py`: added `_merge_search_views` (name-keyed whole-view
  replacement, mirroring `_merge_patterns`' override semantics) called
  from all three merge entry points (`merge`, `merge_definitions`,
  `merge_with_overlay`). `_validate_integrity` now also checks every
  `search_views` link's `entity` exists and every field `path` matches
  the one-level grammar (reuses `graph_store._merge_link_field` as the
  single source of truth for the grammar, catching its `ValueError` and
  re-raising as `OntologyIntegrityError` naming the view).
- `graph_store.py`: added module-level `_merge_link_field(fields, path)`
  and `_view_matches(existing, properties)`, plus instance method
  `_ensure_views(self, db, ctx)` — drives `db._connection` directly
  (`.views()`, `.create_view()`, `.view()`, `.replace_view()`), NEVER the
  asyncdb `create_arangosearch_view()` wrapper (read
  `wiki/arango_store.py:343-400` first, per instructions). Wired as
  step 6 at the end of `initialize_tenant`, after named-graph creation;
  updated the docstring's step list. Per-view `try/except Exception` →
  `logger.warning` + continue, mirroring the existing collection-creation
  loops in the same method (an intentional broad catch, matching the
  file's existing failure-posture convention — not narrowed further).
- `__init__.py`: NOT modified — the package's existing `__all__` does not
  re-export `OntologyDefinition`/`EntityDef`/`TraversalPattern` either, so
  adding `SearchViewDef` alone would be inconsistent; left the minimal
  re-export surface as-is.
- Added `packages/ai-parrot/tests/knowledge/ontology/test_search_views.py`
  covering: layered merge (later-layer-wins wholesale replacement),
  unknown-entity `OntologyIntegrityError`, two-level-nesting rejection at
  merge time, YAML-without-`search_views` still parsing, the
  `_merge_link_field` path grammar (bare/one-level/malformed), and
  `_ensure_views` idempotency (create path, skip-on-match path,
  replace-on-drift path, and a raising connection that only logs a
  warning and never raises).
- `pytest packages/ai-parrot/tests/knowledge/ontology/ -v` → 196 passed
  (10 new + 186 pre-existing, all green). `ruff check` on the three
  modified source files: the only NEW lint entry versus the pre-edit
  baseline is one `BLE001` (`except Exception` inside `_ensure_views`),
  which is a deliberate, spec-mandated failure posture identical to the
  method's existing collection/edge/graph-creation `try/except Exception`
  blocks a few lines above it (same file, same convention, already
  present before this task) — not narrowed, to match spec §3 M2's
  explicit "mirror initialize_tenant's collection loop" instruction.
- Confirmed via the full `pytest packages/ai-parrot/tests/knowledge/
  ontology/` run (196 passed) that base/knowledge/field_services and
  other bundled ontology YAMLs still load unchanged — `search_views`
  defaults to `{}` everywhere it is not declared.
- Environment note (not a code change): this fresh worktree was missing
  the repo's compiled Cython extensions (`*.so` under `packages/*/src/`,
  gitignored build artifacts) that the shared `.venv` depends on
  transitively (`parrot.utils.types`, etc.), which blocked test
  collection entirely. Copied the existing compiled `.so` files from the
  main checkout into the worktree (no source changes) so `pytest` could
  run; this is local-environment bootstrapping only, not part of the
  feature diff.

**`text_es` spike**: DEFERRED. This is an autonomous, non-interactive
worker session with no VPN access to the dev ArangoDB tenant, so
`connection.analyzers()` could not be run against a live server. Per the
task's own instruction this does not block the task — TASK-2494 (which
declares the actual `text_es`/`text_en` view) inherits the same
constraint; operator follow-up: confirm analyzer availability before/at
that task's re-ingest step, falling back to creating the analyzer or
using `text_en` if `text_es` is absent.

**Deviations from spec**: none beyond the `__init__.py` non-change noted
above (which keeps the module consistent with its pre-existing minimal
re-export surface rather than introducing a new asymmetry).
