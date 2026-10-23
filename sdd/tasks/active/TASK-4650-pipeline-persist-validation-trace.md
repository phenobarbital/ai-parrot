# TASK-4650: Persist the capped trace into `context["validation"]` from `SubmissionPipeline.submit`

**Feature**: FEAT-732 — FormDesigner validation audit trail
**Spec**: `sdd/specs/formdesigner-validation-audit-trail.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4648
**Assigned-to**: unassigned

---

## Context

With the validator producing a sealed trace (TASK-4648), the shared `SubmissionPipeline`
must build the collector, hand it to the validator, cap the result and write it beside the
existing `ctx["llm_validation"]`. Because every committing channel goes through
`SubmissionPipeline.submit`, this one edit covers HTTP, A2UI, MS Teams' HTTP submit **and**
server-mode audio by construction. Implements spec §3 Module 5 (as amended at task time).

**Two task-time findings this task encodes** (spec v0.3):
- **No audio edit.** Server-mode audio commits through `SubmissionPipeline.submit`
  (`api/audio_ws.py:1192`), which merges the incoming context with
  `ctx = dict(context or {})` (`services/submission_pipeline.py:325`). `audio/engine.py:1086`
  only builds the context handed to the pipeline; editing it would add a second writer of
  the same key.
- **No collector in the prepare step.** `SubmissionPipeline.validate()` (line 206) backs the
  HTTP `/validate` endpoint; its result is never persisted, so a trace there is pure cost.

---

## Scope

- Add `SubmissionPipeline._audit_config(form)` and `_new_collector(form, *, locale)`.
- In `submit()` only: pass `trace=self._new_collector(form, locale=locale)` to the
  `validator.validate(...)` call, and after `ctx = dict(context or {})` write
  `ctx["validation"] = cap_trace(...)` when the result carries a `ValidationTrace`.
- Write tests: persisted trace shape, `off` byte-identity, cap-before-merge, audio-shaped
  input context, sink payloads, and the storage JSON round trip.

**NOT in scope**:
- `SubmissionPipeline.validate()` (prepare step) — leave it untouched.
- `audio/engine.py` — leave it untouched (see Context).
- Anything in `api/` — the trace is never returned in a response (spec decision 4).
- Validate-only channels (Telegram router, `ui/handlers.py`, MS Teams presets, audio
  client-submit) — they persist nothing, so they persist no trace (spec NG1).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py` | MODIFY | Collector construction, `trace=` on the submit-time validate call, `ctx["validation"]` write |
| `packages/parrot-formdesigner/tests/formdesigner/test_pipeline_validation_trace.py` | CREATE | Tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# added to services/submission_pipeline.py:
from ..core.audit_trail import AuditDetail, AuditTrailConfig, ValidationTrace   # TASK-4644
from .validation_trace import ValidationTraceCollector, cap_trace               # TASK-4647
# test imports:
from parrot_formdesigner.services.sinks.mapper import flatten_submission, nest_submission   # verified: submission_pipeline.py:31
from parrot_formdesigner.services.submissions import FormSubmission, FormSubmissionStorage  # verified: services/__init__.py:26
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py
from .validators import FormValidator, ValidationResult      # line 34 ← import anchor
class SubmissionPipeline:                                    # line 126
    def _plausibility_enabled(self, form: FormSchema) -> bool: ...   # line 150
    def gate_for(self, form, report, *, ack=False) -> ImplausibleSubmission | None: ...   # line 154 ← method anchor
    async def validate(...) -> tuple[ValidationResult, PlausibilityReport | None]: ...    # line 209 — DO NOT TOUCH
        #   line 221: result = await self.validator.validate(   ← identical text to line 266!
    async def submit(self, form, data, *, tenant, user_id, locale, context, extra_data,
                     auth_context, merge_session_id, plausibility=None, ...) -> SubmitOutcome: ...   # line 230
        #   line 264: data = dict(resolution.payload)          ← the unique line just above the submit-time call
        #   line 266: result = await self.validator.validate(
        #   line 267:     form, data, locale=locale, auth_context=auth_context, visit_context=visit_context
        #   line 325: ctx = dict(context or {})                ← unique; the write goes right below it
        #   line 327: ctx["llm_validation"] = plausibility.model_dump(mode="json")   (persistence dump — keep)
        #   line 342: context=ctx or None

# packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py
class FormSubmissionStorage:
    @staticmethod
    def _row_to_submission(row: Any) -> FormSubmission: ...   # line 381 — JSONB `context` arrives as str; _load_json decodes it

# packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/mapper.py
#   lines 62 and 84: "context" is in both the tabular and the document payload column sets
```

### Does NOT Exist
- ~~`SubmissionPipeline.audit_config`~~ / ~~`.trace`~~ — no such attribute; this task adds two
  private helpers, nothing stored on the instance (one pipeline serves concurrent requests).
- ~~`SubmitOutcome.trace`~~ — not added; the trace reaches storage via `context`, never the outcome.
- ~~`FormSubmission.validation`~~ / ~~a `validation_trace` column~~ — no column, no migration (spec NG2).
- ~~`audio/engine.py` writing `context["validation"]`~~ — deliberately not added (see Context).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_pipeline_validation_trace.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py#SubmissionPipeline",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py#SubmissionPipeline.submit",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py#FormSubmissionStorage._row_to_submission"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Cap before merge** (spec §2 E, AC9): `cap_trace` runs on the trace alone, so
  `ctx["llm_validation"]` can never be truncated by it.
- Guard with `isinstance(result.trace, ValidationTrace)`, **not** `is not None`: test doubles
  replace `validator.validate` (`tests/test_submit_merge.py:137`,
  `tests/test_partial_saves_integration.py:197`) and any foreign double returning a non-trace
  object must never reach `cap_trace`.
- `detail: off` must leave `context` byte-identical to today (spec AC2): no collector is
  built, so `result.trace is None`, so no key is written.
- Default (no `audit_trail` block) is `summary` — every committed submission now carries
  `context["validation"]`. Tests that construct `FormSubmission` directly and assert
  `context is None` (`tests/unit/test_submission_revisions.py:106,292`,
  `tests/test_submission_jsonb_shape.py:152`) are unaffected: they never run the pipeline.

---

## Implementation Blueprint

### Steps (in order)
1. Add the imports and the two helpers — *why*: keeps `submit()`'s diff to two small edits.
2. Pass the collector into the submit-time validate call only — *why*: the prepare step is
   never persisted (Context).
3. Write the capped trace right below `ctx = dict(context or {})` — *why*: spec AC1/AC9.
4. Test, then run the Validation Commands.

### `services/submission_pipeline.py` (MODIFY — imports)
```python
# occurrences: 1 (verified: grep -c 'from .validators import FormValidator, ValidationResult' services/submission_pipeline.py)
# AFTER — insert below `from .validators import FormValidator, ValidationResult` (verified: services/submission_pipeline.py:34)
from .validation_trace import ValidationTraceCollector, cap_trace
```
and add, beside the other `..core` imports (lines 16-25):
```python
from ..core.audit_trail import AuditDetail, AuditTrailConfig, ValidationTrace
```

### `services/submission_pipeline.py` (MODIFY — helpers)
```python
# occurrences: 1 (verified: grep -c '    def gate_for(' services/submission_pipeline.py)
# BEFORE — insert above `    def gate_for(` (verified: services/submission_pipeline.py:154)
    @staticmethod
    def _audit_config(form: FormSchema) -> AuditTrailConfig:
        """Return the form's audit config, or the ``summary`` default when absent (FEAT-732)."""
        return form.audit_trail or AuditTrailConfig()

    def _new_collector(self, form: FormSchema, *, locale: str) -> ValidationTraceCollector | None:
        """Build a collector, or ``None`` when detail is OFF — so an audit-off form pays nothing."""
        config = self._audit_config(form)
        if config.detail is AuditDetail.OFF:
            return None
        return ValidationTraceCollector(detail=config.detail, locale=locale)
```

### `services/submission_pipeline.py` (MODIFY — submit-time validate call)
```python
# FILL IN: disambiguate — `result = await self.validator.validate(` occurs TWICE (lines 221, 266) and
#   so does its argument line. Attach to the submit() call by the unique line above it:
#       data = dict(resolution.payload)                      (verified: services/submission_pipeline.py:264)
#   Then REPLACE its argument line (line 267)
#       form, data, locale=locale, auth_context=auth_context, visit_context=visit_context
#   with
#       form,
#       data,
#       locale=locale,
#       auth_context=auth_context,
#       visit_context=visit_context,
#       trace=self._new_collector(form, locale=locale),
#   Leave the line-221 call in validate() exactly as it is.
```

### `services/submission_pipeline.py` (MODIFY — the write)
```python
# occurrences: 1 (verified: grep -c '            ctx = dict(context or {})' services/submission_pipeline.py)
# AFTER — insert below `            ctx = dict(context or {})` (verified: services/submission_pipeline.py:325)
            # FEAT-732 — capped BEFORE the merge, so llm_validation is never what gets truncated.
            if isinstance(result.trace, ValidationTrace):
                ctx["validation"] = cap_trace(
                    result.trace, max_bytes=self._audit_config(form).effective_max_bytes
                )
