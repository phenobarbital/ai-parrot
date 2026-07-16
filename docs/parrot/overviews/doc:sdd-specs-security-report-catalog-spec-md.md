---
type: Wiki Overview
title: 'Feature Specification: Cross-Session Security Report Catalog (Postgres + S3)
  with Fractal Summaries'
id: doc:sdd-specs-security-report-catalog-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The `SecurityAgent` (`agents/security.py`) runs a suite of scanners — CloudSploit,
relates_to:
- concept: mod:parrot.bots.abstract
  rel: mentions
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.interfaces.file
  rel: mentions
- concept: mod:parrot.registry
  rel: mentions
- concept: mod:parrot.scheduler
  rel: mentions
- concept: mod:parrot.tools
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
- concept: mod:parrot_tools.security.models
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: Cross-Session Security Report Catalog (Postgres + S3) with Fractal Summaries

**Feature ID**: FEAT-162
**Date**: 2026-05-12
**Author**: Jesus Lara
**Status**: approved
**Target version**: v1

---

## 1. Motivation & Business Requirements

### Problem Statement

The `SecurityAgent` (`agents/security.py`) runs a suite of scanners — CloudSploit,
Prowler, Trivy, Checkov — most of them Docker-backed and slow (≈10 min per
full run). Today, results live in `/tmp/security-reports/` on the host
filesystem, scoped to the process that produced them and lost on restart.
This creates two friction points:

1. **Conversational re-scans.** A user asking *"give me the HIPAA posture
   report"* triggers a full container scan even when an identical report
   was produced by the daily `@schedule`d task at 08:00 UTC the same morning.
2. **No operational history.** Scheduled tasks log a `dict` of results
   that nobody consumes afterward. There is no way to answer *"how did our
   HIPAA posture change this month?"* or *"which critical findings have
   been open for >2 weeks?"*.

This feature introduces a cross-session, cross-user catalog of security
reports backed by Postgres (metadata) and S3 (content), populated by the
existing producers via a mixin, and consumed by the agent through a new
`SecurityReportToolkit`. Weekly/monthly summarization tasks produce
*higher-level reports of the same shape*, building a fractal operational
memory.

### Goals

- Decouple report **production** (toolkits) from **persistence** (store)
  from **consumption** (toolkit for the LLM).
- Cross-session, cross-user catalog — *not* scoped to a conversation thread.
- Agent prefers reading a recent report over re-running an expensive scan,
  governed by **explicit prompt guidance**, not hidden routing logic.
- Build an operational history that supports trend/drift questions
  (weekly summaries, monthly summaries, persistent findings).
- Reuse the existing FileManager abstraction (`parrot/interfaces/file/*`
  re-exporting `navigator.utils.file`) — no new transport layer.
- Compliance retention: **never delete reports.** Visibility window is a
  query parameter, not a TTL.

### Non-Goals (explicitly out of scope)

- Replacing the FEAT-103 `ArtifactStore` at `parrot/storage/artifacts.py`
  (conversation-scoped artifacts — different abstraction, different lifecycle).
- Generic file-storage UX through the LLM (already covered by `FileManagerTool`).
- Per-user credential / auth on the catalog (single-tenant assumption for v1).
- Cross-agent catalog usage (deferred until a second consumer appears).
- Vector indexing of individual findings in PgVector (hook included,
  activation deferred to a follow-up FEAT).
- Per-finding indexing — `search_findings` v1 only queries the embedded
  top-10 findings per report (resolved in proposal U4).
- S3 storage-class tiering / Glacier lifecycle (deferred; the Terraform
  pattern in `.claude/rules/aws-cost-optimization.md` is referenced for
  the follow-up FEAT).
- Migration of `/tmp/security-reports/` legacy host-filesystem reports
  — v1 starts fresh.
- Cross-tenant isolation — when multi-tenancy hits, add `tenant_id` to
  schema in a follow-up FEAT.
- A nav-admin UI for browsing the catalog (follow-up FEAT, SvelteKit 5 +
  daisyUI per project conventions).

