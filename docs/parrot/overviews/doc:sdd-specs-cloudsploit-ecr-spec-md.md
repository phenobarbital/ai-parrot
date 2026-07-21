---
type: Wiki Overview
title: 'Feature Specification: CloudSploit ECR Image-Scan Collector & Interactive
  Report'
id: doc:sdd-specs-cloudsploit-ecr-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The user maintains two Node.js scripts — `collect_ecr_findings.js` and
relates_to:
- concept: mod:parrot.interfaces.aws
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
- concept: mod:parrot_tools.aws.ecr
  rel: mentions
- concept: mod:parrot_tools.cloudsploit
  rel: mentions
- concept: mod:parrot_tools.cloudsploit.models
  rel: mentions
- concept: mod:parrot_tools.cloudsploit.reports
  rel: mentions
- concept: mod:parrot_tools.decorators
  rel: mentions
- concept: mod:parrot_tools.security.persistence
  rel: mentions
- concept: mod:parrot_tools.toolkit
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: CloudSploit ECR Image-Scan Collector & Interactive Report

**Feature ID**: FEAT-165
**Date**: 2026-05-12
**Author**: Jesús Lara
**Status**: approved
**Target version**: next minor

> **Origin**: Research-grounded proposal at
> [`sdd/proposals/cloudsploit-ecr.proposal.md`](../proposals/cloudsploit-ecr.proposal.md).
> Audit trail at [`sdd/state/FEAT-165/`](../state/FEAT-165/).

---

## 1. Motivation & Business Requirements

### Problem Statement

The user maintains two Node.js scripts — `collect_ecr_findings.js` and
`generate_ecr_report.js` — that:

1. Iterate a curated list of 23 ECR repositories (each with a per-repo tag
   priority list, e.g. `staging > production > dev`) and call
   `aws ecr describe-image-scan-findings` once per first-matching tag, then
   write a unified JSON dump
   `{generated_at, region, repos: [{repo, tag, scan_time, counts, findings}]}`.
2. Consume that JSON to render an interactive, self-contained HTML
   vulnerability report grouped by package, with severity filters, search,
   and per-repo expand/collapse cards.

Today this lives outside AI-Parrot. AWS credentials come from
`~/.cloudsploit/aws/credentials.json`, the repo+tag plan is hard-coded inside
the JS, concurrency is strictly sequential, and the report cannot be triggered
from an AI-Parrot agent or persisted to the security report catalog.

The CloudSploit toolkit already exists and is the natural home for this
capability: it owns CSPM scans and now (FEAT-160) supports per-call config
overrides and (TASK-1110) persistence into the security report catalog via
`ReportPersistenceMixin`. Folding ECR image-scan aggregation into the same
toolkit groups all security-posture and vulnerability-reporting tools under
one agent-discoverable surface.

### Goals

- Provide an agent-facing async method
  `CloudSploitToolkit.collect_ecr_findings(plan=...)` that ingests a
  YAML-validated `EcrCollectionPlan` and emits a typed `EcrCollectionResult`.
- Provide an agent-facing async method
  `CloudSploitToolkit.generate_ecr_report(...)` that renders an interactive
  HTML file from the last collection (or a supplied result).
- Reuse the existing async AWS client (`AWSInterface` /
  `aioboto3.Session`) — credentials must flow through the same path as every
  other AWS toolkit.
- Preserve the full ECR finding payload — including `attributes[]`
  (`package_name`, `package_version`, `fixed_in_versions`,
  `CVSS3_SCORE`/`CVSS4_SCORE`) — so the HTML report can group CVEs by package.
- Honour ECR rate limits via bounded concurrency (`asyncio.Semaphore`),
  configurable from the plan.
- Opt into the existing security report catalog via `ReportPersistenceMixin`
  with `scanner="ecr-image-scan"`.

### Non-Goals (explicitly out of scope)

- **Inspector v2 / Enhanced Scanning path.** Inspector is disabled in the
  target AWS account. The Inspector v2 API
  (`inspector2.list_findings`, already wrapped by `InspectorToolkit`) is not
  called from this FEAT. Adding it is deferred to a follow-up.
