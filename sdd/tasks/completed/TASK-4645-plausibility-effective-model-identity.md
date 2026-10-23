# TASK-4645: Record the effective LLM identity on `PlausibilityReport`

**Feature**: FEAT-732 — FormDesigner validation audit trail
**Spec**: `sdd/specs/formdesigner-validation-audit-trail.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The second FEAT-732 gap: `LLMValidationConfig.model` is `str | None`, and when it is
`None` the client's default model answers — but every `PlausibilityReport(...)` in
`services/plausibility.py` passes `model=cfg.model`, so the stored record says `null`
and never says which model answered. This task adds `resolved_model`, `provider` and
`usage`, read off the response `AIMessage`, and refuses to persist an LLM-produced `ok`
that cannot be attributed. Implements spec §2 F and §3 Module 4 (first half — keeping the
fields off the wire is TASK-4646). It is a root of the task graph.

---

## Scope

- Add `resolved_model`, `provider`, `usage` to `PlausibilityReport`. **Do not** change
  the meaning or the value of the existing `model` field (spec NG4, AC10).
- Add `AnswerPlausibilityChecker._identity(response)` and use it in `check()`.
- Fill the three fields on the LLM-produced `ok` return.
- Route an LLM response that parses but carries no effective model through `_fail()`,
  so it meets `on_error` (`skipped` under `skip`, `PlausibilityBlocked` under `block`).
- Give the four existing plausibility test fakes a `model`/`provider`, so they keep
  producing `ok` under the new rule.
- Write unit tests for the new behaviour.

**NOT in scope**:
- Excluding the new fields from client-facing responses — TASK-4646. Between this task
  and that one the HTTP 200 body briefly carries them; no existing test asserts on it.
- The two **no-call** `ok` returns (`check()` lines 183-184 and 188-189: no eligible
  fields / no renderable items). They make no LLM call, so there is no identity to
  record: leave them exactly as they are — `resolved_model` stays `None`. Do not turn
  them into `skipped` and do not populate `reason` there: either would change the
  FEAT-728 wire shape (spec NG3). This is the precise reading of spec AC11.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py` | MODIFY | Three new optional fields on `PlausibilityReport` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py` | MODIFY | `_identity()`; fill the fields; unidentified `ok` → `_fail()` |
| `packages/parrot-formdesigner/tests/formdesigner/test_plausibility_identity.py` | CREATE | Unit tests for this task |
| `packages/parrot-formdesigner/tests/formdesigner/test_plausibility_checker.py` | MODIFY | Fake message gains `model`/`provider` |
| `packages/parrot-formdesigner/tests/formdesigner/test_http_plausibility.py` | MODIFY | Fake message gains `model`/`provider` |
| `packages/parrot-formdesigner/tests/formdesigner/test_llm_quota_http.py` | MODIFY | Fake message gains `model`/`provider` |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_v2_integration.py` | MODIFY | Fake message gains `model`/`provider` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.llm_validation import LLMValidationConfig, PlausibilityReport  # verified: core/llm_validation.py:28,70
from parrot_formdesigner.services.plausibility import (  # verified: services/plausibility.py:166,43,49
    AnswerPlausibilityChecker,
    PlausibilityBatch,
    PlausibilityBlocked,
)
```
`core/llm_validation.py` already imports `Literal` from `typing` and `BaseModel, Field`
from pydantic (lines 9-11). Add `Any` to the `typing` import for the `usage` field.

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py
class PlausibilityReport(BaseModel):                   # line 70
    status: Literal["ok", "skipped", "blocked"]
    reason: str | None = None
    model: str | None = None                           # line 75 — UNCHANGED (what the config requested)
    threshold: float
    latency_ms: int | None = None
    items: dict[str, PlausibilityVerdict] = Field(default_factory=dict)   # line 78 ← anchor

# packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py
class AnswerPlausibilityChecker:                       # line 166
    async def check(self, form, scalars, *, locale, fields=None) -> PlausibilityReport:  # line 177
        # line 183-184 — `if not targets:` → no-call ok return  (LEAVE AS IS)
        # line 185-186 — `if self._client is None:` → self._fail(...)
        # line 188-189 — `if not items:` → no-call ok return   (LEAVE AS IS)
        # line 195-200 — try: response = await asyncio.wait_for(...); batch = self._parse(response)
        #                except Exception: return self._fail(f"llm_error: {type(exc).__name__}")
        # line 215-217 — the LLM-produced ok return  ← fill the three fields here
    def _parse(self, response: Any) -> PlausibilityBatch: ...   # line 219
    def _fail(self, reason: str) -> PlausibilityReport: ...     # line 238 — raises under on_error="block"

# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage(BaseModel):                            # line 93
    model: str        # line 138 — REQUIRED
    provider: str     # line 139 — REQUIRED
    usage: CompletionUsage   # line 143 — REQUIRED; a pydantic BaseModel (basic.py:48)
```

