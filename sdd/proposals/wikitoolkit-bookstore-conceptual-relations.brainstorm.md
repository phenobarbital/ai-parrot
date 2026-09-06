---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Bookstore Conceptual Relations — a book graph with communities over the ficha catalog

**Date**: 2026-09-06
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

The Bookstore (`parrot.knowledge.bookstore`, spec
`sdd/specs/bookstore-indexed-library.spec.md`) is a flat catalog: one
`BookCard` ("ficha") per book in a SQLite + FTS5 `library.db`, plus one
PageIndex tree per book. The only cross-book capability is lexical
(`catalog_search` → shortlist → per-book tree walk). **There are no
relations between books.** A research agent that finds a note in a
Calderón de la Barca play has no way to discover the same author's
other works, sibling works of the Spanish Golden Age, or conceptually
adjacent works (Confucius' *Analects* ↔ Marcus Aurelius' *Meditations*
as two virtue-ethics traditions) unless the query text happens to
lexically overlap.

Three kinds of relation are wanted, with very different determinism:

| Relation family | Deterministic? | Source of truth |
|---|---|---|
| Authorship / topic / language / era | yes | fields already on `BookCard` |
| Classification (genre, tradition/school, period) | mostly — once classified | **new LLM-filled card fields** (the carding LLM already runs at ingest) |
| Conceptual (influenced_by, responds_to, parallels, contrasts_with) | no | **new pairwise LLM judgement** with rationale + confidence |
| Community membership | derived | graph clustering over the edges above |

Communities (Leiden → Louvain fallback) exist today **only in
wikitoolkit**: `parrot.knowledge.graphindex.communities.detect_communities`
runs over the wiki store's pages + typed edges (`wiki/cli.py`
`_load_graphindex_nodes_edges` → `GraphAssembler` → `detect_communities`
→ `compute_inter_community_graph`). Bookstore computes nothing of the
kind because it has no graph to cluster. This feature gives Bookstore a
book graph so the same machinery applies, and adds an agent-facing
navigation surface ("related books", "communities") plus an export to a
wikitoolkit plane for visualisation and `wikitoolkit query`.

**Users**: the research agent (Claude Code via the `bookstore` MCP /
skill), and the human curating the library via the `bookstore` CLI.

## Constraints & Requirements

- **Bookstore stays self-contained in the MCP path.** The stdio MCP
  server must keep its stdout-purity discipline and must not import
  `parrot.knowledge.wiki` at startup. wikitoolkit is an *export
  target*, never a runtime dependency of the read tools.
- **No-LLM mode must keep working.** Deterministic relations
  (author/topic/language/era) and communities run without a model;
  classification and conceptual relations degrade to "absent", exactly
  like `fallback_card_fields` today.
- **Pairwise LLM cost is bounded.** Conceptual relations run in a
  separate batch (`bookstore relate`), never implicitly inside
  `add`/`add-folder`; candidates are pre-filtered (deterministic
  neighbours ∪ FTS top-k over summaries, cap ≈ 8 per book) and judged
  in **one structured prompt per book**, not one per pair.
- **Closed vocabularies where the agent branches on them**: `genre` and
  `rel` are `Literal` enums; `tradition`/`period` are free text
  normalised by `slugify` so "Estoicismo" and "estoicismo" collide.
- **Additive schema only.** New card fields land through
  `catalog._ADDED_COLUMNS`; a new `book_relations` table is `CREATE IF
  NOT EXISTS`. Existing libraries keep working un-migrated; `bookstore
  relate --all` / `bookstore card --refresh` backfill.
- **Communities are computed over the merged project+global view**
  (project wins id collisions, as `merged_cards` already does) and
  persisted per book (`community_id`, `community_label`) so the MCP
  tools answer without recomputing.
- **Read tools remain read-only.** All computation (relate, communities,
  export) is CLI-only, same rule as ingestion today (spec §4).
- Reuse `graphindex` (core dep: `rustworkx`, `networkx`; optional
  `ai-parrot[leiden]`), never a second clustering stack.

---

## Options Explored

### Option A: Book graph inside `library.db` + graphindex communities + wiki export (source of truth stays in Bookstore)

Extend the catalog with classification fields and a `book_relations`
edge table; a new `relations.py` module computes deterministic edges,
LLM conceptual edges (batched per book with a candidate prefilter) and
communities (by adapting cards/edges into `UniversalNode`/`UniversalEdge`
and calling `graphindex.detect_communities`). Communities are written
back onto the cards. New read tools expose neighbours and communities.
A separate `bookstore export-wiki` projects cards → wiki pages
(category `book`) and edges → typed wiki edges into a dedicated
`SQLiteWikiStore` plane, and writes `graph.html` via
`graphindex.export_html.export_graph`.

✅ **Pros:**
- Bookstore remains one SQLite file per scope; the MCP server keeps
  zero new imports and answers "related books" with a single SQL join.
- Every relation carries `origin` (`deterministic|llm|community`),
  `confidence` and `rationale`, so the agent can tell a hard fact
  (same author) from an LLM opinion (parallels) — the determinism split
  the user called out is first-class in the schema.
- Reuses `detect_communities`, `derive_community_label`,
  `compute_inter_community_graph`, `GraphAssembler`, `export_graph`
  verbatim; the adapter is ~40 lines mirroring
  `wiki/cli.py:_load_graphindex_nodes_edges`.
