---
type: Wiki Overview
title: 'TASK-1080: Direct read operations (list_findings, aggregate, ECR image, coverage,
  account status)'
id: doc:sdd-tasks-completed-task-1080-direct-read-operations-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements the six direct read operations (Spec Module 2, §3) that wrap the
  core Inspector2 API calls. These are the workhorse methods — everything else builds
  on them. The normalized output shape defined in §2 becomes the contract for downstream
  agent prompts.
relates_to:
- concept: mod:parrot.interfaces.aws
  rel: mentions
- concept: mod:parrot_tools.aws.inspector
  rel: mentions
---

# TASK-1080: Direct read operations (list_findings, aggregate, ECR image, coverage, account status)

**Feature**: FEAT-161 — AWS Inspector Toolkit (Inspector2)
**Spec**: `sdd/specs/inspector-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1079
**Assigned-to**: unassigned

---

## Context

Implements the six direct read operations (Spec Module 2, §3) that wrap the core Inspector2 API calls. These are the workhorse methods — everything else builds on them. The normalized output shape defined in §2 becomes the contract for downstream agent prompts.

---

## Scope

- Implement `aws_inspector_list_findings` — wraps `inspector2:ListFindings` with normalized output per §2.
- Implement `aws_inspector_aggregate_findings` — wraps `inspector2:ListFindingAggregations`.
- Implement `aws_inspector_get_ecr_image_findings` — convenience wrapper that pre-filters by repository+digest/tag and adds a severity `summary`.
- Implement `aws_inspector_list_coverage` — wraps `inspector2:ListCoverage`.
- Implement `aws_inspector_get_coverage_statistics` — wraps `inspector2:ListCoverageStatistics`.
- Implement `aws_inspector_batch_get_account_status` — wraps `inspector2:BatchGetAccountStatus`.
- Implement output normalization: ISO-8601 timestamps, description ≤500 chars with `…`, ≤5 vulnerable packages with `_truncated` flag, drop `networkReachabilityDetails`, flatten `packageVulnerabilityDetails` and `resources[0]`.
- Write unit tests with mocked boto3 responses (use `unittest.mock.AsyncMock` patching `self.aws.client`).
- Write snapshot tests for `list_findings` and `get_ecr_image_findings` normalized shapes.

**NOT in scope**: Composite operations (TASK-1081), async exports (TASK-1082), package wiring (TASK-1083).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/aws/inspector.py` | MODIFY | Replace method stubs with implementations |
| `packages/ai-parrot-tools/tests/aws/test_inspector_toolkit.py` | MODIFY | Add unit + snapshot tests for direct reads |
| `packages/ai-parrot-tools/tests/aws/conftest.py` | CREATE | Shared fixtures: `fake_inspector_finding`, `fake_aggregation_response_account` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# All imports from TASK-1079's skeleton are available:
from __future__ import annotations
from typing import Any, Dict, List, Optional
from botocore.exceptions import ClientError
from pydantic import BaseModel, Field
from parrot.interfaces.aws import AWSInterface          # packages/ai-parrot/src/parrot/interfaces/aws.py:22
from ..decorators import tool_schema                     # packages/ai-parrot/src/parrot/tools/decorators.py:37
from ..toolkit import AbstractToolkit                    # packages/ai-parrot/src/parrot/tools/toolkit.py:191

# Additional stdlib imports needed for normalization:
from datetime import datetime  # for ISO-8601 conversion
```

### Existing Signatures to Use

```python
# AWSInterface async context manager pattern (packages/ai-parrot/src/parrot/interfaces/aws.py)
async with self.aws.client("inspector2") as ins:
    response = await ins.list_findings(filterCriteria={...}, maxResults=N, nextToken=token)

# _build_filter_criteria from TASK-1079 (will exist after that task completes)
# Returns a dict suitable for inspector2's filterCriteria parameter
criteria = self._build_filter_criteria(severity=severity, resource_type=resource_type, ...)

# Error handling pattern (securityhub.py:176-180):
except ClientError as e:
    error_code = e.response["Error"].get("Code", "Unknown")
    raise RuntimeError(f"AWS Inspector error ({error_code}): {e}") from e
