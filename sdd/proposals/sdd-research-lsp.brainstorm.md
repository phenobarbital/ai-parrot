---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Selective LSP evidence for SDD research and change verification

**Date**: 2026-09-19
**Author**: Codex with Jesús Lara
**Status**: exploration
**Recommended Option**: B

## Problem Statement

SDD agents need to discover relevant code, understand architectural constraints, resolve the precise symbols affected by a change, and catch mistakes before another review cycle. Wiki documents and AST-derived symbols already address discovery and structure. ADR ingestion and decision retrieval are being explored separately. LSP could improve semantic navigation and feedback on edited code, but duplicating existing lookups could increase both context and latency.

The question is the incremental value of LSP over this repository's existing retrieval stack, measured across a completed task. Fewer lookups are useful only when the agent still finds the necessary evidence and produces correct changes.

### Evidence behind the savings claim

The exact 13% cost, 12% token, and 24% API-call reductions appear in Marmelab's August 27, 2026 report. Its large CRM transformation compared a baseline without navigation help against LSP: cost $47.70 to $41.68, tokens 95.72M to 84.30M, and API calls 1,562 to 1,190. The report covers two scenarios but attributes those figures to the large transformation; it does not establish a general effect against a wiki-plus-AST baseline. Treat the percentages as externally reported observations, not acceptance criteria or expected additive savings. [Primary report](https://marmelab.com/blog/2026/08/27/which-agent-based-plugin-should-you-use-in-2026.html).

### Discovery Q&A

- **Round 1 asked:** feature/base branch; SDD versus runtime consumers; primary outcome; claim source and representative workflow. No answers received before drafting. Apply the skill's feature/dev defaults. SDD research/coding/review is a provisional recommendation, not a confirmed runtime integration requirement. The claim source was independently located.
- **Round 2 asked:** Python-only versus broader languages or diagnostics-only; benchmark pilot versus immediate shared service; correctness versus savings priorities. No answers received before drafting. Recommend Python-only, optional navigation plus diagnostics, with a benchmark gate. These choices remain open for review.
- This document explores alternatives; unanswered product choices do not authorize implementation or new dependencies.

## Constraints & Requirements

- Preserve wiki-first discovery and the offline AST plane. LSP must be optional and lazily started, never a prerequisite for wiki builds or ordinary document queries.
- Keep architectural rationale distinct from inferred code behavior. ADR candidate generation/review remains the separate `sdd-spec-wiki-adr` exploration; LSP cannot establish historical intent.
- Python-first is proposed. The uv workspace and PEP 420 namespace packages require explicit source roots and interpreter configuration. Include satellite imports in evaluation.
- Use async I/O, Pydantic v2 output models, existing toolkit lifecycle conventions, and bounded results. No implementation or package installation in this brainstorm.
- Scope processes and evidence to the actual worktree. Include file content/version and analysis configuration in freshness decisions; branch name alone is insufficient.
- Navigation and diagnostics are advisory evidence. Tests, lint, and review remain the correctness gates. A missing or stale diagnostic response must never mean a clean check.
- Avoid automatic rename, code-action application, and server-requested workspace edits in the pilot. Use configured server commands without shell interpolation or automatic installation.
- Count total model usage, including cache reads/writes and retries, rather than interpreting a reduction in tool calls as the same reduction in API calls.

---

## Options Explored

### Option A: Tighten wiki/AST retrieval and routing without LSP

Use existing symbol lookup, outlines, and blast-radius evidence more consistently. Retrieve short source spans, deduplicate evidence, and stop searching once an explicit question is answered. Instrument repeated reads and reviewer corrections.

**Pros:** Low operational cost; works without language-server environments; establishes a strong control condition and may capture much of the benefit already.

**Cons:** Does not add type-aware reference resolution or live semantic diagnostics; dynamic dispatch and ambiguous names still need investigation.

**Effort:** Low.

