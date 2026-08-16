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

# From FEAT-396 (guardrails-infrastructure) — VERIFIED 2026-08-01, worktree
# merged origin/dev @ 16f53dbc7 (PR #1094) to pick up the landed feature.
from parrot.bots.guardrails import (
    Guardrail, GuardrailAction, GuardrailContext, GuardrailResult,
    GuardrailStage, register_guardrail,
)
```

**Contract correction (2026-08-01, this task):** `GuardrailContext` (base.py)
has NO `ai_message` field — it only carries `stage`/`agent_name`/`user_id`/
`session_id`/`method`/`tool_name`/`extras: dict[str, Any]`. The OUTPUT-stage
context built in `_run_output_pipeline` (`abstract.py:1928`) only set
`extras={'chatbot_id': ...}` — no tool_calls were available to a FLAG
guardrail. Fixed by adding `extras['ai_message'] = response` at that call
site (the only OUTPUT-pipeline `ctx` construction site) so
`GroundednessGuardrail.check()` reads `ctx.extras.get("ai_message")` for
`.tool_calls` / `.input` (user prompt), instead of the non-existent
`ctx.ai_message`.

Also: `registry.py`'s `_RESERVED_NAMES` dict (added in FEAT-396,
`bots/guardrails/registry.py:31-35`) explicitly reserves `"groundedness"` and
raises `NotImplementedError` from `_build_by_name`/`build_guardrails` until
this feature unreserves it — its own docstring anticipates this. Since the
Scope explicitly calls for `register_guardrail("groundedness", ...)`, this
task also touches `bots/guardrails/registry.py` (not in the original file
list) to remove the reservation and add the lazy factory registration,
matching the `prompt_injection`/`secrets`/`moderation` pattern exactly —
otherwise `guardrails=["groundedness"]`/dict-config would keep raising
`NotImplementedError` even after this task ships.

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

**Completed by**: sdd-worker (Claude Sonnet 4.5)
**Date**: 2026-08-01
**Notes**: Worktree was created before FEAT-396 landed on `dev`; merged
`origin/dev` (PR #1094, `16f53dbc7`) into the feature branch first to bring
in the guardrails infrastructure (main repo's local `dev` was independently
stuck mid-merge-conflict on the same PR — untouched, worked entirely from
`origin/dev` instead). Implemented `GroundednessGuardrail` (OUTPUT stage,
FLAG-only, priority 200 observer band) in
`parrot/security/groundedness/guardrail.py`; wired `enable_groundedness` /
`groundedness_policy` (dict→`GroundednessPolicy` coercion) into
`AbstractBot.__init__` right after `_guardrail_pipelines` is built (deferred
`from parrot.security.groundedness...` import inside `__init__` to avoid a
`parrot.bots` ⇄ `parrot.security.groundedness` import cycle through
`parrot.bots.guardrails`). Verified manually: default-off (no guardrail
registered, `enable_groundedness=False`/`groundedness_policy=None`), dict
policy coercion, FLAG report with score+counts attached, non-fatal PASS on
a forced scoring exception (warning logged, no report), and graceful
`no_evidence` fallback when `ctx.extras["ai_message"]` is absent. Existing
guardrails test suite (116 tests across
`test_guardrails_{core_models,pipeline,registry_config,moderation,secrets,
prompt_injection,input_migration}.py` + `integration/test_guardrails_
output.py`) passes. `ruff check` clean on all touched/created files.

**Deviations from spec**:
1. **Contract correction**: `GuardrailContext` has no `.ai_message` field
   (only `extras: dict[str, Any]`). Added `extras['ai_message'] = response`
   at the sole OUTPUT-stage `GuardrailContext` construction site
   (`abstract.py::_run_output_pipeline`, ~line 1928) so the guardrail can
   read `tool_calls`/`input` — `check()` reads
   `ctx.extras.get("ai_message")` instead of the non-existent
   `ctx.ai_message`. Covers both `ask()` and `ask_stream()` (both already
   route through `_run_output_pipeline`), so no `base.py` change was
   needed despite the Codebase Contract citing a `base.py:1871` seam.
2. **Extra file touched**: `parrot/bots/guardrails/registry.py` — the
   Scope explicitly requires `register_guardrail("groundedness", ...)`,
   but FEAT-396's `_RESERVED_NAMES` dict reserved `"groundedness"` and
   raised `NotImplementedError` from `build_guardrails`/`_build_by_name`
   until unreserved (its own docstring anticipates this hand-off).
   Removed the reservation and added the lazy-factory registration,
   matching the `prompt_injection`/`secrets`/`moderation` pattern exactly.
3. **Extra file touched**: `tests/unit/test_guardrails_registry_config.py`
   — `test_reserved_groundedness_raises` asserted the now-obsolete
   reserved-name behavior; replaced with `test_groundedness_builds`
   asserting the guardrail now builds successfully by name.

Telemetry ("score + counts, never atom values") is emitted via
`self.logger.info(...)` inside `check()` (score + per-verdict counts only,
no atom raw values) rather than a new FEAT-176 lifecycle event class —
`events.py` was not in this task's file list, the spec's Test
Specification explicitly validates telemetry via `caplog`, and every
guardrail execution already gets a content-free `GuardrailActionEvent`
(name/stage/action/duration) automatically via the pre-existing
`on_telemetry` wiring, so no infrastructure gap was left unaddressed.
