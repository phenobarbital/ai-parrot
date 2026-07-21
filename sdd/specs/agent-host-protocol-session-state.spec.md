---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: AHP-style Session State, Host & HITL Approval Gates for dev-loop

**Feature ID**: FEAT-322
**Date**: 2026-07-21
**Author**: Jesus Lara (with Claude)
**Status**: draft
**Target version**: next minor
**Proposal**: `sdd/proposals/agent-host-protocol-session-state.proposal.md`
**Brainstorm**: `sdd/proposals/dev-loop-session-state-hitl.brainstorm.md` (Option B ⭐)
**Design sketch**: `sdd/artifacts/devloop_session_state.py` (contract-complete, user-provided)
**Research audit**: `sdd/state/FEAT-322/`

---

## 1. Motivation & Business Requirements

### Problem Statement

The dev-loop (FEAT-129/132/250) is an ad-hoc orchestration process whose
observability layer is an *event log*, not an *authoritative state*:

1. **No snapshot semantics.** `FlowStreamMultiplexer` fans in two Redis
   Streams and emits flat envelopes; a client joining mid-run must replay the
   whole stream and reconstruct state client-side. Every client reimplements
   that fold and can diverge.
2. **No multi-client write arbitration.** Nothing prevents two operators from
   issuing conflicting commands (cancel, approve) against the same run; no
   sequenced, auditable "who did what, and who won" record exists.
3. **No blocking HITL.** `QANode._merge_manual_results` synthesizes
   `passed=True` for every `ManualCriterion`; `DeploymentHandoffNode` pushes,
   opens the draft PR and transitions Jira with zero in-loop human approval.
4. **Standards drift risk.** Microsoft's Agent Host Protocol (AHP, DRAFT) and
   Google's A2A converge on the same shape: authoritative session state +
   sequenced mutations + an `input-required`-like blocked state. dev-loop has
   none of the invariant core (state tree, typed actions, pure reducers) any
   of them would sit on.

### Goals

- **G1 — Authoritative session state**: one frozen, snapshot-able state tree
  per run (`DevLoopSessionState`), mutated exclusively by a closed
  discriminated action union folded through a pure, total, non-raising
  reducer. `fold(log) == state` is a property-tested invariant.
- **G2 — AHP-shaped host**: `DevLoopRunner` acts as the AHP-style *host*:
  it owns one `SessionHost` per run (registry keyed by `run_id`), a
  root-channel run catalogue (`RunRegistryState`, ≅ `ahp-root://`), sequenced
  `ActionEnvelope`s with per-channel `server_seq`, `origin` attribution and
  snapshot/replay semantics — with **zero wire-protocol coupling**.
- **G3 — Blocking HITL gates**: `ApprovalGate` as first-class state —
  `manual_criterion` (per-criterion opt-in), `deployment_approval` (before
  the Jira transition), `revision_approval`, `plan_approval` — with
  first-writer-wins arbitration validated *before* sequencing, per-kind
  fail-closed/fail-open TTL expiry, and a full in-state audit trail.
- **G4 — Zero-regression migration**: dual-publish keeps every legacy
  envelope flowing unchanged; `DevLoopRunner(flow)` legacy construction,
  non-blocking manual criteria and `FLOW_MAX_CONCURRENT_RUNS` semantics all
  preserved by default.
- **G5 — Client surface**: `FlowStreamMultiplexer` gains `view="state"`
  (snapshot on connect + `server_seq`-ordered envelopes with replay); gate
  and cancel commands arrive via REST endpoints backed by the runner.

### Non-Goals (explicitly out of scope)

- **AHP wire compatibility** — no JSON-RPC framing, `initialize`/capability
  negotiation, RFC 9728/6750 auth, or `ahp-*` URIs. AHP is DRAFT ("Breaking
  changes to wire types, actions, and state shapes are expected" — verified
  2026-07-21). Full wire adoption was rejected in the brainstorm (Option A);
  a future wire-adapter spec maps `parrot-*` → `ahp-*` (or A2A task ids).
- Gates-only patching without a state model — rejected in brainstorm
  (Option C: throwaway work, ad-hoc arbitration).
- nav-admin Svelte reducer port + golden-fixture parity CI (separate repo,
  follow-up; this spec only guarantees the JSON Schema export hook).
- Ed25519 / RFC 3161 signing of terminal snapshots (brainstorm: optional
  future hardening).
- Changes to flow topology, CEL predicates, or the FEAT-270 review loop.
- Releasing the run-cap semaphore slot while `awaiting_gate` (see §8).

---

## 2. Architectural Design

### Overview

Adopt brainstorm **Option B**, extended one level up per the AHP host model.
A new transport-free module `parrot/flows/dev_loop/session_state.py` holds
the three invariant layers from the design sketch: (1) frozen state trees —
`DevLoopSessionState` per run **plus** `RunRegistryState` for the root
channel (proposal U2: in scope); (2) closed discriminated action unions —
20 session actions + 3 root actions; (3) pure reducers + `SessionHost`
(sequencing, snapshot, replay, gate arbitration, expiry sweep). Channel URIs
use the neutral `parrot-*` scheme (brainstorm-resolved): `parrot-root://`,
`parrot-session:/<run_id>`, `parrot-terminal:/<run_id>/<node_id>`,
`parrot-changeset:/<run_id>`.

Aligning with AHP's published common types, `ActionEnvelope` carries
`origin: Optional[ActionOrigin]` (`client_id`, `client_seq`) and
`rejection_reason: str = ""` in addition to the sketch's
`channel`/`server_seq`/`action` — the multi-client attribution AHP puts on
every envelope.

`DevLoopRunner` becomes the host: it keeps `Dict[run_id, SessionHost]`,
applies run-lifecycle actions (`RunCreated`/`RunClosed` on the session
channel, `RunAdded`/`RunSummaryChanged`/`RunRemoved` on the root channel),
drives a periodic gate-expiry sweep, and exposes the command methods
(`resolve_gate`, `cancel_run`) that the REST layer adapts. **Host resolution
is registry-based, never reference-captured**: one `AgentsFlow` instance
serves concurrent runs and `FlowEventPublisher` already resolves `run_id`
per event from the FlowContext — the shims follow the same pattern.

