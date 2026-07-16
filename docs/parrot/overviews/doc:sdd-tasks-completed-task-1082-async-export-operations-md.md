---
type: Wiki Overview
title: 'TASK-1082: Async export operations (findings report + SBOM export)'
id: doc:sdd-tasks-completed-task-1082-async-export-operations-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements the four async export operations (Spec Module 4, §3). These kick
  off asynchronous S3 exports (findings report or SBOM) and provide polling methods.
  Designed for qworker-driven offline analysis and SBOM → vector-store ingestion pipelines.
relates_to:
- concept: mod:parrot.interfaces.aws
  rel: mentions
---

# TASK-1082: Async export operations (findings report + SBOM export)

**Feature**: FEAT-161 — AWS Inspector Toolkit (Inspector2)
**Spec**: `sdd/specs/inspector-toolkit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1079
**Assigned-to**: unassigned

---

## Context

Implements the four async export operations (Spec Module 4, §3). These kick off asynchronous S3 exports (findings report or SBOM) and provide polling methods. Designed for qworker-driven offline analysis and SBOM → vector-store ingestion pipelines.

---

## Scope

- Implement `aws_inspector_create_findings_report` — calls `inspector2:CreateFindingsReport`, returns `{report_id: str, status: str}`.
- Implement `aws_inspector_get_findings_report_status` — calls `inspector2:GetFindingsReportStatus`; `ResourceNotFoundException` → `{status: "NOT_FOUND"}` instead of raising.
- Implement `aws_inspector_create_sbom_export` — calls `inspector2:CreateSbomExport`, returns `{report_id: str, status: str}`.
- Implement `aws_inspector_get_sbom_export` — calls `inspector2:GetSbomExport`; same `ResourceNotFoundException` handling.
- Write unit tests for create + poll + not-found handling.

**NOT in scope**: Direct reads (TASK-1080), composite reads (TASK-1081), package wiring (TASK-1083).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/aws/inspector.py` | MODIFY | Replace export method stubs |
| `packages/ai-parrot-tools/tests/aws/test_inspector_toolkit.py` | MODIFY | Add export operation tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# All imports from TASK-1079 skeleton (already in file):
from __future__ import annotations
from typing import Any, Dict, Optional
from botocore.exceptions import ClientError
from parrot.interfaces.aws import AWSInterface
from ..decorators import tool_schema
from ..toolkit import AbstractToolkit
```

### Existing Signatures to Use

```python
# AWSInterface async context manager (packages/ai-parrot/src/parrot/interfaces/aws.py:22)
async with self.aws.client("inspector2") as ins:
    response = await ins.create_findings_report(...)

# Error handling pattern (securityhub.py:176-180):
except ClientError as e:
    error_code = e.response["Error"].get("Code", "Unknown")
    raise RuntimeError(f"AWS Inspector error ({error_code}): {e}") from e

# ResourceNotFoundException special handling (from §7):
# Catch ResourceNotFoundException separately and return {status: "NOT_FOUND"}
```

### Inspector2 Export API Signatures (from AWS docs)

```python
# create_findings_report
response = await ins.create_findings_report(
    filterCriteria={...},  # optional
    reportFormat="JSON",   # CSV|JSON
    s3Destination={
        "bucketName": str,
        "keyPrefix": str,
        "kmsKeyArn": str,
    },
)
# Returns: {"reportId": str}

# get_findings_report_status
response = await ins.get_findings_report_status(reportId=report_id)
# Returns: {"destination": {...}, "errorCode": str|None, "errorMessage": str|None,
#           "filterCriteria": {...}, "reportId": str, "status": str}
# Status: SUCCEEDED|IN_PROGRESS|CANCELLED|FAILED

# create_sbom_export
response = await ins.create_sbom_export(
    reportFormat="CYCLONEDX_1_4",  # CYCLONEDX_1_4|SPDX_2_3
    resourceFilterCriteria={...},   # optional
    s3Destination={
        "bucketName": str,
        "keyPrefix": str,
        "kmsKeyArn": str,
    },
)
# Returns: {"reportId": str}

