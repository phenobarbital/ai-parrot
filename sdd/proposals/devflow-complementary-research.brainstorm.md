---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Complementary (Collaborative) Research for the Dev Flow

**Date**: 2026-08-31
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

The proactive dev-flow (`packages/ai-parrot/src/parrot/flows/dev_flow/`) turns a
natural-language development request into a committed SDD document through a
**single-model research seat**. `IdeationNode` (`nodes/ideation.py:91`) dispatches
one `sdd-ideation` subagent on `claude-sonnet-4-6` (`ideation.py:338`), and that
one agent's reading of the codebase becomes the brainstorm or proposal that every
downstream phase — spec, tasks, worktree, implementation — inherits. The same
shape holds for the ops flow's `ResearchNode` (`dev_loop/nodes/research.py:195`),
which triages a bug on a single Claude Code seat before scaffolding the spec.

That single seat is the narrowest point in the whole pipeline, and it is the one
place where a blind spot is most expensive: an option never considered at ideation
time does not reappear at task time. Everything downstream faithfully implements
whatever the one researcher happened to see.

The repo has already solved the analogous problem one phase later, at review time.
`ParallelPerspectiveReviewDispatcher` (`dev_loop/code_review.py:341`) runs a
primary write-enabled reviewer and a read-only adversary concurrently via
`asyncio.gather` (`code_review.py:392`) and merges their verdicts
(`_merge_verdicts`, `code_review.py:462`), with the adversarial seat selectable
over `{codex, nova}` (`catalog.py:60`, `resolve_adversarial_backend`,
`catalog.py:63`). Two models, two perspectives, one merged artifact.

**Research has no equivalent.** And the review machinery is deliberately
*adversarial* — `CodexAdversarialReviewDispatcher` and
`NovaAdversarialReviewDispatcher` exist to *challenge*. Research does not want a
challenger; it wants a **collaborator**: a second researcher that investigates the
same request from its own angle, and whose findings the primary researcher then
*reads and expands upon*. The value is additive coverage and cross-pollination, not
a contest with a winner.

There is also a standing architectural decision to revisit. FEAT-405
(`sdd/specs/novaclient-dev-loop.spec.md`) explicitly named "a pluggable research
seat" a **non-goal**, reasoning that "`ResearchNode` stays hard-wired to
`ClaudeCodeDispatcher` + `/sdd-spec` + `/sdd-task`. A Bedrock API seat cannot
invoke slash commands, so the generalization would ship an option that could not
do the job." That reasoning is sound *for replacing* the research seat — and
irrelevant *for adding a collaborator beside it*. A second researcher never needs
to run a slash command, never writes the SDD document, and never creates a
worktree; the Claude seat keeps every one of those responsibilities. This feature
threads that needle rather than reversing the decision.

**Who is affected**: developers and agents driving the dev-flow (better-grounded
proposals, fewer missed options surfacing late as rework), and platform operators
who want an AWS-governed model contributing real work under one IAM boundary and
one bill.

## Constraints & Requirements

- **Pure addition.** An operator who configures nothing must see byte-identical
  behavior to today — the same `[R3]` guarantee FEAT-405 held itself to
  (`catalog.py:44-54`). Complementary research is opt-in.
- **Soft-degrade, always.** If the partner fails, times out, or returns unusable
  output, the run logs a warning, records the failure in telemetry, and proceeds
  with single-agent ideation. The partner can never break a run that works today.
- **Claude remains the sole author of the SDD document.** The partner produces
  findings; it never writes, commits, or edits `sdd/**`. Only the `sdd-ideation`
  seat (write-capable, `permission_mode="acceptEdits"`, `ideation.py:329`) owns the
  artifact. This preserves the FEAT-405 reasoning intact.
- **The partner is read-only by construction**, not by policy — no write tool is
  ever registered on it, mirroring how `NovaAdversarialReviewDispatcher` is
  "read-only BY CONSTRUCTION: no tools are ever passed to the model"
  (`dispatchers/nova.py:240`).
- **The partner backend is configurable**, starting with Amazon Nova 2 on Bedrock.
  Follow the established selector shape: a module-level default constant, a
  choices tuple, and a `resolve_*` function (`catalog.py:54/60/63`).
- **Extended thinking must survive the tool loop.** Nova 2's value here is its
  reasoning; the implementation must not corrupt `reasoningContent` signatures
  across tool rounds.
- **Bounded cost.** The partner runs once per ideation (round 1 only), with an
  explicit token/round/time ceiling.
- **One mechanism, both seats.** `IdeationNode` and `ResearchNode` must consume the
  same collaborator abstraction — no forked copy.
- **Provenance is auditable.** It must be possible to determine after the fact what
  the partner actually contributed.
- **No blocking I/O**, `aiohttp`-only, Google-style docstrings, strict type hints,
  Pydantic contracts throughout (`CLAUDE.md` non-negotiables).

### Decisions already taken (interactive discovery)

| # | Decision | Rationale |
|---|---|---|
| D1 | Applies to **both** `IdeationNode` and `ResearchNode` via one shared mechanism | Avoids a forked copy; the ops flow benefits identically |
| D2 | Partner gets a **real read-only repo tool loop**, not a static context pack | It must be able to follow its own curiosity, or it is just a second opinion on Claude's framing |
| D3 | **Parallel, then Claude merges** (`asyncio.gather`, then findings feed the `sdd-ideation` dispatch) | Partner is not anchored by Claude's framing; better wall-clock than sequential |
| D4 | **Soft-degrade to Claude-only** on partner failure | Pure-addition guarantee |
| D5 | Mechanism is the **Converse tool loop on `NovaClient`**, not bedrock-mantle | Keeps Nova 2 *with* thinking; see the finding below |
| D6 | Tool surface: cwd-confined `read_file`/`list_files` + **graph-backed `search_code`** + local git history + web search | Four complementary grounding axes |
| D7 | Findings persist as a separate `sdd/proposals/<slug>.research.md` **and** the merged document attributes insights by source | Provenance auditable; you can tell whether collaboration actually happened |
| D8 | Partner runs on **round 1 only**, not on HITL resume rounds | Bounded cost; Claude already holds the findings on resume |
| D9 | Code search is **graph/FTS5-backed over the existing wiki plane**, not `grep` | The AST + tree-sitter code graph already exists in-repo; see the finding below |

### The finding that reshaped the design

The initial framing was "give Nova a repo tool loop like `NovaCodeDispatcher`."
That combination does not exist and cannot be built as stated:

- `NovaCodeDispatcher` (`dispatchers/nova.py:61`) inherits `LLMCodeDispatcher`'s
  **OpenAI-chat-completions-shaped** loop and routes through the bedrock-mantle
  endpoint.
- Per `nova.py`'s own module docstring and `catalog.py:246-251`, **neither Nova nor
  Anthropic models on Bedrock expose Chat Completions.** Mantle serves the
  agent-native third-party models (MiniMax M2.5, Kimi K2.5, GLM-5). That is
  precisely *why* `NovaAdversarialReviewDispatcher` is a no-tools Converse call.
- So "Nova 2 + mantle tool loop" is not a real combination. Routing via mantle
  would mean abandoning Nova 2 and losing Converse extended thinking.

The better path was already in the tree, unused for this purpose:
**`BedrockConverseBase.ask()` (`clients/bedrock.py:699`) already runs a complete
multi-round Converse `toolUse`/`toolResult` agentic loop.** It executes registered
tools through `AbstractClient._execute_tool` (`clients/base.py:1454`), it
**preserves the assistant turn verbatim so `reasoningContent` blocks and their
signatures travel through unmodified across rounds** (`bedrock.py:986-988`), and
it already emits per-round `ClientRoundEvent` telemetry (FEAT-404, landed —
`bedrock.py:971-981`). Extended thinking is enabled by the `thinking_budget`
parameter (`bedrock.py:715`, applied at `bedrock.py:831-835`).

So Nova 2 + extended thinking + a genuine multi-round read-only repo tool loop is
reachable **today**, with no new agentic loop: register a read-only toolkit on a
`NovaClient` and call `ask(use_tools=True, thinking_budget=N)`. The new work is the
*toolkit* and the *collaborator seam* — not the loop. That is a materially smaller
and lower-risk feature than the original framing implied.

### The second finding: the AST code graph already exists (D9)

The follow-up question — *can the toolkit AST-parse a fetched repository and build a
graph index for code search, instead of grepping, the way wikitoolkit works?* — has
a better answer than "possible". **It is already built, shipped, and running in this
repo**, and the toolkit should consume it rather than reimplement it.

Verified against the live plane (`wikitoolkit status`, 2026-08-31):

