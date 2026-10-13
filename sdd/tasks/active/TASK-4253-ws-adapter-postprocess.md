# TASK-4253: WS adapter — timezone validation, RefineValue execution, v1 encoding

**Feature**: FEAT-653 — Audio form voice post-processors
**Spec**: `sdd/specs/audio-form-voice-postprocessors.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4249, TASK-4252
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8. The engine is pure; the aiohttp adapter `AudioFormWSHandler` performs its I/O
requests. This task makes three changes:

1. **Validate `start_session.timezone`** with `zoneinfo.ZoneInfo` before the engine sees it. An
   invalid zone is logged and dropped (treated as absent), so the engine always gets a valid zone
   or `None`.
2. **Perform `RefineValue`**:
   - get a per-session `LLMValueRefiner` from `llm_client_getter`, cached like the plausibility
     checker;
   - call it under `asyncio.wait_for(cfg.llm_refine_timeout_s)`;
   - feed `ValueRefined` back: `ok`, `failed` (exception, timeout or `None`), or `unavailable`
     (no client).
3. **v1 compatibility**: v1 `confirm_request` drops `value` / `refined_by`, and v1
   `answer_rejected` drops `value` (AC4).

---

## Scope

- Imports, a `self._refiners` cache, `_refiner_for(session_id)`, `_do_refine(ctx, item)`, the
  `_perform_one` row, the `finally` cleanup, timezone validation in `_handle_start_session`, and
  the `_encode` v1 pops.
- Write `test_audio_ws_postprocess.py` (integration through `_process_text` / `_process_binary`
  with fake STT and LLM clients).

**NOT in scope**: engine logic; the STT `language=None` behaviour for "en" (`audio_ws.py:987`,
the separate STT spec).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py` | MODIFY | Timezone, refine I/O, v1 encode, cleanup |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_postprocess.py` | CREATE | Adapter tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# add to api/audio_ws.py
from zoneinfo import ZoneInfo                                          # stdlib
from ..audio.events import RefineValue, ValueRefined                   # TASK-4248 — add to the block at audio_ws.py:42-71
from ..audio.value_refiner import LLMValueRefiner, ValueRefiner        # TASK-4249
from ..core.types import FieldType                                     # core/types.py:16
# already imported: asyncio (:24), Optional/Callable/Any (:36), StartSession (:61), AnswerPlausibilityChecker (:93)
```

### Existing Signatures to Use
```python
# api/audio_ws.py
class AudioFormWSHandler:
    def __init__(..., llm_client_getter: Optional[Callable[[], Optional["AbstractClient"]]] = None, ...)   # :272-300
        self._llm_client_getter = llm_client_getter                                             # :298
        self._checkers: dict[str, AnswerPlausibilityChecker] = {}  # session_id → per-form checker   # :299
    # receive loop finally: `            self._checkers.pop(ctx.state.session_id, None)`           # :398 (1 occurrence)
    async def _handle_start_session(self, *, ws, data, session, request, audio_cache, ctx=None)   # :569
        #   start = parse_inbound({...}); ...; `        assert isinstance(start, StartSession)`     # :594 (1 occurrence)
        #   later: opening = engine.handle(start)                                                    # ~:689
    async def _perform_one(self, ws, ctx, item) -> Optional[InboundEvent]                         # :750
        #   `        if isinstance(item, Submit):` / `            return await self._do_submit(ctx, item)`   # :822-823
    def _encode(self, ctx, msg) -> dict[str, Any]                                                   # :846
        #   `        elif mtype == "confirm_request":` + two pops                                    # :874-876 (1 occurrence)
    def _checker_for(self, form, *, session_id="") -> AnswerPlausibilityChecker                    # :1019 (cache pattern)
class _ConnCtx: request, user, tenant, state: AudioSessionState, engine, form, ...                 # :~180-205
# engine (TASK-4248/4251/4252): ctx.engine.cfg.llm_refine_timeout_s; ctx.state.locale; ctx.state.timezone
# RefineValue(field_id, request_id, transcript, candidate, field_type: str, label, today)
# ValueRefined(type="_value_refined", field_id, request_id, status, value, confidence)
# LLMValueRefiner(client).refine(*, transcript, candidate, field_type: FieldType, label, locale, today, timezone) -> RefinedValue | None
```

### Does NOT Exist
- ~~`AudioFormWSHandler._refiners`~~, ~~`_refiner_for`~~, ~~`_do_refine`~~ — created here.
- ~~A per-feature LLM model setting~~ — reuse `llm_client_getter` (design research S7, model part rejected).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_postprocess.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py#AudioFormWSHandler",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py#AudioFormWSHandler._perform_one",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py#AudioFormWSHandler._encode",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py#AudioFormWSHandler._handle_start_session"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Imports + `self._refiners` + cleanup in `finally` — *why*: one refiner per session, freed with it.
2. Timezone validation after `assert isinstance(start, StartSession)` — *why*: the engine trusts `state.timezone`.
3. `_refiner_for` / `_do_refine` + the `_perform_one` row — *why*: the engine's only path to the LLM.
4. v1 encode pops — *why*: AC4; v1 clients get the FEAT-236 shapes only.
5. Tests.

