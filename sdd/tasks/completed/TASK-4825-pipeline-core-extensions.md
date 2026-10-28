# TASK-4825: Pipeline core extensions — per-stage priority, orthogonal reports, `requires_system_prompt`

**Feature**: FEAT-761 — Agent Security Guardrails (Jailbreak, Tool-Output Injection, Prompt Leakage)
**Spec**: `sdd/specs/agent-security-guardrails.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (design-research S1 + S7). Two defects in the FEAT-396 pipeline
block the new guardrails:

1. **Reports are tied to actions.** `GuardrailPipeline.run()` collects `result.report`
   only for BLOCK and FLAG (`pipeline.py:190-197`). A TRANSFORM's report is silently
   dropped — but TOOL_OUTPUT injection wrapping (TASK-4833) and leakage redaction
   (TASK-4836) both need TRANSFORM **plus** a report. Verified: no existing guardrail
   attaches a report to TRANSFORM/PASS today, so surfacing them changes no current
   metadata.
2. **Priority is a single scalar.** `PromptLeakageGuardrail` is a sanitizer on INPUT
   (12) but an observer on OUTPUT (220). Also `SecretsGuardrail` and
   `PromptInjectionGuardrail` both use priority 10, so TOOL_OUTPUT order depends on
   registration order once injection scans tool output.

Also adds the `requires_system_prompt` class flag TASK-4837 reads to decide whether to
put the rendered system prompt into OUTPUT `ctx.extras` (zero-overhead discipline).

---

## Scope

- Change `Guardrail.priority` to `int | dict[GuardrailStage, int]` and add
  `Guardrail.priority_for(stage)`.
- Add `Guardrail.requires_system_prompt: ClassVar[bool] = False`.
- Make `GuardrailPipeline.run()` order guardrails by `priority_for(ctx.stage)`
  (cached per stage, invalidated on `add()`), stable for ties.
- Surface `result.report` into `flag_reports` for TRANSFORM and PASS results too
  (only when the report is truthy).
- Write unit tests.

**NOT in scope**: changing any existing guardrail's priority value; config.py; any
new guardrail; the `GuardrailPipeline.__init__` signature (do NOT add a `stage` arg —
`config.py` builds one pipeline per stage without passing it, and changing that is
TASK-4826's file).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/guardrails/base.py` | MODIFY | per-stage priority type + `priority_for()` + `requires_system_prompt` |
| `packages/ai-parrot/src/parrot/bots/guardrails/pipeline.py` | MODIFY | stage-aware ordering in `run()`; reports for TRANSFORM/PASS |
| `packages/ai-parrot/tests/unit/test_guardrails_stage_priority_reports.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.guardrails.base import (
    Guardrail, GuardrailAction, GuardrailContext, GuardrailResult, GuardrailStage,
)  # verified: bots/guardrails/base.py:15,32,47,65,97
from parrot.bots.guardrails.pipeline import GuardrailPipeline, PipelineOutcome
    # verified: bots/guardrails/pipeline.py:84,62
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/guardrails/base.py
from typing import Any, Literal          # :10  (ClassVar NOT imported yet — add it)
class GuardrailStage(str, Enum):         # :15 — INPUT/TOOL_OUTPUT/OUTPUT/OUTPUT_STREAM/TOOL_CALL
class Guardrail(ABC):                    # :97
    name: str                            # :119
    stages: set[GuardrailStage]          # :120
    priority: int                        # :121
    on_error: Literal["fail_open", "fail_closed"] = "fail_open"  # :122
    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult:  # :125

# packages/ai-parrot/src/parrot/bots/guardrails/pipeline.py
class GuardrailPipeline:                 # :84
    def __init__(self, on_telemetry=None) -> None:   # :99 — sets self._guardrails :108
    def add(self, guardrail: Guardrail) -> None:     # :112 — sorts at :119
    @property guardrails -> tuple[Guardrail, ...]    # :127 — priority order (used by tools/abstract.py non-string scrub)
    async def run(self, content: str, ctx: GuardrailContext) -> PipelineOutcome:  # :138
        # loop: for guardrail in self._guardrails:   # :158
        # BLOCK report :190-191 · TRANSFORM :193-195 (report dropped) · FLAG :196-197
```

