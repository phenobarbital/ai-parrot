---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: DevLoop Enhancement — Feature-Mode Topology

**Feature ID**: FEAT-378
**Date**: 2026-07-27
**Author**: Jesus Lara (with Claude)
**Status**: draft
**Target version**: next minor
**Brainstorm**: `sdd/proposals/devloop-enhancement.brainstorm.md` (Recommended Option: B)

---

## 1. Motivation & Business Requirements

### Problem Statement

The `parrot.flows.dev_loop` flow was designed for a strict, closed **bug**
resolution process: `BugIntake` pulls logs from CloudWatch/Elasticsearch, the
`ResearchNode` unconditionally creates a Jira ticket, and acceptance criteria
are anchored to flowtasks or shell commands. For developing **new core
features** (in ai-parrot or satellite libraries) all that boilerplate is
unnecessary, and the flow does not represent the real SDD workflow
(`/sdd-brainstorm → /sdd-proposal → /sdd-spec → /sdd-task → implement →
/sdd-done`).

Today `WorkKind` already admits `"new_feature"` (models.py:116), but that kind
routes **identically** to a bug without intake: `enhancement` and
`new_feature` take the same `IS_NOT_BUG → research` edge (definition.py:95),
which demands Jira, log excerpts, and executable criteria. No feature-oriented
topology exists.

A **feature-mode** of the dev_loop is needed, aligned with the "Graph
Engineering" pattern (fan-out → reduce → synthesize, judge panel, bounded
feedback loop) already evaluated in FEAT-377:

1. **Document intake**: the flow requires a brainstorm/proposal markdown, or a
   spec already resolved by the user — not a BugBrief with log sources.
2. **Planner**: the first node generates (if missing) spec + task index with
   `depends_on` (equivalent to `/sdd-spec` + `/sdd-task`) and sizes the dev
   agent pool from the dependency graph; each agent's LLM/backend comes from
   config.
3. **The diamond**: fan-out of N dev agents → worktree merge → a **synthesis**
   node that integrates and reconciles the results.
4. **QA with Judge Panel**: N configurable judges (one LLM client per judge),
   majority decision, with adversarial review (`sdd-secondopinion`) as one of
   the judges.
5. **Feedback router**: an LLM agent that translates the panel's findings into
   an actionable dev-brief and decides bounded retry / escalate /
   accept-with-notes, mounted on the FEAT-377/G1 QA→Development repair loop.
6. **Feature handoff**: push + **mandatory PR against `dev`** (never direct
   merge), plus a documentation artifact of what was done and a
   wiki/knowledge-graph update (`wikitoolkit` / GraphIndex) — an automated
   "sdd-done" that documents and feeds the repo's memory.

Affected: ai-parrot and satellite-library developers who currently run the SDD
cycle by hand; dev_loop operators who can only automate bugs.

### Goals

- Add a third dev_loop topology (feature-mode) selectable by brief `kind`
  (`IntentClassifierNode` route) or CLI/config, additive to the existing bug
  and revision topologies.
- Accept a `FeatureBrief` (document-based intake) as a discriminated union
  with `WorkBrief` — zero behavior change for existing briefs.
- Planner generates missing SDD artifacts (spec, task index, worktree) and
  sizes the dev pool from `TaskScheduler` waves.
- Explicit `SynthesisNode` owning the semantic merge point after the existing
  fan-out/merge (FEAT-323).
- Configurable N-judge QA panel (`JudgePanelReviewDispatcher`) with majority
  decision and `sdd-secondopinion` as the adversarial judge; tie/broken
  majority → escalate (fail-closed).
- `FeedbackRouterNode` on top of the FEAT-377/A repair loop: `retry`
  (≤ `DEV_LOOP_QA_MAX_RETRIES`) / `escalate` / `accept_with_notes` under a
  hard deterministic envelope; the stop rule is inviolable.
- `FeatureHandoffNode`: draft PR against `dev` (never merge), a
  `docs/features/feat-<id>-<slug>.md` artifact committed to the PR branch,
  wiki page ingest, and `DevLoopGraphMemory.publish_run_outcome()` write-back.
  Jira transition only if a ticket exists.
- Declarative/imperative parity: every new node/edge exists in
  `build_dev_loop_definition` AND in the imperative
  `build_dev_loop_feature_flow()` wiring; parity test extended.
- Event-sourced state: all new state (judge verdicts, feedback decisions,
  docs artifact links) enters as action types + reducers on
  `DevLoopSessionState` (FEAT-322).
- Autonomous run end-to-end: no human gates between intake and draft PR.
- Subagent prompts land in `_subagent_data/` (dispatcher reads only from
  there via `load_subagent_definition`), mirrored in `.claude/agents/`.

### Non-Goals (explicitly out of scope)

- No new sibling package: `parrot/flows/feature_dev/` was rejected in
  brainstorm — see `sdd/proposals/devloop-enhancement.brainstorm.md` Option A.
- No AgentCrew-based implementation (Option C: `run_flow()` cannot express the
  bounded feedback loop) and no prompt-only orchestration (Option D: not a
  library capability).
- Does NOT implement the QA→Development retry edge, `DevLoopGraphMemory`, or
  the RUN/CLAIM ontology — those are FEAT-377 (A, B, F); this feature
  consumes/extends them.
- No merge to `dev` ever — the flow ends at a draft PR; a human merges.
- No `wikitoolkit upsert` of **code** at handoff time — code wiki refresh is
  deferred to post-merge (existing post-commit hook); the wiki never
  describes unmerged code.
- No changes to `WorkBrief` or the three existing `WorkKind` values.
- No cross-process persistence/resume of `SessionHost` (FEAT-D, future).

---

## 2. Architectural Design

### Overview

**Option B (user-confirmed, brainstorm Round 1)**: extend
`parrot/flows/dev_loop/` with a **third topology** (alongside the initial and
revision ones), following the exact precedent of
`build_dev_loop_definition(revision=True)` + `build_dev_loop_revision_flow()`
(runner.py:101): a mode parameter on the definition, new nodes registered in
the same registry, extended factories, and route selection via
`IntentClassifierNode` (new routable kind) or CLI
(`parrot devloop run --brief feature.yaml` where the brief is a
`FeatureBrief`).

Resolved design decisions baked into this overview (from brainstorm Open
Questions — do not re-litigate):

- **Brief model**: new `FeatureBrief` with `kind="feature"` in a discriminated
  union `Brief = WorkBrief | FeatureBrief` (discriminator `kind`) handled by
  the same YAML loader. `WorkBrief` and its 3 kinds remain intact — zero
  behavior change for existing briefs.
