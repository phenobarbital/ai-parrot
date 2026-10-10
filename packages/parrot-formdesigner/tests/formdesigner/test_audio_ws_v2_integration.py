"""FEAT-649 TASK-4228 — audio WS end-to-end over aiohttp (v2, commands, resume, block mode, adversarial)."""
from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import WSMsgType, web

from parrot_formdesigner.api.routes import setup_form_api
from parrot_formdesigner.core.constraints import ConditionOperator, DependencyRule, FieldCondition
from parrot_formdesigner.core.llm_validation import LLMValidationConfig
from parrot_formdesigner.core.resolution import resolve_rule_references
from parrot_formdesigner.core.options import FieldOption
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.core.voice import VoiceFormConfig
from parrot_formdesigner.services.partial_saves import PartialSaveStore
from parrot_formdesigner.services.plausibility import PlausibilityBatch
from parrot_formdesigner.services.submissions import FormSubmissionStorage

_TENANT = "navigator"
WS_URL = "/api/v1/{tenant}/forms/{uid}/audio/ws"
_WAV = b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 244


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _DictRedis:
    """Minimal async Redis stub: get / set(nx, ex) / setex / eval(CAS) / delete / expire / close."""

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

    async def eval(self, script: str, numkeys: int, key: str, expected: str, new: str, ttl: int) -> int:
        """Emulates AudioSessionStore's compare-and-set script."""
        if self.data.get(key, "") == expected:
            self.data[key] = new
            return 1
        return 0

    async def delete(self, *keys: str) -> int:
        return sum(1 for k in keys if self.data.pop(k, None) is not None)

    async def expire(self, key: str, ttl: int) -> bool:
        return key in self.data

    async def close(self) -> None:
        return None


class _InMemoryPartialStore(PartialSaveStore):
    """PartialSaveStore whose ``_get_redis()`` returns a shared _DictRedis (pattern: test_partial_saves_integration)."""

    def __init__(self, redis: _DictRedis) -> None:
        super().__init__(ttl_seconds=3600)
        self._fake = redis

    async def _get_redis(self) -> Any:
        return self._fake


class FakeLLM:
    """Plausibility client: scripted verdicts per field, call counter, optional failure."""

    def __init__(self, low: tuple[str, ...] = (), exc: Exception | None = None) -> None:
        self.calls: list[str] = []
        self.low = set(low)
        self.exc = exc

    async def ask(self, prompt: str, **kwargs: Any) -> Any:
        self.calls.append(prompt)
        if self.exc:
            raise self.exc
        items = [
            {"field_id": fid, "plausible": fid not in self.low, "confidence": 0.1 if fid in self.low else 0.95,
             "reason": "odd" if fid in self.low else "ok"}
            for fid in ("name", "color", "agree", "comment")
        ]
        batch = PlausibilityBatch.model_validate({"items": items})
        return type("Msg", (), {"structured_output": batch, "output": batch})()


class FakeSynth:
    """Deterministic TTS: bytes derived from the text; counts calls."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.config = MagicMock(mime_format="audio/wav")

    async def synthesize(self, text: str, language: str | None = None) -> Any:
        self.calls.append(text)
        return MagicMock(audio=b"TTS:" + text.encode()[:32])


class FakeBlobStorage:
    """In-memory AbstractBlobStorage stand-in (put/delete only)."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def put(self, stream: Any, *, metadata: Any) -> str:
        data = b"".join([c async for c in stream])
        ref = f"mem://{metadata.blob_id}"
        self.blobs[ref] = data
        return ref

    async def delete(self, blob_ref: str) -> None:
        self.blobs.pop(blob_ref, None)


