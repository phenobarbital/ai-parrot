---
type: feature
base_branch: dev
---

# Brainstorm: Concept-Document Authority Layer

**Date**: 2026-05-11
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

Pure vector RAG over a corporate corpus produces high-confidence false positives because semantic similarity does not capture **document authority** within that corpus:

- *"How do commissions work?"* → retrieves a critical memo titled *"Why our commissions are not working"* instead of the canonical Sales Commissions Policy.
- *"What is our PTO policy?"* → retrieves an FAQ that paraphrases the policy instead of the policy itself.
- *"Refund process?"* → retrieves a customer-service training deck instead of the operational SOP.

The error is **structural**: authority is not a property of *content*, it is a property of the document's role in the corpus, declared by the organization. Embeddings cannot recover this signal post-hoc, no matter how well-tuned the model.

PageIndex already does high-quality intra-document retrieval via LLM tree-search. What is missing is a **routing layer** that, for a given query, asserts *"the authoritative document(s) for this concept is/are X, Y — search inside THOSE PageIndex trees, not the whole corpus"*. This brainstorm explores how to introduce that routing layer.

Affected users: end users of the chatbot (get correct, policy-grounded answers), curators (have a place to declare authority), agent developers (a deterministic routing primitive instead of similarity heuristics).

---

## Constraints & Requirements

- Must build on the existing `PageIndexToolkit` / `PageIndexRetriever` without forking or duplicating the tree-search code.
- Must declare its prerequisite on **FEAT-ontology-entity-extraction** (in-flight, parallel branch): `EntityResolver`, `ToolCallDispatcher`, and schema extensions for `entity_extraction` / `tool_call` on `TraversalPattern`.
- Must survive content paraphrase, document version updates, and multilingual corpora.
- Must provide a graceful degradation chain (primary → secondary → filtered-vector → plain-vector) with `EnrichedContext.source` labeled at every level for transparency.
- **Multi-tenant**: concepts live in a **shared PgVector namespace** filtered by `tenant_id` at query time (not per-tenant schemas).
- **Edge curation at v1**: YAML-declared edges only. No bootstrap script, no LLM auto-proposer. (Deferred to FEAT-topic-authority-operational.)
- **Edge files**: one **per-tenant `authority.<tenant>.yaml`** file living next to the existing tenant ontology files.
- **PageIndex linkage**: ETL writes `pageindex_tree_id` back into the `Document` entity on ingest; trees are **version-scoped** — each `Document.version` gets its own tree, edges target `document_id` (version-agnostic), `is_current=true` flags the live version.
- **Multi-document answers**: when 2–3 primaries match (regional + global + addendum), all contexts are passed to the LLM with `{doc_type, version, authority}` labels for synthesis.
- **Multi-concept queries**: "how do commissions and bonuses differ?" extracts a *list* of concepts; traversal returns the **union** of authoritative documents.
- No new PageIndex tree builders or extractors — PageIndex stays as-is.
- No `Concept` lifecycle UI at v1 (creation/merge/deprecation are YAML edits).

---

## Options Explored

### Option A: Authority graph layer + scoped PageIndex search (recommended)

Introduce `Document` and `Concept` as first-class ontology entities with a curated `covers_topic` relation carrying `authority ∈ {primary, secondary, mentions}`. A new traversal pattern `authoritative_doc_for_topic` walks the graph (with `is_a` concept-taxonomy expansion) to find authoritative documents for the query's concept(s), then calls a new `PageIndexToolkit.search_documents_scoped(tree_ids, query)` to run PageIndex's existing tree-search restricted to those trees. A new `hybrid_concept_match` resolver strategy (synonym → vector → LLM) resolves free-form query terms to `Concept` IDs. When concept extraction fails OR no primary edge matches, a four-level degradation chain (`secondary` → `doc_type`-filtered vector → plain vector) takes over, with every level tagging `EnrichedContext.source` so the agent can disclose provenance.

PageIndex retains its current role unchanged. The new layer is purely a **router**: it decides *which* PageIndex trees to ask, based on declared authority rather than corpus-wide similarity.

