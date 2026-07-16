---
type: Wiki Overview
title: 'Feature Specification: AWS Inspector Toolkit (Inspector2)'
id: doc:sdd-specs-inspector-toolkit-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Amazon Inspector v2 (boto3 client `inspector2`) is the authoritative source
  for:'
relates_to:
- concept: mod:parrot.interfaces.aws
  rel: mentions
- concept: mod:parrot.tools.decorators
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
- concept: mod:parrot_tools.aws
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: AWS Inspector Toolkit (Inspector2)

**Feature ID**: FEAT-161
**Date**: 2026-05-11
**Author**: Jesus Lara
**Status**: approved
**Target version**: v1

---

## 1. Motivation & Business Requirements

### Problem Statement

Amazon Inspector v2 (boto3 client `inspector2`) is the authoritative source for:

- **ECR Enhanced scanning** findings (OS + language package vulnerabilities, `vulnerablePackages`, `inspectorScore`, EPSS, `fixAvailable`).
- **EC2** vulnerability + network reachability findings.
- **Lambda** standard + code findings.
- **Code Security** findings (Amazon Q-based scanning of repos / IaC).

The existing `SecurityHubToolkit` *aggregates* Inspector findings but loses granularity — no package-level detail, no EPSS, no per-finding fix info. For agent use cases (container image risk reasoning, pre-deployment scoring, SBOM-driven RAG) we need a dedicated toolkit talking directly to Inspector2.

The trigger for this spec: ECR Enhanced scanning panels in the AWS console (per-image CVE breakdown by severity) are sourced from Inspector2 and exposed via `inspector2:ListFindings` with `filterCriteria.resourceType = AWS_ECR_CONTAINER_IMAGE`. We need agents to consume the same data programmatically.

### Goals

- Stateless `InspectorToolkit` matching the established AWS toolkit pattern (`SecurityHubToolkit` / `S3Toolkit`).
- Read operations for findings, aggregations, coverage, and account status.
- Convenience operations for the most common agent use case: "give me the vulns for *this* ECR image".
- Composite "security posture" method analogous to `aws_securityhub_get_security_score`.
- Async export operations (Findings report + SBOM export) returning a report id that can be polled — enables qworker-driven offline analysis and SBOM → vector-store ingestion.

### Non-Goals (explicitly out of scope)

- **No configuration mutation.** No `update_configuration`, no `enable`/`disable` scan types. That is a deployment-time IaC concern, not an agent-time concern.
- **No write ops on findings.** No `batch_update_findings` (suppression). Agents should not silently bury findings; v1 is read-only.
- **No Delegated Administrator / Organizations** flows in v1. Single-account scope. Add in v2 if Trocdigital needs cross-account aggregation.
- **No Inspector Classic.** Deprecated.
- **No `batch_get_finding_details` exposure in v1.** Most enrichment (EPSS, exploit availability) already comes back in `list_findings`. Add `aws_inspector_get_finding_enrichment` in v2 if agents demonstrate the need.
- **No EC2 network reachability findings as a separate method in v1.** Add `aws_inspector_get_network_findings` in v2 to keep `list_findings` output schema tight.

---

## 2. Architectural Design

### Overview

`InspectorToolkit` is a stateless `AbstractToolkit` subclass that wraps the `inspector2` boto3 client through the existing `AWSInterface` async context manager. It mirrors the structure of `SecurityHubToolkit` and `S3Toolkit` exactly — same constructor signature, same `@tool_schema(InputModel)` decorator pattern, same `aws_<service>_<verb>_<object>` naming, same `ClientError → RuntimeError` translation.

The toolkit exposes 12 operations split into four groups:

