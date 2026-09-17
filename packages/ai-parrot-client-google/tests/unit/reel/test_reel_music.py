"""TASK-3327: music policy, isolated Lyria session and PCM->WAV tests.

Mocks the owner's `get_client()` and a fake `client.aio.live.music.connect()`
session (async-context-manager + async-generator `receive()`, matching the
real SDK shape used by the existing `generate_music_stream`), while the REAL
`ReelMusicService.generate()` policy/timeout/byte-bound/rate-verification
logic runs end to end.
"""

from __future__ import annotations

import asyncio
import time
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.clients.google.reel.errors import ReelError
from parrot.clients.google.reel.music import MusicOutcome, ReelMusicService, write_pcm_wav
from parrot.models.google import VideoReelRequest

FAR_DEADLINE = lambda: time.monotonic() + 30.0  # noqa: E731


def _request(**overrides) -> VideoReelRequest:
    defaults = {"prompt": "test reel"}
    defaults.update(overrides)
    return VideoReelRequest(**defaults)


def _chunk(data: bytes = b"AB", mime_type: str = "audio/pcm;rate=48000"):
    return SimpleNamespace(data=data, mime_type=mime_type)


class _FakeSession:
    """`receive()` is an async generator yielding one message per chunk, then hangs
    (simulating a still-open connection with no more data) ONLY when `hang=True` —
    used solely by the cancellation test; every other test's fake stream ends
    normally after its chunks, so the receiver's `finally: queue.put(None)`
    fires immediately and tests don't wait out the full receive budget."""

    def __init__(self, chunks, *, error: Exception | None = None, hang: bool = False):
        self._chunks = chunks
        self._error = error
        self._hang = hang
        self.set_weighted_prompts = AsyncMock()
        self.set_music_generation_config = AsyncMock()
        self.play = AsyncMock()

    async def receive(self):
        for chunk in self._chunks:
            yield SimpleNamespace(server_content=SimpleNamespace(audio_chunks=[chunk]))
        if self._error is not None:
            raise self._error
        if self._hang:
            await asyncio.sleep(3600)


class _FakeConnectCM:
    def __init__(self, session, *, connect_delay: float = 0.0, connect_error: Exception | None = None):
        self._session = session
        self._connect_delay = connect_delay
        self._connect_error = connect_error
        self.exited = False

    async def __aenter__(self):
        if self._connect_delay:
            await asyncio.sleep(self._connect_delay)
        if self._connect_error:
            raise self._connect_error
        return self._session

    async def __aexit__(self, *exc):
        self.exited = True
        return False


def _fake_client(connect_cm):
    client = MagicMock()
    client.aio = MagicMock()
    client.aio.live = MagicMock()
    client.aio.live.music = MagicMock()
    client.aio.live.music.connect = MagicMock(return_value=connect_cm)
    client.aio.aclose = AsyncMock()
    return client


def _fake_owner(client):
    owner = MagicMock()
    owner.get_client = AsyncMock(return_value=client)
    return owner


class TestPolicyShortCircuits:
    async def test_off_policy_makes_no_connection(self, tmp_path):
        owner = _fake_owner(MagicMock())
        service = ReelMusicService(owner, api_version="v1beta")

        outcome = await service.generate(
            _request(music_policy="off"), duration_seconds=20.0, output_directory=tmp_path, deadline=FAR_DEADLINE()
        )

        assert outcome == MusicOutcome(status="off")
        owner.get_client.assert_not_called()

    async def test_native_audio_mode_skips_regardless_of_policy(self, tmp_path):
        owner = _fake_owner(MagicMock())
        service = ReelMusicService(owner, api_version="v1beta")

        outcome = await service.generate(
            _request(audio_mode="native", music_policy="optional"),
            duration_seconds=20.0,
            output_directory=tmp_path,
            deadline=FAR_DEADLINE(),
        )

        assert outcome.status == "skipped"
        owner.get_client.assert_not_called()

    async def test_muted_audio_mode_skips(self, tmp_path):
        owner = _fake_owner(MagicMock())
        service = ReelMusicService(owner, api_version="v1beta")

        outcome = await service.generate(
            _request(audio_mode="muted"), duration_seconds=20.0, output_directory=tmp_path, deadline=FAR_DEADLINE()
        )

        assert outcome.status == "skipped"
        owner.get_client.assert_not_called()


