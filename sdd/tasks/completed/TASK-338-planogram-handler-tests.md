# TASK-338: PlanogramComplianceHandler — Tests

**Feature**: Planogram Compliance Handler
**Spec**: `sdd/specs/planogram-compliance-handler.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-336, TASK-337
**Assigned-to**: —

---

## Context

> Write unit and integration tests for the `PlanogramComplianceHandler` covering POST, GET, SSE, error cases, and config hydration.
> Implements spec Section 3 (Module 3) and Section 4 (Test Specification).

---

## Scope

- Create `tests/handlers/test_planogram_compliance.py` with:
  - Fixtures: `planogram_db_row`, mock app with JobManager and database, sample JPEG image.
  - Unit tests:
    - `test_post_valid_request` — POST with valid image + config_name returns 202 with job_id.
    - `test_post_missing_image` — POST without image returns 400.
    - `test_post_missing_config_name` — POST without config_name returns 400.
    - `test_post_unknown_config` — POST with non-existent config_name returns 404.
    - `test_post_inactive_config` — POST with inactive config returns 400.
    - `test_get_pending_job` — GET with valid pending job_id returns status.
    - `test_get_completed_job` — GET completed job returns results with base64 image.
    - `test_get_failed_job` — GET failed job returns error message.
    - `test_get_unknown_job` — GET with unknown job_id returns 404.
    - `test_build_planogram_config` — DB row correctly hydrated into PlanogramConfig with EndcapGeometry.
  - Integration test:
    - `test_end_to_end_compliance` — POST → poll GET → completed result (mocked pipeline + DB).

**NOT in scope**: Handler implementation (TASK-336), registration (TASK-337).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/handlers/test_planogram_compliance.py` | CREATE | Unit and integration tests |

---

## Implementation Notes

- Use `pytest` and `pytest-asyncio` for async test support.
- Use `aiohttp.test_utils.AioHTTPTestCase` or `aiohttp_client` fixture for handler testing.
- Mock `self.request.app['database']` to return the `planogram_db_row` fixture.
- Mock `PlanogramCompliance.run()` to return a fake result dict with a rendered image path.
- Create a small test JPEG using `PIL.Image` or raw bytes for the multipart upload.
- For base64 image test: create a small PNG, run through the handler flow, verify base64 decode produces valid image.
- For JobManager tests: use the real `JobManager` (in-memory, no external deps).

### Test Fixtures

```python
@pytest.fixture
def planogram_db_row():
    return {
        "planogram_id": 1,
        "config_name": "BOSE S1 Pro+ Planogram",
        "planogram_config": {"brand": "Bose", "category": "Speakers", "shelves": []},
        "roi_detection_prompt": "Analyze the Bose display...",
        "object_identification_prompt": "Identify the speaker...",
        "reference_images": {"S1 Pro+": "/tmp/test_ref.jpg"},
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

---

## Acceptance Criteria

- [ ] All 10 unit tests pass.
- [ ] Integration test (end-to-end with mocked pipeline) passes.
- [ ] `_build_planogram_config` test verifies EndcapGeometry hydration from flat columns.
- [ ] Tests do not require external services (DB and pipeline are mocked).
- [ ] Tests run with: `pytest tests/handlers/test_planogram_compliance.py -v`

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (`sdd/specs/planogram-compliance-handler.spec.md`) Section 4.
2. **Read `parrot/handlers/planogram_compliance.py`** (created in TASK-336).
3. **Read `parrot/handlers/jobs/models.py`** — Job and JobStatus for assertions.
4. **Check existing test patterns** in `tests/` for aiohttp handler test style.
5. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
6. **Implement** the tests following the scope above.
7. **Run tests**: `source .venv/bin/activate && pytest tests/handlers/test_planogram_compliance.py -v`
8. **Commit**: `sdd: complete TASK-338 — PlanogramComplianceHandler tests`
9. **Update index** → `"done"`.

---

## Completion Note

**Completed by**: Claude (sdd-worker)
**Date**: 2026-03-13
**Notes**: Created `tests/handlers/test_planogram_compliance.py` with 12 tests:
10 unit tests + 1 extra defaults test + 1 integration (end-to-end) test.
All 12 tests pass. Used `patch.start()/stop()` for integration test to keep
mocks alive across background asyncio tasks.

**Deviations from spec**: Added one extra unit test (`test_build_planogram_config_defaults`)
for additional coverage beyond the specified 10. All 10 specified tests are present.
