---
id: FEAT-377
title: "Graph Engineering × dev_loop — close the repair loop and wire the knowledge graph"
slug: graphindex-as-engineering-devloop
type: feature
mode: enrichment
status: review
source:
  kind: file
  jira_key: null
  jira_url: null
  fetched_at: 2026-07-26
  summary_oneline: "Evaluate the Graph Engineering framework against GraphIndex + dev_loop; ground gaps in the codebase"
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-377/
created: 2026-07-26
updated: 2026-07-26
---

# FEAT-377 — Graph Engineering × dev_loop: close the repair loop and wire the knowledge graph

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `file: sdd/proposals/graph-engineering-devloop.proposal.md`
> **Audit**: [`sdd/state/FEAT-377/`](../state/FEAT-377/)

---

## 0. Origin

The source is an evaluation document mapping the "Graph Engineering with
Claude Code: 14 Steps From 0 to Graph Architect" framework (@0xCodez) against
AI-Parrot's dev_loop (FEAT-129/132/250/253/270/322/323) and GraphIndex
(FEAT-187/190/191/192/215/217/239/240/260) subsystems. The evaluation
identified 8 gaps (G1–G8) and proposed 6 candidate features (FEAT-A through
FEAT-F).

> The Graph Engineering document validates the architecture AI-Parrot already
> converged on — dev_loop covers nearly every orchestration pattern and
> GraphIndex is a complete knowledge-graph memory pipeline. Its value is the
> audit: it pinpoints that our flow fails **open** (QA → human, instead of
> bounded self-repair) and that our two graph systems — the *process* graph
> and the *knowledge* graph — have never been introduced to each other.

**Initial signals**:
- 14-pattern scorecard: 9 covered, 3 partial, 2 gaps
- Two structural absences: no repair loop (G1), no GraphIndex wire (G2)
- Six secondary gaps: escalation (G3), stop rule (G4), gates (G5),
  checkpoint (G6), hygiene (G7), ontology (G8)

---

## 1. Synthesis Summary

AI-Parrot's dev_loop and GraphIndex subsystems independently implement nearly
all of the Graph Engineering framework's prescribed patterns, but they have
two critical missing connections: (1) QA failure terminates the flow instead
of retrying with feedback (G1), and (2) the process graph and knowledge graph
are completely disconnected — zero Python-level coupling, zero wiki/graph
instructions in dispatched subagent prompts (G2). Closing these two gaps,
along with six verified secondary issues (model escalation, stop-rule
automation, unused gates, checkpoint/resume, prompt drift, ontology gaps),
transforms the dev loop from "agents run once and escalate" into "agents
retry with feedback, remember across runs, and escalate only past the stop
rule." All 11 claims are verified at high confidence against the current
codebase with no unresolved unknowns.

---

## 2. Codebase Findings

