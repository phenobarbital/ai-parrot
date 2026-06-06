---
type: feature
base_branch: dev
---

# Feature Specification: SecurityAdvisor — SOC2-Oriented Read-Only Advisory Agent

**Feature ID**: FEAT-226
**Date**: 2026-06-05
**Author**: Jesus Lara
**Status**: approved
**Target version**: v1

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

The existing `SecurityAgent` (`agents/security.py`) **produces** security
posture data: it runs expensive scanners (CloudSploit, Prowler, Trivy,
Checkov), aggregates ECR/Inspector/SecurityHub findings, and persists every
result into the cross-session catalog (`PostgresS3SecurityReportStore`, FEAT-162)
— metadata in Postgres, content blobs in S3.

What the platform lacks is a **consumer** of that catalog that turns the
accumulated reports into *decisions*. Today a human must open individual HTML
reports, eyeball severity counts, manually notice that "yesterday we had 3
CRITICALs and today we have 7", and translate raw scanner findings into the
language an auditor speaks — SOC2 Trust Service Criteria (CC1–CC9).

We need a second, **read-only** agent — `SecurityAdvisor` — that:

1. Reads the reports the `SecurityAgent` already wrote (it never launches a
   scanner itself).
2. Generates **day-by-day comparatives** (drift: new findings, resolved
   findings, severity shifts) per compliance framework.
3. Produces **actionable recommendations** on the detected security
   incidents, explicitly **mapped to SOC2 controls**, so the output is
   audit-ready.

The read-side infrastructure already exists and must be **reused, not
rebuilt**: `SecurityReportToolkit` (catalog queries), `S3ReportReaderToolkit`
(FEAT-184 — `compare_reports`, `summarize_report`, `filter_reports`, raw S3
browse), and — critically — **`ComplianceMapper` + `soc2_controls.yaml`**
(`parrot_tools/security/reports/`), which already provides a deterministic
SOC2 control catalog (CC1–CC9) and `map_finding_to_controls()` /
`get_framework_coverage()`. The new work is therefore narrow: a deterministic
advisory **engine** that diffs day-over-day and maps the delta to SOC2 controls
*via `ComplianceMapper`*, an LLM-facing **SOC2 advisory toolkit**, the
`ReportKind.ADVISORY` enum value, and the read-only **`SecurityAdvisor`** agent
that orchestrates a scheduled daily advisory plus on-demand answers.

### Goals

- A new `SecurityAdvisor` agent that is **strictly read-only** — it mounts
  only reader toolkits and never instantiates or invokes a scanner toolkit.
- **Day-over-day drift**: compare the two most-recent reports per framework
  (today vs. the prior day) and surface new/resolved findings and severity
  deltas.
- **Structured SOC2 mapping** of scanner findings to Trust Service Criteria
  (CC1–CC9) — deterministic, not LLM-only guesswork. This **reuses the existing
  `ComplianceMapper` + `soc2_controls.yaml`** (`parrot_tools/security/reports/`)
  rather than building a new catalog.
- **Actionable, SOC2-mapped recommendations** for each material incident.
- **Flexible output**: the daily advisory is (a) persisted as a `ReportRef`
  in the same catalog, (b) raised as Jira tickets for material incidents,
  and (c) emailed to the security recipients — and the agent also answers
  on-demand questions.
- **Scheduled daily** advisory run **plus** on-demand tools, mirroring the
  `SecurityAgent` `@schedule` pattern.

### Non-Goals (explicitly out of scope)

- **Running scanners.** The advisor never calls CloudSploit / Prowler /
  Trivy / Checkov, never launches Docker scans, never triggers a fresh scan.
  *(Read-only + may-trigger-scan was considered and rejected — it would
  re-couple the advisor to the expensive scan path the `SecurityAgent`
  already owns.)*
- **Modifying `PostgresS3SecurityReportStore` behavior or its `security_reports`
  schema.** The only catalog change is one additive `ReportKind` enum value
  (text column — no DDL migration).
- **Replacing `SecurityReportToolkit` or `S3ReportReaderToolkit`** — both are
  consumed as-is.
- **Full SOC2 audit automation / evidence collection.** We map findings to
  controls and recommend actions; we do not generate a complete SOC2 audit
  package.
