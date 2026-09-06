---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Bookstore Conceptual Relations — a book graph with communities over the ficha catalog

**Feature ID**: FEAT-533
**Date**: 2026-09-06
**Author**: Jesus Lara (spec: Claude session 2026-09-06)
**Status**: approved
**Target version**: next minor
**Input**: `sdd/proposals/wikitoolkit-bookstore-conceptual-relations.brainstorm.md` (Recommended Option A)

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

The Bookstore (`parrot.knowledge.bookstore`, spec
`sdd/specs/bookstore-indexed-library.spec.md`) is a flat catalog: one
`BookCard` ("ficha") per book in a SQLite + FTS5 `library.db`, plus one
PageIndex tree per book. The only cross-book capability is lexical
(`catalog_search` → shortlist → per-book tree walk). **There are no
relations between books.** A research agent that finds a note in a
Calderón de la Barca play has no way to discover the same author's other
works, sibling works of the Spanish Golden Age, or conceptually adjacent
works (Confucius' *Analects* ↔ Marcus Aurelius' *Meditations* as two
virtue-ethics traditions) unless the query text happens to overlap
lexically.

Three relation families are wanted, with different determinism:

| Relation family | Deterministic? | Source of truth |
|---|---|---|
| Authorship / topic / language / era | yes | fields already on `BookCard` |
| Classification (genre, tradition/school, period) | mostly, once classified | **new LLM-filled card fields** (the carding LLM already runs at ingest) |
| Conceptual (influenced_by, responds_to, parallels, contrasts_with) | no | **new pairwise LLM judgement** with rationale + confidence |
| Community membership | derived | graph clustering over the edges above |

Communities (Leiden → Louvain fallback) exist today **only in
wikitoolkit**: `graphindex.communities.detect_communities` runs over the
wiki store's pages + typed edges (`wiki/cli.py:_load_graphindex_nodes_edges`
→ `GraphAssembler` → `detect_communities` → `compute_inter_community_graph`).
Bookstore computes nothing of the kind because it has no graph to cluster.

### Goals

- **G1 — Classification rides the existing carding call.** `CardDraft`/`BookCard` gain `genre` (closed enum), `traditions[]` and `period` (free text, slug-normalised) at zero extra LLM cost; they are FTS-indexed.
- **G2 — A typed, provenance-bearing book graph in `library.db`.** A `book_relations` table where every edge carries `rel`, `origin` (`deterministic|llm|community`), `weight`, `confidence` and `rationale`, so an agent can tell "same author" from "parallels, LLM-inferred (0.7)".
- **G3 — Bounded LLM cost.** Conceptual relations run only in the explicit `bookstore relate` batch (or `add --relate`), over pre-filtered candidates (deterministic neighbours ∪ FTS top-k, cap 8), **one structured prompt per book**, with a 0.5 confidence floor and a `relation_judgements` log so already-judged pairs are never re-asked without `--force`.
- **G4 — Communities via graphindex, persisted on the ficha.** One merged project+global graph, `detect_communities` (Leiden, Louvain fallback) with **rel-weighted edges** (small graphindex extension), LLM-labelled with `derive_community_label` fallback; `community_id`/`community_label` stored per card, inter-community relations stored per community.
- **G5 — Read-only agent navigation tools.** `bookstore_related_books`, `bookstore_communities`, `bookstore_get_community`, plus an opt-in `expand_related` flag on `bookstore_search`; skill funnel step 1b.
- **G6 — `bookstore export-wiki`.** Projects cards + edges into a dedicated wikitoolkit plane (category `book`, typed edges, `graph.html`) and registers it as a wikitoolkit namespace named `bookstore` (repo `.parrot/wiki.json` for project scope, `~/.parrot/wikis.json` for global) so `wikitoolkit query --ns bookstore` works.
- **G7 — No-LLM mode keeps working.** Deterministic relations and communities run without a model; classification and conceptual relations degrade to "absent", like `fallback_card_fields` today.
- **G8 — Additive schema, no breaking change.** New columns via `_ADDED_COLUMNS`; new tables `CREATE IF NOT EXISTS`; old libraries read back with empty classification and no relations; `relate --all` backfills.

### Non-Goals (explicitly out of scope)

- Making wikitoolkit the source of truth for book relations (brainstorm Option B, rejected: it couples the stdio MCP server to `parrot.knowledge.wiki`). The MCP read path imports **no** wiki module.
- Embedding-similarity edges (brainstorm Option C). `detect_communities(signal_config=…, embedder=…)` already supports it; revisit after a first real-library run (§8).
- Author aliasing across languages ("Marco Aurelio" vs "Marcus Aurelius") as a deterministic feature — that is the LLM `parallels`/conceptual layer's job.
- Any write tool over MCP. Relate/communities/export remain CLI-only, same rule as ingestion (`bookstore-indexed-library.spec.md` §4).
- Hierarchical (multi-resolution) communities; `detect_hierarchical_communities` exists but v1 stores one partition.

---

## 2. Architectural Design

### Overview

Option A from the brainstorm: **the book graph lives inside Bookstore's own
SQLite catalog; graphindex is reused for clustering; wikitoolkit is an
explicit export target.**

1. **Classification at carding.** `_CARD_PROMPT` asks for `genre`,
   `traditions`, `period` in the same `ask_structured(prompt, CardDraft)`
   call. `fallback_card_fields` leaves them empty. Traditions are
   `slugify`-normalised before persistence so "Estoicismo" and
   "estoicismo" collide. `books_fts` gains `genre` and `traditions_text`
   columns; because FTS5 virtual tables cannot `ALTER`, `_ensure_schema`
   detects an old column set via `PRAGMA table_info(books_fts)` and
   rebuilds the FTS table from `books` once.

2. **`book_relations`** (per scope DB): `(src_book_id, dst_book_id, rel,
   weight, origin, confidence, rationale, computed_at)`, PK `(src, dst,
   rel)`, `CHECK (src_book_id <> dst_book_id)`. Symmetric rels are stored
   once with `src < dst`; directed rels (`influenced_by`, `responds_to`)
   as judged. **Cross-scope storage rule (resolved):** an edge is stored
   in the DB of the scope that owns its `src` book; the merged reader
   unions both DBs and drops edges whose endpoints are not both visible
   in `merged_cards()`. A global book may therefore relate to books of
   several projects, and each project sees only its own.

3. **`relations.py` — the engine**, three stages orchestrated by
   `Bookstore.relate_books(book_ids | all, *, use_llm, communities, force)`:
   - *Stage 1 deterministic* (no LLM, O(n²) over ≤ hundreds of cards):
     `same_author` (slugified author intersection), `shares_topic`
     (Jaccard over slugified topics ≥ 0.2, weight = Jaccard),
     `same_tradition` (shared tradition slug), `same_genre`, `same_era`
     (`|year_a − year_b| ≤ 50` or equal `period` slug), `same_language`.
     Deterministic edges for the target books are rewritten from scratch
     each run (idempotent).
   - *Stage 2 conceptual (LLM)*: per target book, candidates = Stage-1
     neighbours ∪ `catalog_search(summary + topics, top_k=8)` minus self
     minus pairs present in `relation_judgements` (unless `force`),
     capped at 8. One `ask_structured(prompt, RelationDraft)` per book
     with all candidate briefs; the model returns `judgements[]` of
     `{dst_book_id, rel, confidence, rationale}` (`rel="none"` allowed).
     Every judged pair is logged in `relation_judgements(src, dst,
     judged_at, model, rel, confidence)`; only `confidence ≥ 0.5` and
     `rel != "none"` become `book_relations` rows with `origin="llm"`.
     Skipped entirely when `has_llm` is `False` or `--no-llm`.
   - *Stage 3 communities*: cards → `UniversalNode(kind=DOCUMENT,
     source_uri=source_path, summary=summary,
     domain_tags={genre, traditions, scope, book_id})`; relations
     (excluding `same_community`) → `UniversalEdge(kind=REFERENCES,
     provenance=EXTRACTED|INFERRED, confidence=<llm only>,
     domain_tags={rel, origin, weight})` through
     `GraphAssembler(tenant_id="bookstore")`; then
     `detect_communities(graph, nodes, resolution, seed=42)` and
     `compute_inter_community_graph`. **Edge weight (resolved):**
     graphindex's `_to_undirected_networkx` and `_to_igraph` are extended
     to read `payload.get("weight", 1.0)` when no `signal_config` is
     given (Module 0), so rel weights (`REL_WEIGHTS`, e.g.
     `influenced_by=1.0`, `same_author=0.9`, `parallels=0.8`,
     `same_tradition=0.7`, `shares_topic=jaccard`, `same_genre=0.3`,
     `same_era=0.3`, `same_language=0.1`) shape the partition. Results
     are persisted: `community_id` + `community_label` on every card,
     `same_community` edges (`origin="community"`) rewritten from
     scratch, and one row per community in a `communities` table (id,
     label, label_origin, algorithm, size, cohesion, centroid,
     members JSON, inter_relations JSON, computed_at). Communities are
     skipped (with a note) when fewer than 3 cards are visible.
   - *Community labelling*: with an LLM, one `ask_structured(prompt,
     CommunityLabelDraft)` per community from member titles/traditions/
     topics; fallback `derive_community_label(titles)`; singleton →
     the book title.

