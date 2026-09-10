---
id: FEAT-548
title: Wire parrot OTEL telemetry into the running parrot-prometheus and ship a usage/cost Grafana dashboard
slug: observability-otel-grafana
type: feature
mode: enrichment
status: accepted
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-09-10
  summary_oneline: Point parrot OTEL at parrot-prometheus and build a Grafana dashboard for usage/tokens/cost by agent and model
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-548/
created: 2026-09-10
updated: 2026-09-10
---

# FEAT-548 — Wire parrot OTEL telemetry into the running parrot-prometheus and ship a usage/cost Grafana dashboard

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `inline`
> **Audit**: [`sdd/state/FEAT-548/`](../state/FEAT-548/)

---

## 0. Origin

The original request, preserved verbatim. The full source is at
`sdd/state/FEAT-548/source.md`.

> parrot observability was recently migrated from openlit to a compatible OTEL
> opentelemetry with per-agent usage, tokens, etc, currently there are a
> prometheus (parrot-prometheus) and grafana (parrot-grafana) docker machines
> running on this server, then we can change the env/.env variables to point to
> prometheus and update the example grafana dashboard to render usage total, by
> agent, by llm model, costs, etc.

**Initial signals** (extracted, not interpreted):
- Verbs: *migrated* (done, past tense), *change*, *point*, *update*, *render*
  → an enrichment/wiring request, not a bug report.
- Named entities: `openlit`, `opentelemetry`/OTEL, `parrot-prometheus`,
  `parrot-grafana`, `env/.env`, "example grafana dashboard".
- Components / labels: none (inline source).
- Acceptance criteria provided: none explicitly; four dashboard dimensions
  named (usage total, by agent, by LLM model, costs).

---

## 1. Synthesis Summary

The openlit→OTEL migration is complete on the emitting side, and the emitter
already produces everything this request asks for:
`packages/ai-parrot/src/parrot/observability/subscribers/metrics.py` emits a USD
cost counter, token histograms and request/error counters, every one of them
labelled with `parrot.agent.name`, a model attribute and `gen_ai.provider.name`.
**No instrumentation work is required.** The gap sits entirely at the two ends.
First, `env/.env` has telemetry switched off and aimed at OpenLIT's `:4318`
rather than the Prometheus OTLP receiver on `:9090` — the live
`parrot-prometheus` confirms this by holding 291 metric names of which *zero*
begin with `gen_ai_` or `parrot_`. Closing that gap is a **pure env-var move**:
the `[observability]` block is repointed from OpenLIT to Prometheus, with no new
container, no second export destination and no code change. Second, both shipped example dashboards under
`packages/ai-parrot/src/parrot/observability/examples/grafana-dashboards/` query
metric names that no code path emits, and neither contains a single by-agent
panel. The work is therefore a configuration change plus a dashboard rewritten
against the real instrument catalog, provisioned through
`docker/grafana/provisioning/dashboards/dashboards.yml` — following the Codex
dashboard integration landed days ago as a working template.

---

## 2. Codebase Findings

