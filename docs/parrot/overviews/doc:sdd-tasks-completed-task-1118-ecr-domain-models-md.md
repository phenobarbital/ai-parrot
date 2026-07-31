---
type: Wiki Overview
title: 'TASK-1118: ECR domain models + CloudSploitConfig.ecr_plan_file'
id: doc:sdd-tasks-completed-task-1118-ecr-domain-models-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Foundation task. Adds the Pydantic types that every later task depends on,
relates_to:
- concept: mod:parrot_tools.cloudsploit.models
  rel: mentions
---

# TASK-1118: ECR domain models + CloudSploitConfig.ecr_plan_file

**Feature**: FEAT-165 — CloudSploit ECR Image-Scan Collector & Interactive Report
**Spec**: `sdd/specs/cloudsploit-ecr.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Foundation task. Adds the Pydantic types that every later task depends on,
plus the single new field on `CloudSploitConfig` (both live in the same
file, so they ship together).

Implements **Module 1** and **Module 7** of the spec
(`sdd/specs/cloudsploit-ecr.spec.md` §3).

The ECR Basic Scanning severities (CRITICAL/HIGH/MEDIUM/LOW/INFORMATIONAL/UNTRIAGED)
do NOT fit the existing `SeverityLevel(OK/WARN/FAIL/UNKNOWN)` enum that the
CSPM scan flow uses, so a new independent enum is required. Reusing
`SeverityLevel` for ECR would corrupt the CSPM summary buckets.

---

## Scope

- Add `EcrSeverity` enum to `parrot_tools/cloudsploit/models.py`.
- Add `EcrRepoPlan` Pydantic model (`name`, `tags` — `min_length=1`).
- Add `EcrCollectionPlan` Pydantic model (`region`, `aws_id`,
  `concurrency: 1..20`, `repos`) with a `from_yaml(path)` classmethod that
  loads via PyYAML, validates the dict, and returns the model.
- Add `EcrScanFinding`, `EcrRepoFindings`, `EcrCollectionResult` Pydantic models
  matching the JS output JSON 1:1 (so existing JS-produced files remain parseable).
- Add `ecr_plan_file: Optional[str] = None` to `CloudSploitConfig`, with the
  same "validate-at-scan-time, not construction-time" semantics as the
  existing `config_file` field (models.py:154-163).
- Add unit tests covering: enum values, plan YAML round-trip, validation
  errors for empty tags / out-of-range concurrency, default of
  `ecr_plan_file`.

**NOT in scope**: the collector that uses the plan (TASK-1120), the report
generator (TASK-1122), exports in `__init__.py` (TASK-1124).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/models.py` | MODIFY | Append the 6 ECR types after line 203; add `ecr_plan_file` to `CloudSploitConfig` after line 163 |
| `packages/ai-parrot-tools/tests/cloudsploit/test_models.py` | MODIFY | Add the 5 tests from §4 of the spec covering the new types |
| `packages/ai-parrot-tools/tests/cloudsploit/fixtures/ecr_collection_plan.yaml` | CREATE | Small valid plan fixture for tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Standard library
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

# Already present at top of the file — re-use, do NOT re-import
from pydantic import BaseModel, Field
# Verified at: packages/ai-parrot-tools/src/parrot_tools/cloudsploit/models.py:6

# PyYAML is transitively available (used by parrot_tools/multidb.py, database/cache.py)
import yaml
# Verified callers: packages/ai-parrot-tools/src/parrot_tools/multidb.py:21
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/cloudsploit/models.py
class SeverityLevel(str, Enum):                     # line 15  — DO NOT extend; ECR gets its own enum
    OK = "OK"; WARN = "WARN"; FAIL = "FAIL"; UNKNOWN = "UNKNOWN"

class CloudSploitConfig(BaseModel):                 # line 81
    # Existing fields ending at line 176 ("results_dir")
    # The new `ecr_plan_file` lives right AFTER `results_dir` and follows the
    # SAME validate-at-scan-time semantics as `config_file` (line 154-163):
    config_file: Optional[str] = Field(             # line 154
        default=None,
        description="...validated at scan time, not at construction..."
    )
    results_dir: Optional[str] = Field(             # line 173
        default=None, ...
    )
```

### Does NOT Exist
- ~~`from parrot_tools.cloudsploit.models import EcrSeverity`~~ — does NOT exist yet; this task creates it.
- ~~`SeverityLevel.CRITICAL`~~ — `SeverityLevel` is OK/WARN/FAIL/UNKNOWN only; do NOT add CRITICAL/HIGH to it.
- ~~`pydantic.field_validator` for plan validation~~ — not needed; `Field(min_length=1)` + `ge`/`le` constraints are enough.
- ~~`from yaml import safe_load` at the top of models.py~~ — defer the import to inside `from_yaml` to avoid hard-failing if yaml is missing in some environment.

---

## Implementation Notes

### Pattern to Follow

Existing `CloudSploitConfig` field declarations (models.py:108-176) are the
exact style: `Optional[str] = Field(default=..., description="...")`.
Mirror that for `ecr_plan_file`.

For the ECR types, follow the existing `ScanFinding` (line 38), `ScanSummary`
(line 50), `ScanResult` (line 69) style: explicit `Field(...,
description=...)` on every attribute. Match the JS output JSON shape:

```python
# Maps to JS:
#   {"repo": str, "tag": str, "scan_time": ISO|null,
#    "counts": {"CRITICAL": N, ...},
#    "findings": [ {name, severity, description, uri, ...attributes...}, ... ]}
```

The `EcrCollectionPlan.from_yaml` classmethod:
```python
@classmethod
def from_yaml(cls, path: str | Path) -> "EcrCollectionPlan":
    """Load and validate a plan from a YAML file.

    Raises:
        FileNotFoundError: if `path` does not exist.
        pydantic.ValidationError: if the parsed YAML does not match schema.
    """
    import yaml
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"ECR collection plan not found: {p}")
    data = yaml.safe_load(p.read_text())
    return cls.model_validate(data)