4. **Read path** (`Bookstore.related_books`, `Bookstore.communities`,
   `Bookstore.get_community`): pure SQL over the per-scope DBs, merged in
   Python, project wins duplicates, dangling endpoints dropped. No graph
   library, no LLM, no wiki import — the MCP server stays lean.

5. **`export-wiki`** (CLI-only, lazy `parrot.knowledge.wiki` import):
   opens `SQLiteWikiStore(<library>/wiki/wiki.db, wiki_name="bookstore")`,
   upserts one `WikiPageRecord` per card (`concept_id="book:<book_id>"`,
   `category="book"`, `summary`, body = rendered ficha + ToC digest,
   `source_id=source_path`, `origin="ingest"`), adds edges
   `(src, dst, rel, provenance)` with `extracted` for deterministic and
   community rels and `inferred` for LLM rels, then writes
   `graph.html`/`graph.json` via `export_graph` with the same
   communities/inter-community objects. **Namespace registration
   (resolved):** by default the command also registers a namespace
   `bookstore` as a `store` entry (`backend="sqlite"`, `store=<wiki dir>`,
   `description="Bookstore book graph"`): in `.parrot/wiki.json` of the
   git root when exporting the project scope, in `PARROT_HOME/wikis.json`
   when exporting the global scope; `--no-register` skips it, and an
   existing entry with a *different* store path is refused (the user
   must `wikitoolkit ns remove bookstore` first), matching `ns add`
   semantics.

### Component Diagram

```
bookstore add --relate ──┐
bookstore relate ────────┤
                         ▼
             Bookstore.relate_books()
                         │
      ┌──────────────────┼───────────────────────┐
      ▼                  ▼                       ▼
relations.deterministic  relations.llm_judge     relations.detect_book_communities
 (Stage 1, no LLM)       (Stage 2, 1 prompt/book) (Stage 3 → graphindex)
      │                  │                       │   GraphAssembler → detect_communities
      └────────┬─────────┘                       │   → compute_inter_community_graph
               ▼                                 ▼
   CatalogStore.book_relations   CatalogStore.communities + cards.community_id
               │                                 │
               └──────────────┬──────────────────┘
                              ▼
        Bookstore.related_books / communities / get_community   (SQL only)
                              │
            ┌─────────────────┼──────────────────────┐
            ▼                 ▼                      ▼
   BookstoreToolkit       bookstore CLI          bookstore export-wiki
   (3 new MCP tools,      (relate/related/        SQLiteWikiStore pages+edges
    expand_related)        communities)           + export_graph(graph.html)
                                                  + ns register "bookstore"
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `bookstore/models.py` (`CardDraft`, `BookCard`) | extends | new fields; new `BookRelation`, `RelationDraft`, `RelationJudgement`, `BookCommunity`, `CommunityLabelDraft` |
| `bookstore/catalog.py` (`CatalogStore`) | extends | `_ADDED_COLUMNS` entries, new DDL for `book_relations`/`relation_judgements`/`communities`, FTS rebuild, relation/community CRUD, merged readers |
| `bookstore/carding.py` | modifies | `_CARD_PROMPT` asks for classification; `fallback_card_fields` unchanged semantics |
| `bookstore/relations.py` (new) | new | Stages 1–3 + graphindex adapter + prompts |
| `bookstore/library.py` (`Bookstore`) | extends | `relate_books`, `related_books`, `communities`, `get_community`, `export_wiki`; `remove_book` cascades edges/judgements; `add_book(relate=)`; `search(expand_related=)` |
| `bookstore/toolkit.py` (`BookstoreToolkit`) | extends | 3 new tools, `expand_related` param |
| `bookstore/cli.py` | extends | `relate`, `related`, `communities`, `export-wiki`; `add --relate`, `add-folder --relate`, `list --by-community` |
| `bookstore/mcp_server.py` | modifies | docstring/tool count only (tools come from the toolkit) |
| `.agent/skills/bookstore/SKILL.md`, `.claude/commands/bookstore.md`, `wiki/google/bookstore_assets.py::BOOKSTORE_SKILL` | modifies | funnel step 1b + citation rule (three mirrors of the same text) |
| `graphindex/communities.py` (`_to_undirected_networkx`, `_to_igraph`) | modifies (Module 0) | honour `payload["weight"]` when no `signal_config`; `CommunitiesResult.weighted` becomes `True` when any payload weight ≠ 1.0 |
| `graphindex/assemble.py`, `schema.py`, `inter_community.py`, `export_html.py` | uses | unchanged |
| `wiki/store.py` (`SQLiteWikiStore`, `WikiPageRecord`), `wiki/project.py` (namespace registry) | uses (lazy, CLI-only) | export + `ns` registration |
| `tests/knowledge/bookstore/conftest.py::make_adapter` | extends | `_structured` side-effect learns `RelationDraft`, `CommunityLabelDraft`, and the classification fields on `CardDraft` |

### Data Models

```python
# bookstore/models.py — additions (design, not implementation)

Genre = Literal[
    "novel", "short_stories", "essay", "treatise", "poetry", "drama",
    "dialogue", "biography", "history", "letters", "reference", "manual",
    "other",
]

RelationKind = Literal[
    # deterministic (origin="deterministic")
    "same_author", "shares_topic", "same_tradition", "same_genre",
    "same_era", "same_language",
    # conceptual (origin="llm") — directed: influenced_by, responds_to
    "influenced_by", "responds_to", "parallels", "contrasts_with",
    # derived (origin="community")
    "same_community",
]
SYMMETRIC_RELS: frozenset[str]   # everything except influenced_by / responds_to
REL_WEIGHTS: dict[str, float]    # default clustering weights per rel (§2 Overview)

class CardDraft(BaseModel):          # existing fields unchanged, plus:
    genre: Genre = "other"
    traditions: list[str] = []       # free text; slug-normalised on persist
    period: Optional[str] = None     # free text, e.g. "siglo de oro", "han dynasty"

class BookCard(BaseModel):           # existing fields unchanged, plus:
    genre: Genre = "other"
    traditions: list[str] = []
    period: Optional[str] = None
    community_id: Optional[str] = None
    community_label: Optional[str] = None
    # brief() adds genre, traditions, period, community_id, community_label

class BookRelation(BaseModel):
    src_book_id: str
    dst_book_id: str
    rel: RelationKind
    weight: float = 1.0
    origin: Literal["deterministic", "llm", "community"]
    confidence: Optional[float] = None     # llm only, [0, 1]
    rationale: str = ""
    computed_at: str

class RelationJudgement(BaseModel):        # one LLM verdict on one candidate pair
    dst_book_id: str
    rel: Literal["influenced_by", "responds_to", "parallels", "contrasts_with", "none"]
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = ""

class RelationDraft(BaseModel):            # structured output, one per source book
    judgements: list[RelationJudgement] = []

class CommunityLabelDraft(BaseModel):      # structured output, one per community
    label: str                             # ≤ 6 words
    description: str = ""                  # one sentence

class BookCommunity(BaseModel):
    community_id: str                      # graphindex Community.community_id (membership hash)
    label: str
    label_origin: Literal["llm", "derived", "title"]
    description: str = ""
    algorithm: Literal["leiden", "louvain"]
    size: int
    cohesion: float
    centroid_book_id: str
    member_book_ids: list[str]
    inter_relations: list[dict]            # InterCommunityRelation.model_dump() rows touching this community
    computed_at: str
```

SQLite DDL (additive, per scope `library.db`):

```sql
-- books: via _ADDED_COLUMNS
ALTER TABLE books ADD COLUMN genre TEXT NOT NULL DEFAULT 'other';
ALTER TABLE books ADD COLUMN traditions TEXT NOT NULL DEFAULT '[]';   -- JSON
ALTER TABLE books ADD COLUMN period TEXT;
ALTER TABLE books ADD COLUMN community_id TEXT;
ALTER TABLE books ADD COLUMN community_label TEXT;

-- books_fts: rebuilt once when the column set differs (FTS5 cannot ALTER)
--   + genre, traditions_text

CREATE TABLE IF NOT EXISTS book_relations (
    src_book_id TEXT NOT NULL,
    dst_book_id TEXT NOT NULL,
    rel         TEXT NOT NULL,
    weight      REAL NOT NULL DEFAULT 1.0,
    origin      TEXT NOT NULL,            -- deterministic | llm | community
    confidence  REAL,
    rationale   TEXT NOT NULL DEFAULT '',
    computed_at TEXT NOT NULL,
    PRIMARY KEY (src_book_id, dst_book_id, rel),
    CHECK (src_book_id <> dst_book_id)
);
CREATE INDEX IF NOT EXISTS idx_book_relations_dst ON book_relations(dst_book_id);

