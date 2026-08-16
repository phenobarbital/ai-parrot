# TASK-2044: Groundedness Unit + Integration Tests and Canonical Fixtures

**Feature**: FEAT-398 — Deterministic Groundedness Scoring
**Spec**: `sdd/specs/deterministic-groundedness-scoring.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2043
**Assigned-to**: unassigned

---

## Context

Spec §4 test specification. Consolidates the full test suite: unit tests for
extractors (M1), scorer (M2), and reporting seam (M3), integration tests
(end-to-end `ask()` and `ask_stream()` with mock-LLM bot), and the five
canonical prototype fixtures stored as YAML. Each preceding task should write
inline smoke tests for its own code; this task ensures comprehensive coverage
across the full pipeline and the canonical cases from the brainstorm prototype.

---

## Scope

- Create `tests/fixtures/groundedness/` directory with canonical YAML fixtures:
  - Two tool outputs + five answer cases with expected per-atom verdicts
    (faithful, transposed digits, invented identifiers, no hard data, rounded
    paraphrase). Sourced from brainstorm Appendix A.
- Create `tests/unit/security/test_groundedness_extractors.py` — comprehensive
  extractor tests (per-kind, de-overlap, NFKC, `min_number_digits`).
- Create `tests/unit/security/test_groundedness_normalize.py` — normalization
  tests (magnitude suffixes, separators, date formats, sig-digit counting).
- Create `tests/unit/security/test_groundedness_scorer.py` — scorer + evidence
  index tests (canonical cases, precision tolerance, determinism, edge cases).
- Create `tests/unit/security/test_groundedness_guardrail.py` — guardrail plugin
  tests (flag-only invariant, non-fatal exception, telemetry hygiene).
- Create `tests/integration/test_groundedness_end_to_end.py`:
  - `test_ask_end_to_end`: mock-LLM bot + stub tools → `ask()` returns report.
  - `test_ask_stream_end_to_end`: same via `ask_stream()`.
  - `test_default_off`: without `enable_groundedness`, no report, no scoring cost.

**NOT in scope**: Performance benchmarks (TASK-2045), documentation.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/fixtures/groundedness/canonical_cases.yaml` | CREATE | Canonical test corpus (5 cases) |
| `tests/fixtures/groundedness/__init__.py` | CREATE | Empty init |
| `tests/unit/security/__init__.py` | CREATE (if absent) | Empty init |
| `tests/unit/security/test_groundedness_extractors.py` | CREATE | Extractor unit tests |
| `tests/unit/security/test_groundedness_normalize.py` | CREATE | Normalization unit tests |
| `tests/unit/security/test_groundedness_scorer.py` | CREATE | Scorer + evidence unit tests |
| `tests/unit/security/test_groundedness_guardrail.py` | CREATE | Guardrail plugin tests |
| `tests/integration/test_groundedness_end_to_end.py` | CREATE | End-to-end integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# From this feature (TASK-2041/2042/2043)
from parrot.security.groundedness.models import Atom, AtomKind
from parrot.security.groundedness.extractors import extract_atoms
from parrot.security.groundedness.normalize import (
    normalize_number, normalize_date, count_significant_digits,
)
from parrot.security.groundedness.evidence import EvidenceIndex
from parrot.security.groundedness.scorer import GroundednessScorer
from parrot.security.groundedness.policy import (
    GroundednessPolicy, GroundednessReport, AtomVerdict,
)
from parrot.security.groundedness.guardrail import GroundednessGuardrail

