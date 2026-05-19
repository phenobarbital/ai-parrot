# AI-Parrot Observability — Quickstart Examples

> WARNING: DO NOT deploy the provided compose file to production as-is.
> It has no authentication, no TLS, and no volume persistence tuning.

This directory contains a self-contained developer stack that lets you see
AI-Parrot traces and metrics in under 5 minutes.

---

## Prerequisites

- Docker 24+ with the Compose plugin (`docker compose version`)
- Python 3.10+ with `ai-parrot[observability,observability-openlit]` installed
- (Optional) An OpenAI API key or any OpenAI-compatible local server
  (e.g. [Ollama](https://ollama.com/))

---

## 1. Start the stack

```bash
cd packages/ai-parrot/src/parrot/observability/examples

docker compose -f docker-compose.observability.yml up -d
```

Services started:

| Service       | URL                            | Purpose                          |
|---------------|--------------------------------|----------------------------------|
| OpenLIT UI    | http://localhost:3000          | Trace + metrics explorer         |
| OTLP receiver | http://localhost:4318 (HTTP)   | Receives spans from the agent    |
| OTLP gRPC     | grpc://localhost:4317          | Alternative gRPC ingestion       |
| ClickHouse    | http://localhost:8123          | OpenLIT storage backend          |
| Prometheus    | http://localhost:9090          | Optional metrics scraping        |

Wait 15-20 seconds for OpenLIT to finish initialising its ClickHouse schema.

---

## 2. Run the demo script

```bash
# Optional: set your OpenAI key
export OPENAI_API_KEY="sk-..."
export OPENAI_BASE_URL="https://api.openai.com/v1"   # or your local server

python basic_telemetry.py
```

The script:
1. Calls `setup_telemetry()` with `enable_openlit=True`.
2. Sends 3 chat completions (or synthetic spans if `openai` is not installed).
3. Calls `shutdown_telemetry()` to flush all data before exiting.

---

## 3. View traces

Open **http://localhost:3000** in your browser.

- Navigate to **Requests** to see per-call trace timelines.
- Navigate to **Metrics** to see token counts, latency, and cost.

---

## 4. Load the Grafana dashboard (optional)

If you have Grafana 10+ running with a Prometheus datasource:

1. In Grafana: **Dashboards → Import**.
2. Upload `grafana-dashboards/parrot-overview.json`.
3. Select your Prometheus datasource when prompted.

The dashboard shows:
- Token throughput by model (tokens/s)
- Cost by model (USD/hour)
- p95 latency by model (seconds)
- Error rate by model

---

## 5. Teardown

```bash
docker compose -f docker-compose.observability.yml down
```

Add `--volumes` to also delete ClickHouse data.

---

## Environment Variables

| Variable         | Default                      | Description                              |
|------------------|------------------------------|------------------------------------------|
| `OTLP_ENDPOINT`  | `http://localhost:4318`      | OTLP collector endpoint                  |
| `OPENAI_API_KEY` | `sk-demo-key`                | OpenAI API key                           |
| `OPENAI_BASE_URL`| `https://api.openai.com/v1`  | OpenAI-compatible base URL               |
| `DEMO_MODEL`     | `gpt-4o-mini`                | Model name for demo calls                |

---

## Further Reading

- [OpenLIT documentation](https://docs.openlit.io/)
- [OpenTelemetry Python SDK](https://opentelemetry-python.readthedocs.io/)
- [GenAI Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
- [Prometheus + Grafana setup](https://grafana.com/docs/grafana/latest/getting-started/get-started-grafana-prometheus/)
- [AI-Parrot observability module README](../README.md)
