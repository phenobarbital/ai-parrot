# ai-parrot-openlit-bridge

Minimal OTLP endpoint validation helper for [AI-Parrot](https://pypi.org/project/ai-parrot/)'s OpenLIT integration (FEAT-462 — Unified Telemetry Bus).

AI-Parrot no longer depends on the `openlit` Python SDK (a monkey-patching
LLM SDK instrumentor whose pinned `openai` version range conflicted with
ai-parrot's own `openai` dependency). OpenLIT is now a pure deployment-time
OTLP endpoint — configure `ObservabilityConfig.otlp_targets` (multi-endpoint
OTLP export) or `OpenLitUsageRecorder` (usage-only spans) in `ai-parrot`
itself. This package provides two small, optional helpers on top of that:

1. `validate_endpoint(url)` — an async probe that checks whether an OTLP
   collector is reachable, with zero heavy dependencies (only `aiohttp`,
   already a workspace dependency).
2. `parrot-openlit-check` — a CLI wrapper around the same probe.
3. A bundled `docker-compose.openlit.yml` to run an OpenLIT collector +
   dashboard locally.

## Installation

```bash
pip install ai-parrot-openlit-bridge
# or, via the ai-parrot extra:
pip install "ai-parrot[observability-openlit]"
```

## Usage

### Python

```python
from ai_parrot_openlit_bridge import validate_endpoint

status = await validate_endpoint("http://localhost:4318")
if status.reachable:
    print(f"OTLP collector reachable (status={status.status_code})")
else:
    print(f"Unreachable: {status.error}")
```

### CLI

```bash
parrot-openlit-check http://localhost:4318
# ✅ Endpoint reachable: http://localhost:4318
#    Status: 200
```

Exit code is `0` when reachable, `1` otherwise — suitable for health-check
scripts / CI smoke tests.

### Local OpenLIT collector

```bash
docker compose -f docker-compose.openlit.yml up -d
parrot-openlit-check http://localhost:4318
```

Then point ai-parrot at it, e.g.:

```bash
export OBSERVABILITY_ENABLED=true
export OBSERVABILITY_BACKEND=otel
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
```