- **New scanners or new parsers.**

---

## 2. Architectural Design

### Overview

`SecurityAdvisor` is an `Agent` subclass registered via
`@register_agent`. It composes **only reader toolkits** plus Jira:

- `SecurityReportToolkit` — catalog queries (`find_security_report`,
  `read_security_report`, `search_findings`, `list_available_frameworks`).
- `S3ReportReaderToolkit` (`s3_` prefix) — `compare_reports`,
  `summarize_report`, `filter_reports`, `get_latest_report`, raw S3 browse.
- **`SOC2AdvisoryToolkit`** (`soc2_` prefix) — NEW. LLM-facing tools that map
  a report's findings to SOC2 controls and run a gap analysis.
- `JiraToolkit` — to file actionable incidents (`basic_auth`, project `NAV`).

The SOC2 control catalog and finding→control mapping are **NOT new** — they
already exist as `ComplianceMapper` (`parrot_tools/security/reports/compliance_mapper.py`)
backed by `mappings/soc2_controls.yaml` (CC1–CC9). The only NEW deterministic
brain is one pure-logic module (no agent, no LLM, no I/O beyond the injected
store + mapper):

- **`advisory_engine.py`** — `SecurityAdvisoryEngine`, which, given a
  `SecurityReportStore` and a `ComplianceMapper`, computes the day-over-day
  diff for a framework (query latest two `ReportRef`s, parse both into
  `list[SecurityFinding]`, diff into new / resolved / persisting /
  severity-changed sets), maps the delta to SOC2 controls via
  `ComplianceMapper.map_finding_to_controls()` and
  `get_framework_coverage()`, and returns a structured `AdvisoryReport`
  Pydantic model (no narrative — the agent's LLM writes prose from it).
  Where useful it reuses the existing `ComparisonDelta` model
  (`parrot_tools.security.models`) instead of re-deriving diff lists.

The agent's scheduled task is the orchestration seam: it calls the engine per
framework, asks its own LLM to narrate the structured `AdvisoryReport`,
persists the markdown as a `ReportRef` (`report_kind=ADVISORY`), files Jira
tickets for material incidents, and emails the recipients.

### Component Diagram

```
                       SecurityAdvisor (Agent, read-only)
                                  │
        ┌──────────────┬──────────┴───────────┬───────────────┐
        ▼              ▼                      ▼               ▼
SecurityReport   S3ReportReader      SOC2AdvisoryToolkit   JiraToolkit
  Toolkit          Toolkit (s3_)        (soc2_)             (NAV tickets)
   (catalog)     (diff/summarize)          │
        │              │                    ▼
        └──────┬───────┘          ┌──────────────────┐
               ▼                  │ SecurityAdvisory  │
     PostgresS3SecurityReportStore│     Engine        │──► AdvisoryReport
       (query / get / fetch)      └────────┬─────────┘     (Pydantic)
               ▲                           ▼
               │                  ┌──────────────────┐
               └──────────────────│  soc2_controls   │ (CC1–CC9 catalog +
                                  │  map_finding_to_ │  deterministic mapping)
                                  │   controls()     │
                                  └──────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.bots.Agent` | subclass | `SecurityAdvisor(Agent)`, async-first |
| `parrot.registry.register_agent` | decorator | `@register_agent(name="security_advisor", at_startup=True)` |
| `PostgresS3SecurityReportStore` | uses (read) | `query`, `get`, `fetch_content` only — never writes via scanner mixins |
| `SecurityReportToolkit` | mounts | catalog read tools (FEAT-162) |
| `S3ReportReaderToolkit` | mounts | diff/summarize tools (FEAT-184) |
| `JiraToolkit` | mounts | files incident tickets (project `NAV`) |
| `ReportRef` / `ReportKind` / `SeverityBreakdown` | uses | persists advisory as a `ReportRef` |
| `parrot.scheduler.schedule` / `ScheduleType` | uses | daily advisory task |
| `ComplianceFramework.SOC2` | uses | `parrot_tools.security.models.ComplianceFramework.SOC2 = "soc2"` |
| `Agent.markdown_report` / `Agent.ask` / `send_notification` | calls | render + narrate + email |

### Data Models

SOC2 control data and finding→control mapping are provided by the EXISTING
`ComplianceMapper` (returns `list[str]` control IDs and coverage `dict`s) —
the engine consumes it; no new SOC2 model is defined. The NEW models live in
`advisory_engine.py`:

```python
# parrot_tools/security/advisory_engine.py
from pydantic import BaseModel, Field

class FindingDelta(BaseModel):
    """Day-over-day change for a single finding (aligned to SecurityFinding)."""
    finding_id: str                 # SecurityFinding.id
    status: Literal["new", "resolved", "persisting", "severity_changed"]
    severity: str                   # SeverityLevel value
    previous_severity: str | None = None
    title: str
    resource: str | None = None     # SecurityFinding.resource
    check_id: str | None = None     # SecurityFinding.check_id
    soc2_control_ids: list[str] = Field(default_factory=list)  # from ComplianceMapper

class AdvisoryRecommendation(BaseModel):
    """One actionable recommendation tied to SOC2 controls."""
    title: str
    severity: str
    soc2_control_ids: list[str]     # from ComplianceMapper.map_finding_to_controls
    affected_resources: list[str] = Field(default_factory=list)
    recommended_action: str
    is_material: bool               # gates Jira ticket creation

class AdvisoryReport(BaseModel):
    """Structured day-over-day SOC2 advisory for one framework. No narrative."""
    framework: str
    baseline_report_id: str | None  # prior-day report (None on first run)
    current_report_id: str
    severity_delta: SeverityBreakdown        # current − baseline (signed counts)
    deltas: list[FindingDelta]
    soc2_coverage: dict                       # ComplianceMapper.get_framework_coverage()
    control_findings: dict[str, int]          # control_id -> failing-finding count
    recommendations: list[AdvisoryRecommendation]
```

### New Public Interfaces

```python
# REUSED (already exists) — parrot_tools/security/reports/compliance_mapper.py
class ComplianceMapper:
    def __init__(self, mappings_dir: str | None = None) -> None: ...
    def map_finding_to_controls(self, finding: SecurityFinding,
                                framework: ComplianceFramework) -> list[str]: ...
    def get_framework_coverage(self, findings: list[SecurityFinding],
                               framework: ComplianceFramework) -> dict: ...
    def get_findings_by_control(self, findings, framework) -> dict[str, list[SecurityFinding]]: ...

# NEW — parrot_tools/security/advisory_engine.py
class SecurityAdvisoryEngine:
    def __init__(self, report_store: SecurityReportStore,
                 mapper: ComplianceMapper | None = None) -> None: ...
    async def build_daily_advisory(
        self, *, framework: str, provider: str = "aws",
    ) -> AdvisoryReport: ...

# NEW — parrot_tools/security/soc2_advisory.py
class SOC2AdvisoryToolkit(AbstractToolkit):
    tool_prefix: str = "soc2"
    def __init__(self, report_store: SecurityReportStore, **kwargs) -> None: ...
    async def map_report_to_soc2(self, report_id: str) -> dict: ...
    async def soc2_gap_analysis(self, framework: str = "soc2") -> dict: ...
    async def daily_soc2_advisory(self, framework: str = "soc2",
                                  provider: str = "aws") -> dict: ...
```

---

## 3. Module Breakdown

> These map directly to Task Artifacts in Phase 2.

### Module 0: `ReportKind.ADVISORY` enum value
- **Path**: `packages/ai-parrot/src/parrot/storage/security_reports/models.py`
- **Responsibility**: Add a single additive enum member
  `ADVISORY = "advisory"` to `ReportKind` so advisory outputs are
  catalog-distinguishable from `SCAN` / `WEEKLY_SUMMARY` / `DRIFT_COMPARISON`.
  The `report_kind` Postgres column is text — **no DDL migration required**.
- **Depends on**: none.

### Module 1: SecurityAdvisoryEngine (day-over-day diff + SOC2 mapping)
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/security/advisory_engine.py`
- **Responsibility**: `SecurityAdvisoryEngine.build_daily_advisory()` —
  query the two most-recent `ReportRef`s for a framework via
  `store.query(ReportFilter(..., order_by="produced_at_desc", limit=2))`,
  fetch + parse both into `list[SecurityFinding]`, compute `FindingDelta`s
  (new/resolved/persisting/severity_changed), roll up a signed
  `severity_delta`, map the delta to SOC2 controls via the EXISTING
  `ComplianceMapper.map_finding_to_controls()` / `get_framework_coverage()`,
  and assemble `AdvisoryReport` + `AdvisoryRecommendation`s. First-run
  (single report) yields baseline=None and treats all findings as `new`.
  Reuse `ComparisonDelta` (`parrot_tools.security.models`) where it fits.
- **Depends on**: Module 0 (none, really); `ComplianceMapper` (exists);
  `SecurityReportStore`; `get_report_parser`; `SecurityFinding` (exists).

### Module 2: SOC2AdvisoryToolkit (LLM-facing, read-only)
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/security/soc2_advisory.py`
- **Responsibility**: `AbstractToolkit` with `tool_prefix="soc2"`, wrapping
  Module 1 + `ComplianceMapper` as agent tools: `map_report_to_soc2`,
  `soc2_gap_analysis` (delegates to `ComplianceMapper.get_framework_coverage`
  / `get_unmapped_findings`), `daily_soc2_advisory`. Returns structured dicts
  (no narrative). Store required; never writes.
- **Depends on**: Module 1; `ComplianceMapper`; `AbstractToolkit`;
  `SecurityReportStore`.

### Module 3: SecurityAdvisor agent
- **Path**: `agents/security_advisor.py`
- **Responsibility**: `@register_agent(name="security_advisor")` `Agent`
  subclass. SOC2-oriented `BACKSTORY`. `agent_tools()` mounts (idempotently)
  `SecurityReportToolkit`, `S3ReportReaderToolkit`, `SOC2AdvisoryToolkit`,
  `JiraToolkit` — **no scanner toolkits**. One `@schedule(DAILY)` task
  `run_daily_soc2_advisory()` that, per framework: calls the engine, narrates
  the `AdvisoryReport` via `self.ask`, persists markdown as a `ReportRef`
  (`report_kind=ADVISORY`), creates a Jira `NAV` ticket per material
  recommendation, and emails the recipients via `send_notification`.
- **Depends on**: Modules 0, 1, 2.

### Module 4: Package exports & docs
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/security/__init__.py`,
  `docs/` advisory note.
- **Responsibility**: Export `SOC2AdvisoryToolkit`, `SecurityAdvisoryEngine`,
  `AdvisoryReport` (+ the new `advisory_engine` models); short doc page
  describing the read-only advisor and its reuse of `ComplianceMapper` for
  SOC2 mapping. (Do NOT export a new SOC2 catalog — it does not exist; the
  catalog is `ComplianceMapper` + `soc2_controls.yaml`.)
- **Depends on**: Modules 1, 2.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_engine_reuses_compliance_mapper` | M1 | Engine maps a finding's controls via injected `ComplianceMapper` (e.g. S3 public → `CC6.x`); no bespoke catalog |
| `test_engine_first_run_all_new` | M1 | Single report → baseline None, all deltas `new` |
| `test_engine_day_over_day_delta` | M1 | Two reports → correct new/resolved/persisting/severity_changed sets + signed `severity_delta` |
| `test_engine_material_recommendation_flag` | M1 | New CRITICAL → `is_material=True`; resolved LOW → not material |
| `test_engine_soc2_coverage_present` | M1 | `AdvisoryReport.soc2_coverage` populated from `get_framework_coverage` |
| `test_toolkit_map_report_to_soc2` | M2 | Returns SOC2 control mapping dict for a stored report |
| `test_toolkit_requires_catalog` | M2 | Missing report → structured `{"error": ...}`, no raise |
| `test_advisor_tools_are_read_only` | M3 | `agent_tools()` mounts no scanner toolkit (no CloudSploit/Prowler/Trivy/Checkov tool names) |
| `test_advisor_registered` | M3 | `security_advisor` resolvable via registry |

### Integration Tests
| Test | Description |
|---|---|
| `test_daily_advisory_end_to_end` | Seed two `ReportRef`s (framework=soc2) in a fake store → `run_daily_soc2_advisory` persists one `ADVISORY` ReportRef, emits ≥1 recommendation, calls Jira for material items (mocked), sends email (mocked) |
| `test_advisory_persisted_kind` | Persisted advisory has `report_kind == ReportKind.ADVISORY` and a non-empty `uri` |

### Test Data / Fixtures
```python
@pytest.fixture
def fake_store():
    """In-memory SecurityReportStore double: query/get/fetch_content/save_report."""
    ...

@pytest.fixture
def two_soc2_reports(fake_store):
    """Yesterday + today SOC2 scan ReportRefs with overlapping + diverging findings."""
    ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All unit tests pass (`pytest packages/ai-parrot-tools/tests/security/ -v`)
- [ ] All integration tests pass (`pytest tests/ -k advisor -v`)
- [ ] `SecurityAdvisor.agent_tools()` mounts **zero** scanner toolkits — asserted
      by `test_advisor_tools_are_read_only` (read-only is a hard constraint).
- [ ] SOC2 mapping is performed by the EXISTING `ComplianceMapper` (no new
      catalog module is created) — asserted by `test_engine_reuses_compliance_mapper`.
- [ ] `AdvisoryReport.soc2_coverage` is populated from
      `ComplianceMapper.get_framework_coverage()`.
- [ ] `SecurityAdvisoryEngine.build_daily_advisory()` returns an `AdvisoryReport`
      whose `deltas` correctly classify new/resolved/persisting/severity_changed
      against the two most-recent reports for the framework.
- [ ] First-run (only one report exists) does not raise: baseline is `None`,
      all findings are `new`.
- [ ] The daily task persists exactly one `ReportRef` with
      `report_kind == ReportKind.ADVISORY` per framework with findings.
- [ ] Material recommendations (`is_material=True`) create a Jira `NAV` ticket;
      non-material ones do not (verified with a mocked `JiraToolkit`).
- [ ] The daily task emails the security recipients via `send_notification`.
- [ ] `ReportKind.ADVISORY` is additive — no DDL migration, existing rows/tests
      unaffected.
- [ ] No new dependency on any scanner SDK or Docker image.
- [ ] Documentation updated in `docs/`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** All entries below were verified by
> reading source on 2026-06-05.

### Verified Imports
```python
# Agent base + registry (verified: agents/security.py:7-9)
from parrot.bots import Agent
from parrot.registry import register_agent

# Scheduler (verified: agents/security.py:10)
from parrot.scheduler import ScheduleType, schedule

# Catalog store + models (verified: packages/ai-parrot/src/parrot/storage/security_reports/__init__.py:6-16)
from parrot.storage.security_reports import (
    SecurityReportStore,            # Protocol (store.py:43)
    PostgresS3SecurityReportStore,  # impl (store.py:144)
    ReportFilter, ReportKind, ReportRef, SeverityBreakdown, EmbeddedFinding,
)
# NOTE: PostgresS3SecurityReportStore is imported by SecurityAgent from
#       parrot.storage.security_reports (sub-path) — verified agents/security.py:11.

# Reader toolkits to MOUNT (verified by class defs):
#   parrot_tools/security/report_toolkit.py:27  -> SecurityReportToolkit
#   parrot_tools/s3/report_reader.py:33         -> S3ReportReaderToolkit
# AbstractToolkit base (verified import in report_toolkit.py:16): from ..toolkit import AbstractToolkit
# Jira (verified: agents/security.py:24): from parrot_tools.jiratoolkit import JiraToolkit

# Compliance framework enum (verified: parrot_tools/security/models.py:40)
from parrot_tools.security import ComplianceFramework  # ComplianceFramework.SOC2 == "soc2"

# SOC2 mapping — REUSE (verified: parrot_tools/security/reports/compliance_mapper.py:16)
from parrot_tools.security.reports import ComplianceMapper  # verified: reports/__init__.py
# Finding + diff models — REUSE (verified: parrot_tools/security/models.py)
from parrot_tools.security.models import (
    SecurityFinding,   # :62
    SeverityLevel,     # :14  (has PASS member)
    ComparisonDelta,   # :153 (new/resolved/unchanged_findings, severity_trend)
)
```

### Existing Class Signatures
```python
# parrot/storage/security_reports/store.py  (SecurityReportStore Protocol)
async def query(self, filter: ReportFilter) -> list[ReportRef]        # :59 / impl :279
async def get(self, report_id: UUID) -> ReportRef | None              # :63 / impl :327
async def fetch_content(self, report_id: UUID) -> bytes               # :67 / impl :335
async def save_report(self, ref: ReportRef, content: bytes | Path) -> ReportRef  # :50 / impl :216
async def query_distinct_frameworks(self) -> list[str]                # :75 / impl :357

# parrot/storage/security_reports/models.py
class ReportKind(str, Enum):                                          # :25
    SCAN="scan"; DAILY_SUMMARY="daily_summary"; WEEKLY_SUMMARY="weekly_summary"
    MONTHLY_SUMMARY="monthly_summary"; DRIFT_COMPARISON="drift_comparison"
    # → ADD: ADVISORY = "advisory"   (Module 0)
class SeverityBreakdown(BaseModel):                                   # :35
    critical:int=0; high:int=0; medium:int=0; low:int=0; informational:int=0
    @property
    def total(self) -> int                                           # :49
class ReportRef(BaseModel):                                          # :69
    report_id: UUID; report_kind: ReportKind; scanner: str
    framework: str | None; provider: str; scope: dict
    severity_summary: SeverityBreakdown; top_findings: list[EmbeddedFinding]
    uri: str; content_type:str="application/json"; content_bytes:int|None
    produced_at: datetime; produced_by: str; parser_version: str
    retention_class: Literal["standard","compliance","ephemeral"]="compliance"
class ReportFilter(BaseModel):                                       # :108
    scanner|framework|provider|report_kind|since|until|scope_match
    limit:int=Field(default=50,ge=1,le=500); order_by:Literal["produced_at_desc","produced_at_asc"]="produced_at_desc"

# parrot_tools/security/report_toolkit.py  (SecurityReportToolkit, AbstractToolkit)
def __init__(self, report_store: SecurityReportStore, file_manager: FileManagerInterface, **kwargs)  # :44
async def find_security_report(self, scanner=None, framework=None, provider=None,
        scope_match=None, max_age_days=30, report_kind="scan", limit=5) -> list[dict]  # :66
async def read_security_report(self, report_id: str,
        section: Literal["summary","critical","high","medium","low","executive","full"]="summary") -> dict  # :126
async def search_findings(...) -> ...                                # :175
async def list_available_frameworks(self) -> list[str]              # :235

# parrot_tools/s3/report_reader.py  (S3ReportReaderToolkit, AbstractToolkit, tool_prefix="s3")
def __init__(self, file_manager: FileManagerInterface, report_store: SecurityReportStore|None=None,
        *, default_prefix="security-reports/", max_diff_changes=50, **kwargs)  # :62
async def get_latest_report(...) -> dict                            # :117
async def filter_reports(...) -> dict                               # :244
async def compare_reports(self, report_a: str, report_b: str) -> dict  # :296  (UUIDs or S3 paths)
async def summarize_report(self, report_id_or_path: str) -> dict    # :326  (structured metrics, no LLM)

# parrot/bots/agent.py
async def markdown_report(self, content: str, filename=None, filename_prefix='report',
        directory=None, subdir='documents', **kwargs) -> str        # :444  (returns Path)

# parrot_tools/security/reports/compliance_mapper.py  (ComplianceMapper — REUSE, do NOT rebuild)
def __init__(self, mappings_dir: str | None = None)                                  # :40
def map_finding_to_controls(self, finding: SecurityFinding, framework: ComplianceFramework) -> list[str]  # :142
def get_framework_coverage(self, findings: list[SecurityFinding], framework: ComplianceFramework) -> dict  # :187
def get_control_details(self, control_id: str, framework: ComplianceFramework) -> dict | None  # :279
def get_all_controls(self, framework: ComplianceFramework) -> dict[str, dict]                   # :311
def get_findings_by_control(self, findings, framework) -> dict[str, list[SecurityFinding]]      # :324
def get_unmapped_findings(self, findings, framework) -> list[SecurityFinding]                   # :354
# Backed by mappings/soc2_controls.yaml (CC1.1..CC9.x, framework: soc2, version "2017").

# parrot_tools/security/models.py  (SecurityFinding — the finding shape, REUSE)
class SecurityFinding(BaseModel):              # :62
    id: str; source: FindingSource; severity: SeverityLevel; title: str    # :69-72
    description: str|None; resource: str|None; resource_type: str|None      # :73-79
    region: str="global"; provider: CloudProvider|None; service: str|None   # :82-86
    check_id: str|None; compliance_tags: list[str]; remediation: str|None    # :89-96
    raw: dict|None; timestamp: datetime|None                                 # :99-102
class ComparisonDelta(BaseModel):              # :153  (reuse for diff if convenient)
    new_findings; resolved_findings; unchanged_findings: list[SecurityFinding]
    severity_trend: dict[str,int]                                            # :171

# agents/security.py — patterns to mirror (verified)
@register_agent(name="security_agent", at_startup=True)             # :124
class SecurityAgent(Agent):                                         # :125
    def agent_tools(self): ...        # idempotent toolkit build, returns list[tool]  # :168
    @schedule(schedule_type=ScheduleType.DAILY, hour=6, minute=0)
    async def summary_report(self): ...  # ask → markdown_report → save_report → Jira diff  # :751
    # send_notification usage: self.send_notification(message=, recipients=, provider="email", subject=)  # :555
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `SecurityAdvisoryEngine` | `SecurityReportStore.query` | two-report fetch | `store.py:279` |
| `SecurityAdvisoryEngine` | `store.fetch_content` + `get_report_parser` | parse findings | `store.py:335`, `report_toolkit.py:24` |
| `SOC2AdvisoryToolkit` | `AbstractToolkit` | subclass, `tool_prefix="soc2"` | `report_reader.py:59` (prefix pattern) |
| `SecurityAdvisor.run_daily_soc2_advisory` | `store.save_report` | persist `ADVISORY` ReportRef | `store.py:216` |
| `SecurityAdvisor` | `JiraToolkit.get_tools()` | mount Jira tools | `agents/security.py:299-321` |
| `SecurityAdvisor` | `send_notification` | email recipients | `agents/security.py:555` |

### Already EXISTS — REUSE, do NOT rebuild
- `ComplianceMapper` + `mappings/soc2_controls.yaml` — the SOC2 CC1–CC9 catalog
  and deterministic `map_finding_to_controls()` ALREADY EXIST. **Do NOT create
  a new `soc2_controls.py` / `SOC2_CONTROL_CATALOG` / `SOC2Control` /
  `map_finding_to_controls` function.** Import `ComplianceMapper` instead.
- `SecurityFinding`, `SeverityLevel` (has `PASS`), `ComparisonDelta` — exist in
  `parrot_tools.security.models`. Reuse them; do not redefine.

### Does NOT Exist (Anti-Hallucination)
- ~~`ReportKind.ADVISORY`~~ — does **not** exist yet; Module 0 adds it.
- ~~`SOC2AdvisoryToolkit`, `SecurityAdvisoryEngine`, `advisory_engine.py`~~ — new; do not import before creating.
- ~~`soc2_controls.py` as a NEW module / `SOC2_CONTROL_CATALOG` constant~~ — must NOT be created; the catalog is the existing `ComplianceMapper` + YAML.
- ~~A "SecurityAdvisor" agent~~ — does not exist; only `SecurityAgent` (`agents/security.py`).
- ~~`store.diff()` / `store.compare()`~~ — the store has **no** diff method. Diffing
  is done by `S3ReportReaderToolkit.compare_reports`, `ComparisonDelta`, or in the new engine.
- ~~`SecurityReportToolkit.compare_*`~~ — comparison lives in `S3ReportReaderToolkit`, not here.
- ~~`self._build_weekly_summary` as an `Agent` base method~~ — referenced in
  `agents/security.py:723` but **not** defined on the read path here; do not assume
  it exists on `Agent`. The advisor must not call it.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Tool-centric**: new capabilities ship as `parrot_tools/security/` modules +
  an `AbstractToolkit`; the agent only wires toolkits in `agent_tools()`.
- **Idempotent `agent_tools()`**: guard on a sentinel toolkit attribute and
  return cached tools — mirror `SecurityAgent.agent_tools()` (security.py:168-187).
- **Async-first**, Google-style docstrings, strict type hints, Pydantic for all
  structured data, `self.logger` (never `print`).
- **Deterministic mapping via reuse**: SOC2 mapping is done by the existing
  `ComplianceMapper` (pure logic, YAML-backed) — never by an LLM, and never by
  a new bespoke catalog. The LLM only narrates the already-computed
  `AdvisoryReport`. Note `ComplianceMapper.map_finding_to_controls` keys off
  `finding.source` + `check_id` (`SOURCE_TO_KEY` / `_get_check_key`), so the
  engine must parse report content into real `SecurityFinding`s (with `source`
  and `check_id` set) for mapping to resolve.
- **`produced_at` must be tz-aware UTC** (`datetime.now(timezone.utc)`) when
  building any `ReportRef` — the model does not validate this (models.py:99-100).

### Known Risks / Gotchas
- **`agents/` is gitignored.** `agents/security.py` is tracked only because it
  predates the ignore rule (same situation as `sdd/templates/*.md`). A *new*
  file `agents/security_advisor.py` **will be ignored** — the implementing task
  MUST `git add -f agents/security_advisor.py`, or the agent will be invisible to
  worktrees/CI. (Verified: `git check-ignore agents/security.py` matches; the file
  is nonetheless in `git ls-files`.)
- **No implicit `since` filter** in `store.query` (store.py:282) — the engine must
  pass `order_by="produced_at_desc"` + `limit=2` (and optionally `since`) explicitly
  to get "today vs. yesterday".
- **`until` is inclusive** (store.py:303) — when excluding the just-inserted row,
  subtract a microsecond, as `summary_report` does (security.py:802).
- **Parser availability**: `get_report_parser(scanner)` must resolve for the
  scanners present in the catalog; HTML-only reports won't parse to findings —
  the engine should degrade to severity-summary deltas from `ReportRef.severity_summary`
  rather than raising.
- **First run / sparse history**: a framework with only one report yields
  baseline=None. Do not treat "no prior report" as an error.
- **Read-only invariant is testable** — keep it that way: never import a scanner
  toolkit in `security_advisor.py`.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| (none new) | — | Reuses existing `parrot`, `parrot_tools`, `pydantic`, `asyncdb` |

---

## 8. Open Questions

> Resolved items were decided during spec intake (no prior brainstorm existed).

- [x] Where do recommendations land? — *Resolved at intake*: **all of** persisted
      `ReportRef` (catalog) + Jira `NAV` tickets for material incidents + email to
      security recipients, **and** on-demand agent answers.
- [x] Read-only vs. may-trigger-scan? — *Resolved at intake*: **strictly read-only**;
      the advisor never launches a scanner. Reflected in §1 Non-Goals and the
      `test_advisor_tools_are_read_only` acceptance criterion.
- [x] Cadence? — *Resolved at intake*: **scheduled daily** advisory + on-demand tools.
- [x] SOC2 mapping approach? — *Resolved at intake*: **structured SOC2 controls
      module** (CC1–CC9) with deterministic finding→control mapping (Modules 1–2),
      not LLM-only.
- [x] Exact daily `@schedule` hour for `run_daily_soc2_advisory` — *Owner: Jesus*:
      should land **after** the `SecurityAgent` scans complete (its latest scan
      schedules at 23:29 UTC). Proposed default: **09:30 UTC**. Decide during
      implementation; non-blocking.: 12:00 UTC
- [x] Which frameworks to iterate in the daily task — *Owner: Jesus*: default to
      `["soc2"]`, optionally also `query_distinct_frameworks()`. Non-blocking.: ok

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — all tasks run sequentially in one
  worktree (`feat-226-security-advisor`).
- Tasks are largely sequential by dependency: Module 0 → Module 1 → Module 2 →
  Module 3 → Module 4. Module 0 (enum) is independent of Module 1 and could be
  parallelized, but the per-spec sequential worktree is simplest given the small
  surface and shared package files.
- **Cross-feature dependencies**: none must be merged first — FEAT-162 (catalog)
  and FEAT-184 (`S3ReportReaderToolkit`) are already in `dev`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-06-05 | Jesus Lara | Initial draft (read-only SOC2 advisor; intake Q&A resolved) |
| 0.2 | 2026-06-05 | Jesus Lara | Reuse existing `ComplianceMapper` + `soc2_controls.yaml` for SOC2 mapping (dropped duplicate catalog module); 5 modules → 4 build tasks |
