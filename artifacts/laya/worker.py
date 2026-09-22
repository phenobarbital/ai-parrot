"""Synchronous CPU inference worker for the Laya evaluation (spec §3 Module 2). Stdlib only; ``laya`` optional.

Run inside the isolated environment:  <worker_python> -m artifacts.laya.worker --checkpoint <dir> --revision <rev>
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import resource
import sys
import time
import traceback
from collections.abc import Sequence
from typing import Any, Protocol

_REAL_STDOUT = sys.stdout  # protocol channel; sys.stdout is rebound to stderr in main()


class Predictor(Protocol):
    """Anything with a synchronous ``predict(state, questions) -> answers`` (real Laya or a test fake)."""

    def predict(self, state: str, questions: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]: ...


def _emit(record: dict[str, Any], out: Any = None) -> None:
    """Write one protocol line to the real stdout (or ``out``) and flush."""
    stream = out or _REAL_STDOUT
    stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    stream.flush()


def _validate_request(obj: Any) -> str | None:
    """Return None when ``obj`` is a well-formed request, else a message (worker_protocol_error)."""
    if not isinstance(obj, dict) or not isinstance(obj.get("request_id"), str) or not obj["request_id"]:
        return "request_id missing"
    if not isinstance(obj.get("state"), str) or not isinstance(obj.get("questions"), dict) or not obj["questions"]:
        return "state/questions missing"
    for qid, q in obj["questions"].items():
        if q.get("type") not in ("noul", "choice") or not isinstance(q.get("text"), str):
            return f"question {qid!r} malformed"
        if q["type"] == "choice" and not (isinstance(q.get("options"), list) and len(q["options"]) >= 2):
            return f"question {qid!r} needs >= 2 options"
    return None


def serve(stdin: Any, predictor: Predictor, out: Any = None) -> int:
    """Serve one JSONL request at a time until EOF; never raise on a bad line or a predictor error."""
    for raw in stdin:
        raw = raw.strip()
        if not raw:
            continue
        request_id = ""
        try:
            obj = json.loads(raw)
            request_id = obj.get("request_id", "") if isinstance(obj, dict) else ""
            problem = _validate_request(obj)
            if problem:
                _emit({"type": "result", "request_id": request_id, "status": "error", "answers": {}, "inference_ms": None,
                       "error_code": "worker_protocol_error", "error_message": problem, "peak_rss_kb": _peak_rss_kb()}, out)
                continue
            t0 = time.perf_counter()
            answers = predictor.predict(obj["state"], obj["questions"])
            inference_ms = (time.perf_counter() - t0) * 1000.0
            missing_or_bad = [qid for qid in obj["questions"] if not isinstance(answers.get(qid), dict)]
            if missing_or_bad:
                _emit({"type": "result", "request_id": request_id, "status": "error", "answers": {}, "inference_ms": inference_ms,
                       "error_code": "worker_failed",
                       "error_message": f"predictor returned no answer for question(s): {missing_or_bad}",
                       "peak_rss_kb": _peak_rss_kb()}, out)
                continue
            _emit({"type": "result", "request_id": request_id, "status": "ok", "answers": answers, "inference_ms": inference_ms,
                   "error_code": None, "error_message": None, "peak_rss_kb": _peak_rss_kb()}, out)
        except json.JSONDecodeError as exc:
            _emit({"type": "result", "request_id": request_id, "status": "error", "answers": {}, "inference_ms": None,
                   "error_code": "worker_protocol_error", "error_message": f"invalid JSON: {exc}", "peak_rss_kb": _peak_rss_kb()}, out)
        except Exception as exc:  # predictor failure: record, keep serving
            print(traceback.format_exc(), file=sys.stderr)
            _emit({"type": "result", "request_id": request_id, "status": "error", "answers": {}, "inference_ms": None,
                   "error_code": "worker_failed", "error_message": f"{type(exc).__name__}: {exc}", "peak_rss_kb": _peak_rss_kb()}, out)
    return 0


def _peak_rss_kb() -> int | None:
    """Peak RSS in kB on Linux; None elsewhere (unit differs — spec §3 M2 'unsupported metrics are null')."""
    if sys.platform != "linux":
        return None
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


class LayaPredictor:
    """Adapter from our question schema to ``laya.Agent.system_one`` (verify against installed 0.3.5 — TASK-3618)."""

    def __init__(self, agent: Any, max_input_tokens: int | None) -> None:
        self._agent = agent
        self.max_input_tokens = max_input_tokens

    def predict(self, state: str, questions: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Run ``system_one`` once and map its output back to our answer schema."""
        laya_questions = _to_laya_questions(questions)
        raw = self._agent.system_one(state, laya_questions)
        return _from_laya_answers(questions, raw)


