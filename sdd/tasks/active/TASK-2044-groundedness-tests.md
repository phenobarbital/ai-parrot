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

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
