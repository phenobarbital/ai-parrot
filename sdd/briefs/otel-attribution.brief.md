---
kind: brief
slug: otel-attribution
key: otel-attribution
base_branch: dev
source:
  type: text
  ref: 'operator request 2026-11-12 (/sdd-brief): OTel telemetry attribution gap: (1) map the server-resolved tenant (already on AfterInvokeEvent/InvokeFailedEvent/AfterClientCallEvent/ClientCallFailedEvent and the current_tenant ContextVar, FEAT-710) onto OTel span attributes (observability/attributes.py) and LLM metric attributes (observability/subscribers/metrics.py) with an "unknown" sentinel; (2) bind current_tenant in BaseBot.invoke() and BaseBot.conversation() (bots/base.py) using the same _resolve_call_tenant resolver as ask()/ask_stream(); (3) bind current_agent_name + current_tenant in the ask() overrides that bypass BaseBot.ask — PandasAgent.ask (bots/data.py:1361), DatabaseAgent.ask (bots/database/agent.py:411), VoiceBot.ask/ask_stream (bots/voice.py:783/527) — preferably via one shared BaseBot helper used by every entry point; (4) coverage test per agent class (BasicAgent, PandasAgent, DatabaseAgent, VoiceBot) asserting LLM-call metrics carry parrot.agent.name and tenant, using in-memory exporters like tests/integration/observability/test_poc.py. Today those three agents emit parrot.agent.name="unknown" and no tenant. Goal: truthfully claim every LLM call is tagged by service, agent and tenant.'
  url: null
jira_issue_key: null
ledger_issue: null
created: "2026-11-12"
---

# Brief: Tag every agent LLM call's OTel telemetry with agent and tenant

## Problem

The operator wants to state, in an external status document, that AI-Parrot's OpenTelemetry
signals can be classified by **service, agent and tenant**. Source (verbatim, abridged to the
goal sentence): *"Today those three agents emit parrot.agent.name="unknown" and no tenant. Goal:
truthfully claim every LLM call is tagged by service, agent and tenant."*

What a Grafana/Prometheus user sees today on `origin/dev`:

- **Service** — fine: `service.name` / `service.version` / `service.instance.id` are on the OTel
  `Resource` shared by the tracer and meter providers (`observability/setup.py:119-126`).
- **Agent** — `parrot.agent.name` is on spans and LLM metrics, but only for calls made through
  `BaseBot.conversation/invoke/ask/ask_stream`. `PandasAgent`, `DatabaseAgent` and `VoiceBot`
  override `ask()` and call the client directly, so their LLM metrics read
  `parrot.agent.name="unknown"`.
- **Tenant** — on no OTel signal at all. It is captured on four lifecycle events (FEAT-710) and
  forwarded to the EventBus, but neither the span attribute builders nor `MetricsSubscriber` read
  it, and it is only bound in `BaseBot.ask/ask_stream`.
- **Voice streaming** — `GeminiLiveClient.stream_voice()` and `NovaAudio.stream_voice()` emit no
  lifecycle events, so audio sessions (`VoiceBot.ask_stream`) produce no LLM spans or metrics.

## Root cause

OTel attribution is read from lifecycle events whose identity fields are captured from
ContextVars at event construction (`clients/base.py:673-690`, `:832`; dispatch is fire-and-forget
via `emit_nowait`, so subscribers cannot read ContextVars later). Four gaps follow:
(1) the span/metric builders never map `event.tenant` (`observability/attributes.py:248` maps only
`parrot.agent.name`; `observability/subscribers/metrics.py:227` likewise), and the two events the
request/round metrics consume — `BeforeClientCallEvent` (`core/events/lifecycle/events/client.py:28`)
and `ClientRoundEvent` (`:225`) — have no `tenant` field at all;
(2) `current_tenant` is bound only in `BaseBot.ask` / `ask_stream` (`bots/base.py:1153`, `:1929`),
not in `conversation()` (`:240` binds the agent only) or `invoke()` (`:697`);
(3) `PandasAgent.ask` (`bots/data.py:1361` → `client.ask` at `:1659`), `DatabaseAgent.ask`
(`bots/database/agent.py:411` → `self._llm.ask` at `:581`) and `VoiceBot.ask` / `ask_stream`
(`bots/voice.py:783`, `:527`; they bind user/session/memory key at `:805` / `:566` but not agent or
tenant) bypass `BaseBot`'s binding entirely;
(4) `GeminiLiveClient.stream_voice` (`ai-parrot-client-google/.../google/live.py:693`) and
`NovaAudio.stream_voice` (`ai-parrot-client-amazon/.../nova/audio.py:1293`) never call the
`AbstractClient._emit_*` helpers (`clients/base.py:638`, `:775`, `:898`), unlike
`GeminiLiveClient.ask` (`live.py:1324`).

