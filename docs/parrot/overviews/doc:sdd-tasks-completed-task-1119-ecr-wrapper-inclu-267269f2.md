---
type: Wiki Overview
title: 'TASK-1119: Extend `aws_ecr_get_image_scan_findings` with `include_attributes`'
id: doc:sdd-tasks-completed-task-1119-ecr-wrapper-include-attributes-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 3** of the spec (`sdd/specs/cloudsploit-ecr.spec.md`
  §3).
relates_to:
- concept: mod:parrot.interfaces.aws
  rel: mentions
- concept: mod:parrot_tools.aws.ecr
  rel: mentions
---

# TASK-1119: Extend `aws_ecr_get_image_scan_findings` with `include_attributes`

**Feature**: FEAT-165 — CloudSploit ECR Image-Scan Collector & Interactive Report
**Spec**: `sdd/specs/cloudsploit-ecr.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 3** of the spec (`sdd/specs/cloudsploit-ecr.spec.md` §3).

The existing wrapper drops ECR's `attributes[]` array (which carries
`package_name`, `package_version`, `fixed_in_versions`,
`CVSS3_SCORE`/`CVSS4_SCORE`) at `aws/ecr.py:206-214`. The new collector
(TASK-1120) and report (TASK-1122) need that payload to group CVEs by
package and render fix versions / CVSS scores.

A new opt-in flag preserves wire compatibility for every existing caller —
default `False` keeps the current shape byte-for-byte.

---

## Scope

- Add `include_attributes: bool = Field(False, description="...")` to
  `GetImageScanFindingsInput` Pydantic model (ecr.py:39).
- Add `include_attributes: bool = False` parameter to
  `aws_ecr_get_image_scan_findings` method (ecr.py:188).
- When `True`, propagate the raw `attributes` list on each finding under a
  new `attributes` key alongside the existing `name`, `severity`,
  `description`, `uri`.
- Default behaviour (`False`) MUST produce the exact same payload as today.
- Add unit tests covering the default and the new flag.

**NOT in scope**: collector logic that consumes the new flag (TASK-1120),
report rendering (TASK-1122), changes to other ECRToolkit methods.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/aws/ecr.py` | MODIFY | Extend `GetImageScanFindingsInput` + method body |
| `packages/ai-parrot-tools/tests/aws/test_ecr_toolkit.py` | MODIFY (or CREATE if missing) | Add 2 tests — default keeps old shape; flag=True surfaces `attributes` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already present at the top of aws/ecr.py — re-use, do NOT re-import.
from __future__ import annotations
import json
from typing import Any, Dict, Optional

from botocore.exceptions import ClientError
from pydantic import BaseModel, Field
from parrot.interfaces.aws import AWSInterface
from ..decorators import tool_schema
from ..toolkit import AbstractToolkit
# Verified at: packages/ai-parrot-tools/src/parrot_tools/aws/ecr.py:5-12
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/aws/ecr.py

class GetImageScanFindingsInput(BaseModel):                     # line 39
    repository_name: str = Field(..., description="Name of the ECR repository")  # line 42
    image_tag: str = Field("latest", description="Image tag to check")           # line 45

class ECRToolkit(AbstractToolkit):                              # line 66
    @tool_schema(GetImageScanFindingsInput)                     # line 187
    async def aws_ecr_get_image_scan_findings(
        self,
        repository_name: str,
        image_tag: str = "latest",
    ) -> Dict[str, Any]:                                        # line 188
        # ...
        async with self.aws.client("ecr") as ecr:               # line 195
            response = await ecr.describe_image_scan_findings(  # line 196
                repositoryName=repository_name,
                imageId={"imageTag": image_tag},
            )
            scan = response.get("imageScanFindings", {})        # line 200
            severity_counts = scan.get("findingSeverityCounts", {})
            findings = [                                        # line 206
                {
                    "name": f.get("name"),
                    "severity": f.get("severity"),
                    "description": f.get("description"),
                    "uri": f.get("uri"),
                }
                for f in scan.get("findings", [])
            ]
            return {                                            # line 216
                "repository_name": repository_name,
                "image_tag": image_tag,
                "scan_status": response.get("imageScanStatus", {}).get("status"),
                "severity_counts": severity_counts,
                "findings": findings,
                "findings_count": len(findings),
                "total_vulnerabilities": sum(severity_counts.values()),
            }
        # except ClientError handler at line 229 returns the
        # `scan_status: "NOT_FOUND"` dict — DO NOT change that behaviour.
```

### Does NOT Exist
- ~~`f["attributes"]` as a dict~~ — ECR returns `attributes` as a **list** of `{"key": str, "value": str}` dicts (or `None`). Iterate it, do not subscript by key.
- ~~`aws_ecr_get_image_scan_findings_detailed`~~ — do NOT add a parallel method; use the flag on the existing method.
- ~~A new input schema class~~ — extend `GetImageScanFindingsInput`, do not create a sibling.

---

## Implementation Notes

### Pattern to Follow

The finding-dict comprehension already at ecr.py:206-214 is the exact line
to extend. Conditionally include the raw `attributes` list:

```python
def _finding_dict(f: dict, include_attributes: bool) -> dict:
    out = {
        "name": f.get("name"),
        "severity": f.get("severity"),
        "description": f.get("description"),
        "uri": f.get("uri"),
    }
    if include_attributes:
        # ECR returns a list of {"key": str, "value": str}, or None
        out["attributes"] = f.get("attributes") or []
    return out

