---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: ADR extraction and decision retrieval in the LLM wiki

**Date**: 2026-09-19
**Author**: Codex with Jesús Lara
**Status**: exploration
**Recommended Option**: B

## Problem Statement

The wiki provides structural code knowledge and searchable documents, but a coding agent also needs to understand which architectural decisions apply to a symbol and why. Existing ADRs contain explicit rationale; code without ADRs can provide evidence for candidate decisions, but cannot prove historical intent or rejected alternatives.

The opportunity is to connect both kinds of knowledge to existing symbol pages. A lookup should distinguish documented decisions from inferred candidates and expose source citations, lifecycle status, and freshness. This supplements AST/tree-sitter extraction rather than replacing it.

## Constraints & Requirements

- User confirmed feature flow from `dev`.
- Include both existing ADR ingestion and generation of labeled candidates from code.
- Support symbol-to-decision lookup and cited “why” retrieval as complementary paths. Their relative delivery priority remains open.
- Candidates must remain visibly inferred until reviewed. A confidence score must never confer accepted status.
- Keep repository scans and retrieval usable without an LLM; generation is an explicit, bounded operation using `AbstractClient` and Pydantic output models.
- Preserve normal code/document search and existing page identities. Do not require GraphIndex deployment to retrieve decisions in the wiki plane.
- No new dependency is proposed. Existing parser extras remain optional; reuse available language scanner outputs.
- This artifact is exploration only; it does not authorize implementation or assert a finalized storage/API contract.

## Options Explored

### Option A: Document-first ADR pages with separate candidate drafts

Recognize ADR documents, extract their sections and lifecycle, and link explicit code citations. A separate generation operation produces draft Markdown ADRs for review and subsequent ingestion.

**Pros:** Smallest conceptual extension; review uses ordinary version-controlled documents; default ingestion stays deterministic.

**Cons:** Candidate lookup is incomplete until drafts are ingested; duplicate drafts and decision identifiers need coordination; inferred and documented knowledge can become separate workflows.

**Effort:** Medium.

**Libraries / Tools:** Existing Pydantic, language scanners, wiki store/search, and `AbstractClient` structured invocation. No additional ADR package.

**Existing Code to Reuse:** `repo_scan.py:634` file extraction, `store.py:409` pages, `graphindex/extractors/code.py:564` citation normalization, and `graphindex/extractors/llm.py:146` structured invocation pattern. Full paths appear in Code Context.

### Option B: Evidence-backed decision records linked to symbols

Introduce a shared decision representation for imported ADRs and inferred candidates. Both enter the wiki retrieval plane with explicit origin, lifecycle, evidence, and symbol links. Deterministic ingestion handles documents and references; an explicit generation operation proposes candidates. Review records acceptance, rejection, or revision without erasing original provenance.

**Pros:** Both retrieval paths use the same records; status and evidence remain visible; candidates become useful immediately without masquerading as accepted decisions; incremental invalidation can track source dependencies.

**Cons:** Requires lifecycle and persistence design across store backends, result packing, and CLI/MCP surfaces. More substantial than parsing Markdown; broad inference can create noise unless scope and budgets are bounded.

**Effort:** High.

**Libraries / Tools:** Pydantic (`packages/ai-parrot/pyproject.toml:54`), existing `aiosqlite` (`:195`), scanner extras (`:274`, `:301`), and existing provider-neutral clients. Reuse wiki storage abstractions rather than introducing a separate vector database.

**Existing Code to Reuse:** `StructuralService.lookup` (`structural/service.py:136`), `WikiCombinedSearch.search` (`search.py:91`), page origin/hash fields (`store.py:444`), and extraction patterns (`graphindex/extractors/llm.py:127`).

### Option C: Query-time decision dossiers

A less obvious approach: persist explicit citation links and source evidence, then assemble an ephemeral ADR-shaped dossier only when a symbol or “why” query is made. Inferred explanations remain labeled, and only explicitly saved dossiers become reviewable candidates.

**Pros:** Avoids a large generated ADR corpus; generation is driven by actual questions; freshest available code can ground each dossier.

**Cons:** Repeated latency/cost, less reproducibility, and uneven inventory coverage; candidate review still needs persistence; query-time generation complicates offline operation.

