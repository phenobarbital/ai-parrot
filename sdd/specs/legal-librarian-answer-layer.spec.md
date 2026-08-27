---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
# Intentional FEAT-ID reuse (FEAT-387 escape hatch): FEAT-449 is the Legal
# LLM Wiki initiative (proposal legal-llm-wiki-spanish-eu-law). This spec is
# its SECOND deliverable (reordered roadmap Sprints 1.5 + 2 — evidence
# retrofit + librarian answer layer), following legal-norms-graph-boe
# (first deliverable, done). Same initiative, same ID — not a collision.
reuse_feature_id: FEAT-449
---

# Feature Specification: Legal Librarian Answer Layer — span-verified, fail-closed answers over the BOE norms graph

**Feature ID**: FEAT-449
**Date**: 2026-08-27
**Author**: Jesus Lara
**Status**: draft
**Target version**: next minor

> **Parent initiative**: [Legal LLM Wiki](../proposals/claude_legal-wiki-design.md)
> (design skeleton, revised 2026-08-27, decisions R1–R16) — see also the
> [FEAT-449 proposal](../proposals/legal-llm-wiki-spanish-eu-law.proposal.md) (D1–D5).
> **Prior deliverable**: `legal-norms-graph-boe.spec.md` (Sprint 1, 8/8 tasks done):
> BOE norms graph with `versions[]` temporal validity and `article_in_force`.
> **This deliverable**: reordered-roadmap Sprints **1.5 + 2** — content-hash evidence
> retrofit, YAML-declared ArangoSearch views, the librarian answer contract with the
> deterministic span verifier, and FEAT-450 wiki-namespace integration.

---

## 1. Motivation & Business Requirements

### Problem Statement

A lawyer's search today is full-text search plus reading until it bleeds — and the
LLM alternative is professionally disqualifying: lawyers have been sanctioned for
citing hallucinated case law. The conclusion is not "LLMs don't work for law"; it is
that the LLM must never be the oracle. **The LLM proposes, the evidence disposes**
(R1): the system's answer is the retrieved evidence itself — exact, verifiable spans
of primary sources — with the model's reading as a clearly-labelled, fully anchored
annotation. The governing invariant is one line (R2):

> *The system cannot assert anything about the corpus without a verifiable span
> reference; without a citation, the answer is "no encontré".*

Generation is stochastic; verification is deterministic — either the quoted span
exists in the stored payload with that hash, or it does not. By construction the
system can fail to find law; it cannot invent it. A false negative costs the lawyer
hours; a false positive costs the licence.

Sprint 1 built the deterministic substrate (BOE norms graph, temporal validity).
What is missing is everything that makes it *answer*: sealed content hashes, a way
to *find* an article from natural language inside the graph (today `article_in_force`
is a point lookup by key — there is no content search at all), the librarian output
contract, the deterministic span verifier, and the federation hookup so the corpus
is visible as a wiki namespace (FEAT-450, already merged).

### Goals

- **G1** — Every stored article version carries a sealed `content_hash`
  (sha256 over NFC + newline-normalized text, `hash_norm_version: 1`) so span
  existence is deterministically checkable (R3, R11).
- **G2** — ArangoSearch views are **declarative ontology configuration**: declared
  in the ontology YAML, provisioned idempotently at tenant initialization (R15).
- **G3** — NL retrieval works **inside the graph only**: materia/concept edges +
  a declarative `search_articles` pattern (`SEARCH … BM25()` + temporal filter) over
  the R15 view. No vectors, no embeddings, anywhere (R14).
- **G4** — The answer is a `LegalAnswer`: a precedence-ordered **dossier of
  `SpanRef`s** (primary payload) plus a **reading guide** whose every sentence
  anchors to ≥1 surviving span; unanchorable sentences are removed and the removal
  recorded (R4). Empty dossier ⇒ first-class "no encontré" (R2).
- **G5** — The legal corpus is queryable as a **read-only wiki namespace** through
  the FEAT-450 federation (R16).

### Non-Goals (explicitly out of scope)

- Case law (TC/CJEU/HUDOC/CENDOJ), the authority-verification tier, and the OQ3
  spike — Sprints 3–4 of the reordered roadmap.
- EUR-Lex/CELLAR ingestion (gated on spike OQ4).
- **Any semantic vector search** — rejected, not deferred (R14): no chunk layer, no
  embeddings, no router embedding fallback. The ontology `vectorize`→pgvector path
  is dead code today (§6 Does NOT Exist) and stays untouched.
- PageIndex for this corpus — rejected in discovery (JSON-tree/sidecar duplication,
  English-stoplisted in-memory BM25, whole-tree LLM walk).
