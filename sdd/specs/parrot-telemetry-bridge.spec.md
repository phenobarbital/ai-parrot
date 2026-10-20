---
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-server]
tags: [telemetry, observability, cost, chat-storage, kpi]
---

# Feature Specification: Parrot telemetry bridge (AI usage → TelemetryEvent)

**Feature ID**: FEAT-775 (cross-repo ID, reserved in `fieldsync/sdd/FEAT_ID_LEDGER.md`, dev @ 7217a8d85)
**Jira**: NVP-506 · Epic NVP-502
**Date**: 2026-10-20
**Author**: Javier León
**Owner**: Henry Cabello
**Status**: draft
**Depends on**: FEAT-774 (`TelemetryEvent` + `BigQueryBatchSubscriber` in navigator-eventbus)

---

## 1. Motivation & Business Requirements

### Problem Statement

The business wants these AI KPIs per client (program), per user and per agent:
- cost and tokens;
- questions asked and their most frequent topics;
- satisfaction;
- error rate.

Today:
- `UsageRecord` (`observability/recorders/models.py:22`) has tokens and cost but, **by PII contract**, no user, session or agent (docstring :1-11).
- Prometheus labels are limited to provider and model.
- The lifecycle events *do* carry `agent_name`, `user_id` and `session_id` (`AfterClientCallEvent`, `core/events/lifecycle/events/client.py:74-76`), but nothing persists them in a queryable form.
- **No** parrot record has a program or tenant.
- `ChatStorage.save_turn` accepts `metadata` (`storage/chat.py:124`), but both call sites in AgentTalk omit it, so token usage per turn is lost.
- Topic analysis of questions does not exist.

### Goals

- Emit one `TelemetryEvent` per agent invocation (`ai.invoke`) and per LLM call (`ai.llm_call`). Each carries `user_id`, `session_id`, `program_slug`, `agent`, model, tokens and cost.
- Add a `current_program_slug` ContextVar and set it wherever the user and session are resolved.
- Persist `usage` and `program` per turn in ChatStorage metadata.
- Add a daily question-topic job that writes `telemetry.ai_question_topics`.
- Document and enable the production configuration: `PARROT_STORAGE_BACKEND=postgres` and `OBSERVABILITY_ENABLED`.

### Non-Goals

- Changing the `UsageRecord` PII contract or the Prometheus label set.
- Storing prompt or response text in `telemetry.events`. Text stays in ChatStorage.
- Dashboards (FEAT-773) and report-builder assistant tokens (FEAT-779).

---

## 2. Architectural Design

### Overview

```
bots/base.py emits ──▶ lifecycle registry ──▶ TelemetryBridge (EventProvider)
  AfterInvokeEvent / InvokeFailedEvent           │ + ContextVars (agent, user, session, program)
  AfterClientCallEvent / ClientCallFailedEvent   │ + CostCalculator.cost_usd(...)
                                                 ▼
                                  TelemetryEvent ──▶ BigQueryBatchSubscriber (FEAT-774)
AgentTalk handler ──save_turn(metadata={usage, program, cost_usd})──▶ ChatStorage
flowtask/cron ──▶ topic job (embeddings + greedy cosine clustering) ──▶ telemetry.ai_question_topics
```

### Integration Points (verified on origin/dev @ 69fb12a41)

| Piece | Location |
|---|---|
| Invoke events | `packages/ai-parrot/src/parrot/core/events/lifecycle/events/invoke.py:14` `BeforeInvokeEvent` (agent_name, method, question, user_id, session_id), `:34` `AfterInvokeEvent` (agent_name, method, duration_ms, input/output_tokens), `:55` `InvokeFailedEvent` (error_type) |
| Client events | `.../events/client.py:45` `AfterClientCallEvent` (client_name, model, duration_ms, input/output_tokens, finish_reason, agent_name, user_id, session_id), `:80` `ClientCallFailedEvent` |
| ContextVars | `packages/ai-parrot/src/parrot/observability/context.py:63` `current_agent_name`, `:65` `current_user_id`, `:67` `current_session_id`, `:105` `invocation_context(...)`, `:147` `current_run_id` |
| Cost | `packages/ai-parrot/src/parrot/observability/cost/calculator.py:135` `CostCalculator`, `:190` `cost_usd(*, provider, model, input_tokens, output_tokens, cached_input_tokens=0)` |
| Provider registration | `packages/ai-parrot/src/parrot/observability/bootstrap.py:138` `get_global_registry().add_provider(subscriber)` |
| Existing PII-free sink (keep it) | `packages/ai-parrot/src/parrot/observability/recorders/subscriber.py:47` `UsageRecordingSubscriber` |
| User/session resolution | `packages/ai-parrot-server/src/parrot/handlers/agent.py:873` `_get_user_session`, which uses `resolve_user_id` (:911) |
| Session programs | `packages/ai-parrot-server/src/parrot/handlers/programs.py:20` `session.get('programs', [])` |
| save_turn call sites | `packages/ai-parrot-server/src/parrot/handlers/agent.py:2729` (streaming, `ai_message`) and `:2968` (non-streaming, `response`) |
| save_turn signature | `packages/ai-parrot/src/parrot/storage/chat.py:106`; `metadata` at :124, stored at :176 |
| Usage model | `packages/ai-parrot/src/parrot/models/responses.py:143` `AIMessage.usage: CompletionUsage`; `models/basic.py:48` `CompletionUsage` (prompt_tokens, completion_tokens, total_tokens, total_time, estimated_cost, extra_usage) |
| Embeddings | `packages/ai-parrot/src/parrot/embeddings/registry.py:55` `EmbeddingRegistry`, `:223` `get_or_create` |
| Clustering | `packages/ai-parrot/src/parrot/memory/dream/runner.py:301` `_cluster_by_embedding` (greedy cosine threshold) |

