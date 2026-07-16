---
type: Wiki Overview
title: 'TASK-1480: SecurityAdvisoryEngine — day-over-day diff + SOC2 mapping'
id: doc:sdd-tasks-completed-task-1480-security-advisory-engine-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The advisor's deterministic brain. Given the cross-session report catalog,
  this
relates_to:
- concept: mod:parrot.storage.security_reports
  rel: mentions
- concept: mod:parrot_tools.security.advisory_engine
  rel: mentions
- concept: mod:parrot_tools.security.models
  rel: mentions
- concept: mod:parrot_tools.security.parsers
  rel: mentions
- concept: mod:parrot_tools.security.reports
  rel: mentions
---

# TASK-1480: SecurityAdvisoryEngine — day-over-day diff + SOC2 mapping

**Feature**: FEAT-226 — SecurityAdvisor (SOC2-Oriented Read-Only Advisory Agent)
**Spec**: `sdd/specs/security-advisor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The advisor's deterministic brain. Given the cross-session report catalog, this
engine fetches the two most-recent reports for a framework, diffs their findings
day-over-day, maps the delta to SOC2 controls **via the existing
`ComplianceMapper`** (NOT a new catalog), and returns a structured
`AdvisoryReport` Pydantic model that the agent's LLM later narrates.

Implements spec §3 Module 1. **No LLM, no agent, no scanners** — pure logic over
the injected store + mapper.

---

## Scope

- Create `advisory_engine.py` with the Pydantic models `FindingDelta`,
  `AdvisoryRecommendation`, `AdvisoryReport` (per spec §2 Data Models).
- Implement `SecurityAdvisoryEngine`:
  - `__init__(self, report_store, mapper=None)` — default `mapper` to a fresh
    `ComplianceMapper()` when not injected.
  - `async build_daily_advisory(*, framework, provider="aws") -> AdvisoryReport`:
    1. Query the two most-recent `ReportRef`s for the framework
       (`ReportFilter(framework=..., report_kind=ReportKind.SCAN,
       order_by="produced_at_desc", limit=2)`).
    2. Parse the current report content into `list[SecurityFinding]` via
       `get_report_parser(scanner).extract_section(content, "full")` (degrade
       gracefully — see Notes).
    3. Diff current vs. baseline into `FindingDelta`s
       (new / resolved / persisting / severity_changed), keyed by
       `SecurityFinding.id`.
    4. Compute a signed `severity_delta: SeverityBreakdown` (current − baseline).
    5. Map findings to SOC2 controls via
       `mapper.map_finding_to_controls(finding, ComplianceFramework.SOC2)` and
       coverage via `mapper.get_framework_coverage(...)`.
    6. Build `AdvisoryRecommendation`s; set `is_material=True` for new/severity-up
       CRITICAL or HIGH findings.
    7. First run (only one report) → `baseline_report_id=None`, all `new`.
- Unit tests for first-run, day-over-day delta, materiality, mapper reuse, coverage.

**NOT in scope**:
- The LLM-facing toolkit (TASK-1481) and the agent (TASK-1482).
- Any new SOC2 catalog/mapping — reuse `ComplianceMapper`.
- Writing to the store.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/security/advisory_engine.py` | CREATE | Models + `SecurityAdvisoryEngine` |
| `packages/ai-parrot-tools/tests/security/test_advisory_engine.py` | CREATE | Unit tests with an in-memory store double |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.storage.security_reports import (   # verified: .../security_reports/__init__.py:6-16
    ReportFilter, ReportKind, ReportRef, SeverityBreakdown, SecurityReportStore,
)
from parrot_tools.security.reports import ComplianceMapper  # verified: reports/__init__.py
from parrot_tools.security.models import (       # verified: parrot_tools/security/models.py
    SecurityFinding, SeverityLevel, ComplianceFramework, ComparisonDelta,
)
from parrot_tools.security.parsers import get_report_parser  # verified: parsers/__init__.py:31
```

### Existing Signatures to Use
```python
# parrot/storage/security_reports/store.py  (SecurityReportStore Protocol)
async def query(self, filter: ReportFilter) -> list[ReportRef]   # :59 / impl :279  (NO implicit since filter)
async def fetch_content(self, report_id: UUID) -> bytes          # :67 / impl :335

# parrot/storage/security_reports/models.py
class ReportFilter(BaseModel):                                   # :108
    scanner|framework|provider|report_kind|since|until|scope_match
    limit: int = Field(default=50, ge=1, le=500)                 # :127
    order_by: Literal["produced_at_desc","produced_at_asc"] = "produced_at_desc"  # :128
class SeverityBreakdown(BaseModel):                              # :35
    critical:int=0; high:int=0; medium:int=0; low:int=0; informational:int=0
class ReportRef(BaseModel):                                      # :69
    report_id: UUID; scanner: str; framework: str|None; produced_at: datetime
    severity_summary: SeverityBreakdown; uri: str                # (and more)

# parrot_tools/security/reports/compliance_mapper.py  (ComplianceMapper — REUSE)
def __init__(self, mappings_dir: str | None = None)                                   # :40
def map_finding_to_controls(self, finding: SecurityFinding, framework: ComplianceFramework) -> list[str]  # :142
def get_framework_coverage(self, findings: list[SecurityFinding], framework: ComplianceFramework) -> dict  # :187
def get_findings_by_control(self, findings, framework) -> dict[str, list[SecurityFinding]]   # :324
# NOTE: mapping keys off finding.source (SOURCE_TO_KEY) + check_id (_get_check_key):136,98 —
#       findings must have source + check_id populated for controls to resolve.

# parrot_tools/security/models.py
class SecurityFinding(BaseModel):              # :62
    id: str; source: FindingSource; severity: SeverityLevel; title: str
    resource: str|None; check_id: str|None; compliance_tags: list[str]; remediation: str|None