- Reading-guide regeneration on heavy pruning — returned as-is in v1 (R12).
- Multi-materia routing / `IntentRouterMixin` configuration — single-materia corpus
  in v1; the router stage here is `as_of` extraction + materia/FTS retrieval only.

---

## 2. Architectural Design

### Overview

Two gates separate this system from a stochastic toy (skeleton §5.1):

| Gate | Question | Mechanism |
|---|---|---|
| **Existence** (this spec, mandatory) | does the quoted span exist? | payload for `(id, version_n)` exists with `content_hash`, and `payload[start:end] == quote` — pure code |
| **Authority** (Sprint 4, out of scope) | is the source officially confirmed? | CENDOJ/TC/EUR-Lex verifiers |

The flow (AgentCrew, deterministic `ToolNode`s around one LLM node):

```
query
  → ToolNode as_of_extract    (regex-first; structured LLM micro-call only as fallback — R9)
  → ToolNode graph_retrieve   (search_articles view pattern + article_in_force + materia
                               edges — all inside the ArangoDB tenant, R14/R15)
  → ToolNode dossier_build    (SpanRef assembly, precedence order, sealed hashes)
  → LegalLibrarianAgent       (ask(structured_output=LegalAnswer); dossier span ids
                               enumerated in the prompt — R12)
  → ToolNode span_verify      (existence gate + anchor integrity + suppression records — R4)
  → ToolNode ground           (GroundednessScorer atom check over the surviving guide)
```

Retrieval is **graph-only** (R14): the BOE corpus was downloaded once into the
ontology tenant (Sprint 1) and every query is answered from the graph — the system
never contacts BOE at answer time. The lexical assist is an ArangoSearch view
(an index over the same collection — zero data duplication), declared in the
ontology YAML (R15) and queried through a declarative pattern that combines
`SEARCH … BM25()` with the `valid_from`/`valid_to` temporal predicate, so a hit on
a repealed wording never enters the dossier for the wrong `as_of`.

Federation (R16): a read-only `BaseWikiStore` adapter exposes the tenant as a wiki
namespace — `search_fts` delegates to the same view, `neighbors` walks the typed
edges, `search_vector` returns `[]` by design. FEAT-450 is merged (`c42802ffe`),
so this lands as consumption of existing machinery plus one registration seam.

### Component Diagram

```
                        ontology YAML (legal v1.1)
                 entities + relations + traversal_patterns
                        + search_views (NEW, R15)
                                  │ provisions (idempotent)
                                  ▼
   ┌──────────────────── ArangoDB legal tenant ────────────────────┐
   │  norma / articulo(versions[]+content_hash) / materia          │
   │  modifica / deroga / pertenece_a edges                        │
   │  legal_articulos_view (ArangoSearch, text_es)  ◄─ NEW         │
   │  span_suppressions (append-only)               ◄─ NEW         │
   └──────┬─────────────────────┬───────────────────────┬──────────┘
          │ search_articles     │ article_in_force      │ read-only adapter
          │ (SEARCH+BM25+as_of) │ (existing pattern)    ▼
          ▼                     ▼               OntologyLegalWikiStore ─→ FEAT-450
   ToolNode graph_retrieve ──→ dossier_build            namespaces (`legal::…`)
                                   │ SpanRefs
                                   ▼
                          LegalLibrarianAgent (structured LegalAnswer)
                                   │
                                   ▼
                       ToolNode span_verify (existence gate,
                       suppression → span_suppressions) → ToolNode ground
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `OntologyDefinition` / `OntologyMerger` (`ontology/schema.py:300`, `merger.py:26`) | **extends** | new `search_views:` section, merged per tenant like traversal patterns |
| `OntologyGraphStore.initialize_tenant` (`ontology/graph_store.py:72`) | **extends** | provisions declared views idempotently (new `_ensure_views` step) |
| `TraversalPattern` / `execute_traversal` (`ontology/schema.py:263`, `graph_store.py:193`) | uses | `search_articles` is a declarative pattern; `validate_aql` passes `SEARCH`/`BM25` |
| `article_in_force` (`parrot_tools/legal/boe/queries.py:24`) | uses | unchanged; dossier resolution per `as_of` |
| `ArticleVersion` / `parse_consolidated` / `BOEDataSource` / `sync_boe` (`parrot_tools/legal/boe/`) | **modifies** | seal `content_hash` + `hash_norm_version` per version; full re-ingest (R7) |
| `AbstractBot.ask(structured_output=…)` (`bots/abstract.py:4202`) | uses | librarian emits `LegalAnswer` structured-first (R12) |
| `ToolNode` (`bots/flows/crew/tool_node.py:168`) / `AgentCrew.run_flow` | uses | deterministic stages around the one LLM node |
| `GroundednessScorer.score` (`security/groundedness/scorer.py:74`) | uses | complementary atom check — it is NOT the span verifier (§6) |
| `BaseWikiStore` (`wiki/store.py:289`) | **implements** | read-only `OntologyLegalWikiStore` adapter |
| `create_wiki_store` (`wiki/store.py:1369`) / `open_namespace_store` (`wiki/federation.py:340`) | **extends** | minimal seam: new backend value `"ontology_legal"` dispatched for namespace kind `database` |
| ArangoSearch view AQL (proven at `wiki/arango_store.py:857-878`, provisioning `:343-400`; also `stores/arango.py:398`) | pattern source | copy the `SEARCH ANALYZER(… TOKENS …) SORT BM25` shape and the multi-analyzer (`text_es`) view-link shape |

### Data Models

```python
# parrot_tools/legal/librarian/models.py  (NEW)

