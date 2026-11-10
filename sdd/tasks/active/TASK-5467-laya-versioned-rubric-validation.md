# TASK-5467: Add explicit versioned rubric checks and provenance

**Feature**: FEAT-589 — Laya capability evaluation follow-up
**Spec**: `sdd/specs/laya-adoption.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5466, TASK-3616
**Assigned-to**: unassigned

## Context

Implement reopened spec Module 7. The original worker placeholders were fixed;
archived task blueprint stubs are not runtime defects. This task addresses a measured
evaluation gap while preserving earlier reports and completed task history.

## Scope

- Add the Pydantic v2 envelope/check models, explicit rubric-file config/CLI option and report version/hash fields specified in Module 7.
- Keep legacy load_rubrics/rubric_pass signatures and behavior; new literal-group scoring applies only to v2.
- Reject malformed/unsupported v2 files and missing requested fixture coverage before any worker/provider dispatch; add a separately versioned fixture file.

**NOT in scope**: production integration, dependency changes, SDK-direct calls, automatic paid runs, retroactive changes to prior metrics.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `artifacts/laya/models.py` | MODIFY | Module 7 scoped implementation or regression evidence |
| `artifacts/laya/live.py` | MODIFY | Module 7 scoped implementation or regression evidence |
| `artifacts/laya/evaluate.py` | MODIFY | Module 7 scoped implementation or regression evidence |
| `artifacts/laya/fixtures/routing_rubrics_v2.json` | CREATE | Module 7 scoped implementation or regression evidence |
| `packages/ai-parrot/tests/unit/laya_eval/test_laya_rubrics_v2.py` | CREATE | Module 7 scoped implementation or regression evidence |

## Codebase Contract (Anti-Hallucination)

Verified at base commit `80385f52d1ad2531945030984fb1dc32f6c10be8`.

### Verified Imports

```python
from pathlib import Path
import pytest
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field
from parrot.models.responses import AIMessage
from artifacts.laya.models import EvaluationConfig, EvaluationReport, SampleResult, RouteDecision
```

Pydantic/typing imports are present in models.py:8–11. AIMessage is imported by live.py:14;
local record classes are defined in models.py (verified below). Existing source already uses
json, re, hashlib and unicodedata is Python stdlib if needed; no external dependency may be added.

New imports introduced within this task: `from artifacts.laya.models import RubricFileV2`
for live.py; `unicodedata` is standard library. `_Record` is defined at models.py:56.

### Existing Signatures to Use

- `artifacts/laya/models.py:97` — `class EvaluationConfig(_Record):`; read continuation lines for full signature.
- `artifacts/laya/models.py:205` — `class EvaluationReport(_Record):`; read continuation lines for full signature.
- `artifacts/laya/live.py:125` — `def load_rubrics(path: Path) -> dict[str, dict[str, Any]]:`; read continuation lines for full signature.
- `artifacts/laya/live.py:139` — `def rubric_pass(answer: str, rubric: dict[str, Any] | None) -> bool | None:`; read continuation lines for full signature.
- `artifacts/laya/evaluate.py:62` — `def parse_args_to_config(argv: Sequence[str] | None) -> tuple[EvaluationConfig, Path]:`; read continuation lines for full signature.

### Does NOT Exist

- No production Laya client or guarantee that fallback means cheaper; only the evaluation adapter exists.
- No full retained provider-response archive in SampleResult. The new evidence field must be minimal.
- No semantic LLM judge, v2 rubric parser or cheap comparison arm is currently available.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "artifacts/laya/models.py",
      "action": "MODIFY"
    },
    {
      "path": "artifacts/laya/live.py",
      "action": "MODIFY"
    },
    {
      "path": "artifacts/laya/evaluate.py",
      "action": "MODIFY"
    },
    {
      "path": "artifacts/laya/fixtures/routing_rubrics_v2.json",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/unit/laya_eval/test_laya_rubrics_v2.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:artifacts/laya/evaluate.py#parse_args_to_config",
    "sym:artifacts/laya/live.py#load_rubrics",
    "sym:artifacts/laya/live.py#rubric_pass",
    "sym:artifacts/laya/models.py#EvaluationConfig",
    "sym:artifacts/laya/models.py#EvaluationReport",
    "sym:artifacts/laya/models.py#RouteDecision",
    "sym:artifacts/laya/models.py#SampleResult",
    "sym:artifacts/laya/models.py#_Record",
    "sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessage"
  ]
}
```

## Implementation Notes

Follow spec Module 7 exactly. Keep synchronous validation before asynchronous work.
Use existing Pydantic v2 records and asyncio Agent dispatch. Preserve legacy report defaults.

## Implementation Blueprint

### Steps (in order)

1. Add the Pydantic v2 envelope/check models, explicit rubric-file config/CLI option and report version/hash fields specified in Module 7. This preserves the spec boundary and prevents misleading completion evidence.
2. Keep legacy load_rubrics/rubric_pass signatures and behavior; new literal-group scoring applies only to v2. This preserves the spec boundary and prevents misleading completion evidence.
3. Reject malformed/unsupported v2 files and missing requested fixture coverage before any worker/provider dispatch; add a separately versioned fixture file. This preserves the spec boundary and prevents misleading completion evidence.

