# TASK-4227: Rewrite AudioFormWSHandler as the thin I/O adapter over AudioFormSession (v1 + v2 encoding, auth moved verbatim)

**Feature**: FEAT-649 — Audio Form Interaction Workflow
**Spec**: `sdd/specs/audio-form-interaction-workflow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4226, TASK-4218, TASK-4219, TASK-4222
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 11. Today `api/audio_ws.py` (1 470 lines) mixes everything:
protocol decoding, the flat-list state machine, TTS, STT, a direct
`FormSubmissionStorage.store()` write, and v1 encoding. That direct write
bypasses `submit_data` (no FEAT-457 sinks, no FEAT-188 events, no
forwarder) and loses the tenant (`registry.get(..., tenant=None)`, `:1138`).

This task rewrites the class into a ~300-line **adapter**. It authenticates,
decodes JSON/binary frames into `InboundEvent`s, calls
`AudioFormSession.handle()` (TASK-4225/4226), performs every I/O request the
engine returns, feeds the results back as events, and encodes wire messages
(v1 shapes preserved; v2 `audio_segment` header + binary frame). It also
saves an autosave snapshot after every transition and again in `finally`.

Route wiring in `api/routes.py` and the end-to-end suite are **TASK-4228**.

---

## Scope

- Keep the module docstring, imports for `_sniff_audio_suffix`,
  `_SENSITIVE_MASK` and `_MIN_AUDIO_BYTES` (`:63-100`), and
  `_sniff_audio_suffix` itself (`:71`) **unchanged**.
- **Delete** `MAX_QUESTIONS = 10` (`:59`) and its truncation (`:489-494`).
  AC5 says "MAX_QUESTIONS module constant is gone". This overrides the M11
  path note "keeps module constants :59-:100". No module in `packages/`
  imports `MAX_QUESTIONS` (verified: `grep -rn MAX_QUESTIONS packages/
  --include=*.py` only hits `api/audio_ws.py`). The cap is now
  `VoiceFormConfig.max_questions`, applied by the planner (TASK-4217).
- Rewrite `AudioFormWSHandler` with the spec M11 constructor. Keep the
  existing `submission_storage=` and `auto_synthesize=` kwargs, and the
  `_auto_synthesize` / `_session_synths` attributes, which
  `test_audio_routes.py:120-142` and `test_audio_ws_handler.py:685,808-842`
  assert. Add `pipeline=`, `blob_storage=`, `session_store=` and
  `llm_client_getter=`.
- **Per-form plausibility checker (reconciled with TASK-4224)**: the checker's
  config is per form (`form.llm_validation`), so the adapter never receives a
  single checker instance. It receives `llm_client_getter: Callable[[], AbstractClient | None]`
  (TASK-4228 passes `FormAPIHandler._get_llm_client`, the same lazy client HTTP uses)
  and builds `AnswerPlausibilityChecker(llm_client_getter() if llm_client_getter else None,
  config=form.llm_validation or LLMValidationConfig())` once per session in
  `_checker_for(form)`. The shared `app["submission_pipeline"]` has
  `plausibility=None` by design: the engine hands its own `PlausibilityReport`
  to `submit(plausibility=state.plausibility)`, so the pipeline never re-runs it.
- Move these methods **verbatim** (behaviour and signature unchanged):
  `_authenticate` (`:282-347`), the tenant-declaration block of
  `handle_websocket` (`:205-220`), `_synthesize` (`:1237`),
  `_auto_synthesize_cached` (`:1271`), `_close_synth` (`:1326`),
  `_build_fallback_html` (`:1361`), `_send_error` (`:1451`) and the
  binary-frame guards (`EMPTY_AUDIO` / `UNSUPPORTED_AUDIO` /
  `TRANSCRIBER_UNAVAILABLE`, `:710-743`).
- Keep `_handle_start_session(*, ws, data, session, request, audio_cache)`
  with that keyword signature. `test_audio_tenant.py:123,153` calls it
  directly. It loads the form with the URL tenant, keeps the
  `TENANT_MISMATCH` close-1008 check (`:470-492`), builds the manifest via
  `AudioFormRenderer.split_into_questions`, builds the engine, and feeds it
  the `StartSession` event.
- Implement `_decode_text` (v1 `LegacyInbound` with `extra="ignore"` when
  `protocol_version` is absent, v2 `extra="forbid"`; S6), `_perform` (the
  I/O mapping table below) and `_encode` (v1/v2 wire).
- S11: map the authenticated `AuthenticatedUser` to `AuthContext` and pass it
  to `pipeline.submit(auth_context=…)`. The tenant always comes from the URL.
- Port `test_audio_ws_handler.py` from the deleted private methods to the
  adapter's public path (wire assertions kept). Add
  `test_audio_ws_adapter.py` for the I/O mapping.

**NOT in scope**: `api/routes.py` wiring and the aiohttp end-to-end suites
(TASK-4228); engine semantics (TASK-4225/4226 — if a behaviour is wrong,
fix it there, never re-implement it in the adapter); documentation (TASK-4235).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py` | MODIFY | Rewrite the class body as the I/O adapter; drop `MAX_QUESTIONS` |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_adapter.py` | CREATE | I/O mapping, v1/v2 encoding, snapshot autosave, auth context |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_handler.py` | MODIFY | Port private-method tests to the adapter path (deviation from plan, see Notes) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from aiohttp import WSMsgType, web                                              # api/audio_ws.py:31
from parrot_formdesigner.audio.models import (                                  # api/audio_ws.py:33-40
    AudioAnswer, AudioFormManifest, AudioQuestion, AudioSessionConfig, AudioSessionState, VoiceMode,
)
from parrot_formdesigner.renderers.audio import AudioFormRenderer, synthesize_with_fallback   # api/audio_ws.py:41-44 ; renderers/audio.py:242, :164
from parrot_formdesigner.services.auth_context import AuthContext              # services/auth_context.py:20 (scheme Literal, token, headers, claims; extra="forbid")
# TYPE_CHECKING only (pattern api/audio_ws.py:47-54):
from parrot.core.ws_auth import AuthenticatedUser, TokenValidator               # packages/ai-parrot/src/parrot/core/ws_auth.py:34 (user_id, username, email, roles, permissions, raw_payload), :44
from parrot.voice.tts.synthesizer import VoiceSynthesizer
from parrot.voice.transcriber.backend import AbstractTranscriberBackend         # transcriber/backend.py:18 ; transcribe(audio_path: Path, language=None) :39
from parrot_formdesigner.services.registry import FormRegistry                 # services/registry.py:240 ; get(form_uid, *, tenant=None) :976
from parrot_formdesigner.services.validators import FormValidator              # services/validators.py:200
from parrot_formdesigner.services.submissions import FormSubmissionStorage     # services/submissions.py:122
from parrot_formdesigner.services.blob_storage import AbstractBlobStorage      # services/blob_storage.py:119
from parrot.clients.base import AbstractClient                                   # packages/ai-parrot/src/parrot/clients/base.py (TYPE_CHECKING only)
from typing import Callable                                                      # stdlib — llm_client_getter type
```

#### Provided by dependency tasks (verify names in the landed files first)
```python
from parrot_formdesigner.audio.engine import AudioFormSession                     # TASK-4225/4226 — handle(), planner, snapshot(), from_snapshot()
from parrot_formdesigner.audio.events import (                                    # TASK-4212
    InboundEvent, Outbound, StartSession, TranscriptReady, AudioFrame, BlobStored, PlanReady, PlausibilityDone,
    SubmitDone, IOFailed, Synthesize, Transcribe, StoreBlob, DeleteBlob, SaveSnapshot, RunPlausibility, Submit, Replan,
    AudioSegment,
)
from parrot_formdesigner.audio.segments import AudioSegmentCache, _SYNTH_LOCK     # TASK-4218
from parrot_formdesigner.audio.recordings import store_recording, delete_recording   # TASK-4218
from parrot_formdesigner.audio.session_store import AudioSessionStore, SnapshotConflict   # TASK-4219
from parrot_formdesigner.services.submission_pipeline import SubmissionPipeline  # TASK-4222 (+ ValidationFailed)
from parrot_formdesigner.services.plausibility import AnswerPlausibilityChecker, PlausibilityBlocked   # TASK-4220
from parrot_formdesigner.core.voice import resolve_voice_config                  # TASK-4209
from parrot_formdesigner.core.llm_validation import LLMValidationConfig          # TASK-4209 — default config for _checker_for(form)
from parrot_formdesigner.core.voice_answer import unwrap_voice                   # TASK-4210
from parrot_formdesigner.audio.narration.engine import Narrator                  # TASK-4214
from parrot_formdesigner.audio.narration.lexicon import load_lexicon             # TASK-4213
```
**Dependency-name check (mandatory first step)**: `grep -n '^class \|^def \|^async def ' audio/events.py audio/engine.py audio/segments.py audio/recordings.py audio/session_store.py services/submission_pipeline.py services/plausibility.py`.
In particular, confirm the binary-frame event (`AudioFrame`), `Replan` /
`PlanReady`, and the exception names `ValidationFailed` / `SnapshotConflict`.
If a name differs, use the landed name and record it in the Completion Note.

### Existing Signatures to Use
```python
# api/audio_ws.py (current, rewritten here)
MAX_QUESTIONS = 10                                    # :59  ← DELETE (AC5); truncation at :489-494 ← DELETE
_SENSITIVE_MASK = "[hidden]"                          # :63  keep
_MIN_AUDIO_BYTES = 256                                # :68  keep
def _sniff_audio_suffix(data: bytes) -> Optional[str] # :71  keep verbatim
class AudioFormWSHandler:                             # :102
    def __init__(self, registry, synthesizer, transcriber, validator, *, token_validator=None, submission_storage=None,
                 max_msg_size=10*1024*1024, auto_synthesize=False) -> None   # :142-151 ; attrs _session_synths :166, _auto_synthesize :164
    async def handle_websocket(self, request) -> web.WebSocketResponse        # :173 ; subprotocol echo :184-195 ; tenant block :205-220
    async def _authenticate(self, ws, request) -> Optional[AuthenticatedUser]  # :282-347  (move verbatim)
    async def _handle_start_session(self, *, ws, data, session, request, audio_cache) -> None   # :439 ; tenant mismatch close :470-492
    async def _synthesize(self, text, *, config=None, language=None, session=None) -> Optional[bytes]   # :1237 (move verbatim)
    async def _auto_synthesize_cached(...)  # :1271 ; async def _close_synth(self, synth)  # :1326 ; async def _build_fallback_html(...)  # :1361
    async def _send_error(self, ws, code, message) -> None                     # :1451 (move verbatim)