> All entries are grounded in the research findings persisted at
> `sdd/state/FEAT-548/findings/`. Each cites the finding ID(s) that justify it.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `env/.env` | `[observability]` section | 715-726 | the switch to flip: `OBSERVABILITY_ENABLED=false`, endpoint aimed at OpenLIT | F004, F010 |
| 2 | `packages/ai-parrot/src/parrot/observability/config.py` | `ObservabilityConfig.from_env` | 347-470 | authoritative env-var contract; every variable that may be changed | F005 |
| 3 | `packages/ai-parrot/src/parrot/observability/exporters.py` | `make_metric_exporter` | 150-154 | appends `/v1/metrics` to a **base** URL; metrics use `otlp_endpoint` only | F006 |
| 4 | `packages/ai-parrot/src/parrot/observability/setup.py` | `setup_telemetry` | 133-208 | traces fan out over `otlp_targets`, metrics do not — the asymmetry this feature exploits | F006 |
| 5 | `packages/ai-parrot/src/parrot/observability/subscribers/metrics.py` | `MetricsSubscriber` | 96-330 | the metric contract every PromQL expression must target | F002, F003 |
| 6 | `packages/ai-parrot/src/parrot/observability/examples/grafana-dashboards/parrot-overview.json` | uid `parrot-observability-overview` | — | example dashboard querying metric names nothing emits | F009 |
| 7 | `packages/ai-parrot/src/parrot/observability/examples/grafana-dashboards/parrot-usage.json` | "AI-Parrot — LLM Usage & Cost" | — | example dashboard bound to the non-OTel `parrot_llm_*` recorder names | F009 |
| 8 | `docker/grafana/provisioning/dashboards/dashboards.yml` | provider `claudestats` | 1-16 | the 30 s auto-load path a parrot dashboard must land in | F008, F011 |
| 9 | `docker/grafana/provisioning/datasources/prometheus.yml` | uid `claudestats-prometheus` | 1-14 | datasource uid a new dashboard must reference | F008 |
| 10 | `docker/prometheus/docker-compose.yml` | `prometheus` service | 30-56 | runs 2.51.0 with `--enable-feature=otlp-write-receiver` → accepts direct OTLP push | F007 |
| 11 | `docker/prometheus/prometheus.yml` | scrape_configs | 1-28 | needs a job only if a collector/scrape model is chosen over direct push | F007, F011 |
| 12 | `docs/architecture/10-observability.md` | env-var table | 20-95 | still tells readers to use `:4318` and the stale example dashboards | F012 |

#### The metric catalog (the dashboard contract) — F002, F003

| Instrument | Kind | Unit | Labels |
|---|---|---|---|
| `gen_ai.client.request.count` | counter | — | `gen_ai.system`, `gen_ai.provider.name`, `gen_ai.request.model`, `parrot.agent.name` |
| `gen_ai.client.error.count` | counter | — | + `error.type` |
| `gen_ai.client.cost.total` | counter | **USD** | `gen_ai.system`, `gen_ai.provider.name`, `gen_ai.response.model`, `parrot.agent.name` |
| `gen_ai.client.operation.duration` | histogram | s | + `gen_ai.operation.name="chat"` |
| `gen_ai.client.token.usage` | histogram | tokens | + `gen_ai.token.type ∈ {input, output}` |
| `parrot.client.rounds` | counter | — | + `parrot.round.number` |
| `parrot.client.round.token.usage` | histogram | tokens | + `parrot.round.number`, `gen_ai.token.type` |
| `parrot.tool.execution.duration` | histogram | s | `parrot.tool.name` |
| `parrot.tool.failure.count` | counter | — | `parrot.tool.name`, `error.type` |
| `parrot.agent.invoke.duration` | histogram | s | `parrot.agent.name`, `parrot.invoke.method` |
| `parrot.agent.invoke.failure.count` | counter | — | `parrot.agent.name`, `parrot.invoke.method` |

Everything the request names — total, by agent, by LLM model, cost — is
answerable from this catalog with no schema change.

### 2.2 Constraints Discovered

- **Metrics have exactly one destination; traces can have many.**
  `make_metric_exporter(config)` reads `config.otlp_endpoint` alone and never
  consults `otlp_targets`, while `setup_telemetry` builds one
  `BatchSpanProcessor` per entry in `config.otlp_targets` (falling back to an
  implicit single target from `otlp_endpoint`).
  *Implication*: moving `otlp_endpoint` to Prometheus moves **both** signals,
  so traces would POST to `/api/v1/otlp/v1/traces`, which Prometheus 2.x does
  not serve.
  *Evidence*: F006

- **`OTEL_EXPORTER_OTLP_ENDPOINT` is a base URL.** The exporters append
  `/v1/metrics` and `/v1/traces` themselves.
  *Implication*: the correct value is `http://localhost:9090/api/v1/otlp`, **not**
  the full `.../v1/metrics` path.
  *Evidence*: F006, F007

