---
id: FC-011
query_id: [Q028, Q045]
type: read
intent: "Observability: OpenTelemetry spans, trace_id propagation, token usage / cost accounting — basis for the three-level telemetry (D12, D13)."
executed_at: 2026-10-25T22:46:15Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-011 — Per-call usage + USD cost + trace_id already recorded (UsageRecord, CostCalculator, GenAI OTel subscriber); attribution via ContextVars; no cross-boundary trace propagation into an outbound RPC

## Summary

`parrot/observability/` (FEAT-176/228/462) provides `CostCalculator`, `GenAIOpenTelemetrySubscriber` (spans), OTLP exporters (grpc + http), pluggable recorders (`recorders/{logging_recorder,openlit_recorder,prometheus_recorder,run_ledger,subscriber}.py`) and the `UsageRecord` model with `provider, client_name, model, input_tokens, output_tokens, cost_usd, cumulative_cost_usd, duration_ms, finish_reason, trace_id, service_name, timestamp, run_id, seat, node_id, cycle, usage_reported, status, error_type`. Span attributes include `gen_ai.usage.cost` and legacy `parrot.cost.usd`. `observability/context.py` holds ContextVars `current_agent_name`, `current_user_id` with `agent_identity()`, `invocation_context()`, `usage_attribution()` managers, so nested agent calls are attributed correctly in-process. What is missing for D13: a caller-generated `trace_id` carried in gRPC metadata / bus headers to a remote parrot (A2A client sends only `Content-Type` and `A2A-Version` headers, FC-001), and a per-capability (not per-LLM-call) cost record for deterministic calls.

## Citations

- path: `packages/ai-parrot/src/parrot/observability/recorders/models.py`
  lines: 22-85
  symbol: `UsageRecord`
  excerpt: |
    class UsageRecord(BaseModel):
        provider: str
        model: str = ""
        input_tokens: int = 0
        output_tokens: int = 0
        cost_usd: Optional[float] = None
        duration_ms: float = 0.0
        trace_id: Optional[str] = None
        run_id: Optional[str] = None
- path: `packages/ai-parrot/src/parrot/observability/context.py`
  lines: 1-15
  symbol: module docstring
  excerpt: |
    """Agent-identity and user-context ContextVars for observability.
    FEAT-228 TASK-1499. Provides task-local carriers that the bot sets around
    each public invocation and the LLM client reads when building its lifecycle
- path: `packages/ai-parrot/src/parrot/observability/context.py`
  lines: 86-162
  symbol: `agent_identity`, `invocation_context`, `usage_attribution`
- path: `packages/ai-parrot/src/parrot/observability/attributes.py`
  lines: 240-242
  symbol: cost span attributes
  excerpt: |
    if cost_usd is not None:
        attrs["parrot.cost.usd"] = cost_usd  # legacy name — kept for backward compat
        attrs["gen_ai.usage.cost"] = cost_usd  # FEAT-462 — OpenLIT SemConv standard
- path: `packages/ai-parrot/src/parrot/observability/__init__.py`
  lines: 63-86
  symbol: exports `CostCalculator`, `GenAIOpenTelemetrySubscriber`
  excerpt: |
    from parrot.observability.cost.calculator import CostCalculator
    from parrot.observability.subscribers.trace import GenAIOpenTelemetrySubscriber
- path: `packages/ai-parrot/src/parrot/observability/exporters.py`
  lines: 52-69
  symbol: OTLP grpc/http trace exporters
- path: `packages/ai-parrot/src/parrot/observability/recorders/base.py`
  lines: 17
  symbol: recorder base docstring
  excerpt: |
    """Abstract base for pluggable usage/token/cost recorders.
- path: `packages/ai-parrot/src/parrot/observability/recorders/logging_recorder.py`
  lines: 17-63
  symbol: `LoggingUsageRecorder`
- path: `packages/ai-parrot/src/parrot/observability/provider.py`
  lines: 9-43
  symbol: provider wiring (`CostCalculator` injected into subscribers)
- path: `packages/ai-parrot/src/parrot/observability/recorders/run_ledger.py`
  lines: 1
  symbol: (run ledger recorder — not read)

## Notes

The lifecycle `TraceContext` (FC-010) and `_apply_cache_hints(trace_context=...)` (FC-004) show W3C trace context is already threaded through client calls in-process; extending it to outbound RPC metadata is incremental.
