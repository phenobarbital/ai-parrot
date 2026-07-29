---
type: Wiki Overview
title: FEAT-NNN — Security Report Catalog & Persistent Operational History
id: doc:sdd-proposals-security-report-catalog-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The `SecurityAgent` (`agents/security.py`) runs a suite of scanners — CloudSploit,
  Prowler, Trivy, Checkov — most of them Docker-backed and slow (≈10 min per full
  run). Today, results live in `/tmp/security-reports/` on the host filesystem, scoped
  to the process that produced the
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.registry
  rel: mentions
- concept: mod:parrot.scheduler
  rel: mentions
- concept: mod:parrot.tools
  rel: mentions
- concept: mod:parrot_tools.cloudsploit
  rel: mentions
- concept: mod:parrot_tools.security
  rel: mentions
---

# FEAT-NNN — Security Report Catalog & Persistent Operational History

> Brainstorm doc · SDD pipeline · Input for `/sdd-spec` and `/sdd-tojira`
> Status: **draft** — assign Jira ID via `/sdd-tojira`

---

## 1. Context & Motivation

The `SecurityAgent` (`agents/security.py`) runs a suite of scanners — CloudSploit, Prowler, Trivy, Checkov — most of them Docker-backed and slow (≈10 min per full run). Today, results live in `/tmp/security-reports/` on the host filesystem, scoped to the process that produced them and lost on restart.

This creates two friction points:

1. **Conversational re-scans.** A user asking *"give me the HIPAA posture report"* triggers a full container scan even when an identical report was produced by the daily `@schedule`d task at 08:00 UTC the same morning.
2. **No operational history.** Scheduled tasks log a `dict` of results that nobody consumes afterward. There is no way to answer *"how did our HIPAA posture change this month?"* or *"which critical findings have been open for >2 weeks?"*.

**The proposal:** introduce a cross-session, cross-user catalog of security reports backed by Postgres (metadata) and S3 (content), populated by the existing producers via a mixin, and consumed by the agent through a new `SecurityReportToolkit`. Add weekly/monthly summarization tasks that produce *higher-level reports of the same shape*, building a fractal operational memory.

---

## 2. Goals & Non-Goals

### Goals

- Decouple report **production** (toolkits) from **persistence** (store) from **consumption** (toolkit for the LLM).
- Cross-session, cross-user catalog — *not* scoped to a conversation thread.
- Agent prefers reading a recent report over re-running an expensive scan, governed by **explicit prompt guidance**, not hidden routing logic.
- Build an operational history that supports trend/drift questions.
- Reuse the FileManager abstraction already in `parrot.tools.file` — no new transport layer.
- Compliance retention: **never delete reports.** Visibility window is a query parameter, not a TTL.

### Non-Goals (this iteration)

- Replacing the FEAT-103 `ArtifactStore` (conversation-scoped artifacts — different abstraction, different lifecycle).
- Generic file-storage UX through the LLM (already covered by `FileManagerTool`).
- Per-user credential/auth on the catalog (single-tenant assumption for v1).
- Cross-agent catalog usage (deferred until a second consumer appears).
- Vector indexing of individual findings in PgVector (hook included, activation deferred).
- S3 storage-class tiering / Glacier lifecycle (deferred; the Terraform pattern in `.claude/rules/aws-cost-optimization.md` is referenced for the follow-up FEAT).

---

## 3. Codebase Contract

> Explicit list of what exists and must NOT be rewritten vs. what must be built.

### Existing infrastructure to reuse (DO NOT replace)