Existing producers are bridged by two 1:1 shims (`action_from_flow_event`,
`action_from_dispatch_event`) invoked at the two existing XADD sites
(publisher + dispatchers), dual-publishing to a new per-run stream
`flow:{run_id}:actions` while legacy streams keep flowing unchanged.

HITL: `QANode` opens one `manual_criterion` gate per `ManualCriterion` with
`blocking=True` (new field, default `False` — proposal U1) after the
FEAT-270 review loop, awaits resolution, and folds outcomes into
`QAReport.criterion_results` *before returning* (CEL edges route on
`result.passed`). `DeploymentHandoffNode` opens a `deployment_approval` gate
after the draft PR exists and **before** the Jira transition; approve →
continue, reject/expire → route to `failure_handler` (brainstorm-resolved:
a human reject is a failed run; rework stays on the PR-comment revision
loop). Expiry policy is per-kind fail-closed/fail-open via
`ApprovalGate.on_expiry: Literal["fail","approve"]` with conf-overridable
TTL defaults (brainstorm-resolved): `deployment_approval` 24h fail,
blocking `manual_criterion` 72h fail, `revision_approval` 24h fail,
`plan_approval` 4h approve (auto-approved by `system:ttl-auto-approve`,
audited in-state).

Retention (brainstorm-resolved): the actions stream is operational, not the
audit record — `XADD … MAXLEN ~ 100000` during the run; on terminal phase
the host serializes the final `Snapshot` (carrying the full gate audit) as a
run artifact; the stream is deleted by the finished-run sweep after
`DEV_LOOP_ACTIONS_RETENTION_DAYS = 7`.

Client surface (proposal U3): WS for reads — `view="state"` on the
multiplexer (snapshot, then envelopes; reconnect replays
`server_seq > last_seen`, mirroring AHP `reconnect`); REST for writes —
`POST /runs/{run_id}/gates/{gate_id}/resolve` and
`POST /runs/{run_id}/cancel` (200 envelope | 404 unknown | 409
already-resolved with resolver identity).

### Component Diagram

```
                         parrot-root://  (RunRegistryState)
                               ▲ RunAdded/RunSummaryChanged/RunRemoved
┌──────────────────────────────┴──────────────────────────────────────┐
│ DevLoopRunner  (AHP-style HOST)                                     │
│   _hosts: Dict[run_id, SessionHost]     _expiry sweep (asyncio task)│
│   run()/run_revision() ──create/close──▶ SessionHost (per run)      │
│   resolve_gate()/cancel_run() ──────────▶   ├ state: DevLoopSessionState
└──────────────┬───────────────────────────   ├ apply() → server_seq  │
               │ commands                     ├ snapshot()/replay_since()
   REST (aiohttp)                             └ on_envelope ──▶ XADD  │
   POST /runs/{id}/gates/{gid}/resolve                flow:{run_id}:actions
   POST /runs/{id}/cancel                                   │
                                                            ▼
 AgentsFlow ──▶ FlowEventPublisher ──shim──▶ host.apply(action)   FlowStreamMultiplexer
      │              │ legacy XADD flow:{run_id}:flow              view="state":
      ▼              ▼                                             Snapshot + envelopes
 QANode / DeploymentHandoffNode        Dispatchers (Claude/Codex/…)  (legacy views intact)
   open_gate() + await resolution        │ legacy XADD flow:{run_id}:dispatch:{node}
   (manual_criterion / deployment)       └─shim──▶ host.apply(action)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `DevLoopRunner` (runner.py:100) | extends | host registry, root catalogue, expiry sweep, `resolve_gate`/`cancel_run`; `active_runs`/`is_active` (:143/:147) preserved |
| `FlowEventPublisher.__call__` (flow.py:94) | extends | dual-publish: after legacy XADD, registry-resolve host by per-event run_id, `host.apply(shim(event))` |
| Dispatcher XADD paths (dispatcher.py:816, :1281, :1721, :2565) | extends | same dual-publish via `action_from_dispatch_event`; all dispatcher families, one shim |
| `ManualCriterion` (models.py:70) | extends | new field `blocking: bool = False` (proposal U1) |
| `QANode` (nodes/qa.py:108, :301) | modifies | blocking criteria open gates after the FEAT-270 review loop; resolutions fold into `QAReport` pre-return |
| `DeploymentHandoffNode.execute` (nodes/deployment_handoff.py:89) | modifies | `deployment_approval` gate between PR creation and Jira transition |
| `FlowStreamMultiplexer` (streaming.py:51) + `flow_stream_ws` (:298) | extends | new `view="state"`; legacy `flow|dispatch|both` untouched |
| aiohttp app wiring (webhook.py pattern, :292) | uses | REST command endpoints registered beside existing handlers |
| `WorkBrief.escalation_assignee` (models.py:161) | depends on | fail-closed expiry / rejection escalation target |
| Redis | extends | new stream `flow:{run_id}:actions` (MAXLEN ~100k); legacy streams unchanged |

### Data Models

Authoritative contracts live in the design sketch
`sdd/artifacts/devloop_session_state.py` and land verbatim-in-structure in
`session_state.py`. Key shapes (signatures only — no implementation here):

```python
# Frozen base: model_config = ConfigDict(frozen=True, extra="forbid")

# ── Session channel ──────────────────────────────────────────────
NodeId     = Literal["intent_classifier","bug_intake","research","development",
                     "qa","deployment_handoff","revision_handoff",
                     "failure_handler","close"]          # == definition.py roster
RunPhase   = Literal["created","running","awaiting_gate","succeeded","failed","cancelled"]
GateKind   = Literal["manual_criterion","deployment_approval","revision_approval","plan_approval"]
GateStatus = Literal["pending","approved","rejected","expired"]