```
**Why**: placed above the existing `if plausibility is not None:` block, so both keys sit side
by side and `context=ctx or None` (line 342) needs no change.

### FILL IN checklist
- [ ] Submit-time call disambiguation — bounded by "line 221 untouched".
- [ ] Test bodies below — bounded by spec AC1, AC2, AC9, AC14, AC15.

---

## Acceptance Criteria

- [ ] A form with no `audit_trail` block, committed through `submit()`, stores
      `context["validation"]` with `trace_schema`, `detail="summary"`, `schema_fingerprint`,
      `ruleset_version`, `form_version`, `checks_run > 0`, and one `fields[]` entry per
      validated field (spec AC1).
- [ ] `audit_trail={"detail": "off"}` stores no `validation` key and the same `context` as
      before FEAT-732 for the same input (spec AC2).
- [ ] With `max_bytes=1024` on a wide form, `context["validation"]["truncated"] is True`
      while `context["llm_validation"]` is complete (spec AC9).
- [ ] An input context carrying `llm_validation` (the audio shape) ends up with **both** keys
      (spec AC14).
- [ ] `flatten_submission` and `nest_submission` both carry `context["validation"]` (spec AC15).
- [ ] `FormSubmissionStorage._row_to_submission` on a row whose `context` is the JSON string
      of a traced context returns an equal dict (spec AC15).
- [ ] `SubmissionPipeline.validate()` still returns `result.trace is None`.
- [ ] `test_submission_pipeline.py` passes unchanged.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_pipeline_validation_trace.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_submission_pipeline.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_submission_pipeline_parity.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_http_plausibility.py -q`
- `pytest packages/parrot-formdesigner/tests/test_store_context_http.py -q`
- `pytest packages/parrot-formdesigner/tests/test_submit_merge.py -q`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/formdesigner/test_pipeline_validation_trace.py
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot_formdesigner.core.audit_trail import AuditTrailConfig
from parrot_formdesigner.core.llm_validation import PlausibilityReport
from parrot_formdesigner.services.sinks.mapper import flatten_submission, nest_submission
from parrot_formdesigner.services.submission_pipeline import SubmissionPipeline
from parrot_formdesigner.services.submissions import FormSubmissionStorage
from parrot_formdesigner.services.validators import FormValidator

# FILL IN: copy `_form`, `_submit_kwargs` and the `pipeline_factory` fixture shape from
#   tests/formdesigner/test_submission_pipeline.py:26-98 (do not import them — test modules
#   are not a shared API). Add an `audit_trail: AuditTrailConfig | None` parameter to `_form`,
#   and a `wide=True` variant with ~200 constrained TEXT fields for the cap test.

async def test_submit_persists_validation_trace(pipeline_factory): ...
async def test_submit_audit_off_writes_nothing(pipeline_factory): ...
async def test_cap_applied_before_context_merge(pipeline_factory): ...   # pass plausibility=PlausibilityReport(...)
async def test_audio_shaped_context_keeps_both_keys(pipeline_factory): ...  # context={"llm_validation": {...}}
def test_trace_reaches_sink_payloads(): ...                  # FormSubmission(context={"validation": {...}})
def test_trace_survives_storage_row_roundtrip(): ...         # row dict with context=json.dumps(ctx)
async def test_prepare_step_builds_no_trace(pipeline_factory): ...
```

---

## Agent Instructions

1. **Work in the feature worktree** — `python -m scripts.sdd.ensure_worktree --slug formdesigner-validation-audit-trail --feature-id FEAT-732`
2. **Read the spec** — §2 E, §3 Module 5 (v0.3), §7 R1/R5/R8.
3. **Check dependencies** — TASK-4648 must be `done` (`ValidationResult.trace` + `validate(trace=)`).
4. **Verify the Codebase Contract** — re-run every `grep -c`.
5. **Update status** → `"in-progress"`.
6. **Implement** from the blueprint; complete every `# FILL IN:`.
7. **Verify** — Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`.
8. **Commit the code** — stage only the two listed files.
9. **Close** — `scripts/sdd/close_task.sh TASK-4650 formdesigner-validation-audit-trail verified`.
10. **Completion Note** — confirm `audio/engine.py` and `validate()` were left untouched.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