def _voice_form(**kwargs: Any) -> FormSchema:
    """Spec §4 fixture: SELECT (with a disabled option), BOOLEAN, TEXT with hint, PASSWORD, dependent TEXT."""
    form = FormSchema(
        form_id="voice-form",
        title="Voice Form",
        tenant=_TENANT,
        is_public=True,
        sections=[
            FormSection(section_id="s1", title="About you", fields=[
                FormField(field_id="name", field_type=FieldType.TEXT, label="What is your name?", required=True,
                          hint="Your full name"),
                FormField(field_id="color", field_type=FieldType.SELECT, label="Favourite color", required=True,
                          options=[FieldOption(value="red", label="Red"), FieldOption(value="green", label="Green"),
                                   FieldOption(value="blue", label="Blue"),
                                   FieldOption(value="teal", label="Teal", disabled=True)]),
                FormField(field_id="agree", field_type=FieldType.BOOLEAN, label="Do you agree?", required=True),
            ]),
            FormSection(section_id="s2", title="Details", fields=[
                FormField(field_id="secret", field_type=FieldType.PASSWORD, label="Pick a passphrase", required=True),
                FormField(field_id="comment", field_type=FieldType.TEXT, label="Any comment?", required=False,
                          depends_on=DependencyRule(
                              conditions=[FieldCondition(field_id="agree", operator=ConditionOperator.EQ,
                                                         value=True)],
                              effect="show")),
            ]),
        ],
        voice=VoiceFormConfig(),
        llm_validation=kwargs.pop("llm_validation", LLMValidationConfig(enabled=True)),
        **kwargs,
    )
    return resolve_rule_references(form)


class _Env:
    """Everything a test needs: app, form, fakes."""

    def __init__(self, form: FormSchema, llm: FakeLLM) -> None:
        self.form = form
        self.llm = llm
        self.redis = _DictRedis()
        self.partial_store = _InMemoryPartialStore(self.redis)
        self.blobs = FakeBlobStorage()
        self.synth = FakeSynth()
        self.stored: list[tuple[Any, ...]] = []
        self.transcripts: list[tuple[str, float]] = []
        self.storage = MagicMock(spec=FormSubmissionStorage)
        self.storage.store = AsyncMock(side_effect=self._store)
        self.transcriber = AsyncMock()
        self.transcriber.transcribe.side_effect = self._transcribe
        registry = AsyncMock()
        registry.get.return_value = form
        validator = AsyncMock()
        from parrot.voice.handler import AuthenticatedUser  # type: ignore[import-untyped]

        validator.validate.return_value = AuthenticatedUser(user_id="test-user", username="testuser")
        self.app = web.Application()
        setup_form_api(
            self.app, registry, client=llm, submission_storage=self.storage, blob_storage=self.blobs,
            partial_store=self.partial_store, synthesizer=self.synth, transcriber=self.transcriber,
            token_validator=validator,
        )
        pipeline = self.app["submission_pipeline"]
        pipeline.submit = AsyncMock(wraps=pipeline.submit)  # spy; the audio adapter holds this same instance

    async def _store(self, *args: Any, **kwargs: Any) -> str:
        self.stored.append((args, kwargs))
        return "sub-1"

    async def _transcribe(self, path: Any, language: str | None = None) -> Any:
        text, conf = self.transcripts.pop(0)
        return MagicMock(text=text, confidence=conf, language="en", duration_seconds=1.0)

    @property
    def url(self) -> str:
        return WS_URL.format(tenant=_TENANT, uid=self.form.form_uid)


@pytest.fixture
def voice_form() -> FormSchema:
    return _voice_form()


@pytest.fixture
def voice_app(voice_form: FormSchema) -> _Env:
    return _Env(voice_form, FakeLLM())


# ---------------------------------------------------------------------------
# WS helpers
# ---------------------------------------------------------------------------


async def recv(ws: Any, timeout: float = 5.0) -> Any:
    msg = await asyncio.wait_for(ws.receive(), timeout)
    if msg.type == WSMsgType.TEXT:
        return json.loads(msg.data)
    if msg.type == WSMsgType.BINARY:
        return msg.data
    return {"type": "_closed", "ws_type": str(msg.type)}


async def until(ws: Any, *stop: str, limit: int = 60) -> list[Any]:
    """Collect frames (JSON dicts and raw bytes) up to and including the first message of a ``stop`` type."""
    out: list[Any] = []
    for _ in range(limit):
        m = await recv(ws)
        out.append(m)
        if isinstance(m, dict) and m.get("type") in stop:
            return out
    raise AssertionError(f"no {stop} in {[m.get('type') if isinstance(m, dict) else 'bin' for m in out]}")


