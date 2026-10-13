"""FEAT-653 TASK-4253 — WS adapter: timezone, LLM refine I/O, v1 encoding (real aiohttp round trips)."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

import pytest

from parrot_formdesigner.api.audio_ws import AudioFormWSHandler
from parrot_formdesigner.audio.events import RefineValue
from parrot_formdesigner.audio.value_refiner import RefinedValue
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.core.voice import VoiceFormConfig
from parrot_formdesigner.services.validators import FormValidator

from .test_audio_ws_v2_integration import _TENANT, _Env, connect, jsons, say, start, sync, until, _WAV


class RefineLLM:
    """Fake LLM client for the value refiner: scripted answer, optional delay / failure, call counter."""

    def __init__(self, value: str | None = None, confidence: float = 0.95, *, delay: float = 0.0, exc=None) -> None:
        self.value, self.confidence, self.delay, self.exc = value, confidence, delay, exc
        self.calls: list[str] = []

    async def ask(self, prompt: str, **kwargs: Any) -> Any:
        self.calls.append(prompt)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.exc:
            raise self.exc
        return SimpleNamespace(
            structured_output=RefinedValue(value=self.value, confidence=self.confidence), output=None
        )


def _form(ft: FieldType, **voice: Any) -> FormSchema:
    return FormSchema(
        form_id="pp-form",
        title="PP",
        tenant=_TENANT,
        is_public=True,
        sections=[
            FormSection(
                section_id="s1",
                title="S",
                fields=[FormField(field_id="a", field_type=ft, label="Answer", required=True)],
            )
        ],
        voice=VoiceFormConfig(**voice),
    )


STOP = ("review_start", "confirm_request", "answer_rejected", "error")


async def _spoken(aiohttp_client, form: FormSchema, text: str, *, conf: float = 0.95, llm=None, **start_kw: Any):
    env = _Env(form, llm or RefineLLM())
    client = await aiohttp_client(env.app)
    ws = await connect(client, env)
    await start(ws, env, **start_kw)
    frames = await say(ws, env, text, conf, *STOP)
    return env, ws, frames


async def test_audio_ws_postprocess_v2(aiohttp_client) -> None:
    env, ws, frames = await _spoken(aiohttp_client, _form(FieldType.PHONE), "0,4,12,523,573")
    assert jsons(frames, "answer_accepted")[0]["value"] == "0412523573"
    await ws.close()
    env, ws, frames = await _spoken(aiohttp_client, _form(FieldType.TIME), "three thirty")
    cr = jsons(frames, "confirm_request")[0]
    assert cr["value"] == "03:30" and cr["refined_by"] == "rules"
    await ws.close()
    env, ws, frames = await _spoken(aiohttp_client, _form(FieldType.EMAIL), "john at gmail")
    rej = jsons(frames, "answer_rejected")[0]
    assert rej["code"] == "INVALID_EMAIL" and rej["value"] == "john@gmail"
    await ws.close()


@pytest.mark.parametrize(
    "field_type,text,expected",
    [
        (FieldType.NUMBER, "twenty five hundred", 2500),
        (FieldType.NUMBER, "two and a half", 2.5),
        (FieldType.INTEGER, "twelve hundred", 1200),
        (FieldType.DATE, "June fifth twenty twenty five", "2025-06-05"),
        (FieldType.TIME, "quarter past three pm", "15:15"),
        (FieldType.PHONE, "plus one 212 555 0100", "+12125550100"),
        (FieldType.EMAIL, "john dot smith at gmail dot com", "john.smith@gmail.com"),
    ],
)
async def test_audio_ws_postprocess_accepted_value_passes_form_validator(
    aiohttp_client, field_type: FieldType, text: str, expected: Any
) -> None:
    """The value the socket accepts is the typed canonical value, and the submit gate takes it as-is."""
    form = _form(field_type)
    _, ws, frames = await _spoken(aiohttp_client, form, text)
    accepted = jsons(frames, "answer_accepted")
    assert accepted and accepted[0]["value"] == expected
    await ws.close()
    result = await FormValidator().validate(form, {"a": accepted[0]["value"]})
    assert result.is_valid, result.errors


async def test_audio_ws_postprocess_v1_compat(aiohttp_client) -> None:
    env = _Env(_form(FieldType.TIME), RefineLLM())
    client = await aiohttp_client(env.app)
    ws = await connect(client, env)
    await ws.send_json({"type": "start_session", "form_uid": str(env.form.form_uid)})
    await until(ws, "question", "error")
    env.transcripts.append(("three thirty", 0.95))
    await ws.send_bytes(_WAV)
    frames = await until(ws, *STOP)
    cr = jsons(frames, "confirm_request")[0]
    assert "value" not in cr and "refined_by" not in cr
    await ws.close()
    env = _Env(_form(FieldType.EMAIL), RefineLLM())
    client = await aiohttp_client(env.app)
    ws = await connect(client, env)
    await ws.send_json({"type": "start_session", "form_uid": str(env.form.form_uid)})
    await until(ws, "question", "error")
    env.transcripts.append(("john at gmail", 0.95))
    await ws.send_bytes(_WAV)
    frames = await until(ws, *STOP)
    rej = jsons(frames, "answer_rejected")[0]
    assert rej["code"] == "INVALID_EMAIL" and "value" not in rej
    await ws.close()


async def test_audio_ws_timezone_validation(aiohttp_client, caplog) -> None:
    """A valid zone makes "tomorrow" certain (accepted); an invalid one is dropped, so it needs confirmation."""
    _, ws, frames = await _spoken(aiohttp_client, _form(FieldType.DATE), "tomorrow", timezone="America/New_York")
    assert jsons(frames, "answer_accepted") and not jsons(frames, "confirm_request")
    await ws.close()
    with caplog.at_level(logging.WARNING):
        _, ws, frames = await _spoken(aiohttp_client, _form(FieldType.DATE), "tomorrow", timezone="Mars/Base")
    assert jsons(frames, "confirm_request")[0]["value"]
    assert any("invalid timezone" in r.getMessage() for r in caplog.records)
    await ws.close()
    _, ws, frames = await _spoken(aiohttp_client, _form(FieldType.DATE), "tomorrow")
    assert jsons(frames, "confirm_request")  # absent timezone → UTC → confirmation
    await ws.close()


async def test_audio_ws_llm_refine_ok(aiohttp_client) -> None:
    llm = RefineLLM("john@gmail.com", 0.95)
    form = _form(FieldType.EMAIL, llm_refine_values=True)
    _, ws, frames = await _spoken(aiohttp_client, form, "john at gmail", llm=llm)
    # product decision 2: the LLM never turns a rules confirm into an accept
    assert not jsons(frames, "answer_accepted")
    cr = jsons(frames, "confirm_request")[0]
    assert cr["value"] == "john@gmail.com" and cr["refined_by"] == "llm"
    assert len(llm.calls) == 1 and "john at gmail" in llm.calls[0]
    await ws.close()


async def test_audio_ws_llm_refine_low_confidence_confirms(aiohttp_client) -> None:
    llm = RefineLLM("john@gmail.com", 0.3)
    form = _form(FieldType.EMAIL, llm_refine_values=True)
    _, ws, frames = await _spoken(aiohttp_client, form, "john at gmail", llm=llm)
    cr = jsons(frames, "confirm_request")[0]
    assert cr["value"] == "john@gmail.com" and cr["refined_by"] == "llm"
    await ws.close()


async def test_audio_ws_llm_refine_timeout(aiohttp_client) -> None:
    llm = RefineLLM("john@gmail.com", 0.95, delay=1.0)
    form = _form(FieldType.EMAIL, llm_refine_values=True, llm_refine_timeout_s=0.05)
    _, ws, frames = await _spoken(aiohttp_client, form, "john at gmail", llm=llm)
    rej = jsons(frames, "answer_rejected")[0]  # rules result (rejected) stands; the turn is not lost
    assert rej["code"] == "INVALID_EMAIL" and rej["value"] == "john@gmail"
    await ws.close()


async def test_audio_ws_llm_refine_failure_keeps_rules_value(aiohttp_client) -> None:
    llm = RefineLLM(exc=RuntimeError("boom"))
    form = _form(FieldType.PHONE, llm_refine_values=True)
    _, ws, frames = await _spoken(aiohttp_client, form, "five five five oh one two three", llm=llm)
    assert jsons(frames, "answer_accepted")[0]["value"] == "5550123"
    await ws.close()


async def test_refiner_unavailable_without_client() -> None:
    handler = object.__new__(AudioFormWSHandler)
    handler._refiners = {}
    handler._llm_client_getter = None
    handler.logger = logging.getLogger("test")
    ctx = SimpleNamespace(
        engine=SimpleNamespace(cfg=VoiceFormConfig()), state=SimpleNamespace(session_id="s", locale="en", timezone=None)
    )
    item = RefineValue(
        field_id="a", request_id="r1", transcript="t", candidate=None, field_type="email", label="A", today="2026-10-12"
    )
    result = await handler._do_refine(ctx, item)
    assert result.status == "unavailable" and result.request_id == "r1"
    assert handler._refiner_for("s") is None


async def test_audio_ws_client_cannot_forge_value_refined(aiohttp_client) -> None:
    """A client can never inject the internal ValueRefined event: the inbound model rejects it, the session lives.

    (Renamed from ``test_audio_ws_refine_stale_reply``: it never exercised the stale-reply check, because the
    forged frame is dropped before the engine sees it. The stale ``request_id`` check is covered where it lives,
    in ``test_audio_engine_llm_refine.py::test_stale_reply_ignored``.)
    """
    llm = RefineLLM("john@gmail.com", 0.95)
    form = _form(FieldType.EMAIL, llm_refine_values=True)
    _, ws, frames = await _spoken(aiohttp_client, form, "john at gmail", llm=llm)
    assert len(jsons(frames, "confirm_request")) == 1
    await ws.send_json(
        {"type": "_value_refined", "field_id": "a", "request_id": "x", "status": "ok", "value": "z@z.io"}
    )
    after = await sync(ws)
    assert not jsons(after, "answer_accepted") and after[-1]["type"] == "pong"
    assert not any(f.get("value") == "z@z.io" for f in after if isinstance(f, dict))
    await ws.close()