- **Modifications to CloudSploit ECR configuration plugins** (CSPM checks
  like `ecrRepositoryPolicy`, `ecrRepositoryHasImageScans`,
  `ecrRepositoryEncrypted`). These are orthogonal to vulnerability scanning
  and remain available via `CloudSploitToolkit.run_scan(plugins=[...])`.
- **PDF rendering of the ECR report.** The HTML report relies on CSS grid,
  gradients, and client-side JS (search/filter), all of which xhtml2pdf
  cannot render. HTML-only in v1.
- **Migration of the 23 hard-coded repos into the repository.** The spec
  ships an example plan at `cloudsploit/ecr_plan.example.yaml`; the
  authoritative plan is ops-managed and lives outside the repo.
- **Moving the new public methods to `ECRToolkit`** in
  `parrot_tools/aws/ecr.py`. Per user framing, methods live on
  `CloudSploitToolkit`.
- **Changes to the CloudSploit CLI executor** (`executor.py`). It is a
  Node.js subprocess wrapper and does not call AWS APIs directly.
- **Changes to existing CSPM models** (`ScanResult`, `ScanFinding`,
  `SeverityLevel(OK/WARN/FAIL/UNKNOWN)`). The new ECR types are
  independent.

---

## 2. Architectural Design

### Overview

A new `EcrScanCollector` collaborator orchestrates the multi-repo /
tag-priority loop, using `AWSInterface` (aioboto3) to call
`ecr.describe_image_scan_findings` for each `(repo, tag)` pair in order, with
first-match-wins semantics. Concurrency across repos is bounded by an
`asyncio.Semaphore` whose size is read from the plan. A new
`EcrCollectionPlan` Pydantic model is loaded from a YAML file at call time.

`ReportGenerator` gains a new method, `generate_ecr_html`, which renders a
new Jinja2 template, `ecr_scan_report.html`. The template is a direct port
of the user's `generate_ecr_report.js` output: severity badges, per-repo
expand/collapse cards, per-package grouping, search and filter controls.
All CSS and JS are inlined so the file is self-contained.

`CloudSploitToolkit` gains two new public async methods:

- `collect_ecr_findings(plan: Optional[str] = None) -> EcrCollectionResult`
- `generate_ecr_report(output_path: Optional[str] = None,
   result: Optional[EcrCollectionResult] = None) -> str`

A small private helper `_resolve_ecr_plan(per_call: Optional[str])` mirrors
the existing `_resolve_config(...)` precedence pattern from FEAT-160
(per-call argument overrides a config field — see `toolkit.py:75-101`). The
plan path may also be set as a new optional field on `CloudSploitConfig`,
`ecr_plan_file: Optional[str] = None`.

`aws_ecr_get_image_scan_findings` (in `parrot_tools/aws/ecr.py:188-240`)
gains a new `include_attributes: bool = False` parameter. When True, the
method returns the raw `attributes[]` array on each finding alongside the
existing normalized shape. The default preserves wire compatibility for
existing callers. The new collector calls it with `include_attributes=True`.

Persistence reuses `ReportPersistenceMixin._persist_report` with
`scanner="ecr-image-scan"`, `framework=None`, `provider="aws"`, and
`scope={"account_id": ..., "region": <plan.region>}`. A new entry in the
parser registry (`security/parsers/`) is **deferred** — initial persistence
calls pass an explicit pre-computed `SeverityBreakdown` to skip parser lookup.

### Component Diagram

```
CloudSploitToolkit
   ├── (existing) CloudSploitExecutor   ── CSPM scans (Docker/CLI)
   ├── (existing) ScanResultParser
   ├── (existing) ReportGenerator       ── + generate_ecr_html()
   ├── (existing) ScanComparator
   └── (new)      EcrScanCollector      ── multi-repo / tag-priority loop
                       │
                       ↓ uses
                  AWSInterface          ── parrot/interfaces/aws.py
                       │
                       ↓ wraps
                  aioboto3 ecr client   ── describe_image_scan_findings
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractToolkit` | extends (via existing `CloudSploitToolkit`) | New async methods auto-become agent tools |
| `ReportPersistenceMixin` | uses | `scanner="ecr-image-scan"` |
| `AWSInterface` (`parrot.interfaces.aws`) | uses | aioboto3 session + `client("ecr")` ctx manager |
| `ECRToolkit.aws_ecr_get_image_scan_findings` | extends (adds opt-in `include_attributes`) | Backward-compatible (defaults to False) |
| `ReportGenerator` (`reports.py`) | extends (adds `generate_ecr_html`) | New Jinja2 template |
| `CloudSploitConfig` | extends (adds optional `ecr_plan_file`) | Mirrors `config_file` precedent |
| Existing CSPM plugins (`ecrRepository*`) | NOT modified | Orthogonal, run via `run_scan(plugins=[...])` |
| Inspector v2 (`InspectorToolkit`) | NOT used | Out of scope (Inspector disabled in target account) |