- **Traces cannot be switched off from env — but they can be silenced.**
  `enable_traces` / `enable_metrics` are code-only fields; `from_env()` never
  reads them. The env-only lever is `OBSERVABILITY_SAMPLING=0.0`, which feeds
  `TraceIdRatioBased(0.0)`; every span is marked non-recording and never reaches
  the exporter, so no trace request is issued and no 404 occurs.
  *Implication*: this keeps the change a pure env move. Setting the value back
  to `1.0` restores traces later, once a trace-capable endpoint is configured.
  *Evidence*: F014, F006

- **`gen_ai.client.token.usage` is a histogram recorded twice per call**
  (once for input, once for output).
  *Implication*: a token total must be built from its `_sum` series; no token
  `_total` counter exists — which is exactly the false assumption baked into
  `parrot-overview.json` today.
  *Evidence*: F002, F009

- **Per-round tokens must never be summed with per-call tokens.**
  `parrot.client.round.token.usage` is a dedicated instrument that FEAT-397 kept
  separate from `gen_ai.client.token.usage` specifically to avoid double counting.
  *Evidence*: F002

- **Per-user usage is not answerable from metrics.** `user_id`/`session_id` are
  span attributes only, deliberately excluded from metric labels as a
  cardinality guard.
  *Implication*: no per-user cost panel is possible from Prometheus; that
  question belongs to the trace backend.
  *Evidence*: F002

- **Cost is computed in-process, not in PromQL.** `CostCalculator` produces USD
  which `MetricsSubscriber` adds to `gen_ai.client.cost.total` with the full
  agent/model/provider label set.
  *Implication*: cost panels are a direct `sum by (...)`, with no price table in
  Grafana. But `cost_usd()` returns `None` for an unpriced model and that call
  silently contributes nothing, so a cost panel needs a companion request-count
  panel or unpriced models vanish from the dashboard entirely.
  *Evidence*: F003

- **`env/.env` is git-ignored** (`.gitignore:181`) and holds live API keys and
  AWS credentials.
  *Implication*: the wiring change is an operator action on this host, not a
  committed diff, and the file's contents must never be reproduced in an SDD
  artifact. This is why U5 (below) resolves to shipping a committed, secret-free
  reference.
  *Evidence*: F004

- **First data can take a minute.** `metric_export_interval_ms` defaults to
  60 000 and has **no env var** — it is settable only in code.
  *Implication*: a freshly-wired dashboard is legitimately empty for up to a
  minute after the first LLM call; verification steps must account for this.
  *Evidence*: F005

- **Prometheus name translation.** Dotted OTel names become Prometheus names via
  `UnderscoreEscapingWithSuffixes` (dots → underscores, plus unit and `_total`
  suffixes), so series will be shaped like `gen_ai_client_request_count_total`
  and `gen_ai_client_token_usage_tokens_bucket`.
  *Implication*: the exact rendering of the `USD` unit on
  `gen_ai.client.cost.total` must be **read off the live TSDB after the first
  export**, not assumed, before the PromQL is finalized.
  *Evidence*: F011, F002

- **Grafana folder naming.** The provider is named `claudestats` and files
  everything into a folder literally called `Claude Code`, with
  `foldersFromFilesStructure: false`. Provisioned dashboards are read-only in
  the UI (`allowUiUpdates: false`) — operators must "Save as" to customise.
  *Evidence*: F008

- **`docker/` is currently dirty.** `docker/grafana/README.md`,
  `docker/prometheus/docker-compose.yml` and `docker/prometheus/prometheus.yml`
  are modified and `docker/prometheus/otel-collector.yml` is untracked — the
  in-flight Codex collector work.
  *Implication*: sequence this feature against that dirty state; do not assume a
  clean tree.
  *Evidence*: F011

- **The emitter is protected but rigid.** 29 unit test modules under
  `packages/ai-parrot/tests/unit/observability/` already assert the env contract,
  multi-target wiring and instrument names.
  *Evidence*: F012

### 2.3 Recent History (Relevant)

