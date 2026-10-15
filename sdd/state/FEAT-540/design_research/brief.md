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
wikitoolkit (LLM wiki) and GraphIndex are the parts of AI-Parrot that a developer can use without an agent: point them at a repository, run `wikitoolkit build`, and get a queryable knowledge graph plus a local MCP server for Claude Code / Codex. Today that use case is impossible without installing the whole framework: `ai-parrot` core declares 59 runtime dependencies and a `parrot.conf` settings module with import-time side effects. The cause is not the wiki/graphindex code itself but a handful of eager package roots (`parrot/auth/__init__.py`, `parrot/knowledge/ontology/__init__.py`, `parrot/stores/__init__.py`) and direct imports of framework providers (embedders, LLM adapters, PageIndex toolkit, `AbstractTool` wrappers, navconfig) that the graph code crosses to fetch a Pydantic model, a dataclass or an exception class. Fresh measurements on dev @ 048479633 (Python 3.12): `parrot.auth.exceptions` 1093 modules, `parrot.knowledge.ontology.schema` 1515, `parrot.knowledge.graphindex` 1877, `parrot.knowledge.graphindex.builder` 1986, `parrot.knowledge.wiki.cli` 2202 — all loading navconfig, parrot.conf, navigator_eventbus, asyncdb, pandas, faiss, pyarrow, redis, asyncpg.

A second, newly stated requirement (owner, 2026-10-14): the graph persistence of these planes must become graph-database agnostic and pluggable. Today the GraphIndex persistence backends (SQLite, Postgres, ArangoDB) are duck-typed with no shared contract or registry and their selection is hard-coded at seven call sites; the ontology graph store is ArangoDB-only and exposes raw AQL execution (`execute_traversal(aql=...)`) as its public surface, which core callers (authorization, entity resolution, the intent-routing mixin) and `parrot_tools` callers (legal, procedures, contracts) use with inline or ontology-YAML-declared AQL; the wiki retrieval plane already has an abstract store plus a backend registry, but backend names are hard-coded in Pydantic Literals in four places and the source-collection manager keeps its own ArangoDB/AQL branch. Integrating a new graph database (HelixDB is the concrete candidate, see sdd/proposals/helixdb-provider.brainstorm.md) would otherwise require forking every AQL-coupled path.