### Data Models

```python
# parrot_tools/cloudsploit/models.py  (additions)

from enum import Enum
from datetime import datetime
from pathlib import Path
from pydantic import BaseModel, Field, field_validator


class EcrSeverity(str, Enum):
    """ECR / vulnerability scan severities (distinct from SeverityLevel)."""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFORMATIONAL = "INFORMATIONAL"
    UNTRIAGED = "UNTRIAGED"


class EcrRepoPlan(BaseModel):
    """One repo + its tag priority order."""
    name: str = Field(..., description="ECR repository name")
    tags: list[str] = Field(
        ..., min_length=1,
        description="Tags to try in priority order; first match wins"
    )


class EcrCollectionPlan(BaseModel):
    """Plan for collect_ecr_findings. Loaded from YAML at runtime."""
    region: str = Field(..., description="AWS region to query")
    aws_id: str = Field(
        default="default",
        description="Credential identifier resolved by AWSInterface"
    )
    concurrency: int = Field(
        default=5, ge=1, le=20,
        description="Max concurrent describe-image-scan-findings calls"
    )
    repos: list[EcrRepoPlan] = Field(..., min_length=1)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "EcrCollectionPlan":
        """Load and validate a plan from a YAML file."""
        ...


class EcrScanFinding(BaseModel):
    """One vulnerability finding from ECR Basic Scanning."""
    name: str = Field(..., description="CVE id or finding name")
    severity: EcrSeverity
    description: str = ""
    uri: str = ""
    package_name: str | None = None
    package_version: str | None = None
    fixed_in_versions: str | None = None
    cvss: str | None = None


class EcrRepoFindings(BaseModel):
    """Findings for a single (repo, tag) pair."""
    repo: str
    tag: str
    scan_time: datetime | None = None
    counts: dict[EcrSeverity, int] = Field(default_factory=dict)
    findings: list[EcrScanFinding] = Field(default_factory=list)


class EcrCollectionResult(BaseModel):
    """Top-level container — mirrors collect_ecr_findings.js output JSON."""
    generated_at: datetime
    region: str
    repos: list[EcrRepoFindings] = Field(default_factory=list)
    skipped: list[dict] = Field(
        default_factory=list,
        description="Per-repo reason when no tag returned a scan (e.g. ScanNotFoundException)"
    )
```

### New Public Interfaces

```python
# parrot_tools/cloudsploit/ecr_collector.py  (new file)

class EcrScanCollector:
    """Iterate (repo, tag) pairs and gather ECR vuln findings concurrently."""

    def __init__(self, aws: AWSInterface) -> None:
        ...

    async def collect(self, plan: EcrCollectionPlan) -> EcrCollectionResult:
        """Run the plan with bounded concurrency; first-match-wins per repo."""
        ...
```

```python
# parrot_tools/cloudsploit/toolkit.py  (CloudSploitToolkit additions)

async def collect_ecr_findings(
    self,
    plan: Optional[str] = None,
) -> EcrCollectionResult:
    """Aggregate ECR vulnerability scan findings across many repos.

    Args:
        plan: Path to a YAML file describing the repos and tag priorities.
            When None, falls back to ``CloudSploitConfig.ecr_plan_file``.
    """
    ...

async def generate_ecr_report(
    self,
    output_path: Optional[str] = None,
    result: Optional[EcrCollectionResult] = None,
) -> str:
    """Render an interactive HTML vulnerability report.

    Args:
        output_path: File path to write the HTML. Auto-generated when None.
        result: Override the last collected result. Defaults to
            ``self._last_ecr_result``.
    """
    ...
```

