---
type: Wiki Overview
title: 'TASK-1482: SecurityAdvisor agent — read-only, scheduled daily SOC2 advisory'
id: doc:sdd-tasks-completed-task-1482-security-advisor-agent-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'The user-facing deliverable: a new `SecurityAdvisor` `Agent` that is **strictly'
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.registry
  rel: mentions
- concept: mod:parrot.scheduler
  rel: mentions
- concept: mod:parrot.storage.security_reports
  rel: mentions
- concept: mod:parrot_tools.jiratoolkit
  rel: mentions
- concept: mod:parrot_tools.s3.report_reader
  rel: mentions
- concept: mod:parrot_tools.security.report_toolkit
  rel: mentions
- concept: mod:parrot_tools.security.soc2_advisory
  rel: mentions
---

# TASK-1482: SecurityAdvisor agent — read-only, scheduled daily SOC2 advisory

**Feature**: FEAT-226 — SecurityAdvisor (SOC2-Oriented Read-Only Advisory Agent)
**Spec**: `sdd/specs/security-advisor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1479, TASK-1481
**Assigned-to**: unassigned

---

## Context

The user-facing deliverable: a new `SecurityAdvisor` `Agent` that is **strictly
read-only** — it reads reports the `SecurityAgent` already wrote, never launches
a scanner. It mounts the read toolkits + the new `SOC2AdvisoryToolkit` + Jira,
and runs a scheduled **daily** SOC2 advisory that persists a `ReportRef`
(`report_kind=ADVISORY`), files Jira tickets for material incidents, and emails
the security recipients. It also answers on demand.

Implements spec §3 Module 3. Mirror the structure of `agents/security.py`
(`SecurityAgent`) — same toolkit-mount + `@schedule` patterns — but with NO
scanner toolkits.

---

## Scope

- Create `agents/security_advisor.py`:
  - `@register_agent(name="security_advisor", at_startup=True)` on
    `class SecurityAdvisor(Agent)`.
  - SOC2-oriented `BACKSTORY` describing the read-only advisory role.
  - Idempotent `agent_tools()` mounting ONLY:
    `SecurityReportToolkit`, `S3ReportReaderToolkit` (`s3_`),
    `SOC2AdvisoryToolkit` (`soc2_`), `JiraToolkit`. **No scanner toolkit.**
    Build one `PostgresS3SecurityReportStore` (read use) shared across toolkits,
    as `SecurityAgent.agent_tools()` does.
  - `@schedule(DAILY)` `run_daily_soc2_advisory()`:
    1. For each framework in `["soc2"]` (default): call the engine /
       `SOC2AdvisoryToolkit.daily_soc2_advisory`.
    2. Narrate the structured `AdvisoryReport` via `self.ask(...)`.
    3. Persist the markdown as a `ReportRef(report_kind=ReportKind.ADVISORY, ...)`
       via `self._report_store.save_report(...)`.
    4. For each `is_material` recommendation, create a Jira `NAV` ticket.
    5. Email the summary via `self.send_notification(...)`.
    6. Wrap each step in try/except + logging (mirror `summary_report`).
- Unit tests: read-only invariant (no scanner tool names), registry resolution,
  and an integration test of the daily task with mocked store/Jira/notification.

**NOT in scope**:
- The engine internals (TASK-1480) and toolkit internals (TASK-1481).
- Adding new SOC2 catalog logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `agents/security_advisor.py` | CREATE | `SecurityAdvisor` agent (**`git add -f` — see Risks**) |
| `tests/test_security_advisor.py` | CREATE | Read-only invariant + registry + daily-task integration |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots import Agent                                   # verified: agents/security.py:7
from parrot.registry import register_agent                      # verified: agents/security.py:9
from parrot.scheduler import ScheduleType, schedule             # verified: agents/security.py:10
from parrot.storage.security_reports import (                   # verified: __init__.py:6-16
    PostgresS3SecurityReportStore, ReportRef, ReportKind, SeverityBreakdown,
)
from parrot.conf import AWS_CREDENTIALS, default_dsn            # verified: agents/security.py:8
from navigator.utils.file.s3 import S3FileManager               # verified: agents/security.py:6
from navconfig import config                                    # verified: agents/security.py:5
from parrot_tools.security.report_toolkit import SecurityReportToolkit   # verified: report_toolkit.py:27
from parrot_tools.s3.report_reader import S3ReportReaderToolkit          # verified: report_reader.py:33
from parrot_tools.security.soc2_advisory import SOC2AdvisoryToolkit      # from TASK-1481
from parrot_tools.jiratoolkit import JiraToolkit                # verified: agents/security.py:24
```