class SpanRef(BaseModel):
    kind: Literal["norma", "articulo"]          # sentencia joins in Sprint 3
    id: str                                     # BOE id or articulo_key ({boe_id}:{numero})
    version_n: int | None                       # articulo version the span indexes into
    start: int                                  # half-open char offsets into the stored
    end: int                                    #   normalized payload of (id, version_n)
    quote: str                                  # must equal payload[start:end] exactly
    content_hash: str                           # sha256 of the stored normalized payload
    hash_norm_version: int                      # normalization contract version (=1)
    title: str
    url: str                                    # boe.es permalink
    as_of: date | None                          # date used to resolve version_n
    basis: Literal["retrieval", "traversal"]

class ConflictNote(BaseModel):
    span_a: str                                 # SpanRef key: "{id}:{version_n}:{start}-{end}"
    span_b: str
    note: str                                   # flagged, NEVER resolved (R5)

class ReadingNote(BaseModel):
    text: str                                   # ONE sentence
    spans: list[str] = Field(min_length=1)      # anchors — SpanRef keys from the dossier
    basis: Literal["deterministic", "llm"]

class LegalAnswer(BaseModel):
    as_of: date                                 # always stated back (R9)
    materias: list[str]
    dossier: list[SpanRef]                      # PRIMARY payload, precedence-ordered
    reading_order: list[str]                    # SpanRef keys — "start with these"
    conflicts: list[ConflictNote]
    reading_guide: list[ReadingNote]            # SECONDARY — anchored or absent
    not_found: list[str]                        # corpus-scoped absence, never ontological
    suppressed_count: int                       # fail-closed prunes (R4)
    disclaimer: str

class SuppressionRecord(BaseModel):             # append-only, span_suppressions collection
    execution_id: str
    suppressed_text: str
    claimed_anchors: list[str]
    reason: Literal["span_not_found", "hash_mismatch", "quote_mismatch",
                    "anchor_lost", "atom_contradicted"]
    user_id: str | None
    created_at: datetime
```

```python
# parrot/knowledge/ontology/schema.py  (EXTENSION, R15)

class SearchViewField(BaseModel):
    path: str                                   # e.g. "titulo" or "versions[*].text"
    analyzers: list[str] = ["text_es"]

class SearchViewLink(BaseModel):
    entity: str                                 # entity name, resolved to its collection
    fields: list[SearchViewField]

class SearchViewDef(BaseModel):
    name: str                                   # view name inside the tenant DB
    links: list[SearchViewLink]

# OntologyDefinition gains:  search_views: dict[str, SearchViewDef] = {}
# MergedOntology gains:      search_views merged across layers (same union
#                            semantics as traversal_patterns)
```

### New Public Interfaces

```python
# parrot_tools/legal/boe/hashing.py  (NEW — Sprint 1.5)
def normalize_for_hash(text: str) -> str: ...       # NFC + \r\n|\r → \n, NOTHING else (R11)
def seal_hash(text: str) -> tuple[str, int]: ...    # (sha256 hex, hash_norm_version=1)

# parrot_tools/legal/boe/queries.py  (EXTENDED)
async def search_articles(
    store: OntologyGraphStore, ctx: TenantContext,
    query: str, as_of: date, limit: int = 20,
) -> list[ArticleHit]: ...                          # executes the declarative pattern

# parrot_tools/legal/librarian/verifier.py  (NEW)
class SpanVerifier:
    async def verify(self, answer: LegalAnswer, retrieval_set: dict[str, str],
                     ) -> tuple[LegalAnswer, list[SuppressionRecord]]: ...
    # pure-code existence gate + anchor integrity; returns the pruned answer

# parrot_tools/legal/librarian/agent.py  (NEW)
class LegalLibrarianAgent(Agent): ...               # read-only toolkits, structured output

# parrot_tools/legal/wiki_store.py  (NEW — R16)
class OntologyLegalWikiStore(BaseWikiStore): ...    # read-only; ~6 methods implemented,
                                                    # writes raise NotImplementedError