```python
# parrot_tools/cloudsploit/reports.py  (ReportGenerator addition)

async def generate_ecr_html(
    self,
    result: "EcrCollectionResult",
    output_path: Optional[str] = None,
) -> str:
    """Render ecr_scan_report.html from an EcrCollectionResult."""
    ...
```

```python
# parrot_tools/aws/ecr.py  (signature change — opt-in flag)

@tool_schema(GetImageScanFindingsInput)
async def aws_ecr_get_image_scan_findings(
    self,
    repository_name: str,
    image_tag: str = "latest",
    include_attributes: bool = False,   # ← NEW
) -> Dict[str, Any]:
    """Get vulnerability scan findings for a container image.

    When include_attributes=True, each finding includes the raw
    ECR `attributes[]` array (package_name, package_version,
    fixed_in_versions, CVSS3_SCORE/CVSS4_SCORE).
    """
    ...
```

---

## 3. Module Breakdown

### Module 1: ECR domain models

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/models.py`
- **Responsibility**: Add `EcrSeverity`, `EcrRepoPlan`, `EcrCollectionPlan`,
  `EcrScanFinding`, `EcrRepoFindings`, `EcrCollectionResult`. Include
  `EcrCollectionPlan.from_yaml(path)` classmethod.
- **Depends on**: PyYAML (already transitively present), pydantic.

### Module 2: `EcrScanCollector`

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/ecr_collector.py` (new file)
- **Responsibility**: Implement the multi-repo iteration with bounded
  `asyncio.Semaphore`, first-match-wins tag fallback, and the mapping from
  raw ECR `attributes[]` array into `EcrScanFinding.package_name` /
  `package_version` / `fixed_in_versions` / `cvss`. Treat
  `ScanNotFoundException` (returned by the wrapper as `scan_status: "NOT_FOUND"`)
  as "try next tag"; if every tag fails, record an entry in
  `EcrCollectionResult.skipped`.
- **Depends on**: Module 1; `parrot.interfaces.aws.AWSInterface`.

### Module 3: `aws_ecr_get_image_scan_findings` extension

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/aws/ecr.py`
- **Responsibility**: Add `include_attributes: bool = False` to
  `GetImageScanFindingsInput` and the method signature; when True,
  propagate the raw `attributes[]` per finding alongside the existing
  normalized fields. No behaviour change when False (default).
- **Depends on**: nothing new; modifies existing.

### Module 4: HTML template

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/templates/ecr_scan_report.html` (new file)
- **Responsibility**: Direct port of `generate_ecr_report.js` output —
  hero header, summary cards (CRITICAL/HIGH/MEDIUM/LOW totals), search
  input, global severity filter buttons, expand/collapse-all toggle,
  per-repo cards (auto-expand when CRITICAL+HIGH > 0), per-package blocks
  with CVE table (severity badge, CVE link, description ≤180 chars, fix
  version, CVSS). Inline CSS + inline JS. No external assets.
- **Depends on**: nothing.

### Module 5: `ReportGenerator.generate_ecr_html`

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/reports.py`
- **Responsibility**: Add async method that loads
  `ecr_scan_report.html` from the existing Jinja2 env, renders it with
  a `EcrCollectionResult` model dump, sorts repos with `navigator-api-tf`
  pinned first then other `navigator-*` then alphabetic (matching the JS),
  groups findings by `(package_name, package_version)`, and either writes
  to `output_path` or returns the HTML string. Browser-targeted — no
  `xhtml2pdf` path.
- **Depends on**: Module 1, Module 4.

### Module 6: `CloudSploitToolkit` ECR methods + plan resolver

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/toolkit.py`
- **Responsibility**: (a) Construct an `EcrScanCollector` instance in
  `__init__`. (b) Add `_resolve_ecr_plan(per_call)` helper mirroring
  `_resolve_config(per_call)`. (c) Add public async methods
  `collect_ecr_findings(plan=None)` and
  `generate_ecr_report(output_path=None, result=None)`. (d) Store the last
  result on `self._last_ecr_result`. (e) After every successful collection,
  call `_persist_after_ecr_scan(result)` (new sibling of
  `_persist_after_scan`) that invokes
  `ReportPersistenceMixin._persist_report(scanner="ecr-image-scan", ...)`.
- **Depends on**: Modules 1, 2, 5.

