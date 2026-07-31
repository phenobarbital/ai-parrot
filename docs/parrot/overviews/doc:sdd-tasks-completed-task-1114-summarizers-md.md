---
type: Wiki Overview
title: 'TASK-1114: WeeklySecuritySummarizer + MonthlySecuritySummarizer (multi-provider
  × framework)'
id: doc:sdd-tasks-completed-task-1114-summarizers-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Deterministic Python diff math + a single LLM call for the executive
relates_to:
- concept: mod:parrot.storage.security_reports
  rel: mentions
- concept: mod:parrot_tools.security.summarizer
  rel: mentions
---

# TASK-1114: WeeklySecuritySummarizer + MonthlySecuritySummarizer (multi-provider × framework)

**Feature**: FEAT-162 — Cross-Session Security Report Catalog
**Spec**: `sdd/specs/security-report-catalog.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1107
**Assigned-to**: unassigned

---

## Context

Deterministic Python diff math + a single LLM call for the executive
paragraph. Produces `WeeklySummary` / `MonthlySummary` Pydantic models
that the SecurityAgent's consolidator (TASK-1116) wraps in a `ReportRef`
with `report_kind=WEEKLY_SUMMARY` / `MONTHLY_SUMMARY` and writes back
through the store — fractal recursion.

Per the user's resolution of the multi-provider OQ
(*full multi-provider from day 1*), summarizers must support a
`provider` axis: `build(scans, framework, provider, previous_summary)`.
The agent's consolidator iterates `(provider, framework)` pairs.

Implements Spec §3 Module 8.

---

## Scope

- Create `parrot_tools/security/summarizer.py` with:
  - `class WeeklySummary(BaseModel)` and `class MonthlySummary(BaseModel)`
    per Spec §2 New Public Interfaces. Add `provider: str` to both.
    Fields: `framework`, `provider`, `period_start`, `period_end`,
    `severity_totals: SeverityBreakdown`, `new_findings`, `resolved_findings`,
    `persistent_findings`, `executive_paragraph`, `source_report_ids`.
  - `class WeeklySecuritySummarizer(llm_client)` with `async def build(
      scans: list[ReportRef], framework: str, provider: str,
      previous_summary: ReportRef | None = None,
    ) -> WeeklySummary`:
    1. Compute `severity_totals` as element-wise sum of
       `scan.severity_summary` across `scans` (deterministic Python).
    2. Compute finding diff sets vs `previous_summary` using **set ops on
       `finding_id`**:
       - `current_finding_ids = {f.finding_id for s in scans for f in s.top_findings}`
       - `previous_finding_ids = {f.finding_id for f in <fetched previous content>}`
         — fetch the previous summary's content via the store (caller can
         pass the previous `WeeklySummary` already deserialized to avoid
         a fetch — see optional `previous_summary_data` kwarg below).
       - `new = current - previous`, `resolved = previous - current`,
         `persistent = current & previous`.
       - For each diff bucket, gather the canonical `EmbeddedFinding`
         objects from the latest occurrence (stable sort by severity).
    3. Build the **input prompt** for the LLM call (executive paragraph
       only): a structured representation of the severity totals + a
       handful of representative findings. Use
       `ThinkingConfig(include_thoughts=False)`.
    4. Call `await self._llm.generate_structured(...)` against a tiny
       Pydantic schema `class _Executive(BaseModel): paragraph: str`
       (3–5 sentences). Verify the exact `llm_client` structured-output
       API at task start by inspecting
       `parrot/clients/google/client.py:1957-1977` (the ThinkingConfig
       precedent).
    5. Return `WeeklySummary(...)`.
  - `class MonthlySecuritySummarizer(llm_client)` with the **same shape**,
    but its input is a list of `weekly_summary` `ReportRef`s (the
    consolidator fetches their content and deserializes into `WeeklySummary`).
    Diff math operates on the weekly `persistent_findings` sets, plus
    the LLM call generates a monthly-scope paragraph.
- Unit tests:
  - **Deterministic diff** — same input scans + same previous summary
    produce identical `new`/`resolved`/`persistent` sets across runs
    (LLM is mocked, returns a constant paragraph).
  - **LLM called exactly once and only for the executive paragraph.**
  - **Severity totals are arithmetic sums** — never derived from the LLM.

**NOT in scope**: SecurityAgent wiring (TASK-1116); the consolidator
scheduled methods themselves; persistence of the resulting `WeeklySummary`
as a `ReportRef` (also TASK-1116).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot_tools/security/summarizer.py` | CREATE | WeeklySummary, MonthlySummary, summarizer classes |
| `tests/security/test_summarizer.py` | CREATE | Unit tests with mocked LLM client |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from __future__ import annotations
import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from parrot.storage.security_reports import (                  # TASK-1105
    EmbeddedFinding, ReportRef, SeverityBreakdown,
)
# LLM client type — keep generic; the SecurityAgent passes its own
# `self.llm` (AbstractBot.llm — see F021). For typing, accept `Any`
# in v1; tighten when the bot LLM type is exported.
```

### Existing Signatures to Use

```python
# parrot/bots/abstract.py:922-928 (F021)
class AbstractBot:
    llm: Any   # set to a GoogleGenAIClient after super().__init__() in Agent