| Component | Path | Notes |
|---|---|---|
| `S3FileManager`, `LocalFileManager`, `FileManagerInterface` | `parrot/tools/file/s3.py`, `local.py`, `abstract.py` | Already async, used by FEAT-103. Has `upload`, `download`, `exists`, `get_url`, etc. |
| `FileManagerFactory` | `parrot/tools/file/tool.py` | `create(manager_type="s3"|"fs"|"gcs"|"temp", **kwargs)`. |
| `AbstractToolkit` | `parrot/tools/abstract` | Auto-discovers async public methods as tools; exclusion list for lifecycle methods is mandatory. |
| `AbstractTool`, `ToolResult` | same | Tool return convention. |
| `@register_agent`, `@schedule(schedule_type=ScheduleType.X, ...)` | `parrot.registry`, `parrot.scheduler` | Already used by `SecurityAgent`. |
| `Agent` lifecycle (`configure → ask`) | `parrot.bots.Agent` | Do not override `ask()`. Persistence lives in producer toolkits. |
| `navconfig.config` | `parrot.conf` | All env vars resolved here. Existing keys: `AWS_KEY`, `AWS_SECRET`, `S3_ARTIFACT_BUCKET`, `aws_security.*`. |
| Pydantic v2 | global | All new models must be v2. |
| Gemini `ThinkingConfig(include_thoughts=False)` | Google GenAI client | Required for any structured-output call inside summarizers. |

### Existing security toolkits to extend (modify, do not replace)

- `CloudSploitToolkit.run_cloudsploit_scan` — `parrot_tools.cloudsploit`
- `ComplianceReportToolkit` — `parrot_tools.security` (orchestrates Prowler + Trivy + Checkov)
- `ContainerSecurityToolkit` — `parrot_tools.security` (Trivy filesystem/image)

These toolkits will gain `ReportPersistenceMixin` and, when configured with a `file_manager` + `report_store`, auto-persist on every scan. **Backward compat:** if either dependency is `None`, persistence is a no-op (existing behavior preserved).

### To be built

1. `parrot/storage/security_reports/models.py` — `ReportKind`, `ReportRef`, `ReportFilter`, `EmbeddedFinding`, `SeverityBreakdown`.
2. `parrot/storage/security_reports/store.py` — `SecurityReportStore` Protocol + `PostgresS3SecurityReportStore` impl.
3. `parrot/storage/security_reports/schema.sql` — Postgres DDL.
4. `parrot_tools/security/persistence.py` — `ReportPersistenceMixin`.
5. `parrot_tools/security/report_toolkit.py` — `SecurityReportToolkit` (find / read / search / list-frameworks).
6. `parrot_tools/security/parsers/` — per-scanner `ReportParser` adapters (Trivy, CloudSploit, Prowler, Checkov).
7. `parrot_tools/security/summarizer.py` — `WeeklySecuritySummarizer`, `MonthlySecuritySummarizer` (deterministic LLM helpers).
8. `agents/security.py` — wire dependencies, update BACKSTORY, add `consolidate_weekly_security_summary` and `consolidate_monthly_security_summary` scheduled tasks.

---

## 4. Architecture Overview

Three layers, strictly separated:

```
┌─ Producer side ────────────────────────────────────────────────┐
│  CloudSploitToolkit ─┐                                         │
│  ComplianceToolkit  ─┼─► ReportPersistenceMixin                │
│  ContainerToolkit   ─┘     │                                   │
│                            │ _persist_report(...)              │
│                            ▼                                   │
│                  ┌─────────────────────┐                       │
│                  │   FileManager       │ ──► S3 bucket         │
│                  │   (transport)       │                       │
│                  └─────────────────────┘                       │
│                            │                                   │
│                            ▼                                   │
│                  ┌─────────────────────┐                       │
│                  │ SecurityReportStore │ ──► Postgres metadata │
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
│    • search_findings(...)        ← cross-report query          │
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

**Key invariant:** `ReportKind ∈ {scan, weekly_summary, monthly_summary, drift_comparison}` all live in the same table with the same `ReportRef` shape. Summaries are reports about reports — the type is fractal.

---

## 5. Module Breakdown (implementation order)

### Module 1 — Storage layer (`parrot/storage/security_reports/`)

**Pydantic models (`models.py`):**

```python
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
    def total(self) -> int: ...

class EmbeddedFinding(BaseModel):
    """Top-N findings inlined into the ReportRef for fast read-without-fetch."""
    finding_id: str
    severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFORMATIONAL"]
    title: str
    resource_id: str | None = None
    rule_id: str | None = None
    remediation_hint: str | None = None