---

## 2. Architectural Design

### Overview

A three-layer separation, strictly enforced:

1. **Producer layer** — existing scanner toolkits (`CloudSploitToolkit`,
   `ComplianceReportToolkit`, `ContainerSecurityToolkit`) gain a
   `ReportPersistenceMixin`. When constructed with a `file_manager` AND
   a `report_store` (both injected by the `SecurityAgent`), each scan
   method auto-persists its output as a side effect. When either is
   `None`, persistence is a no-op (backward compat).
2. **Persistence layer** — a new `PostgresS3SecurityReportStore` writes
   content to S3 via the existing `FileManagerInterface` (April-2026
   migration to `parrot/interfaces/file/*`) and metadata to a Postgres
   table via `asyncdb.AsyncDB(driver='pg', dsn=...)`. The store exposes
   a Protocol-typed API: `save_report`, `query`, `get`, `fetch_content`,
   `index`, `delete` (deletion reserved for explicit GDPR requests).
3. **Consumer layer** — a new `SecurityReportToolkit` exposes four
   LLM-facing tools: `find_security_report`, `read_security_report`,
   `search_findings`, `list_available_frameworks`. The `SecurityAgent`'s
   BACKSTORY is updated with a mandatory *freshness policy* block that
   tells the LLM to call `find_security_report` BEFORE any expensive
   scan tool.

**Fractal summaries.** Weekly and monthly consolidators (`@schedule`d
methods on `SecurityAgent`) produce reports with `report_kind ∈
{weekly_summary, monthly_summary}` written to the **same table**. The
catalog's `ReportRef` shape is shared across raw scans and aggregates.
Diff arithmetic (severity totals, new/resolved findings) is deterministic
Python; an LLM (`ThinkingConfig(include_thoughts=False)` per the existing
precedent in `parrot/clients/google/client.py:1957-1977`) is used *only*
for the `executive_paragraph` field — keeping summaries reproducible and
audit-friendly.

### Component Diagram

```
┌─ Producer side ────────────────────────────────────────────────┐
│  CloudSploitToolkit ─┐                                         │
│  ComplianceToolkit  ─┼─► ReportPersistenceMixin                │
│  ContainerToolkit   ─┘     │                                   │
│                            │ _persist_report(...)              │
│                            ▼                                   │
│                  ┌─────────────────────┐                       │
│                  │   FileManager       │ ──► S3 bucket         │
│                  │   (upload_file)     │                       │
│                  └─────────────────────┘                       │
│                            │                                   │
│                            ▼                                   │
│                  ┌─────────────────────┐                       │
│                  │ SecurityReportStore │ ──► Postgres (asyncdb)│
│                  │      (catalog)      │                       │
│                  └─────────────────────┘                       │
└────────────────────────────────────────────────────────────────┘
                             │
                             │ shared store + file_manager
                             ▼
┌─ Consumer side ────────────────────────────────────────────────┐
│  SecurityReportToolkit (LLM-facing)                            │
│    • find_security_report(...)   ← metadata only               │
│    • read_security_report(...)   ← content by section          │
│    • search_findings(...)        ← cross-report query (v1)     │
│    • list_available_frameworks() ← discovery                   │
└────────────────────────────────────────────────────────────────┘

┌─ Scheduled consolidators (same agent, same store) ─────────────┐
│  Mon 06:00 UTC  → consolidate_weekly_security_summary          │
│                    reads scans (last 7d), writes report_kind=  │
│                    "weekly_summary" for each framework         │
│                                                                │
│  1st 06:00 UTC  → consolidate_monthly_security_summary         │
│                    reads weekly_summaries (last 4w), writes    │
│                    report_kind="monthly_summary"               │
└────────────────────────────────────────────────────────────────┘
```

