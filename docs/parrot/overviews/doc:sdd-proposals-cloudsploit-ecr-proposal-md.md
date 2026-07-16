---
type: Wiki Overview
title: FEAT-165 — Instrumentalize ECR image scan collection + interactive HTML report
  in CloudSploitToolkit
id: doc:sdd-proposals-cloudsploit-ecr-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Verbatim source preserved at `sdd/state/FEAT-165/source.md`. Short excerpt:'
relates_to:
- concept: mod:parrot.interfaces.aws
  rel: mentions
---

---
id: FEAT-165
title: "Instrumentalize ECR image scan collection + interactive HTML report in CloudSploitToolkit"
slug: cloudsploit-ecr
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-05-12
  summary_oneline: "Instrumentalize two Node.js scripts (ECR scan collection + HTML report) inside the existing CloudSploit toolkit"
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-165/
created: 2026-05-12
updated: 2026-05-12
---

# FEAT-165 — Instrumentalize ECR image scan collection + interactive HTML report in CloudSploitToolkit

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `inline` — two Node.js scripts (`collect_ecr_findings.js` + `generate_ecr_report.js`)
> **Audit**: [`sdd/state/FEAT-165/`](../state/FEAT-165/)

---

## 0. Origin

Verbatim source preserved at `sdd/state/FEAT-165/source.md`. Short excerpt:

> Tengo un script Javascript para Cloudsploit ECR, se puede instrumentalizar
> algo así en nuestro CloudSploit toolkit?

Two scripts attached:

- `collect_ecr_findings.js` — iterates a hard-coded list of 23 ECR repos
  (each with a per-repo tag priority list, e.g. `staging > production > dev`),
  calls `aws ecr describe-image-scan-findings` via subprocess, writes a unified
  JSON dump `{generated_at, region, repos: [{repo, tag, scan_time, counts, findings}]}`.
- `generate_ecr_report.js` — consumes that JSON, groups CVEs by package
  (using ECR finding `attributes[]` — `package_name`, `package_version`,
  `fixed_in_versions`, `CVSS3_SCORE`/`CVSS4_SCORE`), renders a self-contained
  interactive HTML with severity badges, expand/collapse cards, search filter,
  and per-severity filters.

**Initial signals**:
- Verb: "se puede instrumentalizar" → request is *feasibility + scoping*, not a bug.
- Named entities: `CloudSploit toolkit`, `ECR`, `Basic Scanning`, `Enhanced Scanning`.
- Components: AWS, security/vuln scanning.
- Acceptance criteria provided: none (implicit: parity with the two scripts).

---

## 1. Synthesis Summary

The two scripts can be folded into AI-Parrot cleanly, but the natural home is a
new **`EcrScanCollector` + `EcrReportGenerator`** pair inside `parrot_tools/cloudsploit/`
that reuses the already-async `aws_ecr_get_image_scan_findings` wrapper at
`packages/ai-parrot-tools/src/parrot_tools/aws/ecr.py:188-240` — *not* the CloudSploit
CLI executor. The hard part (`describe_image_scan_findings` via `aioboto3`) is already
done; the net-new work is the multi-repo/tag-priority orchestration loop and a
Jinja2-rendered HTML template that mirrors `generate_ecr_report.js`. Findings show
no overlap with existing code, no schema migration needed in
`ReportPersistenceMixin`, and severity bucketing requires a small *new* enum
because the toolkit's `SeverityLevel(OK/WARN/FAIL/UNKNOWN)` is incompatible with
ECR's `CRITICAL/HIGH/MEDIUM/LOW/INFORMATIONAL`. Recommendation:
proceed to `/sdd-spec` directly — all four open questions are scope decisions
already resolved with the user.