| Commit | When | Message | Touched |
|--------|------|---------|---------|
| `dc0decca2` | current HEAD~1 | codex grafana dashboard | `docker/grafana/**` |
| `2b2aa9f29` | recent | wip: provisioning observability | `docker/**`, observability |
| `db025707b9` | recent | fix(observability): map dispatcher and client names to `gen_ai.system` | `observability/attributes.py` |
| `97485f734d` | FEAT-462 | fix(unified-telemetry-bus): fix critical OTLP endpoint bug + 2nd review round | `observability/**` |
| `8a012fef37` … `653fc5605e` | FEAT-462 | TASK-2470…2476 — multi-endpoint exporter, OpenLIT recorder, setup refactor, integrations cleanup | `observability/**` |
| `91c0032a9d` | FEAT-397 | TASK-2039 — `MetricsSubscriber` per-round OTel instruments | `subscribers/metrics.py` |

This surface is under active, very recent development — the Codex dashboard is
days old and is the template this feature should copy. *Evidence*: F011, F012

---

## 3. Probable Scope

### What's New

- **A correct parrot Grafana dashboard** — provisioned into
  `docker/grafana/provisioning/dashboards/` (parrot subdirectory) so the running
  `parrot-grafana` auto-loads it within 30 s. Panels: total usage, tokens and
  cost by agent, by model, by provider, request/error rate, latency quantiles.
  *Evidence*: F002, F003, F008
- **A second provisioning provider entry** in `dashboards.yml` creating an
  `AI-Parrot` Grafana folder, so parrot dashboards do not land in the folder
  named `Claude Code`. *Evidence*: F008
- **A committed, secret-free `[observability]` reference** — an example env file
  plus the matching block in the docs (resolved U5 = "Both").
  *Evidence*: F004, F005
- **A parrot section in `docker/grafana/README.md`**, mirroring the Codex
  section's shape including the diagnostic `curl` commands for an empty
  dashboard. *Evidence*: F011

### What Changes

- **`env/.env` `[observability]`** — the core of the feature; an operator action
  on this host, moving the existing variables from OpenLIT to Prometheus:

  ```ini
  [observability]
  OBSERVABILITY_ENABLED=true                                     # was: false
  OBSERVABILITY_BACKEND=otel                                     # unchanged
  OBSERVABILITY_SERVICE_NAME=parrot                              # unchanged
  OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:9090/api/v1/otlp  # was: http://localhost:4318
  OBSERVABILITY_SAMPLING=0.0                                     # new: silence traces (see below)
  OBSERVABILITY_COST=True                                        # unchanged
  # OBSERVABILITY_OPENLIT=true  -> DELETE: deprecated no-op since FEAT-462
  ```

  Three notes on this block. The endpoint is a **base URL** — the exporter
  appends `/v1/metrics` itself, so it must not include that suffix.
  `OBSERVABILITY_OPENLIT=true` is removed rather than flipped to `false`: since
  FEAT-462 it does nothing except raise a `DeprecationWarning`.
  `OBSERVABILITY_SAMPLING=0.0` is what keeps this a pure env move — see the
  trace constraint below.
  *Evidence*: F004, F005, F006, F013, F014
- **`packages/ai-parrot/src/parrot/observability/examples/grafana-dashboards/parrot-overview.json`**
  and **`parrot-usage.json`** — replaced with the corrected dashboard so the
  package stops shipping queries for metrics that do not exist. *Evidence*: F009
- **`docs/architecture/10-observability.md`** — env table and the "import the
  dashboards" instructions updated away from `:4318` / `BACKEND=prometheus`.
  *Evidence*: F012
- **`packages/ai-parrot/src/parrot/observability/examples/README.md`** — reframed
  now that metrics go to Prometheus and OpenLIT is the trace destination.
  *Evidence*: F012

### What's Untouched (Non-Goals)

- Any change to `MetricsSubscriber` instruments, labels or buckets — the emitter
  is complete and covered by 29 test modules. *Evidence*: F002, F012