1. **Direct reads** (5.1–5.6): `list_findings`, `aggregate_findings`, `list_coverage`, `get_coverage_statistics`, `batch_get_account_status`, plus the ECR-image convenience method.
2. **Composite reads** (5.7–5.8): `get_security_posture` and `list_top_vulnerable_resources` — multi-call orchestrations that produce agent-ready summaries.
3. **Async exports** (5.9–5.12): `create_findings_report` / `get_findings_report_status` and `create_sbom_export` / `get_sbom_export` — kick off + poll, designed for qworker-driven offline analysis and SBOM → vector-store ingestion.

A private `_build_filter_criteria(**kwargs)` helper translates simple keyword arguments into the verbose `filterCriteria` dict that `list_findings` and `list_finding_aggregations` consume. Output normalization mirrors `SecurityHubToolkit`: timestamps as ISO-8601 strings, descriptions truncated to 500 chars, vulnerable packages capped at 5 with a `_truncated` flag, network-reachability noise dropped.

Pagination is **explicit, never automatic** — each tool call returns one page plus a `next_token`; the agent (or higher-level orchestration) decides whether to continue. Auto-pagination would balloon LLM context windows.

### Component Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                       InspectorToolkit                            │
│                  (parrot_tools/aws/inspector.py)                  │
│                                                                   │
│  Direct reads          Composite reads        Async exports       │
│  ──────────────        ──────────────         ──────────────      │
│  list_findings         get_security_posture   create_findings_    │
│  aggregate_findings    list_top_vulnerable_     report            │
│  list_coverage           resources            get_findings_       │
│  get_coverage_                                  report_status     │
│    statistics                                 create_sbom_export  │
│  batch_get_account_                           get_sbom_export     │
│    status                                                         │
│  get_ecr_image_                                                   │
│    findings                                                       │
│                                                                   │
│              _build_filter_criteria()  (private helper)           │
└──────────────────────────────┬───────────────────────────────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │     AWSInterface     │   parrot.interfaces.aws
                    │ (async context mgr)  │   wraps aioboto3.Session
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │   inspector2 client  │
                    └──────────────────────┘
```

### Integration Points

| Existing Component                          | Integration Type | Notes                                                                                         |
|---------------------------------------------|------------------|-----------------------------------------------------------------------------------------------|
| `AWSInterface` (`parrot.interfaces.aws`)    | uses             | `async with self.aws.client("inspector2") as ins: ...` for every AWS call.                    |
| `AbstractToolkit` (`parrot.tools.toolkit`)  | extends          | Inherits `get_tools()` auto-discovery; `_build_filter_criteria` is private and auto-excluded. |
| `@tool_schema` (`parrot.tools.decorators`)  | uses             | Binds Pydantic v2 input schemas to each tool method.                                          |
| `SecurityHubToolkit`                        | reference        | Reference for error handling, output shaping, security_score composition.                     |
| `S3Toolkit`                                 | reference        | Reference for multi-call composite methods.                                                   |
| `parrot_tools.aws.__init__`                 | re-export        | Add `InspectorToolkit` to the package re-exports.                                             |

### Data Models

```python
# Pydantic v2 input schemas (one per operation). Sketch — see §3 for full set.

class ListFindingsInput(BaseModel):
    limit: int = Field(20, description="Max findings (capped at 100 by Inspector)")
    severity: str = Field("ALL", description="CRITICAL|HIGH|MEDIUM|LOW|INFORMATIONAL|UNTRIAGED|ALL")
    resource_type: Optional[str] = Field(
        None,
        description="AWS_EC2_INSTANCE|AWS_ECR_CONTAINER_IMAGE|AWS_ECR_REPOSITORY|AWS_LAMBDA_FUNCTION|CODE_REPOSITORY",
    )
    status: str = Field("ACTIVE", description="ACTIVE|SUPPRESSED|CLOSED|ALL")
    fix_available: Optional[str] = Field(None, description="YES|NO|PARTIAL")
    repository_name: Optional[str] = Field(None, description="ECR repository name filter")
    search_term: Optional[str] = Field(None, description="Substring match on title / vulnerabilityId")
    next_token: Optional[str] = Field(None, description="Pagination cursor from prior call")


