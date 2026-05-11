---
type: feature
base_branch: dev
---

# Feature Specification: AWS Inspector Toolkit (Inspector2)

**Feature ID**: FEAT-161
**Date**: 2026-05-11
**Author**: Jesus Lara
**Status**: draft
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
- [ ] No breaking changes to existing public API of any other AWS toolkit.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.**
> Every entry below was verified by reading the actual source on `dev` at the time this spec was written. Implementing agents MUST NOT reference imports, attributes, or methods not listed here without first verifying via `grep` or `read`.

### Verified Imports

```python
# Async AWS client wrapper (lives in the parrot package, not parrot_tools)
from parrot.interfaces.aws import AWSInterface
# verified at: packages/ai-parrot/src/parrot/interfaces/aws.py:22-97

# Toolkit base class
from parrot.tools.toolkit import AbstractToolkit
# verified at: packages/ai-parrot/src/parrot/tools/toolkit.py:191-367

# Pydantic-schema decorator
from parrot.tools.decorators import tool_schema
# verified at: packages/ai-parrot/src/parrot/tools/decorators.py:37-52

# Pydantic v2 (confirmed: 2.12.5 in packages/ai-parrot/pyproject.toml)
from pydantic import BaseModel, Field

# AWS SDK error type
from botocore.exceptions import ClientError
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/interfaces/aws.py
class AWSInterface:
    def __init__(
        self,
        aws_id: str = 'default',
        region_name: Optional[str] = None,
        credentials: Optional[Dict[str, Any]] = None,
        **kwargs,
    ): ...                                                          # lines 22-…

    @asynccontextmanager
    async def client(self, service_name: str, **kwargs) -> AsyncIterator[Any]: ...
        # async context manager — usage: `async with self.aws.client("inspector2") as ins: ...`

    @asynccontextmanager
    async def resource(self, service_name: str, **kwargs) -> AsyncIterator[Any]: ...

    async def validate_credentials(self) -> bool: ...

# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit:
    exclude_tools: tuple[str, ...] = ()   # subclasses override to hide methods

    def __init__(self, **kwargs):                                   # lines 191-…
        self.return_direct = kwargs.get('return_direct', self.return_direct)
        self.base_url = kwargs.get('base_url', self.base_url)
        self._tool_cache: Dict[str, ToolkitTool] = {}
        self._tools_generated = False
        self.logger = logging.getLogger(self.__class__.__name__)

    def get_tools(
        self,
        permission_context: Optional["PermissionContext"] = None,
        resolver: Optional["AbstractPermissionResolver"] = None,
    ) -> List[AbstractTool]: ...
        # auto-discovers public async methods; skips `_`-prefixed names and `exclude_tools` entries

# packages/ai-parrot/src/parrot/tools/decorators.py
def tool_schema(schema: Type[BaseModel], description: Optional[str] = None):
    """Decorator to specify a custom argument schema for a toolkit method."""
    def decorator(func):
        func._args_schema = schema
        func._tool_description = description or func.__doc__ or f"Tool: {func.__name__}"
        return func
    return decorator
```

### Reference Toolkits (pattern to follow exactly)

```python
# packages/ai-parrot-tools/src/parrot_tools/aws/securityhub.py:55-349
class SecurityHubToolkit(AbstractToolkit):
    def __init__(
        self,
        aws_id: str = "default",
        region_name: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.aws = AWSInterface(aws_id=aws_id, region_name=region_name, **kwargs)

    @tool_schema(GetSecurityScoreInput)
    async def aws_securityhub_get_security_score(self) -> Dict[str, Any]:
        """Composite multi-call: get_findings + get_enabled_standards.
        Returns: {"security_score": int, "severity_counts": {...}, ...}"""
        ...

# Error handling pattern (securityhub.py:176-180; identical in s3.py:229-233)
except ClientError as e:
    error_code = e.response["Error"].get("Code", "Unknown")
    raise RuntimeError(
        f"AWS SecurityHub error ({error_code}): {e}"
    ) from e
# → InspectorToolkit MUST use:
#   raise RuntimeError(f"AWS Inspector error ({error_code}): {e}") from e

# packages/ai-parrot-tools/src/parrot_tools/aws/s3.py:47-350
class S3Toolkit(AbstractToolkit):
    # Constructor identical to SecurityHubToolkit (lines 57-68)
    @tool_schema(AnalyzeBucketSecurityInput)
    async def aws_s3_analyze_bucket_security(self, bucket_name: str) -> Dict[str, Any]: ...
    @tool_schema(FindPublicBucketsInput)
    async def aws_s3_find_public_buckets(self) -> Dict[str, Any]: ...
```