- Backfill is a single CLI batch; incremental `--relate` on `add` is a
  thin wrapper over the same function scoped to one book.

❌ **Cons:**
- Two graph representations (SQLite edges in Bookstore, pages/edges in
  the exported wiki plane) that can drift; the export is one-way and
  must be re-run after `relate`.
- `detect_communities` currently ignores per-edge weights unless a
  FEAT-190 `signal_config` is supplied (verified,
  `communities.py:_to_undirected_networkx` never reads the edge
  payload) — rel-weighted clustering needs a small graphindex extension
  or the bookstore builds its own weighted `networkx` graph for the
  Louvain path.
- Cross-scope edges (a global book ↔ a project book) live in one DB but
  reference an id that only exists in the other; the merged reader must
  drop dangling endpoints.

📊 **Effort:** High (Medium per module; 5 modules touched + CLI + skill)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `rustworkx>=0.15` | `GraphAssembler` backing graph | already a core dep (`packages/ai-parrot/pyproject.toml:169`) |
| `networkx>=3.0` | Louvain fallback inside `detect_communities` | core dep (`pyproject.toml:170`) |
| `leidenalg>=0.10`, `python-igraph>=0.10` | Leiden partition | optional extra `ai-parrot[leiden]` (`pyproject.toml:294-296`); silent Louvain fallback |
| `sqlite3` (stdlib) | `book_relations` table + additive columns | same `CatalogStore` connection pattern |
| Pydantic v2 | `RelationDraft`, `ClassificationDraft`, `BookRelation` | structured output through `PageIndexLLMAdapter.ask_structured` |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py:154` — `generate_card_fields` pattern (prompt + `ask_structured` + fallback) to copy for classification and relation drafting.
- `packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py:77` — `_ADDED_COLUMNS` additive-migration hook; `catalog.py:174` `upsert` for the FTS row shape.
- `packages/ai-parrot/src/parrot/knowledge/graphindex/communities.py:505` — `detect_communities`; `:166` `derive_community_label` (fallback label).
- `packages/ai-parrot/src/parrot/knowledge/graphindex/inter_community.py:94` — `compute_inter_community_graph` for community→community relations.
- `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:900-952` — `_load_graphindex_nodes_edges` as the template for the card→`UniversalNode` adapter.
- `packages/ai-parrot/src/parrot/knowledge/graphindex/export_html.py:552` — `export_graph(graph, output_dir, communities=, inter_community=, title=)`.
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:759` — `SQLiteWikiStore(db_path, wiki_name=)`; `:1154` `add_edges([(src, dst, rel, provenance)])`; `:1134` `upsert_pages([WikiPageRecord])`.

---

### Option B: Project books into a wikitoolkit plane and let wikitoolkit own the graph

Every ingested book becomes a wiki page (`category="book"`) in a
dedicated plane; deterministic and LLM edges are written as wiki typed
edges; communities come from the existing `wikitoolkit communities
--kinds book` path; the Bookstore read tools call the wiki store (or
`WikiToolkit.related`) to answer "related books".

✅ **Pros:**
- One graph representation, no drift; `wikitoolkit query / related /
  remember / link` work on books for free, including human-asserted
  edges (`wikitoolkit link a b --rel influenced_by`).
- Zero new persistence code in Bookstore.

❌ **Cons:**
- Couples the Bookstore MCP server to `parrot.knowledge.wiki` at
  runtime — a large import chain (navconfig, aiosqlite, embeddings)
  the bookstore deliberately avoided for stdout purity and startup
  time (`mcp_server.py` header, `_llm.py` header).
- The wiki page taxonomy (`WikiPageCategory`) and
  `_CATEGORY_TO_NODE_KIND` do not know `book`; ranking, lint and
  namespace resolution all assume source-backed pages.
- Two databases must be kept consistent on `remove`/`--force` re-index
  anyway (the PageIndex tree and the catalog still live in Bookstore).
- Communities are recomputed on every CLI call, never persisted on the
  ficha, so the MCP tool would have to cluster on demand.

📊 **Effort:** Medium (less new code) but High integration risk.

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiosqlite` | `SQLiteWikiStore` backend | core dep |
| `parrot.knowledge.wiki` | store, toolkit, communities CLI | becomes a hard runtime dep of Bookstore |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py:944` — `WikiToolkit.remember` (deterministic page ids + asserted edges).
- `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:2364` — `communities` command (`--kinds`, `--inter`).
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:299` — `WikiPageRecord`.

---

### Option C (unconventional): Similarity-only graph — embed the fichas, kNN edges, cluster, no taxonomy

Skip explicit relation types. Embed `summary + topics + toc_digest` per
card with `parrot.embeddings` (or the FEAT-190 `SignalRelevanceConfig`
embedder), build a kNN graph (top-k cosine, threshold), run
`detect_communities` with `signal_config` so edges are weighted by
combined signal relevance, and expose "related books" as nearest
neighbours with the cosine score.

✅ **Pros:**
- No pairwise LLM calls; one embedding per book, cheap to backfill and
  incremental on `add`.
- Captures fuzzy affinity (Confucius ↔ Marcus Aurelius) that no
  deterministic field would.
- `detect_communities(signal_config=…, embedder=…)` already supports
  weighted clustering on this path.

❌ **Cons:**
- No explainability: the agent gets "0.81 similar" instead of
  "parallels — both virtue-ethics manuals for rulers". The user
  explicitly wants typed, rationale-bearing relations.
- Requires an embedding backend (`ai-parrot-embeddings`) — a new
  optional dep for a subsystem that today needs only an LLM.
- Author/genre facts become soft signals the model may miss.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `ai-parrot-embeddings` | embedder backend | optional satellite distribution |
| `numpy` | cosine kNN over ≤ hundreds of vectors | core |
| `graphindex.signal_relevance` (FEAT-190) | edge weighting | already wired into `detect_communities` |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/knowledge/graphindex/communities.py:267` — `_build_weight_fn` / `signal_config` path.
- `packages/ai-parrot/src/parrot/embeddings/` — base + registry.

