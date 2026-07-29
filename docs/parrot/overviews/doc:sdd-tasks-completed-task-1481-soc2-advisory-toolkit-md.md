---
type: Wiki Overview
title: 'TASK-1481: SOC2AdvisoryToolkit — LLM-facing read-only advisory tools'
id: doc:sdd-tasks-completed-task-1481-soc2-advisory-toolkit-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Wrap the `SecurityAdvisoryEngine` and the existing `ComplianceMapper` as
relates_to:
- concept: mod:parrot.storage.security_reports
  rel: mentions
- concept: mod:parrot_tools.security.advisory_engine
  rel: mentions
- concept: mod:parrot_tools.security.models
  rel: mentions
- concept: mod:parrot_tools.security.reports
  rel: mentions
- concept: mod:parrot_tools.security.soc2_advisory
  rel: mentions
---

# TASK-1481: SOC2AdvisoryToolkit — LLM-facing read-only advisory tools

**Feature**: FEAT-226 — SecurityAdvisor (SOC2-Oriented Read-Only Advisory Agent)
**Spec**: `sdd/specs/security-advisor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1480
**Assigned-to**: unassigned

---

## Context

Wrap the `SecurityAdvisoryEngine` and the existing `ComplianceMapper` as
LLM-callable agent tools so the `SecurityAdvisor` agent can map reports to SOC2
controls, run a gap analysis, and produce a daily advisory on demand. The
toolkit returns **structured dicts** — the agent's LLM generates narrative.

Implements spec §3 Module 2. Read-only; the store is required.

---

## Scope

- Create `soc2_advisory.py` with `SOC2AdvisoryToolkit(AbstractToolkit)`,
  `tool_prefix = "soc2"`.
- `__init__(self, report_store, mapper=None, **kwargs)` — build a
  `SecurityAdvisoryEngine(report_store, mapper)` internally; default
  `mapper=ComplianceMapper()`.
- Tools (public async methods → auto-discovered):
  - `map_report_to_soc2(report_id: str) -> dict` — fetch + parse a stored
    report's findings and return `{control_id: [finding summaries]}` via
    `ComplianceMapper.get_findings_by_control` + coverage.
  - `soc2_gap_analysis(framework: str = "soc2") -> dict` — coverage +
    unmapped findings from the latest report
    (`get_framework_coverage` / `get_unmapped_findings`).
  - `daily_soc2_advisory(framework: str = "soc2", provider: str = "aws") -> dict`
    — delegate to `engine.build_daily_advisory(...)` and return
    `AdvisoryReport.model_dump(mode="json")`.
- On missing report / empty catalog, return a structured
  `{"error": "...", "hint": "..."}` dict (never raise).
- Unit tests for each tool, including the error path.

**NOT in scope**:
- The agent (TASK-1482) and persistence/Jira/email (TASK-1482).
- Modifying `SecurityReportToolkit` / `S3ReportReaderToolkit`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/security/soc2_advisory.py` | CREATE | `SOC2AdvisoryToolkit` |
| `packages/ai-parrot-tools/tests/security/test_soc2_advisory.py` | CREATE | Unit tests with store double |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from ..toolkit import AbstractToolkit            # verified pattern: report_reader.py:29 / report_toolkit.py:16
from parrot.storage.security_reports import SecurityReportStore  # verified: __init__.py:13-16
from parrot_tools.security.reports import ComplianceMapper       # verified: reports/__init__.py
from parrot_tools.security.models import ComplianceFramework     # verified: models.py:37
from parrot_tools.security.advisory_engine import SecurityAdvisoryEngine  # from TASK-1480
```

### Existing Signatures to Use
```python
# AbstractToolkit subclass pattern with prefix (verified: parrot_tools/s3/report_reader.py:33-85)
class S3ReportReaderToolkit(AbstractToolkit):
    tool_prefix: str = "s3"                       # :59  → tools get an "s3_" prefix
    def __init__(self, file_manager, report_store=None, *, ..., **kwargs):
        super().__init__(**kwargs)                # :80
# Public async methods on a toolkit are auto-discovered as agent tools
# (e.g. report_reader.py:296 compare_reports, :326 summarize_report).

# ComplianceMapper (REUSE) — see TASK-1480 contract for full signatures:
#   map_finding_to_controls / get_framework_coverage / get_findings_by_control /
#   get_unmapped_findings (compliance_mapper.py:142/187/324/354)