CREATE TABLE IF NOT EXISTS relation_judgements (
    src_book_id TEXT NOT NULL,
    dst_book_id TEXT NOT NULL,
    judged_at   TEXT NOT NULL,
    model       TEXT NOT NULL DEFAULT '',
    rel         TEXT NOT NULL,            -- includes 'none'
    confidence  REAL NOT NULL,
    PRIMARY KEY (src_book_id, dst_book_id)
);

CREATE TABLE IF NOT EXISTS communities (
    community_id    TEXT PRIMARY KEY,
    label           TEXT NOT NULL,
    label_origin    TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    algorithm       TEXT NOT NULL,
    size            INTEGER NOT NULL,
    cohesion        REAL NOT NULL,
    centroid_book_id TEXT NOT NULL,
    members         TEXT NOT NULL,        -- JSON list of book ids
    inter_relations TEXT NOT NULL DEFAULT '[]',  -- JSON
    computed_at     TEXT NOT NULL
);
```

The `communities` table is written **only** to the project DB when a
project scope exists (else global) — the partition is one merged graph
and must not be duplicated per scope; `community_id`/`community_label`
on each card go to that card's own scope DB.

### New Public Interfaces

```python
# bookstore/relations.py
def deterministic_relations(cards: list[BookCard], *, now: str) -> list[BookRelation]
def candidate_pairs(card: BookCard, cards: list[BookCard], det: list[BookRelation],
                    fts_hits: list[BookCard], judged: set[str], cap: int = 8) -> list[BookCard]
async def judge_relations(adapter, card: BookCard, candidates: list[BookCard]) -> RelationDraft
def build_book_graph(cards, relations) -> tuple[GraphAssembler, list[UniversalNode]]
def detect_book_communities(cards, relations, *, resolution=1.0, seed=42, algorithm="leiden")
    -> tuple[CommunitiesResult, InterCommunityGraph]
async def label_community(adapter, community: Community, cards_by_id) -> CommunityLabelDraft
def fallback_label(community: Community, cards_by_id) -> str

# bookstore/library.py — Bookstore
async def relate_books(self, book_ids: Optional[list[str]] = None, *, use_llm: bool = True,
                       communities: bool = True, communities_only: bool = False,
                       force: bool = False, resolution: float = 1.0) -> RelateSummary
def related_books(self, book_id: str, rel: Optional[str] = None, depth: int = 1,
                  top_k: int = 10, min_confidence: float = 0.0) -> list[dict]
def communities(self) -> list[BookCommunity]
def get_community(self, community_id: str) -> BookCommunity
async def export_wiki(self, output_dir: Optional[Path] = None, *, scope: str = "project",
                      register: bool = True) -> dict
async def add_book(..., relate: bool = False)          # new kw-only flag
async def search(..., expand_related: bool = False)    # new kw-only flag
async def remove_book(self, book_id: str) -> bool      # now cascades relations + judgements

# bookstore/toolkit.py — BookstoreToolkit (tool_prefix="bookstore")
async def related_books(self, book_id: str, rel: Optional[str] = None, depth: int = 1,
                        top_k: int = 10) -> list[dict]
async def communities(self) -> list[dict]
async def get_community(self, community_id: str) -> dict
async def search(self, query, book_ids=None, max_books=3, expand_related: bool = False)

# bookstore/cli.py — new commands
bookstore relate [BOOK_ID...] [--all] [--no-llm] [--communities-only] [--force] [--resolution F] [--llm SPEC]
bookstore related BOOK_ID [--rel REL] [--depth N] [--json]
bookstore communities [--json]
bookstore export-wiki [--out DIR] [--global] [--no-register]
bookstore add FILE --relate ; bookstore add-folder DIR --relate ; bookstore list --by-community
```

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2.

### Module 0: graphindex payload edge weights
- **Path**: `packages/ai-parrot/src/parrot/knowledge/graphindex/communities.py`, `packages/ai-parrot/tests/knowledge/graphindex/test_communities.py`
- **Responsibility**: `_to_undirected_networkx` and `_to_igraph` use `payload.get("weight", 1.0)` from the `PyDiGraph` edge payload when `signal_config` is `None` (signal weights still win when supplied); `detect_communities` sets `CommunitiesResult.weighted=True` when any payload weight differs from 1.0. Existing tests `test_unweighted_edges_have_weight_one`, `test_unweighted_flag_when_no_signal_config` must keep passing (payload-less edges stay 1.0/unweighted).
- **Depends on**: nothing (independent of bookstore; can be done first).

### Module 1: Classification + catalog schema
- **Path**: `bookstore/models.py`, `bookstore/catalog.py`, `bookstore/carding.py`, `tests/knowledge/bookstore/test_models.py`, `test_catalog.py`, `test_library.py`
- **Responsibility**: `Genre`, `RelationKind`, `SYMMETRIC_RELS`, `REL_WEIGHTS`; new `CardDraft`/`BookCard` fields and `brief()`; `BookRelation`, `RelationJudgement`, `RelationDraft`, `CommunityLabelDraft`, `BookCommunity`; `_ADDED_COLUMNS` entries; new DDL; FTS rebuild-on-column-drift; `_CARD_PROMPT` classification instructions; `slugify` normalisation of traditions on `upsert`; `refresh_card` carries the new fields; relation/judgement/community CRUD on `CatalogStore` (`upsert_relations`, `delete_relations(book_id | origin)`, `list_relations(book_id, rel)`, `record_judgements`, `judged_pairs(src)`, `upsert_communities`, `list_communities`, `get_community`) and merged readers (`merged_relations`, `merged_communities`).
- **Depends on**: none.

### Module 2: Relations engine (Stages 1–2) + CLI
- **Path**: `bookstore/relations.py` (new), `bookstore/library.py`, `bookstore/cli.py`, `tests/knowledge/bookstore/test_relations.py`, `test_cli.py`
- **Responsibility**: `deterministic_relations`, `candidate_pairs`, `judge_relations` + `_RELATION_PROMPT`; `Bookstore.relate_books` (Stages 1–2, `RelateSummary` with `related/failed/skipped` per book), `Bookstore.related_books` (depth-1/2 walk, `min_confidence`, cross-scope dangling filter), `remove_book` cascade, `add_book(relate=)`, `add_folder(relate=)`; CLI `relate`, `related`, `add --relate`, `add-folder --relate`.
- **Depends on**: Module 1.

### Module 3: Communities (Stage 3) + labelling + CLI
- **Path**: `bookstore/relations.py`, `bookstore/library.py`, `bookstore/cli.py`, `tests/knowledge/bookstore/test_communities.py`
- **Responsibility**: `build_book_graph`, `detect_book_communities` (graphindex adapter with rel weights), `label_community` + `_LABEL_PROMPT`, `fallback_label`; Stage 3 in `relate_books` (incl. `communities_only`, `< 3 cards` skip, `same_community` edge rewrite, per-card write-back, `communities` table in project-or-global DB); `Bookstore.communities`/`get_community`; CLI `communities`, `list --by-community`, `show` prints the new fields.
- **Depends on**: Module 0, Module 2.

### Module 4: Agent surface (toolkit, MCP, skill)
- **Path**: `bookstore/toolkit.py`, `bookstore/library.py` (`search(expand_related=)`), `bookstore/mcp_server.py` (docstring), `.agent/skills/bookstore/SKILL.md`, `.claude/commands/bookstore.md`, `packages/ai-parrot/src/parrot/knowledge/wiki/google/bookstore_assets.py`, `tests/knowledge/bookstore/test_toolkit.py`, `test_mcp_server.py`
- **Responsibility**: three new tools with clamps (`depth` 1–2, `top_k` 1–50), `expand_related` widening (depth-1 neighbours appended to the shortlist, still capped by `max_books`); MCP `tools/list` shows 10 tools; skill funnel step **1b — expand by relations** and the "cite the relation origin" rule, mirrored in all three skill-text locations.
- **Depends on**: Module 3.

### Module 5: `export-wiki` + namespace registration
- **Path**: `bookstore/wiki_export.py` (new), `bookstore/library.py` (`export_wiki`), `bookstore/cli.py`, `tests/knowledge/bookstore/test_export_wiki.py`
- **Responsibility**: lazy-import `parrot.knowledge.wiki.store` / `wiki.project`; cards → `WikiPageRecord` (`category="book"`), relations → `(src, dst, rel, provenance)` edges; `graph.html`/`graph.json` via `graphindex.export_html.export_graph` reusing Module 3's `CommunitiesResult`/`InterCommunityGraph`; namespace registration through `WikiNamespaceConfig(store=…, backend="sqlite", description=…)` + `load_project_config`/`save_project_config` (project scope, root = git root from `LibraryLocation`) or `load_global_registry`/`save_global_registry` (global scope); refuse on a conflicting existing entry; `--no-register`; clear `ClickException` when the wiki package is not importable.
- **Depends on**: Module 3.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_payload_weight_used_without_signal_config` | 0 | edge payload `{"weight": 0.2}` yields nx/igraph weight 0.2; `weighted=True` |
| `test_payload_weight_ignored_when_signal_config` | 0 | signal weights still win |
| `test_unweighted_edges_have_weight_one` (existing) | 0 | payload-less edges remain 1.0, `weighted=False` |
| `test_card_draft_classification_defaults` | 1 | `genre="other"`, `traditions=[]`, `period=None` |
| `test_brief_includes_classification_and_community` | 1 | `brief()` keys |
| `test_added_columns_migrate_old_db` | 1 | a pre-feature `library.db` gains the five columns; old rows read back |
| `test_fts_rebuilt_on_column_drift` | 1 | old `books_fts` (6 cols) is rebuilt; `search("estoicismo")` hits `traditions` |
| `test_traditions_slug_normalised_on_upsert` | 1 | "Estoicismo" → "estoicismo" |
| `test_relation_pk_and_self_check` | 1 | duplicate `(src,dst,rel)` replaces; `src==dst` raises `IntegrityError` |
| `test_symmetric_rel_canonical_order` | 1 | `parallels(b,a)` stored as `(a,b)` |
| `test_card_prompt_requests_classification` | 1 | `_CARD_PROMPT` mentions genre/traditions/period |
| `test_refresh_card_carries_classification` | 1 | `refresh_card` updates the new fields |
| `test_deterministic_same_author_slugified` | 2 | "Calderón de la Barca" vs "Calderon de la Barca" → `same_author` |
| `test_deterministic_shares_topic_jaccard` | 2 | weight equals Jaccard; below 0.2 → no edge |
| `test_deterministic_same_era_window_and_period` | 2 | year window 50; equal period slug |
| `test_candidate_pairs_prefilter_and_cap` | 2 | union of det neighbours + FTS, minus judged, cap 8 |
| `test_judge_relations_one_prompt_per_book` | 2 | `ask_structured` called once for N candidates |
| `test_llm_confidence_floor_and_judgement_log` | 2 | 0.4 → judged but no relation; 0.6 → relation; `none` → judged only |
| `test_relate_skips_judged_pairs_unless_force` | 2 | second run: 0 LLM calls; `--force` re-asks |
| `test_relate_no_llm_runs_stage1_only` | 2 | no adapter → deterministic edges, summary notes LLM skipped |
| `test_relate_llm_failure_keeps_deterministic` | 2 | adapter raises → book in `failed[]`, Stage-1 edges intact |
| `test_related_books_depth2_and_min_confidence` | 2 | hop cap, confidence filter |
| `test_cross_scope_edge_stored_in_src_scope_and_dangling_filtered` | 2 | global src → global DB; unknown dst dropped at read |
| `test_remove_book_cascades_relations_and_judgements` | 2 | both directions removed |
| `test_add_relate_flag_scopes_to_new_book` | 2 | `add_book(relate=True)` judges only the new book |
| `test_build_book_graph_edge_weights_and_provenance` | 3 | `INFERRED`+confidence for llm rels, `EXTRACTED` otherwise; `domain_tags["weight"]` |
| `test_detect_book_communities_two_clusters` | 3 | two dense author/tradition groups → two communities |
| `test_communities_skipped_under_three_cards` | 3 | summary notes skip; no `communities` rows |
| `test_same_community_edges_rewritten` | 3 | old `same_community` rows removed before write |
| `test_community_label_llm_and_fallbacks` | 3 | llm label; `derive_community_label` fallback; singleton → title |
| `test_communities_table_in_project_db_only` | 3 | partition stored once |
| `test_community_id_stable_for_same_membership` | 3 | re-run without changes → same ids |
| `test_toolkit_related_books_clamps` | 4 | `depth` 1–2, `top_k` 1–50 |
| `test_toolkit_communities_and_get_community` | 4 | shapes; unknown id → explanatory error |
| `test_search_expand_related_respects_max_books` | 4 | widened shortlist still capped |
| `test_mcp_tools_list_has_ten_tools` | 4 | names include the three new tools |
| `test_skill_text_mirrors_in_sync` | 4 | SKILL.md / command / `BOOKSTORE_SKILL` contain step 1b |
| `test_export_wiki_pages_and_edges` | 5 | one page per card (`category="book"`), edges with provenance |
| `test_export_wiki_writes_graph_html` | 5 | `graph.html` + `graph.json` exist (echarts CDN fallback allowed) |
| `test_export_wiki_registers_namespace_project` | 5 | `.parrot/wiki.json` gains `namespaces.bookstore` store entry |
| `test_export_wiki_registers_namespace_global` | 5 | `wikis.json` under a temp `PARROT_HOME` |
| `test_export_wiki_conflicting_namespace_refused` | 5 | different store path → error, nothing written |
| `test_export_wiki_no_register_flag` | 5 | registry untouched |
| `test_export_wiki_without_wiki_package` | 5 | import error → `ClickException`, catalog untouched |

