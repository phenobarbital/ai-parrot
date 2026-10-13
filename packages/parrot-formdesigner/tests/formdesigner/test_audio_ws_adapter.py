"""FEAT-649 TASK-4227 — AudioFormWSHandler adapter I/O mapping."""

from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from parrot_formdesigner.api import audio_ws
from parrot_formdesigner.api.audio_ws import AudioFormWSHandler, _ConnCtx
from parrot_formdesigner.audio.models import AudioSessionState, Phase
from parrot_formdesigner.audio.session_store import SnapshotConflict
from parrot_formdesigner.core.llm_validation import LLMValidationConfig
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.plausibility import PlausibilityBlocked
from parrot_formdesigner.services.submission_pipeline import ValidationFailed

_TENANT = "t1"
_WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 512


def _form(*ids: str, required: bool = True, **kwargs) -> FormSchema:
    return FormSchema(
        form_id="f",
        title="T",
        tenant=_TENANT,
        sections=[
            FormSection(
                section_id="s1",
                fields=[
                    FormField(field_id=i, field_type=FieldType.TEXT, label=f"{i}?", required=required) for i in ids
                ],
            )
        ],
        **kwargs,
    )


def _ws() -> AsyncMock:
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    ws.send_bytes = AsyncMock()
    return ws


def _msgs(ws: AsyncMock) -> list[dict]:
    return [c[0][0] for c in ws.send_json.call_args_list]


def _types(ws: AsyncMock) -> list[str]:
    return [m["type"] for m in _msgs(ws)]


@pytest.fixture
def synth() -> AsyncMock:
    s = AsyncMock()
    s.synthesize.return_value = MagicMock(audio=b"AUDIO")
    return s


@pytest.fixture
def stt() -> AsyncMock:
    t = AsyncMock()
    t.transcribe.return_value = MagicMock(text="alice", confidence=0.95, language="en")
    return t


def _handler(form: FormSchema, synth: AsyncMock | None, stt: AsyncMock | None, **kw) -> AudioFormWSHandler:
    registry = AsyncMock()
    registry.get.return_value = form
    return AudioFormWSHandler(registry=registry, synthesizer=synth, transcriber=stt, validator=MagicMock(), **kw)


async def _boot(handler: AudioFormWSHandler, *, start: dict | None = None):
    ws = _ws()
    request = SimpleNamespace(match_info={"form_uid": "f1", "tenant": _TENANT}, headers={})
    ctx = _ConnCtx(
        request=request,
        user=SimpleNamespace(user_id="u1", raw_payload={"sub": "u1"}),
        tenant=_TENANT,
        state=AudioSessionState(session_id="s1", form_uid="f1", user_id="u1", tenant=_TENANT),
    )
    await handler._process_text(ws, ctx, {"type": "start_session", "form_uid": "f1", **(start or {})})
    return ws, ctx


def test_max_questions_constant_removed() -> None:
    """AC5: the module constant is gone."""
    assert not hasattr(audio_ws, "MAX_QUESTIONS")


