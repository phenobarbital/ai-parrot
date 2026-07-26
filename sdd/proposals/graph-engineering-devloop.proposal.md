---
id: null
title: Graph Engineering evaluation — mapping the 14-step framework onto GraphIndex + dev_loop
slug: graph-engineering-devloop
type: evaluation
mode: research
status: draft
source:
  kind: external-document
  url: https://x.com/i/status/2079165300625330317
  document: "Graph Engineering with Claude Code: 14 Steps From 0 to Graph Architect (@0xCodez)"
  fetched_at: 2026-07-26
  summary_oneline: Evaluate the viral Graph Engineering framework against FEAT-187+ (GraphIndex) and FEAT-129+ (dev_loop) to optimize the development flow
overall_confidence: high
base_branch: dev
created: 2026-07-26
updated: 2026-07-26
---

# Graph Engineering × AI-Parrot — Evaluation of GraphIndex + dev_loop

> **Source document**: *"Graph Engineering with Claude Code: 14 Steps From 0 to
> Graph Architect"* by @0xCodez (X article `2079165300625330317`), plus its
> companion knowledge-graph thread. X blocks unauthenticated fetches and the
> sandbox network policy blocks mirrors, so the framework below was
> reconstructed from multiple secondary sources (dev.to summary, aibuilderclub
> guide, youmind digest, the IntuitMachine "From Loop Engineering to Graph
> Engineering" article it responds to). Confidence in the reconstruction: high —
> the same primitives and patterns recur verbatim across all sources.

---

## 1. The Graph Engineering framework, distilled

**Thesis**: *"Loops embed logic in sequence; graphs declare logic in
topology."* Graph engineering is the discipline of modeling agentic workflows
as directed graphs with explicit state transitions, typed edges, and
deterministic failure domains — replacing ad-hoc control flow with a topology
you can inspect, version, and debug.

### Four primitives

| Primitive | Definition |
|---|---|
| **Nodes** | Pure state transformers — each an agent or deterministic step |
| **Edges** | Static topology: branches, fan-out, fan-in, loops |
| **State** | A single typed context that flows along edges; "what turns a pile of agents into a system instead of a group chat that forgets everything" |
| **Routers** | Dynamic edge selection — predicates, escalation, conditional routing |

### The recurring patterns (the "steps")

1. **Redraw the chain** — take a linear agent pipeline and ask, for each
   arrow, "does B truly need A's output?" Independent nodes fan out.
2. **Fan-out / fan-in (the diamond)** — N independent work items run
   concurrently; a fan-out is only useful if something *owns the merge point*
   where one agent sees all results.
3. **Separate verifier contexts** — validation runs in a *fresh* context,
   never in the context that produced the work (adversarial verification).
4. **Validator + router escalation** — a validator node checks quality; a
   router escalates to the next model tier on failure.
5. **Loop-with-gate** — canonical five-node topology:
   `planner → executor → validator → output`, with a bounded loop from
   validator back to planner on failure.
6. **The stop rule** — an explicit policy for when to parallelize vs. run
   sequential, and when a retry loop must stop (cites DeepMind × MIT,
   180 configurations).
7. **The human gate** — human approval modeled as *just another edge*, placed
   exactly where a mistake is expensive to undo.
8. **Checkpointing** — state persisted at node boundaries so runs can pause,
   resume, and replay; deterministic failure domains per node.
9. **Knowledge-graph memory** (companion thread) — *"your agent's memory dies
   with its context window; a knowledge graph makes it permanent"*:
   **Extract → Resolve → Assemble → Query → Repeat**, with a cheap model
   extracting S-P-O triples (one structured call per document), a stronger
   model doing entity resolution, and serialized subgraphs answering
   multi-hop questions.

---

## 2. Scorecard: where AI-Parrot already stands

The headline result of this evaluation: **AI-Parrot has already independently
built almost every mechanism the document prescribes** — dev_loop
(FEAT-129/132/250/253/270/322/323) covers the orchestration patterns and
GraphIndex (FEAT-187/190/191/192/215/217/239/240/260) covers the
knowledge-graph memory pipeline. The framework is therefore most useful to us
not as a to-do list but as an *audit lens*: it exposes exactly one structural
absence (no closed repair loop), one missing wire (dev_loop ↔ GraphIndex), and
a handful of declared-but-unconsumed surfaces.

| # | Graph Engineering pattern | dev_loop | GraphIndex | Verdict |
|---|---|---|---|---|
| P1 | Nodes as typed state transformers | ✅ 9 `DevLoopNode` types, Pydantic contracts in `models.py` | ✅ 8-stage builder pipeline | **Covered** |
| P2 | Typed edges / declared topology | ✅ `build_dev_loop_definition()` is a declarative `FlowDefinition` with CEL predicates; execution mirrors it edge-for-edge in explicit-edge mode (OR-join at `research`) | ✅ 10 `EdgeKind`s, stable edge ids | **Covered** |
| P3 | Shared typed state | ✅ FEAT-322: event-sourced `DevLoopSessionState` — pure `reduce()` over `ActionEnvelope`s, replayable via `view=state` | ✅ `GraphUpdate`/`CommitReceipt` | **Covered** — arguably ahead of the document (event sourcing > mutable state object) |
| P4 | Routers / conditional edges | ✅ `_is_bug`/`_qa_passed` predicates route intake and QA | n/a | **Covered**, but static — no *escalation* router (see G3) |
| P5 | Fan-out/fan-in diamond | ✅ FEAT-323 `DevAgentPool` waves + `TaskScheduler` (Kahn topological waves) + `SubWorktreeManager.merge_sequential()` as the owned merge point | ✅ concurrent extractor fan-in in `builder.py:154` | **Covered** |
| P6 | Separate verifier contexts | ✅ `sdd-qa` runs `permission_mode="plan"`, tools Read/Bash only, fresh dispatch; code review is a second independent verifier (FEAT-270); QA re-runs if the reviewer touched files | ✅ `GroundingEvaluator.ground_claim` verifies claims against evidence paths | **Covered** — textbook implementation |
| P7 | Loop-with-gate (validator → planner) | ❌ `qa failed → failure_handler` is **terminal**; no bounded retry back to `development` | n/a | **Gap G1 — the one structural miss** |
| P8 | Stop rule | ⚠️ Concurrency caps exist (`FLOW_MAX_CONCURRENT_RUNS`, `pool_max`, exactly-one-retry per pool wave) but parallelism is *configured* (`DEV_LOOP_DEV_AGENTS`), never *decided* | n/a | **Partial** (G4) |
| P9 | Human gate as an edge | ✅ FEAT-322 gates: `deployment_approval` + blocking `manual_criterion`, TTLs, REST resolve/cancel | ✅ `confirming_tools = {"revert_write"}` | **Covered**; but `plan_approval`/`revision_approval` gate kinds are declared and never opened (G5) |
| P10 | Checkpointing / resume | ⚠️ Terminal snapshots + full event replay exist; but `awaiting_gate` runs still hold a concurrency slot — checkpoint/resume of `run_flow` was explicitly deferred in FEAT-322 §8 | ✅ SQLite `graph_commits` with pre-images → `revert_commit` | **Partial** (G6) |
| P11 | Knowledge-graph memory pipeline | ❌ **zero** references to `parrot.knowledge` anywhere in `dev_loop/` | ✅ Extract → Embed → Assemble → Resolve → Persist → Query, provenance (`EXTRACTED/INFERRED/ASSERTED`), `LLMGraphExtractor` for free text, `GraphMemoryMixin` | **The missing wire (G2)** — both halves exist; nothing connects them |
| P12 | Cheap-extract / strong-resolve model tiering | n/a | ⚠️ `LLMGraphExtractor` supports tiering (e.g. haiku extract) but resolution is cosine-only; "Level-2 LLM verification explicitly deferred" in `resolve.py` | **Partial** |
| P13 | Inspectable, versioned topology | ✅ definition used for materialization/validation/parity/visualization | ✅ `graph.html`/`graph.json`/`GRAPH_REPORT.md` export | **Covered** |
| P14 | Deterministic failure domains | ✅ per-node `on_error` fan-in to `failure_handler`; dispatch events per node stream; `FlowEventPublisher` failure domains isolated | ✅ persistence failures degrade to `persist_warning`, never fail the tool call | **Covered** |

**Score: 9 covered, 3 partial, 2 gaps.** The two gaps are precisely where the
document predicts the most leverage.

---

## 3. Gap analysis and recommendations (prioritized)

### G1 — Close the repair loop: `qa → development` bounded retry ⭐ highest ROI

The document's canonical topology is *loop-with-gate*: validator failure loops
back to the planner/executor a bounded number of times before a human sees it.
Today `dev-loop`'s QA failure edge goes straight to the terminal
`failure_handler` (human escalation). Every fixable lint error, missed
criterion, or flaky test costs a full human round-trip.

**Proposal**: add a conditional edge `qa —(failed ∧ attempts < N)→ development`
carrying the `QAReport` as feedback into the redispatch brief (the
`sdd-worker` prompt already accepts task-scoped briefs, FEAT-323), with
`shared["qa_attempts"]` incremented in state and the existing
`qa —(failed ∧ attempts ≥ N)→ failure_handler` edge as the stop rule.
Default `N = 2` (configurable `DEV_LOOP_QA_MAX_RETRIES`). This is a pure
topology change in `definition.py` + `flow.py` + a predicate — the machinery
(redispatch, worktree reuse via `_ensure_worktree_safe`, event streams) all
exists.

### G2 — Wire GraphIndex into dev_loop (the missing wire) ⭐ core thesis of the document

*"Your agent's memory dies with its context window; a knowledge graph makes it
permanent."* We built the permanent memory (GraphIndex + LLM-wiki) and the
agent fleet (dev_loop) and never connected them. Grep confirms zero coupling.
Four concrete seams, in ascending effort:

1. **Sync the wiki-first block into the shipped subagent prompts** (hours, not
   days). `.claude/agents/sdd-research.md:32-49` has a *"Wiki-first triage
   (PRIORITY)"* block instructing `wikitoolkit query/page/related` before any
   grep — but the copy the dispatcher actually injects
   (`_subagent_data/sdd-research.md`) has **no wiki instruction at all**, and
   `sdd-worker`/`sdd-qa`/`sdd-codereview` have none in either location.
   Dev-loop research dispatches are grepping blind today while interactive
   sessions query the graph. Fix the drift (see also G7) and add a scoped
   wiki-usage block to all four subagent prompts, gated on the wiki plane
   existing in the target repo.
2. **Research-node graph context injection.** `ResearchNode` already
   aggregates logs + Jira; pre-pend a `GraphContextBuilder.build()` result
   (entity-seeded, budget-capped, citation-serialized — all shipped) for the
   affected component so triage starts from the graph, not from cold grep.
3. **Write run outcomes back as graph memory.** GraphIndex already has the
   vocabulary waiting: `RUN`/`CLAIM` node kinds, `PRODUCED`/`ABOUT`/
   `SUPPORTED_BY` edges, `AssertionMeta`, and `GraphPublisher` commits with
   revert. `DevLoopCloseNode`/`FailureHandlerNode` should publish one audited
   commit per run: what was changed, which claims QA verified, what failed and
   why. This is the "Repeat" stage of Extract → Resolve → Assemble → Query →
   **Repeat** — each run makes the next run's research cheaper. (Note these
   kinds currently persist only in the SQLite plane; see G8.)
