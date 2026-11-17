# TASK-5468: Add explicit cheap baseline, coverage and bounded lifecycle

**Feature**: FEAT-589 — Laya capability evaluation follow-up
**Spec**: `sdd/specs/laya-adoption.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5467, TASK-3618
**Assigned-to**: unassigned

## Context

Implement reopened spec Module 8. The original worker placeholders were fixed;
archived task blueprint stubs are not runtime defects. This task addresses a measured
evaluation gap while preserving earlier reports and completed task history.

## Scope

- Implement opt-in include_cheap_baseline config/CLI, separate cheap arm, distinct model preflight and atomic reserve_group(3), preserving default pairs.
- Report each arm and actual-model coverage separately; do not count the baseline as a Laya choice or infer savings from model names.
- Return null cost when any counted arm sample lacks usable price/usage; preserve known zero-cost totals as zero.
- Close the configured Agent in finally on success/error/cancellation; update fake and opt-in real integration coverage plus README commands.

**NOT in scope**: production integration, dependency changes, SDK-direct calls, automatic paid runs, retroactive changes to prior metrics.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `artifacts/laya/models.py` | MODIFY | Module 8 scoped implementation or regression evidence |
| `artifacts/laya/live.py` | MODIFY | Module 8 scoped implementation or regression evidence |
| `artifacts/laya/evaluate.py` | MODIFY | Module 8 scoped implementation or regression evidence |
| `artifacts/laya/reporting.py` | MODIFY | Module 8 scoped implementation or regression evidence |
| `artifacts/laya/README.md` | MODIFY | Module 8 scoped implementation or regression evidence |
| `packages/ai-parrot/tests/unit/laya_eval/test_laya_cheap_baseline.py` | CREATE | Module 8 scoped implementation or regression evidence |
| `packages/ai-parrot/tests/integration/test_laya_evaluation.py` | MODIFY | Module 8 scoped implementation or regression evidence |

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

- `artifacts/laya/models.py:97` — `class EvaluationConfig(_Record):`; read continuation lines for full signature.
- `artifacts/laya/models.py:163` — `class SampleResult(_Record):`; read continuation lines for full signature.
- `artifacts/laya/live.py:59` — `class LiveCallBudget:`; read continuation lines for full signature.
- `artifacts/laya/live.py:202` — `async def run_live_routing_pairs(`; read continuation lines for full signature.
- `artifacts/laya/evaluate.py:141` — `async def run_evaluation(`; read continuation lines for full signature.
- `artifacts/laya/reporting.py:71` — `def _routing_block(group: list[SampleResult], prices: dict[str, dict[str, Any]] | None) -> dict[str, Any]:`; read continuation lines for full signature.
- `artifacts/laya/reporting.py:47` — `def _cost(samples: list[SampleResult], prices: dict[str, dict[str, Any]] | None) -> float | None:`; read continuation lines for full signature.

- `packages/ai-parrot/src/parrot/bots/abstract.py:5450` — `async def cleanup(self) -> None`; inherited Agent cleanup closes its client and owned resources.

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
      "path": "artifacts/laya/reporting.py",
      "action": "MODIFY"
    },
    {
      "path": "artifacts/laya/README.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/laya_eval/test_laya_cheap_baseline.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/integration/test_laya_evaluation.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:artifacts/laya/evaluate.py#run_evaluation",
    "sym:artifacts/laya/live.py#LiveCallBudget",
    "sym:artifacts/laya/live.py#run_live_routing_pairs",
    "sym:artifacts/laya/models.py#EvaluationConfig",
    "sym:artifacts/laya/models.py#EvaluationReport",
    "sym:artifacts/laya/models.py#RouteDecision",
    "sym:artifacts/laya/models.py#SampleResult",
    "sym:artifacts/laya/reporting.py#_cost",
    "sym:artifacts/laya/reporting.py#_routing_block",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.cleanup",
    "sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessage"
  ]
}
```

## Implementation Notes

Follow spec Module 8 exactly. Keep synchronous validation before asynchronous work.
Use existing Pydantic v2 records and asyncio Agent dispatch. Preserve legacy report defaults.

## Implementation Blueprint

### Steps (in order)

1. Implement opt-in include_cheap_baseline config/CLI, separate cheap arm, distinct model preflight and atomic reserve_group(3), preserving default pairs. This preserves the spec boundary and prevents misleading completion evidence.
2. Report each arm and actual-model coverage separately; do not count the baseline as a Laya choice or infer savings from model names. This preserves the spec boundary and prevents misleading completion evidence.
3. Return null cost when any counted arm sample lacks usable price/usage; preserve known zero-cost totals as zero. This preserves the spec boundary and prevents misleading completion evidence.
4. Close the configured Agent in finally on success/error/cancellation; update fake and opt-in real integration coverage plus README commands. This preserves the spec boundary and prevents misleading completion evidence.

### `artifacts/laya/models.py` (MODIFY)

Attachment anchor: `class SampleResult(_Record):` — `artifacts/laya/models.py:163`, occurrences `1` (verified with grep -F -c).

```python
# Extend EvaluationConfig:
include_cheap_baseline: bool = False
# Extend SampleResult's existing arm field:
arm: Literal["local", "primary", "routed", "cheap"] = "local"
# FILL IN: include_cheap_baseline preflight requires live routing mode and distinct IDs.
```

### `artifacts/laya/live.py` (MODIFY)

Attachment anchor: `async def run_live_routing_pairs(` — `artifacts/laya/live.py:202`, occurrences `1` (verified with grep -F -c).

```python
# Add to LiveCallBudget; keep reserve_pair as a wrapper around reserve_group(2).
def reserve_group(self, size: int) -> bool:
    """Reserve positive size atomically or decline without consuming any slots."""
    # FILL IN: positive integer validation and cap handling; bounded by R3.
    raise NotImplementedError

# In run_live_routing_pairs retain its current signature. Derive group size from
# config.include_cheap_baseline, reserve before any arm, and append cheap last with
# RouteDecision(choice="cheap", selected_model=config.cheap_api_model,
#               confidence=None, reason="cheap_baseline").
# FILL IN: budget failure records call_cap_reached without partial dispatch.
```

### `artifacts/laya/evaluate.py` (MODIFY)

Attachment anchor: `async def run_evaluation(` — `artifacts/laya/evaluate.py:141`, occurrences `1` (verified with grep -F -c).

```python
# In build_parser:
parser.add_argument("--include-cheap-baseline", action="store_true")
# In run_evaluation wrap configure/live calls in try/finally awaiting agent.cleanup().
# FILL IN: validate selected arms before calls and surface missing model evidence;
# preserve cancellation, include the cheap samples in the report, bounded by R3/R4.
```

### `artifacts/laya/reporting.py` (MODIFY)

Attachment anchor: `def _routing_block(` — `artifacts/laya/reporting.py:71`, occurrences `1` (verified with grep -F -c).

```python
# In _routing_block include a separate cheap arm only when requested/present.
# Add coverage: attempted calls, verified arms, actual model IDs and whether the
# cheap baseline returned the configured ID. Baseline samples never enter proportions.
# In _cost, missing price/usage for any sample makes the entire arm cost None;
# a known zero cost stays 0.0. FILL IN: branch tests bounded by R4.
```

### `artifacts/laya/README.md` (MODIFY)

Attachment anchor: `## Google paid verification` — `artifacts/laya/README.md:146`, occurrences `1` (verified with grep -F -c).

```markdown
## Reopened evaluation verification

Document provider-evidence replay, explicit --rubric-file v2 selection and
--include-cheap-baseline. Explain default pairs vs three-call groups, actual-model
mismatches, the same client fallback not proving cost, and null partial-price totals.
FILL IN: exact offline and opt-in paid commands after implementing R1–R4; never fabricate results.
```

### `packages/ai-parrot/tests/unit/laya_eval/test_laya_cheap_baseline.py` (CREATE)

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

### `packages/ai-parrot/tests/integration/test_laya_evaluation.py` (MODIFY)

Attachment anchor: `async def test_live_paired_routing(` — `packages/ai-parrot/tests/integration/test_laya_evaluation.py:199`, occurrences `1` (verified with grep -F -c).

```python
# Extend _FakeAgent with async cleanup and track dispatch order/models/settings.
# Add a three-arm mocked run and assert actual-model evidence, no partial cap group,
# independent Laya routing proportions, and cleanup after errors/cancellation.
# Keep the real integration opt-in. New paid baseline run requires explicit flags/cap.
# FILL IN: tests exercise R3/R4 through evaluate.main, with no real credentials.
```

### FILL IN checklist

- [ ] `artifacts/laya/models.py` — complete its Module 8 changes and remove all planning placeholders from executable files.
- [ ] `artifacts/laya/live.py` — complete its Module 8 changes and remove all planning placeholders from executable files.
- [ ] `artifacts/laya/evaluate.py` — complete its Module 8 changes and remove all planning placeholders from executable files.
- [ ] `artifacts/laya/reporting.py` — complete its Module 8 changes and remove all planning placeholders from executable files.
- [ ] `artifacts/laya/README.md` — complete its Module 8 changes and remove all planning placeholders from executable files.
- [ ] `packages/ai-parrot/tests/unit/laya_eval/test_laya_cheap_baseline.py` — complete its Module 8 changes and remove all planning placeholders from executable files.
- [ ] `packages/ai-parrot/tests/integration/test_laya_evaluation.py` — complete its Module 8 changes and remove all planning placeholders from executable files.

## Acceptance Criteria

- [ ] Default pair still takes two calls; enabled baseline takes exactly three per case in primary/routed/cheap order with identical generation settings.
- [ ] A cap below the required group size dispatches zero calls; previous failed calls still consume slots.
- [ ] Primary/routed/cheap use the configured per-call model without changing the client default or Laya threshold.
- [ ] Reports distinguish configured from provider-returned cheap model, missing evidence and alias mismatch; no partial-price total is reported as complete.
- [ ] Fake-agent tests prove cleanup on normal/error/cancel paths; real test stays opt-in and never calls providers during routine validation.

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/laya_eval/test_laya_cheap_baseline.py -q`
- `pytest packages/ai-parrot/tests/unit/laya_eval/test_laya_reporting.py -q`
- `pytest packages/ai-parrot/tests/unit/laya_eval/test_laya_live_pairs.py -q`
- `pytest packages/ai-parrot/tests/integration/test_laya_evaluation.py -q`

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
