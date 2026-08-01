# TASK-2042: Evidence Index, Scorer, and Policy Models

**Feature**: FEAT-398 — Deterministic Groundedness Scoring
**Spec**: `sdd/specs/deterministic-groundedness-scoring.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2041
**Assigned-to**: unassigned

---

## Context

Module 2 of the groundedness scoring pipeline (spec §3 Module 2). Builds the
`EvidenceIndex` from `ToolCall.result` payloads, the `GroundednessScorer` with
precision-aware tolerance, and the policy/report Pydantic models. This is the
computational core — deterministic, sync, stdlib-only.

---

## Scope

- Create `parrot/security/groundedness/policy.py`:
  - `GroundednessPolicy` — per-agent scoring policy (enabled kinds, tolerance
    params, evidence caps, `min_number_digits`, `include_user_prompt_as_evidence`,
    `contradicted_band`, `min_alert_score`, `max_evidence_bytes`).
  - `AtomVerdict` — per-atom verdict model (`atom`, `verdict`, `nearest_evidence`).
  - `GroundednessReport` — aggregate report model (`score`, `total_atoms`,
    `supported/contradicted/unsupported` lists, flags, `duration_ms`).
- Create `parrot/security/groundedness/evidence.py`:
  - `EvidenceIndex.from_tool_calls(tool_calls, policy, user_prompt)` — recursive
    value traversal of `ToolCall.result` (dict/list payloads), extract atoms from
    each, store per-kind hash-sets (exact match) + numeric list (tolerance checks).
    Bounded by `max_evidence_bytes` with `evidence_truncated` flag. Optional
    user-prompt evidence inclusion.
- Create `parrot/security/groundedness/scorer.py`:
  - `GroundednessScorer.score(answer_text, evidence)` → `GroundednessReport`.
  - Matching logic per answer atom:
    1. Exact normalized match in evidence hash-set → `supported`.
    2. Numeric: precision-aware tolerance (half-unit of answer's last stated
       significant digit) → `supported`.
    3. Same-magnitude numeric within `contradicted_band` (default ≤15%) →
       `contradicted` (attach `nearest_evidence`).
    4. Otherwise → `unsupported`.
  - Edge cases: no atoms → `score=1.0, no_factual_content=True`;
    no tool calls → `score=1.0, no_evidence=True`.
  - Timing: `time.perf_counter()` around scoring, reported in `duration_ms`.
- Update `parrot/security/groundedness/__init__.py` exports.

**NOT in scope**: Bot wiring, guardrail plugin, tests (separate tasks), benchmarks.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/security/groundedness/policy.py` | CREATE | `GroundednessPolicy`, `AtomVerdict`, `GroundednessReport` |
| `packages/ai-parrot/src/parrot/security/groundedness/evidence.py` | CREATE | `EvidenceIndex` |
| `packages/ai-parrot/src/parrot/security/groundedness/scorer.py` | CREATE | `GroundednessScorer` |
| `packages/ai-parrot/src/parrot/security/groundedness/__init__.py` | MODIFY | Add public exports |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# From TASK-2041 (this feature)
from parrot.security.groundedness.models import Atom, AtomKind
from parrot.security.groundedness.extractors import extract_atoms
from parrot.security.groundedness.normalize import count_significant_digits

# From existing codebase
from parrot.models.basic import ToolCall        # models/basic.py:23
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/models/basic.py:23
class ToolCall(BaseModel):
    id: str
    name: str
    arguments: Dict[str, Any]
    result: Optional[Any] = None      # line 28 — evidence payload
    error: Optional[str] = None
    execution_time: Optional[float] = None

# Policy-model template — ObservabilityConfig pattern:
# packages/ai-parrot/src/parrot/observability/config.py:18
class ObservabilityConfig(BaseModel):
    # ... Pydantic model with defaults, validators, from_env classmethod
```

### Does NOT Exist

- ~~`parrot.security.groundedness.evidence`~~ — created by THIS task.
- ~~`parrot.security.groundedness.scorer`~~ — created by THIS task.
- ~~`parrot.security.groundedness.policy`~~ — created by THIS task.
- ~~`parrot.security.pii`~~ — FEAT-324, not implemented. Do NOT import.
- ~~`ToolCall.evidence`~~ — not a field. Use `ToolCall.result`.
- ~~`AIMessage.groundedness`~~ — not a field. Report goes in `metadata` dict.

---

## Implementation Notes

### Pattern to Follow

```python
# policy.py — spec §2 Data Models
class GroundednessPolicy(BaseModel):
    enabled_kinds: list[AtomKind] = Field(default_factory=lambda: list(AtomKind))
    include_user_prompt_as_evidence: bool = True
    contradicted_band: float = 0.15
    min_alert_score: float = 0.8
    max_evidence_bytes: int = 262_144
    min_number_digits: int = 4

class GroundednessReport(BaseModel):
    score: float                      # supported / total_atoms; 1.0 if none
    total_atoms: int
    supported: list[AtomVerdict]
    contradicted: list[AtomVerdict]
    unsupported: list[AtomVerdict]
    no_factual_content: bool = False
    no_evidence: bool = False
    evidence_truncated: bool = False
    duration_ms: float