# v1 wire shapes that MUST stay byte-compatible (test_audio_integration.py, test_audio_ws_handler.py):
#   session_started {session_id, total_questions, title} (:524-529); question {index, field_id, label, required, field_type, voice_mode,
#   render_mode, sensitive, description?, audio? (base64), options?, fallback_html?} (:1215-1233); transcription {field_id, text, confidence} (:783-788);
#   answer_accepted / answer_rejected / confirm_request / form_complete {submission_id, answers} (:1157-1161) / session_ended / pong / error {code, message}
# v1 start_session in test_audio_integration.py:336 sends {"type": "start_session", "form_id": ...} — no form_uid → URL form_uid is used (legacy extra="ignore")
```

### Does NOT Exist
- ~~`MAX_QUESTIONS`~~ after this task (AC5).
- ~~`AbstractTranscriberBackend.transcribe_bytes()`~~ / streaming STT — write a temp file (pattern `:745-751`) and call `transcribe(Path, language=)`.
- ~~`VoiceSynthesizer.synthesize_to_base64()`~~ — base64 is encoded here for v1 only.
- ~~`FormSubmissionStorage.store()` call from the adapter~~ — every submit goes through `SubmissionPipeline.submit()` (AC9).
- ~~`registry.get(..., tenant=None)`~~ — always the URL tenant (bug fixed by this rewrite).
- ~~A2UI voice primitive~~ — out of scope.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_adapter.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_handler.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py#AudioFormWSHandler",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py#_sniff_audio_suffix",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py#AudioFormWSHandler._authenticate",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py#AudioFormWSHandler._handle_start_session",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py#AudioFormWSHandler._synthesize",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py#AudioFormWSHandler._send_error",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/renderers/audio.py#AudioFormRenderer",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/auth_context.py#AuthContext",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py#AudioSessionState"
  ]
}
```

