---
type: feature
base_branch: dev
---

# Feature Specification: GraphIndex Odoo-aware Extractor + SQLite Persistence + Graph Reader

**Feature ID**: FEAT-240
**Date**: 2026-06-16
**Author**: Jesus Lara / Claude Code
**Status**: draft
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

Navigating large Odoo codebases to understand model inheritance is painful.
A third-party module may extend `res.partner` with additional fields, override
methods, or chain `_inherits` — and the only way to discover these contributions
today is to grep manually through hundreds of files.

GraphIndex can solve this with deterministic graph traversal, but it currently
lacks three capabilities: (1) Odoo-domain awareness in the extractor, (2) a
lightweight SQLite persistence backend for offline/local use without ArangoDB,
and (3) a read-side navigator that loads the graph topology into memory for
instant navigation and supports lexical search via FTS5/BM25.

### Goals

- Extract Odoo model semantics (`_name`, `_inherit`, `_inherits`, `fields.*`,
  `@api.*` decorators) into the GraphIndex universal schema.
- Persist the graph into a per-tenant SQLite artefact as an alternative to
  ArangoDB, with incremental staleness checks.
- Provide a read-side navigator with HOT in-memory topology (rustworkx) and
  COLD on-demand source resolution (disk-based line spans + LRU cache).
- Enable queries like: "What does module X add to model `res.partner`?" as
  deterministic graph traversals, not semantic similarity.

### Non-Goals (explicitly out of scope)

- No embeddings or `embedding_ref` population in this route (v1).
- No MCP server exposure (descoped per GraphIndex v1 convention).
- No XML view / OWL JS parsing (possible v2 via tree-sitter multi-language).
- No resolution of dynamic `_name`/`_inherit` expressions (f-strings,
  concatenation) — graceful degradation, not failure.
- No orphan canonical node garbage collection — candidate for analytics.
- Runtime fallback-on-failure was not considered — see brainstorm for context.

---

## 2. Architectural Design

### Overview

Three new components plug into the existing GraphIndex pipeline:

1. **`OdooCodeExtractor`** — subclass of `CodeExtractor` that overrides
   `_extract_class` to detect Odoo model classes and emit canonical model
   nodes + `EXTENDS`/`DEFINES` edges. Non-Odoo classes fall back to the
   base extractor transparently. **Selectable** via a new builder constructor
   parameter (`code_extractor_class`), not auto-detected.

2. **`SQLitePersistence`** — per-tenant `.db` backend with WAL mode, `files`
   table for staleness tracking, `nodes`/`edges` tables, and `nodes_fts`
   virtual table for FTS5/BM25 search. API parity with `GraphIndexPersistence`:
   `persist_graph`, `replace_document_slice`, plus `is_stale`.

3. **`SQLiteGraphReader`** — read-only navigator. On `load()`, reads all nodes
   and edges into a `rustworkx.PyDiGraph` (HOT path). Sync navigation methods
   (`list_models`, `find_model`, `who_extends`, `children`) operate on the
   in-memory graph. Async methods (`search_symbols`, `get_source`) touch
   SQLite/disk (COLD path) with an LRU body cache.

All three components respect the existing universal schema (`UniversalNode`,
`UniversalEdge`). The only schema-level addition is `EdgeKind.EXTENDS`.

### Component Diagram

```
Odoo Source Files
       │
       ▼
┌──────────────────┐
│ OdooCodeExtractor │──▶ UniversalNode + UniversalEdge
└──────────────────┘           │
       │ (canonical odoo_model │
       │  nodes + EXTENDS)     │
       ▼                       ▼
┌───────────────┐    ┌────────────────┐
│ GraphAssembler │    │ GraphEmbedder  │ (skipped for Odoo v1)
└───────────────┘    └────────────────┘
       │
       ▼
┌──────────────────┐
│ SQLitePersistence │──▶ <tenant>.db (WAL + FTS5)
└──────────────────┘
       │
       ▼
┌──────────────────┐
│ SQLiteGraphReader │
│  HOT: rustworkx   │ ← list_models, find_model, who_extends, children
│  COLD: aiosqlite   │ ← search_symbols, get_source
└──────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `CodeExtractor` | extended by | `OdooCodeExtractor` subclasses it, overrides `_extract_class` |
| `GraphIndexPersistence` | paralleled by | `SQLitePersistence` implements the same public API |
| `GraphIndexBuilder` | modified | New `code_extractor_class` param; `mtime` passed to extract |
| `GraphIndexLoader` | modified | Backend selection: ArangoDB / SQLite / Null |
| `EdgeKind` enum | extended | Add `EXTENDS = "extends"` |
| `RelationType` enum | extended | Add `EXTENDS = "extends"` |
| `meta_ontology.py` | extended | Add `gi_extends` collection + `RelationDef` |
| `projection.py` | extended | Add EXTENDS mapping |

### Data Models

#### Two-layer Odoo model representation

| Layer | `symbol_type` | `source_uri` | Purpose |
|-------|---------------|--------------|---------|
| Class | `odoo_model_class` | real file path | The Python class; maintains `CONTAINS` hierarchy |
| Canonical | `odoo_model` | `odoo-model://<name>` | Aggregator per model name; anchor for `EXTENDS` |
| Field | `odoo_field` | real file path | `fields.X(...)` declaration; child of class |
| Method | `function` (base) | real file path | With `decorators` in domain_tags if `@api.*` |