# parrot/clients/google/client.py:1957-1977 (F022) — ThinkingConfig precedent.
# The exact structured-output method name varies; inspect the file at task
# start. Likely a method like:
#   async def generate_structured(self, *, prompt: str, response_schema: type[BaseModel],
#                                 thinking_config: ThinkingConfig | None = None) -> BaseModel
# If the project uses a different shape (e.g. ask_structured), adapt.
```

### Does NOT Exist

- ~~`WeeklySecuritySummarizer.from_config(...)`~~ — no factory; just a
  plain constructor that takes the llm_client.
- ~~A built-in fetch-previous-summary helper on summarizers~~ — the
  consolidator (TASK-1116) fetches and deserializes; pass the result
  in via `previous_summary_data` if available, else summarizer falls
  back to fetching via the store (optional in v1).
- ~~Any cross-framework summarization~~ — each `build` call is scoped to
  exactly one `(provider, framework)` pair.

---

## Implementation Notes

### Pattern to Follow

```python
# parrot_tools/security/summarizer.py — sketch
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from parrot.storage.security_reports import (
    EmbeddedFinding, ReportRef, SeverityBreakdown,
)


class WeeklySummary(BaseModel):
    framework: str
    provider: str
    period_start: datetime
    period_end: datetime
    severity_totals: SeverityBreakdown
    new_findings: list[EmbeddedFinding]
    resolved_findings: list[EmbeddedFinding]
    persistent_findings: list[EmbeddedFinding]
    executive_paragraph: str
    source_report_ids: list[UUID]


class MonthlySummary(BaseModel):
    framework: str
    provider: str
    period_start: datetime
    period_end: datetime
    severity_totals: SeverityBreakdown
    persistent_findings: list[EmbeddedFinding]
    executive_paragraph: str
    source_report_ids: list[UUID]   # the 4 weekly_summary refs consumed


class _Executive(BaseModel):
    paragraph: str


class WeeklySecuritySummarizer:
    def __init__(self, llm_client: Any):
        self._llm = llm_client
        self._logger = logging.getLogger(__name__)

    async def build(
        self,
        scans: list[ReportRef],
        framework: str,
        provider: str,
        previous_summary_data: WeeklySummary | None = None,
    ) -> WeeklySummary:
        period_start = min((s.produced_at for s in scans), default=datetime.utcnow())
        period_end   = max((s.produced_at for s in scans), default=datetime.utcnow())

        # 1. Deterministic severity totals
        totals = SeverityBreakdown(
            critical      = sum(s.severity_summary.critical      for s in scans),
            high          = sum(s.severity_summary.high          for s in scans),
            medium        = sum(s.severity_summary.medium        for s in scans),
            low           = sum(s.severity_summary.low           for s in scans),
            informational = sum(s.severity_summary.informational for s in scans),
        )

        # 2. Set-op diffs on finding_id
        current_findings = {f.finding_id: f for s in scans for f in s.top_findings}
        previous_findings = {
            f.finding_id: f
            for f in (previous_summary_data.persistent_findings if previous_summary_data else [])
        }
        # ... compute new / resolved / persistent ...

        # 3. LLM call — only for the executive paragraph
        exec_paragraph = (await self._call_llm_for_exec(
            framework=framework, provider=provider, totals=totals,
            new=new_findings, resolved=resolved_findings, persistent=persistent_findings,
        )).paragraph

        return WeeklySummary(
            framework=framework, provider=provider,
            period_start=period_start, period_end=period_end,
            severity_totals=totals,
            new_findings=new_findings, resolved_findings=resolved_findings,
            persistent_findings=persistent_findings,
            executive_paragraph=exec_paragraph,
            source_report_ids=[s.report_id for s in scans],
        )

    async def _call_llm_for_exec(self, **ctx) -> _Executive:
        # Compose prompt, call self._llm with response_schema=_Executive
        # and ThinkingConfig(include_thoughts=False) per F022.
        ...
```

### Key Constraints

- **All arithmetic is deterministic Python.** The LLM is invoked ONLY for
  the `executive_paragraph` field.
- **Single LLM call per build.** Unit test asserts call count.
- **Multi-provider day 1.** `provider` is a required arg; the
  consolidator iterates `(provider, framework)` pairs.
- The summarizer does NOT persist anything — it returns the
  `WeeklySummary` / `MonthlySummary` model. Persistence is the
  consolidator's job (TASK-1116).
- Use `ThinkingConfig(include_thoughts=False)` — F022 precedent.

### References in Codebase

- Finding F022 — ThinkingConfig usage at `parrot/clients/google/client.py:1957-1977`.
- Finding F021 — `AbstractBot.llm` is the live LLM attribute.
- Spec §3 Module 8.

---

## Acceptance Criteria

- [ ] `from parrot_tools.security.summarizer import WeeklySecuritySummarizer, MonthlySecuritySummarizer, WeeklySummary, MonthlySummary` resolves.
- [ ] `WeeklySummary` and `MonthlySummary` carry a `provider` field.
- [ ] `severity_totals` is the arithmetic sum of input severity summaries (no LLM input).
- [ ] Same `scans` + same `previous_summary_data` → identical diff sets across runs (LLM mocked).
- [ ] The mocked LLM client is invoked exactly once per `build(...)`, and only for the executive paragraph.
- [ ] All unit tests pass: `pytest tests/security/test_summarizer.py -v`.

---

## Test Specification

```python
# tests/security/test_summarizer.py
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from uuid import uuid4