**Key invariant**: `ReportKind ∈ {scan, weekly_summary, monthly_summary,
drift_comparison}` all live in the same table with the same `ReportRef`
shape. Summaries are reports about reports — the type is fractal.

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `FileManagerInterface` (`parrot/interfaces/file/*` re-exporting `navigator.utils.file`) | uses (consumer) | Store calls `upload_file(source, destination)`, `download_file(source, destination)`, `get_file_url(path, expiry=3600)`, `exists(path)` — see §6. |
| `FileManagerFactory.create` (`parrot/tools/file/tool.py`) | uses | `create(manager_type='s3', bucket_name=..., prefix=..., aws_id='security')`. NO `aws_config` kwarg — see §6 Does-Not-Exist. |
| `AbstractToolkit` (`parrot/tools/toolkit.py:191`) | extends | `SecurityReportToolkit` inherits; tools auto-discovered (every async public method minus lifecycle exclusions at L368-403). |
| `ReportPersistenceMixin` (new) | mix-in | Composed into `CloudSploitToolkit`, `ComplianceReportToolkit`, `ContainerSecurityToolkit`. Mixin pops its kwargs (`file_manager`, `report_store`) before `super().__init__(**kwargs)`. |
| `ScheduleType` + `@schedule` (`parrot/scheduler/__init__.py:41-96`) | uses | New `@schedule(schedule_type=ScheduleType.WEEKLY, day_of_week=0, hour=6, minute=0)` and `@schedule(schedule_type=ScheduleType.MONTHLY, day=1, hour=6, minute=0)` on `SecurityAgent`. |
| `register_agent` (`parrot/registry/registry.py:1130-1156`) | reuses | `SecurityAgent` already registered; no new registration. |
| `AbstractBot.llm` (`parrot/bots/abstract.py:922-928`) | reuses | Summarizer accepts `llm_client=self.llm`. |
| `asyncdb.AsyncDB(driver='pg', dsn=...)` | uses | Store driver; matches `parrot/bots/database/toolkits/base.py:344-351`. |
| `ThinkingConfig(include_thoughts=False)` (`parrot/clients/google/client.py:1957-1977`) | reuses | Pattern for the summarizer's structured-output LLM call. |
| `navconfig.config` (`parrot/conf.py`) | extends | Adds `AWS_CREDENTIALS['security']` slot derived from the `aws_security` INI section. |
| FEAT-103 `ArtifactStore` (`parrot/storage/artifacts.py:22`) | peer (does NOT extend, does NOT replace) | Different lifecycle, different consumers. Spec must NOT depend on it. |
| FEAT-160 `CloudSploitConfig` (`parrot_tools/cloudsploit/`) | aligns with | New `CloudSploitConfig.config_file` field + per-call `config` arg threaded through where SecurityAgent constructs the toolkit. |

### Data Models

```python
# parrot/storage/security_reports/models.py — Pydantic v2 (project pin: 2.12.5)
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
    # @property total -> sum of fields (computed; not stored)

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
    scanner: str                              # "cloudsploit" | "prowler" | "trivy" | "checkov" | "aggregator"
    framework: str | None                     # "HIPAA" | "PCI" | "SOC2" | "GDPR" | None for raw container scans
    provider: str                             # "aws" | "azure" | "gcp" | "oci" | "n/a"
    scope: dict                               # {region, account_id, target_image, iac_path, source_report_ids?}
    severity_summary: SeverityBreakdown
    top_findings: list[EmbeddedFinding]       # max 10, sorted by severity desc
    uri: str                                  # "s3://bucket/key" or "file://path"
    content_type: str = "application/json"
    content_bytes: int | None = None
    produced_at: datetime                     # tz-aware UTC
    produced_by: str                          # "schedule:run_hipaa_pci_compliance" | "agent:<session_id>"
    parser_version: str                       # for schema migrations
    retention_class: Literal["standard", "compliance", "ephemeral"] = "compliance"

class ReportFilter(BaseModel):
    """Query filter for the store. NO age filtering at this layer."""
    scanner: str | None = None
    framework: str | None = None
    provider: str | None = None
    report_kind: ReportKind | None = None
    since: datetime | None = None
    until: datetime | None = None
    scope_match: dict | None = None           # partial dict match (account_id, region, etc.)
    limit: int = 50
    order_by: Literal["produced_at_desc", "produced_at_asc"] = "produced_at_desc"
```