def types(frames: list[Any]) -> list[str]:
    return [m["type"] if isinstance(m, dict) else "<bin>" for m in frames]


def jsons(frames: list[Any], t: str) -> list[dict]:
    return [m for m in frames if isinstance(m, dict) and m["type"] == t]


async def sync(ws: Any) -> list[Any]:
    """Barrier: ping and drain everything up to the pong (the engine answers frames in order)."""
    await ws.send_json({"type": "ping"})
    return await until(ws, "pong")


async def connect(client: Any, env: _Env) -> Any:
    return await client.ws_connect(env.url, protocols=["test-jwt-token"])


async def start(ws: Any, env: _Env, **extra: Any) -> list[Any]:
    await ws.send_json({"type": "start_session", "form_uid": str(env.form.form_uid), "protocol_version": 2, **extra})
    return await until(ws, "question", "error", "review_start")


async def say(ws: Any, env: _Env, text: str, conf: float = 0.95, *stop: str) -> list[Any]:
    env.transcripts.append((text, conf))
    await ws.send_bytes(_WAV)
    return await until(ws, *(stop or ("question", "review_start", "confirm_request", "answer_rejected", "error",
                                       "command_ack")))


def _http_request(form_uid: str, body: dict | None = None, *, method: str = "POST", merge: bool = False,
                  session_id: str = "http-sess") -> MagicMock:
    """Handler-level request double (the /partial and submit routes sit behind navigator-auth in production)."""
    req = MagicMock(spec=web.Request)
    req.match_info = {"form_uid": form_uid}
    req.method = method
    req.__contains__ = lambda self, key: key == "session"
    req.__getitem__ = lambda self, key: {"id": session_id} if key == "session" else None
    req.get = MagicMock(side_effect=lambda key, default=None: _TENANT if key == "tenant" else default)
    req.session = {"session": {"programs": [_TENANT]}}
    req.json = AsyncMock(return_value=body if body is not None else {})
    req.query = MagicMock()
    req.query.get = MagicMock(side_effect=lambda key, default="": "true" if merge and key == "merge_partials" else default)
    return req


async def _fill(ws: Any, env: _Env, *, agree: bool = True) -> list[Any]:
    """Answer name → color → agree → secret (→ comment skipped); returns frames up to ``review_start``."""
    await ws.send_json({"type": "answer_text", "field_id": "name", "value": "Ann"})
    await until(ws, "question")
    await ws.send_json({"type": "answer_selection", "field_id": "color", "value": "red"})
    await until(ws, "question")
    await ws.send_json({"type": "answer_selection", "field_id": "agree", "value": agree})
    await until(ws, "question")
    await ws.send_json({"type": "answer_text", "field_id": "secret", "value": "hunter2"})
    frames = await until(ws, "question", "review_start")
    if frames[-1]["type"] == "question":  # the optional, dependent "comment" field
        assert frames[-1]["field_id"] == "comment"
        await ws.send_json({"type": "skip_question", "field_id": "comment"})
        frames += await until(ws, "review_start")
    return frames