- **Routing**: `IntentClassifierNode` routes `kind == "feature"` (also
  forceable by CLI/config). Jira is **optional**: linked only when
  `FeatureBrief.jira_issue_key` is populated; otherwise every Jira step is a
  no-op.
- **Planner owns decomposition**: when only a brainstorm/proposal arrives, the
  `PlannerNode` subagent generates spec + task index (equivalent of
  `/sdd-spec` + `/sdd-task`) and creates the worktree.
- **Judge panel**: N judges from config; default panel of 3 —
  claude-code/claude-sonnet-4-6 + codex/gpt-5.5 via `sdd-secondopinion`
  (adversarial judge) + gemini/auto; **simple majority**; a tie or an
  abstention that breaks majority → **escalate (fail-closed)**. Overrideable
  in brief/env.
- **Feedback router semantics**: LLM router over the G1 repair loop — `retry`
  (≤ `DEV_LOOP_QA_MAX_RETRIES`) / `escalate` / `accept_with_notes`; the stop
  rule cannot be overridden. `accept_with_notes` only inside a **hard
  deterministic envelope**: deterministic QA passed AND all pending findings
  are minor/nit AND failed manual criteria are non-blocking. Outside the
  envelope, only retry/escalate. Notes go to the PR body.
- **SynthesisNode is a separate node** (`dev_loop.synthesis`) — its own
  telemetry/events, individual on_error, explicit owner of the merge point.
  The extra dispatch and NodeId are accepted.
- **No human gate before the PR** — autonomous up to the draft PR; the human
  only reviews/merges.
- **Docs artifact + wiki**: introduces `docs/features/feat-<id>-<slug>.md`
  (`docs/migration/` stays reserved for migrations/breaking changes); the page
  is ingested to the wiki via `LLMWikiToolkit.create_page` so it is queryable
  by `wikitoolkit query`.
- **Wiki timing (hybrid)**: at handoff, publish the run outcome to the
  knowledge graph (`DevLoopGraphMemory`, metadata always valid) and commit the
  docs artifact to the PR branch + wiki page; the code `wikitoolkit upsert` is
  deferred to the merge into dev (existing post-commit hook / post-merge
  automation).

#### User-Facing Behavior

1. The user writes (or already has) a `*.brainstorm.md`, `*.proposal.md`, or
   `*.spec.md` and creates a minimal YAML brief:

   ```yaml
   kind: feature
   document_path: sdd/proposals/mi-feature.brainstorm.md
   document_kind: proposal        # brainstorm | proposal | spec
   jira_issue_key: null           # optional
   dev_agents:                    # optional; default 1 claude-code
     - {agent: claude-code, model: claude-sonnet-4-6, count: 2}
     - {agent: codex, model: gpt-5.5, count: 1}
   judge_panel:                   # optional; default panel of 3
     judges:
       - {agent: claude-code, model: claude-sonnet-4-6}
       - {agent: codex, model: gpt-5.5}        # adversarial (sdd-secondopinion)
       - {agent: gemini, model: auto}
     decision: majority
   ```

2. `parrot devloop run --brief feature.yaml` (same CLI; the classifier routes
   by `kind`). Progress is observable via the existing Redis streams
   (`flow:{run_id}:flow`) / devloop console.
3. The flow runs autonomously: plans, develops in parallel, synthesizes,
   passes the QA panel, iterates with bounded feedback on failure.
4. On completion the user receives: a **draft PR against `dev`** (never a
   merge), a `docs/features/feat-<id>-<slug>.md` artifact inside the PR (also
   ingested as a queryable wiki page), and the run recorded in the knowledge
   graph. The code wiki refreshes when the PR merges. If a Jira ticket exists,
   it is transitioned and commented with the PR.
5. If the panel escalates (dissent, or retries exhausted), the run opens the
   corresponding gate / routes to `failure_handler` with full state for human
   intervention.

### Component Diagram

```
intent_classifier ─(kind=="feature")→ planner → development → synthesis → qa ─(passed)→ feature_handoff → close
                                                     ↑                     │
                                                     └──(feedback_router: retry ≤ N)──┘
                                                                            │
                                        (escalate / attempts ≥ N)→ failure_handler
```

Internal pipeline per node:

1. **Intake** (`IntentClassifierNode` extended): the loader accepts the
   discriminated union `Brief = WorkBrief | FeatureBrief`. Validates
   `FeatureBrief` (document_path exists and is readable; doc_kind coherent),
   publishes it in `shared["feature_brief"]`, and returns kind for the
   conditional edge `_CEL_IS_FEATURE`.
2. **Planner** (`PlannerNode`, node id `planner`): dispatches subagent
   `sdd-planner` (new prompt in `_subagent_data/`) with the document as
   context + graph context from `DevLoopGraphMemory.build_research_context()`
   (FEAT-377/B). The subagent: generates the spec if doc_kind ≠ spec
   (`/sdd-spec`), generates the task index (`/sdd-task`), creates the worktree
   (`git worktree add -b feat-<id>-<slug> ... HEAD` from `dev`), and emits
   `PlannerOutput`. The node derives the effective `DevAgentPoolConfig`: brief
   config if present; otherwise sized by the width of the first
   `TaskScheduler.from_worktree()` wave (capped at `development_pool_max`).
3. **Development**: current `DevelopmentNode` unchanged — topological waves
   (Kahn), sub-worktrees in `isolated` mode, `merge_sequential()` as merge
   point, `aggregate_outputs()` (all FEAT-323).
4. **Synthesis** (`SynthesisNode`): dispatches an agent (claude-code, cwd =
   integrated worktree) that reviews inter-worker consistency (interfaces,
   imports, duplications), runs the integration `pytest`, and commits
   reconciliation adjustments. Output `SynthesisReport{consistent: bool,
   adjustments: [...], summary}`. Reconciliation failure → on_error edge to
   failure_handler.
5. **QA**: current `QANode` with `codereview_dispatcher =
   JudgePanelReviewDispatcher(judges=[...], decision="majority")`. Each judge
   runs an independent review (same neutral brief); the panel: `passed =
   majority`; findings aggregated with `source=<judge>`; the existing advisory
   path (CONFIRM/REJECT/ESCALATE triage + `review_escalation` gate) is
   preserved using `sdd-secondopinion` as the adversarial judge. Individual
   verdicts are recorded as `JudgeVerdictRecorded` actions in session state.
6. **Feedback router** (`FeedbackRouterNode`): on QA-fail, a short read-only
   LLM dispatch (subagent `sdd-feedback`) receives QAReport + verdicts and
   emits a `FeedbackDecision` (see Overview for the resolved semantics and
   the hard envelope).