**Effort:** Medium for a constrained prototype; High with durable review and backend parity.

**Libraries / Tools:** Existing structural service, wiki context packing, search, Pydantic, and `AbstractClient`; no additional packages.

**Existing Code to Reuse:** `structural/service.py:136`, `context.py:208` result packing, and `toolkit.py:356` query composition. Current query composition is snippet-based, not already an ADR reasoning engine.

## Recommendation

**Option B** best matches the confirmed requirement to ingest ADRs and generate candidates while supporting both retrieval paths. Its extra lifecycle work prevents candidates from silently becoming architectural authority.

Deliver in dependent increments within one feature: deterministic ADR ingestion and reference resolution; symbol/decision retrieval; then bounded candidate generation and review. The final feature includes all three. This trades a larger implementation for a consistent evidence and status contract. Option A is a useful lower-cost fallback if lifecycle/backend scope proves excessive.

## Feature Description

### User-Facing Behavior

Given a symbol identifier or qualified name, return applicable documented decisions and a separately labeled candidate group. Each item includes decision text, status, source path and line/section, relationship to the symbol, and freshness. Ambiguous symbol names return disambiguation choices instead of silently selecting a file.

A “why” query retrieves the same records with supporting code and document excerpts. When only inferred evidence exists, the response says “candidate explanation” and identifies what is observed versus hypothesized. A missing ADR reference reports an unresolved citation. Missing documented rationale may prompt or feed an explicit candidate-generation operation; ordinary retrieval need not invoke a model.

Generation accepts bounded targets such as a module or symbol set and returns reviewable candidates. Review may accept, edit, reject, or link a candidate to an existing ADR. It never rewrites source ADR files implicitly. Whether acceptance requires a committed ADR file is an open product choice.

### Internal Behavior

1. Discover configured ADR locations and recognize supported headings/metadata. Preserve original text and declared status; missing status becomes unknown, not accepted. Treat SDD prose as supporting evidence unless explicitly identified as an ADR.
2. Extract normalized decision records: identity and namespace, title, context, decision, consequences, source-declared lifecycle, origin, review state, evidence references, and content fingerprint. These are proposed fields, not existing model attributes.
3. Resolve explicit code-to-ADR references against repository-scoped IDs. Retain unresolved/ambiguous references. Reuse existing citation semantics while mapping deliberately between GraphIndex node identities and wiki `file:`/`sym:` identities.
4. Candidate generation gathers bounded source excerpts, comments, and relevant documents. Structured output separates observed implementation from hypothesized rationale. Unsupported historical claims, alternatives, and dates remain unknown. Validate that cited spans exist and correspond to the supplied snapshot.
5. Persist candidates with inferred provenance, generation metadata, evidence hashes, and review history. A generation rerun must not overwrite reviewed content. Deduplication uses source scope and evidence identity, not title similarity alone.
6. Retrieval combines decision relevance with explicit symbol links and status. Keep candidates distinct from documented decisions; show superseded decisions for historical queries, with replacement links where available. Acceptance never proves current implementation compliance.
7. Invalidate derived links/candidates when supporting files change or disappear. Mark stale candidates for review; do not automatically revoke human decisions. Preserve independent authored memories.

A proposed relation vocabulary includes `references`, `explains`, `supported_by`, and `supersedes`. The first three exist in GraphIndex; `supersedes` would be new. The spec must settle edge directions and backend persistence rather than assuming these are already available uniformly.

### Edge Cases & Error Handling

- Duplicate ADR numbers across repositories stay namespace-qualified; ambiguous references remain unresolved.
- Long ADRs must be parsed before generic body truncation, with retrievable source spans for decision sections.
- Malformed Markdown or unsupported templates remain ordinary searchable documents with extraction diagnostics.
- Contradictory, rejected, deprecated, and superseded records retain their statuses; ranking must not present them as current authority.
- Missing rationale is not permission to fabricate intent. Candidates may describe a plausible explanation while explicitly leaving historical reasoning unknown.
- Missing model configuration, timeout, budget exhaustion, or invalid output leaves deterministic ingestion/retrieval intact and reports the failed generation scope.
- Rename/delete handling repairs derived references without dropping reviewed records silently. Source freshness and decision lifecycle are separate dimensions.
- Symbol-to-decision retrieval reports applicability evidence; automated architectural compliance or drift detection is deferred.