class DispatchState(_Frozen):   # counters + refs only; heavy content by-reference
    status: DispatchStatus; dispatcher: str; message_count: int
    tool_use_count: int; last_error: str; terminal: str   # parrot-terminal:/ URI

class NodeState(_Frozen):
    node_id: NodeId; status: NodeStatus; error: str
    dispatch: Optional[DispatchState]; summary: Dict[str, str]

class ApprovalGate(_Frozen):
    gate_id: str; kind: GateKind; node_id: NodeId; status: GateStatus
    on_expiry: Literal["fail", "approve"] = "fail"
    title: str; instructions: str; payload_ref: str
    opened_at: float; expires_at: Optional[float]
    resolved_by: str; resolved_at: Optional[float]; comment: str

class DevLoopSessionState(_Frozen):
    run_id: str; channel: str; revision: bool; phase: RunPhase
    work_kind: ...; summary: str; jira_issue_key: str; pr_url: str
    nodes: Dict[str, NodeState]; gates: Dict[str, ApprovalGate]
    cancel_requested_by: str; error: str

# ── Action union (closed, discriminator="type") ──────────────────
# run/created  run/cancelled  run/closed
# node/started  node/completed  node/failed  node/skipped
# dispatch/queued  dispatch/started  dispatch/delta  dispatch/tool_use
# dispatch/tool_result  dispatch/output_invalid  dispatch/failed  dispatch/completed
# gate/opened  gate/resolved  gate/expired
# run/jiraLinked  run/prLinked
DevLoopAction = Annotated[Union[...20 variants...], Field(discriminator="type")]

# ── Envelope & snapshot (AHP-aligned; extends the sketch) ────────
class ActionOrigin(_Frozen):            # NEW vs sketch — AHP common type
    client_id: str
    client_seq: int

class ActionEnvelope(_Frozen):
    channel: str
    server_seq: int
    action: DevLoopAction
    origin: Optional[ActionOrigin] = None      # NEW vs sketch
    rejection_reason: str = ""                 # NEW vs sketch

class Snapshot(_Frozen):
    channel: str; state: DevLoopSessionState; from_seq: int

# ── Root channel (NEW vs sketch — proposal U2) ───────────────────
class RunSummary(_Frozen):
    run_id: str; phase: RunPhase; work_kind: str; summary: str
    jira_issue_key: str; pr_url: str; pending_gate_count: int
    created_at: float; finished_at: Optional[float]

class RunRegistryState(_Frozen):
    channel: str                                # parrot-root://
    runs: Dict[str, RunSummary]

class RunAdded(_ActionBase):          type: Literal["root/runAdded"];   summary: RunSummary
class RunSummaryChanged(_ActionBase): type: Literal["root/runSummaryChanged"]; summary: RunSummary
class RunRemoved(_ActionBase):        type: Literal["root/runRemoved"]; run_id: str
RootAction = Annotated[Union[RunAdded, RunSummaryChanged, RunRemoved],
                       Field(discriminator="type")]
```

### New Public Interfaces

```python
# session_state.py — pure functions
def reduce(state: DevLoopSessionState, action: DevLoopAction) -> DevLoopSessionState:
    """Pure, total, non-raising. fold(log) == state is the invariant."""
def reduce_root(state: RunRegistryState, action: RootAction) -> RunRegistryState: ...
def session_channel(run_id: str) -> str: ...      # parrot-session:/<run_id>
def terminal_channel(run_id: str, node_id: str) -> str: ...
def changeset_channel(run_id: str) -> str: ...
ROOT_CHANNEL = "parrot-root://"

# session_state.py — host (single-writer per run, runner-event-loop driven)
class SessionHost:
    def __init__(self, run_id: str, *, on_envelope: Optional[Callable] = None) -> None: ...
    @property
    def state(self) -> DevLoopSessionState: ...
    def snapshot(self) -> Snapshot: ...
    def replay_since(self, last_seen_server_seq: int) -> List[ActionEnvelope]: ...
    def apply(self, action: DevLoopAction,
              origin: Optional[ActionOrigin] = None) -> ActionEnvelope: ...
    def resolve_gate(self, gate_id: str, resolution: Literal["approved","rejected"],
                     resolved_by: str, comment: str = "") -> ActionEnvelope:
        """Validated BEFORE sequencing — first writer wins; later attempts
        raise GateAlreadyResolvedError / GateNotFoundError, never sequenced."""
    def open_gate(self, *, kind, node_id, title, instructions="", payload_ref="",
                  ttl_seconds=None, on_expiry="fail") -> Tuple[str, ActionEnvelope]: ...
    def expire_due_gates(self, now: Optional[float] = None) -> List[ActionEnvelope]: ...
    def wait_gate(self, gate_id: str) -> Awaitable[ApprovalGate]:
        """asyncio.Event-backed await used by gate-opening nodes."""

# session_state.py — migration shims (1:1, None = ignore)
def action_from_flow_event(event, node_id, ts, error="") -> Optional[DevLoopAction]: ...
def action_from_dispatch_event(kind, node_id, ts, payload=None) -> Optional[DevLoopAction]: ...

# runner.py — host/command surface
class DevLoopRunner:
    def get_host(self, run_id: str) -> Optional[SessionHost]: ...
    @property
    def registry_state(self) -> RunRegistryState: ...
    async def resolve_gate(self, run_id, gate_id, resolution, resolved_by,
                           comment="") -> ActionEnvelope: ...
    async def cancel_run(self, run_id: str, requested_by: str) -> ActionEnvelope: ...

# handlers (new module) — REST adapters over the runner
# POST /runs/{run_id}/gates/{gate_id}/resolve   {resolution, resolved_by, comment}
#   → 200 {envelope} | 404 unknown run/gate | 409 {resolved_by, resolved_at, status}
# POST /runs/{run_id}/cancel                    {requested_by}
```

### Exceptions

```python
class GateNotFoundError(KeyError): ...
class GateAlreadyResolvedError(RuntimeError): ...   # carries resolver identity
```

---

## 3. Module Breakdown

### Module 1: Session-state core (`dev-loop-session-state` capability)
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py`
- **Responsibility**: everything in §2 Data Models + New Public Interfaces —
  state trees (session + root), action unions, `reduce`/`reduce_root`,
  `SessionHost`, channel URI helpers, shims, exceptions. **Imports pydantic +
  stdlib ONLY** (no aiohttp/redis/jsonrpc — enforced by test).
