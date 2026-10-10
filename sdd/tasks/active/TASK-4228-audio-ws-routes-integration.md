# TASK-4228: setup_form_api audio wiring (pipeline, blob storage, session store, checker) + v1/v2/resume/adversarial integration suite

**Feature**: FEAT-649 — Audio Form Interaction Workflow
**Spec**: `sdd/specs/audio-form-interaction-workflow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4227, TASK-4224
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 11 (wiring half) and §4 Integration Tests. TASK-4227 rewrote
`AudioFormWSHandler` as an adapter whose new collaborators (`pipeline`,
`blob_storage`, `session_store`, `plausibility`) all default to `None`.
TASK-4224 made `setup_form_api` build one `SubmissionPipeline` and store it as
`app["submission_pipeline"]`. This task connects the two inside
`setup_form_api` (`api/routes.py:473-496`):

- the audio route gets the **same** pipeline as HTTP (AC9 parity);
- the `blob_storage` that `setup_form_api` already receives;
- an `AudioSessionStore` built over the given `partial_store` (G9, AC16);
- a lazy LLM client getter (`llm_client_getter=handler._get_llm_client`), from which the
  adapter builds a per-form `AnswerPlausibilityChecker` (reconciled with TASK-4224/4227:
  the checker config is per form, so no single checker instance is passed).

It then proves the whole feature end-to-end over a real aiohttp test client.

---

## Scope

- Modify the audio block of `setup_form_api`. Build
  `AudioSessionStore(partial_store, ttl_seconds=3600)` when `partial_store`
  is given (else `None`). Pass `pipeline=app["submission_pipeline"]`,
  `blob_storage=blob_storage`, `session_store=…` and `llm_client_getter=handler._get_llm_client`
  to `AudioFormWSHandler(...)`. Keep `submission_storage=` and
  `auto_synthesize=synthesizer is None` exactly as today, because
  `test_audio_routes.py:113-142` asserts `_auto_synthesize`.
- Keep the mount condition (`synthesizer or transcriber or token_validator`),
  the route path `f"{tp}/forms/{{form_uid}}/audio/ws"`, and the route not
  wrapped by `_wrap_auth` (FEAT-421 note `:466-472`).
- Create `test_audio_ws_v2_integration.py` with the spec §4 integration
  tests: v2 prefetch → review → plausibility → `review_confirm` →
  `form_complete` (via the pipeline, tenant preserved); commands and go-back;
  resume plus cross-channel completion through `/partial`; HTTP
  `on_error: block`; and the adversarial suite (S12).

**NOT in scope**: changes to `api/audio_ws.py`, `audio/engine.py` or
`services/submission_pipeline.py` (fix defects in their own tasks, or report
them); the `voice/optimize` route (TASK-4234 edits `api/routes.py` after
this task); docs (TASK-4235).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` | MODIFY | Pass pipeline, blob storage, session store and checker to the audio adapter |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_v2_integration.py` | CREATE | aiohttp end-to-end suite (v2, commands, resume, block mode, adversarial) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from aiohttp import web                                                          # used throughout api/routes.py
from parrot_formdesigner.api.routes import setup_form_api                        # api/routes.py:192 (used by test_audio_integration.py:14)
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection   # core/schema.py:65, :401, :229
from parrot_formdesigner.core.types import FieldType                             # core/types.py:16
from parrot_formdesigner.services.partial_saves import PartialSaveStore          # services/partial_saves.py:24 ; _get_redis :195
# inside setup_form_api (existing lazy imports, api/routes.py:480-481):
from .audio_ws import AudioFormWSHandler
from ..services.validators import FormValidator
```