- Per-user / per-session dashboards — structurally unavailable in metrics by
  design. *Evidence*: F002
- Removing the OpenLIT stack, the `OpenLitUsageRecorder`, or the
  `ai-parrot-openlit-bridge` distribution — `parrot-openlit-ui` keeps running,
  it simply stops receiving parrot data. *Evidence*: F013
- Any multi-destination export (`OTLP_TARGETS`), new collector service, or code
  change to make `enable_traces` env-settable. Explicitly ruled out by the
  requester: this is an env-variable move, not an architecture change.
  *Evidence*: F006, F014
- Alerting rules, recording rules, retention/long-term storage changes, or
  auth/TLS on the local stack.
- The `PrometheusUsageRecorder` (`OBSERVABILITY_BACKEND=prometheus`, port 9464)
  path — it stays as-is; it simply is not what this dashboard targets.
  *Evidence*: F006, F009

### Patterns to Follow

- **The Codex integration is the template.** `docker/grafana/README.md`'s Codex
  section demonstrates the full shape: an ASCII topology diagram, the exact
  producer config block, the delta-vs-cumulative caveat, a deep link to the
  dashboard, and copy-paste `curl` diagnostics for an empty dashboard.
  *Evidence*: F011
- **Provisioning, not manual import.** File-based provider, `updateIntervalSeconds: 30`,
  datasource referenced by the fixed uid `claudestats-prometheus`.
  *Evidence*: F008
- **Give the dashboard a stable `uid`.** `parrot-usage.json` currently has none,
  so a provisioned copy gets a generated uid and cannot be deep-linked.
  *Evidence*: F009

### Integration Risks

- **Delta vs cumulative temporality (the one low-confidence claim).** Prometheus
  2.51 has no delta→cumulative conversion, and the Codex README documents Codex
  breaking on exactly this path. The direct-push decision assumes OTel Python
  exports cumulative by default. *Mitigation*: verify on the first export by
  checking that counters increase monotonically rather than sawtooth; if not,
  fall back to routing parrot through a collector with `deltatocumulative`
  (the rejected U3 option, which stays available). *Evidence*: F011, F006
- **Exact series names unknown until first export.** Write the PromQL only after
  reading `__name__` values off the live TSDB. *Mitigation*: make "enumerate the
  real `gen_ai_*`/`parrot_*` series names" an explicit first task before any
  panel is authored. *Evidence*: F011, F002
- **Re-enabling telemetry may reintroduce the shutdown hang.** The `.env` comment
  records a ~10 s+ atexit flush block on CTRL+C when the endpoint was
  unreachable. Pointing at a *healthy* endpoint is precisely the documented
  precondition for re-enabling. *Mitigation*: confirm `:9090` is reachable before
  flipping the switch; verify a CTRL+C after a crew run still exits promptly.
  *Evidence*: F004

- **Trace exports would 404 if sampling is left at 1.0.** Because the endpoint
  move carries traces along with metrics (F006) and `enable_traces` is not
  env-settable (F014), omitting `OBSERVABILITY_SAMPLING=0.0` produces a failed
  trace POST per batch — log noise, retry backoff, and a slower atexit flush,
  i.e. a milder version of the very symptom that got telemetry disabled in the
  first place. *Mitigation*: set the sampling variable in the same edit; verify
  no `/v1/traces` requests appear in the Prometheus access path.
  *Evidence*: F014, F006, F004

- **Losing trace visibility is a deliberate trade.** Sampling at 0.0 means no
  per-call timelines and no per-user/session attribution anywhere — spans are
  the only carrier for `user_id`/`session_id` (F002). The running
  `parrot-openlit-ui` will simply stop receiving parrot data.
  *Mitigation*: accepted as scoped; reversible with one variable.
  *Evidence*: F002, F014
- **Dirty `docker/` tree.** Uncommitted Codex collector work sits in the same
  files this feature touches. *Mitigation*: land or stash that work first.
  *Evidence*: F011
