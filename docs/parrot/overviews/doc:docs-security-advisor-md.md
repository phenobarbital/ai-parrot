---
type: Wiki Overview
title: SecurityAdvisor — SOC2-Oriented Read-Only Advisory Agent
id: doc:docs-security-advisor-md
tags:
- overview
timestamp: '2026-07-14T22:20:21+00:00'
summary: already collected by `SecurityAgent` into actionable, audit-ready intelligence.
relates_to:
- concept: mod:parrot_tools.security
  rel: mentions
- concept: mod:parrot_tools.security.reports
  rel: mentions
---

# SecurityAdvisor — SOC2-Oriented Read-Only Advisory Agent

## Overview

`SecurityAdvisor` is a **read-only** agent that turns the security scan data
already collected by `SecurityAgent` into actionable, audit-ready intelligence.
It never launches a scanner. It reads the report catalog, computes day-over-day
drift, maps findings to SOC2 Trust Service Criteria, and distributes the advisory.

## Architecture

```
SecurityAgent (writes scans)
       ↓  catalog (PostgresS3SecurityReportStore)
SecurityAdvisor (reads only)
       ↓  SOC2AdvisoryToolkit → SecurityAdvisoryEngine → ComplianceMapper
       ↓  daily ADVISORY ReportRef  +  Jira tickets  +  email
```

### Strict Read-Only Invariant

`SecurityAdvisor` mounts only reader toolkits:

| Toolkit | Role |
|---------|------|
| `SecurityReportToolkit` | Query and fetch report refs |
| `S3ReportReaderToolkit` | Download raw report content from S3 |
| `SOC2AdvisoryToolkit` | Map findings to SOC2 controls, build daily advisory |
| `JiraToolkit` | Create `NAV` tickets for material recommendations |

No scanner toolkit (`CloudPostureToolkit`, `ContainerSecurityToolkit`,
`SecretsIaCToolkit`) is ever mounted. The scheduler cannot trigger a scan.

## SOC2 Mapping via ComplianceMapper

SOC2 control mapping is handled by the **existing** `ComplianceMapper`
(`parrot_tools.security.reports`), which reads `soc2_controls.yaml`.
There is no new SOC2 catalog in this feature.

`SecurityAdvisoryEngine.build_daily_advisory()` calls:

1. `ComplianceMapper.map_finding_to_controls(finding)` — per-finding control IDs.
2. `ComplianceMapper.get_framework_coverage(framework, findings)` — coverage stats.
3. `ComplianceMapper.get_findings_by_control(findings)` — control → [findings] mapping.

## Daily Advisory Pipeline

Runs every day at **12:00 UTC** (after the SecurityAgent's last scan at 23:29 UTC
the previous day):

```
1. SOC2AdvisoryToolkit.daily_soc2_advisory(framework="soc2")
       → SecurityAdvisoryEngine.build_daily_advisory(framework, provider)
       → fetch latest 2 SCAN reports
       → compute FindingDelta list (new/resolved/persisting/severity_changed)
       → map via ComplianceMapper → AdvisoryReport
2. self.ask(narration_prompt)          # LLM generates markdown advisory
3. store.save_report(ADVISORY ReportRef, content)
4. for material rec in recommendations:
       jira_create_issue(project="NAV", ...)
5. self.send_notification(narrative, recipients, provider="email")
```

### Materiality

A recommendation is **material** (`is_material=True`) when:
- Status is `"new"` or `"severity_changed"` (worsened), AND
- Severity is `"CRITICAL"` or `"HIGH"`.

Only material recommendations trigger Jira tickets.

## Output: ADVISORY ReportRef

Each run persists one `ReportRef` per framework with:
- `report_kind = ReportKind.ADVISORY`
- `scanner = "security_advisor"`
- `content_type = "text/markdown"`
- Raw content: LLM-generated markdown advisory

## Public API

```python
from parrot_tools.security import (
    SecurityAdvisoryEngine,
    AdvisoryReport,
    FindingDelta,
    AdvisoryRecommendation,
    SOC2AdvisoryToolkit,
)

# Standalone engine usage
engine = SecurityAdvisoryEngine(report_store)
report: AdvisoryReport = await engine.build_daily_advisory(framework="soc2")

# Toolkit usage (agent-facing)
toolkit = SOC2AdvisoryToolkit(report_store=store)
advisory_dict = await toolkit.daily_soc2_advisory(framework="soc2")
```

## Data Models

### AdvisoryReport

| Field | Type | Description |
|-------|------|-------------|
| `framework` | `str` | Compliance framework (e.g. `"soc2"`) |
| `baseline_report_id` | `str \| None` | Yesterday's report UUID |
| `current_report_id` | `str` | Today's report UUID |
| `severity_delta` | `SeverityBreakdown` | Current minus baseline counts per severity |
| `deltas` | `list[FindingDelta]` | Per-finding change classification |
| `soc2_coverage` | `dict` | Coverage stats from ComplianceMapper |
| `control_findings` | `dict[str, int]` | Control ID → finding count |
| `recommendations` | `list[AdvisoryRecommendation]` | Prioritised actions |
| `provider` | `str` | Cloud provider (default `"aws"`) |

### FindingDelta

Status values: `"new"` | `"resolved"` | `"persisting"` | `"severity_changed"`.

### AdvisoryRecommendation

Includes `soc2_control_ids`, `affected_resources`, `recommended_action`, and
`is_material` flag.

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `SECURITY_NOTIFICATION_RECIPIENTS` | `jlara@trocglobal.com` | Email recipients |
| `AWS_SECURITY_BUCKET_NAME` | — | S3 bucket for report storage |
| `JIRA_INSTANCE` | — | Jira server URL |
| `JIRA_USERNAME` | — | Jira username |
| `JIRA_API_TOKEN` | — | Jira API token |
| `JIRA_PROJECT` | `NAV` | Default Jira project key |

## Registration

```python
@register_agent(name="security_advisor", at_startup=True)
class SecurityAdvisor(Agent):
    agent_id: str = "security_advisor"
    model: str = "gemini-3-flash-preview"
```

The agent is registered at startup and available via the agent registry.
It lives in `agents/security_advisor.py` (gitignored; committed with `git add -f`).

## See Also

- `parrot_tools/security/advisory_engine.py` — `SecurityAdvisoryEngine` implementation
- `parrot_tools/security/soc2_advisory.py` — `SOC2AdvisoryToolkit` implementation
- `parrot_tools/security/reports/compliance_mapper.py` — SOC2 control mapping
- `parrot_tools/security/reports/soc2_controls.yaml` — SOC2 control catalog
- `parrot/storage/security_reports/models.py` — `ReportKind.ADVISORY` enum value
- `agents/security_advisor.py` — Agent definition and scheduled task
