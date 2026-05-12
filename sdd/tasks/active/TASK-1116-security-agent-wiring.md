# TASK-1116: agents/security.py wiring + scheduled consolidators + BACKSTORY alignment

**Feature**: FEAT-162 — Cross-Session Security Report Catalog
**Spec**: `sdd/specs/security-report-catalog.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-1104, TASK-1109, TASK-1110, TASK-1111, TASK-1112, TASK-1113, TASK-1114, TASK-1115
**Assigned-to**: unassigned

---

## Context

The final integration task. Wires every previously-shipped module into
the live `SecurityAgent`. Adds the two `@schedule`d consolidators
(weekly + monthly), iterating **(provider, framework)** pairs per the
user's multi-provider resolution. Aligns the BACKSTORY freshness block
with the real `SecurityReportToolkit` tool names.

The target file (`agents/security.py`) is **gitignored** — this task's
git diff will be effectively empty (only the task-file move). The actual
code change is local to the implementer's environment; ops applies the
same edits in deployment environments.

Implements Spec §3 Module 9 Path B.

---

## Scope

The edits below are applied to `agents/security.py` locally. They split
into four blocks: (A) `__init__` wiring, (B) `agent_tools()` injection,
(C) two `@schedule`d consolidator methods, (D) BACKSTORY alignment.

### A. `__init__` wiring

After the existing `super().__init__(...)` call, add:

```python
self._file_manager = FileManagerFactory.create(
    manager_type='s3',
    bucket_name=config.get('SECURITY_REPORT_BUCKET', fallback=config.S3_ARTIFACT_BUCKET),
    prefix=config.get('SECURITY_REPORT_S3_PREFIX', fallback='security-reports/'),
    aws_id='security',           # uses AWS_CREDENTIALS['security'] from TASK-1115
)
self._report_store = PostgresS3SecurityReportStore(
    dsn=config.get('SECURITY_REPORT_PG_DSN', fallback=config.default_dsn),
    file_manager=self._file_manager,
)
self._weekly_summarizer = WeeklySecuritySummarizer(llm_client=self.llm)
self._monthly_summarizer = MonthlySecuritySummarizer(llm_client=self.llm)
```

If `AWS_CREDENTIALS['security']` is unavailable (TASK-1115 logged a
warning), `FileManagerFactory.create(aws_id='security')` may fail.
Handle the failure gracefully by falling back to `aws_id='default'`
and logging a warning — the catalog still works, it just uses the
default bucket creds.

### B. `agent_tools()` injection

Modify the existing `agent_tools()` method:

1. Pass `file_manager=self._file_manager, report_store=self._report_store`
   to each producer toolkit constructor (CloudSploitToolkit,
   ComplianceReportToolkit, ContainerSecurityToolkit).
2. Build a `SecurityReportToolkit(report_store=self._report_store,
   file_manager=self._file_manager)` instance.
3. Place `*self._report_toolkit.get_tools()` FIRST in the returned tool
   list. This is a semantic hint: the LLM tends to consider tools in
   order, so the freshness check tools come first.

### C. Scheduled consolidators

Add two methods at module-end (after existing `@schedule`d methods):

```python
@schedule(schedule_type=ScheduleType.WEEKLY, day_of_week=0, hour=6, minute=0)
async def consolidate_weekly_security_summary(self) -> dict:
    """Monday 06:00 UTC — consolidate the last 7 days of scans per (provider, framework)."""
    from datetime import datetime, timedelta, timezone
    since = datetime.now(timezone.utc) - timedelta(days=7)
    produced: list[str] = []

    # Per the multi-provider resolution: iterate (provider, framework) pairs.
    # The provider set is derived from frameworks the agent supports —
    # confirm the exact list at task start by reading the existing
    # SecurityAgent (e.g., self.PROVIDERS, self.FRAMEWORKS, or hard-coded).
    for provider in PROVIDERS:                       # e.g. ("aws", "azure", "gcp")
        for framework in FRAMEWORKS:                 # e.g. ("HIPAA", "PCI", "SOC2")
            scans = await self._report_store.query(ReportFilter(
                report_kind=ReportKind.SCAN, provider=provider, framework=framework,
                since=since, limit=200,
            ))
            if not scans:
                continue
            # Optional: load previous weekly summary for diff
            prev_window_start = since - timedelta(days=7)
            prev_refs = await self._report_store.query(ReportFilter(
                report_kind=ReportKind.WEEKLY_SUMMARY,
                provider=provider, framework=framework,
                since=prev_window_start, until=since, limit=1,
            ))
            prev_summary_data = None
            if prev_refs:
                content = await self._report_store.fetch_content(prev_refs[0].report_id)
                prev_summary_data = WeeklySummary.model_validate_json(content)

            summary = await self._weekly_summarizer.build(
                scans=scans, framework=framework, provider=provider,
                previous_summary_data=prev_summary_data,
            )
            ref = ReportRef(
                report_kind=ReportKind.WEEKLY_SUMMARY,
                scanner="aggregator",
                framework=framework, provider=provider,
                scope={"source_report_ids": [str(s.report_id) for s in scans]},
                severity_summary=summary.severity_totals,
                top_findings=summary.persistent_findings[:10],
                uri="",
                produced_at=datetime.now(timezone.utc),
                produced_by="schedule:consolidate_weekly_security_summary",
                parser_version="1.0.0",
            )
            saved = await self._report_store.save_report(
                ref, summary.model_dump_json().encode("utf-8"),
            )
            produced.append(str(saved.report_id))
    return {"task": "weekly_summary", "produced_count": len(produced),
            "report_ids": produced}