```

### Key Constraints

- All new types must be Pydantic v2 (`model_validate`, not `parse_obj`).
- `EcrSeverity` is `str, Enum` so values serialize cleanly to JSON.
- `counts: dict[EcrSeverity, int]` keys must serialise as severity-name
  strings in JSON (default Pydantic v2 behaviour for `str, Enum` keys).
- `EcrCollectionResult.generated_at` is `datetime` — collector will set it
  with `datetime.now(tz=timezone.utc)` (handled in TASK-1120).
- Do NOT modify or extend `SeverityLevel`.
- Do NOT modify `ScanFinding`, `ScanResult`, or `ScanSummary`.

### References in Codebase

- `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/models.py:38` — existing `ScanFinding` style to mirror.
- `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/models.py:154-163` — `config_file` field as the template for `ecr_plan_file`.
- `packages/ai-parrot-tools/src/parrot_tools/multidb.py:21` — example of `import yaml` usage in the codebase.

---

## Acceptance Criteria

- [ ] `from parrot_tools.cloudsploit.models import EcrSeverity, EcrRepoPlan, EcrCollectionPlan, EcrScanFinding, EcrRepoFindings, EcrCollectionResult` works.
- [ ] `EcrSeverity` has exactly 6 members: CRITICAL, HIGH, MEDIUM, LOW, INFORMATIONAL, UNTRIAGED.
- [ ] `EcrCollectionPlan(region="us-east-2", repos=[EcrRepoPlan(name="x", tags=["staging"])])` validates.
- [ ] `EcrRepoPlan(name="x", tags=[])` raises `pydantic.ValidationError`.
- [ ] `EcrCollectionPlan(..., concurrency=0)` and `concurrency=21` both raise `ValidationError`.
- [ ] `EcrCollectionPlan.from_yaml(path)` round-trips a valid YAML; missing file raises `FileNotFoundError`; bad shape raises `ValidationError`.
- [ ] `CloudSploitConfig().ecr_plan_file is None`.
- [ ] `CloudSploitConfig(ecr_plan_file="/some/path/never/checked.yaml")` does NOT raise at construction (validation happens at scan time, per `config_file` precedent).
- [ ] `SeverityLevel` still has only OK/WARN/FAIL/UNKNOWN (regression guard).
- [ ] `pytest packages/ai-parrot-tools/tests/cloudsploit/test_models.py -v` passes.
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/cloudsploit/models.py` passes.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/cloudsploit/test_models.py (additions)
import pytest
from pydantic import ValidationError

from parrot_tools.cloudsploit.models import (
    CloudSploitConfig,
    EcrCollectionPlan,
    EcrCollectionResult,
    EcrRepoFindings,
    EcrRepoPlan,
    EcrScanFinding,
    EcrSeverity,
    SeverityLevel,
)


class TestEcrSeverity:
    def test_enum_values(self):
        assert {e.value for e in EcrSeverity} == {
            "CRITICAL", "HIGH", "MEDIUM", "LOW", "INFORMATIONAL", "UNTRIAGED",
        }


class TestEcrCollectionPlan:
    def test_from_yaml_roundtrip(self, tmp_path):
        p = tmp_path / "plan.yaml"
        p.write_text(
            "region: us-east-2\n"
            "concurrency: 3\n"
            "repos:\n"
            "  - name: alpha\n"
            "    tags: [staging, production]\n"
        )
        plan = EcrCollectionPlan.from_yaml(p)
        assert plan.region == "us-east-2"
        assert plan.concurrency == 3
        assert plan.repos[0].name == "alpha"
        assert plan.repos[0].tags == ["staging", "production"]

    def test_from_yaml_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            EcrCollectionPlan.from_yaml(tmp_path / "missing.yaml")

    def test_rejects_empty_tags(self):
        with pytest.raises(ValidationError):
            EcrRepoPlan(name="x", tags=[])

    @pytest.mark.parametrize("c", [0, 21])
    def test_concurrency_bounds(self, c):
        with pytest.raises(ValidationError):
            EcrCollectionPlan(
                region="us-east-2",
                concurrency=c,
                repos=[EcrRepoPlan(name="x", tags=["t"])],
            )


class TestCloudSploitConfigEcrPlanFile:
    def test_default_none(self):
        assert CloudSploitConfig().ecr_plan_file is None

    def test_no_validation_at_construction(self):
        # Mirrors config_file precedent — path is NOT checked here.
        cfg = CloudSploitConfig(ecr_plan_file="/nope/never/exists.yaml")
        assert cfg.ecr_plan_file == "/nope/never/exists.yaml"


class TestSeverityLevelRegressionGuard:
    def test_unchanged(self):
        assert {e.value for e in SeverityLevel} == {"OK", "WARN", "FAIL", "UNKNOWN"}
```

---

## Agent Instructions

1. Read the spec at `sdd/specs/cloudsploit-ecr.spec.md` (§2 Data Models, §3 Modules 1 and 7, §6 Codebase Contract).
2. Verify the Codebase Contract: `read` lines 1-203 of `cloudsploit/models.py` to confirm structure.
3. Append the 6 ECR types and the `ecr_plan_file` field — preserve the existing class ordering.
4. Write the tests listed in the Test Specification, plus the YAML fixture.
5. Run `pytest packages/ai-parrot-tools/tests/cloudsploit/test_models.py -v`.
6. Run `ruff check packages/ai-parrot-tools/src/parrot_tools/cloudsploit/models.py`.
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
