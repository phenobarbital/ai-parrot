---
id: F008
query_id: Q010
type: tree
intent: Inspect the Grafana provisioning tree (datasources + dashboard providers) on the running stack
executed_at: 2026-09-10T16:17:00Z
parent_id: F007
depth: 1
---

# F008 — Dropping a JSON file into `docker/grafana/provisioning/dashboards/` auto-loads it

## Summary

Grafana provisioning is file-based and already proven twice. The provider scans
`/etc/grafana/provisioning/dashboards` every 30 s with
`foldersFromFilesStructure: false`, so any `*.json` dashboard added to
`docker/grafana/provisioning/dashboards/` appears automatically in the
`Claude Code` folder without a Grafana restart. The Prometheus datasource is
provisioned with the fixed uid `claudestats-prometheus` — a new dashboard must
reference that uid (or use the default datasource) to resolve.

Provisioned dashboards are read-only in the UI (`allowUiUpdates: false`); a user
must "Save as" to get an editable copy.

## Citations

- path: `docker/grafana/provisioning/dashboards/dashboards.yml`
  lines: 1-16
  excerpt: |
    providers:
      - name: claudestats
        folder: Claude Code
        type: file
        allowUiUpdates: false
        updateIntervalSeconds: 30
        options:
          path: /etc/grafana/provisioning/dashboards
          foldersFromFilesStructure: false

- path: `docker/grafana/provisioning/datasources/prometheus.yml`
  lines: 1-14
  excerpt: |
    datasources:
      - name: Prometheus
        type: prometheus
        uid: claudestats-prometheus
        access: proxy
        url: http://prometheus:9090
        isDefault: true

- path: `docker/grafana/provisioning/dashboards/claude-code-metrics.json`
- path: `docker/grafana/provisioning/dashboards/codex-overview.json`

## Notes

The folder is literally named `Claude Code` and the provider `claudestats` —
adding a parrot dashboard under that provider would file it in a misleadingly
named folder. Either a second provider entry (folder `AI-Parrot`) or
`foldersFromFilesStructure: true` with subdirectories is needed.
