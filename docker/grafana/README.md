# Claude Code → Grafana (timurdigital-claudestats-app)

Grafana + the [Claude Code Stats](https://grafana.com/grafana/plugins/timurdigital-claudestats-app/)
app plugin, reading the shared Prometheus in `docker/prometheus/`.

```
Claude Code --OTLP/http--> parrot-prometheus <--query-- Grafana (claudestats app)
              :9090/api/v1/otlp                            :3001
```

No OTel collector: Prometheus runs with `--enable-feature=otlp-write-receiver`
and accepts the OTLP push directly. Grafana is on 3001 because the OpenLIT UI
already publishes 3000.

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
