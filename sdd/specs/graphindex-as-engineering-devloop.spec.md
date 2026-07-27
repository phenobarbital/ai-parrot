---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Graph Engineering Hardening — repair loop, graph memory wire, gates, checkpoint, hygiene, ontology

**Feature ID**: FEAT-377
**Date**: 2026-07-26
**Author**: Jesus Lara (research + synthesis: Claude, /sdd-proposal FEAT-377)
**Status**: approved
**Target version**: next minor
**Source proposal**: `sdd/proposals/graphindex-as-engineering-devloop.proposal.md` (research audit: `sdd/state/FEAT-377/`)

---

## 1. Motivation & Business Requirements

### Problem Statement

The Graph Engineering framework audit (FEAT-377 proposal, 11 claims verified
at high confidence) found that AI-Parrot's dev_loop implements nearly every
orchestration pattern the framework prescribes — but the flow still **fails
open** and the two graph systems are **disconnected**:

1. **No repair loop (G1)** — `qa failed → failure_handler` is terminal
   (`definition.py:104-111`, `flow.py:343-345`). Every fixable lint error,
   missed criterion, or flaky test costs a full human round-trip via Jira.
2. **The missing wire (G2)** — zero references to `parrot.knowledge` anywhere
   in `dev_loop/`. GraphIndex (permanent memory) and dev_loop (agent fleet)
   have never been introduced: research dispatches grep blind while
   interactive sessions query the wiki; run outcomes are never written back.
3. **Six secondary gaps** — no model-tier escalation on retry (G3), stop rule
   is config-only (G4), `plan_approval`/`revision_approval` gates declared but
   never opened (G5), gated runs hold a concurrency slot with no
   checkpoint/resume (G6), four hygiene defects incl. subagent prompt drift
   (G7), and the Arango ontology silently drops 3 of 9 node kinds and 4 of 10
   edge kinds (G8).

Closing these turns the loop from "agents run once and escalate" into
"agents retry with feedback, remember across runs, and escalate only past
the stop rule."

### Goals

- **G1** Bounded QA→development repair loop carrying `QAReport` feedback,
  hard-capped by `DEV_LOOP_QA_MAX_RETRIES` (default 2).
- **G3** Optional model-tier escalation on retry/redispatch.
- **G4** Deterministic fan-out stop rule in the development node (no LLM).
- **G2** Wire GraphIndex into dev_loop: prompt sync, research context
  injection, run write-back, grounded review findings.
- **G5** Consume the declared `plan_approval` gate (opt-in, fail-open).
- **G6** Release the concurrency slot while `awaiting_gate`; resume on
  gate resolution from event-sourced state.
- **G7** Hygiene batch: prompt-drift repair + full parity sweep, Jira
  transition candidates in FailureHandler, revision-run criteria, dead
  JSON-schema path removal, missing `review_escalation` TTL entry.
- **G8** Complete the Arango meta-ontology: `wiki_page`/`run`/`claim` node
  collections and `produced`/`about`/`supported_by`/`contradicts` edge
  collections.

### Non-Goals (explicitly out of scope)

- Rewriting the flow engine (`parrot/bots/flows/`) — all changes are
  topology/model/node additions.
- Migrating away from SQLite persistence — it remains the primary plane for
  agent graph memory; Arango completion (G8) is about parity, not replacement.
- Changing the working `deployment_approval` / `manual_criterion` /
  `review_escalation` gate flows.
- Adding new LLM providers or dispatcher backends.
- Cross-process crash recovery (process dies mid-run) — G6 v1 scope is
  in-process slot release + resume; full crash resume remains deferred
  (dev-loop-orchestration.spec.md Risk R8 v2).
- The GraphIndex build pipeline itself (extract → resolve → assemble →
  persist stages are untouched except ontology routing).

---

## 2. Architectural Design

### Overview

Six phased modules in dependency order **E → F → A → B**, with **C** and
**D** independent:

- **Module 1 (E — hygiene)** unblocks everything: syncs the drifted
  `_subagent_data/` prompts with `.claude/agents/` (including the wiki-first
  block — this is G2 seam 1), extends the existing parity tests to a full
  sweep, fixes the hard-coded Jira transition, carries acceptance criteria on
  `RevisionBrief`, deletes the dead Claude-dispatcher JSON-schema path, and
  adds the missing `review_escalation` TTL entry.
- **Module 2 (F — ontology)** completes the Arango meta-ontology so the
  memory kinds (`run`, `claim`, `wiki_page`) and assertion edges
  (`produced`, `about`, `supported_by`, `contradicts`) are routable — the
  prerequisite for Module 4's write-back.
- **Module 3 (A — repair loop)** adds the bounded `qa → development` retry
  edge (G1) with per-attempt feedback, an optional escalation model on the
  retry path (G3), and the deterministic fan-out stop rule (G4).
- **Module 4 (B — graph memory wire)** injects `GraphContextBuilder` output
  into research dispatch, publishes one audited `GraphUpdate` per run from
  the terminal nodes, and grounds code-review findings via
  `GroundingEvaluator` — all gated behind an opt-in config.
- **Module 5 (C — plan gate)** opens the declared `plan_approval` gate on
  the research→development boundary (opt-in, fail-open on TTL expiry, per
  the documented semantics in `session_state.py:222-228`).
- **Module 6 (D — checkpoint/resume)** releases the runner semaphore while a
  run is `awaiting_gate` and resumes it on gate resolution, reconstructing
  from the event-sourced session state.

