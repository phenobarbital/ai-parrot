---
type: feature
base_branch: dev
---

# Feature Specification: CloudSploit ECR Image-Scan Collector & Interactive Report

**Feature ID**: FEAT-165
**Date**: 2026-05-12
**Author**: Jesús Lara
**Status**: draft
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
# verified: packages/ai-parrot/src/parrot/interfaces/aws.py:22

# Persistence mixin + kwargs helper
from parrot_tools.security.persistence import (
    ReportPersistenceMixin,
    pop_persistence_kwargs,
)
# verified: packages/ai-parrot-tools/src/parrot_tools/security/persistence.py:37,58

# Existing cloudsploit models (do NOT modify — only ADD siblings)
from parrot_tools.cloudsploit.models import (
    CloudSploitConfig,
    SeverityLevel,        # OK/WARN/FAIL/UNKNOWN — NOT for ECR
    ScanFinding,
    ScanResult,
    ScanSummary,
)
# verified: packages/ai-parrot-tools/src/parrot_tools/cloudsploit/models.py:15-203

# Existing ECR wrapper (extend, don't replace)
from parrot_tools.aws.ecr import ECRToolkit, GetImageScanFindingsInput
# verified: packages/ai-parrot-tools/src/parrot_tools/aws/ecr.py:39,66

# Existing report generator (extend, don't replace)
from parrot_tools.cloudsploit.reports import ReportGenerator
# verified: packages/ai-parrot-tools/src/parrot_tools/cloudsploit/reports.py:19

# Botocore error class (used for ScanNotFoundException handling)
from botocore.exceptions import ClientError
# verified: packages/ai-parrot-tools/src/parrot_tools/aws/ecr.py:8

# PyYAML (transitive dep — already used in parrot_tools/multidb.py, database/cache.py, etc.)
import yaml
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):
    input_class: Optional[Type[BaseModel]] = None       # line 219
    return_direct: bool = False                          # line 220
    base_url: str = BASE_STATIC_URL                      # line 223
    exclude_tools: tuple[str, ...] = ()                  # line 228
    tool_prefix: Optional[str] = None                    # line 242
    prefix_separator: str = "_"                          # line 245

    def __init__(self, **kwargs):                        # line 247
        # Sets self.logger = logging.getLogger(self.__class__.__name__)
        ...
    async def start(self) -> None: ...                   # line 263
    async def stop(self) -> None: ...                    # line 270
    async def cleanup(self) -> None: ...                 # line 277

# packages/ai-parrot-tools/src/parrot_tools/cloudsploit/toolkit.py
class CloudSploitToolkit(ReportPersistenceMixin, AbstractToolkit):
    def __init__(
        self,
        config: Optional[CloudSploitConfig] = None,
        **kwargs,
    ):                                                   # line 34
        self.file_manager, self.report_store = pop_persistence_kwargs(kwargs)
        super().__init__(**kwargs)
        self.config = config or CloudSploitConfig()
        self.executor = CloudSploitExecutor(self.config)
        self.parser = ScanResultParser()
        self.report_generator = ReportGenerator()
        self.comparator = ScanComparator()
        self._last_result: Optional[ScanResult] = None

    async def _persist_after_scan(
        self, result: ScanResult, *, framework: Optional[str],
    ) -> None: ...                                       # line 49

    def _resolve_config(self, per_call: Optional[str]) -> Optional[str]:
        ...                                              # line 75

    async def run_scan(...) -> ScanResult: ...           # line 105
    async def run_compliance_scan(...) -> ScanResult: ...# line 157
    async def get_summary(self) -> dict: ...             # line 204
    async def generate_report(...) -> str: ...           # line 215
    async def compare_scans(...) -> ComparisonReport: ...# line 249
    async def list_findings(...) -> list[dict]: ...      # line 276

# packages/ai-parrot/src/parrot/interfaces/aws.py
class AWSInterface:
    def __init__(
        self,
        aws_id: str = "default",
        region_name: Optional[str] = None,
        credentials: Optional[dict] = None,
        **kwargs,
    ): ...                                               # line 35
    @property
    def region(self) -> str: ...                         # line 101

    @asynccontextmanager
    async def client(
        self, service_name: str, **kwargs
    ) -> AsyncIterator[Any]: ...                         # line 106