# From existing codebase
from parrot.models.basic import ToolCall              # models/basic.py:23
from parrot.models.responses import AIMessage         # models/responses.py:72
```

### Does NOT Exist

- ~~`parrot.security.pii`~~ — FEAT-324, not implemented.
- ~~`parrot.security.groundedness.test_utils`~~ — no test utils module. Build fixtures locally.

---

## Implementation Notes

### Key Constraints

- Tests must use `pytest` and `pytest-asyncio` for async tests.
- Canonical fixtures from the brainstorm prototype (Appendix A):
  1. **Faithful**: answer echoes evidence exactly → score 1.0.
  2. **Transposed digits**: `$1,234,500` vs evidence `$1,243,500` → `contradicted`.
  3. **Invented identifiers**: `INV-9999`, `bob@other.com` not in evidence → `unsupported`.
  4. **No hard data**: "Thank you for your question." → `no_factual_content`, score 1.0.
  5. **Rounded paraphrase**: `$1.24M` vs evidence `$1,240,000` → `supported` (precision tolerance).
- Integration tests use a mock-LLM bot pattern — check existing test patterns.
- **Scoring-only invariant** must be tested: response text byte-identical with scoring on vs off.
- **Determinism** must be tested: 100 runs → identical JSON reports.
- **Telemetry no-values** test: capture log output, assert no atom raw values leaked.

### References in Codebase

- `tests/unit/` — existing test structure and patterns.
- `tests/integration/` — existing integration test patterns.
- Brainstorm Appendix A: `sdd/proposals/deterministic-groundedness-scoring.brainstorm.md`.

---

## Acceptance Criteria

- [ ] All 5 canonical prototype cases pass with expected verdicts.
- [ ] Extractor tests: per-kind positive/negative, de-overlap, NFKC, min_number_digits.
- [ ] Normalization tests: magnitude suffixes, separators, date formats, sig-digit counting.
- [ ] Scorer tests: exact match, precision tolerance, contradicted band, edge cases.
- [ ] Determinism test: 100 runs → identical JSON reports.
- [ ] Guardrail tests: flag-only invariant, non-fatal exception, telemetry hygiene.
- [ ] Integration: `ask()` end-to-end produces report in `metadata`.
- [ ] Integration: `ask_stream()` end-to-end produces report on final `AIMessage`.
- [ ] Integration: default off → no report, no scoring overhead.
- [ ] All tests pass: `pytest tests/unit/security/test_groundedness_* tests/integration/test_groundedness_* -v`
- [ ] No linting errors in test files.

---

## Test Specification

See spec §4 for the full test matrix. Key tests:

```python
# tests/integration/test_groundedness_end_to_end.py
import pytest
from parrot.models.basic import ToolCall


@pytest.fixture
def stub_bot_with_tools():
    """Mock-LLM bot configured with enable_groundedness=True and stub tools."""
    ...


