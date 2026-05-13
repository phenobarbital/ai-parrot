# TASK-1083: IAM policy sidecar + package wiring + example

**Feature**: FEAT-161 — AWS Inspector Toolkit (Inspector2)
**Spec**: `sdd/specs/inspector-toolkit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1080, TASK-1081, TASK-1082
**Assigned-to**: unassigned

---

## Context

Wires up the completed `InspectorToolkit` into the `parrot_tools.aws` package, ships the IAM policy sidecar (establishing a new convention), adds a usage example, and updates the package README. This is the final task that makes the toolkit discoverable and documented.

Implements Spec Module 5 (§3).

---

## Scope

- Create `inspector_toolkit_policy.json` IAM policy sidecar at the specified path.
- Create the `policies/` directory under `parrot_tools/aws/`.
- Add `InspectorToolkit` re-export to `parrot_tools/aws/__init__.py`.
- Create `examples/aws_inspector_toolkit.py` usage example.
- Update the package README's toolkit table to include Inspector.
- Run the full test suite to confirm no regressions.

**NOT in scope**: Any changes to the toolkit implementation itself (those are TASK-1079 through TASK-1082).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/aws/policies/inspector_toolkit_policy.json` | CREATE | IAM policy sidecar |
| `packages/ai-parrot-tools/src/parrot_tools/aws/__init__.py` | MODIFY | Add InspectorToolkit re-export |
| `examples/aws_inspector_toolkit.py` | CREATE | Usage example |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# packages/ai-parrot-tools/src/parrot_tools/aws/__init__.py (current state):
from .route53 import Route53Toolkit
from .ecs import ECSToolkit
from .cloudwatch import CloudWatchToolkit
from .s3 import S3Toolkit
from .guardduty import GuardDutyToolkit
from .ec2 import EC2Toolkit
from .ecr import ECRToolkit
from .iam import IAMToolkit
from .securityhub import SecurityHubToolkit
from .rds import RDSToolkit
from .documentdb import DocumentDBToolkit
from .lambda_func import LambdaToolkit
from .eks import EKSToolkit

__all__ = [
    "Route53Toolkit", "ECSToolkit", "CloudWatchToolkit", "S3Toolkit",
    "GuardDutyToolkit", "EC2Toolkit", "ECRToolkit", "IAMToolkit",
    "SecurityHubToolkit", "RDSToolkit", "DocumentDBToolkit",
    "LambdaToolkit", "EKSToolkit",
]
```

### Existing File Layout

```
packages/ai-parrot-tools/src/parrot_tools/aws/
├── __init__.py
├── cloudwatch.py
├── documentdb.py
├── ec2.py
├── ecr.py
├── ecs.py
├── eks.py
├── guardduty.py
├── iam.py
├── lambda_func.py
├── rds.py
├── route53.py
├── s3.py
├── securityhub.py
└── inspector.py   ← created by TASK-1079
```

### Does NOT Exist

- ~~`parrot_tools/aws/policies/`~~ — directory does not exist yet; this task creates it.
- ~~`*_toolkit_policy.json`~~ — no existing IAM policy sidecar files anywhere.
- ~~`examples/aws_inspector*`~~ — no existing Inspector example.

---

## Implementation Notes

### IAM Policy Sidecar

Create `packages/ai-parrot-tools/src/parrot_tools/aws/policies/inspector_toolkit_policy.json` with the exact content from §7:

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

### `__init__.py` Update

Add to imports:
```python
from .inspector import InspectorToolkit
```

Add to `__all__`:
```python
"InspectorToolkit",
```

### Usage Example Pattern

Follow existing examples in `examples/` directory. The example should demonstrate:
1. Basic toolkit instantiation.
2. `list_findings` with severity filter.
3. `get_ecr_image_findings` for a specific image.
4. `get_security_posture` composite call.
5. Note about pagination (agent must decide to continue).
6. Note about required IAM permissions referencing the sidecar.

### Key Constraints

- The `policies/` directory is new — this establishes the convention for future toolkits.
- `git add -f` may be needed if `templates/` gitignore rule catches `policies/` (check).
- The example must use `async`/`await` throughout.

---

## Acceptance Criteria

- [ ] `inspector_toolkit_policy.json` exists at `packages/ai-parrot-tools/src/parrot_tools/aws/policies/inspector_toolkit_policy.json`.
- [ ] Policy contains exactly the IAM actions from §7 (read ops + export ops).
- [ ] `InspectorToolkit` is re-exported from `parrot_tools.aws.__init__` and in `__all__`.
- [ ] `from parrot_tools.aws import InspectorToolkit` works.
- [ ] `examples/aws_inspector_toolkit.py` exists and demonstrates key operations.
- [ ] No breaking changes to existing toolkit imports.
- [ ] Full test suite passes: `pytest packages/ai-parrot-tools/tests/aws/ -v`.

---

## Test Specification

```python
# Minimal import test (add to existing test file or a new one)
def test_inspector_toolkit_importable():
    from parrot_tools.aws import InspectorToolkit
    assert InspectorToolkit is not None

def test_inspector_toolkit_in_all():
    from parrot_tools.aws import __all__
    assert "InspectorToolkit" in __all__
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/inspector-toolkit.spec.md` (especially §3 Module 5 and §7 IAM)
2. **Check dependencies** — verify TASK-1080, TASK-1081, TASK-1082 are all in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `__init__.py` layout matches what's documented
4. **Update status** in `sdd/tasks/index/inspector-toolkit.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1083-iam-policy-package-wiring-example.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker agent
**Date**: 2026-05-12
**Notes**: Created `policies/` directory and `inspector_toolkit_policy.json` IAM sidecar with exact
actions from spec §7. Updated `__init__.py` with InspectorToolkit import and `__all__` entry (also
alphabetized the imports). Created `examples/aws_inspector_toolkit.py` demonstrating key operations.
Note: needed `git add -f` for the example because `.gitignore` has `examples/**/*.py` rule.
All 48 tests pass.

**Deviations from spec**: none
