---
id: FEAT-322
title: AHP-style multi-agent orchestration for dev-loop — session state, host, HITL gates
slug: agent-host-protocol-session-state
type: feature
mode: enrichment
status: review
source:
  kind: file
  jira_key: null
  jira_url: null
  fetched_at: 2026-07-21
  summary_oneline: AHP-simil orchestration over dev-loop from approved brainstorm (Option B) + devloop_session_state.py design sketch
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-322/
created: 2026-07-21
updated: 2026-07-21
---

# FEAT-322 — AHP-style Multi-Agent Orchestration for dev-loop: Session State, Host & HITL Gates

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `file: sdd/proposals/dev-loop-session-state-hitl.brainstorm.md` + `sdd/artifacts/devloop_session_state.py`
> **Audit**: [`sdd/state/FEAT-322/`](../state/FEAT-322/)

---

## 0. Origin

Full source at `sdd/state/FEAT-322/source.md`.

> "using the brainstorm proposal at `sdd/proposals/dev-loop-session-state-hitl.brainstorm.md`
> and sample code in `sdd/artifacts/devloop_session_state.py` to define a
> orchestration multi-agent using a simil of Agent Host Protocol definition
> [(overview)](https://microsoft.github.io/agent-host-protocol/specification/overview.html)
> [(common)](https://microsoft.github.io/agent-host-protocol/reference/common.html)
> to build over dev loop"

**Initial signals** (extracted, not interpreted):
- Verbs: "define", "build over" → new architecture layer, not a bug fix
- Named entities: Agent Host Protocol (AHP), dev-loop, session state, brainstorm Option B
- Prior art: approved brainstorm (Recommended Option B, 5 of 6 open questions already resolved) + a contract-complete design sketch
- Acceptance criteria provided: no (design-level source)

---

## 1. Synthesis Summary

Turn the dev-loop's ad-hoc event log into an AHP-shaped orchestration model:
`DevLoopRunner` (runner.py:100) becomes the **host** owning one `SessionHost`
per run plus a root-channel run catalogue; each run is a **session** with an
authoritative frozen state tree, a closed action union, and pure reducers
(the new `session_state.py`, from the user's sketch); each of the 7+
dispatcher executions (dispatcher.py) is a **terminal-channel** occupant; and
the PR diff is the **changeset**. Blocking HITL gates (`manual_criterion` in
qa.py:301, `deployment_approval` in deployment_handoff.py:89) become
first-class state with first-writer-wins arbitration, TTL policies, and full
audit. `FlowEventPublisher` (flow.py:71) and the dispatchers dual-publish via
1:1 shims; `FlowStreamMultiplexer` (streaming.py:51) gains a `view="state"`
snapshot+actions mode, and commands arrive via WS-subscribe + REST-resolve.
AHP is confirmed DRAFT, so wire compatibility stays quarantined behind a
future adapter — this feature ships only the invariant core AHP itself is
built on.

---

## 2. Codebase Findings

> Grounded in `sdd/state/FEAT-322/findings/`. All brainstorm anchors
> re-verified at current HEAD (branch `dev`, post-FEAT-270) with **zero
> drift** [F002]. Paths relative to `packages/ai-parrot/src/`.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `parrot/flows/dev_loop/session_state.py` | *(new)* | — | protocol-agnostic core: state/actions/reducers/`SessionHost`/shims | F001, F002 |
| 2 | `parrot/flows/dev_loop/runner.py` | `DevLoopRunner` | :100 | AHP host: `Dict[run_id, SessionHost]` registry, root catalogue, expiry sweep, command methods | F002, F003 |
| 3 | `parrot/flows/dev_loop/flow.py` | `FlowEventPublisher.__call__` | :94 | dual-publish shim point (per-event run_id resolution) | F002, F004 |
| 4 | `parrot/flows/dev_loop/nodes/qa.py` | `_merge_manual_results` / `execute` | :301 / :108 | blocking `manual_criterion` gates replace `passed=True` synthesis | F002, F005 |
| 5 | `parrot/flows/dev_loop/nodes/deployment_handoff.py` | `execute` | :89 | `deployment_approval` gate between PR creation and Jira transition | F002, F006 |
| 6 | `parrot/flows/dev_loop/streaming.py` | `FlowStreamMultiplexer` | :51 | adapter target: `view="state"` snapshot + actions envelopes | F002, F008 |
| 7 | `parrot/flows/dev_loop/dispatcher.py` | `DevLoopCodeDispatcher` + 7 impls | — | terminal-channel producers; XADD site is the second shim point | F007 |
| 8 | `parrot/flows/dev_loop/webhook.py` | `register_pull_request_webhook` | :292 | nearest precedent for an external command surface (REST commands land beside it) | F008 |
| 9 | `parrot/flows/dev_loop/models.py` | `ManualCriterion` / `WorkBrief` / `QAReport` / `DispatchEvent` | :70 / :118 / :349 / :698 | projections read these; `ManualCriterion` gains `blocking: bool = False` (U1) | F002, F005 |

### 2.2 Constraints Discovered

- **Shared flow, per-run identity.** One `AgentsFlow` instance serves
  concurrent runs; `FlowEventPublisher` resolves `run_id` **per event** from
  `info["context"].shared_data` (holder dict is fallback only). The per-run
  `SessionHost` therefore MUST be resolved by run_id through a registry on
  the runner — never captured as a single reference on the flow/publisher.
  *This corrects the brainstorm's holder-centric shim description.*
  *Evidence*: F003, F004

- **CEL predicates route on node results.** Edges evaluate
  `result.passed` (`definition.py`), so QA gate resolutions must be folded
  into the returned `QAReport` before `QANode.execute` returns — the node
  awaits its gates; routing stays declarative and untouched.
  *Evidence*: F005, F008

- **FEAT-270 review loop precedes gates.** `QANode` now runs a
  code-review dispatcher that may fix-and-commit, triggering a deterministic
  re-run, with degrade-to-pass on infra errors. Gate integration lands
  after this loop and must not disturb its semantics.
  *Evidence*: F005

- **Never break a run.** The publisher swallows every Redis failure
  (`flow.py:119`); `host.apply()` must fold in-memory even when the envelope
  XADD fails, mirroring that guarantee. `FLOW_MAX_CONCURRENT_RUNS` semantics
  unchanged (runner.py:124).
  *Evidence*: F003, F004

- **AHP is DRAFT — mirror the invariant subset only.** Confirmed verbatim:
  "Breaking changes to wire types, actions, and state shapes are expected."
  The stable-by-construction subset to mirror: channel-scoped
  `ActionEnvelope {channel, serverSeq, origin, rejectionReason}`,
  `Snapshot {resource, state, fromSeq}`, reconnect replay-vs-snapshot,
  root catalogue events (`root/sessionAdded…`), `SessionInputNeededSet`
  (≅ `awaiting_gate`) and `toolCallReady → toolCallConfirmed` (≅ gate
  arbitration). JSON Schema 2020-12 is published per type group — usable
  later as a codegen drift gate for the Svelte port.
  *Evidence*: F001

- **Dispatcher heterogeneity is invisible to state.** Claude/Codex/Gemini/
  Grok/Z.ai/Moonshot + review dispatchers all emit `DispatchEvent` to
  `flow:{run_id}:dispatch:{node_id}`; the state model needs only
  `DispatchState.dispatcher: str` + counters (AHP lazy-loading rule: heavy
  content stays by-reference on the terminal channel).
  *Evidence*: F007

### 2.3 Recent History (Relevant)

Last ~6 weeks on `parrot/flows/dev_loop/` (newest first, abridged) [F008]:

| Commit | Message | Risk to this feature |
|--------|---------|----------------------|
| `5982096fb` | MoonshotCodeDispatcher + profile | dispatcher.py churn |
| `28a0bbfc2` | fix 10 bugs in FEAT-270 multi-dispatcher gate | qa.py churn |
| `6940c8748` | FEAT-270 new-codereviewers merged | qa.py, factories.py |
| `36c2d306d` | ZaiCodeDispatcher + Grok factory fix | dispatcher.py |
| `1c83406ec` | workflow-agnostic Jira transitions | deployment_handoff.py path |

The files this feature touches are **active** — re-verify anchors at
`/sdd-task` time; keep worktrees short-lived.

---

## 3. Probable Scope  *(mode = enrichment)*

### What's New

- **`parrot/flows/dev_loop/session_state.py`** — the sketch, landed as-is in
  structure, hardened with AHP alignment [F001]:
  - `ActionEnvelope` gains `origin: Optional[ActionOrigin]`
    (`client_id`, `client_seq`) and `rejection_reason: str = ""` — the
    multi-client write-attribution AHP carries on every envelope.
  - **Root channel (U2: in scope)**: `RunRegistryState` frozen tree
    (run_id → `RunSummary {phase, work_kind, summary, jira_issue_key,
    pr_url, pending_gate_count}`) + root actions `RunAdded` / `RunRemoved` /
    `RunSummaryChanged` + `reduce_root()` — mirrors `root/sessionAdded|
    Removed|SummaryChanged` on `parrot-root://`.
  - Everything else per sketch: `DevLoopSessionState`, `NodeState`,
    `DispatchState`, `ApprovalGate` (with `on_expiry`), 20-action
    `DevLoopAction` union, pure total `reduce()`, `SessionHost`
    (apply / snapshot / replay_since / resolve_gate / open_gate /
    expire_due_gates), shims `action_from_flow_event` /
    `action_from_dispatch_event`, neutral `parrot-*` channel URIs.
- **`dev-loop-approval-gates` capability** — blocking HITL gates with
  first-writer-wins arbitration (validate-before-sequence,
  `GateAlreadyResolvedError`), per-kind fail-closed/fail-open TTL policy
  (brainstorm-resolved defaults: deployment 24h fail, blocking manual 72h
  fail, revision 24h fail, plan 4h approve), full in-state audit.
- **Command surface (U3: WS + REST)** — WS on the multiplexer for
  subscribe/snapshot/stream; REST on the aiohttp app for commands:
  `POST /runs/{run_id}/gates/{gate_id}/resolve` (`{resolution, resolved_by,
  comment}` → 200 envelope | 404 | 409 already-resolved) and
  `POST /runs/{run_id}/cancel`. Runner exposes `resolve_gate(run_id, …)` /
  `cancel_run(run_id, requested_by)`; the HTTP layer is a thin adapter.

### What Changes

- **`runner.py`::`DevLoopRunner`** — owns `self._hosts: Dict[str, SessionHost]`
  + `RunRegistryState`; `run()`/`run_revision()` create the host, apply
  `RunCreated`/`RunAdded`, start/stop a per-run expiry-sweep task, apply
  `RunClosed`/`RunRemoved` + terminal-snapshot persistence on completion.
  `active_runs`/`is_active` preserved. *Evidence*: F003
- **`flow.py`::`FlowEventPublisher.__call__`** — dual-publish: after the
  legacy XADD, resolve host by the same per-event run_id and
  `host.apply(action_from_flow_event(...))`; envelope XADD to
  `flow:{run_id}:actions` (MAXLEN ~100k), failures swallowed. *Evidence*: F004
- **`dispatcher.py` XADD path** — same dual-publish via
  `action_from_dispatch_event` (all dispatcher kinds, one shim). *Evidence*: F007
- **`models.py`::`ManualCriterion`** — add `blocking: bool = False` (U1).
  *Evidence*: F005
- **`nodes/qa.py`** — for `blocking=True` criteria: open one
  `manual_criterion` gate each (after the FEAT-270 review loop), await
  resolutions, fold approved→passed / rejected|expired→failed into
  `criterion_results` before returning; non-blocking criteria keep the
  `_merge_manual_results` synthesis. *Evidence*: F005
- **`nodes/deployment_handoff.py`::`execute`** — open `deployment_approval`
  gate after PR creation (payload_ref = changeset URI / pr_url), await; on
  approve → continue to Jira transition; on reject/expire → return
  blocked-style status routed to `failure_handler` (escalation to
  `WorkBrief.escalation_assignee`, models.py:161). *Evidence*: F006
- **`streaming.py`::`FlowStreamMultiplexer`** — `view="state"`: on connect
  send `Snapshot`, then relay `flow:{run_id}:actions` envelopes
  (`server_seq > last_seen` replay). Legacy views untouched (dual-publish
  window). *Evidence*: F008

### What's Untouched (Non-Goals)

- **No AHP wire compatibility**: no JSON-RPC framing, no `initialize`/
  capability negotiation, no RFC 9728/6750 auth, no `ahp-*` URIs — deferred
  to a follow-up wire-adapter spec (AHP is DRAFT [F001]).
- No changes to flow topology, CEL predicates, or the FEAT-270 review loop.
- Legacy streams/envelopes keep flowing (nav-admin unaffected until ported);
  `DevLoopRunner(flow)` legacy construction preserved.
- nav-admin Svelte reducer port + golden-fixture parity CI: separate repo,
  follow-up (types via `model_json_schema()` → TS, per brainstorm).
- No Ed25519/RFC 3161 snapshot signing (brainstorm: optional future hardening).

### Patterns to Follow

- Per-event run_id resolution exactly as `FlowEventPublisher.__call__`
  (flow.py:94-101). *Evidence*: F004
- Swallow-all telemetry guard (flow.py:119) for every shim/XADD. *Evidence*: F004
- Frozen Pydantic v2 + closed discriminated unions (house style; sketch
  already complies). *Evidence*: F001, F002
- Definition→factories→materialize flow-building and `on_error` fan-in for
  gate-rejection routing (definition.py). *Evidence*: F008
- `hypothesis` property tests: `fold(replay_since(0)) == state`, reducer
  totality/no-raise, terminal-phase stickiness (dev-dep already in repo).

### Integration Risks

- **Active files** (qa.py, dispatcher.py churn from FEAT-270/Moonshot):
  re-verify anchors at task time; prefer small, rebased worktrees.
  *Evidence*: F008
- **Blocking gates vs run cap**: a run `awaiting_gate` holds its
  `FLOW_MAX_CONCURRENT_RUNS` semaphore slot — long-TTL gates can starve
  throughput. Mitigation: conf-overridable TTLs (brainstorm) + surface
  `pending_gate_count` in the root catalogue for operator visibility;
  slot-release redesign explicitly out of scope. *Evidence*: F003
- **Dual-publish duplication** in Redis during migration — accepted
  (brainstorm), bounded by MAXLEN caps + 7-day sweep.
- **Gate opened, node hard-errors**: failure handler resolves orphaned
  gates as `expired` (brainstorm edge case); the expiry sweep is the
  backstop. *Evidence*: F006

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | All brainstorm anchors valid at HEAD, zero drift | F002 | high | direct grep verification of every symbol/line |
| C2 | AHP structural mapping: host=runner, session=run, terminal=dispatch stream, changeset=PR, root=run catalogue | F001, F003, F007 | high | spec pages fetched + runner/dispatcher surfaces read |
| C3 | Per-run host must be registry-resolved (shared flow, per-event run_id) | F003, F004 | high | direct read of runner.py + flow.py current behavior |
| C4 | QA gate insertion after FEAT-270 review loop; outcomes fold into QAReport pre-return | F005, F008 | high | direct read of qa.py execute + CEL predicates |
| C5 | Deployment gate slots between PR creation and Jira transition | F006 | high | direct read of execute() step sequence |
| C6 | AHP envelope extras (origin, rejectionReason) adoptable without breaking the sketch | F001 | medium | additive optional fields; not yet property-tested |
| C7 | No client-command surface exists; webhook is nearest precedent | F008 | medium | webhook.py read; aiohttp app wiring not exhaustively swept |
| C8 | Blocking gates hold run-cap slots (throughput risk) | F003 | medium | semaphore held across run_flow; inferred, not load-tested |

Distribution: **5** high, **3** medium, **0** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **U1 — Blocking manual criteria granularity?** — *Resolved*:
  per-criterion field `blocking: bool = False` on `ManualCriterion`
  (models.py:70); default preserves current behavior. *Resolves*: C4
- [x] **U2 — Root channel in scope?** — *Resolved*: include now —
  `RunRegistryState` + `RunAdded`/`RunRemoved`/`RunSummaryChanged` owned by
  the runner; nav-admin run list gets snapshot semantics. *Resolves*: C2
- [x] **U3 — Command transport?** — *Resolved*: WS + REST — WS multiplexer
  socket for subscribe/snapshot/stream; REST
  `POST /runs/{run_id}/gates/{gate_id}/resolve` (and `/cancel`) for
  commands. *Resolves*: C7
- [x] Gate TTL/expiry policy, rejection routing, envelope retention,
  Svelte codegen strategy, URI scheme — all pre-resolved in the source
  brainstorm (see §Open Questions there).

### Unresolved (defer to spec / implementation)

- [ ] **Should a run `awaiting_gate` release its concurrency slot?** —
  *Owner*: Jesus. *Blocks claims*: C8.
  *Plausible answers*: a) no — keep semaphore semantics, rely on TTLs (v1,
  recommended) · b) yes — checkpoint/resume redesign (large, separate feature).

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-322`** — *Rationale*: high-confidence localization (C1-C5),
a contract-complete design sketch, and all material decisions resolved. Per
the brainstorm's parallelism assessment, spec as **two layered specs**:
`dev-loop-session-state` (core module + root channel + host registry + shims
+ `view="state"`) first, then `dev-loop-approval-gates` (QA/deployment gate
integration + command surface) on its frozen contracts.

### Alternatives

- **`/sdd-brainstorm FEAT-322`** — not needed; the source brainstorm already
  explored Options A/B/C and picked B.
- **`/sdd-task FEAT-322`** — too large for direct task decomposition without
  a spec; multiple modules and two capabilities.
- **Manual review** — n/a; research complete, not truncated.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-322/state.json` |
| Source (raw) | `sdd/state/FEAT-322/source.md` |
| Research plan | `sdd/state/FEAT-322/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-322/findings/F001-*.md` … `F008-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-322/synthesis.json` |

**Budget consumed** (profile: default):
- Files read: 9 / 40 · Grep calls: 4 / 25 · Git calls: 1 / 10
- Wiki queries: 5 (free) · Web fetches: 2 (user-directed AHP spec pages)
- Truncated: **no**

**Mode determination**: `auto` → resolved to `enrichment` (source is an
approved brainstorm + design sketch, not a defect report).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Jesus Lara (with Claude) |
