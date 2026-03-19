# TASK-336: PlanogramComplianceHandler — Core Implementation

**Feature**: Planogram Compliance Handler
**Spec**: `sdd/specs/planogram-compliance-handler.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: —
**Assigned-to**: —

---

## Context

> Implement the core `PlanogramComplianceHandler(BaseView)` in `parrot/handlers/planogram_compliance.py` with POST and GET methods, multipart parsing, DB config lookup, async job execution via JobManager, and base64 image encoding in results. Also add an SSE endpoint for job status notifications.
> Implements spec Sections 2 and 3 (Module 1).

---

## Scope

- Create `parrot/handlers/planogram_compliance.py` with `PlanogramComplianceHandler(BaseView)`:
  - `setup(cls, app, route)`: Register routes for the handler (`route`, `route/{job_id}`, `route/{job_id}/sse`).
  - `post()`:
    1. Parse multipart form-data via `_parse_multipart()` → extract `image` file (save to temp dir) and `config_name` string.
    2. Validate: image present, config_name non-empty. Return 400 on failure.
    3. Query `troc.planograms_configurations` by `config_name` where `is_active = TRUE` via `self.request.app['database']`.
    4. If not found → 404.
    5. Build `PlanogramConfig` from DB row via `_build_planogram_config()`.
    6. Initialize `GoogleGenAIClient(model="gemini-3-flash-preview")` and `PlanogramCompliance(planogram_config=config, llm=llm)`.
    7. Create job via `self.job_manager.create_job(...)`.
    8. Define async worker that calls `pipeline.run(image=temp_path, output_dir=temp_dir)`, base64-encodes rendered image, cleans up temp files.
    9. Fire via `self.job_manager.execute_job(job.job_id, worker)`.
    10. Return 202: `{ "job_id": ..., "status": "pending" }`.
  - `get()`:
    1. Extract `job_id` from `match_info` or query params.
    2. If path ends with `/sse`, delegate to `_sse_stream()`.
    3. `self.job_manager.get_job(job_id)` → 404 if not found.
    4. Return status; if COMPLETED include results with `rendered_image_base64` and `content_type`; if FAILED include error.
  - `_sse_stream(job_id)`: SSE endpoint that sends job status events until completion or failure.
  - `_build_planogram_config(row: dict) -> PlanogramConfig`: Hydrate PlanogramConfig from DB row, build EndcapGeometry from flat columns, resolve reference image paths to `Path` objects.
  - `_parse_multipart() -> tuple[str, Path]`: Parse multipart, return `(config_name, image_path)`.
  - `job_manager` property: Resolve `JobManager` from `self.request.app['job_manager']`.

**NOT in scope**: Handler registration in `__init__.py` (TASK-337), tests (TASK-338).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/handlers/planogram_compliance.py` | CREATE | Core handler implementation |

---

## Implementation Notes

- **Follow `VideoReelHandler` pattern** (`parrot/handlers/video_reel.py`) for:
  - `setup()` classmethod with route registration
  - `job_manager` property
  - `_parse_multipart()` structure
  - Job lifecycle (create → execute → poll)
- **Follow `BotHandler` pattern** (`parrot/handlers/chat.py:509-511`) for DB access:
  ```python
  db = self.request.app['database']
  async with await db.acquire() as conn:
      # execute query
  ```
- **DB query**: `SELECT * FROM troc.planograms_configurations WHERE config_name = $1 AND is_active = TRUE LIMIT 1`
- **Config hydration**: Map flat geometry columns to `EndcapGeometry`, resolve `reference_images` JSONB values to `Path` objects.
- **Base64 encoding**: After pipeline completes, read rendered image file and encode:
  ```python
  import base64
  with open(result['rendered_image'], 'rb') as f:
      image_base64 = base64.b64encode(f.read()).decode()
  ```
- **Temp cleanup**: Use `tempfile.mkdtemp()` and clean up in `finally` block.
- **LLM model**: Default `gemini-3-flash-preview`.
- **SSE endpoint**: Use `web.StreamResponse` with `text/event-stream` content type, poll job status periodically, send events until terminal state.

---

## Acceptance Criteria

- [ ] `PlanogramComplianceHandler` extends `BaseView`.
- [ ] `setup()` registers routes for POST, GET, and SSE.
- [ ] POST parses multipart with image + config_name.
- [ ] POST queries `troc.planograms_configurations` and hydrates `PlanogramConfig`.
- [ ] POST returns 202 with `job_id` and `status`.
- [ ] POST returns 404 for unknown config, 400 for missing image/config_name.
- [ ] GET returns job status with compliance results and base64 image on completion.
- [ ] GET returns 404 for unknown job_id.
- [ ] SSE endpoint streams status events until job completes.
- [ ] `_build_planogram_config` correctly maps DB row including `EndcapGeometry`.
- [ ] Temp files cleaned up after job execution.
- [ ] No blocking I/O in async methods.

---

## Test Specification

```python
# Manual verification until TASK-338
# 1. Check handler can be imported
from parrot.handlers.planogram_compliance import PlanogramComplianceHandler

# 2. Check it has required methods
assert hasattr(PlanogramComplianceHandler, 'setup')
assert hasattr(PlanogramComplianceHandler, 'post')
assert hasattr(PlanogramComplianceHandler, 'get')
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (`sdd/specs/planogram-compliance-handler.spec.md`) Sections 2, 3, and 6.
2. **Read `parrot/handlers/video_reel.py`** — this is the primary pattern to follow.
3. **Read `parrot/handlers/chat.py` lines 506-530** — DB access pattern.
4. **Read `parrot/handlers/jobs/job.py`** — JobManager API.
5. **Read `parrot/pipelines/models.py`** — PlanogramConfig and EndcapGeometry models.
6. **Read `parrot/pipelines/table.sql`** — DB schema for troc.planograms_configurations.
7. **Read `examples/pipelines/bose/planogram.py`** — pipeline usage example.
8. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
9. **Implement** following the scope above.
10. **Verify** the handler can be imported without errors.
11. **Commit**: `sdd: complete TASK-336 — PlanogramComplianceHandler core implementation`
12. **Update index** → `"done"`.

---

## Completion Note

**Completed by**: Claude (sdd-worker)
**Date**: 2026-03-13
**Notes**: Created `parrot/handlers/planogram_compliance.py` with `PlanogramComplianceHandler(BaseView)`.
Implements `setup()`, `post()`, `get()`, `_sse_stream()`, `_build_planogram_config()`, `_parse_multipart()`,
`_fetch_planogram_config()`, and `job_manager` property. Follows VideoReelHandler pattern.
Verified import OK.

**Deviations from spec**: None.