#### Edge semantics

- Class **`DEFINES`** canonical — when class has `_name`
- Class **`EXTENDS`** canonical — one per `_inherit` name / `_inherits` key
- Class **`CONTAINS`** field/method — structural
- Module **`CONTAINS`** class — structural (from base extractor)
- Module **`DEFINES`** class — from base extractor

#### Canonical node invariant

Canonical model nodes use synthetic `source_uri` (`odoo-model://res.partner`).
This prevents `replace_document_slice` from deleting them when refreshing a
single file, preserving cross-module `EXTENDS` edges.

### New Public Interfaces

```python
# OdooCodeExtractor — same extract() signature as CodeExtractor
class OdooCodeExtractor(CodeExtractor):
    async def extract(
        self, file_path: str, source: str, *, mtime: Optional[float] = None
    ) -> tuple[list[UniversalNode], list[UniversalEdge]]: ...

# SQLitePersistence
class SQLitePersistence:
    def __init__(self, db_dir: Path) -> None: ...
    async def persist_graph(
        self, ctx: TenantContext, nodes: list[UniversalNode],
        edges: list[UniversalEdge]
    ) -> dict[str, Any]: ...
    async def replace_document_slice(
        self, ctx: TenantContext, document_uri: str,
        nodes: list[UniversalNode], edges: list[UniversalEdge]
    ) -> dict[str, Any]: ...
    async def is_stale(
        self, ctx: TenantContext, source_uri: str, mtime: float, sha1: str
    ) -> bool: ...

# SQLiteGraphReader
class SQLiteGraphReader:
    def __init__(self, db_path, *, repo_root=None, body_cache_size: int = 256): ...
    async def load(self) -> None: ...
    async def close(self) -> None: ...
    def list_models(self) -> list[str]: ...
    def find_model(self, model_name: str) -> Optional[dict]: ...
    def who_extends(self, model_name: str, *, include_definers: bool = False) -> list[dict]: ...
    def children(self, node_id: str, *, symbol_type: Optional[str] = None) -> list[dict]: ...
    async def search_symbols(self, query: str, *, limit: int = 20) -> list[dict]: ...
    async def get_source(self, node_id: str) -> Optional[str]: ...
```

---

## 3. Module Breakdown

### Module 1: Schema & Ontology Prerequisites

- **Paths**:
  - `packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py`
  - `packages/ai-parrot/src/parrot/knowledge/okf/ontology.py`
  - `packages/ai-parrot/src/parrot/knowledge/graphindex/meta_ontology.py`
  - `packages/ai-parrot/src/parrot/knowledge/graphindex/projection.py`
- **Responsibility**: Add `EdgeKind.EXTENDS`, `RelationType.EXTENDS`,
  `gi_extends` collection mapping, and projection table entry.
- **Depends on**: nothing (prerequisite for all other modules)

### Module 2: CodeExtractor Enhancements

- **Path**: `packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/code.py`
- **Responsibility**: Add `mtime` Optional kwarg to `extract()`, stamp `sha1`
  of source content in module node's `domain_tags`, stamp `lineno`/`end_lineno`
  in `_extract_class` and `_extract_function` domain_tags.
- **Depends on**: nothing (backward-compatible additions)

### Module 3: SQLitePersistence

- **Path**: `packages/ai-parrot/src/parrot/knowledge/graphindex/persist_sqlite.py`
- **Responsibility**: Per-tenant SQLite persistence backend. WAL mode, `files`
  table for staleness, `nodes`/`edges` tables, `nodes_fts` FTS5 virtual table.
  API parity with `GraphIndexPersistence`. Atomic `replace_document_slice` via
  DELETE+INSERT in one transaction. `is_stale(ctx, source_uri, mtime, sha1)`.