class TestAudioWsV2Integration:
    async def test_audio_ws_v1_client_still_works(self, aiohttp_client, voice_app: _Env) -> None:
        """AC1: a v1 client (no protocol_version, extra keys) sees the legacy wire and submits without review."""
        env = voice_app
        client = await aiohttp_client(env.app)
        ws = await connect(client, env)
        await ws.send_json({"type": "start_session", "form_uid": str(env.form.form_uid), "bogus": 1})
        frames = await until(ws, "question", "error")
        kinds = types(frames)
        assert kinds[0] == "session_started" and "audio_segment" not in kinds and "<bin>" not in kinds
        assert "protocol_version" not in frames[0]
        q = jsons(frames, "question")[0]
        assert q["field_id"] == "name" and q.get("audio")  # base64 inline narration
        await ws.send_json({"type": "ping", "extra": "x"})
        assert (await until(ws, "pong"))[-1]["type"] == "pong"
        await ws.send_json({"type": "answer_text", "field_id": "name", "value": "Ann", "zzz": 1})
        assert "answer_accepted" in types(await until(ws, "question"))
        await ws.close()

    async def test_audio_ws_v2_prefetch_review_submit(self, aiohttp_client, voice_app: _Env) -> None:
        env = voice_app
        client = await aiohttp_client(env.app)
        ws = await connect(client, env)
        frames = await start(ws, env)
        kinds = types(frames)
        assert kinds[0] == "session_started" and frames[0]["protocol_version"] == 2
        assert kinds.index("audio_segment") < kinds.index("question")
        # every segment header is followed by its binary frame (AC3)
        for i, m in enumerate(frames):
            if isinstance(m, dict) and m["type"] == "audio_segment":
                assert isinstance(frames[i + 1], bytes) and frames[i + 1].startswith(b"TTS:")
        assert "audio" not in jsons(frames, "question")[0]
        assert env.synth.calls  # prefetch synthesised the narration up-front

        review = await _fill(ws, env)
        rs = review[-1]
        assert rs["type"] == "review_start"
        shown = {it["field_id"] for it in rs["items"]}
        assert {"name", "color", "agree", "secret"} <= shown
        assert "hunter2" not in json.dumps(rs)  # S8: sensitive answers never echoed in the review

        # plausibility ran before the review was confirmed, once, without the sensitive field (AC12)
        pl = jsons(review, "plausibility_result")
        assert pl and pl[0]["status"] == "ok"
        assert len(env.llm.calls) == 1 and "hunter2" not in env.llm.calls[0]

        await ws.send_json({"type": "review_confirm", "confirmed": True})
        done = await until(ws, "form_complete", "error", "validation_errors")
        fc = done[-1]
        assert fc["type"] == "form_complete", [m for m in done if isinstance(m, dict) and m["type"] in ("validation_errors", "error")]
        assert fc["submission_id"] and "hunter2" not in json.dumps(fc)
        # AC9: the audio submission went through the shared pipeline into the sink, preserving the URL tenant
        env.storage.store.assert_awaited_once()
        sub = env.storage.store.call_args.args[0]
        assert sub.context.get("channel") == "audio"
        assert env.app["submission_pipeline"].submit.await_args.kwargs["tenant"] == _TENANT
        await ws.close()

    async def test_audio_ws_commands_and_go_back(self, aiohttp_client, voice_app: _Env) -> None:
        env = voice_app
        client = await aiohttp_client(env.app)
        ws = await connect(client, env)
        await start(ws, env)
        await ws.send_json({"type": "answer_text", "field_id": "name", "value": "Ann"})
        await until(ws, "question")  # now asking "color"
        fr = await say(ws, env, "repeat", 0.95, "question")
        assert [m for m in jsons(fr, "command_ack") if m["command"] == "repeat"]
        assert jsons(fr, "question")[-1]["field_id"] == "color"
        fr = await say(ws, env, "back", 0.95, "question")
        assert [m for m in jsons(fr, "command_ack") if m["command"] == "back"]
        assert jsons(fr, "question")[-1]["field_id"] == "name"
        # explicit go_back to the very first question is a no-op error-free repeat, then the flow proceeds
        await ws.send_json({"type": "answer_text", "field_id": "name", "value": "Bob"})
        assert jsons(await until(ws, "question"), "question")[-1]["field_id"] == "color"
        await ws.send_json({"type": "go_back"})
        fr = await until(ws, "question", "error")
        assert jsons(fr, "question")[-1]["field_id"] == "name"
        await ws.close()

    async def test_audio_ws_resume_cross_channel(self, aiohttp_client, voice_app: _Env) -> None:
        env = voice_app
        client = await aiohttp_client(env.app)
        ws = await connect(client, env)
        frames = await start(ws, env)
        sid = frames[0]["session_id"]
        await ws.send_json({"type": "answer_text", "field_id": "name", "value": "Ann"})
        await until(ws, "question")
        await ws.send_json({"type": "answer_selection", "field_id": "color", "value": "green"})
        await until(ws, "question")
        await ws.close()
        await asyncio.sleep(0.2)  # let the server finish its disconnect autosave

        audio_keys = [k for k in env.redis.data if k.startswith("parrot:audio:")]
        assert audio_keys, "snapshot should be stored under the audio prefix"

        ws2 = await connect(client, env)
        await ws2.send_json({"type": "start_session", "form_uid": str(env.form.form_uid), "protocol_version": 2,
                             "resume_session_id": sid})
        frames = await until(ws2, "question", "error")
        resumed = jsons(frames, "session_resumed")
        assert resumed and set(resumed[0]["answered"]) == {"name", "color"}
        assert jsons(frames, "question")[-1]["field_id"] == "agree"
        await ws2.close()

        # HTTP side: /partial only ever holds scalar answers, never the audio snapshot (AC16)
        handler = env.app["form_api_handler"]
        uid = str(env.form.form_uid)
        resp = await handler.save_partial(_http_request(uid, {"answers": {"agree": True}}))
        assert resp.status == 200
        body = json.loads((await handler.get_partial(_http_request(uid, method="GET"))).body)
        assert set(body["data"]).isdisjoint({"phase", "answer_meta", "cursor", "history", "blob_refs"})
        assert "answer_meta" not in json.dumps(body)
        # ... and a merge_partials HTTP submit completes the same form (cross-channel)
        resp = await handler.submit_data(_http_request(
            uid, {"name": "Ann", "color": "green", "secret": "x"}, merge=True))
        assert resp.status == 200, resp.body
        stored = env.storage.store.call_args.args[0]
        assert stored.data["agree"] is True and stored.data["name"] == "Ann"

    async def test_http_submit_with_plausibility_block_mode(self, aiohttp_client) -> None:
        down = FakeLLM(exc=RuntimeError("llm down"))
        env = _Env(_voice_form(llm_validation=LLMValidationConfig(enabled=True, on_error="block")), down)
        handler = env.app["form_api_handler"]
        uid = str(env.form.form_uid)
        body = {"name": "Ann", "color": "red", "agree": True, "secret": "pw"}
        resp = await handler.submit_data(_http_request(uid, dict(body)))
        assert resp.status == 503 and json.loads(resp.body)["code"] == "PLAUSIBILITY_UNAVAILABLE"
        env.storage.store.assert_not_called()  # AC13: retryable, nothing stored

        env2 = _Env(_voice_form(llm_validation=LLMValidationConfig(enabled=True, on_error="skip")),
                    FakeLLM(exc=RuntimeError("llm down")))
        resp = await env2.app["form_api_handler"].submit_data(_http_request(uid, dict(body)))
        assert resp.status == 200 and json.loads(resp.body)["plausibility"]["status"] == "skipped"
        env2.storage.store.assert_awaited_once()

    async def test_audio_adversarial_suite(self, aiohttp_client, voice_app: _Env) -> None:
        env = voice_app
        client = await aiohttp_client(env.app)
        ws = await connect(client, env)
        await start(ws, env)

        # a wrong-field answer never moves the cursor (WRONG_FIELD), also for a duplicated frame after it moved
        await ws.send_json({"type": "answer_text", "field_id": "name", "value": "Ann"})
        await until(ws, "question")
        await ws.send_json({"type": "answer_text", "field_id": "name", "value": "Ann again"})
        err = await until(ws, "error")
        assert err[-1]["code"] == "WRONG_FIELD"
        await sync(ws)

        # an option outside the field's options is rejected, not stored
        await ws.send_json({"type": "answer_selection", "field_id": "color", "value": "purple"})
        fr = await until(ws, "error")
        assert fr[-1]["code"] == "INVALID_OPTION" and "answer_accepted" not in types(fr)
        await sync(ws)
        fr = await say(ws, env, "purple", 0.95)
        assert "answer_accepted" not in types(fr)
        await sync(ws)
        await ws.send_json({"type": "answer_selection", "field_id": "color", "value": "blue"})
        await until(ws, "question")

        # hidden / required flips mid-session: agree=False hides "comment"; flipping back re-shows it
        await ws.send_json({"type": "answer_selection", "field_id": "agree", "value": False})
        fr = await until(ws, "question")
        assert fr[-1]["field_id"] == "secret"
        # a sensitive answer is never echoed back
        await ws.send_json({"type": "answer_text", "field_id": "secret", "value": "s3cr3t-phrase"})
        fr = await until(ws, "review_start", "question", "error")
        assert "s3cr3t-phrase" not in json.dumps(fr, default=str)
        assert fr[-1]["type"] == "review_start"
        assert "comment" not in {it["field_id"] for it in fr[-1]["items"]}

        await ws.send_json({"type": "review_edit", "field_id": "agree"})
        await until(ws, "question")
        await ws.send_json({"type": "answer_selection", "field_id": "agree", "value": True})
        fr = await until(ws, "question", "review_start")
        assert fr[-1]["type"] == "question" and fr[-1]["field_id"] == "comment"
        assert any(m["type"] == "plan_updated" for m in jsons(fr, "plan_updated"))
        await ws.close()

        # one active session per user (AC16): a second concurrent start is refused
        busy = await connect(client, env)
        await busy.send_json({"type": "start_session", "form_uid": str(env.form.form_uid), "protocol_version": 2})
        assert (await until(busy, "error", "question"))[-1].get("code") == "SESSION_ACTIVE"
        await busy.close()

        # v2 is strict: an unknown key is an INVALID_MESSAGE error, the session survives
        env2 = _Env(_voice_form(), FakeLLM())
        client2 = await aiohttp_client(env2.app)
        ws2 = await connect(client2, env2)
        await start(ws2, env2)
        await ws2.send_json({"type": "answer_text", "field_id": "name", "value": "x", "bogus": 1})
        assert (await until(ws2, "error"))[-1]["code"] == "INVALID_MESSAGE"
        await ws2.send_json({"type": "ping"})
        assert (await until(ws2, "pong"))[-1]["type"] == "pong"
        await ws2.close()

    @pytest.mark.xfail(strict=True, reason=(
        "DEFECT (renderers/audio.py, outside TASK-4228 scope): AudioFormRenderer drops FieldOption.disabled when "
        "building manifest options, so the engine's disabled-option guard (S4) never sees it."))
    async def test_audio_ws_disabled_option_rejected(self, aiohttp_client, voice_app: _Env) -> None:
        env = voice_app
        client = await aiohttp_client(env.app)
        ws = await connect(client, env)
        await start(ws, env)
        await ws.send_json({"type": "answer_text", "field_id": "name", "value": "Ann"})
        await until(ws, "question")
        await ws.send_json({"type": "answer_selection", "field_id": "color", "value": "teal"})
        fr = await until(ws, "error", "answer_rejected", "question")
        assert "answer_accepted" not in types(fr)
        await ws.close()

    def test_routes_pass_shared_pipeline_and_session_store(self, voice_app: _Env) -> None:
        from parrot_formdesigner.audio.session_store import AudioSessionStore

        env = voice_app
        audio = next(r.handler.__self__ for r in env.app.router.routes()
                     if r.resource is not None and r.resource.canonical.endswith("/audio/ws"))
        assert audio._pipeline is env.app["submission_pipeline"]  # AC9: one pipeline for HTTP and audio
        assert audio._blob_storage is env.blobs
        assert isinstance(audio._session_store, AudioSessionStore)
        assert audio._session_store.partial_store is env.partial_store
        assert audio._llm_client_getter.__self__ is env.app["form_api_handler"]

        bare = web.Application()
        setup_form_api(bare, AsyncMock(), transcriber=AsyncMock())
        audio2 = next(r.handler.__self__ for r in bare.router.routes()
                      if r.resource is not None and r.resource.canonical.endswith("/audio/ws"))
        assert audio2._session_store is None and audio2._pipeline is bare["submission_pipeline"]

    def test_routes_import_stays_light(self) -> None:
        import subprocess
        import sys

        code = ("import sys, parrot_formdesigner.api.routes; "
                "bad = [m for m in ('parrot.voice', 'parrot_formdesigner.audio.session_store', "
                "'parrot_formdesigner.api.audio_ws') if m in sys.modules]; "
                "sys.exit(1 if bad else 0)")
        assert subprocess.run([sys.executable, "-c", code]).returncode == 0
