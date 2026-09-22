# TASK-3608: Isolated CPU worker entry point and standalone environment manifest

**Feature**: FEAT-589 — Evaluate Laya for typed classification and agent model routing
**Spec**: `sdd/specs/laya-adoption.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3605
**Assigned-to**: unassigned

---

## Context

Implements the child-process half of spec §3 **Module 2**. `worker.py` is the only module that
runs inside the isolated Laya environment: it loads one English checkpoint once, on CPU, emits a
`ready` record, then serves one newline-delimited JSON request at a time from stdin until EOF.
Third-party stdout is redirected to stderr so it can never corrupt the protocol. It imports
nothing from `parrot` and nothing from `artifacts.laya.models` (the worker environment has
neither); the wire schema is validated by hand with plain dicts.

M2 is **not** delegation-eligible (spec §3): the exact Laya 0.3.5 call shape must be verified
against the installed runtime. The blueprint therefore fixes *our* protocol and the module
structure, and leaves the `laya`-specific translation as bounded `FILL IN`s that TASK-3618
verifies with a real run.

`artifacts/laya/pyproject.toml` is a standalone project (not a uv workspace member —
`[tool.uv.workspace] members = ["packages/*"]`) that pins the runtime; nothing installs it
implicitly (spec §2, §7).

---

## Scope

- Create `artifacts/laya/worker.py` (stdlib only, optional `laya` import inside `load_predictor`).
- Create `artifacts/laya/pyproject.toml` pinning `laya==0.3.5` (verify the distribution name on
  PyPI before locking; if it differs, record the real name and keep the version pin).
- Write `packages/ai-parrot/tests/unit/laya_eval/test_laya_worker.py` — exercises `serve()` with a
  fake predictor through in-memory streams, and `main()` as a subprocess with `laya` absent.

**NOT in scope**: token-budget preflight (TASK-3609, same file, later); the host-side
`LayaWorker` (TASK-3610); installing anything.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `artifacts/laya/worker.py` | CREATE | Child-process entry point: load, ready record, NDJSON serve loop |
| `artifacts/laya/pyproject.toml` | CREATE | Standalone environment manifest (pinned Laya runtime) |
| `packages/ai-parrot/tests/unit/laya_eval/test_laya_worker.py` | CREATE | Protocol tests with fake predictor; dependency-missing subprocess test |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `1a7ccd5a1` on 2026-09-21. External Laya contract as inspected in spec §7 on 2026-09-21.

### Verified Imports
```python
# worker.py: STANDARD LIBRARY ONLY at module scope —
import argparse, json, os, platform, resource, sys, time, traceback
# inside load_predictor() only, guarded by ImportError:
#   from laya import Agent            # spec §7: Agent(model_id_or_path, device, token, subfolder); .system_one(state, questions)
# tests (host env):
from artifacts.laya.models import ERROR_CODES, PredictionResult   # TASK-3605
```

### Existing Signatures to Use
```python
# Wire protocol this feature fixes (host side validates with TASK-3605 models):
#  worker -> host, first line:
#    {"type":"ready","worker_pid":int,"device":"cpu","checkpoint_path":str,"checkpoint_revision":str,
#     "checkpoint_sha256":str|null,"packages":{"laya":str|null,"torch":str|null,"transformers":str|null},
#     "max_input_tokens":int|null,"torch_threads":int|null,"load_ms":float,"python":str,"platform":str}
#  worker -> host on fatal startup error, then exit 3:
#    {"type":"error","error_code":"dependency_missing"|"checkpoint_missing"|"worker_failed","error_message":str}
#  host -> worker, one line per request (PredictionRequest.model_dump()):
#    {"request_id":str,"state":str,"questions":{qid:{"type":"noul","text":str}|{"type":"choice","text":str,"options":[str]}}}
#  worker -> host, one line per request:
#    {"type":"result","request_id":str,"status":"ok"|"error","answers":{qid:{...}},"inference_ms":float|null,
#     "error_code":str|null,"error_message":str|null,"peak_rss_kb":int|null}
#  answers: noul -> {"type":"noul","noul":float,"confidence":float}
#           choice -> {"type":"choice","choice":str,"probabilities":{opt:float},"confidence":float}
#  stdin EOF -> worker exits 0.  All diagnostics -> stderr.
# spec §7 external contract (unverified until TASK-3618): laya.Agent(model_id_or_path, device="cpu", token=None, subfolder=None)
#   .system_one(state, questions) synchronous; "noul" is the POSITIVE probability.
```

### Does NOT Exist
- ~~`from artifacts.laya.models import ...` in worker.py~~ — the isolated env has no Pydantic/parrot; hand-validate dicts.
- ~~a `--download` / auto-install path~~ — spec §2: setup is an explicit documented action; the worker only *loads* a local snapshot.
- ~~GPU/auto device selection~~ — `device="cpu"` is passed explicitly and echoed in `ready.device`.
- ~~a verified `questions` format for `laya.Agent.system_one`~~ — translate from OUR schema in `_to_laya_questions()` and mark it for runtime verification.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "artifacts/laya/worker.py", "action": "CREATE"},
    {"path": "artifacts/laya/pyproject.toml", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/unit/laya_eval/test_laya_worker.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Protocol lines go to the *saved* real stdout handle; `sys.stdout` is rebound to `sys.stderr`
  before importing/loading Laya and stays there (spec §2 "capture third-party stdout").
- One request at a time; the loop is `for line in stdin:`; a malformed line yields a `result`
  with `status="error"`, `error_code="worker_protocol_error"` and `request_id` = whatever could be
  parsed (else `""`), and the loop continues (host decides).
- Predictor exceptions become `status="error"`, `error_code="worker_failed"` with the exception
  text; the worker does not exit.
- `inference_ms` measures only the `predict` call; load time goes in `ready.load_ms`.
- `peak_rss_kb` = `resource.getrusage(RUSAGE_SELF).ru_maxrss` on Linux (kB); `None` with a
  `peak_rss_reason` on platforms where the unit differs (macOS reports bytes) — spec §3 M2.
- Checkpoint identity: `checkpoint_sha256` = SHA-256 over the sorted relative paths + bytes of
  `*.safetensors`/`*.json` files under `checkpoint_path` (null if the directory is missing — but a
  missing directory is a `checkpoint_missing` fatal error anyway).

---

## Implementation Blueprint

### Steps (in order)
1. Write `pyproject.toml` — *why*: the README (TASK-3618) and the runtime (TASK-3610) reference this manifest as the only sanctioned install path.
2. Write `worker.py` top-down: constants, `_emit`, `_answer_*` validators, `Predictor` protocol, `FakePredictor`-friendly `serve()`, `load_predictor()`, `main()` — *why*: `serve()` must be testable without `laya`, so everything Laya-specific lives in `load_predictor()`/`LayaPredictor`.
3. Write the tests: in-memory `serve()` tests first, then the `python -m artifacts.laya.worker` subprocess test with `laya` absent — *why*: the dependency-missing path is the one every fresh checkout hits.
4. `git add -f` the three files.

### `artifacts/laya/pyproject.toml` (CREATE)
```toml
# Standalone environment for the Laya CPU worker (FEAT-589). NOT a uv workspace member.
# Create with:  uv venv artifacts/laya/.venv --python 3.12 && uv pip install --python artifacts/laya/.venv/bin/python -e artifacts/laya
[project]
name = "laya-cpu-evaluation-worker"
version = "0.1.0"
description = "Isolated CPU inference worker for the FEAT-589 Laya evaluation (not published)"
requires-python = ">=3.10"
dependencies = [
    "laya==0.3.5",  # FILL IN: confirm the PyPI distribution name for github.com/NandhaKishorM/laya before locking — bounded by spec §7 "verify installable distribution"
]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools]
py-modules = ["worker"]
```
**Why**: torch/transformers/safetensors/huggingface_hub/numpy resolve transitively inside this
environment only (spec §7 table); their exact versions are captured in the `ready` record, not pinned here.

### `artifacts/laya/worker.py` (CREATE — protocol core)
```python
"""Synchronous CPU inference worker for the Laya evaluation (spec §3 Module 2). Stdlib only; ``laya`` optional.

Run inside the isolated environment:  <worker_python> -m artifacts.laya.worker --checkpoint <dir> --revision <rev>
"""
from __future__ import annotations