---

## Implementation Notes

### I/O mapping table (one branch per `Outbound` kind in `_perform`)
| Outbound | Adapter action | Event fed back |
|---|---|---|
| wire message (`SessionStarted`, `Question`, `Transcription`, …, `Error`, `Pong`) | `ws.send_json(self._encode(msg))` | — |
| `Synthesize(keys, texts)` | `await self._segments.ensure(texts, locale=, voice=, form_uid=, version=)`; v2: per key `send_json(AudioSegment header)` then `send_bytes(audio)`; v1 (or `prefetch=False`): keep bytes in `self._v1_audio[key]` for base64 `audio` on the next `question` | — |
| `Replan` | `delta = await session.planner.replan(session.state.answers, locale=session.state.locale)` | `PlanReady(order, delta)` |
| `Transcribe(field_id, audio)` | temp file (`:745-751`) → `await self.transcriber.transcribe(path, language=)`; decode failure → `IOFailed("AUDIO_DECODE_ERROR")` | `TranscriptReady(field_id, text, language, confidence, audio_mime, audio_bytes_len, duration_ms)` |
| `StoreBlob(field_id, audio, mime)` | `await store_recording(self._blob_storage, ...)`; no storage → skip | `BlobStored(field_id, blob_ref)` |
| `DeleteBlob(blob_ref)` | `await delete_recording(...)` (best effort, log on failure) | — |
| `SaveSnapshot(state)` | `await self._session_store.save(form_uid, session_id, session.snapshot(), expected_revision=rev)`; `SnapshotConflict` → `Error("RESUME_CONFLICT")` + close | — |
| `RunPlausibility(fields)` | `await self._checker_for(form).check(form, unwrap_voice(data), locale=, fields=)`; `PlausibilityBlocked` → report `status="blocked"` | `PlausibilityDone(report)` |
| `Submit(data, context)` | `await self._pipeline_for(form).submit(form, data, tenant=<URL>, user_id=, locale=, context=, extra_data=None, auth_context=self._auth_context(user), merge_session_id=state.session_id, plausibility=state.plausibility)`; `ValidationFailed` / `PlausibilityBlocked` mapped | `SubmitDone(outcome \| errors)` |