- **Depends on**: nothing in-tree beyond pydantic (sketch is the blueprint).

### Module 2: Property & unit tests for the core
- **Path**: `packages/ai-parrot/tests/flows/dev_loop/test_session_state.py`
- **Responsibility**: hypothesis property tests — `fold(replay_since(0)) ==
  state`, reducer totality (random action sequences never raise), terminal-
  phase stickiness, gate arbitration (first-writer-wins, conflicting resolve
  = no-op in reducer / raise in host), expiry policies (fail vs approve,
  `system:ttl-auto-approve` audit), root reducer, shim mappings 1:1.
- **Depends on**: Module 1.

### Module 3: Runner as host
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/runner.py`
- **Responsibility**: `_hosts` registry + `RunRegistryState`; create host +
  `RunCreated`/`RunAdded` in `run()`/`run_revision()` (run-<hex8>/rev-<hex8>
  ids preserved); terminal handling — `RunClosed`, terminal-snapshot
  persistence, `RunRemoved` after retention; per-run envelope sink (XADD
  `flow:{run_id}:actions`, MAXLEN ~100000, failures swallowed); expiry-sweep
  asyncio task; `resolve_gate`/`cancel_run`/`get_host`/`registry_state`.
  Conf keys: `DEV_LOOP_GATE_TTL_DEPLOYMENT` (86400), `_MANUAL` (259200),
  `_REVISION` (86400), `_PLAN` (14400), `DEV_LOOP_ACTIONS_RETENTION_DAYS` (7).
- **Depends on**: Module 1.

### Module 4: Dual-publish shims
- **Path**: `flow.py` (`FlowEventPublisher.__call__`) + `dispatcher.py`
  (the four XADD sites: :816 Claude, :1281 Codex, :1721 Gemini, :2565 LLM
  family — via one shared helper, not four copies)
- **Responsibility**: after each legacy XADD, resolve the host from the
  runner registry by the SAME run_id already computed per-event and
  `host.apply(shim(...))`. Both failures swallowed independently — legacy
  publish never depends on the new path and vice versa.
- **Depends on**: Modules 1, 3.

### Module 5: HITL gate integration (`dev-loop-approval-gates` capability)
- **Path**: `models.py` (`ManualCriterion.blocking: bool = False`),
  `nodes/qa.py`, `nodes/deployment_handoff.py`
- **Responsibility**: QA — for `blocking=True` criteria open one
  `manual_criterion` gate each (after the FEAT-270 review loop + manual
  merge point), `await host.wait_gate(...)`, fold approved→passed /
  rejected|expired→failed into `criterion_results` before returning;
  non-blocking criteria keep `_merge_manual_results` synthesis unchanged.
  DeploymentHandoff — open `deployment_approval` gate after PR creation
  (payload_ref = changeset URI, pr_url in title/instructions), await;
  approve → Jira transition proceeds; reject/expire → return
  `{"status": "blocked", "error": "deployment_approval <rejected|expired> by <who>"}`
  (reuses the existing blocked path + `_mark_blocked`; run routes to
  `failure_handler` per existing topology, escalating to
  `escalation_assignee`). Nodes obtain the host via shared state
  (`shared["session_host"]`, seeded by the runner) — nodes never import the
  runner.
- **Depends on**: Modules 1, 3.

### Module 6: Streaming `view="state"`
- **Path**: `streaming.py` (`FlowStreamMultiplexer`, `flow_stream_ws`)
- **Responsibility**: extend `ViewLiteral` with `"state"`; on connect emit
  `{"source":"state","event_kind":"snapshot", payload: Snapshot}` (host if
  live, else rebuilt by folding `flow:{run_id}:actions` from seq 0), then
  relay envelopes; `?last_seen=<server_seq>` replays the gap (AHP reconnect
  semantics). Legacy views byte-identical.
- **Depends on**: Modules 1, 3 (+ 4 for live envelopes).

### Module 7: REST command endpoints
- **Path**: new `packages/ai-parrot/src/parrot/flows/dev_loop/commands.py`
  (aiohttp handlers registered like webhook.py's pattern)
- **Responsibility**: `POST /runs/{run_id}/gates/{gate_id}/resolve` and
  `POST /runs/{run_id}/cancel` → runner methods; map
  `GateNotFoundError`/unknown run → 404, `GateAlreadyResolvedError` → 409
  with resolver identity, success → 200 envelope JSON. Build
  `ActionOrigin(client_id=<caller identity>, client_seq=<from body|0>)`.
- **Depends on**: Modules 1, 3.

**Task-level parallelism** (brainstorm assessment): M1+M2 first (T1);
then M3+M4 (T2); M5 (T3) and M6+M7 (T4) are mutually independent after T2.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_fold_replay_equals_state` | M2 | hypothesis: applying random action sequences, `fold(replay_since(0)) == host.state` |
| `test_reducer_total_never_raises` | M2 | hypothesis: reducer accepts any action in any state (incl. terminal) without raising |
| `test_terminal_phase_sticky` | M2 | actions after cancelled/succeeded/failed never change phase |
| `test_gate_first_writer_wins` | M2 | second `resolve_gate` raises `GateAlreadyResolvedError` with resolver identity; log contains exactly one `gate/resolved` |
| `test_gate_expiry_fail_closed` | M2 | `on_expiry="fail"` sweep emits `GateExpired`; phase recomputed |
| `test_gate_expiry_fail_open` | M2 | `on_expiry="approve"` sweep emits `GateResolved(resolved_by="system:ttl-auto-approve")` |
| `test_awaiting_gate_phase` | M2 | pending gate ⇒ `awaiting_gate`; resolution ⇒ back to `running` |
| `test_root_reducer` | M2 | RunAdded/RunSummaryChanged/RunRemoved fold correctly; unknown run removal = no-op |
| `test_shim_mappings_1to1` | M2 | every `flow.*` event and `DispatchEvent.kind` maps to the documented action; unknown → None |
| `test_no_transport_imports` | M2 | `session_state` module imports contain no aiohttp/redis/jsonrpc |
| `test_envelope_origin_rejection_fields` | M2 | ActionEnvelope round-trips origin + rejection_reason |
| `test_runner_host_lifecycle` | M3 | run() creates host + RunAdded; terminal → RunClosed + snapshot persisted |
| `test_runner_registry_isolation` | M3 | two concurrent runs get distinct hosts; envelopes land on their own streams |
| `test_runner_resolve_gate_routing` | M3 | resolve_gate targets the right host; unknown run raises |
| `test_dual_publish_legacy_unchanged` | M4 | legacy `flow:{run_id}:flow` envelope bytes unchanged with shims active |
| `test_shim_swallow_redis_down` | M4 | XADD failure on actions stream: run proceeds, in-memory state still folds |
| `test_manual_blocking_default_false` | M5 | no `blocking` set ⇒ behavior identical to today (synthesis path) |
| `test_qa_blocking_gate_approved` | M5 | blocking criterion approved ⇒ `criterion_results` passed=True + audit |
| `test_qa_blocking_gate_rejected` | M5 | rejected/expired ⇒ passed=False ⇒ `QAReport.passed=False` routes to failure |
| `test_handoff_gate_before_jira` | M5 | Jira transition NOT called until gate approved; called after |
| `test_handoff_gate_rejected_blocks` | M5 | reject ⇒ blocked status, `_mark_blocked`, no Jira transition |
| `test_view_state_snapshot_then_actions` | M6 | connect ⇒ snapshot first, then ordered envelopes |
| `test_view_state_replay_last_seen` | M6 | `?last_seen=N` ⇒ only envelopes with server_seq > N |
| `test_rest_resolve_200_404_409` | M7 | status-code contract incl. 409 body with resolver identity |