### `api/audio_ws.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        self._checkers: dict\[str, AnswerPlausibilityChecker\] = {}' audio_ws.py)
# AFTER — insert below the `self._checkers: ...` line (verified: audio_ws.py:299)
        self._refiners: dict[str, Optional[ValueRefiner]] = {}  # session_id → LLM post-processor (FEAT-653)
```
```python
# occurrences: 1 (verified: grep -c '            self._checkers.pop(ctx.state.session_id, None)' audio_ws.py)
# AFTER — insert below it (verified: audio_ws.py:398)
            self._refiners.pop(ctx.state.session_id, None)
```
```python
# occurrences: 1 (verified: grep -c '        assert isinstance(start, StartSession)' audio_ws.py)
# AFTER — insert below `        assert isinstance(start, StartSession)` (verified: audio_ws.py:594)
        if start.timezone:
            try:
                ZoneInfo(start.timezone)
            except Exception:  # noqa: BLE001 — ZoneInfoNotFoundError / ValueError for malformed keys
                self.logger.warning("start_session: ignoring invalid timezone %r", start.timezone)
                start = start.model_copy(update={"timezone": None})
```
```python
# occurrences: 1 (verified: grep -c '            return await self._do_submit(ctx, item)' audio_ws.py)
# AFTER — insert below `            return await self._do_submit(ctx, item)` (verified: audio_ws.py:823)

        if isinstance(item, RefineValue):
            return await self._do_refine(ctx, item)
```
```python
# occurrences: 1 (verified: grep -c '        elif mtype == "confirm_request":' audio_ws.py)
# REPLACE the confirm_request branch (audio_ws.py:874-876) with:
        elif mtype == "confirm_request":
            for key in ("matched", "alternatives", "value", "refined_by"):
                wire.pop(key, None)
        elif mtype == "answer_rejected":
            wire.pop("value", None)
```
New methods (place next to `_checker_for`):
```python
    def _refiner_for(self, session_id: str) -> Optional[ValueRefiner]:
        """Per-session LLM post-processor from ``llm_client_getter``; None when no client is configured."""
        if session_id not in self._refiners:
            client = self._llm_client_getter() if self._llm_client_getter is not None else None
            self._refiners[session_id] = LLMValueRefiner(client) if client is not None else None
        return self._refiners[session_id]

    async def _do_refine(self, ctx: _ConnCtx, item: RefineValue) -> "InboundEvent":
        """Run the LLM post-processor under the form's timeout; never fails the turn."""
        engine = ctx.engine
        assert engine is not None
        refiner = self._refiner_for(ctx.state.session_id)
        if refiner is None:
            return ValueRefined(type="_value_refined", field_id=item.field_id, request_id=item.request_id, status="unavailable")
        try:
            result = await asyncio.wait_for(
                refiner.refine(
                    transcript=item.transcript,
                    candidate=item.candidate,
                    field_type=FieldType(item.field_type),
                    label=item.label,
                    locale=ctx.state.locale,
                    today=item.today,
                    timezone=ctx.state.timezone,
                ),
                timeout=engine.cfg.llm_refine_timeout_s,
            )
        except Exception as exc:  # noqa: BLE001 — TimeoutError included; fall back to the rules result
            self.logger.warning("LLM value refine failed for %s: %s", item.field_id, type(exc).__name__)
            result = None
        # FILL IN: result None → status "failed"; else status "ok" with value=result.value, confidence=result.confidence
        raise NotImplementedError
