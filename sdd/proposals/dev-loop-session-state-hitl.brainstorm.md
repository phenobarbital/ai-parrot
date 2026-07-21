---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: AHP-style Session State Model & HITL Approval Gates for dev-loop

**Date**: 2026-07-21
**Author**: Jesus Lara (with Claude)
**Status**: exploration
**Recommended Option**: B

> All code references verified against commit
> `e252257862cdeeb514034a1de6559a7be76168f5`. Paths are relative to
> `packages/ai-parrot/src/`. **Implementing agents MUST re-verify every
> reference against the current HEAD before use** (line numbers drift).

---

## Problem Statement

The dev-loop (FEAT-129/132/250) is an ad-hoc orchestration process. Its
observability layer is an *event log*, not an *authoritative state*:

1. **No snapshot semantics.** `FlowStreamMultiplexer` (streaming.py:51) fans
   in two Redis Streams (`flow:{run_id}:flow`, `flow:{run_id}:dispatch:{node_id}`)
   and emits flat envelopes. A client joining mid-run must replay the entire
   stream and reconstruct state client-side; every client (nav-admin Svelte,
   future CLI) reimplements that fold logic independently and can diverge.
2. **No multi-client write arbitration.** Nothing prevents two operators from
   issuing conflicting commands (cancel, approve) against the same run; there
   is no sequenced, auditable "who did what, and who won" record.
3. **No blocking HITL.** `QANode._merge_manual_results` (nodes/qa.py:301)
   synthesizes `passed=True` for every `ManualCriterion` — manual criteria
   are informational only and never gate the flow. `DeploymentHandoffNode`
   (nodes/deployment_handoff.py:46) pushes, opens the (draft) PR and
   transitions Jira with **zero human approval step** in-loop. Approval today
   happens out-of-band in GitHub, invisible to the run.
4. **Standards drift risk.** Microsoft's Agent Host Protocol (AHP) and
   Google's A2A both converge on the same shape: authoritative session
   state + sequenced mutations + an `input-required`/gate-like blocked state.
   Whatever wire protocol wins, ai-parrot's dev-loop currently has none of
   the invariant core (state tree, typed actions, pure reducers) that any of
   them would sit on.

Affected: dev-loop operators (nav-admin users), the nav-admin Svelte plugin,
`DevLoopRunner` hosting, and any future external client of runs.

## Constraints & Requirements

- Pydantic v2 house style: `frozen=True`, `extra="forbid"`, closed
  discriminated unions, deterministic contracts. No emergent/heuristic state.
- Reducers MUST be pure, total and non-raising: `fold(log) == state` must be
  a property-testable invariant (host and Svelte client run the same logic).
- Zero regression for the existing WS consumers during migration: the current
  `FlowStreamMultiplexer` envelopes must keep flowing until nav-admin is
  ported (dual-publish window).
- Wire-protocol agnostic core: **no** JSON-RPC / aiohttp / redis imports in
  the state/actions/reducers module. AHP is DRAFT status (breaking changes
  expected); A2A may be imposed by ecosystem pressure. The adapter layer is
  the only thing allowed to churn.
- Redis Streams remain the durable envelope log (replay source); they stop
  being the *source of state*.