class TestEncoding:
    async def test_v2_prefetch_sends_segment_header_then_bytes_before_question(self, synth, stt) -> None:
        ws, _ = await _boot(_handler(_form("a", "b"), synth, stt), start={"protocol_version": 2})
        types = _types(ws)
        assert types[0] == "session_started"
        first_q = types.index("question")
        headers = [i for i, t in enumerate(types) if t == "audio_segment"]
        assert headers and max(headers) < first_q
        assert ws.send_bytes.await_count == len(headers)
        assert all(c[0][0] == b"AUDIO" for c in ws.send_bytes.call_args_list)
        seg = _msgs(ws)[headers[0]]
        assert seg["key"] and seg["kind"] and seg["text"] and isinstance(seg["mime"], str)
        assert "audio" not in _msgs(ws)[first_q]  # prefetched: no inline base64

    async def test_v2_prefetch_off_inlines_audio(self, synth, stt) -> None:
        ws, _ = await _boot(_handler(_form("a"), synth, stt), start={"protocol_version": 2, "prefetch": False})
        assert "audio_segment" not in _types(ws)
        ws.send_bytes.assert_not_called()
        q = next(m for m in _msgs(ws) if m["type"] == "question")
        assert q["audio"] == base64.b64encode(b"AUDIO").decode()

    async def test_v1_question_carries_base64_audio(self, synth, stt) -> None:
        ws, _ = await _boot(_handler(_form("a"), synth, stt))
        assert "audio_segment" not in _types(ws)
        ws.send_bytes.assert_not_called()
        q = next(m for m in _msgs(ws) if m["type"] == "question")
        assert q["audio"] == base64.b64encode(b"AUDIO").decode()
        assert "narration" not in q and "section_uid" not in q
        started = next(m for m in _msgs(ws) if m["type"] == "session_started")
        assert "protocol_version" not in started

    async def test_v2_unknown_key_rejected_v1_ignored(self, synth, stt) -> None:
        h = _handler(_form("a"), synth, stt)
        msg = {"type": "answer_text", "field_id": "a", "value": "x", "bogus": 1}
        assert h._decode_text(msg, protocol_version=1).value == "x"
        with pytest.raises(ValidationError):
            h._decode_text(msg, protocol_version=2)
        assert h._decode_text({"type": "_transcript"}, protocol_version=2) is None

    async def test_v2_invalid_message_is_error(self, synth, stt) -> None:
        h = _handler(_form("a"), synth, stt)
        ws, ctx = await _boot(h, start={"protocol_version": 2})
        ws.send_json.reset_mock()
        await h._process_text(ws, ctx, {"type": "answer_text", "field_id": "a", "value": "x", "bogus": 1})
        assert _msgs(ws)[0]["code"] == "INVALID_MESSAGE"