7. **Feature handoff** (`FeatureHandoffNode`): push branch → draft PR
   `--base dev` (gh/REST, retry-once, `DeploymentHandoffNode` pattern) →
   generates `docs/features/feat-<id>-<slug>.md` (what was implemented,
   decisions, accepted findings, how to test) and commits/pushes it to the PR
   branch → ingests that page to the wiki (`LLMWikiToolkit.create_page`;
   silent degrade with warning if the wiki is not initialized) →
   `DevLoopGraphMemory.publish_run_outcome()` (audited RUN/CLAIM/PRODUCED
   commit; no-op if FEAT-377/B is not configured) → Jira transition + comment
   **only if** a ticket exists. Returns `{status, pr_url, pr_number,
   docs_path, wiki_page_id}`. **Never merges.**
8. **Close**: current `DevLoopCloseNode` (tolerates absent Jira:
   `closed_without_ticket`).

Parity: the new nodes/edges are added to `build_dev_loop_definition` (new mode
parameter), to the factories (`dev_loop.planner`, `dev_loop.synthesis`,
`dev_loop.feedback_router`, `dev_loop.feature_handoff`), and to the imperative
wiring of a `build_dev_loop_feature_flow()` (precedent:
`build_dev_loop_revision_flow`, runner.py:101). The `NodeId` Literal and
session_state reducers are extended with the new ids/actions.

### Integration Points

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/flows/dev_loop/definition.py` | modifies | Mode parameter + feature nodes/edges (alongside FEAT-377/A's retry edge — coordinate) |
| `parrot/flows/dev_loop/flow.py` / `runner.py` | extends | `build_dev_loop_feature_flow()` (precedent: revision, runner.py:101); `DevLoopRunner.run()` accepts FeatureBrief |
| `parrot/flows/dev_loop/models.py` | extends | `FeatureBrief`, `PlannerOutput`, `JudgeSpec`, `JudgePanelConfig`, `SynthesisReport`, `FeedbackDecision` |
| `parrot/flows/dev_loop/nodes/` | extends | `planner.py`, `synthesis.py`, `feedback_router.py`, `feature_handoff.py` (4 new nodes) |
| `parrot/flows/dev_loop/code_review.py` | extends | `JudgePanelReviewDispatcher` registered as `"judge-panel"` |
| `parrot/flows/dev_loop/session_state.py` | modifies | `NodeId` +4, new actions + reducers |
| `parrot/flows/dev_loop/_subagent_data/` | extends | `sdd-planner.md`, `sdd-feedback.md` (+ mirror in `.claude/agents/`) |
| `parrot/flows/dev_loop/factories.py` | modifies | +4 factories |
| `parrot/cli/devloop/` | extends | Brief loader detects FeatureBrief by `kind`; optional wizard |
| `parrot/conf.py` | extends | `DEV_LOOP_JUDGE_PANEL` (json/env), `DEV_LOOP_DOCS_ARTIFACT_DIR` (default `docs/features`), `DEV_LOOP_WIKI_PAGE_INGEST` (bool) |
| FEAT-377 (A, B, F) | depends on | Retry edge + `DevLoopGraphMemory` + RUN/CLAIM ontology must land first |
| Bug-loop / revision topologies | none | Additive; parity test protects the current topology |

No breaking changes: `WorkBrief`/bug path intact; `FeatureBrief` is a new
model discriminated by `kind`.

### Data Models

```python
# parrot/flows/dev_loop/models.py — new models (names/fields are the contract;
# exact validators to be finalized at implementation)

class FeatureBrief(BaseModel):
    kind: Literal["feature"] = "feature"
    document_path: str                      # must exist and be readable
    document_kind: Literal["brainstorm", "proposal", "spec"]
    jira_issue_key: Optional[str] = None    # Jira optional in feature-mode
    dev_agents: Optional[List[DevAgentSpec]] = None
    judge_panel: Optional[JudgePanelConfig] = None

Brief = Annotated[Union[WorkBrief, FeatureBrief], Field(discriminator="kind")]
# NOTE: WorkBrief.kind is WorkKind = Literal["bug","enhancement","new_feature"]
# with default "bug" — verify pydantic v2 discriminated-union compatibility
# with the default; adjust with a tagged-union loader shim if needed.

class JudgeSpec(BaseModel):
    agent: DevAgentBackend                  # reuses the 7-backend Literal (models.py:372)
    model: str = ""                         # empty → backend default from env

class JudgePanelConfig(BaseModel):
    judges: List[JudgeSpec]                 # min_length=1; default panel of 3
    decision: Literal["majority"] = "majority"

class PlannerOutput(BaseModel):
    spec_path: str
    task_index_path: str
    feat_id: str
    branch_name: str
    worktree_path: str
    repo_path: str
    jira_issue_key: Optional[str] = None
    suggested_pool: Optional[DevAgentPoolConfig] = None   # from wave-1 width

class SynthesisReport(BaseModel):
    consistent: bool
    adjustments: List[str] = []
    summary: str = ""

class FeedbackDecision(BaseModel):
    decision: Literal["retry", "escalate", "accept_with_notes"]
    dev_brief: str = ""                     # actionable brief injected on retry
    notes: str = ""                         # appended to PR body on accept_with_notes
```

### New Public Interfaces

```python
# parrot/flows/dev_loop/runner.py (or flow.py, matching the revision precedent)
def build_dev_loop_feature_flow(
    *, dispatcher, jira_toolkit=None, git_toolkit=None, redis_url,
    codereview_dispatcher=None, development_dispatcher_builder=None,
    development_pool_max=4, name="dev-loop-feature",
    publish_flow_events=True,
) -> AgentsFlow: ...

# parrot/flows/dev_loop/definition.py — mode-aware definition
def build_dev_loop_definition(
    *, revision: bool = False, mode: Literal["bug", "feature"] = "bug",
) -> FlowDefinition: ...
# (exact parameter shape may fold `revision` into `mode`; parity test decides)

# parrot/flows/dev_loop/code_review.py
class JudgePanelReviewDispatcher(AbstractCodeReviewDispatcher):
    def __init__(self, *, judges: List[JudgeSpec],
                 decision: str = "majority", redis_url: str, ...): ...
# registered: CodeReviewDispatcherFactory.register("judge-panel", ...)