### Proposed Validation

Use a small repository fixture with accepted and superseded ADRs, duplicate IDs, explicit citations, an undocumented symbol, and a long ADR. Verify exact symbol links, cited “why” results, status visibility, evidence-span validity, idempotent re-ingestion, and source-change invalidation. Mock structured model outputs to test malformed responses, unsupported citations, and preservation of reviewed candidates. Run equivalent storage contract tests for whichever backends the spec includes. No model-quality percentage or performance target is asserted without a benchmark.

## Capabilities

### New Capabilities

- `wiki-adr-ingestion`: structured ADR extraction and explicit citation resolution.
- `wiki-decision-retrieval`: symbol lookup and cited rationale retrieval with status and evidence.
- `wiki-decision-candidates`: bounded inference, distinct labeling, and auditable review.

### Modified Capabilities

- `wikitoolkit-language-plugins`: consume existing scanner evidence; ADR extraction must not require replacing language parsers.
- `pageindex-content-store-and-llm-wiki-foundations`: extend wiki persistence/retrieval contracts for decisions. These names reference existing files under `sdd/specs/`; actual modification scope belongs to the spec.

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| Wiki repository scanning and incremental ingestion | extends | ADR discovery, source spans, source-owned derived records |
| Wiki store models and backend implementations | modifies | Typed lifecycle/evidence persistence requires an additive contract |
| Structural service | extends | Resolve symbols before traversing decision links |
| Wiki search and context packing | extends | Preserve citations and candidate/status labels within token budgets |
| CLI, toolkit, MCP | extends | Expose shared service behavior; exact command names remain unspecified |
| GraphIndex code extractor | reuses concepts | Citation handling exists, but does not resolve ADR documents |
| Client abstraction | depends on | Bounded structured generation; no changes to `clients/base.py` |
| Concept/document authority work | coordinates | Align terminology without making ontology/PgVector mandatory |

## Code Context

All source paths below were read in the working checkout. Imports are statically verified at their call sites, not runtime-tested.

### User-Provided Code

No code snippets were supplied. Original request, verbatim:

> currently we are saving in the LLM wiki plane the code using ast-tree parsers, but we can think on retrieval (extract) using Architecture Decision Records (ADRs) from the codebase?

Q&A response, verbatim:

> 1. both 2. generate a labeled candidate 3. symbol-to-decision lookup or prioritize cited “why” answers 4. feature from dev

### Verified Codebase References

Paths in this table are relative to `packages/ai-parrot/src/parrot/`.

| Path and line | Verified contract or behavior |
|---|---|
| `knowledge/wiki/repo_scan.py:527` | `_category_for(rel_path: str) -> str` maps documentation suffixes to `document`. |
| `knowledge/wiki/repo_scan.py:634` | `build_file_slice(root: Path, rel_path: str, body_max_chars: int = DEFAULT_BODY_MAX_CHARS, max_file_bytes: int = DEFAULT_MAX_FILE_BYTES, symbol_depth: int = 2) -> FileSlice \| None`. |
| `knowledge/wiki/repo_scan.py:709` | Generic body content is truncated before page creation. |
| `knowledge/wiki/store.py:409` | `WikiPageRecord(BaseModel)` has open-string category and origin, attribution, source, and hash fields; no arbitrary metadata field. |
| `knowledge/wiki/structural/service.py:136` | `async def lookup(self, query: str, *, kind: SymbolKind \| None = None, language: str \| None = None, path_prefix: str \| None = None, limit: int = 20) -> SymbolLookupOutput`. |
| `knowledge/wiki/search.py:91` | `async def search(self, query: str, mode: str = "combined", top_k: int = 10, tree_name: Optional[str] = None, weights: Optional[dict[str, float]] = None, include_archived: bool = False) -> list[WikiSearchResult]`. Store-backed dispatch at line 125. |
| `knowledge/wiki/toolkit.py:356` | `async def query(self, wiki_name: str, question: str, file_answer: bool = False, mode: str = "combined") -> dict[str, Any]`; packs search results, then synthesizes snippets. |
| `knowledge/wiki/toolkit.py:882` | `remember` accepts an open-string category and related pages; supports decision memories, not a dedicated ADR lifecycle. |
| `knowledge/wiki/context.py:208` | `pack_results` is the token-budgeted result-packing seam. |
| `knowledge/graphindex/extractors/code.py:99` | `async def extract(self, file_path: str, source: str, *, mtime: Optional[float] = None) -> tuple[list[UniversalNode], list[UniversalEdge]]`. |
| `knowledge/graphindex/extractors/code.py:564` | `_extract_citations` normalizes ADR/RFC references and creates per-file rationale nodes with symbol-to-citation `REFERENCES` edges. |
| `knowledge/graphindex/extractors/llm.py:146` | `async def extract(self, text: str) -> ExtractedGraph`; invokes the supplied client with `output_type=ExtractedGraph` at line 155. Its generic schema is not an ADR schema. |
| `knowledge/graphindex/schema.py:53` | Existing node kinds include `RATIONALE`; edge enum at line 86 includes `REFERENCES`, `EXPLAINS`, `SUPPORTED_BY`, and `CONTRADICTS`. |