from parrot.storage.security_reports import (
    EmbeddedFinding, ReportKind, ReportRef, SeverityBreakdown,
)
from parrot_tools.security.summarizer import (
    WeeklySecuritySummarizer, WeeklySummary, _Executive,
)


def _scan(severity_kwargs, top_findings):
    return ReportRef(
        report_kind=ReportKind.SCAN, scanner="cloudsploit", framework="HIPAA",
        provider="aws", scope={},
        severity_summary=SeverityBreakdown(**severity_kwargs),
        top_findings=top_findings,
        uri="s3://b/k.json",
        produced_at=datetime.now(timezone.utc),
        produced_by="test", parser_version="1.0.0",
    )


def _f(fid, sev="HIGH"):
    return EmbeddedFinding(finding_id=fid, severity=sev, title=fid)


class TestWeekly:
    async def test_severity_totals_are_arithmetic_sum(self):
        llm = AsyncMock()
        llm.generate_structured = AsyncMock(return_value=_Executive(paragraph="x"))
        s = WeeklySecuritySummarizer(llm_client=llm)
        scans = [
            _scan(dict(critical=1, high=2), []),
            _scan(dict(critical=3, high=4, medium=5), []),
        ]
        summary = await s.build(scans=scans, framework="HIPAA", provider="aws")
        assert summary.severity_totals.critical == 4
        assert summary.severity_totals.high == 6
        assert summary.severity_totals.medium == 5

    async def test_llm_called_once(self):
        llm = AsyncMock()
        llm.generate_structured = AsyncMock(return_value=_Executive(paragraph="x"))
        s = WeeklySecuritySummarizer(llm_client=llm)
        await s.build(scans=[_scan(dict(), [])], framework="HIPAA", provider="aws")
        assert llm.generate_structured.call_count == 1

    async def test_diff_deterministic(self):
        llm = AsyncMock()
        llm.generate_structured = AsyncMock(return_value=_Executive(paragraph="x"))
        s = WeeklySecuritySummarizer(llm_client=llm)
        scans = [_scan(dict(), [_f("F1"), _f("F2"), _f("F3")])]
        prev = WeeklySummary(
            framework="HIPAA", provider="aws",
            period_start=datetime.now(timezone.utc) - timedelta(days=14),
            period_end=datetime.now(timezone.utc) - timedelta(days=7),
            severity_totals=SeverityBreakdown(),
            new_findings=[], resolved_findings=[],
            persistent_findings=[_f("F2"), _f("F4")],
            executive_paragraph="prev", source_report_ids=[],
        )
        a = await s.build(scans=scans, framework="HIPAA", provider="aws", previous_summary_data=prev)
        b = await s.build(scans=scans, framework="HIPAA", provider="aws", previous_summary_data=prev)
        assert {f.finding_id for f in a.new_findings} == {f.finding_id for f in b.new_findings}
        assert {f.finding_id for f in a.resolved_findings} == {f.finding_id for f in b.resolved_findings}
        assert {f.finding_id for f in a.persistent_findings} == {f.finding_id for f in b.persistent_findings}
```

---

## Agent Instructions

1. Read the spec section §3 Module 8 and the multi-provider resolution in §8.
2. Verify the LLM structured-output API in `parrot/clients/google/client.py` —
   the exact method name might be `generate_structured`, `ask_structured`,
   `complete_with_schema`, etc. Match the existing pattern.
3. Implement summarizers per the sketch above.
4. Run unit tests.
5. Move this file to `sdd/tasks/completed/`; update per-spec index; commit.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-12
**Notes**: LLM API method confirmed: `ask(prompt, structured_output=_Executive, stateless=True)`.
The GoogleGenAIClient's `ask()` accepts `structured_output` as a type and returns an `AIMessage`
with `structured_output` attribute containing the parsed Pydantic model.

Implemented `WeeklySecuritySummarizer` and `MonthlySecuritySummarizer` in
`parrot_tools/security/summarizer.py` with `WeeklySummary`, `MonthlySummary`, and `_Executive`
Pydantic models. All 14 unit tests pass (14 passed in 0.26s).

Multi-provider iteration handled in the agent consolidator (TASK-1116) as designed.

**Deviations from spec**: None. The task sketch used `generate_structured`; actual API is `ask()`.
This was confirmed by reading `parrot/clients/google/client.py` as instructed in Agent Instructions.
