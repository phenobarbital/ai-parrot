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
         dsn=config.get('SECURITY_REPORT_PG_DSN', fallback=config.default_dsn),
         file_manager=self._file_manager,
     )
     ```
     plus the weekly/monthly summarizers wired with `llm_client=self.llm`.
  3. **`agent_tools()`**: pass `file_manager=self._file_manager,
     report_store=self._report_store` to each producer toolkit constructor;
     add `SecurityReportToolkit(...)` first in the returned list (semantic
     hint for the LLM).
  4. **BACKSTORY**: align/replace the L56-63 freshness-policy block with
     a verbatim version referencing the real `SecurityReportToolkit` tool
     names. The block content is included in §7 Patterns to Follow for
     traceability.
  5. **Schedules**: add `@schedule(schedule_type=ScheduleType.WEEKLY,
     day_of_week=0, hour=6, minute=0)` for `consolidate_weekly_security_summary`
     and `@schedule(schedule_type=ScheduleType.MONTHLY, day=1, hour=6,
     minute=0)` for `consolidate_monthly_security_summary`. Both methods
     iterate the framework set (`HIPAA`, `PCI`, `SOC2`), call the
     summarizer, then `save_report` a `weekly_summary` / `monthly_summary`
     `ReportRef`.
  6. **Existing scheduled tasks**: require NO signature change — once
     producer toolkits have the mixin wired, those tasks auto-populate
     the catalog as a side effect.
- **Depends on**: Modules 1-8 + the FEAT-160 CloudSploitConfig surface.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_report_ref_roundtrip` | Module 1 | `ReportRef.model_validate(ref.model_dump())` is identity; tz-aware UTC preserved. |
| `test_severity_breakdown_total` | Module 1 | `total` property = sum of fields; zero by default. |
| `test_schema_idempotent` | Module 2 | Run `schema.sql` twice against a test DB; second run succeeds with no error. |
| `test_store_save_and_get` | Module 3 | `save_report` → `get(report_id)` returns the same `ReportRef`. Content fetchable via `fetch_content`. |
| `test_store_query_no_implicit_since` | Module 3 | `query(ReportFilter(limit=10))` with no `since` returns reports older than 30 days too. **Hard requirement** — the store must not apply default age filtering. |
| `test_store_query_scope_match` | Module 3 | `scope_match={"account_id": "X"}` returns only matching rows. |
| `test_parser_trivy_determinism` | Module 4 | Same input bytes → same `SeverityBreakdown` and `top_findings` across runs. |
| `test_parser_cloudsploit_determinism` | Module 4 | Same as above, for CloudSploit JSON. |
| `test_parser_extract_section_critical` | Module 4 | `extract_section(content, 'critical')` returns only critical findings. |
| `test_mixin_no_op_when_deps_none` | Module 5 | With `file_manager=None` or `report_store=None`, `_persist_report` returns `None` and does not raise. |
| `test_mixin_kwargs_pop` | Module 5 | Producer toolkit constructor with `file_manager=fm, report_store=rs, other_kw=v` forwards only `other_kw=v` to `super().__init__`. |
| `test_cloudsploit_persists_after_scan` | Module 6 | `await toolkit.run_compliance_scan('HIPAA')` calls `_persist_report` exactly once; ref appears in subsequent `store.query`. |
| `test_trivy_temp_file_lifecycle` | Module 6 | `trivy_scan_filesystem` writes a temp file, hands it to the mixin, and deletes it after persist (even on persist failure — finally clause). |
| `test_find_returns_metadata_only` | Module 7 | `find_security_report(...)` does NOT call `fetch_content`; response size dominated by embedded `top_findings`. |
| `test_read_summary_no_fetch` | Module 7 | `read_security_report(rid, 'summary')` does NOT call `fetch_content`. |
| `test_search_findings_v1_top10_limitation` | Module 7 | Searching for a known finding NOT in any `top_findings` returns empty (documents the v1 limit). |
| `test_weekly_summarizer_deterministic_diff` | Module 8 | Same input scans + previous summary → same `new_findings`/`resolved_findings`/`persistent_findings` sets across runs (LLM call is mocked). |
| `test_weekly_summarizer_llm_call_only_for_executive` | Module 8 | The mocked LLM is invoked exactly once and only for the `executive_paragraph` field. |

### Integration Tests