- **No existing data to build against.** Prometheus holds zero parrot series, so
  the dashboard cannot be validated against history — a real agent run is
  required to produce the first series, and nothing appears for up to 60 s after
  it. *Evidence*: F010, F005

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | Every LLM metric already carries `parrot.agent.name`, model and provider | F002 | high | direct read of `MetricsSubscriber` handlers |
| C2 | Cost is emitted natively as a USD counter, not derived in PromQL | F003 | high | direct read of `_on_client_after` + `setup_telemetry` |
| C3 | Telemetry is currently disabled and aimed at OpenLIT, not Prometheus | F004 | high | direct read of the `[observability]` block |
| C4 | Live Prometheus holds zero `gen_ai_*`/`parrot_*` series | F010 | high | directly observed: 291 names, 0 matches, both targets healthy |
| C5 | Both example dashboards query names nothing emits; neither has a by-agent panel | F009 | high | every panel expression enumerated and compared to the catalog |
| C6 | Prometheus accepts a direct OTLP push; a collector is optional for parrot | F007 | high | `--enable-feature=otlp-write-receiver` in compose + healthy live instance |
| C7 | Moving the endpoint carries traces along with metrics, so they would 404 against Prometheus unless silenced | F006, F014 | high | inferred from exporter/setup code paths; not yet observed failing |
| C12 | `enable_traces` is not env-settable, so `OBSERVABILITY_SAMPLING=0.0` is the only env-only way to silence traces | F014 | high | direct read: field declared in the model, absent from `from_env` |
| C8 | Dropping JSON into `docker/grafana/provisioning/dashboards/` auto-loads it in 30 s | F008, F011 | high | provider config, corroborated by two working dashboards |
| C9 | The openlit→OTEL migration is complete; OpenLIT survives only as an OTLP destination | F013 | high | FEAT-462 deprecation validators + the instrumentor skip-list rationale |
| C10 | Exact Prometheus-translated series names (esp. the `USD` suffix on the cost counter) are as predicted | F011, F002 | medium | inferred from the collector's `translation_strategy`; must be verified against the live TSDB |
| C11 | OTel Python's default cumulative temporality makes direct push to Prometheus 2.51 safe without a delta→cumulative processor | F011, F006 | low | not verified in this repo, and the Codex README documents delta metrics breaking this exact path |

Distribution: **10** high, **1** medium, **1** low.

> C11 is low and is load-bearing for the chosen transport (U3). It is mitigated
> rather than resolved: the collector path stays available as a documented
> fallback, and the spec should carry an explicit verification step for it.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **U1 — Once metrics point at Prometheus, where should traces go?**
  *Resolved* (revised by the requester after the first pass): **nowhere — this is
  a straight move of the existing env variables from OpenLIT to Prometheus.** No
  `OTLP_TARGETS` split, no second destination, no collector. Because
  `enable_traces` is not env-settable (F014), traces are silenced within the same
  env move by `OBSERVABILITY_SAMPLING=0.0`, which stops any span from reaching an
  exporter. Reversible with one variable if traces are wanted again later.
  *Resolves claims*: C7, C12

- [x] **U2 — Which artifact is "the example grafana dashboard" to update?**
  *Resolved*: Both. Author one correct dashboard provisioned into
  `docker/grafana/provisioning/dashboards/` so it auto-loads on the running
  Grafana, **and** replace the two stale package-example files with the same
  JSON so the package stops advertising non-existent metrics.
  *Resolves claims*: C5, C8

- [x] **U3 — Direct OTLP push, or route parrot through an OTel Collector?**
  *Resolved*: Direct OTLP push to
  `http://localhost:9090/api/v1/otlp`. No new container. The collector path
  remains the documented fallback if C11 fails in practice.
  *Resolves claims*: C10, C11

- [x] **U4 — Where should the parrot dashboard appear in Grafana?**
  *Resolved*: A new `AI-Parrot` folder — add a second provider entry in
  `dashboards.yml` pointing at a `parrot/` subdirectory with `folder: AI-Parrot`,
  leaving the two existing dashboards in `Claude Code` untouched.
  *Resolves claims*: C8