### New Public Interfaces

```python
# parrot/storage/security_reports/store.py
from pathlib import Path
from typing import Protocol
from uuid import UUID

class SecurityReportStore(Protocol):
    async def save_report(self, ref: ReportRef, content: bytes | Path) -> ReportRef: ...
    async def index(self, ref: ReportRef) -> None: ...
    async def query(self, filter: ReportFilter) -> list[ReportRef]: ...
    async def get(self, report_id: UUID) -> ReportRef | None: ...
    async def fetch_content(self, report_id: UUID) -> bytes: ...
    async def delete(self, report_id: UUID) -> None: ...   # GDPR-only; not used by retention
    async def bootstrap_schema(self) -> None: ...           # additive helper; runs schema.sql idempotently
```

```python
# parrot_tools/security/persistence.py
class ReportPersistenceMixin:
    """Mixin for any toolkit that produces a security report artifact.

    Activation: pass file_manager AND report_store to the toolkit constructor.
    If either is None, _persist_report() returns None (no-op, no error).

    Construction protocol: producer toolkit must pop these kwargs from
    **kwargs BEFORE super().__init__(**kwargs) to preserve AbstractToolkit's
    parent contract.
    """
    file_manager: FileManagerInterface | None = None
    report_store: SecurityReportStore | None = None
    parser_version: str = "1.0.0"

    async def _persist_report(
        self,
        *,
        scanner: str,
        framework: str | None,
        provider: str,
        scope: dict,
        content: bytes | Path,
        content_type: str = "application/json",
        report_kind: ReportKind = ReportKind.SCAN,
        produced_by: str | None = None,
        severity_summary: SeverityBreakdown | None = None,
        top_findings: list[EmbeddedFinding] | None = None,
    ) -> ReportRef | None: ...
```

```python
# parrot_tools/security/report_toolkit.py
class SecurityReportToolkit(AbstractToolkit):
    """Read-side toolkit. The agent calls THIS before running expensive scans."""

    DEFAULT_VISIBILITY_DAYS: int = 30

    def __init__(
        self,
        report_store: SecurityReportStore,
        file_manager: FileManagerInterface,
        **kwargs,
    ): ...

    async def find_security_report(
        self,
        scanner: str | None = None,
        framework: str | None = None,
        provider: str | None = None,
        scope_match: dict | None = None,
        max_age_days: int = 30,
        report_kind: str = "scan",
        limit: int = 5,
    ) -> list[dict]: ...

    async def read_security_report(
        self,
        report_id: str,
        section: Literal["summary", "critical", "high", "medium", "low", "executive", "full"] = "summary",
    ) -> dict: ...

    async def search_findings(
        self,
        query: str,
        scanner: str | None = None,
        severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"] | None = None,
        since_days: int = 30,
        limit: int = 20,
    ) -> list[dict]: ...   # v1: SQL ILIKE on top_findings JSONB only (see §1 Non-Goals)

    async def list_available_frameworks(self) -> list[str]: ...
```

```python
# parrot_tools/security/summarizer.py
class WeeklySummary(BaseModel):
    framework: str
    period_start: datetime
    period_end: datetime
    severity_totals: SeverityBreakdown
    new_findings: list[EmbeddedFinding]
    resolved_findings: list[EmbeddedFinding]
    persistent_findings: list[EmbeddedFinding]   # open ≥2 weeks
    executive_paragraph: str                      # 3–5 sentences
    source_report_ids: list[UUID]

class WeeklySecuritySummarizer:
    def __init__(self, llm_client: "GoogleGenAIClient"): ...
    async def build(
        self,
        scans: list[ReportRef],
        framework: str,
        previous_summary: ReportRef | None = None,
    ) -> WeeklySummary: ...

class MonthlySecuritySummarizer:
    """Same shape as WeeklySecuritySummarizer; consumes weekly_summary reports."""
    ...
```