| Test | Description |
|---|---|
| `test_freshness_policy_avoids_rescan` | Seed a recent HIPAA `scan` ref in the test store; invoke `SecurityAgent` with *"give me the HIPAA report"*; verify the tool-call sequence is `find_security_report → read_security_report` (no `run_compliance_scan`). |
| `test_explicit_fresh_triggers_scan` | Invoke `SecurityAgent` with *"run a fresh HIPAA scan now"*; verify `run_compliance_scan` is called and the resulting ref is findable in the same session. |
| `test_weekly_consolidator_end_to_end` | Seed 7 days of synthetic scans across HIPAA / PCI / SOC2; run `consolidate_weekly_security_summary`; verify a `weekly_summary` ref exists per framework with non-empty `persistent_findings` if findings span the window. |
| `test_monthly_consolidator_consumes_weeklies` | Seed 4 `weekly_summary` refs per framework; run `consolidate_monthly_security_summary`; verify a `monthly_summary` ref per framework that links via `scope.source_report_ids`. |
| `test_catalog_cross_session_visibility` | Persist a report in session A; in a new session B, `find_security_report` returns it (Postgres-backed, not in-process). |

### Test Data / Fixtures

```python
# tests/storage/security_reports/conftest.py
@pytest.fixture
def synthetic_cloudsploit_json() -> bytes:
    """Minimal valid CloudSploit JSON with 2 critical, 3 high findings."""

@pytest.fixture
def synthetic_trivy_json() -> bytes:
    """Minimal valid Trivy filesystem-scan JSON with 1 critical, 1 high."""

@pytest.fixture
async def report_store(tmp_path, postgres_test_dsn):
    fm = LocalFileManager(base_path=tmp_path)
    store = PostgresS3SecurityReportStore(dsn=postgres_test_dsn, file_manager=fm)
    await store.bootstrap_schema()
    yield store
    # Cleanup truncates security_reports.

@pytest.fixture
def seven_days_of_scans(report_store, synthetic_cloudsploit_json) -> list[ReportRef]:
    """Seed 7 daily scans across HIPAA/PCI/SOC2; returns the saved refs."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All unit tests pass (`pytest tests/storage/security_reports/ tests/security/ -v`)
- [ ] All integration tests pass (`pytest tests/integration/security/ -v`)
- [ ] Existing `@schedule`d tasks in `SecurityAgent` produce `ReportRef`s automatically (no signature change; persistence is a side-effect via the mixin).
- [ ] Live test against `SecurityAgent`: ask *"give me the HIPAA report"* → tool sequence `find_security_report` → `read_security_report`, no scan triggered, response in <5 s when a same-day report exists.
- [ ] Live test: ask *"run a fresh HIPAA scan now"* → tool sequence `run_compliance_scan` → ref appears in subsequent `find_security_report` calls within the session.
- [ ] Weekly summarizer integration test passes: seed 7 days of synthetic scans, run `consolidate_weekly_security_summary`, verify a `weekly_summary` ref exists per framework with non-zero `persistent_findings` when synthetic findings span the window.
- [ ] Monthly summarizer integration test passes: seed 4 `weekly_summary` refs per framework, run `consolidate_monthly_security_summary`, verify a `monthly_summary` ref per framework with `scope.source_report_ids` referencing the 4 weeklies.
- [ ] Parser determinism: same input bytes → identical `SeverityBreakdown` and `top_findings` across runs.
- [ ] Store: `query(ReportFilter(limit=...))` with no `since` returns reports older than 30 days too (the store applies no implicit age filter).
- [ ] Migration: legacy reports under `/tmp/security-reports/` are NOT migrated (v1 starts fresh).
- [ ] `agents/security.py` imports cleanly after the broken stub at L445-471 is removed (or replaced by the new consolidator that depends on shipped modules).
- [ ] `parrot/conf.py` exposes `AWS_CREDENTIALS['security']` derived from the `aws_security` INI section, and `FileManagerFactory.create(manager_type='s3', aws_id='security', ...)` resolves at runtime.
- [ ] BACKSTORY's freshness-policy block (currently at L56-63 in `agents/security.py`) names the real `SecurityReportToolkit` tool surface — `find_security_report`, `read_security_report`, `search_findings`, `list_available_frameworks` — and contains no references to nonexistent tools.
- [ ] No breaking changes to existing public API: scanner toolkit return shapes (`ScanResult`, `ConsolidatedReport`) preserved; existing `@schedule`d tasks return the same `dict` shape they return today.
- [ ] Docs: `parrot/storage/security_reports/README.md` (≤2 pages) with the three-layer diagram, key naming convention, and the freshness-policy block as a quotable reference.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase
> as of `dev` HEAD `ed740bec` (proposal commit, 2026-05-12). Implementation
> agents MUST NOT reference imports, attributes, or methods not listed here
> without first verifying via `grep` or `read`. Every entry is grounded in a
> finding under `sdd/state/FEAT-162/findings/`.

### Verified Imports

```python
# Storage / file
from parrot.tools.file.tool import FileManagerFactory                       # parrot/tools/file/tool.py [F003]
from parrot.interfaces.file import FileManagerInterface                     # re-export from navigator.utils.file [F002, F004]
# (Concrete impls — S3FileManager, LocalFileManager — accessed via the factory; no direct
#  import is part of this FEAT's surface.)