> All entries are grounded in research findings at `sdd/state/FEAT-377/findings/`.
> Each cites finding IDs. **No fabricated paths or symbols.**

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot/src/parrot/flows/dev_loop/definition.py` | `build_dev_loop_definition` | 104-111 | QA edges: only qa→handoff and qa→failure_handler | F001 |
| 2 | `packages/ai-parrot/src/parrot/flows/dev_loop/flow.py` | `build_dev_loop_flow` | 343-345 | Imperative wiring mirrors declarative — no retry edge | F001 |
| 3 | `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py` | `ResearchNode.execute` | 1-924 | No GraphIndex context injection, no wiki tools | F002 |
| 4 | `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/close.py` | `DevLoopCloseNode` | 1-143 | No graph write-back at run completion | F002 |
| 5 | `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/failure_handler.py` | `FailureHandlerNode` | 87-89 | Hard-coded Jira transition + no graph write-back | F002, F007 |
| 6 | `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-research.md` | — | — | Missing wiki-first block that `.claude/agents/` copy has | F002 |
| 7 | `packages/ai-parrot/src/parrot/flows/dev_loop/agent_pool.py` | `_next_worker` | 159-174 | Round-robin retry — no model-tier escalation | F003 |
| 8 | `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py` | `GateKind` | 166-172 | plan_approval + revision_approval never opened | F005 |
| 9 | `packages/ai-parrot/src/parrot/flows/dev_loop/runner.py` | `DevLoopRunner` | 573-586 | Semaphore held during gate waits | F006 |
| 10 | `packages/ai-parrot/src/parrot/flows/dev_loop/models.py` | `RevisionBrief` | 283-305 | No acceptance_criteria — revision QA lint-only | F007 |
| 11 | `packages/ai-parrot/src/parrot/knowledge/graphindex/meta_ontology.py` | `_ENTITY_DEFS` | 30-120 | Only 6 of 9 NodeKinds mapped | F008 |
| 12 | `packages/ai-parrot/src/parrot/knowledge/graphindex/persist.py` | `_upsert_nodes` | 240 | Silently skips unmapped kinds | F008 |

### 2.2 Constraints Discovered

- **Event-sourced state model.** `DevLoopSessionState` uses pure `reduce()` over
  `ActionEnvelope`s (FEAT-322). Any new state (e.g., `qa_attempts` counter) must
  be added as an action type with a reducer, not as mutable state.
  *Evidence*: F001

- **Declarative + imperative parity.** The flow topology exists in two forms:
  `definition.py` (declarative, used for validation/visualization) and `flow.py`
  (imperative, used for execution via OR-join). New edges must be added to both
  and covered by the parity test.
  *Evidence*: F001

- **Subagent prompt sourcing.** `load_subagent_definition()` reads only from
  `_subagent_data/` via `importlib.resources` — never from `.claude/agents/`.
  Any prompt change must land in the package copy to take effect in dispatched runs.
  *Evidence*: F002, F007

- **Arango ontology boundary.** Node/edge kinds without `KIND_TO_COLLECTION` /
  `EDGE_KIND_TO_COLLECTION` entries are silently dropped by `_upsert_nodes` /
  `_create_edges`. New kinds (RUN, CLAIM, WIKI_PAGE) require collection mappings
  before they can persist to ArangoDB.
  *Evidence*: F008

- **Concurrency semaphore scope.** The `DevLoopRunner._semaphore` is held for
  the entire flow lifetime including gate waits. Long-TTL gates exhaust the pool.
  *Evidence*: F006

### 2.3 Recent History (Relevant)

The most recent topology-affecting features are:

| Feature | When | Impact |
|---------|------|--------|
| FEAT-323 (multi-agent pool) | Recent | Added `DevAgentPool`, `TaskScheduler`, wave dispatch |
| FEAT-322 (session state + gates) | Recent | Event-sourced state, gate infrastructure, deployment_approval |
| FEAT-270 (code review) | Recent | Added code-review verifier as independent QA step |
| FEAT-375 (adversarial second opinion) | Recent | Added sdd-secondopinion subagent |

No recent commits address any of the 8 gaps.

---

## 3. Probable Scope

### What's New

- **QA → development retry edge** with bounded counter + QAReport feedback injection (G1)
- **Model-tier escalation policy** in pool retry path (G3)
- **Graph context injection** in `ResearchNode` via `GraphContextBuilder.build()` (G2 seam 2)
- **Run outcome write-back** in `CloseNode`/`FailureHandlerNode` as graph memory commits (G2 seam 3)

### What Changes

- **`definition.py` + `flow.py`**: new conditional edge `qa —(failed ∧ attempts < N)→ development` with `_CEL_QA_RETRY` predicate [F001]
- **`models.py`**: add `qa_attempts` counter to session state as a new action type [F001]
- **`_subagent_data/*.md`**: sync wiki-first block from `.claude/agents/` copies [F002]
- **`agent_pool.py`**: optional escalation policy on `_next_worker` retry [F003]
- **`failure_handler.py`**: replace hard-coded `"Needs Human Review"` with `transition_issue_with_candidates` [F007]
- **`models.py` `RevisionBrief`**: carry `acceptance_criteria` field [F007]
- **`meta_ontology.py`**: add `wiki_page`, `run`, `claim` entity definitions [F008]
- **`persist.py`**: route new node/edge kinds to Arango collections [F008]

### What's Untouched (Non-Goals)

- Rewriting the flow engine — all changes are topology/model additions
- Migrating away from SQLite persistence — it remains a valid plane
- Changing the `deployment_approval` gate (already working)
- Adding new LLM providers or dispatchers
- The GraphIndex build pipeline itself (extract → resolve → assemble → persist)

### Patterns to Follow

- **Event-sourced state**: new `qa_attempts` follows the same `ActionEnvelope` + pure `reduce()` pattern as existing counters. *Evidence*: F001
- **Declarative + imperative parity**: add edges to both `definition.py` and `flow.py`, extend parity test. *Evidence*: F001
- **`transition_issue_with_candidates`**: use the synonym-fallback helper already in `nodes/base.py:53`, as `deployment_handoff.py` and `close.py` do. *Evidence*: F007
- **`GraphPublisher.commit`**: write-back uses the existing commit/revert pattern with `RUN`/`CLAIM` node kinds and `PRODUCED`/`ABOUT`/`SUPPORTED_BY` edges. *Evidence*: F008

### Integration Risks

- **Infinite retry risk (G1)**: The repair loop must have a hard cap (`DEV_LOOP_QA_MAX_RETRIES`, default 2). Without it, a deterministic QA failure would loop forever. *Mitigation*: the existing `_CEL_QA_FAILED` predicate is extended with `∧ attempts < N`; the `attempts ≥ N` case routes to `failure_handler` as today. *Evidence*: F001

- **Ontology prerequisite (G8 → G2)**: Write-back (G2 seam 3) depends on `RUN`/`CLAIM`/`PRODUCED`/`ABOUT`/`SUPPORTED_BY` kinds being routable in persistence. The ontology must be extended first. *Mitigation*: FEAT-F before FEAT-B in the execution order. *Evidence*: F008

- **Prompt drift regression**: Syncing `_subagent_data/` copies is a one-time fix; without CI parity checks, they will drift again. *Mitigation*: add a parity assertion in the existing test suite. *Evidence*: F002, F007

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | QA failure routes exclusively to failure_handler — no bounded retry loop | F001 | high | Direct read of definition.py edges + flow.py wiring |
| C2 | Zero Python-level coupling between dev_loop and GraphIndex | F002 | high | Exhaustive grep across all dev_loop .py and .md files |
| C3 | Wiki-first block in interactive sdd-research.md absent from dispatched copy | F002 | high | Direct diff of both copies |
| C4 | Dispatch retry is positional (round-robin), not model-tier escalation | F003 | high | agent_pool._next_worker picks by index; no tier field |
| C5 | Pool-vs-single decision is config-driven; wave sizing is dynamic via TaskScheduler | F004 | high | Development node checks config; TaskScheduler uses Kahn's algorithm |
| C6 | plan_approval and revision_approval declared but never opened | F005 | high | Exhaustive grep for open_gate shows only 3 of 5 kinds used |
| C7 | Gated runs hold semaphore; checkpoint/resume deferred to v2 | F006 | high | runner.py semaphore scope + spec Risk R8 |
| C8 | Subagent prompts drifted: repo has per-spec index + wiki, package copies unchanged | F007 | high | Line count + content diff |
| C9 | FailureHandlerNode hard-codes Jira transition instead of using helper | F007 | high | Direct read vs base.py:53 helper |
| C10 | RevisionBrief lacks acceptance_criteria — revision QA lint-only | F007 | high | Model definition + runner.py:653 comment |
| C11 | Arango meta-ontology maps 6 of 9 NodeKinds; 3 silently dropped | F008 | high | NodeKind enum (9) vs _ENTITY_DEFS (6) vs KIND_TO_COLLECTION (6) |

Distribution: **11** high, **0** medium, **0** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

All claims verified at high confidence. No user Q&A required.

### Unresolved (defer to spec / implementation)

None — all gaps fully grounded in codebase evidence.

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-377`** — *Rationale*: all 8 gaps verified at high confidence
with precise localization and no unresolved unknowns. The evaluation already
provides a feature decomposition (FEAT-A through FEAT-F) that can be codified
into spec acceptance criteria directly.

### Suggested Feature Decomposition (from evaluation, verified)

| Candidate | Scope | Effort | Depends on |
|---|---|---|---|
| FEAT-A `dev-loop-qa-repair-loop` | G1 + G3 (bounded retry with tier escalation) + G4 (stop rule) | S–M | — |
| FEAT-B `dev-loop-graph-memory` | G2 seams 1–3 (prompt sync, research context, run write-back) | M | G8 ontology (FEAT-F) |
| FEAT-C `dev-loop-plan-gate` | G5 (`plan_approval` consumer) | S | — |
| FEAT-D `dev-loop-checkpoint-resume` | G6 | M–L | — |
| FEAT-E `dev-loop-hygiene` | G7 batch | S | — |
| FEAT-F `graphindex-ontology-completion` | G8 ontology + collection routing | S | — |

**Recommended order**: **E → F → A → B** (hygiene unblocks prompt-sync seam;
ontology unblocks graph write-back; repair loop is highest-ROI topology change;
graph wire is the framework's core thesis). C, D can proceed in parallel.

### Alternatives

- **`/sdd-brainstorm FEAT-377`** — if you want to explore alternative
  decompositions or prioritizations beyond the evaluation's recommended order.
- **`/sdd-task FEAT-377`** — not recommended; this is a multi-feature umbrella
  that should be decomposed into individual specs first.
- **Individual specs** — e.g. `/sdd-spec` for each FEAT-A through FEAT-F
  independently, using this proposal as the source.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-377/state.json` |
| Source (raw) | `sdd/state/FEAT-377/source.md` |
| Findings (digests) | `sdd/state/FEAT-377/findings/F001-*.md` through `F008-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-377/synthesis.json` |

**Budget consumed**:
- Files read: ~35 / 40 (across 4 parallel research agents)
- Grep calls: ~22 / 25
- Git calls: ~6 / 10
- Wiki queries: 4 (free — not budget-counted)
- Truncated: **no**

**Mode determination**: `enrichment` — the source document is a complete
evaluation with identified gaps, not a bug investigation.

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Source document | `sdd/proposals/graph-engineering-devloop.proposal.md` (evaluation) |
| Research method | 4 parallel subagents + 4 wiki queries |
| Operator | Claude Opus 4.6 |