# SecurityAdvisoryEngine (TASK-1480):
#   async build_daily_advisory(*, framework, provider="aws") -> AdvisoryReport
```

### Does NOT Exist
- ~~`soc2_controls.py` / a new SOC2 catalog~~ — reuse `ComplianceMapper`.
- ~~`AbstractToolkit.register_tool()` decorator requirement~~ — public async
  methods are auto-discovered; follow the existing toolkit pattern, don't invent APIs.
- ~~`SOC2AdvisoryToolkit` writing to the store~~ — read-only; no `save_report` here.

---

## Implementation Notes

### Pattern to Follow
```python
class SOC2AdvisoryToolkit(AbstractToolkit):
    tool_prefix: str = "soc2"

    def __init__(self, report_store: SecurityReportStore,
                 mapper: ComplianceMapper | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._store = report_store
        self._mapper = mapper or ComplianceMapper()
        self._engine = SecurityAdvisoryEngine(report_store, self._mapper)
        self.logger = logging.getLogger(__name__)

    async def daily_soc2_advisory(self, framework: str = "soc2",
                                  provider: str = "aws") -> dict:
        """Produce today-vs-yesterday SOC2 advisory for a framework."""
        report = await self._engine.build_daily_advisory(
            framework=framework, provider=provider)
        return report.model_dump(mode="json")
```

### Key Constraints
- Every tool has a clear Google-style docstring (it becomes the LLM tool description).
- Catch fetch/parse errors → return `{"error": ..., "hint": ...}`; never raise to the LLM.
- Async throughout; `self.logger` for diagnostics.

### References in Codebase
- `parrot_tools/s3/report_reader.py` — dual-mode toolkit + structured-error pattern.
- `parrot_tools/security/report_toolkit.py` — catalog-backed toolkit pattern.

---

## Acceptance Criteria

- [ ] `SOC2AdvisoryToolkit` subclasses `AbstractToolkit`, `tool_prefix == "soc2"`.
- [ ] `get_tools()` returns the three tools with the `soc2_` prefix.
- [ ] `daily_soc2_advisory` returns a JSON-serializable advisory dict (engine output).
- [ ] `map_report_to_soc2` returns control→findings mapping via `ComplianceMapper`.
- [ ] Missing report / empty catalog → structured `{"error": ...}` (no exception).
- [ ] Tests pass: `pytest packages/ai-parrot-tools/tests/security/test_soc2_advisory.py -v`
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/security/soc2_advisory.py`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/security/test_soc2_advisory.py
import pytest
from parrot_tools.security.soc2_advisory import SOC2AdvisoryToolkit


@pytest.fixture
def toolkit(fake_store):
    return SOC2AdvisoryToolkit(report_store=fake_store)


class TestSOC2AdvisoryToolkit:
    def test_prefix_and_tools(self, toolkit):
        assert toolkit.tool_prefix == "soc2"
        names = [t.name for t in toolkit.get_tools()]
        assert any(n.startswith("soc2_") for n in names)

    async def test_daily_advisory(self, toolkit):
        out = await toolkit.daily_soc2_advisory(framework="soc2")
        assert "recommendations" in out

    async def test_missing_report_is_structured_error(self, toolkit):
        out = await toolkit.map_report_to_soc2("00000000-0000-0000-0000-000000000000")
        assert "error" in out
```

---

## Agent Instructions

1. Read the spec (§3 Module 2, §6 Codebase Contract) and TASK-1480's output.
2. Confirm `SecurityAdvisoryEngine` (TASK-1480) is in `sdd/tasks/completed/`.
3. Verify the `AbstractToolkit` prefix pattern by reading `report_reader.py`.
4. Implement; run pytest + ruff.
5. Move this file to `sdd/tasks/completed/` and set the per-spec index to `done`.
6. Fill in the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-05
**Notes**: Created soc2_advisory.py with SOC2AdvisoryToolkit(AbstractToolkit, tool_prefix="soc2"). Three tools: map_report_to_soc2, soc2_gap_analysis, daily_soc2_advisory. All return structured dicts, never raise. store.get() exists at store.py:63. 12/12 tests pass, ruff clean.

**Deviations from spec**: none