4. **Ground code-review findings.** `GroundingEvaluator.ground_claim` returns
   supported evidence paths or a structured `revise` instruction — exactly the
   shape needed to filter hallucinated review findings before they fail a QA
   gate.

### G3 — Escalation router on dispatch failure

The document's validator-router escalates to the next model tier on failure.
dev_loop has seven interchangeable dispatcher backends and a
`DevAgentSpec.model` override, but retry logic (pool: exactly one retry on
`_next_worker`) retries on the *same* tier. Add an optional escalation policy
to the retry paths — e.g. `sonnet → opus` on `DispatchOutputValidationError`
or QA-failure redispatch (composes with G1: retry #2 escalates). The config
surface already exists (`DEV_LOOP_DEV_AGENTS` specs); this is dispatch-selection
logic, not new infrastructure.

### G4 — Make the stop rule explicit

Parallelism is currently an operator choice. Encode the document's stop rule
as a small deterministic policy in `DevelopmentNode._resolve_pool_config`:
fan out only when `TaskScheduler.next_wave()` yields ≥ 2 truly independent
tasks; otherwise degrade to single-agent (the degradation path already
exists). One decision function, unit-testable, no LLM.

### G5 — Open the declared human gates

`GateKind` declares `plan_approval` and `revision_approval` with TTL settings
(`DEV_LOOP_GATE_TTL_PLAN`/`_REVISION`) but nothing calls `open_gate` for them.
The document's placement rule — *"the human gate goes exactly where a mistake
is expensive to undo"* — points at the research→development edge: approving
the plan (Jira ticket + spec + task decomposition) before an agent fleet burns
tokens implementing it is the cheap-to-approve/expensive-to-skip point.
Opt-in flag like FEAT-322's `require_deployment_approval`.

### G6 — Checkpoint/resume for gated runs

FEAT-322 §8 consciously deferred releasing the `FLOW_MAX_CONCURRENT_RUNS` slot
while `awaiting_gate`. The event-sourced state (pure `reduce`, snapshots,
replay) means the hard part is done — a paused run is fully reconstructible
from `flow:{run_id}:actions`. Raising this from "future feature" to scheduled
is consistent with the document's checkpointing step, and is a prerequisite
before long-TTL blocking manual criteria (already warned about in the spec).

### G7 — Repair the drifted / dead surfaces (hygiene batch)

Small items surfaced by this audit, bundled as one cleanup feature:
- **Subagent dual-sourcing drift**: `_subagent_defs.py` docstring advertises
  repo + package sourcing; only the package copy runs; copies have drifted
  (research 99 vs 80 lines, worker 328 vs 274). Either implement repo-first
  sourcing or make the package copy canonical and add a CI parity check.
- **`FailureHandlerNode` hard-codes** `transition="Needs Human Review"`
  (`failure_handler.py:87-89`) instead of `transition_issue_with_candidates`
  — breaks on any Jira workflow lacking that exact label.
- **Revision QA is lint-only**: `RevisionBrief` doesn't carry the original
  acceptance criteria, so revision runs verify almost nothing. Persist the
  criteria (they're in the run snapshot / graph memory per G2-3) and re-run
  them.
- **Dead JSON-schema path** in the Claude dispatcher
  (`_materialize_json_schema` exists, `json_schema_path` pinned `None`) —
  delete or revive.

### G8 — GraphIndex ontology drift + process discipline

- The Arango meta-ontology covers 6 of 9 `NodeKind`s — `wiki_page`, `run`,
  `claim` are silently dropped by `_upsert_nodes` ("Unknown kind") and survive
  only in SQLite. Before G2-3 lands, either add the three collections or
  document SQLite as the sole plane for memory kinds.
- **The four most recent GraphIndex commits shipped outside the SDD trail**
  (`514a5447` provenance+publisher, `787cc9fa` GraphMemoryMixin,
  `a76413d6` LLMGraphExtractor, `09fe7df6` grounding) — ~1,200 LOC of public
  surface with no spec or tasks. The document's own point — *"a topology you
  can inspect, version, and debug"* — applies to the dev process itself: the
  SDD graph is our process topology, and these nodes are off-graph. Backfill
  a spec.

---

## 4. Suggested feature decomposition

| Candidate | Scope | Effort | Depends on |
|---|---|---|---|
| FEAT-A `dev-loop-qa-repair-loop` | G1 + G3 (bounded retry with tier escalation) + G4 (stop rule) | S–M | — |
| FEAT-B `dev-loop-graph-memory` | G2 seams 1–3 (prompt sync, research context injection, run write-back) | M | G8 ontology decision |
| FEAT-C `dev-loop-plan-gate` | G5 (`plan_approval` consumer) | S | — |
| FEAT-D `dev-loop-checkpoint-resume` | G6 | M–L | — |
| FEAT-E `dev-loop-hygiene` | G7 batch | S | — |
| FEAT-F `graphindex-sdd-backfill` | G8 spec backfill + ontology completion | S | — |

Recommended order: **E → A → B** (hygiene unblocks the prompt-sync seam; the
repair loop is the highest-ROI topology change; the graph wire is the
document's core thesis). C, D, F can proceed in parallel.

---

## 5. Bottom line

The Graph Engineering document validates the architecture AI-Parrot already
converged on — dev_loop is a working example of nearly every pattern it
teaches, and GraphIndex is a complete implementation of its knowledge-graph
memory pipeline. Its value to us is the audit: it pinpoints that our flow
still fails **open** (QA failure → human, instead of a bounded self-repair
loop) and that our two graph systems — the *process* graph and the *knowledge*
graph — have never been introduced to each other. Closing those two gaps turns
the dev loop from "agents run once and escalate" into "agents retry with
feedback, remember across runs, and escalate only past the stop rule" — which
is the document's definition of a graph architect's system.
