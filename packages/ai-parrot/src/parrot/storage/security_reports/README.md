# parrot/storage/security_reports

Cross-session security report catalog backed by Postgres (metadata) and
S3 (content). Introduced by FEAT-162.

## What this is

This module stores the output of cloud-security scanners (CloudSploit,
Prowler, Trivy, Checkov) in a durable, cross-session catalog. Raw scan
reports, weekly summaries, and monthly summaries all share the same
`ReportRef` shape and live in the same Postgres table. The `SecurityAgent`
reads from this catalog before triggering expensive scans, governed by an
explicit freshness policy in its BACKSTORY. The module enforces a strict
three-layer separation: producers write, the store persists, and the
consumer toolkit exposes the catalog to the LLM.

## Component Diagram

```
+- Producer side -------------------------------------------------------+
|  CloudSploitToolkit  -+                                               |
|  ComplianceToolkit   -+-> ReportPersistenceMixin                     |
|  ContainerToolkit    -+     |                                         |
|                             |  _persist_report(...)                   |
|                             v                                         |
|                   +-------------------+                               |
|                   |   FileManager     | --> S3 bucket                 |
|                   |   (upload_file)   |                               |
|                   +-------------------+                               |
|                             |                                         |
|                             v                                         |
|                   +-------------------+                               |
|                   |SecurityReportStore| --> Postgres (asyncdb)        |
|                   |    (catalog)      |                               |
|                   +-------------------+                               |
+-----------------------------------------------------------------------+
                              |
                              | shared store + file_manager
                              v
+- Consumer side -------------------------------------------------------+
|  SecurityReportToolkit (LLM-facing)                                   |
|    - find_security_report(...)   <- metadata only                     |
|    - read_security_report(...)   <- content by section                |
|    - search_findings(...)        <- cross-report query (v1 top-10)    |
|    - list_available_frameworks() <- discovery                         |
+-----------------------------------------------------------------------+

+- Scheduled consolidators (same agent, same store) --------------------+
|  Mon 06:00 UTC  -> consolidate_weekly_security_summary               |
|                    reads scans (last 7d), writes weekly_summary       |
|                                                                       |
|  1st 06:00 UTC  -> consolidate_monthly_security_summary              |
|                    reads weekly_summaries (last 4w), writes           |
|                    monthly_summary                                    |
+-----------------------------------------------------------------------+
```

## Three layers

### Producers

`CloudSploitToolkit`, `ComplianceReportToolkit`, and `ContainerSecurityToolkit`
gain a `ReportPersistenceMixin` (see `parrot_tools/security/persistence.py`).
When a toolkit is constructed with both `file_manager` and `report_store`
injected by the `SecurityAgent`, each scan method auto-persists its output as
a side effect via `_persist_report(...)`. When either dependency is `None`,
persistence is a no-op (backward compatible).

The mixin pops its own kwargs (`file_manager`, `report_store`) before passing
the remainder to `super().__init__(**kwargs)`, so the producer toolkits'
existing constructors are unchanged.

### Persistence

`PostgresS3SecurityReportStore` (see `store.py`) implements the
`SecurityReportStore` Protocol:

- `save_report(ref, content)` -- uploads content bytes to S3 first
  (`security-reports/{scanner}/{framework}/{YYYY}/{MM}/{DD}/{report_id}.json`),
  then inserts the metadata row in Postgres. S3-first ordering is
  orphan-tolerant: a missing Postgres row is less harmful than a missing S3 object.
- `query(ReportFilter)` -- returns `list[ReportRef]` sorted by `produced_at DESC`.
  No implicit age filter -- the caller controls the `since` window.
- `get(report_id)` -- fetch a single `ReportRef` by UUID.
- `fetch_content(report_id)` -- download the raw bytes from S3.
- `index(ref)` / `delete(report_id)` -- reserved for vector indexing and
  GDPR deletion requests respectively.

Postgres driver: `asyncdb.AsyncDB(driver='pg', dsn=...)`. Schema is in
`parrot/storage/security_reports/schema.sql` (bare SQL; no migration framework).

### Consumer

`SecurityReportToolkit` (see `parrot_tools/security/report_toolkit.py`) exposes
four async methods auto-discovered as LLM tools by `AbstractToolkit`:

- `find_security_report` -- returns metadata only; never calls `fetch_content`.
- `read_security_report` -- returns `{"ref": ...}` for `section="summary"` without
  fetching content; fetches and parses for all other sections.
- `search_findings` -- in-Python filter over the embedded `top_findings` column
  (v1 limitation: only top-10 findings per report are searchable).
- `list_available_frameworks` -- diagnostic; returns deduplicated sorted list.

## Fractal ReportKind

All report types share the `ReportRef` shape and the same Postgres table.
Summaries are reports about reports.

| kind             | produced by                           | schedule         |
|------------------|---------------------------------------|------------------|
| scan             | CloudSploit, Prowler, Trivy, Checkov  | per scan call    |
| weekly_summary   | WeeklySecuritySummarizer              | Mon 06:00 UTC    |
| monthly_summary  | MonthlySecuritySummarizer             | 1st 06:00 UTC    |
| drift_comparison | reserved for future FEAT              | n/a              |

Diff arithmetic (severity totals, new/resolved/persistent findings) is
deterministic Python. An LLM call (one per `build()` invocation) generates
only the `executive_paragraph` field.

## Freshness policy

The following block appears verbatim in the `SecurityAgent` BACKSTORY. It is
reproduced here as a canonical reference for developers and ops.

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
     (no fetch needed -- it's embedded).
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

## Conventions

- Pydantic v2 only (project pin: 2.12.5). No Pydantic v1 compatibility shims.
- asyncdb `AsyncDB(driver='pg', dsn=...)` for Postgres. No ORM.
- Bare `.sql` schema (`schema.sql`). No migration framework (Alembic is not used).
- Compliance retention: never delete reports. Visibility is a query parameter
  (`since`), not a TTL. GDPR deletion is the only exception (via `delete()`).
- `search_findings` v1 limitation: only the embedded `top_findings` JSONB column
  (top-10 findings per report) is searchable. Findings ranked 11th or lower in a
  report are not indexed. Document this caveat to users.

## Related

- `sdd/specs/security-report-catalog.spec.md` -- full feature specification.
- `sdd/proposals/security-report-catalog.proposal.md` -- research and proposals.
- `packages/ai-parrot/src/parrot/storage/artifacts.py` -- FEAT-103 peer
  abstraction (conversation-scoped artifacts; different lifecycle).
- `.claude/rules/aws-cost-optimization.md` -- referenced for the deferred
  S3 lifecycle / Glacier tiering follow-up FEAT.