import argparse
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
            # FILL IN: if answers lacks a qid or has a non-dict value -> status error worker_failed; else status ok
            #          — bounded by spec §2 "Each response echoes the request ID. Reject malformed/mismatched records."
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
```
**Why this shape**: `serve()` takes streams and a `Predictor`, so the whole protocol is unit-testable
with `io.StringIO` and a fake — no Laya, no subprocess. Error records carry the twelve-code
vocabulary from `models.ERROR_CODES` by string (the worker cannot import it).

### `artifacts/laya/worker.py` (CREATE — continued: Laya loading and `main`)
```python
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
```
`_checkpoint_sha256`, `_package_versions` (via `importlib.metadata.version`, `None` on
`PackageNotFoundError`) and `_torch_threads` (`torch.get_num_threads()` or `None`) are small
helpers you add above `load_predictor`.
**Why this shape**: the three fatal startup paths map to three stable codes and exit 3; the host
(TASK-3610) reads exactly one first line and decides. Everything Laya-specific is inside
`LayaPredictor`/`load_predictor`, so `serve()` and `main()`'s error paths are testable today.

### `packages/ai-parrot/tests/unit/laya_eval/test_laya_worker.py` (CREATE)
```python
"""FEAT-589 M2 — worker protocol with a fake predictor; dependency-missing path as a real subprocess."""
from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

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
    req = json.dumps({"request_id": "r3", "state": "s", "questions": {"q": {"type": "choice", "text": "t", "options": ["a", "b"]}}})
    (rec,) = _run([req], _Fake(error=RuntimeError("boom")))
    assert rec["status"] == "error" and rec["error_code"] == "worker_failed" and "boom" in rec["error_message"]