### AWS Toolkit Sibling Layout (verified)

`packages/ai-parrot-tools/src/parrot_tools/aws/`:

```
__init__.py                cloudwatch.py     documentdb.py    ec2.py
ecr.py                     ecs.py            eks.py           guardduty.py
iam.py                     lambda_func.py    rds.py           route53.py
s3.py                      securityhub.py
```

`inspector.py` will be the **15th** sibling. There is no `policies/` directory yet.

### Integration Points

| New Component                              | Connects To                            | Via                                  | Verified At                                                                       |
|--------------------------------------------|----------------------------------------|--------------------------------------|------------------------------------------------------------------------------------|
| `InspectorToolkit.__init__`                | `AWSInterface(aws_id, region_name, …)` | construction                         | `packages/ai-parrot/src/parrot/interfaces/aws.py:22`                              |
| every operation                            | `self.aws.client("inspector2")`        | `async with` context manager         | `packages/ai-parrot/src/parrot/interfaces/aws.py` (async context manager method) |
| `@tool_schema(<InputModel>)`               | method binding                         | decorator                            | `packages/ai-parrot/src/parrot/tools/decorators.py:37`                            |
| auto-discovery                             | `AbstractToolkit.get_tools()`          | inherited                            | `packages/ai-parrot/src/parrot/tools/toolkit.py:191`                              |
| `parrot_tools.aws` re-export               | `InspectorToolkit`                     | `__init__.py` edit                   | `packages/ai-parrot-tools/src/parrot_tools/aws/__init__.py`                       |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot_tools/aws/inspector.py`~~ — no pre-existing inspector module; clean slate.
- ~~`InspectorToolkit`~~ — class does not yet exist anywhere in the repo (grep confirms zero references to "inspector" under `packages/ai-parrot-tools/src/`).
- ~~`parrot_tools/aws/policies/`~~ — directory does not exist; will be **created** by this feature, establishing the IAM sidecar convention.
- ~~`*_toolkit_policy.json`~~ — no existing IAM policy sidecar file in any AWS toolkit. The Inspector spec is the first to ship one.
- ~~`aioboto3` in `pyproject.toml`~~ — `aioboto3` is **transitive** (via `aiobotocore`/`boto3` chain) and **not** declared as a direct dependency. If new code imports `aioboto3` directly, declare it (see §7 Known Risks).
- ~~`parrot.tools.toolkit.AbstractToolkit.get_security_score`~~ — there is no base-class composite scoring helper; `aws_securityhub_get_security_score` is implemented in-toolkit at `securityhub.py:276-349`. The Inspector composite must be implemented the same way (in-toolkit), not by inheriting any helper.
- ~~`InspectorClassic` / `inspector` (v1) client~~ — Inspector v1 is deprecated; use `inspector2` exclusively.
- ~~`batch_update_findings` on `inspector2`~~ — not used; mutation is out of scope (see §1 Non-Goals).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Constructor signature** must match `SecurityHubToolkit` / `S3Toolkit` verbatim:
  ```python
  def __init__(self, aws_id: str = "default", region_name: Optional[str] = None, **kwargs):
      super().__init__(**kwargs)
      self.aws = AWSInterface(aws_id=aws_id, region_name=region_name, **kwargs)
  ```
- **Tool naming**: `aws_inspector_<verb>_<object>` (snake_case, prefixed). No exceptions.
- **Async only**, `Dict[str, Any]` return type for every tool.
- **Client usage**: `async with self.aws.client("inspector2") as ins: ...` — never call boto3 sync.
- **Errors**: `ClientError` → `RuntimeError(f"AWS Inspector error ({code}): {e}")` from `e`. Match the exact format used in `securityhub.py:176-180`.
- **Filter criteria builder**: implement `_build_filter_criteria(**kwargs) -> Dict[str, Any]` as a private (`_`-prefixed) method so `AbstractToolkit.get_tools()` skips it automatically. If for any reason it cannot be `_`-prefixed, add it to the class's `exclude_tools` tuple. Behavior:
  - Drop kwargs that are `None` or `"ALL"`.
  - Translate simple kwargs to `{comparison, value}`: `EQUALS` for enums, `PREFIX` for repository names ending in `*`, `CONTAINS` for `search_term`.
  - Map the simpler `status` kwarg to `findingStatus`.

### Output Normalization Rules (mandatory)

- **Truncate** `description` to 500 chars; append `…` if truncated.
- **Drop** `networkReachabilityDetails` for v1 (no `include_network` kwarg in v1).
- **Keep at most 5** `vulnerablePackages` per finding; set `vulnerable_packages_truncated: True` if more.
- **ISO-format** all timestamps (`datetime.isoformat()`).
- **Flatten** `packageVulnerabilityDetails` and `resources[0]` into top-level keys. If multiple resources are present, take the first and add `_multi_resource: True`.
- Preserve `finding_arn` so an agent can deep-link to the AWS console.

### Pagination Strategy

- `list_findings`: AWS caps `maxResults` at 100. Honor the cap. Return `next_token` in the output dict.
- `list_coverage`: AWS cap is 1000.
- **Never auto-paginate.** Each tool call returns one page. The agent (or higher-level orchestration) decides whether to continue. Auto-pagination would balloon LLM context windows.

### Error Handling Matrix

| Condition                                            | Response                                                                  |
|------------------------------------------------------|---------------------------------------------------------------------------|
| `ClientError` (generic)                              | `RuntimeError(f"AWS Inspector error ({code}): {e}") from e`               |
| `AccessDeniedException`                              | `RuntimeError` with appended hint listing the required IAM action.        |
| `ResourceNotFoundException` on report/SBOM polling   | Return `{status: "NOT_FOUND"}` — do **not** raise (polling expected).     |
| `ValidationException` from a bad filter combination  | Catch + re-raise as `RuntimeError` with the offending filter highlighted.  |
| Inspector not enabled in the region                  | Returns empty results — surface a top-level `inspector_enabled: False` hint. |

### Security & IAM Permissions

Ship `inspector_toolkit_policy.json` at `packages/ai-parrot-tools/src/parrot_tools/aws/policies/inspector_toolkit_policy.json` with:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "InspectorReadOps",
      "Effect": "Allow",
      "Action": [
        "inspector2:ListFindings",
        "inspector2:ListFindingAggregations",
        "inspector2:ListCoverage",
        "inspector2:ListCoverageStatistics",
        "inspector2:BatchGetAccountStatus",
        "inspector2:BatchGetFindingDetails"
      ],
      "Resource": "*"
    },
    {
      "Sid": "InspectorExports",
      "Effect": "Allow",
      "Action": [
        "inspector2:CreateFindingsReport",
        "inspector2:GetFindingsReportStatus",
        "inspector2:CreateSbomExport",
        "inspector2:GetSbomExport"
      ],
      "Resource": "*"
    }
  ]
}
```