All state additions follow the FEAT-322 event-sourcing pattern: new action
types join the `DevLoopAction` discriminated union with a branch in the pure
`reduce()` — no mutable state.

### Component Diagram

```
                 ┌────────────────────── Module 3 (A) ──────────────────────┐
                 │                                                          │
 intent ─→ research ─→ development ─→ qa ──(passed)──→ deployment_handoff ─→ close
              │   ▲          ▲         │                      │
              │   │          │         ├─(failed ∧ attempts<N)┘◄─ retry edge (new)
              │   │          └─────────┘   carries QAReport feedback
              │   │                    │
              │   │                    └─(failed ∧ attempts≥N)─→ failure_handler
              │   │                                                   │
   Module 5 (C)   │                                                   │
   plan_approval  │                                                   │
   gate (opt-in)  │                                                   │
              │   │                                                   │
              ▼   │                                                   ▼
        ┌─────────┴──────────── Module 4 (B) ─────────────────────────────┐
        │  GraphContextBuilder.build() ──→ research dispatch prompt       │
        │  GraphPublisher.publish(GraphUpdate) ←── close/failure_handler  │
        │  GroundingEvaluator.ground_claim() ←── qa code-review findings  │
        └───────────────── parrot.knowledge.graphindex ───────────────────┘
                                    ▲
                     Module 2 (F): ontology completion
                     (run/claim/wiki_page + assertion edges)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `build_dev_loop_definition()` (`definition.py`) | extends | new `qa → development` conditional edge + retry CEL predicates (Module 3) |
| `build_dev_loop_flow()` (`flow.py`) | extends | mirrored imperative edge; parity test updated (Module 3) |
| `DevLoopAction` union + `reduce()` (`session_state.py`) | extends | new `QaAttemptRecorded` action + reducer branch (Module 3) |
| `DevAgentPool` / `DevAgentSpec` (`agent_pool.py`, `models.py`) | extends | optional `escalation_model` consulted on retry (Module 3) |
| `DevelopmentNode._resolve_pool_config` (`nodes/development.py`) | extends | deterministic `should_fan_out()` stop rule (Module 3) |
| `ResearchNode.execute` (`nodes/research.py`) | uses | prepends `GraphContext.text` to the dispatch brief when graph memory enabled (Module 4) |
| `DevLoopCloseNode` / `FailureHandlerNode` | uses | publish one `GraphUpdate` per run via `GraphPublisher` (Module 4) |
| `QANode` code-review path (`nodes/qa.py`) | uses | filters findings through `GroundingEvaluator.ground_claim` (Module 4) |
| `SessionHost.open_gate` (`session_state.py`) | uses | `plan_approval` gate opened on research completion (Module 5) |
| `DevLoopRunner` semaphore (`runner.py:182,573-586`) | modifies | slot released while `awaiting_gate`, re-acquired on resume (Module 6) |
| `transition_issue_with_candidates` (`nodes/base.py:53`) | uses | replaces hard-coded transition in `failure_handler.py:87-89` (Module 1) |
| `COLLECTION_TO_KIND` / `EDGE_KIND_TO_COLLECTION` (`meta_ontology.py`) | extends | 3 node + 4 edge collections added (Module 2) |
| `_upsert_nodes` / `_create_edges` (`persist.py`) | unchanged | routing works automatically once mappings exist (Module 2) |

### Data Models

```python
# Module 3 — session_state.py: new action in the DevLoopAction union
class QaAttemptRecorded(BaseModel):
    """Recorded each time QA fails and a repair retry is dispatched."""
    type: Literal["qa_attempt_recorded"] = "qa_attempt_recorded"
    attempt: int                    # 1-based attempt that just failed
    qa_notes: str = ""              # condensed QAReport failure summary

# Module 3 — models.py: QAReport gains the attempt counter (CEL-visible)
class QAReport(BaseModel):
    ...existing fields...
    attempt: int = 1                # which QA attempt produced this report

# Module 3 — models.py: DevAgentSpec gains optional escalation tier
class DevAgentSpec(BaseModel):
    agent: DevAgentBackend
    model: str = ""
    count: int = 1
    escalation_model: str = ""      # model used on retry/redispatch; "" = same

# Module 1 — models.py: RevisionBrief carries the original criteria
class RevisionBrief(BaseModel):
    ...existing 7 required fields...
    acceptance_criteria: Optional[List[AcceptanceCriterion]] = None
    # None → legacy lint-only behavior preserved

# Module 4 — run write-back payload (constructed, not a new model):
# GraphUpdate(nodes=[UniversalNode(kind=RUN), ...claims...],
#             edges=[PRODUCED, ABOUT, SUPPORTED_BY...],
#             agent_id="dev-loop", run_id=<run_id>, asserted_by="dev_loop.close")
```

### New Public Interfaces

```python
# Module 3 — nodes/development.py (module-level, unit-testable, no LLM)
def should_fan_out(wave: List[TaskRef], pool_cfg: DevAgentPoolConfig) -> bool:
    """Stop rule: fan out only when the first wave has >= 2 independent tasks."""