```
Wiki      : parrot (sqlite)
Root      : /home/jesuslara/proyectos/ai-parrot
Storage   : /home/jesuslara/proyectos/ai-parrot/.parrot/wiki      (548 MB)
Plane     : 11518 pages, 18844 edges, ~24.9M tokens
Categories: {module: 5139, document: 4587, overview: 1011, config: 716, ...}
Languages : {'python': 'ast', 'php': 'tree-sitter', 'javascript': 'tree-sitter',
             'rust': 'tree-sitter', 'perl': 'tree-sitter'}
Sources   : 10442 tracked, 229 stale
```

The pieces that make this a wiring job rather than a build job:

- **A pluggable per-language scanner framework.** `LanguageScanner` ABC
  (`knowledge/wiki/languages/base.py`) with `outline()`, `build_reference_index()`,
  and `resolve_import()`. `PythonScanner` (`languages/python.py:30`) uses the stdlib
  `ast` module directly (`ast.parse` at `:49`, walking `ClassDef`/`FunctionDef`/
  `AsyncFunctionDef`/`Import`/`ImportFrom`) to emit a summary, an API outline, and
  raw import specifiers. PHP, JavaScript/TypeScript, Rust and Perl do the same via
  tree-sitter (`languages/treesitter.py`). Explicitly **deterministic and offline**
  (FEAT-394) — no LLM in the indexing path.
- **A repo scanner that turns that into a graph.** `scan_repository()`
  (`repo_scan.py:776`) discovers files through `git ls-files` (`_git_ls_files:398`,
  so `.gitignore` is honored for free), builds `file:` and directory pages
  (`build_file_slice:556`, `build_dir_pages:645`), and derives cross-file
  `references` edges from resolved imports (`build_import_edges:718`).
- **A search layer that is exactly the described "graph-based search".**
  `WikiCombinedSearch` (`wiki/search.py:32`) over an **FTS5/BM25** virtual table
  (`store.py:117` `CREATE VIRTUAL TABLE ... USING fts5`), with an optional cosine
  **vector** leg (`search_fts:1147` / `search_vector:1195`), combined and
  token-budget-packed by `pack_results`.
- **Incremental rebuilds, already automated.** Sources are tracked with staleness
  (10442 tracked / 229 stale above); `build --force` is the full rebuild. A
  git post-commit hook already runs `upsert --changed` into the SQLite plane, so
  the index tracks commits without anyone thinking about it.
- **Agent-facing tools that already exist** — see the correction in Does NOT Exist.

**Measured, honestly.** A warm CLI query returns 12 ranked, deduplicated,
token-costed results in **~592 tokens / 1.79 s**; the equivalent `grep -rn` returns
**23 raw hits in 0.07 s**. Grep wins raw wall-clock on a single exact symbol, and
that gap should not be oversold — but it is the wrong cost function three ways:

1. **~1.7 s of the 1.79 s is CLI cold start** (Python interpreter + tree-sitter
   grammar loading, visible in the debug trace). In-process — which is exactly how
   the toolkit would use it — a query is an SQLite FTS5 lookup against an already
   open connection.
2. **Tokens, not seconds, are the agent's budget.** 592 ranked tokens versus 23 raw
   `path:line:` hits that the model must then read files to interpret.
3. **Grep's 23 hits included duplicates from `packages/ai-parrot/build/lib.linux-x86_64-cpython-311/`** —
   stale build artifacts. The plane excludes them via `git ls-files`. Noise
   suppression is a correctness property, not a speed one.