@schedule(schedule_type=ScheduleType.MONTHLY, day=1, hour=6, minute=0)
async def consolidate_monthly_security_summary(self) -> dict:
    """1st of month 06:00 UTC — consolidate ~4 weekly summaries per (provider, framework)."""
    # Same shape as weekly, but queries report_kind=WEEKLY_SUMMARY and
    # writes report_kind=MONTHLY_SUMMARY. Use the monthly summarizer.
    ...
```

### D. BACKSTORY alignment

Replace lines ≈56-63 of `agents/security.py` (the existing freshness-policy
block) with the verbatim block from Spec §7 *BACKSTORY Freshness-Policy Block*.
Confirm there are no other dangling references to `find_security_report`,
`read_security_report`, etc. elsewhere in the BACKSTORY string.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `agents/security.py` | MODIFY (local, gitignored) | __init__ + agent_tools + 2 consolidators + BACKSTORY block |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Add (or confirm) inside agents/security.py:
from datetime import datetime, timedelta, timezone

from parrot.scheduler import schedule, ScheduleType                  # F008
from parrot.tools.file.tool import FileManagerFactory                # F003
from parrot.conf import config                                       # F014

from parrot.storage.security_reports import (                        # TASK-1105 / TASK-1107
    ReportFilter, ReportKind, ReportRef, SeverityBreakdown,
    PostgresS3SecurityReportStore,
)
from parrot_tools.security.report_toolkit import SecurityReportToolkit   # TASK-1113
from parrot_tools.security.summarizer import (                       # TASK-1114
    WeeklySecuritySummarizer, MonthlySecuritySummarizer,
    WeeklySummary, MonthlySummary,
)
```

### Existing Signatures to Use

```python
# parrot/tools/file/tool.py                F003
# parrot/scheduler/__init__.py:41-96       F008  (ScheduleType.WEEKLY, .MONTHLY)
# parrot/registry/registry.py:1130-1156    F009  (existing @register_agent on SecurityAgent)
# parrot/bots/abstract.py:922-928          F021  (self.llm)
# parrot/conf.py                           F014  (config, S3_ARTIFACT_BUCKET, default_dsn, AWS_CREDENTIALS)
```

### Does NOT Exist

- ~~`config.AWS_KEY` / `config.DEFAULT_PG_DSN`~~ — real names are
  `AWS_ACCESS_KEY` / `default_dsn`.
- ~~A `self.session_id` attribute~~ — used in some `produced_by` strings
  in the brainstorm; verify whether `AbstractBot` exposes one and
  fall back to a generated UUID if not.
- ~~A built-in framework / provider list on `SecurityAgent`~~ — confirm
  whether these are class attributes, env-driven lists, or hard-coded
  in scan methods; carry the same convention into the consolidators.

---

## Implementation Notes

### Key Constraints

- **agents/security.py is gitignored.** Edits are local-only. Document
  every block applied in the completion note (start/end line numbers
  after the edit, brief diff summary).
- **TASK-1104 must be completed first** — the broken
  `consolidate_weekly_security_summary` stub at the original L445-471
  must be gone before this task adds the new (correct) version.
