"""FEAT-761 TASK-4828 — embedding engine, corpus loader, score_async offload."""

import threading
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from parrot.bots.guardrails.base import GuardrailAction, GuardrailContext, GuardrailStage
from parrot.bots.guardrails.builtin import _engine_chassis as chassis
from parrot.bots.guardrails.builtin import prompt_injection as prompt_injection_module
from parrot.bots.guardrails.builtin.prompt_injection import PromptInjectionGuardrail


class _ThreadRecordingEngine:
    """Small engine recording the thread that runs its synchronous score method."""

    engine_name = "fake"
    model_id = "fake-model"

    def __init__(self) -> None:
        """Initialize without a score thread."""
        self.thread_id: int | None = None

    def score(self, text: str) -> float:
        """Record its executing thread and return a safe score."""
        self.thread_id = threading.get_ident()
        return 0.01


class _EmbeddingSession:
    """Fake ORT session returning fixed token embeddings."""

    def run(self, output_names, feed):
        """Return token embeddings for a three-token single-item batch."""
        return [
            np.array(
                [[[3.0, 4.0], [0.0, 0.0], [-3.0, -4.0]]],
                dtype=np.float32,
            )
        ]


@pytest.mark.asyncio
async def test_score_async_runs_engine_score_off_event_loop_thread():
    """The chassis offloads synchronous engines so checks do not block asyncio."""
    engine = _ThreadRecordingEngine()

    assert await chassis.score_async(engine, "safe text") == 0.01
    assert engine.thread_id is not None
    assert engine.thread_id != threading.get_ident()


def test_load_corpus_matrix_normalizes_and_rejects_invalid_arrays(tmp_path: Path):
    """Corpus loading is safe, normalizes rows, and rejects invalid shapes."""
    corpus_path = tmp_path / "corpus.npy"
    np.save(corpus_path, np.array([[3.0, 4.0], [0.0, 0.0]], dtype=np.float64))

    corpus = chassis.load_corpus_matrix(corpus_path)

    assert corpus.dtype == np.float32
    assert np.allclose(corpus, [[0.6, 0.8], [0.0, 0.0]])

    one_dimensional = tmp_path / "one-dimensional.npy"
    np.save(one_dimensional, np.array([1.0, 2.0], dtype=np.float32))
    with pytest.raises(ValueError, match="non-empty 2-D"):
        chassis.load_corpus_matrix(one_dimensional)

    empty = tmp_path / "empty.npy"
    np.save(empty, np.empty((0, 2), dtype=np.float32))
    with pytest.raises(ValueError, match="non-empty 2-D"):
        chassis.load_corpus_matrix(empty)

    pickled = tmp_path / "pickled.npy"
    np.save(pickled, np.array([["unsafe"]], dtype=object), allow_pickle=True)
    with pytest.raises(ValueError, match="allow_pickle=False"):
        chassis.load_corpus_matrix(pickled)


def test_embedding_score_masked_mean_pooling_cosine_and_negative_clamp():
    """Embedding scores use attention-mask pooling and do not return negatives."""
    engine = object.__new__(chassis.EmbeddingSimilarityEngine)
    engine._max_length = 32
    engine._tokenizer = lambda *args, **kwargs: {
        "input_ids": np.array([[101, 102, 103]], dtype=np.int64),
        "attention_mask": np.array([[1, 1, 0]], dtype=np.int64),
    }
    engine._session = _EmbeddingSession()
    engine._input_names = {"input_ids", "attention_mask", "token_type_ids"}
    engine._corpus_matrix = np.array([[0.6, 0.8], [-0.6, -0.8]], dtype=np.float32)

    assert engine.score("test") == pytest.approx(1.0)

    engine._corpus_matrix = np.array([[-0.6, -0.8]], dtype=np.float32)
    assert engine.score("test") == 0.0


def test_embedding_resolution_without_corpus_degrades_to_none(tmp_path: Path, monkeypatch, caplog):
    """An embedding spec without its corpus logs and resolves to the heuristic floor."""
    graph = tmp_path / "model.onnx"
    graph.touch()
    spec = chassis.EngineSpec(
        category="embedding-no-corpus",
        env_prefix="PARROT_TEST_EMBEDDING",
        default_model_id="test/model",
        kind="embedding",
    )
    monkeypatch.setenv("PARROT_TEST_EMBEDDING_ONNX_DIR", str(tmp_path))
    monkeypatch.delenv("PARROT_TEST_EMBEDDING_CORPUS", raising=False)
    monkeypatch.setattr(chassis, "_try_cache", lambda ignored_spec: None)
    chassis._reset_chassis_state()

    assert chassis.resolve_engine(spec) is None
    assert "PARROT_TEST_EMBEDDING_CORPUS is not set" in caplog.text


@pytest.mark.asyncio
async def test_prompt_injection_check_offloads_fake_engine_without_verdict_change():
    """Prompt injection check accepts a fake scoring engine through score_async."""
    engine = _ThreadRecordingEngine()
    context = GuardrailContext(stage=GuardrailStage.INPUT, agent_name="test")
    with patch.object(prompt_injection_module, "_resolve_injection_engine", return_value=engine):
        guardrail = PromptInjectionGuardrail(strict_mode=True, block_on_threat=True)
        result = await guardrail.check("ordinary question", context)

    assert result.action == GuardrailAction.PASS
    assert engine.thread_id is not None
    assert engine.thread_id != threading.get_ident()
