<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
An autonomous agent running on a developer machine should be able to persist and search its knowledge without provisioning a PostgreSQL server or container. The requested alternative is LanceDB, usable for vector search alone and for combined vector, full-text and graph retrieval.

The intended users are developers assembling local agents and their retrieval tools. Success means opening a local data directory, ingesting documents, retrieving relevant material, and reopening the same data after restart using existing AI-Parrot configuration and embedding providers. Whether the entire agent must run offline remains a separate user decision.

The existing multi-store toolkit already federates vector and graph origins, but a call selects either each origin's normal search or its FTS method. A dedicated hybrid origin can place LanceDB's vector-plus-FTS results alongside graph results in one call. See Code Context R3–R5.

### Constraints and goals
- Flow: `feature`, based on `dev`, carrying forward the proposal and the brainstorm workflow defaults. The authoring branch is `feat-contracts-demo-agent`; this document creates no implementation branch.
- Add an optional backend in `ai-parrot-embeddings`, using the existing `AbstractStore` abstraction and namespace layout. SDK selection remains explicit; no dependency is installed in this brainstorm. R1–R2.
- Local filesystem persistence must not require a database service, container, cloud account or storage API key. Model providers remain an independent configuration concern.
- Preserve async public operations, stable identities, collection isolation, metadata filtering and default parent-document exclusion. R2.
- Preserve native score semantics and provenance. Vector distance, lexical BM25 and hybrid relevance are different quantities. R4.
- Reuse existing GraphIndex retrieval when graph federation is enabled. Replacing its internal seed backend is a distinct scope choice. R5.
- Keep existing configured PostgreSQL and other backends usable. No automatic migration or global default switch is requested.
- Implement no distributed transactions, cloud deployment or network-filesystem guarantees as part of the proposed baseline.
- No numerical latency, memory, corpus-size or recall target was supplied. Establish a representative corpus during specification before making performance commitments.

User decisions on the five scope questions (recorded after this exploration document was written):
- v1 scope: include vector, FTS and native hybrid, with optional graph federation. (Yes)
- Local-only boundary: a FULLY OFFLINE agent after provisioning — not merely embedded storage
  with existing remote model providers.
- Writer concurrency: independent processes MUST be able to write the same dataset concurrently.
  (The exploration document's single-writer default is superseded.)
- Graph integration: federation with the existing GraphIndex retriever ONLY; LanceDB does not
  replace its internal seed index.
- Hybrid failure: a failing hybrid leg fails that whole origin; other origins continue. No
  partial-result marking.

### Recommended option / probable scope
Recommend **Option A — LanceDB Backend with a Dedicated Hybrid Origin**, subject to the unanswered scope questions. It provides the requested embedded backend and a direct route from native hybrid retrieval to graph federation. The additional adapter is small relative to defining a reusable hybrid API across backends whose semantics already differ.

Choose Option B if a shared hybrid capability for multiple databases is itself a requirement. Choose Option C if separately visible retrieval legs and independent failure handling matter more than native hybrid fusion. If the first release is limited to vector and standalone FTS, Option A can ship its backend first and defer its hybrid origin.

LanceDB's current documentation describes vector-plus-FTS retrieval with default reciprocal-rank fusion and explicit text/vector inputs. This allows retaining AI-Parrot's embedding provider rather than adopting a second embedding registry. The exact async SDK calls and compatible release still require validation. [Official hybrid search documentation](https://docs.lancedb.com/search/hybrid-search).

Implement a full store backend for lifecycle, ingestion, vector search, FTS and native hybrid retrieval. Add a small LanceDB-specific `SearchOrigin` adapter whose normal search uses the selected vector or hybrid mode and whose FTS method performs lexical search. The store owns SDK calls; the origin owns federation payloads. Existing `VectorStoreOrigin` remains usable for vector-only integrations.

**Pros:**

- Covers the requested modes and supports native vector/FTS fusion before graph federation.
- Keeps LanceDB behavior explicit, including score mapping, missing-index errors and query limits.
- Requires no reinterpretation of existing backends' hybrid methods.
- Contains changes mainly within one new backend and one new origin.

**Cons:**

- Adds a backend-specific adapter that may later overlap a generalized capability API.
- Requires a precise store-to-origin hybrid result contract.
- Native hybrid ordering survives in the origin section, but the toolkit's merged list is reranked separately with BM25. R4.

**Effort:** Medium.

**Libraries / Tools:**

| Package | Purpose | Verification |
|---|---|---|
| `lancedb` | Embedded vector, FTS and native hybrid engine | New optional dependency; absent from inspected manifests; version compatibility untested |
| `pyarrow` | Explicit storage schemas and result conversion | Core declares `>=25.0`; R7 |
| Existing embedding backend | Generate vectors through AI-Parrot | Satellite declares local and remote provider extras; R1 |
| `rustworkx`, `aiosqlite` | Existing optional graph composition | Already declared by core; R7 |

**Existing Code to Reuse:**

- `packages/ai-parrot/src/parrot/stores/abstract.py:245` — store search contract and parent visibility.
- `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/base.py:42` — origin interface.
- `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/vector.py:90` — provenance normalization pattern.
- `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/graphindex.py:43` — graph federation configuration.

### Verified code anchors (paths only — open them yourself)
packages/ai-parrot/src/parrot/stores/__init__.py
packages/ai-parrot/src/parrot/interfaces/vector.py
packages/ai-parrot-embeddings/pyproject.toml
packages/ai-parrot/src/parrot/stores/abstract.py
packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/base.py
packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/vector.py
packages/ai-parrot/src/parrot/models/stores.py
packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py
packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/graphindex.py
packages/ai-parrot/src/parrot/knowledge/graphindex/retriever.py
packages/ai-parrot/src/parrot/knowledge/graphindex/sqlite_reader.py
packages/ai-parrot-embeddings/src/parrot/stores/postgres.py
packages/ai-parrot-embeddings/src/parrot/stores/arango.py
packages/ai-parrot/pyproject.toml
packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/__init__.py

### Questions still open in the exploration document
Scope questions are settled (see constraints above). The technical questions the
exploration document left open are:
- Which LanceDB SDK release provides the async API, native FTS and native hybrid search, and
  what is its compatibility envelope with the pyarrow pin already declared by the workspace?
- How should metadata filters and parent-document visibility be represented on this backend?
- What is the store-to-origin hybrid result contract, including native score/rank provenance?
- What index build and read-freshness lifecycle does the backend need (FTS index creation,
  visibility of just-written rows, concurrent readers)?
- What representative corpus should acceptance run against, given no latency/recall target was
  supplied?

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
