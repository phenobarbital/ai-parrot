# Brainstorm: Planogram Compliance Handler

**Date**: 2026-03-13
**Author**: Claude
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

The planogram compliance pipeline (`PlanogramCompliance`) exists and works well as a standalone script (see `examples/pipelines/bose/planogram.py`), but there is **no HTTP handler** to expose it as a REST API. Teams need to:

1. Upload a store photo and specify a planogram configuration name.
2. Have the system fetch the full planogram config from Postgres (`troc.planograms_configurations`).
3. Run the compliance analysis asynchronously (it's CPU/GPU-heavy with YOLO + LLM calls).
4. Poll for results, including a base64-encoded rendered compliance overlay image.

**Users affected**: Frontend developers consuming the API, retail ops teams running compliance checks, integration partners.

**Why now**: The pipeline and the database schema (`troc.planograms_configurations`) are both ready. The missing piece is the HTTP handler that ties them together with async job management.

## Constraints & Requirements

- Must follow the existing handler pattern: `BaseView` subclass with `setup()` classmethod (see `VideoReelHandler`).
- Must use the existing `JobManager` (`parrot/handlers/jobs/`) for async execution — POST returns 202 + job_id, GET polls status.
- Must use `PlanogramCompliance` from `parrot/pipelines/planogram/plan.py` and `PlanogramConfig` from `parrot/pipelines/models.py`.
- Database access via `self.request.app['database']` + `asyncdb` (existing pattern from `ChatHandler`).
- Image upload via `aiohttp` multipart form-data parsing.
- Rendered overlay image returned as base64 in the JSON response (not streamed).
- Async-first — no blocking I/O in async methods.
- Optional SSE event to notify frontend of progress and final result.

---

## Options Explored

### Option A: Single Handler with JobManager (Mirror VideoReelHandler)

Follow the exact same pattern as `VideoReelHandler`: a single `PlanogramComplianceHandler(BaseView)` with POST (create job) and GET (poll result) methods.

**Flow:**
1. POST receives multipart: `image` (JPEG file) + `config_name` (string field).
2. Handler queries `troc.planograms_configurations` by `config_name` to build `PlanogramConfig`.
3. Handler calls `self.job_manager.create_job(...)` and fires `pipeline.run()` as a background task.
4. Returns 202 with `{ job_id, status: "pending" }`.
5. GET with `job_id` returns status; when completed, includes results with `rendered_image` as base64.

| Library / Tool | Purpose | Notes |
|---|---|---|
| `aiohttp` | HTTP server + multipart parsing | Already used |
| `navigator.views.BaseView` | Handler base class | Existing pattern |
| `parrot.handlers.jobs.JobManager` | Async job tracking | In-memory, existing |
| `parrot.pipelines.planogram.plan.PlanogramCompliance` | Pipeline execution | Existing |
| `parrot.pipelines.models.PlanogramConfig` | Config model | Existing |
| `asyncdb` | Postgres query for config | Existing in app |

**Existing Code to Reuse:**
- `parrot/handlers/video_reel.py` — job manager integration, multipart parsing, setup pattern
- `parrot/handlers/jobs/` — JobManager, JobStatus, Job model
- `parrot/pipelines/planogram/plan.py` — PlanogramCompliance pipeline
- `parrot/pipelines/models.py` — PlanogramConfig, EndcapGeometry
- `parrot/pipelines/table.sql` — DB schema for `troc.planograms_configurations`

**Pros:**
- Proven pattern — VideoReelHandler works identically
- Minimal new code — reuses all existing infrastructure
- Simple mental model — POST to submit, GET to poll
- Base64 image in JSON keeps the frontend simple (single response with all data)

**Cons:**
- In-memory job storage means jobs lost on server restart
- Base64 encoding increases response payload ~33% vs binary

**Effort:** Low

---

### Option B: Handler with SSE Streaming for Real-Time Progress

Same POST submission, but instead of GET polling, use Server-Sent Events (SSE) to stream progress updates as the pipeline runs each step (ROI detection → object identification → compliance check → rendering).

| Library / Tool | Purpose | Notes |
|---|---|---|
| `aiohttp` SSE | `web.StreamResponse` | Existing pattern in `stream.py` |
| All from Option A | Same | Same |

**Existing Code to Reuse:**
- `parrot/handlers/stream.py` — SSE streaming patterns
- All from Option A

**Pros:**
- Real-time progress updates (useful for long-running analyses)
- No polling overhead
- Better UX — user sees step-by-step progress

**Cons:**
- More complex frontend integration (EventSource API)
- Pipeline doesn't currently emit progress events — would need modification (doesn't require progress events, just final result)
- SSE connection management adds complexity
- Harder to resume if connection drops

**Effort:** Medium

---

### Option C: Webhook-Based with External Job Queue (RQ/Celery)

Use an external job queue (Redis Queue or Celery) instead of in-memory `JobManager`. Pipeline result is posted to a webhook URL or stored in Redis for retrieval.

| Library / Tool | Purpose | Notes |
|---|---|---|
| `rq` or `celery` | External job queue | New dependency |
| `redis` | Job result storage | May already be available |
| All from Option A | Same | Same |

**Existing Code to Reuse:**
- `parrot/handlers/jobs/worker.py` — has RQ worker configuration already
- All from Option A

**Pros:**
- Jobs survive server restarts
- Can scale workers independently
- Better for high-volume production use

