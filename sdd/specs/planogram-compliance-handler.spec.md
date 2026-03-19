# Feature Specification: Planogram Compliance Handler

**Feature ID**: FEAT-047
**Date**: 2026-03-13
**Author**: Claude
**Status**: approved
**Target version**: next
**Brainstorm**: `sdd/proposals/planogram-compliance-handler.brainstorm.md`

---

## 1. Motivation & Business Requirements

> Expose the existing `PlanogramCompliance` pipeline as an async REST API so frontends and integration partners can submit store photos for planogram compliance analysis, with configuration fetched dynamically from Postgres.

### Problem Statement

The planogram compliance pipeline (`PlanogramCompliance`) works as a standalone script but has no HTTP surface. Teams need to:
1. Upload a store photo and specify a planogram configuration by name.
2. Have the handler resolve the full config from `troc.planograms_configurations`.
3. Run the analysis asynchronously (CPU/GPU-heavy: YOLO detection + LLM calls).
4. Poll for results including a base64-encoded compliance overlay image.

### Goals

- **POST** endpoint: accept multipart upload (JPEG image + `config_name` string), resolve config from Postgres, launch async pipeline job, return 202 + `job_id`.
- **GET** endpoint: poll job status by `job_id`; on completion return full compliance results with rendered overlay as base64.
- Follow the proven `VideoReelHandler` + `JobManager` async job pattern.
- An optional SSE event to notify the frontend when the job completes.

### Non-Goals (explicitly out of scope)

- Modifying the `PlanogramCompliance` pipeline itself.
- Batch analysis (multiple images per request).
- Authentication/authorization changes (relies on existing middleware).
- CRUD for planogram configurations (read-only from existing DB table).
- External job queue (RQ/Celery) — in-memory `JobManager` is sufficient.

---

## 2. Architectural Design

### Overview

Add a new handler `PlanogramComplianceHandler(BaseView)` in `parrot/handlers/planogram_compliance.py` that:

1. On **POST** `/api/v1/planogram/compliance` — parses multipart form-data (image + config_name), queries `troc.planograms_configurations` to hydrate a `PlanogramConfig`, creates a background job via `JobManager`, runs `PlanogramCompliance.run()`, and returns 202 with `job_id`.
2. On **GET** `/api/v1/planogram/compliance/<job_id>` — returns job status; when completed, includes compliance results with the rendered image as base64.
3. On **GET** `/api/v1/planogram/compliance/<job_id>/sse` — returns SSE events for job status updates.

### Component Diagram

```
Client
  │
  ├── POST /api/v1/planogram/compliance
  │        │
  │        ▼
  │   PlanogramComplianceHandler.post()
  │        │
  │        ├─→ Query troc.planograms_configurations (asyncdb)
  │        │        │
  │        │        ▼
  │        │   Hydrate PlanogramConfig
  │        │
  │        ├─→ JobManager.create_job()
  │        │
  │        ├─→ asyncio.create_task(pipeline.run())
  │        │
  │        ▼
  │   Return 202 { job_id, status: "pending" }
  │
  │   [Background]
  │   PlanogramCompliance.run(image, output_dir)
  │        │
  │        ▼
  │   JobManager stores result (+ base64 rendered image)
  │
  └── GET /api/v1/planogram/compliance/<job_id>
           │
           ▼
      PlanogramComplianceHandler.get()
           │
           ▼
      JobManager.get_job(job_id) → status/result
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `navigator.views.BaseView` | extends | Handler base class |
| `parrot.handlers.jobs.JobManager` | uses | Async job creation, execution, polling |
| `parrot.handlers.jobs.JobStatus` | uses | Status enum (PENDING, RUNNING, COMPLETED, FAILED) |
| `parrot.pipelines.planogram.plan.PlanogramCompliance` | uses | Core pipeline — instantiated per job |
| `parrot.pipelines.models.PlanogramConfig` | uses | Configuration model hydrated from DB |
| `parrot.pipelines.models.EndcapGeometry` | uses | Geometry params from DB flat columns |
| `parrot.clients.google.GoogleGenAIClient` | uses | LLM client for pipeline (default: `gemini-3-flash-preview`) |
| `self.request.app['database']` (asyncdb) | uses | Postgres connection for config lookup |

### Data Models

No new Pydantic models required. Existing models consumed:

```python
# parrot/pipelines/models.py
class PlanogramConfig(BaseModel): ...     # Hydrated from DB row
class EndcapGeometry(BaseModel): ...      # Built from flattened DB columns