✅ **Pros:**
- Captures authority natively in the data model — survives paraphrase, versions, multilingual queries.
- Zero duplication with PageIndex: `search_documents_scoped` just iterates over a subset of `_indices` and calls the existing `retriever.search()` / `retriever.retrieve()`.
- Reuses FEAT-ontology-entity-extraction primitives (`EntityResolver`, `ToolCallDispatcher`, `entity_extraction` + `tool_call` schema fields). No new orchestration plumbing.
- Graceful degradation means *zero regressions*: queries with no concept modeled still flow through to plain PageIndex → vector, same as today.
- Concept taxonomy via `is_a` gives free recall expansion ("commissions" pulls "sales commissions", "channel commissions" without re-curating each edge).

❌ **Cons:**
- Depends on FEAT-ontology-entity-extraction landing first — coordination risk.
- YAML curation at v1 means coverage starts narrow; the system is only as good as the curated edge set. FEAT-topic-authority-operational must follow soon.
- Concept embedding pipeline adds a new write path on every tenant init (mitigated by content-hash idempotency).
- `IntentRouterMixin._run_graph_pageindex` must be extended to propagate `user_context` and `tenant_id` into `ontology_process()` — currently it does not.

📊 **Effort:** Medium-High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (no new external libs) | — | All capability is built on existing PgVector, PageIndex, and ontology stack |
| `pydantic` | `SearchScopedInput`, `EntityExtractionRule` schema models | Already in use; matches `SearchDocumentsInput` pattern |
| `PyYAML` | Loading per-tenant authority YAML | Already used by `OntologyParser` |
| `hashlib` (stdlib) | Concept content hashing for re-embed detection | — |

🔗 **Existing Code to Reuse:**
- `parrot/knowledge/ontology/parser.py` + `merger.py` — load and merge `authority.<tenant>.yaml` on top of base ontology
- `parrot/knowledge/ontology/tenant.py` — `TenantOntologyManager.resolve()` hook for concept-embedding pipeline
- `parrot/knowledge/ontology/mixin.py` — `OntologyRAGMixin.ontology_process()` for degradation chain integration
- `parrot/knowledge/ontology/schema.py` — `EnrichedContext` already has `source` field; reuse for labeling
- `parrot/tools/pageindex_toolkit.py` — extend with `search_documents_scoped()`; reuse `_indices` dict and `retriever.search()` / `retriever.retrieve()`
- `parrot/stores/postgres.py` — `PgVectorStore` for the concepts namespace (extension needed for tenant_id filter — see Open Questions)
- `parrot/bots/mixins/intent_router.py` — `_run_graph_pageindex` refactor to drive PageIndex *through* the ontology

---

### Option B: Vector reranker with authority metadata

Keep one corpus-wide vector index, but at ingest time tag each document with metadata fields (`doc_type`, `is_canonical`, `authority_score`, `effective_date`). Retrieval pulls top-K by similarity, then a reranker (LLM-as-judge or a simple weighted score combining similarity × authority_score × doc_type prior) reorders and selects the answer source. PageIndex tree-search is invoked on the top-1 reranked document.

✅ **Pros:**
- No new graph layer; no ontology coupling.
- Faster to ship — purely a retrieval-pipeline tweak.
- Easy to A/B against pure vector with offline judgments.

❌ **Cons:**
- Does not solve the structural problem — authority remains a soft signal competing with similarity. The *"Why our commissions are not working"* memo still ranks high because its embedding is closer to the query than the policy's.
- Reranker tuning is a per-corpus exercise that never converges; every new document type breaks the priors.
- No taxonomy/inheritance: "commissions" and "sales commissions" remain unrelated unless edge-cased in metadata.
- Per-document `authority_score` curation is just as much manual work as `covers_topic` edges, with less expressive power.

📊 **Effort:** Low-Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (no new external libs) | — | Reranker is in-process |

🔗 **Existing Code to Reuse:**
- `parrot/stores/postgres.py` — add `doc_type`, `authority_score` to existing metadata schema
- `parrot/tools/pageindex_toolkit.py` — invoke unchanged on top-1 doc
- Existing vector RAG path