**Cons:**
- Adds infrastructure dependency (Redis/RabbitMQ)
- Overkill for current needs
- More complex deployment
- Current `JobManager` works fine for the expected load

**Effort:** High

---

## Recommendation

**Option A — Single Handler with JobManager** is the clear choice but adding an SSE event to notify frontend of progress and final result (if implemented)

It mirrors the proven `VideoReelHandler` pattern exactly, reuses all existing infrastructure, and delivers the required functionality with minimal new code. The in-memory job limitation is acceptable because:
- Planogram analyses are short-lived (seconds to a couple of minutes)
- The existing `VideoReelHandler` uses the same pattern in production
- Option C can be adopted later if scale demands it

The base64 image encoding trade-off is acceptable — frontends expect JSON responses, and the rendered overlay images are typically under 1MB.

---

## Feature Description

### User-Facing Behavior

**POST `/api/v1/planogram/compliance`**
- User uploads a JPEG photo via multipart form-data (`image` field).
- User provides `config_name` string identifying which planogram configuration to use (e.g., "BOSE S1 Pro+ Planogram").
- Optionally provides `user_id` and `session_id` for tracking.
- Receives immediate 202 response: `{ "job_id": "<uuid>", "status": "pending" }`.

**GET `/api/v1/planogram/compliance?job_id=<uuid>`** or **GET `/api/v1/planogram/compliance/<job_id>`**
- Polls job status.
- While running: `{ "job_id": "...", "status": "running" }`.
- On completion: `{ "job_id": "...", "status": "completed", "result": { "overall_compliant": true/false, "overall_compliance_score": 0.85, "shelf_results": [...], "rendered_image_base64": "<base64-string>", "content_type": "image/png" } }`.
- On failure: `{ "job_id": "...", "status": "failed", "error": "..." }`.

### Internal Behavior

1. **Config Resolution**: Query `troc.planograms_configurations` by `config_name` to get full planogram config, prompts, reference images, geometry, and detection parameters.
2. **Config Hydration**: Map DB row to `PlanogramConfig` Pydantic model, including building `EndcapGeometry` from flattened DB columns.
3. **Pipeline Setup**: Initialize `PlanogramCompliance` with the hydrated config and an LLM client (Google GenAI).
4. **Job Execution**: Create job via `JobManager`, fire `pipeline.run(image, output_dir)` as background async task.
5. **Result Processing**: On completion, read the rendered image file, base64-encode it, attach to result dict.
6. **Cleanup**: Remove temporary image files after encoding.

### Edge Cases & Error Handling

- **Unknown `config_name`**: Return 404 with `{ "error": "Planogram configuration 'X' not found" }`.
- **Inactive configuration** (`is_active=False`): Return 400 with explanation.
- **Missing/invalid image**: Return 400 if no image part in multipart or file is not a valid JPEG/PNG.
- **Pipeline failure** (YOLO model missing, LLM timeout): Job status becomes `failed` with error message.
- **No rendered image**: If pipeline doesn't produce `rendered_image`, omit `rendered_image_base64` from result.
- **Large images**: Consider a max upload size (e.g., 20MB) to prevent memory issues.
- **Concurrent jobs**: JobManager handles multiple concurrent jobs; each gets a unique UUID.
- **Job not found on GET**: Return 404 if `job_id` doesn't exist in JobManager.

---

## Capabilities

### New Capabilities
- `planogram-compliance-handler` — HTTP handler exposing planogram analysis as async REST API
- `planogram-config-resolver` — Database query logic to hydrate `PlanogramConfig` from `troc.planograms_configurations`

### Modified Capabilities
- None — this builds on existing code without modifying it

---

## Impact & Integration

| Component | Impact | Details |
|---|---|---|
| `parrot/handlers/` | New file | `planogram_compliance.py` handler |
| `parrot/handlers/__init__.py` | Minor edit | Export new handler |
| `parrot/pipelines/models.py` | Possibly extend | Add `from_db_row()` classmethod to `PlanogramConfig` |
| App configuration | Minor edit | Register handler route + ensure JobManager is configured |
| `troc.planograms_configurations` | Read-only | No schema changes needed |

---

## Open Questions

| # | Question | Owner | Impact |
|---|---|---|---|
| 1 | Which LLM model should be the default for the handler? (`gemini-3-flash-preview` as in the example, or configurable per planogram config?) | @jesuslara | Affects config schema | Yes, use gemini-3-flash-preview
| 2 | Should reference images in the DB be URLs or local file paths? How are they resolved at runtime? | @jesuslara | Affects config hydration | local images file paths. 
| 3 | Should the handler support batch analysis (multiple images in one request)? | @jesuslara | Scope decision | No, only one image at a time.
| 4 | Max upload size limit for images? | @jesuslara | Infrastructure config | 20MB
| 5 | Should the handler be registered in a specific app/sub-app, or the main app? | @jesuslara | Route setup | main app (app.py)

---

## Parallelism Assessment

- **Internal parallelism**: Low — the handler, config resolver, and route registration are tightly coupled. Tasks should run sequentially.
- **Cross-feature independence**: High — this handler is a new file that doesn't conflict with any in-flight features. Only touches `__init__.py` for exports.
- **Recommended isolation**: `per-spec` — all tasks sequential in one worktree.
- **Rationale**: The feature is a single handler file + minor integration edits. No benefit from splitting across worktrees. Estimated 2-3 tasks total.
