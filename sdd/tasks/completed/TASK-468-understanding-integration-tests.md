# TASK-468: Integration Tests for Understanding Handler

**Feature**: image-video-understanding-handler
**Spec**: `sdd/specs/image-video-understanding-handler.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-466, TASK-467
**Assigned-to**: unassigned

---

## Context

End-to-end integration tests that verify the full request lifecycle: HTTP request →
handler → client call → response serialisation. Uses `aiohttp.test_utils` to spin
up the handler and send real HTTP requests with test images.
Implements **Module 4** (integration portion) from the spec.

---

## Scope

- Write integration tests using `aiohttp.test_utils.AioHTTPTestCase` or `aiohttp_client` pytest fixture.
- Test POST with a real test image (generated via Pillow) → verify 200 + response structure.
- Test POST with a mock video file → verify video path is dispatched.
- Test GET → verify catalog/schema response.
- Test error cases: no prompt (400), no media (400), unsupported file type (400).
- Mock `GoogleGenAIClient` at the boundary (don't call real API) but exercise the full handler stack.

**NOT in scope**: tests against the live Google API (those would be E2E tests).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/handlers/test_understanding_integration.py` | CREATE | Integration tests |

---

## Implementation Notes

### Pattern to Follow
```python
import pytest
from aiohttp import web, FormData
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop
from unittest.mock import AsyncMock, patch, MagicMock
from PIL import Image
from pathlib import Path
import tempfile

from parrot.handlers.understanding import UnderstandingHandler


@pytest.fixture
def app():
    """Create aiohttp app with UnderstandingHandler mounted."""
    app = web.Application()
    UnderstandingHandler.setup(app, route="/api/v1/google/understanding")
    return app


@pytest.fixture
def sample_image_bytes(tmp_path):
    """Generate a simple test PNG in memory."""
    img = Image.new("RGB", (200, 200), "red")
    path = tmp_path / "test.png"
    img.save(path)
    return path.read_bytes(), "test.png"


class TestUnderstandingIntegration:
    @pytest.mark.asyncio
    async def test_post_image_multipart(self, aiohttp_client, app, sample_image_bytes):
        """POST multipart with image → 200 + content in response."""
        client = await aiohttp_client(app)
        data = FormData()
        data.add_field("prompt", "Describe this image")
        data.add_field("file", sample_image_bytes[0],
                       filename=sample_image_bytes[1],
                       content_type="image/png")

        with patch("parrot.handlers.understanding.GoogleGenAIClient") as MockClient:
            instance = AsyncMock()
            instance.image_understanding.return_value = mock_ai_message()
            MockClient.return_value.__aenter__ = AsyncMock(return_value=instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            resp = await client.post("/api/v1/google/understanding", data=data)
            assert resp.status == 200
            body = await resp.json()
            assert "content" in body
```

### Key Constraints
- Always mock `GoogleGenAIClient` — never call the real API in tests.
- Generate test images with Pillow (no external files needed).
- For video tests, create a minimal file with `.mp4` extension (content doesn't matter since client is mocked).
- Clean up temp files after tests.

### References in Codebase
- `tests/` — existing test patterns
- `parrot/handlers/understanding.py` — the handler under test

---

## Acceptance Criteria

- [ ] Integration test for image POST → 200 with mocked client
- [ ] Integration test for video POST → 200 with mocked client
- [ ] Integration test for GET → 200 with schema
- [ ] Integration test for missing prompt → 400
- [ ] Integration test for missing media → 400
- [ ] All tests pass: `pytest tests/handlers/test_understanding_integration.py -v`

---

## Test Specification

See Implementation Notes above for the full test scaffold.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/image-video-understanding-handler.spec.md`
2. **Check dependencies** — verify TASK-466 and TASK-467 are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"`
4. **Implement** the integration tests
5. **Verify** all tests pass
6. **Move this file** to `tasks/completed/TASK-468-understanding-integration-tests.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-03-27
**Notes**: All 20 integration tests pass. Tests cover GET catalog, POST multipart image/video, JSON mode, and all 400 error cases. GoogleGenAIClient mocked at boundary. Pillow-generated test images used as fixtures.

**Deviations from spec**: none
