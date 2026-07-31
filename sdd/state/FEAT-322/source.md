---
kind: file
jira_key: null
fetched_at: 2026-07-21T00:00:00Z
summary_oneline: AHP-style multi-agent orchestration protocol (session state + HITL gates) over dev-loop, from approved brainstorm + design sketch
---

# Source: agent-host-protocol-session-state

## Primary source (file)

`sdd/proposals/dev-loop-session-state-hitl.brainstorm.md` — approved brainstorm
"AHP-style Session State Model & HITL Approval Gates for dev-loop"
(Recommended Option: **B** — protocol-agnostic state core, AHP-shaped,
adapter-isolated). All open questions except one (blocking manual criteria
opt-in granularity) are resolved in the brainstorm.

Key decisions already made in the brainstorm:
- Neutral channel URI scheme (`parrot-session:/`, `parrot-terminal:/`,
  `parrot-changeset:/`, `parrot-root://`); `parrot-*` → `ahp-*` mapping owned
  by a future wire adapter.
- Gate expiry policy: fail-closed vs fail-open per kind
  (`ApprovalGate.on_expiry: Literal["fail","approve"]`), conf-overridable TTLs.
- Deployment-approval rejection routes to `failure_handler` (escalation), not
  the revision graph.
- Envelope retention: snapshot-at-terminal + XTRIM cap + 7-day sweep.
- Svelte port: TS types generated from Pydantic JSON Schema; reducer logic
  hand-written with golden-fixture parity CI.

## Secondary source (design sketch)

`sdd/artifacts/devloop_session_state.py` — complete user-provided design
sketch: frozen Pydantic state tree (`DevLoopSessionState`, `NodeState`,
`DispatchState`, `ApprovalGate`), closed discriminated action union
(20 actions), pure total `reduce()`, `SessionHost` (sequencing, snapshot,
replay, gate arbitration, expiry sweep), and migration shims
(`action_from_flow_event`, `action_from_dispatch_event`).

## User directive (inline, this invocation)

> "define a orchestration multi-agent using a simil of Agent Host Protocol
> definition to build over dev loop"

Referenced external specs:
- https://microsoft.github.io/agent-host-protocol/specification/overview.html
- https://microsoft.github.io/agent-host-protocol/reference/common.html

Interpretation: this proposal must go beyond the brainstorm's per-run session
state — it should define the **host/orchestration layer** in AHP terms: the
dev-loop runner as an AHP-style *host* that manages multiple agent *sessions*
(runs), a root channel enumerating sessions, per-session channels
(state/terminal/changeset), typed client commands (subscribe, dispatchAction,
resolve gate, cancel), and how the multi-agent dispatchers (research,
development, qa, code-review subagents) surface through that model.