def _to_laya_questions(questions: dict[str, dict[str, Any]]) -> Any:
    """Translate our {qid: {type,text,options}} schema into the shape ``system_one`` expects."""
    # FILL IN: build from the installed laya/agent.py signature (spec §7 URL) — noul questions carry text only,
    #          choice questions carry text + options; keep qid order — bounded by spec §2 "one fixed schema per scenario"
    raise NotImplementedError

def _from_laya_answers(questions: dict[str, dict[str, Any]], raw: Any) -> dict[str, dict[str, Any]]:
    """Map Laya output to {qid: answer}; ``noul`` is the POSITIVE probability (spec §2), never its confidence."""
    # FILL IN: for noul -> {"type":"noul","noul":<positive prob>,"confidence":<conf>};
    #          for choice -> {"type":"choice","choice":<argmax option>,"probabilities":{opt:p},"confidence":<conf>}
    #          — bounded by spec §3 M1 answer invariants (finite, [0,1], probabilities over exactly the options)
    raise NotImplementedError


def _checkpoint_sha256(checkpoint: str) -> str | None:
    """SHA-256 over the sorted relative paths + bytes of ``*.safetensors``/``*.json`` under ``checkpoint``.

    Returns None if ``checkpoint`` is not a directory (a missing directory is a fatal
    ``checkpoint_missing`` error handled by the caller, not surfaced here).
    """
    if not os.path.isdir(checkpoint):
        return None
    digest = hashlib.sha256()
    relevant: list[str] = []
    for root, _dirs, files in os.walk(checkpoint):
        for name in files:
            if name.endswith((".safetensors", ".json")):
                full = os.path.join(root, name)
                relevant.append(os.path.relpath(full, checkpoint))
    for rel in sorted(relevant):
        digest.update(rel.encode("utf-8"))
        with open(os.path.join(checkpoint, rel), "rb") as fh:
            digest.update(fh.read())
    return digest.hexdigest()


def _package_versions(names: Sequence[str]) -> dict[str, str | None]:
    """Best-effort installed version per package name; None when not installed."""
    versions: dict[str, str | None] = {}
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def _torch_threads() -> int | None:
    """``torch.get_num_threads()`` if torch is importable, else None."""
    try:
        import torch  # noqa: PLC0415 — optional runtime, worker env only
    except ImportError:
        return None
    return torch.get_num_threads()


def load_predictor(checkpoint: str, revision: str) -> tuple[LayaPredictor, dict[str, Any]]:
    """Import Laya, load the local CPU checkpoint once, and return (predictor, ready_fields).

    Raises:
        ImportError: Laya or a runtime dependency is missing (-> ``dependency_missing``).
        FileNotFoundError: ``checkpoint`` is not a directory (-> ``checkpoint_missing``).
    """
    if not os.path.isdir(checkpoint):
        raise FileNotFoundError(checkpoint)
    from laya import Agent  # noqa: PLC0415 — optional runtime, worker env only

    t0 = time.perf_counter()
    agent = Agent(checkpoint, device="cpu")  # FILL IN: exact kwargs per installed laya.Agent.__init__ — bounded by spec §7 "explicit CPU device and local snapshot"
    load_ms = (time.perf_counter() - t0) * 1000.0
    max_input_tokens = None  # FILL IN: read the tokenizer/model max length from the loaded agent — bounded by spec §3 M2 "checkpoint's actual limits"
    ready = {"checkpoint_path": checkpoint, "checkpoint_revision": revision, "checkpoint_sha256": _checkpoint_sha256(checkpoint),
             "packages": _package_versions(("laya", "torch", "transformers")), "max_input_tokens": max_input_tokens,
             "torch_threads": _torch_threads(), "load_ms": load_ms}
    return LayaPredictor(agent, max_input_tokens), ready


def main(argv: Sequence[str] | None = None) -> int:
    """Load the pinned CPU checkpoint and serve one JSONL request at a time until stdin EOF."""
    parser = argparse.ArgumentParser(prog="artifacts.laya.worker", description="Laya CPU inference worker (FEAT-589)")
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args(argv)
    sys.stdout = sys.stderr  # third-party prints can no longer corrupt the protocol channel
    try:
        predictor, ready = load_predictor(args.checkpoint, args.revision)
    except ImportError as exc:
        _emit({"type": "error", "error_code": "dependency_missing", "error_message": f"{exc}; see artifacts/laya/README.md"})
        return 3
    except FileNotFoundError as exc:
        _emit({"type": "error", "error_code": "checkpoint_missing", "error_message": f"checkpoint directory not found: {exc}"})
        return 3
    except Exception as exc:
        print(traceback.format_exc(), file=sys.stderr)
        _emit({"type": "error", "error_code": "worker_failed", "error_message": f"{type(exc).__name__}: {exc}"})
        return 3
    _emit({"type": "ready", "worker_pid": os.getpid(), "device": "cpu", "python": platform.python_version(),
           "platform": platform.platform(), **ready})
    return serve(sys.stdin, predictor)


if __name__ == "__main__":
    sys.exit(main())
