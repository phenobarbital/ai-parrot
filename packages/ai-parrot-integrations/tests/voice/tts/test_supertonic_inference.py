"""
Unit tests for the Supertonic 4-graph ONNX inference wiring.

Tests cover:
- UnicodeProcessor tokenisation against a list-style indexer.
- chunk_text paragraph/sentence splitting.
- SupertonicPipeline runs the four graphs in order with the exact tensor
  feed keys upstream expects, and returns int16 PCM.
- SupertonicONNXBackend lazily builds the pipeline, wires it as inference_fn,
  aligns the WAV sample rate, and produces a playable WAV.

ONNX sessions are faked (no real weights / no onnxruntime graph load), so the
suite runs anywhere.
"""

import io
import json
import wave

import numpy as np
import pytest

from parrot.voice.tts.supertonic_inference import (
    SupertonicONNXBackend,
    SupertonicPipeline,
    UnicodeProcessor,
    chunk_text,
)

# ---------------------------------------------------------------------------
# Fake ONNX sessions + model dir
# ---------------------------------------------------------------------------


class _FakeSession:
    """Stand-in for ort.InferenceSession keyed by the graph it represents."""

    def __init__(self, kind: str, recorder: dict) -> None:
        self.kind = kind
        self.recorder = recorder

    def run(self, output_names, feed):  # noqa: D401 - mimics ORT signature
        self.recorder.setdefault(self.kind, []).append(set(feed.keys()))
        if self.kind == "duration_predictor":
            return [np.array([0.5], dtype=np.float32)]
        if self.kind == "text_encoder":
            length = feed["text_ids"].shape[1]
            return [np.zeros((1, 8, length), dtype=np.float32)]
        if self.kind == "vector_estimator":
            # Echo the latent unchanged so its shape flows to the vocoder.
            return [feed["noisy_latent"]]
        if self.kind == "vocoder":
            # 20000 samples > 24000 * (0.5/1.05) so trimming is exercised.
            return [np.zeros((1, 20000), dtype=np.float32)]
        raise AssertionError(f"unexpected graph: {self.kind}")


def _build_model_dir(tmp_path):
    """Create a fake Supertonic model directory (no real ONNX bytes)."""
    onnx_dir = tmp_path / "onnx"
    voices_dir = tmp_path / "voice_styles"
    onnx_dir.mkdir()
    voices_dir.mkdir()

    for name in (
        "duration_predictor",
        "text_encoder",
        "vector_estimator",
        "vocoder",
    ):
        (onnx_dir / f"{name}.onnx").write_bytes(b"\x00")

    cfgs = {
        "ae": {"sample_rate": 24000, "base_chunk_size": 256},
        "ttl": {"chunk_compress_factor": 2, "latent_dim": 4},
    }
    (onnx_dir / "tts.json").write_text(json.dumps(cfgs))

    # Identity codepoint table covering Latin-1 (test text is ASCII).
    (onnx_dir / "unicode_indexer.json").write_text(json.dumps(list(range(256))))

    style = {
        "style_ttl": {"dims": [1, 2, 3], "data": [0.0] * 6},
        "style_dp": {"dims": [1, 2, 2], "data": [0.0] * 4},
    }
    (voices_dir / "M1.json").write_text(json.dumps(style))
    return tmp_path


@pytest.fixture
def fake_onnx(monkeypatch):
    """Patch onnxruntime.InferenceSession to return graph-aware fakes."""
    import onnxruntime

    recorder: dict = {}

    def _factory(path, sess_options=None, providers=None):
        kind = path.rsplit("/", 1)[-1].replace(".onnx", "")
        return _FakeSession(kind, recorder)

    monkeypatch.setattr(onnxruntime, "InferenceSession", _factory)
    return recorder


# ---------------------------------------------------------------------------
# Tokeniser + chunking
# ---------------------------------------------------------------------------


