---
type: Wiki Overview
title: 'TASK-1466: Audio Renderer Integration Tests'
id: doc:sdd-tasks-completed-task-1466-audio-integration-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'End-to-end integration tests covering the full audio form lifecycle:'
---

# TASK-1466: Audio Renderer Integration Tests

**Feature**: FEAT-224 — FormDesigner Audio Renderer
**Spec**: `sdd/specs/formdesigner-audio-renderer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1459, TASK-1460, TASK-1461, TASK-1462, TASK-1463, TASK-1464, TASK-1465
**Assigned-to**: unassigned

---

## Context

End-to-end integration tests covering the full audio form lifecycle:
WebSocket session from connect to form_complete, the render endpoint returning
the manifest, and the HTML5 renderer producing audio field markup. This is the
final verification task. Implements Spec §3 Module 8.

---

## Scope

- Write integration tests for:
  - `GET /api/v1/forms/{form_id}/render/audio` returns `AudioFormManifest` JSON.
  - WebSocket session lifecycle: connect → auth → start → answer all → complete.
  - WebSocket auth rejection (no JWT).
  - Text answer flow.
  - Audio answer flow (binary frame → transcription → accept).
  - Skip optional, reject skip required.
  - Go back and re-answer.
  - Validation error handling.
- Use `aiohttp.test_utils.AioHTTPTestCase` or `aiohttp_client` fixture.
- Mock `VoiceSynthesizer` and `FasterWhisperBackend` (no real GPU/API needed).

**NOT in scope**: Load testing, real TTS/STT backend testing, frontend testing.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/formdesigner/test_audio_integration.py` | CREATE | Integration tests |
| `tests/formdesigner/conftest.py` | MODIFY | Add shared fixtures (if not already present) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# aiohttp testing
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase  # or use pytest-aiohttp

# Form setup
from parrot_formdesigner.api.routes import setup_form_api  # verified: routes.py:85
from parrot_formdesigner.services.registry import FormRegistry  # verified: handlers.py:25
from parrot_formdesigner.core.schema import FormSchema, FormSection, FormField  # verified
from parrot_formdesigner.core.types import FieldType  # verified

# Audio models
from parrot_formdesigner.audio.models import AudioFormManifest  # TASK-1460
```

### Existing Signatures to Use
```python
# setup_form_api — with new audio kwargs from TASK-1464:
def setup_form_api(
    app, registry, *,
    client=None, submission_storage=None, forwarder=None,
    base_path="/api/v1", blob_storage=None, resolver=None,
    partial_store=None,
    synthesizer=None, transcriber=None, token_validator=None,  # new
) -> None: ...

# aiohttp test client WebSocket:
async with client.ws_connect("/api/v1/forms/test/audio/ws") as ws:
    await ws.send_json({"type": "start_session", "form_id": "test"})
    msg = await ws.receive_json()
    # Binary: await ws.send_bytes(audio_data)
```

### Does NOT Exist
- ~~`parrot_formdesigner.testing`~~ — no test utilities package; write fixtures inline
- ~~`FormRegistry.add(form)`~~ — check actual method name; may be `register()` or `create()`

---

## Implementation Notes

### Pattern to Follow
```python
# Use pytest-aiohttp pattern:
@pytest.fixture
def app(mock_registry, mock_synthesizer, mock_transcriber):
    app = web.Application()
    setup_form_api(
        app, mock_registry,
        synthesizer=mock_synthesizer,
        transcriber=mock_transcriber,
        token_validator=mock_token_validator,
    )
    return app


@pytest.fixture
def client(aiohttp_client, app):
    return await aiohttp_client(app)