Verified imports: `from parrot.knowledge.wiki.store import WikiPageRecord, estimate_tokens` at `knowledge/wiki/repo_scan.py:39`; `SymbolRecord`, `SymbolRef`, and symbol helpers at line 40; `BaseWikiStore` at `knowledge/wiki/structural/service.py:28`.

Existing citation tests: `packages/ai-parrot/tests/knowledge/graphindex/test_graphify_parity.py:109` covers citation nodes, deduplication, edges, absent references, and normalization. Inspected, not executed for this documentation task.

### Does NOT Exist (Anti-Hallucination)

- No dedicated ADR parser/lifecycle or ADR-to-symbol retrieval implementation was found by ADR/architecture-decision searches within `packages/ai-parrot/src/parrot/knowledge/wiki/`.
- `WikiPageRecord.metadata` and dedicated ADR status fields are absent from the inspected model.
- `EdgeKind.SUPERSEDES` is absent from the inspected GraphIndex enum.
- A GraphIndex citation node is not the resolved ADR document and does not establish its accepted status.
- No conventional `docs/adr/`, `docs/adrs/`, or `docs/decisions/` corpus was found in the inspected tracked-path listing. Real ADR locations/templates must be supplied or configured; test citation strings do not establish that corpus exists.

## Parallelism Assessment

- **Internal parallelism:** After identity, lifecycle, and evidence contracts stabilize, ingestion and retrieval/generation can be developed separately. Schema changes and backend migrations should have one owner.
- **Cross-feature independence:** Shared seams include `repo_scan.py`, `store.py`, `search.py`, `cli.py`, and structural services. Coordinate with structural-plane and wiki-store work. `sdd/specs/concept-document-authority.spec.md` also covers authority semantics, but concerns ontology traversal; its presence does not prove an active concurrent implementation.
- **Recommended isolation:** per-spec.
- **Rationale:** Cross-cutting schema and lifecycle changes favor one feature worktree with sequenced integration. No implementation branch is needed for this brainstorm-only change.

## Open Questions

- [x] Flow and base branch — *Owner: Jesús*: feature from `dev`.
- [x] Existing ADRs or inference — *Owner: Jesús*: both.
- [x] Missing documented rationale — *Owner: Jesús*: generate a labeled candidate.
- [x] Retrieval use cases — *Owner: Jesús*: symbol-to-decision lookup or cited “why” answers; both are included in exploration.
- [ ] Which real ADR directories/templates and sample repository should define the ingestion fixtures? — *Owner: Jesús*
- [ ] Which retrieval path is the first delivery priority if sequencing is necessary: symbol lookup or cited “why” answers? — *Owner: Jesús*
- [ ] Where are candidates reviewed, who may accept them, and must acceptance produce a committed ADR file? — *Owner: Jesús*
- [ ] What default generation scope, model budget, and input sources are appropriate; should Git history be included in v1? — *Owner: Jesús / spec author*
- [ ] Which persistence representation, backend parity scope, and rename/supersession identity rules will the first release guarantee? — *Owner: spec author*