# parrot/flows/dev_loop/nodes/ — four new DevLoopNode subclasses,
# registered via @register_dev_loop_node:
#   PlannerNode ("planner"), SynthesisNode ("synthesis"),
#   FeedbackRouterNode ("feedback_router"), FeatureHandoffNode ("feature_handoff")
```

---

## 3. Module Breakdown

### Module 1: Feature-mode models + brief loader
- **Path**: `parrot/flows/dev_loop/models.py`, `parrot/cli/devloop/` (loader)
- **Responsibility**: `FeatureBrief`, `JudgeSpec`, `JudgePanelConfig`,
  `PlannerOutput`, `SynthesisReport`, `FeedbackDecision`; discriminated union
  `Brief`; YAML loader detects `kind: feature`. Extend
  `ClaudeCodeDispatchProfile.subagent` Literal with `sdd-planner` /
  `sdd-feedback`.
- **Depends on**: existing models (WorkBrief, DevAgentSpec, DevAgentPoolConfig).

### Module 2: PlannerNode + sdd-planner subagent
- **Path**: `parrot/flows/dev_loop/nodes/planner.py`,
  `parrot/flows/dev_loop/_subagent_data/sdd-planner.md`, mirror in
  `.claude/agents/sdd-planner.md`
- **Responsibility**: document-driven planning dispatch; spec/task-index
  generation when missing; worktree creation; pool sizing from
  `TaskScheduler.from_worktree()` wave-1 width; optional Jira link (no
  creation unless keyed).
- **Depends on**: Module 1; existing `ResearchNode` pattern; FEAT-377/B
  (`DevLoopGraphMemory.build_research_context()` — degrade to no graph
  context if unavailable).

### Module 3: SynthesisNode
- **Path**: `parrot/flows/dev_loop/nodes/synthesis.py`
- **Responsibility**: post-merge reconciliation dispatch in the integrated
  worktree; integration pytest; `SynthesisReport`; on_error → failure_handler.
- **Depends on**: Module 1; existing `DevelopmentNode`/`SubWorktreeManager`
  outputs.

### Module 4: JudgePanelReviewDispatcher
- **Path**: `parrot/flows/dev_loop/code_review.py`, `parrot/conf.py`
- **Responsibility**: generalize `ParallelPerspectiveReviewDispatcher._run_judge`
  (single hardcoded Claude-shaped judge, code_review.py:460,500-506) into an
  N-judge panel built via `build_dispatcher()` per `JudgeSpec`; majority
  decision; judge-down degradation; tie/majority-break → escalate; register
  as `"judge-panel"`; `DEV_LOOP_JUDGE_PANEL` config key.
- **Depends on**: Module 1. (Independent of Modules 2-3 — lowest-contention
  module.)

### Module 5: FeedbackRouterNode + sdd-feedback subagent
- **Path**: `parrot/flows/dev_loop/nodes/feedback_router.py`,
  `parrot/flows/dev_loop/_subagent_data/sdd-feedback.md`, mirror in
  `.claude/agents/`
- **Responsibility**: read-only LLM dispatch mapping QAReport + panel verdicts
  to `FeedbackDecision`; enforce the deterministic `accept_with_notes`
  envelope in Python (not in the prompt); respect
  `qa_attempts < DEV_LOOP_QA_MAX_RETRIES` (FEAT-377/A stop rule).
- **Depends on**: Modules 1, 4; FEAT-377/A (retry edge + attempt counter).

### Module 6: FeatureHandoffNode
- **Path**: `parrot/flows/dev_loop/nodes/feature_handoff.py`, `parrot/conf.py`
- **Responsibility**: push + draft PR `--base dev` (reuse
  `DeploymentHandoffNode` push/PR/retry helpers); generate + commit
  `docs/features/feat-<id>-<slug>.md`; wiki page ingest
  (`LLMWikiToolkit.create_page`, degrade with warning);
  `DevLoopGraphMemory.publish_run_outcome()` (no-op without FEAT-377/B);
  conditional Jira transition. Never merges.
- **Depends on**: Modules 1, 3; FEAT-377/B (graph write-back, optional).

### Module 7: Topology, factories, session state, CLI wiring
- **Path**: `parrot/flows/dev_loop/definition.py`, `flow.py`, `runner.py`,
  `factories.py`, `session_state.py`, `nodes/intent_classifier.py`,
  `parrot/cli/devloop/`
- **Responsibility**: feature-mode definition + imperative
  `build_dev_loop_feature_flow()`; `_CEL_IS_FEATURE` predicate; +4 factories;
  `NodeId` +4; actions/reducers `JudgeVerdictRecorded`,
  `FeedbackDecisionRecorded`, `DocsArtifactLinked`; classifier routes
  `kind=="feature"`; `DevLoopRunner.run()` accepts `FeatureBrief`; parity
  test extended.
- **Depends on**: Modules 1-6; FEAT-377/A (shares definition.py/flow.py edits
  — coordinate/sequence).

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_feature_brief_discriminated_union` | 1 | YAML with `kind: feature` loads `FeatureBrief`; existing bug/enhancement/new_feature briefs still load `WorkBrief` unchanged |
| `test_feature_brief_validation` | 1 | Missing/unreadable `document_path` or incoherent `document_kind` → ValidationError/ValueError before any dispatch |
| `test_planner_pool_sizing` | 2 | Pool derived from wave-1 width, capped at `development_pool_max`; brief-provided pool wins |
| `test_planner_spec_passthrough` | 2 | `document_kind: spec` skips spec generation (subagent brief asserts /sdd-task-only path) |
| `test_planner_jira_optional` | 2 | No `jira_issue_key` → no Jira toolkit calls |
| `test_synthesis_report_failure_routes_on_error` | 3 | Failed reconciliation → on_error edge, no handoff |
| `test_judge_panel_majority` | 4 | 2/3 pass → passed; 1/3 pass → failed |
| `test_judge_panel_tie_escalates` | 4 | Even split or majority-breaking abstention → escalate, never pass |
| `test_judge_panel_judge_down_degrades` | 4 | One judge infra-error → decide with remaining; majority down → escalate (fail-closed) |
| `test_judge_panel_findings_source_tagged` | 4 | Aggregated findings carry `source=<judge>` |
| `test_feedback_envelope_deterministic` | 5 | `accept_with_notes` rejected outside the hard envelope regardless of LLM output |
| `test_feedback_stop_rule_inviolable` | 5 | `qa_attempts ≥ DEV_LOOP_QA_MAX_RETRIES` → router cannot emit retry |
| `test_feature_handoff_never_merges` | 6 | Handoff produces draft PR only; no merge invocation exists |
| `test_feature_handoff_wiki_degrade` | 6 | Wiki uninitialized → warning + PR still created |
| `test_feature_handoff_docs_artifact` | 6 | `docs/features/feat-<id>-<slug>.md` generated and committed to PR branch |
| `test_definition_parity_feature_mode` | 7 | Declarative definition and imperative wiring declare identical nodes/edges (extends existing parity test) |
| `test_bug_topology_unchanged` | 7 | Bug and revision topologies byte-identical to pre-feature-mode snapshot |
| `test_session_state_new_actions` | 7 | `JudgeVerdictRecorded`, `FeedbackDecisionRecorded`, `DocsArtifactLinked` reduce correctly; unknown-action behavior unchanged |