---

### Option C: LLM-as-router over document catalog

Maintain a flat catalog `{document_id, title, summary, doc_type}` per tenant (no graph, no edges, no concepts). At query time, send the user query + the catalog to an LLM and ask it to pick the top-K authoritative documents to search. Then call `PageIndexToolkit.search_documents` (or a new scoped variant) on the LLM's selection.

✅ **Pros:**
- Minimal data engineering — only document metadata is needed.
- LLM can reason about implicit authority signals (title cues, doc_type) without explicit curation.
- Easy to bootstrap on a new tenant.

❌ **Cons:**
- LLM latency on the hot path for every query (vs graph traversal: O(ms)).
- Non-determinism: same query may route to different documents across runs, breaking caching and audit.
- Does not scale beyond ~100 documents per tenant in the catalog prompt without summarization, and summarization re-introduces the embedding-quality problem we're trying to avoid.
- Cost: every query is an extra LLM call before retrieval even starts.
- No explicit taxonomy: cannot answer "what is the authority document for this concept" outside of a query context.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `AbstractClient` | LLM call for routing | Existing |

🔗 **Existing Code to Reuse:**
- `parrot/clients/*` — any provider
- `parrot/tools/pageindex_toolkit.py` — unchanged invocation

---

## Recommendation

**Option A** is recommended.

The error mode we're solving (*authority is a property of role, not content*) is structural. Options B and C both treat authority as something the system *infers* — either via metadata heuristics or LLM judgement on every query. Both will work passably on the easy cases (*"PTO policy"*) and quietly fail on the hard ones (the *"commissions are not working"* memo problem). Both also accumulate technical debt as the corpus grows: B needs per-corpus reranker tuning, C needs per-query LLM cost and grows the prompt unboundedly.

