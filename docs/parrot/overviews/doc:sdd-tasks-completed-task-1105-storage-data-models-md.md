---
type: Wiki Overview
title: 'TASK-1105: Storage data models (ReportKind, ReportRef, ReportFilter, SeverityBreakdown,
  EmbeddedFinding)'
id: doc:sdd-tasks-completed-task-1105-storage-data-models-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Foundation task for FEAT-162. Defines the Pydantic v2 data layer used by
relates_to:
- concept: mod:parrot.interfaces.file
  rel: mentions
- concept: mod:parrot.storage.security_reports
  rel: mentions
---

# TASK-1105: Storage data models (ReportKind, ReportRef, ReportFilter, SeverityBreakdown, EmbeddedFinding)

**Feature**: FEAT-162 — Cross-Session Security Report Catalog
**Spec**: `sdd/specs/security-report-catalog.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Foundation task for FEAT-162. Defines the Pydantic v2 data layer used by
every other module: the report kind enum, the canonical `ReportRef` shape
(fractal — used for raw scans AND for weekly/monthly summaries), the
query filter, and the helper models (`SeverityBreakdown`, `EmbeddedFinding`).

Implements Spec §3 Module 1.

---

## Scope

- Create `parrot/storage/security_reports/` package directory with
  `__init__.py` that re-exports the public model names.
- Create `parrot/storage/security_reports/models.py` with:
  - `class ReportKind(str, Enum)` — members: `SCAN`, `WEEKLY_SUMMARY`,
    `MONTHLY_SUMMARY`, `DRIFT_COMPARISON`.
  - `class SeverityBreakdown(BaseModel)` — int fields (default 0):
    `critical`, `high`, `medium`, `low`, `informational`. Add a
    `@property total -> int` returning the sum.
  - `class EmbeddedFinding(BaseModel)` — `finding_id`, `severity`
    (`Literal["CRITICAL","HIGH","MEDIUM","LOW","INFORMATIONAL"]`), `title`,
    and optional `resource_id`, `rule_id`, `remediation_hint`.
  - `class ReportRef(BaseModel)` — full field set per Spec §2 Data Models.
    `report_id` default = `uuid4`; `top_findings: list[EmbeddedFinding]`
    capped at 10 in usage (no model-level validator required).
    `produced_at` MUST be tz-aware UTC (use `datetime.now(timezone.utc)`
    in callers; document this in the docstring).
  - `class ReportFilter(BaseModel)` — query filter per Spec §2 Data Models.
    **No default `since`** — the store does not auto-filter by age
    (Spec §5 hard requirement).
- Create unit tests covering: model roundtrip, `SeverityBreakdown.total`,
  default values, `ReportKind` membership.

**NOT in scope**: Postgres DDL (TASK-1106), store implementation
(TASK-1107), parser logic (TASK-1108), any toolkit changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/storage/security_reports/__init__.py` | CREATE | Re-export public model names |
| `parrot/storage/security_reports/models.py` | CREATE | All Pydantic v2 models |
| `tests/storage/security_reports/__init__.py` | CREATE | Test package init |
| `tests/storage/security_reports/test_models.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from datetime import datetime, timezone
from enum import Enum
from typing import Literal
from uuid import UUID, uuid4
from pydantic import BaseModel, Field   # pydantic 2.12.5 — pyproject.toml:47
```

### Existing Signatures to Use

```python
# parrot/storage/  (existing peer modules — for layout reference only)
# parrot/storage/artifacts.py — FEAT-103 ArtifactStore (peer; do NOT import)
# parrot/security/security_events.sql — schema-layout precedent (referenced by TASK-1106)
```

### Does NOT Exist

- ~~`parrot/storage/security_reports/`~~ — clean slate; this task creates the package.
- ~~`from parrot.storage.security_reports import *`~~ — no existing exports.
- ~~Any v1 Pydantic idioms (`Config`, `.dict()`, `.json()`)~~ — project is
  pinned to Pydantic 2.12.5; use `model_dump`, `model_dump_json`,
  `model_validate`.

---

## Implementation Notes

### Pattern to Follow

```python
# parrot/storage/security_reports/models.py — sketch
from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID, uuid4
from pydantic import BaseModel, Field


class ReportKind(str, Enum):
    SCAN = "scan"
    WEEKLY_SUMMARY = "weekly_summary"
    MONTHLY_SUMMARY = "monthly_summary"
    DRIFT_COMPARISON = "drift_comparison"


class SeverityBreakdown(BaseModel):
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    informational: int = 0

    @property
    def total(self) -> int:
        return self.critical + self.high + self.medium + self.low + self.informational


class EmbeddedFinding(BaseModel):
    finding_id: str
    severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFORMATIONAL"]
    title: str
    resource_id: str | None = None
    rule_id: str | None = None
    remediation_hint: str | None = None


class ReportRef(BaseModel):
    report_id: UUID = Field(default_factory=uuid4)
    report_kind: ReportKind
    scanner: str
    framework: str | None
    provider: str
    scope: dict
    severity_summary: SeverityBreakdown
    top_findings: list[EmbeddedFinding] = Field(default_factory=list)
    uri: str
    content_type: str = "application/json"
    content_bytes: int | None = None
    produced_at: datetime   # MUST be tz-aware UTC
    produced_by: str
    parser_version: str
    retention_class: Literal["standard", "compliance", "ephemeral"] = "compliance"


class ReportFilter(BaseModel):
    scanner: str | None = None
    framework: str | None = None
    provider: str | None = None
    report_kind: ReportKind | None = None
    since: datetime | None = None
    until: datetime | None = None
    scope_match: dict | None = None
    limit: int = 50
    order_by: Literal["produced_at_desc", "produced_at_asc"] = "produced_at_desc"
```