# packages/ai-parrot-tools/src/parrot_tools/aws/ecr.py
class ECRToolkit(AbstractToolkit):
    def __init__(
        self,
        aws_id: str = "default",
        region_name: Optional[str] = None,
        **kwargs,
    ): ...                                               # line 76

    @tool_schema(GetImageScanFindingsInput)
    async def aws_ecr_get_image_scan_findings(
        self,
        repository_name: str,
        image_tag: str = "latest",
    ) -> Dict[str, Any]: ...                             # line 188

class GetImageScanFindingsInput(BaseModel):
    repository_name: str                                 # line 42
    image_tag: str = "latest"                            # line 45

# packages/ai-parrot-tools/src/parrot_tools/cloudsploit/models.py
class SeverityLevel(str, Enum):
    OK = "OK"; WARN = "WARN"; FAIL = "FAIL"; UNKNOWN = "UNKNOWN"  # line 15-20

class CloudSploitConfig(BaseModel):
    config_file: Optional[str] = Field(default=None, ...)  # line 154
    aws_region: str = Field(default=AWS_DEFAULT_REGION or "us-east-1", ...)  # line 128
    aws_default_region: str = Field(default=AWS_DEFAULT_REGION or "us-east-1", ...)  # line 132
    results_dir: Optional[str] = Field(default=None, ...)  # line 173

# packages/ai-parrot-tools/src/parrot_tools/cloudsploit/reports.py
class ReportGenerator:
    def __init__(self):                                  # line 26
        self.env = Environment(
            loader=FileSystemLoader(<templates_dir>),
            autoescape=True,
        )                                                # line 28-32

    async def generate_html(
        self, result: ScanResult,
        output_path: Optional[str] = None,
        max_findings: int = DEFAULT_MAX_FINDINGS,
    ) -> str: ...                                        # line 63

    async def generate_pdf(...) -> str: ...              # line 100
    async def generate_comparison_html(...) -> str: ...  # line 134

# packages/ai-parrot-tools/src/parrot_tools/security/persistence.py
def pop_persistence_kwargs(
    kwargs: dict[str, Any],
) -> tuple[FileManagerInterface | None, SecurityReportStore | None]:
    ...                                                  # line 37