class SeverityLevel(str, Enum):                # :14  (includes a PASS member)
class ComparisonDelta(BaseModel):              # :153
    new_findings; resolved_findings; unchanged_findings: list[SecurityFinding]; severity_trend: dict[str,int]

# parrot_tools/security/parsers/__init__.py
def get_report_parser(scanner: str) -> ReportParser            # :31
# ReportParser.extract_section(self, content: bytes|Path, section: str) -> dict  (parsers/_types.py:65)
```

### Does NOT Exist
- ~~`soc2_controls.py` / `SOC2_CONTROL_CATALOG` / `SOC2Control` / a new `map_finding_to_controls` function~~
  — the catalog is the EXISTING `ComplianceMapper` + `mappings/soc2_controls.yaml`. Do NOT create one.
- ~~`SecurityReportStore.diff()` / `.compare()`~~ — no such method; diff here or via `ComparisonDelta`.
- ~~`ReportFilter` applies a default `since`~~ — it does NOT; pass `order_by`/`limit` explicitly (store.py:282).
- ~~`ReportRef.findings`~~ — not a field; findings come from parsing `fetch_content`, or `severity_summary`/`top_findings`.

---

## Implementation Notes

### Pattern to Follow
- Async-first; Pydantic for all models; `self.logger = logging.getLogger(__name__)`.
- Mirror the freshness/diff query approach already used in
  `agents/security.py:summary_report` (query previous report with
  `order_by="produced_at_desc"`, `until = produced_at - timedelta(microseconds=1)`).

### Key Constraints
- **Graceful degradation**: if `get_report_parser(scanner)` cannot parse content
  into findings (e.g. HTML-only report), fall back to a severity-summary delta
  computed from `ReportRef.severity_summary` and emit a single coarse
  recommendation rather than raising.
- **Determinism**: identical inputs → identical `AdvisoryReport`. Sort delta and
  recommendation lists by (severity desc, finding_id) so output is stable/testable.
- **Materiality**: `is_material=True` only for new or severity-increased findings
  at CRITICAL/HIGH. Resolved findings and LOW/INFO are not material.
- `provider` is recorded on the produced advisory (used by TASK-1482 when building
  the persisted `ReportRef`).

### References in Codebase
- `agents/security.py:751` — `summary_report` diff pattern.
- `parrot_tools/s3/report_reader.py:296` — `compare_reports` (generic diff) for reference.

---

## Acceptance Criteria

- [ ] `SecurityAdvisoryEngine.build_daily_advisory()` returns a valid `AdvisoryReport`.
- [ ] First-run (single report) → `baseline_report_id is None`, all deltas `new`, no raise.
- [ ] Two-report case classifies new/resolved/persisting/severity_changed correctly
      and produces a signed `severity_delta`.
- [ ] SOC2 control IDs on deltas/recommendations come from the injected `ComplianceMapper`
      (asserted by mapping a known finding, e.g. an S3 public-access finding → a `CC6.x` control).
- [ ] `AdvisoryReport.soc2_coverage` is populated from `get_framework_coverage`.
- [ ] Material flag is set only for new/severity-up CRITICAL/HIGH findings.
- [ ] Tests pass: `pytest packages/ai-parrot-tools/tests/security/test_advisory_engine.py -v`
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/security/advisory_engine.py`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/security/test_advisory_engine.py
import pytest
from parrot_tools.security.advisory_engine import (
    SecurityAdvisoryEngine, AdvisoryReport, FindingDelta,
)


class _FakeStore:
    """In-memory SecurityReportStore double: query/fetch_content."""
    def __init__(self, refs, contents): ...
    async def query(self, filter): ...
    async def fetch_content(self, report_id): ...


@pytest.fixture
def engine(...):
    return SecurityAdvisoryEngine(report_store=_FakeStore(...))


class TestSecurityAdvisoryEngine:
    async def test_first_run_all_new(self, engine):
        report = await engine.build_daily_advisory(framework="soc2")
        assert report.baseline_report_id is None
        assert all(d.status == "new" for d in report.deltas)

    async def test_day_over_day_delta(self, engine):
        report = await engine.build_daily_advisory(framework="soc2")
        statuses = {d.status for d in report.deltas}
        assert {"new", "resolved"} & statuses

    async def test_reuses_compliance_mapper(self, engine):
        report = await engine.build_daily_advisory(framework="soc2")
        assert any(d.soc2_control_ids for d in report.deltas)

    async def test_material_recommendation_flag(self, engine):
        report = await engine.build_daily_advisory(framework="soc2")
        assert any(r.is_material for r in report.recommendations)
```

---

## Agent Instructions

1. Read the spec (§2 Data Models, §3 Module 1, §6 Codebase Contract, §7).
2. Verify every import/signature in the contract still holds (`grep`/`read`).
3. Implement the models + engine; reuse `ComplianceMapper` (do NOT build a catalog).
4. Run pytest + ruff; ensure deterministic, sorted output.
5. Move this file to `sdd/tasks/completed/` and set the per-spec index to `done`.
6. Fill in the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-05
**Notes**: Created advisory_engine.py with FindingDelta, AdvisoryRecommendation, AdvisoryReport Pydantic models and SecurityAdvisoryEngine. Engine correctly queries 2 most-recent SCAN reports, diffs findings using id-keyed sets, maps to SOC2 controls via ComplianceMapper, signs severity deltas, and classifies materiality. Graceful degradation for unparseable content. 11/11 tests pass, ruff clean.

**Deviations from spec**: The parsers' extract_section("full") returns raw scanner dict format (not SecurityFinding objects) — SecurityFinding objects are reconstructed from raw JSON in _parse_findings(). This is correct per the existing parser architecture.