findings = [_finding_dict(f, include_attributes) for f in scan.get("findings", [])]
```

You may inline the helper if you prefer; whichever keeps the diff small.

### Key Constraints

- Default `False` MUST produce a byte-identical payload to the current
  method (regression test in §Acceptance Criteria).
- `attributes` must be a `list[dict]`, never `None` — coerce missing /
  `None` to `[]`.
- Do NOT change the `ScanNotFoundException` branch (line 229-236).
- Do NOT change the `listing` path (`aws_ecr_list_repository_images`,
  line 247).
- The `@tool_schema(GetImageScanFindingsInput)` decorator must continue to
  reflect all parameters — adding a field to the Input model is the right
  surface.

### References in Codebase

- `packages/ai-parrot-tools/src/parrot_tools/aws/ecr.py:188-240` — the
  method being extended.
- `packages/ai-parrot-tools/src/parrot_tools/aws/ecr.py:39-47` — Input
  model to extend.
- Look for an existing `test_ecr_toolkit.py` under
  `packages/ai-parrot-tools/tests/aws/`. If absent, create the file
  with a minimal `@pytest.mark.asyncio` setup that mocks
  `AWSInterface.client("ecr")` (use `unittest.mock.AsyncMock`).

---

## Acceptance Criteria

- [ ] `GetImageScanFindingsInput` has a new `include_attributes: bool` field
      with default `False`.
- [ ] `aws_ecr_get_image_scan_findings(repository_name="r", image_tag="t")`
      (no flag) produces the SAME dict shape as before this task — no
      `attributes` key on findings.
- [ ] Same call with `include_attributes=True` adds an `attributes` key
      to every finding dict, whose value is the raw ECR `attributes` list
      (or `[]` when absent / None).
- [ ] `ScanNotFoundException` still returns
      `{"scan_status": "NOT_FOUND", ...}` (regression).
- [ ] `pytest packages/ai-parrot-tools/tests/aws/test_ecr_toolkit.py -v`
      passes.
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/aws/ecr.py`
      passes.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/aws/test_ecr_toolkit.py
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from parrot_tools.aws.ecr import ECRToolkit


SAMPLE_ECR_RESPONSE = {
    "imageScanStatus": {"status": "COMPLETE"},
    "imageScanFindings": {
        "findingSeverityCounts": {"CRITICAL": 1, "HIGH": 2},
        "findings": [
            {
                "name": "CVE-2024-0001",
                "severity": "CRITICAL",
                "description": "boom",
                "uri": "https://example/cve",
                "attributes": [
                    {"key": "package_name", "value": "openssl"},
                    {"key": "package_version", "value": "1.1.1"},
                    {"key": "CVSS3_SCORE", "value": "9.8"},
                ],
            },
        ],
    },
}


@pytest.fixture
def toolkit(monkeypatch):
    tk = ECRToolkit.__new__(ECRToolkit)
    tk.aws = MagicMock()

    class _CtxClient:
        async def __aenter__(self_):
            return self_
        async def __aexit__(self_, *a):
            return False
        describe_image_scan_findings = AsyncMock(return_value=SAMPLE_ECR_RESPONSE)
    tk.aws.client = MagicMock(return_value=_CtxClient())
    return tk


@pytest.mark.asyncio
async def test_default_payload_excludes_attributes(toolkit):
    result = await toolkit.aws_ecr_get_image_scan_findings("r", "t")
    f = result["findings"][0]
    assert set(f.keys()) == {"name", "severity", "description", "uri"}


@pytest.mark.asyncio
async def test_include_attributes_surfaces_raw_list(toolkit):
    result = await toolkit.aws_ecr_get_image_scan_findings(
        "r", "t", include_attributes=True,
    )
    f = result["findings"][0]
    assert "attributes" in f
    assert isinstance(f["attributes"], list)
    keys = {a["key"] for a in f["attributes"]}
    assert "package_name" in keys
    assert "CVSS3_SCORE" in keys


@pytest.mark.asyncio
async def test_include_attributes_coerces_none_to_empty(toolkit, monkeypatch):
    monkeypatch.setitem(
        SAMPLE_ECR_RESPONSE["imageScanFindings"]["findings"][0],
        "attributes",
        None,
    )
    result = await toolkit.aws_ecr_get_image_scan_findings(
        "r", "t", include_attributes=True,
    )
    assert result["findings"][0]["attributes"] == []
```

---

## Agent Instructions

1. Read the spec at `sdd/specs/cloudsploit-ecr.spec.md` (§2 Overview, §3 Module 3, §6 Codebase Contract).
2. Verify the Codebase Contract: `read` lines 39-240 of `aws/ecr.py`.
3. Extend the Input model and method per the pattern above.
4. Write the 3 unit tests in `tests/aws/test_ecr_toolkit.py` (create if needed).
5. Run `pytest packages/ai-parrot-tools/tests/aws/test_ecr_toolkit.py -v`.
6. Run `ruff check packages/ai-parrot-tools/src/parrot_tools/aws/ecr.py`.
7. Move this file to `sdd/tasks/completed/`.
8. Update `sdd/tasks/index/cloudsploit-ecr.json` task status to `done`.
9. Fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