#### Provided by dependency tasks (verify in the landed files first)
```python
from parrot_formdesigner.audio.session_store import AudioSessionStore            # TASK-4219 — AudioSessionStore(partial_store, *, ttl_seconds)
from parrot_formdesigner.services.plausibility import AnswerPlausibilityChecker  # TASK-4220
# TASK-4224: setup_form_api stores the shared pipeline at app["submission_pipeline"] with plausibility=None
#            (by design: the engine passes its own PlausibilityReport to submit). No checker instance is exposed;
#            pass llm_client_getter=handler._get_llm_client (handler = app["form_api_handler"], api/handlers.py:197).
# TASK-4227: AudioFormWSHandler(..., pipeline=, blob_storage=, session_store=, llm_client_getter=, submission_storage=, auto_synthesize=)
```
**Dependency-name check (mandatory first step)**:
`grep -n 'submission_pipeline\|AnswerPlausibilityChecker' api/routes.py` and
`grep -n 'def __init__' -A20 api/audio_ws.py`. Use the names that actually
landed, and record any difference in the Completion Note.

### Existing Signatures to Use
```python
# api/routes.py:192-216
def setup_form_api(app, registry, *, client: "AbstractClient | None" = None, submission_storage=None, forwarder=None,
                   base_path="/api/v1", blob_storage: "AbstractBlobStorage | None" = None, resolver=None,
                   partial_store: "PartialSaveStore | None" = None, synthesizer=None, transcriber=None, token_validator=None, ...) -> None
# api/routes.py:479-496 (current audio block)
    if synthesizer is not None or transcriber is not None or token_validator is not None:
        from .audio_ws import AudioFormWSHandler          # :480
        from ..services.validators import FormValidator   # :481
        audio_handler = AudioFormWSHandler(               # :483
            registry=registry, synthesizer=synthesizer, transcriber=transcriber, validator=FormValidator(),
            token_validator=token_validator, submission_storage=submission_storage,
            auto_synthesize=synthesizer is None,          # :490
        )
        app.router.add_get(f"{tp}/forms/{{form_uid}}/audio/ws", audio_handler.handle_websocket)   # :493-496
# Test helpers to reuse (patterns, not imports):
#   test_audio_integration.py:25-129 — mock_registry / mock_synthesizer / mock_transcriber / mock_token_validator / app fixture
#   (mock_token_validator returns parrot.voice.handler.AuthenticatedUser(user_id="test-user", username="testuser"), :101-109)
#   test_partial_saves_integration.py:88-120 — InMemoryPartialStore overriding _get_redis() with a dict-backed _FakeRedis
#   (get / setex / delete / close). AudioSessionStore.claim_active needs SET NX → extend the stub with
#   `async def set(self, key, value, *, nx=False, ex=None)`; fakeredis is NOT installed (spec §6 Does NOT Exist).
```

