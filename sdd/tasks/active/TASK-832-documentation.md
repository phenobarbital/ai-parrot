# TASK-832: Documentation — Storage Backends Guide

**Feature**: FEAT-116 — Pluggable Storage Backends for Conversations & Artifacts
**Spec**: `sdd/specs/dynamodb-fallback-redis.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-822, TASK-823, TASK-824, TASK-826, TASK-827, TASK-828, TASK-829, TASK-830, TASK-831
**Assigned-to**: unassigned

---

## Context

End-user-facing documentation for the new pluggable storage system. Without
this, the feature is not discoverable: engineers won't know `PARROT_STORAGE_BACKEND`
exists, how to switch backends, or that a DynamoDB Local `docker-compose.yml`
is a supported option.

Implements **Module 9** of the spec (§3). Runs last because it needs the
final config names and class names from TASK-829 / TASK-831.

---

## Scope

Create `docs/storage-backends.md` with these sections:

1. **Overview** (≤ 8 lines). What the layer does; the four supported backends; two-table logical model (threads/turns + artifacts) + pluggable overflow.
2. **Backend Selection Matrix** (table). One row per backend; columns: `PARROT_STORAGE_BACKEND` value, typical environment, persistence guarantees, required config, recommended overflow.
3. **Environment Variables** (table). Every new `PARROT_*` var from `parrot/conf.py` (see TASK-829 and TASK-831) with a one-line description and default.
4. **Quickstart** — three blocks, copy-pasteable:
   - *Data-analyst laptop (SQLite, no Docker)*: just run — `PARROT_STORAGE_BACKEND=sqlite` is the default.
   - *AWS production (DynamoDB)*: required env vars, link to DynamoDB table provisioning via infrastructure-as-code.
   - *GCP production (Postgres)*: required env vars, minimal `CREATE DATABASE` step.
5. **DynamoDB Local via docker-compose** — complete, working `docker-compose.yml` with `-sharedDb` flag AND a volume mount for `/home/dynamodblocal/data` so data survives container restarts. Plus the env vars to point the app at it (`DYNAMODB_ENDPOINT_URL=http://localhost:8000`).
6. **Overflow Storage** — explain when overflow happens (>200 KB inline artifact definitions) and how `PARROT_OVERFLOW_STORE` selects among S3 / GCS / local filesystem / temp dir. Include one example each.
7. **Migration Notes** — brief: "v1 does NOT provide cross-backend migration tooling. Each backend is a separate persistent store. Switching backends in place is not supported." Link to the open question in the spec for visibility.
8. **Observability** — show how to plug in a `StorageMetrics` object via `PARROT_STORAGE_METRICS="mymodule:metrics"` and give a ~10-line Prometheus adapter example. Reference TASK-831's `StorageMetrics` protocol.
9. **Known Limitations** — one-liners:
   - SQLite is single-writer; not suitable for multi-process deployments.
   - Mongo TTL reaper runs once per minute.
   - No built-in backend-switching or data migration.
   - MinIO not supported as overflow (explicitly rejected — use GCS or LocalFileManager).
10. **Troubleshooting** — three common errors and their fixes:
    - `ValueError: Unknown PARROT_STORAGE_BACKEND` → list valid values.
    - `RuntimeError: PARROT_POSTGRES_DSN is required for postgres backend` → set the DSN.
    - DynamoDB Local loses data on restart → check `-sharedDb` flag and volume mount.

Additionally:
- Link the new doc from `README.md` or wherever the project's doc index lives (scan for it; do not create a new index file if none exists — ask in the Completion Note instead).
- Link the new doc from a comment in `parrot/storage/__init__.py` so code readers find it.

**NOT in scope**: Architecture-level documentation (the spec itself is the canonical source). Performance benchmarks. MinIO instructions (explicitly rejected). GCP Cloud Memorystore / any managed-service-specific setup.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/storage-backends.md` | CREATE | User-facing guide per Scope |
| `packages/ai-parrot/src/parrot/storage/__init__.py` | MODIFY | Add one-line module docstring comment pointing to `docs/storage-backends.md` |
| Project doc index (if it exists) | MODIFY (conditional) | Link the new doc |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports / References

Nothing is imported by the doc itself. But the doc references concrete names that MUST match the codebase as of task completion:

```
Classes (all will exist after prior tasks):
  parrot.storage.ConversationBackend
  parrot.storage.backends.dynamodb.ConversationDynamoDB
  parrot.storage.backends.sqlite.ConversationSQLiteBackend
  parrot.storage.backends.postgres.ConversationPostgresBackend
  parrot.storage.backends.mongodb.ConversationMongoBackend
  parrot.storage.overflow.OverflowStore
  parrot.storage.s3_overflow.S3OverflowManager      # back-compat subclass
  parrot.storage.metrics.StorageMetrics             # Protocol (from TASK-831)
  parrot.storage.metrics.NoopStorageMetrics
  parrot.storage.instrumented.InstrumentedBackend

FileManagerInterface implementations:
  parrot.interfaces.file.s3.S3FileManager           # parrot/interfaces/file/s3.py:15
  parrot.interfaces.file.gcs.GCSFileManager         # parrot/interfaces/file/gcs.py:16
  parrot.interfaces.file.local.LocalFileManager     # parrot/interfaces/file/local.py:13
  parrot.interfaces.file.tmp.TempFileManager        # parrot/interfaces/file/tmp.py:15