### Key Constraints

- All async-irrelevant (pure data); no event-loop concerns here.
- Pydantic v2 only — never `dict()`, never `Config` subclass; use
  `model_config = ConfigDict(...)` if needed.
- `produced_at` is documented as tz-aware UTC. We do NOT validate at the
  model layer (validators add overhead on every load from DB); callers
  are responsible. Unit tests should pass a tz-aware value.

### References in Codebase

- `parrot/storage/artifacts.py` — peer storage module; mirror the
  `__init__.py` style (re-export public names; no logic).
- Spec §2 Data Models — verbatim source for the field shapes.

---

## Acceptance Criteria

- [ ] `parrot/storage/security_reports/__init__.py` re-exports `ReportKind`,
      `ReportRef`, `ReportFilter`, `SeverityBreakdown`, `EmbeddedFinding`.
- [ ] `from parrot.storage.security_reports import ReportKind, ReportRef, ReportFilter, SeverityBreakdown, EmbeddedFinding` resolves.
- [ ] All unit tests pass: `pytest tests/storage/security_reports/test_models.py -v`.
- [ ] No linting errors: `ruff check parrot/storage/security_reports/`.
- [ ] `SeverityBreakdown(critical=1, high=2).total == 3`.
- [ ] `ReportRef.model_validate(ref.model_dump(mode="json"))` returns an equal `ReportRef`.

---

## Test Specification

```python
# tests/storage/security_reports/test_models.py
import pytest
from datetime import datetime, timezone
from uuid import UUID
from pydantic import ValidationError

from parrot.storage.security_reports import (
    ReportKind, ReportRef, ReportFilter, SeverityBreakdown, EmbeddedFinding,
)


class TestReportKind:
    def test_members(self):
        assert ReportKind.SCAN.value == "scan"
        assert ReportKind.WEEKLY_SUMMARY.value == "weekly_summary"
        assert ReportKind.MONTHLY_SUMMARY.value == "monthly_summary"
        assert ReportKind.DRIFT_COMPARISON.value == "drift_comparison"


class TestSeverityBreakdown:
    def test_defaults_zero(self):
        s = SeverityBreakdown()
        assert s.total == 0

    def test_total_sum(self):
        s = SeverityBreakdown(critical=1, high=2, medium=3, low=4, informational=5)
        assert s.total == 15


class TestReportRef:
    def test_roundtrip(self):
        ref = ReportRef(
            report_kind=ReportKind.SCAN,
            scanner="cloudsploit",
            framework="HIPAA",
            provider="aws",
            scope={"account_id": "123456789012", "region": "us-east-1"},
            severity_summary=SeverityBreakdown(critical=2, high=5),
            uri="s3://bucket/key.json",
            produced_at=datetime.now(timezone.utc),
            produced_by="agent:test",
            parser_version="1.0.0",
        )
        clone = ReportRef.model_validate(ref.model_dump(mode="json"))
        assert clone.report_id == ref.report_id
        assert clone.severity_summary.total == 7

    def test_defaults(self):
        ref = ReportRef(
            report_kind=ReportKind.SCAN,
            scanner="trivy",
            framework=None,
            provider="n/a",
            scope={},
            severity_summary=SeverityBreakdown(),
            uri="file:///tmp/x.json",
            produced_at=datetime.now(timezone.utc),
            produced_by="test",
            parser_version="1.0.0",
        )
        assert isinstance(ref.report_id, UUID)
        assert ref.top_findings == []
        assert ref.retention_class == "compliance"
        assert ref.content_type == "application/json"


class TestReportFilter:
    def test_defaults(self):
        f = ReportFilter()
        assert f.since is None        # CRITICAL: no implicit age filter
        assert f.limit == 50
        assert f.order_by == "produced_at_desc"
```

---

## Agent Instructions

1. Read the spec sections referenced above for full context.
2. Verify the Codebase Contract — confirm Pydantic v2 is still pinned.
3. Implement models per the pattern in §Implementation Notes.
4. Run unit tests.
5. Move this file to `sdd/tasks/completed/`; update the per-spec index;
   commit.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-12
**Notes**: Implemented all 5 Pydantic v2 models (ReportKind, SeverityBreakdown,
EmbeddedFinding, ReportRef, ReportFilter) per spec §2 Data Models verbatim.
Added __init__.py re-exporting all public names. Added 20 unit tests — all pass.
Also updated the worktree conftest.py to add missing
parrot.interfaces.file.{abstract,s3,local,gcs} sub-module stubs (pre-existing
worktree infrastructure issue, not spec-related).

**Deviations from spec**: none
