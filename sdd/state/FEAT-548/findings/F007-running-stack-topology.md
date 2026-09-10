---
id: F007
query_id: Q011
type: read
intent: Read the prometheus/grafana docker-compose to learn container names, network, ports and OTLP receiver flags
executed_at: 2026-09-10T16:16:00Z
parent_id: null
depth: 0
---

# F007 — The running observability stack: four containers, one `parrot-metrics` network

## Summary

`docker ps` confirms all four relevant containers are up. Prometheus runs 2.51.0
with `--enable-feature=otlp-write-receiver` and 90 d retention, so it accepts an
OTLP **push** at `http://localhost:9090/api/v1/otlp/v1/metrics` with no collector
in front. Grafana is on loopback 3001 (3000 is taken by the OpenLIT UI) and joins
the externally-owned `parrot-metrics` network, reaching Prometheus as
`http://prometheus:9090`. `parrot-codex-otel` is a Codex-dedicated collector
(loopback 4328 → 4318) whose Prometheus exporter on `:8889` is scraped under the
`codex` job. OpenLIT owns 4317-4318 on all interfaces.

| Container | Image | Published | Role |
|---|---|---|---|
| `parrot-prometheus` | prom/prometheus:v2.51.0 | 0.0.0.0:9090 | TSDB + OTLP write receiver |
| `parrot-grafana` | parrot-grafana (local build) | 127.0.0.1:3001→3000 | dashboards |
| `parrot-codex-otel` | otel-collector-contrib:0.148.0 | 127.0.0.1:4328→4318 | Codex delta→cumulative |
| `parrot-openlit-ui` | ghcr.io/openlit/openlit | 0.0.0.0:3000, 4317-4318 | trace explorer (ClickHouse-backed) |

## Citations

- path: `docker/prometheus/docker-compose.yml`
  lines: 1-60
  excerpt: |
    name: parrot-prometheus
    services:
      otel-collector:
        image: otel/opentelemetry-collector-contrib:0.148.0
        container_name: parrot-codex-otel
        ports: ["127.0.0.1:4328:4318"]
      prometheus:
        image: prom/prometheus:v2.51.0
        container_name: parrot-prometheus
        ports: ["9090:9090"]
        command:
          - "--storage.tsdb.retention.time=90d"
          - "--enable-feature=otlp-write-receiver"
        extra_hosts: ["host.docker.internal:host-gateway"]
    networks:
      parrot-metrics:
        name: parrot-metrics

- path: `docker/grafana/docker-compose.yml`
  lines: 1-40
  excerpt: |
    container_name: parrot-grafana
    ports: ["127.0.0.1:3001:3000"]
    volumes:
      - ./provisioning/datasources:/etc/grafana/provisioning/datasources:ro
      - ./provisioning/dashboards:/etc/grafana/provisioning/dashboards:ro
    networks:
      parrot-metrics:
        external: true

- path: `docker/prometheus/prometheus.yml`
  lines: 1-28
  excerpt: |
    # Claude Code metrics are PUSHED here over OTLP (--enable-feature=
    # otlp-write-receiver), so they need no scrape job.
    scrape_configs:
      - job_name: "prometheus"
      - job_name: "codex"
        static_configs:
          - targets: ["otel-collector:8889"]
      # - job_name: "openlit"   # commented out — OpenLIT's 4318 is an OTLP
      #                         # receiver, not a /metrics endpoint

## Notes

`prometheus.yml` already records the lesson that OpenLIT's 4318 is a receiver
and not scrapeable — the previously attempted `openlit` scrape job is commented
out as dead. `extra_hosts: host.docker.internal:host-gateway` is already present,
so a container-side scrape of a host process is possible if ever needed.