## Research findings

- **Verified anchors** (all checked with `test -e <path> && sed -n '<line>p' <path>` on a tree identical
  to `origin/dev` for these files): `observability/attributes.py:141`, `:248`;
  `observability/subscribers/metrics.py:201`, `:227`, `:258`; `observability/subscribers/trace.py:278`
  (after-event attributes are applied at span end, so `tenant` on after/failed events reaches spans);
  `bots/base.py:240`, `:697`, `:1128`, `:1153`; `bots/data.py:1361`, `:1659`;
  `bots/database/agent.py:411`, `:581`; `bots/voice.py:527`, `:566`, `:659`, `:783`, `:805`, `:865`;
  `clients/base.py:638`, `:673`, `:748`, `:775`, `:832`, `:898`; `core/events/lifecycle/events/client.py:28`,
  `:95`, `:225`; `live.py:693`, `:787`, `:821`, `:1324`; `nova/audio.py:1293`, `:1403`, `:2013`.
- **Event fields today**: `AfterClientCallEvent.tenant` (`client.py:95`), `ClientCallFailedEvent.tenant`
  (`:141`), `AfterInvokeEvent.tenant`, `InvokeFailedEvent.tenant` exist; `BeforeClientCallEvent`,
  `ClientRoundEvent`, `BeforeInvokeEvent` have none. Invoke spans get identity at end
  (`trace.py:257`), so `BeforeInvokeEvent` needs no change.
- **Metric handlers** (`metrics.py:187-194`): request count ← `BeforeClientCallEvent`; duration,
  tokens, cost ← `AfterClientCallEvent`; rounds ← `ClientRoundEvent`; errors ← `ClientCallFailedEvent`;
  invoke duration/failures ← `AfterInvokeEvent`/`InvokeFailedEvent`. Tool metrics carry only
  `parrot.tool.name` (out of scope: not LLM calls).
- **Blast radius**: `_resolve_call_tenant` is called only by `BaseBot.ask` / `ask_stream` and tested
  by `tests/unit/bots/test_current_tenant_binding.py`; `build_after_client_attrs` is covered by
  `tests/unit/observability/test_attributes.py`. No existing test asserts an exact attribute dict
  (only `test_metrics_subscriber.py:68` asserts a token-type set), so adding keys is safe.
  `test_metrics_label_whitelist.py` forbids only per-task SDD ids; `parrot.tenant` is bounded.
- **EventBus fan-out** (`observability/fanout.py`) forwards after/failed events minus
  `error_message`; adding `tenant` to before/round events does not change what is forwarded.