### Integration Tests
| Test | Description |
|---|---|
| `test_feature_flow_happy_path` | FeatureBrief → planner → development (stub dispatcher) → synthesis → QA pass → handoff (PR stubbed) → close, without Jira |
| `test_feature_flow_feedback_retry` | QA fail → feedback router retry with injected dev-brief → second QA pass → handoff (requires FEAT-377/A) |
| `test_feature_flow_escalation` | Panel dissent → failure_handler with full state |
| `test_cli_brief_roundtrip` | `parrot devloop run --brief feature.yaml` parses FeatureBrief and selects feature topology |

### Test Data / Fixtures
```python
@pytest.fixture
def feature_brief(tmp_path):
    doc = tmp_path / "demo.proposal.md"
    doc.write_text("# Proposal: demo\n...")
    return FeatureBrief(document_path=str(doc), document_kind="proposal")

@pytest.fixture
def judge_panel_config():
    return JudgePanelConfig(judges=[
        JudgeSpec(agent="claude-code", model="claude-sonnet-4-6"),
        JudgeSpec(agent="codex", model="gpt-5.5"),
        JudgeSpec(agent="gemini", model=""),
    ])
# Dispatchers/PR/gh/wiki/graph are stubbed — no network or CLI in tests.
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `FeatureBrief` with `kind="feature"` loads via the same YAML loader as
      `WorkBrief`; all pre-existing briefs behave identically (zero behavior
      change — `test_bug_topology_unchanged` green).
- [ ] Feature-mode topology exists in `build_dev_loop_definition` AND in
      imperative `build_dev_loop_feature_flow()` wiring; parity test covers it.
- [ ] `PlannerNode` generates spec + task index when given a
      brainstorm/proposal, skips spec generation for `document_kind: spec`,
      creates the worktree, and sizes the pool from `TaskScheduler` waves.
- [ ] Jira is optional end-to-end in feature-mode: with no
      `jira_issue_key`, no Jira issue is created and close returns
      `closed_without_ticket`.
- [ ] `JudgePanelReviewDispatcher` registered as `"judge-panel"`: N judges
      from config (default 3 incl. `sdd-secondopinion` adversarial), majority
      decision, tie/majority-breaking abstention → escalate (fail-closed),
      judge-down degradation.
- [ ] `FeedbackRouterNode` emits retry/escalate/accept_with_notes;
      `accept_with_notes` only inside the hard deterministic envelope
      (deterministic QA passed ∧ pending findings all minor/nit ∧ failed
      manual criteria non-blocking); the FEAT-377/A stop rule
      (`DEV_LOOP_QA_MAX_RETRIES`) cannot be overridden.
- [ ] `FeatureHandoffNode` ends every successful run in a **draft PR against
      `dev`** — no code path merges; `docs/features/feat-<id>-<slug>.md` is
      generated, committed to the PR branch, and ingested as a wiki page
      (degrading with a warning when wiki/gh are unavailable); run outcome
      published via `DevLoopGraphMemory.publish_run_outcome()` when
      configured (no-op otherwise). No code `wikitoolkit upsert` at handoff.
- [ ] All new state is event-sourced: `JudgeVerdictRecorded`,
      `FeedbackDecisionRecorded`, `DocsArtifactLinked` actions + reducers on
      `DevLoopSessionState`; no mutable state added.
- [ ] Subagent prompts `sdd-planner.md` and `sdd-feedback.md` exist in
      `_subagent_data/` (and mirrored in `.claude/agents/`);
      `ClaudeCodeDispatchProfile.subagent` Literal extended.
- [ ] New conf keys documented and defaulted: `DEV_LOOP_JUDGE_PANEL`,
      `DEV_LOOP_DOCS_ARTIFACT_DIR` (default `docs/features`),
      `DEV_LOOP_WIKI_PAGE_INGEST`.
- [ ] The run is autonomous intake→PR (no human gates); escalation paths open
      the existing gates / route to failure_handler.
- [ ] No new external dependencies; async/await throughout; all unit +
      integration tests pass (`pytest tests/ -v` for the dev_loop suites).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Carried forward from the brainstorm's Code Context and **re-verified
> 2026-07-27 against `dev`** (no dev_loop commits landed since the brainstorm;
> FEAT-377's 12 tasks are in-progress in a worktree, NOT merged).

### Verified Imports
```python
# Confirmed in the codebase (import path is parrot.flows.dev_loop;
# source lives at packages/ai-parrot/src/parrot/…, PEP 420 host):
from parrot.flows.dev_loop.models import WorkBrief, DevAgentSpec, DevAgentPoolConfig
from parrot.flows.dev_loop.flow import build_dev_loop_flow
from parrot.flows.dev_loop.runner import DevLoopRunner, build_dev_loop_revision_flow
from parrot.flows.dev_loop.code_review import CodeReviewDispatcherFactory
from parrot.flows.dev_loop.agent_builder import build_dispatcher
from parrot.flows.dev_loop.nodes.base import register_dev_loop_node, DevLoopNode
from parrot.knowledge.graphindex.publish import GraphPublisher
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/definition.py:61  ✓ verified 2026-07-27
def build_dev_loop_definition(*, revision: bool = False) -> FlowDefinition: ...
# Node-id constants :36-44 (intent_classifier, bug_intake, research, development,
# qa, deployment_handoff, failure_handler, close, revision_handoff)
# CEL predicates :47-50 (_CEL_IS_BUG, _CEL_IS_NOT_BUG, _CEL_QA_PASSED, _CEL_QA_FAILED)

# packages/ai-parrot/src/parrot/flows/dev_loop/flow.py:189
def build_dev_loop_flow(*, dispatcher, jira_toolkit, log_toolkits, redis_url,
    name="dev-loop", publish_flow_events=True, lifecycle_events=True,
    development_dispatcher=None, development_profile=None,
    development_pool_config=None, development_dispatcher_builder=None,
    development_pool_max=4, git_toolkit=None, repos=None,
    codereview_dispatcher=None, require_deployment_approval=False) -> AgentsFlow: ...
# ⚠ Runs in explicit-edge mode: from_definition is AND-join; edges are
#   re-declared imperatively (flow.py:301-307, :332-360). Parity mandatory.

# packages/ai-parrot/src/parrot/flows/dev_loop/runner.py:101  ✓ verified
def build_dev_loop_revision_flow(*, dispatcher, jira_toolkit, git_toolkit,
    redis_url, codereview_dispatcher=None, name="dev-loop-revision",
    publish_flow_events=True) -> AgentsFlow: ...
# ← PRECEDENT for build_dev_loop_feature_flow (second topology, same factories)

