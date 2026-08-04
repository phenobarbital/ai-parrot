---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Dev-Flow — SDD-Oriented AgentsFlow for Feature Development

**Feature ID**: FEAT-412
**Date**: 2026-08-05
**Author**: Jesus Lara (with Claude)
**Status**: approved
**Target version**: next minor

---

## 1. Motivation & Business Requirements

### Problem Statement

`parrot.flows.dev_loop` is complete but **rigid for feature development**: it
was designed around operations (Bug Intake pulling CloudWatch/Elasticsearch
logs, mandatory Jira tickets, `affected_component` questioning, QA oriented to
"did the bug get fixed"). That completeness is exactly right for operations
and bug triage — and exactly wrong for developing a new feature, where none of
that boilerplate applies.

FEAT-378 added a **feature-mode topology** (planner → development pool →
synthesis → judge-panel QA → feedback router → draft PR), but its intake is
**document-only**: it requires an already-written brainstorm/proposal/spec
(`FeatureBrief.document_path`, validated eagerly at model construction —
`models/base.py:780`) and runs **fully autonomously** ("no human gates between
intake and draft PR" — FEAT-378 Goals). The real SDD workflow, however, starts
earlier and is interactive: a developer describes an *Enhancement* or *New
Feature* in **natural language**, `/sdd-brainstorm` explores it, and **Open
Questions are resolved with the human** before `/sdd-spec` freezes decisions.

Additionally, the HITL surface needed for that interaction does not exist in
the example server today: gates live in the library
(`DevLoopRunner.resolve_gate` — `runner.py:713`; REST handler in
`dev_loop/commands.py:70`), but `examples/dev_loop/server.py` never mounts a
resolve route, and `static/index.html` renders gates only as a read-only
audit trail. The `ApprovalGate` model itself only supports approve/reject +
free-text comment (`session_state.py:225`), not structured question/answer.

We need a **new AgentsFlow — `dev-flow` —** that models the actual SDD
development cycle end-to-end:

```
NL request (enhancement | new_feature)  ──► brainstorm (+ HITL Open Questions)
        or an existing SDD document ─────► spec + tasks ──► multi-agent
development ──► synthesis ──► QA ──► draft PR
```

with a matching development-only example server (`server_dev.py`) and a
development-only UI template (`static/dev.html`).

### Goals

1. New package **`parrot/flows/dev_flow/`** implementing the `dev-flow`
   topology as a first-class flow, cleanly separated from the operations
   flow (`dev_loop`) — see the placement rationale in §2 Overview.
2. **Intent chosen by the user in the UI** (no LLM classification): three
   intents — `enhancement`, `new_feature` (both natural-language) and
   `feature` (existing SDD brainstorm/proposal — the existing
   `FeatureBrief`).
3. **`IdeationNode`**: converts the natural-language request into a
   committed SDD document via a new `sdd-ideation` subagent — a full
   `sdd/proposals/<slug>.brainstorm.md` (options analysis) for
   `new_feature`, a lighter `sdd/proposals/<slug>.proposal.md` (scope +
   rationale, no options analysis) for `enhancement` — resolving Open
   Questions through HITL. When the target document already exists, the
   subagent resumes/extends it (never overwrites, never suffixes).
4. **HITL Open-Questions gate**: a single gate carrying ALL open questions of
   a round (new `GateKind` `"open_questions"` with structured
   `questions`/`answers`), answered in one round-trip over the existing
   WS-read/REST-write channel; bounded re-ask rounds.
5. **Maximal reuse** of the FEAT-378 feature-mode chain: `planner`,
   `development` (multi-agent pool), `synthesis`, `qa` (judge panel),
   `feedback_router`, `feature_handoff` (draft PR against `dev`),
   `failure_handler`, `close` are consumed as already-registered
   `dev_loop.*` node types — not reimplemented.
6. **`examples/dev_loop/server_dev.py`**: aiohttp server for the dev-flow —
   no CloudWatch toolkits, no mandatory Jira, WITH the gate-resolution route
   mounted (the missing HITL write path).
7. **`examples/dev_loop/static/dev.html`**: development-only UI — intent
   picker, NL intake, document intake, interactive Open-Questions panel,
   run timeline, draft-PR summary. `index.html` stays untouched for ops.
8. Flow terminates with a **draft PR** containing the feature (identical
   terminal behavior to feature-mode's `FeatureHandoffNode`).

### Non-Goals (explicitly out of scope)

- **No changes to the three existing dev_loop topologies** (bug, revision,
  feature). `dev_flow` is additive; `server.py` + `index.html` remain the
  operations console. (The gate-model extension in §3 Module 2 is additive
  and backward-compatible.)
- **No LLM-based intent classification** — the user picks the intent in the
  UI (decided 2026-08-05; see §8).
- No research-first proposal pipeline: the `enhancement` intent generates a
  *light* proposal (scope, rationale, impact, open questions), not the deep
  `/sdd-proposal` research artifact. An existing full proposal is accepted
  through the `feature` intent (`document_kind="proposal"`), which
  `PlannerNode` already handles.
- No cross-process gate persistence/resume (same limitation as FEAT-377
  TASK-1917 — in-process park/resume only).
- No Jira creation anywhere: like feature-mode, Jira is link-only when
  `jira_issue_key` is provided.
- No merge to `dev` ever — the flow ends at a draft PR; a human merges.
- No changes to `afd.html` (dead design mockup, never routed).

---

## 2. Architectural Design

### Overview

**A new sibling package `parrot/flows/dev_flow/`** — NOT a fourth flag on
`build_dev_loop_definition`.

> **Relationship to FEAT-378's Option A rejection**: FEAT-378 rejected a
> sibling package *for feature-mode* because feature-mode shares the
> dev_loop's intake (`IntentClassifierNode`) and event plumbing wholesale.
> `dev-flow` is different in kind, not degree (decided 2026-08-05, see §8):
> the current flow front-loads operations concerns (CloudWatch logs, Bug
> Intake, mandatory Jira, bug-resolution QA questioning) that a development
> flow would have to disable with an ever-growing pile of flags. Separating
> `bug_flow` (dev_loop) from `dev_flow` keeps each topology's concerns
> clean. Reuse happens at the right altitude: **node types, models, session
> state, streaming, dispatcher and runner machinery are imported from
> `dev_loop`**, only the intake nodes and the topology are new.

### Component Diagram

```
                       DevFlowBrief (union, user-selected intent)
                                      │
                              ┌───────▼────────┐
                              │   dev_intake   │  validates brief, routes by kind
                              └───────┬────────┘
              kind ∈ {enhancement,    │      kind == "feature"
                      new_feature}    │      (brainstorm/proposal given)
                     ┌────────────────┴─────────────────────┐
                     ▼                                      │
             ┌──────────────┐   open_questions gate         │
             │   ideation   │◄──── (HITL, ≤ N rounds, ──────┼── WS read /
             └──────┬───────┘       single gate per round)  │   REST write
                    │  emits FeatureBrief(document_kind=    │
                    │   "brainstorm" [new_feature] |        │
                    │   "proposal"   [enhancement])         │
                    └────────────────┬──────────────────────┘
                                     ▼
    planner ──► development ──► synthesis ──► qa ──(passed)──► feature_handoff ──► close
                    ▲                          │                     ▲   (draft PR)
                    │                          ▼                     │
                    └──(retry, bounded)── feedback_router ──(accept_with_notes)
                                               │
                                               └──(escalate)──► failure_handler
                              (+ on_error fan-in from every middle node)
```

Everything from `planner` onward is byte-identical in behavior to the
FEAT-378 feature-mode graph (`definition.py:_build_feature_definition`) —
same node types, same CEL predicates, same bounded repair loop
(`FeedbackRouterNode._retry_allowed()` enforces `DEV_LOOP_QA_MAX_RETRIES`).

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `dev_loop.planner/development/synthesis/qa/feedback_router/feature_handoff/failure_handler/close` node types | reuses | Referenced by type name in the new `FlowDefinition`; factories reused via `build_dev_loop_node_factories` (`factories.py`) |
| `FeatureBrief` (`models/base.py:725`) | reuses | `IdeationNode` output; `feature` intent passthrough |
| `DevLoopNode` + `register_dev_loop_node` (`nodes/base.py:193/:174`) | extends | Base class + idempotent registry for the two new node types |
| `SessionHost.open_gate/wait_gate/resolve_gate` (`session_state.py:1079/:1149/:1034`) | extends | New gate kind + structured answers (additive fields) |
| `dev_loop/commands.py` (`resolve_gate_handler:70`, `register_command_routes`) | extends + mounts | `ResolveGateRequest` gains `answers`; `server_dev.py` mounts the routes |
| `DevLoopRunner` (`runner.py`) | extends | `DevFlowRunner` subclass hosting the single dev-flow topology |
| `flow_stream_ws` (`dev_loop/streaming.py`) | reuses | Same WS multiplexer (`view=flow\|dispatch\|both\|state`) |
| `ClaudeCodeDispatcher` + `load_subagent_definition` (`_subagent_defs.py:86`) | extends | New `sdd-ideation` subagent definition (dual-mode: brainstorm/proposal) |
| `AgentsFlow` explicit-edge mode (`parrot/bots/flows/flow/flow.py`) | uses | OR-joins at `planner` and `failure_handler` require explicit-edge execution (same engine limitation as dev_loop — `definition.py` module docstring) |
| `DevLoopWikiSearch` (`wiki_search.py`) | reuses | Repo context injected into the `sdd-ideation` dispatch |
| `examples/dev_loop/llm_catalog.py` | reuses | Backend/judge catalogs for `/api/config` |

### Data Models

```python
# parrot/flows/dev_flow/models.py  (NEW)

DevRequestKind = Literal["enhancement", "new_feature"]

class DevRequestBrief(BaseModel):
    """Natural-language intake for the dev-flow (enhancement / new feature)."""
    kind: DevRequestKind                       # user-selected in the UI
    title: str                                 # short name; slug source
    description: str                           # the natural-language request
    context: str = ""                          # optional extra context/links
    jira_issue_key: Optional[str] = None       # link-only, like FeatureBrief
    dev_agents: Optional[List[DevAgentSpec]] = None
    judge_panel: Optional[JudgePanelConfig] = None

# Discriminated union on `kind` — mirrors dev_loop's `Brief` pattern.
DevFlowBrief = Annotated[
    Union[DevRequestBrief, FeatureBrief], Field(discriminator="kind")
]

class IdeationOutput(BaseModel):
    """Contract for the sdd-ideation subagent's final JSON."""
    document_path: str                # sdd/proposals/<slug>.brainstorm.md | .proposal.md
    document_kind: Literal["brainstorm", "proposal"]  # brainstorm=new_feature, proposal=enhancement
    slug: str
    resumed_existing: bool = False    # target doc existed and was extended in place
    open_questions: List[str] = []    # unresolved [ ] items this round
    summary: str = ""
    committed: bool = False           # doc committed to base_branch?
```

```python
# parrot/flows/dev_loop/session_state.py  (EXTEND — additive, backward-compatible)

GateKind = Literal[
    "manual_criterion", "deployment_approval", "revision_approval",
    "plan_approval", "review_escalation",
    "open_questions",                          # NEW (FEAT-412)
]

class ApprovalGate(_Frozen):
    ...                                        # existing fields unchanged
    questions: List[str] = []                  # NEW — structured questions
    answers: Dict[str, str] = {}               # NEW — question -> answer

class GateResolved(_ActionBase):
    ...                                        # existing fields unchanged
    answers: Dict[str, str] = {}               # NEW
```

```python
# parrot/flows/dev_loop/commands.py  (EXTEND)

class ResolveGateRequest(BaseModel):
    resolution: Literal["approved", "rejected"]
    resolved_by: str
    comment: str = ""
    client_seq: int = 0
    answers: Dict[str, str] = {}               # NEW — required non-empty by the
                                               # host when gate.kind == "open_questions"
                                               # and resolution == "approved"
```

Old persisted envelopes keep validating (all new fields default). The reducer
folds `answers` into the gate exactly like `comment`.

### New Public Interfaces

```python
# parrot/flows/dev_flow/definition.py
def build_dev_flow_definition() -> FlowDefinition: ...
    # flow="dev-flow"; nodes: dev_flow.dev_intake, dev_flow.ideation,
    # dev_loop.planner, dev_loop.development, dev_loop.synthesis,
    # dev_loop.qa, dev_loop.feedback_router, dev_loop.feature_handoff,
    # dev_loop.failure_handler, dev_loop.close

# parrot/flows/dev_flow/flow.py
def build_dev_flow(
    *, dispatcher, redis_url: str,
    jira_toolkit=None, git_toolkit=None, wiki_toolkit=None,
    codereview_dispatcher=None, development_dispatcher_builder=None,
    development_pool_max: int = 4, graph_memory=None,
    wiki_search=None, skip_qa: bool = False,
    require_plan_approval: bool = False,   # build-time default; per-run
                                           # override via shared state (§2)
    ideation_max_rounds: int | None = None,
    name: str = "dev-flow", publish_flow_events: bool = True,
) -> AgentsFlow: ...
    # mirrors build_dev_loop_feature_flow (runner.py:178) — declarative
    # materialize, explicit-edge execution.

# parrot/flows/dev_flow/runner.py
class DevFlowRunner(DevLoopRunner):
    async def run(self, brief: DevFlowBrief, *, run_id=None,
                  initial_task="", extra_shared=None) -> FlowResult: ...
    # single topology: no per-kind flow switching; inherits gates/park/
    # resume/streams/bundle machinery unchanged.
```

**CEL routing predicates** (`dev_flow/definition.py`):

```
dev_intake → ideation : 'result.kind == "enhancement" || result.kind == "new_feature"'
dev_intake → planner  : 'result.kind == "feature"'
ideation → planner    : on_success
planner … close         : identical to _build_feature_definition (FEAT-378)
on_error fan-in         : every middle node → failure_handler
```

The `dev_intake → planner` / `ideation → planner` merge is an **OR-join**:
like dev_loop, the graph executes in the engine's explicit-edge mode
(`AgentsFlow.add_node()/add_edge()`), with the `FlowDefinition` kept as the
declarative source for materialization/validation/parity.

### The Open-Questions HITL round-trip (normative)

1. `IdeationNode` dispatches `sdd-ideation` with the `DevRequestBrief`
   (+ optional `DevLoopWikiSearch` repo context). The subagent writes the
   intent's document — `new_feature` →
   `sdd/proposals/<slug>.brainstorm.md` (options analysis +
   recommendation), `enhancement` → `sdd/proposals/<slug>.proposal.md`
   (light: scope, rationale, impact — no options analysis) — with FEAT-145
   frontmatter (`type: feature`, `base_branch: dev`) and returns an
   `IdeationOutput` JSON.
   **Existing-document policy (resolved 2026-08-05)**: when the target
   path already exists, the subagent reads it and RESUMES/EXTENDS it in
   place (new Open-Questions rounds on the same document,
   `resumed_existing=true`); it never overwrites blindly and never creates
   `-2`-suffixed copies. The resolved `document_path` is surfaced in the
   gate title so the user can detect (and reject) an unintended reuse.
2. If `open_questions` is non-empty: the node opens ONE gate —
   `host.open_gate(kind="open_questions", node_id="ideation",
   title=..., questions=[...], ttl_seconds=DEV_FLOW_GATE_TTL_QUESTIONS,
   on_expiry="fail")` — and `await host.wait_gate(gate_id)`. Park/resume
   (`DEV_LOOP_GATE_PARK`) applies unchanged: a run awaiting answers frees
   its concurrency slot.
3. The UI receives `gate/opened` on the state WS, renders one input per
   question, and POSTs `.../gates/{gate_id}/resolve` with
   `resolution="approved"` + `answers={question: answer, ...}`.
   Partial answers are allowed (unanswered questions stay open in the doc).
4. The node re-dispatches `sdd-ideation` (resume) with the answers; the
   subagent marks answered questions `[x] … — *Resolved*: <answer>` in the
   document (the exact convention `/sdd-spec` §2b consumes). A re-dispatch
   MAY surface new open questions → new gate, bounded by
   `DEV_FLOW_IDEATION_MAX_ROUNDS` (default 2). Questions still `[ ]` when
   rounds are exhausted remain in the document and flow into the spec's §8
   via the planner — they do NOT block the run.
5. `resolution="rejected"` = the user aborts the ideation → the node
   raises, the `on_error` edge routes to `failure_handler`.
   Gate expiry is **fail-closed** (`on_expiry="fail"` → `GateExpired` →
   failure path): silence is not consent for spec decisions.
6. The subagent commits the document to `base_branch` (SDD auto-commit
   rule — worktrees created later by `sdd-planner` must see it);
   `IdeationOutput.committed` reports it and the node fails fast when
   `False`.
7. Terminal output: the node constructs
   `FeatureBrief(document_path=..., document_kind=<IdeationOutput.document_kind>,
   jira_issue_key/dev_agents/judge_panel passthrough)` and publishes it to
   `ctx["feature_brief"]` — exactly the key `PlannerNode` reads
   (`nodes/planner.py`, spec FEAT-378 §3 Module 2).

### `server_dev.py` and `dev.html` (deliverable shape)

`examples/dev_loop/server_dev.py` mirrors `server.py`'s structure with these
deltas (seams verified in `server.py`):

| Concern | `server.py` (ops) | `server_dev.py` (dev-flow) |
|---|---|---|
| `GET /` | `static/index.html` (`:1027`) | `static/dev.html` |
| Flow | `build_dev_loop_flow` + injected `_feature_flow` (`:1412/:1456`) | `build_dev_flow` only |
| Runner | `DevLoopRunner` (`:1437`) | `DevFlowRunner` |
| Log toolkits | `_build_log_toolkits()` CloudWatch (`:660`) | **absent** |
| Jira | reporter/escalation REQUIRED for bugs (`:776`) | optional link-only (`jira_issue_key`) |
| Brief building | `_build_brief_from_form` (`:714`, requires `affected_component`, `log_sources`) | `_build_dev_brief_from_form`: `DevRequestBrief` (title+description) or `FeatureBrief` (reuse of the `:956` logic) |
| `GET /api/config` | kinds incl. bug + log_group/time_window/jira_project (`:1031`) | kinds `[enhancement, new_feature, feature]`, `document_kinds`, `ideation_max_rounds`, `require_plan_approval` default, no observability defaults |
| Gate resolution | **not mounted** | `register_command_routes(app, runner)` (or an `/api/flow/…`-prefixed equivalent) — the HITL write path |
| Plan gate | conf-only at flow build (`:1405`) | **per-run UI toggle**: form field → `extra_shared["require_plan_approval"]`; `DevelopmentNode` honors the shared-state override (falls back to the build-time flag) |
| Cancel / bundle / replay / WS | `:1181/:1215/:1270/:1545` | identical (same streaming module) |
| Default port | 8080 | **8081** (`PORT` env still wins) — both servers can run side-by-side |

`static/dev.html` is a copy-and-trim of `index.html` (no templating exists —
`handle_index` serves a hardcoded file) with:

- REMOVED: `#work-intake` bug placeholder (`index.html:221–233` bug wording),
  `TOPOLOGY.bug` (`:337–346`), ops tab bodies `criteria/context/observability/
  jira` (`:1125–1168`), `buildPayload()` bug branch (`:1331–1347`),
  `affectedComponent/logGroup/timeWindow` form state (`:416–417`).
- ADDED: 3-intent picker (`enhancement` / `new_feature` / `feature` document);
  NL intake (title + description textarea) for the first two; `TOPOLOGY.dev`
  entry (`dev_intake, ideation, planner, development, synthesis, qa,
  feedback_router, feature_handoff, close, failure_handler`); an
  **Open-Questions panel** that activates on `gate/opened` with
  `kind === "open_questions"` (one input per `gate.questions[]`, submit →
  `POST resolve` with `answers`, plus a Reject/abort button); a
  **plan-approval toggle** in the advanced options (per-run
  `require_plan_approval`) whose `plan_approval` gate renders in the same
  HITL panel (approve/reject + comment — no structured answers); gate audit
  trail retained; `localStorage` theme key changed to `"devflow-theme"` to
  not couple with the ops console.
- KEPT: stepper, execution views (panels/spine/rail), dispatch telemetry,
  judge verdicts, feedback decisions, docs artifact, PR summary card,
  bundle/report actions — all already mode-generic in `index.html`.

### Configuration (new keys in `parrot/conf.py`)

| Key | Default | Meaning |
|---|---|---|
| `DEV_FLOW_IDEATION_MAX_ROUNDS` | `2` | Max open-questions HITL rounds per run |
| `DEV_FLOW_GATE_TTL_QUESTIONS` | `86400` (24 h) | TTL for `open_questions` gates (fail-closed on expiry) |

Everything else (`DEV_LOOP_QA_MAX_RETRIES`, `DEV_LOOP_GATE_PARK`, judge
panel, pool sizing, `DEV_LOOP_REPOS`, docs artifact dir…) is consumed
unchanged from the existing `DEV_LOOP_*` keys — dev-flow deliberately does
NOT fork the shared knobs.

---

## 3. Module Breakdown

### Module 1: dev_flow package skeleton + models
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_flow/__init__.py`,
  `models.py`
- **Responsibility**: `DevRequestBrief`, `DevFlowBrief` union (discriminator
  `kind`), `IdeationOutput`, `parse_dev_brief()` loader. Lazy-import
  hygiene mirroring `dev_loop/__init__.py`.
- **Depends on**: existing `dev_loop.models` (`FeatureBrief`, `DevAgentSpec`,
  `JudgePanelConfig`).

### Module 2: Gate model extension (open_questions) + per-run plan-gate override
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py`,
  `packages/ai-parrot/src/parrot/flows/dev_loop/commands.py`,
  `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py`
- **Responsibility**: `GateKind += "open_questions"`; additive
  `ApprovalGate.questions/answers`, `GateResolved.answers`,
  `SessionHost.open_gate(questions=...)` / `resolve_gate(answers=...)`
  passthrough + reducer fold; `ResolveGateRequest.answers` with host-side
  validation (approved `open_questions` gate requires ≥1 answer).
  Backward-compat: every new field defaults; old envelopes must re-validate.
  Additionally (resolved 2026-08-05): `DevelopmentNode`'s plan-gate check
  honors a per-run `shared["require_plan_approval"]` override before
  falling back to the constructor flag (additive — the gate helper at
  `development.py:276` is otherwise unchanged), so the UI toggle works
  without rebuilding the flow.
- **Depends on**: none (additive to existing FEAT-322/FEAT-377 machinery).

### Module 3: `sdd-ideation` subagent definition
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_flow/_subagent_data/sdd-ideation.md`
  (+ mirror `.claude/agents/sdd-ideation.md`), loader in
  `dev_flow/_subagent_defs.py` (same contract as
  `dev_loop/_subagent_defs.py:86 load_subagent_definition`)
- **Responsibility**: dual-mode system prompt for the ideation phase —
  ONE subagent definition with a `mode` field in the dispatch payload
  (`"brainstorm"` for `new_feature`, `"proposal"` for `enhancement`), NOT
  two prompt files. Consume the NL request (+ wiki context + prior-round
  answers), write/update the corresponding
  `sdd/proposals/<slug>.{brainstorm|proposal}.md` with FEAT-145 frontmatter
  and the `[ ]`/`[x] — *Resolved*: <answer>` Open-Questions convention,
  **resume/extend the document if it already exists**, commit it to
  `base_branch` (explicit paths only, never `git add -A`), emit ONE final
  `IdeationOutput` JSON (no prose).
- **Depends on**: Module 1 (contract).

### Module 4: DevIntakeNode + IdeationNode
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_flow/nodes/__init__.py`,
  `nodes/dev_intake.py`, `nodes/ideation.py`
- **Responsibility**:
  - `DevIntakeNode` (`dev_flow.dev_intake`): loads/validates the
    `DevFlowBrief` (ctx or JSON prompt — mirrors
    `IntentClassifierNode._load_brief`), publishes `ctx["feature_brief"]`
    when kind == "feature", emits `flow.intake_validated`, returns the brief
    for CEL routing.
  - `IdeationNode` (`dev_flow.ideation`): the HITL round-trip exactly as
    §2 (dispatch in the intent's mode → gate → re-dispatch,
    ≤ `DEV_FLOW_IDEATION_MAX_ROUNDS`), terminal output `FeatureBrief`
    (document_kind from `IdeationOutput`) into `ctx["feature_brief"]`.
  Both subclass `DevLoopNode` and register via `register_dev_loop_node`
  (`nodes/base.py:174` — idempotent, safe across re-imports).
- **Depends on**: Modules 1, 2, 3.

### Module 5: Topology — definition + flow builder
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_flow/definition.py`,
  `flow.py`, `factories.py`
- **Responsibility**: `build_dev_flow_definition()` (nodes/edges/CEL per §2)
  and `build_dev_flow()` (declarative-materialize-then-explicit-edge, the
  `build_dev_loop_feature_flow` pattern — `runner.py:178`). `factories.py`
  wraps `build_dev_loop_node_factories` and adds factories for the two new
  node types. Definition↔imperative parity test (dev_loop's
  `test_declarative_flow.py` precedent).
- **Depends on**: Module 4.

### Module 6: DevFlowRunner
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_flow/runner.py`
- **Responsibility**: `DevFlowRunner(DevLoopRunner)` — accepts
  `DevFlowBrief`, seeds `ctx["dev_brief"]` (+ `ctx["feature_brief"]` when
  applicable), always runs the single dev-flow graph (no `_run_feature`
  switching), inherits gates/park/resume, session host, actions stream,
  bundle/report persistence unchanged.
- **Depends on**: Modules 1, 5.

### Module 7: `server_dev.py`
- **Path**: `examples/dev_loop/server_dev.py`
- **Responsibility**: aiohttp app per the §2 table — dev-flow wiring, gate
  resolve route mounted, trimmed `/api/config`, `_build_dev_brief_from_form`,
  per-run `require_plan_approval` passthrough (form →
  `extra_shared["require_plan_approval"]`), default port 8081. Startup
  mirrors `server.py:_on_startup` minus `_build_log_toolkits` and the bug
  flow.
- **Depends on**: Modules 2, 6.

### Module 8: `static/dev.html`
- **Path**: `examples/dev_loop/static/dev.html`
- **Responsibility**: development-only UI per the §2 REMOVED/ADDED/KEPT
  lists, including the interactive Open-Questions panel driven by
  `gate/opened` → `POST resolve` with `answers`.
- **Depends on**: Module 7 (config/route shapes).

### Module 9: Documentation
- **Path**: `examples/dev_loop/README.md`, `examples/dev_loop/GUIA.md`
- **Responsibility**: document the second server/UI pair (when to use ops
  console vs dev console), the `open_questions` gate protocol, and the new
  conf keys.
- **Depends on**: Modules 7, 8.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_dev_request_brief_validation` | 1 | kind/title/description required; union discriminates `enhancement`/`new_feature`/`feature` |
| `test_parse_dev_brief_feature_passthrough` | 1 | `feature` kind yields the existing `FeatureBrief` (document must exist) |
| `test_gate_open_questions_kind` | 2 | `open_gate(kind="open_questions", questions=[...])` → gate carries questions; snapshot round-trips |
| `test_gate_resolve_with_answers` | 2 | `resolve_gate(..., answers={...})` folds answers into state; audit fields intact |
| `test_gate_resolve_answers_required` | 2 | approving an `open_questions` gate with empty answers → rejected (400 at REST layer) |
| `test_gate_backward_compat` | 2 | pre-FEAT-412 envelopes (no questions/answers) still validate and reduce |
| `test_ideation_output_contract` | 3 | subagent JSON parses into `IdeationOutput`; `committed=False` fails the node |
| `test_plan_gate_per_run_override` | 2 | `shared["require_plan_approval"]=True` opens the plan gate even when the constructor flag is False (and vice versa) |
| `test_dev_intake_routes_by_kind` | 4 | enhancement/new_feature → ideation edge predicate true; feature → planner edge |
| `test_ideation_enhancement_emits_proposal` | 4 | `enhancement` intent → dispatch mode "proposal" → `FeatureBrief.document_kind == "proposal"`; `new_feature` → "brainstorm" |
| `test_ideation_resumes_existing_doc` | 4 | pre-existing target doc → subagent receives it, `resumed_existing=True`, no `-2` copy created |
| `test_ideation_gate_roundtrip` | 4 | fake dispatcher emits open questions → gate opens → resolve with answers → re-dispatch receives answers |
| `test_ideation_rounds_bounded` | 4 | subagent keeps asking → stops after `DEV_FLOW_IDEATION_MAX_ROUNDS`, run continues |
| `test_ideation_gate_rejected_escalates` | 4 | rejected gate → node error → failure_handler path |
| `test_dev_flow_definition_valid` | 5 | `build_dev_flow_definition()` validates; node/edge inventory matches §2 |
| `test_dev_flow_parity` | 5 | declarative definition ↔ imperative wiring parity (dev_loop precedent) |
| `test_runner_accepts_dev_brief` | 6 | `DevFlowRunner.run(DevRequestBrief)` seeds context; feature brief skips ideation |

### Integration Tests

| Test | Description |
|---|---|
| `test_dev_flow_e2e_nl_to_draft_pr` | Simulated dispatchers (e2e_demo pattern): NL request → ideation + 1 HITL round → planner → dev pool → QA pass → draft-PR handoff → close |
| `test_dev_flow_e2e_document_intake` | `feature` intent with a proposal doc: ideation node skipped, rest identical |
| `test_server_dev_gate_route` | `POST /api/…/gates/{id}/resolve` with answers unblocks a parked run (aiohttp test client) |
| `test_server_dev_config_shape` | `/api/config` has dev kinds only, no log_group/time_window keys |

### Test Data / Fixtures

```python
@pytest.fixture
def dev_request_brief() -> DevRequestBrief:
    return DevRequestBrief(
        kind="enhancement",
        title="compression budget telemetry",
        description="Add per-tool telemetry to the compression budget so ...",
    )

@pytest.fixture
def fake_ideation_dispatcher():
    """Scripted dispatcher: round 1 → IdeationOutput with 2 open questions;
    round 2 (with answers) → IdeationOutput with none, committed=True."""
```

---

## 5. Acceptance Criteria

- [ ] `build_dev_flow()` produces a valid `AgentsFlow`; parity test between
      `build_dev_flow_definition()` and the imperative wiring passes.
- [ ] A `new_feature` run produces a committed
      `sdd/proposals/<slug>.brainstorm.md`; an `enhancement` run produces a
      committed `sdd/proposals/<slug>.proposal.md` (light format) — both
      with FEAT-145 frontmatter and the `[x] … — *Resolved*: <answer>`
      convention for HITL-answered questions. A pre-existing target
      document is resumed/extended in place, never overwritten or suffixed.
- [ ] Open Questions are delivered as ONE `open_questions` gate per round
      (structured `questions` list), resolvable via REST with structured
      `answers`; rounds bounded by `DEV_FLOW_IDEATION_MAX_ROUNDS`; expiry
      is fail-closed; rejection aborts to `failure_handler`.
- [ ] A `feature` intent (existing brainstorm/proposal) skips the ideation
      node entirely and behaves like FEAT-378 feature-mode from `planner` on.
- [ ] The `require_plan_approval` UI toggle opens a `plan_approval` gate for
      that run only (per-run `extra_shared` override honored by
      `DevelopmentNode`), resolvable from the dev.html HITL panel.
- [ ] Every successful run terminates with a **draft PR against `dev`**
      (existing `FeatureHandoffNode` behavior) — never a merge.
- [ ] The gate-model extension is additive: all existing dev_loop tests pass
      unmodified; pre-existing persisted action envelopes still validate.
- [ ] `server_dev.py` runs side-by-side with `server.py` (default port 8081),
      mounts the gate-resolution route, wires **no** CloudWatch/log toolkits,
      and never requires Jira reporter/escalation fields.
- [ ] `static/dev.html` contains no bug-intake, CloudWatch, affected-component
      or mandatory-Jira UI; the Open-Questions panel answers a live gate
      end-to-end from the browser. `index.html` byte-identical to before.
- [ ] All unit + integration tests pass
      (`pytest packages/ai-parrot/tests/flows/dev_flow/ tests/… -v`); `ruff`
      and `mypy` clean on new files.
- [ ] `README.md`/`GUIA.md` document the dev console and the gate protocol.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified 2026-08-05 on branch `dev` (post-`origin/dev` fast-forward).

### Verified Imports

```python
from parrot.flows.dev_loop.models import (        # models/__init__.py re-exports
    FeatureBrief,          # models/base.py:725
    DevAgentSpec,          # models/base.py (TASK-1918 contract)
    JudgePanelConfig,      # models/base.py:~830+
    PlannerOutput,
)
from parrot.flows.dev_loop.nodes.base import (
    DevLoopNode,               # nodes/base.py:193
    register_dev_loop_node,    # nodes/base.py:174 (idempotent @register_node)
)
from parrot.flows.dev_loop.session_state import (
    ApprovalGate,          # session_state.py:225
    GateKind,              # session_state.py:172 (Literal, 5 kinds today)
    GateOpened,            # session_state.py:440
    GateResolved,          # session_state.py:445
    GateExpired,           # session_state.py:455
    GateNotFoundError,     # session_state.py:662
    GateAlreadyResolvedError,  # session_state.py:666
)
from parrot.flows.dev_loop.commands import (
    ResolveGateRequest,        # commands.py:~45 (fields at :51-54)
    resolve_gate_handler,      # commands.py:70
    register_command_routes,
)
from parrot.flows.dev_loop.runner import DevLoopRunner   # runner.py
from parrot.flows.dev_loop.factories import build_dev_loop_node_factories
from parrot.flows.dev_loop.dispatchers import ClaudeCodeDispatcher
from parrot.flows.dev_loop._subagent_defs import load_subagent_definition  # :86
from parrot.flows.dev_loop.wiki_search import DevLoopWikiSearch
from parrot.bots.flows import AgentsFlow
from parrot.bots.flows.flow.definition import (
    EdgeDefinition, FlowDefinition, NodeDefinition,
)
from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.types import DependencyResults
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py
GateKind = Literal["manual_criterion", "deployment_approval",
                   "revision_approval", "plan_approval",
                   "review_escalation"]                        # :172-178
GateStatus = Literal["pending", "approved", "rejected", "expired"]  # :180

class ApprovalGate(_Frozen):                                   # :225
    gate_id: str; kind: GateKind; node_id: NodeId
    status: GateStatus = "pending"
    on_expiry: Literal["fail", "approve"] = "fail"             # :237
    title: str = ""; instructions: str = ""; payload_ref: str = ""
    opened_at: float; expires_at: Optional[float]
    resolved_by: str = ""; resolved_at: Optional[float]; comment: str = ""

class SessionHost:
    def resolve_gate(self, gate_id, resolution: Literal["approved","rejected"],
                     resolved_by, comment="", origin=None) -> ActionEnvelope  # :1034
    def open_gate(self, *, kind: GateKind, node_id: NodeId, title: str,
                  instructions="", payload_ref="", ttl_seconds=None,
                  on_expiry: Literal["fail","approve"]="fail",
                  ) -> Tuple[str, ActionEnvelope]              # :1079
    def expire_due_gates(self, now=None) -> List[ActionEnvelope]  # :1116
    async def wait_gate(self, gate_id: str) -> ApprovalGate    # :1149

# packages/ai-parrot/src/parrot/flows/dev_loop/commands.py
class ResolveGateRequest(BaseModel):                           # frozen, extra="forbid"
    resolution: Literal["approved", "rejected"]                # :51
    resolved_by: str  # min_length=1                           # :52
    comment: str = ""; client_seq: int = 0                     # :53-54
async def resolve_gate_handler(request) -> web.Response        # :70
# routes: POST /runs/{run_id}/gates/{gate_id}/resolve ; POST /runs/{run_id}/cancel
# runner read from request.app["dev_loop_runner"]              # :84

# packages/ai-parrot/src/parrot/flows/dev_loop/runner.py
def build_dev_loop_feature_flow(*, dispatcher, jira_toolkit=None,
    git_toolkit=None, wiki_toolkit=None, redis_url, codereview_dispatcher=None,
    development_dispatcher_builder=None, development_pool_max=4,
    graph_memory=None, require_plan_approval=False, skip_qa=False,
    name="dev-loop-feature", publish_flow_events=True) -> AgentsFlow  # :178
class DevLoopRunner:
    async def run(self, brief: Union[WorkBrief, FeatureBrief], *,
                  run_id=None, initial_task="", extra_shared=None
                  ) -> FlowResult                              # :885
    async def resolve_gate(self, run_id, gate_id, resolution,
                           resolved_by, comment, origin) -> ...  # :713
    async def resume_run(self, run_id) -> FlowResult           # (park/resume)

# packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py
class FeatureBrief(BaseModel):                                 # :725
    kind: Literal["feature"] = "feature"
    document_path: str          # eager readability validator  # :780
    document_kind: Literal["brainstorm", "proposal", "spec"]   # :747
    jira_issue_key: Optional[str] = None                       # :755
    dev_agents: Optional[List[DevAgentSpec]] = None            # :763
    judge_panel: Optional[JudgePanelConfig] = None             # :771

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/base.py
def register_dev_loop_node(name: str)                          # :174
class DevLoopNode(Node)                                        # :193

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/planner.py
# PlannerNode reads shared["feature_brief"] (FeatureBrief) — placed by the
# intake node; dispatches "sdd-planner"; returns PlannerOutput.
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `DevIntakeNode` | CEL routing | returns `DevFlowBrief`; `result.kind` predicates | `dev_loop/definition.py` CEL precedent (`_CEL_IS_FEATURE`) |
| `IdeationNode` | `SessionHost.open_gate/wait_gate` | `ctx` session host (same access pattern as QA/handoff nodes) | `nodes/qa.py:745,761`; `nodes/deployment_handoff.py:274,283` |
| `IdeationNode` | `PlannerNode` | writes `ctx["feature_brief"]` | `nodes/planner.py` (spec FEAT-378 §3 M2 step 1) |
| plan-gate UI toggle | `DevelopmentNode` plan gate | `extra_shared["require_plan_approval"]` → shared-state override | gate helper at `nodes/development.py:276` (`kind="plan_approval"`, `on_expiry="approve"`) |
| `build_dev_flow` | node factories | `build_dev_loop_node_factories` + 2 new factories | `dev_loop/factories.py`, `flow.py:build_dev_loop_flow` pattern |
| `server_dev.py` | gate REST | `register_command_routes(app, runner)` | `commands.py` (routes documented in module docstring) |
| `dev.html` | state WS | `gate/opened`/`gate/resolved` action folding | `index.html:497–571 foldAction`, `:581 connect` |
| `server_dev.py` | WS relay | `flow_stream_ws` (`?view=flow\|dispatch\|both\|state`) | `server.py:1545` route; `dev_loop/streaming.py` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot/flows/dev_flow/`~~ — the package does not exist yet (this spec
  creates it).
- ~~`sdd-ideation` subagent~~ — `_subagent_data/` today contains only:
  sdd-autopilot, sdd-codereview, sdd-feedback, sdd-planner, sdd-qa,
  sdd-research, sdd-secondopinion, sdd-worker.
- ~~`GateKind "open_questions"`~~, ~~`ApprovalGate.questions`~~,
  ~~`ApprovalGate.answers`~~, ~~`ResolveGateRequest.answers`~~ — gate model
  is approve/reject + comment only today.
- ~~a gate-resolution route in `examples/dev_loop/server.py`~~ — the library
  handler exists (`commands.py:70`) but `build_app` (server.py:1533) never
  mounts it; the UI's gate panel is read-only.
- ~~LLM intent classification~~ — `IntentClassifierNode` only VALIDATES a
  typed brief and routes on its `kind`; it never infers intent from text.
- ~~`DevRequestBrief` / `DevFlowBrief` / `IdeationOutput`~~ — new models.
- ~~a per-run `require_plan_approval` override~~ — today the flag is fixed
  at flow construction (`server.py:1405` → node constructor); Module 2
  adds the `shared["require_plan_approval"]` override.
- ~~`static/dev.html`~~ / ~~`server_dev.py`~~ — new files. `handle_index`
  serves a hardcoded `static/index.html` (`server.py:1027`); there is NO
  templating/placeholder mechanism anywhere in the example.
- ~~`DEV_FLOW_*` conf keys~~ — none exist yet.
- ~~revision mode in the example server~~ — `run_revision` exists in the
  runner but is not exposed by `server.py` (nor will it be by
  `server_dev.py`).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Declarative + explicit-edge execution**: author the topology in
  `dev_flow/definition.py` as a `FlowDefinition`, materialize through
  factories, execute with `add_node()/add_edge()` explicit mode — the
  OR-joins at `planner` and `failure_handler` cannot run under the
  AND-join `from_definition` scheduler (same engine limitation documented in
  `dev_loop/definition.py`'s module docstring). Keep the parity test.
- **Event-sourced state only**: any new state (questions, answers, rounds)
  enters as actions + reducers on the FEAT-322 machinery — never mutate
  snapshots directly.
- **Additive frozen models**: `_Frozen` state models are persisted in Redis
  streams; every new field MUST default so historical envelopes re-validate.
- **Subagent I/O contract**: `sdd-ideation` emits ONE final JSON object
  (no prose/fences) exactly like sdd-planner/sdd-feedback; prompts live in
  `_subagent_data/` and are read via a `load_subagent_definition`-style
  loader, mirrored in `.claude/agents/`.
- **uv + venv**: `source .venv/bin/activate` before any command; tests with
  `pytest`; async-first; Google docstrings + strict type hints; Pydantic v2.

### Known Risks / Gotchas

- **Gate-model surface is shared with the ops flow** — Module 2 touches
  `dev_loop/session_state.py`. Mitigation: strictly additive fields with
  defaults + `test_gate_backward_compat` + the full existing dev_loop suite
  as a regression net.
- **Ideation doc must be committed before planning**: `sdd-planner` runs
  `/sdd-spec` and creates the worktree from `base_branch` HEAD — an
  uncommitted document is invisible there. The node fails fast on
  `IdeationOutput.committed == False`.
- **Resume/extend can grab the wrong document**: two different ideas can
  slugify to the same `sdd/proposals/<slug>.*.md`; resuming would then
  extend an unrelated document. Mitigations: the resolved `document_path`
  (+ `resumed_existing`) is shown in the gate title/UI, the user can reject
  the gate, and the subagent is instructed to abort (fresh open question)
  when the existing document's Problem Statement clearly does not match the
  request.
- **Dual-mode subagent prompt**: one `sdd-ideation` definition emits two
  formats (brainstorm vs light proposal). The mode is a structured dispatch
  field, and `/sdd-spec` must consume BOTH outputs — the proposal format
  must keep the same frontmatter + Open-Questions conventions so the
  planner path stays uniform.
- **Concurrent SDD sessions on `dev`**: the ideation/spec commits land on
  `dev`; the subagent must stage explicit paths only (never `git add -A`)
  per the SDD auto-commit rule.
- **HITL latency**: an `open_questions` gate can stay pending for hours —
  park/resume (`DEV_LOOP_GATE_PARK`, default true) must be verified for the
  new kind so parked runs don't starve `FLOW_MAX_CONCURRENT_RUNS`.
- **Partial answers**: users may answer only some questions; unanswered ones
  must remain `[ ]` in the doc and must NOT be re-asked verbatim forever —
  bounded rounds + carry-into-spec-§8 is the escape valve.
- **`dev.html` divergence**: a copy-and-trim will drift from `index.html`
  over time. Accepted trade-off (decided 2026-08-05): the two consoles serve
  different audiences; shared JS extraction is deferred until a third
  console appears.
- **`llm_catalog.py` import**: `server_dev.py` lives next to `server.py` and
  reuses its sibling module — keep the example self-contained (no package
  install required beyond the workspace).

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| — | — | No new dependencies; aiohttp/redis/pydantic already in use |

---

## 8. Open Questions

- [x] Package placement — *Resolved 2026-08-05 (user)*: new sibling package
  `parrot/flows/dev_flow/`, NOT a fourth flag on `build_dev_loop_definition`.
  Rationale: the current flow front-loads ops concerns (CloudWatch, Bug
  Intake, mandatory Jira, bug-resolution QA); toggling them off would need
  ever more flags instead of separating concerns (`bug_flow` vs `dev_flow`).
  Node types/models/session-state/runner machinery are still reused from
  `dev_loop` by import.
- [x] Open-Questions HITL shape — *Resolved 2026-08-05 (user)*: ONE gate per
  round carrying ALL questions (new `open_questions` kind, structured
  `questions`/`answers`), bounded re-ask rounds; not per-question gates, not
  an ad-hoc WS chat channel.
- [x] Intent determination — *Resolved 2026-08-05 (user)*: the user selects
  the intent explicitly in the UI (enhancement / new_feature / SDD document);
  no LLM classification node.
- [x] HTML strategy — *Resolved 2026-08-05 (user)*: new `static/dev.html`
  served by `server_dev.py`; `index.html` untouched for operations.
- [x] Plan-approval gate in the UI — *Resolved 2026-08-05 (user)*: YES.
  `dev.html` exposes a per-run `require_plan_approval` toggle (advanced
  options); the resulting `plan_approval` gate renders in the same HITL
  panel as the Open Questions (approve/reject + comment). Requires the
  per-run `shared["require_plan_approval"]` override in `DevelopmentNode`
  (§3 Module 2).
- [x] Existing-document policy — *Resolved 2026-08-05 (user)*:
  RESUME/EXTEND the existing `sdd/proposals/<slug>.*.md` (new
  Open-Questions rounds on the same doc, `resumed_existing=true`); never
  overwrite, never create `-2`-suffixed copies. Ambiguity risk mitigated in
  §7 Known Risks (document path surfaced in the gate; user can reject).
- [x] `enhancement` path — *Resolved 2026-08-05 (user)*: `enhancement`
  generates a **light proposal** (`.proposal.md` — scope, rationale,
  impact, open questions; no options analysis) instead of a brainstorm;
  `new_feature` keeps the full brainstorm. Both are produced by the single
  dual-mode `sdd-ideation` subagent and both feed `PlannerNode` unchanged
  (`FeatureBrief.document_kind` already admits `"proposal"`). This is why
  the ideation stage is named `ideation`, not `brainstorm`.

---

## Worktree Strategy

- **Isolation unit**: per-spec — one worktree
  (`.claude/worktrees/feat-412-sdd-dev-flow`), tasks sequential.
- **Parallelizable**: Modules 2 (gate extension) and 3 (subagent prompt) are
  independent of each other after Module 1; everything else is a chain
  (1 → {2,3} → 4 → 5 → 6 → 7 → 8 → 9). Single-worktree sequential execution
  is recommended anyway — Module 2 touches shared `dev_loop` files.
- **Cross-feature dependencies**: none pending; consumes FEAT-322 (session
  state), FEAT-377 (park/resume, repair loop), FEAT-378 (feature-mode nodes)
  — all already on `dev`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-05 | Jesus Lara (with Claude) | Initial draft |
| 0.2 | 2026-08-05 | Jesus Lara (with Claude) | §8 fully resolved: plan-gate UI toggle (per-run override), resume/extend existing docs, enhancement → light proposal; `brainstorm` stage renamed `ideation` (dual-mode `sdd-ideation` subagent) |
