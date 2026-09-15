# FEAT-548 — verified Prometheus series names

**Captured**: 2026-09-10, ~17:37–17:54 UTC
**By**: sdd-worker (autonomous), operator's own machine, real credentials
**Preconditions**: TASK-3107 applied (env vars set at process level — see
Methodology note below); `parrot-prometheus` recreated with
`--enable-feature=otlp-write-receiver`; `parrot-grafana` up.

## Methodology note (read this first)

`ObservabilityConfig.from_env()` resolves via `navconfig`, whose `BASE_DIR`
in this worktree resolves to the **main repo checkout**
(`/home/jesuslara/proyectos/ai-parrot`), not this worktree — a `navconfig`
quirk when running from a git worktree sharing the main repo's venv
(confirmed: `navconfig.conf.BASE_DIR` prints the main repo path regardless
of `cwd`). The main repo's `env/.env` does not carry the `[observability]`
block either (see TASK-3107's completion note — it had none at all before
this feature), so a plain `from_env()` call silently fell back to defaults
(`enabled=False`).

**Workaround used**: the six `OBSERVABILITY_*`/`OTEL_EXPORTER_OTLP_ENDPOINT`
variables from TASK-3107's block were exported at the **process
environment** level for each verification run
(`OBSERVABILITY_ENABLED=true OBSERVABILITY_BACKEND=otel ... python3
script.py`). `_env_getter()` (`config.py:370`) falls back to
`os.environ.get(key)` when `navconfig`'s own lookup returns `None` for that
key, so this reliably reproduces the exact same `ObservabilityConfig` an
operator gets from a correctly-populated `env/.env` on a real single-repo
checkout — confirmed by printing `ObservabilityConfig.from_env()` before
each run (`enabled=True backend=otel endpoint=http://localhost:9090/api/v1/otlp
sampling=0.0`, matching TASK-3107's block exactly). This is a worktree
testing artifact, not a change to how `env/.env` itself is read in normal
(non-worktree, or npm-installed) operation — recorded here per
`worktree-test-setup-and-jira-shim-gotcha` precedent, not filed as an
observability-package defect.

## Baseline (before TASK-3107's changes took effect)
gen_ai_*/parrot_* series present: **0** — confirmed via
`docker inspect parrot-prometheus` showing the pre-existing container
predated the `docker/` reorg entirely (old bind mount, missing
`--enable-feature=otlp-write-receiver`); recreated cleanly via
`docker compose -f docker/prometheus/docker-compose.yml up -d`, then
re-baselined: 212 total series, 0 matching `gen_ai_*`/`parrot_*` — the F010
zero-series baseline, reproduced.

## Name map (OTel instrument -> Prometheus series, VERBATIM)

| OTel instrument | Prometheus series |
|---|---|
| gen_ai.client.request.count | `gen_ai_client_request_count_total` |
| gen_ai.client.error.count | **absent** — see Findings below |
| gen_ai.client.cost.total | `gen_ai_client_cost_USD_total` — note the `USD` unit is inserted mid-name (`<name>_<UNIT>_total`), not appended as a suffix |
| gen_ai.client.operation.duration | `gen_ai_client_operation_duration_seconds_bucket` / `_sum` / `_count` |
| gen_ai.client.token.usage | `gen_ai_client_token_usage_tokens_bucket` / `_sum` / `_count` |
| parrot.client.rounds | **absent** — not exercised by this verification (see Findings) |
| parrot.client.round.token.usage | **absent** — not exercised by this verification (see Findings) |
| parrot.tool.execution.duration | **absent** — not exercised (no tool calls made) |
| parrot.tool.failure.count | **absent** — not exercised (no tool calls made) |
| parrot.agent.invoke.duration | **absent** — not exercised (see Findings) |
| parrot.agent.invoke.failure.count | **absent** — not exercised (see Findings) |

## Label map (OTel attribute -> Prometheus label, VERBATIM)

| OTel attribute | Prometheus label |
|---|---|
| parrot.agent.name | `parrot_agent_name` (value `unknown` — see Findings) |
| gen_ai.request.model | `gen_ai_request_model` |
| gen_ai.response.model | `gen_ai_response_model` |
| gen_ai.provider.name | `gen_ai_provider_name` |
| gen_ai.system | `gen_ai_system` |
| gen_ai.token.type | `gen_ai_token_type` |
| error.type | not observed (no error.count series emitted — see Findings) |

## Temporality (AC-5)

Ran a genuine single-process, single-`instance` monotonicity probe: 3
real `openai:gpt-4o-mini` calls ~22–26s apart in ONE long-lived process
(so `service.instance.id` stayed constant), with `metric_export_interval_ms`
shortened to 5000ms for this verification run only (code-only field,
`config.py:211`, not env-settable — production wiring from TASK-3107 is
untouched; see spec Codebase Contract).

| sample | time (UTC) | value |
|---|---|---|
| 1 | 17:52:58 | 1 |
| 2 | 17:53:24 | 2 |
| 3 | 17:53:51 | 3 |

Monotonic increase observed: **yes**

Direct push delivers cumulative counters, as the spec's C11 risk note
hoped. AC-13's collector fallback is **not required**.

## Traces (AC-6)
/v1/traces requests observed: **none** — grepped every captured process
log (`waiting for fire-and-forget event forwarding...` runs +
monotonicity probes) for `trace`/`export.*error`/`ConnectionError`/
`otlp.*error`; only match is the expected
`setup_telemetry: observability active for 'parrot' (traces=True, ...)`
info line (that flag just means the trace *subsystem* is wired, not that
a request was sent — `TraceIdRatioBased(0.0)` marks every span
non-recording before an exporter is ever reached, confirmed independently
by `test_zero_sampling_emits_no_spans` in TASK-3114).
OTLP export errors in log: **none**.

## Shutdown (AC-7)
CTRL+C was not literally sent (no interactive terminal in this harness);
`shutdown_telemetry()` wall-clock time is used as the direct proxy — it is
what the ~10s+ atexit block symptom actually measures. Observed range
across 7 process runs: **0.00s – 8.96s** (typical), with one **23.35s**
outlier during a run with 3 consecutive real provider *failures*
(Anthropic/Moonshot billing errors, Groq model-not-found) stacked before
the successful OpenAI call — plausibly SDK-level HTTP retry/backoff on the
failing providers' own clients, not the observability pipeline (the same
run's `shutdown_telemetry()` itself does no provider-specific work). Normal
successful-call runs were consistently fast (0.00–8.96s), well under the
original ~10s+ symptom. **Caveat, not a blocker**: an operator whose first
real run also hits several failing providers back-to-back may see a slower
shutdown; this is provider-client retry behavior, out of FEAT-548's scope
(the spec's non-goals exclude changes to client code).

## Findings (beyond the template — flagged, not silently worked around)

1. **`gen_ai.client.error.count` never emitted, across 7 distinct real
   failures spanning 5 different provider clients** (Groq ×2 model-not-found,
   NVIDIA ×2 model-EOL, Anthropic billing, Moonshot billing, OpenAI
   model-not-found). `MetricsSubscriber._on_client_fail` (`metrics.py:295`)
   is wired correctly and `AbstractClient._emit_failed_call`
   (`clients/base.py:700`) exists and calls `forward_to_global`, so the
   wiring *should* work — but no failing call in this session produced the
   series. Not investigated further per this task's scope (`NOT in scope:
   ... fixing a delta-temporality failure ... record the finding, do not
   improvise a workaround` — extending the same principle to this second
   unexpected gap). **Recorded, not fixed.** Worth its own investigation
   task if error-rate dashboarding matters before this ships.
2. **Fire-and-forget event forwarding can be silently dropped if the
   process exits (or `shutdown_telemetry()` is called) immediately after
   the last client call, with no intervening event-loop yield.**
   Empirically reproduced: a single `client.ask()` call followed
   immediately by `shutdown_telemetry()` in a `finally` block produced
   **zero** `gen_ai.client.*` series from that call (not even request
   count) — `AbstractClient._emit_after_call`'s `forward_to_global(event)`
   dispatches via a scheduled (not awaited-through) task, and nothing in
   `ask()`'s own call chain yields long enough for it to run before the
   process tears down. Inserting a brief `await asyncio.sleep(...)` between
   the last call and `shutdown_telemetry()` reliably fixes it (used
   throughout this verification). **This is a real integration gotcha for
   any short-lived script/CLI/lambda-style caller** — worth a documentation
   note in TASK-3112 (docs sync) and/or `docs/architecture/10-observability.md`,
   not a code change under this feature's scope.
3. **`parrot.agent.name` is always `unknown`, and the `parrot.*`
   agent/tool-level instruments never appear**, because this verification
   used raw `AbstractClient.ask()` calls (`LLMFactory.create(...)`), not
   `parrot.bots.Agent`/`Chatbot`. That is expected and matches the
   instrument catalog's own design (`parrot.client.rounds`,
   `parrot.tool.*`, `parrot.agent.invoke.*` are agent/tool-framework
   instruments, not client-level) — not a defect, just a scope note for
   whoever authors TASK-3110's "by agent" panels: they will show real data
   only for calls routed through the agent framework, not bare client
   calls like this verification's.

## Instrument catalog cross-check

Every instrument this session actually exercised (`gen_ai.client.request.count`,
`.cost.total`, `.operation.duration`, `.token.usage`) matches its
`subscribers/metrics.py` definition exactly — no name/unit surprises beyond
the `USD` mid-name insertion already noted. `gen_ai.client.token.usage` is
confirmed as `_bucket`/`_sum`/`_count` (a histogram), never a `_total`
counter — directly reproducing why `parrot-overview.json`'s
`gen_ai_client_token_usage_total` query (F009) has never matched anything.
