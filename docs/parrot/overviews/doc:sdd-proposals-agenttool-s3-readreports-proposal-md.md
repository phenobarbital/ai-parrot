---
type: Wiki Overview
title: FEAT-184 — Agnostic S3 report reader toolkit for LLM agents
id: doc:sdd-proposals-agenttool-s3-readreports-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'The original request, preserved verbatim:'
---

---
id: FEAT-184
title: Agnostic S3 report reader toolkit for LLM agents
slug: agenttool-s3-readreports
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-05-18
  summary_oneline: S3 report reader toolkit — agnostic LLM-facing tools for retrieving, filtering, comparing, and summarizing S3-stored reports
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-184/
created: 2026-05-18
updated: 2026-05-18
---

# FEAT-184 — Agnostic S3 report reader toolkit for LLM agents

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `inline`
> **Audit**: [`sdd/state/FEAT-184/`](../state/FEAT-184/)

---

## 0. Origin

The original request, preserved verbatim:

> *A Security Agent using CloudSploitToolkit and other tools is using
> `PostgresS3SecurityReportStore` for saving all those findings in an S3
> bucket. Current JSON files follow the scan report format (e.g.,
> `security-reports/cloudsploit/scan_20260518_232916.json`). The idea is
> creating a tool for interacting with the S3 bucket — the agent can
> retrieve the last report, filter by report, extract reports by category,
> compare two reports to each other (comparing current last report with
> previous one to find changes), summarize reports. The toolkit (inheriting
> from `AbstractToolkit` and extending `FileS3Manager` +
> `PostgresS3SecurityReportStore`) should be more agnostic, allowing LLMs to
> extract HTML or JSON documents from S3 bucket.*

**Initial signals** (extracted, not interpreted):
- Verbs: *creating*, *retrieve*, *filter*, *compare*, *summarize*, *extract* → constructive / enrichment
- Named entities: `CloudSploitToolkit`, `PostgresS3SecurityReportStore`, `FileS3Manager`, `AbstractToolkit`, S3 bucket
- Components / labels: AI-Parrot / tools / storage / agents / S3
- Acceptance criteria provided: no (implicit from description)

---

## 1. Synthesis Summary

The request asks for a new LLM-facing toolkit that bridges the security report
catalog (`PostgresS3SecurityReportStore`) and raw S3 storage
(`FileManagerInterface`) into a single, **agnostic** tool surface. The existing
`SecurityReportToolkit` (FEAT-162) already covers basic catalog queries
(`find_security_report`, `read_security_report`, `search_findings`,
`list_available_frameworks`) but is tightly coupled to security-report models
and lacks three capabilities the user explicitly requests: **report comparison**,
**structured summarization**, and **direct S3 object browsing** for non-indexed
documents (HTML, arbitrary JSON). The new toolkit operates in **dual mode** —
catalog-backed queries when a `SecurityReportStore` is injected, raw S3 browsing
via `FileManagerInterface` when it is not. It sits alongside the existing
`SecurityReportToolkit` (which remains the security-agent-specific convenience
layer) as the agnostic, any-agent reader.

---

## 2. Codebase Findings

> All entries are grounded in `sdd/state/FEAT-184/findings/F001-F010.md`.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `parrot_tools/security/report_toolkit.py` | `SecurityReportToolkit` | 27-249 | Existing read-side toolkit (FEAT-162). Security-specific: no compare, no summarize, no raw S3 browse. Stays as-is. | F001 |
| 2 | `parrot/storage/security_reports/store.py` | `PostgresS3SecurityReportStore` | 144-389 | Catalog persistence. Methods: `query`, `get`, `fetch_content`, `query_distinct_frameworks`. Uses `asyncdb.AsyncDB` + `FileManagerInterface`. | F002 |
| 3 | `parrot/storage/security_reports/models.py` | `ReportRef`, `ReportFilter`, `ReportKind`, `SeverityBreakdown`, `EmbeddedFinding` | 1-129 | Catalog data models. `ReportRef.content_type` already supports `application/json` and `text/html`. `uri` points to S3 key. | F007 |
| 4 | `parrot/interfaces/file/__init__.py` | `FileManagerInterface` | — | S3/GCS/Local file abstraction. Key methods: `list_files(path, pattern)`, `find_files(keywords, extension, prefix)`, `download_file(source, dest)`, `get_file_url(path, expiry)`, `get_file_metadata(path)`, `exists(path)`. Returns `FileMetadata(name, path, size, content_type, modified_at, url)`. | F003 |
| 5 | `parrot/tools/toolkit.py` | `AbstractToolkit` | 191-518 | Base class. Auto-discovers public async methods; `exclude_tools` tuple; `tool_prefix` for namespacing; `_pre_execute`/`_post_execute` hooks. | F004 |
| 6 | `parrot_tools/cloudsploit/toolkit.py` | `CloudSploitToolkit` | 159-801 | Composition pattern exemplar. `ReportPersistenceMixin` + `AbstractToolkit`; pops `file_manager`/`report_store` from kwargs before `super().__init__()`. Has `compare_scans` using `ScanComparator`. | F005 |
| 7 | `parrot_tools/cloudsploit/comparator.py` | `ScanComparator` | 1-71 | CloudSploit-specific comparison: identity key = `(plugin, region, resource)`. Tracks new/resolved/unchanged/severity-changed. NOT reusable for generic JSON. | F006 |
| 8 | `parrot_tools/security/parsers/__init__.py` | `get_report_parser` | 21-50 | Parser registry: trivy, cloudsploit, prowler, checkov, aggregator. Each implements `parse(content) → ParsedReport` and `extract_section(content, section) → dict`. | F008 |
| 9 | `parrot_tools/aws/s3.py` | `S3Toolkit` | 47-372 | Bucket-level inspection (list buckets, security analysis). NOT an object reader. | F009 |
| 10 | `parrot_tools/security/persistence.py` | `ReportPersistenceMixin` | 59-198 | Write-side mixin for producer toolkits. NOT needed by the new consumer toolkit. | F010 |

