---
type: Wiki Overview
title: FEAT-240 — GraphIndex Odoo-aware extractor + SQLite persistence + graph reader
id: doc:sdd-proposals-odoo-graphindex-code-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The brainstorm proposes three capabilities for the GraphIndex pipeline, enabling
relates_to:
- concept: mod:parrot.knowledge.okf
  rel: mentions
---

---
id: FEAT-240
title: "GraphIndex Odoo-aware extractor + SQLite persistence + graph reader"
slug: odoo-graphindex-code
type: feature
mode: enrichment
status: accepted
source:
  kind: file
  jira_key: null
  jira_url: null
  fetched_at: 2026-06-16
  summary_oneline: "Odoo-aware code extractor, SQLite persistence backend, and graph reader for navigable Odoo repositories"
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-240/
created: 2026-06-16
updated: 2026-06-16
---

# FEAT-240 — GraphIndex Odoo-aware extractor + SQLite persistence + graph reader

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `file: sdd/proposals/odoo-graphindex-code.brainstorm.md`
> **Audit**: [`sdd/state/FEAT-240/`](../state/FEAT-240/)

---

## 0. Origin

The brainstorm proposes three capabilities for the GraphIndex pipeline, enabling
navigable, searchable access to Odoo code repositories without vectorization:

> **`OdooCodeExtractor`** — subclass of `CodeExtractor` capturing Odoo model semantics
> (`_name`/`_inherit`/`_inherits`, `fields.*`, `@api.*`) and emitting `EXTENDS` edges
> to canonical model nodes.
>
> **`SQLitePersistence`** — per-tenant SQLite backend parallel to ArangoDB, with WAL,
> FTS5, and incremental staleness checks.
>
> **`SQLiteGraphReader`** — read side with HOT topology in rustworkx (instant navigation)
> and COLD source bodies on demand (LRU + FTS5/BM25 search).

Guide use case: *discover what a third-party Odoo module adds to a core model
(e.g. `res.partner`) without reading the code manually.* Resolved as deterministic
graph traversal, not semantic similarity.

**Initial signals**:
- Verbs: "dar acceso navegable y buscable" → feature enrichment
- Named entities: Odoo, GraphIndex, SQLite, rustworkx, FTS5, tree-sitter
- Components: graphindex extractors, persistence, schema
- Acceptance criteria provided: yes (15 criteria in brainstorm §8)

---

## 1. Synthesis Summary

This feature extends the GraphIndex pipeline with Odoo-domain awareness and a lightweight
SQLite persistence/read path. The brainstorm is detailed and largely accurate — its
proposed code aligns well with the actual `CodeExtractor` patterns (`_make_node_id`,
`_get_node_text`, `_extract_class` override), the schema extension points (`EdgeKind`,
`RelationType`), and the pipeline architecture. **One critical correction**: the brainstorm
claims `SQLitePersistence` is "already delivered" — it is not; it must be implemented as
part of this feature, adding a significant task. All required dependencies (rustworkx,
aiosqlite, orjson, tree-sitter) are already available in the project. The OKF shared
ontology module (FEAT-239, merged same day) provides the exact extension pattern for
`RelationType.EXTENDS`.

---

## 2. Codebase Findings

