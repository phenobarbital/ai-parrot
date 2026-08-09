---
type: feature
base_branch: dev
---

# Brainstorm: HITL escalation for SaaS agentic flows

**Date**: 2026-08-09
**Author**: Jesus Lara (investigation by Claude)
**Status**: exploration
**Recommended Option**: Option C
**Related**: `saas-whatsapp-community-manager.brainstorm.md`

---

## Problem Statement

Two places in the SaaS plane need a human in the loop:

1. A drafted public reply to a bad review should be approvable before it goes
   out, at least while a tenant is building trust in the system.
2. A WhatsApp guest who asks for a person must reach one.

The Community Manager phase shipped a **deliberately minimal** stand-in: the
guardrail can block a reply, and blocked replies are recorded rather than
published. That is not escalation — nobody is notified, and there is no way to
approve and resume.

The repository already contains a substantial HITL framework (~4,000 lines).
The work is mostly *connecting* it, and the connection is not trivial: the
framework and the flow engine have two independent, unintegrated notions of
"suspend".

## What already exists (verified)

### Core — `packages/ai-parrot/src/parrot/human/`

`models.py` (~551 lines):
- `WaitStrategy`: `BLOCK` (long-poll), `SUSPEND` (persist to Redis, raise an
  interrupt, resume later), `HOT_THEN_SUSPEND` (reserved, currently treated as
  BLOCK).
- `InteractionType`: `free_text`, `approval`, `single_choice`, `multi_choice`,
  `form`, `poll`.
- `Severity` with full ordering operators; `BusinessHours` with tz/day/hour
  validators and `contains(now)`; `EscalationTier`, `EscalationPolicy` with
  `select_starting_tier(...)`; `ConsensusMode`; `TimeoutAction`.
- `HumanInteraction`, `HumanResponse`, `InteractionResult`.

`manager.py` (~1542 lines), `HumanInteractionManager`:
- **Blocking**: `request_human_input(interaction, channel="telegram")` creates
  the `asyncio.Future` *before* dispatch (so synchronous channels can resolve
  inline), schedules `_handle_timeout`, dispatches, then awaits.
  `receive_response()` resolves it in-process.
- **Non-blocking**: `request_human_input_async(...)` returns the interaction id
  immediately and writes `hitl:callback:{id}` to Redis with TTL = the
  interaction timeout. Resume via polling `get_result()` (`hitl:result:{id}`)
  or the `hitl:completed` pub/sub channel.
- Tiered escalation: `advance_chain()`, `_escalate_to_next_tier()`,
  `_evaluate_consensus()`, `_tally()`, `_notify_originator()`, `_retry()`.
- Redis namespace: `hitl:interaction:*`, `hitl:responses:*`, `hitl:result:*`,
  `hitl:callback:*`, plus the `hitl:completed` channel.

`tool.py` — `HumanTool(AbstractTool)`; the SUSPEND branch raises
`HumanInteractionInterrupt`, which is caught by `clients/claude.py` (re-raised
rather than swallowed as a tool error) and by `parrot/auth/confirmation.py`.

`node.py` — `HumanDecisionNode`, a pseudo-agent satisfying the flow node
duck-type. Each `ask()` mints a fresh interaction id so retries never collide.
Returns `consolidated_value` on success but the **full `InteractionResult`** on
timeout/cancel, so downstream predicates can branch on status.

`escalation_intent.py` — `RejectIntentDetector.is_escalation_intent(text)` with
an LLM fallback. This is the ready-made "guest asked for a human" detector.

`actions/` — `TicketAction` (backends: `zammad.py`, `webhook.py`, `email.py`)
and `NotifyAction` (async-notify: email/ses/telegram/teams/sms/slack).

### Channels — `human/channels/`

`HumanChannel(ABC)`: `start/stop`, `send_interaction` (abstract),
`send_notification`, `cancel_interaction`, `register_response_handler`,
`register_cancel_handler`, plus `escalate_option()` — the standard "talk to a
human" button injected into rendered interactions.

Implementations: `CLIHumanChannel`, `CLIDaemonHumanChannel`, `WebHumanChannel`
(over `UserSocketManager`), `TelegramHumanChannel` (aiogram inline keyboards,
single-use callback tokens bound to (human, interaction), private chat only),
`TeamsHumanChannel` (Adaptive Cards, isolated so it never imports aiogram).

**There is no WhatsApp channel.**

### Web surface

`packages/ai-parrot-server/src/parrot/handlers/web_hitl.py` —
`POST /api/v1/agents/hitl/respond`, `@is_authenticated()`. Resolves the manager,
404s when neither pending nor resolved, **403 unless
`is_valid_respondent(interaction_id, respondent)`**, treats the escalate option
as `advance_chain(cause="reject")`. `human/suspended_store.py` provides
`SuspendedExecutionStore` (`save`/`load`/`delete`), the concrete resume store
for SUSPEND.

### The integration gap — the crux of this feature

**Flow checkpointing and HITL suspend/resume are separate mechanisms that do
not talk to each other.**

- `AgentsFlow` has `checkpoint=True`, `suspend()` and
  `resume(flow_id, ..., agent_registry=...)`, backed by Redis and a durable
  store, with leases (`FlowLockedError`).