### Does NOT Exist
- ~~`Guardrail.priority_for()`~~ — created by this task.
- ~~`Guardrail.requires_system_prompt`~~ — created by this task.
- ~~`GuardrailPipeline(stage=...)`~~ — the pipeline does NOT know its stage; do not add one.
- ~~`PipelineOutcome.reports`~~ — the field is `flag_reports`; keep the name (seams read it).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/bots/guardrails/base.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/bots/guardrails/pipeline.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/test_guardrails_stage_priority_reports.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/guardrails/base.py#Guardrail",
    "sym:packages/ai-parrot/src/parrot/bots/guardrails/pipeline.py#GuardrailPipeline",
    "sym:packages/ai-parrot/src/parrot/bots/guardrails/pipeline.py#GuardrailPipeline.run",
    "sym:packages/ai-parrot/src/parrot/bots/guardrails/pipeline.py#GuardrailPipeline.add"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Back-compat is absolute**: a scalar `priority` behaves exactly as today; ties keep
  registration order (stable sort); `guardrails` property keeps returning the
  scalar-resolved order.
- Ordering cost must stay negligible (FEAT-396 gate: p99 < 0.5 ms for 3 no-op
  guardrails) — cache the per-stage order, never re-sort on every `run()`.
- `run()` on an empty pipeline must still short-circuit before any ordering work.

---

## Implementation Blueprint

### Steps (in order)
1. Edit `base.py`: widen `priority`, add `requires_system_prompt` and `priority_for()` —
   *why*: leakage needs different bands per stage; the flag lets OUTPUT seams skip
   prompt plumbing when nobody needs it.
2. Edit `pipeline.py`: add an order cache, invalidate it in `add()`, use it in `run()` —
   *why*: the pipeline only learns its stage from `ctx.stage` at run time.
3. Edit the TRANSFORM/PASS branches to surface truthy reports — *why*: S1, TRANSFORM +
   report is the TOOL_OUTPUT wrap contract.
4. Write tests; run the existing pipeline suite unchanged — *why*: compat invariant.

### `packages/ai-parrot/src/parrot/bots/guardrails/base.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from typing import Any, Literal' base.py)
# REPLACE `from typing import Any, Literal` (verified: base.py:10) with:
from typing import Any, ClassVar, Literal
```
```python
# occurrences: 1 (verified: grep -c '    priority: int' base.py)
# REPLACE `    priority: int` (verified: base.py:121) with:
    priority: int | dict[GuardrailStage, int]
```
```python
# occurrences: 1 (verified: grep -c '    on_error: Literal["fail_open", "fail_closed"] = "fail_open"' base.py)
# AFTER — insert below `    on_error: Literal["fail_open", "fail_closed"] = "fail_open"` (verified: base.py:122)
    #: Set True by OUTPUT guardrails that compare against the turn's rendered
    #: system prompt (FEAT-761 prompt leakage); seams only populate
    #: ``ctx.extras["system_prompt"]`` when a registered guardrail asks for it.
    requires_system_prompt: ClassVar[bool] = False

    def priority_for(self, stage: GuardrailStage | None) -> int:
        """Resolve this guardrail's effective priority for ``stage``.

        A scalar ``priority`` applies to every stage (pre-FEAT-761 behavior).
        A ``{stage: int}`` mapping lets one guardrail sit in different bands
        per stage; a stage missing from the mapping (or ``stage=None``)
        resolves to the mapping's lowest value.

        Args:
            stage: The stage being ordered, or ``None`` for a stage-agnostic order.

        Returns:
            The integer priority (lower runs first).
        """
        # FILL IN: int -> return it; dict -> dict.get(stage) when stage in it, else min(values) — bounded by "scalar behaves exactly as today"
```
Also update the class docstring's `priority:` attribute line to mention the mapping form.

**Why this shape**: `priority_for(None)` gives the pipeline a deterministic
stage-agnostic order for the public `guardrails` property without changing it for
scalar guardrails. Do not convert existing scalar priorities anywhere.

### `packages/ai-parrot/src/parrot/bots/guardrails/pipeline.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        self._guardrails: list[Guardrail] = []' pipeline.py)
# AFTER — insert below `        self._guardrails: list[Guardrail] = []` (verified: pipeline.py:108)
        # Per-stage execution order, built lazily from `priority_for(stage)`
        # and invalidated on every `add()` (FEAT-761 per-stage priority).
        self._order_cache: dict[GuardrailStage, tuple[Guardrail, ...]] = {}
```
```python
# occurrences: 1 (verified: grep -c '        self._guardrails.sort(key=lambda g: g.priority)' pipeline.py)
# REPLACE `        self._guardrails.sort(key=lambda g: g.priority)` (verified: pipeline.py:119) with:
        self._guardrails.sort(key=lambda g: g.priority_for(None))
        self._order_cache.clear()

    def _ordered_for(self, stage: GuardrailStage) -> tuple[Guardrail, ...]:
        """Return guardrails in execution order for ``stage`` (cached, stable for ties)."""
        # FILL IN: return cached tuple, else sorted(self._guardrails, key=lambda g: g.priority_for(stage)) stored in cache — bounded by stable-sort tie order