### 2.2 Constraints Discovered

- **`FileManagerInterface.list_files` returns `FileMetadata` objects.** The new
  toolkit must serialize these for the LLM (name, path, size, content_type,
  modified_at). *Evidence*: F003.

- **`SecurityReportStore` is optional.** The dual-mode design means the toolkit
  works with just `FileManagerInterface` for raw S3 browsing. When
  `report_store` is `None`, catalog-dependent methods
  (`get_latest_report`, `compare_reports`) degrade gracefully or return an
  informative error. *Evidence*: F002, F003.

- **Parser dispatch is scanner-keyed.** `get_report_parser(scanner)` requires
  knowing the scanner name. When browsing raw S3 (no catalog), the scanner is
  unknown — the toolkit must infer from file path conventions or content
  structure, or skip parser dispatch for generic JSON. *Evidence*: F008.

- **`ScanComparator` is CloudSploit-specific.** Identity key
  `(plugin, region, resource)` does not apply to Trivy, Prowler, or generic
  JSON. The new toolkit needs a generic JSON diff baseline with optional
  parser-dispatch for richer domain-aware comparison. *Evidence*: F006.

- **Existing `SecurityReportToolkit` stays.** It is wired into the
  SecurityAgent's BACKSTORY flow (find → read → scan-if-stale). The new toolkit
  supplements it, not replaces it. *Evidence*: F001.

- **`AbstractToolkit` auto-discovery.** Every public async method becomes a
  tool. The new toolkit's public API surface IS its tool surface. *Evidence*: F004.

- **`content_type` already supports HTML.** `ReportRef.content_type` defaults to
  `application/json` but is a free string. `_mirror_rendered_report` already
  stores HTML in S3. The toolkit can serve both JSON and HTML content. *Evidence*: F007, F010.

### 2.3 Recent History (Relevant)

| Commit / merge | When | Note | Touched paths |
|---|---|---|---|
| FEAT-162 security-report-catalog | 2026-05-12 | Landed the full catalog: store, models, parsers, persistence mixin, SecurityReportToolkit, summarizers. All components this FEAT-184 extends. | `parrot/storage/security_reports/*`, `parrot_tools/security/*` |
| FEAT-160 cloudsploit-config-support | 2026-05-12 | Added per-call `config` arg on CloudSploitToolkit scans. Tangential — no impact on the reader toolkit. | `parrot_tools/cloudsploit/*` |
| FEAT-161 inspector-toolkit | 2026-05-12 | AWS Inspector Toolkit. Another scanner that feeds the catalog. | `parrot_tools/security/*` |

---

## 3. Probable Scope *(enrichment)*

### What's New