| Libraries / Tools | Purpose | Dependency status |
|---|---|---|
| Existing wiki, AST scanners, `rg` | Bounded discovery and fallback | Already used; optional scanner extras declared |
| Existing context packing | Deduplicate compact evidence | Available; not an absolute token ceiling for an oversized first stub |

**Existing Code to Reuse:** `packages/ai-parrot/src/parrot/knowledge/wiki/structural/toolkit.py:101`; `packages/ai-parrot/src/parrot/knowledge/wiki/context.py:208`.

### Option B: Selective LSP navigation and verification pilot

Start from Option A's retrieval discipline. Add LSP only for questions requiring semantic resolution: the definition behind an import or receiver, references to a selected symbol, and diagnostics after an edit. Return compact evidence with provenance and freshness; fetch source ranges only when needed. Measure before building a broad shared service.

**Pros:** Directly targets gaps in AST retrieval; may prevent missed callers and repair cycles; retains cheap discovery and graceful degradation.

**Cons:** Medium lifecycle and protocol complexity; setup and warm-up can outweigh savings; precise results depend on environment and server capabilities. References are not guaranteed complete for dynamic Python behavior.

**Effort:** Medium for one server and a bounded pilot; a generalized multi-language service would be High.

| Libraries / Tools | Purpose | Dependency status |
|---|---|---|
| Pyright language server | Candidate Python semantic backend | Not declared in inspected manifests; proposed external executable, subject to approval before introduction |
| Python `asyncio`, existing Pydantic/toolkit machinery | Process ownership, typed output, lifecycle | Existing runtime/dependencies |
| LSP client adapter | Initialization, requests, synchronization, bounded responses | No existing adapter found; transport/library selection remains open |

**Existing Code to Reuse:** `packages/ai-parrot/src/parrot/tools/toolkit.py:390`; `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py:204`; `packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py:136`.