```

### Inspector2 API Response Shapes (from AWS docs, verified)

```python
# list_findings response:
{
    "findings": [{
        "findingArn": str,
        "severity": str,                        # CRITICAL|HIGH|MEDIUM|LOW|INFORMATIONAL|UNTRIAGED
        "title": str,
        "description": str,
        "status": str,                           # ACTIVE|SUPPRESSED|CLOSED
        "fixAvailable": str,                     # YES|NO|PARTIAL
        "exploitAvailable": str,                 # YES|NO
        "inspectorScore": float,
        "epss": {"score": float},
        "firstObservedAt": datetime,
        "lastObservedAt": datetime,
        "type": str,                             # NETWORK_REACHABILITY|PACKAGE_VULNERABILITY|CODE_VULNERABILITY
        "packageVulnerabilityDetails": {
            "vulnerabilityId": str,
            "vulnerablePackages": [{"name": str, "version": str, "fixedVersion": str, "packageManager": str, "filePath": str}],
        },
        "networkReachabilityDetails": {...},     # DROP THIS in v1 normalization
        "resources": [{
            "id": str,                           # resource ARN
            "type": str,                         # AWS_ECR_CONTAINER_IMAGE, etc.
            "region": str,
            "details": {
                "awsEcrContainerImage": {
                    "repositoryName": str,
                    "imageDigest": str,
                    "imageTags": [str],
                    "registryId": str,
                    "platform": str,
                    "inUseCount": int,
                    "lastInUseAt": datetime,
                },
            },
        }],
    }],
    "nextToken": str | None,
}
```

### Does NOT Exist

- ~~`InspectorToolkit._normalize_finding`~~ — does not exist yet; must be created in this task (private helper).
- ~~`InspectorToolkit._normalize_findings`~~ — does not exist yet; convenience wrapper for a list.
- ~~`moto.inspector2`~~ — moto has limited inspector2 support; use `unittest.mock.AsyncMock` to mock `self.aws.client`.

---

## Implementation Notes

### Normalization Helper

Create a private `_normalize_finding(self, raw: Dict) -> Dict` method that:
1. Extracts `finding_arn`, `severity`, `title`, `status` directly.
2. Truncates `description` to 500 chars (append `…` if cut).
3. Extracts `vulnerability_id` from `packageVulnerabilityDetails.vulnerabilityId`.
4. Maps `fixAvailable`, `exploitAvailable` to snake_case keys.
5. Extracts `inspectorScore` → `inspector_score`, `epss.score` → `epss_score`.
6. Converts `firstObservedAt`/`lastObservedAt` → ISO-8601 strings.
7. Flattens `resources[0]` into a `resource` dict; if `len(resources) > 1`, add `_multi_resource: True`.
8. For ECR images: populates `resource.ecr_image` with snake_case fields.
9. Keeps at most 5 `vulnerablePackages`; sets `vulnerable_packages_truncated: True` if more.
10. Drops `networkReachabilityDetails` entirely.

### Pagination

- `list_findings`: cap `maxResults` at 100 (AWS limit). Pass `nextToken` if provided. Return `next_token` in output.
- `list_coverage`: cap at 1000. Same pattern.
- Never auto-paginate.

### `get_ecr_image_findings` Logic

1. Build filter: `resource_type="AWS_ECR_CONTAINER_IMAGE"`, `repository_name` always set.
2. If `image_digest` provided, add `ecrImageHash` filter with `EQUALS`.
3. If `image_tag` provided (and no digest), add `ecrImageTags` filter with `EQUALS`.
4. Call `list_findings` internally (reuse `_build_filter_criteria` + the actual API call logic).
5. Compute `summary` by counting severities across returned findings.
6. Return `{image: {}, summary: {}, findings: [...], count: int, next_token: str|None}`.

---

## Acceptance Criteria

- [ ] All 6 direct read methods are implemented and return the correct normalized shapes from §2.
- [ ] `list_findings` output matches the normalized finding shape exactly.
- [ ] `description` is truncated to ≤500 chars with `…` suffix.
- [ ] `vulnerable_packages` capped at 5 with `vulnerable_packages_truncated` flag.
- [ ] `networkReachabilityDetails` is dropped from output.
- [ ] All timestamps are ISO-8601 strings.
- [ ] `get_ecr_image_findings` adds `summary` with severity counts.
- [ ] Pagination: `next_token` returned when AWS provides `nextToken`.
- [ ] `ClientError` → `RuntimeError("AWS Inspector error (...): ...")` pattern.
- [ ] All unit tests pass: `pytest packages/ai-parrot-tools/tests/aws/test_inspector_toolkit.py -v -k "not live"`.
- [ ] Snapshot tests committed for `list_findings` and `get_ecr_image_findings` shapes.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/aws/test_inspector_toolkit.py (additions)
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot_tools.aws.inspector import InspectorToolkit


class TestListFindings:
    @pytest.mark.asyncio
    async def test_normalizes_output(self, toolkit, fake_inspector_finding):
        """Output matches the §2 normalized shape."""
        # Mock self.aws.client to return fake_inspector_finding
        ...

    @pytest.mark.asyncio
    async def test_truncates_description(self, toolkit):
        """Description >500 chars is truncated with … suffix."""
        ...

    @pytest.mark.asyncio
    async def test_truncates_packages(self, toolkit):
        """>5 vulnerable packages → kept 5, vulnerable_packages_truncated: True."""
        ...

    @pytest.mark.asyncio
    async def test_drops_network_reachability(self, toolkit):
        """networkReachabilityDetails not present in normalized output."""
        ...

    @pytest.mark.asyncio
    async def test_pagination_returns_next_token(self, toolkit):
        """When AWS returns nextToken, it appears in next_token."""
        ...


class TestGetEcrImageFindings:
    @pytest.mark.asyncio
    async def test_adds_summary(self, toolkit, fake_inspector_finding):
        """Top-level summary aggregates severity counts."""
        ...


class TestAggregateFindingsSeverityCounts:
    @pytest.mark.asyncio
    async def test_severity_counts(self, toolkit, fake_aggregation_response_account):
        """Each row contains severity_counts dict."""
        ...


class TestClientErrorHandling:
    @pytest.mark.asyncio
    async def test_client_error_to_runtime_error(self, toolkit):
        """ClientError → RuntimeError('AWS Inspector error (Code): ...')."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/inspector-toolkit.spec.md` for full context (especially §2 normalized output shapes)
2. **Check dependencies** — verify TASK-1079 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm imports and the skeleton from TASK-1079
4. **Update status** in `sdd/tasks/index/inspector-toolkit.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1080-direct-read-operations.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker agent
**Date**: 2026-05-12
**Notes**: Implemented all 6 direct read operations. Added `_extract_aggregation_key` module-level
helper for polymorphic aggregation response handling. All 34 non-stub tests pass. Linting clean.

**Deviations from spec**: Added `_extract_aggregation_key` as a module-level private function.
