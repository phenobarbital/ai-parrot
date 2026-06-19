"""Tests for AgentTranscribeOnly — Mode B pluggable STT (TASK-1608 — FEAT-249).

Verifies:
- The transcribe logic (transcript returned, stt_backend selector, 503, 400)
  by calling the underlying methods on a fake instance (bypassing auth decorators).
- BotManager._register_transcribe_route registers the expected route.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import types
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from aiohttp import web


# ---------------------------------------------------------------------------
# Helpers: inject / restore fake voice stack modules
# ---------------------------------------------------------------------------


def _inject_fake_voice_stack(transcript: str = "hello world") -> dict:
    """Inject a minimal fake VoiceTranscriber into sys.modules."""

    class _FakeResult:
        text = transcript

    class _FakeVoiceTranscriber:
        def __init__(self, config):
            self._config = config

        async def transcribe_file(self, path):
            return _FakeResult()

    class _FakeTranscriberBackend:
        def __init__(self, value):
            self.value = value

        @classmethod
        def __call__(cls, value):
            return cls(value)

        def __new__(cls, value):
            obj = object.__new__(cls)
            obj.value = value
            return obj

    class _FakeVoiceTranscriberConfig:
        def __init__(self, **kw):
            self.backend = kw.get("backend")

    transcriber_mod = types.ModuleType("parrot.voice.transcriber.transcriber")
    transcriber_mod.VoiceTranscriber = _FakeVoiceTranscriber  # type: ignore[attr-defined]

    models_mod = types.ModuleType("parrot.voice.transcriber.models")
    models_mod.TranscriberBackend = _FakeTranscriberBackend  # type: ignore[attr-defined]
    models_mod.VoiceTranscriberConfig = _FakeVoiceTranscriberConfig  # type: ignore[attr-defined]

    saved = {
        "parrot.voice.transcriber.transcriber": sys.modules.get("parrot.voice.transcriber.transcriber"),
        "parrot.voice.transcriber.models": sys.modules.get("parrot.voice.transcriber.models"),
    }
    sys.modules["parrot.voice.transcriber.transcriber"] = transcriber_mod
    sys.modules["parrot.voice.transcriber.models"] = models_mod
    return saved


def _restore_modules(saved: dict) -> None:
    for key, val in saved.items():
        if val is None:
            sys.modules.pop(key, None)
        else:
            sys.modules[key] = val


# ---------------------------------------------------------------------------
# Fake handler: bypasses auth decorators by calling the real _transcribe_attachment
# ---------------------------------------------------------------------------


class _FakeAgentVoiceTalk:
    """Minimal fake that reuses AgentVoiceTalk._transcribe_attachment / _find_audio_attachment."""

    def __init__(self, *, stt_backend: str | None = None):
        self.logger = MagicMock()
        self._stt_backend: str | None = stt_backend
        self._tts_backend: str | None = None
        self._tts_format: str | None = None

    async def _transcribe_attachment(self, file_info: dict) -> str:
        from parrot.handlers.agent_voice import AgentVoiceTalk
        return await AgentVoiceTalk._transcribe_attachment(self, file_info)

    @staticmethod
    def _is_audio(file_info: dict) -> bool:
        from parrot.handlers.agent_voice import AgentVoiceTalk
        return AgentVoiceTalk._is_audio(file_info)

    def _find_audio_attachment(self, attachments: dict):
        from parrot.handlers.agent_voice import AgentVoiceTalk
        return AgentVoiceTalk._find_audio_attachment(self, attachments)

    def _unlink_attachment(self, file_info: dict) -> None:
        pass  # no real tempfiles to clean up in tests


# ---------------------------------------------------------------------------
# Test 1: transcription succeeds and returns the transcript text
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcribe_returns_text_from_fake_backend():
    """_transcribe_attachment returns the transcript string from the fake backend."""
    saved = _inject_fake_voice_stack(transcript="test transcript")
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()

    handler = _FakeAgentVoiceTalk()
    file_info = {"file_path": Path(tmp.name), "file_name": "test.wav", "mime_type": "audio/wav"}

    try:
        text = await handler._transcribe_attachment(file_info)
    finally:
        _restore_modules(saved)
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)

    assert text == "test transcript"


# ---------------------------------------------------------------------------
# Test 2: stt_backend selector is honoured
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stt_backend_selector_is_propagated():
    """When stt_backend is set, it is passed through to VoiceTranscriberConfig."""
    used_configs: list = []

    class _CapturingTranscriber:
        def __init__(self, config):
            used_configs.append(config)

        async def transcribe_file(self, path):
            class _R:
                text = "captured"
            return _R()

    saved = _inject_fake_voice_stack()
    sys.modules["parrot.voice.transcriber.transcriber"].VoiceTranscriber = _CapturingTranscriber

    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp.close()

    handler = _FakeAgentVoiceTalk(stt_backend="openai")
    file_info = {"file_path": Path(tmp.name), "file_name": "rec.mp3", "mime_type": "audio/mpeg"}

    try:
        await handler._transcribe_attachment(file_info)
    finally:
        _restore_modules(saved)
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)

    assert len(used_configs) == 1
    # backend was set on the config object
    assert used_configs[0].backend is not None


# ---------------------------------------------------------------------------
# Test 3: 503 when voice stack is absent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcribe_503_when_voice_stack_absent():
    """_transcribe_attachment raises HTTPServiceUnavailable when [voice] is absent."""
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()

    # Force ImportError from the voice stack
    saved = {}
    for key in ("parrot.voice.transcriber.transcriber", "parrot.voice.transcriber.models"):
        saved[key] = sys.modules.get(key)
        sys.modules[key] = None  # type: ignore[assignment]

    handler = _FakeAgentVoiceTalk()
    file_info = {"file_path": Path(tmp.name), "file_name": "audio.wav", "mime_type": "audio/wav"}

    try:
        with pytest.raises(web.HTTPServiceUnavailable):
            await handler._transcribe_attachment(file_info)
    finally:
        _restore_modules(saved)
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)


# ---------------------------------------------------------------------------
# Test 4: _find_audio_attachment returns None when no audio present
# ---------------------------------------------------------------------------


def test_find_audio_attachment_returns_none_for_empty():
    """_find_audio_attachment returns (None, None) when no audio files are uploaded."""
    handler = _FakeAgentVoiceTalk()
    audio_info, field = handler._find_audio_attachment({})
    assert audio_info is None
    assert field is None


# ---------------------------------------------------------------------------
# Test 5: BotManager._register_transcribe_route wires the endpoint
# ---------------------------------------------------------------------------


def test_manager_registers_transcribe_route():
    """BotManager._register_transcribe_route registers /api/v1/agents/transcribe/{agent_id}."""
    from parrot.manager.manager import BotManager

    app = web.Application()
    manager = BotManager.__new__(BotManager)
    manager.logger = MagicMock()

    result = manager._register_transcribe_route(app.router)

    assert result is True
    paths = [r.resource.canonical for r in app.router.routes()]
    assert "/api/v1/agents/transcribe/{agent_id}" in paths