### Existing Signatures to Use
```python
# agents/security.py — the agent to mirror (read it before writing)
@register_agent(name="security_agent", at_startup=True)        # :124
class SecurityAgent(Agent):                                    # :125
    model: str = "gemini-3-flash-preview"                      # :129 (pick a model; gemini-3-flash-preview is fine)
    def agent_tools(self):                                     # :168  idempotent; build store + toolkits, return list
        s3file = S3FileManager(aws_id="security_bucket", bucket_name=config.get("AWS_SECURITY_BUCKET_NAME"))  # :189
        self._report_store = PostgresS3SecurityReportStore(dsn=default_dsn, file_manager=s3file)              # :197
        # JiraToolkit(server_url=..., auth_type="basic_auth", username=..., password=jira_api_token, default_project=...)  # :299
    @schedule(schedule_type=ScheduleType.DAILY, hour=6, minute=0)
    async def summary_report(self):                            # :751  ask → markdown_report → save_report → Jira diff
        ref = ReportRef(report_kind=ReportKind.DAILY_SUMMARY, scanner="security_agent", framework=None,
                        provider="aws", scope=scope, severity_summary=SeverityBreakdown(), uri="",
                        content_type="text/markdown", content_bytes=len(content),
                        produced_at=datetime.now(timezone.utc), produced_by="agent:...", parser_version="1.0.0")  # :779
        ref = await self._report_store.save_report(ref, content)   # :793
    # send_notification(message=..., recipients=..., provider="email", subject=...)  # :555

# parrot/bots/agent.py
async def markdown_report(self, content, filename=None, filename_prefix='report',
        directory=None, subdir='documents', **kwargs) -> str   # :444  (returns a Path)

# SOC2AdvisoryToolkit (TASK-1481): tool_prefix="soc2";
#   async daily_soc2_advisory(framework="soc2", provider="aws") -> dict
```

### Does NOT Exist
- ~~Any scanner toolkit on this agent~~ — `SecurityAdvisor` must NOT import or mount
  `CloudSploitToolkit`, `ComplianceReportToolkit`, `ContainerSecurityToolkit`, or AWS scanner toolkits.
- ~~`Agent._build_weekly_summary`~~ — referenced in `agents/security.py:723` but NOT a base `Agent`
  method; do NOT call it here.
- ~~`ReportKind.ADVISORY` before TASK-1479 lands~~ — depends on TASK-1479.
- ~~A new SOC2 catalog~~ — SOC2 mapping comes through `SOC2AdvisoryToolkit` → `ComplianceMapper`.

---

## Implementation Notes

### Pattern to Follow
- Copy the skeleton of `agents/security.py` `agent_tools()` (idempotent guard on a
  sentinel toolkit attribute → return cached tools) but mount only reader toolkits + Jira.
- Build `_report_store` once and pass it to `SecurityReportToolkit(report_store=...,
  file_manager=...)`, `S3ReportReaderToolkit(file_manager=..., report_store=...)`, and
  `SOC2AdvisoryToolkit(report_store=...)`.
- For the daily task, mirror `summary_report`: build markdown, `save_report` an
  `ADVISORY` `ReportRef` with tz-aware UTC `produced_at`, then Jira + email.