### Program resolution

The program is resolved per request in this order:
1. an explicit `program` / `program_slug` on the request (query param, or body for AgentTalk), if it is one of the session's programs;
2. the agent's configured program, when the bot belongs to one program;
3. the first entry of `session['programs']` when there is exactly one;
4. otherwise `None`.

A program the user does not belong to is never accepted from the client.

### Data Models

```python
# observability/context.py (new)
current_program_slug: ContextVar[Optional[str]] = ContextVar("parrot_current_program_slug", default=None)
# invocation_context(...) gains `program_slug: Optional[str] = None` (token-based set/reset like the others)

# observability/telemetry_bridge.py (new)
class TelemetryBridge:   # EventProvider registered on get_global_registry()
    def __init__(self, emit: Callable[[TelemetryEvent], None], calculator: CostCalculator | None = None): ...
    # AfterInvokeEvent      -> event_name="ai.invoke",   status="ok",    duration_ms, attrs{agent, method, input_tokens, output_tokens}
    # InvokeFailedEvent     -> event_name="ai.invoke",   status="error", attrs{agent, method, error_type}   (never error_message)
    # AfterClientCallEvent  -> event_name="ai.llm_call", status="ok",    attrs{agent, provider, model, input_tokens, output_tokens, cost_usd, finish_reason}
    # ClientCallFailedEvent -> event_name="ai.llm_call", status="error", attrs{agent, provider, model, error_type}
    # user_id/session_id from the event, falling back to the ContextVars; program_slug from current_program_slug
```

`telemetry.ai_question_topics` (one row per cluster per day per program):
`run_date DATE, program_slug STRING, agent STRING, topic_id STRING, label STRING, size INT64, sample_questions ARRAY<STRING> (≤5, PII-scrubbed), first_seen DATE, model STRING`.

---

## 3. Module Breakdown

### Module 1: program ContextVar
Add `current_program_slug` and extend `invocation_context`. Set the program in `_get_user_session` and the AgentTalk entry points following the resolution order above.

### Module 2: `TelemetryBridge`
Map the four events. Cost uses `CostCalculator.cost_usd`; when pricing is unknown, `cost_usd=None` and `attrs.pricing_missing=true`. The bridge is registered in `bootstrap.py` only when `TELEMETRY_ENABLED` is true and FEAT-774's `setup_telemetry` is available. `UsageRecordingSubscriber` is left untouched.

### Module 3: per-turn usage in ChatStorage
At `agent.py:2729` and `:2968`, pass:

`metadata={"usage": msg.usage.model_dump(), "cost_usd": cost, "program": program_slug, "agent": agent_name}`

`msg` is `ai_message` at the first call site and `response` at the second. When `estimated_cost` is None, the cost is backfilled with `CostCalculator`. The Redis hot tier (`chat.py` ~:190) also stores `metadata.usage`.

### Module 4: question-topic job
A batch job, runnable from flowtask or the CLI, that runs daily:
1. read the previous day's `user_message` per program and agent from ChatStorage (Postgres backend);
2. embed it with `EmbeddingRegistry.get_or_create`;
3. cluster it, reusing `_cluster_by_embedding` (with a threshold that can be configured);
4. label each cluster with one cheap LLM call over the top samples;
5. write `telemetry.ai_question_topics`.

### Module 5: production configuration
Write a deploy note and the values for FEAT-780: `PARROT_STORAGE_BACKEND=postgres` (today the default is sqlite), `OBSERVABILITY_ENABLED=true`, `OBSERVABILITY_BACKEND=prometheus` (kept) and `TELEMETRY_ENABLED=true`.

---

## 4. Test Specification

### Unit Tests
- `test_bridge_maps_after_client_call`: the event and ContextVars produce a `TelemetryEvent` with `event_name="ai.llm_call"`, the program, the agent and cost.
- `test_bridge_failed_never_includes_error_message`.
- `test_bridge_unknown_pricing_sets_flag`.
- `test_program_resolution_rejects_foreign_program`.
- `test_invocation_context_resets_program`, covering nested contexts.
- `test_save_turn_metadata_has_usage`: both call sites, with a mocked ChatStorage.
- `test_usage_record_unchanged`: `UsageRecord` still has no user, session or program (a guard on the PII contract).
- `test_topic_job_clusters_and_scrubs`: emails and phone numbers are removed from `sample_questions`.

### Integration Tests
- In staging, one AgentTalk turn produces one `ai.invoke` row and at least one `ai.llm_call` row in `telemetry_dev.events` with the same `session_id`. The ChatStorage turn has `metadata.usage.total_tokens > 0`.

---

## 5. Acceptance Criteria

- [ ] AI cost and tokens can be queried by user, agent and program in `telemetry.events`. The FEAT-773 dashboards consume them.
- [ ] ChatStorage turns carry `usage`, `cost_usd` and `program`.
- [ ] `telemetry.ai_question_topics` is filled daily for every program that has chats.
- [ ] The `UsageRecord` PII contract and the Prometheus labels are unchanged.
- [ ] Production runs with `PARROT_STORAGE_BACKEND=postgres` (coordinated with FEAT-780).

---

## 6. Task Breakdown (for Henry)

1. Program ContextVar plus program resolution in `_get_user_session`, with tests.
2. `TelemetryBridge` and its registration in the bootstrap, behind `TELEMETRY_ENABLED`, with tests. Needs the FEAT-774 release.
3. `save_turn` metadata at both call sites, plus the hot tier, with tests.
4. Question-topic job and `ai_question_topics` DDL, with tests.
5. Production configuration note and values handed to FEAT-780.
6. Staging integration check and a sample query for FEAT-773.