### Integration Tests

| Test | Description |
|---|---|
| `test_e2e_run_with_blocking_gates` | stub dispatcher run: QA blocking criterion + deployment gate; resolve via runner; assert final snapshot phases, gate audit, `flow:{run_id}:actions` fold == final state |
| `test_ws_state_view_reconnect` | connect mid-run, disconnect, reconnect with last_seen — no gaps/dupes (extends existing `test_websocket_replay.py` pattern) |
| `test_crash_rebuild_from_actions_stream` | fold `flow:{run_id}:actions` from 0 reproduces state incl. pending gates |

### Test Data / Fixtures

```python
@pytest.fixture
def host():                      # fresh SessionHost("run-test0001")
@pytest.fixture
def fake_redis():                # reuse existing dev-loop stream-stub pattern
@pytest.fixture
def action_sequences():          # hypothesis strategies over the action union
```

---

## 5. Acceptance Criteria

- [ ] `session_state.py` imports only pydantic + stdlib (verified by test);
      all models `frozen=True, extra="forbid"`; action unions closed with
      `discriminator="type"`.
- [ ] Property invariant holds: `fold(replay_since(0)) == state` under
      hypothesis-generated action sequences; reducer is total and
      non-raising; terminal phases sticky.
- [ ] Gate arbitration is first-writer-wins **validated before sequencing**:
      exactly one `gate/resolved` envelope per gate; later attempts raise
      `GateAlreadyResolvedError` carrying who/when; audit fields
      (`resolved_by`, `resolved_at`, `comment`) present in-state.
- [ ] Per-kind TTL policy enforced: deployment 24h / blocking-manual 72h /
      revision 24h fail-closed → `GateExpired` + escalation route;
      plan 4h fail-open → auto-approve audited as `system:ttl-auto-approve`.
      TTLs conf-overridable (`DEV_LOOP_GATE_TTL_*`), per-gate override via
      `open_gate(ttl_seconds=...)`.
- [ ] `ManualCriterion.blocking` defaults to `False` and existing QA behavior
      is byte-identical for unset criteria; blocking criteria gate the run
      and fold into `QAReport` before `QANode.execute` returns.
- [ ] `DeploymentHandoffNode` never calls the Jira transition before a
      `deployment_approval` gate is approved; reject/expire routes the run
      to `failure_handler` (existing blocked path).
- [ ] Dual-publish: legacy `flow:{run_id}:flow` and
      `flow:{run_id}:dispatch:{node_id}` envelopes unchanged (existing
      streaming/dispatcher tests pass unmodified); new
      `flow:{run_id}:actions` stream carries sequenced envelopes with
      MAXLEN ~100000; all new-path failures swallowed
      (`host.apply` still folds in-memory when Redis is down).
- [ ] Root channel: `registry_state` reflects add/summary-change/remove for
      concurrent runs; per-run hosts are registry-resolved (two concurrent
      runs never cross-contaminate envelopes or state).
- [ ] `view="state"`: snapshot precedes envelopes; `last_seen` replay has no
      gaps or duplicates; legacy views unchanged.
- [ ] REST contract: 200 envelope / 404 unknown / 409 already-resolved (with
      resolver identity); cancel produces terminal-sticky `run/cancelled`.
- [ ] Terminal snapshot persisted as a run artifact on terminal phase;
      actions stream swept after `DEV_LOOP_ACTIONS_RETENTION_DAYS` (7).
- [ ] `FLOW_MAX_CONCURRENT_RUNS` semantics and legacy `DevLoopRunner(flow)`
      construction unchanged; `pending_gate_count` surfaced in `RunSummary`.
