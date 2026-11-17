---
id: F010
query_id: Q031
type: read
intent: "Read the local Codex config to determine whether an [otel] block / telemetry export is configured or supported."
executed_at: 2026-10-30T22:58:00Z
duration_ms: 1500
parent_id: FC-009
depth: 1
lane: codebase
merged_from: ['FC-010', 'FX-002']
---

# F010 — RESOLVED (was Spike S3): codex-cli 0.164.0 exports OTel with `gen_ai.usage.*`, a four-tier token split, cost in micro-USD, and a hooks system

## Summary

The source marks every Codex fact "unverified" and makes Spike S3 a gate. Direct probing of
the installed binary settles most of it. **codex-cli 0.164.0 ships a `codex_otel` crate**
and emits, under `otel.name`, the standard OpenTelemetry GenAI semantic conventions —
the **same vocabulary parrot's own `MetricsSubscriber` already uses** (FC-007):

- `gen_ai.usage.input_tokens`
- `gen_ai.usage.cache_read.input_tokens`
- `gen_ai.usage.cache_write.input_tokens`
- `gen_ai.usage.output_tokens`
- `codex.usage.reasoning_output_tokens`
- `codex.usage.total_tokens`
- `codex.turn.token_usage`, `codex.turn.cost_microusd`, `codex.api_request`,
  `codex.api_request.duration_ms`, `codex.conversation.turn.count`, `codex.tool.call`

Correlation attributes present in the binary: `conversation.id`, `turn.id`, `thread.id`,
`execution.id`, `user.id`, `user.account_id`, `model`, `app.version`, `originator`,
**`auth_mode`** (plus `auth.env_openai_api_key_present` / `auth.env_codex_api_key_present`),
and for sub-agents `agent.type`, `parent.conversation.id`, `parent.turn.id`, `root.turn.id`,
`initiating.agent.path`. There are `codex_otel.log_only` and `codex_otel.trace_safe` modes
and an exporter with a disabled state (`ExporterDisabled`, "otel exporter: …").

Two consequences the source could not know:

1. **Codex gives a four-tier token split including a cache-*write* tier**, which parrot's
   own price table cannot express (FC-006: entries have only `cached_input_per_1m`).
2. **Codex reports `auth_mode`**, which is exactly the signal the source's per-seat
   `billed` / `subscription` pricing policy needs — it does not have to be configured by hand.

**Codex also has a Claude-Code-shaped hooks system, already in use in this repo.**
`.codex/hooks.json` registers a `PreToolUse` hook with a `matcher` running
`sh scripts/sdd/codex_hook.sh`, and `~/.codex/config.toml` tracks per-hook
`trusted_hash` entries under `[hooks.state]`. The source's open question "is there a hook or
`notify` mechanism that exposes a session id" is answered: yes, with the same
event/matcher/command shape as Claude Code.

## Citations

- path: `~/.codex/config.toml`
  lines: 1-30
  symbol: `local codex config`
  excerpt: |
    model = "gpt-6-astra"
    model_reasoning_effort = "medium"
    [plugins."github@openai-curated"]
    enabled = true
    [projects."/home/jesuslara/proyectos/ai-parrot"]
    trust_level = "trusted"
    [hooks.state]
    [hooks.state."/home/jesuslara/proyectos/ai-parrot/.codex/hooks.json:pre_tool_use:0:0"]
    trusted_hash = "sha256:3ba9d40ca05c2bb630a828fc22f74d93e90a78c23a39e632e1bceefd870325c6"
    -- NO [otel] block configured locally

- path: `.codex/hooks.json`
  lines: 1-15
  symbol: `codex hooks config`
  excerpt: |
    {
      "hooks": {
        "PreToolUse": [
          { "matcher": "Bash",
            "hooks": [ { "type": "command",
                         "command": "sh scripts/sdd/codex_hook.sh",
                         "timeout": 10 } ] } ] } }

- path: `$(which codex)`
  lines: n/a
  symbol: `codex_otel GenAI metric names (binary strings, codex-cli 0.164.0)`
  excerpt: |
    otel.name codex.request.reasoning_effort
              gen_ai.usage.input_tokens
              gen_ai.usage.cache_read.input_tokens
              gen_ai.usage.cache_write.input_tokens
              gen_ai.usage.output_tokens
              codex.usage.reasoning_output_tokens
              codex.usage.total_tokens

- path: `$(which codex)`
  lines: n/a
  symbol: `codex turn/cost metrics`
  excerpt: |
    codex.api_request  codex.api_request.duration_ms
    codex.conversation.turn.count
    codex.tool.call  codex.tool.call.duration_ms
    codex.turn.cost_microusd
    codex.turn.token_usage
    token_type / input / cached_input / cache_write_input / total

- path: `$(which codex)`
  lines: n/a
  symbol: `codex_otel attribute set`
  excerpt: |
    event.name event.timestamp conversation.id turn.id user.id user.account_id
    model app.version originator auth_mode terminal.type user.email
    agent.type item.id parent.conversation.id parent.turn.id root.turn.id
    initiating.agent.path  execution.id  thread.id
    auth.mode auth.env_openai_api_key_present auth.env_codex_api_key_present
    codex_otel.log_only / codex_otel.trace_safe / ExporterDisabled

- path: `codex exec --help`
  lines: n/a
  symbol: `exec options (codex-cli 0.164.0)`
  excerpt: |
    Commands: resume | fork | review | help
    Options: -c/--config <key=value> (dotted path into ~/.codex/config.toml)
             --enable/--disable <FEATURE>, --strict-config
             -m/--model, --oss, --json, --output-schema <JSON Schema>

- path: `~/.codex/`
  lines: n/a
  symbol: `local codex state`
  excerpt: |
    logs_2.sqlite (45.6 MB; table `logs`: id, ts, ts_nanos, level, target,
      feedback_log_body, module_path, file, line, thread_id, process_uuid,
      estimated_bytes — 13,520 rows; a tracing log, NOT a usage store)
    sessions/  session_index.jsonl  history.jsonl  auth.json

## Notes

- `~/.codex/logs_2.sqlite` is a `tracing` log sink keyed by `target`/`module_path`, with no
  token columns — it is **not** a usable usage source; the OTel exporter is.
- No `[otel]` section is configured locally today, so Codex is exporting nothing right now.
  Turning it on is a config change (`-c otel.…` or a `[otel]` block), not a code change.
- Because Codex speaks `gen_ai.usage.*`, a single OTel collector could in principle receive
  **both** the Codex seat and parrot's own `MetricsSubscriber` (FC-007) under one schema.
  Claude Code's `claude_code.*` names do not follow that convention, so the Claude Code seat
  is the odd one out, not Codex.
- Unverified and still a spike: whether `codex exec --json` carries the same token fields on
  its **stdout event stream** (as opposed to the OTel pipe). Settling that needs one real
  `codex exec --json` run, which this read-only lane did not perform.


---

## Merged from FX-002 (external lane)

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
