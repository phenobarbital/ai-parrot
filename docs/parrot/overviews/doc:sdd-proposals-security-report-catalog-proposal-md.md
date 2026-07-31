---
type: Wiki Overview
title: FEAT-162 — Cross-session Postgres+S3 catalog for security reports with fractal
  weekly/monthly summaries
id: doc:sdd-proposals-security-report-catalog-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The original request, preserved verbatim, is the comprehensive SDD brainstorm
relates_to:
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.interfaces.file
  rel: mentions
- concept: mod:parrot.tools
  rel: mentions
- concept: mod:parrot_tools.security.models
  rel: mentions
---

---
id: FEAT-162
title: Cross-session Postgres+S3 catalog for security reports with fractal weekly/monthly summaries
slug: security-report-catalog
type: feature
mode: enrichment
status: review
source:
  kind: file
  jira_key: null
  jira_url: null
  file_path: sdd/proposals/security-report-catalog-brainstorm.md
  fetched_at: 2026-05-12
  summary_oneline: Cross-session security report catalog (Postgres metadata + S3 content) populated by producer toolkits and consumed via a new SecurityReportToolkit, with weekly/monthly fractal summaries.
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-162/
created: 2026-05-12
updated: 2026-05-12
---

# FEAT-162 — Cross-session Postgres+S3 catalog for security reports with fractal weekly/monthly summaries

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `file: sdd/proposals/security-report-catalog-brainstorm.md`
> **Audit**: [`sdd/state/FEAT-162/`](../state/FEAT-162/)

---

## 0. Origin

The original request, preserved verbatim, is the comprehensive SDD brainstorm
at `sdd/proposals/security-report-catalog-brainstorm.md`. The full source
(committed in the same change) is the authoritative narrative; this proposal
exists to anchor it in the live codebase.

> *"The `SecurityAgent` (`agents/security.py`) runs a suite of scanners —
> CloudSploit, Prowler, Trivy, Checkov — most of them Docker-backed and slow
> (≈10 min per full run). Today, results live in `/tmp/security-reports/` on
> the host filesystem, scoped to the process that produced them and lost on
> restart. … **The proposal:** introduce a cross-session, cross-user catalog
> of security reports backed by Postgres (metadata) and S3 (content),
> populated by the existing producers via a mixin, and consumed by the agent
> through a new `SecurityReportToolkit`. Add weekly/monthly summarization
> tasks that produce higher-level reports of the same shape, building a
> fractal operational memory."*

**Initial signals** (extracted, not interpreted):
- Verbs: *introduce*, *decouple*, *reuse*, *auto-persist*, *consolidate* → constructive / enrichment
- Named entities: `SecurityAgent`, `CloudSploitToolkit`, `ComplianceReportToolkit`, `ContainerSecurityToolkit`, `FileManagerFactory`, `S3FileManager`, `AbstractToolkit`, `ScheduleType`, `register_agent`, `navconfig`, plus seven new components (`ReportPersistenceMixin`, `SecurityReportToolkit`, `PostgresS3SecurityReportStore`, `ReportRef`, `WeeklySecuritySummarizer`, `MonthlySecuritySummarizer`, per-scanner parsers).
- Components / labels: AI-Parrot / agents / security / storage / scheduler
- Acceptance criteria provided: yes (brainstorm §11, 7 items)

---

## 1. Synthesis Summary