### Module 7: `CloudSploitConfig.ecr_plan_file`

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/models.py`
- **Responsibility**: Add an optional `ecr_plan_file: Optional[str] = None`
  field with the same "validate-at-scan-time, not construction-time"
  semantics as `config_file` (existing field, models.py:154-163).
- **Depends on**: nothing.

### Module 8: Example plan + module exports

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/ecr_plan.example.yaml` (new file)
- **Responsibility**: Ship a documented example YAML mirroring the user's
  23-repo / tag-priority shape. Will be the reference for ops when
  authoring the production plan.
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/__init__.py`
- **Responsibility**: Re-export the new public symbols: `EcrCollectionPlan`,
  `EcrCollectionResult`, `EcrRepoFindings`, `EcrScanFinding`, `EcrSeverity`,
  `EcrScanCollector`.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_ecr_severity_enum_values` | Module 1 | All 6 expected values present; isinstance str |
| `test_collection_plan_from_yaml_roundtrip` | Module 1 | Load valid YAML → typed plan; bad shape raises ValidationError |
| `test_collection_plan_rejects_empty_tags` | Module 1 | `tags=[]` fails validation (`min_length=1`) |
| `test_collection_plan_concurrency_bounds` | Module 1 | `concurrency=0` and `concurrency=21` both rejected |
| `test_collector_first_match_wins` | Module 2 | Repo with `tags=["staging","prod"]` — staging returns findings, prod never queried |
| `test_collector_fallback_on_scan_not_found` | Module 2 | First tag returns `scan_status="NOT_FOUND"` → tries next tag |
| `test_collector_skipped_when_all_tags_fail` | Module 2 | All tags return NOT_FOUND → `result.skipped` gets the repo |
| `test_collector_bounded_concurrency` | Module 2 | Track in-flight calls; never exceeds `plan.concurrency` |
| `test_collector_propagates_attributes` | Module 2 | Mocked finding with `attributes=[{key:"package_name",value:"openssl"},...]` → `EcrScanFinding.package_name == "openssl"` |
| `test_ecr_wrapper_include_attributes_false_default` | Module 3 | Default call preserves existing payload (no `attributes` key) |
| `test_ecr_wrapper_include_attributes_true` | Module 3 | Set True → raw `attributes[]` array present on each finding |
| `test_reports_generate_ecr_html_writes_file` | Module 5 | Output path written; returns the path |
| `test_reports_generate_ecr_html_returns_string` | Module 5 | output_path=None → returns rendered string |
| `test_reports_navigator_api_pinned_first` | Module 5 | Mixed repo list — `navigator-api-tf` first in rendered HTML |
| `test_reports_groups_cves_by_package` | Module 5 | Multiple findings same pkg+ver → single pkg block with N CVEs |
| `test_toolkit_collect_ecr_findings_uses_plan_arg` | Module 6 | Per-call plan overrides `ecr_plan_file` field; debug log emitted |
| `test_toolkit_collect_ecr_falls_back_to_config_field` | Module 6 | `plan=None` + `ecr_plan_file` set → loads from config |
| `test_toolkit_collect_ecr_no_plan_raises` | Module 6 | Both None → ValueError |
| `test_toolkit_generate_ecr_report_uses_last_result` | Module 6 | After `collect_ecr_findings`, `generate_ecr_report()` uses `_last_ecr_result` |
| `test_toolkit_persists_ecr_scan_when_deps_present` | Module 6 | Mocked `report_store.save_report` called with `scanner="ecr-image-scan"`, `provider="aws"`, `scope` containing region |
| `test_toolkit_persistence_no_op_when_deps_absent` | Module 6 | Without `file_manager` / `report_store` kwargs → no exception, no call |
| `test_config_ecr_plan_file_default_none` | Module 7 | Field default is None |
| `test_init_exports_ecr_symbols` | Module 8 | `from parrot_tools.cloudsploit import EcrCollectionPlan` works |

### Integration Tests

| Test | Description |
|---|---|
| `test_end_to_end_with_mocked_ecr_client` | Stub `aws.client("ecr")` to a mock that returns fixture findings for 3 repos with varied tag priorities. Confirm `EcrCollectionResult` shape matches the JS output JSON byte-for-byte (modulo timestamp). |
| `test_html_report_renders_with_real_fixtures` | Load a fixture JSON (collected once from real ECR, anonymised) → render HTML → assert it contains expected severity counts, repo names, and at least one package-grouped CVE row. |