### Integration Tests

| Test | Description |
|---|---|
| `test_relate_all_end_to_end_fake_adapter` | 5 markdown books (2 authors, 2 traditions) → `relate --all` → deterministic + llm + communities persisted; `related`/`communities` CLI JSON output; `catalog_search` hits traditions |
| `test_mcp_related_books_roundtrip` | `bookstore mcp` stdin `initialize` + `tools/call bookstore_related_books` → valid JSON-RPC, zero non-protocol stdout bytes |
| `test_export_wiki_then_wikitoolkit_communities` | exported plane readable by `SQLiteWikiStore.dump_pages/dump_edges`; `_load_graphindex_nodes_edges(store, {"book"})` returns N nodes/M edges |

### Test Data / Fixtures

```python
# tests/knowledge/bookstore/conftest.py — extend make_adapter()._structured
#   schema is CardDraft        -> CardDraft(..., genre="essay", traditions=["Estoicismo"], period="Imperio romano")
#   schema is RelationDraft    -> RelationDraft(judgements=[RelationJudgement(dst_book_id=..., rel="parallels", confidence=0.7, rationale="...")])
#   schema is CommunityLabelDraft -> CommunityLabelDraft(label="Ética de la virtud")
#
# New fixture: `library_five_books(tmp_path)` — ingests 5 SAMPLE_MARKDOWN variants via
# Bookstore.add_book with title/authors/topics overrides forming two author groups and
# two tradition groups, under PARROT_LIBRARY_DIR=tmp_path.
# New fixture: `legacy_library_db(tmp_path)` — a library.db created with the pre-feature
# _BOOKS_DDL/_FTS_DDL literal to exercise migrations.
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All bookstore tests pass: `pytest packages/ai-parrot/tests/knowledge/bookstore/ -v` (existing 60+ plus the new suites).
- [ ] graphindex suite green with Module 0: `pytest packages/ai-parrot/tests/knowledge/graphindex/test_communities.py -v` — payload weights honoured without `signal_config`, existing unweighted tests unchanged.
- [ ] PageIndex and wiki suites still green: `pytest packages/ai-parrot/tests/knowledge/pageindex/ tests/knowledge/wiki/ -q`.
- [ ] **G1**: `CardDraft`/`BookCard` expose `genre` (closed `Literal`), `traditions[]`, `period`; one carding LLM call fills them; `bookstore search "estoicismo" --catalog-only` matches a book whose only mention is in `traditions`.
- [ ] **G2**: `book_relations` rows carry `rel`, `origin`, `weight`, `confidence`, `rationale`; `bookstore related <id> --json` and `bookstore_related_books` return them; deterministic vs LLM edges are distinguishable.
- [ ] **G3**: `bookstore relate --all` on N books issues at most N relation prompts (+ one per community for labels); a second run without `--force` issues zero relation prompts; relations below 0.5 confidence never appear in `book_relations`; `add`/`add-folder` never call the relation LLM without `--relate`.
- [ ] **G4**: communities computed on the merged project+global graph via `detect_communities` with rel weights; `community_id`/`community_label` persisted on cards; `communities` table stored once (project DB when present); LLM labels with `derive_community_label` fallback; skipped with a note under 3 cards.
- [ ] **G5**: `bookstore mcp` `tools/list` returns exactly 10 `bookstore_*` tools, all read-only; `bookstore_search(expand_related=True)` never exceeds `max_books`; the skill text (three mirrors) documents funnel step 1b and the origin-citation rule.
- [ ] **G6**: `bookstore export-wiki` writes `wiki.db` (pages `category="book"`, typed edges with provenance) and `graph.html`/`graph.json`; registers namespace `bookstore` (project → `.parrot/wiki.json`, `--global` → `PARROT_HOME/wikis.json`); `--no-register` skips; conflicting entry refused; `wikitoolkit communities --kinds book` runs over the exported plane.
- [ ] **G7**: with no LLM, `relate --all` produces deterministic edges and communities and exits 0 with an explanatory note; MCP read tools keep working.
- [ ] **G8**: a pre-feature `library.db` opens without error, old cards read back with defaults, FTS rebuilt once; no existing public signature changes (new params are keyword-only with defaults).
- [ ] MCP stdout purity: MCP smoke test (`initialize` + `tools/list` + one `tools/call`) shows zero non-protocol bytes on stdout; `parrot.knowledge.wiki` is **not** in `sys.modules` after `create_bookstore_mcp_server()` (regression test).
- [ ] Cross-scope rule: edges stored in the `src` book's scope DB; dangling endpoints filtered at read time (test).
- [ ] `remove_book` cascades relations (both directions) and judgements (test).
- [ ] Docs: `docs/` page for the book graph (relate/related/communities/export-wiki, degradation matrix row) and `sdd/specs/bookstore-indexed-library.spec.md` §3/§4/§5/§6 updated to reference this spec.
- [ ] No new required dependencies; `ai-parrot[leiden]` remains optional with Louvain fallback.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.
> All references re-verified on 2026-09-06 against `dev` @ `6c4c2cc16`.
> Paths are relative to `packages/ai-parrot/src/` unless stated.

### Verified Imports

```python
from parrot.knowledge.bookstore import BookCard, CardDraft, TocEntry, LibraryLocation, resolve_locations  # bookstore/__init__.py:23-24 (Bookstore/BookstoreToolkit/CatalogStore via lazy __getattr__ :36-52)
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError          # library.py:88, :55
from parrot.knowledge.bookstore.catalog import CatalogStore, merged_cards, merged_search  # catalog.py:85, :329, :355
from parrot.knowledge.bookstore.carding import slugify, unique_slug, derive_toc, fallback_card_fields, generate_card_fields, sample_sections  # carding.py:44,68,83,138,154,189
from parrot.knowledge.bookstore.config import LibraryLocation, resolve_locations  # config.py:31, :78
from parrot.knowledge.bookstore._llm import resolve_adapter, ENV_LLM, ENV_LLM_LIGHT  # _llm.py
from parrot.knowledge.bookstore.toolkit import BookstoreToolkit                 # toolkit.py:26
from parrot.knowledge.bookstore.mcp_server import create_bookstore_mcp_server  # mcp_server.py:61
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter          # ask_structured at llm_adapter.py:99