class AggregateFindingsInput(BaseModel):
    aggregation_type: str = Field(
        "REPOSITORY",
        description=(
            "ACCOUNT|AMI|AWS_EC2_INSTANCE|AWS_ECR_CONTAINER|FINDING_TYPE|"
            "IMAGE_LAYER|LAMBDA_FUNCTION|LAMBDA_LAYER|PACKAGE|REPOSITORY|TITLE"
        ),
    )
    limit: int = Field(25, description="Max aggregation rows")
    severity: Optional[str] = Field(None, description="Pre-filter findings before aggregating")
    resource_type: Optional[str] = Field(None)


class GetEcrImageFindingsInput(BaseModel):
    repository_name: str = Field(..., description="ECR repository name")
    image_digest: Optional[str] = Field(None, description="sha256:... — preferred over tag")
    image_tag: Optional[str] = Field(None, description="Image tag (if digest not supplied)")
    severity: str = Field("ALL")
    limit: int = Field(50)


class ListCoverageInput(BaseModel):
    resource_type: Optional[str] = Field(None)
    scan_status: Optional[str] = Field(None, description="ACTIVE|INACTIVE")
    scan_status_reason: Optional[str] = Field(
        None,
        description="e.g. SCAN_ELIGIBILITY_EXPIRED, IMAGE_PULLED_WITH_INVALID_SCAN_TYPE",
    )
    repository_name: Optional[str] = Field(None)
    limit: int = Field(50)
    next_token: Optional[str] = Field(None)


class GetSecurityPostureInput(BaseModel):
    weights: Optional[Dict[str, int]] = Field(
        None,
        description="Override default severity weights: {CRITICAL: 10, HIGH: 5, MEDIUM: 2, LOW: 1}",
    )


class ListTopVulnerableResourcesInput(BaseModel):
    resource_type: Optional[str] = Field(None)
    limit: int = Field(10)
    weights: Optional[Dict[str, int]] = Field(None)


class CreateFindingsReportInput(BaseModel):
    s3_bucket: str = Field(...)
    s3_key_prefix: str = Field("inspector-reports/")
    kms_key_arn: str = Field(..., description="Required by Inspector for findings reports")
    report_format: str = Field("JSON", description="CSV|JSON")
    severity: Optional[str] = Field(None)
    resource_type: Optional[str] = Field(None)


class CreateSbomExportInput(BaseModel):
    s3_bucket: str = Field(...)
    s3_key_prefix: str = Field("inspector-sboms/")
    kms_key_arn: str = Field(...)
    report_format: str = Field("CYCLONEDX_1_4", description="CYCLONEDX_1_4|SPDX_2_3")
    resource_type: Optional[str] = Field(None)
    repository_name: Optional[str] = Field(None)
```

### New Public Interfaces

```python
# packages/ai-parrot-tools/src/parrot_tools/aws/inspector.py

