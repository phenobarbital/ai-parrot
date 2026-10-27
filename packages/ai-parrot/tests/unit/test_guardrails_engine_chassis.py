"""FEAT-761 TASK-4827 — engine chassis parity + generic resolver/warmup."""
import asyncio
import math
import subprocess
import sys
import types

import pytest

from parrot.bots.guardrails.builtin import _engine_chassis as chassis
from parrot.bots.guardrails.builtin import prompt_injection as pi_module

_LOGITS = [0.1, 5.0]
# Golden value captured from the pre-refactor `_OnnxInjectionEngine` on this fixture.
_GOLDEN_SCORE = math.exp(5.0) / (math.exp(0.1) + math.exp(5.0))


@pytest.fixture(autouse=True)
def _reset():
    chassis._reset_chassis_state()
    yield
    chassis._reset_chassis_state()


@pytest.fixture
def fake_ort(monkeypatch):
    """Fake `onnxruntime`/`transformers` modules (pattern from test_guardrails_prompt_injection.py)."""
    fake = types.ModuleType("onnxruntime")

    class _Opts:
        def __init__(self):
            self.intra_op_num_threads = None
            self.inter_op_num_threads = None

    class _Input:
        name = "input_ids"

    class _Session:
        def __init__(self, path, sess_options=None, providers=None):
            self.path = path
            self.sess_options = sess_options
            self.providers = providers

        def get_inputs(self):
            return [_Input()]

        def run(self, output_names, feed):
            return [[_LOGITS]]

    fake.SessionOptions = _Opts
    fake.InferenceSession = _Session

    tf = types.ModuleType("transformers")

    class _Tok:
        calls: list = []

        @classmethod
        def from_pretrained(cls, path, **kwargs):
            return cls()

        def __call__(self, text, return_tensors=None, truncation=None, max_length=None):
            _Tok.calls.append(max_length)
            return {"input_ids": [[1, 2, 3]], "attention_mask": [[1, 1, 1]]}

    tf.AutoTokenizer = _Tok
    monkeypatch.setitem(sys.modules, "onnxruntime", fake)
    monkeypatch.setitem(sys.modules, "transformers", tf)
    return fake


def _model_dir(tmp_path, labels):
    (tmp_path / "model.onnx").write_bytes(b"x")
    import json

    (tmp_path / "config.json").write_text(json.dumps({"id2label": labels}))
    return tmp_path


def _spec(category="jailbreak", prefix="PARROT_TESTJB", model="org/model"):
    return chassis.EngineSpec(
        category=category, env_prefix=prefix, default_model_id=model, positive_label_match=("jailbreak", "malicious"),
    )


def test_import_is_free():
    code = (
        "import sys; import parrot.bots.guardrails; "
        "import parrot.bots.guardrails.builtin._engine_chassis; "
        "assert 'onnxruntime' not in sys.modules and 'transformers' not in sys.modules"
    )
    import os
    from pathlib import Path

    src = str(Path(chassis.__file__).resolve().parents[4])
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([src, os.environ.get("PYTHONPATH", "")])}
    subprocess.run([sys.executable, "-c", code], check=True, env=env, timeout=120)


def test_positive_index_matching(tmp_path):
    d = _model_dir(tmp_path, {"0": "MALICIOUS", "1": "BENIGN"})
    assert chassis.resolve_positive_index(d, ("jailbreak", "malicious")) == 0
    assert chassis.resolve_positive_index(d, ("nothing",)) == 1
    assert chassis.resolve_positive_index(tmp_path / "missing", ("x",)) == 1


def test_classifier_env_prefix(tmp_path, fake_ort, monkeypatch):
    monkeypatch.setenv("PARROT_TESTJB_ORT_INTRA_OP_THREADS", "3")
    monkeypatch.setenv("PARROT_TESTJB_ORT_INTER_OP_THREADS", "4")
    d = _model_dir(tmp_path, {"0": "SAFE", "1": "JAILBREAK"})
    eng = chassis.ClassifierOnnxEngine(d, d / "model.onnx", "m", env_prefix="PARROT_TESTJB",
                                       positive_label_match=("jailbreak",), max_length=128)
    assert eng._session.sess_options.intra_op_num_threads == 3
    assert eng._session.sess_options.inter_op_num_threads == 4
    assert isinstance(eng, chassis.ScoringEngine)
    eng.score("hi")
    assert sys.modules["transformers"].AutoTokenizer.calls[-1] == 128