- [ ] JSON Schema export hook: `model_json_schema()` emits `oneOf` +
      `discriminator` for the action union (Svelte codegen consumes later).
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`.
- [ ] No breaking changes to existing public API (`parrot.flows.dev_loop`
      exports remain; new symbols added to `__init__.py`).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** All references verified
> 2026-07-21 on branch `dev` (post-FEAT-270; research audit
> `sdd/state/FEAT-322/findings/F002`). Paths relative to
> `packages/ai-parrot/src/`. These files are under ACTIVE development
> (FEAT-270 / new dispatchers) — re-verify at task time.

### Verified Imports

```python
from parrot.flows.dev_loop.flow import FlowEventPublisher       # dev_loop/__init__.py:25
from parrot.flows.dev_loop.runner import DevLoopRunner          # dev_loop/__init__.py:26
from parrot.flows.dev_loop.streaming import FlowStreamMultiplexer, flow_stream_ws  # __init__.py:28-31
from parrot.flows.dev_loop.webhook import register_pull_request_webhook            # __init__.py:32-34
from parrot.flows.dev_loop.models import ManualCriterion        # used at nodes/qa.py:38
from parrot.bots.flows.core.context import FlowContext          # nodes/base.py:27
from parrot.bots.flows.core.node import Node                    # nodes/base.py:29
from parrot.bots.flows.core.types import DependencyResults      # nodes/deployment_handoff.py:30
from parrot import conf                                         # runner.py:25
```

### Existing Class Signatures

```python
# parrot/flows/dev_loop/runner.py
class DevLoopRunner:                                            # :100
    def __init__(self, flow: AgentsFlow, *, max_concurrent_runs=None,
                 dispatcher=None, jira_toolkit=None, git_toolkit=None,
                 redis_url=None, codereview_dispatcher=None) -> None: ...  # :109
    active_runs: Set[str]        # property, :143 (copy of self._active)
    def is_active(self, run_id: str) -> bool: ...               # :147
    async def run(self, brief: WorkBrief, *, run_id=None, initial_task="",
                  extra_shared=None) -> FlowResult: ...         # :153; mints run-<hex8> :177
    async def run_revision(self, brief: RevisionBrief, *, run_id=None)
                  -> FlowResult: ...                            # :211; mints rev-<hex8> :245
# semaphore: asyncio.Semaphore(FLOW_MAX_CONCURRENT_RUNS) :126 (conf read :121-125)
# seeds shared_data: bug_brief/work_brief/run_id :178-182
# sets flow._run_id_holder["run_id"] pre-run :194-196 (FALLBACK only — see flow.py)

# parrot/flows/dev_loop/flow.py
class FlowEventPublisher:                                       # :71
    def __init__(self, redis_url: str, run_id_holder: Dict[str, str]) -> None: ...  # :89
    async def __call__(self, event: str, node_id: str, info: Dict[str, Any]) -> None:  # :94
        # run_id from info["context"].shared_data["run_id"] :97-99 (PER EVENT —
        # concurrent runs on ONE flow instance publish to their own streams);
        # holder fallback :100-101; XADD flow:{run_id}:flow maxlen=10_000 :113-118;
        # every failure swallowed :119-120
# flow event names: node_started/node_completed/node_failed/node_skipped (prefixed "flow.")

# parrot/flows/dev_loop/streaming.py
class FlowStreamMultiplexer:                                    # :51
    def __init__(self, redis, *, run_id, view: ViewLiteral = "both",
                 dispatch_refresh_seconds=2.0, block_ms=1000) -> None: ...  # :54
    async def replay(self) -> AsyncIterator[Dict[str, Any]]: ...  # :133
    async def tail(self) -> AsyncIterator[Dict[str, Any]]: ...    # :163
    async def close(self) -> None: ...                            # :209
ViewLiteral = Literal["flow", "dispatch", "both"]               # :43
async def flow_stream_ws(request: web.Request) -> web.WebSocketResponse: ...  # :298
# envelope: {"source","node_id","event_kind","ts","payload"}; ?view= & ?replay= params

# parrot/flows/dev_loop/dispatcher.py
class DevLoopCodeDispatcher(Protocol):                          # :129
    async def dispatch(self, *, brief: BaseModel, profile: BaseModel,
                       output_model: Type[T], run_id: str, node_id: str,
                       cwd: str) -> T: ...                      # :132
# XADD sites (one per dispatcher family — shim target):
#   Claude :816 · Codex :1281 · Gemini :1721 · LLM/Grok/Zai :2565
#   all: xadd(stream_key, fields, maxlen=maxlen, approximate=True)
#   stream: flow:{run_id}:dispatch:{node_id}

# parrot/flows/dev_loop/nodes/qa.py
class QANode(DevLoopNode):
    async def execute(self, ctx, deps=None, **kwargs) -> QAReport: ...  # :108
    # filters ManualCriterion pre-dispatch :129-136; FEAT-270 review loop
    # :148-164 (fix→re-run deterministic QA); manual merge :166-167;
    # passed = deterministic AND code_review :170; stores shared["qa_report"] :205
    @staticmethod
    def _merge_manual_results(report: QAReport,
                              manual: List[ManualCriterion]) -> QAReport: ...  # :301
    # synthesizes CriterionResult(passed=True, kind="manual", exit_code=0) :311-322

# parrot/flows/dev_loop/nodes/deployment_handoff.py
class DeploymentHandoffNode(DevLoopNode):                       # :46
    def __init__(self, *, jira_toolkit, git_toolkit=None, gh_cli_path=None,
                 target_repo=None, base_branch="dev",
                 name="deployment_handoff") -> None: ...        # :64
    async def execute(self, ctx, deps=None, **kwargs) -> Dict[str, Any]:  # :89
    # 1. push :118-126 → 2. DRAFT PR retry-once :128-160 →
    # 3. Jira transition UNCONDITIONAL :164-175 (gate goes between 2 and 3)
    # → 4. Jira comment :177+; blocked path returns {"status":"blocked","error":...}

# parrot/flows/dev_loop/models.py
class ManualCriterion(BaseModel): ...                           # :70  (kind="manual"; name, text; NO blocking field yet)
class WorkBrief(BaseModel): ...                                 # :118
    escalation_assignee: str                                    # :161