---

## 3. Module Breakdown

> Implementation order matches dependency order. Tasks 1-3 must land
> before any producer-toolkit change (Task 6) so the broken stub at
> `agents/security.py:445-471` (see §6) imports cleanly.

### Module 1: Storage data models
- **Path**: `parrot/storage/security_reports/__init__.py`, `parrot/storage/security_reports/models.py`
- **Responsibility**: Pydantic v2 models: `ReportKind`, `SeverityBreakdown`,
  `EmbeddedFinding`, `ReportRef`, `ReportFilter`. Public exports via
  `__init__.py` mirror the model names.
- **Depends on**: nothing (pure data layer).

### Module 2: Postgres schema
- **Path**: `parrot/storage/security_reports/schema.sql`
- **Responsibility**: Bare DDL: `CREATE TABLE IF NOT EXISTS security_reports`
  with the column shape from §2 Data Models; three indexes
  (`(scanner, framework, produced_at DESC)`,
   `(report_kind, produced_at DESC)`,
   GIN on `scope`).
- **Depends on**: Module 1 (column names match the Pydantic model fields).
- **Operational note**: Applied out-of-band by ops, matching the
  `parrot/security/security_events.sql` precedent. No migration framework
  exists project-wide (resolved brainstorm OQ #2 — see §8).

### Module 3: Store Protocol + Postgres+S3 implementation
- **Path**: `parrot/storage/security_reports/store.py`
- **Responsibility**: `SecurityReportStore` Protocol + `PostgresS3SecurityReportStore`
  implementation using `asyncdb.AsyncDB(driver='pg', dsn=...)` and a
  `FileManagerInterface`. Methods:
  - `save_report(ref, content)`: upload to S3 first via `file_manager.upload_file(...)`,
    then insert metadata via asyncdb. Orphan-tolerant (S3 wins, Postgres can
    be reconciled out-of-band).
  - `query(filter)`: NEVER applies a default `since` filter — visibility window
    is the caller's responsibility.
  - `bootstrap_schema()`: idempotently executes `schema.sql`.
  - S3 key naming: `security-reports/{scanner}/{framework_or_none}/{YYYY}/{MM}/{DD}/{report_id}.json`
    — deterministic for human browsing; never used by the query path.
- **Depends on**: Modules 1 + 2 + the existing `FileManagerInterface`.

### Module 4: Per-scanner parser registry
- **Path**: `parrot_tools/security/parsers/__init__.py`, `parsers/trivy.py`,
  `parsers/cloudsploit.py`, `parsers/prowler.py`, `parsers/checkov.py`,
  `parsers/aggregator.py`
- **Responsibility**: Deterministic Python parsers — one per scanner — with two
  methods each: `parse(content) -> ParsedReport(severity_summary, top_findings)`
  and `extract_section(content, section) -> dict`. A `get_report_parser(scanner)`
  registry function dispatches by scanner name. Aggregator is a passthrough
  used by weekly/monthly summaries.
- **Why pure Python, not an LLM call**: speed, reproducibility, version-tag
  via `parser_version` on `ReportRef` to support future schema migrations.
- **Depends on**: Module 1 (returns Module 1's models).

### Module 5: ReportPersistenceMixin
- **Path**: `parrot_tools/security/persistence.py`
- **Responsibility**: The mixin defined in §2 New Public Interfaces. Owns
  the `_persist_report` flow: parse content (via Module 4) to derive
  `severity_summary` + `top_findings`, build the `ReportRef`, upload, index.
  Returns the persisted `ReportRef` or `None` (when deps absent).
- **Depends on**: Modules 1, 3, 4.

### Module 6: Producer toolkit integration
- **Path** (3 files, package likely `packages/ai-parrot-tools/src/parrot_tools/...`):
  - `parrot_tools/cloudsploit/toolkit.py`
  - `parrot_tools/security/<compliance-toolkit-module>.py`
  - `parrot_tools/security/<container-toolkit-module>.py`
- **Responsibility per toolkit**:
  - Add `ReportPersistenceMixin` to base chain.
  - `__init__` pops `file_manager` and `report_store` from `**kwargs` before
    `super().__init__(**kwargs)`.
  - After each scan method succeeds, call `await self._persist_report(...)`
    with the scanner-specific scope (`account_id`, `region`, `target_image`,
    `iac_path` as applicable). Return shape is **unchanged** — persistence
    is a side effect. Scan methods continue to return the Pydantic models
    (`ScanResult`, `ConsolidatedReport`) they return today.
- **Trivy specifics (resolved U3)**: `ContainerSecurityToolkit.trivy_scan_filesystem`
  (and siblings) capture stdout and write to a temp file *inside the toolkit*;
  hand the `Path` to the mixin; delete after `_persist_report` returns. The
  mixin's `content: bytes | Path` signature is unchanged.
- **CloudSploit specifics**: when `CloudSploitConfig.results_dir` is set, the
  toolkit already writes JSON to `{results_dir}/scan_{ts}.json` — pass that
  `Path` to the mixin. When `results_dir` is unset, serialize the `ScanResult`
  via `result.model_dump_json().encode()` and pass bytes. **Threading
  FEAT-160**: respect `CloudSploitConfig.config_file` and the per-call `config`
  arg added in that merge.
- **Depends on**: Module 5.

### Module 7: SecurityReportToolkit (LLM-facing read side)
- **Path**: `parrot_tools/security/report_toolkit.py`
- **Responsibility**: The toolkit defined in §2 New Public Interfaces.
  Inherits `AbstractToolkit`; tools are auto-discovered.
  - `find_security_report`: builds a `ReportFilter` from kwargs + the
    `max_age_days` window, queries the store, returns metadata only
    (severity summary + embedded `top_findings`).
  - `read_security_report`: by section. `summary` returns the ref;
    other sections fetch content and dispatch to the parser's
    `extract_section`.
  - `search_findings` (v1 limit): SQL ILIKE against `top_findings::jsonb`
    plus optional severity/since filters. Tool docstring documents the
    "top-10 per report" limitation.
  - `list_available_frameworks`: diagnostic — `SELECT DISTINCT framework`.
- **Depends on**: Modules 1, 3, 4.

### Module 8: Summarizers
- **Path**: `parrot_tools/security/summarizer.py`
- **Responsibility**: `WeeklySecuritySummarizer.build(scans, framework, previous_summary)`
  and `MonthlySecuritySummarizer.build(weekly_summaries, framework, previous_summary)`.
  Diff math is deterministic Python (set ops on `finding_id`); the LLM
  (passed in via `llm_client=self.llm`) is invoked **only** for
  `WeeklySummary.executive_paragraph` using `ThinkingConfig(include_thoughts=False)`.
- **Depends on**: Modules 1, 3.

### Module 9: SecurityAgent wiring + navconfig slot
- **Path A**: `parrot/conf.py` — add `AWS_CREDENTIALS['security']` slot
  derived from the existing `aws_security` INI section (keys: `aws_key`,
  `aws_secret`, `region_name`). Reuses the existing `AWS_CREDENTIALS`
  registration pattern. Resolved U2.
- **Path B**: `agents/security.py` — **gitignored**, so changes are
  described in prose for ops/implementer coordination (resolved U1).
  Concrete edits (in order):
  1. **Remove or land the stub** at L445-471 (`consolidate_weekly_security_summary`)
     so the file imports cleanly after Modules 1-3 land. Recommended
     ordering: this task runs FIRST, removes the broken stub, and the
     consolidator is reintroduced in step 4 below.
  2. **`__init__`**: construct
     ```
     self._file_manager = FileManagerFactory.create(
         manager_type='s3',
         bucket_name=config.get('SECURITY_REPORT_BUCKET', fallback=config.S3_ARTIFACT_BUCKET),
         prefix='security-reports/',
         aws_id='security',
     )
     self._report_store = PostgresS3SecurityReportStore(

…(truncated)…
