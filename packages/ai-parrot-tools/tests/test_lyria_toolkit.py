"""Tests for LyriaToolkit and Google Lyria music generation tools."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import wave

import pytest

from parrot.models.google import MusicGenre, MusicMood
from parrot_tools import TOOL_REGISTRY
from parrot_tools.google.audio_utils import (
    save_pcm_to_wav,
    seconds_to_pcm_bytes,
    slice_wav_file,
)
from parrot_tools.google.lyria import LyriaToolkit
from parrot_tools.google.lyria_models import (
    LyriaMusicParameters,
    parse_natural_music_request,
)


@pytest.fixture
def mock_pcm_chunk():
    """100ms chunk of 48kHz stereo 16-bit PCM (19,200 bytes)."""
    return b"\x00" * 19200


@pytest.fixture
def mock_client(mock_pcm_chunk):
    """Mock GoogleGenAIClient exposing generate_music_stream/batch."""

    class _MockClient:
        async def generate_music_stream(self, *args, **kwargs):
            for _ in range(120):  # 12 seconds worth of chunks
                yield mock_pcm_chunk

        async def generate_music_batch(self, *args, **kwargs):
            raise NotImplementedError

    return _MockClient()


class TestLyriaModels:
    """Unit tests for LyriaMusicParameters/LyriaMusicResult and NLP heuristics."""

    def test_default_parameters(self):
        p = LyriaMusicParameters(prompt="test")
        assert p.duration_seconds == 10
        assert p.bpm == 90
        assert p.density == 0.5
        assert p.brightness == 0.5
        assert p.temperature == 1.0

    def test_parameter_boundaries(self):
        with pytest.raises(Exception):
            LyriaMusicParameters(prompt="test", duration_seconds=0)
        with pytest.raises(Exception):
            LyriaMusicParameters(prompt="test", duration_seconds=150)
        with pytest.raises(Exception):
            LyriaMusicParameters(prompt="test", bpm=40)
        with pytest.raises(Exception):
            LyriaMusicParameters(prompt="test", bpm=250)

    def test_parse_natural_music_request_ambient_slow(self):
        p = parse_natural_music_request("a soft ambient music with slow tempo")
        assert p.duration_seconds == 10  # default
        assert p.bpm == 70  # slow tempo
        assert p.density == 0.3  # soft
        # "Ambient" is not a MusicGenre enum member (only a MusicMood
        # member) — genre is a free-form Optional[str], so the literal
        # string is what the heuristic parser produces here.
        assert p.genre == "Ambient"
        assert p.mood in ("Ambient", "Subdued Melody", "Chill")

    def test_parse_natural_music_request_explicit_duration(self):
        p = parse_natural_music_request("energetic techno beat for 25 seconds")
        assert p.duration_seconds == 25
        assert p.bpm == 130
        assert p.genre == MusicGenre.TECHNO.value


class TestAudioUtils:
    """Unit tests for PCM/WAV framing utilities."""

    def test_seconds_to_pcm_bytes(self):
        assert seconds_to_pcm_bytes(1.0) == 192000
        assert seconds_to_pcm_bytes(10.0) == 1920000

    def test_save_pcm_to_wav(self, tmp_path):
        pcm = b"\x00" * 192000  # 1 second
        out = tmp_path / "out.wav"
        res = save_pcm_to_wav(pcm, out)
        assert res.exists()

        with wave.open(str(res), "rb") as wf:
            assert wf.getframerate() == 48000
            assert wf.getnchannels() == 2
            assert wf.getsampwidth() == 2
            assert wf.getnframes() == 48000

    def test_slice_wav_file(self, tmp_path):
        # 3 seconds of PCM audio.
        pcm = b"\x00" * (192000 * 3)
        src = save_pcm_to_wav(pcm, tmp_path / "src.wav")
        dst = slice_wav_file(src, tmp_path / "dst.wav", 1.0)

        with wave.open(str(dst), "rb") as wf:
            assert wf.getnframes() == 48000
            assert wf.getframerate() == 48000


class TestLyriaToolkit:
    """Unit and integration tests for LyriaToolkit."""

    def test_tool_generation(self):
        tk = LyriaToolkit()
        tools = tk.get_tools()
        names = {t.name for t in tools}
        assert "lyria_generate_music" in names
        assert "lyria_list_genres_and_moods" in names
        assert "lyria_parse_music_prompt" in names

    @pytest.mark.asyncio
    async def test_generate_music_streaming_success(self, mock_client, tmp_path):
        tk = LyriaToolkit(client=mock_client, output_dir=tmp_path)
        res = await tk.generate_music(
            prompt="soft ambient music",
            duration_seconds=10,
            bpm=70,
            genre="Ambient",
        )
        assert res["status"] == "success"
        assert res["duration_seconds"] == 10.0
        out_file = Path(res["file_path"])
        assert out_file.exists()

        with wave.open(str(out_file), "rb") as wf:
            assert wf.getframerate() == 48000
            assert wf.getnchannels() == 2
            assert wf.getsampwidth() == 2
            assert wf.getnframes() == 48000 * 10

    @pytest.mark.asyncio
    async def test_generate_music_custom_duration(self, mock_client, tmp_path):
        tk = LyriaToolkit(client=mock_client, output_dir=tmp_path)
        res = await tk.generate_music(prompt="soft ambient music", duration_seconds=5)
        assert res["status"] == "success"
        assert res["duration_seconds"] == 5.0
        assert res["size_bytes"] > 0

        # Exactly 5 * 192,000 = 960,000 PCM bytes plus the fixed 44-byte
        # RIFF/WAVE header written by the stdlib `wave` module.
        assert res["size_bytes"] == 960000 + 44

    @pytest.mark.asyncio
    async def test_generate_music_batch_mode(self, tmp_path):
        batch_wav = save_pcm_to_wav(b"\x00" * (192000 * 30), tmp_path / "raw_batch.wav")

        class _BatchClient:
            async def generate_music_batch(self, *args, **kwargs):
                return [batch_wav]

        tk = LyriaToolkit(client=_BatchClient(), output_dir=tmp_path, mode="batch")
        res = await tk.generate_music(prompt="a calm piano piece", duration_seconds=7)

        assert res["status"] == "success"
        assert res["duration_seconds"] == 7.0
        out_file = Path(res["file_path"])
        assert out_file.exists()
        with wave.open(str(out_file), "rb") as wf:
            assert wf.getnframes() == 48000 * 7

    @pytest.mark.asyncio
    async def test_list_genres_and_moods(self):
        tk = LyriaToolkit()
        catalog = await tk.list_genres_and_moods()
        assert set(catalog["genres"]) == {g.value for g in MusicGenre}
        assert set(catalog["moods"]) == {m.value for m in MusicMood}
        assert catalog["genres"]
        assert catalog["moods"]

    @pytest.mark.asyncio
    async def test_lazy_client_error(self, monkeypatch):
        tk = LyriaToolkit()

        def _raise_import_error(*args, **kwargs):
            raise ImportError("no module named 'parrot.clients.google.client'")

        # Force the lazy import inside _get_client to fail, simulating a
        # missing ai-parrot-client-google installation.
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "parrot.clients.google.client":
                raise ImportError("No module named 'parrot.clients.google.client'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        with pytest.raises(RuntimeError, match="GoogleGenAIClient is not available"):
            await tk._get_client()

    def test_discovery_registry(self):
        assert TOOL_REGISTRY["lyria"] == "parrot_tools.google.lyria.LyriaToolkit"
        assert TOOL_REGISTRY["google_lyria"] == "parrot_tools.google.lyria.LyriaToolkit"


class TestLyriaToolkitReviewFixes:
    """Regression tests for issues raised in the FEAT-534 code review.

    Covers: batch-mode lazy client missing vertexai=True, an unhandled
    RuntimeError escaping generate_music() when the client is unavailable,
    batch-mode misreporting the requested (not actual) duration, and the
    auto_open=False lifecycle gap that made _close() unreachable via the
    standard ToolManager.cleanup_toolkits() path.
    """

    @pytest.mark.asyncio
    async def test_batch_mode_lazy_client_requests_vertexai(self, monkeypatch):
        """_get_client() must pass vertexai=True when mode='batch'."""
        import sys
        import types

        captured = {}

        class _FakeGoogleGenAIClient:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        fake_module = types.ModuleType("parrot.clients.google.client")
        fake_module.GoogleGenAIClient = _FakeGoogleGenAIClient
        monkeypatch.setitem(sys.modules, "parrot.clients.google.client", fake_module)

        tk = LyriaToolkit(mode="batch")
        await tk._get_client()
        assert captured.get("vertexai") is True

        tk2 = LyriaToolkit(mode="stream")
        captured.clear()
        await tk2._get_client()
        assert captured.get("vertexai") is False

    @pytest.mark.asyncio
    async def test_generate_music_returns_error_dict_on_missing_client(self, monkeypatch):
        """generate_music() must not raise when the client is unavailable."""
        tk = LyriaToolkit()

        async def _raise(*args, **kwargs):
            raise RuntimeError(
                "GoogleGenAIClient is not available. Ensure ai-parrot-client-google is installed: boom"
            )

        monkeypatch.setattr(tk, "_get_client", _raise)
        res = await tk.generate_music(prompt="test")
        assert res["status"] == "error"
        assert "not available" in res["error"]

    @pytest.mark.asyncio
    async def test_batch_mode_reports_actual_duration_not_requested(self, tmp_path):
        """Batch result must reflect the ACTUAL sliced duration, not the request."""
        # Source batch WAV is only 5 seconds — shorter than the requested 60s.
        short_batch_wav = save_pcm_to_wav(b"\x00" * (192000 * 5), tmp_path / "raw.wav")

        class _BatchClient:
            async def generate_music_batch(self, *args, **kwargs):
                return [short_batch_wav]

        tk = LyriaToolkit(client=_BatchClient(), output_dir=tmp_path, mode="batch")
        res = await tk.generate_music(prompt="test", duration_seconds=60)
        assert res["status"] == "success"
        # Must report the actual ~5s duration, not the requested 60s.
        assert res["duration_seconds"] == pytest.approx(5.0, abs=0.01)
        assert res["sample_rate"] == 48000
        assert res["channels"] == 2

    @pytest.mark.asyncio
    async def test_auto_open_lifecycle_closes_owned_client(self):
        """auto_open=True must flip _opened so cleanup_toolkits() can _close()."""
        from parrot.tools.manager import ToolManager

        mock_client = MagicMock()
        mock_client.close = AsyncMock()

        tk = LyriaToolkit()  # no injected client -> owns its own lazily

        async def fake_get_client():
            tk._client = mock_client
            return mock_client

        tk._get_client = fake_get_client

        manager = ToolManager()
        manager.register_toolkit(tk)
        tool = manager.get_tool("lyria_list_genres_and_moods")

        assert tk._opened is False
        await tool.execute()
        assert tk._opened is True

        await manager.cleanup_toolkits()
        mock_client.close.assert_awaited_once()


class TestLyriaEndToEnd:
    """Integration test: LyriaToolkit registered with ToolManager."""

    @pytest.mark.asyncio
    async def test_end_to_end_agent_tool_calling(self, mock_client, tmp_path):
        from parrot.tools.manager import ToolManager

        toolkit = LyriaToolkit(client=mock_client, output_dir=tmp_path)
        manager = ToolManager()
        manager.register_toolkit(toolkit)

        tool = manager.get_tool("lyria_generate_music")
        assert tool is not None

        result = await tool.execute(
            prompt="soft ambient music",
            duration_seconds=5,
            bpm=70,
            genre="Ambient",
        )

        payload = result.result if hasattr(result, "result") else result
        assert payload["status"] == "success"
        out_file = Path(payload["file_path"])
        assert out_file.exists()
        with wave.open(str(out_file), "rb") as wf:
            assert wf.getnframes() == 48000 * 5