class QAReport(BaseModel): ...                                  # :349 (passed, criterion_results, lint_*, notes, code_review_* FEAT-250/270)
class DispatchEvent(BaseModel): ...                             # :698 (kind Literal of 8 dispatch.* values; ts/run_id/node_id/payload)

# parrot/flows/dev_loop/definition.py — node roster (== NodeId Literal)
# intent_classifier bug_intake research development qa deployment_handoff
# failure_handler close (+ revision_handoff) :36-44
# CEL predicates route on result fields: 'result.passed == true|false' :49-50
# on_error fan-in incl. HANDOFF → failure_handler :53, :118-121

# parrot/conf.py
CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES: int                     # :842 (fallback 3)
FLOW_MAX_CONCURRENT_RUNS: int                                  # :845 (fallback 5)
WORKTREE_BASE_PATH: str                                        # :860-862
DEV_LOOP_JIRA_TRANSITIONS_READY: list[str]                     # :925
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `SessionHost` registry | `DevLoopRunner.run/run_revision` | create/close host around `run_flow(ctx)` | runner.py:153/:211 |
| flow-event shim | `FlowEventPublisher.__call__` | after legacy XADD, same per-event run_id | flow.py:94-118 |
| dispatch shim | dispatcher XADD helper(s) | after legacy XADD | dispatcher.py:816/:1281/:1721/:2565 |
| QA gates | `QANode.execute` manual-merge point | replace `_merge_manual_results` call for blocking criteria | qa.py:166-167 |
| deployment gate | `DeploymentHandoffNode.execute` | between PR creation and Jira transition | deployment_handoff.py:160-164 |
| gate rejection routing | existing blocked/on_error paths | `{"status":"blocked"}` + `_mark_blocked` | deployment_handoff.py:153-160; definition.py:118-121 |
| `view="state"` | `FlowStreamMultiplexer` / `flow_stream_ws` | new ViewLiteral branch | streaming.py:43/:51/:298 |
| REST commands | aiohttp app | registered like webhook handlers | webhook.py:292 |
| host access from nodes | `ctx.shared_data["session_host"]` | seeded by runner beside run_id | runner.py:178-182 (pattern) |

### User-Provided Code (verified reference)