> **Scanner-engine clarification (Inspector v2 is OUT of scope).**
> Inspector v2 / Enhanced Scanning is disabled in the target AWS account.
> This FEAT depends exclusively on the generic `ecr.describe_image_scan_findings`
> endpoint, which works against **Basic Scanning** without requiring Inspector
> (the JS source script's own docstring confirms this: *"Works with both Basic
> Scanning and Enhanced Scanning (Inspector)"*). The CloudSploit ECR
> configuration plugins (`ecrRepositoryPolicy`, `ecrRepositoryHasImageScans`,
> `ecrRepositoryEncrypted`, etc.) are **orthogonal CSPM checks**, not
> vulnerability scans, and remain available via the existing
> `CloudSploitToolkit.run_scan(plugins=[...])` path — they are not modified
> by this FEAT.

---

## 2. Codebase Findings

> Every entry is grounded in the digests at `sdd/state/FEAT-165/findings/`.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/toolkit.py` | `CloudSploitToolkit` | 27-315 | Add `collect_ecr_findings(plan_path, ...)` and `generate_ecr_report(...)` public async methods + hold the new collaborators. | F001 |
| 2 | `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/models.py` | new: `EcrSeverity`, `EcrScanFinding`, `EcrRepoFindings`, `EcrCollectionResult`, `EcrCollectionPlan` | after 203 | Independent Pydantic types — distinct from `SeverityLevel(OK/WARN/FAIL/UNKNOWN)`. | F002 |
| 3 | `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/ecr_collector.py` | new: `EcrScanCollector` | new file | Multi-repo / tag-priority loop with bounded concurrency (`asyncio.Semaphore`). Composes `AWSInterface`. | F003, F007 |
| 4 | `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/reports.py` | `ReportGenerator.generate_ecr_html` | after 157 | Browser-targeted Jinja2 render of `EcrCollectionResult`. | F004 |
| 5 | `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/templates/ecr_scan_report.html` | new template | new file | Port of `generate_ecr_report.js` HTML (inline CSS + JS preserved). | F004 |
| 6 | `packages/ai-parrot-tools/src/parrot_tools/aws/ecr.py` | `aws_ecr_get_image_scan_findings` | 188-240 | Extend to **preserve `attributes[]`** (currently drops `package_name`, `package_version`, `fixed_in_versions`, CVSS). Add `include_attributes: bool = False` flag for backwards compatibility. | F003 |
| 7 | `packages/ai-parrot-tools/src/parrot_tools/security/persistence.py` | `ReportPersistenceMixin._persist_report` | 77-150 | Reuse as-is with `scanner="ecr-image-scan"`. No schema change in v1. | F005 |

### 2.2 Constraints Discovered

- **Auth via `AWSInterface`, not credential files.** The JS script reads
  `~/.cloudsploit/aws/credentials.json` directly; Python must flow through
  `parrot.interfaces.aws.AWSInterface` (aioboto3 + navconfig `AWS_CREDENTIALS`).
  *Evidence*: F003.
- **Severity enum mismatch.** ECR severities (CRITICAL/HIGH/MEDIUM/LOW/INFORMATIONAL)
  do not fit the existing `SeverityLevel` (OK/WARN/FAIL/UNKNOWN). A new `EcrSeverity`
  enum is required; reusing `SeverityLevel` would corrupt CSPM scan summaries.
  *Evidence*: F002.
- **Async-only public methods.** `AbstractToolkit` auto-exposes async methods as
  agent tools. Both new methods must be `async def`.
  *Evidence*: F001.
- **HTML is browser-only.** The interactive features (CSS grid, gradients, JS
  filter handlers, expand/collapse) are incompatible with `xhtml2pdf`. PDF is
  intentionally out of scope (confirmed in Q&A — U3).
  *Evidence*: F004.
- **Bounded concurrency for ECR rate limits.** 23 repos × up to 3 tag attempts =
  up to 69 API calls; raw `asyncio.gather` will hit `ThrottlingException`. Use a
  small semaphore (default 5–8) configurable via the plan.
  *Evidence*: F007.
- **Repo+tag list is config, not code.** 23 entries with bespoke tag priorities
  will drift; hard-coding them creates PR churn. User confirmed Q1 →
  YAML loaded at runtime.
  *Evidence*: F007.
- **Use the `_resolve_config` pattern from FEAT-160** for per-call plan-path
  overrides on `collect_ecr_findings(plan=...)` to match `run_scan(config=...)`
  precedent at `toolkit.py:75-101`.
  *Evidence*: F006.

### 2.3 Recent History (Relevant)

| Commit | When | Author | Message | Touched files |
|--------|------|--------|---------|---------------|
| `8b7eb250` | 2026-05-12 | Jesús Lara | `wip: aws agent` | `aws/rds.py` |
| `87efb7d9` | 2026-05-12 | TASK-1110 | `feat(security-report-catalog): CloudSploitToolkit mixin integration` | cloudsploit/* |
| `bfb825e7` | 2026-05-12 | merge | FEAT-160 cloudsploit-config-support → dev | cloudsploit/* |
| `a9e3fabd`...`5d88b83c` | 2026-05-12 | feat | InspectorToolkit full skeleton + ECR-aware filters | aws/inspector.py |
| `f34c33d6`..`2c64175b` | 2026-05-12 | feat | `--config=` plumbing through executor/toolkit (`_resolve_config` pattern) | cloudsploit/* |

*Implication*: the surface is hot — coordinate with `wip: aws agent` to ensure
the new ECR scan tools are reachable from that agent. *Evidence*: F006.

---

## 3. Probable Scope

### What's New

- **`EcrCollectionPlan`** Pydantic model — `{region: str, concurrency: int = 5,
  repos: list[EcrRepoPlan]}` where `EcrRepoPlan = {name: str, tags: list[str]}`.
  Loaded from YAML via a small loader helper.
- **`EcrSeverity` enum** — `CRITICAL | HIGH | MEDIUM | LOW | INFORMATIONAL | UNTRIAGED`.
- **`EcrScanFinding`** Pydantic — `{name, severity, description, uri, package_name,
  package_version, fixed_in_versions, cvss}`.
- **`EcrRepoFindings`** Pydantic — `{repo, tag, scan_time, counts: dict[EcrSeverity, int],
  findings: list[EcrScanFinding]}`.
- **`EcrCollectionResult`** Pydantic — `{generated_at, region, repos: list[EcrRepoFindings]}`.
  Mirrors the JS output JSON 1:1 so any existing JS-produced report file is
  still parseable.
- **`EcrScanCollector`** — composes `AWSInterface` + the plan; emits
  `EcrCollectionResult`. Bounded concurrency via `asyncio.Semaphore`.
- **`ReportGenerator.generate_ecr_html(result, output_path=None)`** — Jinja2 render.
- **Template**: `cloudsploit/templates/ecr_scan_report.html` — direct port of
  `generate_ecr_report.js` HTML (interactive features preserved).
- **Two new `CloudSploitToolkit` methods**:
  - `async def collect_ecr_findings(plan: Optional[str] = None) -> EcrCollectionResult`
  - `async def generate_ecr_report(format: str = "html", output_path: Optional[str] = None) -> str`
- **Tests**: `tests/cloudsploit/test_ecr_collector.py`, `test_ecr_reports.py`,
  augment `test_toolkit.py` with the two new methods.

### What Changes

- **`aws/ecr.py::aws_ecr_get_image_scan_findings`** (188-240) — add
  `include_attributes: bool = False` parameter; when True, propagate the raw
  `attributes[]` array on each finding. Default False preserves existing
  behavior. *Evidence*: F003.
- **`cloudsploit/__init__.py`** — re-export the new public symbols
  (`EcrCollectionResult`, `EcrCollectionPlan`, etc.).
- **`cloudsploit/toolkit.py::CloudSploitToolkit.__init__`** — instantiate
  `EcrScanCollector` and assign `self.ecr_collector` (mirroring `self.executor`,
  `self.parser`, etc.).

### What's Untouched (Non-Goals)

- **Inspector v2 / Enhanced Scanning path** — confirmed deferred to a follow-up
  FEAT (user answer to U2). Inspector v2 is disabled in the target AWS account;
  the collector ONLY consumes the Basic-Scanning side of
  `ecr.describe_image_scan_findings`. The Inspector v2 API
  (`inspector2.list_findings`, already wrapped by `InspectorToolkit`) is not
  called from this FEAT.
- **CloudSploit ECR configuration plugins** (CSPM checks like
  `ecrRepositoryPolicy`, `ecrRepositoryHasImageScans`,
  `ecrRepositoryEncrypted`) — these are **orthogonal** to vuln scanning and
  remain available via the existing `CloudSploitToolkit.run_scan(plugins=[...])`
  path. No changes here.
- **PDF rendering of the ECR report** — confirmed HTML-only (user answer to U3).
- **Moving the new methods onto `ECRToolkit`** — confirmed staying on
  `CloudSploitToolkit` per user framing (user answer to U4).
- **The CloudSploit-CLI executor (`executor.py`)** — does not run ECR scans;
  no changes needed there.
- **CSPM scan models (`ScanResult`, `ScanFinding`, `SeverityLevel`)** — left
  intact; the new ECR types are independent.
- **Migration of the 23 hard-coded repos** — the spec will ship a
  `cloudsploit/ecr_plan.example.yaml` and document the format, but the
  authoritative plan lives outside the repo (ops-managed).

### Patterns to Follow

- **`_resolve_config` precedence pattern** at `toolkit.py:75-101` — clone it as
  `_resolve_plan(per_call)` for the new `plan` argument. *Evidence*: F006.
- **`pop_persistence_kwargs(kwargs)` BEFORE `super().__init__`** — already in
  `toolkit.py:36-39`; new collaborators must not break this ordering. *Evidence*: F005.
- **Jinja2 `Environment(FileSystemLoader(template_dir), autoescape=True)`** at
  `reports.py:28-32` — reuse the same env; only add a new template file.
  *Evidence*: F004.
- **Per-scanner `ReportPersistenceMixin` call** — `_persist_report(scanner="ecr-image-scan",
  framework=None, provider="aws", scope={"account_id":..., "region":...})` —
  mirrors `_persist_after_scan` at `toolkit.py:49-73`. *Evidence*: F005.
- **`@tool_schema(Input)` decorator** on the public methods if we want richer
  agent tool descriptions — see `aws/ecr.py:93` for the canonical pattern.
  *Evidence*: F003.

### Integration Risks

- **Concurrency tuning.** Default `Semaphore(5)` is a guess; ECR
  per-account quotas vary. *Mitigation*: expose `concurrency` on the plan
  and document it.
- **`include_attributes` propagation.** Extending `aws_ecr_get_image_scan_findings`
  changes a public toolkit method's payload shape when the flag is True. *Mitigation*:
  default `False` preserves wire compatibility; flag is opt-in.
- **Coordination with `wip: aws agent`.** The agent on branch tip may want to call
  `collect_ecr_findings` directly. *Mitigation*: surface the method via
  `CloudSploitToolkit` so it's discoverable through the same registration path
  as the existing CSPM tools.
- **Scan-not-found handling.** ECR returns `ScanNotFoundException` when a repo
  was never scanned; the JS script silently skips. *Mitigation*: existing
  wrapper at `aws/ecr.py:230-236` already returns a `scan_status: "NOT_FOUND"`
  dict — the collector treats that as "try next tag" and records a `skipped`
  reason on the result.

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | `aws_ecr_get_image_scan_findings` exists at `aws/ecr.py:188` and is the right call to wrap | F003 | high | direct read of method + grep confirms it's the only call site |
| C2 | `CloudSploitToolkit` public async methods are auto-exposed as agent tools via `AbstractToolkit` | F001 | high | confirmed by reading the class hierarchy |
| C3 | Severity bucketing needs a new enum independent from `SeverityLevel` | F002 | high | direct comparison of enums |
| C4 | Jinja2 + xhtml2pdf is the canonical reporting pattern in `cloudsploit/` | F004 | high | direct read of `reports.py` |
| C5 | The existing wrapper drops `attributes[]` and needs extension | F003 | high | direct read of ecr.py:206-214 |
| C6 | `ReportPersistenceMixin` will accept the new scanner with no schema change | F005 | medium | inferred from `scanner: str` signature; not yet verified against `ReportRef.scanner` constraints |
| C7 | Repo+tag list should be config-driven YAML | F007 + user answer | high | F007 + explicit user confirmation (U1) |
| C8 | Bounded concurrency (`asyncio.Semaphore(5)` default) is correct over raw fan-out | F007 | medium | reasoning from ECR rate-limit behavior; not benchmarked |
| C9 | Interactive HTML report cannot be reused for PDF | F004 + user answer | high | F004 + explicit user confirmation (U3) |
| C10 | Recommended placement is `CloudSploitToolkit`, not `ECRToolkit` | user answer | high | explicit user confirmation (U4) |
| C11 | Basic Scanning only in v1; Enhanced Scanning is a follow-up FEAT | F003, F006 + user answer | high | explicit user confirmation (U2); Inspector v2 is disabled in the target AWS account |
| C12 | `ecr.describe_image_scan_findings` works WITHOUT Inspector enabled — it is a generic ECR endpoint that returns whichever scan engine the repo has configured (Basic in this case) | F003 + JS source docstring | high | AWS API contract; confirmed by the JS script's own comment "Works with both Basic Scanning and Enhanced Scanning" |
| C13 | CloudSploit ECR configuration plugins (`ecrRepository*`) are CSPM checks, orthogonal to vulnerability scanning and untouched by this FEAT | F001 | high | direct read of the toolkit's existing `run_scan(plugins=[...])` surface |

Distribution: **11** high, **2** medium, **0** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **¿Dónde debe vivir la lista de repos + tag-priorities?** —
  *Resolved*: YAML cargado en runtime, Pydantic-validated, path pasado a
  `collect_ecr_findings(plan=...)`. *Resolves claims*: C7.
- [x] **¿Soportar Basic + Enhanced Scanning en v1?** — *Resolved*: Solo Basic
  en v1. Enhanced (Inspector v2) como FEAT seguido. *Resolves claims*: C11.
- [x] **¿El reporte HTML también necesita variante PDF?** — *Resolved*: Solo
  HTML — las features interactivas son el punto. *Resolves claims*: C9.
- [x] **¿Dónde colocar los nuevos métodos públicos?** — *Resolved*:
  `CloudSploitToolkit` (framing del usuario, agrupa security-posture + vuln
  scans). *Resolves claims*: C10.

### Unresolved (defer to spec / implementation)

*None.* All scope decisions were resolved in the Q&A phase.

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-165`** — *Rationale*: localization is high-confidence across
7 entries (C1, C2, C5), all scope decisions are settled (C7, C9, C10, C11),
and the implementation maps cleanly onto existing patterns (Jinja2 reports,
AWSInterface aioboto3, ReportPersistenceMixin). No architectural fork needs
brainstorming.

### Alternatives

- **`/sdd-brainstorm FEAT-165`** — only if you want to explicitly score
  CloudSploitToolkit-home vs ECRToolkit-home vs facade-on-both with library/code
  references before specing. Not recommended given U4 is already resolved.
- **Direct `/sdd-task FEAT-165`** — *not recommended*. The work touches 7
  files (3 new, 4 modified) and 1+ new template; a single task would be too
  coarse.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-165/state.json` |
| Source (raw) | `sdd/state/FEAT-165/source.md` |
| Research plan | `sdd/state/FEAT-165/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-165/findings/F001-*.md` … `F007-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-165/synthesis.json` |

**Budget consumed**:
- Files read: 11 / 40
- Grep calls: 6 / 25
- Git calls: 1 / 10
- Wall time: ~90s / 300s
- Truncated: **no**

**Mode determination**: `auto` → resolved to `enrichment` (user asks "se puede
instrumentalizar" — feasibility/scoping, not investigation of a malfunction).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Jesús Lara |