Config (from parrot/conf.py):
  PARROT_STORAGE_BACKEND          default: sqlite
  PARROT_SQLITE_PATH              default: ~/.parrot/parrot.db
  PARROT_POSTGRES_DSN             default: (unset; required for postgres)
  PARROT_MONGODB_DSN              default: (unset; required for mongodb)
  PARROT_OVERFLOW_STORE           default: s3 if dynamodb else local
  PARROT_OVERFLOW_LOCAL_PATH      default: ~/.parrot/artifacts
  PARROT_STORAGE_METRICS          default: (unset; no instrumentation)
  DYNAMODB_CONVERSATIONS_TABLE    default: parrot-conversations
  DYNAMODB_ARTIFACTS_TABLE        default: parrot-artifacts
  DYNAMODB_REGION                 default: (AWS_REGION_NAME)
  DYNAMODB_ENDPOINT_URL           default: None (set to http://localhost:8000 for DynamoDB Local)
```

Before writing, VERIFY each name exists via `grep` or `read`. If any name has drifted during implementation, update the doc accordingly.

### Does NOT Exist — Do Not Document

- ~~MinIO as an overflow option~~ — explicitly rejected.
- ~~Filesystem JSON-per-file backend~~ — rejected (SQLite dominates it).
- ~~Automatic backend-switching / failover~~ — the spec rejects this explicitly.
- ~~A migration tool `parrot storage migrate`~~ — not in v1.
- ~~CosmosDB, Firestore, Cassandra~~ — not in scope.

---

## Implementation Notes

### DynamoDB Local docker-compose Example

Include this verbatim:

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

Plus the env snippet:

```bash
export PARROT_STORAGE_BACKEND=dynamodb
export DYNAMODB_ENDPOINT_URL=http://localhost:8000
export AWS_ACCESS_KEY=dummy
export AWS_SECRET_KEY=dummy
export DYNAMODB_REGION=us-east-1
```

Note in the doc: **persistence requires BOTH the `-sharedDb` flag AND the volume mount**. Without either, data is lost on container restart.

### Observability Adapter Example

```python
# example_prometheus_metrics.py
from prometheus_client import Histogram, Counter

LATENCY = Histogram("parrot_storage_latency_ms", "Storage latency", ["backend", "method"])
ERRORS = Counter("parrot_storage_errors_total", "Storage errors", ["backend", "method", "error_type"])


class PrometheusStorageMetrics:
    def record_latency(self, backend, method, duration_ms):
        LATENCY.labels(backend=backend, method=method).observe(duration_ms)

    def record_error(self, backend, method, error_type):
        ERRORS.labels(backend=backend, method=method, error_type=error_type).inc()


metrics = PrometheusStorageMetrics()
```

Then: `export PARROT_STORAGE_METRICS=example_prometheus_metrics:metrics`.

### Style

- Use CommonMark + tables; no HTML.
- Keep sections short. Headings `##` for sections, `###` for subsections.
- Every env var in monospace. Every class name in monospace with full import path on first mention.
- Examples must be COMPLETE and COPY-PASTEABLE.

### References in Codebase

- `parrot/storage/__init__.py` — the public entry point; a one-line doc-pointer comment here is appropriate.
- `parrot/conf.py` — config names.

---

## Acceptance Criteria

- [ ] `docs/storage-backends.md` exists and covers all 10 required sections listed in Scope.
- [ ] Every class/env var referenced in the doc exists in the codebase at task completion time (grep-verified).
- [ ] The docker-compose example uses `-sharedDb` AND mounts a volume for `/home/dynamodblocal/data`.
- [ ] The Prometheus adapter example uses the `StorageMetrics` protocol correctly (two methods, correct signatures).
- [ ] `parrot/storage/__init__.py` has a one-line comment/docstring pointing readers at `docs/storage-backends.md`.
- [ ] If the project has a doc index (e.g., `docs/README.md`, `mkdocs.yml`), the new page is linked there; otherwise the agent notes this in the Completion Note.
- [ ] Markdown lints cleanly (if the project uses a lint; otherwise a plain read-through suffices).

---

## Test Specification

Docs have no automated tests beyond:

```bash
# Verify every class name mentioned in the doc exists
grep -oE 'parrot\.[a-zA-Z_.]+\.[A-Z][a-zA-Z]+' docs/storage-backends.md | sort -u | while read ref; do
  python -c "import importlib; m, _, a = '$ref'.rpartition('.'); mod = importlib.import_module(m); getattr(mod, a)" || echo "MISSING: $ref"
done
```

Run this manually before marking the task complete.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §3 Module 9 for the full list of docs requirements.
2. **Check dependencies** — all of TASK-822 through TASK-831 should be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — grep every class name before writing.
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
5. **Draft** the doc in one pass; reference the Scope checklist.
6. **Verify** every example command / env var / class name against the codebase.
7. **Find the project doc index** via `ls docs/` and `grep -l ".md" mkdocs.yml 2>/dev/null` — link the new page appropriately.
8. **Move** this file to `sdd/tasks/completed/`.
9. **Update index** → `"done"`.
10. **Fill in the Completion Note** — mention any open question encountered (e.g. "no doc index found, doc not yet linked anywhere").

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