The S3 + KMS write side of exports (`s3:PutObject`, `s3:AbortMultipartUpload`, `kms:GenerateDataKey`, `kms:Encrypt`) is documented in the README but kept as a separate sample policy so consumers can choose to expose only read ops.

### Known Risks / Gotchas

- **`moto` coverage for `inspector2` is partial** — pin unit tests to operations moto actually supports; use snapshot tests with recorded fixtures for the rest.
- **`aioboto3` is not a declared dependency.** It is currently transitive via `boto3`/`aiobotocore` but the `pyproject.toml` of `packages/ai-parrot-tools` does not list it. If implementation imports `aioboto3` directly, add it to that `pyproject.toml`. (Indirect use through `AWSInterface` is fine because `AWSInterface` lives in `ai-parrot` where the chain is already in place.)
- **No IAM policy sidecar precedent** — this feature creates the `parrot_tools/aws/policies/` directory. Future toolkits should follow the same convention; mention this in the README.
- **Pagination amplification risk**: agents may loop on `next_token` indefinitely. Document in the example that the orchestration layer is responsible for capping iterations.
- **Score weighting bias**: Inspector surfaces many low-severity OS package CVEs that don't affect the running app. Default weights `{10, 5, 2, 1}` reuse SecurityHub's; expose `weights` kwarg so callers can recalibrate. See §8 for the resolved decision.