class TestAdapterIO:
    async def test_replan_awaits_planner_and_feeds_plan_ready(self, synth, stt) -> None:
        h = _handler(_form("a", "b"), synth, stt)
        ws, ctx = await _boot(h)
        spy = AsyncMock(side_effect=ctx.engine.planner.replan)
        ctx.engine.planner.replan = spy
        await h._process_text(ws, ctx, {"type": "answer_text", "field_id": "a", "value": "x"})
        spy.assert_awaited()
        assert [m for m in _msgs(ws) if m["type"] == "question"][-1]["field_id"] == "b"

    async def test_transcribe_writes_temp_file_and_feeds_transcript(self, synth, stt) -> None:
        h = _handler(_form("a", "b"), synth, stt)
        ws, ctx = await _boot(h)
        ws.send_json.reset_mock()
        await h._process_binary(ws, ctx, _WEBM)
        path = stt.transcribe.call_args[0][0]
        assert isinstance(path, Path) and path.suffix == ".webm"
        assert not path.exists()  # cleaned up
        tr = next(m for m in _msgs(ws) if m["type"] == "transcription")
        assert tr["text"] == "alice" and tr["confidence"] == 0.95
        assert ctx.engine.state.answers["a"].value == "alice"
        assert ctx.engine.state.answers["a"].audio_mime == "audio/webm"

    async def test_decode_error_maps_to_audio_decode_error(self, synth, stt) -> None:
        stt.transcribe.side_effect = RuntimeError("libav boom")
        h = _handler(_form("a"), synth, stt)
        ws, ctx = await _boot(h)
        ws.send_json.reset_mock()
        await h._process_binary(ws, ctx, _WEBM)
        err = _msgs(ws)[0]
        assert err["type"] == "error" and err["code"] == "AUDIO_DECODE_ERROR"
        assert "a" not in ctx.engine.state.answers

    async def test_store_blob_calls_store_recording_and_feeds_blob_stored(self, synth, stt, monkeypatch) -> None:
        store = AsyncMock(return_value="blob-ref-1")
        monkeypatch.setattr(audio_ws, "store_recording", store)
        h = _handler(_form("a"), synth, stt, blob_storage=MagicMock())
        ws, ctx = await _boot(h)
        await h._process_binary(ws, ctx, _WEBM)
        store.assert_awaited_once()
        kw = store.call_args.kwargs
        assert kw["tenant"] == _TENANT and kw["session_id"] == "s1" and kw["mime"] == "audio/webm"
        assert ctx.engine.state.answers["a"].blob_ref == "blob-ref-1"

    async def test_store_blob_skipped_without_storage(self, synth, stt) -> None:
        h = _handler(_form("a"), synth, stt)
        ws, ctx = await _boot(h)
        await h._process_binary(ws, ctx, _WEBM)
        assert ctx.engine.state.answers["a"].blob_ref is None

    async def test_submit_uses_pipeline_with_url_tenant_and_auth_context(self, synth, stt) -> None:
        pipeline = MagicMock()
        pipeline.submit = AsyncMock(
            return_value=SimpleNamespace(submission_id="sub-9", stored_in="sink", forwarded=False)
        )
        storage = MagicMock()
        storage.store = AsyncMock()
        h = _handler(_form("a"), synth, stt, pipeline=pipeline, submission_storage=storage)
        ws, ctx = await _boot(h)
        ws.send_json.reset_mock()
        await h._process_text(ws, ctx, {"type": "answer_text", "field_id": "a", "value": "x"})
        kw = pipeline.submit.call_args.kwargs
        assert kw["tenant"] == _TENANT and kw["user_id"] == "u1" and kw["merge_session_id"] == "s1"
        assert kw["auth_context"].claims == {"sub": "u1"}
        assert kw["submission_id"] == ctx.state.submission_id
        done = next(m for m in _msgs(ws) if m["type"] == "form_complete")
        assert done["submission_id"] == "sub-9"
        assert done["answers"]["a"] == {"value": "x", "source": "text"}
        storage.store.assert_not_called()
        for call in h.registry.get.call_args_list:
            assert call.kwargs.get("tenant") == _TENANT

    async def test_validation_failure_becomes_validation_errors_and_reask(self, synth, stt) -> None:
        pipeline = MagicMock()
        pipeline.submit = AsyncMock(side_effect=ValidationFailed({"a": ["too short"]}))
        h = _handler(_form("a"), synth, stt, pipeline=pipeline)
        ws, ctx = await _boot(h)
        ws.send_json.reset_mock()
        await h._process_text(ws, ctx, {"type": "answer_text", "field_id": "a", "value": "x"})
        types = _types(ws)
        assert "validation_errors" in types and types[-1] == "question"
        assert next(m for m in _msgs(ws) if m["type"] == "validation_errors")["errors"] == {"a": ["too short"]}

    async def test_submit_failure_surfaces_error(self, synth, stt) -> None:
        pipeline = MagicMock()
        pipeline.submit = AsyncMock(side_effect=RuntimeError("db down"))
        h = _handler(_form("a"), synth, stt, pipeline=pipeline)
        ws, ctx = await _boot(h)
        ws.send_json.reset_mock()
        await h._process_text(ws, ctx, {"type": "answer_text", "field_id": "a", "value": "x"})
        assert next(m for m in _msgs(ws) if m["type"] == "error")["code"] == "SUBMIT_FAILED"
        assert "db down" not in str(_msgs(ws))

    async def test_plausibility_blocked_becomes_blocked_report(self, synth, stt) -> None:
        form = _form("a", llm_validation=LLMValidationConfig(enabled=True, on_error="block"))
        checker = MagicMock()
        checker.config = form.llm_validation
        checker.check = AsyncMock(side_effect=PlausibilityBlocked("llm down"))
        h = _handler(form, synth, stt)
        h._checker_for = lambda *_a, **_k: checker  # type: ignore[method-assign]
        ws, ctx = await _boot(h, start={"protocol_version": 2})
        ws.send_json.reset_mock()
        await h._process_text(ws, ctx, {"type": "answer_text", "field_id": "a", "value": "x"})
        checker.check.assert_awaited_once()
        assert any(m["type"] == "error" and m["code"] == "PLAUSIBILITY_UNAVAILABLE" for m in _msgs(ws))
        assert "review_start" in _types(ws)

    async def test_checker_built_per_form_config_once_per_session(self, synth, stt) -> None:
        cfg = LLMValidationConfig(enabled=True, threshold=0.9)
        form = _form("a", llm_validation=cfg)
        client = object()
        h = _handler(form, synth, stt, llm_client_getter=lambda: client)
        c1 = h._checker_for(form, session_id="s1")
        assert c1 is h._checker_for(form, session_id="s1")
        assert c1.config.threshold == 0.9 and c1._client is client
        plain = _handler(_form("a"), synth, stt)._checker_for(_form("a"), session_id="x")
        assert plain.config.enabled is False and plain._client is None


