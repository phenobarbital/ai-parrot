# SurrealDB G1 Spike Harness

This directory contains the harness for the FEAT-824 Phase 1 spike (G1) to evaluate SurrealDB 3.3.x and its Python SDK.

## Prerequisites

- Docker
- `uv` (Python package installer)

## Starting the Server

Run the pinned SurrealDB server:

```bash
docker compose up -d
```

The server will be available at `http://localhost:8000` with credentials `root`/`root`.

## Running the Harness

Install the pinned SDK and run the harness:

```bash
uv run --no-project --with surrealdb==<pin> --with pydantic python scripts/spikes/surrealdb_g1/harness.py \
  --url http://localhost:8000 \
  --username root \
  --password root \
  --server-image surrealdb/surrealdb@sha256:<digest> \
  --sdk-version <pin> \
  --report sdd/state/FEAT-824/g1/report.md
```

Replace `<pin>` with the SDK version and `<digest>` with the server image digest.

## Fallbacks

- If the SDK is unavailable, use HTTP `/sql` endpoint directly.
- If the server image cannot be pulled, use a local build or a different tag.

## Reading the Verdict

The report at `sdd/state/FEAT-824/g1/report.md` will contain a final line:

- **Verdict: GO** — all blocking checks passed.
- **Verdict: NO-GO** — at least one blocking check failed.