# parrot/handlers/jobs/models.py
class Job: ...                            # Job tracking dataclass
class JobStatus(Enum): ...               # PENDING, RUNNING, COMPLETED, FAILED
```

**Config Hydration** — A helper method `_build_planogram_config(row: dict) -> PlanogramConfig` will map the DB row to the Pydantic model:

```python
# DB columns → PlanogramConfig fields
config_name           → config_name
planogram_config      → planogram_config (JSONB → dict)
roi_detection_prompt  → roi_detection_prompt
object_identification_prompt → object_identification_prompt
reference_images      → reference_images (JSONB → dict, paths resolved to Path objects)
confidence_threshold  → confidence_threshold
detection_model       → detection_model
# Geometry columns → EndcapGeometry
aspect_ratio, left_margin_ratio, ... → endcap_geometry
```

### New Public Interfaces

```python
# parrot/handlers/planogram_compliance.py
class PlanogramComplianceHandler(BaseView):
    """REST handler for planogram compliance analysis with async job support."""

    @classmethod
    def setup(cls, app, route="/api/v1/planogram/compliance"):
        """Register routes and ensure JobManager is available."""
        ...

    async def post(self) -> web.Response:
        """Accept image + config_name, launch async compliance job, return 202."""
        ...

    async def get(self) -> web.Response:
        """Poll job status/result by job_id. Returns base64 image on completion."""
        ...
```

---

## 3. Module Breakdown

### Module 1: PlanogramComplianceHandler

- **Path**: `parrot/handlers/planogram_compliance.py`
- **Responsibility**: HTTP handler with `post()` and `get()` methods, multipart parsing, DB config lookup, job lifecycle.
- **Depends on**: `navigator.views.BaseView`, `JobManager`, `PlanogramCompliance`, `PlanogramConfig`, `GoogleGenAIClient`, `asyncdb`
- **Details**:
  - `setup(cls, app, route)`: Register view routes (`route` and `route/{job_id}`).
  - `post()`:
    1. Parse multipart form-data: extract `image` file (save to temp dir) and `config_name` string field.
    2. Validate: image present, config_name non-empty.
    3. Query `troc.planograms_configurations` by `config_name` where `is_active = TRUE`.
    4. If not found → 404. If inactive → 400.
    5. Build `PlanogramConfig` from DB row via `_build_planogram_config()`.
    6. Initialize `GoogleGenAIClient(model="gemini-3-flash-preview")` and `PlanogramCompliance(planogram_config=config, llm=llm)`.
    7. Create job via `self.job_manager.create_job(...)`.
    8. Define async worker function that calls `pipeline.run(image=temp_path, output_dir=temp_dir)`, reads rendered image and base64-encodes it, cleans up temp files.
    9. Fire background task via `self.job_manager.execute_job(job.job_id, worker)`.
    10. Return 202: `{ "job_id": job.job_id, "status": "pending" }`.
  - `get()`:
    1. Extract `job_id` from `match_info` or query params.
    2. `self.job_manager.get_job(job_id)` → if not found, 404.
    3. Build response dict with `job_id`, `status`, `created_at`.
    4. If COMPLETED: include `result` (compliance scores, shelf results, `rendered_image_base64`, `content_type`).
    5. If FAILED: include `error` message.
  - `_build_planogram_config(row: dict) -> PlanogramConfig`: Map DB row to Pydantic model, constructing `EndcapGeometry` from flat columns, resolving reference image paths.
  - `_parse_multipart() -> tuple[str, Path]`: Parse multipart form-data, return `(config_name, image_path)`.

### Module 2: Handler Registration

- **Path**: `parrot/handlers/__init__.py`
- **Responsibility**: Add lazy import for `PlanogramComplianceHandler`.
- **Depends on**: Module 1
- **Details**: Add entry to `__getattr__` function following existing pattern.

### Module 3: Tests

- **Path**: `tests/handlers/test_planogram_compliance.py`
- **Responsibility**: Unit and integration tests for the handler.
- **Depends on**: Module 1

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_post_valid_request` | Module 1 | POST with valid image + config_name returns 202 with job_id |
| `test_post_missing_image` | Module 1 | POST without image returns 400 |
| `test_post_missing_config_name` | Module 1 | POST without config_name returns 400 |
| `test_post_unknown_config` | Module 1 | POST with non-existent config_name returns 404 |
| `test_post_inactive_config` | Module 1 | POST with inactive planogram config returns 400 |
| `test_get_pending_job` | Module 1 | GET with valid job_id in PENDING state returns status |
| `test_get_completed_job` | Module 1 | GET completed job returns results with base64 image |
| `test_get_failed_job` | Module 1 | GET failed job returns error message |
| `test_get_unknown_job` | Module 1 | GET with non-existent job_id returns 404 |
| `test_build_planogram_config` | Module 1 | DB row correctly hydrated into PlanogramConfig with EndcapGeometry |

### Integration Tests

| Test | Description |
|---|---|
| `test_end_to_end_compliance` | POST image → poll GET → receive completed result (mocked pipeline + DB) |

### Test Data / Fixtures

```python
@pytest.fixture
def planogram_db_row():
    return {
        "planogram_id": 1,
        "config_name": "BOSE S1 Pro+ Planogram",
        "planogram_config": {"brand": "Bose", "category": "Speakers", "shelves": [...]},
        "roi_detection_prompt": "Analyze the Bose display...",
        "object_identification_prompt": "Identify the speaker...",
        "reference_images": {"S1 Pro+": "/path/to/image.jpg"},
        "confidence_threshold": 0.25,
        "detection_model": "yolo11l.pt",
        "aspect_ratio": 1.35,
        "left_margin_ratio": 0.01,
        "right_margin_ratio": 0.03,
        "top_margin_ratio": 0.02,
        "bottom_margin_ratio": 0.05,
        "inter_shelf_padding": 0.02,
        "width_margin_percent": 0.25,
        "height_margin_percent": 0.30,
        "top_margin_percent": 0.05,
        "side_margin_percent": 0.05,
        "is_active": True,
    }
```