- **Depends on**: Module 1 (uses EdgeKind.EXTENDS in edge kind column)

### Module 4: OdooCodeExtractor

- **Path**: `packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/odoo_code.py`
- **Responsibility**: Subclass of `CodeExtractor`. Overrides `_extract_class` to
  detect Odoo model classes, emit canonical `odoo_model` nodes, `EXTENDS`/`DEFINES`
  edges, `odoo_field` nodes for `fields.*`, and `@api.*` decorator annotations.
  Falls back to base for non-Odoo classes.
- **Depends on**: Module 1 (EdgeKind.EXTENDS), Module 2 (lineno stamping)

### Module 5: SQLiteGraphReader

- **Path**: `packages/ai-parrot/src/parrot/knowledge/graphindex/sqlite_reader.py`
- **Responsibility**: Read-only navigator. HOT topology in `rustworkx.PyDiGraph`
  loaded on `load()`. Sync navigation: `list_models`, `find_model`, `who_extends`,
  `children`. Async I/O: `search_symbols` (FTS5/BM25), `get_source` (disk line
  spans + LRU cache).
- **Depends on**: Module 3 (reads the SQLite artefact it produces)

### Module 6: Builder & Loader Wiring

- **Paths**:
  - `packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py`
  - `packages/ai-parrot/src/parrot/knowledge/graphindex/loader.py`
  - `packages/ai-parrot/pyproject.toml`
- **Responsibility**:
  - Builder: Add `code_extractor_class` constructor param (default: `CodeExtractor`).
    Pass `mtime=os.stat(path).st_mtime` to `extract()`. Support incremental
    builds via `persistence.is_stale()` when backend supports it.
  - Loader: Add SQLite backend selection alongside ArangoDB/Null.
  - pyproject.toml: Add `aiosqlite` and `orjson` to `graphindex` extra.
- **Depends on**: Modules 2, 3, 4

### Module 7: Tests

- **Paths**:
  - `packages/ai-parrot/tests/knowledge/graphindex/test_odoo_extractor.py`
  - `packages/ai-parrot/tests/knowledge/graphindex/test_persist_sqlite.py`
  - `packages/ai-parrot/tests/knowledge/graphindex/test_sqlite_reader.py`
- **Responsibility**: Comprehensive tests for all new components.
- **Depends on**: Modules 1-6

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_odoo_class_with_name` | 4 | `_name = 'x.y'` → odoo_model_class + canonical odoo_model + DEFINES edge |
| `test_odoo_class_inherit_only` | 4 | `_inherit = 'res.partner'` (no _name) → EXTENDS edge, no DEFINES |
| `test_odoo_class_inherit_list` | 4 | `_inherit = ['a', 'b']` → one EXTENDS per name |
| `test_odoo_class_inherits_dict` | 4 | `_inherits = {'res.partner': 'partner_id'}` → EXTENDS per key |
| `test_odoo_field_extraction` | 4 | `fields.Many2one(...)` → odoo_field node + CONTAINS edge + kwargs |
| `test_odoo_api_decorator` | 4 | `@api.depends('a', 'b')` → decorators in domain_tags |
| `test_non_odoo_fallback` | 4 | Plain Python class → identical to base CodeExtractor output |
| `test_dynamic_name_degrades` | 4 | `_name = f"x.{var}"` → no canonical links, no crash |
| `test_lineno_stamping` | 2 | Every symbol node has `lineno`/`end_lineno` in domain_tags |
| `test_sha1_mtime_stamping` | 2 | Module node has `sha1` and `mtime` when provided |
| `test_extract_backward_compat` | 2 | `extract(path, source)` without mtime still works |
| `test_sqlite_persist_roundtrip` | 3 | persist_graph → read back nodes/edges |
| `test_sqlite_replace_slice` | 3 | replace_document_slice atomicity; canonical nodes survive |
| `test_sqlite_is_stale` | 3 | Returns False when mtime matches; True when sha1 differs |
| `test_sqlite_fts5_populated` | 3 | Title/summary searchable after persist |
| `test_reader_load` | 5 | load() populates rustworkx graph with correct node/edge count |
| `test_reader_who_extends` | 5 | who_extends('res.partner') returns all EXTENDS contributors |
| `test_reader_find_model` | 5 | find_model aggregates fields/methods from all contributors |
| `test_reader_search_bm25` | 5 | search_symbols returns BM25-ranked results |
| `test_reader_get_source` | 5 | get_source with repo_root returns exact line slice |
| `test_reader_lru_limit` | 5 | LRU cache respects body_cache_size |

### Integration Tests

| Test | Description |
|---|---|
| `test_builder_with_odoo_extractor` | Full pipeline with OdooCodeExtractor + SQLitePersistence |
| `test_incremental_build_skips_unchanged` | is_stale returns False → file skipped |

### Test Data / Fixtures

```python
ODOO_MODEL_SOURCE = '''
from odoo import models, fields, api

class ResPartner(models.Model):
    _name = 'res.partner'
    _inherit = ['mail.thread']

    vat_verified = fields.Boolean(string='VAT Verified')
    credit_limit = fields.Float(string='Credit Limit', required=True)

    @api.depends('vat')
    def _compute_vat_status(self):
        pass
'''