class TestSnapshots:
    async def test_snapshot_saved_after_transition_and_in_finally(self, synth, stt) -> None:
        store = MagicMock()
        store.claim_active = AsyncMock(return_value=True)
        store.save = AsyncMock(side_effect=[1, 2, 3])
        store.delete = AsyncMock()
        h = _handler(_form("a", "b"), synth, stt, session_store=store)
        ws, ctx = await _boot(h)
        await h._process_text(ws, ctx, {"type": "answer_text", "field_id": "a", "value": "x"})
        assert store.save.await_count == 1
        assert store.save.call_args.kwargs["expected_revision"] == 0
        assert ctx.revision == 1
        await h._autosave(ctx, final=True)
        assert store.save.await_count == 2
        assert store.save.call_args.kwargs["expected_revision"] == 1
        assert ctx.engine.state.phase == Phase.ASKING
        store.delete.assert_not_called()

    async def test_completed_session_is_released_not_saved(self, synth, stt) -> None:
        pipeline = MagicMock()
        pipeline.submit = AsyncMock(return_value=SimpleNamespace(submission_id="s", stored_in="none", forwarded=False))
        store = MagicMock()
        store.claim_active = AsyncMock(return_value=True)
        store.save = AsyncMock(return_value=1)
        store.delete = AsyncMock()
        h = _handler(_form("a"), synth, stt, pipeline=pipeline, session_store=store)
        ws, ctx = await _boot(h)
        await h._process_text(ws, ctx, {"type": "answer_text", "field_id": "a", "value": "x"})
        store.delete.assert_awaited()
        saves = store.save.await_count
        await h._autosave(ctx, final=True)
        assert store.save.await_count == saves

    async def test_no_store_is_noop(self, synth, stt) -> None:
        h = _handler(_form("a"), synth, stt)
        ws, ctx = await _boot(h)
        await h._autosave(ctx, final=True)  # must not raise

    async def test_snapshot_conflict_surfaces_error(self, synth, stt) -> None:
        store = MagicMock()
        store.claim_active = AsyncMock(return_value=True)
        store.save = AsyncMock(side_effect=SnapshotConflict("race"))
        h = _handler(_form("a", "b"), synth, stt, session_store=store)
        ws, ctx = await _boot(h)
        ws.send_json.reset_mock()
        await h._process_text(ws, ctx, {"type": "answer_text", "field_id": "a", "value": "x"})
        assert any(m["type"] == "error" and m["code"] == "RESUME_CONFLICT" for m in _msgs(ws))
        ws.close.assert_awaited()
        assert ctx.closed is True

    async def test_second_active_session_rejected(self, synth, stt) -> None:
        store = MagicMock()
        store.claim_active = AsyncMock(return_value=False)
        h = _handler(_form("a"), synth, stt, session_store=store)
        ws, ctx = await _boot(h)
        assert _msgs(ws)[0]["code"] == "SESSION_ACTIVE"
        assert ctx.engine is None

    async def test_resume_without_store_is_unavailable(self, synth, stt) -> None:
        h = _handler(_form("a"), synth, stt)
        ws, ctx = await _boot(h, start={"protocol_version": 2, "resume_session_id": "old"})
        assert _msgs(ws)[0]["code"] == "RESUME_UNAVAILABLE"

    async def test_resume_missing_snapshot_is_unavailable(self, synth, stt) -> None:
        store = MagicMock()
        store.load = AsyncMock(return_value=None)
        h = _handler(_form("a"), synth, stt, session_store=store)
        ws, ctx = await _boot(h, start={"protocol_version": 2, "resume_session_id": "old"})
        assert _msgs(ws)[0]["code"] == "RESUME_UNAVAILABLE"

    async def test_resume_roundtrip_from_snapshot(self, synth, stt) -> None:
        store = MagicMock()
        store.claim_active = AsyncMock(return_value=True)
        store.save = AsyncMock(return_value=1)
        store.delete = AsyncMock()
        form = _form("a", "b")
        h = _handler(form, synth, stt, session_store=store)
        ws, ctx = await _boot(h)
        await h._process_text(ws, ctx, {"type": "answer_text", "field_id": "a", "value": "x"})
        snap = ctx.engine.snapshot().model_copy(update={"revision": 4})
        store.load = AsyncMock(return_value=snap)
        h2 = _handler(form, synth, stt, session_store=store)
        ws2, ctx2 = await _boot(h2, start={"protocol_version": 2, "resume_session_id": "s1"})
        types = _types(ws2)
        assert "session_resumed" in types and types[-1] == "question"
        assert ctx2.revision == 4
        assert ctx2.engine.state.answers["a"].value == "x"
        assert [m for m in _msgs(ws2) if m["type"] == "question"][-1]["field_id"] == "b"


