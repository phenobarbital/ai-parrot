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
    path: str                                   # "titulo" or "versions[*].text" (one nesting level max)
    analyzers: list[str] = Field(default_factory=lambda: ["text_es"])

class SearchViewLink(BaseModel):
    entity: str                                 # entity NAME (e.g. "Articulo"); merger resolves
                                                # it to EntityDef.collection and fails if unknown
    fields: list[SearchViewField]

class SearchViewDef(BaseModel):
    links: list[SearchViewLink]
    model_config = ConfigDict(extra="forbid")
    # The view NAME is the dict key in `search_views:` — no name field, no drift.

# OntologyDefinition gains:  search_views: dict[str, SearchViewDef] = Field(default_factory=dict)
# MergedOntology gains:      search_views: dict[str, SearchViewDef] = Field(default_factory=dict)
#                            (union-by-name across layers, later layer wins —
#                             same semantics as traversal_patterns in OntologyMerger)
```

```python
# parrot_tools/legal/librarian/models.py — the LLM-facing DRAFT models.
# THE LLM NEVER EMITS OFFSETS. It emits payload keys + literal quotes; the
# verifier locates each quote deterministically (str.find) and derives
# start/end. This is load-bearing: offsets from a stochastic source would
# defeat the existence gate.

class DraftSpan(BaseModel):
    payload_key: str                            # "{id}:{version_n}" — from the enumerated dossier
    quote: str                                  # verbatim text the librarian cites

class DraftReadingNote(BaseModel):
    text: str                                   # ONE sentence
    spans: list[DraftSpan] = Field(min_length=1)
    basis: Literal["deterministic", "llm"]

class DraftConflictNote(BaseModel):
    span_a: DraftSpan
    span_b: DraftSpan
    note: str

class DraftAnswer(BaseModel):                   # ask(structured_output=DraftAnswer)
    reading_order: list[str]                    # payload keys, librarian's suggested order
    conflicts: list[DraftConflictNote]
    reading_guide: list[DraftReadingNote]
    not_found: list[str]                        # corpus-scoped absence statements

# The FINAL LegalAnswer (above) is assembled by the span_verify stage:
# quotes located → offsets derived → SpanRefs sealed → prunes applied.
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