```

---

## 3. Module Breakdown

### Module 1: Hash sealing + BOE re-ingest (Sprint 1.5)
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/legal/boe/` (`hashing.py` NEW; `models.py`, `parser.py`/`datasource.py` modified)
- **Responsibility**: `normalize_for_hash` (NFC + newline only, R11), `ArticleVersion` gains `content_hash: str` + `hash_norm_version: int`; sealing happens where version text is constructed so every ingested version carries it; full `sync_boe()` re-run refreshes the corpus (R7 — corpus reproducible from source).
- **Depends on**: nothing (blocking for M4–M7).

### Module 2: Declarative ArangoSearch views in the ontology schema (R15)
- **Path**: `packages/ai-parrot/src/parrot/knowledge/ontology/` (`schema.py`, `merger.py`, `graph_store.py`)
- **Responsibility**: `SearchViewDef`/`SearchViewLink`/`SearchViewField` models; `OntologyDefinition.search_views` + merge (union, same layering as `traversal_patterns`, validation that `entity` names resolve); `OntologyGraphStore._ensure_views` provisioning (create-if-absent, reconcile-if-drifted — copy the reconcile shape from `wiki/arango_store.py:393-400`) called from `initialize_tenant`. Framework change, domain-agnostic.
- **Depends on**: nothing (parallel to M1).

### Module 3: Legal ontology v1.1 — view + search pattern
- **Path**: `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/legal.ontology.yaml`
- **Responsibility**: declare `legal_articulos_view` (links: `Articulo.versions[*].text`, `Norma.titulo`; analyzers `["text_es", "text_en"]`) and the `search_articles` traversal pattern: `SEARCH` over the view + `BM25(doc)` ranking + per-version temporal filter (`valid_from <= @as_of < valid_to|null`) so only the in-force wording for `@as_of` is returned; binds `@query`, `@as_of`, `@limit`.
- **Depends on**: Module 2.