### Constraints and goals
- G1 Import ceilings in fresh subprocesses: parrot.auth.exceptions <= 150 modules, parrot.knowledge.ontology.schema <= 240, parrot.knowledge.graphindex <= 800, parrot.knowledge.graphindex.builder <= 1200, parrot.knowledge.wiki.cli <= 850; none of navconfig, parrot.conf, navigator_eventbus, asyncdb, pandas, faiss, pyarrow, redis, asyncpg loaded.
- G2 Nothing under parrot/knowledge/wiki/ or parrot/knowledge/graphindex/ imports parrot.tools.*, parrot.clients.*, parrot.loaders.*, parrot.stores.*, parrot.embeddings.*, parrot.conf or concrete PageIndex adapters at module level.
- G3 Framework capability preserved exactly (real embedders, LLM adapter, PageIndex toolkit, Arango/Postgres planes) — injected rather than imported; hashing embedder stays the offline default.
- G4 Framework tools and the SDK MCP transport share plain operations, input schemas and result serialization; the complete current tool surface (query/page/related/remember/note/status/vault + lint, standup, ledger, structural, decisions, schema, bulk/sync) is preserved.
- G5 Local and remote-proxy stdio MCP run with parrot.mcp / parrot.tools / parrot_tools blocked; framework stdio and HTTP (serve.py) consumers keep working.
- G6 After this feature the graph tree is git-mv-shaped for the follow-up standalone distribution (FEAT-541).
- G7 (new) Every GraphIndex persistence backend satisfies one explicit contract and is selected through one registry/factory seam; consumers never branch on backend; optional capabilities (temporal history, hybrid retrieval, incremental staleness) are discoverable without hasattr probing.
- G8 (new) The ontology graph store has a backend-neutral contract; raw AQL is no longer the public surface for core callers; ArangoDB keeps working unchanged behind that contract.
- No behaviour change for the existing sqlite / memory / arangodb / postgres backends; existing planes reopen unchanged; no data migration.
- No new third-party dependency. navconfig stays an optional lazy credential provider. asyncdb stays the Arango driver; asyncpg+pgvector stay the Postgres driver.
- Hard cuts are acceptable: there are no external consumers; renamed/removed internal APIs are updated in-feature, no deprecation shims (old dotted import paths must still resolve lazily until FEAT-541's redirector).
- Out of scope: the HelixDB backend itself, parrot/interfaces/hierarchy.py (15 direct AQL calls outside the knowledge tree), Cypher, schema migrations, creating packages/parrot-graphindex/.

### Recommended option / probable scope
Phase 1 of 2 (Option B of sdd/proposals/parrot-graphindex-standalone.brainstorm.md): cut the framework seams inside the existing workspace, in place, so that FEAT-541 can later move the tree physically. Decided scope for this revision:
1. PEP 562 lazy roots for parrot/auth, parrot/knowledge/ontology, parrot/stores, plus a subprocess-based import-ceiling harness.
2. Structural Protocols for the providers graph code consumes (embedder incl. similarity search and embedding lookup; LLM caller mirroring PageIndexLLMAdapter.ask/ask_structured/ask_json; PageIndexer limited to the six methods the extractors call) with explicit injection, a built-in default and a ProviderNotAvailable error; GraphIndexEmbedder becomes a framework adapter.
3. Relocation of every AbstractTool/AbstractToolkit wiki wrapper (core tools, structural, decisions, schema, ledger, lint, standup, bulk/sync) to parrot_tools.wiki over shared plain operation modules; lazy old-path compatibility.
4. One configuration resolver (explicit -> env -> optional navconfig -> project defaults -> fallback) replacing the scattered readers, including pg_schema.py's import-time DSN resolution; the SQL dialect map moved out of parrot.tools.
5. Transport-neutral operation descriptors for the wiki MCP server with an explicit auto/framework/sdk selector; golden tool manifests per configuration.
6. Local GraphDocument / loader shapes; GraphIndexLoader moved to parrot.loaders.
7. A backend-neutral GraphIndex persistence contract (base + optional capability contracts) with a backend registry and a single factory replacing the hard-coded sqlite/postgres/arangodb dispatch in factory.py, graphindex/loader.py, wiki/runtime.py, wiki/cli.py (4 sites) and flows/dev_loop/graph_memory.py; the ArangoDB backend becomes a framework adapter like the others; wiki backend Literals validated against the registry; the source-collection manager's ArangoDB branch moved behind a backend contract.
8. A backend-neutral ontology graph-store contract with typed operations for the traversals core code performs (management-chain reachability, document field lookup, exact-key and fuzzy entity lookups, declared traversal patterns, dynamic LLM-generated queries), so that raw query execution is dialect-explicit and no core caller composes AQL; the ArangoDB implementation keeps AQL internally; parrot_tools callers (legal, procedures, contracts) are migrated.

### Verified code anchors (paths only — open them yourself)
packages/ai-parrot/src/parrot/auth/__init__.py
packages/ai-parrot/src/parrot/auth/exceptions.py
packages/ai-parrot/src/parrot/knowledge/ontology/__init__.py
packages/ai-parrot/src/parrot/knowledge/ontology/schema.py
packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py
packages/ai-parrot/src/parrot/knowledge/ontology/authorization.py
packages/ai-parrot/src/parrot/knowledge/ontology/entity_resolver.py
packages/ai-parrot/src/parrot/knowledge/ontology/mixin.py
packages/ai-parrot/src/parrot/knowledge/ontology/intent.py
packages/ai-parrot/src/parrot/knowledge/ontology/validators.py
packages/ai-parrot/src/parrot/stores/__init__.py
packages/ai-parrot/src/parrot/stores/abstract.py
packages/ai-parrot/src/parrot/knowledge/graphindex/__init__.py
packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py
packages/ai-parrot/src/parrot/knowledge/graphindex/embed.py
packages/ai-parrot/src/parrot/knowledge/graphindex/factory.py
packages/ai-parrot/src/parrot/knowledge/graphindex/loader.py
packages/ai-parrot/src/parrot/knowledge/graphindex/persist.py
packages/ai-parrot/src/parrot/knowledge/graphindex/persist_sqlite.py
packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py
packages/ai-parrot/src/parrot/knowledge/graphindex/pg_schema.py
packages/ai-parrot/src/parrot/knowledge/graphindex/publish.py
packages/ai-parrot/src/parrot/knowledge/graphindex/retriever.py
packages/ai-parrot/src/parrot/knowledge/graphindex/signals.py
packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/loader.py
packages/ai-parrot/src/parrot/knowledge/retrieval/pin.py
packages/ai-parrot/src/parrot/knowledge/contracts/temporal.py
packages/ai-parrot/src/parrot/flows/dev_loop/graph_memory.py
packages/ai-parrot/src/parrot/knowledge/wiki/store.py
packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py
packages/ai-parrot/src/parrot/knowledge/wiki/postgres_store.py
packages/ai-parrot/src/parrot/knowledge/wiki/federation.py
packages/ai-parrot/src/parrot/knowledge/wiki/sources.py
packages/ai-parrot/src/parrot/knowledge/wiki/models.py
packages/ai-parrot/src/parrot/knowledge/wiki/project.py
packages/ai-parrot/src/parrot/knowledge/wiki/llm_resolve.py
packages/ai-parrot/src/parrot/knowledge/wiki/runtime.py
packages/ai-parrot/src/parrot/knowledge/wiki/triage.py
packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
packages/ai-parrot/src/parrot/knowledge/wiki/tools.py
packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py
packages/ai-parrot/src/parrot/knowledge/wiki/structural/tools.py
packages/ai-parrot/src/parrot/knowledge/wiki/decisions/tools.py
packages/ai-parrot/src/parrot/knowledge/wiki/schema/tools.py
packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py
packages/ai-parrot/src/parrot/knowledge/wiki/serve.py
packages/ai-parrot/src/parrot/knowledge/wiki/documents.py
packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py
packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py
packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py
packages/ai-parrot-tools/src/parrot_tools/graphindex/flowtask.py
packages/ai-parrot-tools/src/parrot_tools/legal/wiki_store.py
packages/ai-parrot-tools/src/parrot_tools/legal/boe/queries.py
packages/ai-parrot-tools/src/parrot_tools/procedures/retrieval.py
packages/ai-parrot-tools/src/parrot_tools/contracts/retrieval.py
sdd/proposals/parrot-graphindex-standalone.brainstorm.md
sdd/proposals/helixdb-provider.brainstorm.md
sdd/specs/parrot-graphindex-package.spec.md

### Questions still open in the exploration document
- TenantContext carries ArangoDB-named fields (arango_db, pgvector_schema) and the ontology schema carries ArangoSearch view definitions (SearchViewDef) and ArangoDB collection names; should a backend-neutral contract rename or reinterpret them, and who owns that change?
- The intent resolver lets the LLM generate dynamic AQL validated by a regex-based AQL validator; how should dynamic query generation behave for a backend whose query language has no validator?
- parrot_tools legal tools construct the ontology store directly against ArangoDB with inline AQL; should they stay explicitly ArangoDB-bound or be migrated to typed operations?
- parrot/knowledge/retrieval/pin.py reads the SQLite files table directly through the persistence's private db path; is that an acceptable SQLite-only consumer?
- The GraphIndex ArangoDB backend composes the ontology graph store; should the two contracts stay layered that way?
- Should the ontology traversal patterns declared in ontology YAML (query_template) carry one template per query dialect, or be expressed in a neutral form?

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