---

## Recommendation

**Option A** is recommended because:

- It honours the user's split between deterministic and non-deterministic
  relations at the schema level (`origin`, `confidence`, `rationale` on
  every edge), which Option C cannot express and Option B only
  expresses through wiki provenance strings.
- It keeps the MCP read path free of wikitoolkit (Option B's main risk)
  while still delivering the wiki plane + `graph.html` the user wants,
  as a one-way `export-wiki` command — the "both" answer from
  discovery.
- The pairwise LLM cost is contained by design (batch command,
  candidate prefilter, one prompt per book), and everything else runs
  in no-LLM mode.
- Option C's embedding weighting is **not lost**: `detect_communities`
  already accepts `signal_config`/`embedder`, so a later task can add
  similarity-weighted clustering without touching the schema. Recorded
  as an open question, not v1 scope.

What is traded off: a second copy of the graph in the exported wiki
plane (accepted — export is explicit and idempotent), and a small
extension to `graphindex` if rel-weighted Louvain is wanted (default
v1: unweighted, rel expressed through `domain_tags`).

---

## Feature Description

### User-Facing Behavior

**CLI (curation, LLM-optional):**

```bash
bookstore add libro.pdf --relate          # ingest + classify + relate this one book
bookstore relate <book_id> [<book_id>…]   # (re)compute relations for given books
bookstore relate --all [--no-llm]         # backfill: deterministic + LLM + communities
bookstore relate --all --communities-only # recluster without new LLM calls
bookstore related <book_id> [--rel same_author] [--json]
bookstore communities [--json]            # id, label, size, members
bookstore export-wiki [--out <dir>]       # wiki plane + graph.html
```

`bookstore show <book_id>` prints the new card fields (`genre`,
`traditions`, `period`, `community`), and `bookstore list` groups by
community when `--by-community` is passed.

**Agent tools (MCP, read-only), added to `BookstoreToolkit`:**

| Tool | LLM? | Purpose |
|---|---|---|
| `bookstore_related_books(book_id, rel=None, depth=1, top_k=10)` | no | typed neighbours with `rel`, `origin`, `confidence`, `rationale`; `depth=2` walks one more hop (capped) |
| `bookstore_communities()` | no | every community: `community_id`, `label`, `size`, member briefs |
| `bookstore_get_community(community_id)` | no | one community + its inter-community relations |
| `bookstore_search(…, expand_related=False)` | optional | unchanged default; when `True`, the catalog shortlist is widened with depth-1 neighbours before the tree walk (still capped by `max_books`) |

The `bookstore` skill (`.agent/skills/bookstore/SKILL.md`) gains a
funnel step **1b — expand by relations**: after `catalog_search`, call
`bookstore_related_books` on the best hit before opening books; and a
rule to cite the relation's `origin` when it drives a claim ("the
library links these as *parallels* (LLM-inferred, 0.7)").

**Card fields visible to the agent** (`get_card`, `brief()`): `genre`,
`traditions[]`, `period`, `community_id`, `community_label`.

### Internal Behavior

1. **Classification at carding.** `CardDraft` gains `genre`
   (closed `Literal`), `traditions: list[str]`, `period: str | None`.
   `_CARD_PROMPT` asks for them in the same call — no extra LLM cost
   at ingest. `fallback_card_fields` leaves them empty. `BookCard` and
   the `books` table gain the columns (additive migration); the FTS row
   gains `traditions_text`/`genre` so `catalog_search "estoicismo"`
   hits. `slugify` normalises traditions before persistence.

2. **`book_relations` table** (per scope DB):
   `(src_book_id, dst_book_id, rel, weight, origin, confidence,
   rationale, computed_at)`, PK `(src, dst, rel)`. `rel` ∈
   `{same_author, shares_topic, same_tradition, same_genre, same_era,
   same_language, influenced_by, responds_to, parallels,
   contrasts_with, same_community}`. Symmetric rels are stored once
   with `src < dst`; directed ones (`influenced_by`, `responds_to`) as
   given.

3. **`relations.py` — the engine** (pure functions + one batch
   orchestrator on `Bookstore`):
   - *Stage 1 deterministic*: over the merged card list — same
     normalised author (`same_author`), Jaccard(topics) ≥ threshold
     (`shares_topic`, weight = Jaccard), shared tradition slug
     (`same_tradition`), same genre, |year diff| within an era window
     or equal `period` (`same_era`). O(n²) in Python over tens/hundreds
     of cards — negligible.
   - *Stage 2 conceptual (LLM)*: for each target book, candidates =
     Stage-1 neighbours ∪ FTS top-k on the book's summary/topics,
     minus already-judged pairs (unless `--force`), capped (≈ 8). One
     `ask_structured(prompt, RelationDraft)` per book with all
     candidate briefs; the model returns a list of
     `{dst, rel, confidence, rationale}` or an empty list. Relations
     below a confidence floor are dropped. Skipped entirely when
     `has_llm` is `False` or `--no-llm`.
   - *Stage 3 communities*: cards → `UniversalNode(kind=DOCUMENT,
     domain_tags={genre, traditions, scope})`, relations →
     `UniversalEdge(kind=REFERENCES, domain_tags={rel, origin, weight})`
     through `GraphAssembler(tenant_id="bookstore")`;
     `detect_communities(graph, nodes, resolution, seed)` (Leiden if
     the extra is installed, else Louvain); `compute_inter_community_graph`
     for community-level relations. Result is persisted: `community_id`
     + `community_label` on each card, `same_community` edges
     (origin=`community`) rewritten from scratch each run, and the
     inter-community meta-graph stored as JSON in a small
     `communities` table (id, label, size, cohesion, members,
     inter-relations).
   - *Community labelling*: with an LLM, one prompt per community with
     member titles/traditions/topics → short label; fallback
     `derive_community_label(titles)` (already deterministic).

4. **Read path** (`Bookstore.related_books`, `Bookstore.communities`):
   union `book_relations` across scope DBs, drop edges whose endpoints
   are not both in `merged_cards()`, project wins duplicates. No graph
   library on the read path.

5. **`export-wiki`**: opens `SQLiteWikiStore(<out>/wiki.db,
   wiki_name="bookstore")`, upserts one `WikiPageRecord` per card
   (`concept_id="book:<book_id>"`, `category="book"`, `summary`, body
   = rendered ficha + ToC digest, `origin="ingest"`), adds edges
   `(src, dst, rel, provenance)` with provenance `extracted` for
   deterministic/community and `inferred` for LLM rels, then writes
   `graph.html`/`graph.json` via `export_graph` with the same
   communities/inter-community objects. Imports `parrot.knowledge.wiki`
   lazily inside the command only.

### Edge Cases & Error Handling

- **No LLM**: `relate` runs Stages 1 and 3 only and says so; existing
  `llm`-carded books keep their classification; `card_origin` semantics
  unchanged.
- **LLM failure mid-batch**: per-book try/except (same as
  `_draft_card`); the book keeps its deterministic edges, a warning is
  logged, the summary reports `failed[]`. Never aborts the batch.
- **Tiny libraries** (< 3 books): communities are skipped with a note
  (modularity is meaningless); deterministic/LLM relations still work.
- **Isolated books**: singleton communities are allowed
  (`Community.size == 1`, cohesion 0.0 — documented behaviour of
  `detect_communities`); label falls back to the book title.
- **Dangling cross-scope edges** (global book related to a project
  book from another repo): filtered at read time; `relate --all`
  prunes edges whose `dst` no longer exists in any visible scope.
- **`remove`/`--force` re-index**: `remove_book` deletes both
  directions of the book's edges; re-index with a changed slug is
  impossible (`slug = existing.book_id` on update) so edges survive a
  `--force`.
- **Self-relations / duplicate pairs**: rejected at insert (`src != dst`
  CHECK, symmetric canonical ordering).
- **FTS5 column growth**: `books_fts` is created `IF NOT EXISTS`, so
  new FTS columns require detecting the old column set (`PRAGMA
  table_info(books_fts)`) and rebuilding the virtual table from
  `books` — one-time, inside `_ensure_schema`.
- **Non-Latin/ambiguous authors**: `same_author` matches on
  `slugify(author)`; "Marco Aurelio" vs "Marcus Aurelius" will *not*
  match deterministically — that is exactly the LLM `parallels`/alias
  layer's job (documented, not "fixed").
- **`export-wiki` when `parrot.knowledge.wiki` is not importable**
  (satellite-less install): clear `ClickException`, nothing else
  affected.
- **Leiden extra missing**: silent Louvain fallback with a logged
  warning (existing behaviour); `algorithm` recorded in the
  `communities` table so the CLI can show it.

---

## Capabilities

### New Capabilities
- `bookstore-book-classification`: LLM-filled `genre` / `traditions` / `period` on the ficha, FTS-indexed, with deterministic fallback.
- `bookstore-relations-engine`: `book_relations` table + deterministic and LLM-batched conceptual relation computation (`bookstore relate`).
- `bookstore-communities`: graphindex-backed community detection over the book graph, persisted per card, LLM-labelled with deterministic fallback, inter-community relations.
- `bookstore-relation-tools`: `bookstore_related_books`, `bookstore_communities`, `bookstore_get_community`, `expand_related` on `bookstore_search`; skill funnel step 1b.
- `bookstore-wiki-export`: `bookstore export-wiki` → dedicated wikitoolkit plane + `graph.html`.

### Modified Capabilities
- `bookstore-indexed-library` (`sdd/specs/bookstore-indexed-library.spec.md`): ficha schema (§3) grows; tool surface (§4) grows from 7 to 10 tools; ingestion (§5) gains `--relate`; degradation matrix (§6) gains a relations row.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `bookstore/models.py` | extends | `CardDraft` + `BookCard` new fields; new `BookRelation`, `RelationDraft`, `BookCommunity` models |
| `bookstore/catalog.py` | extends | `_ADDED_COLUMNS` entries, `book_relations` + `communities` DDL, FTS rebuild, relation CRUD, merged readers |
| `bookstore/carding.py` | modifies | `_CARD_PROMPT` asks for classification; new relation/label prompts (or a sibling `relations.py`) |
| `bookstore/relations.py` (new) | new | Stages 1–3 + graphindex adapter |
| `bookstore/library.py` | extends | `relate_books`, `related_books`, `communities`, `export_wiki`; `remove_book` cascades edges |
| `bookstore/toolkit.py` | extends | 3 new tools + `expand_related` flag |
| `bookstore/cli.py` | extends | `relate`, `related`, `communities`, `export-wiki`, `add --relate` |
| `bookstore/mcp_server.py` | modifies | docstring/tool count only (tools come from the toolkit) |
| `.agent/skills/bookstore/SKILL.md`, `.claude/commands/bookstore.md` | modifies | funnel step 1b, citation rule |
| `wiki/google/bookstore_assets.py` (`BOOKSTORE_SKILL`) | modifies | mirrors the skill text for Antigravity installs |
| `graphindex/communities.py` | depends on (maybe extends) | optional: honour `payload["weight"]` in `_to_undirected_networkx` for rel-weighted clustering |
| `parrot.knowledge.wiki` | depends on (lazy, CLI-only) | `SQLiteWikiStore`, `WikiPageRecord` for `export-wiki` |
| `packages/ai-parrot/tests/knowledge/bookstore/` | extends | new `test_relations.py`, `test_communities.py`, `test_export_wiki.py`; conftest `make_adapter` learns `RelationDraft`/classification |

No new required dependencies. No breaking change: old cards read back
with empty classification and no relations.

---

## Code Context

### User-Provided Code

_None — the user provided the problem framing only (novels/essays,
author relations à la Calderón de la Barca, conceptual relations à la
Confucius ↔ Marcus Aurelius, reuse of the carding LLM, communities as a
relation type)._

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/knowledge/bookstore/models.py:34
class CardDraft(BaseModel):
    title: str
    authors: list[str]
    year: Optional[int]
    language: Optional[str]
    topics: list[str]          # "5-10 research topics/keywords"
    summary: str

# From packages/ai-parrot/src/parrot/knowledge/bookstore/models.py:64
class BookCard(BaseModel):
    book_id: str; title: str; authors: list[str]; year: Optional[int]
    language: Optional[str]; topics: list[str]; summary: str
    toc_digest: str; toc: list[TocEntry]; tree_name: str
    scope: Literal["project", "global"]; source_path: str; source_sha256: str
    source_format: Literal["pdf", "md", "txt", "epub", "mobi", "docx"]
    page_count: Optional[int]; chapter_count: int; added_at: str
    card_origin: Literal["llm", "fallback", "manual"]
    def brief(self) -> dict: ...            # line 93

# From packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py
_CARD_PROMPT = """You are a librarian writing the catalog card ..."""   # line 21
def slugify(text: str) -> str: ...                                        # line 44
def derive_toc(tree: dict[str, Any], max_depth: int = 2) -> tuple[list[TocEntry], str]  # line 83
def fallback_card_fields(file_path: Path, toc_entries: list[TocEntry]) -> CardDraft     # line 138
async def generate_card_fields(adapter: Any, *, filename: str, doc_description: str,
                               toc_digest: str, samples: list[str]) -> CardDraft         # line 154
def sample_sections(content_loader: Any, node_ids: list[str], max_samples: int = 2) -> list[str]  # line 189

# From packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py
_BOOKS_DDL = "CREATE TABLE IF NOT EXISTS books (...)"           # line 40
_FTS_DDL = "CREATE VIRTUAL TABLE IF NOT EXISTS books_fts USING fts5(...)"  # line 62 (tokenize unicode61 remove_diacritics 2)
_ADDED_COLUMNS: list[tuple[str, str]] = []                        # line 77 — additive migrations hook
class CatalogStore:                                               # line 85
    def __init__(self, db_path: Path | str) -> None
    def _connection(self) -> Iterator[sqlite3.Connection]          # short-lived, WAL
    def _ensure_schema(self, conn) -> None                         # applies _ADDED_COLUMNS via PRAGMA table_info
    def upsert(self, card: BookCard) -> None                       # line 174 — DELETE+INSERT FTS row
    def remove(self, book_id: str) -> bool
    def get(self, book_id: str) -> Optional[BookCard]
    def find_by_sha(self, sha256: str) -> Optional[BookCard]
    def list_cards(self) -> list[BookCard]
    def taken_slugs(self) -> set[str]
    def search(self, query: str, top_k: int = 8) -> list[tuple[BookCard, float]]
def merged_cards(stores: list[tuple[str, CatalogStore]]) -> list[BookCard]   # line 329 — earlier scope wins
def merged_search(...)                                                       # line 355

# From packages/ai-parrot/src/parrot/knowledge/bookstore/library.py
class BookstoreError(RuntimeError)                                 # line 55
class _NullAdapter                                                 # line 59 — ask_structured raises
class Bookstore:                                                   # line 88
    def __init__(self, locations: list[LibraryLocation], adapter: Optional[Any] = None,
                 lightweight_model: Optional[str] = None) -> None  # line 102
    @property has_llm -> bool                                      # line 125
    def _catalog(self, scope: str) -> CatalogStore                 # line 138
    def _toolkit(self, scope: str) -> PageIndexToolkit             # line 143
    def _content_store(self, scope: str) -> NodeContentStore       # line 154
    def _stores(self) -> list[tuple[str, CatalogStore]]            # line 161
    def list_books(self) -> list[BookCard]                         # line 184
    def catalog_search(self, query: str, top_k: int = 8) -> list[BookCard]   # line 188
    def resolve_book(self, book_id: str) -> tuple[BookCard, LibraryLocation] # line 192
    async def search_book(...)                                     # line 221
    async def add_book(self, file_path, scope="project", title=None, authors=None,
                       topics=None, force=False) -> tuple[BookCard, str]      # line 343
    async def _draft_card(...) -> CardDraft                        # try generate_card_fields, except → fallback
    async def add_folder(...)                                      # line 617
    async def remove_book(self, book_id: str) -> bool              # line 663
    async def refresh_card(self, book_id: str) -> BookCard         # line 675

# From packages/ai-parrot/src/parrot/knowledge/bookstore/toolkit.py:26
class BookstoreToolkit(AbstractToolkit):
    name = "bookstore"; tool_prefix = "bookstore"
    def __init__(self, bookstore: Bookstore, **kwargs: Any) -> None
    async def catalog_search / list_books / get_card / get_toc / search_book / read_section / search

# From packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py
def _open_bookstore(llm_spec=None, require_exists=False, scope_needed=None, use_llm=True) -> Bookstore  # line 31
@bookstore.command("add") ... "add-folder" (151) "list" (241) "show" (257) "toc" (279)
"search" (299) "card" (334) "remove" (356) "mcp" (376) "locations" (389)

# From packages/ai-parrot/src/parrot/knowledge/bookstore/_llm.py
def resolve_adapter(llm_spec=None, lightweight_model=None) -> tuple[Optional[Any], Optional[str], Optional[Any]]
ENV_LLM = "PARROT_BOOKSTORE_LLM"; ENV_LLM_LIGHT = "PARROT_BOOKSTORE_LLM_LIGHT"

# From packages/ai-parrot/src/parrot/knowledge/bookstore/mcp_server.py:61
def create_bookstore_mcp_server(locations: list[LibraryLocation], adapter=None,
                                lightweight_model=None) -> StdioMCPServer

# From packages/ai-parrot/src/parrot/knowledge/bookstore/config.py:31
class LibraryLocation:  scope: Scope; root: Path; db_path -> Path (property)
def resolve_locations(cwd=..., require_exists=...) -> list[LibraryLocation]   # line 78

# From packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py:99
async def ask_structured(self, prompt: str, output_type: type, temperature: float = 0.0,
                         system_prompt: Optional[str] = None) -> Any

# From packages/ai-parrot/src/parrot/knowledge/graphindex/communities.py
class Community(BaseModel):            # line 50 — community_id, size, member_node_ids,
                                       #   centroid_node_id, cohesion, modularity_contribution, top_titles, label
class CommunitiesResult(BaseModel):    # line 85 — modularity, resolution, seed, weighted,
                                       #   communities, node_to_community, algorithm
def derive_community_label(titles: Iterable[str], max_terms: int = 3) -> str   # line 166
def detect_communities(graph: rustworkx.PyDiGraph, nodes: list[UniversalNode],
                       resolution: float = 1.0, seed: int = 42,
                       signal_config: SignalRelevanceConfig | None = None,
                       embedder: object | None = None, write_back_to_nodes: bool = True,
                       algorithm: str = "leiden") -> CommunitiesResult          # line 505
def detect_hierarchical_communities(graph, nodes, resolutions=None, seed=42, ...)  # line 662

# From packages/ai-parrot/src/parrot/knowledge/graphindex/inter_community.py
class InterCommunityRelation(BaseModel)   # line 26 — source/target ids+labels, directed counts, weights, coupling_ratio
class InterCommunityGraph(BaseModel)      # line 70 — relations, community_count, connected_pairs, density
def compute_inter_community_graph(graph: rustworkx.PyDiGraph,
                                  communities_result: CommunitiesResult) -> InterCommunityGraph   # line 94

# From packages/ai-parrot/src/parrot/knowledge/graphindex/assemble.py:24
class GraphAssembler:
    def __init__(self, tenant_id: str) -> None
    def add_nodes(self, nodes: list[UniversalNode]) -> list[int]      # line 113
    def add_edges(self, edges: list[UniversalEdge]) -> list[Optional[int]]   # line 124
    .graph -> rustworkx.PyDiGraph

# From packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py
class NodeKind(str, Enum): DOCUMENT, SECTION, SYMBOL, CONCEPT, RATIONALE, SKILL, WIKI_PAGE, RUN, CLAIM   # line 36
class EdgeKind(str, Enum): CONTAINS, REFERENCES, DEFINES, MENTIONS, EXPLAINS, EXTENDS, PRODUCED, ABOUT,
                           SUPPORTED_BY, CONTRADICTS, CALLS, IMPLEMENTS                                  # line 64
class UniversalNode(BaseModel): node_id, kind, title, source_uri, content_ref?, summary?, embedding_ref?,
                                domain_tags: dict, parent_id?, provenance, assertion?                   # line 149
class UniversalEdge(BaseModel): source_id, target_id, kind, provenance, confidence?, assertion?, domain_tags  # line 184
   # confidence MUST be set iff provenance == Provenance.INFERRED (field_validator)

# From packages/ai-parrot/src/parrot/knowledge/graphindex/export_html.py:552
def export_graph(graph: rustworkx.PyDiGraph, output_dir: Path, *, communities=None, analytics=None,
                 inter_community=None, god_top_k: int = 15, title: str = "GraphIndex Knowledge Map",
                 echarts_js: str | None = None, allow_cdn_fallback: bool = True) -> tuple[Path, Path]

# From packages/ai-parrot/src/parrot/knowledge/wiki/store.py
class WikiPageRecord(BaseModel):       # line 299 — concept_id, node_id?, title, category (open str),
                                       #   summary, body, source_id, token_count, origin, asserted_by, updated_at, content_hash
class BaseWikiStore(ABC):              # line 415 — upsert_pages (434), add_edges (437), dump_pages (480), dump_edges (483)
class SQLiteWikiStore(BaseWikiStore):  # line 711
    def __init__(self, db_path: str | Path, wiki_name: str = "", *, read_only: bool = False)   # line 759
    async def add_edges(self, edges: list[tuple]) -> int   # line 1154 — (src, dst, rel) or (src, dst, rel, provenance)
    async def dump_edges(self) -> list[dict]               # line 1729 — keys: src, dst, rel

# From packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
_CATEGORY_TO_NODE_KIND = {module, document, config, overview, summary, entity, concept}   # line 865 — no "book"
_REL_TO_EDGE_KIND = {contains, defines, references, extends, mentions, explains}          # line 875 — unknown rel → REFERENCES
async def _load_graphindex_nodes_edges(store: BaseWikiStore, graph_kinds: frozenset[str])  # line 900 — the adapter template
async def _export_graph_html(store, output_dir, wiki_name, graph_kinds)                    # line 956 — communities + inter + export_graph
def communities(...)                                                                        # line 2364 — `wikitoolkit communities --kinds --inter`
```

#### Verified Imports
```python
from parrot.knowledge.bookstore import BookCard, CardDraft, TocEntry, LibraryLocation, resolve_locations  # bookstore/__init__.py:23-24
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError
from parrot.knowledge.bookstore.catalog import CatalogStore, merged_cards, merged_search
from parrot.knowledge.bookstore.carding import slugify, generate_card_fields, fallback_card_fields
from parrot.knowledge.graphindex.communities import detect_communities, derive_community_label, CommunitiesResult, Community
from parrot.knowledge.graphindex.inter_community import compute_inter_community_graph, InterCommunityGraph
from parrot.knowledge.graphindex.assemble import GraphAssembler
from parrot.knowledge.graphindex.schema import NodeKind, EdgeKind, UniversalNode, UniversalEdge, Provenance
from parrot.knowledge.graphindex.export_html import export_graph
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord   # CLI-only, lazy
```

#### Key Attributes & Constants
- `BookstoreToolkit.tool_prefix = "bookstore"` → tools are named `bookstore_<method>` (toolkit.py:34).
- `CatalogStore._ADDED_COLUMNS: list[tuple[str, str]]` — `(column_name, "ALTER clause")`, applied in `_ensure_schema` (catalog.py:77, :128).
- `books_fts` tokenizer: `unicode61 remove_diacritics 2` (catalog.py:69) — "Calderón" and "Calderon" already match.
- `detect_communities(..., algorithm="leiden")` falls back to Louvain silently when `leidenalg`/`igraph` are missing (communities.py:505 docstring); the extra is `ai-parrot[leiden]` (pyproject.toml:294).
- `Community.community_id` is a 16-char SHA-1 of sorted member ids — stable for identical membership, changes on any membership change (communities.py:50). Persisted labels must therefore be keyed by membership hash or re-labelled each run.
- `UniversalEdge` validator: `confidence` required iff `provenance == INFERRED` (schema.py:187) — LLM relations map to `INFERRED` + confidence; deterministic to `EXTRACTED`.
- `Bookstore.locations` is ordered project-first; `merged_cards` earlier-scope-wins (catalog.py:329).
- Test fake adapter: `tests/knowledge/bookstore/conftest.py:make_adapter()` dispatches `ask_structured` on the schema class — extend the `_structured` side-effect for the new draft models.

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.knowledge.bookstore.relations`~~ — no relations module, no `book_relations` table, no `BookRelation` model today.
- ~~`BookCard.genre` / `.traditions` / `.period` / `.community_id`~~ — not fields; `CardDraft` has only title/authors/year/language/topics/summary.
- ~~`Bookstore.related_books()` / `.communities()` / `.relate_books()` / `.export_wiki()`~~ — none exist.
- ~~`bookstore relate` / `related` / `communities` / `export-wiki` CLI commands~~ — CLI has add, add-folder, list, show, toc, search, card, remove, mcp, locations only.
- ~~Community detection inside Bookstore or PageIndex~~ — only `graphindex.communities`, invoked by `wiki/cli.py` (`build` graph export and `communities` command). PageIndex trees have no cross-document edges.
- ~~Per-edge weight support in `detect_communities`~~ — `_to_undirected_networkx` (communities.py:210) sets weight 1.0 unless `signal_config` is passed; the `PyDiGraph` edge payload's `weight` is ignored there (it **is** read by `compute_inter_community_graph`).
- ~~`WikiPageCategory.BOOK`~~ — the enum has summary/entity/concept/comparison/overview/synthesis/answer/archive; `WikiPageRecord.category` is an open string, so `"book"` is storable but unknown to `_CATEGORY_TO_NODE_KIND` (defaults to `WIKI_PAGE`) and to default query ranking.
- ~~`_REL_TO_EDGE_KIND["parallels"]` etc.~~ — unknown rels map to `REFERENCES` in the wiki graph export; the rel string survives only in the wiki `edges` table.
- ~~`Bookstore.remove_book` cascading to relations~~ — today it only deletes the tree + catalog row.
- ~~An embedder in Bookstore~~ — no `parrot.embeddings` usage anywhere under `bookstore/`.

---

## Parallelism Assessment

- **Internal parallelism**: moderate. Natural task order: (T1) models + catalog schema + carding classification → (T2) `relations.py` Stage 1+2 + `relate`/`related` CLI → (T3) communities Stage 3 + `communities` CLI + LLM labelling → (T4) toolkit tools + `expand_related` + skill/command/assets text → (T5) `export-wiki`. T2 and T3 both edit `library.py`/`catalog.py`; T4 and T5 only read the engine and could run in parallel with each other after T3.
- **Cross-feature independence**: FEAT-531 (`wikitoolkit-cli-llm-fallback`, in progress) touches `bookstore/_llm.py::resolve_adapter` and CLI LLM defaults; this feature does not modify `_llm.py`, only calls `_open_bookstore`. Uncommitted work on `wiki/google/bookstore.py` / `bookstore_assets.py` (Antigravity installer) overlaps only with the skill-text mirror in T4 — coordinate that single file. No overlap with FEAT-529/481/494.
- **Recommended isolation**: `per-spec`.
- **Rationale**: every task touches the same three files (`models.py`, `catalog.py`, `library.py`) and the schema evolves task by task; a single worktree with sequential tasks avoids migration-order conflicts. T4/T5 are small enough that a second worktree buys little.

---

## Open Questions

- [x] Feature or hotfix; base branch? — *Owner: Jesus Lara*: feature on `dev`.
- [x] Where do relations live? — *Owner: Jesus Lara*: both — `book_relations` in `library.db` as source of truth, plus an explicit `bookstore export-wiki` into a dedicated wikitoolkit plane.
- [x] Which relation sources in v1? — *Owner: Jesus Lara*: all four — deterministic (author/topics/language/era), LLM classification on the ficha, LLM pairwise conceptual relations, communities as a relation.
- [x] Agent surface? — *Owner: Jesus Lara*: explicit navigation tools (`bookstore_related_books`, `bookstore_communities`), not implicit expansion (an opt-in `expand_related` flag on `search` is kept as a thin extra).
- [x] When does the pairwise LLM run and with what prefilter? — *Owner: Jesus Lara*: separate `bookstore relate [book_id|--all]` batch (+ optional `--relate` on add); candidates = deterministic neighbours ∪ FTS top-k, cap ≈ 8; one prompt per book.
- [x] Taxonomy closed or open? — *Owner: Jesus Lara*: closed `Literal` for `genre` and `rel`; free text slug-normalised for `tradition`/`period`.
- [x] Community scope and labelling? — *Owner: Jesus Lara*: one graph over merged project+global cards; LLM-generated labels with `derive_community_label` fallback; persisted per book.
- [x] Shape of the wikitoolkit projection? — *Owner: Jesus Lara*: `bookstore export-wiki` command → dedicated plane (`SQLiteWikiStore`, category `book`, typed edges) + `graph.html`; Bookstore never imports wikitoolkit on the MCP path.
- [ ] Storage rule for cross-scope edges: store in the `src` book's scope DB and filter dangling endpoints at read time (proposed default), or keep all edges in the project DB when one exists? — *Owner: Jesus Lara*
- [ ] Per-rel edge weights in clustering: extend `graphindex._to_undirected_networkx` to honour `payload["weight"]` (small, benefits wikitoolkit too), or accept unweighted v1? — *Owner: Jesus Lara*
- [ ] Default Leiden `resolution` for tens-of-books graphs (1.0 tends to yield one giant community on small dense graphs); expose `--resolution` and pick a default empirically on the user's real library? — *Owner: Jesus Lara*
- [ ] Confidence floor for LLM relations (proposed 0.5) and whether to store rejected/low-confidence judgements to avoid re-asking on the next `relate` run. — *Owner: Jesus Lara*
- [ ] Should `export-wiki` also register the plane in the repo's wiki namespaces (`wiki-namespaces` spec) so `wikitoolkit query --wiki bookstore` works, or stay a standalone directory? — *Owner: Jesus Lara*
- [ ] Future: similarity-weighted edges via `detect_communities(signal_config=…)` (Option C signal) — out of v1, revisit after the first real-library run. — *Owner: Jesus Lara*
