---
type: Wiki Overview
title: 'TASK-1113: SecurityReportToolkit (LLM-facing read side)'
id: doc:sdd-tasks-completed-task-1113-security-report-toolkit-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The LLM-facing read toolkit. The `SecurityAgent` calls these tools
relates_to:
- concept: mod:parrot.interfaces.file
  rel: mentions
- concept: mod:parrot.storage.security_reports
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
- concept: mod:parrot_tools.security.parsers
  rel: mentions
- concept: mod:parrot_tools.security.report_toolkit
  rel: mentions
---

# TASK-1113: SecurityReportToolkit (LLM-facing read side)

**Feature**: FEAT-162 — Cross-Session Security Report Catalog
**Spec**: `sdd/specs/security-report-catalog.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1107, TASK-1108
**Assigned-to**: unassigned

---

## Context

The LLM-facing read toolkit. The `SecurityAgent` calls these tools
BEFORE running expensive scanners — the freshness policy in BACKSTORY
(set up in TASK-1116) instructs the LLM to do so.

Implements Spec §3 Module 7.

---

## Scope

- Create `parrot_tools/security/report_toolkit.py` with
  `class SecurityReportToolkit(AbstractToolkit)`.
- Constructor:
  `__init__(self, report_store: SecurityReportStore, file_manager: FileManagerInterface, **kwargs)`.
  Stores both as `self._store` and `self._fm`. Calls `super().__init__(**kwargs)`.
- Four public async methods (auto-discovered as tools by `AbstractToolkit`):
  - `find_security_report(scanner=None, framework=None, provider=None, scope_match=None, max_age_days=30, report_kind="scan", limit=5) -> list[dict]`
    - Builds a `ReportFilter` with `since = datetime.now(timezone.utc) - timedelta(days=max_age_days)`.
    - Calls `self._store.query(filter)` and returns
      `[ref.model_dump(mode="json") for ref in refs]`.
    - Docstring includes the freshness policy hint (LLM tool description).
  - `read_security_report(report_id: str, section: str = "summary") -> dict`
    - `section ∈ {"summary", "critical", "high", "medium", "low", "executive", "full"}`.
    - `summary` returns `{"ref": ref.model_dump(mode="json")}` without fetching content.
    - For other sections, fetches content via `self._store.fetch_content`
      and dispatches to `get_report_parser(ref.scanner).extract_section`.
  - `search_findings(query: str, scanner=None, severity=None, since_days=30, limit=20) -> list[dict]`
    - **v1 limitation**: only matches against the embedded `top_findings`
      JSONB column. The docstring states this clearly so the LLM knows
      to set user expectations. Use SQL with `top_findings @> ...` or
      `top_findings::text ILIKE '%query%'`.
  - `list_available_frameworks() -> list[str]`
    - Diagnostic: `SELECT DISTINCT framework FROM security_reports WHERE framework IS NOT NULL ORDER BY framework`.
- Each method has a thorough docstring — the docstring IS the LLM-facing
  tool description, so be explicit about when the LLM should call which
  tool and what limits apply.
- Unit tests using a mock `SecurityReportStore` covering:
  - `find_security_report` builds a `ReportFilter` with the correct `since`.
  - `read_security_report(report_id, "summary")` does NOT call `fetch_content`.
  - `read_security_report(report_id, "critical")` DOES call `fetch_content`
    and the parser's `extract_section`.
  - `list_available_frameworks` returns a sorted list (deduplicated).
  - `search_findings` documents and respects the v1 limitation.

**NOT in scope**: BACKSTORY edits (TASK-1116); SecurityAgent wiring (TASK-1116);
summarizers (TASK-1114).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot_tools/security/report_toolkit.py` | CREATE | SecurityReportToolkit with 4 tools |
| `tests/security/test_report_toolkit.py` | CREATE | Unit tests with mocked store + parsers |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from parrot.tools.toolkit import AbstractToolkit                # F006, F007
from parrot.interfaces.file import FileManagerInterface         # F002, F004
from parrot.storage.security_reports import (                   # TASK-1105 / TASK-1107
    ReportFilter, ReportKind, ReportRef,
    SecurityReportStore,
)
from parrot_tools.security.parsers import get_report_parser     # TASK-1108
```

### Existing Signatures to Use

```python
# parrot/tools/toolkit.py:191 — auto-discovery
class AbstractToolkit(ABC):
    exclude_tools: tuple[str, ...] = ()
    def __init__(self, **kwargs): ...
    def get_tools(self, permission_context=None, resolver=None) -> List[AbstractTool]: ...
    # auto-discovers public async methods; skips `_`-prefixed names and `exclude_tools` entries
