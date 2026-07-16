---
type: Wiki Overview
title: 'TASK-1081: Composite read operations (security posture + top vulnerable resources)'
id: doc:sdd-tasks-completed-task-1081-composite-read-operations-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements the two composite read operations (Spec Module 3, §3) that orchestrate
  multiple Inspector2 API calls to produce agent-ready summaries. These mirror the
  pattern used by `SecurityHubToolkit.aws_securityhub_get_security_score` but are
  Inspector-specific.
relates_to:
- concept: mod:parrot.interfaces.aws
  rel: mentions
---

# TASK-1081: Composite read operations (security posture + top vulnerable resources)

**Feature**: FEAT-161 — AWS Inspector Toolkit (Inspector2)
**Spec**: `sdd/specs/inspector-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1080
**Assigned-to**: unassigned

---

## Context

Implements the two composite read operations (Spec Module 3, §3) that orchestrate multiple Inspector2 API calls to produce agent-ready summaries. These mirror the pattern used by `SecurityHubToolkit.aws_securityhub_get_security_score` but are Inspector-specific.

---

## Scope

- Implement `aws_inspector_get_security_posture` — orchestrates `list_finding_aggregations(ACCOUNT)` + `list_coverage_statistics` + `batch_get_account_status`; computes weighted score `100 - (critical*10 + high*5 + medium*2 + low*1)` clamped `[0, 100]`.
- Implement `aws_inspector_list_top_vulnerable_resources` — aggregates findings by resource ARN, sorts by weighted severity, returns top N.
- Both methods accept an optional `weights` kwarg to override default severity weights.
- Write unit tests validating score math and sort order.

**NOT in scope**: Direct reads (TASK-1080), async exports (TASK-1082), package wiring (TASK-1083).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/aws/inspector.py` | MODIFY | Replace composite method stubs |
| `packages/ai-parrot-tools/tests/aws/test_inspector_toolkit.py` | MODIFY | Add composite operation tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# All imports from TASK-1079 skeleton (already in file):
from __future__ import annotations
from typing import Any, Dict, List, Optional
from botocore.exceptions import ClientError
from parrot.interfaces.aws import AWSInterface
from ..decorators import tool_schema
from ..toolkit import AbstractToolkit
```

### Existing Signatures to Use

```python
# SecurityHubToolkit.aws_securityhub_get_security_score pattern (securityhub.py:270-349):
# - Calls multiple AWS APIs within a single `async with self.aws.client(...)` block
# - Computes: penalty = critical*10 + high*5 + medium*2 + low*1
# - Score = max(0, 100 - penalty)
# - Returns structured dict with security_score, severity_counts, total_active_findings

# Inspector2 API calls needed:
# 1. list_finding_aggregations(aggregationType="ACCOUNT", ...) → severity counts
# 2. list_coverage_statistics(filterCriteria={}, groupBy="RESOURCE_TYPE") → coverage stats
# 3. batch_get_account_status() → scan type enablement status

# Direct read methods from TASK-1080 (available after that task):
# self.aws_inspector_list_findings(...)  — but composite methods should call boto3 directly
# to avoid double-normalization and to batch calls in a single client context.
```

### `get_security_posture` Output Shape (from §2)

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

### Does NOT Exist

- ~~`AbstractToolkit.get_security_score`~~ — no base-class scoring helper; implement in-toolkit.
- ~~`InspectorToolkit._compute_score`~~ — does not exist; implement scoring inline or as a private helper.

---

## Implementation Notes

### `get_security_posture` Logic

1. Open `async with self.aws.client("inspector2") as ins:`.
2. Call `list_finding_aggregations(aggregationType="ACCOUNT")` to get severity counts.
3. Call `list_coverage_statistics()` with appropriate groupBy to get coverage stats (ECR images, EC2 instances, Lambda functions scanned).
4. Call `batch_get_account_status()` to get scan type enablement.
5. Compute weighted score: `score = max(0, min(100, 100 - (c*w_c + h*w_h + m*w_m + l*w_l)))` using provided `weights` or defaults `{CRITICAL: 10, HIGH: 5, MEDIUM: 2, LOW: 1}`.
6. Return the composite dict per the output shape above.
7. Wrap in `try/except ClientError` with the standard error translation.

### `list_top_vulnerable_resources` Logic

1. Call `list_finding_aggregations(aggregationType="RESOURCE")` to get per-resource severity counts.
2. Compute weighted severity for each resource using the same weight system.
3. Sort descending by weighted severity.
4. Return top `limit` resources.
5. Apply optional `resource_type` filter.

### Key Constraints

- Both methods must use the standard `ClientError → RuntimeError` translation.
- Score clamped to `[0, 100]`.
- `weights_used` must always be included in output so the agent knows what weights were applied.

---

## Acceptance Criteria

- [ ] `get_security_posture` returns the output shape from §2 exactly.
- [ ] Score math: `100 - (10*c + 5*h + 2*m + 1*l)` clamped to `[0, 100]`.
- [ ] Custom `weights` override works correctly.
- [ ] `list_top_vulnerable_resources` returns resources sorted by weighted severity desc.
- [ ] `limit` parameter is honored.
- [ ] `ClientError → RuntimeError` pattern consistent with other methods.
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/aws/test_inspector_toolkit.py -v -k "posture or top_vulnerable"`.
- [ ] Snapshot test for `get_security_posture` output shape committed.

---

## Test Specification

```python
class TestGetSecurityPosture:
    @pytest.mark.asyncio
    async def test_score_math(self, toolkit):
        """Score = 100 - (10*c + 5*h + 2*m + 1*l) clamped [0, 100]."""
        # Mock: 2 CRITICAL, 3 HIGH, 5 MEDIUM, 10 LOW
        # Expected: 100 - (20 + 15 + 10 + 10) = 45
        ...

    @pytest.mark.asyncio
    async def test_score_clamps_to_zero(self, toolkit):
        """Score cannot go below 0."""
        # Mock: 20 CRITICAL → penalty = 200 → score = 0
        ...

    @pytest.mark.asyncio
    async def test_weights_override(self, toolkit):
        """Custom weights override defaults."""
        # Mock: 1 CRITICAL with weights={CRITICAL: 50}
        # Expected: 100 - 50 = 50
        ...

    @pytest.mark.asyncio
    async def test_output_includes_weights_used(self, toolkit):
        """Output always includes weights_used dict."""
        ...


class TestListTopVulnerableResources:
    @pytest.mark.asyncio
    async def test_sorted_by_weighted_severity(self, toolkit):
        """Resources sorted by weighted severity descending."""
        ...

    @pytest.mark.asyncio
    async def test_limit_honored(self, toolkit):
        """Only top N resources returned."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/inspector-toolkit.spec.md` (especially §2 `get_security_posture` output and §3 Module 3)
2. **Check dependencies** — verify TASK-1080 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm SecurityHubToolkit scoring pattern is still as documented
4. **Update status** in `sdd/tasks/index/inspector-toolkit.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1081-composite-read-operations.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker agent
**Date**: 2026-05-12
**Notes**: Implemented both composite operations:
- `aws_inspector_get_security_posture`: orchestrates 3 API calls, computes weighted score clamped [0, 100], returns full output shape per spec §2.
- `aws_inspector_list_top_vulnerable_resources`: aggregates by resource ARN, sorts by weighted severity descending, honors limit.
All 4 composite tests pass. Score math, clamping, weights override all verified.

**Deviations from spec**: none
