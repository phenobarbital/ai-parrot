"""FEAT-589 M2 — worker protocol with a fake predictor; dependency-missing path as a real subprocess."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from artifacts.laya import worker
from artifacts.laya.models import ERROR_CODES, PredictionResult

REPO_ROOT = Path(__file__).resolve().parents[5]


class _Fake:
    def __init__(self, answers=None, error: Exception | None = None):
        self.answers, self.error, self.calls = answers or {}, error, []

    def predict(self, state, questions):
        self.calls.append((state, questions))
        if self.error:
            raise self.error
        return {qid: dict(self.answers.get(qid, {"type": "noul", "noul": 0.2, "confidence": 0.9})) for qid in questions}


def _run(lines: list[str], predictor) -> list[dict]:
    out = io.StringIO()
    assert worker.serve(io.StringIO("".join(l + "\n" for l in lines)), predictor, out) == 0
    return [json.loads(l) for l in out.getvalue().splitlines()]


def test_ok_result_echoes_request_id_and_parses_as_prediction_result():
    req = {"request_id": "r1", "state": "hello", "questions": {"injection": {"type": "noul", "text": "q"}}}
    (rec,) = _run([json.dumps(req)], _Fake())
    assert rec["type"] == "result" and rec["request_id"] == "r1" and rec["status"] == "ok"
    PredictionResult(**{k: v for k, v in rec.items() if k not in ("type", "peak_rss_kb")})


def test_malformed_lines_yield_protocol_errors_and_loop_continues():
    good = json.dumps({"request_id": "r2", "state": "s", "questions": {"q": {"type": "noul", "text": "t"}}})
    recs = _run(["{not json", json.dumps({"request_id": "", "state": "s", "questions": {}}), good], _Fake())
    assert [r["error_code"] for r in recs[:2]] == ["worker_protocol_error"] * 2 and recs[2]["status"] == "ok"
    assert all(r["error_code"] in ERROR_CODES for r in recs if r["error_code"])


def test_predictor_exception_becomes_worker_failed_not_exit():
    req = json.dumps(
        {"request_id": "r3", "state": "s", "questions": {"q": {"type": "choice", "text": "t", "options": ["a", "b"]}}}
    )
    (rec,) = _run([req], _Fake(error=RuntimeError("boom")))
    assert rec["status"] == "error" and rec["error_code"] == "worker_failed" and "boom" in rec["error_message"]


def test_confident_negative_noul_answer_passed_through_untouched():
    """The worker must not 'fix' a confident negative — a low ``noul`` with high confidence stays as-is."""
    req = json.dumps({"request_id": "r4", "state": "s", "questions": {"q": {"type": "noul", "text": "t"}}})
    fake = _Fake(answers={"q": {"type": "noul", "noul": 0.01, "confidence": 0.99}})
    (rec,) = _run([req], fake)
    assert rec["status"] == "ok"
    assert rec["answers"]["q"] == {"type": "noul", "noul": 0.01, "confidence": 0.99}


def test_incomplete_answers_yield_worker_failed():
    """A predictor that drops a requested question id is a worker failure, not a silent partial ``ok``."""
    req = json.dumps(
        {
            "request_id": "r5",
            "state": "s",
            "questions": {"q1": {"type": "noul", "text": "t"}, "q2": {"type": "noul", "text": "t2"}},
        }
    )
    fake = _Fake(answers={"q1": {"type": "noul", "noul": 0.5, "confidence": 0.5}})

    class _Partial(_Fake):
        def predict(self, state, questions):
            self.calls.append((state, questions))
            return {"q1": {"type": "noul", "noul": 0.5, "confidence": 0.5}}

    (rec,) = _run([req], _Partial())
    assert rec["status"] == "error" and rec["error_code"] == "worker_failed"
    assert "q2" in rec["error_message"]


def _laya_importable() -> bool:
    try:
        import laya  # noqa: F401
    except ImportError:
        return False
    return True


def test_main_without_laya_emits_dependency_missing_and_exit_3(tmp_path):
    if _laya_importable():
        pytest.skip("laya is importable in this interpreter; the dependency-missing path cannot be exercised")
    proc = subprocess.run(
        [sys.executable, "-m", "artifacts.laya.worker", "--checkpoint", str(tmp_path), "--revision", "x"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 3
    first = json.loads(proc.stdout.splitlines()[0])
    assert first["type"] == "error" and first["error_code"] == "dependency_missing"


def test_main_with_missing_checkpoint_dir(tmp_path):
    """A nonexistent --checkpoint is a fatal ``checkpoint_missing`` regardless of whether ``laya`` is installed:
    ``load_predictor`` checks ``os.path.isdir`` before ever importing ``laya``."""
    missing = tmp_path / "does-not-exist"
    proc = subprocess.run(
        [sys.executable, "-m", "artifacts.laya.worker", "--checkpoint", str(missing), "--revision", "x"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 3
    first = json.loads(proc.stdout.splitlines()[0])
    assert first["type"] == "error" and first["error_code"] == "checkpoint_missing"