### External Dependencies

| Package      | Version     | Reason                                                                            |
|--------------|-------------|-----------------------------------------------------------------------------------|
| `aioboto3`   | (existing)  | Already used transitively by AWS toolkits via `AWSInterface`. No new direct dep needed unless the implementation imports it directly. |
| `pydantic`   | `>=2.0`     | Already a direct dep (confirmed 2.12.5 in `packages/ai-parrot/pyproject.toml`).    |
| `moto`       | (test-time) | Already in test deps. Inspector2 coverage is partial; supplement with snapshots.  |
| `syrupy`     | (test-time) | Snapshot testing of normalized output shapes.                                      |

---

## 8. Open Questions

> Resolved questions are marked `[x]` with the rationale. Unresolved items remain `[ ]`.

- [x] **Score weights — reuse SecurityHub `{10, 5, 2, 1}` or recalibrate for Inspector?** — *Resolved*: keep `{CRITICAL: 10, HIGH: 5, MEDIUM: 2, LOW: 1}` as the default and expose a `weights` kwarg on `get_security_posture` and `list_top_vulnerable_resources`. Rationale: parity with `SecurityHubToolkit` is more valuable to agents than a per-toolkit recalibration, and the kwarg lets users override on a case-by-case basis.
- [x] **Expose `batch_get_finding_details` in v1?** — *Resolved*: no. Most enrichment (EPSS + exploit availability) already comes back in `list_findings`. If agents demonstrate the need, add `aws_inspector_get_finding_enrichment` in v2. Captured in §1 Non-Goals.
- [x] **Network reachability findings (EC2): separate method or kwarg?** — *Resolved*: defer entirely to v2 as a separate `aws_inspector_get_network_findings` method. Keeps the v1 `list_findings` output schema tight. Captured in §1 Non-Goals and §7 Output Normalization (drop `networkReachabilityDetails`).
- [x] **Suppression / status updates on findings?** — *Resolved*: out of scope for v1. Agents must not silently bury findings. Captured in §1 Non-Goals.
- [x] **IAM policy sidecar convention — establish here, or skip?** — *Resolved*: establish the convention with this toolkit. The `policies/` directory does not yet exist (verified — see §6 "Does NOT Exist"); this feature creates it and ships `inspector_toolkit_policy.json`. Future AWS toolkits should follow suit. Mention the convention in the package README.
- [ ] **Should `_build_filter_criteria` be a private (`_`-prefixed) method or added to `exclude_tools`?** — *Owner: implementer*. `AbstractToolkit.get_tools()` already skips `_`-prefixed methods, so the `_`-prefix should suffice; verify during implementation that no exclusion-list edit is needed.
- [ ] **Snapshot fixture sourcing**: where do we get a real Inspector finding to seed the snapshot tests — capture from a live account during integration testing, or hand-craft a representative dict?  — *Owner: implementer*. Decide during Module 2 implementation.

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — all five modules implemented sequentially in a single worktree. The modules form a tight dependency chain (Module 1 → 2/3/4, then 5 wires everything up) and live in a single file (`inspector.py`) plus one IAM sidecar; parallel worktrees would only generate merge conflicts.
- **Cross-feature dependencies**: none. This spec stands alone — `AWSInterface`, `AbstractToolkit`, and `@tool_schema` are all already merged on `dev`.
- **Worktree creation** (after `/sdd-task`):
  ```bash
  git checkout dev
  git worktree add -b feat-161-inspector-toolkit \
    .claude/worktrees/feat-161-inspector-toolkit HEAD
  ```

---

## Revision History

| Version | Date       | Author     | Change                                                                  |
|---------|------------|------------|-------------------------------------------------------------------------|
| 0.1     | 2026-05-11 | Jesus Lara | Initial spec; promoted from `sdd/specs/inspector-toolkit-spec.md` draft.|