from parrot.knowledge.graphindex.communities import detect_communities, detect_hierarchical_communities, derive_community_label, Community, CommunitiesResult  # communities.py:505, 662, 166, 50, 85
from parrot.knowledge.graphindex.inter_community import compute_inter_community_graph, InterCommunityRelation, InterCommunityGraph  # inter_community.py:94, 26, 70
from parrot.knowledge.graphindex.assemble import GraphAssembler                  # assemble.py:24
from parrot.knowledge.graphindex.schema import NodeKind, EdgeKind, Provenance, UniversalNode, UniversalEdge  # schema.py:36, 64, ~28, 149, 184
from parrot.knowledge.graphindex.export_html import export_graph                 # export_html.py:552

# CLI-only, lazy (inside the export-wiki command / Bookstore.export_wiki):
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord, BaseWikiStore  # store.py:711, 299, 415
from parrot.knowledge.wiki.project import (WikiNamespaceConfig, GlobalWikiRegistry, WikiProjectConfig,
    find_project_root, load_project_config, save_project_config,
    global_registry_path, load_global_registry, save_global_registry)  # project.py:175, 344, 365, 640, 667, 692, 955, 960, 986
```

### Existing Class Signatures

```python
# bookstore/models.py
class TocEntry(BaseModel)                                               # line 15
class CardDraft(BaseModel):                                             # line 34
    title: str; authors: list[str] = []; year: Optional[int] = None
    language: Optional[str] = None; topics: list[str] = []; summary: str = ""
class BookCard(BaseModel):                                              # line 64
    book_id: str; title: str; authors: list[str]; year: Optional[int]; language: Optional[str]
    topics: list[str]; summary: str; toc_digest: str; toc: list[TocEntry]; tree_name: str
    scope: Literal["project", "global"] = "project"; source_path: str; source_sha256: str
    source_format: Literal["pdf", "md", "txt", "epub", "mobi", "docx"]
    page_count: Optional[int]; chapter_count: int = 0; added_at: str
    card_origin: Literal["llm", "fallback", "manual"] = "llm"
    def brief(self) -> dict                                             # line 93

# bookstore/carding.py
_CARD_PROMPT = """You are a librarian writing the catalog card (ficha) ..."""     # line 21 (format keys: filename, doc_description, toc_digest, samples)
_SAMPLE_CHAR_CAP = 2000
def slugify(text: str) -> str                                                     # line 44 — NFKD, ASCII, [a-z0-9-]+, ≤64, never empty ("book")
def unique_slug(base: str, taken: set[str]) -> str                                # line 68
def derive_toc(tree: dict[str, Any], max_depth: int = 2) -> tuple[list[TocEntry], str]   # line 83
def fallback_card_fields(file_path: Path, toc_entries: list[TocEntry]) -> CardDraft      # line 138
async def generate_card_fields(adapter: Any, *, filename: str, doc_description: str,
                               toc_digest: str, samples: list[str]) -> CardDraft          # line 154 — adapter.ask_structured(prompt, CardDraft); accepts dict return
def sample_sections(content_loader: Any, node_ids: list[str], max_samples: int = 2) -> list[str]  # line 189

# bookstore/catalog.py
_BOOKS_DDL: str                                        # line 40 — CREATE TABLE IF NOT EXISTS books (book_id PK, ..., card_origin)
_FTS_DDL: str                                          # line 62 — books_fts(book_id UNINDEXED, title, authors_text, topics_text, summary, toc_digest, tokenize='unicode61 remove_diacritics 2')
_ADDED_COLUMNS: list[tuple[str, str]] = []             # line 77 — (column_name, "ALTER clause") applied in _ensure_schema
_JSON_COLUMNS = ("authors", "topics", "toc")           # line 82
class CatalogStore:                                    # line 85
    def __init__(self, db_path: Path | str) -> None
    def _connection(self) -> Iterator[sqlite3.Connection]        # contextmanager; row_factory=sqlite3.Row; always closes
    def _ensure_schema(self, conn) -> None                        # WAL; DDL; PRAGMA table_info(books) + _ADDED_COLUMNS; FTS probe → _fts_available
    def supports_fts(self) -> bool                                # line ~142
    @staticmethod _row_to_card(row) -> BookCard                   # line ~160
    def upsert(self, card: BookCard) -> None                      # line 174 — INSERT OR REPLACE books; DELETE+INSERT books_fts
    def remove(self, book_id: str) -> bool                        # line ~212
    def get(self, book_id: str) -> Optional[BookCard]
    def find_by_sha(self, sha256: str) -> Optional[BookCard]
    def list_cards(self) -> list[BookCard]
    def taken_slugs(self) -> set[str]
    def search(self, query: str, top_k: int = 8) -> list[tuple[BookCard, float]]   # FTS MATCH or LIKE fallback
def merged_cards(stores: list[tuple[str, CatalogStore]]) -> list[BookCard]         # line 329 — earlier scope wins
def merged_search(stores, query, top_k) -> list[BookCard]                          # line 355

# bookstore/config.py
class LibraryLocation:  scope: Scope; root: Path; db_path -> Path                # line 31 (dataclass)
def resolve_locations(cwd: Path | None = ..., require_exists: bool = ...) -> list[LibraryLocation]   # line 78 — PARROT_LIBRARY_DIR → <git root>/.parrot/library → ~/.parrot/library

# bookstore/library.py
class BookstoreError(RuntimeError)                                              # line 55
class _NullAdapter                                                              # line 59 — ask() -> "", ask_structured() raises RuntimeError
class Bookstore:                                                                # line 88
    def __init__(self, locations: list[LibraryLocation], adapter: Optional[Any] = None, lightweight_model: Optional[str] = None)  # line 102
    locations: list[LibraryLocation]; adapter; lightweight_model; logger
    @property has_llm -> bool                                                   # line 125
    def _location(self, scope) -> LibraryLocation                               # line 132
    def _catalog(self, scope: str) -> CatalogStore                              # line 138
    def _toolkit(self, scope: str) -> PageIndexToolkit                          # line 143
    def _content_store(self, scope: str) -> NodeContentStore                    # line 154
    def _stores(self) -> list[tuple[str, CatalogStore]]                         # line 161
    def _all_taken_slugs(self) -> set[str]                                      # line 164
    def list_books(self) -> list[BookCard]                                      # line 184
    def catalog_search(self, query: str, top_k: int = 8) -> list[BookCard]      # line 188
    def resolve_book(self, book_id: str) -> tuple[BookCard, LibraryLocation]    # line 192
    def get_card(self, book_id) -> BookCard; def get_toc(self, book_id) -> dict  # 206, 211
    async def search_book(self, book_id, query, top_k=...) -> list[dict]        # line 221
    def read_section(self, book_id, node_id) -> dict                            # line 239
    async def search(self, query: str, book_ids: Optional[list[str]] = None, max_books: int = 3, top_k: int = 5) -> dict   # line ~262
    async def add_book(self, file_path, scope="project", title=None, authors=None, topics=None, force=False) -> tuple[BookCard, str]  # line 343
    async def _draft_card(self, path, tree_name, scope, doc_description, toc_digest, toc_entries) -> CardDraft   # try generate_card_fields → except fallback
    async def add_folder(...)                                                   # line 617
    async def remove_book(self, book_id: str) -> bool                           # line 663 — delete_tree + catalog.remove (NO relation cascade today)
    async def refresh_card(self, book_id: str) -> BookCard                      # line 675 — model_copy(update={title, authors, year, language, topics, summary, toc_digest, toc, card_origin})

