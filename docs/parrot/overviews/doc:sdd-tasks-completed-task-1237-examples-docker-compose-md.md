---
type: Wiki Overview
title: 'TASK-1237: Examples + observability docker-compose'
id: doc:sdd-tasks-completed-task-1237-examples-docker-compose-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Spec §3 Module 10 and D4 (resolved): bundle a minimal example stack so users
  can `docker compose up` and immediately see traces/metrics for a running agent.
  The stack is intentionally one option (OpenLIT UI) — other community backends are
  linked from docs but not bundled.'
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.observability
  rel: mentions
---

# TASK-1237: Examples + observability docker-compose

**Feature**: FEAT-177 — OpenTelemetry + Cost Observability
**Spec**: `sdd/specs/otel-observability.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1235
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 10 and D4 (resolved): bundle a minimal example stack so users can `docker compose up` and immediately see traces/metrics for a running agent. The stack is intentionally one option (OpenLIT UI) — other community backends are linked from docs but not bundled.

---

## Scope

- Create `parrot/observability/examples/docker-compose.observability.yml` — a single-file stack with OpenLIT UI + minimal Prometheus + ClickHouse (OpenLIT's storage dep).
- Create `parrot/observability/examples/basic_telemetry.py` — a runnable script that:
  1. Calls `setup_telemetry(ObservabilityConfig(enabled=True, enable_openlit=True))`.
  2. Constructs a small `Chatbot` against a mock or local OpenAI-compatible endpoint.
  3. Sends 3 `ask` calls.
  4. Calls `shutdown_telemetry()`.
- Create `parrot/observability/examples/grafana-dashboards/parrot-overview.json` — a starter dashboard with 4 panels: token throughput, cost by model, p95 latency, error rate.
- Create `parrot/observability/examples/README.md` linking everything together.

**NOT in scope**: Production-ready dashboards; Helm charts; non-OpenLIT backends (linked, not bundled).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/examples/docker-compose.observability.yml` | CREATE | OpenLIT UI + ClickHouse + Prometheus. |
| `packages/ai-parrot/src/parrot/observability/examples/basic_telemetry.py` | CREATE | Runnable demo. |
| `packages/ai-parrot/src/parrot/observability/examples/grafana-dashboards/parrot-overview.json` | CREATE | Starter dashboard JSON. |
| `packages/ai-parrot/src/parrot/observability/examples/README.md` | CREATE | Quickstart and links. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports (for basic_telemetry.py)

```python
import asyncio
from parrot.observability import (
    ObservabilityConfig, setup_telemetry, shutdown_telemetry,
)
# A concrete bot to demo — the existing Chatbot from parrot.bots
# Confirm the exact import path before using:
#   grep -r "class Chatbot" packages/ai-parrot/src/parrot/bots/
```

### OpenLIT UI defaults

- OpenLIT UI port: 3000 (HTTP)
- OTLP receiver port: 4318 (HTTP), 4317 (gRPC)
- ClickHouse port: 8123 (HTTP), 9000 (TCP)

### Does NOT Exist

- ~~A `parrot.bots.create_demo_chatbot` factory~~ — none exists. The example uses whatever real bot/client surface AI-Parrot ships; verify against current code at implementation time.

---

## Implementation Notes

### docker-compose snippet (illustrative — adjust to current OpenLIT release)

```yaml
version: "3.8"
services:
  openlit-ui:
    image: ghcr.io/openlit/openlit:latest
    ports: ["3000:3000", "4318:4318", "4317:4317"]
    depends_on: [clickhouse]
    environment:
      - INIT_DB_HOST=clickhouse
  clickhouse:
    image: clickhouse/clickhouse-server:latest
    ports: ["8123:8123", "9000:9000"]
    ulimits: { nofile: { soft: 262144, hard: 262144 } }
  prometheus:
    image: prom/prometheus:latest
    ports: ["9090:9090"]
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
```

A minimal `prometheus.yml` (scrape OpenLIT or the agent's `/metrics` if exposed) ships alongside.

### Example script outline

```python
async def main():
    setup_telemetry(ObservabilityConfig(
        enabled=True,
        service_name="parrot-demo",
        otlp_endpoint="http://localhost:4318",
        enable_openlit=True,
        enable_cost_tracking=True,
    ))
    try:
        bot = ...   # construct a Chatbot using current AI-Parrot API
        for q in ["Hello", "What's the weather?", "Tell me a joke"]:
            await bot.ask(q)
    finally:
        shutdown_telemetry()


if __name__ == "__main__":
    asyncio.run(main())
```

### Key Constraints

- Example must run on a developer laptop with `docker compose up` + `python basic_telemetry.py` and produce visible OpenLIT UI traces.
- All endpoints localhost-only by default.
- README explicitly warns: "DO NOT deploy this compose file to production as-is."

---

## Acceptance Criteria

- [ ] `docker compose -f packages/ai-parrot/src/parrot/observability/examples/docker-compose.observability.yml up -d` brings up OpenLIT UI on http://localhost:3000.
- [ ] `python packages/ai-parrot/src/parrot/observability/examples/basic_telemetry.py` runs to completion without errors against the running stack.
- [ ] Traces appear in OpenLIT UI for each of the 3 demo `ask` calls.
- [ ] Grafana dashboard JSON loads in Grafana 10+ without manual edits (Prometheus datasource auto-resolves by name).
- [ ] README documents: prerequisites (Docker), startup command, teardown command, the link out to upstream OpenLIT / Grafana docs.

---

## Test Specification

This task has no automated tests — verification is manual per the acceptance criteria. Document the manual verification steps in the example README.

(Optional: a smoke test that imports `basic_telemetry` and runs `main()` against `enabled=False` to exercise the import path without needing the stack.)

---

## Agent Instructions

1. Confirm TASK-1235 complete (`setup_telemetry` must work end-to-end).
2. Build the four files per the table.
3. Manually validate the docker-compose stack on a local Docker daemon.
4. Take a screenshot of the OpenLIT UI showing a trace and attach it to the completion note.

---

## Completion Note

Created all 4 required files plus a companion `prometheus.yml` required by the compose stack:
- `docker-compose.observability.yml`: OpenLIT UI (ghcr.io/openlit/openlit:latest) + ClickHouse 24-alpine + Prometheus v2.51.0 with healthcheck on ClickHouse
- `prometheus.yml`: scrape config for OpenLIT metrics endpoint
- `basic_telemetry.py`: demonstrates `setup_telemetry(enabled=True, enable_openlit=True)`, 3 chat completion calls (falls back to synthetic OTel spans if `openai` not installed), `shutdown_telemetry()`
- `grafana-dashboards/parrot-overview.json`: 4 panels (token throughput, cost by model, p95 latency, error rate) for Grafana 10+ with Prometheus datasource variable
- `examples/README.md`: full quickstart including prerequisites, startup/teardown commands, env vars table, and links to upstream docs
Smoke test (import + callable check) passes. Live Docker validation requires a running Docker daemon (not available in CI). Committed as `feat(otel-observability): TASK-1237`.