# packages/ai-parrot/src/parrot/flows/dev_loop/runner.py:156,522  ✓ verified
class DevLoopRunner:
    async def run(self, brief: WorkBrief, *, run_id=None, initial_task="",
                  extra_shared=None) -> FlowResult: ...  # :522

# packages/ai-parrot/src/parrot/flows/dev_loop/models.py  ✓ verified
WorkKind = Literal["bug", "enhancement", "new_feature"]        # :116
class WorkBrief(BaseModel):                                     # :138
    kind: WorkKind = "bug"                                      # :151
    acceptance_criteria: List[AcceptanceCriterion]              # :180 (min_length=1)
    dev_agents: Optional[List[DevAgentSpec]]                    # :200
    dev_isolation: Optional[Literal["shared", "isolated"]]      # :210
DevAgentBackend = Literal["claude-code","codex","gemini","nvidia","grok","zai","moonshot"]  # :372
class DevAgentSpec(BaseModel):   # :377 — agent, model="", count=1
class DevAgentPoolConfig(BaseModel):  # :396 — agents (min 1), isolation_mode="shared"
class ResearchOutput(BaseModel):  # :312 — jira_issue_key, spec_path, feat_id,
                                  # branch_name, worktree_path, repo_path, log_excerpts
class DevelopmentOutput(BaseModel):  # :452
class QAReport(BaseModel):  # :487 — passed, criterion_results, lint_passed,
                            # notes, code_review_passed, code_review_findings
class CodeReviewVerdict(BaseModel):  # :757 — passed, findings, summary, files_modified
class AdversarialFinding(CodeReviewFinding):  # :793 — source, disposition
                            # Optional[Literal["confirm","reject","escalate"]]
class ClaudeCodeDispatchProfile(BaseModel):  # :519
    subagent: Optional[Literal["sdd-research","sdd-worker","sdd-qa","sdd-codereview"]] = "sdd-worker"  # :527
    # ⚠ new subagents (sdd-planner, sdd-feedback) require extending this Literal
# CodexDispatchProfile-shaped profiles: subagent Literal includes
# "sdd-secondopinion" at models.py:557 and :884 (Codex-only — see Does NOT Exist)

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/intent_classifier.py:33  ✓
class IntentClassifierNode(DevLoopNode):
    def __init__(self, *, redis_url: str, name: str = "intent_classifier"): ...  # :48
    # Does NOT classify with an LLM: validates and propagates brief.kind (:62,:111,:142)

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py:119  ✓
class ResearchNode(DevLoopNode):
    # execute :162-295 — ALWAYS creates Jira (issuetype by kind, :85-89
    # {"bug":"Bug","enhancement":"Story","new_feature":"New Feature"});
    # /sdd-spec, /sdd-task and worktree live in the subagent PROMPT
    # (_subagent_data/sdd-research.md:38-44), not in Python.

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py:88  ✓
class QANode(DevLoopNode):
    # execute :113-249 — deterministic QA (sdd-qa, plan mode :280-285) +
    # pluggable code review + adversarial triage FEAT-375 ALREADY WIRED
    # (:168-186, advisory→_run_finding_triage :393, review_escalation gate :513-524)

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/deployment_handoff.py:46  ✓
class DeploymentHandoffNode(DevLoopNode):
    def __init__(self, *, jira_toolkit, git_toolkit=None, gh_cli_path=None,
        target_repo=None, base_branch="dev", name="deployment_handoff",
        require_deployment_approval=False): ...  # :71
    # execute :100 — _push_branch :283 → draft PR :117-119
    # (gh pr create --draft --base dev :325 / REST :354, retry-once :144-162)

# packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py  ✓ verified
class AbstractCodeReviewDispatcher(ABC):   # :59 — advisory=False :74, review() :80
class CodeReviewDispatcherFactory:         # :133 — register :139, create :148
# Registered: "claude-code" :159, "codex" :180, "gemini" :200,
#             "codex-adversarial" :220 (advisory), "parallel" :292 (advisory)
class ParallelPerspectiveReviewDispatcher: # :293
    # ctor: primary, adversary, judge_dispatcher=None, judge_enabled=False (:312-325)
    # _merge_verdicts :357/:411, _run_judge :460 (SINGLE judge, Claude-shaped
    # profile :500-506 — the exact seam to generalize into the N-judge panel)

# packages/ai-parrot/src/parrot/flows/dev_loop/agent_builder.py:98  ✓
def build_dispatcher(spec: DevAgentSpec, *, redis_url, max_concurrent,
    stream_ttl_seconds, config_getter=...) -> Tuple[DevLoopCodeDispatcher, BaseModel]: ...
# 7 backends with default model per env (:136-201) — the "one LLM per judge" lever

# packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py:43  ✓
class TaskScheduler:
    @classmethod
    def from_worktree(cls, worktree_path, feature_slug): ...  # :111
    def next_wave(self) -> List[TaskRef]: ...   # :166  (Kahn; cycle → ValueError :128)

# packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py:75  ✓
class SubWorktreeManager:
    async def merge_sequential(self, *, resolver: Optional[Resolver] = None) -> MergeReport: ...  # :181
    # ⚠ ASYNC (brainstorm listed it without async). The diamond's merge point
    # (FEAT-323); refresh_all :264, cleanup :297

# packages/ai-parrot/src/parrot/flows/dev_loop/agent_pool.py:89  ✓
class DevAgentPool:
    async def run_wave(self, tasks, *, research, run_id, cwd_for) -> WaveResult: ...  # :237
def aggregate_outputs(results, incomplete) -> DevelopmentOutput: ...  # :340

# packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py  ✓
NodeId = Literal[...]        # :139 — ONLY the 9 current ids; extend for new nodes
GateKind = Literal["manual_criterion","deployment_approval","revision_approval",
                   "plan_approval","review_escalation"]   # :166
class SessionHost:           # :724 — open_gate :862, wait_gate :932, resolve_gate :817
def reduce(...): ...         # :560 — all new state = action + reducer (FEAT-322)

# packages/ai-parrot/src/parrot/knowledge/wiki/  (wikitoolkit)  ✓ verified
class LLMWikiToolkit(AbstractToolkit):  # toolkit.py:46
    async def create_page(...)          # toolkit.py:509 — handoff page ingest
    # ingest_source :140, search :844
# CLI entry: pyproject.toml:115 → parrot.knowledge.wiki.cli:main; click group :596
# build command cli.py:634 (pipeline INLINE — no reusable build_wiki())
# git post-commit hook already runs: `wikitoolkit upsert --changed --quiet`
#   (wiki/claude_code/assets.py:167-175) ← the post-merge code-upsert mechanism

# packages/ai-parrot/src/parrot/knowledge/graphindex/publish.py:37  ✓ verified
class GraphPublisher:
    async def publish(self, update: GraphUpdate) -> CommitReceipt: ...  # :90