```

### Key Constraints

- **Deterministic**: same (answer, evidence) → identical report. No randomness,
  no floats that might differ across platforms (use `Decimal` or careful rounding
  if needed for tolerance comparison).
- Precision-aware tolerance: half a unit of the answer's last stated significant
  digit. `$1.24M` (3 sig digits) → tolerance = ±5000 (half of 10000, the place
  value of the last digit). `$1,234,500` (7 sig digits) → tolerance = ±0.5.
- `contradicted` band: same-magnitude numeric within `contradicted_band` (≤15%)
  but outside precision tolerance. Attach `nearest_evidence` for diagnostics.
- Recursive value traversal for `ToolCall.result`: dicts → traverse values,
  lists → traverse items, strings → extract atoms, other types → `str()`.
- `max_evidence_bytes` cap: sum `len(str(result))` across tool calls; stop
  adding evidence once cap is reached, set `evidence_truncated=True`.
- All sync. Google-style docstrings, strict type hints.

### References in Codebase

- `packages/ai-parrot/src/parrot/models/basic.py:23` — `ToolCall` model.
- `packages/ai-parrot/src/parrot/observability/config.py:18` — `ObservabilityConfig` policy pattern.

---

## Acceptance Criteria

- [ ] `EvidenceIndex.from_tool_calls()` builds from `ToolCall.result` with dict/list traversal.
- [ ] `max_evidence_bytes` cap triggers `evidence_truncated` flag.
- [ ] User-prompt evidence toggle works (`include_user_prompt_as_evidence`).
- [ ] Scorer: faithful answer → score 1.0.
- [ ] Scorer: transposed `$1,234,500` vs evidence `$1,243,500` → `contradicted`.
- [ ] Scorer: invented `INV-9999` / foreign email → `unsupported`.
- [ ] Scorer: no hard-data atoms → `no_factual_content=True`, score 1.0.
- [ ] Scorer: no tool calls → `no_evidence=True`, score 1.0.
- [ ] Scorer: rounded `$1.24M` vs evidence `$1,240,000` → `supported` (precision-aware tolerance).
- [ ] Full-precision `$1,234,500` vs evidence `$1,234,500` → `supported` (exact match).
- [ ] Determinism: identical inputs → byte-identical JSON report across 100 runs.
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/security/groundedness/`
- [ ] Imports work: `from parrot.security.groundedness.scorer import GroundednessScorer`

---

## Test Specification

```python
# tests/unit/security/test_groundedness_scorer.py
import pytest
from parrot.models.basic import ToolCall
from parrot.security.groundedness.evidence import EvidenceIndex
from parrot.security.groundedness.scorer import GroundednessScorer
from parrot.security.groundedness.policy import GroundednessPolicy, GroundednessReport


@pytest.fixture
def policy():
    return GroundednessPolicy()


@pytest.fixture
def tool_calls_revenue():
    """Two tool calls returning revenue data."""
    return [
        ToolCall(id="1", name="get_revenue", arguments={},
                 result={"revenue": "$1,243,500", "quarter": "Q2 2026"}),
        ToolCall(id="2", name="get_clients", arguments={},
                 result={"clients": ["ACME Corp"], "contact": "alice@acme.com"}),
    ]


class TestEvidenceIndex:
    def test_builds_from_tool_calls(self, tool_calls_revenue, policy):
        idx = EvidenceIndex.from_tool_calls(tool_calls_revenue, policy)
        assert idx is not None

    def test_max_evidence_bytes(self, policy):
        policy.max_evidence_bytes = 10
        big_tc = [ToolCall(id="1", name="t", arguments={}, result="x" * 100)]
        idx = EvidenceIndex.from_tool_calls(big_tc, policy)
        assert idx.evidence_truncated


class TestScorer:
    def test_faithful_answer(self, tool_calls_revenue, policy):
        scorer = GroundednessScorer(policy)
        idx = EvidenceIndex.from_tool_calls(tool_calls_revenue, policy)
        report = scorer.score("Revenue was $1,243,500 for Q2 2026", idx)
        assert report.score == 1.0

    def test_transposed_digits_contradicted(self, tool_calls_revenue, policy):
        scorer = GroundednessScorer(policy)
        idx = EvidenceIndex.from_tool_calls(tool_calls_revenue, policy)
        report = scorer.score("Revenue was $1,234,500", idx)
        assert len(report.contradicted) > 0

    def test_invented_identifier_unsupported(self, tool_calls_revenue, policy):
        scorer = GroundednessScorer(policy)
        idx = EvidenceIndex.from_tool_calls(tool_calls_revenue, policy)
        report = scorer.score("Invoice INV-9999 from bob@other.com", idx)
        assert len(report.unsupported) >= 2

    def test_no_factual_content(self, tool_calls_revenue, policy):
        scorer = GroundednessScorer(policy)
        idx = EvidenceIndex.from_tool_calls(tool_calls_revenue, policy)
        report = scorer.score("Thank you for your question.", idx)
        assert report.no_factual_content is True
        assert report.score == 1.0

    def test_rounded_paraphrase_supported(self, policy):
        tc = [ToolCall(id="1", name="t", arguments={}, result={"val": "$1,240,000"})]
        scorer = GroundednessScorer(policy)
        idx = EvidenceIndex.from_tool_calls(tc, policy)
        report = scorer.score("Revenue was approximately $1.24M", idx)
        supported_money = [v for v in report.supported if v.atom.raw == "$1.24M"]
        assert len(supported_money) == 1

    def test_determinism(self, tool_calls_revenue, policy):
        scorer = GroundednessScorer(policy)
        idx = EvidenceIndex.from_tool_calls(tool_calls_revenue, policy)
        text = "Revenue was $1,243,500 for Q2 2026"
        reports = [scorer.score(text, idx).model_dump_json() for _ in range(100)]
        assert len(set(reports)) == 1
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/deterministic-groundedness-scoring.spec.md` for full context
2. **Check dependencies** — verify TASK-2041 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm TASK-2041 exports exist, confirm `ToolCall` at `models/basic.py:23`
4. **Update status** in `sdd/tasks/index/deterministic-groundedness-scoring.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2042-groundedness-scorer.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
