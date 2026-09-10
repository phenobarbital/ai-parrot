# AI-Parrot Observability — Quickstart Examples

> WARNING: DO NOT deploy the provided compose file to production as-is.
> It has no authentication, no TLS, and no volume persistence tuning.

This directory contains a self-contained developer stack that lets you see
AI-Parrot **traces** in under 5 minutes via OpenLIT. **Metrics go to the
separate Prometheus + Grafana stack at the repo root** (`docker/prometheus/`,
`docker/grafana/`) — see step 1 below and `docker/grafana/README.md`. OpenLIT
is a plain OTLP trace destination (FEAT-462), not a metrics backend; the two
stacks are independent and both optional.

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

Wait 15-20 seconds for OpenLIT to finish initialising its ClickHouse schema.

Prometheus is no longer part of this stack — it moved to `docker/prometheus/`
at the repo root (with every other docker artifact) and is now shared with the
Grafana stack in `docker/grafana/`:

```bash
docker compose -f docker/prometheus/docker-compose.yml up -d   # http://localhost:9090
```

---

## 2. Run the demo script

```bash
# Optional: set your OpenAI key
export OPENAI_API_KEY="sk-..."
export OPENAI_BASE_URL="https://api.openai.com/v1"   # or your local server

python basic_telemetry.py
```

The script:
1. Calls `setup_telemetry()` pointed at the local OpenLIT collector via
   `otlp_endpoint` (FEAT-462: OpenLIT is a plain OTLP destination, not an
   SDK flag).
2. Sends 3 chat completions (or synthetic spans if `openai` is not installed).
3. Calls `shutdown_telemetry()` to flush all data before exiting.

---

## 3. View traces

Open **http://localhost:3000** in your browser.

- Navigate to **Requests** to see per-call trace timelines.
- Navigate to **Metrics** to see token counts, latency, and cost.

---

## 4. Load the Grafana dashboard (optional)

This needs the separate Prometheus + Grafana stack (step 1's note above), with
`env/.env`'s `[observability]` block pointed at Prometheus's OTLP write
receiver — see `docker/grafana/README.md` for the exact config and topology.
Once `docker/grafana/docker-compose.yml` is up, the **AI-Parrot — LLM Usage &
Cost** dashboard is provisioned automatically into Grafana's **AI-Parrot**
folder — no manual import needed. Open it at
<http://localhost:3001/d/parrot-usage-cost/>.

A byte-identical copy ships in this directory,
[`grafana-dashboards/parrot-usage-cost.json`](grafana-dashboards/parrot-usage-cost.json),
for reference or manual import elsewhere.

The dashboard shows:
- Total cost, requests, tokens, and requests without a matched cost (unpriced
  models made visible, not silently dropped)
- Cost rate, tokens/s, and cumulative cost **by agent** — the dimension no
  earlier dashboard here ever had, despite `parrot.agent.name` being on every
  LLM metric since FEAT-228
- Cost rate, tokens/s, and cumulative cost by model + provider
- Request rate by agent and p50/p95 latency

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
