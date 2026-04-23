# Storage Backends Guide

## Overview

AI-Parrot persists chat history, conversation threads, and artifacts through a pluggable
`parrot.storage.backends.base.ConversationBackend` ABC. Four backends ship in v1:
**SQLite**, **PostgreSQL**, **MongoDB**, and **DynamoDB**. Large artifact definitions
(>200 KB) overflow to a separate `parrot.storage.overflow.OverflowStore` backed by any
`FileManagerInterface` (S3, GCS, local filesystem, or temp dir).

The backend is selected once at startup via the `PARROT_STORAGE_BACKEND` environment
variable. There is no runtime auto-switching — changing the backend requires a restart.

---

## Backend Selection Matrix

| `PARROT_STORAGE_BACKEND` | Typical environment | Persistence | Required config | Default overflow |
|---|---|---|---|---|
| `sqlite` *(default)* | Laptop / CI / no-docker | Single-file local DB | `PARROT_SQLITE_PATH` | `local` |
| `dynamodb` | AWS production | DynamoDB + S3 | `DYNAMODB_*` + `AWS_*` | `s3` |
| `postgres` | GCP / shared dev | Postgres JSONB | `PARROT_POSTGRES_DSN` | `local` or `PARROT_OVERFLOW_STORE` |
| `mongodb` | Mongo / DocumentDB | MongoDB BSON | `PARROT_MONGODB_DSN` | `local` or `PARROT_OVERFLOW_STORE` |

**Important**: Unknown values for `PARROT_STORAGE_BACKEND` raise `ValueError` at startup
(fail-fast, no silent fallback).

---

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `PARROT_STORAGE_BACKEND` | Active backend: `sqlite`, `dynamodb`, `postgres`, `mongodb` | `sqlite` |
| `PARROT_SQLITE_PATH` | Path to SQLite database file | `~/.parrot/parrot.db` |
| `PARROT_POSTGRES_DSN` | PostgreSQL connection string | *(unset; required for postgres)* |
| `PARROT_MONGODB_DSN` | MongoDB connection string | *(unset; required for mongodb)* |
| `PARROT_OVERFLOW_STORE` | Overflow file manager: `s3`, `gcs`, `local`, `tmp` | `s3` if dynamodb else `local` |
| `PARROT_OVERFLOW_LOCAL_PATH` | Base path for `local` overflow | `~/.parrot/artifacts` |
| `PARROT_STORAGE_METRICS` | `module:attribute` path to a `StorageMetrics` instance | *(unset; no instrumentation)* |
| `DYNAMODB_CONVERSATIONS_TABLE` | DynamoDB conversations table name | `parrot-conversations` |
| `DYNAMODB_ARTIFACTS_TABLE` | DynamoDB artifacts table name | `parrot-artifacts` |
| `DYNAMODB_REGION` | AWS region for DynamoDB | `AWS_REGION_NAME` |
| `DYNAMODB_ENDPOINT_URL` | Override DynamoDB endpoint (DynamoDB Local) | `None` |

---

## Quickstart

### Data-analyst laptop (SQLite, no Docker)

`sqlite` is the default — no configuration needed:

```bash
# Just run; ~/.parrot/parrot.db is created automatically
python -m parrot.server
```

To use a custom path:

```bash
export PARROT_SQLITE_PATH=/data/my_parrot.db
```

### AWS production (DynamoDB)

```bash
export PARROT_STORAGE_BACKEND=dynamodb
export DYNAMODB_CONVERSATIONS_TABLE=parrot-conversations
export DYNAMODB_ARTIFACTS_TABLE=parrot-artifacts
export DYNAMODB_REGION=us-east-1
export AWS_ACCESS_KEY=<key>
export AWS_SECRET_KEY=<secret>
# Overflow to S3 (default when dynamodb backend)
export AWS_BUCKET=my-artifact-bucket
```

Tables must be pre-provisioned (PAY_PER_REQUEST) with `PK` (hash) + `SK` (range) keys.

### GCP production (Postgres)

```bash
export PARROT_STORAGE_BACKEND=postgres
export PARROT_POSTGRES_DSN=postgresql://parrot:secret@10.0.0.5:5432/parrot
export PARROT_OVERFLOW_STORE=gcs
# Tables are auto-created on first initialize()
```

---

## DynamoDB Local via docker-compose

For local development that mimics AWS DynamoDB:

```yaml
# docker-compose.dynamodb-local.yml
services:
  dynamodb-local:
    image: amazon/dynamodb-local:latest
    container_name: parrot-dynamodb-local
    command: ["-jar", "DynamoDBLocal.jar", "-sharedDb", "-dbPath", "/home/dynamodblocal/data"]
    ports:
      - "8000:8000"
    volumes:
      - dynamodb_data:/home/dynamodblocal/data
    working_dir: /home/dynamodblocal
    user: "1000"

volumes:
  dynamodb_data:
```