**The honest limitation**: `DevLoopWikiSearch` passes **no embedder**, so the plane
is queried lexically today. A genuinely conceptual query ("how does a review seat
degrade when the backend has an outage") scored **0.06 / 0.00** — BM25 cannot do
concept matching. Symbol, module, and topic queries are excellent; pure-concept
recall needs the vector leg enabled (Q10).

**The worktree question this raises** is the one real engineering decision, and the
config already answers it: `project.py:74` states that `storage_dir` **"may be
absolute, so two repositories can share one"** plane. A feature worktree should
therefore point at the main checkout's existing plane rather than build a fresh
548 MB one per worktree (Q9).

---

## Options Explored

### Option A: `ResearchPartner` collaborator + a read-only repo toolkit

A new, small abstraction — a **research partner** — deliberately parallel to the
existing review-dispatcher family but *collaborative* rather than adversarial.

Three pieces:

1. **`ReadOnlyRepoToolkit`** — a new `AbstractToolkit` giving any `AbstractClient`
   a cwd-confined, write-free view of a checkout: `read_file`, `list_files`,
   **graph-backed `search_code`**, local `git_log`/`git_show`/`git_blame`, and an
   optional web search. Read-only by construction: `apply_patch` and `run_command`
   are simply not members. The cwd-confinement logic for the file readers is
   *ported* from `LLMCodeDispatcher`'s battle-tested private methods
   (`_tool_read_file` `llm.py:662`, `_tool_list_files` `llm.py:677`), not
   reinvented. Reusable well beyond this feature.

   **`search_code` is graph search, not grep (D9).** It queries the existing
   AST/tree-sitter wiki plane through `WikiCombinedSearch` (`wiki/search.py:32`)
   rather than shelling out — ranked pages with API outlines and `references`
   edges, token-budgeted, build artifacts already excluded. Two of the tools are
   therefore **thin wrappers over shipped code, not new implementations**:
   `search_code` delegates to `WikiQueryTool` (`wiki/tools.py:155`) or
   `DevLoopWikiSearch.build_research_context` (`wiki_search.py:91`), and a
   `related_code` tool delegates to `WikiRelatedTool` (`wiki/tools.py:225`) to walk
   `contains`/`references` edges. A `grep_files` fallback stays available for exact
   literal matching (regexes, config strings, anything the plane does not page),
   but it is the fallback, not the default. This also makes the toolkit
   **multi-language for free** — Python via `ast`, PHP/JS/TS/Rust/Perl via
   tree-sitter — which a hand-rolled Python-only AST parser would not have been.

2. **`AbstractResearchPartner`** + a `ResearchPartnerFactory`, mirroring
   `AbstractCodeReviewDispatcher` (`code_review.py:85`) and
   `CodeReviewDispatcherFactory` (`code_review.py:164`) — including the
   `advisory = True` marker (`code_review.py:100`). First and only
   implementation: `NovaResearchPartner`, driving `NovaClient.ask(use_tools=True,
   thinking_budget=N, structured_output=ResearchFindings)` over the existing
   Converse loop. Registered under `"nova"`; selected via a
   `resolve_research_partner_backend()` resolver shaped exactly like
   `resolve_adversarial_backend` (`catalog.py:63`) with an
   `ADVERSARIAL_BACKEND`-style default constant and choices tuple
   (`catalog.py:54/60`).

3. **`ComplementaryResearchCoordinator`** — the shared seam both nodes call. Given
   a brief and a cwd it fans the partner out concurrently with the primary seat's
   work, awaits both under a deadline, writes the partner's raw findings to
   `sdd/proposals/<slug>.research.md`, and returns a `ComplementaryFindings`
   object that the node folds into its dispatch payload. Every failure mode
   degrades to `None`. This is the research-phase twin of
   `ParallelPerspectiveReviewDispatcher` (`code_review.py:341`) — same
   `asyncio.gather`-and-merge shape, different phase and a cooperative rather than
   competitive merge.

`IdeationNode` gains one optional constructor kwarg (a coordinator or `None`) and
two new fields on its existing `_IdeationBrief` (`ideation.py:69`):
`partner_findings` and `partner_findings_path`. The `sdd-ideation` prompt gains a
section instructing it to read the partner's findings, expand on them, and
attribute insights by source. `ResearchNode` gains the same kwarg. Wiring happens
in `build_dev_flow_node_factories` (`factories.py:41`, `IdeationNode` constructed
at `factories.py:117`).

✅ **Pros:**
- Follows a pattern the repo has already proven at review time, so it reads as
  idiomatic rather than novel — and reviewers already know the shape.
- Reuses the entire Converse agentic loop, thinking-signature preservation, and
  FEAT-404 per-round usage telemetry. **No new agentic loop is written.**
- The `ReadOnlyRepoToolkit` is independently valuable: any Bedrock, Gemini, or
  local-LLM seat can be given safe repo grounding afterwards.
- Cleanly satisfies D1 (one mechanism, two nodes) with a single seam per node.
- Sidesteps FEAT-405's non-goal honestly: Claude keeps slash commands, document
  authorship, and the worktree. Nothing is reversed.
- Soft-degradation is a natural property of a coordinator returning `Optional`.
- No graph topology change → no interaction with FEAT-480's checkpoint
  fingerprinting.

❌ **Cons:**
- Introduces a new abstraction family (partner + factory + coordinator) alongside
  the existing review-dispatcher family. Two sibling hierarchies with a family
  resemblance but no shared base — a reviewer will reasonably ask why they are not
  unified (that is Option B).
- The `ReadOnlyRepoToolkit` is genuinely new code with real security weight:
  path-traversal confinement, symlink escape, and search-result size bounds all
  have to be right. This is the module that most deserves adversarial review.
- Prompt-level attribution ("which insight came from whom") is a soft contract the
  model can drift from; it is checkable but not structurally enforced.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `boto3` / `aiobotocore` | Bedrock Converse transport | Already a dependency via `BedrockConverseBase` (`clients/bedrock.py:114`); no new dep |
| `pydantic` | `ResearchFindings` / `ComplementaryFindings` contracts | Already core to the project |
| `ddgs` (via `parrot_tools.ddgsearch`) | Web-search axis for external prior art | `DdgSearchTool(AbstractTool)` exists at `parrot_tools/ddgsearch.py:19`; no API key needed. `serpapi.py`, `googlesearch.py`, `bingsearch.py` are keyed alternatives |
| `asyncio` (stdlib) | `gather` fan-out + `timeout` deadline | Same primitives as `code_review.py:392` |
| `git` (subprocess) | Local history axis (`log`/`show`/`blame`) | Must be built — `parrot_tools/gittoolkit.py` is a **GitHub API** toolkit, not local git (see Does NOT Exist) |
| `parrot.knowledge.wiki` (in-repo) | Graph-backed `search_code` / `related_code` over the AST + tree-sitter plane | **Already built and running**: FTS5/BM25 SQLite plane, 11518 pages / 18844 edges. Consume `WikiQueryTool`/`WikiRelatedTool` (`wiki/tools.py:155/225`) — do not reimplement |
| `ast` (stdlib) / `tree-sitter` | Python and PHP/JS/TS/Rust/Perl outlines feeding the plane | Consumed transitively via the wiki build; **not** a direct dependency of this feature. `tree_sitter_{php,typescript,javascript,rust,perl}` already installed |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/clients/bedrock.py:699` — `BedrockConverseBase.ask()`: the multi-round Converse tool loop, `thinking_budget` support, reasoning-signature preservation, FEAT-404 round events. The heart of the feature, unmodified.
- `packages/ai-parrot/src/parrot/clients/nova/client.py:31` — `NovaClient`; `_default_model = "nova-2-lite"` (`:65`).
- `packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py:341` — `ParallelPerspectiveReviewDispatcher`: the parallel-fan-out-and-merge template.
- `packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py:85/164` — `AbstractCodeReviewDispatcher` + `CodeReviewDispatcherFactory`: the abstraction/registry shape to mirror.
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/nova.py:240` — `NovaAdversarialReviewDispatcher`: the read-only-by-construction Converse seat, including its degrade-on-infra-error contract.
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py:662/677/691` — the cwd-confined `_tool_read_file` / `_tool_list_files` / `_tool_search_files` implementations to port.
- `packages/ai-parrot/src/parrot/flows/dev_loop/wiki_search.py:91` — `DevLoopWikiSearch.build_research_context()`: already-working best-effort wiki context, already used by `IdeationNode`; wrap it as a tool.
- `packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py:54/60/63` — the backend-selector triad to copy for the partner selector.

---

### Option B: Generalize the review machinery into one "perspective" abstraction

Rather than a sibling hierarchy, refactor the existing adversarial machinery into a
phase-agnostic **perspective** concept. `AbstractCodeReviewDispatcher` becomes (or
gains) an `AbstractPerspective` with a `contribute()` verb;
`ParallelPerspectiveReviewDispatcher` — already named for *perspectives* rather
than reviews — becomes the generic parallel-fan-out-and-merge engine, parameterized
by a merge policy that is *adversarial* (verdict arbitration) at review time and
*cooperative* (findings union) at research time. Research partners and adversarial
reviewers become two configurations of one mechanism.

✅ **Pros:**
- One abstraction instead of two look-alikes; the conceptual unity a reviewer of
  Option A would immediately ask for.
- The existing class name (`ParallelPerspectiveReviewDispatcher`) suggests the
  original author was already reaching for this generalization.
- Future phases (a second QA perspective, a planning perspective) get the
  mechanism for free.

❌ **Cons:**
- **Touches the working adversarial review path**, which is load-bearing for
  FEAT-375/405 and the whole dev-loop QA gate. This directly violates the
  pure-addition constraint: a refactor here can regress a path that works today,
  and the regression would surface at QA time in unrelated features.
- The two phases differ in more than the merge policy: reviews consume a diff and
  produce an arbitrated verdict; research consumes a brief and produces a findings
  union. Forcing one interface risks a lowest-common-denominator abstraction that
  fits neither well.
- Much larger blast radius and test matrix for the same user-visible outcome. The
  generalization is speculative until there is a third perspective phase.
- Bad sequencing against in-flight work: FEAT-479 already touches
  `dev_loop/dispatchers/llm.py` and FEAT-480 touches `dev_flow/flow.py`.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| — | No new dependencies | Pure refactor plus Option A's toolkit, which is still required |

🔗 **Existing Code to Reuse:**
- `dev_loop/code_review.py:85` — `AbstractCodeReviewDispatcher`, the class to generalize.
- `dev_loop/code_review.py:341/436/462` — `ParallelPerspectiveReviewDispatcher`, `_resolve_side`, `_merge_verdicts`: the engine to parameterize.
- `dev_loop/code_review.py:596` — `JudgePanelReviewDispatcher`: a third existing consumer that would have to be migrated.

---

### Option C: Expose the partner to Claude as a tool (Claude-driven collaboration)

The unconventional one. Instead of the node fanning out two researchers, build a
single new `AbstractTool` — `consult_research_partner(question, context)` — and add
it to the `sdd-ideation` agent's allowed tools. Claude decides *when* and *how often*
to consult Nova, and about *what*. Collaboration becomes an in-conversation move
rather than a topology.

No coordinator, no merge step, no parallel fan-out, no changes to either node's
structure — the entire feature is one tool plus a prompt instruction.

✅ **Pros:**
- Smallest possible surface: one tool, one prompt paragraph. Nothing in the flow
  graph, the node constructors, or the factories changes.
- Genuinely adaptive — Claude consults the partner on the questions where it is
  actually uncertain, rather than paying for one fixed broad consultation.
- Naturally supports multi-turn exchange (the bounded-exchange topology considered
  and set aside) with no new loop machinery: it is just repeated tool calls.
- Collaboration is *visible* in the transcript as tool calls, which is a real
  observability win.

❌ **Cons:**
- **Deviates from decision D3.** The partner is invoked *by* Claude, so it is
  anchored to Claude's framing of the question — losing the independent-angle
  property that motivated parallel-then-merge. This is the core value the feature
  is chasing, and this option trades it away.
- Non-determinism: Claude may never call the tool, or call it twelve times. Cost
  and coverage both become unbounded and unpredictable — awkward against the
  bounded-cost constraint and hard to assert in tests.
- Nested agent loops: a Converse tool loop (Nova with repo tools) running inside a
  Claude Agent SDK tool call. Timeouts, cancellation, and telemetry attribution all
  get harder, and a hang is harder to bound.
- The `.research.md` provenance artifact (D7) has no natural writer — findings would
  be scattered across tool results.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| — | Reuses Option A's `ReadOnlyRepoToolkit` and `NovaClient` path | Still needs the toolkit; the loop is the same |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/tools/abstract.py` — `AbstractTool` base.
- `packages/ai-parrot/src/parrot/flows/dev_flow/nodes/ideation.py:329-339` — the dispatch profile where the allowed-tools list is set.
- `packages/ai-parrot/src/parrot/clients/bedrock.py:699` — the same Converse loop, nested one level deeper.

---

### Option D: A first-class `complementary_research` node in the flow graph

Realize the parallel-then-merge topology as actual DAG structure: a new
`dev_flow.complementary_research` node running concurrently with (or immediately
before) `ideation`, joined by an OR-join, with its own edges in
`build_dev_flow_definition()` (`dev_flow/definition.py`) and its own entry in
`build_dev_flow_node_factories()`.

✅ **Pros:**
- Maximum observability: the partner becomes a real node with real lifecycle
  events, so `on_node_event` listeners, the run bundle, and the per-node usage
  table all see it without special-casing.
- Checkpointable in its own right — a resumed run could reuse partner findings
  instead of paying for them twice (attractive alongside FEAT-480).
- The collaboration is visible in the rendered graph, which is genuinely good
  documentation.

❌ **Cons:**
- **Direct collision with FEAT-480** (dev-flow node caching), which is in flight
  and whose spec covers checkpoint fingerprinting over the dev-flow topology
  (`Module 5: Proactive Dev Flow Integration`) and touches `dev_flow/flow.py`
  in 5 tasks. Changing the node set concurrently invites fingerprint churn and
  merge pain.
- The dev-flow graph already cannot use `from_definition` because of its OR-joins
  (`definition.py` module docstring); adding another join deepens a limitation the
  codebase is already working around.
- Does not satisfy D1 by itself — a graph node in `dev_flow` does nothing for
  `dev_loop`'s `ResearchNode`, so the shared mechanism from Option A is *still*
  required underneath. This is additive ceremony on top of Option A, not an
  alternative to it.
- Harder soft-degradation: a failed node routes to `failure_handler` via the
  on-error fan-in unless deliberately exempted, fighting the D4 requirement.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| — | No new dependencies | Requires Option A's components regardless |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/flows/dev_flow/definition.py` — `build_dev_flow_definition()` and the existing OR-join precedent.
- `packages/ai-parrot/src/parrot/flows/dev_flow/factories.py:41` — `build_dev_flow_node_factories`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/base.py` — `DevLoopNode` + `register_dev_loop_node`.

---

## Recommendation

**Option A** is recommended.

It is the only option that satisfies all eight recorded decisions without either
disturbing working code or giving up the property the feature exists for.

Against **Option B**: B's conceptual unity is real and tempting, but it buys that
unity by refactoring the adversarial review path — code that currently gates every
dev-loop QA cycle. The pure-addition constraint is not a nicety here; a regression
in `ParallelPerspectiveReviewDispatcher` would surface as mysterious QA behavior in
unrelated features. And the generalization is speculative: with exactly two phases,
"reviews arbitrate a verdict from a diff" and "research unions findings from a
brief" have less in common than the shared fan-out suggests. The right time to
unify is when a third perspective phase appears and the common shape is evidence
rather than prediction. Option A deliberately leaves that door open by mirroring
the review family's structure closely enough that a later merge is mechanical.

Against **Option C**: C is by far the cheapest and has the most attractive
observability story, and I want to be honest that it is a genuinely good idea for a
*different* feature. But it inverts the control flow in the one way that costs the
feature its point. The entire premise — stated in the original framing as
collaboration rather than challenge, and locked in as D3 — is that the second
researcher investigates *the same thing* from *its own angle*, and that Claude then
reads findings it did not commission. Under C, Nova only ever answers questions
Claude already knew to ask. That is a competent research *assistant*; it is not a
complementary researcher, and the blind spots most worth catching are exactly the
ones Claude would not think to ask about.

Against **Option D**: D is not really an alternative — it is Option A plus graph
ceremony, since a `dev_flow` node still leaves `ResearchNode` unserved. Its
observability and checkpointing benefits are real but are precisely what collides
with FEAT-480's in-flight fingerprinting work. Better sequencing: ship A now, and
promote the coordinator to a graph node later if the telemetry proves it is worth
checkpointing. Nothing in A forecloses that.

What Option A trades away, stated plainly:

- **Two sibling abstraction families** rather than one unified one — accepted
  deliberately, as the cost of not touching working review code, and mitigated by
  mirroring the review family's shape closely.
- **Attribution is prompt-enforced, not structural.** The merged document's
  "which insight came from whom" depends on the `sdd-ideation` prompt being
  followed. The `.research.md` sidecar (D7) is the structural backstop: even if
  attribution drifts, the partner's raw contribution is on disk and diffable.
- **A fixed one-shot consultation** rather than adaptive multi-turn — the cost of
  bounded, predictable spend and testable behavior.
- **A new security-sensitive module.** `ReadOnlyRepoToolkit` is where this feature
  can actually hurt someone, and it should get the adversarial review budget.

---

## Feature Description

### User-Facing Behavior

Nothing changes unless a deployment opts in. With `DEV_FLOW_RESEARCH_PARTNER`
unset, `IdeationNode` and `ResearchNode` behave exactly as today.

When enabled (`DEV_FLOW_RESEARCH_PARTNER=nova`), a dev-flow run started from a
natural-language request produces:

1. **A second artifact**: `sdd/proposals/<slug>.research.md`, committed alongside
   the brainstorm — the partner's own findings in its own voice: what it looked at,
   what it found, what it thinks the options are, what it could not determine.
   Formatted to match the existing hand-written precedent
   `sdd/proposals/agents-flow-refactor.research.md`.
2. **A richer primary document.** The brainstorm or proposal contains options and
   considerations traceable to the partner, with insights attributed by source
   (e.g. "*Nova 2 additionally identified …*"), and Claude's expansion on them.
3. **Visible collaboration in telemetry.** The run bundle's per-agent usage table
   gains a `research-partner` row (its tokens flow through the existing FEAT-404
   `ClientRoundEvent` path), and the ideation node's event stream carries
   `partner.started` / `partner.completed` / `partner.degraded`.

An operator who enables the partner and whose AWS credentials are missing sees a
warning in the log, a `partner.degraded` event, and a completely normal run — the
brainstorm is simply single-authored, exactly as before.

### Internal Behavior

**`ReadOnlyRepoToolkit`** — an `AbstractToolkit` constructed with a repo root. Every
tool is confined to that root: paths are resolved and verified to remain inside it
(rejecting `..` traversal and symlink escapes), results are size-bounded, and
timeouts bound every subprocess. Tool set across four grounding axes:

| Axis | Tools | Grounding | Backed by |
|---|---|---|---|
| Structural | `search_code`, `related_code` | Symbols, API outlines, and `references` edges from the AST/tree-sitter plane | `WikiCombinedSearch` (`search.py:32`), `WikiQueryTool`/`WikiRelatedTool` (`tools.py:155/225`) |
| Static | `read_file`, `list_files`, `grep_files` (fallback) | Exact file contents and literal matches | Ported from `llm.py:662/677/691` |
| Historical | `git_log`, `git_show`, `git_blame` | Why the code became this way | New — local `git` subprocess |
| External | `web_search` | Prior art and libraries outside the repo | `DdgSearchTool` (`ddgsearch.py:19`) |

There is no `apply_patch` and no `run_command`. Read-only is a property of the
membership list, not of a flag that could be misconfigured.

**Index freshness and worktrees.** The toolkit does not build an index; it consumes
the plane the repo already maintains (incremental, git-post-commit-driven). When the
partner runs inside a feature worktree, the toolkit resolves the plane by absolute
`storage_dir` back to the main checkout (`project.py:74` — "two repositories can
share one") rather than paying a 548 MB cold build per worktree. The plane is then
slightly behind the worktree's uncommitted edits, which is acceptable and even
desirable at *research* time: the partner is investigating the codebase as it
stands, not reviewing a diff. `git_*` and `read_file` cover anything uncommitted.
If the plane is missing or unbuilt entirely, `search_code` degrades to `grep_files`
with a logged warning — never a failure (Q9).

**`NovaResearchPartner`** — implements `AbstractResearchPartner`. Constructs a
`NovaClient`, registers a `ReadOnlyRepoToolkit` bound to the run's cwd, and issues
a single `ask(prompt, model=…, use_tools=True, thinking_budget=N,
structured_output=ResearchFindings, max_tokens=…)`. The existing Converse loop
(`bedrock.py:699`) then runs however many tool rounds the model needs, preserving
its reasoning signatures between rounds. The prompt is deliberately *neutral*: the
brief, the repo root, and the research question — and explicitly **not** Claude's
framing, hypotheses, or preferred conclusion. (Same discipline `CLAUDE.md` mandates
for adversarial review, for the same reason: supplying conclusions produces
ratification, not independent research.) Returns a validated `ResearchFindings`.

**`ComplementaryResearchCoordinator`** — the seam. `research(brief, cwd, slug)`:

1. Resolves the configured partner backend; returns `None` immediately if disabled.
2. Launches the partner under `asyncio.timeout(partner_timeout_seconds)`,
   concurrently with the primary seat's own work via `asyncio.gather`.
3. On success: renders the findings to `sdd/proposals/<slug>.research.md`, commits
   it (staging **only** that path, per the SDD auto-commit rule), and returns a
   `ComplementaryFindings` carrying the findings, the path, and usage metadata.
4. On **any** failure — timeout, credential error, Bedrock outage, structured-output
   parse failure, commit failure — logs a warning, emits `partner.degraded`, and
   returns `None`. It never raises into the node.

**`IdeationNode` changes** (minimal and additive): one optional constructor kwarg;
in `execute()`, call the coordinator before the first `_dispatch`; pass
`partner_findings` / `partner_findings_path` through the existing `_IdeationBrief`
(`ideation.py:69`). Resume rounds pass empty partner fields (D8) — the findings are
already in the document by then. `ResearchNode` gets the identical treatment on its
own dispatch path.

**Prompt changes**: `dev_flow/_subagent_data/sdd-ideation.md` gains a
"Complementary Research" section — read the partner's findings, treat them as a
peer's contribution to *expand*, not a claim to rebut; attribute insights by
source; state explicitly where you disagree and why (disagreement is data, not
conflict); and never let their absence change your process.

**Configuration** (`conf.py`, following the `DEV_LOOP_ADVERSARIAL_*` naming
neighborhood at `conf.py:947-1082`):

| Key | Default | Purpose |
|---|---|---|
| `DEV_FLOW_RESEARCH_PARTNER` | `""` (disabled) | Partner backend; `"nova"` is the only initial choice |
| `DEV_FLOW_RESEARCH_PARTNER_MODEL` | `us.amazon.nova-2-lite-v1:0` | Mirrors `DEV_LOOP_NOVA_REVIEW_MODEL` (`conf.py:1069`) |
| `DEV_FLOW_RESEARCH_PARTNER_THINKING_BUDGET` | e.g. `4096` | Converse `thinking_budget` (`bedrock.py:715`) |
| `DEV_FLOW_RESEARCH_PARTNER_TIMEOUT` | e.g. `600` | Hard deadline |
| `DEV_FLOW_RESEARCH_PARTNER_MAX_TOKENS` | e.g. `16384` | Cost ceiling |
| `DEV_FLOW_RESEARCH_PARTNER_WEB_SEARCH` | `false` | Gates the external-egress axis independently |

Plus a `catalog.py` triad mirroring `catalog.py:54/60/63`:
`RESEARCH_PARTNER_BACKEND`, `_RESEARCH_PARTNER_CHOICES`,
`resolve_research_partner_backend()`.

### Edge Cases & Error Handling

| Case | Behavior |
|---|---|
| Partner disabled (default) | Coordinator returns `None` before any work. Byte-identical to today. |
| AWS credentials missing / Bedrock 403 | Warning + `partner.degraded`; single-agent run. Never fatal. |
| Partner exceeds timeout | `asyncio.timeout` cancels it; degrade. Cancellation must not leak the subprocesses its tools started. |
| Structured-output parse failure | Degrade. (Explicitly *not* the "degrade to a passing verdict" pattern of `NovaAdversarialReviewDispatcher` — there is no verdict here, so absence is simply absence.) |
| Partner returns empty / trivial findings | Treated as absent: no `.research.md` is written, no empty section in the brainstorm. |
| `.research.md` write or commit fails | Findings are still passed in-memory to the dispatch; provenance is lost but the collaboration is not. Warn. |
| Partner tries to escape the repo root | Toolkit rejects the path with a structured tool error; the model sees the rejection and continues. Rejection is logged. |
| Partner attempts a write | Impossible — no write tool is registered. |
| Tool loop does not converge | Bounded by `max_tokens` + timeout; Converse ends the loop on `max_tokens`. |
| Web search enabled but network-blocked | That single tool returns a structured error; the other three axes still work. |
| HITL resume rounds | Partner does not re-run (D8). Its findings persist in the document and the sidecar. |
| Concurrent runs on the same repo | The toolkit is read-only, so no write contention. `.research.md` is slug-scoped. Two runs on the same slug is a pre-existing dev-flow concern, not new here. |
| Both Claude and the partner fail | Existing `IdeationNode` failure path is unchanged — the partner is never the reason a run fails. |
| Findings too large for the dispatch payload | Truncate with an explicit marker and keep the full text in `.research.md`; the prompt points Claude at the file. |

---

## Capabilities

### New Capabilities

- `devflow-complementary-research`: A configurable, read-only, collaborative
  second researcher that investigates a dev request in parallel with the primary
  Claude seat, persists its findings as an auditable artifact, and feeds them to
  the primary seat for expansion and attributed merge. Includes the
  `ReadOnlyRepoToolkit` that gives any `AbstractClient` safe repo grounding, and
  the `ResearchPartner` abstraction + Nova 2 implementation.

### Modified Capabilities

- `sdd-dev-flow` (FEAT-412) — `IdeationNode` gains an optional collaborator seam
  and two new `_IdeationBrief` fields; the `sdd-ideation` prompt gains a
  Complementary Research section.
- `novaclient-dev-loop` (FEAT-405) — its "pluggable research seat" non-goal is
  **narrowed, not reversed**: a Bedrock seat may now *contribute to* research
  without *replacing* the Claude seat that runs slash commands and authors
  documents. FEAT-405's `catalog.py` selector triad gains a research-partner
  sibling. Worth an explicit note in that spec so the two do not read as
  contradictory.
- `dev-loop-orchestration` — `ResearchNode` gains the same optional seam.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/flows/dev_flow/nodes/ideation.py` | modifies | One optional kwarg, two `_IdeationBrief` fields, one coordinator call in `execute()`. Primary integration point. |
| `parrot/flows/dev_flow/factories.py` | modifies | Build + inject the coordinator at `factories.py:117`. **Also touched by FEAT-479/480 — coordinate.** |
| `parrot/flows/dev_flow/_subagent_data/sdd-ideation.md` | modifies | Complementary Research prompt section. Mirror to `.claude/agents/sdd-ideation.md`. |
| `parrot/flows/dev_loop/nodes/research.py` | modifies | Same optional seam. **Touched by FEAT-479 (1 task).** |
| `parrot/flows/dev_loop/catalog.py` | extends | Research-partner selector triad + `BackendInfo` role. |
| `parrot/conf.py` | extends | Six new `DEV_FLOW_RESEARCH_PARTNER_*` keys. Additive only. |
| `parrot/tools/` or `parrot_tools/` | new | `ReadOnlyRepoToolkit`. **Placement is an open question (Q1).** |
| `parrot/flows/dev_flow/` (new module) | new | `research_partner.py` (abstraction + factory + Nova impl) and `complementary_research.py` (coordinator). |
| `parrot/clients/bedrock.py` | depends on | **Unmodified.** Consumed as-is — the single most important property of this design. |
| `parrot/clients/nova/client.py` | depends on | Unmodified. |
| `parrot/flows/dev_loop/code_review.py` | depends on | **Unmodified.** Pattern source only. Option B would have changed it; Option A does not. |
| `parrot/knowledge/wiki/` | depends on | **Unmodified.** `WikiQueryTool`/`WikiRelatedTool`/`WikiCombinedSearch` and the AST+tree-sitter plane consumed as-is (D9). Creates a core→`knowledge.wiki` dependency from the toolkit — relevant to Q1's placement decision. |
| `sdd/proposals/*.research.md` | new artifact | New committed output; slug-scoped. |
| Run bundle / usage report | extends | New `research-partner` seat row via existing FEAT-404 events. **Overlaps FEAT-479 (`usage_report.py`, 6 tasks) — sequence after it.** |
| CI / deployment | none | No new required dependency; opt-in, degrades without AWS credentials. |
| Security surface | **new** | Read-only repo access from a hosted model + optional web egress. Needs explicit adversarial review. |

**Breaking changes**: none. Every change is additive and default-off.

---

## Code Context

### User-Provided Code

No code snippets were provided. The user's framing, verbatim, for the record:

> dev_flow (`packages/ai-parrot/src/parrot/flows/dev_flow/`) is an AgentsFlow
> workflow following our Spec-Driven Development procedure (proactive Spec-Driven
> Development) have a node for Research using Claude Agent SDK for that task, the
> idea is based on the exiting Adversarial Code Review (Claude vs Codex that is
> already working on our SDD flow), creates a Complementary/Colaborative Research
> where 2 sub-agents (Claude Agent SDK + Amazon Nova 2 with thinking using AWS
> Bedrock client) with research together over the same thing and sharing insights
> and findings to create a combined document for proposal, idea is not an
> "adversarial" but Claude Agent reading the findings created by the second
> sub-agent (configurable but we starts with Amazon Nova 2) as a complementary
> research and expand the ideas over the research, not out of challenge between
> them, but collaboration.

**Terminology correction carried forward**: the dev-flow has **no `research` node**
— `definition.py` lists `research` among the nodes "deliberately absent". The
dev-flow's research-and-write-a-document seat is **`IdeationNode`**
(`dev_flow/nodes/ideation.py:91`). `ResearchNode` exists only in `dev_loop`
(`dev_loop/nodes/research.py:195`). Both are in scope (D1).

### Verified Codebase References

#### Classes & Signatures

```python
# From packages/ai-parrot/src/parrot/clients/bedrock.py:114
class BedrockConverseBase(AbstractClient):
    def __init__(...)                                              # line 130
    def _prepare_tools(self, filter_names: Optional[List[str]] = None
                       ) -> List[Dict[str, Any]]:                  # line 531
    async def ask(                                                 # line 699
        ...,
        thinking_budget: Optional[int] = None,                     # line 715
    )
    async def ask_stream(..., thinking_budget=None)                # lines 1056, 1070
    # Extended thinking is applied as:
    #   additional_fields["thinking"] = {"type": "enabled",
    #                                    "budget_tokens": thinking_budget}
    #                                                              # lines 831-835
    # Multi-round Converse tool loop: toolUse -> _execute_tool -> toolResult
    #                                                              # lines 930-990
    # FEAT-404 per-round ClientRoundEvent emitted after each round # lines 971-981
    # CRITICAL: assistant turn preserved verbatim so reasoningContent
    # blocks and their signatures travel through unmodified.       # lines 986-988

# From packages/ai-parrot/src/parrot/clients/nova/client.py:31
class NovaClient(BedrockConverseBase, NovaAudio, NovaGeneration):
    _default_model: str = "nova-2-lite"                            # line 65
    _fallback_model: str = "nova-lite"                             # line 66
    def __init__(...)                                              # line 68

# From packages/ai-parrot/src/parrot/clients/base.py
class AbstractClient:
    self.tools: Dict[str, Union[ToolDefinition, AbstractTool]] = {} # line 355
    async def _execute_tool(...)                                    # line 1454
    async def _execute_tool_call(...)                               # line 1563

# From packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py
class AbstractCodeReviewDispatcher(ABC):                            # line 85
    advisory: bool = False                                          # line 100
class CodeReviewDispatcherFactory:                                  # line 164
    @classmethod
    def register(cls, name: str)                                    # line 170
class CodexAdversarialReviewDispatcher(AbstractCodeReviewDispatcher): # line 267
    advisory = True                                                  # line 278
class ParallelPerspectiveReviewDispatcher(AbstractCodeReviewDispatcher): # line 341
    # "Composite reviewer: primary (write-enabled) + adversary, merged"
    primary_result, adversary_result = await asyncio.gather(...)     # line 392
    def _resolve_side(self, result, source) -> CodeReviewVerdict     # line 436
    def _merge_verdicts(self, primary, adversary)                    # line 462
class JudgePanelReviewDispatcher(AbstractCodeReviewDispatcher):      # line 596
    results = await asyncio.gather(...)                             # line 728
#   adversary_passed: bool                                          # line 76

# From packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/nova.py
class NovaCodeDispatcher(LLMCodeDispatcher):                        # line 61
    async def dispatch(...)                                         # line 217
class NovaAdversarialReviewDispatcher(AbstractCodeReviewDispatcher): # line 240
    agent_name = "nova-adversarial"                                 # line 267
    advisory = True                                                 # line 268
    # "Read-only BY CONSTRUCTION: no tools are ever passed to the model."
    # Drives NovaClient.ask(..., use_tools=False, structured_output=...)

# From packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py
class LLMCodeDispatcher:                                            # line 40
    async def _dispatch_loop(...)                                   # line 173
    def _tool_schemas(self, output_model) -> List[Dict[str, Any]]    # line 524
    def _tool_read_file(self, cwd, args) -> Dict[str, Any]          # line 662  <- PORT
    def _tool_list_files(self, cwd, args) -> Dict[str, Any]         # line 677  <- PORT
    async def _tool_search_files(...)                               # line 691  <- PORT
    async def _tool_apply_patch(...)                                # line 723  (EXCLUDE)
    #   raises ValueError("apply_patch requires workspace-write sandbox")  # 730
    async def _tool_run_command(...)                                # line 749  (EXCLUDE)

# From packages/ai-parrot/src/parrot/flows/dev_loop/wiki_search.py
class DevLoopWikiSearch:                                            # line 26
    def __init__(self, *, store: object, wiki_name: str)            # line 32
    def from_project(...)                                           # line 38
    async def build_research_context(self, query: str,
        budget_tokens: int = _DEFAULT_BUDGET_TOKENS) -> Optional[str]  # line 91
    # Best-effort: returns None on ANY internal error, never raises.

# From packages/ai-parrot/src/parrot/flows/dev_flow/nodes/ideation.py
class _IdeationBrief(BaseModel):                                    # line 69
    mode: Literal["brainstorm", "proposal"]
    title: str; description: str; context: str = ""
    graph_context: str = ""
    answers: dict[str, str] = Field(default_factory=dict)
    document_path: str = ""
    round: int = 1
@register_dev_loop_node("dev_flow.ideation")                        # line 90
class IdeationNode(DevLoopNode):                                    # line 91
    def __init__(self, *, dispatcher: ClaudeCodeDispatcher,
                 ideation_max_rounds: int | None = None, ...)       # line 105
    async def execute(...)                                          # line 122
    async def _dispatch(...)                                        # line 286
    #   permission_mode="acceptEdits"                               # line 329
    #   model="claude-sonnet-4-6"                                   # line 338

# From packages/ai-parrot/src/parrot/flows/dev_flow/models.py
class DevRequestBrief(BaseModel):                                   # line 47
    kind: DevRequestKind                                            # line 63
    title: str; description: str; context: str                      # lines 71/79/84
    jira_issue_key: str | None                                      # line 88
class IdeationOutput(BaseModel):                                    # line 157
    document_path: str                                              # line 167
    document_kind: Literal["brainstorm", "proposal"]                # line 175
    slug: str                                                       # line 183
    resumed_existing: bool                                          # line 184
    open_questions: list[str]                                       # line 192
    summary: str                                                    # line 200
    committed: bool                                                 # line 204

# From packages/ai-parrot/src/parrot/flows/dev_flow/factories.py
def build_dev_flow_node_factories(..., dispatcher: Any, ...)        # line 41
    #   IdeationNode(dispatcher=dispatcher, ...) constructed        # line 117

# From packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py
class ResearchNode(DevLoopNode):                                    # line 195
    def __init__(self, *, dispatcher: ClaudeCodeDispatcher, ...)    # line 218
    #   dispatch -> ResearchOutput                                  # line 423

# From packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py
ADVERSARIAL_BACKEND: str = "codex"                                  # line 54
_ADVERSARIAL_BACKEND_CHOICES: Tuple[str, ...] = ("codex", "nova")   # line 60
def resolve_adversarial_backend(config_getter=None) -> str          # line 63
    #   BackendInfo(id="nova", ...) roles=("development","adversarial")  # line 230

# From packages/ai-parrot/src/parrot/flows/dev_loop/models/nova.py
class NovaAdversarialReviewProfile(BaseModel):                      # line 130

# From packages/ai-parrot/src/parrot/flows/dev_flow/_subagent_defs.py
_VALID_NAMES: frozenset[str] = frozenset({"sdd-ideation"})          # line 33
def load_subagent_definition(name: str) -> str
    # Reads ONLY dev_flow/_subagent_data/<name>.md — never .claude/agents/

# From packages/ai-parrot-tools/src/parrot_tools/ddgsearch.py:19
class DdgSearchTool(AbstractTool): ...      # keyless web search
# From packages/ai-parrot-tools/src/parrot_tools/file_reader.py
class FileReaderToolArgs(AbstractToolArgsSchema): ...              # line 17
class FileReaderTool(AbstractTool): ...                            # line 31
# NOTE: not cwd-confined to a repo root — do NOT assume it is safe as-is.
```

#### Verified Imports

```python
# Confirmed to resolve:
from parrot.clients.nova.client import NovaClient                   # nova/client.py:31
from parrot.clients.bedrock import BedrockConverseBase              # bedrock.py:114
from parrot.flows.dev_loop.code_review import (                     # code_review.py
    AbstractCodeReviewDispatcher,                                   # :85
    CodeReviewDispatcherFactory,                                    # :164
    ParallelPerspectiveReviewDispatcher,                            # :341
)
from parrot.flows.dev_loop.catalog import resolve_adversarial_backend  # catalog.py:63
from parrot.flows.dev_loop.wiki_search import DevLoopWikiSearch     # wiki_search.py:26
from parrot.flows.dev_loop.dispatchers import ClaudeCodeDispatcher  # used at ideation.py:56
from parrot.flows.dev_loop.models import (                          # used at ideation.py:57
    ClaudeCodeDispatchProfile, FeatureBrief,
)
from parrot.flows.dev_loop.nodes.base import DevLoopNode, register_dev_loop_node
from parrot.flows.dev_flow.models import DevRequestBrief, IdeationOutput
from parrot.flows.dev_flow._subagent_defs import load_subagent_definition
from parrot.tools import tool                                       # per CLAUDE.md
from parrot_tools.ddgsearch import DdgSearchTool                    # ddgsearch.py:19
# The wiki / code-graph plane (D9):
from parrot.knowledge.wiki.tools import (                           # wiki/tools.py
    WikiQueryTool, WikiPageTool, WikiRelatedTool, WikiStatusTool,   # :155/:190/:225/:409
    create_wiki_tools,                                              # :541
)
from parrot.knowledge.wiki.search import WikiCombinedSearch         # wiki/search.py:32
from parrot.knowledge.wiki.toolkit import LLMWikiToolkit            # wiki/toolkit.py:54
from parrot.knowledge.wiki.languages.base import (                  # wiki/languages/base.py
    LanguageScanner, LanguageOutline,
)
from parrot.knowledge.wiki.repo_scan import scan_repository         # repo_scan.py:776
from parrot.knowledge.wiki.context import pack_results              # used at wiki_search.py:112
```

#### The code-graph subsystem (D9)

```python
# From packages/ai-parrot/src/parrot/knowledge/wiki/languages/base.py
class LanguageOutline(BaseModel):
    summary: str = ""
    outline: list[str] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)
class LanguageScanner(ABC):
    name: ClassVar[str]
    suffixes: ClassVar[frozenset[str]]
    @abstractmethod
    def outline(self, source: str, rel_path: str) -> LanguageOutline: ...
    def build_reference_index(self, rel_paths: Iterable[str]) -> Any: ...
    def resolve_import(...) -> ...: ...
    def mode(self) -> str: ...        # "ast" | "tree-sitter"

# From packages/ai-parrot/src/parrot/knowledge/wiki/languages/python.py:30
class PythonScanner(LanguageScanner):
    def outline(self, source, rel_path) -> LanguageOutline:          # line 36
        tree = ast.parse(source, filename=rel_path or "<unknown>")   # line 49
        # walks ast.Import / ast.ImportFrom / ast.ClassDef /
        # ast.FunctionDef / ast.AsyncFunctionDef                     # lines 63-78
    def build_reference_index(self, rel_paths) -> Any                # line 81
    def resolve_import(...)                                          # line 111

# From packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py
def discover_repo_files(...)                                         # line 355
def _git_ls_files(root: Path) -> list[str] | None                    # line 398  (gitignore-aware)
def build_file_slice(...)                                            # line 556
def build_dir_pages(...)                                             # line 645
def build_import_edges(...)                                          # line 718  (`references` edges)
def scan_repository(...)                                             # line 776  <- ENTRY POINT

# From packages/ai-parrot/src/parrot/knowledge/wiki/search.py:32
class WikiCombinedSearch:
    # modes: "lexical" (FTS5/BM25), "vector" (cosine, needs embedder),
    #        "combined"; default weights lexical .6 / vector .4  (line 174)
    async def search(self, query, mode=..., top_k=..., tree_name=...)  # line 91
    # Vector leg is SKIPPED when no embedder is supplied (line 202) —
    # DevLoopWikiSearch supplies none, so today it is lexical-only.

# From packages/ai-parrot/src/parrot/knowledge/wiki/store.py
CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(...)         # line 117
async def search_fts(self, query, category=None, limit=10)           # line 1147
async def search_vector(self, embedding, limit=10)                   # line 1195

# From packages/ai-parrot/src/parrot/knowledge/wiki/project.py
def storage_path(self, root: Path) -> Path                           # line 457
    storage_dir: str = Field(default=f"{PARROT_DIR}/wiki")           # line 402
    # ":74 — ``storage_dir`` may be absolute, so two repositories can
    #  share one" -> the worktree plane-sharing mechanism (Q9).
```

#### Key Attributes & Constants

- `BedrockConverseBase.ask(..., thinking_budget=None)` → enables Converse extended thinking (`bedrock.py:715`, applied `bedrock.py:831-835`)
- `NovaClient._default_model` → `"nova-2-lite"` (`nova/client.py:65`)
- `AbstractCodeReviewDispatcher.advisory` → `bool`, default `False` (`code_review.py:100`)
- `ADVERSARIAL_BACKEND` → `"codex"` (`catalog.py:54`)
- `_ADVERSARIAL_BACKEND_CHOICES` → `("codex", "nova")` (`catalog.py:60`)
- `conf.DEV_FLOW_IDEATION_MAX_ROUNDS` → `int`, default `2` (`conf.py:972`)
- `conf.DEV_LOOP_NOVA_REVIEW_MODEL` → default `us.amazon.nova-2-lite-v1:0` (`conf.py:1069`)
- `conf.DEV_LOOP_ADVERSARIAL_BACKEND` → default `"codex"` (`conf.py:1082`)
- `conf.DEV_LOOP_ADVERSARIAL_MODEL` → default `"gpt-5.5"` (`conf.py:947`)
- `conf.DEV_LOOP_NOVA_MANTLE_BASE_URL` / `_REGION` (`conf.py:1037/1040`) — mantle only; **not** used by this feature
- `conf.DEV_LOOP_NOVA_MECHANICAL_MODEL` (`conf.py:1072`)

### Does NOT Exist (Anti-Hallucination)

- ~~`AdversarialCodeReviewDispatcher`~~ — **not the real class name.** The composite parallel reviewer is `ParallelPerspectiveReviewDispatcher` (`code_review.py:341`).
- ~~a `research` node in the dev-flow graph~~ — `dev_flow/definition.py` explicitly lists `research` among nodes "deliberately absent". The dev-flow's research seat is `IdeationNode`.
- ~~`ReadOnlyRepoToolkit`~~ / ~~`RepoBrowseToolkit`~~ / any read-only repo-browsing toolkit — does not exist anywhere. The cwd-confined readers are **private methods** on `LLMCodeDispatcher` (`llm.py:662/677/691`) and are not reusable as-is.
- ~~`parrot_tools.code_toolkit.CodeToolkit` as a repo browser~~ — it exists (`code_toolkit.py:266`) but is a **coding-agent-delegation** toolkit (`implement_spec`, `fix_bug`, `review_diff`, `generate_tests`, `explain_patch`), not a file/search browser.
- ~~a local-git toolkit~~ — `parrot_tools/gittoolkit.py` is a **GitHub API** toolkit (`RepositoryCredential:48`, `CreatePullRequestInput:267`, `SearchRepoCodeInput:438`). There is **no** `git log` / `git show` / `git blame` tool over a local checkout. Must be built.
- ⚠️ **CORRECTED (2026-08-31)** — an earlier revision of this document wrongly listed "a `wiki_query` `AbstractTool`" as non-existent. **It exists.** `parrot/knowledge/wiki/tools.py` (FEAT-403 Module 5) ships six `AbstractTool` subclasses — `WikiQueryTool:155`, `WikiPageTool:190`, `WikiRelatedTool:225`, `WikiRememberTool:257`, `WikiNoteTool:344`, `WikiStatusTool:409` — plus the `create_wiki_tools(store, root, config) -> list[AbstractTool]` factory at `:541`. There is also a full `LLMWikiToolkit(AbstractToolkit)` at `wiki/toolkit.py:54`. **Do not write new wiki tools; bind these.** (`DevLoopWikiSearch` at `wiki_search.py:26` is separately a plain helper, not a tool — that part was accurate.)
- ~~`GraphIndexToolkit` as the code-search backend~~ — it exists (`parrot_tools/graphindex/toolkit.py:72`) but requires a prebuilt `rustworkx.PyDiGraph` + `faiss.Index` + node maps in its constructor (`:116`). It is **not** the subsystem backing `wikitoolkit` code search; that is `parrot/knowledge/wiki/` over an SQLite FTS5 plane. Do not confuse the two.
- ~~a need to write an AST parser or build a code graph~~ — **already exists and is running.** `LanguageScanner` ABC (`wiki/languages/base.py`), `PythonScanner` using stdlib `ast` (`languages/python.py:30`), tree-sitter scanners for PHP/JS/Rust/Perl, `scan_repository()` (`repo_scan.py:776`), `build_import_edges()` (`repo_scan.py:718`). The live plane holds 11518 pages / 18844 edges. Writing a new AST indexer would be duplicating shipped, tested code.
- ~~`NovaResearchDispatcher`~~ / ~~`NovaResearchPartner`~~ / ~~`ComplementaryResearchCoordinator`~~ / ~~`AbstractResearchPartner`~~ / ~~`ResearchPartnerFactory`~~ — none exist; all are proposed by this brainstorm.
- ~~a Chat Completions endpoint for `us.amazon.nova-*` or `us.anthropic.*` on Bedrock~~ — does not exist. Confirmed by `dispatchers/nova.py` module docstring and `catalog.py:246-251`. Therefore `NovaCodeDispatcher`/bedrock-mantle **cannot** serve Nova 2, and the OpenAI-shaped `LLMCodeDispatcher` loop cannot be reused for it.
- ~~code that writes `sdd/proposals/*.research.md`~~ — `agents-flow-refactor.research.md` exists as a **hand-written** artifact. There is no generator.
- ~~a `partner`/`collaborator` field on `_IdeationBrief`~~ (`ideation.py:69`) — the model has exactly `mode`, `title`, `description`, `context`, `graph_context`, `answers`, `document_path`, `round`.
- ~~`sdd-research` or `sdd-secondopinion` in `dev_flow._subagent_defs`~~ — `_VALID_NAMES` is `frozenset({"sdd-ideation"})` only (`_subagent_defs.py:33`). dev_flow owns its own prompt set deliberately.
- ~~`FileReaderTool` as a safe repo reader~~ — it exists (`file_reader.py:31`) but is **not** confined to a repo root. Do not assume it is safe for an untrusted model without adding confinement.

---

## Parallelism Assessment

- **Internal parallelism**: **Good, along a clean seam.** The feature splits into
  three weakly-coupled workstreams: (1) `ReadOnlyRepoToolkit` — a standalone
  `AbstractToolkit` with no dev-flow dependencies, testable entirely on a temp-dir
  fixture; (2) `AbstractResearchPartner` + `NovaResearchPartner` + the catalog/conf
  selector — depends only on the toolkit's interface, not its implementation; (3)
  the coordinator + node seams + prompt changes. (1) and (2) can proceed
  concurrently once the toolkit's tool-name/schema contract is fixed in the spec;
  (3) depends on (2)'s interface only. In practice the coupling is loose enough for
  parallel worktrees but the total task count is modest, so the coordination
  overhead may not repay itself.

- **Cross-feature independence**: **Two live conflicts, both manageable, both
  requiring sequencing rather than avoidance.**

  | In-flight | Overlap | Assessment |
  |---|---|---|
  | **FEAT-479** `devflow-telemetry-accounting` (11 tasks, just started) | `dev_loop/usage_report.py` (6 tasks), `dev_loop/runner.py` (9), `dev_flow/runner.py` (4), `dev_flow/models.py` (1), `dev_loop/nodes/research.py` (1), `dev_loop/dispatchers/llm.py` (4) | **Real overlap on the telemetry surface.** FEAT-479 is rebuilding the usage report on a run ledger (its Module 7). Adding a `research-partner` seat row *before* that lands means writing against a surface being replaced. **Sequence after FEAT-479**, or scope this feature's telemetry to emitting events only and let 479's ledger pick them up. Also both touch `research.py` — small, but coordinate. |
  | **FEAT-480** `dev-flow-node-caching` (7 tasks, just started) | `dev_flow/flow.py` (5 tasks), `dev_loop/flow.py` (4), `dev_flow/runner.py`, `dev_loop/checkpoint.py` | **Avoided by design.** FEAT-480's Module 5 fingerprints the dev-flow topology; Option D (a new graph node) would have collided head-on. Option A changes **no** node set and **no** edges, so the fingerprint is untouched. This is a concrete reason to prefer A over D right now. |

  No overlap at all with the review path (`code_review.py` unmodified),
  `clients/bedrock.py`, or `clients/nova/`. The only file this feature and both
  in-flight features all touch is `dev_flow/factories.py` — a small, append-shaped
  change on all three sides.

- **Recommended isolation**: **`per-spec`**

- **Rationale**: The task count is moderate and the three workstreams share a
  design that is still settling — particularly the toolkit's tool-name/schema
  contract, which both the toolkit and the partner depend on. Sequential tasks in
  one worktree let that contract firm up in code rather than in prose, at the cost
  of some wall-clock. More decisively: two features are already live on the
  neighboring files, so a third concurrent worktree multiplies the three-way merge
  risk on `factories.py` and the telemetry surface for little gain. Revisit if the
  spec decomposes to more than ~10 tasks, in which case the toolkit is the natural
  candidate to split out — it is the one piece with no dev-flow dependencies at all.

---

## Open Questions

- [ ] **Q1 — Where does `ReadOnlyRepoToolkit` live?** `CLAUDE.md` says concrete external wrappers go in `parrot_tools`, while base machinery stays in core `parrot/tools/`. This toolkit is neither: it wraps the local filesystem, not an external service, and it is general-purpose rather than dev-flow-specific. Candidates: (a) `parrot_tools/repo/` — consistent with "concrete toolkits ship from ai-parrot-tools", but makes core dev-flow depend on the tools distribution; (b) `parrot/tools/repo/` in core — no new cross-distribution dependency, arguably justified as reusable machinery; (c) `parrot/flows/dev_loop/` — no dependency questions, but buries a reusable component. Leaning (b). — *Owner: Jesus Lara*
- [ ] **Q2 — Should the toolkit be its own capability/spec?** It is independently valuable and independently reviewable (it carries the feature's real security weight), which argues for its own spec. Against: two specs for one user-visible outcome is ceremony, and the toolkit has no consumer without this feature. Currently folded in as Module 1. — *Owner: Jesus Lara*
- [ ] **Q3 — Sequencing against FEAT-479.** Wait for 479's ledger to land before adding the `research-partner` usage row, or ship this feature emitting events only and let 479 pick them up? The latter unblocks now but leaves the telemetry story half-done until 479 merges. — *Owner: Jesus Lara*
- [ ] **Q4 — Is `nova-2-lite` the right default, or should it be Nova 2 Pro?** `NovaAdversarialReviewDispatcher` defaults to Lite specifically because `us.anthropic.*` ids are gated behind a per-account Anthropic use-case form on Bedrock (`dispatchers/nova.py:240`). Research is a deeper task than verdict-rendering, so Lite + a generous `thinking_budget` may underperform. Needs an empirical comparison on 2–3 real dev requests. — *Owner: Jesus Lara*
- [ ] **Q5 — Should `web_search` be on by default when the partner is enabled?** It is the axis Claude's repo-grounded research is weakest on, which is the strongest argument for it — but it is also the only one that sends any part of the brief to a third party. Proposed default: **off**, gated by its own key. Confirm that the external-egress posture is acceptable at all for repo-derived queries. — *Owner: Jesus Lara*
- [ ] **Q6 — Does the partner see the human's HITL answers?** D8 says the partner runs on round 1 only, so it never sees them. If a human's answer materially reframes the problem, the partner's findings are stale for the rest of the run and Claude alone absorbs the reframing. Accept (bounded cost), or add a narrow exception when an answer changes the document's scope? — *Owner: Jesus Lara*
- [ ] **Q7 — Should attribution be structural rather than prompt-enforced?** E.g. `ResearchFindings` carries discrete findings with stable ids, and the merged document must cite ids. Stronger guarantee that collaboration happened; more rigid prose. Currently prompt-enforced with the `.research.md` sidecar as backstop. — *Owner: Jesus Lara*
- [ ] **Q9 — Worktree plane strategy (D9).** The plane is 548 MB and rooted at the checkout, so a fresh build per feature worktree is a non-starter. `project.py:74` says `storage_dir` may be absolute so two repositories can share one plane — is pointing the worktree at the main checkout's plane acceptable? It means the partner sees the repo at roughly last-commit state, not the worktree's uncommitted edits. My read: acceptable and arguably correct at research time (the partner investigates the codebase, it does not review a diff), with `git_*`/`read_file` covering anything uncommitted. Alternative: a small per-worktree overlay plane for changed files only. Needs a decision before the toolkit's constructor signature is fixed. — *Owner: Jesus Lara*
- [ ] **Q10 — Enable the vector leg for the partner's `search_code`?** `WikiCombinedSearch` supports cosine `search_vector` (`store.py:1195`) but `DevLoopWikiSearch` supplies no embedder (`search.py:202` skips the leg), so search is lexical-only today. Measured consequence: a conceptual query ("how does a review seat degrade when the backend has an outage") scored 0.06/0.00, while symbol and topic queries score 0.8–1.0. A researching agent asks conceptual questions far more than a grepping one does, so this may matter more here than anywhere else the plane is used. Cost: an embedder in the loop plus embedding storage for 11518 pages. Possibly its own feature. — *Owner: Jesus Lara*
- [ ] **Q11 — Does `search_code` belong to the primary Claude seat too?** The partner gets graph search; the `sdd-ideation` Claude seat currently gets a one-shot `graph_context` string (`ideation.py`, via `build_research_context`) rather than an interactive search tool. If graph search is genuinely better than grep, the primary seat is the bigger beneficiary — but that widens scope beyond the complementary-research feature. Flagging deliberately rather than silently expanding. — *Owner: Jesus Lara*
- [ ] **Q8 — Add a note to `sdd/specs/novaclient-dev-loop.spec.md` (FEAT-405)?** Its "pluggable research seat" non-goal will read as contradicted by this feature unless annotated with the narrowing (contribute-to vs. replace). Cheap, and prevents a future reader concluding one of the two specs is wrong. — *Owner: Jesus Lara*