- `HumanDecisionNode.ask()` uses the **blocking** `request_human_input`. A flow
  waiting on a human therefore holds a live coroutine and an in-process
  `asyncio.Future`. It does not checkpoint and exit; a deploy or a crash loses
  the wait.
- The non-blocking path (`request_human_input_async` + `hitl:completed` +
  `SuspendedExecutionStore`) exists only for the **agent/HTTP** surface
  (`SuspendingWebHumanTool`), never for a flow node.
- Worse for us: **`AgentsFlow.resume()` takes no `node_factories`**. It rebuilds
  through `from_definition(checkpoint.definition, agent_registry=...)`, so a
  custom node type falls back to the generic `cls(node_id=..., dependencies=...,
  successors=...)` constructor and any node holding live dependencies cannot be
  reconstructed. `dev_loop`/`dev_flow` never hit this because they do not
  checkpoint. **Any flow-level HITL suspend for the SaaS flows is blocked on
  fixing this first** — a three-line, backwards-compatible change (add
  `node_factories` and forward it).

### The pattern that does compose today

`parrot/flows/dev_loop/session_state.py` — approval gates:
`open_gate(kind, node_id, title, ttl_seconds, on_expiry=...)`,
`await wait_gate(gate_id)` on an internal `asyncio.Event`, `expire_due_gates()`.
A node reaches into `ctx.shared_data["session_host"]`, opens a gate, awaits it,
and raises on non-approval so the flow's `on_error` edge routes. The human
resolves through an HTTP command that folds a `GateResolved` action into
event-sourced session state. Worked example:
`flows/dev_loop/nodes/development.py:226 _check_plan_approval`.

Note also `InteractiveDecisionNode` (`bots/flows/flow/nodes.py`) is **not** this:
it is a blocking terminal `questionary.select` in a thread executor, unconnected
to `HumanInteractionManager` and not resumable. Two different classes share that
name depending on import path; do not confuse them.

---

## Constraints & Requirements

- A tenant's reviewer must only see and answer their own tenant's interactions —
  `is_valid_respondent` is per-respondent, not per-tenant, today.
- A pending approval must survive a deploy. That is what rules out the blocking
  path for anything with a human-scale timeout.
- Escalation must not require the reviewer to be online: notification-first,
  with a tiered fallback, is the point of `EscalationPolicy`.
- WhatsApp handoff needs a `HumanChannel` implementation that does not exist.

---

## Options Explored

### Option A: Keep the parked-approval stand-in, add notifications

Notify via `NotifyAction`; approve through the existing SaaS endpoints.

✅ **Pros:** ships immediately; no engine change; already tenant-scoped.

❌ **Cons:** no tiers, no business hours, no timeout policy, no consensus —
reimplements a worse version of what already exists.

📊 **Effort:** Low.

### Option B: Blocking `HumanDecisionNode` in the flow

Drop the existing node into the graph.

✅ **Pros:** smallest use of the framework; works today.

❌ **Cons:** the flow holds a live coroutine for the whole wait; a deploy loses
it; a per-tenant concurrency semaphore would be consumed by humans thinking.
Unsuitable for hour-scale approvals.

📊 **Effort:** Low.

### Option C: Suspend-and-resume HITL node, after fixing `resume()` — RECOMMENDED

1. Add `node_factories` to `AgentsFlow.resume()` (small, backwards compatible,
   independently valuable — it unblocks every custom-node flow in the repo).
2. Build a `HitlGateNode` for `parrot_saas` that calls
   `request_human_input_async`, records the interaction on the checkpoint, and
   ends the run in a suspended state.
3. A `hitl:completed` subscriber resumes the flow by `flow_id`.
4. Add `WhatsAppHumanChannel` implementing `HumanChannel` with interactive
   list/button replies.
5. Scope respondents by tenant.

✅ **Pros:** uses the framework as designed; survives deploys; tiers, business
hours and timeouts come for free; the WhatsApp channel then serves both the
handoff and approvals.

❌ **Cons:** the largest option, and it touches core (`resume`).

📊 **Effort:** High.

🔗 **Existing Code to Reuse:** effectively all of `parrot/human/`; the gate
pattern in `dev_loop/session_state.py` as the model for the node/host split;
`RejectIntentDetector` for intent; `web_hitl.py` for the respond endpoint shape.

---

## Open Questions

- [ ] Does the `node_factories` change to `AgentsFlow.resume()` land as part of
      this feature or as an independent core fix? It is useful on its own.
- [ ] Tenant scoping of respondents: extend `is_valid_respondent`, or wrap the
      manager per tenant?
- [ ] Which channel do hospitality tenants actually want approvals on —
      WhatsApp, email, or the SaaS web UI? This decides build order.
- [ ] Default `TimeoutAction` for an unanswered reply approval: publish anyway,
      or drop? Business-sensitive, and the answer probably differs by sentiment.

## Recommendation

Option C, staged: land the `resume(node_factories=...)` fix first, then the
suspending node, then the WhatsApp channel. Option A is an acceptable interim
for a first design partner, but it should be understood as a stopgap and not
allowed to grow tiers of its own.