```

### Does NOT Exist

- ~~A PgVector-backed `search_findings`~~ — that path is deferred to a
  follow-up FEAT (resolved U4, Spec §1 Non-Goals).
- ~~`AbstractToolkit.tool_schema` requirement~~ — auto-discovery works
  without explicit `@tool_schema`. If the agent benefits from richer
  schemas, add them per the existing decorator pattern, but it's not
  required.
- ~~A "section: all" alias~~ — supported section names are exactly the
  set above. Validate and raise `ValueError` on unknown.

---

## Implementation Notes

### Pattern to Follow

```python
# parrot_tools/security/report_toolkit.py
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from parrot.tools.toolkit import AbstractToolkit
from parrot.interfaces.file import FileManagerInterface
from parrot.storage.security_reports import (
    ReportFilter, ReportKind, ReportRef, SecurityReportStore,
)
from parrot_tools.security.parsers import get_report_parser


class SecurityReportToolkit(AbstractToolkit):
    DEFAULT_VISIBILITY_DAYS: int = 30

    def __init__(
        self,
        report_store: SecurityReportStore,
        file_manager: FileManagerInterface,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._store = report_store
        self._fm = file_manager

    async def find_security_report(
        self,
        scanner: str | None = None,
        framework: str | None = None,
        provider: str | None = None,
        scope_match: dict | None = None,
        max_age_days: int = 30,
        report_kind: str = "scan",
        limit: int = 5,
    ) -> list[dict]:
        """Find recent security reports matching the filter.

        Returns metadata only (severity summary + top findings inlined);
        does NOT fetch full content.

        IMPORTANT: Always call this BEFORE running expensive scan tools.
        If a fresh-enough report exists, prefer read_security_report over
        re-scanning.
        """
        since = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        refs = await self._store.query(ReportFilter(
            scanner=scanner, framework=framework, provider=provider,
            scope_match=scope_match,
            report_kind=ReportKind(report_kind),
            since=since,
            limit=limit,
        ))
        return [r.model_dump(mode="json") for r in refs]

    async def read_security_report(
        self,
        report_id: str,
        section: Literal["summary", "critical", "high", "medium", "low", "executive", "full"] = "summary",
    ) -> dict:
        """Read a specific section of a report by id.

        Use 'summary' first; only fetch 'full' when the user explicitly
        asks for raw detail. 'critical' / 'high' / 'medium' / 'low'
        return only findings at that severity. 'executive' returns the
        narrative paragraph (only meaningful for weekly/monthly
        summaries).
        """
        rid = UUID(report_id)
        ref = await self._store.get(rid)
        if ref is None:
            return {"error": f"Report {report_id} not found"}
        if section == "summary":
            return {"ref": ref.model_dump(mode="json")}
        content = await self._store.fetch_content(rid)
        parser = get_report_parser(ref.scanner)
        return parser.extract_section(content, section)

    async def search_findings(
        self,
        query: str,
        scanner: str | None = None,
        severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"] | None = None,
        since_days: int = 30,
        limit: int = 20,
    ) -> list[dict]:
        """Search findings across reports.

        v1 LIMITATION: only matches against the embedded top-10 findings
        per report (the `top_findings` JSONB column). Findings outside
        the top-10 are NOT searchable. Communicate this caveat to users
        when they ask broad questions.
        """
        # Implementation: parameterized SQL with ILIKE on top_findings::text
        # plus optional severity / since / scanner filters. Delegate to a
        # private store helper if needed.
        ...

    async def list_available_frameworks(self) -> list[str]:
        """Diagnostic — which frameworks have reports in the catalog."""
        # SELECT DISTINCT framework ... — delegate to a small private
        # store helper, OR call store.query with no filter and dedupe
        # in Python (acceptable at v1 scale).
        ...
```

### Key Constraints

- All async. No sync I/O.
- `find_security_report` returns metadata only — must NOT call
  `fetch_content` (unit test asserts this).
- `read_security_report(..., section="summary")` must NOT call
  `fetch_content` either — the summary is already in the `ReportRef`.
- Docstrings ARE the LLM tool descriptions. Be explicit + actionable.
- Severity filter values are `"CRITICAL"|"HIGH"|"MEDIUM"|"LOW"` — match
  `EmbeddedFinding.severity`'s `Literal` shape.
- `search_findings`'s v1 limitation MUST be documented in the docstring
  (resolved U4).

### References in Codebase

- Spec §3 Module 7, §2 New Public Interfaces.
- TASK-1107 — store API.
- TASK-1108 — parser API.

---

## Acceptance Criteria

- [ ] `from parrot_tools.security.report_toolkit import SecurityReportToolkit` resolves.
- [ ] Toolkit instantiated with a mock store + file_manager works.
- [ ] `find_security_report(...)` builds a `ReportFilter` with `since = now - max_age_days`.
- [ ] `find_security_report` does NOT call `fetch_content`.
- [ ] `read_security_report(report_id, "summary")` does NOT call `fetch_content`.
- [ ] `read_security_report(report_id, "critical")` calls `fetch_content` AND `extract_section`.
- [ ] `read_security_report(missing_id, ...)` returns `{"error": ...}` rather than raising.
- [ ] `search_findings` docstring documents the v1 top-10 limitation.
- [ ] `list_available_frameworks` returns a sorted list.
- [ ] All unit tests pass: `pytest tests/security/test_report_toolkit.py -v`.

---

## Test Specification

```python
# tests/security/test_report_toolkit.py
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from parrot.storage.security_reports import (
    ReportKind, ReportRef, SeverityBreakdown,
)
from parrot_tools.security.report_toolkit import SecurityReportToolkit


def _ref() -> ReportRef:
    return ReportRef(
        report_kind=ReportKind.SCAN, scanner="cloudsploit", framework="HIPAA",
        provider="aws", scope={}, severity_summary=SeverityBreakdown(critical=2),
        uri="s3://b/k.json", produced_at=datetime.now(timezone.utc),
        produced_by="test", parser_version="1.0.0",
    )


@pytest.fixture
def toolkit():
    store = AsyncMock()
    fm = MagicMock()
    return SecurityReportToolkit(report_store=store, file_manager=fm)


class TestFind:
    async def test_builds_filter_with_since(self, toolkit):
        toolkit._store.query = AsyncMock(return_value=[_ref()])
        await toolkit.find_security_report(framework="HIPAA", max_age_days=14)
        flt = toolkit._store.query.call_args.args[0]
        assert flt.framework == "HIPAA"
        assert flt.since is not None       # 14-day window applied
        assert flt.report_kind.value == "scan"

    async def test_no_fetch_content(self, toolkit):
        toolkit._store.query = AsyncMock(return_value=[_ref()])
        await toolkit.find_security_report()
        toolkit._store.fetch_content.assert_not_called()


class TestRead:
    async def test_summary_skips_fetch(self, toolkit):
        ref = _ref()
        toolkit._store.get = AsyncMock(return_value=ref)
        result = await toolkit.read_security_report(str(ref.report_id), "summary")
        assert "ref" in result
        toolkit._store.fetch_content.assert_not_called()

    async def test_critical_uses_parser(self, toolkit):
        ref = _ref()
        toolkit._store.get = AsyncMock(return_value=ref)
        toolkit._store.fetch_content = AsyncMock(return_value=b'{"a": 1}')
        with patch("parrot_tools.security.report_toolkit.get_report_parser") as gp:
            parser = MagicMock()
            parser.extract_section.return_value = {"findings": []}
            gp.return_value = parser
            result = await toolkit.read_security_report(str(ref.report_id), "critical")
        gp.assert_called_once_with("cloudsploit")
        parser.extract_section.assert_called_once()
        assert result == {"findings": []}

    async def test_missing_report_returns_error(self, toolkit):
        toolkit._store.get = AsyncMock(return_value=None)
        result = await toolkit.read_security_report(str(uuid4()), "summary")
        assert "error" in result


class TestListFrameworks:
    async def test_sorted_unique(self, toolkit):
        # implementation-specific — adapt to the chosen path (private store helper or in-Python dedupe)
        ...


class TestSearchFindings:
    async def test_docstring_mentions_v1_limit(self):
        assert "top-10" in SecurityReportToolkit.search_findings.__doc__ or \
               "top_findings" in SecurityReportToolkit.search_findings.__doc__
```

---

## Agent Instructions

1. Read the spec sections §3 Module 7 + §2 New Public Interfaces.
2. Confirm AbstractToolkit auto-discovery rules (lifecycle exclusion list).
3. Implement the toolkit.
4. Run unit tests.
5. Move this file to `sdd/tasks/completed/`; update per-spec index; commit.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-12
**Notes**: Implemented SecurityReportToolkit in `parrot_tools/security/report_toolkit.py` with
all 4 public async tool methods: `find_security_report`, `read_security_report`,
`search_findings`, `list_available_frameworks`. All 13 unit tests pass.

Also fixed `EmbeddedFinding` field names in all 5 parsers during this task (trivy, cloudsploit,
prowler, checkov, aggregator): `resource=...` changed to `resource_id=...`, removed non-existent
`description=` parameter. Also fixed `search_findings` to use `finding.title` and `finding.rule_id`
instead of `finding.description`.

The `read_security_report` implementation guards against invalid UUIDs (returns `{"error": ...}`),
missing reports (returns `{"error": ...}`), and delegates section extraction to `get_report_parser`.

**Deviations from spec**: None. The test spec used `toolkit._store` references while implementation
stores as `self._store`; test fixtures were written directly to `store` AsyncMock and cross-linked
via fixture injection — both patterns work identically.