# Toolkit base
from parrot.tools.toolkit import AbstractToolkit                            # parrot/tools/toolkit.py:191 [F006, F007]
from parrot.tools.abstract import AbstractTool, ToolResult, AbstractToolArgsSchema  # parrot/tools/abstract.py [F006]

# Scheduler
from parrot.scheduler import schedule, ScheduleType                         # parrot/scheduler/__init__.py:41-96 [F008]

# Registry
from parrot.registry import register_agent                                  # parrot/registry/registry.py:1130-1156 [F009]

# Bot base (for typing the summarizer's llm_client param)
from parrot.bots.abstract import AbstractBot                                # parrot/bots/abstract.py [F021]

# Postgres driver (project convention)
from asyncdb import AsyncDB                                                 # 30 usages across parrot/; pattern at parrot/bots/database/toolkits/base.py:344-351 [F015]

# navconfig
from parrot.conf import (
    config,
    AWS_ACCESS_KEY,        # parrot/conf.py [F014]
    AWS_SECRET_KEY,        # parrot/conf.py [F014]
    AWS_REGION_NAME,       # parrot/conf.py:418 [F014]
    S3_ARTIFACT_BUCKET,    # parrot/conf.py:475 [F014]
    default_dsn,           # parrot/conf.py [F014]
    AWS_CREDENTIALS,       # parrot/conf.py [F014]
)
# NEW (this FEAT): AWS_CREDENTIALS['security'] slot derived from the
# `aws_security` INI section (keys aws_key, aws_secret, region_name).

# Existing security models (avoid collision with new SeverityBreakdown)
from parrot_tools.security.models import SeverityLevel, ConsolidatedReport  # parrot_tools/security/models.py [F012, F013]

# Pydantic v2 (project pin: 2.12.5)                                          # pyproject.toml:47 [F018]
from pydantic import BaseModel, Field
```

### Existing Class Signatures (verbatim, with line numbers)

```python
# parrot/tools/toolkit.py
class AbstractToolkit:                                                # line 191
    # Auto-discovers async public methods as tools.
    # Lifecycle methods excluded by name (line 368-403):
    #   get_tools, get_tools_filtered, get_tools_sync, get_tool,
    #   list_tool_names, start, stop, cleanup,
    #   plus an `exclude_tools` tuple consumed by the discovery walk.
    def __init__(self, **kwargs): ...
    def get_tools(self) -> list[AbstractTool]: ...
    # [F007]

# parrot/interfaces/file/ (re-export from navigator.utils.file.abstract)
class FileManagerInterface(ABC):                                      # F004 cites .venv .../abstract.py:36-165
    @abstractmethod
    async def list_files(self, path: str = "", pattern: str = "*") -> List[FileMetadata]: ...
    @abstractmethod
    async def get_file_url(self, path: str, expiry: int = 3600) -> str: ...
    @abstractmethod
    async def upload_file(self, source: Union[BinaryIO, Path], destination: str) -> FileMetadata: ...
    @abstractmethod
    async def download_file(self, source: str, destination: Union[Path, BinaryIO]) -> Path: ...
    @abstractmethod
    async def copy_file(self, source: str, destination: str) -> FileMetadata: ...
    @abstractmethod
    async def delete_file(self, path: str) -> bool: ...
    @abstractmethod
    async def exists(self, path: str) -> bool: ...
    @abstractmethod
    async def get_file_metadata(self, path: str) -> FileMetadata: ...
    @abstractmethod
    async def create_file(self, path: str, content: bytes) -> bool: ...

# parrot/tools/file/tool.py
class FileManagerFactory:                                              # [F003]
    @staticmethod
    def create(*, manager_type: str, **kwargs) -> FileManagerInterface: ...
    # manager_type ∈ {"s3", "fs"/"local", "gcs", "temp"}
    # S3FileManager kwargs: bucket_name, prefix, aws_id, credentials (NOT aws_config)
    # [F003, F005]

# parrot/scheduler/__init__.py
class ScheduleType(Enum):                                              # line 41+ [F008]
    DAILY = ...
    WEEKLY = ...
    MONTHLY = ...
    # (other members)

def schedule(*, schedule_type: ScheduleType, **kwargs):                # line 41-96 [F008]
    # **kwargs is passed through verbatim to the scheduler:
    # day_of_week (WEEKLY), day (MONTHLY), hour, minute, etc.

# parrot/registry/registry.py
def register_agent(name: str, **kwargs):                               # line 1130-1156 [F009]
    # Decorator factory for AbstractBot subclasses.
    # Accepts at_startup=True via kwargs.