Feeding an event back calls `session.handle(ev)` again, and its outbound list
is performed recursively (iteratively, not by recursion depth). Phase
transitions never await, because only `_perform` awaits.

### Key Constraints
- `parrot.voice.*`, `parrot.core.ws_auth` and `parrot.clients.*` are imported only under `TYPE_CHECKING` or lazily inside functions (AC21).
- `_pipeline_for(form)` returns `self._pipeline`, or else lazily builds
  `SubmissionPipeline(validator=self.validator, submission_storage=self._submission_storage, forwarder=None, partial_store=None, plausibility=None)` (the engine passes its own report to `submit`).
  This keeps the handler usable when constructed without the new kwargs, as
  the existing tests and TASK-4228 do.
- Snapshot autosave runs after every `handle()` that changed state (the
  engine emits `SaveSnapshot`) and once in `finally`, but only when a session
  store exists and the session is not COMPLETE. Without Redis it is a no-op
  (spec M7).
- One active session per user (`claim_active`). A second connection gets
  `Error("SESSION_ACTIVE")`. Resume via `StartSession.resume_session_id` loads
  the snapshot, then calls `AudioFormSession.from_snapshot`. A missing
  snapshot → `Error("RESUME_UNAVAILABLE")`.
- Logging: never log transcripts or answer values (S8).