# Module 4 — new module: parrot/flows/dev_loop/graph_memory.py
class DevLoopGraphMemory:
    """Facade wiring GraphIndex into dev_loop nodes (opt-in)."""
    @classmethod
    async def from_config(cls, ...) -> Optional["DevLoopGraphMemory"]:
        """Returns None unless DEV_LOOP_GRAPH_MEMORY_PATH is configured."""
    async def build_research_context(self, brief: WorkBrief) -> Optional[str]: ...
    async def publish_run_outcome(self, run_id: str, report: QAReport | None,
                                  outcome: str, summary: str) -> Optional[CommitReceipt]: ...
    async def ground_findings(self, findings: list[str]) -> list[str]: ...

# Module 6 — runner.py
class DevLoopRunner:
    async def resume_run(self, run_id: str) -> FlowResult:
        """Re-acquire a slot and resume a run parked on a resolved gate."""
```

New configuration keys (navconfig, all optional):

| Key | Default | Module |
|---|---|---|
| `DEV_LOOP_QA_MAX_RETRIES` | `2` | 3 |
| `DEV_LOOP_GRAPH_MEMORY_PATH` | unset (disabled) | 4 |
| `DEV_LOOP_REQUIRE_PLAN_APPROVAL` | `false` | 5 |
| `DEV_LOOP_GATE_PARK` | `true` | 6 |

---

## 3. Module Breakdown

### Module 1: dev-loop hygiene batch (Phase E)
- **Path**: `parrot/flows/dev_loop/_subagent_data/*.md`,
  `parrot/flows/dev_loop/nodes/failure_handler.py`,
  `parrot/flows/dev_loop/models.py`, `parrot/flows/dev_loop/runner.py`,
  `parrot/flows/dev_loop/dispatcher.py`,
  `tests/flows/dev_loop/test_subagent_parity.py` (new)
- **Responsibility**:
  1. Sync all five `_subagent_data/*.md` prompts with their
     `.claude/agents/` counterparts (carries the wiki-first block into
     `sdd-research.md` — G2 seam 1) and add a **generic full-body parity
     test** covering every dual-sourced prompt (today only
     `sdd-secondopinion` has full parity and `sdd-worker` section-only).
  2. `failure_handler.py:87-89`: replace hard-coded
     `transition="Needs Human Review"` with
     `transition_issue_with_candidates(...)` (candidates:
     `["Needs Human Review", "Blocked", "To Do"]`), as
     `deployment_handoff.py` and `close.py` already do.
  3. `RevisionBrief.acceptance_criteria` optional field; `run_revision`
     (`runner.py:594-673`) re-runs them when present instead of the
     lint-only synthetic brief.
  4. Delete `ClaudeCodeDispatcher._materialize_json_schema` and the pinned
     `json_schema_path=None` plumbing (the Codex dispatcher keeps its own,
     actively used copy).
  5. Add `"review_escalation"` to `_GATE_TTL_CONF_ATTR` (`runner.py:71-76`)
     — currently `gate_ttl_for()` raises `KeyError` for it.
- **Depends on**: —

### Module 2: GraphIndex ontology completion (Phase F)
- **Path**: `parrot/knowledge/graphindex/meta_ontology.py`,
  `tests/knowledge/graphindex/`
- **Responsibility**: add `gi_wiki_pages`/`gi_runs`/`gi_claims` to
  `COLLECTION_TO_KIND` (lines 191-198) with matching `_ENTITY_DEFS` entries,
  and `gi_produced`/`gi_about`/`gi_supported_by`/`gi_contradicts` to
  `EDGE_KIND_TO_COLLECTION` (lines 204-211). After this, `persist.py`'s
  `_upsert_nodes`/`_create_edges` route the new kinds with no code change
  (they look up the dicts). Test: every `NodeKind` and `EdgeKind` member has
  a collection mapping (enum-completeness assertion, prevents recurrence).
- **Depends on**: —

### Module 3: QA repair loop + escalation + stop rule (Phase A)
- **Path**: `parrot/flows/dev_loop/definition.py`,
  `parrot/flows/dev_loop/flow.py`, `parrot/flows/dev_loop/session_state.py`,
  `parrot/flows/dev_loop/models.py`, `parrot/flows/dev_loop/nodes/qa.py`,
  `parrot/flows/dev_loop/nodes/development.py`,
  `parrot/flows/dev_loop/agent_pool.py`
- **Responsibility**:
  1. **G1 topology**: `QAReport.attempt` field; QA node stamps it from
     shared state. New CEL predicates
     (`N = DEV_LOOP_QA_MAX_RETRIES` interpolated at definition build time):
     - `_CEL_QA_RETRY = "result.passed == false && result.attempt < N"` →
       edge `qa → development`
     - `_CEL_QA_EXHAUSTED = "result.passed == false && result.attempt >= N"` →
       edge `qa → failure_handler`
     Mirrored in `flow.py` with Python predicates. `DevelopmentNode` reads
     the prior `QAReport` from shared state on re-entry and appends a
     condensed failure summary (criterion results + lint tail) to the
     redispatch brief; worktree is reused via the existing
     `_ensure_worktree_safe` path. `QaAttemptRecorded` action + reducer
     branch persists the counter in session state.
  2. **G3 escalation**: `DevAgentSpec.escalation_model` (default `""` =
     current behavior). Consulted in two places: `DevAgentPool.run_wave`'s
     single retry (`_next_worker` worker keeps its backend but swaps model),
     and the Module-3 QA-retry redispatch (attempt ≥ 2 uses the escalation
     model when set). **No built-in per-backend ladder in v1** — escalation
     is explicit per spec entry; empty string disables it (decided
     2026-07-26, see §8).
  3. **G4 stop rule**: `should_fan_out(wave, pool_cfg)` — pure function;
     `DevelopmentNode` degrades to the existing single-agent path when the
     first `TaskScheduler.next_wave()` yields < 2 tasks, even if a pool is
     configured.
- **Depends on**: Module 1 (prompt sync, so retried workers get current
  instructions)

### Module 4: dev-loop graph memory wire (Phase B)
- **Path**: `parrot/flows/dev_loop/graph_memory.py` (new),
  `parrot/flows/dev_loop/nodes/research.py`,
  `parrot/flows/dev_loop/nodes/close.py`,
  `parrot/flows/dev_loop/nodes/failure_handler.py`,
  `parrot/flows/dev_loop/nodes/qa.py`
- **Responsibility**: `DevLoopGraphMemory` facade built from
  `DEV_LOOP_GRAPH_MEMORY_PATH` via `build_graph_memory_toolkit()` internals
  (`SQLitePersistence` + `GraphPublisher` + `GraphExpandedRetriever`).
  **Write-back targets the SQLite plane only in v1** (decided 2026-07-26,
  see §8); Arango deployments project the memory kinds later via the
  Module 2 ontology — no dual publish.
  - *Seam 2*: `ResearchNode` prepends `GraphContext.text` (budget-capped,
    citation-serialized) to the research dispatch prompt.
  - *Seam 3*: `close.py`/`failure_handler.py` publish one `GraphUpdate` per
    run — a `RUN` node, `CLAIM` nodes for verified criteria, `PRODUCED`/
    `ABOUT`/`SUPPORTED_BY` edges, `AssertionMeta` provenance. Publish
    failures degrade to a logged warning, never fail the node (matches the
    GraphIndex `persist_warning` convention).
  - *Seam 4*: QA's code-review findings pass through `ground_findings()`;
    findings returning `decision == "revise"` are demoted to notes rather
    than gate-failing.
  - Everything no-ops when `DEV_LOOP_GRAPH_MEMORY_PATH` is unset.
- **Depends on**: Module 1 (seam 1 done there), Module 2 (kinds routable)

### Module 5: plan-approval gate consumer (Phase C)
- **Path**: `parrot/flows/dev_loop/runner.py`
- **Responsibility**: when `DEV_LOOP_REQUIRE_PLAN_APPROVAL=true`, the
  **runner's post-research hook** (decided 2026-07-26, see §8 — no new flow
  node, no `ResearchNode` change) opens
  `open_gate(kind="plan_approval", on_expiry="approve", ...)` with the plan
  summary (Jira key, spec path, task count) as instructions, and
  `await wait_gate(...)` before the development node dispatches. Fail-open
  (advisory) per the documented semantics. Follows the FEAT-322
  `require_deployment_approval` wiring pattern.
- **Depends on**: — (Module 6 recommended before enabling long TTLs in prod)

### Module 6: checkpoint/park for gated runs (Phase D)
- **Path**: `parrot/flows/dev_loop/runner.py`,
  `parrot/flows/dev_loop/session_state.py`
- **Responsibility**: when a gate opens and `DEV_LOOP_GATE_PARK=true`, the
  runner releases its semaphore slot (run state → `parked`; the
  event-sourced state is already fully reconstructible from
  `flow:{run_id}:actions`). **Parking applies uniformly to ALL gate kinds**
  (decided 2026-07-26, see §8) — one code path, no TTL threshold or
  per-kind allowlist. On gate resolution, `resume_run(run_id)` re-acquires
  a slot and continues the wait-side of the gate. v1 is in-process (the
  runner object survives); cross-process crash resume stays out of scope
  (Non-Goals).
- **Depends on**: Module 5 only for end-to-end testing of a parked
  plan-approval gate (unit tests use `deployment_approval`)

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_all_subagent_prompts_parity` | 1 | full-body equality of every `_subagent_data/*.md` vs `.claude/agents/*.md` |
| `test_failure_handler_transition_candidates` | 1 | mock Jira lacking "Needs Human Review" → falls through candidates |
| `test_revision_brief_criteria_rerun` | 1 | `RevisionBrief` with criteria → QA runs them; without → legacy lint-only |
| `test_gate_ttl_review_escalation` | 1 | `gate_ttl_for("review_escalation")` no longer raises |
| `test_every_kind_has_collection` | 2 | all `NodeKind`/`EdgeKind` members present in the ontology mappings |
| `test_persist_run_claim_nodes` | 2 | `_upsert_nodes` routes `run`/`claim`/`wiki_page` without "Unknown kind" |
| `test_qa_retry_edge_bounded` | 3 | failed QA at attempt 1 → development; at attempt N → failure_handler |
| `test_qa_report_attempt_stamped` | 3 | QA node stamps `attempt` from session state |
| `test_definition_flow_parity_with_retry` | 3 | existing parity test extended for the new edge |
| `test_escalation_model_on_retry` | 3 | retry dispatch uses `escalation_model` when set, same model when `""` |
| `test_should_fan_out` | 3 | <2 independent tasks → False; ≥2 → True; no pool → False |
| `test_graph_memory_disabled_noop` | 4 | unset path → facade is None, nodes behave exactly as today |
| `test_run_writeback_publishes_commit` | 4 | close node publishes RUN+CLAIM `GraphUpdate`; failure degrades to warning |
| `test_ground_findings_demotes_revise` | 4 | "revise" findings demoted to notes, "grounded" kept |
| `test_plan_gate_opt_in` | 5 | flag off → no gate; on → gate opened with `on_expiry="approve"` |
| `test_parked_run_releases_slot` | 6 | gate wait releases semaphore; a queued run acquires it |
| `test_resume_run_after_gate` | 6 | resolved gate → `resume_run` completes the flow |

### Integration Tests

| Test | Description |
|---|---|
| `test_repair_loop_e2e` | stub dispatcher fails QA once, passes on retry → flow reaches close with `attempt == 2` |
| `test_repair_loop_exhaustion_e2e` | QA fails N times → failure_handler, Jira escalation comment includes attempt trail |
| `test_graph_memory_round_trip` | run writes back → next run's research context contains the prior RUN/CLAIM nodes |
| `test_parked_plan_gate_e2e` | plan gate + park: slot freed while awaiting, run resumes and completes on approval |

### Test Data / Fixtures

```python
@pytest.fixture
def failing_then_passing_dispatcher():
    """Stub DevLoopCodeDispatcher: QA criteria fail on attempt 1, pass on 2."""

@pytest.fixture
def tmp_graph_memory(tmp_path):
    """SQLitePersistence-backed DevLoopGraphMemory at tmp_path / 'graph.db'."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All unit + integration tests above pass (`pytest tests/flows/dev_loop/ tests/knowledge/graphindex/ -v`)
- [ ] A QA failure with a fixable defect retries development up to `DEV_LOOP_QA_MAX_RETRIES` (default 2) with `QAReport` feedback in the redispatch brief, then — and only then — escalates to `failure_handler`
- [ ] The declarative/imperative parity test covers the new retry edge (definition ↔ flow)
- [ ] `qa_attempts` is persisted as an event-sourced action, replayable via `view=state`
- [ ] With `escalation_model` set, retry dispatches use the stronger model; unset preserves current behavior byte-for-byte
- [ ] `should_fan_out` degrades a configured pool to single-agent when the first wave has < 2 independent tasks
- [ ] Every `NodeKind` and `EdgeKind` member routes to an Arango collection; the enum-completeness test guards regressions
- [ ] All five subagent prompts are byte-identical between `.claude/agents/` and `_subagent_data/`, enforced by a parity test that auto-discovers files
- [ ] Dispatched `sdd-research` prompt contains the wiki-first triage block
- [ ] With `DEV_LOOP_GRAPH_MEMORY_PATH` set: research briefs contain graph context, terminal nodes publish one `GraphUpdate` per run (revertable via `revert_commit`), and code-review findings are grounded; unset: zero behavior change
- [ ] Graph write-back failures never fail the close/failure node (warning only)
- [ ] `DEV_LOOP_REQUIRE_PLAN_APPROVAL=true` opens a fail-open `plan_approval` gate before development; default `false` changes nothing
- [ ] With `DEV_LOOP_GATE_PARK=true`, a run awaiting a gate does not hold a `FLOW_MAX_CONCURRENT_RUNS` slot
- [ ] `FailureHandlerNode` succeeds against a Jira workflow without a "Needs Human Review" transition
- [ ] Revision runs with carried criteria re-verify them (not lint-only)
- [ ] `gate_ttl_for("review_escalation")` returns a TTL instead of raising `KeyError`
- [ ] No breaking changes to existing public API (all new config keys optional, all defaults preserve current behavior)

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified 2026-07-26 against `dev`. Implementation agents MUST NOT reference
> imports, attributes, or methods not listed here without verifying via
> `grep`/`read`. All paths relative to `packages/ai-parrot/src/`.

### Verified Imports

```python
# GraphIndex — all exported (PEP 562 lazy) from the package __init__:
from parrot.knowledge.graphindex import (      # __init__.py:63-111 (__all__), 117-133 (_LAZY_ATTRS)
    GraphPublisher,            # publish.py:37
    GraphUpdate, CommitReceipt,  # schema.py:226, schema.py:262 (NOT in publish.py)
    GraphContextBuilder, ContextBuildConfig, GraphContext,  # context_builder.py:93,45,70
    GroundingEvaluator, GroundingResult,  # grounding.py:96,53
    NodeKind, EdgeKind, AssertionMeta, UniversalNode, UniversalEdge,  # schema.py
    build_graph_memory_toolkit,  # factory.py:203
    SQLitePersistence, SQLiteGraphReader,
    stable_edge_id,            # schema.py:122
)
# NOTE: parrot/knowledge/__init__.py re-exports NOTHING (docstring-only).
# `from parrot.knowledge import GraphPublisher` FAILS — use the full path.

# dev_loop
from parrot.flows.dev_loop.nodes.base import transition_issue_with_candidates  # nodes/base.py:53
from parrot.flows.dev_loop.models import (
    WorkBrief, QAReport, RevisionBrief, DevAgentSpec, AcceptanceCriterion, CriterionResult,
)
from parrot.flows.dev_loop.session_state import GateKind, ActionEnvelope, reduce
```

### Existing Class Signatures

```python
# parrot/flows/dev_loop/definition.py
_CEL_QA_PASSED = "result.passed == true"    # line 49
_CEL_QA_FAILED = "result.passed == false"   # line 50
# Edge pattern (line 105-108; `from` is a keyword → dict unpack):
EdgeDefinition(**{"from": QA}, to=HANDOFF, condition="on_condition", predicate=_CEL_QA_PASSED)

# parrot/flows/dev_loop/flow.py:343-345 — the two edges Module 3 rewires:
flow.add_edge("qa", "deployment_handoff", predicate=_qa_passed)
flow.add_edge("qa", "failure_handler", predicate=_qa_failed)

# parrot/bots/flows/flow/flow.py:249-256
def add_edge(self, from_: str, to: str, *, condition: str = "always",
             predicate: Optional[Union[str, Callable[[Any], bool]]] = None) -> FlowEdge:
# a predicate auto-promotes condition to "on_condition" (lines 284-285)

# parrot/flows/dev_loop/session_state.py
GateKind = Literal["manual_criterion", "deployment_approval",
                   "revision_approval", "plan_approval", "review_escalation"]  # lines 166-172
def open_gate(self, *, kind: GateKind, node_id: NodeId, title: str,
              instructions: str = "", payload_ref: str = "",
              ttl_seconds: Optional[int] = None,
              on_expiry: Literal["fail", "approve"] = "fail",
              ) -> Tuple[str, ActionEnvelope]:                     # lines 862-872
async def wait_gate(self, gate_id: str) -> ApprovalGate:           # line 932
# New actions: add to DevLoopAction discriminated union (lines 406-417) AND a
# branch in `def reduce(state, action)` (line 560; flat `if t == "...":` match,
# unknown action → no-op at line 689). There is NO register_reducer function.

# parrot/flows/dev_loop/models.py
class RevisionBrief(BaseModel):   # line 283; fields 292-304, ALL required:
    repo_path: str; branch: str; pr_number: int; repository: str
    jira_issue_key: str; feedback: str; head_sha: str
class DevAgentSpec(BaseModel):    # line 377; fields 385-393:
    agent: DevAgentBackend        # Literal["claude-code","codex","gemini","nvidia","grok","zai","moonshot"] (372-374)
    model: str = ""
    count: int = 1                # ge=1
class WorkBrief(BaseModel):       # line 138 (alias BugBrief = WorkBrief, line 223)
    acceptance_criteria: List[AcceptanceCriterion]  # line 180, min_length=1
class QAReport(BaseModel):        # line 487; fields 494-511:
    passed: bool; criterion_results: List[CriterionResult]
    lint_passed: bool; lint_output: str = ""; notes: str = ""
    code_review_passed: bool = True; code_review_findings: List[str] = []

# parrot/flows/dev_loop/runner.py
_GATE_TTL_CONF_ATTR: Dict[GateKind, str] = {                       # lines 71-76
    "deployment_approval": "DEV_LOOP_GATE_TTL_DEPLOYMENT",
    "manual_criterion": "DEV_LOOP_GATE_TTL_MANUAL",
    "revision_approval": "DEV_LOOP_GATE_TTL_REVISION",
    "plan_approval": "DEV_LOOP_GATE_TTL_PLAN",
}   # "review_escalation" MISSING → gate_ttl_for (line 79) KeyErrors on it
self._semaphore = asyncio.Semaphore(self.max_concurrent_runs)      # line 182
async def run_revision(self, brief: RevisionBrief, *,
                       run_id: Optional[str] = None) -> FlowResult:  # lines 594-599
# run_revision synthesizes lint-only criteria — comment at line 653

# parrot/flows/dev_loop/agent_pool.py
async def run_wave(self, tasks: List[TaskRef], *, research: ResearchOutput,
                   run_id: str, cwd_for: Callable[[str], str]) -> WaveResult:  # 237-244
def _next_worker(self, failed_worker: PoolWorker) -> PoolWorker:   # line 159 (round-robin)

# parrot/flows/dev_loop/nodes/development.py
def _resolve_pool_config(self, shared: Dict[str, Any]) -> Optional[DevAgentPoolConfig]:  # line 139
async def _execute_pool(self, shared, research, pool_cfg) -> DevelopmentOutput:  # 235-240

# parrot/flows/dev_loop/task_scheduler.py
def next_wave(self) -> List[TaskRef]:                              # line 166

# parrot/flows/dev_loop/nodes/base.py:53-60
async def transition_issue_with_candidates(jira: Any, issue: str,
    candidates: Sequence[str], *, logger: logging.Logger, **kwargs) -> Optional[Dict[str, Any]]:
# already used by deployment_handoff.py:204,397 and close.py:78

# parrot/knowledge/graphindex/context_builder.py
class GraphContextBuilder:            # line 93
    def __init__(self, retriever: GraphExpandedRetriever,
                 entity_resolver: Optional[object] = None) -> None:  # 104-108
    async def build(self, task: str,
                    config: Optional[ContextBuildConfig] = None) -> GraphContext:  # 251-255
class GraphContext(BaseModel):        # line 70: text, entities, node_ids,
                                      # cited_edge_ids, conflicts, budget_used, truncated

# parrot/knowledge/graphindex/publish.py
class GraphPublisher:                 # line 37
    def __init__(self, persistence: Any, ctx: TenantContext) -> None:  # line 47
    async def publish(self, update: GraphUpdate) -> CommitReceipt:     # line 90
    async def revert_commit(self, commit_id: str) -> dict[str, Any]:   # line 140

# parrot/knowledge/graphindex/schema.py
class GraphUpdate(BaseModel):         # line 226; fields 250-259:
    nodes: list[UniversalNode]; edges: list[UniversalEdge]
    removed_edges: list[tuple[str, str, str]]; removed_nodes: list[str]
    agent_id: str; run_id: Optional[str] = None; asserted_by: str
    source: Optional[str] = None; reason: Optional[str] = None; op: str = "publish"
class NodeKind(str, Enum):            # line 36; 9 members (53-61) incl. WIKI_PAGE, RUN, CLAIM
class EdgeKind(str, Enum):            # line 64; 10 members (82-91) incl. PRODUCED, ABOUT,
                                      # SUPPORTED_BY, CONTRADICTS
class AssertionMeta(BaseModel):       # line 94; asserted_by, asserted_at, agent_id,
                                      # run_id, source, confidence (114-119)

# parrot/knowledge/graphindex/grounding.py
class GroundingEvaluator:             # line 96
    def __init__(self, retriever: GraphExpandedRetriever,
                 client: Optional[Any] = None, max_hops: int = 2) -> None:  # 108-113
    async def ground_claim(self, claim: str) -> GroundingResult:            # line 204
class GroundingResult:                # line 53; decision: Literal["grounded","revise"] (74)

# parrot/knowledge/graphindex/meta_ontology.py
COLLECTION_TO_KIND: dict[str, str]    # lines 191-198: 6 entries (document..skill)
KIND_TO_COLLECTION                    # line 201: derived {v: k for k, v in ...}
EDGE_KIND_TO_COLLECTION               # lines 204-211: 6 entries (contains..extends)

# parrot/knowledge/graphindex/factory.py:203-211
async def build_graph_memory_toolkit(db_dir: Path | str, tenant_id: str = "default",
    agent_id: str = "agent", run_id: Optional[str] = None, embedder: Optional[Any] = None,
    client: Optional[Any] = None, dimension: int = DEFAULT_DIMENSION) -> "GraphIndexToolkit":
# returns GraphIndexToolkit lazily imported from parrot_tools.graphindex.toolkit (line 236)
# also: make_stub_tenant_context(tenant_id) (line 45), HashingGraphEmbedder (line 118)
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| retry edge | `build_dev_loop_definition()` edge list | new `EdgeDefinition` | `definition.py:104-111` |
| retry edge (imperative) | `AgentsFlow.add_edge` | Python predicate | `flow.py:343-345` |
| `QaAttemptRecorded` | `DevLoopAction` union + `reduce()` | discriminator branch | `session_state.py:406-417,560` |
| escalation | `DevAgentPool.run_wave` retry path | `_next_worker` + model swap | `agent_pool.py:159,237-244` |
| `should_fan_out` | `DevelopmentNode._resolve_pool_config` | call before pool build | `nodes/development.py:139` |
| `DevLoopGraphMemory` | `GraphPublisher.publish()` | `GraphUpdate` per run | `publish.py:90` |
| `DevLoopGraphMemory` | `GraphContextBuilder.build()` | research context | `context_builder.py:251-255` |
| `DevLoopGraphMemory` | `GroundingEvaluator.ground_claim()` | finding filter | `grounding.py:204` |
| plan gate | `SessionHost.open_gate/wait_gate` | `kind="plan_approval"` | `session_state.py:862-872,932` |
| transition fix | `transition_issue_with_candidates` | replaces literal | `nodes/base.py:53`, `failure_handler.py:87-89` |
| ontology entries | `_upsert_nodes`/`_create_edges` lookups | dict entries only | `persist.py:240` |

### Does NOT Exist (Anti-Hallucination)

- ~~`qa_attempts` / `qa_retries`~~ — no such symbol anywhere in `dev_loop/` (Module 3 creates it)
- ~~`DEV_LOOP_QA_MAX_RETRIES`~~ — not in code or config; only in the two proposal docs (Module 3 creates it)
- ~~`from parrot.knowledge import GraphPublisher`~~ — `parrot/knowledge/__init__.py` re-exports nothing; use `parrot.knowledge.graphindex`
- ~~`GraphUpdate`/`CommitReceipt` defined in `publish.py`~~ — they live in `schema.py:226,262`
- ~~any import of `parrot.knowledge` inside `dev_loop/`~~ — zero exist today (Module 4 adds the first)
- ~~`register_reducer()` / reducer registry~~ — reducers are a flat `if`-match inside `reduce()` (`session_state.py:560`); extend the union + add a branch
- ~~a generic all-files subagent parity test~~ — only `test_secondopinion_brief.py::test_dual_source_bodies_identical` (full, one file) and `test_pool_wiring.py::test_both_copies_have_identical_task_scoped_section` (worker, section-only) exist
- ~~`DevAgentSpec.escalation_model` / `.tier`~~ — no tier/escalation field exists (Module 3 adds it)
- ~~`RevisionBrief.acceptance_criteria`~~ — not a field today (Module 1 adds it)
- ~~`_GATE_TTL_CONF_ATTR["review_escalation"]`~~ — missing; `gate_ttl_for("review_escalation")` currently raises `KeyError`
- ~~`GraphPublisher.commit()`~~ — the method is `publish(update)` (`publish.py:90`)

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Event sourcing (FEAT-322)**: new state = new action model in the
  `DevLoopAction` discriminated union + a branch in pure `reduce()`. Never
  mutate session state directly.
- **Declarative/imperative parity (FEAT-250)**: every topology change lands
  in BOTH `definition.py` (CEL) and `flow.py` (Python predicate), and the
  parity test asserts they match edge-for-edge.
- **`transition_issue_with_candidates`** with ordered synonym candidates —
  the established pattern in `deployment_handoff.py` and `close.py`.
- **Degrade, never fail, on memory writes**: mirror GraphIndex's
  `persist_warning` convention — graph write-back failures log and continue.
- **Opt-in config, navconfig-sourced** — same shape as FEAT-322's
  `require_deployment_approval`.
- **`_subagent_data/` is canonical for dispatch**: `load_subagent_definition`
  reads ONLY the package copy (`_subagent_defs.py:64-88`) despite its
  docstring advertising dual sourcing. Module 1 makes the copies identical
  and the parity test keeps them so; do NOT implement repo-first sourcing
  (rejected — package copy stays canonical for installed deployments).

### Known Risks / Gotchas

- **Infinite retry** — the repair loop MUST be bounded by the interpolated
  CEL cap; a deterministic QA failure (e.g. impossible criterion) would
  otherwise loop. The exhaustion edge is the stop rule; integration test
  covers it.
- **CEL sees only the node result** — `cel_evaluator` coerces the node's
  Pydantic result via `model_dump()`; the retry predicate can only reference
  `QAReport` fields, hence `attempt` must live ON the report, not merely in
  shared state.
- **OR-join execution mode** — the dev-loop executes in explicit-edge mode
  (OR-join at `research`); the new `qa → development` back-edge introduces a
  cycle, which explicit-edge mode supports but `from_definition`'s AND-join
  scheduler does not. The definition remains the declarative source; verify
  the materialization/validation path tolerates the cycle (extend the parity
  test, and if the validator rejects cycles, scope the exemption to
  `on_condition` back-edges).
- **Worktree reuse across attempts** — the retried development run must
  reuse the same worktree (`_ensure_worktree_safe`), or attempt 2 loses
  attempt 1's committed progress.
- **Escalation cost** — `escalation_model` on a 7-backend matrix: only
  validate the model string is non-empty; resolving invalid model names is
  the dispatcher's existing failure domain.
- **Arango collection creation** — new collections must be created on
  ensure/bootstrap (wherever `gi_*` collections are ensured today), not just
  mapped; otherwise upserts fail at runtime on fresh databases.
- **Parked-run lifecycle** — releasing the semaphore while `awaiting_gate`
  means more runs than slots can be live-but-parked; the gate expiry sweep
  (FEAT-322) must still fire for parked runs, and `resume_run` on an
  expired-approved gate must behave identically to an explicit approval.
- **Prompt sync direction** — `.claude/agents/` copies are the newer ones
  (99 vs 80, 328 vs 274 lines); sync repo → package, then hand-verify the
  package copies contain the FEAT-145 per-spec-index instructions.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| — | — | No new dependencies; all building blocks ship in `parrot.knowledge.graphindex` and `parrot.flows.dev_loop` |

---

## 8. Open Questions

> The FEAT-377 proposal closed research with **zero unknowns** (11/11 claims
> high-confidence). The implementation-level decisions surfaced while
> drafting this spec were all resolved by the user on 2026-07-26 — no open
> questions remain.

- [x] Should the spec cover all 6 candidate features or a subset? —
  *Resolved by user (2026-07-26)*: full umbrella, all 6 modules in one spec.
- [x] Default escalation ladder per backend (e.g. `claude-code`:
  `sonnet → opus`)? — *Resolved by user (2026-07-26)*: **explicit only** —
  no built-in ladder in v1; `escalation_model` is set per `DevAgentSpec`
  entry, empty string means escalation disabled. (Applied in Module 3.)
- [x] Graph write-back plane for v1? — *Resolved by user (2026-07-26)*:
  **SQLite-only** — write-back via `build_graph_memory_toolkit` internals;
  Arango deployments project the memory kinds later through the Module 2
  ontology; no dual publish. (Applied in Module 4.)
- [x] `plan_approval` gate placement? — *Resolved by user (2026-07-26)*:
  **runner post-research hook**, mirroring `deployment_approval`'s wiring —
  no new flow node, no `ResearchNode` change. (Applied in Module 5.)
- [x] Park on ALL gate kinds or only long-TTL ones? — *Resolved by user
  (2026-07-26)*: **all gate kinds** when `DEV_LOOP_GATE_PARK=true` —
  uniform semantics, one code path. (Applied in Module 6.)

---

## Worktree Strategy

- **Default isolation unit**: per-spec — one worktree
  (`.claude/worktrees/feat-377-graphindex-as-engineering-devloop`), tasks
  sequential in module order 1 → 2 → 3 → 4 → 5 → 6.
- **Parallelizable in principle**: Modules 1+2 touch disjoint packages
  (dev_loop prompts/nodes vs graphindex ontology) and Modules 5+6 are
  independent of 3+4 — but single-worktree sequential execution is
  recommended: Module 3 depends on 1, Module 4 depends on 1+2, and 5/6 both
  edit `runner.py` (merge hazard if split).
- **Cross-feature dependencies**: none — no other in-flight spec touches
  `dev_loop/` topology or `graphindex/` ontology.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-26 | Jesus Lara + Claude | Initial draft from FEAT-377 proposal (full-umbrella scope) |
| 0.2 | 2026-07-26 | Jesus Lara + Claude | All §8 open questions resolved (explicit escalation, SQLite-only write-back, runner-hook plan gate, park all kinds) |