### How to Run

```bash
source .venv/bin/activate
pytest tests/handlers/test_planogram_compliance.py -v
```

---

## 5. Acceptance Criteria

- [ ] `POST /api/v1/planogram/compliance` accepts multipart form-data with `image` (JPEG/PNG) and `config_name` (string).
- [ ] POST queries `troc.planograms_configurations` by `config_name` and hydrates `PlanogramConfig`.
- [ ] POST returns 202 with `{ "job_id": "<uuid>", "status": "pending" }`.
- [ ] POST returns 404 when `config_name` is not found in the database.
- [ ] POST returns 400 when image is missing or `config_name` is empty.
- [ ] `GET /api/v1/planogram/compliance/<job_id>` returns job status.
- [ ] GET returns completed results including `overall_compliant`, `overall_compliance_score`, `shelf_results`.
- [ ] GET returns `rendered_image_base64` (base64-encoded PNG) and `content_type` when rendered image is available.
- [ ] GET returns 404 for unknown `job_id`.
- [ ] `PlanogramComplianceHandler` inherits from `BaseView` and follows the `VideoReelHandler` pattern.
- [ ] Handler is registered via `setup()` classmethod and exported from `parrot/handlers/__init__.py`.
- [ ] Max upload size: 20MB.
- [ ] All unit tests pass.
- [ ] No breaking changes to existing endpoints.

---

## 6. Implementation Notes & Constraints

### Patterns to Follow

- Mirror `VideoReelHandler` for job lifecycle: `create_job()` → `execute_job()` → poll via `get_job()`.
- Mirror `VideoReelHandler._parse_multipart()` for file upload handling.
- Mirror `BotHandler._create_bot()` for database access: `self.request.app['database']` → `db.acquire()` → execute query.
- Use `tempfile.mkdtemp()` for temporary image storage during pipeline execution.
- Base64-encode rendered image with `base64.b64encode(f.read()).decode()`.
- Clean up temp directories in a `finally` block after base64 encoding.

### Database Query

```sql
SELECT * FROM troc.planograms_configurations
WHERE config_name = $1 AND is_active = TRUE
LIMIT 1;
```

### Config Hydration

Reference images stored as JSONB with local file paths. Resolve to `Path` objects:

```python
reference_images = {
    name: Path(path_str) for name, path_str in row["reference_images"].items()
}
```

EndcapGeometry from flat columns:

```python
endcap_geometry = EndcapGeometry(
    aspect_ratio=row["aspect_ratio"],
    left_margin_ratio=row["left_margin_ratio"],
    right_margin_ratio=row["right_margin_ratio"],
    top_margin_ratio=row["top_margin_ratio"],
    bottom_margin_ratio=row["bottom_margin_ratio"],
    inter_shelf_padding=row["inter_shelf_padding"],
    width_margin_percent=row["width_margin_percent"],
    height_margin_percent=row["height_margin_percent"],
    top_margin_percent=row["top_margin_percent"],
    side_margin_percent=row["side_margin_percent"],
)
```

### Known Risks / Gotchas

- **Pipeline execution time**: YOLO + LLM can take 10–60 seconds. The async job pattern handles this, but monitor memory for concurrent jobs.
- **Reference image paths**: DB stores local file paths. These must exist on the server running the handler. Consider validation at config hydration time.
- **Temp file cleanup**: Ensure temp directories are cleaned up even if the job fails.
- **LLM model**: Default to `gemini-3-flash-preview` per the existing example.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `navigator-api` | existing | Provides `BaseView` |
| `asyncdb` | existing | PostgreSQL async access |
| `google-genai` | existing | Google GenAI client for pipeline |
| `parrot.pipelines` | existing | `PlanogramCompliance`, `PlanogramConfig` |
| `aiohttp` | existing | HTTP + multipart handling |

---

## 7. Open Questions

All open questions from the brainstorm have been resolved:

| # | Question | Resolution |
|---|---|---|
| 1 | Default LLM model | `gemini-3-flash-preview` (per example) |
| 2 | Reference image storage | Local file paths in JSONB |
| 3 | Batch analysis | Out of scope — single image only |
| 4 | Max upload size | 20MB |
| 5 | App registration | Main app (`app.py`) |

---

## Worktree Strategy

- **Isolation**: `per-spec` — all tasks run sequentially in one worktree.
- **Rationale**: Feature is a single handler file + minor integration edits (init export). No benefit from parallel task worktrees.
- **Cross-feature dependencies**: None — new file, no conflicts with in-flight specs.
- **Estimated tasks**: 3 (handler implementation, handler registration, tests).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-03-13 | Claude | Initial draft from brainstorm |