class ReportRef(BaseModel):
    report_id: UUID
    report_kind: ReportKind
    scanner: str                         # "cloudsploit" | "prowler" | "trivy" | "checkov" | "aggregator"
    framework: str | None                # "HIPAA" | "PCI" | "SOC2" | "GDPR" | None for raw container scans
    provider: str                        # "aws" | "azure" | "gcp" | "oci" | "n/a"
    scope: dict                          # {region, account_id, target_image, iac_path, source_report_ids?}
    severity_summary: SeverityBreakdown
    top_findings: list[EmbeddedFinding]  # max 10, sorted by severity desc
    uri: str                             # s3://bucket/key or file://path
    content_type: str = "application/json"
    content_bytes: int | None = None
    produced_at: datetime                # tz-aware UTC
    produced_by: str                     # "schedule:run_hipaa_pci_compliance" | "agent:<session_id>"
    parser_version: str                  # for schema migrations
    retention_class: Literal["standard", "compliance", "ephemeral"] = "compliance"

class ReportFilter(BaseModel):
    """Query filter for the store. NO age filtering at this layer."""
    scanner: str | None = None
    framework: str | None = None
    provider: str | None = None
    report_kind: ReportKind | None = None
    since: datetime | None = None
    until: datetime | None = None
    scope_match: dict | None = None      # partial dict match (account_id, region, etc.)
    limit: int = 50
    order_by: Literal["produced_at_desc", "produced_at_asc"] = "produced_at_desc"
```

**Store Protocol (`store.py`):**

```python
class SecurityReportStore(Protocol):
    async def save_report(self, ref: ReportRef, content: bytes | Path) -> ReportRef: ...
    async def index(self, ref: ReportRef) -> None:
        """Index-only path: content was already uploaded by caller."""
    async def query(self, filter: ReportFilter) -> list[ReportRef]: ...
    async def get(self, report_id: UUID) -> ReportRef | None: ...
    async def fetch_content(self, report_id: UUID) -> bytes: ...
    async def delete(self, report_id: UUID) -> None:
        """Reserved for explicit GDPR-style requests; not used by retention."""