ODOO_EXTENDER_SOURCE = '''
from odoo import models, fields

class ResPartnerExt(models.Model):
    _inherit = 'res.partner'

    loyalty_points = fields.Integer(string='Loyalty Points')
'''

PLAIN_PYTHON_SOURCE = '''
class MyService:
    def process(self):
        pass
'''
```

---

## 5. Acceptance Criteria

### Extractor

- [ ] A class with `_name = 'x.y'` produces: node `odoo_model_class`, canonical node `odoo_model` (title `x.y`, source_uri `odoo-model://x.y`), and edge `DEFINES` class→canonical.
- [ ] A class with `_inherit = 'res.partner'` (no `_name`) produces edge `EXTENDS` class→canonical, and **no** `DEFINES`.
- [ ] `_inherit` as list and `_inherits` as dict generate one `EXTENDS` per name.
- [ ] `fields.Many2one('res.partner', string='Cliente')` produces node `odoo_field` with `field_type=Many2one`, `comodel_name=res.partner`, `string=Cliente`, and edge `CONTAINS` class→field.
- [ ] `@api.depends('a', 'b')` on a method produces `domain_tags["decorators"] == [{"name": "depends", "args": ["a", "b"]}]`.
- [ ] A plain Python class (no Odoo signals) produces identical output to base `CodeExtractor`.
- [ ] `_name = f"x.{var}"` (dynamic) does not crash; class is emitted without canonical links.
- [ ] Every symbol node has `lineno`/`end_lineno` in `domain_tags`.

### Persistence

- [ ] `replace_document_slice` on a file does NOT delete the canonical node of a model that file extends.
- [ ] `is_stale` returns `False` when `mtime` matches; `True` when `sha1` differs.
- [ ] FTS5 index is populated on `persist_graph` and `replace_document_slice`.

### Reader

- [ ] `who_extends('res.partner')` lists all classes with `EXTENDS` edges, each with `module`.
- [ ] `find_model('res.partner')` aggregates `fields` and `methods` from all contributors.
- [ ] `search_symbols('reconcile')` returns BM25-ordered results (best first).
- [ ] `get_source(node_id)` with `repo_root` and span returns exact line slice; without `repo_root` returns summary.
- [ ] LRU body cache does not exceed `body_cache_size`.

### Wiring

- [ ] Builder accepts `code_extractor_class` param; default is `CodeExtractor`.
- [ ] Builder passes `mtime` to `extract()` when building from files.
- [ ] `aiosqlite` and `orjson` are explicit in `graphindex` extra.
- [ ] No breaking changes to existing public API.
- [ ] All existing graphindex tests continue to pass.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
# Schema types — schema.py
from parrot.knowledge.graphindex.schema import (
    EdgeKind,        # verified: schema.py:53
    NodeKind,        # verified: schema.py:33
    Provenance,      # verified: schema.py:18
    UniversalNode,   # verified: schema.py:71
    UniversalEdge,   # verified: schema.py:102
)

# Extractor base — extractors/code.py
from parrot.knowledge.graphindex.extractors.code import (
    CodeExtractor,   # verified: code.py:61
    _make_node_id,   # verified: code.py:34
    _get_node_text,  # verified: code.py:48
)

# Extractors package — extractors/__init__.py
from parrot.knowledge.graphindex.extractors import CodeExtractor  # verified: __init__.py:16

# OKF ontology
from parrot.knowledge.okf.ontology import (
    RelationType,    # verified: ontology.py:58
    ConceptType,     # verified: ontology.py:27
)

# Persistence
from parrot.knowledge.graphindex.persist import GraphIndexPersistence  # verified: persist.py:101