### Does NOT Exist
- ~~`fakeredis`~~ — use a dict-backed stub.
- ~~`app["audio_session_store"]`~~ or any other new app key unless TASK-4224 created it. Do not invent app keys here.
- ~~A second LLM client for plausibility~~ — reuse the `client` / checker that TASK-4224 wired.
- ~~`_wrap_auth` on the audio route~~ — deliberately undecorated (FEAT-421, `api/routes.py:466-472`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_v2_integration.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py#setup_form_api",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/partial_saves.py#PartialSaveStore",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py#FormSchema",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py#FormField",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/types.py#FieldType"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `AudioSessionStore` import stays lazy inside the `if` block, matching the
  existing lazy `from .audio_ws import …` (`:480`). Importing
  `api/routes.py` must not import Redis or `parrot.voice`.
- `test_audio_routes.py`, `test_audio_integration.py` and
  `test_audio_tenant.py` must still pass **unmodified**.
- The integration suite uses only fakes: a fake transcriber with scripted
  `text` / `confidence`, a fake synthesizer with deterministic bytes that
  counts calls, a fake LLM client or checker, an in-memory blob storage and a
  dict-backed Redis. No network, GPU or ONNX.
- `test_audio_ws_resume_cross_channel` must check that the HTTP `/partial`
  surface sees only the scalar answers, never the audio snapshot (AC16).

### References in Codebase
- `tests/formdesigner/test_audio_integration.py` — aiohttp test-client + `ws_connect(..., protocols=["test-jwt-token"])` pattern.
- `tests/test_partial_saves_integration.py:88-120` — in-memory partial store.
- Spec §4 Integration Tests table; §5 AC3, AC9, AC12–AC16.

---

## Implementation Blueprint

### Steps (in order)
1. Run the dependency-name check — *why*: the pipeline app key and the checker exposure come from TASK-4224.
2. Edit the audio block of `setup_form_api` (block below) — *why*: one shared pipeline gives AC9 parity between HTTP and audio.
3. Build the fakes in the test module, then write one test per spec §4 integration row.
4. Run the three pre-existing audio suites unmodified.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        audio_handler = AudioFormWSHandler(' api/routes.py → 1, line 483)
# REPLACE the call `audio_handler = AudioFormWSHandler(...)` (api/routes.py:483-491) with:
        session_store = None
        if partial_store is not None:
            from ..audio.session_store import AudioSessionStore

            session_store = AudioSessionStore(partial_store, ttl_seconds=3600)
        audio_handler = AudioFormWSHandler(
            registry=registry,
            synthesizer=synthesizer,
            transcriber=transcriber,
            validator=FormValidator(),
            token_validator=token_validator,
            submission_storage=submission_storage,
            pipeline=app.get("submission_pipeline"),
            blob_storage=blob_storage,
            session_store=session_store,
            llm_client_getter=handler._get_llm_client,  # same lazy client as HTTP; adapter builds a per-form checker (AC10/AC11)
            auto_synthesize=synthesizer is None,
        )
```
**Why**: `app.get("submission_pipeline")` is the single pipeline TASK-4224
created, so audio and HTTP share sink exclusivity, events, forwarder and
partial cleanup (AC9). `ttl_seconds=3600` matches the `VoiceFormConfig`
default `resume_ttl_seconds`. Per-form TTLs are applied by the store on
save, if TASK-4219 implemented that. `llm_client_getter` is the handler's
lazy `_get_llm_client` (`handler` is the `FormAPIHandler` bound earlier in
`setup_form_api`, also stored as `app["form_api_handler"]`), so audio and HTTP
use one client and zero LLM calls happen when a form disables `llm_validation`.

### `packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_v2_integration.py` (CREATE)
```python
"""FEAT-649 TASK-4228 — audio WS end-to-end over aiohttp (v2, commands, resume, block mode, adversarial)."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from parrot_formdesigner.api.routes import setup_form_api
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.partial_saves import PartialSaveStore

WS_URL = "/api/v1/navigator/forms/{uid}/audio/ws"


class _DictRedis:
    """Minimal async Redis stub: get / set(nx, ex) / setex / delete / expire / close (fakeredis is not installed)."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool:
        if nx and key in self.data:
            return False
        self.data[key] = value
        return True

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.data[key] = value

    async def delete(self, *keys: str) -> int:
        return sum(1 for k in keys if self.data.pop(k, None) is not None)

    async def expire(self, key: str, ttl: int) -> bool:
        return key in self.data

    async def close(self) -> None:
        return None


class _InMemoryPartialStore(PartialSaveStore):
    """PartialSaveStore whose _get_redis() returns a shared _DictRedis (pattern: test_partial_saves_integration.py:88)."""

    def __init__(self, redis: _DictRedis) -> None:
        super().__init__(ttl_seconds=3600)
        self._fake = redis

    async def _get_redis(self) -> Any:
        return self._fake


@pytest.fixture
def voice_form() -> FormSchema:  # FILL IN: spec §4 fixture — 2 sections, SELECT (4 options incl. "Saltar"), BOOLEAN,
    ...                          #          TEXT with hint, PASSWORD, GROUP with children, depends_on chain; voice + llm_validation blocks.
```
**Why**: the stub implements only the Redis calls `PartialSaveStore` and
`AudioSessionStore` make. Extend it if TASK-4219 calls another method (check
with `grep -n 'await redis\.' audio/session_store.py services/partial_saves.py`),
but never import a real Redis client.

### FILL IN checklist
- [ ] `routes.py` — `llm_client_getter=handler._get_llm_client` wired; confirm the local name of the FormAPIHandler in `setup_form_api`; bounded by AC10/AC11 (one client, zero calls when disabled)
- [ ] `voice_form` fixture + fake transcriber / synthesizer / LLM client / blob storage; bounded by spec §4 Test Data
- [ ] one test per spec §4 integration row (names below); bounded by AC3/AC9/AC12–AC16/S12

---

## Acceptance Criteria

- [ ] The audio route receives the same `SubmissionPipeline` instance as `submit_data`. A submission made by voice reaches sinks and events with the URL tenant (AC9).
- [ ] `test_audio_ws_v1_client_still_works`: `test_audio_integration.py`, `test_audio_routes.py` and `test_audio_tenant.py` pass unmodified (AC1).
- [ ] `test_audio_ws_v2_prefetch_review_submit`: `protocol_version: 2` gives `audio_segment` header+binary frames, then questions, `review_start`, `plausibility_result`, then `review_confirm` → `form_complete` (AC3, AC12, AC15).
- [ ] `test_audio_ws_commands_and_go_back`: spoken "repetir" / "atrás" give `command_ack` plus the effect (AC14).
- [ ] `test_audio_ws_resume_cross_channel`: disconnect, then `start_session{resume_session_id}` → `session_resumed`; `/partial` + `merge_partials` complete the same answers over HTTP; the snapshot is not exposed (AC16).
- [ ] `test_http_submit_with_plausibility_block_mode`: with `on_error: block` and an unavailable client, the submit fails with a retryable error and nothing is stored; with `skip`, the submission is stored with `skipped` (AC13).
- [ ] `test_audio_adversarial_suite` covers hidden/required flips mid-session, a disabled option chosen by voice, a duplicate binary frame after the cursor moved (`WRONG_FIELD`), a sensitive answer that is never echoed, and a v1 client with extra keys (S12).
- [ ] `ruff check` passes on both files. Importing `api/routes.py` does not import Redis or `parrot.voice`.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_v2_integration.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_integration.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_routes.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_tenant.py -q`

---

## Test Specification

```python
class TestAudioWsV2Integration:
    async def test_audio_ws_v2_prefetch_review_submit(self, aiohttp_client, voice_app): ...
    async def test_audio_ws_commands_and_go_back(self, aiohttp_client, voice_app): ...
    async def test_audio_ws_resume_cross_channel(self, aiohttp_client, voice_app): ...
    async def test_http_submit_with_plausibility_block_mode(self, aiohttp_client, voice_app): ...
    async def test_audio_adversarial_suite(self, aiohttp_client, voice_app): ...
    def test_routes_pass_shared_pipeline_and_session_store(self): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug audio-form-interaction-workflow --feature-id FEAT-649`)
2. **Read the spec** (§3 M11, §4 Integration Tests, §5 AC1/AC3/AC9/AC12–AC16)
3. **Check dependencies** — TASK-4227 and TASK-4224 `"done"` in `sdd/tasks/index/audio-form-interaction-workflow.json`
4. **Verify the Codebase Contract** — run the dependency-name check; re-run `grep -c` for the routes anchor (TASK-4224 also edited `api/routes.py`, so line numbers will have moved)
5. **Update status** → `"in-progress"`, commit only the index file
6. **Implement** — blueprint blocks first, then every `# FILL IN:`
7. **Verify** — every Validation Command with `PYTHONPATH=packages/parrot-formdesigner/src`
8. **Commit the code** — only the two files listed
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4228 audio-form-interaction-workflow verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