```

**`PostgresS3SecurityReportStore` impl notes:**

- Uses `asyncpg` (or `asyncdb` Postgres driver — match the rest of the codebase).
- S3 key naming: `security-reports/{scanner}/{framework_or_none}/{YYYY}/{MM}/{DD}/{report_id}.json` — deterministic for human browsing in console, never used by query path.
- Postgres schema with indexes on `(scanner, framework, produced_at DESC)`, `(report_kind, produced_at DESC)`, and a GIN index on `scope` for `scope_match`.
- `save_report` is transactional: upload to S3 first, then insert metadata. On metadata failure, S3 object is orphaned (acceptable; reconcile job out of scope).
- `query()` **NEVER** applies a default `since` — the visibility window is the caller's responsibility. The store is dumb on purpose.

**Postgres DDL (`schema.sql`):**

```sql
CREATE TABLE security_reports (
    report_id           UUID PRIMARY KEY,
    report_kind         TEXT NOT NULL,
    scanner             TEXT NOT NULL,
    framework           TEXT,
    provider            TEXT NOT NULL,
    scope               JSONB NOT NULL DEFAULT '{}',
    severity_summary    JSONB NOT NULL,
    top_findings        JSONB NOT NULL DEFAULT '[]',
    uri                 TEXT NOT NULL,
    content_type        TEXT NOT NULL DEFAULT 'application/json',
    content_bytes       BIGINT,
    produced_at         TIMESTAMPTZ NOT NULL,
    produced_by         TEXT NOT NULL,
    parser_version      TEXT NOT NULL,
    retention_class     TEXT NOT NULL DEFAULT 'compliance',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_security_reports_scanner_framework_produced
    ON security_reports (scanner, framework, produced_at DESC);
CREATE INDEX idx_security_reports_kind_produced
    ON security_reports (report_kind, produced_at DESC);
CREATE INDEX idx_security_reports_scope_gin
    ON security_reports USING GIN (scope);
```

---

### Module 2 — `ReportPersistenceMixin` (`parrot_tools/security/persistence.py`)

```python
class ReportPersistenceMixin:
    """Mixin for any toolkit that produces a security report artifact.

    Activation: set `file_manager` AND `report_store` at construction.
    If either is None, _persist_report() returns None (no-op, no error).
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
        # Either provide pre-computed summary/findings,
        # or rely on the registered parser for this scanner:
        severity_summary: SeverityBreakdown | None = None,
        top_findings: list[EmbeddedFinding] | None = None,
    ) -> ReportRef | None:
        if not self.file_manager or not self.report_store:
            return None
        # 1. Parse content for embedded summary if not provided
        if severity_summary is None or top_findings is None:
            parser = get_report_parser(scanner)
            parsed = parser.parse(content)
            severity_summary = severity_summary or parsed.severity_summary
            top_findings = top_findings or parsed.top_findings
        # 2. Build ref
        ref = ReportRef(
            report_id=uuid4(),
            report_kind=report_kind,
            scanner=scanner,
            framework=framework,
            provider=provider,
            scope=scope,
            severity_summary=severity_summary,
            top_findings=top_findings[:10],
            uri="",  # filled after upload
            content_type=content_type,
            produced_at=datetime.now(timezone.utc),
            produced_by=produced_by or f"toolkit:{type(self).__name__}",
            parser_version=self.parser_version,
        )
        # 3. Persist
        return await self.report_store.save_report(ref, content)
```

---

### Module 3 — Producer toolkit integration

Each producer toolkit gains `ReportPersistenceMixin` and an internal call after the scan succeeds. Example (CloudSploit):

```python
class CloudSploitToolkit(ReportPersistenceMixin, AbstractToolkit):
    def __init__(self, *, config: CloudSploitConfig,
                 file_manager: FileManagerInterface | None = None,
                 report_store: SecurityReportStore | None = None):
        super().__init__()
        self.file_manager = file_manager
        self.report_store = report_store
        # ... existing init ...

    async def run_cloudsploit_scan(
        self,
        compliance: str,
        output_format: str = "json",
    ) -> dict:
        # ... existing Docker scan, writes to results_dir ...
        result_path = Path(self.config.results_dir) / f"{scan_id}.{output_format}"

        ref = await self._persist_report(
            scanner="cloudsploit",
            framework=compliance,
            provider=self.config.cloud_provider.value,
            scope={
                "account_id": self.config.aws_account_id,
                "region": self.config.aws_region,
            },
            content=result_path,
            content_type=f"application/{output_format}",
        )
        # Return shape kept dict-compatible for back-compat with existing code,
        # but ref fields surfaced so LLM gets the useful metadata up front.
        return {
            "report_ref": ref.model_dump(mode="json") if ref else None,
            "severity_summary": ref.severity_summary.model_dump() if ref else {},
            "framework": compliance,
            "scan_id": scan_id,
            "persisted": ref is not None,
        }
```

**Decision:** scan tools no longer return the raw report content to the LLM context — only the `ReportRef` + summary. The LLM uses `read_security_report(report_id, section=...)` if it needs detail. This single change is what makes large scans (50MB CloudSploit JSON) usable conversationally.

---

### Module 4 — `SecurityReportToolkit` (LLM-facing consumer)

```python
class SecurityReportToolkit(AbstractToolkit):
    """Read-side toolkit. The agent calls THIS before running expensive scans."""

    DEFAULT_VISIBILITY_DAYS: int = 30

    def __init__(self, report_store: SecurityReportStore,
                 file_manager: FileManagerInterface):
        super().__init__()
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
        """
        Find recent security reports matching the filter. Returns metadata only
        (severity summary + top findings inlined); does NOT fetch full content.

        IMPORTANT: Always call this BEFORE running expensive scan tools
        (run_cloudsploit_scan, run_*_compliance, scan_filesystem, etc.).
        If a fresh-enough report exists, prefer read_security_report over re-scanning.
        """
        since = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        refs = await self._store.query(ReportFilter(
            scanner=scanner, framework=framework, provider=provider,
            scope_match=scope_match,
            report_kind=ReportKind(report_kind),
            since=since, limit=limit,
        ))
        return [r.model_dump(mode="json") for r in refs]

    async def read_security_report(
        self,
        report_id: str,
        section: Literal["summary", "critical", "high", "medium", "low", "executive", "full"] = "summary",
    ) -> dict:
        """Read a specific section of a report by id. Use 'summary' first; only
        fetch 'full' when the user explicitly asks for raw detail."""
        rid = UUID(report_id)
        ref = await self._store.get(rid)
        if not ref:
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
        """Search findings across reports (v1: SQL ILIKE + JSONB on top_findings;
        PgVector path is a future extension)."""
        ...

    async def list_available_frameworks(self) -> list[str]:
        """Diagnostic: which frameworks have reports in the catalog."""
        ...
```

---

### Module 5 — Parser registry (`parrot_tools/security/parsers/`)

A small registry maps `scanner` → `ReportParser` with two responsibilities:

1. `parse(content) -> ParsedReport(severity_summary, top_findings)` — used at write time by the mixin.
2. `extract_section(content, section) -> dict` — used at read time by `read_security_report`.

Implementations: `TrivyParser`, `CloudSploitParser`, `ProwlerParser`, `CheckovParser`, `AggregatorParser` (for weekly/monthly summaries — passthrough).

**Why a parser, not an LLM call:** scan outputs have stable JSON schemas. An LLM call here would be slow, non-deterministic, and would add token cost on every persist. Parsers are pure functions, version-tagged (`parser_version` field on `ReportRef` enables future schema migrations).

---

### Module 6 — Summarizers (`parrot_tools/security/summarizer.py`)

The weekly/monthly summarizers are deterministic LLM helpers (not agents, not toolkits — they don't have user-facing tools). They consume `ReportRef` lists from the store and produce a single `WeeklySummary` Pydantic model via structured output.

```python
class WeeklySummary(BaseModel):
    framework: str
    period_start: datetime
    period_end: datetime
    severity_totals: SeverityBreakdown
    new_findings: list[EmbeddedFinding]
    resolved_findings: list[EmbeddedFinding]
    persistent_findings: list[EmbeddedFinding]   # open ≥2 weeks — the high-signal section
    executive_paragraph: str                      # 3–5 sentences for human readers
    source_report_ids: list[UUID]

class WeeklySecuritySummarizer:
    def __init__(self, llm_client: LLMClient):  # Gemini 2.5 Pro by default
        self._llm = llm_client

    async def build(self, scans: list[ReportRef],
                    framework: str,
                    previous_summary: ReportRef | None = None) -> WeeklySummary:
        # 1. Compute diff vs. previous_summary deterministically (set operations on
        #    finding_id) — no LLM involved in the diff math.
        # 2. LLM call ONLY for executive_paragraph generation, with
        #    ThinkingConfig(include_thoughts=False) and structured output.
        ...
```

**Hard rule:** all arithmetic (severity totals, diffs, counts) is deterministic Python. The LLM is used **only** for the executive paragraph. This keeps summaries reproducible and audit-friendly — important for compliance.

The monthly summarizer follows the same shape but consumes `weekly_summary` reports instead of raw scans.

---

### Module 7 — `SecurityAgent` integration (`agents/security.py`)

This is the live-test target. Changes:

**A. Constructor wiring**

```python
def __init__(self, *args, **kwargs):
    super().__init__(*args, backstory=BACKSTORY, **kwargs)
    self._logger = logging.getLogger("SecurityAgent")

    # ... existing AWS creds ...

    # NEW: Persistence dependencies
    self._file_manager = FileManagerFactory.create(
        manager_type="s3",
        bucket_name=config.get("SECURITY_REPORT_BUCKET", fallback=config.S3_ARTIFACT_BUCKET),
        prefix="security-reports/",
        aws_config={
            "aws_access_key_id": config.AWS_ACCESS_KEY,
            "aws_secret_access_key": config.AWS_SECRET_KEY,
            "region_name": config.AWS_REGION_NAME,
        },
    )
    self._report_store = PostgresS3SecurityReportStore(
        dsn=config.get("SECURITY_REPORT_PG_DSN", fallback=config.DEFAULT_PG_DSN),
        file_manager=self._file_manager,
    )
    self._weekly_summarizer = WeeklySecuritySummarizer(llm_client=self.llm)
    self._monthly_summarizer = MonthlySecuritySummarizer(llm_client=self.llm)
```

**B. Inject store + file_manager into producer toolkits in `agent_tools()`**

```python
def agent_tools(self):
    persistence_kwargs = {
        "file_manager": self._file_manager,
        "report_store": self._report_store,

…(truncated)…