# builder.py:56 GraphIndexBuilder.build(sources, ctx) :137
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `PlannerNode` | dispatch pattern of `ResearchNode` | `DevLoopNode` dispatch + subagent prompt | `nodes/research.py:119,162-295` |
| `PlannerNode` pool sizing | `TaskScheduler.from_worktree()` / `next_wave()` | classmethod + wave width | `task_scheduler.py:111,166` |
| `SynthesisNode` | integrated worktree post-`merge_sequential` | reads `DevelopmentOutput` + dispatch cwd | `worktree_manager.py:181` (async) |
| `JudgePanelReviewDispatcher` | `CodeReviewDispatcherFactory.register("judge-panel")` | factory registration | `code_review.py:133,139` |
| `JudgePanelReviewDispatcher` judges | `build_dispatcher(JudgeSpec→DevAgentSpec)` | one dispatcher per judge | `agent_builder.py:98,136-201` |
| `FeedbackRouterNode` | FEAT-377/A repair loop (`_CEL_QA_RETRY`, `qa_attempts`) | feedback-injection + stop rule | FEAT-377 spec (NOT yet on dev) |
| `FeatureHandoffNode` | push/PR helpers of `DeploymentHandoffNode` | reuse `_push_branch` / gh / REST pattern | `nodes/deployment_handoff.py:283,325,354` |
| `FeatureHandoffNode` wiki | `LLMWikiToolkit.create_page` | async call, degrade on failure | `knowledge/wiki/toolkit.py:509` |
| `FeatureHandoffNode` graph | `DevLoopGraphMemory.publish_run_outcome()` | FEAT-377/B facade (no-op if absent) | FEAT-377 spec (NOT yet on dev) |
| New actions/reducers | `session_state.reduce` | action + reducer per FEAT-322 | `session_state.py:560` |

### Key Attributes & Constants
- `conf.DEV_LOOP_CODEREVIEW_AGENT` → `"claude-code"|"codex"|"gemini"|"codex-adversarial"|"parallel"` (parrot/conf.py:928-934) ✓
- `conf.DEV_LOOP_CODEREVIEW_JUDGE` → bool, default False (conf.py:995-999) ✓
- `conf.DEV_LOOP_ADVERSARIAL_MODEL` → `gpt-5.5` (conf.py:986-988) ✓
- Review-backend selection lives in `examples/dev_loop/server.py:598-688`, NOT in `build_dev_loop_flow`
- `_ISSUE_TYPE_BY_KIND = {"bug":"Bug","enhancement":"Story","new_feature":"New Feature"}` (research.py:85-89)
- `docs/migration/feat-<id>-<slug>.md` — existing manual convention (6 files), no automation

### Does NOT Exist (Anti-Hallucination)

Re-verified 2026-07-27 on `dev` (FEAT-377 worktree not merged):

- ~~Feature-mode / `feature_mode` / `build_dev_loop_definition(mode=...)`~~ — only `revision: bool` exists; `enhancement`/`new_feature` route identically to research.
- ~~LLM classification in `IntentClassifierNode`~~ — it only validates and propagates `kind`.
- ~~`qa → development` edge / `_CEL_QA_RETRY` / `qa_attempts` / `DEV_LOOP_QA_MAX_RETRIES`~~ — proposed by FEAT-377 (TASK-1910/1911), **not yet on dev**. Verify merge status before Module 5/7 work.
- ~~`graph_memory.py` / `DevLoopGraphMemory`~~ — FEAT-377 TASK-1914/1915, **not yet on dev**. `FeatureHandoffNode`/`PlannerNode` must no-op/degrade when absent.
- ~~N-judge panel / `judges: List[...]`~~ — only a single optional `judge_dispatcher`, default off, hardcoded Claude-shaped profile (code_review.py:500-506).
- ~~Reusable `build_wiki()`~~ — the `wikitoolkit build` pipeline is inline in the click command (wiki/cli.py:634); `LLMWikiToolkit.rebuild_index` only regenerates `index.md`.
- ~~Docs generation / PR in `/sdd-done`~~ — sdd-done pushes and merges to local base; it never opens a PR nor writes documentation.
- ~~PR creation outside `deployment_handoff.py`~~ — `revision_handoff` is forbidden from creating PRs (revision_handoff.py:10).
- ~~`docs/features/`~~ — does not exist yet; **this feature introduces it** (resolved Q; `docs/migration/` stays for migrations/breaking changes).
- ~~`sdd-secondopinion` in `ClaudeCodeDispatchProfile.subagent`~~ — Codex-only (models.py:527 vs :557,:884).
- ~~`gate_ttl_for("review_escalation")`~~ — KeyError; that TTL is read directly from conf (qa.py:473).
- ~~Cross-process persistence/resume of `SessionHost`~~ — in-memory per run; checkpoint/resume is FEAT-D (future).
- ~~Sync `merge_sequential`~~ — it is `async def` (worktree_manager.py:181); await it.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Second-topology precedent**: mirror `build_dev_loop_revision_flow()`
  (runner.py:101) exactly — same factories, imperative `add_edge` re-declaration,
  parity test. `from_definition` is AND-join (flow.py:301-307); every
  conditional edge MUST be re-declared imperatively.
- **Node pattern**: subclass `DevLoopNode`, register with
  `@register_dev_loop_node`, dispatch via the injected dispatcher; behavioral
  logic that belongs to the subagent goes in the `_subagent_data/*.md` prompt
  (see `sdd-research.md` — /sdd-spec, /sdd-task and worktree creation live in
  the prompt, not Python).
- **Event-sourced state only** (FEAT-322): new state = action type + reducer
  on `DevLoopSessionState`; never mutate.
- **Config keys in `parrot/conf.py`** with env override, following the
  `DEV_LOOP_CODEREVIEW_*` block style (conf.py:928-999):
  `DEV_LOOP_JUDGE_PANEL` (JSON), `DEV_LOOP_DOCS_ARTIFACT_DIR`
  (default `docs/features`), `DEV_LOOP_WIKI_PAGE_INGEST` (bool).
- Async/await throughout; `uv` + venv; Google-style docstrings + strict type
  hints; Pydantic models for every structure; `self.logger`.

### Known Risks / Gotchas
- **FEAT-377 coupling (biggest risk)**: FEAT-377 A/B/F touch
  `definition.py`/`flow.py`/`models.py`/`session_state.py` and are
  in-progress in their own worktree. **Sequence FEAT-377 merge before
  Modules 5-7**, or coordinate in the same worktree queue. Degradations when
  FEAT-377 pieces are absent: retry edge missing → feedback router can only
  escalate/accept; `DevLoopGraphMemory` missing → graph context and
  write-back are no-ops.