### Module 4: Librarian contracts + span verifier + suppression log
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/legal/librarian/` (`models.py`, `verifier.py`) + `span_suppressions` collection declared in the ontology YAML (M3)
- **Responsibility**: the §2 Pydantic contracts; `SpanVerifier` existence gate (hash equality → offset-slice equality → anchor integrity → prune + `SuppressionRecord`); suppression records land in the **append-only `span_suppressions` collection in the tenant** — NOT `AuditLedger` (see §8 note); empty-dossier rule ⇒ "no encontré" answer shape.
- **Depends on**: Module 1 (hashes must exist).

### Module 5: `search_articles` helper + `as_of` extraction
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/legal/boe/queries.py` (extend) + `parrot_tools/legal/librarian/as_of.py` (NEW)
- **Responsibility**: typed `search_articles()` wrapper (mirrors `article_in_force`'s pattern-lookup style); `extract_as_of(query) -> date | None` — deterministic date regexes first, single structured LLM micro-call (`date | null`) only when regex finds nothing, default today; the used `as_of` always flows into `LegalAnswer.as_of` (R9).
- **Depends on**: Module 3.

### Module 6: Retrieval DAG + `LegalLibrarianAgent`
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/legal/librarian/` (`agent.py`, `flow.py`)
- **Responsibility**: the §2 flow as `AgentCrew.run_flow` with `ToolNode` stages; dossier assembly (SpanRefs from `search_articles` hits + explicit-id lookups, precedence: norm text in force first); prompt enumerates dossier span keys; `ask(structured_output=LegalAnswer)`; post-LLM `span_verify` + `GroundednessScorer` atom stage wired per §5.3 of the skeleton.
- **Depends on**: Modules 4, 5.

### Module 7: Wiki-namespace adapter (R16)
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/legal/wiki_store.py` (NEW) + minimal seams in `parrot/knowledge/wiki/store.py` (`create_wiki_store`) and `wiki/federation.py` (`open_namespace_store`)
- **Responsibility**: read-only `OntologyLegalWikiStore(BaseWikiStore)` — `search_fts` (AQL against `legal_articulos_view`, stub-dict shape per `wiki/store.py` contract), `get_page` (articulo → in-force text page), `list_pages`, `neighbors` (typed edges), `stats`; `search_vector` returns `[]` (R14); all write methods raise. Registration: backend value `"ontology_legal"` accepted by `create_wiki_store` kwargs path and dispatched in `open_namespace_store` for kind `database`, so `.parrotwiki`-style configs can declare `legal:` as a namespace.
- **Depends on**: Modules 2, 3.

### Module 8: Integration tests — the invariant end-to-end
- **Path**: `packages/ai-parrot-tools/tests/legal/` (extend existing fixtures from TASK-2376)
- **Responsibility**: see §4.
- **Depends on**: all modules.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_normalize_for_hash_nfc_newlines_only` | M1 | NFC applied; `\r\n`→`\n`; interior whitespace untouched |
| `test_article_version_carries_sealed_hash` | M1 | parser/datasource output includes `content_hash` + `hash_norm_version=1` |
| `test_search_view_def_merge_and_validation` | M2 | unknown entity name in a view link fails merge; layered union works |
| `test_ensure_views_idempotent` | M2 | second `initialize_tenant` run does not recreate/duplicate the view |
| `test_search_articles_pattern_passes_validate_aql` | M3 | the pattern's AQL passes `validate_aql` unchanged |
| `test_search_articles_temporal_filter` | M3/M5 | a repealed wording matching the query is NOT returned for a later `as_of` |
| `test_span_verifier_hash_mismatch_prunes` | M4 | tampered payload ⇒ span removed, `SuppressionRecord(reason="hash_mismatch")` |
| `test_span_verifier_quote_mismatch_prunes` | M4 | `payload[start:end] != quote` ⇒ pruned + recorded |
| `test_reading_note_loses_all_anchors_is_suppressed` | M4 | sentence removed, `suppressed_count` incremented, record appended |
| `test_empty_dossier_is_no_encontre` | M4 | empty dossier ⇒ `not_found` populated, empty guide, no error |
| `test_extract_as_of_regex_first` | M5 | explicit dates parsed without LLM; none ⇒ `None` (caller defaults today) |
| `test_wiki_store_read_only` | M7 | write methods raise; `search_vector` returns `[]` |
| `test_wiki_store_search_fts_stub_shape` | M7 | stub dicts match the `BaseWikiStore` contract fields |

### Integration Tests
| Test | Description |
|---|---|
| `test_reingest_seals_hashes_end_to_end` | `sync_boe()` over fixtures ⇒ every version in Arango carries a verifiable hash |
| `test_librarian_answers_with_anchored_guide` | known norm question ⇒ dossier non-empty, every guide sentence anchored to surviving spans |
| `test_librarian_honest_not_found` | case-law question over norms-only corpus ⇒ "no encontré", corpus-scoped |
| `test_fabricated_span_cannot_survive` | inject an LLM answer citing a non-retrieved id ⇒ span pruned, sentence suppressed, suppression recorded |
| `test_namespace_exposes_legal_corpus` | `open_namespace_store` with the new backend ⇒ FTS hit on a known article via the federation path |

### Test Data / Fixtures
Reuse the TASK-2376 BOE consolidated-XML fixtures (amendment-chain norms) in
`packages/ai-parrot-tools/tests/legal/conftest.py`; add one tampered-payload fixture
for the hash-mismatch path. LLM-dependent tests mock the client; the verifier and
retrieval tests are fully deterministic (no LLM, no network).

---

## 5. Acceptance Criteria

- [ ] Every `articulo.versions[]` entry in the re-ingested corpus carries
      `content_hash` (sha256 over `normalize_for_hash(text)`) and
      `hash_norm_version = 1`; `supresion` versions (`text=None`) carry no hash.
- [ ] `search_views` declared in an ontology YAML are provisioned idempotently at
      tenant init; running init twice produces one view with the declared links.
- [ ] `search_articles("<known phrase>", as_of)` returns the in-force wording only:
      a query phrase present solely in a superseded version returns that version
      only when `as_of` falls inside its validity window.
- [ ] The one-line invariant holds mechanically: a `LegalAnswer` that cites a span
      absent from the execution's retrieval set (wrong id, wrong hash, or wrong
      offsets) never reaches the caller with that span — it is pruned, the
      dependent sentence suppressed, `suppressed_count` incremented, and a
      `SuppressionRecord` appended.
- [ ] Empty dossier ⇒ the answer IS "no encontré": `not_found` describes materias +
      `as_of` searched; `reading_guide == []`; exit code/shape is success, not error.
- [ ] Every `ReadingNote` in a delivered answer has ≥1 anchor into the delivered
      dossier; `LegalAnswer.as_of` is always populated and matches the resolution
      date used by retrieval.
- [ ] The legal corpus resolves as a read-only FEAT-450 namespace: `search_fts`
      through the federation returns a known article; all write paths refuse.
- [ ] Zero vector-search code paths introduced: no embedder, no pgvector, no chunk
      collection (R14) — enforced by review, greppable by absence.
- [ ] All unit + integration tests pass (`pytest packages/ai-parrot-tools/tests/legal/ -v`
      and the ontology tests for M2).
- [ ] No breaking changes to `article_in_force`, `sync_boe`, or existing ontology
      YAML consumers (base/knowledge/field_services ontologies unaffected by M2).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Verified 2026-08-27 against `dev`
> (direct reads + three discovery sweeps; every entry carries file:line).

### Verified Imports
```python
from parrot_tools.legal.boe.models import ArticleVersion, ParsedNorm      # boe/models.py
from parrot_tools.legal.boe.queries import article_in_force               # boe/queries.py:24
from parrot_tools.legal.boe.sync import sync_boe                          # boe/sync.py:24
from parrot_tools.legal.ids import normalize_boe_id, article_key          # legal/ids.py:19,94
from parrot.knowledge.ontology.schema import (
    EntityDef, RelationDef, TraversalPattern, OntologyDefinition,
    MergedOntology, TenantContext,
)                                                                          # ontology/schema.py:40,116,263,300,330,406
from parrot.knowledge.ontology.graph_store import OntologyGraphStore       # ontology/graph_store.py
from parrot.knowledge.ontology.merger import OntologyMerger                # ontology/merger.py:26
from parrot.knowledge.ontology.validators import validate_aql              # ontology/validators.py:36
from parrot.knowledge.wiki.store import BaseWikiStore, create_wiki_store   # wiki/store.py:289,1369
from parrot.knowledge.wiki.federation import open_namespace_store          # wiki/federation.py:340
from parrot.security.groundedness.scorer import GroundednessScorer         # groundedness/scorer.py:56
from parrot.models.outputs import StructuredOutputConfig                   # models/outputs.py:67
```

### Existing Class Signatures
```python
# parrot_tools/legal/boe/models.py — ArticleVersion (Sprint 1; NO hash fields yet)
class ArticleVersion(BaseModel):
    n: int; text: str | None; valid_from: date; valid_to: date | None
    modified_by: str | None
    kind: Literal["redaccion", "adicion", "supresion"]
    source: Literal["boe_consolidada"]; derived: bool

# parrot_tools/legal/boe/queries.py:24
async def article_in_force(store: OntologyGraphStore, ctx: TenantContext,
                           articulo_key: str, as_of: date) -> ArticleVersion | None
# — reads pattern from ctx.ontology.traversal_patterns; KeyError if undeclared.

# parrot_tools/legal/boe/sync.py:24
async def sync_boe(tenant_id: str, since: date | None = None) -> RefreshReport

# ontology/graph_store.py
class OntologyGraphStore:
    async def initialize_tenant(...)            # :72 — DB + collections + named graph; NO views today
    def _ensure_index(...)                      # :174-191 — documented but a NO-OP body
    async def execute_traversal(...)            # :193 — runs ontology-supplied AQL template

# ontology/schema.py
class EntityDef(BaseModel):                     # :40 — model_config extra="forbid" (:63)
class TraversalPattern(BaseModel):              # :263 — query_template + bind vars + authorization
class TenantContext(BaseModel):                 # :406-421 — tenant_id, arango_db, pgvector_schema

# ontology/validators.py:36
async def validate_aql(aql: str, max_depth: int | None = None) -> str
# rejects ONLY: INSERT|UPDATE|REMOVE|REPLACE|UPSERT, system collections, APPLY|CALL|V8(,
# excess traversal depth. SEARCH / BM25 / TOKENS / ANALYZER pass.

# wiki/store.py
class BaseWikiStore: ...                        # :289-378 — 14 abstract methods; read set:
                                                # get_page, list_pages, search_fts, search_vector,
                                                # neighbors, stats
def create_wiki_store(storage_dir, wiki_name="", backend="sqlite", **kwargs)  # :1369
# backend set CLOSED today: "sqlite" | "memory" | "arangodb"; unknown ⇒ ValueError.

# wiki/federation.py:340
async def open_namespace_store(name, cfg, *, base_dir, read_only=True,
                               arango_timeout=...) -> tuple[BaseWikiStore, Path | None]
# kinds: path | vault | store | database; kind "database" opens ArangoDBWikiStore
# (expects wiki_* collections; read_only verifies instead of provisioning).

# wiki/arango_store.py — the AQL/view shapes to COPY (not import):
#   _view_properties/_create_pages_view  :343-400  (multi-analyzer links, reconcile-on-drift)
#   search_fts SEARCH ANALYZER(... IN TOKENS(@q,@a) ...) SORT BM25(doc) DESC  :857-878

# stores/arango.py (ai-parrot-embeddings) — alternative provisioning reference:
#   create_view(view_name, collections, text_fields, ...)  :398
#   driver create_arangosearch_view  asyncdb arangodb.py:1611

# security/groundedness/scorer.py:74
def score(self, answer_text: str, evidence: EvidenceIndex) -> GroundednessReport
# EvidenceIndex (evidence.py:31) is ATOM-based (money/percent/number/date/identifier).

# bots/abstract.py:4202
async def ask(..., structured_output: Optional[Union[Type[BaseModel],
              StructuredOutputConfig]] = None, ...) -> AIMessage
# result carried on response.structured_output.

# bots/flows/crew/tool_node.py:168
class ToolNode(Node)

# security/audit_ledger.py — WHY IT IS NOT USED HERE:
class AuditLedger:                              # :296
    async def append(*, user_id, channel, tool, provider,
                     credential_material) -> AuditLedgerEntry   # :338
# credential-invocation ledger (KMS-signed fingerprints) — its append contract
# REQUIRES credential_material; a span suppression has none. See §8.
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `SearchViewDef` provisioning | `OntologyGraphStore.initialize_tenant` | new `_ensure_views` step | `graph_store.py:72` |
| `search_articles` pattern | `execute_traversal` + `validate_aql` | declarative AQL template | `graph_store.py:193`, `validators.py:13-33` |
| Hash sealing | version-dict construction in parser/datasource | new `hashing.seal_hash` | `parser.py:202` (`_parse_bloque`), `datasource.py:33` |
| `SpanVerifier` | dossier payloads from `article_in_force`/`search_articles` | pure-code comparison | `queries.py:24` |
| `LegalLibrarianAgent` | `ask(structured_output=LegalAnswer)` | structured-first (R12) | `abstract.py:4202` |
| `ToolNode ground` | `GroundednessScorer.score()` | atoms over surviving guide | `scorer.py:74` |
| `OntologyLegalWikiStore` | `open_namespace_store` kind `database` | new backend dispatch | `federation.py:381-399` |

### Does NOT Exist (Anti-Hallucination)
- ~~`ArticleVersion.content_hash` / `hash_norm_version`~~ — created by M1; absent on `dev`.
- ~~Any ArangoSearch view, analyzer, or `SEARCH` AQL in `parrot/knowledge/ontology/`~~ —
  zero hits package-wide; the only lexical mechanism is an unindexed `LIKE`
  (`entity_resolver.py:414`). M2 creates the first.
- ~~`EntityDef.fts` / any view key in ontology YAML~~ — `extra="forbid"` makes it a
  validation error today; that is precisely what M2 adds (at `OntologyDefinition`
  level, not `EntityDef`).
- ~~`PgVectorStore.upsert()` / `.search()`~~ — do not exist on any store;
  `refresh.py:303` and `mixin.py:611` call them inside `except Exception` — the
  ontology `vectorize`→pgvector stage is dead code. Do NOT wire anything to it (R14).
- ~~`chunk` collection / per-version embeddings~~ — never existed; dropped by R14.
- ~~`KnowledgeRouter`~~ — does not exist (proposal C5); routing machinery is
  `IntentRouterMixin`, not used in v1.
- ~~GraphIndex reading `norma`/`articulo`~~ — impossible by construction: closed
  `NodeKind` enum + `gi_*`-only collection maps (`meta_ontology.py:285-312`,
  `persist.py:508`). Do not route legal retrieval through `GraphIndexToolkit`.
- ~~`EvidenceIndex` as a span verifier~~ — it is atom-based detection only; the
  span existence gate is NEW code (M4).
- ~~`create_wiki_store(backend="ontology_legal")`~~ — backend set is closed today
  (`store.py:1404-1411`); M7 adds the value.
- ~~A generic event method on `AuditLedger`~~ — `append()` is credential-specific;
  there is no fitting call for suppression events (see §8).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Copy the ArangoSearch view-link + reconcile shape from
  `wiki/arango_store.py:343-400` and the `SEARCH … BM25` AQL from `:857-878`
  (adapting field paths to `versions[*].text`); `text_es` + `text_en` analyzers.
- Author `search_articles` exactly like `article_in_force`
  (`boe/queries.py:24-72`): pattern fetched from `ctx.ontology.traversal_patterns`,
  never inlined; `KeyError` on missing pattern is a loud config bug.
- `SpanVerifier` and all `ToolNode` stages: pure code, no LLM, no network —
  the whole point (skeleton §5.3).
- Grounded read-only agent precedent: `agents/security_advisor.py`
  (`_audit_citations`) — mandatory references, citations re-audited, unvalidated
  items routed to review (proposal F010).
- Google-style docstrings, strict typing, Pydantic v2, `self.logger` — house rules.

### Known Risks / Gotchas
- **The view indexes ALL versions** (including repealed wordings) — the temporal
  predicate in the `search_articles` AQL is load-bearing; a missing filter
  silently reintroduces the exact FTS failure mode this system exists to kill
  (repealed law returned with full confidence). Covered by
  `test_search_articles_temporal_filter`.
- **`text_es` analyzer availability** must be confirmed on the target ArangoDB
  (built-in in stock deployments, but verify the dev instance) — first task spike.
- **Re-ingest is a full corpus refresh** (R7): coordinate on the dev ArangoDB
  (wikis live there; VPN required — see ops memory); `sync_boe` is idempotent per
  norm via the refresh pipeline.
- **Nested-array view links**: ArangoSearch link on `versions[*].text` needs
  `trackListPositions`/include-all-fields decisions; validate offsets returned by
  `SEARCH` are NOT used for spans — span offsets always come from the stored
  payload slice, never from the view.
- **`suppresion` versions have `text=None`** — hashing and the view must skip them.
- **Structured-output size**: a large dossier enumerated in the prompt plus a
  structured `LegalAnswer` can get long; keep dossier `limit` bounded (default 20)
  and quotes trimmed at dossier-build time (the verifier checks the quote, not the
  whole payload).
- **Federation seam scope-creep**: M7's `create_wiki_store`/`open_namespace_store`
  changes must stay additive (new backend value dispatch only) — no behavior change
  for `sqlite`/`memory`/`arangodb`.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| — | — | none new: `asyncdb[arangodb]`, Pydantic v2, and the test stack are already workspace dependencies |

---

## 8. Open Questions

### Resolved (carried from the brainstorm decision log — do NOT re-open)

- [x] Librarian contract — *Resolved (R1, R5, R12)*: dossier primary, guide
  secondary and span-anchored; guide may contain reading order, conflict flags,
  corpus-scoped absence, traversal-derived context; structured-first output;
  pruned guide returned as-is.
- [x] Fail-closed semantics — *Resolved (R2, R4)*: no assertion without a
  verifiable span; unanchorable sentences removed AND recorded; empty dossier ⇒
  first-class "no encontré".
- [x] Evidence model — *Resolved (R3, R11)*: spans + payload hashes + recorded
  suppressions; normalization = NFC + newline only, `hash_norm_version: 1`,
  frozen before re-ingest.
- [x] Retrofit strategy — *Resolved (R7)*: full BOE re-ingest with sealed hashes;
  no hash-on-read backfill.
- [x] Retrieval substrate — *Resolved (R14, R15)*: graph-only, no vectors
  anywhere; ArangoSearch views declared in ontology YAML and provisioned at
  tenant init; search as declarative AQL pattern.
- [x] `as_of` extraction — *Resolved (R9)*: regex-first, structured LLM
  micro-call fallback, default today, always stated back.
- [x] Federation timing — *Resolved (R16)*: FEAT-450 is merged; the namespace
  adapter ships in THIS spec, not later.
- [x] Substrate/tenancy — *Resolved (D1/R13)*: ontology tenant, database-per-
  materia model; no GraphIndex namespaces.

### Resolved during spec (deviation surfaced, not silent)

- [x] **Suppression records do NOT go through `AuditLedger`** — the brainstorm's
  §5.3 named `AuditLedger.append()` as the mechanism, but its verified contract is
  credential-specific (`credential_material` required, KMS fingerprint derivation —
  `audit_ledger.py:338`). The *intent* (durable, append-only, attributable record)
  is preserved via the `span_suppressions` append-only collection in the tenant
  (`SuppressionRecord` model, M4). If a signed ledger is later required, an
  `AuditLedger`-style signer can wrap the same records — out of scope here.

### Unresolved (defer to implementation / follow-ups)

- [ ] `text_es` analyzer present on the target ArangoDB deployment? — *Owner: first
  M2/M3 task (5-minute spike; fallback: create the analyzer or use `text_en` +
  Spanish stopword config)*.
- [ ] Exact ArangoSearch link options for the nested `versions[*].text` path
  (`trackListPositions`, `includeAllFields`) — *Owner: M2 implementation; decided
  by fixture tests, not by this spec*.
- [ ] OQ3 (CENDOJ spike) and OQ4 (CELLAR spike) — unchanged, gate Sprints 3–4 and
  EUR-Lex respectively; nothing in this spec depends on them.

---

## Worktree Strategy

- **Isolation**: `per-spec` — one worktree, tasks sequential.
- **Rationale**: M1 (hashes) blocks M4–M6; M2 blocks M3 which blocks M5/M7; the
  dependency chain is nearly linear and M2 touches core ontology files that M3/M7
  read — parallel worktrees would conflict on `schema.py`/`legal.ontology.yaml`.
- **Cross-feature dependencies**: none pending — FEAT-450 is already merged into
  `dev`; Sprint 1 (`legal-norms-graph-boe`) is merged.
- Worktree: `git worktree add -b feat-449-legal-librarian-answer-layer
  .claude/worktrees/feat-449-legal-librarian-answer-layer HEAD` (from `dev`, after
  `/sdd-task`).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-27 | Jesus Lara | Initial draft from revised brainstorm (R1–R16) + three-lane codebase discovery |
