# TASK-3609: Worker token-budget preflight (reject context overflow, never truncate)

**Feature**: FEAT-589 — Evaluate Laya for typed classification and agent model routing
**Spec**: `sdd/specs/laya-adoption.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3608
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2: "Check tokenized input plus question/options against the checkpoint's actual
limits before calling inference. Reject overflow; no silent truncation of evidence." Spec §7 lists
silent truncation as a risk that would invalidate grounded results. This task adds the pure
preflight function to `worker.py` and wires it into `LayaPredictor.predict()` so an oversized
request becomes a `context_overflow` error result instead of a silently truncated answer.

The function is pure (takes a token-counting callable) so it is fully testable without Laya;
TASK-3618 verifies that the real tokenizer/limit wiring matches the installed runtime's
serialization behaviour.

---

## Scope

- Add `check_context_budget(count_tokens, state, questions, limit) -> str | None` to `worker.py`.
- Call it at the top of `LayaPredictor.predict()`; on overflow raise `ContextOverflow` (new
  exception) which `serve()` maps to `error_code="context_overflow"`.
- Write `packages/ai-parrot/tests/unit/laya_eval/test_laya_context_limits.py`.

**NOT in scope**: choosing the real tokenizer (that is `load_predictor`'s `FILL IN`, verified in TASK-3618).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `artifacts/laya/worker.py` | MODIFY | Add `ContextOverflow`, `check_context_budget`; wire into `LayaPredictor.predict` and `serve` |
| `packages/ai-parrot/tests/unit/laya_eval/test_laya_context_limits.py` | CREATE | Boundary/overflow tests with a fake token counter |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `1a7ccd5a1` on 2026-09-21; `worker.py` is created by TASK-3608 (its blueprint fixes the anchors below).

### Verified Imports
```python
from artifacts.laya import worker   # TASK-3608; symbols: serve, Predictor, LayaPredictor, _emit, _peak_rss_kb
```

### Existing Signatures to Use
```python
# artifacts/laya/worker.py (TASK-3608)
class LayaPredictor:
    def __init__(self, agent: Any, max_input_tokens: int | None) -> None
    def predict(self, state: str, questions: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]
def serve(stdin: Any, predictor: Predictor, out: Any = None) -> int   # `except Exception` -> worker_failed
```

### Does NOT Exist
- ~~`truncate=True` / `max_length` truncation in the worker~~ — forbidden by spec §3 M2.
- ~~a tokenizer in the host process~~ — counting happens only in the worker environment.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "artifacts/laya/worker.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/laya_eval/test_laya_context_limits.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Budget = tokens(state) + Σ tokens(question text) + Σ tokens(option) over all questions; overflow
  when `> limit`. Equal to the limit is allowed (boundary test).
- `limit is None` (unknown) → preflight returns `None` and the answer carries no overflow claim;
  the ready record already reports `max_input_tokens: null` so the report can disclose it.
- The error message names the counted tokens and the limit.

---

## Implementation Blueprint

### Steps (in order)
1. Add `ContextOverflow` and `check_context_budget` above `class LayaPredictor` — *why*: pure function first, testable without Laya.
2. Wire `predict()` and the `serve()` exception mapping — *why*: the overflow must surface as its own stable code, not as `worker_failed`.
3. Tests, then commit (`worker.py` is already tracked; `git add -f` the test).

### `artifacts/laya/worker.py` (MODIFY — new exception + preflight)
```python
# occurrences: 1 (verified: grep -c '^class LayaPredictor' artifacts/laya/worker.py)
# BEFORE — insert ABOVE `class LayaPredictor:`
class ContextOverflow(Exception):
    """Raised before inference when the tokenized request exceeds the checkpoint's input limit."""


def check_context_budget(count_tokens: Callable[[str], int], state: str,
                         questions: dict[str, dict[str, Any]], limit: int | None) -> str | None:
    """Return None when the request fits ``limit`` tokens, else a message describing the overflow.

    Counts ``state`` plus every question text and every choice option; never truncates anything
    (spec §3 Module 2). ``limit=None`` means the limit is unknown and the check is skipped.
    """
    if limit is None:
        return None
    total = count_tokens(state)
    for q in questions.values():
        total += count_tokens(q.get("text", ""))
        for opt in q.get("options", []) or []:
            total += count_tokens(str(opt))
    if total > limit:
        return f"request needs {total} tokens but the checkpoint accepts at most {limit}; evidence is not truncated"
    return None