**Persistence requires BOTH the `-sharedDb` flag AND the volume mount.**
Without either, data is lost on container restart.

App configuration:

```bash
export PARROT_STORAGE_BACKEND=dynamodb
export DYNAMODB_ENDPOINT_URL=http://localhost:8000
export AWS_ACCESS_KEY=dummy
export AWS_SECRET_KEY=dummy
export DYNAMODB_REGION=us-east-1
```

Create tables with the AWS CLI:

```bash
aws dynamodb create-table \
  --table-name parrot-conversations \
  --attribute-definitions AttributeName=PK,AttributeType=S AttributeName=SK,AttributeType=S \
  --key-schema AttributeName=PK,KeyType=HASH AttributeName=SK,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST \
  --endpoint-url http://localhost:8000
```

---

## Overflow Storage

Artifact `definition` payloads larger than **200 KB** are offloaded to an
`parrot.storage.overflow.OverflowStore` backed by a `FileManagerInterface`.

| `PARROT_OVERFLOW_STORE` | FileManagerInterface | Notes |
|---|---|---|
| `s3` | `parrot.interfaces.file.s3.S3FileManager` | Default for dynamodb backend |
| `gcs` | `parrot.interfaces.file.gcs.GCSFileManager` | For GCP deployments |
| `local` | `parrot.interfaces.file.local.LocalFileManager` | Default for non-DynamoDB backends |
| `tmp` | `parrot.interfaces.file.tmp.TempFileManager` | Ephemeral; data lost on restart |

Example — force local overflow:

```bash
export PARROT_OVERFLOW_STORE=local
export PARROT_OVERFLOW_LOCAL_PATH=/data/parrot-artifacts
```

---

## Migration Notes

**v1 does NOT provide cross-backend migration tooling.** Each backend is an independent
persistent store. Switching `PARROT_STORAGE_BACKEND` starts fresh — existing data in
the old backend is not migrated automatically. A future feature will add migration tools
when a customer requests it.

---

## Observability

Add per-method latency and error metrics by setting `PARROT_STORAGE_METRICS` to a
`module:attribute` path pointing at a `parrot.storage.metrics.StorageMetrics` instance.

The factory wraps the selected backend in
`parrot.storage.instrumented.InstrumentedBackend` at startup, calling
`record_latency(backend_name, method, duration_ms)` and
`record_error(backend_name, method, error_type)` around every operation.

### Prometheus adapter example

```python
# example_prometheus_metrics.py
from prometheus_client import Histogram, Counter

LATENCY = Histogram(
    "parrot_storage_latency_ms", "Storage latency", ["backend", "method"]
)
ERRORS = Counter(
    "parrot_storage_errors_total", "Storage errors", ["backend", "method", "error_type"]
)


class PrometheusStorageMetrics:
    def record_latency(self, backend, method, duration_ms):
        LATENCY.labels(backend=backend, method=method).observe(duration_ms)

    def record_error(self, backend, method, error_type):
        ERRORS.labels(backend=backend, method=method, error_type=error_type).inc()


metrics = PrometheusStorageMetrics()
```

```bash
export PARROT_STORAGE_METRICS=example_prometheus_metrics:metrics
```

---

## Known Limitations

- **SQLite is single-writer.** Not suitable for multi-process deployments. For
  multi-worker local setups, use Postgres via Docker.
- **MongoDB TTL reaper runs once per minute.** Do not assert instant expiry in tests.
- **No built-in backend-switching or data migration.** Changing backend requires restart
  and starts with an empty store.
- **MinIO is not supported as overflow.** Use `gcs` or `local` instead.

---

## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| `ValueError: Unknown PARROT_STORAGE_BACKEND='foo'` | Typo or unsupported backend | Set to one of: `sqlite`, `postgres`, `mongodb`, `dynamodb` |
| `RuntimeError: PARROT_POSTGRES_DSN is required for postgres backend` | DSN not configured | `export PARROT_POSTGRES_DSN=postgresql://...` |
| `RuntimeError: PARROT_MONGODB_DSN is required for mongodb backend` | DSN not configured | `export PARROT_MONGODB_DSN=mongodb://...` |
| DynamoDB Local loses data on restart | Missing `-sharedDb` or volume | Ensure both `-sharedDb` flag AND the volume mount are present in docker-compose |
| `RuntimeError: Failed to import metrics from '...'` | Bad `PARROT_STORAGE_METRICS` path | Check the `module:attribute` format and that the module is importable |
