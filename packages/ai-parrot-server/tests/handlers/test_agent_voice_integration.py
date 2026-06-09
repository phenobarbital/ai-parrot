"""Integration tests for the voice route wiring (TASK-1513, FEAT-231).

These tests verify:
- the voice route resolves to AgentVoiceTalk when registered the way
  manager.py registers it;
- an ImportError on the voice handler is guarded — the route is skipped, a
  warning is logged, and boot does not crash;
- the end-to-end data flow audio → STT → envelope → TTS → JSON
  ``{content, audio_base64, audio_format}`` (driven through the handler's real
  seams with stubbed voice services and a stub bot reply);
- PBAC/auth are inherited from AgentTalk unchanged (no re-implementation).
"""
from __future__ import annotations

import json
import wave
from unittest.mock import MagicMock

import pytest
from aiohttp import web

from parrot.handlers.agent import AgentTalk
from parrot.handlers.agent_voice import AgentVoiceTalk


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def short_wav_bytes() -> bytes:
    """Tiny valid mono 16 kHz WAV payload."""
    import io

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 1600)
    return buf.getvalue()


@pytest.fixture
def stub_bot():
    """A bot whose ask() returns a fixed AIMessage-like reply."""
    bot = MagicMock()
    reply = MagicMock()
    reply.response = "Hola, ¿en qué puedo ayudarte?"
    bot.ask.return_value = reply
    return bot


def _make_handler(did_transcribe: bool = True) -> AgentVoiceTalk:
    handler = AgentVoiceTalk.__new__(AgentVoiceTalk)
    handler.post_init()
    handler._did_transcribe = did_transcribe
    return handler


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_voice_route_registered():
    """POST /api/v1/agents/voice/{agent_id} resolves to AgentVoiceTalk."""
    app = web.Application()
    app.router.add_view('/api/v1/agents/voice/{agent_id}', AgentVoiceTalk)

    matched = [
        r for r in app.router.routes()
        if r.handler is AgentVoiceTalk
    ]
    assert matched, "AgentVoiceTalk route was not registered"
    resource = matched[0].resource
    assert resource is not None
    assert "/api/v1/agents/voice/" in resource.canonical


def test_register_voice_routes_helper_adds_route():
    """The manager helper registers the voice route on a real router."""
    from parrot.manager.manager import BotManager

    mgr = BotManager.__new__(BotManager)
    mgr.logger = MagicMock()
    app = web.Application()
    registered = mgr._register_voice_routes(app.router)

    assert registered is True
    assert any(r.handler is AgentVoiceTalk for r in app.router.routes())


def test_missing_voice_stack_skips_route_without_crash(monkeypatch):
    """ImportError on the voice handler → warning logged, route skipped, no crash."""
    from parrot.manager.manager import BotManager
    import builtins

    real_import = builtins.__import__

    def _failing_import(name, *args, **kwargs):
        if name.endswith("handlers.agent_voice") or name == "agent_voice":
            raise ImportError("simulated missing voice stack")
        # Relative imports surface via fromlist on the package module.
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _failing_import)

    mgr = BotManager.__new__(BotManager)
    mgr.logger = MagicMock()
    app = web.Application()

    registered = mgr._register_voice_routes(app.router)

    assert registered is False
    assert not any(r.handler is AgentVoiceTalk for r in app.router.routes())
    mgr.logger.warning.assert_called_once()


# ---------------------------------------------------------------------------
# End-to-end data flow (audio → STT → envelope → TTS → JSON)
# ---------------------------------------------------------------------------


async def test_voice_round_trip_end_to_end(monkeypatch, tmp_path, stub_bot):
    """audio → STT → bot reply envelope → TTS → JSON {content, audio_base64, audio_format}."""
    h = _make_handler()

    # --- Inbound STT: stub the transcriber to return the bot's expected input.
    audio = tmp_path / "note.wav"
    with wave.open(str(audio), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 1600)

    class _FakeResult:
        text = "¿quién eres?"

    class _FakeTranscriber:
        def __init__(self, config):
            pass

        async def transcribe_file(self, path):
            return _FakeResult()

        async def close(self):
            pass

    import parrot.voice.transcriber.transcriber as tmod
    monkeypatch.setattr(tmod, "VoiceTranscriber", _FakeTranscriber)

    transcript = await h._transcribe_attachment(
        {"file_path": audio, "file_name": "note.wav", "mime_type": "audio/wav"}
    )
    assert transcript == "¿quién eres?"
    assert not audio.exists()  # tempfile cleaned up

    # --- Text dispatch (LLM-agnostic): the stub bot answers the transcript.
    reply = stub_bot.ask(question=transcript)
    # Inherited JSON envelope shape (as built by AgentTalk._format_response).
    envelope = {
        "input": transcript,
        "output": {"structured": "not-spoken"},
        "data": None,
        "response": reply.response,
        "content": reply.response,
    }

    # --- Outbound TTS: stub the synthesizer.
    async def fake_synth(text):
        assert text == reply.response  # only AIMessage.response is synthesized
        return "QUk=", "audio/wav"

    h._synthesize = fake_synth
    out = await h._augment_with_audio(web.json_response(envelope))
    payload = json.loads(out.body)

    assert payload["content"] == reply.response
    assert payload["audio_base64"] == "QUk="
    assert payload["audio_format"] == "audio/wav"
    # Non-speakable structured output rode along untouched.
    assert payload["output"] == {"structured": "not-spoken"}


# ---------------------------------------------------------------------------
# Inherited PBAC / auth
# ---------------------------------------------------------------------------


def test_inherited_pbac_and_auth_apply_to_voice():
    """PBAC + auth seams are inherited from AgentTalk verbatim (no re-impl)."""
    # PBAC guard is the exact inherited method object — same policy behaviour.
    assert AgentVoiceTalk._check_pbac_agent_access is AgentTalk._check_pbac_agent_access
    # The voice subclass adds only the two voice seams over the text handler.
    assert "post" in AgentVoiceTalk.__dict__
    assert "handle_upload" in AgentVoiceTalk.__dict__
    assert issubclass(AgentVoiceTalk, AgentTalk)