```
```python
# occurrences: 1 (verified: grep -c '        for guardrail in self._guardrails:' pipeline.py)
# REPLACE `        for guardrail in self._guardrails:` (verified: pipeline.py:158) with:
        for guardrail in self._ordered_for(ctx.stage):
```
```python
# occurrences: 1 (verified: grep -c '            elif result.action == GuardrailAction.TRANSFORM:' pipeline.py)
# REPLACE the TRANSFORM branch + PASS comment (verified: pipeline.py:193-198):
            elif result.action == GuardrailAction.TRANSFORM:
                if result.content is not None:
                    working_content = result.content
                # FEAT-761 (S1): a TRANSFORM may carry a non-content report
                # (e.g. TOOL_OUTPUT injection wrap, leakage redaction counts).
                if result.report:
                    flag_reports[guardrail.name] = result.report
            elif result.action == GuardrailAction.FLAG:
                flag_reports[guardrail.name] = result.report or {}
            elif result.report:
                # PASS with a (non-content) report — surfaced the same way.
                flag_reports[guardrail.name] = result.report
```
Update the `PipelineOutcome.flag_reports` docstring to "reports keyed by guardrail
name — from FLAG, and from any other action that attached one".

**Why**: keeps `flag_reports` as the single channel every seam already reads
(`_run_output_pipeline`, `_merge_guardrail_reports`, `tools/abstract.py`).

### `packages/ai-parrot/tests/unit/test_guardrails_stage_priority_reports.py` (CREATE)
```python
"""FEAT-761 TASK-4825 — per-stage priority + orthogonal reports."""
from typing import ClassVar

import pytest

from parrot.bots.guardrails.base import (
    Guardrail, GuardrailAction, GuardrailContext, GuardrailResult, GuardrailStage,
)
from parrot.bots.guardrails.pipeline import GuardrailPipeline


class _Recorder(Guardrail):
    """Stub guardrail that records call order and returns a fixed result."""

    stages: ClassVar[set] = {GuardrailStage.INPUT, GuardrailStage.OUTPUT}

    def __init__(self, name, priority, result, log):
        self.name, self.priority, self._result, self._log = name, priority, result, log

    async def check(self, content, ctx):
        self._log.append(self.name)
        return self._result


def _ctx(stage):
    return GuardrailContext(stage=stage, agent_name="t")

# FILL IN: tests — scalar order unchanged; dict priority orders differently on INPUT vs OUTPUT;
# ties keep registration order; priority_for(None) = min; add() invalidates cache;
# TRANSFORM+report surfaces in flag_reports; PASS+report surfaces; TRANSFORM without report adds nothing;
# BLOCK/FLAG behavior unchanged — bounded by AC list below
```

### FILL IN checklist
- [ ] `base.py::Guardrail.priority_for` — scalar/dict/None resolution; bounded by back-compat
- [ ] `pipeline.py::GuardrailPipeline._ordered_for` — cached stable sort; bounded by perf gate
- [ ] tests — all cases listed above

---

## Acceptance Criteria

- [ ] Scalar-priority guardrails run in exactly the pre-change order (existing suites green).
- [ ] A guardrail with `priority={INPUT: 12, OUTPUT: 220}` sorts by the stage of `ctx`.
- [ ] TRANSFORM and PASS results with a truthy `report` appear in `PipelineOutcome.flag_reports`.
- [ ] `requires_system_prompt` defaults to `False` on every existing guardrail.
- [ ] `ruff check` clean on both modified files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_guardrails_stage_priority_reports.py -q`
- `pytest packages/ai-parrot/tests/unit/test_guardrails_pipeline.py -q`
- `pytest packages/ai-parrot/tests/unit/test_guardrails_core_models.py -q`

---

## Test Specification

See the CREATE block above; minimum cases: scalar order, per-stage dict order, tie
stability, cache invalidation, TRANSFORM report surfaced, PASS report surfaced,
TRANSFORM without report → no entry.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug agent-security-guardrails --feature-id FEAT-761`), never on `dev`.
2. Read the spec; confirm `Depends-on` tasks are `done` in `sdd/tasks/index/agent-security-guardrails.json`.
3. Re-verify every anchor above (`grep -c`); fix the contract first if drifted.
4. Mark `in-progress`, implement from the blueprint, complete every `# FILL IN:`.
5. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
6. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4825 agent-security-guardrails verified`; fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Seat: gpt-5.6-terra · Backend: codex · Attempts: 1)
**Date**: 2026-10-27
**Notes**: Delivered and merged; merge-tier validation green. Closed via close_task.sh (no durable review-evidence artifact writable). Deliverable reviewed by worker at merge.

**Deviations from spec**: none