> All entries in this section are grounded in the research findings persisted
> at `sdd/state/FEAT-240/findings/`. Each cites the finding ID(s) that justify
> its inclusion. **No fabricated paths or symbols.**

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py` | `EdgeKind` | 53-68 | Add `EXTENDS = "extends"` member | F001 |
| 2 | `packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/code.py` | `CodeExtractor` | 95-344 | Add `mtime` param, `sha1` stamping, `lineno`/`end_lineno` in domain_tags | F002 |
| 3 | `packages/ai-parrot/src/parrot/knowledge/graphindex/meta_ontology.py` | `EDGE_KIND_TO_COLLECTION` | 195-201 | Add `"extends": "gi_extends"` + `RelationDef` | F003 |
| 4 | `packages/ai-parrot/src/parrot/knowledge/graphindex/projection.py` | `EDGE_KIND_TO_RELATION_TYPE` | 65-71 | Add `EdgeKind.EXTENDS → RelationType.EXTENDS` | F004 |
| 5 | `packages/ai-parrot/src/parrot/knowledge/okf/ontology.py` | `RelationType` | 58-82 | Add `EXTENDS = "extends"` member | F004 |
| 6 | `packages/ai-parrot/src/parrot/knowledge/graphindex/persist.py` | `GraphIndexPersistence` | 101-306 | Reference for SQLitePersistence API surface parity | F005 |
| 7 | `packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py` | `GraphIndexBuilder` | 54-576 | Wire extractor selection, `mtime` passing, SQLite backend | F006 |
| 8 | `packages/ai-parrot/pyproject.toml` | `graphindex` extra | 158-163 | Add `aiosqlite`, `orjson` to explicit deps | F007 |

### 2.2 Constraints Discovered

- **Backward-compatible CodeExtractor changes.** `mtime` as `Optional` kwarg,
  `sha1`/`lineno` as additive domain_tags keys. All existing callers (builder,
  loader, tests) remain unaffected — they pass only `file_path` and `source`.
  *Evidence*: F002, F006

- **OdooCodeExtractor must fall back for non-Odoo classes.** The brainstorm correctly
  calls `super()._extract_class()` when no Odoo signals are detected (`_name`,
  `_inherit`, `_inherits`, or Odoo base classes). This ensures mixed Python/Odoo
  repos work transparently.
  *Evidence*: F002

- **Canonical model nodes need synthetic `source_uri`.** Using `odoo-model://<name>`
  prevents `replace_document_slice` from deleting the canonical node when refreshing
  a single file. This is well-reasoned and correct — the ArangoDB backend's
  `replace_document_slice` filters by `source_uri`.
  *Evidence*: F005

- **ArangoDB parity is optional for EXTENDS.** `meta_ontology.py` needs `gi_extends`
  collection + `RelationDef` only if the ArangoDB backend must also persist EXTENDS
  edges. The SQLite backend handles edge kinds natively via a `kind` column.
  *Evidence*: F003

- **Pipeline persistence is already injected.** `GraphIndexBuilder.__init__` accepts
  a persistence instance — swapping ArangoDB for SQLite is a constructor param, not
  a code change. Extractor selection is the harder wiring task.
  *Evidence*: F006

- **FEAT-239 established the extension pattern.** The OKF shared ontology module
  (`parrot.knowledge.okf`) was just extracted and extended with 4 new `RelationType`
  members + 5 new `ConceptType` members. Adding `EXTENDS` follows the identical
  pattern with zero friction.
  *Evidence*: F004, F009

### 2.3 Recent History (Relevant)

| Commit | When | Message | Impact |
|--------|------|---------|--------|
| `fd4b89ca2` | 2026-06-16 | Merge feat-239-graphindex-frontmatter | Added projection.py, OKF shared module — directly extends the files this feature touches |
| `6c9d34e44` | 2026-06-16 | Merge feat-215-graphindex-analytics-insights | Enhanced analytics — graph reader could leverage gap detection |
| `95bd7022b` | recent | Merge feat-217-graph-expanded-retrieval | Added retriever.py — pattern for reader-side components |

> 30 commits on graphindex paths in last 60 days. The module is actively maintained
> and patterns are fresh. (F009)

---

## 3. Probable Scope *(enrichment mode)*

### What's New

- **`SQLitePersistence`** (`persist_sqlite.py`) — Per-tenant `.db` artefact with WAL,
  `files` table for staleness tracking, `nodes`/`edges` tables, `nodes_fts` for
  FTS5/BM25 search. API parity with `GraphIndexPersistence`: `persist_graph`,
  `replace_document_slice`, plus `is_stale(ctx, source_uri, mtime, sha1)`.