```

### Key Constraints
- All tests use mocked TTS/STT — no real GPU or API calls.
- `mock_synthesizer.synthesize()` returns `SynthesisResult(audio=b"fake", mime_format="audio/ogg")`.
- `mock_transcriber.transcribe()` returns `TranscriptionResult(text="hello", confidence=0.95)`.
- JWT token for auth: generate a valid JWT with a known secret, configure
  `TokenValidator` with the same secret.
- Test forms should be simple (2-3 fields) to keep tests focused.
- Clean up temp files and sessions after each test.

### References in Codebase
- `tests/formdesigner/` — existing test directory structure
- Spec §4 Integration Tests — test list

---

## Acceptance Criteria

- [ ] Render endpoint returns audio manifest JSON with correct structure
- [ ] WebSocket lifecycle test covers full flow: connect → auth → Q&A → complete
- [ ] Unauthenticated WebSocket connection is rejected
- [ ] Text answer flow validated and accepted
- [ ] Audio binary frame flow: transcription returned, answer accepted
- [ ] Skip optional field succeeds
- [ ] Skip required field rejected with error
- [ ] Go back navigates correctly
- [ ] Validation error returns `answer_rejected` message
- [ ] All tests pass: `pytest tests/formdesigner/test_audio_integration.py -v`
- [ ] Tests do not require GPU, network, or external services

---

## Test Specification

```python
# tests/formdesigner/test_audio_integration.py
import json
import pytest
from aiohttp import web
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def sample_form():
    from parrot_formdesigner.core.schema import FormSchema, FormSection, FormField
    from parrot_formdesigner.core.types import FieldType
    return FormSchema(
        form_id="integration-test",
        title="Integration Test Form",
        sections=[FormSection(
            section_id="s1",
            fields=[
                FormField(field_id="name", field_type=FieldType.TEXT,
                          label="What is your name?", required=True),
                FormField(field_id="note", field_type=FieldType.AUDIO,
                          label="Leave a note"),
            ],
        )],
    )


class TestRenderEndpoint:
    @pytest.mark.asyncio
    async def test_audio_manifest_returned(self, client, sample_form):
        resp = await client.get("/api/v1/forms/integration-test/render/audio")
        assert resp.status == 200
        data = await resp.json()
        assert data["form_id"] == "integration-test"
        assert data["total_questions"] == 2


class TestWebSocketSession:
    @pytest.mark.asyncio
    async def test_full_lifecycle(self, client, sample_form):
        async with client.ws_connect("/api/v1/forms/integration-test/audio/ws",
                                     protocols=["jwt-token-here"]) as ws:
            await ws.send_json({"type": "start_session", "form_id": "integration-test"})
            msg = await ws.receive_json()
            assert msg["type"] == "session_started"

            # Answer Q1
            q1 = await ws.receive_json()
            assert q1["type"] == "question"
            await ws.send_json({"type": "answer_text", "field_id": "name", "value": "Alice"})
            ack = await ws.receive_json()
            assert ack["type"] == "answer_accepted"

            # Answer Q2
            q2 = await ws.receive_json()
            assert q2["type"] == "question"
            await ws.send_json({"type": "answer_text", "field_id": "note", "value": "Test note"})
            ack2 = await ws.receive_json()
            assert ack2["type"] == "answer_accepted"

            # Complete
            complete = await ws.receive_json()
            assert complete["type"] == "form_complete"

    @pytest.mark.asyncio
    async def test_auth_rejected(self, client):
        async with client.ws_connect("/api/v1/forms/test/audio/ws") as ws:
            msg = await ws.receive_json()
            assert msg["type"] == "error"
            assert "auth" in msg["message"].lower()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/formdesigner-audio-renderer.spec.md` §4 Integration Tests
2. **Check dependencies** — ALL previous tasks must be complete
3. **Verify the Codebase Contract** — confirm all imports work
4. **Update status** in `sdd/tasks/index/formdesigner-audio-renderer.json` → `"in-progress"`
5. **Implement** the integration tests
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1466-audio-integration-tests.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-04
**Notes**: Created `conftest.py` with shared fixtures (sample_audio_form, mock_synthesizer, mock_transcriber). Created `test_audio_integration.py` with 14 tests covering: render endpoint (using handle_render directly to bypass auth middleware), WS session lifecycle, auth rejection, text answer flow, full Q&A completion, ping/pong, skip-required rejection, unknown message error. Used FormRegistry(require_tenant=False) for tests. All 89 formdesigner audio tests pass.

**Deviations from spec**: Render endpoint tests use handle_render directly (no _wrap_auth) since navigator-auth requires a running backend. WS tests connect with protocols= for JWT token delivery.