- **`parrot_tools/s3/report_reader.py`** — `S3ReportReaderToolkit(AbstractToolkit)`.
  The agnostic LLM-facing toolkit. Composes `FileManagerInterface` (required) +
  `SecurityReportStore` (optional). Exposes ~8 public async methods that
  auto-discover as agent tools:

  | Tool method | Purpose | Requires catalog? |
  |-------------|---------|-------------------|
  | `list_s3_reports(prefix, pattern, limit)` | Browse S3 objects by prefix/pattern | No |
  | `get_latest_report(scanner, framework, report_kind)` | Retrieve the most recent catalog report | Yes |
  | `get_report_content(report_id_or_path, section)` | Download and return report content (JSON or HTML), optionally a specific section | Dual |
  | `filter_reports(scanner, framework, provider, category, since_days, limit)` | Query the catalog with flexible filters | Yes |
  | `compare_reports(report_a, report_b)` | Diff two reports — generic JSON diff + parser dispatch when available | Dual |
  | `summarize_report(report_id_or_path)` | Extract structured metrics: severity counts, top findings, categories, content type | Dual |
  | `get_report_url(report_id_or_path, expiry)` | Generate a pre-signed S3 URL for direct download | No |
  | `list_report_categories()` | List distinct scanners, frameworks, and report kinds in the catalog | Yes |

- **`parrot_tools/s3/comparator.py`** — `GenericReportComparator`. Performs
  structural JSON diff (keys added/removed/changed, array element diffs).
  When a scanner name is known, dispatches to the scanner-specific comparator
  (e.g., `ScanComparator` for CloudSploit) for richer output. Falls back to
  generic diff for unknown formats or HTML documents.

- **`parrot_tools/s3/__init__.py`** — Package init with public exports.

- **`tests/s3/test_report_reader.py`** — Unit tests covering:
  - Raw S3 browsing (no catalog)
  - Catalog-backed queries
  - Dual-mode content fetch (by UUID vs. by S3 path)
  - Report comparison (generic + parser-dispatch)
  - Structured summarization
  - Graceful degradation when catalog is `None`

### What Changes

- **`parrot_tools/__init__.py`** — Register `S3ReportReaderToolkit` in the
  toolkit registry so agents can discover it by name.
  *Evidence*: F005 (follows CloudSploitToolkit registration pattern).

### What's Untouched (Non-Goals)

- **`SecurityReportToolkit`** (`parrot_tools/security/report_toolkit.py`) —
  stays as the security-agent-specific convenience layer. Not modified, not
  replaced.
- **`PostgresS3SecurityReportStore`** — consumed as-is via the
  `SecurityReportStore` protocol. No modifications to the store.
- **`ReportPersistenceMixin`** — write-side concern. The new toolkit is
  read-only.
- **`ScanComparator`** — stays as CloudSploit-specific. Reused via dispatch, not
  modified.
- **Parser registry** — consumed as-is. No new parsers needed for this FEAT.
- **LLM-powered narrative summaries** — deferred. The toolkit returns structured
  data; the agent's LLM generates narratives.
- **Write/upload capabilities** — this is a reader toolkit. No mutation of S3
  content.
- **Schema changes to `security_reports` table** — no DDL changes.

### Patterns to Follow

- **`AbstractToolkit` auto-discovery** — every public async method is a tool.
  Use descriptive docstrings (they become tool descriptions for the LLM).
  *Evidence*: F004.
- **Constructor composition** — compose `FileManagerInterface` +
  `SecurityReportStore` (optional) via constructor injection, same pattern as
  `SecurityReportToolkit`. *Evidence*: F001, F002.
- **`exclude_tools` for internal methods** — if any helper is accidentally
  public, use `exclude_tools` to hide it. *Evidence*: F004.
- **`tool_prefix` namespacing** — use `tool_prefix="s3_"` to namespace all
  tools (e.g., `s3_list_reports`, `s3_get_latest_report`). Prevents collision
  with `SecurityReportToolkit` tools. *Evidence*: F004.
- **Parser dispatch via `get_report_parser(scanner)`** — reuse existing parsers
  for section extraction on catalog-backed reports. *Evidence*: F008.
- **`FileMetadata` serialization** — convert to dict for LLM consumption:
  `{name, path, size, content_type, modified_at}`. *Evidence*: F003.

### Integration Risks

- **R1** — *Tool name collision with SecurityReportToolkit*. Both toolkits
  could be mounted on the same agent. **Mitigation**: use `tool_prefix="s3_"`
  on the new toolkit, ensuring all tools are namespaced
  (e.g., `s3_compare_reports` vs. `find_security_report`). *Evidence*: F001, F004.

- **R2** — *Dual-mode confusion for the LLM*. When `report_store` is `None`,
  catalog-dependent tools return informative errors. The LLM might not
  understand why. **Mitigation**: tool docstrings explicitly state catalog
  requirement. The `list_s3_reports` and `get_report_url` tools always work.
  *Evidence*: F002, F003.

- **R3** — *Generic JSON diff noise*. Structural diffs on large scan reports
  (1000+ findings) can be verbose. **Mitigation**: cap diff output to top-N
  changes by severity. When a parser is available, dispatch to the domain-aware
  comparator which produces a cleaner `ComparisonReport`. *Evidence*: F006.

