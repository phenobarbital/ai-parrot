"""Unit tests for AgentVoiceTalk handler (TASK-1512, FEAT-231).

These tests exercise the two voice seams in isolation via the handler's
helper methods, using a ``__new__``-constructed instance (no aiohttp request
required) — the same pattern as ``test_agenttalk_resume_unit``.

Covered:
- audio attachment detection (_is_audio / _find_audio_attachment);
- inbound STT: audio tempfile transcribed and cleaned up;
- outbound TTS: only AIMessage.response is synthesized; output/data/media
  stay in content; audio_base64 + audio_format attached on success;
- graceful degradation to text-only when the synthesizer raises;
- a no-voice request falls through to the inherited text behaviour.
"""
from __future__ import annotations

import json
import wave

from aiohttp import web

from parrot.handlers.agent import AgentTalk
from parrot.handlers.agent_voice import AgentVoiceTalk


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_handler(did_transcribe: bool = True) -> AgentVoiceTalk:
    """Build an AgentVoiceTalk without going through the aiohttp view __init__."""
    handler = AgentVoiceTalk.__new__(AgentVoiceTalk)
    handler.post_init()
    handler._did_transcribe = did_transcribe
    return handler


def _write_wav(path) -> None:
    """Write a tiny valid mono 16 kHz WAV file."""
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 1600)


# ---------------------------------------------------------------------------
# Audio detection
# ---------------------------------------------------------------------------


def test_is_audio_by_mime_and_extension():
    h = _make_handler()
    assert h._is_audio({"mime_type": "audio/ogg", "file_name": "n.ogg"})
    assert h._is_audio({"mime_type": "", "file_name": "voice.wav"})
    assert h._is_audio({"mime_type": "video/webm", "file_name": "clip"})
    assert not h._is_audio({"mime_type": "image/png", "file_name": "p.png"})
    assert not h._is_audio({"mime_type": "", "file_name": "doc.pdf"})


def test_find_audio_attachment():
    h = _make_handler()
    attachments = {
        "files": [
            {"mime_type": "image/png", "file_name": "p.png"},
            {"mime_type": "audio/wav", "file_name": "voice.wav"},
        ]
    }
    info, field = h._find_audio_attachment(attachments)
    assert field == "files"
    assert info["file_name"] == "voice.wav"

    none_info, none_field = h._find_audio_attachment({"x": [{"mime_type": "text/plain", "file_name": "a.txt"}]})
    assert none_info is None and none_field is None


# ---------------------------------------------------------------------------
# Inbound STT
# ---------------------------------------------------------------------------


async def test_transcribe_attachment_cleans_tempfile(monkeypatch, tmp_path):
    """Audio tempfile is transcribed via VoiceTranscriber and then unlinked."""
    h = _make_handler()
    audio = tmp_path / "note.wav"
    _write_wav(audio)

    class _FakeResult:
        text = "hola mundo"

    class _FakeTranscriber:
        def __init__(self, config):
            pass

        async def transcribe_file(self, path):
            assert path == audio
            return _FakeResult()

        async def close(self):
            pass

    import parrot.voice.transcriber.transcriber as tmod
    monkeypatch.setattr(tmod, "VoiceTranscriber", _FakeTranscriber)

    file_info = {"file_path": audio, "file_name": "note.wav", "mime_type": "audio/wav"}
    text = await h._transcribe_attachment(file_info)

    assert text == "hola mundo"
    assert not audio.exists()  # tempfile cleaned up in finally


# ---------------------------------------------------------------------------
# Outbound TTS
# ---------------------------------------------------------------------------


async def test_voice_out_synthesizes_response_field_only():
    """TTS reads only AIMessage.response; output/data/media are untouched."""
    h = _make_handler()
    seen = {}

    async def fake_synth(text):
        seen["text"] = text
        return "QUk=", "audio/wav"

    h._synthesize = fake_synth
    envelope = {
        "response": "Hola, ¿en qué puedo ayudarte?",
        "output": {"secret": "do-not-speak"},
        "data": [1, 2, 3],
        "media": "/tmp/img.png",
    }
    out = await h._augment_with_audio(web.json_response(envelope))
    payload = json.loads(out.body)

    assert seen["text"] == "Hola, ¿en qué puedo ayudarte?"
    assert payload["audio_base64"] == "QUk="
    assert payload["audio_format"] == "audio/wav"
    # Non-speakable fields ride along untouched inside content.
    assert payload["output"] == {"secret": "do-not-speak"}
    assert payload["data"] == [1, 2, 3]
    assert payload["media"] == "/tmp/img.png"


async def test_envelope_has_audio_base64_on_success():
    h = _make_handler()

    async def fake_synth(text):
        return "QUk=", "audio/wav"

    h._synthesize = fake_synth
    out = await h._augment_with_audio(web.json_response({"response": "hi"}))
    payload = json.loads(out.body)
    assert "audio_base64" in payload and "audio_format" in payload


async def test_degrades_to_text_only_when_tts_raises():
    h = _make_handler()

    async def boom(text):
        raise RuntimeError("no tts backend")

    h._synthesize = boom
    original = web.json_response({"response": "hi", "content": "hi"})
    out = await h._augment_with_audio(original)
    payload = json.loads(out.body)

    assert "audio_base64" not in payload
    assert payload["content"] == "hi"
    assert out is original  # unchanged response returned


async def test_augment_ignores_non_json_response():
    h = _make_handler()
    html = web.Response(text="<html></html>", content_type="text/html")
    out = await h._augment_with_audio(html)
    assert out is html


# ---------------------------------------------------------------------------
# post() gate
#
# ``post()`` itself is wrapped by the @is_authenticated()/@user_session()
# class decorators (which require a real aiohttp request), so the full
# round-trip through post() is exercised in the TASK-1513 integration test
# (test_agent_voice_integration). Here we assert the inheritance contract that
# makes the override safe.
# ---------------------------------------------------------------------------


def test_subclasses_agenttalk_without_modifying_post():
    """AgentVoiceTalk subclasses AgentTalk and adds its own post override.

    The inherited text-path machinery (resolution, PBAC, envelope) is reused,
    not duplicated — the override only wraps super().post().
    """
    assert issubclass(AgentVoiceTalk, AgentTalk)
    # The override is defined on the subclass (not inherited verbatim).
    assert "post" in AgentVoiceTalk.__dict__
    assert "handle_upload" in AgentVoiceTalk.__dict__
    # Inherited inbound/outbound helper seams come from AgentTalk unchanged.
    assert AgentVoiceTalk._prepare_response is AgentTalk._prepare_response
    assert AgentVoiceTalk._resolve_bot is AgentTalk._resolve_bot