- **Multi-provider iteration** is required per the spec's §8 resolution
  ("full multi-provider from day 1"). The consolidator iterates
  `(provider, framework)` pairs — confirm the canonical provider list
  at task start.
- **BACKSTORY** must match the exact block in Spec §7. No paraphrasing —
  the tool names in the block must match `find_security_report`,
  `read_security_report`, `search_findings` literally.
- **No `_persist_report` calls from the consolidator** — the
  consolidator builds its own `ReportRef` and calls `save_report`
  directly (the summarizer is not a producer toolkit; no mixin
  involvement here).

### Test Coverage (live + integration)

This task is verified through Spec §5 integration tests:

- `test_freshness_policy_avoids_rescan` — the SecurityAgent prefers
  `find_security_report` over `run_compliance_scan` when a recent ref
  exists.
- `test_explicit_fresh_triggers_scan` — explicit "fresh" prompts still
  invoke the scanner.
- `test_weekly_consolidator_end_to_end` — seed 7 days of synthetic scans
  per (provider, framework); run `consolidate_weekly_security_summary`;
  verify one `weekly_summary` per pair.
- `test_monthly_consolidator_consumes_weeklies` — same shape, monthly.

Since these tests instantiate `SecurityAgent` (the live target), they
require the local agents/security.py to have all blocks applied.

### References in Codebase

- Spec §3 Module 9 Path B, §5 Acceptance Criteria, §7 *BACKSTORY Freshness-Policy Block*.
- Findings F001, F008, F014, F019, F021, F022.

---

## Acceptance Criteria

- [ ] `agents/security.py` imports cleanly after the edits
      (`python -c "from agents.security import SecurityAgent"` succeeds).
- [ ] `SecurityAgent.__init__` constructs `_file_manager`, `_report_store`,
      `_weekly_summarizer`, `_monthly_summarizer`.
- [ ] `agent_tools()` returns a list with `SecurityReportToolkit` tools FIRST.
- [ ] Each producer toolkit is constructed with `file_manager` and
      `report_store` kwargs.
- [ ] `consolidate_weekly_security_summary` is decorated with
      `@schedule(schedule_type=ScheduleType.WEEKLY, day_of_week=0, hour=6, minute=0)`
      and iterates `(provider, framework)` pairs.
- [ ] `consolidate_monthly_security_summary` is decorated with
      `@schedule(schedule_type=ScheduleType.MONTHLY, day=1, hour=6, minute=0)`.
- [ ] BACKSTORY freshness block matches Spec §7 verbatim and references
      only tools that exist (`find_security_report`, `read_security_report`,
      `search_findings`, `list_available_frameworks`).
- [ ] Spec §5 live tests pass (freshness avoids re-scan; explicit fresh
      triggers scan; weekly/monthly consolidator end-to-end).
- [ ] Completion note documents (a) every block applied with line ranges,
      (b) the canonical provider + framework lists used by the consolidator.

---

## Test Specification

The functional tests live in `tests/integration/security/` and were
specified in TASK-1107 / TASK-1113 / TASK-1114 + the spec §4 table. This
task does not introduce its own unit tests; the integration tests carry
the verification.

If the implementer needs a faster local check, the canonical smoke is:

```bash
source .venv/bin/activate
python -c "from agents.security import SecurityAgent; SecurityAgent(...)"   # constructor smoke
pytest tests/integration/security/ -v -k "freshness or consolidator"
```

---

## Agent Instructions

1. Read the spec — §3 Module 9 Path B, §5 Acceptance Criteria, §7 BACKSTORY block.
2. Confirm TASK-1104 has been completed (broken stub removed) and
   TASK-1105..1115 are completed in `sdd/tasks/completed/`.
3. Apply blocks A, B, C, D in order.
4. Run the integration smoke tests.
5. Document the line ranges + canonical provider/framework lists in the
   completion note (since the file is gitignored).
6. Move this task file to `sdd/tasks/completed/`; update per-spec index; commit.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:
  - Block A (__init__ wiring): lines <range>
  - Block B (agent_tools): lines <range>
  - Block C (consolidators): added at lines <range>
  - Block D (BACKSTORY): lines <range> (replaced original L56-63)
  - Canonical provider list used: <e.g. ("aws", "azure", "gcp")>
  - Canonical framework list used: <e.g. ("HIPAA", "PCI", "SOC2")>
  - Integration smoke output: <paste>

**Deviations from spec**: none | describe if any
