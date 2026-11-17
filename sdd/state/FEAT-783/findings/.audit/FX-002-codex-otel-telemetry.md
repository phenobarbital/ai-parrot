---
id: FX-002
query_id: X2
type: read
intent: "External probe: determine whether the Codex seat exports OpenTelemetry, which events carry token usage, and whether it honours OTEL_RESOURCE_ATTRIBUTES."
executed_at: 2026-10-30T22:40:00Z
duration_ms: 4200
parent_id: FX-001
depth: 1
---

# FX-002 — Codex 0.164.0 ships a full OTel stack with per-turn token AND cost metrics

## Summary

Symbol extraction from the Codex 0.164.0 binary (`strings`) shows a first-class
`codex_otel` crate, not an afterthought. Codex emits a `codex.*` event/metric
family, reads the standard `OTEL_EXPORTER_OTLP_*` environment variables, and
**references `OTEL_RESOURCE_ATTRIBUTES`** — the attribute mechanism the source
document only verified for Claude Code. Decisively for this feature, the binary
carries the metric names `codex.turn.token_usage` and
**`codex.turn.cost_microusd`**, plus a `TokenCountEvent` whose field cluster
includes `session_id`, `root_turn_id`, `total_token_usage`,
`thread_token_usage`, `model_context_window` and **`plan_type`**.

The four token counters Codex reports are `input_tokens`, `cached_input_tokens`,
`output_tokens` and `reasoning_output_tokens` — note the fourth: Codex reports a
*reasoning* counter that neither Claude Code nor the parrot clients have, and it
has no slot in the source document's four-counter schema.

This is a `strings`-level probe of a release binary, not a documented contract.
Every field below must be re-confirmed against one captured run or against
Codex's own telemetry documentation before a spec depends on it.

## Citations

- path: `~/.codex/packages/standalone/releases/0.164.0-x86_64-unknown-linux-musl/bin/codex`
  lines: n/a
  symbol: `codex.* metric names`
  excerpt: |
    codex.api_request
    codex.api_request.duration_ms
    codex.conversation.turn.count
    codex.tool.call / codex.tool.call.duration_ms
    codex.turn.cost_microusd
    codex.turn.token_usage

- path: `~/.codex/.../bin/codex`
  lines: n/a
  symbol: `token counter fields`
  excerpt: |
    input_tokens
    cached_input_tokens
    output_tokens
    reasoning_output_tokens
    total_token_usage / thread_token_usage / last_token_usage
    turn.completed

- path: `~/.codex/.../bin/codex`
  lines: n/a
  symbol: `TokenCountEvent attribute cluster`
  excerpt: |
    session_id root_turn_id usage thread_token_usage total_token_usage
    model_context_window TokenCountEvent rate_limits limit_name
    plan_type rate_limit_reached_type credits spend_control_reached

- path: `~/.codex/.../bin/codex`
  lines: n/a
  symbol: `shared OTel resource attributes`
  excerpt: |
    event.name event.timestamp conversation.id turn.id
    user.id user.account_id user.email model app.version
    originator auth_mode terminal.type

- path: `~/.codex/.../bin/codex`
  lines: n/a
  symbol: `OTEL_* environment variables`
  excerpt: |
    OTEL_EXPORTER_OTLP_ENDPOINT / _HEADERS / _TIMEOUT / _COMPRESSION
    OTEL_EXPORTER_OTLP_{TRACES,METRICS,LOGS}_ENDPOINT (+ per-signal variants)
    OTEL_RESOURCE_ATTRIBUTES
    OTEL_TRACES_SAMPLER

- path: `~/.codex/.../bin/codex`
  lines: n/a
  symbol: `codex_otel source modules`
  excerpt: |
    otel/src/skill_invocation.rs
    otel/src/guardian_assessment.rs
    codex_otel.log_only / codex_otel.trace / codex_otel.trace_safe
    otel.kind = thread | exec | network | capability_roots

## Notes

Three consequences for the proposed design, each a contradiction or a
simplification of the source document:

1. The source's row "Codex interactive — unknown whether it honours
   `OTEL_RESOURCE_ATTRIBUTES` or exposes a session id" resolves to **yes on both
   counts**: the variable is referenced and `conversation.id` / `session_id` are
   carried on events. Codex and Claude Code can therefore feed the SAME collector
   pipeline, which collapses the source's separate "Codex wrapper" ingestor.
2. `codex.turn.cost_microusd` means Codex, like Claude Code, self-reports a cost.
   Per the source's own cost model this is a `source_cost_usd` for reconciliation,
   never a value — but it gives the drift cross-check a real input for this seat.
3. `plan_type` on `TokenCountEvent` and `auth_mode` on the shared attributes make
   the per-seat pricing policy (`billed` vs `subscription`) **machine-readable**
   rather than a static config choice. The source assumed this had to be declared
   per seat by hand.

`reasoning_output_tokens` is a genuine gap in the source's schema: a four-counter
usage record silently drops it, and for a reasoning model that is most of the
output spend.

[cross-lane: type=read, intent=does parrot's own OTel/observability subsystem already configure OTEL_EXPORTER_OTLP_* so a second producer can join it]