# bookstore/toolkit.py
class BookstoreToolkit(AbstractToolkit):                                        # line 26
    name = "bookstore"; tool_prefix = "bookstore"                               # lines 33-34
    def __init__(self, bookstore: Bookstore, **kwargs: Any) -> None            # line 36
    async def catalog_search(self, query: str, top_k: int = 8) -> list[dict]   # clamps 1-50
    async def list_books(self) -> list[dict]
    async def get_card(self, book_id: str) -> dict                             # pops toc, source_sha256
    async def get_toc(self, book_id: str) -> dict
    async def search_book(self, book_id: str, query: str, top_k: int = 8) -> list[dict]
    async def read_section(self, book_id: str, node_id: str) -> dict
    async def search(self, query: str, book_ids: Optional[list[str]] = None, max_books: int = 3) -> dict   # clamps 1-10

# bookstore/cli.py
_INVOCATION_CWD                                                                  # captured before heavy imports
def _open_bookstore(llm_spec=None, require_exists=False, scope_needed=None, use_llm=True) -> Bookstore   # line 31
def _echo_card(card) -> None                                                     # line 69
@click.group bookstore                                                           # line 92
commands: add (96/111), add-folder (151/167), list (241), show (257), toc (279), search (299/310), card (334/342), remove (356/359), mcp (376), locations (389)

# bookstore/_llm.py
ENV_LLM = "PARROT_BOOKSTORE_LLM"; ENV_LLM_LIGHT = "PARROT_BOOKSTORE_LLM_LIGHT"
def resolve_adapter(llm_spec=None, lightweight_model=None) -> tuple[Optional[Any], Optional[str], Optional[Any]]   # (adapter, light, client); all None → degraded

# bookstore/mcp_server.py
_INVOCATION_CWD; def _ensure_stderr_logging() -> None
def create_bookstore_mcp_server(locations: list[LibraryLocation], adapter=None, lightweight_model=None) -> StdioMCPServer   # line 61

# pageindex/llm_adapter.py
class PageIndexLLMAdapter:
    async def ask_structured(self, prompt: str, output_type: type, temperature: float = 0.0, system_prompt: Optional[str] = None) -> Any   # line 99 — client.invoke(..., output_type=)

# graphindex/communities.py
class Community(BaseModel):           # line 50 — community_id (16-char sha1 of sorted members), size, member_node_ids, centroid_node_id, cohesion, modularity_contribution, top_titles, label=""; frozen
class CommunitiesResult(BaseModel):   # line 85 — modularity, resolution, seed, weighted, communities, node_to_community, algorithm="louvain"; frozen
class HierarchicalCommunitiesResult   # line 105
def derive_community_label(titles: Iterable[str], max_terms: int = 3) -> str            # line 166
def _to_undirected_networkx(graph, nodes, signal_config=None, embedder=None) -> nx.Graph  # line 210 — iterates graph.edge_index_map().values() as (src_idx, tgt_idx, _payload); w = weight_fn(a,b) if weight_fn else 1.0  (payload IGNORED today)
def _build_weight_fn(graph, nodes, signal_config, embedder)                              # line 267 — None when no signal_config
def _to_igraph(graph, nodes, signal_config=None, embedder=None)                          # line 306 — same loop; ig_graph.es["weight"] = list(edge_weight.values())
def _run_leiden(graph, nodes, *, resolution, seed, signal_config, embedder) -> list[set[str]] | None   # line 381 — None when leidenalg/igraph missing
def detect_communities(graph: rustworkx.PyDiGraph, nodes: list[UniversalNode], resolution: float = 1.0, seed: int = 42,
                       signal_config=None, embedder=None, write_back_to_nodes: bool = True, algorithm: str = "leiden") -> CommunitiesResult   # line 505
def detect_hierarchical_communities(graph, nodes, resolutions=None, seed=42, signal_config=None, embedder=None) -> HierarchicalCommunitiesResult  # line 662

# graphindex/inter_community.py
class InterCommunityRelation(BaseModel)   # line 26 — source/target_community_id, source/target_label, directed_edge_count, reverse_edge_count, total_weight, reverse_weight, coupling_ratio; frozen
class InterCommunityGraph(BaseModel)      # line 70 — relations, community_count, connected_pairs, total_possible_pairs, density; frozen
def compute_inter_community_graph(graph: rustworkx.PyDiGraph, communities_result: CommunitiesResult) -> InterCommunityGraph   # line 94 — READS edge payload "weight" (defaults 1.0)

# graphindex/assemble.py
class GraphAssembler:                                   # line 24
    def __init__(self, tenant_id: str) -> None          # line 35
    graph: rustworkx.PyDiGraph
    def add_node(self, node: UniversalNode) -> int      # line 45
    def add_edge(self, edge: UniversalEdge) -> Optional[int]   # line 77 — payload dict built from the edge (includes domain_tags); None when an endpoint is missing
    def add_nodes(self, nodes) -> list[int]; def add_edges(self, edges) -> list[Optional[int]]   # 113, 124
    def get_neighbors(...); def get_edges_for_node(...); node_count(); edge_count()             # 153, 188, 221, 226

# graphindex/schema.py
class Provenance(str, Enum): EXTRACTED="extracted", INFERRED="inferred", AMBIGUOUS="ambiguous", ASSERTED="asserted"   # ~line 28
class NodeKind(str, Enum): DOCUMENT, SECTION, SYMBOL, CONCEPT, RATIONALE, SKILL, WIKI_PAGE, RUN, CLAIM                 # line 36
class EdgeKind(str, Enum): CONTAINS, REFERENCES, DEFINES, MENTIONS, EXPLAINS, EXTENDS, PRODUCED, ABOUT, SUPPORTED_BY, CONTRADICTS, CALLS, IMPLEMENTS   # line 64
class UniversalNode(BaseModel): node_id, kind, title, source_uri, content_ref=None, summary=None, embedding_ref=None, domain_tags: dict = {}, parent_id=None, provenance, assertion=None   # line 149
class UniversalEdge(BaseModel): source_id, target_id, kind, provenance, confidence: float | None, assertion=None, domain_tags: dict = {}   # line 184 — validator: confidence set IFF provenance == INFERRED

# graphindex/export_html.py
def export_graph(graph: rustworkx.PyDiGraph, output_dir: Path, *, communities=None, analytics=None, inter_community=None,
                 god_top_k: int = 15, title: str = "GraphIndex Knowledge Map", echarts_js: str | None = None,
                 allow_cdn_fallback: bool = True) -> tuple[Path, Path]     # line 552 — (graph.html, graph.json)

# wiki/store.py
class WikiPageRecord(BaseModel):        # line 299 — concept_id (min_length=1), node_id=None, title="", category: str = "concept" (open string), summary="", body="", source_id, token_count, origin ("ingest"|"authored"|"memory"), asserted_by, updated_at (None → now), content_hash
class BaseWikiStore(ABC):               # line 415 — upsert_pages(pages: list[WikiPageRecord]) -> int (434); add_edges(edges: list[tuple]) -> int (437); dump_pages() (480); dump_edges() (483)
class SQLiteWikiStore(BaseWikiStore):   # line 711
    def __init__(self, db_path: str | Path, wiki_name: str = "", *, read_only: bool = False)   # line 759 — mkdir parents unless read_only
    async def upsert_pages(self, pages) -> int                    # line 1134
    async def add_edges(self, edges: list[tuple]) -> int          # line 1154 — (src, dst, rel) or (src, dst, rel, provenance); INSERT OR REPLACE; provenance default 'extracted'
    async def dump_edges(self) -> list[dict]                      # line 1729 — keys src, dst, rel