class ReportPersistenceMixin:
    file_manager: FileManagerInterface | None = None     # line 73
    report_store: SecurityReportStore | None = None      # line 74
    parser_version: str = "1.0.0"                        # line 75

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
    ) -> ReportRef | None: ...                           # line 77
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `EcrScanCollector.collect` | `AWSInterface.client("ecr")` | async ctx mgr → `describe_image_scan_findings` | `parrot/interfaces/aws.py:106`, `parrot_tools/aws/ecr.py:196` |
| `EcrScanCollector` | `aws_ecr_get_image_scan_findings(..., include_attributes=True)` | direct call OR replicated inline aioboto3 call | `parrot_tools/aws/ecr.py:188` (after Module 3 ext) |
| `CloudSploitToolkit.collect_ecr_findings` | `EcrScanCollector.collect` | composition (self.ecr_collector) | new file |
| `CloudSploitToolkit.collect_ecr_findings` | `_persist_report(scanner="ecr-image-scan", ...)` | mixin method call | `security/persistence.py:77` |
| `CloudSploitToolkit.generate_ecr_report` | `ReportGenerator.generate_ecr_html` | composition (self.report_generator) | `cloudsploit/reports.py` (after Module 5 ext) |
| `ReportGenerator.generate_ecr_html` | `Environment.get_template("ecr_scan_report.html")` | Jinja2 lookup | `cloudsploit/reports.py:28-32` |
| `CloudSploitConfig.ecr_plan_file` | `CloudSploitToolkit._resolve_ecr_plan` | precedence resolver | new helper (mirrors `_resolve_config` at toolkit.py:75) |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot_tools.cloudsploit.EcrCollector`~~ — name is `EcrScanCollector`,
  module file is `ecr_collector.py`.
- ~~`SeverityLevel.CRITICAL`~~ — `SeverityLevel` is OK/WARN/FAIL/UNKNOWN.
  ECR severities live in the **new** `EcrSeverity` enum.
- ~~`ScanFinding` for ECR data~~ — `ScanFinding` is for CSPM (CloudSploit
  plugin) findings; ECR uses the new `EcrScanFinding`.
- ~~`ReportGenerator.generate_ecr_pdf`~~ — out of scope (HTML only in v1).
- ~~`xhtml2pdf` for the ECR report~~ — incompatible with the template's
  grid/gradient/JS features.
- ~~`InspectorToolkit.collect_*` calls from this FEAT~~ — Inspector v2 is
  out of scope; the collector calls ECR directly.
- ~~`CloudSploitExecutor` for ECR scans~~ — the executor only shells out to
  the CloudSploit Node.js CLI; it does NOT call any AWS API directly.
- ~~`@register_agent` on the new toolkit~~ — agents live in
  `packages/ai-parrot/src/parrot/bots/agents/`, not in tools. We are
  extending an existing toolkit, not registering a new agent.
- ~~Hard-coded repo list in Python~~ — the plan loads from YAML at
  runtime (resolved in proposal Q1).
- ~~`asyncio.gather(*all_calls)` unbounded fan-out~~ — must use
  `asyncio.Semaphore(plan.concurrency)`; raw gather hits ECR rate limits.
- ~~Reading `~/.cloudsploit/aws/credentials.json` directly~~ — credentials
  flow through `AWSInterface` (navconfig `AWS_CREDENTIALS`).
- ~~`describe_image_scan_findings` requires Inspector v2~~ — false; it is
  a generic ECR endpoint. With Basic Scanning enabled it returns
  Basic-Scanning results. The JS docstring confirms: *"Works with both
  Basic Scanning and Enhanced Scanning (Inspector)"*.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **`_resolve_config` precedence pattern** (`toolkit.py:75-101`) — clone as
  `_resolve_ecr_plan(per_call)` for the new `plan` argument. Emit DEBUG log
  when per-call overrides config field.
- **`pop_persistence_kwargs(kwargs)` BEFORE `super().__init__`** — already
  in `toolkit.py:36-39`. Do NOT change this ordering when adding the new
  collaborator instance.
- **Jinja2 `Environment(FileSystemLoader(template_dir), autoescape=True)`**
  at `reports.py:28-32` — reuse the same env; only add a new template file.
- **`@tool_schema(Input)`** decorator pattern from `aws/ecr.py:93,155,187,246`
  — apply to the new `CloudSploitToolkit.collect_ecr_findings` and
  `generate_ecr_report` methods to give richer agent tool descriptions.
- **`async with self.aws.client("ecr") as ecr:`** pattern from
  `aws/ecr.py:107,161,195,254` — single-use client per call; do not cache.
- **Graceful `ScanNotFoundException`** — current wrapper at `aws/ecr.py:230-236`
  returns `{"scan_status": "NOT_FOUND", ...}`; collector treats this as
  fallback signal, not an error.
- **Async-first**: every public method on `CloudSploitToolkit` must be
  `async def` or it will not be discovered as an agent tool.
- **PEP 257 + Google-style docstrings** on every public symbol (matches
  the existing toolkit code style).

### Known Risks / Gotchas

- **ECR rate limits**. `describe_image_scan_findings` has a per-account
  rate limit (TPS). With 23 repos × up to 3 tag attempts = up to 69
  calls, even with concurrency=5 a cold run will burst.
  *Mitigation*: bound concurrency from the plan; surface
  `ThrottlingException` clearly in logs (don't silently retry — let the
  caller decide).
- **`attributes[]` shape drift**. ECR finding `attributes` is a list of
  `{key, value}` dicts; the keys `CVSS3_SCORE` and `CVSS4_SCORE` are
  AWS-version-dependent. Code must fall back: prefer `CVSS4_SCORE`, then
  `CVSS3_SCORE`, then None.
- **HTML report size**. With 23 repos × hundreds of CVEs each, the
  rendered HTML can exceed 5 MB. Browser performance is fine; just be
  aware in tests (don't snapshot full output).
- **Timestamp timezone**. JS uses `new Date().toISOString()` (UTC).
  Python `datetime.now()` is naive local — must use
  `datetime.now(tz=timezone.utc)` for `generated_at` to keep wire
  parity with the JS output.
- **Severity counts payload variability**. ECR Basic Scanning returns
  `findingSeverityCounts` with absent keys when count is 0; the JS uses
  `(c.CRITICAL||0)`. Mirror with `result.counts.get(EcrSeverity.X, 0)`.
- **Coordination with `wip: aws agent`** branch (commit `8b7eb250`).
  Surface the new methods via the standard `CloudSploitToolkit`
  registration path so the AWS agent discovers them without bespoke
  wiring.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `aioboto3` | (already required, via `parrot.interfaces.aws`) | async ECR client |
| `botocore` | (transitive via aioboto3) | `ClientError` for ECR errors |
| `pydantic` | (already required) | model validation |
| `PyYAML` | (already transitive) | `EcrCollectionPlan.from_yaml` |
| `jinja2` | (already required, via `cloudsploit/reports.py`) | HTML template |

No new dependencies must be declared in `pyproject.toml`.

---

## 8. Open Questions

### Resolved (during proposal phase — carried forward verbatim)

- [x] **¿Dónde debe vivir la lista de repos + tag-priorities?** —
  *Resolved in proposal*: YAML cargado en runtime, Pydantic-validated, path
  pasado a `collect_ecr_findings(plan=...)` o (fallback) leído desde
  `CloudSploitConfig.ecr_plan_file`. Authoritative plan ops-managed,
  outside the repo. Spec ships only `ecr_plan.example.yaml`.
- [x] **¿Soportar Basic + Enhanced Scanning en v1?** — *Resolved in
  proposal*: Solo Basic en v1. Inspector v2 está deshabilitado en la
  cuenta AWS objetivo; el endpoint `describe_image_scan_findings`
  funciona contra Basic sin requerir Inspector. Enhanced (Inspector v2)
  como FEAT seguido.
- [x] **¿El reporte HTML también necesita variante PDF?** — *Resolved in
  proposal*: Solo HTML. Las features interactivas (filtros, search,
  expand/collapse, CSS grid, gradients) son el punto. `xhtml2pdf` no
  puede renderizarlas.
- [x] **¿Dónde colocar los nuevos métodos públicos?** — *Resolved in
  proposal*: `CloudSploitToolkit` (`cloudsploit/toolkit.py`).
  `ECRToolkit` queda intocado salvo la extensión retrocompatible
  `include_attributes=True` en `aws_ecr_get_image_scan_findings`.

### Unresolved (defer to implementation)

*None.* All decisions necessary to scaffold tasks are resolved.

> Implementation-time judgement calls (e.g. exact default for
> `concurrency`, exact wording of error messages) are intentionally NOT
> open questions — they are routine choices the implementing agent makes
> with reference to the patterns in §7.

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` (sequential tasks in one worktree).
- **Rationale**: Modules 1–8 share `cloudsploit/` and modify
  `cloudsploit/toolkit.py` plus `aws/ecr.py`. Running them in parallel
  worktrees would conflict on those files. Sequential order also lets
  each task ship its own tests, building confidence in the chain.
- **Suggested order** (Module 1 → Module 8): models → collector →
  ecr wrapper extension → template → report method → toolkit methods →
  config field → exports + example.
- **Cross-feature dependencies**: none. FEAT-160 (config-support) and
  TASK-1110 (catalog mixin) are already merged on `dev`.
- **Worktree creation**:
  ```bash
  git worktree add -b feat-165-cloudsploit-ecr \
    .claude/worktrees/feat-165-cloudsploit-ecr HEAD
  ```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-12 | Jesús Lara | Initial draft from FEAT-165 proposal |