`sdd/artifacts/devloop_session_state.py` — complete design sketch: `_Frozen`
base, channel helpers, `DispatchState`/`NodeState`/`ApprovalGate`/
`DevLoopSessionState`, 20-action union, `ActionEnvelope`/`Snapshot`,
`reduce()` (+ `_with_node`/`_with_dispatch`/`_recompute_phase` helpers,
terminal-sticky), `SessionHost` (apply/snapshot/replay_since/resolve_gate/
open_gate/expire_due_gates), `GateAlreadyResolvedError`/`GateNotFoundError`,
`_FLOW_EVENT_MAP`/`_DISPATCH_KIND_MAP` shims. Implementing agents start from
this file; §2 lists the deltas (ActionOrigin, rejection_reason, root channel,
`wait_gate`, `on_envelope` sink).

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.flows.dev_loop.session_state`~~ — created by this feature (M1)
- ~~`SessionHost` / `ApprovalGate` / `ActionEnvelope` / `DevLoopSessionState` / `RunRegistryState` / `ActionOrigin`~~ — nowhere in-tree yet
- ~~`parrot.flows.dev_loop.commands`~~ — created by M7; NO REST/WS command surface exists today (webhook.py handles only GitHub PR webhooks)
- ~~`DevLoopRunner.resolve_gate` / `.cancel_run` / `.get_host` / `.registry_state` / `._hosts`~~ — runner has no HITL/host surface
- ~~`ManualCriterion.blocking`~~ — field does not exist yet (M5 adds it)
- ~~`ViewLiteral "state"` / `FlowStreamMultiplexer.snapshot()` / `?last_seen` param~~ — multiplexer only replays streams
- ~~`flow:{run_id}:actions` stream / per-run `server_seq`~~ — only Redis Stream IDs exist today
- ~~`DEV_LOOP_GATE_TTL_*` / `DEV_LOOP_ACTIONS_RETENTION_DAYS` conf keys~~ — M3 adds them (conf.py verified: absent)
- ~~any `ahp`/`a2a` package, import, or dependency~~ — none in-tree
- ~~`sweep_finished_worktrees`~~ — referenced in brainstorm as the sweep to mirror; verify actual sweep utility name at task time before citing it in code
- ~~a blocking path for `ManualCriterion` / any approval step in `DeploymentHandoffNode.execute`~~ — confirmed absent (qa.py:301, deployment_handoff.py:164)

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Per-event run_id resolution** exactly as `FlowEventPublisher.__call__`
  (flow.py:97-101): context first, holder fallback. The host lookup in shims
  MUST use the same run_id, resolved per event — never a captured reference
  (one `AgentsFlow` serves concurrent runs).
- **Never-break-a-run**: every new publish/apply path wrapped in
  swallow-and-log (flow.py:119-120 is the reference); `host.apply` folds
  in-memory even when the envelope XADD fails.
- **Frozen Pydantic v2 house style**: `frozen=True`, `extra="forbid"`,
  closed discriminated unions; `model_copy(update=...)` for state evolution
  (sketch already complies).
- **Node attribute style**: dev-loop nodes set attrs via
  `object.__setattr__` in `__init__` (qa.py:96-102, deployment_handoff.py:74-83).
- **Gate outcomes fold into results, not context**: CEL predicates route on
  the returned model (`result.passed`, definition.py:49-50) — QA gates must
  resolve before the node returns.
- **hypothesis for reducer properties** (dev-dep already used in repo tests).
- **XADD with `maxlen=..., approximate=True`** (flow.py:116-117,
  dispatcher.py:816) for the actions stream.
- Logging via `self.logger` / module logger; navconfig logging in runner.

### Known Risks / Gotchas

- **Active files**: qa.py / dispatcher.py / factories.py are hot (FEAT-270,
  Moonshot/Z.ai dispatchers landed in the last weeks). Re-verify §6 line
  anchors at `/sdd-task` and at each task start; keep the worktree
  short-lived and rebase early.
- **Gates hold the run-cap slot**: a run `awaiting_gate` keeps its
  `FLOW_MAX_CONCURRENT_RUNS` semaphore slot; long-TTL gates can starve
  throughput. v1 mitigation: conf-overridable TTLs + `pending_gate_count`
  in `RunSummary` for operator visibility (see §8).
- **Host crash mid-run**: rebuild by folding `flow:{run_id}:actions` from
  seq 0 (determinism invariant); pending gates survive as state. The
  `view="state"` handler uses the same fold when no live host exists.
- **Gate opened, node hard-errors**: `on_error` edge fires as today; the
  failure handler (or the expiry sweep as backstop) resolves orphaned gates
  as `expired`.
- **Late/duplicate GateResolved**: host validates `status == "pending"`
  before sequencing (raise); reducer treats a conflicting resolve as no-op
  (total, non-raising) — both layers required.
- **Run cancelled while awaiting_gate**: `run/cancelled` is terminal-sticky;
  pending gates remain in-state for audit but unreachable.
- **Dual-publish duplication** in Redis during migration — accepted
  (brainstorm), bounded by MAXLEN caps + 7-day sweep + terminal snapshot.
- **QA degrade-to-pass (FEAT-270)**: `code_review_passed=True` can mean
  "not reviewed" — do not let gate logic reinterpret it; gates only touch
  the manual-criteria path.
- **Concurrent SDD sessions on dev**: stage explicit paths only; verify
  `git diff --cached` immediately before each commit.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `pydantic` | `>=2` | frozen models, discriminated unions (already core dep) |
| `hypothesis` | dev-dep | reducer totality/determinism property tests (already used in repo) |
| `redis.asyncio` | in-tree | actions-stream XADD (already used by publisher/dispatchers) |
| `aiohttp` | in-tree | REST command endpoints + WS (already used) |

No new runtime dependencies.

---

## 8. Open Questions

### Resolved (carried from brainstorm — do not re-open)

- [x] Gate TTL defaults per kind + expiry semantics — *Resolved in
  brainstorm*: fail-closed vs fail-open per kind via
  `ApprovalGate.on_expiry: Literal["fail","approve"] = "fail"`; defaults
  (conf-overridable `DEV_LOOP_GATE_TTL_*`, per-gate `open_gate(ttl_seconds)`):
  deployment_approval 24h fail-closed, blocking manual_criterion 72h
  fail-closed, revision_approval 24h fail-closed, plan_approval 4h
  fail-open (`system:ttl-auto-approve`, audited in-state). Silence ≠ consent
  for irreversible effects.
- [x] Deployment-approval rejection routing — *Resolved in brainstorm*:
  rejection routes to `failure_handler` (escalation to
  `escalation_assignee`); a human reject is a failed run. Rework keeps its
  existing channel (PR comments → revision loop via
  `register_pull_request_webhook`).
- [x] Envelope retention for `flow:{run_id}:actions` — *Resolved in
  brainstorm*: snapshot-at-terminal + trim. XADD `MAXLEN ~ 100000` during
  the run; terminal `Snapshot` persisted as run artifact (carries gate
  audit); stream deleted by the finished-run sweep after
  `DEV_LOOP_ACTIONS_RETENTION_DAYS = 7`.
- [x] Svelte reducer port strategy — *Resolved in brainstorm*: types
  generated (`model_json_schema()` → `json-schema-to-typescript`; tagged
  unions give tsc-exhaustiveness drift gate); reducer logic hand-written,
  verified by hypothesis-generated golden fixtures
  `(action_log, expected_snapshot)` deep-equal in nav-admin CI.
- [x] Channel URI naming — *Resolved in brainstorm*: neutral scheme
  (`parrot-root://`, `parrot-session:/`, `parrot-terminal:/`,
  `parrot-changeset:/`); `parrot-*` → `ahp-*` (or A2A task-id) mapping owned
  exclusively by the future wire adapter.

### Resolved (proposal-phase Q&A, 2026-07-21)

- [x] Blocking manual criteria granularity — *Resolved*: per-criterion field
  `blocking: bool = False` on `ManualCriterion` (models.py:70); default
  preserves current behavior.
- [x] Root channel scope — *Resolved*: in scope now — `RunRegistryState` +
  `RunAdded`/`RunSummaryChanged`/`RunRemoved` owned by the runner.
- [x] Command transport — *Resolved*: WS for subscribe/snapshot/stream
  (`view="state"`), REST for commands
  (`POST /runs/{run_id}/gates/{gate_id}/resolve`, `POST /runs/{run_id}/cancel`).

### Unresolved

- [ ] Should a run in `awaiting_gate` release its `FLOW_MAX_CONCURRENT_RUNS`
  semaphore slot? — *Owner: Jesus*. v1 answer assumed by this spec: **no**
  (keep semaphore semantics, rely on TTLs + `pending_gate_count`
  visibility). Releasing the slot requires checkpoint/resume of `run_flow`
  — a separate feature if ever needed. Decide before layering long-TTL
  blocking manual criteria onto high-throughput deployments.

---

## Worktree Strategy

- **Isolation unit**: per-spec — one worktree
  (`feat-322-agent-host-protocol-session-state`), tasks sequential by
  default.
- **Parallelizable inside the feature** (brainstorm T1-T4, if a second
  worker is ever attached): after M1+M2 (core) and M3+M4 (host + shims)
  land, M5 (gates) and M6+M7 (streaming + REST) are mutually independent.
- **Cross-feature dependencies**: none must merge first. CAUTION: qa.py /
  dispatcher.py / factories.py are active (FEAT-270 follow-ups, new
  dispatchers) — check for in-flight branches touching them before creating
  the worktree; rebase promptly after any dev merge.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-21 | Jesus Lara (with Claude) | Initial draft from FEAT-322 proposal + dev-loop-session-state-hitl brainstorm (Option B) |