# parrot/bots/abstract.py
class AbstractBot:                                                     # [F021]
    llm: Any                                                           # line 922-928
    # Set to a GoogleGenAIClient (or other) after super().__init__()
    # in Agent.__init__ (agents/agent.py:127-131).

# packages/ai-parrot-tools/src/parrot_tools/cloudsploit/toolkit.py
class CloudSploitToolkit(AbstractToolkit):                             # [F011]
    def __init__(self, config: Optional[CloudSploitConfig] = None, **kwargs):  # line 23-37
        super().__init__(**kwargs)
        self.config = config or CloudSploitConfig()
        # ...

    async def run_scan(
        self, plugins=None, ignore_ok=False, suppress=None, config=None,
    ) -> ScanResult:                                                   # line 71-119
        # When self.config.results_dir is set:
        #   writes JSON to {results_dir}/scan_{YYYYMMDD_HHMMSS}.json
        ...

    async def run_compliance_scan(
        self, framework: str, ignore_ok: bool = True, config=None,
    ) -> ScanResult:                                                   # line 121-163
        ...

    # FEAT-160 (merged 2026-05-12) added:
    #   CloudSploitConfig.config_file: Optional[str]
    #   per-call `config` arg on run_scan / run_compliance_scan

# packages/ai-parrot-tools/src/parrot_tools/security/<container>.py
class ContainerSecurityToolkit(AbstractToolkit):                       # [F012, F013, F023]
    # All public methods prefixed trivy_*:
    async def trivy_scan_filesystem(self, ...) -> ScanResult: ...      # NOT scan_filesystem
    async def trivy_scan_image(self, ...) -> ScanResult: ...
    # NO results_dir / report_output_dir attribute — Trivy output is captured from STDOUT.

# packages/ai-parrot-tools/src/parrot_tools/security/<compliance>.py
class ComplianceReportToolkit(AbstractToolkit):                        # [F012]
    # Orchestrates Prowler + Trivy + Checkov.
    # Public scan methods return ConsolidatedReport (Pydantic), not dict.

