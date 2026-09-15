# Claude Code → Grafana (timurdigital-claudestats-app)

Grafana + the [Claude Code Stats](https://grafana.com/grafana/plugins/timurdigital-claudestats-app/)
app plugin, reading the shared Prometheus in `docker/prometheus/`.

```
Claude Code --OTLP/http--> parrot-prometheus <--query-- Grafana (claudestats app)
              :9090/api/v1/otlp                            :3001
```

Claude Code pushes directly to Prometheus with
`--enable-feature=otlp-write-receiver`. Codex uses a collector to convert its
delta metrics to cumulative metrics before Prometheus scrapes them. Grafana is
on 3001 because the OpenLIT UI already publishes 3000.

## Run

```bash
docker compose -f docker/prometheus/docker-compose.yml up -d   # owns the parrot-metrics network
docker compose -f docker/grafana/docker-compose.yml up -d --build
```

## Claude Code side

In `~/.claude/settings.json` (already applied on this machine); restart Claude
Code afterwards — env is read at startup.

```json
{
  "env": {
    "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
    "OTEL_METRICS_EXPORTER": "otlp",
    "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:9090/api/v1/otlp",
    "OTEL_METRIC_EXPORT_INTERVAL": "30000",
    "OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE": "cumulative"
  }
}
```

`cumulative` is required: Claude Code defaults to delta temporality and
Prometheus 2.x has no delta→cumulative conversion, so delta datapoints would be
silently mis-added.

## Codex side

The shared Prometheus compose stack also starts `parrot-codex-otel`, pinned to
`otel/opentelemetry-collector-contrib:0.148.0`:

```text
Codex --OTLP/http--> collector <--scrape :8889-- Prometheus <--query-- Grafana
         :4328       delta to cumulative          :9090              :3001
```

Merge this into `~/.codex/config.toml` (do not duplicate existing TOML tables):

```toml
[otel]
environment = "local"
log_user_prompt = false

[otel.metrics_exporter.otlp-http]
endpoint = "http://localhost:4328/v1/metrics"
protocol = "binary"
```

Restart Codex after changing its configuration. Processes already configured
for this endpoint recover when the collector starts. The receiver is published
only on loopback; its Prometheus exporter is internal to `parrot-metrics`.

Codex 0.154.0 was observed emitting **delta** sums and histograms. Do not point
it directly at the Prometheus 2.51 OTLP receiver: this stack needs the
[delta-to-cumulative processor](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/v0.148.0/processor/deltatocumulativeprocessor).
It keeps accumulation state in memory, so restarting the collector resets
counters. Inactive streams expire after one hour. Prometheus `rate`/`increase`
handle counter resets but cannot recover activity lost while the receiver was
unavailable.

Open [Codex Overview](http://localhost:3001/d/codex-overview/codex-overview).
Allow at least two scrapes and new Codex activity for rate/increase panels.
HTTP API and SSE panels can remain empty when Codex uses WebSocket transport.
The `model` and `auth_mode` selectors default to All.

To diagnose an empty dashboard:

```bash
docker compose -f docker/prometheus/docker-compose.yml ps
docker logs --tail 30 parrot-codex-otel
curl -fsSG http://localhost:9090/api/v1/query --data-urlencode 'query=up{job="codex"}'
curl -fsSG http://localhost:9090/api/v1/query --data-urlencode 'query=count by (__name__) ({__name__=~"codex_.*"})'
```

`up{job="codex"}=1` confirms scraping works; actual `codex_*` series confirm
Codex has exported metrics. A dashboard alone cannot create these series.
After changing `docker/prometheus/prometheus.yml`, validate and reload it:

```bash
docker exec parrot-prometheus promtool check config /etc/prometheus/prometheus.yml
curl -fsS -X POST http://localhost:9090/-/reload
```

See the [Codex configuration reference](https://developers.openai.com/codex/config-reference/)
for metrics exporter settings.

## AI-Parrot side

```text
parrot --OTLP/http--> Prometheus <--query-- Grafana
        :9090/api/v1/otlp   :9090            :3001
```

No collector: Prometheus runs with `--enable-feature=otlp-write-receiver` and
takes the push directly. Put this in `env/.env` (full copy at
`env/.env.observability.example`):

```ini
[observability]
OBSERVABILITY_ENABLED=true
OBSERVABILITY_BACKEND=otel
OBSERVABILITY_SERVICE_NAME=parrot
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:9090/api/v1/otlp
OBSERVABILITY_SAMPLING=0.0
OBSERVABILITY_COST=True
```

The endpoint is a **base URL** — the exporter appends `/v1/metrics`. Sampling is
`0.0` because that endpoint carries both signals, Prometheus 2.x serves no
`/v1/traces`, and `enable_traces` is not settable from the environment
(`config.py:132`). Metrics export every 60 s and that interval has no env var, so
allow a minute after the first LLM call before calling the dashboard broken.

The dashboard is provisioned from a **sibling** mount,
`docker/grafana/provisioning/dashboards-parrot/` — not a subdirectory of the
`claudestats` provider's own scanned path (`provisioning/dashboards/`). A
nested layout was tried first and found, empirically, to make `claudestats`
silently claim the file and misfile it into the *Claude Code* folder instead
of *AI-Parrot*; see `dashboards.yml`'s comments.

Open [AI-Parrot — LLM Usage & Cost](http://localhost:3001/d/parrot-usage-cost/).

To diagnose an empty dashboard:

```bash
curl -fsSG http://localhost:9090/api/v1/query --data-urlencode 'query=count by (__name__) ({__name__=~"gen_ai_.*|parrot_.*"})'
docker compose -f docker/prometheus/docker-compose.yml ps
```

Real `gen_ai_*` series confirm parrot has exported. A dashboard alone cannot
create them.

## Grafana side

1. http://localhost:3001 — the `Prometheus` data source is provisioned
   (`http://prometheus:9090`, the docker DNS name of `parrot-prometheus` on the
   `parrot-metrics` network).
2. Administration → Plugins → **Claude Stats** → Enable.
3. Configuration tab → **Metric Format** = *Prometheus / OTEL Collector*.
   This path produces `claude_code_cost_usage_USD_total`, not the
   Grafana-Cloud style `claude_code_cost_usage`.

## Dashboards

Two ways to see the numbers, both already wired up:

* **Claude Stats app** — sidebar → Claude Stats. Its own pages (Team Overview,
  Cost, Tokens, Tools, Productivity); nothing to import.
* **"Claude Code Metrics"** — [grafana.com dashboard 25255](https://grafana.com/grafana/dashboards/25255-claude-code-metrics-prometheus/),
  31 panels, provisioned from `provisioning/dashboards/claude-code-metrics.json`
  into the *Claude Code* folder and bound to the `claudestats-prometheus`
  data source. It is read-only in the UI (Save as → editable copy).

  To refresh it from upstream:

  ```bash
  curl -s https://grafana.com/api/dashboards/25255/revisions/latest/download \
    | python3 -c 'import json,sys; d=json.loads(sys.stdin.read().replace("${DS_PROMETHEUS}","claudestats-prometheus")); [d.pop(k,None) for k in ("__inputs","__requires","__elements")]; d["uid"]="claude-code-metrics"; d["title"]="Claude Code Metrics"; print(json.dumps(d,indent=2))' \
    > docker/grafana/provisioning/dashboards/claude-code-metrics.json
  ```

## Verify

```bash
curl -s 'http://localhost:9090/api/v1/label/__name__/values' | grep -o 'claude_code[^"]*'
```