class InspectorToolkit(AbstractToolkit):
    """Stateless toolkit wrapping Amazon Inspector v2 (inspector2)."""

    def __init__(
        self,
        aws_id: str = "default",
        region_name: Optional[str] = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.aws = AWSInterface(aws_id=aws_id, region_name=region_name, **kwargs)

    @tool_schema(ListFindingsInput)
    async def aws_inspector_list_findings(self, **kwargs) -> Dict[str, Any]: ...

    @tool_schema(AggregateFindingsInput)
    async def aws_inspector_aggregate_findings(self, **kwargs) -> Dict[str, Any]: ...

    @tool_schema(GetEcrImageFindingsInput)
    async def aws_inspector_get_ecr_image_findings(self, **kwargs) -> Dict[str, Any]: ...

    @tool_schema(ListCoverageInput)
    async def aws_inspector_list_coverage(self, **kwargs) -> Dict[str, Any]: ...

    async def aws_inspector_get_coverage_statistics(self) -> Dict[str, Any]: ...
    async def aws_inspector_batch_get_account_status(self) -> Dict[str, Any]: ...

    @tool_schema(GetSecurityPostureInput)
    async def aws_inspector_get_security_posture(self, **kwargs) -> Dict[str, Any]: ...

    @tool_schema(ListTopVulnerableResourcesInput)
    async def aws_inspector_list_top_vulnerable_resources(self, **kwargs) -> Dict[str, Any]: ...

    @tool_schema(CreateFindingsReportInput)
    async def aws_inspector_create_findings_report(self, **kwargs) -> Dict[str, Any]: ...

    async def aws_inspector_get_findings_report_status(self, report_id: str) -> Dict[str, Any]: ...

    @tool_schema(CreateSbomExportInput)
    async def aws_inspector_create_sbom_export(self, **kwargs) -> Dict[str, Any]: ...

    async def aws_inspector_get_sbom_export(self, report_id: str) -> Dict[str, Any]: ...
```

**Normalized output shape for `list_findings` (and the `findings[]` array of `get_ecr_image_findings`):**

```python
{
    "findings": [
        {
            "finding_arn": str,
            "vulnerability_id": str,        # CVE-2026-34875
            "severity": str,
            "title": str,
            "description": str,             # truncated to 500 chars (suffix '…' if cut)
            "status": str,
            "fix_available": str,           # YES|NO|PARTIAL
            "exploit_available": str,       # YES|NO
            "inspector_score": float,       # 0-10
            "epss_score": Optional[float],
            "first_observed_at": str,       # ISO-8601
            "last_observed_at": str,
            "resource": {
                "id": str,                  # ARN
                "type": str,
                "region": str,
                "ecr_image": Optional[{     # populated for AWS_ECR_CONTAINER_IMAGE
                    "repository_name": str,
                    "image_digest": str,
                    "image_tags": List[str],
                    "registry_id": str,
                    "platform": str,
                    "in_use_count": int,
                    "last_in_use_at": Optional[str],
                }],
            },
            "vulnerable_packages": [
                {
                    "name": str,
                    "version": str,
                    "fixed_in_version": Optional[str],
                    "package_manager": str,   # OS|PIP|NPM|GEM|GOMOD|...
                    "file_path": Optional[str],
                }
            ],
            "vulnerable_packages_truncated": bool,  # true if > 5 packages
        }
    ],
    "count": int,
    "next_token": Optional[str],
}
```

`get_ecr_image_findings` adds a top-level `summary`:

```python
{
    "image": {"repository_name", "image_digest", "image_tags"},
    "summary": {"CRITICAL": int, "HIGH": int, "MEDIUM": int, "LOW": int, "INFORMATIONAL": int},
    "findings": [...],   # shape above
    "count": int,
    "next_token": Optional[str],
}
```

`get_security_posture` output:

```python
{
    "security_score": int,                    # 0-100
    "severity_counts": {"CRITICAL": int, "HIGH": int, "MEDIUM": int, "LOW": int, "INFORMATIONAL": int, "UNTRIAGED": int},
    "total_active_findings": int,
    "coverage": {
        "ecr_images_scanned": int,
        "ec2_instances_scanned": int,
        "lambda_functions_scanned": int,
        "resources_with_expired_eligibility": int,
    },
    "enabled_scan_types": {
        "EC2": "ENABLED|DISABLED|SUSPENDED",
        "ECR": "...",
        "LAMBDA": "...",
        "LAMBDA_CODE": "...",
        "CODE_REPOSITORY": "...",
    },
    "weights_used": Dict[str, int],
}
```

---

## 3. Module Breakdown

### Module 1: `InspectorToolkit` skeleton + Pydantic input schemas

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/aws/inspector.py`
- **Responsibility**: Class scaffold, constructor, all `BaseModel` input schemas, `_build_filter_criteria()` private helper.
- **Depends on**: `AWSInterface`, `AbstractToolkit`, `@tool_schema` (all existing).

### Module 2: Direct read operations (5.1–5.6)

- **Path**: same file (`inspector.py`).
- **Operations**:
  - `aws_inspector_list_findings` — wraps `list_findings` with normalized output.
  - `aws_inspector_aggregate_findings` — wraps `list_finding_aggregations`.
  - `aws_inspector_get_ecr_image_findings` — convenience wrapper with summary.
  - `aws_inspector_list_coverage` — wraps `list_coverage`.
  - `aws_inspector_get_coverage_statistics` — wraps `list_coverage_statistics`.
  - `aws_inspector_batch_get_account_status` — wraps `batch_get_account_status`.
- **Depends on**: Module 1.

### Module 3: Composite read operations (5.7–5.8)

- **Path**: same file.
- **Operations**:
  - `aws_inspector_get_security_posture` — orchestrates `list_finding_aggregations(ACCOUNT)` + `list_coverage_statistics` + `batch_get_account_status`; computes weighted score `100 - (critical*10 + high*5 + medium*2 + low*1)` clamped `[0, 100]`.
  - `aws_inspector_list_top_vulnerable_resources` — aggregates by resource ARN, sorts by weighted severity, returns top N.
- **Depends on**: Module 2.

### Module 4: Async export operations (5.9–5.12)

- **Path**: same file.
- **Operations**:
  - `aws_inspector_create_findings_report` — kicks off async S3 export, returns `report_id`.
  - `aws_inspector_get_findings_report_status` — polls; `ResourceNotFoundException` returns `{status: "NOT_FOUND"}` instead of raising.
  - `aws_inspector_create_sbom_export` — kicks off CycloneDX/SPDX export.
  - `aws_inspector_get_sbom_export` — polls.
- **Depends on**: Module 1.

### Module 5: IAM policy sidecar + package wiring + example

- **Paths**:
  - `packages/ai-parrot-tools/src/parrot_tools/aws/policies/inspector_toolkit_policy.json` — new directory + file (establishes a sidecar convention; see §8 Open Questions for the decision rationale).
  - `packages/ai-parrot-tools/src/parrot_tools/aws/__init__.py` — add `InspectorToolkit` re-export.
  - `examples/aws_inspector_toolkit.py` — usage example.
  - Package README — operations table.
- **Depends on**: Module 4 (the toolkit must be implemented before re-export).

---

## 4. Test Specification

### Unit Tests

| Test                                           | Module    | Description                                                                            |
|------------------------------------------------|-----------|----------------------------------------------------------------------------------------|
| `test_build_filter_criteria_drops_none_and_all`| Module 1  | None and "ALL" kwargs are dropped from the resulting `filterCriteria` dict.            |
| `test_build_filter_criteria_enum_to_equals`    | Module 1  | Enum-style kwargs (severity, resource_type) become `[{comparison: EQUALS, value: …}]`. |
| `test_build_filter_criteria_search_term_contains` | Module 1 | `search_term="foo"` → `[{comparison: CONTAINS, value: "foo"}]`.                       |
| `test_build_filter_criteria_repo_prefix_glob`  | Module 1  | `repository_name="prod-*"` → `[{comparison: PREFIX, value: "prod-"}]`.                 |
| `test_list_findings_normalizes_output`         | Module 2  | Output matches the §2 normalized shape; description ≤500 chars; timestamps ISO-8601.   |
| `test_list_findings_truncates_packages`        | Module 2  | >5 vulnerable packages → kept 5, `vulnerable_packages_truncated: True`.                |
| `test_list_findings_drops_network_reachability`| Module 2  | `networkReachabilityDetails` not present in normalized output (v1).                    |
| `test_get_ecr_image_findings_adds_summary`     | Module 2  | Top-level `summary` aggregates severity counts from the findings array.                |
| `test_aggregate_findings_severity_counts`      | Module 2  | Each row contains `severity_counts: {critical, high, medium, low}`.                    |
| `test_get_security_posture_score_math`         | Module 3  | Score = `100 - (10*c + 5*h + 2*m + 1*l)` clamped to `[0, 100]`; weights override works.|
| `test_list_top_vulnerable_resources_sort`      | Module 3  | Resources sorted by weighted severity desc; `limit` honored.                            |
| `test_get_findings_report_status_not_found`    | Module 4  | `ResourceNotFoundException` → `{status: "NOT_FOUND"}`, no raise.                       |
| `test_client_error_to_runtime_error`           | All       | `ClientError` raised by boto3 → `RuntimeError("AWS Inspector error (Code): …")`.       |
| `test_pagination_returns_next_token`           | Module 2  | When AWS returns `nextToken`, it appears in `next_token` of the toolkit output.         |

### Integration Tests

| Test                                       | Description                                                                                         |
|--------------------------------------------|-----------------------------------------------------------------------------------------------------|
| `test_live_list_findings_ecr` (`@pytest.mark.live`) | Gated by `RUN_LIVE_AWS_TESTS=1`. Calls `list_findings` against a non-prod account.            |
| `test_live_get_security_posture` (`@pytest.mark.live`) | Gated by env var. Validates the composite call returns a parseable score and coverage.   |

### Snapshot Tests (`syrupy`)

| Test                                           | Description                                                                  |
|------------------------------------------------|------------------------------------------------------------------------------|
| `test_snapshot_list_findings_normalized_shape` | Pin the normalized output dict shape — downstream agent prompts depend on it.|
| `test_snapshot_get_security_posture_shape`     | Pin the composite output shape.                                              |

### Test Data / Fixtures

```python
# Use moto where it supports inspector2; fall back to recorded fixtures for unsupported ops.

@pytest.fixture
def fake_inspector_finding():
    """Single AWS_ECR_CONTAINER_IMAGE finding with 7 vulnerable packages
    (to exercise the >5 truncation path)."""
    return {...}  # snapshot of a real Inspector response

@pytest.fixture
def fake_aggregation_response_account():
    """list_finding_aggregations(aggregationType=ACCOUNT) response with
    severity counts for one account."""
    return {...}
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `InspectorToolkit` class exists at `packages/ai-parrot-tools/src/parrot_tools/aws/inspector.py` and is re-exported from `parrot_tools/aws/__init__.py`.
- [ ] All 12 operations in §2 (`aws_inspector_*`) are implemented and decorated with `@tool_schema(<InputModel>)` where appropriate.
- [ ] `_build_filter_criteria` is a private (`_`-prefixed) method and is excluded from `get_tools()` discovery.
- [ ] All unit tests pass (`pytest packages/ai-parrot-tools/tests/aws/test_inspector_toolkit.py -v`).
- [ ] Snapshot tests for normalized output shapes are committed and pass.
- [ ] Live integration tests (gated by `RUN_LIVE_AWS_TESTS=1`) pass against a non-prod account.
- [ ] `inspector_toolkit_policy.json` IAM policy sidecar is shipped at `packages/ai-parrot-tools/src/parrot_tools/aws/policies/inspector_toolkit_policy.json` containing exactly the IAM actions listed in §7.
- [ ] No mutation operations exist on the toolkit (no `update_*`, no `enable_*`, no `batch_update_findings`).
- [ ] No auto-pagination — every paginated op returns `next_token` and stops.
- [ ] Output normalization rules from §7 are enforced: ISO-8601 timestamps, descriptions ≤500 chars, ≤5 vulnerable packages with `_truncated` flag, `networkReachabilityDetails` dropped.
- [ ] `ClientError → RuntimeError` translation matches the existing `securityhub.py` pattern (see §6 Codebase Contract).
- [ ] `ResourceNotFoundException` on report/SBOM polling returns `{status: "NOT_FOUND"}` instead of raising.
- [ ] Usage example added at `examples/aws_inspector_toolkit.py` and the package README's toolkit table is updated.

…(truncated)…