- **Voice usage**: both streams already accumulate a `LiveCompletionUsage` (`live.py:787`, merged at
  `:821`; `nova/audio.py:1403`, set from Nova's `usageEvent` at `:2013`), so session-level after
  events can report real token counts.
- **Ledger context**: `issue:aee666627fc7` — `bots/data.py` has 7 pre-existing ruff findings (open,
  low). Do not fix them here; lint only the lines you change.
- **Existing tests to extend**: `tests/unit/bots/test_current_tenant_binding.py` (uses the
  `make_bot` fixture in `tests/unit/bots/conftest.py:318`), `tests/unit/clients/test_client_emits_agent_name.py`,
  `tests/clients/test_live_usage_metadata.py`, `tests/clients/test_nova_audio_sdk.py`,
  `tests/bots/test_voicebot_contract.py`, `tests/integration/observability/test_poc.py` (in-memory
  span exporter + metric reader wiring).

## Decisions

- **Base branch: `dev`** (operator, Q&A). Worktree off `origin/dev`; `/sdd-done` opens the PR to `dev`.
- **Nova voice streaming is in scope** (operator, Q&A): `NovaAudio.stream_voice` emits lifecycle events.

## Assumptions

Decisions taken without a Q&A round; revisit before launching the worker if any is wrong.

- **Gemini Live voice streaming is also in scope** (HOTFIX-otel-attribution-4). Found after the Q&A
  round: `GeminiLiveClient.stream_voice` has the same no-emission gap as Nova and is `VoiceBot`'s
  default provider, so the goal sentence cannot hold without it. It is a separate task so it can be
  dropped (delete the task file and its index entry) without touching the others.
- **Attribute key `parrot.tenant`**, sentinel `"unknown"` on both spans and metrics when no tenant is
  bound (keeps series bounded and makes coverage gaps visible as a filterable value).
- **Resolver unchanged**: `_resolve_call_tenant` precedence (explicit `tenant` → `ctx.kwargs["tenant"]`
  → none). No fallback to a bot's static tenant; callers that want one pass it explicitly.
- **Read `tenant` from `kwargs` with `.get()`, never `.pop()`**, in `conversation()`, `invoke()` and
  the overriding agents, so whatever those methods forward today is unchanged.
- **Voice granularity**: one before/after (or failed) pair per `stream_voice` session, with the
  session's accumulated token usage; per-turn events are out of scope.
- **Out of scope**: tool-call metric labels, the separate Prometheus usage recorder
  (`recorders/prometheus_recorder.py`, provider/model only), dashboards and docs.

## Fix plan

1. **HOTFIX-otel-attribution-1** — tenant on OTel signals: `tenant` field on `BeforeClientCallEvent`
   and `ClientRoundEvent` (captured in `AbstractClient._emit_before_call` / `_emit_round_event`), and
   `parrot.tenant` on client/invoke spans and every LLM metric. *(no deps)*
2. **HOTFIX-otel-attribution-2** — shared call-identity helper on `BaseBot`
   (`_bind_call_tenant`, `_bind_call_identity`, `_reset_call_identity`, `with_call_identity`
   decorator); `ask`/`ask_stream` route their tenant binding through it; `conversation()` and
   `invoke()` bind the tenant. *(no deps)*
3. **HOTFIX-otel-attribution-3** — `PandasAgent.ask`, `DatabaseAgent.ask` (decorator) and
   `VoiceBot.ask` / `ask_stream` (inline bind/reset in their existing `try/finally`) bind agent and
   tenant. *(depends on 2)*
4. **HOTFIX-otel-attribution-4** — `GeminiLiveClient.stream_voice` emits before/after/failed client
   events per session. *(no deps)*
5. **HOTFIX-otel-attribution-5** — `NovaAudio.stream_voice` emits before/after/failed client events
   per session. *(no deps)*
6. **HOTFIX-otel-attribution-6** — end-to-end coverage test: BasicAgent, PandasAgent, DatabaseAgent and
   VoiceBot LLM calls produce metrics and spans carrying `parrot.agent.name == bot.name` and
   `parrot.tenant == <tenant>` through the real subscribers and in-memory OTel readers.
   *(depends on 1, 2, 3)*

## Validation commands

> Run from the worktree root with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-client-google/src:packages/ai-parrot-client-amazon/src`.

- `pytest packages/ai-parrot/tests/unit/observability/test_tenant_attribution.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_attributes.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_metrics_subscriber.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_metrics_label_whitelist.py -q`
- `pytest packages/ai-parrot/tests/unit/clients/test_client_emits_agent_name.py -q`
- `pytest packages/ai-parrot/tests/unit/bots/test_current_tenant_binding.py -q`
- `pytest packages/ai-parrot/tests/unit/bots/test_overriding_agents_identity.py -q`
- `pytest packages/ai-parrot/tests/bots/test_voicebot_contract.py -q`
- `pytest packages/ai-parrot/tests/clients/test_live_stream_voice_events.py -q`
- `pytest packages/ai-parrot/tests/clients/test_live_usage_metadata.py -q`
- `pytest packages/ai-parrot/tests/clients/test_nova_stream_voice_events.py -q`
- `pytest packages/ai-parrot/tests/clients/test_nova_audio_sdk.py -q`
- `pytest packages/ai-parrot/tests/integration/observability/test_agent_tenant_attribution.py -q`
- `pytest packages/ai-parrot/tests/integration/observability/test_poc.py -q`
