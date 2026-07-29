---
type: Wiki Overview
title: 'TASK-1124: Example plan YAML + `__init__.py` re-exports'
id: doc:sdd-tasks-completed-task-1124-ecr-example-plan-and-exports-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 8** of the spec (`sdd/specs/cloudsploit-ecr.spec.md`
  §3).
relates_to:
- concept: mod:parrot_tools.cloudsploit
  rel: mentions
---

# TASK-1124: Example plan YAML + `__init__.py` re-exports

**Feature**: FEAT-165 — CloudSploit ECR Image-Scan Collector & Interactive Report
**Spec**: `sdd/specs/cloudsploit-ecr.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1118, TASK-1120
**Assigned-to**: unassigned

---

## Context

Implements **Module 8** of the spec (`sdd/specs/cloudsploit-ecr.spec.md` §3).

Final glue task:

1. Re-export the new ECR public symbols from
   `parrot_tools.cloudsploit.__init__` so callers can do
   `from parrot_tools.cloudsploit import EcrCollectionPlan, ...`.
2. Ship a documented example YAML plan at
   `cloudsploit/ecr_plan.example.yaml` mirroring the user's curated
   23-repo / tag-priority shape. This is the reference for ops when
   authoring the production plan; the authoritative plan lives outside
   the repo (per spec §1 Non-Goals).

---

## Scope

- Extend `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/__init__.py`
  to re-export the new symbols from `models.py` and the new collector class
  from `ecr_collector.py`. Update `__all__` accordingly.
- Create `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/ecr_plan.example.yaml`
  containing the 23-repo list with tag priorities exactly as in the
  proposal's `sdd/state/FEAT-165/source.md` (script 1 — `REPOS = [...]`).
  Add a header comment explaining how to load it.
- Add one unit test that imports every new public symbol from the
  package namespace.

**NOT in scope**: shipping a production plan (ops-managed), documentation
in `docs/` (left to a follow-up doc task), package version bump.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/__init__.py` | MODIFY | Add 6 new imports + `__all__` entries |
| `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/ecr_plan.example.yaml` | CREATE | 23-repo reference plan with header comment |
| `packages/ai-parrot-tools/tests/cloudsploit/test_init_exports.py` | MODIFY (or CREATE) | One test importing every new symbol via the package namespace |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Current __init__.py (will be extended):
from .models import (
    CloudProvider,
    CloudSploitConfig,
    ComparisonReport,
    ComplianceFramework,
    ScanFinding,
    ScanResult,
    ScanSummary,
    SeverityLevel,
)
from .toolkit import CloudSploitToolkit
# Verified at: cloudsploit/__init__.py:1-12
```

### Existing Signatures to Use
```python
# Symbols added by prior tasks that this task re-exports:
# - from .models: EcrSeverity, EcrRepoPlan, EcrCollectionPlan,
#                 EcrScanFinding, EcrRepoFindings, EcrCollectionResult
# - from .ecr_collector: EcrScanCollector
```

### Does NOT Exist
- ~~A package-level `_ecr_plan.yaml`~~ — the example file lives next to
  the code, not under tests/.
- ~~`from parrot_tools.cloudsploit import collect_ecr_findings`~~ —
  `collect_ecr_findings` is an instance method on `CloudSploitToolkit`,
  not a free function.
- ~~A separate `cloudsploit.ecr` subpackage~~ — everything lives at the
  `cloudsploit/` top level (single module per concern).

---

## Implementation Notes

### Pattern to Follow

```python
# packages/ai-parrot-tools/src/parrot_tools/cloudsploit/__init__.py
"""CloudSploit Security Scanning Toolkit for AI-Parrot."""
from .ecr_collector import EcrScanCollector
from .models import (
    CloudProvider,
    CloudSploitConfig,
    ComparisonReport,
    ComplianceFramework,
    EcrCollectionPlan,
    EcrCollectionResult,
    EcrRepoFindings,
    EcrRepoPlan,
    EcrScanFinding,
    EcrSeverity,
    ScanFinding,
    ScanResult,
    ScanSummary,
    SeverityLevel,
)
from .toolkit import CloudSploitToolkit

__all__ = [
    "CloudProvider",
    "CloudSploitConfig",
    "CloudSploitToolkit",
    "ComparisonReport",
    "ComplianceFramework",
    "EcrCollectionPlan",
    "EcrCollectionResult",
    "EcrRepoFindings",
    "EcrRepoPlan",
    "EcrScanCollector",
    "EcrScanFinding",
    "EcrSeverity",
    "ScanFinding",
    "ScanResult",
    "ScanSummary",
    "SeverityLevel",
]
```

### ecr_plan.example.yaml structure

```yaml
# packages/ai-parrot-tools/src/parrot_tools/cloudsploit/ecr_plan.example.yaml
#
# Example ECR collection plan for CloudSploitToolkit.collect_ecr_findings().
# Copy this file, edit the repo list to match your environment, and pass
# the path to:
#
#     await toolkit.collect_ecr_findings(plan="/path/to/your_plan.yaml")
#
# `tags` are tried in priority order; the first one with scan findings wins.

region: us-east-2
aws_id: default          # AWSInterface credential identifier (navconfig)
concurrency: 5           # Max concurrent describe_image_scan_findings calls