The brainstorm proposes a three-layer separation — **producers** (existing
scanner toolkits) → **persistence** (a new `PostgresS3SecurityReportStore`
populated through a `ReportPersistenceMixin`) → **consumer** (a new LLM-facing
`SecurityReportToolkit`) — plus weekly/monthly LLM-assisted consolidators that
produce reports about reports (a fractal `ReportKind`). Research grounded every
architectural pillar in the live codebase and found **no architectural
contradiction**, but surfaced ~10 concrete corrections to the brainstorm's
codebase contract: file paths shifted in the April-2026 fileinterface migration,
scanner toolkits return Pydantic models (not `dict`), CloudSploit method names
were guessed wrong, `ContainerSecurityToolkit` has no `results_dir`, navconfig
keys carry different names, and `agents/security.py` is gitignored *and*
contains a broken `consolidate_weekly_security_summary` stub today that
references symbols this FEAT is about to introduce. The brainstorm's two open
questions on Postgres driver and migration framework are also resolved by
direct codebase observation. **Recommendation**: proceed straight to `/sdd-spec`,
carrying every correction below into §6 *Codebase Contract*.

---

## 2. Codebase Findings

> Every entry is grounded in `sdd/state/FEAT-162/findings/F001-F023.md`. Path
> + symbol + line range + finding ID, throughout.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `agents/security.py` | `SecurityAgent` | 1-471 | Live integration target. Gitignored. Contains a **broken** `consolidate_weekly_security_summary` stub at L445-471 referencing symbols (`self._report_store`, `ReportFilter`, `self._build_weekly_summary`) that this FEAT introduces. BACKSTORY (L56-63) already mentions `find_security_report` even though the tool doesn't exist yet. | F001, F019 |
| 2 | `parrot/interfaces/file/` (re-exports from `navigator.utils.file`) | `FileManagerInterface` | F004 cites L36-165 of the upstream abstract | Canonical FileManager surface after April-2026 migration. Methods are `upload_file` / `download_file` / `get_file_url` / `exists` / `get_file_metadata` / `create_file` / `create_from_bytes` / `copy_file` / `delete_file`. **Not** `upload` / `download` / `get_url`. | F002, F004, F020 |
| 3 | `parrot/tools/file/tool.py` | `FileManagerFactory.create` | F003 | Real factory entry point. Takes `manager_type` plus per-impl kwargs. **No** `aws_config` kwarg. | F003 |
| 4 | `parrot/tools/file/s3.py` (impl) | `S3FileManager.__init__` | F005 | Accepts `aws_id` (key into navconfig `AWS_CREDENTIALS`) **OR** `credentials={'aws_key': ..., 'aws_secret': ..., 'region_name': ...}`. | F005 |
| 5 | `parrot/tools/toolkit.py` | `AbstractToolkit` | 191-403 | Real location of the toolkit base. Auto-discovers async public methods; lifecycle exclusion list at 368-403: `get_tools`, `get_tools_filtered`, `get_tools_sync`, `get_tool`, `list_tool_names`, `start`, `stop`, `cleanup`, plus an `exclude_tools` tuple. | F006, F007 |
| 6 | `parrot/tools/abstract.py` | `AbstractTool`, `ToolResult`, `AbstractToolArgsSchema` | — | Exports tool-result types only — **not** the toolkit base. Brainstorm's `parrot/tools/abstract` path for `AbstractToolkit` is wrong. | F006 |
| 7 | `parrot/scheduler/__init__.py` | `ScheduleType`, `schedule` | 41-96 | `ScheduleType.WEEKLY` and `ScheduleType.MONTHLY` exist; the `@schedule(...)` decorator passes arbitrary kwargs through, so `day_of_week`, `day`, `hour`, `minute` work as the brainstorm uses them. | F008 |
| 8 | `parrot/registry/registry.py` | `register_agent` | 1130-1156 | Decorator factory for `AbstractBot` subclasses; accepts `at_startup=True` via `**kwargs`. SecurityAgent already registered. | F009 |
| 9 | `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/toolkit.py` | `CloudSploitToolkit` | 23-37, 71-119, 121-163 | Public scan methods are `run_scan(plugins, ignore_ok, suppress, config) -> ScanResult` and `run_compliance_scan(framework, ignore_ok=True, config=None) -> ScanResult`. **Both return Pydantic `ScanResult`** (not `dict`). No `output_format` kwarg on scan; format conversion lives in a separate `generate_report(format=...)`. CloudSploit writes JSON to `{results_dir}/scan_{YYYYMMDD_HHMMSS}.json` after parsing when `results_dir` is set. **FEAT-160 (merged today)** added `CloudSploitConfig.config_file` and a per-call `config` arg. | F010, F011, F019 |
| 10 | `packages/ai-parrot-tools/src/parrot_tools/security/` | `ComplianceReportToolkit`, `ContainerSecurityToolkit`, `ConsolidatedReport`, `SeverityLevel` | F012, F013 | Compliance toolkit returns `ConsolidatedReport` (Pydantic). Container toolkit's real method is **`trivy_scan_filesystem`** (all public methods prefixed `trivy_`); **no `results_dir` / `report_output_dir`** — Trivy output comes from stdout. Existing `SeverityLevel` enum lives here too. | F012, F013, F023 |
| 11 | `parrot/conf.py` | `S3_ARTIFACT_BUCKET`, `AWS_ACCESS_KEY`, `AWS_SECRET_KEY`, `AWS_REGION_NAME`, `default_dsn`, `AWS_CREDENTIALS` | 418 (`AWS_REGION_NAME`), 475 (`S3_ARTIFACT_BUCKET`) | Real navconfig surface. Names are **`AWS_ACCESS_KEY` / `AWS_SECRET_KEY` / `default_dsn`** — not `AWS_KEY` / `AWS_SECRET` / `DEFAULT_PG_DSN` as the brainstorm assumed. `aws_security` is an INI **section** consumed via `config.get('aws_security', '<key>')`, not a parrot.conf constant. | F014 |
| 12 | `parrot/bots/abstract.py` | `AbstractBot.llm` | 922-928 | Live attribute on the bot base. Set to a `GoogleGenAIClient` after `super().__init__()` in `Agent` (`agents/agent.py:127-131`). Brainstorm's `llm_client=self.llm` is correct. | F021 |
| 13 | `parrot/clients/google/client.py` | `ThinkingConfig(include_thoughts=False)` | 1957-1977 | Existing precedent for structured-output calls. Summarizer follows verbatim. | F022 |
| 14 | `parrot/storage/artifacts.py` | `ArtifactStore` (FEAT-103) | 22+ | Peer abstraction. DynamoDB/SQLite + `OverflowStore`, conversation-scoped. **Not** a replacement target — different lifecycle, different consumers. | F017 |
| 15 | `parrot/bots/database/toolkits/base.py` | `asyncdb.AsyncDB(driver='pg', dsn=...)` | 344-351 | Canonical Postgres-async pattern. 30 usages of `asyncdb` across `parrot/` vs 1 raw `asyncpg` call. | F015 |
| 16 | `parrot/security/security_events.sql` | bare DDL | — | Closest precedent for schema layout: a `.sql` file co-located with the module using `CREATE TABLE IF NOT EXISTS` + `CREATE INDEX`. No Python loader; ops applies it out-of-band. **No migration framework anywhere** (no Alembic, no migrations dir). | F016 |
| 17 | `packages/ai-parrot/pyproject.toml` | `pydantic` dependency | 47 | Pinned to 2.12.5 — Pydantic v2 confirmed. | F018 |