### Does NOT Exist
- ~~`PlausibilityReport.resolved_model` / `.provider` / `.usage`~~ — this task adds them.
- ~~`AIMessage.model_name`~~ / ~~`AIMessage.llm`~~ — the field is `model` (`responses.py:138`).
- ~~`AbstractClient.resolved_model`~~ / ~~`.effective_model`~~ — do not exist. `client.model`
  exists but **can be `None`** (`clients/base.py:424`) — never read identity off the client.
- ~~`PlausibilityItemOut.model`~~ — the per-item LLM output carries no model (`plausibility.py:34-39`).
- ~~a fake client returning a real `AIMessage`~~ — the existing fakes build a throwaway
  `type("Msg", (), {...})()` object; read attributes with `getattr(..., None)`, never
  `isinstance(response, AIMessage)`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_plausibility_identity.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_plausibility_checker.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_http_plausibility.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_llm_quota_http.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_v2_integration.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py#PlausibilityReport",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py#AnswerPlausibilityChecker",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py#AnswerPlausibilityChecker.check",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py#AnswerPlausibilityChecker._fail",
    "sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessage"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The response is the source of truth, never the client (spec §2 F).
- `usage` must survive `model_dump(mode="json")` and `json.dumps` — store a plain dict.
- An unattributable LLM `ok` must not be persisted: it goes through `_fail()` (spec AC12).

---

## Implementation Blueprint

### Steps (in order)
1. Add the three fields to `PlausibilityReport` — *why*: TASK-4646, TASK-4650 and the
   persisted record all read them; optional fields keep every existing constructor valid.
2. Add `_identity()` — *why*: one place reads identity off an `AIMessage`-shaped object,
   tolerant of the throwaway fakes the tests use.
3. Call it after a successful parse and route a missing model through `_fail()` — *why*:
   spec AC12; `_fail` already implements `on_error`, so do not re-implement it.
4. Fill the fields on the LLM-produced `ok` return — *why*: spec AC11.
5. Update the four fakes, then write the new tests — *why*: without `model` on the fakes
   every existing `ok` assertion becomes `skipped` and the merge gate goes red.

### `packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    items: dict\[str, PlausibilityVerdict\] = Field(default_factory=dict)' core/llm_validation.py)
# AFTER — insert below `    items: dict[str, PlausibilityVerdict] = Field(default_factory=dict)` (verified: core/llm_validation.py:78)
    resolved_model: str | None = None
    """The model that actually answered (``AIMessage.model``) — FEAT-732.

    ``model`` above is what the config REQUESTED and may be ``None`` (client
    default). This is what RESPONDED. ``None`` only when no LLM call was made.
    """
    provider: str | None = None
    """The provider that answered (``AIMessage.provider``)."""
    usage: dict[str, Any] | None = None
    """Token usage of the call (``AIMessage.usage``), JSON-dumped."""