repos:
  - name: navigator-api-tf
    tags: [staging, production, dev]
  - name: navigator-next-tf
    tags: [staging, production, dev]
  - name: navigator-front-tf
    tags: [staging, production]
  - name: navigator-frontend-next-tf
    tags: [staging, production, dev]
  - name: navigator-svelte-tf
    tags: [porygon-staging, staging, production]
  - name: navigator-apps-tf
    tags: [staging, dev]
  - name: navigator-front-middleware-tf
    tags: [staging, production]
  - name: navigator-eventhooks-tf
    tags: [staging, dev]
  - name: navigator-chatbots-tf
    tags: [staging, production]
  - name: navigator-voice-tf
    tags: [staging, production]
  - name: navigator-partner-portal-tf
    tags: [staging, dev]
  - name: navigator-agents-server-tf
    tags: [staging, staging-jira, production]
  - name: navigator-api-ai-tf
    tags: [staging, dev]
  - name: navigator-mcp-tf
    tags: [aws-staging, aws-dev]
  - name: navigator-copilot-svelte-tf
    tags: [staging, production]
  - name: dataintegrator-tf
    tags: [staging, production, dev]
  - name: dataintegrator-worker-tf
    tags: [staging, production, dev]
  - name: dataintegrator-worker-ai-tf
    tags: [staging, dev]
  - name: dataintegrator-worker-scraping-tf
    tags: [staging, dev]
  - name: dataintegrator-sftp-tf
    tags: [staging, production]
  - name: logstash-tf
    tags: [staging, latest]
  - name: zammad-tf
    tags: [staging, latest, dev]
  - name: zammad-teams-middleware-tf
    tags: [staging, dev]
```

### Key Constraints

- Preserve every existing symbol in `__all__`.
- Sort `__all__` alphabetically (the current list is partially sorted; fully
  sort it).
- The example YAML must load successfully via
  `EcrCollectionPlan.from_yaml(...)` — verify in the test (see below).
- Do NOT commit this file as `ecr_plan.yaml` (no `.example.` suffix) —
  the bare name is reserved for the ops-managed file outside the repo.

### References in Codebase

- `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/__init__.py:1-24`
  — existing exports to extend.
- `sdd/state/FEAT-165/source.md` (script 1, `REPOS = [...]`) — authoritative
  source for the example plan's 23 repos and their tag priorities.

---

## Acceptance Criteria

- [ ] `from parrot_tools.cloudsploit import EcrCollectionPlan, EcrCollectionResult, EcrRepoFindings, EcrRepoPlan, EcrScanCollector, EcrScanFinding, EcrSeverity` works.
- [ ] `parrot_tools.cloudsploit.__all__` contains every new symbol and is sorted alphabetically.
- [ ] No existing exports were removed (regression).
- [ ] `EcrCollectionPlan.from_yaml(<path-to-example>)` loads cleanly and produces a plan with 23 repos and `concurrency=5`.
- [ ] `pytest packages/ai-parrot-tools/tests/cloudsploit/test_init_exports.py -v` passes.
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/cloudsploit/__init__.py` passes.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/cloudsploit/test_init_exports.py
from importlib.resources import files
from pathlib import Path

import pytest

import parrot_tools.cloudsploit as cs


def test_ecr_symbols_exported():
    expected = {
        "EcrCollectionPlan", "EcrCollectionResult", "EcrRepoFindings",
        "EcrRepoPlan", "EcrScanCollector", "EcrScanFinding", "EcrSeverity",
    }
    assert expected.issubset(set(cs.__all__))
    for name in expected:
        assert hasattr(cs, name), name


def test_existing_symbols_still_exported():
    for name in [
        "CloudProvider", "CloudSploitConfig", "CloudSploitToolkit",
        "ComparisonReport", "ComplianceFramework", "ScanFinding",
        "ScanResult", "ScanSummary", "SeverityLevel",
    ]:
        assert hasattr(cs, name), name


def test_all_is_sorted():
    assert cs.__all__ == sorted(cs.__all__)


def test_example_plan_yaml_loads():
    pkg_dir = Path(cs.__file__).parent
    example = pkg_dir / "ecr_plan.example.yaml"
    assert example.is_file()
    plan = cs.EcrCollectionPlan.from_yaml(example)
    assert plan.region == "us-east-2"
    assert plan.concurrency == 5
    assert len(plan.repos) == 23
    names = {r.name for r in plan.repos}
    assert "navigator-api-tf" in names
    assert "zammad-teams-middleware-tf" in names
```

---

## Agent Instructions

1. Read the spec at `sdd/specs/cloudsploit-ecr.spec.md` (§3 Module 8).
2. Verify dependencies: TASK-1118 and TASK-1120 must be in `sdd/tasks/completed/`.
3. Update `cloudsploit/__init__.py` with the new re-exports (alphabetical `__all__`).
4. Create `cloudsploit/ecr_plan.example.yaml` with the 23-repo list (header comment explaining usage).
5. Add the 4 tests above.
6. Run `pytest packages/ai-parrot-tools/tests/cloudsploit/test_init_exports.py -v`.
7. Run `ruff check packages/ai-parrot-tools/src/parrot_tools/cloudsploit/__init__.py`.
8. Move this file to `sdd/tasks/completed/`.
9. Update `sdd/tasks/index/cloudsploit-ecr.json` task status to `done`.
10. Fill in the Completion Note.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-12
**Notes**: Updated __init__.py with 7 new ECR symbols + alphabetically sorted __all__ (16 entries total). Created ecr_plan.example.yaml with 23 repos and header comment. Created test_init_exports.py with 4 tests; all pass.
**Deviations from spec**: none