- [x] **U5 — Should this feature add a committed, secret-free reference for the
  `[observability]` block, given `env/.env` is git-ignored?**
  *Resolved*: Both — a committed secret-free example env file **and** the
  matching block in `docs/architecture/10-observability.md`, cross-referencing
  each other.

### Unresolved (defer to spec / implementation)

- [ ] **What are the real Prometheus series names after the first export?**
  *Owner*: implementation (first task)
  *Blocks claims*: C10
  *Plausible answers*: a) `gen_ai_client_cost_total_USD_total` ·
  b) `gen_ai_client_cost_total_usd_total` · c) unit suffix dropped entirely.
  Must be read off `/api/v1/label/__name__/values`, never assumed.

- [ ] **Does the direct push actually deliver cumulative counters?**
  *Owner*: implementation (verification step)
  *Blocks claims*: C11
  *Plausible answers*: a) yes — OTel Python defaults to cumulative, dashboard
  works as designed · b) no — counters sawtooth, requiring the collector fallback.

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-548`** — *Rationale*: localization is high-confidence and
complete (C1–C6, C8, C9), the emitter needs no change, and all five
configuration forks have been resolved. What remains is exactly what a spec
formalizes: concrete acceptance criteria for the wiring, the panel inventory,
and the two verification steps that close C10 and C11.

### Alternatives

- **`/sdd-brainstorm FEAT-548`** — not needed; the architectural forks
  (direct push vs collector, trace destination, dashboard placement) were
  enumerated in §3 and resolved in §5.
- **`/sdd-task FEAT-548`** — not suitable. Despite "no instrumentation work",
  this spans an operator action, two docker directories, two package example
  files and two docs — more than one logical commit.
- **Manual review** — not required; research completed within budget with no
  truncation.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-548/state.json` |
| Source | `sdd/state/FEAT-548/source.md` |
| Research plan | `sdd/state/FEAT-548/research_plan.json` |
| Findings (14) | `sdd/state/FEAT-548/findings/F001…F014` |
| Synthesis | `sdd/state/FEAT-548/synthesis.json` |

**Budget**: `default` profile — completed without truncation.
Wiki available (35 036 pages / 20 932 symbols); wiki orientation queries were
run off-budget alongside the planned grep/glob/read/git_log/tree queries.

**Findings index**:

| ID | Title |
|----|-------|
| F001 | The OTEL observability layer lives in core `parrot.observability` |
| F002 | The complete emitted metric catalog and its label sets |
| F003 | Cost is computed in-process and emitted as a USD counter |
| F004 | `env/.env` has an `[observability]` block that is switched OFF and aimed at OpenLIT |
| F005 | `ObservabilityConfig.from_env()` is the authoritative env-var contract |
| F006 | Metrics are PUSHed to exactly one OTLP endpoint; traces can fan out to many |
| F007 | The running observability stack: four containers, one `parrot-metrics` network |
| F008 | Dropping a JSON file into `docker/grafana/provisioning/dashboards/` auto-loads it |
| F009 | Both example dashboards query metric names that NOTHING in the codebase emits |
| F010 | Live Prometheus holds ZERO `gen_ai_*`/`parrot_*` series today |
| F011 | The Codex dashboard is a working precedent — with uncommitted changes still in the tree |
| F012 | Docs and a 29-file unit test suite already pin this surface |
| F013 | The openlit→OTEL migration is complete; OpenLIT survives as an optional OTLP destination |
| F014 | `enable_traces` is NOT env-settable; `OBSERVABILITY_SAMPLING=0.0` is the env-only way to silence traces |

**Related prior specs** (background for the spec author): FEAT-177
`otel-observability`, FEAT-228 `per-agent-cost-usage-metrics` (put
`parrot.agent.name` on metrics), FEAT-397 `tokens-observability` (per-round
instruments), FEAT-462 `unified-telemetry-bus` (multi-target OTLP, openlit
deprecation).