- **R4** — *Scanner inference for raw S3 paths*. When browsing without catalog,
  scanner name must be inferred from S3 key path
  (`security-reports/cloudsploit/...`). **Mitigation**: parse the S3 key path
  against the known prefix convention
  `{prefix}{scanner}/{framework}/{date}/{id}.json`. Fall back to generic parser
  if unknown. *Evidence*: F002, F008.

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | New toolkit inherits `AbstractToolkit` with auto-discovery | F004 | high | Direct read of base class; all existing toolkits follow this pattern. |
| C2 | `FileManagerInterface.list_files` + `find_files` provide S3 browsing | F003 | high | Direct inspection of interface methods; returns `FileMetadata`. |
| C3 | `SecurityReportStore.query` + `fetch_content` provide catalog access | F002 | high | Direct read of store implementation. |
| C4 | Generic JSON diff is needed (ScanComparator is CloudSploit-specific) | F006 | high | Direct read; identity key is `(plugin, region, resource)` — not portable. |
| C5 | Parser registry can be reused for section extraction | F008 | high | `get_report_parser(scanner)` + `extract_section` are already public API. |
| C6 | `SecurityReportToolkit` is NOT replaced — it stays as-is | F001 | high | Different scope: agent-specific convenience vs. agnostic reader. |
| C7 | `ReportRef.content_type` supports both JSON and HTML | F007 | high | Free string field, `text/html` already used by `_mirror_rendered_report`. |
| C8 | `tool_prefix` prevents name collisions between toolkits | F004 | high | `AbstractToolkit._resolve_tool_name` applies prefix idempotently. |
| C9 | Dual-mode (catalog optional) is architecturally clean | F002, F003 | high | `SecurityReportStore` is a Protocol; `None` check is straightforward. |
| C10 | Scanner can be inferred from S3 key path for raw browsing | F002 | medium | Relies on convention `{prefix}{scanner}/{framework}/...`; breaks for non-standard paths. |

Distribution: **9 high**, **1 medium**, **0 low**.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **U1 — Should the toolkit compose `SecurityReportStore` directly or accept
  a generic document store protocol?** — *Resolved*: Dual-mode. Accept
  `FileManagerInterface` (required) + `SecurityReportStore` (optional). Catalog
  is optional — toolkit works with just the file manager for non-indexed
  documents.
  *Resolves claims*: C9

- [x] **U2 — For report comparison, which diff strategy?** — *Resolved*:
  Generic JSON diff as the baseline. When a parser is available (scanner name
  known), dispatch to it for richer domain-aware comparison. Falls back to
  generic diff for unknown formats.
  *Resolves claims*: C4

- [x] **U3 — For summarization, should the toolkit call an LLM or return
  structured data?** — *Resolved*: Return structured data (severity counts, top
  findings, categories, delta). The calling agent's LLM generates the narrative
  summary. No LLM dependency in the toolkit.

### Unresolved (defer to spec / implementation)

- [ ] **Package location** — *Owner*: tbd. Should the toolkit live at
  `parrot_tools/s3/` (new package) or `parrot_tools/security/s3_reader.py`
  (collocated with existing security tools)? The agnostic nature suggests a
  standalone package.

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-184`** — *Rationale*: localization is high-confidence (9/10
claims at high), all three design unknowns are resolved, and the architecture
is a clean composition of existing abstractions (`AbstractToolkit` +
`FileManagerInterface` + `SecurityReportStore` Protocol). The scope is
well-bounded: one new toolkit module, one generic comparator, tests.

### Alternatives

- **`/sdd-brainstorm FEAT-184`** — only if you want to explore radically
  different API surfaces (e.g., a single `query_s3` mega-tool vs. the granular
  tool set proposed).
- **`/sdd-task FEAT-184`** — not recommended without a spec: the toolkit has
  ~8 tools and a comparator module, so decomposition into tasks would benefit
  from a spec's acceptance criteria.
- **Manual review** — not needed: research was complete (not truncated) and
  overall confidence is high.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-184/state.json` |
| Source (raw) | `sdd/state/FEAT-184/source.md` |
| Findings (digests) | `sdd/state/FEAT-184/findings/F001-F010.md` |

**Budget consumed**:
- Files read: 12 / 40
- Grep calls: 14 / 25
- Git calls: 3 / 10
- Wall time: ~180s / 300s
- Truncated: **no**

**Mode determination**: explicit `enrichment` (constructive verbs: *creating*,
*retrieve*, *filter*, *compare*, *summarize*; new toolkit component).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Schema versions | state=1.0, synthesis=1.0 |
| Operator | Jesus Lara (jlara@trocglobal.com) |
