# TASK-2045: Performance Benchmarks and Documentation

**Feature**: FEAT-398 — Deterministic Groundedness Scoring
**Spec**: `sdd/specs/deterministic-groundedness-scoring.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2044
**Assigned-to**: unassigned

---

## Context

Spec §4 (Performance Benchmarks) and §5 acceptance criterion on documentation.
Adds benchmark tests that gate on the latency budget (p99 < 10 ms for the
typical case) and documents the feature's semantics and honest limitations in
`docs/`.

---

## Scope

- Create `tests/benchmarks/test_groundedness_perf.py`:
  - Benchmark 1: 1 KB answer vs 3×2 KB evidence → p99 < 10 ms (spec gate).
  - Benchmark 2: 4 KB answer vs 10 tools × 4 KB → p99 < 50 ms (informational).
  - Use `time.perf_counter()` over 1000 iterations, report p50/p99/max.
- Create `docs/groundedness.md` — user-facing documentation:
  - What the scorer does and doesn't do (tripwire, not truth oracle).
  - How to enable: `enable_groundedness=True`, `groundedness_policy={...}`.
  - Report semantics: `supported`, `contradicted`, `unsupported` verdicts.
  - Policy knobs: `min_number_digits`, `contradicted_band`, `min_alert_score`,
    `max_evidence_bytes`, `include_user_prompt_as_evidence`, `enabled_kinds`.
  - Known limits: en-US locale bias, small-integer blindness, legitimate
    outside knowledge scores `unsupported`.

**NOT in scope**: Implementation code (TASK-2041/2042/2043), unit/integration tests (TASK-2044).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/benchmarks/test_groundedness_perf.py` | CREATE | Latency benchmarks |
| `docs/groundedness.md` | CREATE | User-facing documentation |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# From this feature
from parrot.models.basic import ToolCall
from parrot.security.groundedness.evidence import EvidenceIndex
from parrot.security.groundedness.scorer import GroundednessScorer
from parrot.security.groundedness.policy import GroundednessPolicy
```

### Does NOT Exist

- ~~`tests/benchmarks/`~~ — may or may not exist; create directory if absent.
- ~~`pytest-benchmark`~~ — do NOT add external deps; use raw `time.perf_counter()`.

---

## Implementation Notes

### Key Constraints

- Benchmarks use `time.perf_counter()` directly (no external benchmark libraries).
- Run 1000 iterations, compute p50/p99/max from sorted durations.
- The p99 < 10 ms gate is a hard acceptance criterion (spec §5).
- Documentation must be honest about limitations (spec §7 Known Risks).
- No new runtime dependencies.

### References in Codebase

- `docs/` — existing documentation structure.
- `tests/benchmarks/` — may contain existing benchmarks to follow as pattern.

---

## Acceptance Criteria

- [ ] Benchmark 1 (1 KB answer vs 3×2 KB evidence): p99 < 10 ms.
- [ ] Benchmark 2 (4 KB answer vs 10×4 KB evidence): p99 < 50 ms.
- [ ] Documentation covers: enablement, report semantics, policy knobs, honest limits.
- [ ] Benchmarks pass: `pytest tests/benchmarks/test_groundedness_perf.py -v`
- [ ] No linting errors in new files.

---

## Test Specification

```python
# tests/benchmarks/test_groundedness_perf.py
import time
import pytest
from parrot.models.basic import ToolCall
from parrot.security.groundedness.evidence import EvidenceIndex
from parrot.security.groundedness.scorer import GroundednessScorer
from parrot.security.groundedness.policy import GroundednessPolicy