def test_unicode_processor_list_indexer(tmp_path):
    """UnicodeProcessor maps codepoints through a list indexer and lang-wraps."""
    indexer = tmp_path / "unicode_indexer.json"
    indexer.write_text(json.dumps(list(range(256))))
    proc = UnicodeProcessor(str(indexer))

    text_ids, text_mask = proc(["Hi"], ["en"])

    # "<en>Hi.</en>" — identity table means id == codepoint.
    assert text_ids.shape[0] == 1
    assert text_ids[0, 0] == ord("<")
    assert text_mask.shape[1] == 1  # (B, 1, L)
    # Unknown language downgrades to English instead of raising.
    ids_unknown, _ = proc(["Hi"], ["zz"])
    assert ids_unknown[0, 0] == ord("<")


def test_chunk_text_splits_sentences():
    """Long text splits into <= max_len chunks on sentence boundaries."""
    text = "First sentence here. Second sentence follows. Third one too."
    chunks = chunk_text(text, max_len=30)
    assert len(chunks) >= 2
    assert all(len(c) <= 31 for c in chunks)


def test_chunk_text_never_empty():
    """A trivial string still yields one chunk."""
    assert chunk_text("Hello") == ["Hello"]


def test_chunk_text_hard_splits_long_sentence():
    """A single over-long sentence (no boundaries) is hard-split to <= max_len."""
    text = "word " * 50  # ~250 chars, no terminal punctuation -> one "sentence"
    chunks = chunk_text(text, max_len=30)
    assert len(chunks) > 1
    assert all(len(c) <= 30 for c in chunks)


def test_chunk_text_hard_splits_unbroken_token():
    """A single token longer than max_len is sliced mid-token, losing nothing."""
    chunks = chunk_text("x" * 100, max_len=30)
    assert all(len(c) <= 30 for c in chunks)
    assert "".join(chunks) == "x" * 100


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def test_pipeline_runs_four_graphs_in_order(tmp_path, fake_onnx):
    """The pipeline feeds each graph the exact tensors upstream expects."""
    model_dir = _build_model_dir(tmp_path)
    pipeline = SupertonicPipeline(str(model_dir))

    pcm = pipeline.synthesize_pcm("Hello world", voice="M1", language="en-US")

    # Raw PCM: 16-bit mono, trimmed to predicted duration (0.5s / 1.05 speed).
    assert isinstance(pcm, bytes)
    expected_samples = int(24000 * (0.5 / 1.05))
    assert len(pcm) == expected_samples * 2

    # Exact feed keys per graph (the contract that makes the 4 graphs line up).
    assert fake_onnx["duration_predictor"][0] == {"text_ids", "style_dp", "text_mask"}
    assert fake_onnx["text_encoder"][0] == {"text_ids", "style_ttl", "text_mask"}
    assert fake_onnx["vector_estimator"][0] == {
        "noisy_latent",
        "text_emb",
        "style_ttl",
        "text_mask",
        "latent_mask",
        "current_step",
        "total_step",
    }
    assert fake_onnx["vocoder"][0] == {"latent"}
    # Flow-matching loop ran total_step (default 8) times.
    assert len(fake_onnx["vector_estimator"]) == 8


def test_infer_chunk_clamps_oversized_duration(tmp_path, fake_onnx):
    """A pathological duration is clamped so latent_len stays within the limit.

    Without the clamp this overflows the vector estimator's positional table and
    crashes the ORT kernel ("1000 by <N>" broadcast error).
    """
    model_dir = _build_model_dir(tmp_path)
    pipeline = SupertonicPipeline(str(model_dir))

    # Force the duration predictor to predict an absurd 100s for the chunk.
    pipeline.dp_ort.run = lambda names, feed: [np.array([100.0], dtype=np.float32)]

    style = pipeline._get_style("M1")
    _wav, duration = pipeline._infer_chunk("text", "en", style)

    chunk_size = pipeline.base_chunk_size * pipeline.chunk_compress_factor
    max_duration = pipeline._MAX_LATENT_LEN * chunk_size / pipeline.sample_rate
    assert float(duration.max()) <= max_duration + 1e-6


