<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
The Navigator telemetry epic (NVP-502) needs AI cost, tokens and error rate per **tenant**, user and agent,
written to a BigQuery sink (`TelemetryEvent` + `BigQueryBatchSubscriber`, NVP-505, which lands in
`navigator-eventbus`). The closed PR #1747 proposed doing this with a `TelemetryBridge` *inside* ai-parrot.
That design would have added a fourth in-process subscriber to every LLM call, recomputed cost a fourth time,
run BigQuery I/O in the agent process, collided with the existing `parrot.observability.setup_telemetry`,
and introduced a TROC-specific `program_slug` concept into the framework.

ai-parrot already has everything needed for an out-of-process design:
- `navigator-eventbus` is a core dependency (`packages/ai-parrot/pyproject.toml:187`), and the lifecycle
  `EventRegistry` used by every bot *is* `navigator_eventbus.lifecycle.registry.EventRegistry`.
- The registry has per-subscription dual-emit (`forward_to_bus=True`) to an `EventBus` channel
  `"{prefix}.{EventClassName}"`, fire-and-forget (FEAT-176/177, extracted in FEAT-313/317, brokers FEAT-316).
- Tenancy already exists (FEAT-707): handlers resolve the tenant server-side via `resolve_request_tenant`
  and pass `ask(tenant=...)`.

What is missing:
- Nothing forwards the four usage events to a bus: the global registry has no `EventBus`, and no
  subscription with `forward_to_bus=True` exists for them.
- The events carry `user_id`/`session_id` but no `tenant` and no `cost_usd`. A ContextVar cannot cross the
  bus, and an external consumer has no pricing tables.
- The tenant ContextVar is skills-specific (`_skill_tenant`, `skills/tenancy.py:77`) and is bound only for
  `tenant_based` bots.
- AgentTalk (`handlers/agent.py`) neither resolves nor passes the tenant. Its two `save_turn` calls omit
  `metadata`, so per-turn usage is lost.

### Constraints and goals
- G1. Forward `AfterInvokeEvent`, `InvokeFailedEvent`, `AfterClientCallEvent` and `ClientCallFailedEvent` to an
  `EventBus`, behind a config flag (default off), so any consumer, in-process or not, can subscribe.
- G2. Make the four events self-describing: add `tenant: Optional[str]` to all four, and `cost_usd: Optional[float]`
  to `AfterClientCallEvent`. Cost is computed **once**, at the origin, with the process-shared `CostCalculator`.
- G3. Use one generic `current_tenant` ContextVar, bound on every `ask()`/`ask_stream()`, that
  `skills/tenancy.py` reuses. There is no `program`/`program_slug` concept anywhere in ai-parrot.
- G5. **Cost is computed exactly once per LLM call.** Today each subscriber computes it independently
  from the same `AfterClientCallEvent`: `UsageRecordingSubscriber` (`recorders/subscriber.py:103-104`),
  `MetricsSubscriber` (`subscribers/metrics.py:243-244`) and the trace subscriber (`subscribers/trace.py:276-277`).
  After this feature, the origin computes it (`clients/base.py`) and all three subscribers read `event.cost_usd`.
- G4. AgentTalk resolves the tenant with the existing `resolve_request_tenant` (same as `chat.py:454-458`),
  passes it to `ask`/`ask_stream`, and persists `metadata={usage, cost_usd, tenant, agent}` in both `save_turn`
  calls.

### Non-Goals (explicitly out of scope)

- A `TelemetryBridge`, the `TelemetryEvent` model, the BigQuery sink, or `setup_telemetry(app)` inside
  ai-parrot. All of these live in the external consumer (NVP-505, navigator-eventbus or a worker).
- Mapping tenant → TROC program / `client_id`. That is the consumer's job, and ai-parrot never learns "program".
- The question-topic clustering job (FEAT-775 draft Module 4). It can be specced separately against ChatStorage.
- Changing the `UsageRecord` PII contract, the Prometheus label set or the OTel span attributes.
- Forwarding `BeforeInvokeEvent` (carries `question` text), `ClientStreamChunkEvent` or tool events.
- New tenant-resolution logic. `_get_user_session` is not touched, and no request/agent/session precedence
  chain is added.

---

### Recommended option / probable scope
Scope agreed with the maintainer: (1) forward the four usage lifecycle events (AfterInvokeEvent, InvokeFailedEvent, AfterClientCallEvent, ClientCallFailedEvent) from ai-parrot's global lifecycle registry to a navigator-eventbus EventBus, behind a config flag, so an external telemetry consumer (BigQuery sink, outside ai-parrot) can subscribe; (2) add tenant (all four) and cost_usd (AfterClientCallEvent) fields to those events; (3) one generic current_tenant ContextVar reused by skills/tenancy.py; tenant resolved by the existing FEAT-707 server-side resolution; (4) compute CostCalculator cost exactly once per LLM call (today each subscriber computes it); (5) AgentTalk handler passes the server-resolved tenant and persists usage/cost/tenant/agent metadata in ChatStorage.save_turn.

### Verified code anchors (paths only — open them yourself)
packages/ai-parrot/src/parrot/core/events/lifecycle/events/invoke.py
packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py
packages/ai-parrot/src/parrot/clients/base.py
packages/ai-parrot/src/parrot/bots/base.py
packages/ai-parrot/src/parrot/observability/context.py
packages/ai-parrot/src/parrot/observability/bootstrap.py
packages/ai-parrot/src/parrot/observability/setup.py
packages/ai-parrot/src/parrot/observability/cost/calculator.py
packages/ai-parrot/src/parrot/observability/recorders/subscriber.py
packages/ai-parrot/src/parrot/observability/subscribers/metrics.py
packages/ai-parrot/src/parrot/observability/subscribers/trace.py
packages/ai-parrot/src/parrot/skills/tenancy.py
packages/ai-parrot/src/parrot/skills/mixin.py
packages/ai-parrot/src/parrot/storage/chat.py
packages/ai-parrot-server/src/parrot/handlers/agent.py
packages/ai-parrot-server/src/parrot/handlers/chat.py
packages/ai-parrot-server/src/parrot/handlers/scope.py
packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py
.venv/lib/python3.12/site-packages/navigator_eventbus/lifecycle/registry.py
.venv/lib/python3.12/site-packages/navigator_eventbus/lifecycle/global_registry.py
.venv/lib/python3.12/site-packages/navigator_eventbus/lifecycle/base.py

### Questions still open in the exploration document
none

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