- Gate arbitration MUST be first-writer-wins, validated *before* sequencing
  (AHP's tool-call confirmation semantics), with full audit trail
  (`resolved_by`, `resolved_at`, comment) and TTL/expiry → escalation to
  `WorkBrief.escalation_assignee` (models.py:118, field verified).
- Event publishing must never break a run (same guarantee
  `FlowEventPublisher` gives today — flow.py:71 docstring: "every failure is
  swallowed").
- `FLOW_MAX_CONCURRENT_RUNS` semantics unchanged (runner.py:100).

---

## Options Explored

### Option A: Full AHP adoption (wire protocol included)

Implement an AHP-compliant host: JSON-RPC 2.0 framing, `initialize` /
`subscribe` / `dispatchAction` methods, `ahp-root://` + `ahp-session:/<uuid>`
+ `ahp-terminal:/<id>` + `ahp-changeset:/<id>` channels, `serverSeq`
envelopes, write-ahead reconciliation, RFC 9728/6750 auth. Generate Pydantic
models from the published JSON Schemas (2020-12) in CI.

✅ **Pros:**
- Standards-compliant from day one; third-party AHP clients (IDE panels,
  reference clients) could attach to dev-loop runs with no custom client.
- Schema-driven codegen gives free drift detection against the spec.
- Terminal/changeset channels map naturally onto dispatch ptys and PR diffs.

❌ **Cons:**
- AHP is explicitly DRAFT: "Breaking changes to wire types, actions, and
  state shapes are expected." Wire-level compliance is a moving target.
- Large surface: reconnection, capability negotiation, resource* commands,
  auth flow — most of it not needed by nav-admin today.
- Couples ai-parrot's internal orchestration to a TypeScript-first spec
  before any Python reference implementation exists.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `jsonrpcserver` / hand-rolled | JSON-RPC 2.0 framing | aiohttp WS transport already in-tree |
| `datamodel-code-generator` | Pydantic models from AHP JSON Schemas | CI drift gate |

🔗 **Existing Code to Reuse:**
- `parrot/flows/dev_loop/streaming.py:51` — `FlowStreamMultiplexer` (WS plumbing, replay loop)
- `parrot/flows/dev_loop/webhook.py` — aiohttp app wiring patterns

---

### Option B: Protocol-agnostic state core, AHP-shaped, adapter-isolated ⭐

Introduce a new module `parrot/flows/dev_loop/session_state.py` containing
the three invariant layers only: (1) `DevLoopSessionState` frozen state tree,
(2) closed `DevLoopAction` discriminated union, (3) pure `reduce()` +
`SessionHost` (sequencing, snapshot, replay, gate arbitration). Channel URIs
use a neutral scheme (`parrot-session:/<run_id>`, …) that mirrors AHP's
channel *model* without claiming wire compatibility; the `parrot-*` → `ahp-*`
mapping belongs to the future adapter. The module imports no transport. Existing producers are bridged by two shim
functions mapping `FlowEventPublisher` events and `DispatchEvent.kind`
values 1:1 into actions. HITL gates (`ApprovalGate`, `GateOpened`/
`GateResolved`/`GateExpired`) become first-class state: `QANode` opens a
`manual_criterion` gate per `ManualCriterion` instead of synthesizing
`passed=True`; `DeploymentHandoffNode` opens a `deployment_approval` gate
before the Jira transition and awaits resolution (asyncio.Event set by the
host on `GateResolved`). The wire (current WS envelopes now; AHP or A2A
later) is a thin adapter over `SessionHost.snapshot()` / `replay_since()` /
envelope broadcast.

✅ **Pros:**
- Captures the part of AHP that is *stable by construction* (Redux model);
  survives AHP draft churn and an eventual A2A pivot (`awaiting_gate` ≅
  A2A `input-required`).
- Deterministic, closed contracts — property-testable
  (`fold(replay_since(0)) == state`), fully aligned with house style.
- HITL gates land as real product value immediately, independent of any
  protocol adoption.
- Incremental: dual-publish keeps nav-admin working; Svelte port of the
  reducer is mechanical (same union, same fold).

❌ **Cons:**
- Not wire-compatible with AHP clients yet (deferred to a follow-up spec).
- Dual-publish window means temporary event duplication in Redis.
- One more projection to keep in sync with node results (mitigated: state
  holds display-ready summaries only; full models stay in `FlowContext`).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic>=2` | frozen models, discriminated unions | already a core dep |
| `hypothesis` | property tests for reducer totality/determinism | dev-dep, already used in repo tests |

🔗 **Existing Code to Reuse:**
- `parrot/flows/dev_loop/flow.py:71` — `FlowEventPublisher` (attach shim in `__call__`, flow.py:94)
- `parrot/flows/dev_loop/models.py:698` — `DispatchEvent` (kind → action mapping)
- `parrot/flows/dev_loop/runner.py:100` — `DevLoopRunner` (owns `SessionHost` per run)
- `parrot/flows/dev_loop/streaming.py:51` — `FlowStreamMultiplexer` (adapter target)
- `parrot/flows/dev_loop/nodes/qa.py:301` — `_merge_manual_results` (replaced by gate opening)
- `parrot/flows/dev_loop/nodes/deployment_handoff.py:89` — `execute` (gate insertion point, pre-Jira-transition)

---

### Option C: Gates-only, no state model

Keep the event-log architecture untouched; add a small `GateRegistry`
(Redis hash per run) that `DeploymentHandoffNode` polls/awaits, plus two new
`DispatchEvent`-style kinds (`gate.opened`, `gate.resolved`) on the existing
streams. nav-admin renders gates from the event stream as it does today.

✅ **Pros:**
- Smallest diff; ships HITL deployment approval fastest.
- No client-side changes beyond rendering two new event kinds.

❌ **Cons:**
- Doubles down on the reconstruct-state-from-log problem (constraint 1
  unaddressed); every future client still reimplements the fold.
- Arbitration via Redis `HSETNX`-style checks is ad-hoc — exactly the
  emergent/heuristic pattern the house style rejects.
- Zero reusable ground when AHP/A2A adoption becomes necessary; this work
  gets thrown away.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `redis.asyncio` | HSETNX-based gate claim | already in-tree |

🔗 **Existing Code to Reuse:**
- `parrot/flows/dev_loop/models.py:698` — `DispatchEvent` (extend `kind` Literal)
- `parrot/flows/dev_loop/nodes/deployment_handoff.py:64` — `__init__` (inject registry)

---

## Recommendation

**Option B** is recommended because:

- It extracts the *invariant* subset of AHP (authoritative state, typed
  actions, pure reducers, sequenced envelopes, gate arbitration) while
  quarantining everything that is DRAFT-volatile (wire framing, method
  names, auth) behind a future adapter. If AHP stabilizes → adapter spec.
  If A2A wins → different adapter, same core. Option A bets the internal
  architecture on a moving spec; Option C produces throwaway work and
  ad-hoc arbitration.
- It converts the ManualCriterion gap (qa.py:301 synthesizes `passed=True`)
  and the unguarded Jira transition (deployment_handoff.py:89) into a single
  general mechanism (`ApprovalGate`) instead of two point fixes.
- Trade-off accepted: no third-party AHP client compatibility in this
  feature. That is deliberately deferred — the follow-up wire-adapter spec
  becomes cheap once this core exists.

---

## Feature Description

### User-Facing Behavior

- nav-admin's run view is driven by a **snapshot + action stream**: opening a
  run mid-flight renders instantly from `Snapshot` (phase, per-node status,
  dispatch counters, gates) instead of replaying the whole event history.
- When QA reaches manual criteria, or DeploymentHandoff is about to
  transition Jira, the run enters **`awaiting_gate`**: nav-admin shows a
  gate card (title, instructions, evidence link, TTL countdown) with
  Approve / Reject + comment. Any connected operator may resolve; the first
  resolution wins, later attempts get a clear "already approved by X" error.
  Rejection of a `deployment_approval` gate routes the run to
  `failure_handler` (existing escalation path).
- Unresolved gates past TTL follow their `on_expiry` policy: fail-closed
  kinds (`deployment_approval`, blocking `manual_criterion`,
  `revision_approval`) flip to `expired` and the run escalates to
  `WorkBrief.escalation_assignee` (existing field) via the failure path;
  fail-open kinds (`plan_approval`) are auto-approved by
  `system:ttl-auto-approve`, explicitly audited in-state.
- Every resolution is audited in-state: `resolved_by`, `resolved_at`,
  `comment` — and therefore in the append-only envelope log.

### Internal Behavior

- `DevLoopRunner` instantiates one `SessionHost` per run (single-writer,
  event-loop-driven). `FlowEventPublisher.__call__` and the dispatchers'
  XADD path additionally call `host.apply(shim(event))`; the host folds the
  action, assigns `server_seq`, and the envelope is XADDed to a new stream
  `flow:{run_id}:actions` (dual-publish with legacy streams during
  migration).
- `QANode.execute` opens one `manual_criterion` gate per `ManualCriterion`
  (replacing the `passed=True` synthesis) — configurable: `blocking=True`
  per criterion, default preserving current non-blocking behavior for
  backward compat.
- `DeploymentHandoffNode.execute` opens a `deployment_approval` gate after
  the draft PR exists but **before** the Jira transition, then awaits an
  `asyncio.Event` the host sets on `GateResolved`/`GateExpired`.
- `FlowStreamMultiplexer` gains a `view="state"` mode: on connect, send
  `snapshot`, then relay envelopes from `flow:{run_id}:actions` (replay via
  `server_seq > last_seen`).

### Edge Cases & Error Handling

- Host crash mid-run: state is rebuilt by folding `flow:{run_id}:actions`
  from seq 0 (determinism invariant); pending gates survive as state.
- Late/duplicate `GateResolved` (e.g. replayed command): host validates
  `status == "pending"` pre-sequencing; reducer treats a conflicting resolve
  as no-op (total, non-raising).
- Run cancelled while `awaiting_gate`: `RunCancelled` is terminal-sticky;
  pending gates remain in-state for audit but are unreachable.
- Redis unavailable: `host.apply` still folds in-memory (run proceeds);
  envelope XADD failures are swallowed and logged, mirroring
  `FlowEventPublisher`'s never-break-a-run guarantee (flow.py:71).
- Gate opened by a node that then hard-errors: `on_error` edge to
  `failure_handler` fires as today; the failure handler resolves the
  orphaned gate as `expired`.

---

## Capabilities

### New Capabilities
- `dev-loop-session-state`: authoritative frozen state tree + closed action
  union + pure reducers + `SessionHost` sequencing/replay for dev-loop runs.
- `dev-loop-approval-gates`: blocking HITL gates (manual_criterion,
  deployment_approval, revision_approval, plan_approval) with
  first-writer-wins arbitration, TTL expiry and audit trail.

### Modified Capabilities
- `dev-loop-orchestration`: QA manual-criteria handling and
  DeploymentHandoff gain gate integration; runner hosts `SessionHost`.
- `dev-loop-streaming` (Module 3 / spec G4): multiplexer gains
  snapshot+actions view; dual-publish migration.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/flows/dev_loop/session_state.py` | new | protocol-agnostic core (state/actions/reducers/host/shims) |
| `parrot/flows/dev_loop/runner.py` (`DevLoopRunner`, :100) | extends | owns `SessionHost` per run; exposes `resolve_gate` command path |
| `parrot/flows/dev_loop/flow.py` (`FlowEventPublisher`, :71) | extends | dual-publish: legacy envelope + `host.apply(shim)` |
| `parrot/flows/dev_loop/nodes/qa.py` (`_merge_manual_results`, :301) | modifies | blocking manual criteria open gates (opt-in flag) |
| `parrot/flows/dev_loop/nodes/deployment_handoff.py` (`execute`, :89) | modifies | deployment_approval gate before Jira transition |
| `parrot/flows/dev_loop/streaming.py` (`FlowStreamMultiplexer`, :51) | extends | `view="state"` snapshot+actions mode |
| `parrot/flows/dev_loop/models.py` | depends on | projections read `QAReport` (:349), `WorkBrief` (:118), `DispatchEvent` (:698) |
| nav-admin Svelte plugin | extends | reducer port + gate cards (separate repo, follow-up) |
| Redis | extends | new stream `flow:{run_id}:actions`; legacy streams unchanged |

No breaking changes: legacy streams, `DevLoopRunner(flow)` construction and
non-blocking manual criteria all preserved by default.

---

## Code Context

### User-Provided Code

```python
# Source: user-provided — design sketch "devloop_session_state.py"
# (full file attached to the feature; key contracts excerpted)

class SessionHost:
    def apply(self, action: DevLoopAction) -> ActionEnvelope: ...
    def snapshot(self) -> Snapshot: ...
    def replay_since(self, last_seen_server_seq: int) -> List[ActionEnvelope]: ...
    def resolve_gate(self, gate_id, resolution, resolved_by, comment="") -> ActionEnvelope:
        """Validated BEFORE sequencing — first writer wins, later attempts
        raise GateAlreadyResolvedError and never become actions."""

def reduce(state: DevLoopSessionState, action: DevLoopAction) -> DevLoopSessionState:
    """Pure, total, non-raising. fold(log) == state is the invariant."""
```

### Verified Codebase References

Verified at commit `e252257862cdeeb514034a1de6559a7be76168f5`; paths relative
to `packages/ai-parrot/src/`.

#### Classes & Signatures
```python
# From parrot/flows/dev_loop/flow.py:71
class FlowEventPublisher:
    def __init__(self, redis_url: str, run_id_holder: Dict[str, str]) -> None: ...
    async def __call__(self, event: str, node_id: str, info: Dict[str, Any]) -> None:  # :94
        ...

# From parrot/flows/dev_loop/models.py:698
class DispatchEvent(BaseModel):
    kind: Literal[
        "dispatch.queued", "dispatch.started", "dispatch.message",
        "dispatch.tool_use", "dispatch.tool_result",
        "dispatch.output_invalid", "dispatch.failed", "dispatch.completed",
    ]
    ts: float
    run_id: str
    node_id: str
    payload: Dict[str, Any]

# From parrot/flows/dev_loop/models.py:349
class QAReport(BaseModel):
    passed: bool
    criterion_results: List[CriterionResult]
    lint_passed: bool
    lint_output: str = ""
    notes: str = ""
    code_review_passed: bool = True   # FEAT-250 additive gate
    code_review_findings: List[str]

# From parrot/flows/dev_loop/models.py:70
class ManualCriterion(BaseModel): ...   # kind="manual"; fields: name, text

# From parrot/flows/dev_loop/nodes/qa.py:301
@staticmethod
def _merge_manual_results(report: QAReport, manual: List[ManualCriterion]) -> QAReport:
    # synthesizes CriterionResult(..., passed=True) for EVERY manual criterion
    ...

# From parrot/flows/dev_loop/nodes/deployment_handoff.py:46
class DeploymentHandoffNode(DevLoopNode):
    def __init__(self, *, jira_toolkit, git_toolkit=None, gh_cli_path=None,
                 target_repo=None, base_branch="dev",
                 name="deployment_handoff") -> None: ...   # :64
    async def execute(self, ctx, deps=None, **kwargs) -> Dict[str, Any]:  # :89
        # returns {"status": "ready_to_deploy", "pr_url": ..., "pr_number": int}
        # or {"status": "blocked", "error": ...}; PR opened as DRAFT
        ...

# From parrot/flows/dev_loop/runner.py:100
class DevLoopRunner:
    def __init__(self, flow: AgentsFlow, *, max_concurrent_runs=None,
                 dispatcher=None, jira_toolkit=None, git_toolkit=None,
                 redis_url=None, codereview_dispatcher=None) -> None: ...  # :109

# From parrot/flows/dev_loop/nodes/base.py:152
class DevLoopNode(Node): ...

# From parrot/flows/dev_loop/streaming.py:51
class FlowStreamMultiplexer:
    def __init__(self, redis, *, run_id, view="both",
                 dispatch_refresh_seconds=2.0, block_ms=1000) -> None: ...
```

#### Verified Imports
```python
# Confirmed working at the pinned commit:
from parrot.bots.flows.core.context import FlowContext        # nodes/base.py:27
from parrot.bots.flows.core.node import Node                  # nodes/base.py:29
from parrot.bots.flows.core.types import DependencyResults    # nodes/deployment_handoff.py:30
from parrot.bots.flows.flow.flow import NODE_REGISTRY, register_node  # nodes/base.py:30
from parrot.flows.dev_loop.models import ManualCriterion      # nodes/qa.py:38
```

#### Key Attributes & Constants
- `WorkBrief.escalation_assignee` → `str` (parrot/flows/dev_loop/models.py:118 class; field verified in body) — gate-expiry escalation target
- `conf.FLOW_MAX_CONCURRENT_RUNS` (parrot/flows/dev_loop/runner.py:124 usage) — run-cap semantics to preserve
- Redis stream keys: `flow:{run_id}:flow`, `flow:{run_id}:dispatch:{node_id}` (streaming.py module docstring)
- Flow event names emitted: `node_started`, `node_completed`, `node_failed`, `node_skipped` (flow.py:18, prefixed `flow.` at :105)

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.flows.dev_loop.session_state`~~ — module does not exist yet (this feature creates it)
- ~~`SessionHost` / `ApprovalGate` / `ActionEnvelope` / `DevLoopSessionState`~~ — nowhere in the codebase
- ~~any `ahp`/`a2a` package, import or dependency~~ — none in-tree
- ~~`FlowStreamMultiplexer.snapshot()`~~ / any snapshot mechanism — multiplexer only replays streams
- ~~a blocking path for `ManualCriterion`~~ — qa.py:301 always synthesizes `passed=True`
- ~~any approval step in `DeploymentHandoffNode.execute`~~ — Jira transition is unconditional on the success path
- ~~`DevLoopRunner.resolve_gate` / gate awareness~~ — runner has no HITL surface
- ~~server-side sequence numbers~~ — Redis Stream IDs exist, but no per-run monotonic `server_seq` in envelopes

---

## Parallelism Assessment

- **Internal parallelism**: High. Natural worktree split: (T1)
  `session_state.py` core + property tests (no in-tree deps beyond pydantic);
  (T2) runner/publisher dual-publish wiring (depends on T1 contracts only);
  (T3) QA + DeploymentHandoff gate integration (depends on T1); (T4)
  multiplexer `view="state"` (depends on T1+T2). T3 and T4 are mutually
  independent.
- **Cross-feature independence**: Touches `runner.py`, `flow.py`,
  `nodes/qa.py`, `nodes/deployment_handoff.py`, `streaming.py` — check for
  in-flight FEAT-250/FEAT-270 follow-ups on the same files before branching.
- **Recommended isolation**: per-spec (one spec per new capability:
  `dev-loop-session-state` first, `dev-loop-approval-gates` layered on it).
- **Rationale**: the state core is dependency-free and contract-first; gates
  and adapters consume its frozen contracts, so specs can proceed serially
  at the spec level while tasks parallelize per worktree.

---

## Open Questions

- [ ] Should blocking manual criteria be opt-in per `ManualCriterion`
      (`blocking: bool = False`, preserving current behavior) or a
      flow-level config flag? — *Owner: Jesus*
- [x] Gate TTL defaults per kind (deployment_approval vs manual_criterion)
      and whether expiry → `failure_handler` or auto-approve for
      non-deployment kinds — *Owner: Jesus*: policy is **fail-closed vs
      fail-open per kind**, encoded as `ApprovalGate.on_expiry:
      Literal["fail", "approve"] = "fail"`. Defaults (conf-overridable via
      `DEV_LOOP_GATE_TTL_*`, per-gate override via `open_gate(ttl_seconds)`):
      `deployment_approval` 24h fail-closed; blocking `manual_criterion`
      72h fail-closed; `revision_approval` 24h fail-closed;
      `plan_approval` 4h **fail-open**. Rule: gates guarding
      irreversible/external effects (deploy, PR push, mandated human
      verification) never auto-approve — silence ≠ consent — and expire
      into `failure_handler` escalation; advisory gates (plan) auto-approve
      on expiry so their absence-of-answer degrades to today's behavior.
      The reducer is untouched: the host's expiry sweep emits `GateExpired`
      (fail-closed) or `GateResolved(resolved_by="system:ttl-auto-approve")`
      (fail-open), so auto-approvals are explicitly audited in-state like
      any human resolution.
- [x] Does rejection of a `deployment_approval` gate route to
      `failure_handler` (escalation) or to the revision graph
      (FEAT-250 G6) for rework? — *Owner: Jesus*: rejection routes to
      `failure_handler` (escalation to `escalation_assignee`). A human
      reject is semantically a failed run, not a near-miss; legitimate
      rework keeps its existing channel — PR comments trigger the revision
      loop via `register_pull_request_webhook` — so routing reject to the
      revision graph would duplicate that mechanism with ambiguous
      semantics.
- [x] Envelope retention policy for `flow:{run_id}:actions` (XTRIM MAXLEN vs
      keep-forever for audit; interaction with `sweep_finished_worktrees`)
      — *Owner: Jesus*: **snapshot-at-terminal + trim** — the envelope log
      is operational (live replay), not the audit record; audit already
      lives in the Jira trail, PR history and the gate resolution fields
      persisted in-state. Three layers: (1) during the run,
      `XADD … MAXLEN ~ 100000` as a safety cap only; (2) on terminal phase
      the host serializes the final `Snapshot` (which carries the full gate
      audit) and persists it as a run artifact alongside the other run
      outputs (or attached to the Jira ticket); (3) the actions stream is
      deleted by the same sweep as `sweep_finished_worktrees` after a
      7-day grace (`DEV_LOOP_ACTIONS_RETENTION_DAYS = 7`). Optional future
      hardening (out of scope here): Ed25519/RFC 3161 signing of the
      terminal snapshot, reusing the attestation-system pattern.
- [x] Should the Svelte reducer port be generated from the Pydantic JSON
      Schema (codegen) or hand-written with a schema-parity CI test?
      — *Owner: Jesus*: both, split by layer. **Types are generated**:
      `model_json_schema()` on the action union / state / envelope →
      `json-schema-to-typescript` (Pydantic v2 discriminated unions emit
      `oneOf` + `discriminator` → TS tagged unions; adding an action in
      Python breaks `tsc` exhaustiveness in the TS reducer = drift gate).
      **Reducer logic is hand-written** (schemas describe shape, not
      transitions), verified by golden-fixture parity: a Python script
      (hypothesis-driven) generates `(action_log, expected_snapshot)` JSON
      fixtures; nav-admin CI folds each log with the TS reducer and
      deep-equals the snapshot. Pure + deterministic on both sides ⇒
      fixture equality is observational equivalence.
- [x] Naming: keep AHP-shaped channel URIs (`ahp-session:/…`) or use a
      neutral scheme (`parrot-session:/…`) until a wire adapter exists?
      — *Owner: Jesus*: neutral scheme (`parrot-session:/`,
      `parrot-terminal:/`, `parrot-changeset:/`, root `parrot-root://`).
      AHP is DRAFT and URIs are persisted inside XADDed envelopes; the
      `parrot-*` → `ahp-*` (or A2A task-id) translation is a mapping owned
      exclusively by the future wire adapter.