```
(add `from collections.abc import Callable, Sequence` to the import block.)

### `artifacts/laya/worker.py` (MODIFY — wire into predict and serve)
```python
# occurrences: 1 (verified: grep -c 'laya_questions = _to_laya_questions(questions)' artifacts/laya/worker.py)
# BEFORE — insert ABOVE `        laya_questions = _to_laya_questions(questions)` inside LayaPredictor.predict
        problem = check_context_budget(self._count_tokens, state, questions, self.max_input_tokens)
        if problem:
            raise ContextOverflow(problem)
```
```python
# occurrences: 1 (verified: grep -c '        except Exception as exc:  # predictor failure' artifacts/laya/worker.py)
# BEFORE — insert ABOVE `        except Exception as exc:  # predictor failure: record, keep serving` in serve()
        except ContextOverflow as exc:
            _emit({"type": "result", "request_id": request_id, "status": "error", "answers": {}, "inference_ms": None,
                   "error_code": "context_overflow", "error_message": str(exc), "peak_rss_kb": _peak_rss_kb()}, out)
```
`self._count_tokens` is a new `LayaPredictor.__init__` parameter `count_tokens: Callable[[str], int]`
(default `lambda s: len(s.split())` so tests can construct it; `load_predictor` passes the real
tokenizer length — `# FILL IN: tokenizer from the loaded laya Agent — verified in TASK-3618`).
**Why**: overflow must be decided before `system_one` runs (spec §3 M2 "before calling inference").

### `packages/ai-parrot/tests/unit/laya_eval/test_laya_context_limits.py` (CREATE)
```python
"""FEAT-589 M2 — context budget preflight: boundary passes, overflow rejects, nothing is truncated."""
from __future__ import annotations

import io
import json

from artifacts.laya import worker

_COUNT = lambda s: len(s.split())  # noqa: E731 — deterministic fake tokenizer
_Q = {"category": {"type": "choice", "text": "which label", "options": ["billing", "technical"]}}


def test_exact_boundary_is_allowed():
    state = "one two three"
    budget = _COUNT(state) + _COUNT("which label") + 2
    assert worker.check_context_budget(_COUNT, state, _Q, budget) is None


def test_one_over_is_rejected_with_counts_in_message():
    state = "one two three"
    budget = _COUNT(state) + _COUNT("which label") + 2 - 1
    msg = worker.check_context_budget(_COUNT, state, _Q, budget)
    assert msg and str(budget) in msg and "truncated" in msg


def test_unknown_limit_skips_check():
    assert worker.check_context_budget(_COUNT, "x " * 10_000, _Q, None) is None


def test_overflow_surfaces_as_context_overflow_result_and_state_untouched():
    class _Agent:
        def __init__(self):
            self.seen = []

        def system_one(self, state, questions):
            self.seen.append(state)
            return {}

    agent = _Agent()
    predictor = worker.LayaPredictor(agent, max_input_tokens=3, count_tokens=_COUNT)
    req = json.dumps({"request_id": "big", "state": "a b c d e f", "questions": {"q": {"type": "noul", "text": "t"}}})
    out = io.StringIO()
    worker.serve(io.StringIO(req + "\n"), predictor, out)
    rec = json.loads(out.getvalue())
    assert rec["error_code"] == "context_overflow" and rec["request_id"] == "big"
    assert agent.seen == []  # inference never ran; nothing was truncated to make it fit


def test_fitting_request_reaches_the_agent_untruncated():
    # FILL IN: predictor with a large limit; assert agent.seen == [state] exactly (monkeypatch _to_laya_questions/_from_laya_answers to identity fakes) — spec §3 M2
    raise NotImplementedError
```
**Why**: the spec §4 "Context limits" row: "Boundary/overflow cases do not silently truncate state or options".

### FILL IN checklist
- [ ] `worker.py::LayaPredictor.__init__` — `count_tokens` parameter; `load_predictor` passes the real tokenizer
- [ ] `test_laya_context_limits.py::test_fitting_request_reaches_the_agent_untruncated`

---

## Acceptance Criteria

- [ ] AC-1 — Exactly-at-limit passes; one-over is rejected; the message names both numbers.
- [ ] AC-2 — An overflowing request yields `context_overflow` and `system_one` is never called.
- [ ] AC-3 — No code path shortens `state`, question text or options.
- [ ] `ruff check artifacts/laya/worker.py` clean.

## Validation Commands
- `pytest packages/ai-parrot/tests/unit/laya_eval/test_laya_context_limits.py -q`
- `pytest packages/ai-parrot/tests/unit/laya_eval/test_laya_worker.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. Read spec §3 Module 2 (preflight paragraph) and §7 "Silent input truncation".
2. Confirm TASK-3608 is completed; verify the three anchors with `grep -n` before editing.
3. Implement, run both Validation Commands, commit, move this file, update the index, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