class TestSuccessfulGeneration:
    async def test_writes_wav_with_verified_rate_and_documented_stereo_16bit(self, tmp_path):
        chunks = [
            _chunk(data=b"AB", mime_type="audio/pcm;rate=48000"),
            _chunk(data=b"CD", mime_type="audio/pcm;rate=48000"),
        ]
        session = _FakeSession(chunks)
        connect_cm = _FakeConnectCM(session)
        client = _fake_client(connect_cm)
        owner = _fake_owner(client)
        service = ReelMusicService(owner, api_version="v1beta")

        outcome = await service.generate(
            _request(music_policy="optional"), duration_seconds=0.01, output_directory=tmp_path, deadline=FAR_DEADLINE()
        )

        assert outcome.status == "succeeded"
        assert outcome.local_path.suffix == ".wav"
        with wave.open(str(outcome.local_path), "rb") as wf:
            assert wf.getframerate() == 48000
            assert wf.getnchannels() == 2
            assert wf.getsampwidth() == 2
            assert wf.readframes(wf.getnframes()) == b"ABCD"
        client.aio.aclose.assert_awaited_once()
        assert connect_cm.exited is True

    async def test_injected_api_version_used_to_build_client(self, tmp_path):
        chunks = [_chunk()]
        session = _FakeSession(chunks)
        connect_cm = _FakeConnectCM(session)
        client = _fake_client(connect_cm)
        owner = _fake_owner(client)
        service = ReelMusicService(owner, api_version="v1beta_custom")

        await service.generate(
            _request(music_policy="optional"), duration_seconds=0.01, output_directory=tmp_path, deadline=FAR_DEADLINE()
        )

        owner.get_client.assert_awaited_once_with(http_options={"api_version": "v1beta_custom"})

    async def test_synthesized_prompt_preserved_when_music_prompt_absent(self, tmp_path):
        chunks = [_chunk()]
        session = _FakeSession(chunks)
        connect_cm = _FakeConnectCM(session)
        client = _fake_client(connect_cm)
        owner = _fake_owner(client)
        service = ReelMusicService(owner, api_version="v1beta")

        await service.generate(
            _request(music_policy="optional", music_genre="Chillout"),
            duration_seconds=0.01,
            output_directory=tmp_path,
            deadline=FAR_DEADLINE(),
        )

        sent_prompts = session.set_weighted_prompts.call_args.kwargs["prompts"]
        assert "Background music for test reel" in sent_prompts[0].text
        # Matches the existing `_generate_reel_music` prompt-building convention
        # (generation.py:2265) verbatim: f"...{request.music_genre}" renders the
        # enum's repr, not its .value.
        assert "CHILLOUT" in sent_prompts[0].text


class TestOptionalFailureModes:
    async def test_connection_failure_returns_unavailable_outcome(self, tmp_path):
        session = _FakeSession([])
        connect_cm = _FakeConnectCM(session, connect_error=RuntimeError("no route to host"))
        client = _fake_client(connect_cm)
        owner = _fake_owner(client)
        service = ReelMusicService(owner, api_version="v1beta")

        outcome = await service.generate(
            _request(music_policy="optional"), duration_seconds=20.0, output_directory=tmp_path, deadline=FAR_DEADLINE()
        )

        assert outcome.status == "unavailable"
        assert outcome.warning is not None
        client.aio.aclose.assert_awaited_once()

    async def test_connection_handshake_timeout_returns_timeout_outcome(self, tmp_path):
        session = _FakeSession([])
        connect_cm = _FakeConnectCM(session, connect_delay=0.2)
        client = _fake_client(connect_cm)
        owner = _fake_owner(client)
        service = ReelMusicService(owner, api_version="v1beta", connect_timeout_seconds=0.05)

        outcome = await service.generate(
            _request(music_policy="optional"), duration_seconds=20.0, output_directory=tmp_path, deadline=FAR_DEADLINE()
        )

        assert outcome.status == "timeout"

    async def test_empty_stream_returns_unavailable_outcome(self, tmp_path):
        session = _FakeSession([])
        connect_cm = _FakeConnectCM(session)
        client = _fake_client(connect_cm)
        owner = _fake_owner(client)
        service = ReelMusicService(owner, api_version="v1beta")

        outcome = await service.generate(
            _request(music_policy="optional"), duration_seconds=0.05, output_directory=tmp_path, deadline=FAR_DEADLINE()
        )

        assert outcome.status == "unavailable"
        assert "no audio" in outcome.warning.lower()

    async def test_missing_mime_type_rate_never_guessed(self, tmp_path):
        """Core Q6 behavior: a chunk with no parseable rate must fail closed, never
        default to either of the two conflicting public sources (44.1kHz/48kHz)."""
        chunks = [_chunk(mime_type=None), _chunk(mime_type="")]
        session = _FakeSession(chunks)
        connect_cm = _FakeConnectCM(session)
        client = _fake_client(connect_cm)
        owner = _fake_owner(client)
        service = ReelMusicService(owner, api_version="v1beta")

        outcome = await service.generate(
            _request(music_policy="optional"), duration_seconds=0.01, output_directory=tmp_path, deadline=FAR_DEADLINE()
        )

        assert outcome.status == "unavailable"
        assert "rate" in outcome.warning.lower()

    async def test_inconsistent_declared_rates_returns_unavailable(self, tmp_path):
        chunks = [_chunk(mime_type="audio/pcm;rate=48000"), _chunk(mime_type="audio/pcm;rate=44100")]
        session = _FakeSession(chunks)
        connect_cm = _FakeConnectCM(session)
        client = _fake_client(connect_cm)
        owner = _fake_owner(client)
        service = ReelMusicService(owner, api_version="v1beta")

        outcome = await service.generate(
            _request(music_policy="optional"), duration_seconds=0.01, output_directory=tmp_path, deadline=FAR_DEADLINE()
        )

        assert outcome.status == "unavailable"
        assert "inconsistent" in outcome.warning.lower()

    async def test_byte_limit_exceeded_returns_unavailable(self, tmp_path):
        chunks = [_chunk(data=b"X" * 100) for _ in range(5)]
        session = _FakeSession(chunks)
        connect_cm = _FakeConnectCM(session)
        client = _fake_client(connect_cm)
        owner = _fake_owner(client)
        service = ReelMusicService(owner, api_version="v1beta", max_bytes=250)

        outcome = await service.generate(
            _request(music_policy="optional"), duration_seconds=0.05, output_directory=tmp_path, deadline=FAR_DEADLINE()
        )

        assert outcome.status == "unavailable"
        assert "byte" in outcome.warning.lower()