def test_pipeline_unknown_voice_raises(tmp_path, fake_onnx):
    """An unknown voice id surfaces a clear ValueError."""
    model_dir = _build_model_dir(tmp_path)
    pipeline = SupertonicPipeline(str(model_dir))
    with pytest.raises(ValueError):
        pipeline.synthesize_pcm("Hello", voice="does-not-exist")


# ---------------------------------------------------------------------------
# Backend wiring
# ---------------------------------------------------------------------------


async def test_backend_wires_pipeline_and_returns_wav(tmp_path, fake_onnx):
    """SupertonicONNXBackend lazily builds the pipeline and yields a WAV."""
    model_dir = _build_model_dir(tmp_path)
    backend = SupertonicONNXBackend(model_dir=str(model_dir))

    # Lazy: nothing loaded until first synthesize.
    assert backend._inference_fn is None

    result = await backend.synthesize("Hello world", language="en")

    assert backend._inference_fn is not None  # pipeline wired in
    assert backend.sample_rate == 24000  # aligned to model's native rate
    assert result.mime_format == "audio/wav"
    with wave.open(io.BytesIO(result.audio), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 24000


def test_backend_missing_dir_raises(tmp_path):
    """A configured-but-missing model dir raises ValueError (no silent degrade)."""
    backend = SupertonicONNXBackend(model_dir=str(tmp_path / "nope"))
    with pytest.raises(ValueError, match="not found"):
        backend._ensure_session()


def test_backend_defaults_to_base_dir(tmp_path, fake_onnx, monkeypatch):
    """With no arg/env, resolution falls back to <BASE_DIR>/models/supertonic-3."""
    import parrot.voice.tts.supertonic_inference as mod

    monkeypatch.delenv("SUPERTONIC_MODEL_PATH", raising=False)
    target = tmp_path / "models" / "supertonic-3"
    target.mkdir(parents=True)
    _build_model_dir(target)
    monkeypatch.setattr(mod, "BASE_DIR", tmp_path)

    backend = SupertonicONNXBackend(model_dir=None)
    backend._ensure_session()
    assert backend._pipeline is not None
    assert backend.sample_rate == 24000


# ---------------------------------------------------------------------------
# TTSConfig total_step / speed plumbing
# ---------------------------------------------------------------------------


def test_ttsconfig_supertonic_params_defaults_and_bounds():
    """TTSConfig exposes total_step/speed with upstream defaults and bounds."""
    from pydantic import ValidationError

    from parrot.voice.tts.models import TTSConfig

    cfg = TTSConfig(backend="supertonic")
    assert cfg.total_step == 8
    assert cfg.speed == 1.05

    assert TTSConfig(total_step=20, speed=0.8).total_step == 20
    for bad in ({"total_step": 0}, {"total_step": 51}, {"speed": 0.0}, {"speed": 3.5}):
        with pytest.raises(ValidationError):
            TTSConfig(**bad)


def test_synthesizer_passes_supertonic_params():
    """VoiceSynthesizer forwards total_step/speed/voice to the ONNX backend."""
    from parrot.voice.tts.models import TTSConfig
    from parrot.voice.tts.synthesizer import VoiceSynthesizer

    synth = VoiceSynthesizer(TTSConfig(backend="supertonic", voice="F2", total_step=12, speed=0.9))
    backend = synth._get_backend()
    assert backend._total_step == 12
    assert backend._speed == 0.9
    assert backend.voice == "F2"


def test_pipeline_honours_total_step(tmp_path, fake_onnx):
    """A custom total_step changes the flow-matching loop count."""
    model_dir = _build_model_dir(tmp_path)
    pipeline = SupertonicPipeline(str(model_dir), total_step=3)
    pipeline.synthesize_pcm("Hello world", voice="M1", language="en")
    assert len(fake_onnx["vector_estimator"]) == 3