- **`OdooCodeExtractor`** (`extractors/odoo_code.py`) — Subclass of `CodeExtractor`.
  Overrides `_extract_class` to detect Odoo model classes (via `_name`/`_inherit`/
  `_inherits` assignments or `Model`/`TransientModel`/`AbstractModel` bases). Emits
  canonical `odoo_model` nodes, `EXTENDS`/`DEFINES` edges, `odoo_field` nodes for
  `fields.*` declarations, and `@api.*` decorator annotations.

- **`SQLiteGraphReader`** (`sqlite_reader.py`) — HOT topology in `rustworkx.PyDiGraph`
  loaded once at startup. Sync navigation: `list_models()`, `find_model()`,
  `who_extends()`, `children()`. Async I/O: `search_symbols()` (FTS5/BM25),
  `get_source()` (disk-based line-span resolution with LRU cache).

### What Changes

- **`schema.py`::EdgeKind** — Add `EXTENDS = "extends"` *Evidence*: F001
- **`ontology.py`::RelationType** — Add `EXTENDS = "extends"` *Evidence*: F004
- **`meta_ontology.py`::EDGE_KIND_TO_COLLECTION** — Add `"extends": "gi_extends"` + `RelationDef` *Evidence*: F003
- **`projection.py`::EDGE_KIND_TO_RELATION_TYPE** — Add EXTENDS mapping *Evidence*: F004
- **`extractors/code.py`::CodeExtractor** — Add `mtime` kwarg to `extract()`, stamp `sha1` + `lineno`/`end_lineno` in `domain_tags` *Evidence*: F002
- **`builder.py`::GraphIndexBuilder** — Configurable extractor (CodeExtractor vs OdooCodeExtractor), pass `mtime` to extract, support SQLite backend selection *Evidence*: F006
- **`pyproject.toml`** — Add `aiosqlite` and `orjson` to `graphindex` extra *Evidence*: F007

### What's Untouched (Non-Goals)

- **Embedding pipeline** (`embed.py`) — no embeddings or `embedding_ref` in v1
- **MCP exposure** — explicitly descoped per brainstorm
- **XML/OWL/JS parsing** — possible v2 via tree-sitter multi-language
- **Dynamic `_name`/`_inherit` resolution** (f-strings, concatenation) — graceful degradation, not failure
- **Orphan canonical node recolection** — descoped; analytics can mark them later

### Patterns to Follow

- **Extractor subclassing**: Override `_extract_class`, call `super()` for non-matching
  cases. Exactly what `SkillExtractor` does for non-skill files. *Evidence*: F002
- **Persistence parity**: Match `GraphIndexPersistence` API surface. Injected via
  constructor — no factory needed. *Evidence*: F005, F006
- **Test pattern**: Fixtures with in-memory tree-sitter parsing, `tmp_path` for
  SQLite artefacts, explicit assertion on node/edge counts + domain_tags. *Evidence*: F008
- **OKF enum extension**: Add member to enum + add mapping in projection.py. Exact
  pattern from FEAT-239. *Evidence*: F004, F009

### Integration Risks

- **CodeExtractor signature change**: Adding `mtime` as `Optional[float] = None`
  kwarg is safe — all 3 callers (builder, loader, tests) use positional-only for
  the existing params. Risk: **low**. *Evidence*: F002, F006

- **Extractor hardcoding in builder**: `_extract_code` creates `CodeExtractor()`
  directly. Refactoring to accept a configurable extractor class is the riskiest
  change, though straightforward. Risk: **medium**. *Evidence*: F006