```
Also change `from typing import TYPE_CHECKING, Literal` (line 9) to
`from typing import TYPE_CHECKING, Any, Literal`.
**Why**: appended after `items` so positional order of existing fields is untouched.
Do **not** use the `model: str | None = None` line as an anchor — it occurs twice (lines
42 and 75).

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '            batch = self._parse(response)' services/plausibility.py)
# AFTER the whole try/except block that contains `            batch = self._parse(response)`
#   (verified: services/plausibility.py:197) — i.e. directly below the
#   `return self._fail(f"llm_error: {type(exc).__name__}")` line that closes the except
        resolved_model, provider, usage = self._identity(response)
        if not resolved_model:
            # FEAT-732 AC12: a parseable answer nobody can attribute is not a success.
            self.logger.warning("plausibility: response for form %s carries no model identity", form.form_id)
            return self._fail("llm_error: unidentified_model")
```
```python
# occurrences: 1 (verified: grep -c 'status="ok", threshold=cfg.threshold, model=cfg.model, latency_ms=latency_ms, items=verdicts' services/plausibility.py)
# REPLACE the line `            status="ok", threshold=cfg.threshold, model=cfg.model, latency_ms=latency_ms, items=verdicts`
#   (verified: services/plausibility.py:216) with:
            status="ok",
            threshold=cfg.threshold,
            model=cfg.model,
            resolved_model=resolved_model,
            provider=provider,
            usage=usage,
            latency_ms=latency_ms,
            items=verdicts,
```
```python
# occurrences: 1 (verified: grep -c '    def _fail(self, reason: str) -> PlausibilityReport:' services/plausibility.py)
# BEFORE — insert above `    def _fail(self, reason: str) -> PlausibilityReport:` (verified: services/plausibility.py:238)
    @staticmethod
    def _identity(response: Any) -> tuple[str | None, str | None, dict[str, Any] | None]:
        """Extract (resolved_model, provider, usage) from an AIMessage-shaped response.

        Reads ``response.model`` / ``.provider`` / ``.usage`` — required fields on
        AIMessage (responses.py:138-139,143). Tolerant of test doubles: a missing
        or empty attribute yields ``None``, which ``check()`` then treats as an LLM
        failure rather than an unattributable success.
        """
        model = getattr(response, "model", None)
        provider = getattr(response, "provider", None)
        raw_usage = getattr(response, "usage", None)
        # FILL IN: normalise raw_usage to a JSON-safe dict — BaseModel → model_dump(mode="json"),
        #   dict → dict(raw_usage), anything else → None. Bounded by AC: usage survives json.dumps.
        usage: dict[str, Any] | None = None
        return (str(model) if model else None, str(provider) if provider else None, usage)
```
**Why**: the identity check sits *after* the try/except so a provider error still reports
`llm_error: <ExceptionName>` exactly as today, and *before* the verdict loop so an
unattributable batch is never turned into verdicts.

### The four test fakes (MODIFY — one line each)
```python
# test_plausibility_checker.py — occurrences: 1 (verified: grep -c 'return type("Msg", (), {"structured_output": self.result, "output": self.result})()' ...) — line 32
        return type("Msg", (), {"structured_output": self.result, "output": self.result, "model": "fake-model-1", "provider": "fake"})()
# test_http_plausibility.py — occurrences: 1 (line 36) — same edit on `{"structured_output": self._batch, "output": self._batch}`
# test_llm_quota_http.py — occurrences: 1 (line 54) — same edit on `{"structured_output": self.batch, "output": self.batch}`
# test_audio_ws_v2_integration.py — occurrences: 1 (line 104) — same edit on `{"structured_output": batch, "output": batch}`
```
**Why**: add the two keys only; change nothing else in those files.

### FILL IN checklist
- [ ] `plausibility.py::_identity` — usage normalisation; bounded by "usage survives `json.dumps`".
- [ ] `test_plausibility_identity.py` — the test bodies below; bounded by spec AC10–AC13.

