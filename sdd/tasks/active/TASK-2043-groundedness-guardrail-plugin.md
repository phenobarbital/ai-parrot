# TASK-2043: Groundedness Guardrail Plugin (Reporting / Bot Wiring)

**Feature**: FEAT-398 — Deterministic Groundedness Scoring
**Spec**: `sdd/specs/deterministic-groundedness-scoring.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2042, FEAT-396 (guardrails-infrastructure)
**Assigned-to**: unassigned

---

## Context

Module 3 of the groundedness scoring pipeline (spec §3 Module 3, revised in
spec v0.2). The scoring engine (TASK-2041 + TASK-2042) is wired into the bot
response path as a **`GroundednessGuardrail`** — a FLAG-only plugin on the
OUTPUT pipeline of the unified guardrails infrastructure (FEAT-396). The
guardrail attaches the `GroundednessReport` to
`AIMessage.metadata["guardrails"]["groundedness"]`, emits telemetry (score +
counts only, never atom values), and is non-fatal (exception → warning, turn
completes without a report).

**IMPORTANT**: This task depends on FEAT-396 (`guardrails-infrastructure`)
landing first — specifically the `Guardrail` ABC, `GuardrailPipeline`,
`GuardrailStage`, `GuardrailAction`, `GuardrailResult`, and
`GuardrailContext` from `parrot/bots/guardrails/`. If FEAT-396 is not yet
implemented when this task is picked up, STOP and note the blocker.

---

## Scope

- Create `parrot/security/groundedness/guardrail.py`:
  - `GroundednessGuardrail(Guardrail)` — FLAG-only, OUTPUT stage.
  - `async def check(content, ctx)` → builds `EvidenceIndex` from
    `ctx.ai_message.tool_calls`, runs `GroundednessScorer.score()`,
    returns `GuardrailResult` with action=FLAG and the report in metadata.
  - Register via `register_guardrail("groundedness", ...)`.
- Wire bot kwargs:
  - `enable_groundedness: bool = False` on `AbstractBot.__init__`.
  - `groundedness_policy: dict | GroundednessPolicy | None` — coerce dict →
    `GroundednessPolicy` (same pattern as other structured kwargs).
  - When `enable_groundedness=True`, add `GroundednessGuardrail` to the bot's
    guardrail pipeline (if FEAT-396 pipeline is present).
- Telemetry: emit score + per-verdict counts via FEAT-176 lifecycle observers.
  **Never emit atom raw values** (they may contain PII).
- Non-fatal: wrap scoring in try/except at the guardrail level; log warning on
  failure; turn completes without a report.
- INFO log when a turn falls below `min_alert_score`.
- Update `parrot/security/groundedness/__init__.py` exports.

**NOT in scope**: Extractors/scorer engine (TASK-2041/2042), tests (TASK-2044),
benchmarks (TASK-2045), the guardrails infrastructure itself (FEAT-396).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/security/groundedness/guardrail.py` | CREATE | `GroundednessGuardrail` plugin |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | Add `enable_groundedness` / `groundedness_policy` kwargs (~line 379-392 area) |
| `packages/ai-parrot/src/parrot/security/groundedness/__init__.py` | MODIFY | Add guardrail exports |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# From TASK-2041/2042 (this feature)
from parrot.security.groundedness.extractors import extract_atoms
from parrot.security.groundedness.evidence import EvidenceIndex
from parrot.security.groundedness.scorer import GroundednessScorer
from parrot.security.groundedness.policy import GroundednessPolicy, GroundednessReport

# From existing codebase
from parrot.models.basic import ToolCall              # models/basic.py:23
from parrot.models.responses import AIMessage         # models/responses.py:72

# From FEAT-396 (guardrails-infrastructure) — VERIFY EXISTENCE BEFORE USING
# These are DESIGNED signatures from the FEAT-396 spec; they do NOT exist yet.
# When FEAT-396 lands, verify actual import paths and signatures.
# from parrot.bots.guardrails import (
#     Guardrail, GuardrailResult, GuardrailContext,
#     GuardrailStage, GuardrailAction, register_guardrail,
# )
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/abstract.py:379-392 (kwarg area)
self.enable_redaction: bool = bool(kwargs.pop('enable_redaction', False))
self.enable_tools: bool = kwargs.get('enable_tools', kwargs.get('use_tools', True))
# ^^^ Follow this pattern for enable_groundedness

# packages/ai-parrot/src/parrot/bots/abstract.py:3461
def get_response(
    self,
    response: AIMessage,
    return_sources: bool = True,
    return_context: bool = False,
    return_tools: bool = False,
) -> AIMessage:

# packages/ai-parrot/src/parrot/bots/base.py:1871
# Final yield of ai_message in ask_stream — the seam where scoring attaches.
yield ai_message

# packages/ai-parrot/src/parrot/models/responses.py:202
metadata: Dict[str, Any] = Field(...)   # report carrier
```

### Does NOT Exist

- ~~`parrot.bots.guardrails`~~ — FEAT-396, not implemented yet. This task BLOCKS on it.
- ~~`AIMessage.groundedness`~~ — not a field. Report goes in `metadata["guardrails"]["groundedness"]`.
- ~~`parrot.security.pii`~~ — FEAT-324, not implemented. Do NOT import.
- ~~Direct scoring hooks in `get_response()`/`ask_stream()`~~ — spec v0.2
  delegates to the guardrails pipeline (FEAT-396); do NOT add inline scoring
  code to these methods. The guardrail plugin runs as part of the pipeline.

---

## Implementation Notes

### Pattern to Follow

```python
# guardrail.py — follows the Guardrail ABC from FEAT-396
class GroundednessGuardrail(Guardrail):
    stage = GuardrailStage.OUTPUT
    action = GuardrailAction.FLAG

    def __init__(self, policy: GroundednessPolicy | None = None):
        self.policy = policy or GroundednessPolicy()
        self.scorer = GroundednessScorer(self.policy)

    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult:
        # Build evidence from tool_calls on the AIMessage
        # Score the content
        # Return FLAG result with report in metadata
        ...
```

### Key Constraints

- The guardrail is FLAG-only: it never modifies, masks, or blocks the response.
- **Scoring-only invariant**: response text delivered to caller MUST be byte-identical
  whether scoring is on or off.
- Telemetry: score + verdict counts only. **Never emit atom raw values** through
  telemetry — they may contain emails, IDs, or other sensitive data.
- Non-fatal: any exception in scoring → `self.logger.warning(...)`, turn succeeds
  without a report. Mirror the FEAT-252 scrubber failure contract.
- Dict-to-policy coercion: `groundedness_policy` kwarg accepts `dict | GroundednessPolicy | None`.
- INFO log when `report.score < policy.min_alert_score`.

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/abstract.py:379` — kwarg pattern area.
- `packages/ai-parrot/src/parrot/bots/abstract.py:3461` — `get_response()` seam.
- `packages/ai-parrot/src/parrot/bots/base.py:1871` — `ask_stream` final yield seam.
- `packages/ai-parrot/src/parrot/security/redaction.py` — FEAT-252 non-fatal pattern.
- FEAT-396 spec: `sdd/specs/guardrails-infrastructure.spec.md`.

---

## Acceptance Criteria

- [ ] `GroundednessGuardrail` registered as a guardrail plugin.
- [ ] Bot kwarg `enable_groundedness=True` activates the guardrail.
- [ ] Dict → `GroundednessPolicy` coercion works.
- [ ] Report attached to `AIMessage.metadata["guardrails"]["groundedness"]`.
- [ ] Response text is byte-identical with scoring on vs off.
- [ ] Scorer exception → warning log, turn completes without report.
- [ ] Telemetry carries score + counts, never atom raw values.
- [ ] INFO log on turns below `min_alert_score`.
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/security/groundedness/`

---

## Test Specification

```python
# tests/unit/security/test_groundedness_guardrail.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.security.groundedness.guardrail import GroundednessGuardrail
from parrot.security.groundedness.policy import GroundednessPolicy


class TestGroundednessGuardrail:
    @pytest.mark.asyncio
    async def test_flag_only_no_mutation(self):
        """Response text is byte-identical with scoring on vs off."""
        # Setup: mock GuardrailContext with AIMessage + tool_calls
        # Assert: result.action == FLAG, content unchanged

    @pytest.mark.asyncio
    async def test_scorer_exception_nonfatal(self):
        """Scorer exception → warning, turn succeeds."""
        # Patch scorer.score to raise → guardrail returns gracefully

    @pytest.mark.asyncio
    async def test_telemetry_no_atom_values(self, caplog):
        """Emitted telemetry contains score/counts, never raw atom values."""
        # Run guardrail, inspect caplog / observer capture
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/deterministic-groundedness-scoring.spec.md` for full context
2. **Check dependencies** — verify TASK-2042 is done AND FEAT-396 guardrails-infrastructure is implemented
3. **If FEAT-396 is not implemented**: STOP, note the blocker, do not proceed
4. **Verify the Codebase Contract** — confirm FEAT-396 exports exist, confirm bot kwarg area
5. **Update status** in `sdd/tasks/index/deterministic-groundedness-scoring.json` → `"in-progress"`
6. **Implement** following the scope, codebase contract, and notes above
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-2043-groundedness-guardrail-plugin.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