# parrot/clients/google/client.py
# ThinkingConfig usage precedent (line 1957-1977) [F022]
# When invoking Gemini with structured output for a Pydantic schema:
#   thinking_config = ThinkingConfig(include_thoughts=False)
#   ...
```

### Configuration References (navconfig)

| Key / Section | Source | How it's read | Notes |
|---|---|---|---|
| `S3_ARTIFACT_BUCKET` | `parrot/conf.py:475` | `from parrot.conf import S3_ARTIFACT_BUCKET` | Default S3 bucket; the new `SECURITY_REPORT_BUCKET` env var falls back to this. |
| `AWS_REGION_NAME` | `parrot/conf.py:418` | `from parrot.conf import AWS_REGION_NAME` | Default AWS region. |
| `AWS_ACCESS_KEY` / `AWS_SECRET_KEY` | `parrot/conf.py` | `from parrot.conf import ...` | Default app AWS creds. |
| `default_dsn` | `parrot/conf.py` | `from parrot.conf import default_dsn` | **NOT** `DEFAULT_PG_DSN`. Default Postgres DSN. |
| `AWS_CREDENTIALS` | `parrot/conf.py` | dict keyed by `aws_id` for `S3FileManager(aws_id=...)` | This FEAT adds a `'security'` key derived from the `aws_security` INI section. |
| `aws_security` (INI section) | navconfig INI | `config.get('aws_security', '<key>')` | Existing section holding `aws_key`, `aws_secret`, `region_name` for the security S3 bucket. The new `AWS_CREDENTIALS['security']` slot populates from these. |
| `SECURITY_REPORT_BUCKET` | env (new) | `config.get('SECURITY_REPORT_BUCKET', fallback=config.S3_ARTIFACT_BUCKET)` | Per-env override. |
| `SECURITY_REPORT_S3_PREFIX` | env (new) | `config.get('SECURITY_REPORT_S3_PREFIX', fallback='security-reports/')` | Allows multi-env isolation in the same bucket. |
| `SECURITY_REPORT_PG_DSN` | env (new) | `config.get('SECURITY_REPORT_PG_DSN', fallback=config.default_dsn)` | Catalog database DSN. |
| `SECURITY_REPORT_DEFAULT_VISIBILITY_DAYS` | env (new) | `config.get('SECURITY_REPORT_DEFAULT_VISIBILITY_DAYS', fallback=30)` | Default `max_age_days` for `find_security_report`. |
| `SECURITY_REPORT_LLM_MODEL` | env (new) | `config.get('SECURITY_REPORT_LLM_MODEL', fallback=<agent default>)` | Override for the summarizer (e.g., Flash for cheaper). |

### Integration Points (new code → existing)

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `PostgresS3SecurityReportStore` | `FileManagerInterface.upload_file` | method call | F004 |
| `PostgresS3SecurityReportStore` | `FileManagerInterface.download_file` / `exists` / `get_file_url` | method call | F004 |
| `PostgresS3SecurityReportStore` | `asyncdb.AsyncDB(driver='pg', dsn=...)` | constructor | `parrot/bots/database/toolkits/base.py:344-351` [F015] |
| `ReportPersistenceMixin` (in scanner toolkits) | `AbstractToolkit.__init__(**kwargs)` | `super().__init__(**kwargs)` after `.pop()` | `parrot/tools/toolkit.py:191` [F006, F007] |
| `SecurityReportToolkit` | `AbstractToolkit` (auto-discovery) | inheritance | `parrot/tools/toolkit.py:368-403` [F007] |
| `WeeklySecuritySummarizer` | `GoogleGenAIClient` + `ThinkingConfig(include_thoughts=False)` | constructor + per-call kwarg | `parrot/clients/google/client.py:1957-1977` [F022] |
| `SecurityAgent` (new consolidators) | `@schedule(schedule_type=ScheduleType.WEEKLY, day_of_week=0, hour=6, minute=0)` | decorator | `parrot/scheduler/__init__.py:41-96` [F008] |
| `SecurityAgent.__init__` | `FileManagerFactory.create(manager_type='s3', aws_id='security', ...)` | call | `parrot/tools/file/tool.py` [F003] |
| `parrot/conf.py` change | existing `AWS_CREDENTIALS` dict | new key `'security'` | `parrot/conf.py` [F014] |
| New schema | `parrot/security/security_events.sql` (style precedent) | layout convention | [F016] |

### Does NOT Exist (Anti-Hallucination)

The brainstorm referenced several plausible-sounding paths and symbols that
**do not exist** in the codebase as of `ed740bec`. Implementation MUST NOT
reference these:

- ~~`parrot.tools.file.s3.S3FileManager`~~ — `parrot/tools/file/s3.py` may exist
  as a thin shim, but the canonical path is `parrot/interfaces/file/` (re-export
  of `navigator.utils.file.s3`). Use `FileManagerFactory.create(manager_type='s3', ...)`
  rather than importing the concrete class. [F002, F005]
- ~~`parrot.tools.file.local.LocalFileManager`~~ — same as above; use the factory.
- ~~`parrot.tools.file.abstract.FileManagerInterface`~~ — actual canonical home is
  `parrot/interfaces/file/` (re-export). [F004]
- ~~`FileManagerInterface.upload(...)`~~ — real method is `upload_file(source, destination)`. [F004]
- ~~`FileManagerInterface.download(...)`~~ — real method is `download_file(source, destination)`. [F004]
- ~~`FileManagerInterface.get_url(...)`~~ — real method is `get_file_url(path, expiry=3600)`. [F004]
- ~~`FileManagerFactory.create(manager_type=..., aws_config={...})`~~ — the factory has
  **no** `aws_config` kwarg. Use `aws_id='security'` (keyed into `AWS_CREDENTIALS`)
  or a `credentials={'aws_key': ..., 'aws_secret': ..., 'region_name': ...}` dict. [F003, F005]
- ~~`parrot.tools.abstract.AbstractToolkit`~~ — `parrot/tools/abstract.py` exports
  `AbstractTool`, `ToolResult`, `AbstractToolArgsSchema` only. The toolkit base
  lives at `parrot/tools/toolkit.py:191`. [F006]
- ~~`CloudSploitToolkit.run_cloudsploit_scan(compliance, output_format)`~~ — the
  real public methods are `run_scan(plugins, ignore_ok, suppress, config) -> ScanResult`
  and `run_compliance_scan(framework, ignore_ok=True, config=None) -> ScanResult`.
  There is **no** `output_format` kwarg on scan; format conversion lives in a
  separate `generate_report(format=...)` method. [F011]
- ~~`ContainerSecurityToolkit.scan_filesystem`~~ — real name is `trivy_scan_filesystem`
  (all public methods prefixed `trivy_`). [F012]
- ~~`ContainerSecurityToolkit.results_dir` / `report_output_dir`~~ — does not exist.
  Trivy output comes from stdout. This FEAT resolves the gap by writing stdout to
  a temp file inside the toolkit (resolved U3). [F012, F023]
- ~~Scanner methods return `dict`~~ — they return Pydantic models: `ScanResult`
  (CloudSploit, ContainerSecurity) or `ConsolidatedReport` (ComplianceReport).
  The mixin must serialize via `result.model_dump_json().encode()` for the
  bytes branch. [F011, F012]
- ~~`config.AWS_KEY` / `config.AWS_SECRET`~~ — real names are `AWS_ACCESS_KEY` /
  `AWS_SECRET_KEY`. [F014]
- ~~`config.DEFAULT_PG_DSN`~~ — real name is `default_dsn` (lower-case, imported
  from navconfig). [F014]
- ~~`config.aws_security.<key>`~~ — `aws_security` is an **INI section**, not a
  parrot.conf attribute. Read via `config.get('aws_security', '<key>')`. This
  FEAT adds an `AWS_CREDENTIALS['security']` slot derived from those keys so
  callers can use `aws_id='security'`. [F014]
- ~~Any Alembic / migrations directory / migration framework in `parrot/storage/`~~
  — none exists. New schema lands as a bare `.sql` file, applied out-of-band.
  Precedent: `parrot/security/security_events.sql`. [F016]
- ~~`raw asyncpg.create_pool(...)` as the primary connection pattern~~ — 1 usage
  vs 30 `asyncdb` usages. New code MUST use `asyncdb.AsyncDB(driver='pg', dsn=...)`. [F015]

### Recent Activity Context (drift since brainstorm)

- **2026-05-12** — FEAT-160 (cloudsploit-config-support) merged today (6 commits,
  TASK-1079..1083 + fix at `a9e3fabd`). Added `CloudSploitConfig.config_file`
  and per-call `config` arg on `run_scan`/`run_compliance_scan`. The brainstorm
  pre-dates this; spec wires the new field where `SecurityAgent` constructs the
  toolkit. [F019]
- **2026-05-12** — FEAT-161 (AWS Inspector Toolkit) merged today. Tangential to
  this FEAT — surfaces another scanner that could later join the catalog
  (deferred). [F019]
- **2026-05-11** — Local fix to Trivy executor for the security agent
  (`d866f7af`). The `agents/security.py` file is gitignored; possible local
  collisions with this FEAT's wiring task. [F019]
- **2026-04-25/27** — `fileinterface-migration` series (TASK-851/852/869).
  Established `parrot/interfaces/file/` re-exports from `navigator.utils.file`.
  The brainstorm's `parrot/tools/file/*` paths are stale relative to this. [F002, F020]
- **2026-05-05** — navigator-api version bump; final stabilization of the
  FileManager surface. No drift since. [F020]

### Existing Broken Stub (must address)

`agents/security.py:445-471` contains an in-progress
`consolidate_weekly_security_summary` stub that references symbols introduced
*by this FEAT* (`self._report_store`, `ReportFilter`, `self._build_weekly_summary`).
This file is gitignored. The implementation must, **in order**:

1. Remove the stub (so the file imports cleanly after Module 1 lands).
2. Ship Modules 1-8.
3. Re-introduce the consolidator in Module 9 referencing the now-shipped symbols.

The BACKSTORY block at lines 56-63 in the same file references
`find_security_report` even though no such tool exists today. Module 9 step
**4** must align the block with the real `SecurityReportToolkit` tool surface
or — if Modules 1-8 are not yet landed — temporarily soften the block during
the rollout window.

[F001]

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **`asyncdb.AsyncDB(driver='pg', dsn=...)`** — Postgres async convention.
  Match the call pattern at `parrot/bots/database/toolkits/base.py:344-351`
  for the store's connection initialization. [F015]
- **Bare `.sql` schema co-located with the module** — match
  `parrot/security/security_events.sql`. Apply via `bootstrap_schema()`
  (idempotent) or out-of-band by ops. No Alembic. [F016]
- **`ThinkingConfig(include_thoughts=False)` for structured Gemini calls**
  — match `parrot/clients/google/client.py:1957-1977`. [F022]
- **`AbstractToolkit` auto-discovery** — every async public method on
  `SecurityReportToolkit` becomes a tool exposed to the LLM. Use the
  lifecycle exclusion list at `parrot/tools/toolkit.py:368-403` as the
  reference for what NOT to expose; if any helper is added that should
  not become a tool, prefix it with `_`. [F007]
- **Mixin `.pop()` pattern** — every producer toolkit constructor must
  pop `file_manager` and `report_store` from `**kwargs` BEFORE
  `super().__init__(**kwargs)`. Failing to do so breaks the
  `AbstractToolkit` parent contract. [F012]
- **Pydantic v2 idioms** — `model_dump(mode='json')` for API surfaces,
  `model_dump_json()` for serialization to disk/network, `model_validate`
  for inputs. No v1 helpers. [F018]
- **Logger pattern** — `self.logger = logging.getLogger(__name__)` in
  every new class; `self.logger.info / debug / warning / error` — never `print`.

### BACKSTORY Freshness-Policy Block (verbatim, for Module 9 step 4)

```text
=== Report Freshness Policy (MANDATORY) ===

Before running ANY expensive scanner tool (run_scan, run_compliance_scan,
the ComplianceReportToolkit scan methods, trivy_scan_filesystem on the
container toolkit), you MUST first call `find_security_report` with the
relevant filters (scanner, framework, scope_match for account_id/region/target).

Only execute a fresh scan when one of these is true:
  (a) find_security_report returned an empty list within the 30-day window,
  (b) the user explicitly asked for "fresh", "re-scan", "latest", "now",
  (c) find_security_report failed with an error.

When a recent report exists:
  1. Surface its severity_summary and produced_at from the ref itself
     (no fetch needed — it's embedded).
  2. If the user wants detail, call read_security_report with the smallest
     section that answers the question ('critical' for triage, 'high'
     for follow-up, 'executive' for stakeholder summaries, 'full' only
     when explicitly requested).
  3. Always cite the report's produced_at timestamp so the user knows
     the data age.

For trend questions spanning >30 days, prefer report_kind="weekly_summary"
or "monthly_summary" over raw scans. For cross-report finding search,
use search_findings (v1 only matches against the embedded top-10 findings
per report).
```

### Known Risks / Gotchas

- **R1 — Gitignored live target.** `agents/security.py` cannot be reviewed
  via PR diff. **Mitigation (resolved U1)**: spec describes all wiring in
  §3 Module 9 in prose; implementer + ops coordinate via the spec; no
  tracked template is added in this FEAT. [F001]
- **R2 — Broken stub blocks import.** Existing
  `consolidate_weekly_security_summary` at `agents/security.py:445-471`
  references yet-to-exist symbols. **Mitigation**: Module 9 step 1 removes
  the stub FIRST; the consolidator is reintroduced in step 5 only after
  Modules 1-8 are in place. [F001]
- **R3 — Trivy stdout vs mixin's `bytes | Path` signature.** **Mitigation
  (resolved U3)**: `ContainerSecurityToolkit` writes Trivy stdout to a temp
  file inside the toolkit, hands the `Path` to the mixin, deletes after
  persist (in a `try / finally`). Mixin signature unchanged. [F012, F023]
- **R4 — FEAT-160 (just merged today) changed `CloudSploitConfig`.**
  **Mitigation**: Module 9 step 2 threads `CloudSploitConfig.config_file`
  when constructing the toolkit. [F019]
- **R5 — BACKSTORY references vapor.** The live prompt at
  `agents/security.py:56-63` already mentions `find_security_report`.
  **Mitigation**: Module 9 step 4 aligns the BACKSTORY with the real
  `SecurityReportToolkit` tool names; if Modules 1-8 haven't landed yet
  when the agent is restarted, temporarily soften the block until they do. [F001]
- **R6 — Enum collision risk.** Existing
  `parrot_tools.security.models.SeverityLevel` is a *level* enum; the
  new `SeverityBreakdown` is a *count container*. **Mitigation**: distinct
  names; document the difference in `parrot/storage/security_reports/README.md`. [F013]
- **R7 — S3 cost grows monotonically** because the spec never deletes
  reports (compliance retention). **Mitigation**: follow-up FEAT for S3
  lifecycle tiering (Standard → IA → Glacier) per
  `.claude/rules/aws-cost-optimization.md` — out of scope here.
- **R8 — Postgres orphans on S3-success/Postgres-failure.** Per `save_report`,
  S3 upload runs first; if metadata insert fails, the S3 object is orphaned.
  **Mitigation**: acceptable for v1. A reconcile job is out of scope; the
  cost is bounded by retry idempotency in callers.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `pydantic` | `==2.12.5` (existing pin) | Data models. [F018] |
| `asyncdb` | (existing) | Postgres async driver. [F015] |
| `navigator-api` / `navigator.utils.file` | (existing) | FileManager surface (re-exported by `parrot/interfaces/file/`). [F002, F004] |
| `google-genai` | (existing) | `ThinkingConfig(include_thoughts=False)` for the summarizer. [F022] |

No new third-party dependencies are introduced by this FEAT.

---

## 8. Open Questions

### Resolved (during brainstorm + proposal phases — carried forward)

- [x] **OQ#1 — Postgres driver: `asyncpg` or `asyncdb`?**
  *Resolved by codebase observation* (proposal F015): use `asyncdb` —
  30 usages across `parrot/` vs 1 raw asyncpg call. The store uses
  `from asyncdb import AsyncDB` with `driver='pg', dsn=...`, matching
  the pattern at `parrot/bots/database/toolkits/base.py:344-351`.

- [x] **OQ#2 — Schema migrations: which pattern does the project use?**
  *Resolved by codebase observation* (proposal F016): no migration
  framework exists (no Alembic, no migrations dir). The new schema lands
  as a bare `.sql` with `CREATE TABLE IF NOT EXISTS` + `CREATE INDEX`,
  applied out-of-band by ops. Precedent: `parrot/security/security_events.sql`.
  The store additionally exposes a `bootstrap_schema()` convenience.

- [x] **U1 — Traceability of the gitignored `agents/security.py`**
  *Resolved in proposal Q&A*: keep `agents/security.py` untracked. The
  spec describes the wiring in §3 Module 9 prose; the implementer and
  ops coordinate via the spec. No new tracked template file in this FEAT.

- [x] **U2 — AWS credential resolution for the catalog's S3 bucket**
  *Resolved in proposal Q&A*: add `AWS_CREDENTIALS['security']` slot in
  `parrot/conf.py` derived from the `aws_security` INI section.
  `SecurityAgent` calls `FileManagerFactory.create(manager_type='s3',
  aws_id='security', ...)`.

- [x] **U3 — Trivy report content path into the mixin**
  *Resolved in proposal Q&A*: `ContainerSecurityToolkit` writes Trivy
  stdout to a temp file inside the toolkit; the mixin's content
  signature stays `bytes | Path` and Trivy always uses the `Path`
  branch. The toolkit owns the tmp-file lifecycle (write, hand to
  mixin, delete after persist).

- [x] **U4 — `search_findings` v1 scope**
  *Resolved in proposal Q&A*: accept v1 limitation — SQL ILIKE + JSONB
  on `top_findings` is the v1 query path. Documented in the tool
  description and §1 Non-Goals. Per-finding indexing + PgVector
  deferred to a follow-up FEAT.

### Unresolved (carried from brainstorm — non-blocking for spec)

- [x] **Multi-provider scope: does v1 need a `provider` axis in
  summarizers / consolidators, or is single-AWS sufficient?** — *Owner: tbd*.
  The `scope` JSONB already supports multi-account, but the consolidators
  currently iterate frameworks only. *Plausible answers*: a) AWS-only v1,
  defer; b) accept multi-account same-provider; c) full multi-provider
  from day 1. Decidable at implementation time without re-spec.: c) full multi-provider from day 1.

- [x] **Time-zone rendering in nav-admin / front-end** — *Owner: tbd*.
  All `produced_at` is UTC in the store; whether the front-end renders
  in user-local tz is a downstream UI question, not a catalog concern.
  Likely follow-up FEAT alongside the catalog UI.: UTC.

### Implementation-time clarifications (may surface during /sdd-task)

- [ ] **Exact filenames for compliance and container toolkit modules**
  inside `packages/ai-parrot-tools/src/parrot_tools/security/` — the
  proposal F012/F013 confirm the package layout but the implementer
  should `ls` the directory in their worktree to anchor the exact
  filenames for Module 6 patches.

---

## Worktree Strategy

**Isolation unit: per-spec.**

All tasks for FEAT-162 run sequentially in a single worktree, because:

1. **Strong dependency chain.** Modules 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9
   are each consumed by the next; Module 6 in particular requires
   Modules 1-5 to be in place before the mixin can be wired into producers.
2. **Live test target is shared.** `agents/security.py` (gitignored) is
   the single integration target — Module 9 finishes only after the rest
   land. Parallelizing within the same worktree provides no benefit.
3. **Test fixtures cross modules.** The integration tests (§4) need
   Modules 1, 3, and 7 simultaneously seeded; a single worktree gives a
   coherent state at any point in time.

**Worktree creation** (after `/sdd-task` produces the task index):

```bash
git checkout dev
git worktree add -b feat-162-security-report-catalog \
  .claude/worktrees/feat-162-security-report-catalog HEAD
```

**Cross-feature dependencies** (must be merged before FEAT-162 worktree
starts):

- FEAT-160 (cloudsploit-config-support) — **already merged** on
  2026-05-12. The spec relies on `CloudSploitConfig.config_file` and the
  per-call `config` arg landed in that merge.
- FEAT-103 (`ArtifactStore`) — **already merged**. Cited as a peer
  abstraction; no behavioral dependency.

**Follow-up FEATs** (out of scope here, queued for later):

- FEAT-NNN: PgVector findings index — enables semantic `search_findings`.
- FEAT-NNN: S3 lifecycle policy (Standard → IA → Glacier).
- FEAT-NNN: nav-admin catalog UI (SvelteKit 5 + daisyUI).
- FEAT-NNN: Drift comparison tool (`compare_reports(report_id_a, report_id_b)`
  producing a `drift_comparison` `ReportRef`).
- FEAT-NNN: Multi-tenant isolation (`tenant_id` column + `permission_context`).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-12 | Jesus Lara | Initial draft. Codebase contract carried forward from `sdd/proposals/security-report-catalog.proposal.md` (research commit `ed740bec`); brainstorm-resolved + proposal-resolved open questions echoed into §8. |