### 2.2 Constraints Discovered

- **FileManager method names**. The mixin and the store must call
  `upload_file` / `download_file` / `get_file_url` / `exists` — the brainstorm's
  `upload` / `download` / `get_url` snippets are **wrong**. *Evidence*: F004.

- **`FileManagerFactory.create` has no `aws_config` kwarg.** Use
  `aws_id='security'` keyed into `AWS_CREDENTIALS`, or a literal
  `credentials={'aws_key': ..., 'aws_secret': ..., 'region_name': ...}`.
  *Evidence*: F003, F005.

- **Scanner public methods return Pydantic models, not `dict`.** Serialize
  via `result.model_dump_json().encode()` when calling the mixin's `bytes`
  branch. *Evidence*: F011, F012.

- **CloudSploit method names.** `run_scan(plugins, ignore_ok, suppress, config)`
  and `run_compliance_scan(framework, ignore_ok=True, config=None)` — the
  brainstorm's `run_cloudsploit_scan(compliance, output_format)` is fabricated.
  Format conversion is a *separate* `generate_report(format=...)` step.
  *Evidence*: F011.

- **`ContainerSecurityToolkit` has no `results_dir`.** Trivy is stdout-only.
  Per U3, this FEAT will have `ContainerSecurityToolkit` write Trivy stdout
  to a temp file (owned by the toolkit's lifecycle) and pass the `Path` to
  the mixin. *Evidence*: F012, F023.

- **`agents/security.py` is gitignored.** Implementation cannot lean on CI
  diff review. Per U1, the spec describes wiring in §3 prose; the implementer
  and ops coordinate via the spec. No tracked template is added in this FEAT.
  *Evidence*: F001, F019.

- **`agents/security.py` has a broken `consolidate_weekly_security_summary`
  stub at L445-471** referencing yet-to-exist symbols. The very first task
  must either delete the stub or land Modules 1-4 atomically before flipping
  it on, otherwise the agent fails to import mid-FEAT. *Evidence*: F001.

- **BACKSTORY already references `find_security_report`** (L56-63) even
  though the tool doesn't exist. Spec must either land Module 4 before/with
  Module 7 (BACKSTORY rewrite) or temporarily soften the BACKSTORY block
  during the rollout. *Evidence*: F001.

- **Producer toolkits forward `**kwargs` to `AbstractToolkit`.** The mixin
  must `pop()` `file_manager` and `report_store` from `kwargs` before
  `super().__init__(**kwargs)` to preserve the parent contract.
  *Evidence*: F012.

- **Postgres driver convention**: `asyncdb.AsyncDB(driver='pg', dsn=...)`.
  30 usages vs 1 raw asyncpg. *Resolves brainstorm OQ #1*. *Evidence*: F015.

- **No schema migration framework exists.** Bare `.sql` with
  `CREATE TABLE IF NOT EXISTS`, applied out-of-band by ops. The new store
  may also expose a `bootstrap_schema()` method as an additive convention.
  *Resolves brainstorm OQ #2*. *Evidence*: F016.

- **AWS creds for the security S3 bucket** come from a non-default INI
  section. Per U2, the spec adds `AWS_CREDENTIALS['security']` in
  `parrot/conf.py` so `FileManagerFactory.create(aws_id='security')` is
  idiomatic. *Evidence*: F014.

- **FEAT-160 (cloudsploit-config-support) merged today (2026-05-12)** —
  added `CloudSploitConfig.config_file` and per-call `config` arg. Spec
  threads the new field when constructing the toolkit. *Evidence*: F019.

- **Existing `SeverityLevel` enum** at `parrot_tools.security.models`
  coexists with the new `SeverityBreakdown` (count container, not level
  enum). Name carefully — they are distinct shapes. *Evidence*: F013.

- **FEAT-103 `ArtifactStore`** is a peer, not a replacement. Spec must
  cite both in §6 with a one-line non-replacement note. *Evidence*: F017.

- **Pydantic v2 (2.12.5)** is the project standard. All new models v2.
  *Evidence*: F018.

### 2.3 Recent History (Relevant)

| Commit / merge | When | Note | Touched paths |
|---|---|---|---|
| FEAT-160 cloudsploit-config-support merge (`bfb825e7`) + TASK-1079..1083 | 2026-05-12 (today) | Added `CloudSploitConfig.config_file` and per-call `config` arg on `run_scan`/`run_compliance_scan`. Brainstorm pre-dates this; spec must thread it. | `parrot_tools/cloudsploit/*` |
| FEAT-161 inspector-toolkit merge (`49334fb4`, `57c0ff8f`, `a9e3fabd`) | 2026-05-12 | AWS Inspector Toolkit + post-merge fixes. Tangential to FEAT-162 — surfaces another scanner that could later join the catalog (deferred). | `parrot_tools/security/*` |
| `fix on trivy executor for security agent` (`d866f7af`) | 2026-05-11 | Iteration on Trivy path on the security agent. Possible merge collisions in `agents/security.py` (gitignored). | `agents/security.py` (untracked) |
| fileinterface-migration series (TASK-851/852/869) | 2026-04-25/27 | Established `parrot.interfaces.file` re-exports from `navigator.utils.file`. The brainstorm's `parrot.tools.file.*` paths are stale relative to this. | `parrot/interfaces/file/*` |
| navigator-api version bump | 2026-05-05 | Final stabilization of the FileManager surface. No drift since. | `pyproject.toml`, FileManager surface |

*Evidence*: F019, F020.

---

## 3. Probable Scope  *(enrichment)*

### What's New

- **`parrot/storage/security_reports/models.py`** — Pydantic v2 models:
  `ReportKind` enum (`scan` / `weekly_summary` / `monthly_summary` /
  `drift_comparison`), `SeverityBreakdown`, `EmbeddedFinding`, `ReportRef`,
  `ReportFilter`.
- **`parrot/storage/security_reports/store.py`** — `SecurityReportStore`
  Protocol + `PostgresS3SecurityReportStore` impl using
  `asyncdb.AsyncDB(driver='pg', dsn=...)` and a `FileManagerInterface`. May
  expose a `bootstrap_schema()` convenience method.
- **`parrot/storage/security_reports/schema.sql`** — bare DDL (`CREATE TABLE
  IF NOT EXISTS security_reports`, three indexes) modeled on
  `parrot/security/security_events.sql`. Applied out-of-band by ops.
- **`parrot_tools/security/persistence.py`** — `ReportPersistenceMixin`. Pops
  `file_manager` / `report_store` from `kwargs` before `super().__init__()`.
  `content` accepts `bytes | Path`. No-op if either dep is `None`.
- **`parrot_tools/security/report_toolkit.py`** — `SecurityReportToolkit`
  (LLM-facing). Tools: `find_security_report`, `read_security_report`,
  `search_findings` (v1: SQL ILIKE + JSONB on `top_findings`),
  `list_available_frameworks`.
- **`parrot_tools/security/parsers/`** — deterministic Python parsers:
  `TrivyParser`, `CloudSploitParser`, `ProwlerParser`, `CheckovParser`,
  `AggregatorParser`. Each implements `parse(content) -> ParsedReport` and
  `extract_section(content, section) -> dict`. Carries a `parser_version`.
- **`parrot_tools/security/summarizer.py`** — `WeeklySecuritySummarizer` and
  `MonthlySecuritySummarizer`. **Deterministic diffs** in Python; LLM
  (`ThinkingConfig(include_thoughts=False)` per F022) only for the
  `executive_paragraph` field.

### What Changes

- **`packages/ai-parrot-tools/src/parrot_tools/cloudsploit/toolkit.py`** —
  add `ReportPersistenceMixin` to the base chain; thread `file_manager` /
  `report_store` kwargs through `__init__` via `.pop()`; auto-persist after
  `run_scan` and `run_compliance_scan` (returning the `ScanResult`
  unchanged for back-compat). *Evidence*: F011.
- **`parrot_tools/security/<compliance-toolkit-module>`** — same mixin
  pattern. Persistence is a side-effect; `ConsolidatedReport` return shape
  preserved. *Evidence*: F012.
- **`parrot_tools/security/<container-toolkit-module>`** — same mixin
  pattern. Resolve the no-`results_dir` issue per **U3**: capture Trivy
  stdout, write to a temp file, pass the `Path` to the mixin, delete after
  persist. *Evidence*: F012, F023.
- **`agents/security.py`** *(gitignored — per U1, no tracked template added)*:
  - Construct `FileManagerFactory.create(manager_type='s3', aws_id='security', prefix=…)` and `PostgresS3SecurityReportStore(dsn=config.default_dsn, file_manager=…)`.
  - Inject those into producer toolkits in `agent_tools()`.
  - **First**, fix / remove the broken `consolidate_weekly_security_summary` stub at L445-471 (or land Modules 1-4 atomically so it imports cleanly).
  - Add the new `@schedule`d consolidators (`consolidate_weekly_security_summary` Mon 06:00 UTC, `consolidate_monthly_security_summary` 1st 06:00 UTC).
  - Align the BACKSTORY freshness block (L56-63) with the real `SecurityReportToolkit` tool surface.
  - *Evidence*: F001, F019.
- **`parrot/conf.py`** — add `AWS_CREDENTIALS['security']` slot derived from
  the `aws_security` INI section so `FileManagerFactory.create(aws_id='security')`
  is idiomatic (per **U2**). *Evidence*: F014.

### What's Untouched (Non-Goals)

Explicitly out of scope, to prevent later scope creep:
- `parrot/storage/artifacts.py` (FEAT-103 `ArtifactStore`) — peer abstraction
  for conversation-scoped artifacts. Stays as is.
- `parrot/interfaces/file/*` and the upstream `navigator.utils.file.*`
  surface — consumed as-is; the spec must not reshape it.
- `/tmp/security-reports/` host-filesystem migration — v1 starts fresh; no
  back-migration of legacy reports (brainstorm §11 AC #5).
- Other `SecurityAgent` scheduled tasks beyond the two new consolidators —
  they auto-populate the catalog as a side-effect of the mixin; signatures
  and return-dict shapes preserved (brainstorm §5 Module 7.E).
- Per-finding indexing / PgVector — per **U4**, deferred to a follow-up
  FEAT.
- Cross-agent catalog usage — deferred until a second consumer appears
  (brainstorm §2 Non-Goals).
- Per-user credential / auth on the catalog — single-tenant assumption for
  v1 (brainstorm §2 Non-Goals).
- S3 storage-class tiering / Glacier lifecycle — deferred to a follow-up
  FEAT keyed to `.claude/rules/aws-cost-optimization.md`.

### Patterns to Follow

- **`asyncdb.AsyncDB(driver='pg', dsn=...)`** — match `parrot/bots/database/toolkits/base.py:344-351`. *Evidence*: F015.
- **Bare `.sql` DDL co-located with the module** — match `parrot/security/security_events.sql`. *Evidence*: F016.
- **`ThinkingConfig(include_thoughts=False)` for structured Gemini calls** — match `parrot/clients/google/client.py:1957-1977`. *Evidence*: F022.
- **`AbstractToolkit` auto-discovery** — every async public method on the toolkit (minus the lifecycle exclusion list) is auto-exposed; no manual registration. *Evidence*: F007.
- **Mixin `.pop()` pattern** — pop mixin kwargs from `**kwargs` before `super().__init__(**kwargs)`. *Evidence*: F012.
- **`AbstractBot.llm`** — the live attribute the summarizer accepts as its LLM dependency. *Evidence*: F021.

### Integration Risks

- **R1** — *Gitignored live target*. `agents/security.py` cannot be reviewed
  via diff. **Mitigation (U1 resolution)**: keep it untracked; the spec
  describes wiring in prose; the implementer coordinates with ops. *Evidence*: F001, F019.
- **R2** — *Broken stub blocks import*. Existing
  `consolidate_weekly_security_summary` at L445-471 references
  `self._report_store`, `ReportFilter`, `self._build_weekly_summary` which
  don't exist yet. **Mitigation**: spec orders Modules 1-2 (storage models +
  store) as the first tasks; the broken stub is either deleted in Task 0 or
  rewritten only after Modules 1-4 are in place. *Evidence*: F001.
- **R3** — *Trivy stdout vs mixin's `bytes | Path` signature*.
  **Mitigation (U3 resolution)**: `ContainerSecurityToolkit` writes Trivy
  stdout to a temp file, passes the `Path` to the mixin, deletes after
  persist. Mixin signature unchanged. *Evidence*: F012, F023.
- **R4** — *Today's FEAT-160 merge changed `CloudSploitConfig`*. Brainstorm
  pre-dates the new `config_file` field. **Mitigation**: spec threads
  `CloudSploitConfig.config_file` when `SecurityAgent` constructs the
  toolkit. *Evidence*: F019.
- **R5** — *BACKSTORY references vapor*. The agent's prompt at L56-63 tells
  the LLM to call `find_security_report` even though no such tool exists in
  the live agent_tools(). **Mitigation**: spec lands Module 4 before/with
  the SecurityAgent wiring task that re-anchors the BACKSTORY block (or
  softens the BACKSTORY temporarily). *Evidence*: F001.
- **R6** — *Enum collision risk*. Existing `SeverityLevel` enum in
  `parrot_tools.security.models` could collide with the new
  `SeverityBreakdown` import. **Mitigation**: names are distinct shapes
  (level vs counts) — document the difference in §6. *Evidence*: F013.

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | The catalog belongs at `parrot/storage/security_reports/`, peer to `parrot/storage/artifacts.py` | F017 | high | Existing storage layout houses peer stores; ArtifactStore added there in FEAT-103. |
| C2 | FileManager methods are `upload_file` / `download_file` / `get_file_url` / `exists` | F004 | high | Direct read of `FileManagerInterface` contract. |
| C3 | `FileManagerFactory.create()` has no `aws_config` kwarg | F003, F005 | high | Direct read of factory + S3FileManager constructors. |
| C4 | Scanner public methods return Pydantic `ScanResult` / `ConsolidatedReport`, not `dict` | F011, F012 | high | Direct reads of toolkit method signatures. |
| C5 | CloudSploit method names are `run_scan` / `run_compliance_scan`; no `output_format` scan kwarg | F011 | high | Direct read; brainstorm's `run_cloudsploit_scan` is fabricated. |
| C6 | `ContainerSecurityToolkit` captures Trivy via stdout — no `results_dir` attribute | F012, F023 | high | Direct read; brainstorm's `results_dir` assumption fails. |
| C7 | `agents/security.py` is gitignored AND contains a broken `consolidate_weekly_security_summary` stub | F001, F019 | high | File-read + git-log inspection. |
| C8 | Postgres driver convention is `asyncdb` (30 usages vs 1 asyncpg) | F015 | high | Codebase-wide grep count. Resolves brainstorm OQ #1. |
| C9 | No schema migration framework exists; bare `.sql` is precedent | F016 | high | Codebase search returned no Alembic / migrations dir. Resolves brainstorm OQ #2. |
| C10 | `ScheduleType` has `WEEKLY` / `MONTHLY`; `@schedule` passes kwargs through | F008 | high | Direct read of decorator. |
| C11 | `AbstractToolkit` auto-discovery → Module 4 tools auto-exposed | F007 | high | Direct read of lifecycle exclusion list. |
| C12 | `AbstractBot.llm` is the live attribute; brainstorm's `llm_client=self.llm` is correct | F021 | high | Direct read. |
| C13 | AWS creds for SecurityAgent come from `aws_security` INI section | F014 | high | Direct read + grep. |
| C14 | Adding `AWS_CREDENTIALS['security']` to `parrot/conf.py` is the idiomatic resolution | F014 | medium | Pattern-matched against existing `AWS_CREDENTIALS` slots; not directly observed but consistent with the shape. Resolved by U2. |

…(truncated)…