> Each module below carries an **Implementation detail** block. These are binding:
> implementing agents follow them verbatim unless the code has drifted (verify
> with the file:line anchors in §6 first, then adapt minimally and note the
> deviation in the task's Completion Note).

### Module 1: Hash sealing + BOE re-ingest (Sprint 1.5)
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/legal/boe/` (`hashing.py` NEW; `models.py`, `parser.py` modified; `datasource.py`/`sync.py` unchanged)
- **Responsibility**: normalize-then-store-then-hash so spans slice stored text directly; full `sync_boe()` re-run (R7).
- **Depends on**: nothing (blocking for M4–M6, M8).

**Implementation detail:**

```python
# parrot_tools/legal/boe/hashing.py  (NEW — complete file body)
"""Content-hash sealing for BOE article versions (FEAT-449 R3/R11)."""
import hashlib
import unicodedata

HASH_NORM_VERSION = 1  # bump ONLY with a migration plan — changing this invalidates every stored span

def normalize_for_hash(text: str) -> str:
    """Unicode NFC + newline normalization (\\r\\n|\\r -> \\n). NOTHING else —
    no whitespace collapse: offsets must index text identical to what the
    lawyer is shown (R11)."""
    return unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")

def seal_hash(normalized_text: str) -> str:
    """sha256 hex over the ALREADY-normalized text."""
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
```

- `models.py` — `ArticleVersion` gains two fields (append after `derived`):
  `content_hash: str | None` and `hash_norm_version: int | None`. Enforce with a
  Pydantic `model_validator(mode="after")`: `text is None` ⇔ `content_hash is None`
  ⇔ `hash_norm_version is None` (suprimida versions carry no hash). Update the
  class docstring accordingly.
- `parser.py::_parse_bloque` (line 202) — inside the version loop, replace
  `text = None if kind == "supresion" else _extract_body_text(version_el)` with:

```python
raw = None if kind == "supresion" else _extract_body_text(version_el)
text = normalize_for_hash(raw) if raw is not None else None   # STORE normalized text
content_hash = seal_hash(text) if text is not None else None
norm_version = HASH_NORM_VERSION if text is not None else None
```

  and pass `content_hash=content_hash, hash_norm_version=norm_version` into the
  `ArticleVersion(...)` constructor. **The stored `text` IS the normalized text** —
  hash what you store, slice what you stored. No change to the `valid_to` chaining
  or to the returned record shape (`versions` still `model_dump(mode="json")`).
- Re-ingest: `await sync_boe(tenant_id, since=None)` (full refresh — `since=None`,
  `sync.py:24`). Ops note: the legal tenant lives on the dev ArangoDB (VPN
  required); if the dev DB times out, run data scripts with `ENV=prod`.
- Fixture updates: TASK-2376 fixtures/tests under
  `packages/ai-parrot-tools/tests/legal/` assert version dicts — extend expected
  records with the two new fields; do NOT loosen assertions.

### Module 2: Declarative ArangoSearch views in the ontology schema (R15)
- **Path**: `packages/ai-parrot/src/parrot/knowledge/ontology/` (`schema.py`, `merger.py`, `graph_store.py`)
- **Responsibility**: `search_views:` as first-class ontology YAML config, provisioned idempotently at tenant init. Framework change, domain-agnostic — no `legal` reference anywhere in this module.
- **Depends on**: nothing (parallel to M1).

**Implementation detail:**

- `schema.py`: add `SearchViewField` / `SearchViewLink` / `SearchViewDef` exactly
  as in §2 Data Models (all `extra="forbid"`); add
  `search_views: dict[str, SearchViewDef] = Field(default_factory=dict)` to BOTH
  `OntologyDefinition` (line 300) and `MergedOntology` (line 330). The dict key
  is the view name.
- `merger.py`: merge `search_views` with the same name-keyed union used for
  `traversal_patterns` (later layer overrides same-named view). Add validation
  mirroring the `vectorize` check (merger.py:427-434): every `link.entity` must
  name a merged entity — unknown entity ⇒ merge error naming the view and layer.
- `graph_store.py`: new private method, called as **step 6** at the end of
  `initialize_tenant` (after named-graph creation, ~line 160):

```python
async def _ensure_views(self, db: Any, ctx: TenantContext) -> None:
    """Provision/reconcile declared ArangoSearch views. Idempotent.

    IMPORTANT: drives the underlying arangoasync Database via
    db._connection directly. The asyncdb wrapper
    create_arangosearch_view() calls async views()/create_view() WITHOUT
    awaiting them and raises TypeError against a real server — known
    vendored bug, worked around identically in
    parrot/knowledge/wiki/arango_store.py:358-400 (READ that method
    before writing this one).
    """
    for view_name, view_def in ctx.ontology.search_views.items():
        properties: dict[str, Any] = {"links": {}}
        for link in view_def.links:
            entity = ctx.ontology.entities[link.entity]      # validated by merger
            fields: dict[str, Any] = {}
            for f in link.fields:
                _merge_link_field(fields, f.path)             # path grammar below
            properties["links"][entity.collection] = {
                "analyzers": sorted({a for f in link.fields for a in f.analyzers}),
                "fields": fields,
            }
        connection = db._connection
        existing = await connection.views()
        if not any(v.get("name") == view_name for v in existing):
            await connection.create_view(name=view_name, view_type="arangosearch",
                                         properties=properties)
        elif not _view_matches(await connection.view(view_name), properties):
            await connection.replace_view(view_name, properties)
```

- Path grammar (module-level helper `_merge_link_field(fields, path)`):
  `"titulo"` → `fields["titulo"] = {}`; `"versions[*].text"` →
  `fields["versions"] = {"fields": {"text": {}}}`. Exactly ONE nesting level
  supported; any other shape ⇒ `ValueError` at merge time (checked in merger, not
  at provisioning). ArangoSearch auto-expands array elements under a nested link —
  no `trackListPositions` in v1 (view match positions are NEVER used for spans;
  spans always slice the stored payload — M4).
- Failure posture: mirror `initialize_tenant`'s collection loop — a view failure
  logs `logger.warning` and continues (tenant init must not hard-fail on a search
  index); unit tests still assert the create/reconcile/skip paths.

### Module 3: Legal ontology v1.1 — view + search pattern + suppression collection
- **Path**: `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/legal.ontology.yaml`
- **Responsibility**: declare the view, the `search_articles` pattern, and the `SpanSuppression` entity; bump `version: "1.1"`.
- **Depends on**: Module 2.

**Implementation detail** — add these blocks (style-matched to the existing file):

```yaml
# under entities: (alongside Norma/Articulo/Materia)
  SpanSuppression:
    collection: span_suppressions
    key_field: suppression_id
    properties:
      - suppression_id:
          type: string
          required: true
          unique: true
      - execution_id:
          type: string
          required: true
      - suppressed_text:
          type: string
          required: true
      - claimed_anchors:
          type: list
      - reason:
          type: string
          required: true
      - user_id:
          type: string
      - created_at:
          type: datetime
          required: true

# NEW top-level section (schema support lands in M2):
search_views:
  legal_articulos_view:
    links:
      - entity: Articulo
        fields:
          - path: "versions[*].text"
            analyzers: ["text_es", "text_en"]
      - entity: Norma
        fields:
          - path: "titulo"
            analyzers: ["text_es", "text_en"]

# under traversal_patterns: (alongside article_in_force)
  search_articles:
    description: >
      Lexical candidate search over article wordings, then in-force version
      resolution for @as_of. SEARCH matches at DOCUMENT level (any version's
      text can match) — the temporal filter selects the in-force version and
      the Python helper applies the token-containment guard so a hit that
      exists only in a superseded wording is dropped (see search_articles()
      in parrot_tools/legal/boe/queries.py). Analyzer names cannot be bind
      vars inside ANALYZER()/TOKENS() and view names cannot be bind vars at
      all — both are literal here, matching the view declared above.
    trigger_intents:
      - que dice la ley sobre
      - que articulo regula
      - normativa aplicable
      - which article regulates
    query_template: >
      FOR a IN legal_articulos_view
        SEARCH ANALYZER(a.versions.text IN TOKENS(@query, "text_es"), "text_es")
            OR ANALYZER(a.versions.text IN TOKENS(@query, "text_en"), "text_en")
        LET score = BM25(a)
        SORT score DESC
        LIMIT @limit
        FOR v IN a.versions
          FILTER v.valid_from <= @as_of
          FILTER v.valid_to == null OR v.valid_to > @as_of
          RETURN { articulo_key: a._key, norma_ref: a.norma_ref,
                   numero: a.numero, version: v, score: score }
    post_action: none
```

- `Norma.titulo` participates in the view for ranking/recall, but the pattern
  returns only `articulo` rows — norm-title hits surface through their articles.
- `validate_aql` passes this template (only mutations/system-collections/JS are
  rejected — `validators.py:13-33`); add a unit test asserting exactly that.

### Module 4: Librarian contracts + span verifier + suppression log
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/legal/librarian/` (`__init__.py`, `models.py`, `verifier.py`, `suppression.py` — all NEW)
- **Responsibility**: §2 contracts (final + draft); the deterministic existence gate; the append-only suppression log.
- **Depends on**: Module 1 (hashes), Module 3 (collection).

**Implementation detail:**

- `models.py`: the §2 Data Models blocks verbatim (`SpanRef`, `ConflictNote`,
  `ReadingNote`, `LegalAnswer`, `SuppressionRecord`, `DraftSpan`,
  `DraftReadingNote`, `DraftConflictNote`, `DraftAnswer`), plus:

```python
class PayloadEntry(BaseModel):
    payload_key: str                 # "{articulo_key}:{version_n}"
    payload: str                     # stored NORMALIZED version text
    content_hash: str                # carried from the record (NOT recomputed here)
    title: str                       # "{norma_ref} art. {numero}"
    url: str                         # https://www.boe.es/buscar/act.php?id={norma_ref}
    as_of: date
    version_n: int
    articulo_key: str
    basis: Literal["retrieval", "traversal"]
```

  Key formats everywhere: `payload_key = f"{articulo_key}:{version_n}"`;
  span key = `f"{payload_key}:{start}-{end}"`.
- `verifier.py` — pure code, no LLM, no network, fully unit-testable:

```python
class SpanVerifier:
    """Existence gate (skeleton §5.1/§5.3).

    Verification order per DraftSpan — first failure wins, reason is exact:
      1. payload_key not in retrieval_set          -> prune "span_not_found"
      2. seal_hash(entry.payload) != entry.content_hash
                                                   -> prune "hash_mismatch"
         (defence in depth: store tampered/drifted since ingest)
      3. idx = entry.payload.find(span.quote); idx == -1
                                                   -> prune "quote_mismatch"
         else start, end = idx, idx + len(span.quote)
         (FIRST occurrence — documented, deterministic)
    Then per DraftReadingNote: drop pruned spans from .spans; if none survive
    -> suppress the sentence: suppressed_count += 1, SuppressionRecord(
       reason="anchor_lost", suppressed_text=note.text,
       claimed_anchors=[s.payload_key for s in note.spans]).
    DraftConflictNote with either side pruned -> dropped + recorded
    ("anchor_lost"). reading_order: filtered to surviving payload_keys
    silently (pointers, not claims). Surviving DraftSpans -> SpanRef with
    offsets sealed here (kind/id/version_n/url/as_of/basis from PayloadEntry).
    dossier = deduped surviving SpanRefs, dossier_build order preserved.
    Empty dossier -> LegalAnswer(not_found=[corpus-scoped statement built
    from materias + as_of], reading_guide=[], conflicts=[], dossier=[]).
    """

    def verify(
        self,
        draft: DraftAnswer,
        retrieval_set: dict[str, PayloadEntry],
        *,
        as_of: date,
        materias: list[str],
        execution_id: str,
        user_id: str | None = None,
    ) -> tuple[LegalAnswer, list[SuppressionRecord]]: ...
```

- `suppression.py` — `SuppressionLog` with exactly ONE public method
  `async def append(self, record: SuppressionRecord) -> None`, inserting into
  `span_suppressions` through the tenant's asyncdb connection
  (`suppression_id = f"{execution_id}:{seq}"`). NO update/delete/list methods —
  append-only by construction; reading it is an ops/AQL concern. Why not
  `AuditLedger`: its `append()` requires `credential_material` and derives KMS
  fingerprints (`audit_ledger.py:338`) — a suppression has no credential (§8).

### Module 5: `search_articles` helper + `as_of` extraction
- **Path**: `parrot_tools/legal/boe/queries.py` + `boe/models.py` (extend); `parrot_tools/legal/librarian/as_of.py` (NEW)
- **Responsibility**: typed pattern wrapper with the temporal token guard; deterministic date extraction (R9).
- **Depends on**: Module 3.

**Implementation detail:**

- `boe/models.py` — add:

```python
class ArticleHit(BaseModel):
    articulo_key: str
    norma_ref: str
    numero: str
    version: ArticleVersion          # the in-force version for the queried as_of
    score: float                     # BM25 from the view
```

- `queries.py::search_articles` — mirror `article_in_force` (lines 24-72)
  structurally: pattern fetched from
  `ctx.ontology.traversal_patterns["search_articles"]` (loud `KeyError` if
  undeclared), executed via `store.execute_traversal`, binds
  `{"query": query, "as_of": _iso(as_of), "limit": limit}`. NOTE: no `@@articulo`
  bind — the view name is literal in the template.
  **Token-containment guard** (the load-bearing temporal check, applied in Python
  AFTER the AQL): fold both query and `version.text` with
  `unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()`;
  query tokens = regex `\w{4,}` over the folded query; keep a hit iff ≥1 token is
  a substring of the folded in-force text. If the query yields ZERO such tokens
  (short/stopword-only query), skip the guard. This is what drops a candidate
  whose match lives only in a superseded wording.
- `as_of.py::extract_as_of(query: str, llm_ask) -> date | None` — regexes tried
  IN ORDER over the query:
  1. ISO: `\b(\d{4})-(\d{2})-(\d{2})\b`
  2. numeric ES (day-first): `\b(\d{1,2})/(\d{1,2})/(\d{4})\b`
  3. long ES (case-insensitive): `\b(\d{1,2})\s+de\s+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+de\s+(\d{4})\b`
  Exactly ONE distinct date across all matches → return it, no LLM call. Zero or
  more-than-one distinct dates → ONE structured micro-call:
  `ask(structured_output=AsOfExtraction)` with
  `class AsOfExtraction(BaseModel): as_of: date | None`, prompt = the user query
  plus any regex candidates. `None` → the caller (flow M6) defaults to
  `date.today()`. The used value ALWAYS lands in `LegalAnswer.as_of` (R9);
  invalid calendar dates from regex (e.g. 31/02) are discarded as non-matches.

### Module 6: Retrieval DAG + `LegalLibrarianAgent`
- **Path**: `parrot_tools/legal/librarian/` (`agent.py`, `flow.py`)
- **Responsibility**: the §2 flow; dossier assembly; structured draft; post-LLM gates.
- **Depends on**: Modules 4, 5.

**Implementation detail:**

- `flow.py` — `AgentCrew.run_flow` with `ToolNode` stages (deterministic callables):
  1. `as_of_extract` → M5 `extract_as_of`; output `{query, as_of}` (default today).
  2. `graph_retrieve` → explicit-id pass FIRST: regex `BOE-A-\d{4}-\d+` and
     `articulo_key` shapes recognized via `parrot_tools/legal/ids.py`
     (`is_valid_boe_id`, `article_key`); found articulo ids resolved with
     `article_in_force(store, ctx, key, as_of)`. THEN
     `search_articles(store, ctx, query, as_of, limit=20)`.
  3. `dossier_build` → build `retrieval_set: dict[str, PayloadEntry]` (payload =
     stored normalized version text; `content_hash` carried from the record — NOT
     recomputed; recomputation is the verifier's job) and the prompt enumeration:
     explicit-id entries first, then BM25 order, cap 20. Each prompt entry shows
     `payload_key`, title, validity window (`valid_from`/`valid_to`), and the FULL
     version text. If a payload exceeds 4000 chars, show head 2000 + `\n[...]\n` +
     tail 1000 and say so — the verifier always checks against the FULL payload.
  4. `librarian` → `LegalLibrarianAgent.ask(structured_output=DraftAnswer)`.
     System prompt: the librarian rules from skeleton §5.2 (R1/R5 — may rank,
     flag conflicts, state corpus-scoped absence, narrate traversal-derived
     context; must NOT resolve conflicts or assert beyond the dossier), plus:
     "the ONLY legal payload_key values are the ones enumerated; quotes must be
     copied verbatim from the shown text".
  5. `span_verify` → `SpanVerifier.verify(...)`; append every `SuppressionRecord`
     via `SuppressionLog`; assemble the final `LegalAnswer` (fills `as_of`,
     `materias`, `suppressed_count`, `disclaimer`).
  6. `ground` → `GroundednessScorer.score(guide_text, evidence)` where
     `guide_text` = surviving `ReadingNote.text` joined with newlines and
     `evidence` = `EvidenceIndex` built from the dossier payloads; a CONTRADICTED
     numeric/identifier atom ⇒ suppress that sentence via the same record path
     (reason `"atom_contradicted"`).
- `agent.py` — `class LegalLibrarianAgent(Agent)`: read-only (no write tools
  mounted), no conversation memory, low temperature; class docstring carries the
  one-line invariant (R2) verbatim.
- Final `dossier` ordering: explicit-id spans first, then BM25 score desc; stable
  tiebreak by `payload_key`. Deterministic — same inputs, same order.

### Module 7: Wiki-namespace adapter (R16)
- **Path**: `parrot_tools/legal/wiki_store.py` (NEW) + `parrot/knowledge/wiki/store.py` + `parrot/knowledge/wiki/federation.py` (both minimal, additive)
- **Responsibility**: legal corpus as a read-only FEAT-450 namespace.
- **Depends on**: Modules 2, 3.

**Implementation detail:**

- `wiki/store.py` — pluggable backend registry (additive; existing backends untouched):

```python
_EXTRA_BACKENDS: dict[str, Callable[..., BaseWikiStore]] = {}

def register_wiki_backend(name: str, factory: Callable[..., BaseWikiStore]) -> None:
    """Register a satellite-provided wiki backend (FEAT-449 M7)."""
    _EXTRA_BACKENDS[name] = factory

# in create_wiki_store (line 1369), immediately BEFORE the final ValueError:
if backend in _EXTRA_BACKENDS:
    return _EXTRA_BACKENDS[backend](storage_dir=storage_dir, wiki_name=wiki_name, **kwargs)
```

- `wiki/federation.py::open_namespace_store` — in the `kind == "database"` branch
  (~line 397), BEFORE the `_open_arango` call (read the registry through the
  module so import-time registration is seen):

```python
from parrot.knowledge.wiki import store as wiki_store  # module import, top of file

if cfg.backend and cfg.backend != "arangodb" and cfg.backend in wiki_store._EXTRA_BACKENDS:
    store = wiki_store._EXTRA_BACKENDS[cfg.backend](
        storage_dir=None,
        wiki_name=name,
        database=cfg.database or "",
        arango_params=resolve_arango_params(_arango_config_for(cfg)),
        read_only=read_only,
    )
    await _assert_plane_readable(store)
    return store, None
```

  Behavior for `backend in {"arangodb", None}` is byte-for-byte unchanged.
- `parrot_tools/legal/__init__.py` — registration at import time:
  `register_wiki_backend("ontology_legal", OntologyLegalWikiStore.factory)`.
- `OntologyLegalWikiStore(BaseWikiStore)` — implement ALL 16 abstract methods
  (`wiki/store.py:289-378`; ABC — a partial class will not instantiate). Binding
  mapping table:

| Method | Behavior |
|---|---|
| `upsert_pages`, `add_edges`, `replace_source_slice`, `delete_page`, `upsert_embedding` | `raise NotImplementedError("ontology_legal namespace is read-only")` |
| `get_page(concept_id, include_body)` | `concept_id` = `articulo_key`; body = in-force text for `date.today()` (embedded-array filter, same predicate as `article_in_force`); title `"{norma_ref} art. {numero}"`; `category="articulo"`; `source_id=norma_ref` |
| `list_pages(category, limit, origin)` | AQL over `articulo` (and `norma` when `category == "norma"`); stub dicts, no bodies |
| `search_fts(query, category, limit)` | the `search_articles` AQL with `as_of = today` + the M5 token guard, projected to the stub shape `{concept_id, node_id, title, category, summary, source_id, token_count, score}` — summary = first 280 chars of in-force text; `node_id = articulo_key`; `token_count = len(text) // 4` |
| `search_vector(embedding, limit)` | `return []` — R14; NEVER raise (combined search must degrade silently to lexical) |
| `neighbors(concept_id, rel, direction)` | AQL over `modifica`/`deroga`/`pertenece_a` edge collections filtered by `_from`/`_to`, mapped to `{concept_id, rel, direction}` stubs |
| `dump_pages`, `dump_edges` | plain AQL scans (export path); page bodies = in-force text |
| `stats` | counts: normas, articulos, total versions, in-force versions |
| `orphan_sources`, `broken_edges`, `missing_bodies` | `return []` (wiki lint semantics do not apply to a projected corpus) |

- Constructor/factory:
  `factory(*, storage_dir=None, wiki_name, database, arango_params, read_only=True, **_)`
  — VERIFIES the database and the `articulo` collection exist, NEVER provisions
  (mirror the `read_only` semantics of `arango_store.py:282-306`); raises
  `FileNotFoundError` when absent so `_skip_for` classifies the namespace as
  "unbuilt" (`federation.py:407-420`).

### Module 8: Integration tests — the invariant end-to-end
- **Path**: `packages/ai-parrot-tools/tests/legal/` (extend TASK-2376 fixtures/conftest) + core ontology tests for M2
- **Responsibility**: §4 tables. Librarian/flow tests mock the LLM client with canned `DraftAnswer`s — including one citing a fabricated `payload_key` and one with a mangled quote (both must be pruned + recorded). Verifier/retrieval/adapter tests are fully deterministic (no LLM, no network). Arango-dependent tests reuse TASK-2376's integration markers and skip-if-no-server semantics.
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
- ~~`asyncdb.drivers.arangodb.create_arangosearch_view()` as a usable wrapper~~ —
  it calls async `views()`/`create_view()` WITHOUT awaiting them and raises
  `TypeError: 'coroutine' object is not iterable` against a real server (vendored
  bug, documented and worked around at `wiki/arango_store.py:358-400`). M2's
  `_ensure_views` MUST drive `db._connection` directly, same as the wiki store.
- ~~LLM-emitted span offsets~~ — the librarian never emits `start`/`end`; it emits
  `payload_key` + verbatim `quote` (`DraftSpan`), and the verifier derives offsets
  via `payload.find(quote)`. Any task that has the LLM produce integers into
  `SpanRef.start/end` is implementing the spec wrong.

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
- **Quote ambiguity**: `payload.find(quote)` anchors the FIRST occurrence when a
  quote appears more than once in a payload. Acceptable in v1 (the quote text is
  identical either way — the citation is correct, only the offset choice is
  arbitrary); documented in `SpanVerifier`'s docstring, not solved.
- **asyncdb view-wrapper bug**: never call `create_arangosearch_view()` from the
  installed asyncdb driver (unawaited coroutines — see §6); use the direct
  `db._connection` pattern from `wiki/arango_store.py:358-400`.

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
