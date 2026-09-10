---
id: F011
query_id: Q015
type: git_log
intent: Check git history of the docker prometheus/grafana stack to see what it was built for, and what is uncommitted
executed_at: 2026-09-10T16:20:00Z
parent_id: F007
depth: 1
---

# F011 — The Codex dashboard landed days ago and is a working precedent — with uncommitted changes still in the tree

## Summary

The stack is recent and actively evolving: `dc0decca2 codex grafana dashboard`
and `2b2aa9f29 wip: provisioning observability` are the two most recent commits
touching `docker/`. The working tree is currently **dirty in exactly this area**:
`docker/grafana/README.md`, `docker/prometheus/docker-compose.yml` and
`docker/prometheus/prometheus.yml` are modified, and
`docker/prometheus/otel-collector.yml` is untracked. Those uncommitted changes
are what introduced the `parrot-codex-otel` collector and its `codex` scrape job.

The Codex integration is a complete, documented, end-to-end template for what
this feature needs to do for parrot: a collector decision, a scrape/push
decision, a provisioned dashboard JSON, a README section, and explicit
diagnostic `curl` commands for an empty dashboard.

## Citations

- path: `docker/grafana/README.md`
  lines: 45-105 (uncommitted addition)
  excerpt: |
    ## Codex side
    Codex --OTLP/http--> collector --scrape :8889--> Prometheus <--query-- Grafana
             :4328       delta to cumulative          :9090              :3001
    ...
    Codex 0.154.0 was observed emitting **delta** sums and histograms. Do not point
    it directly at the Prometheus 2.51 OTLP receiver: this stack needs the
    delta-to-cumulative processor.
    ...
    curl -fsSG http://localhost:9090/api/v1/query --data-urlencode 'query=count by (__name__) ({__name__=~"codex_.*"})'

- path: `docker/prometheus/otel-collector.yml`
  lines: 1-31 (untracked)
  excerpt: |
    processors:
      deltatocumulative:
        max_stale: 1h
        max_streams: 50000
    exporters:
      prometheus:
        endpoint: 0.0.0.0:8889
        translation_strategy: UnderscoreEscapingWithSuffixes
        resource_to_telemetry_conversion:
          enabled: true

- path: `docker/prometheus/docker-compose.yml`
  lines: 20-30 (uncommitted addition)

## Notes

`translation_strategy: UnderscoreEscapingWithSuffixes` in the collector config
is the concrete evidence for how dotted OTel names become Prometheus names on
this host — dots to underscores, plus unit/`_total` suffixes. The Prometheus
2.51 OTLP write receiver applies the equivalent translation on the direct-push
path. This is the naming rule any new PromQL must be written against.