---

## Acceptance Criteria

- [ ] `cfg.model=None` + response `model="x"` → `report.model is None` and `report.resolved_model == "x"`.
- [ ] `cfg.model="y"` → `report.model == "y"` exactly as before (spec AC10).
- [ ] Every LLM-produced `ok` (`latency_ms is not None`) carries non-empty `resolved_model`
      and `provider`, and a `usage` that survives `json.dumps` (spec AC11).
- [ ] A parseable response with no model → `status="skipped"`,
      `reason="llm_error: unidentified_model"` under `on_error="skip"`; `PlausibilityBlocked`
      under `on_error="block"` (spec AC12).
- [ ] The two no-call `ok` returns are byte-identical to before (`resolved_model is None`,
      `reason is None`).
- [ ] A `skipped` report has `resolved_model is None` (spec AC13).
- [ ] All four updated suites stay green.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_plausibility_identity.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_plausibility_checker.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_http_plausibility.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_llm_quota_http.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_v2_integration.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/test_llm_validation_policy.py -q`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/formdesigner/test_plausibility_identity.py
import json

import pytest

from parrot_formdesigner.core.llm_validation import LLMValidationConfig
from parrot_formdesigner.services.plausibility import AnswerPlausibilityChecker, PlausibilityBatch, PlausibilityBlocked


class _Client:
    """Fake whose response attributes are configurable per test."""

    def __init__(self, batch, **attrs):
        self.batch, self.attrs = batch, attrs

    async def ask(self, prompt, **kwargs):
        return type("Msg", (), {"structured_output": self.batch, "output": self.batch, **self.attrs})()


# FILL IN: a minimal form with one llm-enabled TEXT field "name" (copy _make_form's shape
#   from test_plausibility_checker.py:35-56) and a batch with one verdict for "name".

async def test_resolved_model_from_response(): ...          # cfg.model=None, attrs model="x"
async def test_model_field_meaning_unchanged(): ...         # cfg.model="y" → report.model == "y"
async def test_ok_without_model_skips_under_skip(): ...     # no model attr, on_error="skip"
async def test_ok_without_model_blocks_under_block(): ...   # pytest.raises(PlausibilityBlocked)
async def test_no_call_ok_unchanged(): ...                  # no eligible fields → resolved_model None, reason None
async def test_usage_is_json_safe(): ...                    # usage=<a pydantic model> → json.dumps(report.model_dump(mode="json"))
```

---

## Agent Instructions

1. **Work in the feature worktree** — `python -m scripts.sdd.ensure_worktree --slug formdesigner-validation-audit-trail --feature-id FEAT-732`
2. **Read the spec** — §2 F, §3 Module 4, §5 AC10–AC13.
3. **Check dependencies** — none.
4. **Verify the Codebase Contract** — re-run every `grep -c`.
5. **Update status** → `"in-progress"` in the per-spec index.
6. **Implement** from the blueprint; complete every `# FILL IN:`.
7. **Verify** — Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`.
8. **Commit the code** — stage only the seven listed files.
9. **Close** — `scripts/sdd/close_task.sh TASK-4645 formdesigner-validation-audit-trail verified`.
10. **Completion Note** — record the AC11 reading (no-call `ok` keeps `resolved_model=None`).

---

## Completion Note

**Completed by**: sdd-worker orchestrator; implemented by seat gpt-5.6-sol (codex), attempt 1 (uid b23bd08896234221a1f7fb6d57b9438e), duration 185s
**Date**: 2026-10-23
**Notes**: PlausibilityReport gains resolved_model/provider/usage; checker fails with llm_error: unidentified_model when no identity. Tests updated/added. Merge-tier validation green (472 passed, 6 skipped). Orchestrator diff review: no fixes needed; review recorded via coder_record_review. Closed with close_task.sh because the engine exposes no durable review-evidence ref for finalize_task.

**Deviations from spec**: none