class TestGroundednessPerf:
    def test_typical_case_p99_under_10ms(self):
        """1 KB answer vs 3×2 KB evidence: p99 < 10 ms."""
        policy = GroundednessPolicy()
        scorer = GroundednessScorer(policy)
        answer = "Revenue was $1,243,500 for Q2 2026. " * 25  # ~1 KB
        tc = [
            ToolCall(id=str(i), name=f"tool_{i}", arguments={},
                     result="x" * 2048)
            for i in range(3)
        ]
        idx = EvidenceIndex.from_tool_calls(tc, policy)

        durations = []
        for _ in range(1000):
            start = time.perf_counter()
            scorer.score(answer, idx)
            durations.append((time.perf_counter() - start) * 1000)

        durations.sort()
        p99 = durations[int(len(durations) * 0.99)]
        assert p99 < 10.0, f"p99={p99:.2f}ms exceeds 10ms gate"

    def test_heavy_case_p99_under_50ms(self):
        """4 KB answer vs 10×4 KB evidence: p99 < 50 ms."""
        policy = GroundednessPolicy()
        scorer = GroundednessScorer(policy)
        answer = "Revenue was $1,243,500 for Q2 2026. " * 100  # ~4 KB
        tc = [
            ToolCall(id=str(i), name=f"tool_{i}", arguments={},
                     result="x" * 4096)
            for i in range(10)
        ]
        idx = EvidenceIndex.from_tool_calls(tc, policy)

        durations = []
        for _ in range(1000):
            start = time.perf_counter()
            scorer.score(answer, idx)
            durations.append((time.perf_counter() - start) * 1000)

        durations.sort()
        p99 = durations[int(len(durations) * 0.99)]
        assert p99 < 50.0, f"p99={p99:.2f}ms exceeds 50ms gate"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/deterministic-groundedness-scoring.spec.md` §4-§5 for benchmark and doc requirements
2. **Check dependencies** — verify TASK-2044 is done
3. **Update status** in `sdd/tasks/index/deterministic-groundedness-scoring.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Run** `pytest tests/benchmarks/test_groundedness_perf.py -v`
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2045-groundedness-benchmarks-docs.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.5)
**Date**: 2026-08-01
**Notes**: Created `packages/ai-parrot/tests/benchmarks/test_groundedness_perf.py`
following the task's own Test Specification skeleton (raw
`time.perf_counter()`, 1000 iterations, p50/p99/max computed from sorted
durations, printed for visibility with `-s`): Benchmark 1 (1 KB answer vs
3×2 KB tool-output evidence) asserts the spec's hard p99 < 10 ms gate —
measured p99 ≈ 1.2 ms; Benchmark 2 (4 KB answer vs 10×4 KB evidence)
asserts the informational p99 < 50 ms gate — measured p99 ≈ 6.1 ms. Both
comfortably clear their gates (not flaky-close). Deliberately did NOT use
the `pytest-benchmark` plugin/`@pytest.mark.benchmark` marker even though
it is already a dev-dependency used by sibling suites
(`test_guardrails_pipeline_perf.py`) — the Codebase Contract explicitly
lists it under "Does NOT Exist" for this task ("do NOT add external
deps; use raw time.perf_counter()"), and unmarked tests run in normal
`pytest` invocations (not skipped by `tests/benchmarks/conftest.py`,
which only skips tests carrying the `benchmark` keyword), matching the
AC's plain `pytest tests/benchmarks/test_groundedness_perf.py -v` command.
Created `docs/groundedness.md` (repo-root `docs/` — confirmed as the
correct location: the spec's own AC literally says "Documentation
updated in `docs/`", and root `docs/` holds 85 other feature docs vs.
the sparse `packages/ai-parrot/docs/` which holds only one unrelated
FEAT-176 file): covers what the scorer does/doesn't do (tripwire, not
truth oracle), enablement (`enable_groundedness`/`groundedness_policy`,
dict-or-model), where the report lands on both `ask()` and
`ask_stream()`, full report-field semantics including the
precision-aware tolerance rule (with the prototype's own
fixed-tolerance rejection rationale), every `GroundednessPolicy` knob,
the four honest known limits from spec §7 (small-integer blindness,
outside-knowledge-scores-unsupported, en-US locale bias, not a
semantic-hallucination replacement), and a performance table pulling the
just-measured p50/p99/max numbers. Verified benchmarks pass and `ruff
check` is clean on the new benchmark file; re-ran the full groundedness
suite (94 unit/integration tests from TASK-2044 + these 2 benchmarks =
96) to confirm no regression.

**Deviations from spec**: none — one path clarification only (see
Notes above: `docs/groundedness.md` resolved to repo-root `docs/`,
matching both the task's literal path and the spec's own AC wording).