### `artifacts/laya/models.py` (MODIFY)

Attachment anchor: `class EvaluationConfig(_Record):` — `artifacts/laya/models.py:97`, occurrences `1` (verified with grep -F -c).

```python
class RubricV2(_Record):
    """Literal groups: one required alternative per group, plus forbidden terms."""
    all_of: list[list[str]]
    none_of: list[str] = Field(default_factory=list)
    # FILL IN: validators reject empty groups/strings; bounded by R2.


class RubricFileV2(_Record):
    """Only version 2 is supported by this envelope."""
    version: Literal[2]
    cases: dict[str, RubricV2]
    # FILL IN: reject empty case mappings; bounded by R2.

# Add EvaluationConfig.rubric_file: Path | None = None.
# Add EvaluationReport.rubric_sha256: str | None = None.
# Add EvaluationReport.rubric_version: int | None = None.
```

### `artifacts/laya/live.py` (MODIFY)

Attachment anchor: `def load_rubrics(` — `artifacts/laya/live.py:125`, occurrences `1` (verified with grep -F -c).

```python
def load_rubrics(path: Path) -> dict[str, dict[str, Any]]:
    """Load legacy mapping or validate a v2 envelope and tag normalized entries."""
    # FILL IN: preserve legacy branches; validate v2 with RubricFileV2; bounded by R2.
    raise NotImplementedError


def rubric_pass(answer: str, rubric: dict[str, Any] | None) -> bool | None:
    """Apply the selected rubric version; None means no quality judgment."""
    # FILL IN: legacy exact/substrings unchanged; v2 literal-group boundaries + forbidden terms.
    raise NotImplementedError
```

### `artifacts/laya/evaluate.py` (MODIFY)

Attachment anchor: `def parse_args_to_config(` — `artifacts/laya/evaluate.py:62`, occurrences `1` (verified with grep -F -c).

```python
# In build_parser:
parser.add_argument("--rubric-file", type=Path, default=None)
# In parse_args_to_config before worker startup: resolve config.rubric_file or
# fixtures/routing_rubrics.json, load it, validate requested case coverage.
# In run_evaluation use that same path and retain hash/version in EvaluationReport.
# FILL IN: invalid format/version/coverage -> ValueError preflight; bounded by R2.
```

### `artifacts/laya/fixtures/routing_rubrics_v2.json` (CREATE)

```json
{"version": 2, "cases": {}}
```
FILL IN: populate each existing routing fixture ID with validated literal groups and forbidden facts; an empty cases mapping must not pass validation.

### `packages/ai-parrot/tests/unit/laya_eval/test_laya_rubrics_v2.py` (CREATE)

```python
"""Regression tests for the FEAT-589 follow-up contracts."""
from __future__ import annotations

import pytest

def test_followup_contract_acceptance() -> None:
    """Exercise the module acceptance matrix through public evaluation interfaces."""
    # FILL IN: replace this planning scaffold with the focused behavioral tests below.
    # No paid calls, runtime stubs, or tautological assertions in completed tests.
    raise NotImplementedError
```

### FILL IN checklist

- [ ] `artifacts/laya/models.py` — complete its Module 7 changes and remove all planning placeholders from executable files.
- [ ] `artifacts/laya/live.py` — complete its Module 7 changes and remove all planning placeholders from executable files.
- [ ] `artifacts/laya/evaluate.py` — complete its Module 7 changes and remove all planning placeholders from executable files.
- [ ] `artifacts/laya/fixtures/routing_rubrics_v2.json` — complete its Module 7 changes and remove all planning placeholders from executable files.
- [ ] `packages/ai-parrot/tests/unit/laya_eval/test_laya_rubrics_v2.py` — complete its Module 7 changes and remove all planning placeholders from executable files.

## Acceptance Criteria

- [ ] Legacy exact_answer and required_facts tests stay unchanged; unspecified rubric remains None.
- [ ] V2 accepts required literal alternatives with normalized boundaries and rejects forbidden literals; test wrong answers, contradictions, substrings, empty patterns/groups and unknown version.
- [ ] CLI custom v2 file is actually used, hash/version are recorded, and invalid v2 configuration starts no worker or paid call.
- [ ] No preexisting fixture or measured report is overwritten; docs identify v2 as a new heuristic rubric, not retrospective held-out validation.

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/laya_eval/test_laya_rubrics_v2.py -q`
- `pytest packages/ai-parrot/tests/unit/laya_eval/test_laya_live_pairs.py -q`
- `pytest packages/ai-parrot/tests/unit/laya_eval/test_laya_evaluate_cli.py -q`

## Test Specification

Use fixture-driven offline tests for every acceptance bullet, plus malformed/missing inputs.
Assert externally visible output, preserved evidence, dispatch count and cleanup; do not
assert implementation text. Integration live flags remain opt-in with explicit model IDs/cap.

## Agent Instructions

Implement only this task in the feature worktree provisioned by sdd-start. Reverify anchors
before editing. Do not change historical completion notes or old reports. Run the scoped
validation commands, commit implementation, and finalize through `parrot sdd task finalize`
with actual TaskCompletionEvidence; do not manually move this task or invent verification.

## Completion Note

Pending implementation; no completion evidence is claimed by this planning document.
