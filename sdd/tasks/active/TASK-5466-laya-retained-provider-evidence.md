# TASK-5466: Retain minimal provider evidence for offline verification

**Feature**: FEAT-589 — Laya capability evaluation follow-up
**Spec**: `sdd/specs/laya-adoption.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3606, TASK-3615
**Assigned-to**: unassigned

## Context

Implement reopened spec Module 6. The original worker placeholders were fixed;
archived task blueprint stubs are not runtime defects. This task addresses a measured
evaluation gap while preserving earlier reports and completed task history.

## Scope

- Add an empty-default provider_evidence mapping to SampleResult without breaking old report loading.
- Implement capture_provider_evidence and resolve_provider_model exactly as spec Module 6; integrate them into extract_model_evidence and _arm_sample.
- Persist allowlisted raw identities even for unknown providers; never copy full raw responses or request-derived model proof.

**NOT in scope**: production integration, dependency changes, SDK-direct calls, automatic paid runs, retroactive changes to prior metrics.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `artifacts/laya/models.py` | MODIFY | Module 6 scoped implementation or regression evidence |
| `artifacts/laya/live.py` | MODIFY | Module 6 scoped implementation or regression evidence |
| `packages/ai-parrot/tests/unit/laya_eval/test_laya_evidence_retention.py` | CREATE | Module 6 scoped implementation or regression evidence |

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

### Existing Signatures to Use

- `artifacts/laya/models.py:163` — `class SampleResult(_Record):`; read continuation lines for full signature.
- `artifacts/laya/live.py:101` — `def extract_model_evidence(message: AIMessage, requested_model: str | None) -> ModelEvidence:`; read continuation lines for full signature.
- `artifacts/laya/live.py:148` — `async def _arm_sample(`; read continuation lines for full signature.

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
      "path": "packages/ai-parrot/tests/unit/laya_eval/test_laya_evidence_retention.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:artifacts/laya/live.py#_arm_sample",
    "sym:artifacts/laya/live.py#extract_model_evidence",
    "sym:artifacts/laya/models.py#EvaluationConfig",
    "sym:artifacts/laya/models.py#EvaluationReport",
    "sym:artifacts/laya/models.py#RouteDecision",
    "sym:artifacts/laya/models.py#SampleResult",
    "sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessage"
  ]
}
```

## Implementation Notes

Follow spec Module 6 exactly. Keep synchronous validation before asynchronous work.
Use existing Pydantic v2 records and asyncio Agent dispatch. Preserve legacy report defaults.

## Implementation Blueprint

### Steps (in order)

1. Add an empty-default provider_evidence mapping to SampleResult without breaking old report loading. This preserves the spec boundary and prevents misleading completion evidence.
2. Implement capture_provider_evidence and resolve_provider_model exactly as spec Module 6; integrate them into extract_model_evidence and _arm_sample. This preserves the spec boundary and prevents misleading completion evidence.
3. Persist allowlisted raw identities even for unknown providers; never copy full raw responses or request-derived model proof. This preserves the spec boundary and prevents misleading completion evidence.

### `artifacts/laya/models.py` (MODIFY)

Attachment anchor: `class SampleResult(_Record):` — `artifacts/laya/models.py:163`, occurrences `1` (verified with grep -F -c).

```python
# Extend SampleResult; retain all other fields and defaults.
provider_evidence: dict[str, str] = Field(default_factory=dict)
```

### `artifacts/laya/live.py` (MODIFY)

Attachment anchor: `def extract_model_evidence(` — `artifacts/laya/live.py:101`, occurrences `1` (verified with grep -F -c).

```python
def capture_provider_evidence(message: AIMessage) -> dict[str, str]:
    """Retain only provider and raw string model/model_version/modelVersion fields."""
    # FILL IN: allowlist and omit nonstrings, bounded by R1; never copy raw wholesale.
    raise NotImplementedError


def resolve_provider_model(evidence: dict[str, str]) -> str | None:
    """Interpret only known provider tags, never request-derived model metadata."""
    # FILL IN: existing provider-family precedence, unknown -> None, bounded by R1.
    raise NotImplementedError

# In extract_model_evidence: resolve from capture_provider_evidence(message).
# In _arm_sample's final SampleResult constructor, add:
# provider_evidence=capture_provider_evidence(message)
```

### `packages/ai-parrot/tests/unit/laya_eval/test_laya_evidence_retention.py` (CREATE)

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

- [ ] `artifacts/laya/models.py` — complete its Module 6 changes and remove all planning placeholders from executable files.
- [ ] `artifacts/laya/live.py` — complete its Module 6 changes and remove all planning placeholders from executable files.
- [ ] `packages/ai-parrot/tests/unit/laya_eval/test_laya_evidence_retention.py` — complete its Module 6 changes and remove all planning placeholders from executable files.

## Acceptance Criteria

- [ ] JSON roundtrip retains Google snake/camel version keys and Anthropic raw model while excluding fake credentials, headers and content.
- [ ] Offline resolving retained evidence matches runtime extraction for known aliases; unknown/missing/empty identities remain unverified.
- [ ] Existing provider-evidence regressions and historical report parsing remain compatible.

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/laya_eval/test_laya_evidence_retention.py -q`
- `pytest packages/ai-parrot/tests/unit/laya_eval/test_laya_live.py -q`

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
