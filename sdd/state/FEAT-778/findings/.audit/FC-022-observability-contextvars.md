---
id: FC-022
query_id: Q041
type: read
intent: "Read observability context: attribution ContextVars for agent/run/seat."
executed_at: 2026-10-30T16:46:28Z
duration_ms: 400
parent_id: null
depth: 0
---

# FC-022 — Attribution ContextVars: `current_agent_name`, `current_user_id`, `current_session_id`, `current_memory_key_id`, `current_tenant`, `current_run_id`, `current_seat`; helpers `agent_identity()`, `invocation_context()`, `usage_attribution()`

## Summary

`observability/context.py` (188 lines). Per-call OTEL/usage attribution is ContextVar-based; an activated expert running inside a conductor would be attributed to the conductor's `current_agent_name` unless the dispatcher wraps the activation in `agent_identity(<expert>)` (inline mode) or spawns a distinct agent (subagent mode). `current_seat` (dev-loop seats) is the closest existing "which role ran this" tag. No `tier` attribute exists.

## Citations

- path: `packages/ai-parrot/src/parrot/observability/context.py`
  lines: 67-82
  symbol: `current_agent_name / current_user_id / current_session_id / current_memory_key_id / current_tenant`
  excerpt: |
    current_agent_name: ContextVar[Optional[str]] = ContextVar("parrot_current_agent_name", default=None)
    current_tenant: ContextVar[Optional[str]] = ContextVar("parrot_current_tenant", default=None)

- path: `packages/ai-parrot/src/parrot/observability/context.py`
  lines: 86-114
  symbol: `agent_identity / invocation_context`
  excerpt: |
    def agent_identity(name: Optional[str]) -> Iterator[None]:
    def invocation_context(

- path: `packages/ai-parrot/src/parrot/observability/context.py`
  lines: 156-162
  symbol: `current_run_id / current_seat / usage_attribution`
  excerpt: |
    current_run_id: ContextVar[Optional[str]] = ContextVar("parrot_current_run_id", default=None)
    current_seat: ContextVar[Optional[str]] = ContextVar("parrot_current_seat", default=None)
    def usage_attribution(

## Notes

Skills tenancy reuses `current_tenant` from here (FC-009).