- **aiosqlite version pinning**: Currently transitive via asyncdb. Making it explicit
  could conflict if asyncdb pins a specific version. Risk: **low** — check version
  ranges. *Evidence*: F007

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | `EdgeKind.EXTENDS` is a one-line addition to `schema.py` | F001 | high | Direct read of enum; no exhaustive iteration in downstream code |
| C2 | `CodeExtractor.extract()` signature change is backward-compatible | F002 | high | Optional kwarg; all callers verified to use positional-only |
| C3 | `RelationType` is trivially extensible (FEAT-239 just added 4 members) | F004, F009 | high | Same-day merge proves the pattern |
| C4 | `SQLitePersistence` does NOT exist — must be implemented | F005 | high | Exhaustive grep; 0 matches in entire codebase |
| C5 | Builder persistence is injected; SQLite backend swaps in cleanly | F006 | high | Constructor injection pattern verified |
| C6 | All runtime dependencies already available | F007 | high | rustworkx in extra; aiosqlite/orjson transitive |
| C7 | Brainstorm's `OdooCodeExtractor` design follows CodeExtractor patterns | F002 | high | Imports `_make_node_id`, `_get_node_text`; overrides `_extract_class` correctly |
| C8 | Brainstorm's `SQLiteGraphReader` HOT/COLD design is sound | F007 | medium | rustworkx available; aiosqlite proven elsewhere; LRU is standard — but reader hasn't been prototyped |
| C9 | 19 existing tests provide strong pattern baseline for new tests | F008 | high | Direct listing of test files and their coverage |
| C10 | Extractor selection in builder is hardcoded — needs refactoring | F006 | high | Direct read of `_extract_code` method |

Distribution: **8** high, **1** medium, **0** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **Does `RelationType` support extension?** — *Resolved*: Yes, trivially.
  FEAT-239 just added 4 new members to the enum in the same commit cycle.
  Recommend option (a) from brainstorm: add `RelationType.EXTENDS` directly.
  *Resolves claims*: C3

- [x] **Is SQLitePersistence already implemented?** — *Resolved*: No. The brainstorm
  incorrectly states it is "ya entregado." It must be built as part of this feature.
  *Resolves claims*: C4

- [x] **Should OdooCodeExtractor always replace CodeExtractor or be selectable?** —
  *Resolved*: Selectable. Make the extractor configurable via builder constructor param.
  *Resolves claims*: C10

- [x] **Should aiosqlite be an explicit graphindex extra dependency?** —
  *Resolved*: Yes, add explicitly to the `graphindex` extra for clean dependency boundaries.
  *Resolves claims*: C6

### Unresolved

(none — all questions resolved)

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-240`** — *Rationale*: The brainstorm provides detailed code-level
design with 15 acceptance criteria. All localization is high-confidence (C1-C7, C9-C10).
The critical correction (SQLitePersistence scope) is clear. A spec can be written
directly from this proposal + brainstorm, decomposing into ~6-8 tasks.

### Alternatives

- **`/sdd-brainstorm FEAT-240`** — if you want to explore alternative architectures
  (e.g., using DuckDB instead of SQLite, or a different reader topology strategy).
- **`/sdd-task FEAT-240`** — only if you accept the brainstorm design as-is and want
  to skip the spec step (risky given the SQLitePersistence scope correction).
- **Manual review** — if you want to validate the brainstorm's tree-sitter AST
  walking approach against complex Odoo codebases before committing to the design.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-240/state.json` |
| Source (raw) | `sdd/state/FEAT-240/source.md` |
| Findings (digests) | `sdd/state/FEAT-240/findings/F001-*.md` through `F009-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-240/synthesis.json` |

**Budget consumed**:
- Files read: ~25 / 40
- Grep calls: ~18 / 25
- Git calls: ~6 / 10
- Truncated: **no**

**Mode determination**: `auto` → resolved to `enrichment` (feature brainstorm
with detailed design, no bug indicators).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Operator | Claude Code (FEAT-240 proposal session) |
| Source document | `sdd/proposals/odoo-graphindex-code.brainstorm.md` |
| Research agents | 3 parallel Explore agents (schema+extractors, OKF+deps, git history) |
| Findings count | 9 (F001–F009) |