### Test Data / Fixtures

```python
# tests/cloudsploit/fixtures/ecr_describe_findings_sample.json
# Captured ECR response (with attributes[]) for ONE repo+tag, anonymised.

# tests/cloudsploit/fixtures/ecr_collection_plan.yaml
# Small 3-repo plan to drive collector tests.

@pytest.fixture
def ecr_plan_path(tmp_path) -> Path:
    """Write a temp YAML plan and return its path."""
    p = tmp_path / "plan.yaml"
    p.write_text("""
region: us-east-2
concurrency: 3
repos:
  - name: alpha
    tags: [staging, production]
  - name: beta
    tags: [latest]
""")
    return p

@pytest.fixture
def mock_ecr_client():
    """AsyncMock for the aioboto3 ECR client."""
    ...
```

---

## 5. Acceptance Criteria

This feature is complete when ALL of the following are true:

- [ ] `EcrCollectionPlan.from_yaml(path)` loads a YAML file with the
      shape `{region, concurrency?, aws_id?, repos:[{name, tags:[...]}]}`
      and rejects invalid shapes with `pydantic.ValidationError`.
- [ ] `EcrScanCollector.collect(plan)` queries the ECR API exactly once
      per `(repo, tag)` until the first match per repo, and never exceeds
      `plan.concurrency` in-flight calls.
- [ ] `aws_ecr_get_image_scan_findings(..., include_attributes=True)`
      returns the raw `attributes[]` array on each finding; the default
      (`False`) keeps the existing payload byte-compatible.
- [ ] `CloudSploitToolkit.collect_ecr_findings()` is exposed as an agent
      tool (visible in `toolkit.get_tools()`).
- [ ] `CloudSploitToolkit.generate_ecr_report()` writes a self-contained
      HTML file that opens in a browser with no external requests, and
      preserves the JS report's features: search input, global severity
      filter buttons (CRITICAL/HIGH/MEDIUM), per-repo expand/collapse
      cards (CRITICAL/HIGH auto-expand), per-package blocks with CVE table.
- [ ] Repo ordering in the rendered HTML pins `navigator-api-tf` first,
      then other `navigator-*` by worst-severity counts, then alphabetic.
- [ ] When `file_manager` and `report_store` are injected, every successful
      `collect_ecr_findings()` writes one entry to the security report
      catalog with `scanner="ecr-image-scan"`, `provider="aws"`, and a
      `scope` dict containing the region (and account_id when resolvable).
      Without those kwargs, no persistence call is made and no exception
      is raised.
- [ ] No regression in CSPM scan flow:
      `CloudSploitToolkit.run_scan` and `run_compliance_scan` still pass
      their existing tests; `SeverityLevel(OK/WARN/FAIL/UNKNOWN)` and
      `ScanResult` are untouched.
- [ ] Inspector v2 is **not** called from any code path in this FEAT
      (grep for `inspector2`, `inspector_` in the new modules → zero hits).
- [ ] CloudSploit ECR config plugins (`ecrRepositoryPolicy`,
      `ecrRepositoryHasImageScans`, `ecrRepositoryEncrypted`, etc.) remain
      callable via `run_scan(plugins=[...])` — no change to plugin
      handling.
- [ ] All unit tests pass (`pytest packages/ai-parrot-tools/tests/cloudsploit/ -v`).
- [ ] No breaking changes to the public APIs of `CloudSploitToolkit`,
      `ECRToolkit`, `ReportGenerator`, or any model class.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying them.

### Verified Imports

```python
# Core toolkit base class — re-exported from parrot.tools.toolkit
from parrot_tools.toolkit import AbstractToolkit
# verified: packages/ai-parrot-tools/src/parrot_tools/toolkit.py:2

# tool_schema decorator
from parrot_tools.decorators import tool_schema
# verified: packages/ai-parrot-tools/src/parrot_tools/decorators.py:2
# canonical impl: packages/ai-parrot/src/parrot/tools/decorators.py:37

# AWS async client wrapper
from parrot.interfaces.aws import AWSInterface

…(truncated)…
