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
The original request, preserved verbatim. The full source is at
`sdd/state/FEAT-548/source.md`.

> parrot observability was recently migrated from openlit to a compatible OTEL
> opentelemetry with per-agent usage, tokens, etc, currently there are a
> prometheus (parrot-prometheus) and grafana (parrot-grafana) docker machines
> running on this server, then we can change the env/.env variables to point to
> prometheus and update the example grafana dashboard to render usage total, by
> agent, by llm model, costs, etc.

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

### Constraints and goals
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

### Recommended option / probable scope
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

### Verified code anchors (paths only — open them yourself)
env/.env
packages/ai-parrot/src/parrot/observability/config.py
packages/ai-parrot/src/parrot/observability/exporters.py
/v1/metrics
packages/ai-parrot/src/parrot/observability/setup.py
packages/ai-parrot/src/parrot/observability/subscribers/metrics.py
packages/ai-parrot/src/parrot/observability/examples/grafana-dashboards/parrot-overview.json
packages/ai-parrot/src/parrot/observability/examples/grafana-dashboards/parrot-usage.json
docker/grafana/provisioning/dashboards/dashboards.yml
docker/grafana/provisioning/datasources/prometheus.yml
docker/prometheus/docker-compose.yml
docker/prometheus/prometheus.yml
docs/architecture/10-observability.md

### Questions still open in the exploration document
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

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