### Porting `test_audio_ws_handler.py` (deviation: file not in the plan's list)
That suite calls private methods this rewrite deletes: `_accept_answer`,
`_send_question`, `_handle_answer_selection`, `_handle_answer_payload`,
`_handle_confirm_answer`, `_handle_answer_audio`, `_handle_skip_question`,
`_handle_go_back`, `_handle_repeat_question` and `_handle_ping` (all
verified by grep). Port each test so it drives the adapter through the
**public** path: a fake `ws` plus `handler._process_text(ws, ctx, data)` /
`handler._process_binary(ws, ctx, data)`, the two entry points block 2
defines. Keep every **wire** assertion: message types, keys, `"[hidden]"`
masking, `audio` base64 presence/absence, `fallback_html` escaping.

Replace assertions on `state.current_index` with assertions on the next
`question` message. **One assertion changes on purpose**:
`test_answer_selection_multi` expects `state.answers["tags"].value == "a,b"`
today (`:531`). AC6 / G5 / the owner decision ("MULTI_SELECT stored as a
list") require `["a", "b"]`. Change it and cite AC6 in the Completion Note.
`test_audio_integration.py`, `test_audio_routes.py` and `test_audio_tenant.py`
must pass **unmodified**.

---

## Implementation Blueprint

### Steps (in order)
1. Run the dependency-name check — *why*: the adapter touches the outputs of seven dependency tasks.
2. Delete `MAX_QUESTIONS` and keep the other module constants (block 1).
3. Rewrite `__init__` keeping the old kwargs (block 1) — *why*: routes and tests construct the handler with them.
4. Rewrite `handle_websocket` around `_process_text` / `_process_binary` (block 2), moving the auth and tenant code verbatim.
5. Implement `_perform` / `_encode` from the mapping table (block 3).
6. Re-implement `_handle_start_session` as the engine bootstrap (block 4).
7. Port `test_audio_ws_handler.py`, then write `test_audio_ws_adapter.py`.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py` (MODIFY) — block 1: constants + constructor
```python
# occurrences: 1 (verified: grep -c 'MAX_QUESTIONS = 10' api/audio_ws.py)
# DELETE lines :58-59  "# Maximum audio questions per session ..." / "MAX_QUESTIONS = 10"  (AC5)

# occurrences: 1 (verified: grep -c 'class AudioFormWSHandler:' api/audio_ws.py)
# REPLACE the class body starting at `class AudioFormWSHandler:` (api/audio_ws.py:102) — __init__:
    def __init__(
        self,
        registry: "FormRegistry",
        synthesizer: Optional["VoiceSynthesizer"],
        transcriber: Optional["AbstractTranscriberBackend"],
        validator: "FormValidator",
        *,
        token_validator: Optional["TokenValidator"] = None,
        submission_storage: Optional["FormSubmissionStorage"] = None,
        pipeline: Optional["SubmissionPipeline"] = None,
        blob_storage: Optional["AbstractBlobStorage"] = None,
        session_store: Optional["AudioSessionStore"] = None,
        llm_client_getter: Optional[Callable[[], Optional["AbstractClient"]]] = None,
        max_msg_size: int = 10 * 1024 * 1024,
        auto_synthesize: bool = False,
    ) -> None:
        """Initialize the adapter; every new collaborator is optional (degrades, never fails)."""
        self.registry = registry
        self.synthesizer = synthesizer
        self.transcriber = transcriber
        self.validator = validator
        self._token_validator = token_validator
        self._submission_storage = submission_storage
        self._pipeline = pipeline
        self._blob_storage = blob_storage
        self._session_store = session_store
        self._llm_client_getter = llm_client_getter
        self._checkers: dict[str, "AnswerPlausibilityChecker"] = {}   # session_id → per-form checker
        self._max_msg_size = max_msg_size
        self._auto_synthesize = auto_synthesize
        self._session_synths: dict[str, Any] = {}   # kept: test_audio_ws_handler.py:842, auto_synthesize path
        self.logger = logging.getLogger(__name__)
```
**Why**: `auto_synthesize` / `_auto_synthesize` / `_session_synths` /
`submission_storage` are asserted by the existing suites. The new
collaborators default to `None` so `setup_form_api` keeps working until
TASK-4228 passes them.

### block 2: connection loop
```python
    async def handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        """Authenticate, check tenant, then pump frames through the engine."""
        # MOVE VERBATIM: subprotocol echo + ws.prepare (:184-195), self._authenticate (:198-200), tenant block (:205-220)
        ctx = _ConnCtx(request=request, user=user, tenant=declared_tenant,
                       state=AudioSessionState(session_id=str(uuid.uuid4()), form_uid=request.match_info.get("form_uid", ""),
                                               user_id=user.user_id))
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except json.JSONDecodeError:
                        await self._send_error(ws, "INVALID_JSON", "Invalid JSON message")
                        continue
                    await self._guarded(ws, self._process_text(ws, ctx, data), "INTERNAL_ERROR")
                elif msg.type == WSMsgType.BINARY:
                    await self._guarded(ws, self._process_binary(ws, ctx, msg.data), "TRANSCRIPTION_ERROR")
                elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                    break
        finally:
            await self._autosave(ctx, final=True)
            cached_synth = self._session_synths.pop(ctx.state.session_id, None)
            if cached_synth is not None:
                await self._close_synth(cached_synth)
        return ws

    async def _process_text(self, ws: web.WebSocketResponse, ctx: "_ConnCtx", data: dict[str, Any]) -> None:
        """start_session bootstraps the engine; every other message is decoded and handled."""
        if data.get("type") == "start_session":
            await self._handle_start_session(ws=ws, data=data, session=ctx.state, request=ctx.request,
                                             audio_cache={}, ctx=ctx)
            return
        if ctx.engine is None:
            await self._send_error(ws, "SESSION_NOT_STARTED", "Call start_session first")
            return
        event = self._decode_text(data, protocol_version=ctx.state.protocol_version)
        if event is None:
            await self._send_error(ws, "UNKNOWN_MESSAGE_TYPE", f"Unknown message type: {data.get('type', '')}")
            return
        await self._perform(ws, ctx, ctx.engine.handle(event))

    async def _process_binary(self, ws: web.WebSocketResponse, ctx: "_ConnCtx", audio: bytes) -> None:
        """Guards moved verbatim from :710-743, then AudioFrame → engine."""
        # FILL IN: SESSION_NOT_STARTED / TRANSCRIBER_UNAVAILABLE / EMPTY_AUDIO (_MIN_AUDIO_BYTES) / UNSUPPORTED_AUDIO
        #          (_sniff_audio_suffix) with the exact v1 messages, then
        #          await self._perform(ws, ctx, ctx.engine.handle(AudioFrame(audio=audio, mime=<suffix→mime>)))
        #          — bounded by test_audio_ws_handler EMPTY_AUDIO/UNSUPPORTED_AUDIO expectations.
```
**Why**: `_ConnCtx` is a small private dataclass holding `request`, `user`,
`tenant`, `state`, `engine`, `form`, `revision` and `v1_audio`. It
replaces the old `_audio_cache: dict[int, str]` local. `_guarded` wraps the
`try/except Exception → logger.exception + _send_error(code)` pattern from
`:236-252`, so behaviour on unexpected errors is unchanged.

### block 3: `_perform` / `_encode` / helpers
```python
    async def _perform(self, ws: web.WebSocketResponse, ctx: "_ConnCtx", outbound: list["Outbound"]) -> None:
        """Perform outbound items in order; I/O results are fed back into the engine (iteratively)."""
        queue = list(outbound)
        while queue:
            item = queue.pop(0)
            feedback = await self._perform_one(ws, ctx, item)
            if feedback is not None:
                queue[:0] = ctx.engine.handle(feedback)   # results run before the remaining items

    async def _perform_one(self, ws: web.WebSocketResponse, ctx: "_ConnCtx", item: "Outbound") -> "InboundEvent | None":
        """One mapping-table row; returns the event to feed back, or None for wire messages."""
        # FILL IN: one branch per row of the I/O mapping table (Implementation Notes) — bounded by AC3 (v2 audio_segment header
        #          then send_bytes before the first question; v1 base64 `audio` on `question`), AC8 (blob ids from store_recording),
        #          AC9 (pipeline only, URL tenant), AC13 (PlausibilityBlocked → status "blocked"), AC16 (CAS revision).
        return None

    def _encode(self, ctx: "_ConnCtx", msg: "Outbound") -> dict[str, Any]:
        """Wire dict for one message; v1 clients get the FEAT-236 shapes (and base64 audio on question)."""
        # FILL IN: msg.model_dump(exclude_none=True, mode="json"); for v1 drop v2-only keys and attach
        #          ctx.v1_audio[<question label key>] as base64 "audio" — bounded by test_audio_integration.py / AC3.
        return {}

    def _decode_text(self, data: dict[str, Any], *, protocol_version: int) -> "InboundEvent | None":
        """v1 → LegacyInbound (extra ignored); v2 → InboundEvent (extra forbidden). None for unknown types."""
        # FILL IN: TypeAdapter(InboundEvent / legacy union).validate_python(data); ValidationError on v2 → Error("INVALID_MESSAGE")
        #          — bounded by S6 / test_legacy_inbound_ignores_unknown_keys.
        return None

    def _auth_context(self, user: "AuthenticatedUser") -> AuthContext:
        """S11: AuthenticatedUser → AuthContext for the submission pipeline."""
        return AuthContext(scheme="bearer", claims=dict(getattr(user, "raw_payload", {}) or {}))
```
**Why**: `queue[:0] = …` processes an I/O result's follow-ups (for example
`PlanReady` → `Question`) before the remaining items. That preserves wire
ordering without recursion. The `return None` / `return {}` lines are
placeholder returns that the FILL IN replaces.

### block 4: `_handle_start_session` (engine bootstrap, signature kept)
```python
    async def _handle_start_session(self, *, ws: web.WebSocketResponse, data: dict[str, Any], session: AudioSessionState,
                                    request: web.Request, audio_cache: dict[int, str], ctx: "_ConnCtx | None" = None) -> None:
        """Load the form with the URL tenant (TENANT_MISMATCH close kept), build manifest + engine, feed StartSession."""
        # MOVE VERBATIM: form_uid/locale resolution, _build_session_config, registry.get(form_uid, tenant=declared_tenant),
        #                FORM_NOT_FOUND, TENANT_MISMATCH + ws.close(code=1008) (:449-492)
        # FILL IN: questions = AudioFormRenderer(synthesizer=self.synthesizer).split_into_questions(form, locale=locale) (NO cap here);
        #          manifest; cfg = resolve_voice_config(form, session.config); engine = AudioFormSession(form=, manifest=, cfg=,
        #          narrator=Narrator(locale), lexicon=load_lexicon(locale), state=session, llm_cfg=form.llm_validation);
        #          AudioSegmentCache(self.synthesizer, lock=_SYNTH_LOCK); resume branch (claim_active / load / from_snapshot);
        #          await self._perform(ws, ctx, engine.handle(StartSession-from-data)) — bounded by AC3, AC5, AC16 and
        #          test_audio_tenant.py (ctx=None path must still close on mismatch and call registry.get(uid, tenant=declared)).
```
**Why**: `test_audio_tenant.py` calls this method without `ctx` and with a
`MagicMock` validator. When `ctx is None`, build a throwaway `_ConnCtx`
from `request` and `session`. The tenant assertions must keep passing
unchanged.

### `packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_adapter.py` (CREATE)
```python
"""FEAT-649 TASK-4227 — AudioFormWSHandler adapter I/O mapping."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot_formdesigner.api import audio_ws
from parrot_formdesigner.api.audio_ws import AudioFormWSHandler


def test_max_questions_constant_removed() -> None:
    """AC5: the module constant is gone."""
    assert not hasattr(audio_ws, "MAX_QUESTIONS")
```

### FILL IN checklist
- [ ] `_process_binary` — v1 guards verbatim; `AudioFrame` mime from suffix; bounded by the existing EMPTY/UNSUPPORTED tests
- [ ] `_perform_one` — every mapping-table row; bounded by AC3/AC8/AC9/AC13/AC16
- [ ] `_encode` / `_decode_text` — v1 shapes, v2 forbid; bounded by AC3/S6
- [ ] `_handle_start_session` — bootstrap + resume + no cap; bounded by AC5/AC16 and `test_audio_tenant.py`
- [ ] `_autosave` / `_guarded` / `_ConnCtx` / `_pipeline_for`; bounded by spec M11 "snapshot autosave after every transition and in finally"
- [ ] `test_audio_ws_handler.py` ported (only the `"a,b"` → `["a", "b"]` assertion changes meaning); bounded by AC1/AC6

---

## Acceptance Criteria

- [ ] `MAX_QUESTIONS` no longer exists in `api/audio_ws.py` (AC5).
- [ ] `test_audio_integration.py`, `test_audio_routes.py` and `test_audio_tenant.py` pass **unmodified** (AC1).
- [ ] The ported `test_audio_ws_handler.py` passes with the same wire assertions; MULTI_SELECT is a list (AC6).
- [ ] The adapter never calls `FormSubmissionStorage.store` and never calls `registry.get(..., tenant=None)`. Submit goes through `SubmissionPipeline.submit` with the URL tenant and an `AuthContext` (AC9, S11).
- [ ] A v2 client receives an `audio_segment` header + binary frame for every planned question before the first `question`. A v1 client receives base64 `audio` in `question` (AC3).
- [ ] A snapshot is saved after transitions and in `finally` when a session store is configured. `SnapshotConflict` is surfaced as an error.
- [ ] No module-level import of `parrot.voice`, `parrot.core` or `parrot.clients` (AC21). `ruff check` is clean.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_adapter.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_handler.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_integration.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_tenant.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_routes.py -q`

---

## Test Specification

```python
class TestAdapterIO:
    async def test_v2_prefetch_sends_segment_header_then_bytes_before_question(self): ...
    async def test_v1_question_carries_base64_audio(self): ...
    async def test_replan_awaits_planner_and_feeds_plan_ready(self): ...
    async def test_transcribe_writes_temp_file_and_feeds_transcript(self): ...
    async def test_decode_error_maps_to_audio_decode_error(self): ...
    async def test_store_blob_calls_store_recording_and_feeds_blob_stored(self): ...
    async def test_submit_uses_pipeline_with_url_tenant_and_auth_context(self): ...
    async def test_plausibility_blocked_becomes_blocked_report(self): ...
    async def test_snapshot_saved_after_transition_and_in_finally(self): ...
    async def test_snapshot_conflict_surfaces_error(self): ...
    async def test_v2_unknown_key_rejected_v1_ignored(self): ...
    def test_max_questions_constant_removed(self): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug audio-form-interaction-workflow --feature-id FEAT-649`)
2. **Read the spec** (§3 M11, M6, M7, M9; §5 AC1/AC3/AC5/AC9/AC16/AC21) and the current `api/audio_ws.py` end-to-end before deleting anything
3. **Check dependencies** — TASK-4226, TASK-4218, TASK-4219, TASK-4222 `"done"` in `sdd/tasks/index/audio-form-interaction-workflow.json`
4. **Verify the Codebase Contract** — run the dependency-name check; re-run `grep -c` for every anchor
5. **Update status** → `"in-progress"`, commit only the index file
6. **Implement** — blueprint blocks first, then every `# FILL IN:`
7. **Verify** — every Validation Command with `PYTHONPATH=packages/parrot-formdesigner/src`
8. **Commit the code** — only the three files listed
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4227 audio-form-interaction-workflow verified`
10. **Fill in the Completion Note** (list every ported test and the `"a,b"` → list change), then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