```
**Why**: `asyncio.TimeoutError` is an `Exception`, so the single except covers it. Never log the
transcript (it may be personal data).

### `tests/formdesigner/test_audio_ws_postprocess.py` (CREATE)
```python
"""FEAT-653 TASK-4253 — WS adapter: timezone, LLM refine I/O, v1 encoding."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot_formdesigner.api.audio_ws import AudioFormWSHandler, _ConnCtx
from parrot_formdesigner.audio.models import AudioSessionState
from parrot_formdesigner.audio.value_refiner import RefinedValue
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType

_TENANT = "acme"
_WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 512


def _form(ft: FieldType, *, voice: dict | None = None, meta: dict | None = None) -> FormSchema:
    return FormSchema(
        form_id="f", title="T", tenant=_TENANT, voice=voice,
        sections=[FormSection(section_id="s1", fields=[
            FormField(field_id="a", field_type=ft, label="A?", required=True, meta=meta)])],
    )


def _ws() -> AsyncMock:
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    ws.send_bytes = AsyncMock()
    return ws


def _msgs(ws: AsyncMock) -> list[dict]:
    return [c[0][0] for c in ws.send_json.call_args_list]


def _handler(form: FormSchema, transcript: str, **kw) -> AudioFormWSHandler:
    registry = AsyncMock()
    registry.get.return_value = form
    stt = AsyncMock()
    stt.transcribe.return_value = MagicMock(text=transcript, confidence=0.95, language="en", duration_seconds=1.0)
    synth = AsyncMock()
    synth.synthesize.return_value = MagicMock(audio=b"AUDIO")
    return AudioFormWSHandler(registry=registry, synthesizer=synth, transcriber=stt, validator=MagicMock(), **kw)


async def _boot(h: AudioFormWSHandler, start: dict):
    ws = _ws()
    request = SimpleNamespace(match_info={"form_uid": "f1", "tenant": _TENANT}, headers={})
    ctx = _ConnCtx(request=request, user=SimpleNamespace(user_id="u1", raw_payload={"sub": "u1"}), tenant=_TENANT,
                   state=AudioSessionState(session_id="s1", form_uid="f1", user_id="u1", tenant=_TENANT))
    await h._process_text(ws, ctx, {"type": "start_session", "form_uid": "f1", **start})
    return ws, ctx


async def test_invalid_timezone_dropped_valid_kept() -> None:
    _, ctx = await _boot(_handler(_form(FieldType.DATE), "tomorrow"), {"protocol_version": 2, "timezone": "Mars/Base"})
    assert ctx.state.timezone is None
    _, ctx = await _boot(_handler(_form(FieldType.DATE), "tomorrow"), {"protocol_version": 2, "timezone": "America/New_York"})
    assert ctx.state.timezone == "America/New_York"


async def test_v2_spoken_phone_canonical_and_confirm_value() -> None:
    h = _handler(_form(FieldType.PHONE), "0,4,12,523,573")
    ws, ctx = await _boot(h, {"protocol_version": 2})
    await h._process_binary(ws, ctx, _WEBM)
    acc = next(m for m in _msgs(ws) if m["type"] == "answer_accepted")
    assert acc["value"] == "0412523573"


async def test_v1_confirm_request_has_no_value() -> None:
    h = _handler(_form(FieldType.TIME), "three thirty")
    ws, ctx = await _boot(h, {})
    await h._process_binary(ws, ctx, _WEBM)
    cr = next(m for m in _msgs(ws) if m["type"] == "confirm_request")
    assert "value" not in cr and "refined_by" not in cr


async def test_llm_refine_ok_and_timeout() -> None:
    client = AsyncMock()
    client.ask.return_value = SimpleNamespace(structured_output=RefinedValue(value="john@gmail.com", confidence=0.95), output=None)
    h = _handler(_form(FieldType.EMAIL, voice={"llm_refine_values": True}), "john at gmail", llm_client_getter=lambda: client)
    ws, ctx = await _boot(h, {"protocol_version": 2})
    await h._process_binary(ws, ctx, _WEBM)
    assert next(m for m in _msgs(ws) if m["type"] == "answer_accepted")["value"] == "john@gmail.com"
    # FILL IN: a slow client (ask sleeps > llm_refine_timeout_s; use voice={"llm_refine_values": True,
    # "llm_refine_timeout_s": 0.05}) → falls back to rules → answer_rejected INVALID_EMAIL with value "john@gmail"


async def test_llm_unavailable_falls_back() -> None:
    # FILL IN: llm_refine_values True, no llm_client_getter → rules result (answer_rejected INVALID_EMAIL), no exception
    ...
```

### FILL IN checklist
- [ ] `_do_refine` result mapping
- [ ] timeout and unavailable test bodies
- [ ] confirm `FormSchema(voice=...)` accepts a dict (`VoiceFormConfig` coercion) — if not, pass `VoiceFormConfig(...)`

---

## Acceptance Criteria

- [ ] Invalid timezones never reach the engine; valid ones land in `AudioSessionState.timezone`.
- [ ] `RefineValue` → `ValueRefined` with ok / failed (exception or timeout) / unavailable; the turn always completes (AC6).
- [ ] v1 `confirm_request` / `answer_rejected` never carry `value` / `refined_by` (AC4).
- [ ] Existing adapter/integration suites pass unmodified.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_postprocess.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_adapter.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_v2_integration.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_integration.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. Work in the feature worktree: `python -m scripts.sdd.ensure_worktree --slug audio-form-voice-postprocessors --feature-id FEAT-653`.
2. Read the spec; check `Depends-on` tasks are `done` in `sdd/tasks/index/audio-form-voice-postprocessors.json`.
3. Verify the Codebase Contract before writing code.
4. Set this task `in-progress` in the index and commit only the index.
5. Implement from the blueprint; complete every `FILL IN`; never change a fixed name or path.
6. Run the Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`.
7. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4253 audio-form-voice-postprocessors verified`; fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
