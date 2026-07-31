---
type: Wiki Overview
title: 'TASK-1464: Route Registration — WebSocket Mount & Renderer Seed'
id: doc:sdd-tasks-completed-task-1464-audio-route-registration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Wires the audio renderer and WebSocket handler into the existing route
---

# TASK-1464: Route Registration — WebSocket Mount & Renderer Seed

**Feature**: FEAT-224 — FormDesigner Audio Renderer
**Spec**: `sdd/specs/formdesigner-audio-renderer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1462, TASK-1463
**Assigned-to**: unassigned

---

## Context

Wires the audio renderer and WebSocket handler into the existing route
registration system. After this task, the audio endpoint is live and
discoverable. Implements Spec §3 Module 6.

---

## Scope

- Modify `setup_form_api()` in `api/routes.py` to add the WebSocket route:
  `GET /api/v1/forms/{form_id}/audio/ws`.
- Modify `_seed_default_renderers()` in `api/render.py` to register
  `AudioFormRenderer` under the `"audio"` format key.
- Accept optional `synthesizer`, `transcriber`, and `token_validator` parameters
  in `setup_form_api()` for the audio handler construction.
- Write integration tests confirming the routes are registered.

**NOT in scope**: Handler logic (TASK-1463), renderer logic (TASK-1462).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` | MODIFY | Add WS route + new kwargs |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py` | MODIFY | Register audio renderer |
| `tests/formdesigner/test_audio_routes.py` | CREATE | Route registration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# api/routes.py current imports (verified):
from aiohttp import web  # line implicit
from ..services.registry import FormRegistry  # verified: routes.py:37
from .handlers import FormAPIHandler  # verified: routes.py:41

# New imports to add:
from .audio_ws import AudioFormWSHandler  # created by TASK-1463

# api/render.py current imports (verified):
from ..renderers.base import AbstractFormRenderer  # verified: render.py:26
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py:85
def setup_form_api(
    app: web.Application,
    registry: FormRegistry,
    *,
    client: "AbstractClient | None" = None,
    submission_storage: "FormSubmissionStorage | None" = None,
    forwarder: "SubmissionForwarder | None" = None,
    base_path: str = "/api/v1",
    blob_storage: "AbstractBlobStorage | None" = None,
    resolver: "RestFieldResolver | None" = None,
    partial_store: "PartialSaveStore | None" = None,
) -> None: ...
# Route pattern (line 162+):
#   app.router.add_get(f"{bp}/forms", _wrap_auth(handler.method))

# packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py:37
def _seed_default_renderers() -> None: ...
    # Current seeds: html, adaptive, xml, pdf (lines 54-57)
    _RENDERERS.setdefault("audio", AudioFormRenderer())  # add this

# packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py:60
def register_renderer(format_key: str, renderer: AbstractFormRenderer) -> None: ...
```

### Does NOT Exist
- ~~`setup_form_api(..., synthesizer=, transcriber=, token_validator=)`~~ — these kwargs do NOT exist yet; must be added
- ~~`app.router.add_websocket()`~~ — aiohttp uses `app.router.add_get()` for WS routes (the handler returns `WebSocketResponse`)
- ~~`_wrap_auth()` for WebSocket~~ — `_wrap_auth` uses navigator-auth decorators which expect HTTP responses; WebSocket auth is handled inside the handler via `TokenValidator`

---

## Implementation Notes

### Pattern to Follow
```python
# In setup_form_api(), add after existing routes:
# Audio WebSocket (FEAT-224) — no _wrap_auth; JWT auth is inside the handler
if synthesizer is not None or transcriber is not None:
    audio_handler = AudioFormWSHandler(
        registry=registry,
        synthesizer=synthesizer,
        transcriber=transcriber,
        validator=FormValidator(),
        token_validator=token_validator,
        submission_storage=submission_storage,
    )
    app.router.add_get(
        f"{bp}/forms/{{form_id}}/audio/ws",
        audio_handler.handle_websocket,
    )
```

### Key Constraints
- The WebSocket route MUST NOT be wrapped with `_wrap_auth()` because navigator-auth
  decorators return HTTP 401 responses, which are incompatible with WebSocket
  upgrade. JWT auth happens inside the handler.
- `synthesizer`, `transcriber`, and `token_validator` should be optional kwargs
  with `None` defaults. When all are `None`, the WS route is not mounted (audio
  feature is disabled).
- `_seed_default_renderers()` should always register the audio renderer (it just
  returns the manifest JSON — no TTS/STT dependency at render time).

### References in Codebase
- `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` — existing route registration
- `packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py:37` — renderer seeding

---

## Acceptance Criteria

- [ ] `_seed_default_renderers()` registers `"audio"` → `AudioFormRenderer()`
- [ ] `setup_form_api()` accepts `synthesizer`, `transcriber`, `token_validator` kwargs
- [ ] When voice services are provided, WS route at `/api/v1/forms/{form_id}/audio/ws` is mounted
- [ ] When voice services are `None`, WS route is NOT mounted (graceful degradation)
- [ ] WebSocket route is NOT wrapped with `_wrap_auth()`
- [ ] `GET /api/v1/forms/{form_id}/render/audio` returns audio manifest via render dispatcher
- [ ] Tests pass: `pytest tests/formdesigner/test_audio_routes.py -v`
- [ ] No linting errors

---

## Test Specification

```python
# tests/formdesigner/test_audio_routes.py
import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop
from unittest.mock import AsyncMock, MagicMock
from parrot_formdesigner.api.routes import setup_form_api
from parrot_formdesigner.api.render import _RENDERERS, _seed_default_renderers


class TestAudioRendererRegistration:
    def test_audio_renderer_seeded(self):
        _seed_default_renderers()
        assert "audio" in _RENDERERS

    def test_audio_renderer_type(self):
        _seed_default_renderers()
        from parrot_formdesigner.renderers.audio import AudioFormRenderer
        assert isinstance(_RENDERERS["audio"], AudioFormRenderer)


class TestAudioRouteRegistration:
    def test_ws_route_registered_with_voice_services(self):
        app = web.Application()
        registry = MagicMock()
        setup_form_api(
            app, registry,
            synthesizer=MagicMock(),
            transcriber=MagicMock(),
        )
        routes = [r.resource.canonical for r in app.router.routes()
                  if hasattr(r, 'resource') and r.resource]
        assert any("/audio/ws" in r for r in routes)

    def test_ws_route_not_registered_without_voice(self):
        app = web.Application()
        registry = MagicMock()
        setup_form_api(app, registry)
        routes = [r.resource.canonical for r in app.router.routes()
                  if hasattr(r, 'resource') and r.resource]
        assert not any("/audio/ws" in r for r in routes)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/formdesigner-audio-renderer.spec.md` §3 Module 6
2. **Check dependencies** — TASK-1462 (renderer) and TASK-1463 (WS handler) must be complete
3. **Verify the Codebase Contract** — confirm `setup_form_api()` signature and `_seed_default_renderers()` contents
4. **Update status** in `sdd/tasks/index/formdesigner-audio-renderer.json` → `"in-progress"`
5. **Implement** the route and renderer registration
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1464-audio-route-registration.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-04
**Notes**: Modified `api/routes.py` to add `synthesizer`, `transcriber`, `token_validator` kwargs to `setup_form_api()`. WS route mounted at `{bp}/forms/{form_id}/audio/ws` only when voice services are provided (graceful degradation). Modified `api/render.py` to add `AudioFormRenderer` to `_seed_default_renderers()`. 8 tests pass.

**Deviations from spec**: none