Option A makes authority **declared, not inferred**. Curators state which document is canonical for which concept; the system trusts the declaration. The traversal pattern is deterministic, cacheable, auditable, and survives content changes (an updated policy keeps its edges; a new memo doesn't inherit them). The degradation chain ensures we don't regress on queries where authority is not yet curated — we just fall back to vector and *label* the response source so the agent can disclose.

We trade off:
- **Curation cost** — YAML edges need to be written and maintained. Mitigated by FEAT-topic-authority-operational which will systematize this.
- **Coordination with FEAT-ontology-entity-extraction** — we depend on its primitives. Mitigated by treating its spec as a hard contract and freezing the interface we consume.
- **Slightly higher engineering effort up-front** — Medium-High vs Low for B/C. We accept this because the cheaper options don't actually solve the problem; they just defer it.

---

## Feature Description

### User-Facing Behavior

A user asks the chatbot *"How do commissions work?"*. The bot's response is grounded in the **Sales Commissions Policy** (the document a human curator has declared authoritative for the Commissions concept), not the highest-similarity match. The response carries provenance: *"Per the Sales Commissions Policy v3.2 (effective 2026-01-15)…"*.

If multiple primary documents apply — say, a global commissions policy plus a Spain-specific addendum — the bot synthesizes from both, naming each: *"Globally, commissions are X. In Spain, per the addendum, Y applies…"*.

If no concept is curated yet for the question (e.g., a brand-new business term not in YAML), the bot answers from vector RAG and discloses: *"I didn't find an authoritative document on this; here is what I found from search…"*.

Multi-concept queries (*"how do commissions and bonuses differ?"*) route through the authoritative documents for **both** concepts and the LLM compares.

### Internal Behavior

1. **Query arrives at the agent.** `IntentRouterMixin` selects the `_run_graph_pageindex` strategy (existing).
2. **`OntologyRAGMixin.ontology_process()` is invoked** with `query`, `user_context`, and `tenant_id`. (The mixin call already exists; `_run_graph_pageindex` must be extended to pass these — currently it only forwards `prompt`.)
3. **Intent resolution** matches the query against the `authoritative_doc_for_topic` traversal pattern's `trigger_intents` (Spanish + English phrases).
4. **Entity extraction** runs the new `hybrid_concept_match` resolver against the `topic` slot, returning a list of `Concept` IDs:
   - Synonym/fuzzy exact match — accept if confidence > 0.95.
   - Vector match top-K against the shared `concepts` namespace, **filtered by `tenant_id`** — accept top-1 if score > 0.85 AND > 1.3× score of top-2.
   - Otherwise, LLM tie-breaker over top-5.
   - Result is cached by `(query_hash, ontology_version, tenant_id)`.
5. **Graph traversal** executes the `authoritative_doc_for_topic` AQL: for each resolved Concept, walk `is_a` 0..3 levels, find primary `covers_topic` edges to `is_current` documents, order by `authority_score DESC, effective_date DESC`, limit 3 *per concept* (union for multi-concept queries).
6. **`ToolCallDispatcher` (from FEAT-ontology-entity-extraction)** invokes `PageIndexToolkit.search_documents_scoped(tree_ids=…, query=…)` with the union of `pageindex_tree_id`s from the traversal results.
7. **PageIndex tree-search** runs unchanged inside each of those trees and returns merged `scoped_results` (per-tree `node_list`, `thinking`, `context`).
8. **`EnrichedContext` is built** with `source="graph:primary"` (or `"graph:secondary"` if degraded), `graph_context` (the doc metadata), and the merged PageIndex contexts.
9. **The agent's LLM** receives all contexts with their `{doc_type, version, authority}` labels and composes the answer.

**Concept embedding pipeline.** On `TenantOntologyManager.resolve()`, for each `Concept` in the resolved tenant ontology, compute `sha256(label + sorted(synonyms) + description)`. Compare against stored hashes in the shared `concepts_index` table (keyed by `(tenant_id, concept_id)`). For changed/new concepts, embed and upsert into the shared `concepts` PgVector namespace with `tenant_id` metadata. Removed concepts → delete rows. Idempotent and fast (~ms cached, ~seconds first load).

**Version-scoped trees.** When ETL ingests a new version of an existing document, `PageIndexToolkit.index_documents` creates a new tree; the ETL writes the new `pageindex_tree_id` into the `Document` entity along with the bumped `version` and `effective_date`, and sets `is_current=true` on the new version while flipping the prior version's `is_current=false`. `covers_topic` edges target `document_id` (version-agnostic), so they automatically follow whichever version is current. Old trees are retained but never searched (traversal filters `is_current=true`).

### Edge Cases & Error Handling

- **Concept extraction returns nothing.** → Skip the graph traversal; fall through to `doc_type IN ('policy', 'manual')`-filtered vector → plain vector. Tag `EnrichedContext.source` accordingly.
- **Concept resolved but no primary edge.** → Relax to `authority == 'secondary'` and retry the same traversal. If still empty, fall through to filtered vector.
- **Multi-concept extracted but only one has a primary doc.** → Return the union (one strong primary + nothing for the other). LLM can still answer the half it has and disclose the gap.
- **`pageindex_tree_id` references a tree that was deleted.** → `search_documents_scoped` silently skips missing tree_ids and logs a warning. Stale-edge alert is the curator's job (FEAT-topic-authority-operational).
- **Two primary documents have equal `authority_score`.** → Deterministic tie-break: `effective_date DESC`, then `created_at DESC`. Same ordering across runs.
- **Concept synonyms list mixes languages.** → Single normalized list; match-time normalization handles case/diacritics. Re-evaluate if multilingual tenants surface concrete pain.
- **YAML edge points to a `document_id` that doesn't exist.** → Loader raises `OntologyMergeError` at startup. Hard fail; not a silent skip.
- **Concept hash collision is impossible in practice** (sha256), so re-embedding correctness is deterministic.

---

## Capabilities

### New Capabilities
- `concept-document-authority`: declared authority routing over Document/Concept entities with PageIndex scoping and graceful degradation.

### Modified Capabilities
- `intent-router`: extend `_run_graph_pageindex` to propagate `user_context` and `tenant_id` into `ontology_process()`, and to drive PageIndex *through* the ontology rather than as a parallel cascade.
- `ontology-rag`: add the four-level degradation chain (primary → secondary → filtered vector → plain vector) inside `ontology_process()` with `source` labeling.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/knowledge/ontology/defaults/base.ontology.yaml` | extends | Add `Document` + `Concept` entity definitions, `covers_topic` + `is_a` relations, `authoritative_doc_for_topic` traversal pattern at the base layer |
| `parrot/knowledge/ontology/parser.py` + `merger.py` | extends | Load per-tenant `authority.<tenant>.yaml` (covers_topic + is_a edges only) on top of base ontology |
| `parrot/knowledge/ontology/tenant.py` (`TenantOntologyManager.resolve`) | extends | Hook the concept-embedding pipeline (content-hash diff + upsert) into the resolve path |
| `parrot/knowledge/ontology/entity_resolver.py` (from FEAT-ontology-entity-extraction) | extends | Add `hybrid_concept_match` strategy (synonym → vector → LLM, with tenant_id filter) |
| `parrot/knowledge/ontology/mixin.py` (`OntologyRAGMixin.ontology_process`) | modifies | Replace static `_build_tool_hint` for `tool_call` post-action with the FEAT-ontology-entity-extraction `ToolCallDispatcher`; insert the four-level degradation chain |
| `parrot/tools/pageindex_toolkit.py` | extends | Add `search_documents_scoped(tree_ids, query, include_tree_context)`; new `SearchScopedInput` pydantic model |
| `parrot/bots/mixins/intent_router.py` (`_run_graph_pageindex`) | modifies | Propagate `user_context` + `tenant_id` to `ontology_process()`; replace parallel cascade with ontology-driven flow with unscoped-PageIndex fallback |
| `parrot/stores/postgres.py` (`PgVectorStore`) | extends | Support `tenant_id` metadata column + WHERE filter on `search()` for the shared concepts namespace (see Open Questions) |
| ETL ingest pipeline (out of scope here; consumer responsibility) | depends on | Must write `pageindex_tree_id`, bump `version`, set `is_current` correctly on document re-index |

No breaking changes to existing public APIs. `PageIndexToolkit.search_documents` is unchanged. `OntologyRAGMixin.ontology_process` signature is unchanged.

---

## Code Context

### User-Provided Code

The user authored a draft brainstorm at `sdd/proposals/FEAT-concept-document-authority-brainstorm.md`. The proposed YAML schema, traversal pattern, `hybrid_concept_match` pseudocode, and `search_documents_scoped` skeleton in that draft are preserved as design intent here; they are not yet code in the codebase.

### Verified Codebase References

Each entry below has been verified against the working tree on 2026-05-11.

#### Classes & Signatures

```python
# parrot/pageindex/retriever.py:11
class PageIndexRetriever:
    async def search(self, query: str) -> "TreeSearchResult": ...        # line 38
    async def retrieve(
        self,
        query: str,
        pdf_pages: Optional[list[tuple[str, int]]] = None,
    ) -> str: ...                                                          # line 81
```

```python
# parrot/tools/pageindex_toolkit.py:39
class PageIndexToolkit(AbstractToolkit):
    _indices: dict[str, dict[str, Any]]  # {index_id: {"tree": ..., "retriever": PageIndexRetriever}} — line 63

    @tool_schema(IndexDocumentsInput)
    async def index_documents(
        self,
        documents: list[str],
        document_names: Optional[list[str]] = None,
    ) -> dict[str, Any]: ...                                               # line 72

    @tool_schema(SearchDocumentsInput)
    async def search_documents(
        self,
        index_id: str,
        query: str,
        include_tree_context: bool = False,
    ) -> dict[str, Any]: ...                                               # line 114
```

```python
# parrot/tools/decorators.py:37
def tool_schema(schema: Type[BaseModel], description: Optional[str] = None):
    """Decorator: attaches a pydantic schema and description to a tool method."""
    # used by PageIndexToolkit; reusable verbatim for SearchScopedInput
```

```python
# parrot/bots/mixins/intent_router.py:107
class IntentRouterMixin:
    async def _run_graph_pageindex(                                        # line 615
        self,
        prompt: str,
        candidates: list[RouterCandidate],  # noqa: ARG002
    ) -> Optional[str]:
        # Current behavior (lines 615–667):
        #   1. if hasattr(self, "ontology_process"): result = await self.ontology_process(prompt)
        #      ⚠ currently passes ONLY prompt — does NOT propagate user_context or tenant_id.
        #   2. else: graph_store.query(...)
        #   3. fallback: pageindex_retriever.retrieve(prompt)
```

```python
# parrot/knowledge/ontology/mixin.py:27
class OntologyRAGMixin:
    async def ontology_process(                                            # line 65
        self,
        query: str,
        user_context: dict[str, Any],
        tenant_id: str,
        domain: str | None = None,
    ) -> EnrichedContext:
        # Flow:
        #   - resolve tenant via TenantOntologyManager.resolve()
        #   - resolve intent via OntologyIntentResolver.resolve()
        #   - cache lookup
        #   - execute_traversal via OntologyGraphStore
        #   - post-action: 'vector_search' → _do_vector_search;
        #                  'tool_call'     → _build_tool_hint (STATIC HINT ONLY, not a real dispatch)
        # FEAT-ontology-entity-extraction will replace _build_tool_hint with ToolCallDispatcher.
```

```python
# parrot/knowledge/ontology/tenant.py:18
class TenantOntologyManager:
    async def resolve(                                                     # line 74
        self,
        tenant_id: str,
        domain: str | None = None,
    ) -> "TenantContext": ...
    # Concept-embedding pipeline hooks in here on resolve().
```

```python
# parrot/knowledge/ontology/merger.py:26
class OntologyMerger:
    def merge(self, yaml_paths: list[Path]) -> "MergedOntology":           # line 51
        # Loads each via OntologyParser.load() and applies layered rules:
        #   - entities with extend=True: properties concatenated, vectorize unioned
        #   - relations: new added; same name → endpoints immutable, discovery rules concatenated
        #   - traversal patterns: trigger_intents deduped/concatenated, query_template/post_action overridden
```

```python
# parrot/knowledge/ontology/schema.py:303
class EnrichedContext(BaseModel):
    source: str = "none"                                                   # line 318
    graph_context: list[dict[str, Any]] | None = None
    vector_context: list[dict[str, Any]] | None = None
    tool_hint: str | None = None
    intent: "ResolvedIntent" | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
```

```python
# parrot/stores/postgres.py:58
class PgVectorStore:
    def __init__(self, schema: str = 'public', ...): ...                   # line 66
    async def add_documents(self, schema=..., table=..., ...): ...         # line 592
    async def search(self, query, schema=..., ...): ...                    # line 745
    # NOTE: tenant separation today is by SCHEMA, not by metadata filter.
    # Shared-namespace + tenant_id WHERE filter requires extension — see Open Questions.
```

#### Verified Imports

```python
from parrot.pageindex.retriever import PageIndexRetriever          # parrot/pageindex/__init__.py
from parrot.tools.pageindex_toolkit import PageIndexToolkit         # parrot/tools/pageindex_toolkit.py:39
from parrot.tools.decorators import tool_schema                     # parrot/tools/decorators.py:37
from parrot.bots.mixins.intent_router import IntentRouterMixin      # parrot/bots/mixins/intent_router.py:107
from parrot.knowledge.ontology.mixin import OntologyRAGMixin        # parrot/knowledge/ontology/mixin.py:27
from parrot.knowledge.ontology.tenant import TenantOntologyManager  # parrot/knowledge/ontology/tenant.py:18
from parrot.knowledge.ontology.merger import OntologyMerger         # parrot/knowledge/ontology/merger.py:26
from parrot.knowledge.ontology.schema import EnrichedContext        # parrot/knowledge/ontology/schema.py:303
from parrot.stores.postgres import PgVectorStore                    # parrot/stores/postgres.py:58
```

#### Key Attributes & Constants
- `PageIndexToolkit._indices: dict[str, dict[str, Any]]` — per-tree records `{index_id: {"tree": ..., "retriever": ...}}` (parrot/tools/pageindex_toolkit.py:63). `search_documents_scoped` will iterate over a subset of these keys.
- `EnrichedContext.source: str` — already supports a label string. New values introduced by this feature: `"graph:primary"`, `"graph:secondary"`, `"vector:filtered"`, `"vector:plain"` (parrot/knowledge/ontology/schema.py:318).
- Default ontologies live under `parrot/knowledge/ontology/defaults/`; tenant-specific ontologies under `{ontology_dir}/clients/{tenant_id}.ontology.yaml`. Per-tenant authority files will follow the same shape: `{ontology_dir}/authority/{tenant_id}.yaml`.

### Does NOT Exist (Anti-Hallucination)

The following are **prerequisites from FEAT-ontology-entity-extraction** — they must land first and are NOT to be referenced as if they exist on `dev` yet:

- ~~`parrot.knowledge.ontology.entity_resolver.EntityResolver`~~ — not yet on dev; contracted by FEAT-ontology-entity-extraction.
- ~~`parrot.knowledge.ontology.tool_dispatcher.ToolCallDispatcher`~~ — not yet on dev; contracted by FEAT-ontology-entity-extraction.
- ~~`EntityExtractionRule`, `ToolCallSpec`, `AuthorizationSpec` on `TraversalPattern`~~ — schema extensions in FEAT-ontology-entity-extraction.
- ~~`ResolvedIntent.resolved_entities`~~ — added by FEAT-ontology-entity-extraction.
- ~~`PageIndexToolkit.search_documents_scoped`~~ — to be added by THIS feature; does not exist yet.
- ~~`PgVectorStore` metadata `tenant_id` WHERE filter on `search()`~~ — current API isolates by `schema=`, not by tenant metadata column. Either extend the store or layer a filter at the caller — see Open Questions.
- ~~`Document.pageindex_tree_id` as an existing property~~ — to be added via the YAML extension in this feature.
- ~~`_run_graph_pageindex` propagating `user_context` and `tenant_id`~~ — current implementation passes only `prompt`. Must be extended.

---

## Parallelism Assessment

- **Internal parallelism**: The work splits cleanly into four largely independent strands once FEAT-ontology-entity-extraction lands:
  1. **YAML schema extension** (Document/Concept entities, relations, traversal pattern) + per-tenant authority loader/merger.
  2. **Concept embedding pipeline** (content-hash diff, upsert, shared-namespace + tenant_id metadata) hooked into `TenantOntologyManager.resolve()`.
  3. **`PageIndexToolkit.search_documents_scoped`** — purely additive to the toolkit; touches only one file.
  4. **`hybrid_concept_match` resolver strategy** + degradation chain inside `OntologyRAGMixin.ontology_process` + `_run_graph_pageindex` refactor — these share `mixin.py` and `intent_router.py` so they sequence together.
  Strand 3 can ship in parallel with everything else. Strands 1+2+4 share the ontology resolve path, so they sequence within a single worktree.

- **Cross-feature independence**:
  - **Hard prerequisite**: FEAT-ontology-entity-extraction (parallel branch). This feature *blocks* on its `EntityResolver` and `ToolCallDispatcher` interfaces being stable.
  - **Drives**: FEAT-topic-authority-operational (curation lifecycle for `covers_topic` edges) — separate feature, no shared files.
  - **Shared files with in-flight specs**:
    - `parrot/knowledge/ontology/mixin.py` — FEAT-ontology-entity-extraction also modifies this. Sequence accordingly.
    - `parrot/bots/mixins/intent_router.py` — FEAT-ontology-entity-extraction also modifies this. Sequence accordingly.
    - `parrot/knowledge/ontology/schema.py` — FEAT-ontology-entity-extraction extends `TraversalPattern` and `ResolvedIntent`. We add `Concept`/`Document` entity schemas; non-overlapping additions.

- **Recommended isolation**: `per-spec`.

- **Rationale**: Although strand 3 (`search_documents_scoped`) is technically independent, the feature's value emerges only when all four strands compose. The shared editing of `mixin.py` and `intent_router.py` across strands 1+2+4 outweighs the benefit of an extra worktree for strand 3. A single worktree off `dev`, with tasks ordered within it, is the right granularity. Mixed-worktree parallelism is the wrong frame here — the bigger parallelism risk is **with FEAT-ontology-entity-extraction**, not within this feature, and that's handled by sequencing the two features (this one rebases onto entity-extraction's branch when it merges).

---

## Open Questions

- [x] **`Section` as a first-class entity, yes or no?** — *Owner: Jesus Lara*: No for v1. Adds ETL complexity and graph size with no demonstrated need. Revisit if a use case requires section-level authority (e.g., a single policy where different sections are owned by different teams).
- [x] **Concept hierarchy depth.** — *Owner: Jesus Lara*: `0..3 INBOUND concept_is_a` as default; tunable per tenant. Document the tradeoff (deeper = better recall, worse latency).
- [x] **Concept synonyms across languages.** — *Owner: Jesus Lara*: Single normalized `synonyms` list at v1. Re-evaluate when multilingual tenants surface concrete failure cases.
- [x] **Authority tie-break beyond `authority_score`.** — *Owner: Jesus Lara*: `effective_date DESC` secondary, `created_at DESC` tertiary. Deterministic across runs.
- [x] **Multi-document response composition.** — *Owner: Jesus Lara*: Pass all 2–3 primaries to the LLM with `{doc_type, version, authority}` labels so it composes with awareness of overlap.
- [x] **Multi-concept queries at v1.** — *Owner: Jesus Lara*: Resolve concept list; return union of authoritative documents. Intersection optimization deferred.
- [x] **Edge curation mechanism for v1.** — *Owner: Jesus Lara*: YAML-only. No bootstrap script and no LLM auto-proposer at v1; that scope belongs to FEAT-topic-authority-operational.
- [x] **PageIndex tree linkage.** — *Owner: Jesus Lara*: ETL writes `pageindex_tree_id` back into the `Document` entity on (re-)ingest. Version-scoped trees; edges target `document_id` not `(document_id, version)`.
- [x] **Tenant isolation for concept embeddings.** — *Owner: Jesus Lara*: Shared PgVector namespace, filter by `tenant_id` metadata at query time. This requires extending `PgVectorStore.search()` to accept a metadata WHERE clause OR adding a `tenant_id` column with a dedicated filter parameter — see the next, still-open, question.
- [ ] **`PgVectorStore` extension shape for tenant filtering.** — *Owner: Jesus Lara*: Today `PgVectorStore` separates tenants by `schema=`. For the shared concepts namespace we need a row-level filter. Two paths:
  (a) Add a generic `metadata_filters: dict[str, Any]` parameter to `PgVectorStore.search()` that ANDs into the WHERE clause; concepts namespace passes `{"tenant_id": tenant_id}`.
  (b) Special-case a `tenant_id` column with a dedicated `tenant_id=` parameter on `search()` and `add_documents()`.
  (a) is more general and re-usable for future per-row filters. (b) is narrower but easier to reason about. *Recommend (a); confirm during spec.*
- [ ] **Per-tenant authority YAML directory location.** — *Owner: Jesus Lara*: Proposed `{ontology_dir}/authority/{tenant_id}.yaml`. Confirm this fits the existing tenant ontology directory convention, or align with `{ontology_dir}/clients/{tenant_id}.ontology.yaml` naming. Either way, only `covers_topic` and `is_a` edges live in this file; `Concept` definitions stay in tenant or base ontology files.
- [ ] **Ordering with FEAT-ontology-entity-extraction.** — *Owner: Jesus Lara*: Confirm the merge order. Likely sequence: FEAT-ontology-entity-extraction lands on `dev` first, then this feature rebases onto it. If timeline pressure forces parallel development, freeze the EntityResolver / ToolCallDispatcher / `entity_extraction` + `tool_call` schema field interfaces in the entity-extraction spec so this feature can build against the contract.
