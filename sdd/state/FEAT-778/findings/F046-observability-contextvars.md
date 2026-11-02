---
id: F046
query_id: Q012
type: wiki_page
intent: "Observability attribution ContextVars"
executed_at: 2026-10-30T16:47:12Z
duration_ms: 400
parent_id: null
depth: 0
merged_from: [FW-012-observability-contextvars]
---

# F046 — Per-agent attribution is ContextVar-based (`current_agent_name`, `current_run_id`, `current_seat`, `current_tenant`); nested `agent_identity()` scopes attribute inner agents correctly — per-expert OTEL needs no new plumbing, only a scope per activation

## Summary

`observability/context.py` exposes `current_agent_name`, `current_user_id`, `current_session_id`, `current_memory_key_id` (FEAT-525), `current_tenant` (FEAT-710), `current_run_id` and `current_seat` (FEAT-479; seat is a free string such as `"development.w1"`), with token-based context managers `agent_identity(name)`, `invocation_context(...)` and `usage_attribution(run_id, seat)`. Nested scopes push/pop so an inner agent's LLM calls are attributed to the inner agent and restored on exit. `current_seat` is deliberately NOT the closed `NodeId` Literal.

## Citations

- path: `packages/ai-parrot/src/parrot/observability/context.py`
  lines: 1-80
  symbol: `agent_identity` / `invocation_context` / `usage_attribution`
  wiki_page_id: file:packages/ai-parrot/src/parrot/observability/context.py
  score: 0.91
  excerpt: |
    current_agent_name: ContextVar[Optional[str]] = ContextVar("parrot_current_agent_name", default=None)
    current_tenant: ContextVar[Optional[str]] = ContextVar("parrot_current_tenant", default=None)
    current_run_id = ContextVar("parrot_current_run_id", default=None)
    current_seat = ContextVar("parrot_current_seat", default=None)   # free string, not NodeId
    @contextmanager
    def agent_identity(name): token = current_agent_name.set(name); try: yield; finally: current_agent_name.reset(token)
    @contextmanager
    def usage_attribution(run_id, seat=None): ...

## Notes

An inline expert (persona injected into the conductor) would still be attributed to the conductor's `current_agent_name` unless the activation wraps the call in `agent_identity(expert.name)`; `current_seat` can carry `"<stage>.<expert>"` for stage-level cost accounting. Answers the source's "tier → OTEL" question partially: no attribute for tier exists.
