"""FEAT-589 M2 — LayaWorker against a fake protocol child (spec §4 'Worker protocol/deadlines')."""
from __future__ import annotations

import asyncio
import json
import sys
import textwrap
from pathlib import Path

import pytest

from artifacts.laya.models import EvaluationConfig, PredictionRequest
from artifacts.laya.runtime import LayaWorker, WorkerStartupError

# Fake child: behaviour is selected by --revision (startup-delay / hang / noisy / bad-id / ok).
FAKE_CHILD = textwrap.dedent('''
    import json, sys, time, os
    args = sys.argv; rev = args[args.index("--revision") + 1]
    if rev == "startup-delay":
        time.sleep(30)
    print("loading noise on stdout", file=sys.stderr)
    sys.stdout.write(json.dumps({"type": "ready", "worker_pid": os.getpid(), "device": "cpu", "checkpoint_path": "x",
        "checkpoint_revision": rev, "packages": {}, "load_ms": 1.0, "python": "3", "platform": "fake"}) + "\\n"); sys.stdout.flush()
    for line in sys.stdin:
        req = json.loads(line)
        if rev == "hang":
            time.sleep(30)
        rid = "WRONG" if rev == "bad-id" else req["request_id"]
        if rev == "noisy":
            print("garbage on stderr", file=sys.stderr)
        answers = {q: {"type": "noul", "noul": 0.1, "confidence": 0.9} for q in req["questions"]}
        sys.stdout.write(json.dumps({"type": "result", "request_id": rid, "status": "ok", "answers": answers,
            "inference_ms": 2.0, "error_code": None, "error_message": None, "peak_rss_kb": 1234}) + "\\n"); sys.stdout.flush()
''')


@pytest.fixture
def fake_module(tmp_path, monkeypatch) -> str:
    (tmp_path / "fake_laya_child.py").write_text(FAKE_CHILD, encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    return "fake_laya_child"


def _cfg(module: str, revision: str, tmp_path: Path, **kw) -> EvaluationConfig:
    return EvaluationConfig(worker_python=Path(sys.executable), checkpoint_path=tmp_path, checkpoint_revision=revision,
                            output_dir=tmp_path / "out", worker_module=module, startup_timeout_s=kw.pop("startup", 20.0),
                            prediction_timeout_s=kw.pop("predict", 5.0), **kw)


def _req(rid: str = "r1") -> PredictionRequest:
    return PredictionRequest(request_id=rid, state="hello", questions={"injection": {"type": "noul", "text": "q"}})


async def test_ready_ok_roundtrip_and_rss(fake_module, tmp_path):
    async with LayaWorker(_cfg(fake_module, "ok", tmp_path)) as w:
        assert w.ready is not None and w.ready.device == "cpu" and w.startup_ms is not None
        res = await w.predict(_req())
        assert res.status == "ok" and res.roundtrip_ms is not None and res.inference_ms == 2.0 and w.peak_rss_kb == 1234


async def test_startup_timeout_terminates_child(fake_module, tmp_path):
    with pytest.raises(WorkerStartupError) as ei:
        async with LayaWorker(_cfg(fake_module, "startup-delay", tmp_path, startup=1.0)):
            pass
    assert ei.value.error_code == "startup_timeout"


async def test_inference_timeout_marks_failed_and_reaps(fake_module, tmp_path):
    async with LayaWorker(_cfg(fake_module, "hang", tmp_path, predict=1.0)) as w:
        res = await w.predict(_req())
        assert res.status == "error" and res.error_code == "inference_timeout" and w.failed
        again = await w.predict(_req("r2"))
        assert again.error_code == "worker_failed"
        assert w._proc is None  # reaped, not abandoned


async def test_stderr_noise_is_retained_not_mixed_into_protocol(fake_module, tmp_path):
    async with LayaWorker(_cfg(fake_module, "noisy", tmp_path)) as w:
        assert (await w.predict(_req())).status == "ok"
        await asyncio.sleep(0.2)
        assert any("garbage" in line for line in w.stderr_tail)


async def test_mismatched_request_id_is_protocol_error(fake_module, tmp_path):
    async with LayaWorker(_cfg(fake_module, "bad-id", tmp_path)) as w:
        assert (await w.predict(_req())).error_code == "worker_protocol_error"


async def test_cancellation_shuts_child_down_then_propagates(fake_module, tmp_path):
    async with LayaWorker(_cfg(fake_module, "hang", tmp_path)) as w:
        task = asyncio.create_task(w.predict(_req()))
        await asyncio.sleep(0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert w._proc is None  # child shut down


async def test_missing_worker_module_is_worker_failed_startup(tmp_path):
    async with LayaWorker(_cfg("no_such_module_xyz", "ok", tmp_path)) as w:
        with pytest.raises(WorkerStartupError) as ei:
            async with w:
                pass
        assert ei.value.error_code == "worker_failed"