def _select_form() -> FormSchema:
    from parrot_formdesigner.core.options import FieldOption

    return FormSchema(
        form_id="f",
        title="T",
        tenant=_TENANT,
        sections=[
            FormSection(
                section_id="s1",
                fields=[
                    FormField(
                        field_id="c",
                        field_type=FieldType.SELECT,
                        label="Color?",
                        required=True,
                        options=[FieldOption(value="r", label="Red"), FieldOption(value="g", label="Green")],
                    ),
                ],
            )
        ],
    )


def test_segment_kind_new_keys() -> None:
    assert AudioFormWSHandler._segment_kind("q:u:options_intro") == "options"
    assert AudioFormWSHandler._segment_kind("q:u:opt:3") == "option"
    assert AudioFormWSHandler._segment_kind("q:u:label") == "question"
    assert AudioFormWSHandler._segment_kind("q:u:hint") == "hint"
    assert AudioFormWSHandler._segment_kind("q:u:options") == "options"
    assert AudioFormWSHandler._segment_kind("review:1") == "review"
    assert AudioFormWSHandler._segment_kind("sys:x") == "system"


class TestOptionSegments:
    async def test_do_synthesize_v2_emits_option_segments(self, synth, stt) -> None:
        ws, _ = await _boot(_handler(_select_form(), synth, stt), start={"protocol_version": 2})
        segs = [m for m in _msgs(ws) if m["type"] == "audio_segment"]
        kinds = [s["kind"] for s in segs]
        assert kinds.count("option") == 2
        intro = [s for s in segs if s["key"].endswith(":options_intro")]
        assert len(intro) == 1 and intro[0]["kind"] == "options"
        assert not [s for s in segs if s["key"].startswith("pause:")]
        assert ws.send_bytes.await_count == len(segs)

    async def test_do_synthesize_v1_inline_groups_option_keys(self, synth, stt) -> None:
        ws, _ = await _boot(_handler(_select_form(), synth, stt))
        texts = [c[0][0] for c in synth.synthesize.call_args_list]
        assert len(texts) == 1
        assert texts[0].endswith("1, Red. 2, Green.")
        q = next(m for m in _msgs(ws) if m["type"] == "question")
        assert q["audio"] == base64.b64encode(b"AUDIO").decode()