class TestRequiredPolicyRaises:
    async def test_required_policy_raises_reel_error_on_connection_failure(self, tmp_path):
        session = _FakeSession([])
        connect_cm = _FakeConnectCM(session, connect_error=RuntimeError("boom"))
        client = _fake_client(connect_cm)
        owner = _fake_owner(client)
        service = ReelMusicService(owner, api_version="v1beta")

        with pytest.raises(ReelError):
            await service.generate(
                _request(music_policy="required"),
                duration_seconds=20.0,
                output_directory=tmp_path,
                deadline=FAR_DEADLINE(),
            )

    async def test_required_policy_succeeds_normally_when_available(self, tmp_path):
        chunks = [_chunk()]
        session = _FakeSession(chunks)
        connect_cm = _FakeConnectCM(session)
        client = _fake_client(connect_cm)
        owner = _fake_owner(client)
        service = ReelMusicService(owner, api_version="v1beta")

        outcome = await service.generate(
            _request(music_policy="required"), duration_seconds=0.01, output_directory=tmp_path, deadline=FAR_DEADLINE()
        )

        assert outcome.status == "succeeded"


class TestReceiverCancellation:
    async def test_receiver_task_joined_on_cancellation(self, tmp_path):
        """A generate() call cancelled mid-stream must still close the owned
        client (the receiver task is joined, not leaked)."""
        session = _FakeSession([_chunk()], hang=True)  # stays "open" until cancelled
        connect_cm = _FakeConnectCM(session)
        client = _fake_client(connect_cm)
        owner = _fake_owner(client)
        service = ReelMusicService(owner, api_version="v1beta")

        task = asyncio.create_task(
            service.generate(
                _request(music_policy="optional"),
                duration_seconds=100.0,  # long budget, so cancellation must come from outside
                output_directory=tmp_path,
                deadline=FAR_DEADLINE(),
            )
        )
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        client.aio.aclose.assert_awaited_once()


class TestWritePcmWav:
    def test_round_trip_matches_metadata_exactly(self, tmp_path):
        pcm = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        dest = write_pcm_wav(pcm, tmp_path / "out", sample_rate=48000, channels=2, sample_width=2)

        assert dest.suffix == ".wav"
        with wave.open(str(dest), "rb") as wf:
            assert wf.getframerate() == 48000
            assert wf.getnchannels() == 2
            assert wf.getsampwidth() == 2
            assert wf.getnframes() == 2  # 8 bytes / (2 channels * 2-byte width) = 2 frames
            assert wf.readframes(wf.getnframes()) == pcm

    def test_enforces_wav_suffix(self, tmp_path):
        dest = write_pcm_wav(b"\x00\x00", tmp_path / "out.raw", sample_rate=24000, channels=1, sample_width=2)
        assert dest.name == "out.wav"

    def test_rejects_invalid_metadata(self, tmp_path):
        with pytest.raises(ValueError):
            write_pcm_wav(b"\x00\x00", tmp_path / "out", sample_rate=0, channels=2, sample_width=2)