def test_injection_engine_parity(tmp_path, fake_ort, monkeypatch):
    monkeypatch.setenv("PARROT_INJECTION_ORT_INTRA_OP_THREADS", "5")
    d = _model_dir(tmp_path, {"0": "SAFE", "1": "INJECTION"})
    eng = pi_module._OnnxInjectionEngine(tokenizer_dir=d, graph_path=d / "model.onnx", model_id="x")
    assert isinstance(eng, chassis.ClassifierOnnxEngine)
    assert eng.engine_name == "onnx"
    assert eng._injection_index == 1
    assert eng._session.sess_options.intra_op_num_threads == 5
    assert eng._session.sess_options.inter_op_num_threads == 1
    assert eng.score("anything") == pytest.approx(_GOLDEN_SCORE, abs=1e-12)
    assert sys.modules["transformers"].AutoTokenizer.calls[-1] == 512


def test_delegates_keep_behavior(tmp_path, monkeypatch):
    import numpy as np

    monkeypatch.setenv("X_INT", "bad")
    assert pi_module._env_int("X_INT", 7) == 7
    assert pi_module._softmax(np.array(_LOGITS))[1] == pytest.approx(_GOLDEN_SCORE)
    d = _model_dir(tmp_path, {"0": "INJECTION", "1": "SAFE"})
    assert pi_module._resolve_injection_index(d) == 0


def test_resolve_env_dir_wins_and_memoizes(tmp_path, fake_ort, monkeypatch):
    d = _model_dir(tmp_path, {"0": "SAFE", "1": "JAILBREAK"})
    monkeypatch.setenv("PARROT_TESTJB_ONNX_DIR", str(d))
    spec = _spec()
    eng = chassis.resolve_engine(spec)
    assert eng is not None and eng.model_id == str(d)
    assert chassis.resolve_engine(spec) is eng
    assert chassis.resolve_engine(spec, force_reresolve=True) is not eng


def test_resolve_cache_probe(tmp_path, fake_ort, monkeypatch):
    snap = tmp_path / "snap"
    (snap / "onnx").mkdir(parents=True)
    (snap / "onnx" / "model.onnx").write_bytes(b"x")
    (snap / "config.json").write_text('{"id2label": {"0": "SAFE", "1": "JAILBREAK"}}')
    import huggingface_hub

    monkeypatch.setattr(huggingface_hub, "try_to_load_from_cache",
                        lambda repo, path: str(snap / path))
    eng = chassis.resolve_engine(_spec())
    assert eng is not None and eng.model_id == "org/model"


def test_resolve_none_and_per_category(monkeypatch):
    import huggingface_hub

    monkeypatch.setattr(huggingface_hub, "try_to_load_from_cache", lambda repo, path: None)
    assert chassis.resolve_engine(_spec("a", "PARROT_TA")) is None
    assert chassis.resolve_engine(_spec("b", "PARROT_TB", model="")) is None
    assert set(chassis._RESOLVED) == {"a", "b"}


def test_resolve_bad_env_dir_never_raises(tmp_path, monkeypatch):
    import huggingface_hub

    monkeypatch.setattr(huggingface_hub, "try_to_load_from_cache", lambda repo, path: None)
    monkeypatch.setenv("PARROT_TESTJB_ONNX_DIR", str(tmp_path / "nope"))
    assert chassis.resolve_engine(_spec()) is None


def test_warmup_download_failure_never_raises(monkeypatch):
    import huggingface_hub

    def boom(*a, **k):
        raise RuntimeError("offline")

    monkeypatch.setattr(huggingface_hub, "snapshot_download", boom)
    monkeypatch.setattr(huggingface_hub, "try_to_load_from_cache", lambda repo, path: None)
    assert asyncio.run(chassis.warmup_model(_spec())) == "none"


def test_warmup_noop_download_when_env_dir_valid(tmp_path, fake_ort, monkeypatch):
    import huggingface_hub

    called = []
    monkeypatch.setattr(huggingface_hub, "snapshot_download", lambda *a, **k: called.append(a))
    d = _model_dir(tmp_path, {"0": "SAFE", "1": "JAILBREAK"})
    monkeypatch.setenv("PARROT_TESTJB_ONNX_DIR", str(d))
    assert asyncio.run(chassis.warmup_model(_spec())) == "onnx"
    assert called == []