# get_sbom_export
response = await ins.get_sbom_export(reportId=report_id)
# Returns: {"errorCode": str|None, "errorMessage": str|None,
#           "filterCriteria": {...}, "format": str, "reportId": str,
#           "s3Destination": {...}, "status": str}
```

### Does NOT Exist

- ~~`InspectorToolkit._poll_report`~~ — no polling helper exists; each poll method is a single API call, not an auto-poller.
- ~~Auto-polling/wait loop~~ — polling is the agent's responsibility; these methods return status once.

---

## Implementation Notes

### `create_findings_report` Logic

1. Build `s3Destination` dict from `s3_bucket`, `s3_key_prefix`, `kms_key_arn`.
2. Optionally build `filterCriteria` using `_build_filter_criteria(severity=..., resource_type=...)` if filters provided.
3. Call `inspector2:CreateFindingsReport`.
4. Return `{report_id: str, status: "IN_PROGRESS"}`.

### `get_findings_report_status` Logic

1. Call `inspector2:GetFindingsReportStatus(reportId=report_id)`.
2. If `ResourceNotFoundException` → return `{report_id: report_id, status: "NOT_FOUND"}`.
3. Otherwise, return normalized status dict.

### `create_sbom_export` Logic

1. Build `s3Destination` from inputs.
2. Optionally build `resourceFilterCriteria` if `resource_type` or `repository_name` provided.
3. Call `inspector2:CreateSbomExport`.
4. Return `{report_id: str, status: "IN_PROGRESS"}`.

### `get_sbom_export` Logic

1. Call `inspector2:GetSbomExport(reportId=report_id)`.
2. If `ResourceNotFoundException` → return `{report_id: report_id, status: "NOT_FOUND"}`.
3. Otherwise, return normalized status dict with `s3_destination`, `report_format`, `status`.

### Key Constraints

- `ResourceNotFoundException` must NOT raise — return `{status: "NOT_FOUND"}` (this is expected during polling).
- Other `ClientError` subtypes → standard `RuntimeError` translation.
- `report_format` for findings: `"JSON"` or `"CSV"`.
- `report_format` for SBOM: `"CYCLONEDX_1_4"` or `"SPDX_2_3"`.

---

## Acceptance Criteria

- [ ] `create_findings_report` calls the correct API and returns `{report_id, status}`.
- [ ] `get_findings_report_status` returns `{status: "NOT_FOUND"}` on `ResourceNotFoundException`.
- [ ] `create_sbom_export` calls the correct API and returns `{report_id, status}`.
- [ ] `get_sbom_export` returns `{status: "NOT_FOUND"}` on `ResourceNotFoundException`.
- [ ] All other `ClientError` → `RuntimeError("AWS Inspector error (...): ...")`.
- [ ] No auto-polling or wait loops.
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/aws/test_inspector_toolkit.py -v -k "report or sbom"`.

---

## Test Specification

```python
class TestCreateFindingsReport:
    @pytest.mark.asyncio
    async def test_returns_report_id(self, toolkit):
        """Returns report_id from AWS response."""
        ...

    @pytest.mark.asyncio
    async def test_client_error_raised(self, toolkit):
        """ClientError → RuntimeError."""
        ...


class TestGetFindingsReportStatus:
    @pytest.mark.asyncio
    async def test_not_found_returns_status(self, toolkit):
        """ResourceNotFoundException → {status: 'NOT_FOUND'}."""
        ...

    @pytest.mark.asyncio
    async def test_succeeded_status(self, toolkit):
        """Normal response returns status and details."""
        ...


class TestCreateSbomExport:
    @pytest.mark.asyncio
    async def test_returns_report_id(self, toolkit):
        """Returns report_id from AWS response."""
        ...


class TestGetSbomExport:
    @pytest.mark.asyncio
    async def test_not_found_returns_status(self, toolkit):
        """ResourceNotFoundException → {status: 'NOT_FOUND'}."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/inspector-toolkit.spec.md` (especially §3 Module 4 and §7 Error Handling Matrix)
2. **Check dependencies** — verify TASK-1079 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm the skeleton and `_build_filter_criteria` exist
4. **Update status** in `sdd/tasks/index/inspector-toolkit.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1082-async-export-operations.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker agent
**Date**: 2026-05-12
**Notes**: Implemented all 4 async export operations:
- `create_findings_report` + `get_findings_report_status` (with ResourceNotFoundException → NOT_FOUND)
- `create_sbom_export` + `get_sbom_export` (same NOT_FOUND handling)
All 6 export tests pass. No auto-polling. ResourceNotFoundException correctly handled.

**Deviations from spec**: none