def test_main_without_laya_emits_dependency_missing_and_exit_3(tmp_path):
    proc = subprocess.run([sys.executable, "-m", "artifacts.laya.worker", "--checkpoint", str(tmp_path), "--revision", "x"],
                          cwd=REPO_ROOT, capture_output=True, text=True, timeout=60)
    # FILL IN: if `laya` IS importable in this interpreter, pytest.skip — bounded by "skips never presented as evidence" (spec §4)
    assert proc.returncode == 3
    first = json.loads(proc.stdout.splitlines()[0])
    assert first["type"] == "error" and first["error_code"] == "dependency_missing"


def test_main_with_missing_checkpoint_dir():
    # FILL IN: nonexistent --checkpoint -> first line error_code == "checkpoint_missing" (only when laya importable; else skip) — spec §2
    raise NotImplementedError
```
**Why**: spec §4 "Worker protocol/deadlines" (worker half): stderr noise, malformed ids, predictor
failures, dependency-missing. Deadlines/cancellation are host-side (TASK-3610).

### FILL IN checklist
- [ ] `pyproject.toml` — confirm distribution name for `laya==0.3.5`
- [ ] `worker.py::serve` — answers completeness check → `worker_failed`
- [ ] `worker.py::_to_laya_questions` / `_from_laya_answers` / `load_predictor` kwargs / `max_input_tokens` — verified against installed runtime (TASK-3618 re-checks)
- [ ] `test_laya_worker.py` — skip guards when `laya` is importable; checkpoint-missing test

---

## Acceptance Criteria

- [ ] AC-1 — `serve()` never raises on malformed input or predictor errors; every emitted record is one JSON line with a `type`.
- [ ] AC-2 — `python -m artifacts.laya.worker --help` works in the workspace venv (no `laya`).
- [ ] AC-3 — Without `laya`, `main()` emits a `dependency_missing` error record and exits 3.
- [ ] AC-4 — `worker.py` imports no `parrot`, `pydantic` or `artifacts.*` symbol at module scope.
- [ ] `ruff check artifacts/laya/worker.py` clean.

## Validation Commands
- `pytest packages/ai-parrot/tests/unit/laya_eval/test_laya_worker.py -q`

---

## Test Specification

See the CREATE block above. Add a test that a `noul` answer of `{"noul": 0.01, "confidence": 0.99}`
from the fake is passed through untouched (the worker must not "fix" a confident negative).

---

## Agent Instructions

1. Read spec §2 "Overview", §3 Module 2 and §7 "External Dependencies".
2. Confirm TASK-3605 is completed. Do NOT install Laya; do NOT download weights.
3. Implement from the Blueprint; run the Validation Command and `python -m artifacts.laya.worker --help`.
4. `git add -f` the three files, commit, move this file, update the index, fill the Completion Note —
   state explicitly which Laya call-shape `FILL IN`s remain unverified for TASK-3618.

---

## Completion Note

**Completed by**: sdd-coder (native, backend=native, model=sonnet, attempt_uid=df9247b8d4c342f4ae60a1dcd8c0b1f0), consolidated by sdd-worker orchestrator
**Date**: 2026-09-22
**Notes**: Implemented `artifacts/laya/worker.py`, `artifacts/laya/pyproject.toml` (pinned `laya==0.3.5`,
verified live against PyPI) and `packages/ai-parrot/tests/unit/laya_eval/test_laya_worker.py` exactly per
the Implementation Blueprint. Only stdlib imports at module scope; `laya` imported solely inside
`load_predictor()`, guarded by `ImportError` → `dependency_missing` (exit 3). Resolved FILL IN item 2
(incomplete-answers rejection in `serve()`); left items covering the real Laya call shape
(`_to_laya_questions`, `_from_laya_answers`, `Agent()` kwargs, `max_input_tokens`) as `NotImplementedError`
placeholders bounded to TASK-3618's real-runtime verification, per spec §3 (M2 is not delegation-eligible).
Merge-tier validation: `packages/ai-parrot/tests/unit/laya_eval/` — 28/28 passed (chunk with TASK-3606).
2 residual `E741` (ambiguous variable name `l`) findings in the test file deferred to the feature-wide
`/sdd-done` lint pass, per policy — not corrected here. Implementation landed at merge commit `a2180e8da`;
this SDD-state closure commit follows TASK-3606's closure (HEAD order), so it was closed manually rather
than via `scripts.sdd.finalize_task` (which requires implementation_sha == exact current HEAD, and this
task's code commit is no longer at HEAD once the sibling task's closure commit landed first).

**Deviations from spec**: none