- **Nonexistent/unreadable document** → classifier fails validation
  (ValueError) before spending a dispatch; clean `failed` run.
- **Spec already resolved** (`document_kind: spec`): planner skips `/sdd-spec`,
  goes straight to `/sdd-task` (or validates an existing index).
- **Task index without depends_on / single task** → pool degrades to
  single-agent (current `TaskScheduler.from_index_file` → `None` / single
  wave behavior).
- **Dependency cycle** → `TaskScheduler` raises ValueError → planner reports
  and the run fails with diagnostics (no dev dispatch).
- **Judge down / infra error** → panel degrades as today (`_resolve_side` →
  nit advisory) and decides with remaining judges; majority of panel down →
  escalate (fail-closed).
- **Panel tie** (even N or abstentions) → escalate, never pass by default.
- **Retries exhausted** (`qa_attempts ≥ DEV_LOOP_QA_MAX_RETRIES`) → FEAT-377/A
  stop rule routes to failure_handler; the feedback router cannot override.
  Enforce the `accept_with_notes` envelope in Python, not in the prompt.
- **Wiki uninitialized / `gh` absent** → wiki page ingest skipped with
  warning (does not block the PR); PR falls back to REST with `GITHUB_TOKEN`;
  if both fail → `status: blocked` (`_mark_blocked` pattern, without Jira).
- **No Jira**: all Jira steps are no-ops; `close` returns
  `closed_without_ticket` (already supported).
- **Discriminated union with defaults**: `WorkBrief.kind` defaults to `"bug"`;
  confirm pydantic v2 discriminator behavior with defaulted discriminators in
  the union loader (shim in the YAML loader if necessary).
- **dispatcher.py is 3053 lines** — do not grow it; new logic goes in nodes /
  code_review.py / subagent prompts.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| (none new) | — | gh CLI + aiohttp (PR), click (CLI), redis already present |
| `LLMWikiToolkit` (internal) | — | Handoff docs-page ingest via `create_page` (wiki/toolkit.py:509); code upsert is post-merge — no reusable `build_wiki()` |

---

## 8. Open Questions

> All brainstorm questions were resolved before this spec (see
> `sdd/proposals/devloop-enhancement.brainstorm.md`). Echoed here for the
> decision audit trail.

- [x] Type/base? — *Resolved in brainstorm (Jesus)*: feature / dev.
- [x] New package or dev_loop variant? — *Resolved in brainstorm (Jesus)*: variant inside `parrot/flows/dev_loop/`.
- [x] Relationship with FEAT-377? — *Resolved in brainstorm (Jesus)*: this feature depends on FEAT-377 (A, B, F); it consumes the repair loop and DevLoopGraphMemory.
- [x] Who decomposes into tasks when only a brainstorm/proposal arrives? — *Resolved in brainstorm (Jesus)*: the PlannerNode generates spec + task index (equivalent of /sdd-spec + /sdd-task).
- [x] QA panel composition? — *Resolved in brainstorm (Jesus)*: N judges via config (default 3, one LLM per judge via dispatchers), majority; adversarial = sdd-secondopinion as a judge; tie/strong dissent → escalate.
- [x] Feedback agent semantics? — *Resolved in brainstorm (Jesus)*: LLM router over the G1 repair loop — retry (≤ DEV_LOOP_QA_MAX_RETRIES) / escalate / accept_with_notes; stop rule inviolable.
- [x] Human gate before the PR? — *Resolved in brainstorm (Jesus)*: no — autonomous up to the draft-PR; the human only reviews/merges.
- [x] Mode selection and Jira? — *Resolved in brainstorm (Jesus)*: IntentClassifier routes the feature kind (also forceable via CLI/config); Jira optional.
- [x] New `kind` literal (`"feature"`) or re-route `"new_feature"`? — *Resolved in brainstorm (Jesus)*: new `FeatureBrief` with `kind="feature"`, discriminated union `Brief = WorkBrief | FeatureBrief` through the same YAML loader. `WorkBrief` and its 3 current kinds intact — zero behavior change for existing briefs.
- [x] Default panel and even-N rule? — *Resolved in brainstorm (Jesus)*: claude-code/claude-sonnet-4-6 + codex/gpt-5.5 via sdd-secondopinion (adversarial judge) + gemini/auto; simple majority; tie or majority-breaking abstention → escalate (fail-closed). Overrideable in brief/env.
- [x] `SynthesisNode` separate or a DevelopmentNode phase? — *Resolved in brainstorm (Jesus)*: separate node `dev_loop.synthesis` — own telemetry/events, individual on_error, explicit merge-point owner. Extra dispatch and NodeId accepted.
- [x] Docs artifact location and wiki ingest? — *Resolved in brainstorm (Jesus)*: introduces `docs/features/feat-<id>-<slug>.md` (docs/migration/ reserved for migrations/breaking changes), ingested as a wiki page via `LLMWikiToolkit.create_page` to be queryable by `wikitoolkit query`.
- [x] Wiki update from the PR branch or post-merge? — *Resolved in brainstorm (Jesus)*: hybrid — at handoff, publish the run outcome to the knowledge graph (`DevLoopGraphMemory`, metadata always valid) and commit the docs artifact to the PR branch + wiki page; the code `wikitoolkit upsert` is deferred to the merge into dev (existing post-commit hook / post-merge automation). The wiki never describes code that didn't land.
- [x] When does `accept_with_notes` apply? — *Resolved in brainstorm (Jesus)*: hard deterministic rule, no extra quorum — only if deterministic QA passed AND all pending findings are minor/nit AND failed manual criteria are non-blocking. The LLM router decides inside that envelope; outside it, only retry/escalate. Notes go to the PR body.

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — one worktree, tasks sequential.
- **Rationale** (brainstorm Parallelism Assessment): the topology, models and
  session state form a coupled core with a shared parity test
  (`definition.py`, `flow.py`, `models.py`, `session_state.py`,
  `factories.py` — high contention); parallelizing inside the feature would
  produce painful merges in the same files.
- **Optional parallel extraction**: Module 4 (`dev-loop-judge-panel`,
  `code_review.py` + conf) is the only low-contention capability and could be
  split into a sibling spec/worktree if throughput matters.
- **Cross-feature dependencies**: **FEAT-377 (graphindex-as-engineering-devloop)
  must merge to `dev` first** (its 12 tasks — notably TASK-1910/1911 repair
  loop and TASK-1914/1915 graph memory — touch the same core files). Sequence
  this feature's worktree after FEAT-377 lands, or queue it in the same
  worktree pipeline.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-27 | Jesus Lara (with Claude) | Initial draft from devloop-enhancement.brainstorm.md (Option B; 15/15 questions resolved) |