### Key Constraints
- `produced_at=datetime.now(timezone.utc)` (model does not validate tz — models.py:99-100).
- `content_type="text/markdown"`, `parser_version="1.0.0"`, `provider` from the advisory.
- Materiality gates Jira: only `recommendation.is_material` → `jira_create_issue` (issuetype `Task`, project `NAV`).
- Default frameworks list `["soc2"]`; keep it a small constant for now (open question in spec §8 — non-blocking).
- Pick a concrete `@schedule` hour AFTER scans finish — proposed default 09:30 UTC (spec §8).

### References in Codebase
- `agents/security.py:751` (`summary_report`) and `:706` (`consolidate_weekly_security_summary`) — persistence patterns.
- `feedback_jira_toolkit_basic_auth` (memory) — Jira uses `basic_auth` with JIRA_INSTANCE/USERNAME/API_TOKEN/PROJECT.

---

## Acceptance Criteria

- [ ] `SecurityAdvisor.agent_tools()` mounts **zero** scanner toolkits — asserted by
      `test_advisor_tools_are_read_only` (no tool name contains cloudsploit/prowler/trivy/checkov/scan-launch).
- [ ] `security_advisor` is resolvable via the registry.
- [ ] `run_daily_soc2_advisory` persists exactly one `ReportRef` with
      `report_kind == ReportKind.ADVISORY` per framework with findings (mocked store).
- [ ] Material recommendations create a Jira `NAV` ticket; non-material ones do not (mocked Jira).
- [ ] The daily task calls `send_notification` to the security recipients (mocked).
- [ ] The agent file is committed with `git add -f` (it lives under the gitignored `agents/`).
- [ ] Tests pass: `pytest tests/test_security_advisor.py -v`
- [ ] `ruff check agents/security_advisor.py`

---

## Test Specification

```python
# tests/test_security_advisor.py
import pytest

SCANNER_HINTS = ("cloudsploit", "prowler", "trivy", "checkov", "run_scan", "run_compliance_scan")


def test_advisor_registered():
    from parrot.registry import ...  # resolve "security_advisor"
    ...


def test_advisor_tools_are_read_only(advisor):
    names = [t.name.lower() for t in advisor.agent_tools()]
    assert not any(h in n for n in names for h in SCANNER_HINTS)


async def test_daily_advisory_end_to_end(advisor, fake_store, mock_jira, mock_notify):
    result = await advisor.run_daily_soc2_advisory()
    saved = fake_store.saved_refs()
    assert any(r.report_kind.value == "advisory" for r in saved)
    assert mock_notify.called
```

---

## Agent Instructions

1. Read the spec (§3 Module 3, §6 Codebase Contract, §7 Risks) AND `agents/security.py`.
2. Confirm TASK-1479 (enum) and TASK-1481 (toolkit) are in `sdd/tasks/completed/`.
3. Implement the agent mirroring `SecurityAgent` minus scanners; keep it read-only.
4. **`git add -f agents/security_advisor.py`** — the `agents/` dir is gitignored.
5. Run pytest + ruff.
6. Move this file to `sdd/tasks/completed/` and set the per-spec index to `done`.
7. Fill in the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-05
**Notes**: Created agents/security_advisor.py with SecurityAdvisor(@register_agent("security_advisor"), Agent subclass). agent_tools() mounts SecurityReportToolkit, S3ReportReaderToolkit, SOC2AdvisoryToolkit, JiraToolkit — no scanner toolkits. run_daily_soc2_advisory() scheduled DAILY at 12:00 UTC: builds advisory via soc2_toolkit.daily_soc2_advisory, narrates via self.ask, persists ReportRef(report_kind=ADVISORY), creates Jira tickets for material recommendations, emails recipients. Created tests/test_security_advisor.py with 5 tests (registered, read_only, persists_advisory_ref, material_jira, sends_email). Key fix: importlib.util.spec_from_file_location bypasses agents/ namespace resolution. agents/__init__.py copied manually to worktree. agents/security_advisor.py force-added with git add -f. All 5 tests pass, ruff clean.

**Deviations from spec**: agents/ is gitignored; used git add -f per spec note.