class TestEndToEnd:
    @pytest.mark.asyncio
    async def test_ask_end_to_end(self, stub_bot_with_tools):
        """ask() returns AIMessage with groundedness report in metadata."""
        result = await stub_bot_with_tools.ask("What was the revenue?")
        report = result.metadata.get("guardrails", {}).get("groundedness")
        assert report is not None
        assert report["score"] >= 0.0

    @pytest.mark.asyncio
    async def test_ask_stream_end_to_end(self, stub_bot_with_tools):
        """ask_stream() final AIMessage has report."""
        messages = []
        async for msg in stub_bot_with_tools.ask_stream("What was the revenue?"):
            messages.append(msg)
        final = messages[-1]
        report = final.metadata.get("guardrails", {}).get("groundedness")
        assert report is not None

    @pytest.mark.asyncio
    async def test_default_off(self):
        """Without enable_groundedness, no report and no scoring cost."""
        # Bot without enable_groundedness → metadata has no "groundedness" key
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/deterministic-groundedness-scoring.spec.md` §4 for full test spec
2. **Read the brainstorm** at `sdd/proposals/deterministic-groundedness-scoring.brainstorm.md` Appendix A for canonical fixtures
3. **Check dependencies** — verify TASK-2043 is done
4. **Update status** in `sdd/tasks/index/deterministic-groundedness-scoring.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Run** `pytest tests/unit/security/test_groundedness_* tests/integration/test_groundedness_* -v`
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-2044-groundedness-tests.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.5)
**Date**: 2026-08-01
**Notes**: Implemented the full test suite under `packages/ai-parrot/tests/`
(the existing home of all groundedness code and prior security test files):
`tests/fixtures/groundedness/canonical_cases.yaml` — the 5 canonical
prototype cases from the brainstorm's Appendix A (faithful, transposed
digits, invented identifiers, no hard data, rounded paraphrase), all
scored against the SAME two shared tool-output evidence strings so the
fixture exercises exact-match / precision-tolerance / contradicted-band /
no-factual-content behavior against one consistent evidence set;
`tests/unit/security/test_groundedness_extractors.py` (per-kind
positive/negative, de-overlap, NFKC fullwidth-digit pre-pass,
`min_number_digits` noise floor incl. the magnitude-suffix exemption);
`tests/unit/security/test_groundedness_normalize.py` (magnitude suffixes,
separators, sign handling, all 3 date formats + error paths,
`count_significant_digits` incl. the degenerate all-zero literal);
`tests/unit/security/test_groundedness_scorer.py` (exact match, kind
isolation — a money claim is never "supported" by same-valued
percent/number evidence, precision-aware tolerance, contradicted band,
`no_evidence`/`no_factual_content` edge cases, 100-run determinism via
`model_dump_json()` equality, and the 5 canonical cases parametrized
against the shared YAML fixture); `tests/unit/security/
test_groundedness_guardrail.py` (FLAG-only invariant — `result.content`
is always `None`, never TRANSFORM/BLOCK; non-fatal degradation to PASS on
both a `scorer.score()` exception AND an `EvidenceIndex.from_tool_calls()`
exception; graceful `no_evidence` fallback when `ctx.extras['ai_message']`
is absent; telemetry hygiene — atom raw values from both answer and
evidence never appear in `caplog`, only score/counts; the `min_alert_score`
INFO log); `tests/integration/test_groundedness_end_to_end.py` (`ask()`
and `ask_stream()` full round trips via a `_patched_bot`/fake-LLM pattern
mirroring the existing `test_guardrails_input_migration.py`/
`test_guardrails_output.py` suites — `enable_groundedness=True` attaches
the report to `AIMessage.metadata["guardrails"]["groundedness"]` on both
entrypoints' final message; `enable_groundedness=False` (default) leaves
`metadata["guardrails"]` free of a `"groundedness"` key and leaves
`response.output` byte-identical, proving the scoring-only invariant
end-to-end). Verified every canonical case's expected verdict/score by
hand-tracing the actual `extract_atoms`/`normalize_number`/
`count_significant_digits`/`GroundednessScorer._classify_numeric` logic
against the fixture's evidence and answer text before asserting, per the
Codebase Contract's anti-hallucination discipline — no test assertion was
written against an assumed/hoped-for behavior. All 94 new tests pass;
`ruff check` clean (one auto-fixable import-order finding, fixed); the
pre-existing guardrails suite (`test_guardrails_core_models.py`,
`test_guardrails_pipeline.py`, `test_guardrails_registry_config.py`,
`test_guardrails_output.py` — 61 tests) still passes unmodified,
confirming no regression from the new fixtures/imports.

**Deviations from spec**:
1. **Path prefix**: the Scope/Files table lists paths as `tests/...`
   without a package prefix; placed all files under
   `packages/ai-parrot/tests/...` — the existing (and only) home of
   `tests/unit/security/`-adjacent security tests, the guardrails test
   suite, and the `parrot.security.groundedness` package itself under
   `packages/ai-parrot/src/`. No ambiguity once the existing repo layout
   is checked (a monorepo of `packages/*` distributions, not a
   single-package repo).
2. **Integration test client-seam split**: `ask()` resolves its LLM client
   via `self.get_client()` (async-context-manager) + the overridable
   `execute_llm_call()` hook — mocked exactly as `_wire_fake_llm` does in
   `test_guardrails_input_migration.py`. `ask_stream()` instead reads
   `self._llm` directly (an async-context-manager whose `.ask_stream()` is
   an async generator) — not documented in the task's Codebase Contract,
   discovered by reading `bots/base.py`'s `ask_stream()` implementation
   directly. Both seams are pre-existing, unmodified bot internals; no
   production code changed to accommodate the tests.
3. **Extra assertions beyond the Test Specification skeleton**: added a
   `test_ask_stream_default_off_no_report` and a
   `test_default_off`-response-text-identity assertion (byte-identical
   `result.output` with scoring on vs off) — direct evidence for the
   scoring-only invariant AC that the skeleton's `test_default_off`
   docstring names but the given `...` stub did not assert.