# wiki/project.py
GLOBAL_REGISTRY_FILENAME = "wikis.json"                           # line 43
class WikiNamespaceConfig(BaseModel):                             # line 175 — extra="forbid"; path|store|database|vault (exactly one), backend="sqlite", credentials_env, description="", weight=1.0
class GlobalWikiRegistry(BaseModel):                              # line 344 — version=1, namespaces: dict[str, WikiNamespaceConfig]
class WikiProjectConfig(BaseModel):                               # line 365 — has .namespaces: dict[str, WikiNamespaceConfig]
def find_project_root(start: Path | None = None) -> Path | None   # line 640 — nearest .parrot/wiki.json, else nearest .git root
def load_project_config(root: Path) -> WikiProjectConfig          # line 667 — default WikiProjectConfig(wiki_name=root.name) when no file; WikiConfigError when invalid
def save_project_config(root: Path, config: WikiProjectConfig) -> Path   # line 692 — writes .parrot/wiki.json
def global_registry_path() -> Path                                # line 955 — PARROT_HOME/wikis.json
def load_global_registry(path: Path | None = None) -> GlobalWikiRegistry   # line 960
def save_global_registry(registry: GlobalWikiRegistry, path: Path | None = None) -> Path   # line 986

# wiki/cli.py (reference only — NOT imported by bookstore)
_CATEGORY_TO_NODE_KIND (line 865, no "book" → WIKI_PAGE); _REL_TO_EDGE_KIND (line 875, unknown rel → REFERENCES)
async def _load_graphindex_nodes_edges(store, graph_kinds: frozenset[str])   # line 900 — adapter template
def ns_add(...)   # line 2218 — load_project_config → WikiNamespaceConfig(...) → config.namespaces[name] = entry → save_project_config; global: load_global_registry → registry.namespaces[name] = entry → save_global_registry; refuses if name exists in the other registry
def communities(...)   # line 2364 — `wikitoolkit communities --kinds <csv> [--inter]`