# Builder
from parrot.knowledge.graphindex.builder import GraphIndexBuilder  # verified: builder.py:54

# Meta-ontology
from parrot.knowledge.graphindex.meta_ontology import (
    EDGE_KIND_TO_COLLECTION,  # verified: meta_ontology.py:195
)

# Projection
from parrot.knowledge.graphindex.projection import (
    EDGE_KIND_TO_RELATION_TYPE,  # verified: projection.py:65
    NODE_KIND_TO_CONCEPT_TYPE,   # verified: projection.py:56
)
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/code.py

def _make_node_id(source_uri: str, symbol: str) -> str:  # line 34
    raw = f"{source_uri}::{symbol}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]

def _get_node_text(node, source_bytes: bytes) -> str:  # line 48

class CodeExtractor:  # line 61
    def __init__(
        self,
        tag_set: Optional[set[str]] = None,
        ignore_file: Optional[str] = None,
    ) -> None:  # line 80

    async def extract(
        self, file_path: str, source: str,
    ) -> tuple[list[UniversalNode], list[UniversalEdge]]:  # line 95

    def _extract_class(
        self, node, file_path: str, source_bytes: bytes,
        parent_id: str, nodes: list[UniversalNode],
        edges: list[UniversalEdge],
    ) -> str:  # line 237

    def _extract_function(
        self, node, file_path: str, source_bytes: bytes,
        parent_id: str, nodes: list[UniversalNode],
        edges: list[UniversalEdge],
    ) -> str:  # line 295

    def _get_docstring(
        self, func_or_class_node, source_bytes: bytes,
    ) -> Optional[str]:  # line 374
```

```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/persist.py

class GraphIndexPersistence:  # line 101
    def __init__(self, graph_store: OntologyGraphStore) -> None:  # line 113

    async def persist_graph(
        self, ctx: TenantContext,
        nodes: list[UniversalNode],
        edges: list[UniversalEdge],
    ) -> dict[str, Any]:  # line 121

    async def replace_document_slice(
        self, ctx: TenantContext, document_uri: str,
        nodes: list[UniversalNode],
        edges: list[UniversalEdge],
    ) -> dict[str, Any]:  # line 157
```

```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py

class GraphIndexBuilder:  # line 54
    def __init__(
        self,
        persistence: GraphIndexPersistence,
        embedder: GraphIndexEmbedder,
        output_dir: Optional[Path] = None,
        ignore_file: Optional[Path] = None,
        resolution_config: Optional[ResolutionConfig] = None,
        pageindex_toolkit: Optional[PageIndexToolkit] = None,
        signal_config: Optional[SignalRelevanceConfig] = None,
        detect_communities_enabled: bool = False,
        community_resolution: float = 1.0,
    ) -> None:  # line 94
    # persistence stored at self.persistence = persistence  (line 106)

    async def build(
        self, sources: SourceConfig, ctx: TenantContext,
    ) -> BuildResult:  # line 122

    async def _extract_code(
        self, sources: SourceConfig,
    ) -> tuple[list[UniversalNode], list[UniversalEdge]]:  # line 404
    # Currently hardcodes: extractor = CodeExtractor()
```

```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py

class UniversalNode(BaseModel):  # line 71
    node_id: str                                       # line 90
    kind: NodeKind                                     # line 91
    title: str                                         # line 92
    source_uri: str                                    # line 93
    content_ref: Optional[str] = None                  # line 94
    summary: Optional[str] = None                      # line 95
    embedding_ref: Optional[str] = None                # line 96
    domain_tags: dict = Field(default_factory=dict)    # line 97
    parent_id: Optional[str] = None                    # line 98
    provenance: Provenance = Provenance.EXTRACTED       # line 99

class UniversalEdge(BaseModel):  # line 102
    source_id: str                                     # line 118
    target_id: str                                     # line 119
    kind: EdgeKind                                     # line 120
    provenance: Provenance = Provenance.EXTRACTED       # line 121
    confidence: Optional[float] = None                 # line 122