Pyright supports execution-environment and virtual-environment configuration, making it a candidate for this workspace; actual import resolution must be tested. This is not a claim that it is already installed or configured. [Pyright configuration](https://github.com/microsoft/pyright/blob/main/docs/configuration.md).

### Option C: LSP as the primary retrieval service across languages

Maintain language servers for each active worktree and route most navigation through a shared service, exposing definitions, references, symbols, hierarchies, and diagnostics. Keep the wiki for documents and rationale.

**Pros:** A common semantic interface and reusable live sessions across research, coding, and review.

**Cons:** High deployment and testing cost; repeats existing structural discovery; server capabilities vary; supporting Python, TypeScript/Svelte, Rust, and Cython is not one integration. An LSP reference list is not a complete runtime call graph. This revives costs deliberately avoided by the earlier AST brainstorm.

**Effort:** High.

| Libraries / Tools | Purpose | Dependency status |
|---|---|---|
| Per-language server executables and an LSP client | Semantic operations | New dependencies; inventory and selection required |
| Existing MCP/toolkit surface | Agent-facing access | Reuse possible; MCP and LSP still need a deliberate adapter |

**Existing Code to Reuse:** `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py:91`; earlier boundary in `sdd/proposals/ast-grep-for-wikitoolkit.brainstorm.md:285`.

### Option D: Change-triggered evidence packets

Less obvious approach: keep research on wiki/AST and invoke a bounded semantic pass only at change checkpoints. A changed-symbol packet contains relevant references, before/after diagnostics, and source hashes. Coding/review agents consume one packet instead of repeatedly choosing individual lookup tools.

**Pros:** Controls tool-schema and interaction overhead; targets rework directly; useful where agents underuse navigation tools.

**Cons:** Does not help initial semantic localization; may analyze unused evidence; diagnostics settling and packet invalidation remain necessary. Batch work does not automatically reduce billed model tokens.

**Effort:** Medium.

| Libraries / Tools | Purpose | Dependency status |
|---|---|---|
| Same optional Python server as B | Checkpoint analysis | Not currently declared |
| Existing structural impact and context packing | Select and render packet evidence | Available; requires explicit result mapping |

**Existing Code to Reuse:** `packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py:287`; `packages/ai-parrot/src/parrot/knowledge/wiki/context.py:208`.

---

## Recommendation

**Option B**, delivered as a measured pilot with Option A as its control. LSP is most promising for semantic questions that the structural plane cannot settle and for earlier feedback after edits. Avoid running wiki, AST, and LSP for every question. Option D is a useful follow-up if checkpoint verification accounts for most of the measured benefit.

The prior AST brainstorm rejected replacing indexing with LSP. This proposal preserves that boundary: persistent structural discovery remains separate from transient, environment-dependent semantic evidence. ADR exploration can proceed independently.

| Agent question | Preferred evidence |
|---|---|
| Which subsystem implements this concept? | Wiki/document discovery, then AST candidates |
| Why was it designed this way? | Documented decisions; future ADR retrieval with lifecycle/provenance |
| Which definition does this particular expression refer to? | LSP at a verified source position |
| Which statically discoverable references need checking? | LSP references, supplemented by structural and text evidence |
| Did this edit introduce detectable type/import errors? | Fresh diagnostic delta |
| Does the behavior satisfy the requirement? | Tests and review |

### Experiment and decision gate

1. Select 12 representative tasks: four localization/reference investigations, four cross-file changes, and four bug fixes with review. Include namespace imports, duplicate symbol names, dynamic registration, stale files, and an unavailable-server case. Prepare expected evidence and behavioral acceptance checks independently of the tool used.
2. Compare the current workflow, A (disciplined wiki/AST), B-navigation, B-diagnostics, and B-combined. This separates routing improvements from LSP effects. Initially run three paired repetitions per task/arm; extend if results are noisy. This is a pilot, not a statistical power claim.
3. Pin repository starting commit, model/version/settings, prompts except necessary tool instructions, dependencies, and task acceptance checks. Use fresh working states and counterbalanced order. Report cold-start and warm-session results separately. Keep ADR availability identical across arms; evaluate it as a separate factor when implemented.
4. Record uncached input, cache-read/cache-write input where exposed, output/reasoning usage as reported, actual or reconstructable model cost with a pinned price basis, model API requests including retries, tool calls by type, LSP requests, wall time, server CPU/RSS/startup, and result size. Do not add cache usage twice if a provider's total already includes it.
5. Record evidence precision/recall on curated fixtures, accepted-task rate, first-pass acceptance, missed-reference defects, reviewer correction cycles, repeated file reads, and repeated edits of the same region. Measure correction count separately from the number of API calls.
6. Report per-task paired differences and distributions, not just pooled totals. Charge failed attempts and retries: cohort model cost per successful task = all attempt costs / accepted tasks, alongside completion rate. Report local compute separately unless an agreed monetary basis exists.
7. Proposed gate for discussion: at least 10% lower model cost per successful task against A, with no observed acceptance-rate reduction or new correctness failures in the pilot, plus no more than 10% median wall-time regression. Inspect tail latency and cold-start outliers before deciding. A 20% reduction in correction cycles with cost within 5% of A may justify a correctness-led rollout if the owner explicitly accepts that tradeoff. These are proposed thresholds, not measured results or guarantees.

No experiment was executed for this brainstorm. If the benefit disappears against A, retain A and defer a service. If diagnostics dominate, prefer D. If navigation gains survive overhead, specify B for a broader trial.

---

## Feature Description

### User-Facing Behavior

The agent begins with wiki discovery and a bounded structural lookup. If it still needs semantic evidence, it requests a definition or references for an unambiguous file position. Results identify the backend, worktree, source version, locations, truncation, and unavailable/partial status. A rename-impact investigation also searches string-based registries and configuration; a semantic reference result alone cannot certify all callers.

After a meaningful edit checkpoint, the agent receives newly introduced/resolved diagnostics relative to a baseline plus the scope actually analyzed. Relevant tests and lint still run. The same optional tools must be visible to the coding/review seats being measured; merely configuring them for an outer research orchestrator is insufficient.

### Internal Behavior

1. Use wiki/AST to choose a target. Start LSP only when the task requires semantic evidence; do not add another LLM router just to select a tool.
2. Negotiate capabilities and position encoding. Translate source lines and columns explicitly; wiki records provide line spans, not a reliable LSP identifier column. Normalize both `Location` and `LocationLink` results.
3. Own a lazy session per canonical worktree, language, server version, and environment/configuration. Preserve the actual worktree root when sharing an interpreter. Do not reuse one mutable document session across divergent worktrees.
4. Synchronize document open/change/save/close state and serialize conflicting edits. Invalidate relevant cached evidence on source/configuration/dependency changes; workspace references need broader invalidation than the target file alone.
5. Cap result count, bytes, and rendered context; deduplicate URI/range evidence and expose truncation. Request a narrow source excerpt only when needed. Preserve provenance instead of promoting transient observations into permanent architectural facts.
6. Use a bounded diagnostic wait. Record document versions when supplied; reject older results. If a server omits versions and freshness cannot be established, return uncertain/stale rather than a clean outcome. Push diagnostics replace the previous set, including an empty set that clears prior findings. [LSP diagnostic contract](https://raw.githubusercontent.com/microsoft/language-server-protocol/gh-pages/_specifications/lsp/3.17/language/publishDiagnostics.md).
7. Time out, cancel, clean up partially started processes, and fall back once to wiki/AST or ordinary checks. Keep transport logging off protocol stdout. No automatic server installation or workspace mutation.

LSP defines navigation and capability negotiation, but method support must be checked for the selected server; call hierarchy, implementations, and pull diagnostics are not assumed universal. [Official LSP specification source](https://github.com/microsoft/language-server-protocol/blob/gh-pages/_specifications/lsp/3.17/specification.md).

### Edge Cases & Error Handling

- **Python dynamic behavior:** decorators, monkeypatching, registries, reflection, string imports, and generated code can escape static resolution. Retain `rg`, source inspection, and tests.
- **Incomplete environment:** unresolved imports may indicate configuration problems. Surface environment health, not a flood of apparent edit regressions.
- **Concurrent edits or stale wiki positions:** verify content identity, re-resolve positions, or return a conflict; never silently query an outdated coordinate.
- **Untracked/unsaved files:** either synchronize the exact content explicitly or limit the pilot to on-disk checkpoints and declare that limitation.
- **Large reference sets:** paginate/cap and mark partial coverage; do not imply completeness from a truncated list.
- **External paths:** confine local reads to allowed roots; dependency locations outside the worktree require an explicit readable-root policy. Federated wiki IDs are not automatically local filesystem paths.
- **Unsupported language, timeout, crash:** preserve a reason code and fallback path. No server/no diagnostics is distinct from validated/no findings.
- **Existing diagnostic debt:** compare against baseline, including affected callers where supported; avoid reporting every pre-existing warning as new. Document limited analysis scope.

---

## Capabilities

### New Capabilities

- `sdd-semantic-navigation`: optional definition/reference evidence at verified positions.
- `sdd-change-diagnostics`: freshness-aware diagnostic deltas at edit checkpoints.
- `sdd-retrieval-evaluation`: paired measurement of cost, latency, evidence quality, and rework.

### Modified Capabilities

- `ast-grep-for-wikitoolkit`: consume existing symbol evidence as candidate discovery; no replacement of its offline contract.
- Future SDD research/coding/review tool routing would gain an optional semantic path; exact host integration is unresolved.
- `sdd-spec-wiki-adr` remains a separate brainstorm, not an implemented prerequisite or a modified shipped capability.

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| Wiki structural service | consumes | Existing IDs, locations, and structural evidence; preserve behavior |
| Wiki context packing | reuses concepts | Compact rendering and deduplication; enforce pilot caps separately |
| SDD research/coding/review host | extends | Tool visibility, bounded routing, instrumentation; exact host pending |
| Optional concrete toolkit in `parrot_tools` | proposed addition | Own server lifecycle if a reusable adapter is chosen |
| Wiki MCP registration | optional extension | Existing exposure seam; avoid forcing LSP into wiki core |
| Worktree configuration | depends on | Correct source roots/interpreter and resource isolation |
| ADR exploration | coordinates | Keep rationale provenance separate; no runtime dependency |
| CI/checks | adds optional evaluation | Existing tests/lint remain authoritative; no mandatory server for ordinary users |

No API breaking changes or dependency edits are proposed for the brainstorm. Repository manifests contain AST/tree-sitter support, but no declared Pyright, pylsp, pygls, lsprotocol, or Jedi dependency in the inspected root/workspace manifests. The UI declares Svelte and TypeScript; that does not establish an installed LSP server. Decide adapter ownership and approve dependencies during specification, before implementation.

---

## Code Context

### User-Provided Code

No code snippets supplied. Original notes preserved verbatim:

> using Language Server Protocol (LSP) can consistenly cut costs by 13%, tokens by 12%, and API calls by 24%. Using the current combination of Wiki codebase (with ast-parsed code + ADR-based code retrieval - in exploration - ), this brainstorm is to know if adding a LSP can be useful to optimize the code retrieval, LSP lookups, confirming code changes, etc, to me, Fewer, sharper lookups also meant less rework, but I need to know your suggestion over this brainstorm.

### Verified Codebase References

Wiki queried before source inspection; inspected the `CodeStructuralToolkit` symbol page. Paths below were then read directly in the working tree on `dev`.

#### Classes & Signatures

| Location | Verified contract / implication |
|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/structural/toolkit.py:26` | `class CodeStructuralToolkit(AbstractToolkit)`; `tool_prefix: str = "code"` at line 42 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/structural/toolkit.py:101` | `async def symbol_lookup(self, query: str, kind: str \| None = None, language: str \| None = None, path_prefix: str \| None = None, limit: int = 20) -> dict[str, Any]` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py:136` | `async def lookup(self, query: str, *, kind: SymbolKind \| None = None, language: str \| None = None, path_prefix: str \| None = None, limit: int = 20) -> SymbolLookupOutput`; hashes/repairs hit files before repeating search |
| `packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py:218` | `async def outline(self, target: str, *, depth: int = 2, include_source: bool = False) -> CodeOutlineOutput`; optional bounded source excerpt |
| `packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py:287` | `async def blast_radius(self, symbol: str, *, relations: list[str] \| None = None, depth: int = 2, include_inferred: bool = True, include_tests: bool = True) -> BlastRadiusOutput`; reverse graph traversal, not an LSP references query |
| `packages/ai-parrot/src/parrot/knowledge/wiki/context.py:208` | `def pack_results(results: Iterable[Any], budget_tokens: int = DEFAULT_BUDGET_TOKENS) -> PackedContext`; deduplicates IDs; oversized first result can exceed budget at line 245 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py:91` | `def create_wiki_mcp_server(root: Path) -> StdioMCPServer`; structural tools appended at line 209 |
| `packages/ai-parrot/src/parrot/tools/toolkit.py:390` | `async def _open(self) -> None`; partial startup cleanup belongs to the override; `_close` at 406 and `_ensure_open` at 419 provide lifecycle hooks |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py:464` | Local `_wiki_ctx() -> str` invokes `self._wiki_search.build_research_context(wiki_query)`; wiki/graph/partner contexts gathered at 491 and appended at 495. This is prompt context, not an existing LSP dispatcher |

#### Verified Imports

Source-level imports verified; no runtime import smoke test claimed:

- `from parrot.knowledge.wiki.structural.service import StructuralService` — `packages/ai-parrot/src/parrot/knowledge/wiki/structural/toolkit.py:21`.
- `from parrot.tools.toolkit import AbstractToolkit` — `packages/ai-parrot/src/parrot/knowledge/wiki/structural/toolkit.py:23`.
- `from pydantic import BaseModel, Field` — `packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py:19`.

#### Key Attributes & Constants

- `_BLAST_RADIUS_NODE_CAP = 500` — `packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py:41`.
- `SymbolHit` stores signature, doc, line spans and `stale`, but no LSP document version or identifier column — `packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py:48`.
- `_record_to_hit` caps signature/doc at 200/240 characters — `packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py:107`.
- `ast-grep-py>=0.45` is in `wiki-structural` — `packages/ai-parrot/pyproject.toml:316`; tree-sitter extras at line 301.
- Prior LSP-as-indexing option was rejected — `sdd/proposals/ast-grep-for-wikitoolkit.brainstorm.md:285`. Its stronger language about accuracy is a historical proposal, not a correctness guarantee adopted here.
- ADR artifact explicitly has `Status: exploration` — `sdd/proposals/sdd-spec-wiki-adr.brainstorm.md:13`.

### Does NOT Exist (Anti-Hallucination)

- No LSP client implementation or declared language-server dependency found by targeted searches for `LSP`, `LanguageServer`, `language_server`, `pyright`, `pylsp`, `lsprotocol`, and `pygls` in package Python files/manifests. Incidental copyright matches are not dependencies. This does not audit globally installed executables.
- No dedicated ADR lifecycle/retrieval implementation found in the inspected wiki source search; an ADR brainstorm is not proof of shipped behavior.
- No LSP-backed freshness/diagnostic contract exists in the inspected structural output models.
- No benchmark against AI-Parrot's wiki-plus-AST workflow was run or located in this investigation.
- `textDocument/references` is not a complete runtime dependency graph; clean diagnostics are not proof that a change is correct.

---

## Parallelism Assessment

- **Internal parallelism:** Once the evidence/session contract is agreed, protocol fixtures, benchmark tasks, and host wiring can be developed separately. Transport lifecycle and freshness logic should have one owner.
- **Cross-feature independence:** Coordinate with ADR exploration and wiki structural work around IDs, provenance, and output budgets. Shared hotspots include wiki context/MCP registration and SDD research prompt assembly. Avoid unrelated edits to scanners/store schemas.
- **Recommended isolation:** per-spec.
- **Rationale:** One worktree keeps session configuration, tool contracts, and evaluation reproducible; independent ADR work can proceed without dependency on LSP.

## Open Questions

- [x] Flow defaults — *Owner: Codex*: `type: feature`, `base_branch: dev`, applied per skill defaults; no explicit user confirmation received.
- [x] Provenance of percentages — *Owner: Codex*: located Marmelab's primary report; workload-specific observations, not local measurements.
- [x] Which host and seats are first consumers — *Owner: Jesús* (2026-09-19): SDD CLI research/coding/review seats are the first consumers. In-process dev-loop agents are not wired in during this pilot.
- [x] Is Python-only navigation plus diagnostics the approved initial scope — *Owner: Jesús* (2026-09-19): Yes, Python-only, both navigation and diagnostics, matching Option B as recommended.
- [x] Which representative tasks and cost/quality/latency thresholds should govern the pilot — *Owner: Jesús* (2026-09-19): Accepted the brainstorm's proposal as-is — the 12-task design (§ Experiment and decision gate, step 1), 3 paired repetitions per task/arm, and the proposed gate (≥10% lower model cost per successful task vs. A, no acceptance-rate/correctness regression, ≤10% median wall-time regression).
- [x] Which server executable/version and client adapter should be approved, and who owns environment provisioning — *Owner: Jesús* (2026-09-19): Pyright approved as the pilot candidate server. Provisioning ownership and exact version pin remain for specification time.
- [x] Should access reuse an existing host LSP session, use an optional standalone toolkit, or extend wiki MCP — *Owner: Jesús* (2026-09-19): Standalone optional toolkit in `parrot_tools`, owning its own server lifecycle, kept out of wiki core.
- [x] Are on-disk checkpoints sufficient, and what freshness, timeout, and memory budgets are acceptable — *Owner: Jesús* (2026-09-19): On-disk checkpoints only for the pilot; unsaved/in-memory edit synchronization is out of scope and the limitation is declared explicitly (see Edge Cases & Error Handling).