# tests/knowledge/bookstore/conftest.py
SAMPLE_MARKDOWN: str
def make_adapter() -> MagicMock   # adapter.model="heavy"; adapter.ask_structured = AsyncMock(side_effect=_structured) dispatching on schema class (CardDraft → CardDraft(...), else IngestedMarkdown)
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `CardDraft.genre/traditions/period` | `generate_card_fields` → `adapter.ask_structured(prompt, CardDraft)` | same structured call, extended prompt | `carding.py:154-187` |
| `CatalogStore` new columns | `_ensure_schema` `_ADDED_COLUMNS` loop | append tuples | `catalog.py:77`, `:128-131` |
| `CatalogStore.upsert` FTS row | `books_fts` DELETE+INSERT | add `genre`, `traditions_text` columns after rebuild | `catalog.py:174-212` |
| `relations.deterministic_relations` | `Bookstore.list_books()` (merged) | card list | `library.py:184` |
| `relations.candidate_pairs` FTS hits | `Bookstore.catalog_search(query, top_k)` | `merged_search` | `library.py:188`, `catalog.py:355` |
| `relations.judge_relations` | `adapter.ask_structured(prompt, RelationDraft)` | same adapter as carding | `llm_adapter.py:99`, `library.py:125 has_llm` |
| `relations.build_book_graph` | `GraphAssembler.add_nodes/add_edges` | `UniversalNode(kind=NodeKind.DOCUMENT)`, `UniversalEdge(kind=EdgeKind.REFERENCES, provenance=…, confidence=…, domain_tags={"weight": …})` | `assemble.py:113,124`, `schema.py:149,184` |
| `relations.detect_book_communities` | `detect_communities(graph, nodes, resolution, seed, algorithm="leiden")` + `compute_inter_community_graph(graph, result)` | direct calls | `communities.py:505`, `inter_community.py:94` |
| Module 0 payload weight | `_to_undirected_networkx` / `_to_igraph` edge loop | `_payload.get("weight", 1.0)` when `weight_fn is None` | `communities.py:210-260`, `:306-380` |
| `relations.fallback_label` | `derive_community_label(titles)` | direct call | `communities.py:166` |
| `Bookstore.remove_book` cascade | `CatalogStore.delete_relations`, `delete_judgements` (new) before `catalog.remove` | method calls | `library.py:663-673` |
| `Bookstore.add_book(relate=True)` | `relate_books([slug])` after `catalog.upsert(card)` | method call | `library.py:~415 (catalog.upsert)` |
| `BookstoreToolkit.related_books/communities/get_community` | `Bookstore.related_books/communities/get_community` | thin async wrappers, clamps | `toolkit.py:26-149` pattern |
| `bookstore relate/related/communities/export-wiki` | `_open_bookstore(llm_spec, require_exists=True, use_llm=...)` | Click commands | `cli.py:31` |
| `wiki_export` pages | `SQLiteWikiStore(db_path, wiki_name="bookstore").upsert_pages([WikiPageRecord(...)])` | lazy import | `store.py:759`, `:1134`, `:299` |
| `wiki_export` edges | `SQLiteWikiStore.add_edges([(src, dst, rel, provenance)])` | 4-tuples | `store.py:1154` |
| `wiki_export` graph.html | `export_graph(assembler.graph, out_dir, communities=, inter_community=, title=)` | reuse Module 3 objects | `export_html.py:552` |
| namespace registration (project) | `load_project_config(git_root)` → `config.namespaces["bookstore"] = WikiNamespaceConfig(store=…, backend="sqlite", description=…)` → `save_project_config` | mirrors `ns_add` | `project.py:667, 175, 692`; `cli.py:2218-2310` |
| namespace registration (global) | `load_global_registry()` → `registry.namespaces["bookstore"] = …` → `save_global_registry(registry)` | mirrors `ns_add --global` | `project.py:960, 344, 986` |
| Skill text mirrors | `.agent/skills/bookstore/SKILL.md`, `.claude/commands/bookstore.md`, `wiki/google/bookstore_assets.py::BOOKSTORE_SKILL` | text edits | repo paths (verified present) |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.knowledge.bookstore.relations`~~, ~~`.wiki_export`~~ — new modules of this spec; no `book_relations` / `relation_judgements` / `communities` tables today.
- ~~`BookCard.genre` / `.traditions` / `.period` / `.community_id` / `.community_label`~~ — not fields; `CardDraft` has only title/authors/year/language/topics/summary.
- ~~`BookRelation`, `RelationDraft`, `RelationJudgement`, `BookCommunity`, `CommunityLabelDraft`, `RelateSummary`~~ — to be created in `models.py` / `relations.py`.
- ~~`Bookstore.relate_books/related_books/communities/get_community/export_wiki`~~; ~~`add_book(relate=)`~~; ~~`search(expand_related=)`~~ — none exist.
- ~~`CatalogStore.upsert_relations/list_relations/delete_relations/record_judgements/judged_pairs/upsert_communities/list_communities/get_community`~~, ~~`merged_relations`/`merged_communities`~~ — to be created.
- ~~`bookstore relate|related|communities|export-wiki` commands~~; ~~`add --relate`~~; ~~`list --by-community`~~ — CLI has add, add-folder, list, show, toc, search, card, remove, mcp, locations only.
- ~~Community detection inside Bookstore or PageIndex~~ — only `graphindex.communities`, invoked by `wiki/cli.py`. PageIndex trees have no cross-document edges.
- ~~Per-edge payload weight support in `detect_communities`~~ — `_to_undirected_networkx` (`communities.py:210`) and `_to_igraph` (`:306`) set 1.0 unless `signal_config`; **Module 0 adds it**. `compute_inter_community_graph` already reads `payload["weight"]`.
- ~~`WikiPageCategory.BOOK`~~ — enum has summary/entity/concept/comparison/overview/synthesis/answer/archive; `WikiPageRecord.category` is an open string so `"book"` is storable, but `_CATEGORY_TO_NODE_KIND` maps it to `WIKI_PAGE` and default query ranking does not know it.
- ~~`_REL_TO_EDGE_KIND["parallels"|"same_author"|…]`~~ — unknown rels map to `REFERENCES` in `wikitoolkit`'s graph export; the rel string survives only in the wiki `edges` table.
- ~~`Bookstore.remove_book` cascading to relations~~ — today it deletes the tree + catalog row only.
- ~~An embedder in Bookstore~~ — no `parrot.embeddings` usage under `bookstore/`; Option C is out of scope.
- ~~`WikiNamespaceConfig(kind="store")`~~ — `kind` is derived from which of `path|store|database|vault` is set, not a constructor field; `extra="forbid"`.
- ~~A public helper `register_namespace()` in `wiki/project.py`~~ — registration logic lives inline in `cli.py:ns_add`; Module 5 mirrors it with the load/save functions (or extracts a shared helper — implementer's choice, must not import `wiki/cli.py`).
- ~~`ALTER TABLE books_fts ADD COLUMN`~~ — FTS5 virtual tables cannot be altered; rebuild required.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Carding pattern** (`carding.py:154-187`): prompt constant + `ask_structured` + Pydantic validation of a dict return + deterministic fallback; wrap every LLM stage in `try/except` that logs and degrades (`library.py:_draft_card`).
- **Catalog pattern** (`catalog.py`): short-lived `sqlite3` connections, WAL, `INSERT OR REPLACE`, JSON text columns listed in a `_JSON_COLUMNS`-style tuple, additive migrations only; keep the `_ensure_schema` idempotent.
- **Scope merge pattern** (`catalog.py:329 merged_cards`): project first, earlier scope wins; apply the same to relations and communities readers.
- **graphindex adapter pattern** (`wiki/cli.py:900-952`): build `UniversalNode`/`UniversalEdge` lists, feed `GraphAssembler`, call `detect_communities` and `compute_inter_community_graph` inside `try/except` that only logs.
- **Stdout purity** (`mcp_server.py`, `_llm.py`): no `parrot.knowledge.wiki` import at module level anywhere under `bookstore/`; `wiki_export.py` imports inside functions; add a regression test asserting `"parrot.knowledge.wiki" not in sys.modules` after server construction.
- **Read-only toolkit** (`toolkit.py`): new tools are thin wrappers with clamps and docstrings that *are* the LLM-facing description; keep outputs compact (briefs, not full cards).
- **Namespace registration** mirrors `cli.py:ns_add` semantics exactly (refuse cross-registry duplicates, `extra="forbid"` model, relative store paths resolved against the registry's directory — store the path **relative to the git root** for project entries and absolute for global ones).
- Google-style docstrings, strict type hints, Pydantic models, `self.logger`, async for anything touching the adapter or the PageIndex toolkit.

### Known Risks / Gotchas

- **Community ids are membership hashes** (`Community.community_id`, `communities.py:50`): any membership change changes the id, so labels cannot be cached by id across runs. Mitigation: re-label on every Stage 3 run; with an LLM this is one prompt per community (small); cache by id within a run only. Store `label_origin` so a fallback label can be upgraded later.
- **Louvain fallback is silent** except for a log line: record `algorithm` from `CommunitiesResult.algorithm` in the `communities` table and print it in `bookstore communities`.
- **Small dense graphs collapse into one community** at `resolution=1.0`: expose `--resolution` (default 1.0) and document; leave the empirical default as an open question (§8).
- **Dangling cross-scope edges**: a global DB can hold edges to project books from other repos; readers must filter by visible ids, and `relate --all` prunes edges whose `dst` is invisible **only in the scope being processed** (never delete global edges just because *this* project cannot see the dst).
- **`relation_judgements` PK is `(src, dst)` directional**: Stage 2 judges from the perspective of `src`; the reverse pair may be judged when the other book is the target. Accept the asymmetry (it is how `influenced_by` gets its direction); symmetric rels are canonicalised on write so duplicates collapse.
- **FTS rebuild** must run inside one transaction and must not run on every open: compare `PRAGMA table_info(books_fts)` column names to the expected tuple.
- **`UniversalEdge` validator**: `confidence` must be set iff `provenance == INFERRED` (`schema.py:187`). Deterministic/community edges → `EXTRACTED` with `confidence=None`; LLM edges → `INFERRED` with their confidence.
- **Module 0 must not change wikitoolkit behaviour**: wiki edges carry no `weight` payload today (`_load_graphindex_nodes_edges` builds plain `UniversalEdge`s), so `payload.get("weight", 1.0)` is a no-op there; the existing unweighted tests are the guard.
- **Non-Latin author names** collapse to `"book"` in `slugify` (docstring, `carding.py:44-58`): `same_author` must skip slugs equal to the fallback `"book"` or shorter than 3 chars to avoid false positives.
- **`add --relate` inside `add-folder`**: relate each book right after its ingest (per-file scope), then run Stage 3 once at the end of the folder — never per file.
- **Namespace registration when no git root** (`PARROT_LIBRARY_DIR` outside a repo, or global scope): fall back to the global registry and say so.
- **Skill text lives in three places** (`.agent/skills/bookstore/SKILL.md`, `.claude/commands/bookstore.md`, `wiki/google/bookstore_assets.py`): a test compares the funnel section across them; note that `wiki/google/*` is currently being edited by another in-flight session — rebase before touching it.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `rustworkx` | `>=0.15` (core, `pyproject.toml:169`) | `GraphAssembler` backing graph |
| `networkx` | `>=3.0` (core, `pyproject.toml:170`) | Louvain path in `detect_communities` |
| `leidenalg` + `python-igraph` | `>=0.10` (optional extra `ai-parrot[leiden]`, `pyproject.toml:294-296`) | Leiden partition; silent Louvain fallback |
| `aiosqlite` | core | `SQLiteWikiStore` (export-wiki only, lazy) |
| `sqlite3` FTS5 | stdlib build | catalog FTS (LIKE fallback exists) |

No new required dependency.

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

- [x] Feature or hotfix; base branch? — *Resolved in brainstorm*: feature on `dev`.
- [x] Where do relations live? — *Resolved in brainstorm*: both — `book_relations` in `library.db` as source of truth, plus an explicit `bookstore export-wiki` into a dedicated wikitoolkit plane.
- [x] Which relation sources in v1? — *Resolved in brainstorm*: all four — deterministic (author/topics/language/era), LLM classification on the ficha, LLM pairwise conceptual relations, communities as a relation.
- [x] Agent surface? — *Resolved in brainstorm*: explicit navigation tools (`bookstore_related_books`, `bookstore_communities`), not implicit expansion (an opt-in `expand_related` flag on `search` is kept as a thin extra).
- [x] When does the pairwise LLM run and with what prefilter? — *Resolved in brainstorm*: separate `bookstore relate [book_id|--all]` batch (+ optional `--relate` on add); candidates = deterministic neighbours ∪ FTS top-k, cap ≈ 8; one prompt per book.
- [x] Taxonomy closed or open? — *Resolved in brainstorm*: closed `Literal` for `genre` and `rel`; free text slug-normalised for `tradition`/`period`.
- [x] Community scope and labelling? — *Resolved in brainstorm*: one graph over merged project+global cards; LLM-generated labels with `derive_community_label` fallback; persisted per book.
- [x] Shape of the wikitoolkit projection? — *Resolved in brainstorm*: `bookstore export-wiki` command → dedicated plane (`SQLiteWikiStore`, category `book`, typed edges) + `graph.html`; Bookstore never imports wikitoolkit on the MCP path.
- [x] Storage rule for cross-scope edges? — *Resolved at spec time (2026-09-06)*: store in the `src` book's scope DB and filter dangling endpoints at read time.
- [x] Per-rel edge weights in clustering? — *Resolved at spec time (2026-09-06)*: extend `graphindex._to_undirected_networkx` / `_to_igraph` to honour `payload["weight"]` when no `signal_config` (Module 0); benefits wikitoolkit too.
- [x] Confidence floor and memory of LLM judgements? — *Resolved at spec time (2026-09-06)*: floor 0.5 + `relation_judgements` log; `relate` skips judged pairs unless `--force`.
- [x] Register the exported plane as a wikitoolkit namespace? — *Resolved at spec time (2026-09-06)*: yes — `export-wiki` registers namespace `bookstore` (project `.parrot/wiki.json` or global `wikis.json`), `--no-register` opts out.
- [ ] Default Leiden `resolution` for tens-of-books graphs: keep 1.0 and expose `--resolution`, then tune on the user's real library after the first `relate --all`. — *Owner: Jesus Lara* (implementation-time)
- [ ] Deterministic thresholds (`shares_topic` Jaccard ≥ 0.2, `same_era` window 50 years) and `REL_WEIGHTS` values: proposed defaults, adjust after the first real run. — *Owner: Jesus Lara* (implementation-time)
- [ ] Future: similarity-weighted edges via `detect_communities(signal_config=…, embedder=…)` (brainstorm Option C signal) — out of v1. — *Owner: Jesus Lara*
- [ ] Should `wikitoolkit`'s `_CATEGORY_TO_NODE_KIND` learn `"book" → DOCUMENT` so the exported plane's `graph.html` from `wikitoolkit build` classifies nodes correctly? One-line change in `wiki/cli.py`; not required for `bookstore export-wiki`'s own `graph.html`. — *Owner: Jesus Lara*

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — one worktree
  `.claude/worktrees/feat-533-wikitoolkit-bookstore-conceptual-relations`
  branched from `dev`; tasks run sequentially in dependency order
  M0 → M1 → M2 → M3 → M4 → M5.
- **Parallelisable**: M0 touches only `graphindex/communities.py` + its
  test and has no bookstore dependency — it may be done first in the same
  worktree or as an independent small PR; M4 and M5 are independent of
  each other after M3 (both only read the engine) but both edit
  `library.py`/`cli.py`, so keep them sequential in the single worktree.
- **Cross-feature dependencies**: none blocking. FEAT-531
  (`wikitoolkit-cli-llm-fallback`, in progress) edits
  `bookstore/_llm.py::resolve_adapter` and CLI LLM defaults; this spec
  does not modify `_llm.py`. The in-flight uncommitted work on
  `wiki/google/bookstore.py` / `bookstore_assets.py` / `installer.py`
  (Antigravity installer) overlaps only with M4's skill-text mirror in
  `bookstore_assets.py` — rebase onto `dev` before M4.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-06 | Jesus Lara / Claude | Initial draft from brainstorm (Option A) + four spec-time resolutions |