```

### Does NOT Exist (Anti-Hallucination)

- ~~`SQLitePersistence`~~ — does not exist; must be created as `persist_sqlite.py`
- ~~`OdooCodeExtractor`~~ — does not exist; must be created as `extractors/odoo_code.py`
- ~~`SQLiteGraphReader`~~ — does not exist; must be created as `sqlite_reader.py`
- ~~`CodeExtractor.extract(..., mtime=...)`~~ — `mtime` param does not exist yet
- ~~`EdgeKind.EXTENDS`~~ — does not exist in enum yet
- ~~`RelationType.EXTENDS`~~ — does not exist in enum yet
- ~~`GraphIndexPersistence.is_stale()`~~ — no such method on the ArangoDB backend
- ~~`domain_tags["lineno"]` / `domain_tags["end_lineno"]`~~ — not stamped by current `_extract_class` or `_extract_function`
- ~~`domain_tags["sha1"]`~~ — not computed by current `extract()`
- ~~`GraphIndexBuilder.__init__(..., code_extractor_class=...)`~~ — no such param yet

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Extractor subclassing**: Override `_extract_class`, call `super()` for
  non-matching cases. Import `_make_node_id` and `_get_node_text` from
  `extractors.code` module level. Pattern verified in `code.py:34-58`.
- **Persistence parity**: Match `GraphIndexPersistence` public API
  (`persist_graph`, `replace_document_slice`). Add `is_stale` as a new
  method that the ArangoDB backend lacks (optional protocol).
- **Test fixtures**: Use in-memory tree-sitter parsing with string source
  (as in `test_code_extractor.py`). Use `tmp_path` for SQLite artefacts.
- **Enum extension**: Add member + mapping entry. Exact pattern from
  FEAT-239 (4 members added to `RelationType` in the same cycle).
- **Builder injection**: Persistence is already injected via constructor
  param. Add `code_extractor_class` with default `CodeExtractor` to maintain
  backward compatibility.

### Known Risks / Gotchas

- **Canonical node lifecycle**: Canonical `odoo_model` nodes use synthetic
  `source_uri` (`odoo-model://...`) so `replace_document_slice` won't delete
  them. Trade-off: orphan canonicals accumulate when all classes referencing
  a model are deleted. Acceptable in v1; analytics can flag them.
- **Extractor selection is additive, not breaking**: The `code_extractor_class`
  param defaults to `CodeExtractor`, so all existing builder usage is unaffected.
- **aiosqlite version compatibility**: Currently transitive via `asyncdb>=2.11.6`.
  Making it explicit in `graphindex` extra — verify version range doesn't conflict.
- **FTS5 tokenizer choice**: Using `unicode61` (brainstorm choice). Adequate
  for code identifiers (snake_case splits on underscore). If CamelCase splitting
  is needed later, a custom tokenizer can replace it.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `rustworkx` | `>=0.15` | Already in graphindex extra. In-memory graph for reader HOT path. |
| `aiosqlite` | `>=0.17` | **Add to graphindex extra.** Async SQLite for persistence + reader. |
| `orjson` | `>=3.9` | **Add to graphindex extra.** Fast JSON for domain_tags serialization. |
| `tree-sitter` | `>=0.23` | Already in graphindex extra. AST parsing for extractor. |
| `tree-sitter-languages` | `>=1.10` | Already in graphindex extra. Python grammar. |

---

## 8. Open Questions

- [x] **OKF `RelationType` for `EXTENDS`**: option (a) or (b)? — *Resolved in proposal*:
  Option (a) — add `RelationType.EXTENDS` directly. The enum was just extended by
  FEAT-239 with zero friction.
- [x] **Is `SQLitePersistence` already implemented?** — *Resolved in proposal*:
  No. It must be built as part of this feature. The brainstorm incorrectly claims
  it is "ya entregado."
- [x] **Should `OdooCodeExtractor` always replace `CodeExtractor` or be selectable?** —
  *Resolved by user*: Selectable via builder constructor parameter
  (`code_extractor_class`).
- [x] **Should `aiosqlite` be explicit in `graphindex` extra?** —
  *Resolved by user*: Yes, add explicitly for clean dependency boundaries.

---

## Worktree Strategy

- **Isolation unit**: per-spec (sequential tasks in one worktree)
- **All 7 modules run sequentially** — each builds on the previous.
  Module 1 (schema) must land before Module 4 (extractor) can import
  `EdgeKind.EXTENDS`, and Module 3 (persistence) before Module 5 (reader).
- **Cross-feature dependencies**: None. FEAT-239 (OKF frontmatter) is already
  merged into `dev`. No other pending features touch the same files.
- **Recommended worktree**:
  ```bash
  git worktree add -b feat-240-odoo-graphindex-code \
    .claude/worktrees/feat-240-odoo-graphindex-code HEAD
  ```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-06-16 | Jesus Lara / Claude Code | Initial spec from accepted proposal FEAT-240 |
