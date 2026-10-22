# TASK-4624: `ImplausibleSubmission` + `SubmissionPipeline.gate_for()` + `plausibility_ack`

**Feature**: FEAT-728 — FormBuilder LLM-validation enforcement policy + LLM quota
**Spec**: `sdd/specs/formbuilder-llm-validation-enforcement.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4623
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 — the heart of the feature. Every channel (HTTP, A2UI, Teams,
audio) commits through `SubmissionPipeline` (FEAT-649 Module 9), so putting the
enforcement decision here is what makes one rule apply everywhere instead of
four per-channel reimplementations. The gate is a *pure* method
(`gate_for()`) plus one raise site in `submit()`, placed immediately after the
plausibility step and before metadata enrichment, so a refused submission never
reaches a sink, the forwarder or `onAfterSubmit`.

---

## Scope

- Add the `ImplausibleSubmission` exception (policy, fields, report, `errors`,
  `code`) and export it in `__all__`.
- Add `SubmissionPipeline.gate_for(form, report, *, ack=False) -> ImplausibleSubmission | None`.
- Add the `plausibility_ack: bool = False` keyword to `submit()`, raise the gate
  at the declared site, and record `acknowledged: true` in
  `ctx["llm_validation"]` when an acknowledged `review` proceeds.
- Dispatch `onError` for a `reject` refusal only (never for `review`).
- Write tests for the policy matrix, the raise site's side-effect freedom and
  the `onError` asymmetry.

**NOT in scope**: the HTTP/A2UI response mapping (TASK-4625); the quota
(TASK-4626/4627); the audio call site (TASK-4628); changing
`AnswerPlausibilityChecker`, `validate()`'s signature, or the
`PlausibilityBlocked`/`on_error` behaviour.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py` | MODIFY | Exception, `gate_for()`, `plausibility_ack`, raise site, ack recording |
| `packages/parrot-formdesigner/tests/formdesigner/test_plausibility_enforcement.py` | CREATE | Policy matrix + side-effect tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# add to the existing import block of services/submission_pipeline.py:
from ..core.llm_validation import PlausibilityReport, implausible_fields, llm_validation_enabled
#   verified: services/submission_pipeline.py:18 (existing line imports PlausibilityReport,
#   llm_validation_enabled) — `implausible_fields` is added by TASK-4623
# already present, do not re-add:
from ..core.events import FormEventAbort                      # verified: services/submission_pipeline.py:17
from ..core.schema import FormSchema, UnknownFieldsPolicy      # verified: services/submission_pipeline.py:19
from ..core.voice_answer import unwrap_voice                   # verified: services/submission_pipeline.py:20
from .validators import FormValidator, ValidationResult        # verified: services/submission_pipeline.py:29
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py
__all__ = ["SubmissionPipeline", "SubmitOutcome", "SubmitSinkError", "ValidationFailed", "PlausibilityBlocked"]  # line 38

class ValidationFailed(Exception):                       # line 55  — the shape to mirror
    def __init__(self, errors: dict[str, Any]) -> None:   # line 58
    errors: dict[str, Any]                                # line 60

class SubmissionPipeline:                                 # line 72
    plausibility: AnswerPlausibilityChecker | None         # line 92
    logger: logging.Logger                                # line 93
    def _plausibility_enabled(self, form: FormSchema) -> bool:    # line 96
    async def validate(self, form, data, *, locale, auth_context,
                       llm_validation: bool = False, visit_context=None
                       ) -> tuple[ValidationResult, PlausibilityReport | None]:   # line 100
    async def submit(self, form, data, *, tenant, user_id, locale, context, extra_data,
                     auth_context, merge_session_id,            # line 130  <-- kwarg anchor
                     plausibility: PlausibilityReport | None = None,
                     request=None, visit_context=None, submission_id=None) -> SubmitOutcome:   # line 119
    def attach_verdicts(self, data, report) -> dict[str, Any]:    # line 324

# the raise site's neighbourhood (verified: services/submission_pipeline.py:186-199)
#   :186  comment "Plausibility sits after every deterministic 422 …"
#   :188  if plausibility is None and self.plausibility is not None and self._plausibility_enabled(form):
#   :189      plausibility = await self.plausibility.check(form, unwrap_voice(result.sanitized_data), locale=locale)
#   :193  outbound = {**result.sanitized_data, **extras} if extras else result.sanitized_data
#   :195  stored_data = self.attach_verdicts(result.sanitized_data, plausibility)
#   :196  ctx = dict(context or {})
#   :197  if plausibility is not None:
#   :198      ctx["llm_validation"] = plausibility.model_dump(mode="json")

# the local helper already defined inside submit() (verified: services/submission_pipeline.py:139-144)
async def _on_error(exc: BaseException, where: str) -> None: ...

# packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py
def implausible_fields(report: PlausibilityReport) -> list[str]:   # added by TASK-4623
class PlausibilityVerdict(BaseModel):                     # line 39
    plausible: bool; confidence: float; reason: str        # lines 42-44
```

### Does NOT Exist

- ~~`SubmissionPipeline.enforce()`~~ / ~~`.check_policy()`~~ — the method is
  named `gate_for`; nothing else may be invented.
- ~~`SubmitOutcome.rejected`~~ / ~~`.gate`~~ — the refusal is an exception, not
  an outcome field. Do NOT add a field to `SubmitOutcome`.
- ~~`ValidationFailed(errors, code=…)`~~ — `ValidationFailed.__init__` takes
  `errors` only (line 58). `ImplausibleSubmission` is a separate class, NOT a
  subclass of `ValidationFailed` (a subclass would be caught by the existing
  `except ValidationFailed` branches in handlers and audio and silently mapped
  to the wrong code).
- ~~`PlausibilityReport.status = "rejected"`~~ — the Literal is
  `"ok" | "skipped" | "blocked"` only (`core/llm_validation.py:65`).
- ~~`self.dispatch(...)`~~ — the dispatcher is `self._dispatch` (line 76), and
  inside `submit()` you use the local `_on_error(...)` helper.
- ~~`form.llm_validation.policy`~~ — the field is
  `form.llm_validation.on_implausible` (added by TASK-4623); `form.llm_validation`
  may be `None` (`core/schema.py:491`), so always guard it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/parrot-formdesigner/tests/formdesigner/test_plausibility_enforcement.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py#SubmissionPipeline",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py#SubmissionPipeline.submit",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py#SubmissionPipeline.validate",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py#ValidationFailed",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py#SubmitOutcome",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py#LLMValidationConfig"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- **`gate_for()` is pure**: no I/O, no logging, no dispatch, idempotent. Both
  `/validate` (TASK-4625) and `submit()` call it with the same arguments and
  must get the same answer — that agreement is spec AC10.
- **`ack` never clears `reject`.** This is the whole difference between the two
  enforcing policies.
- **Raise before side effects.** The raise site is between line 189 (the
  plausibility call) and line 193 (`outbound = …`). Anything after that line
  builds or writes the submission.
- **`onError` asymmetry is deliberate** (spec AC6): `reject` is a refusal like
  `ValidationFailed`, so it dispatches `onError`; `review` is a controlled
  client round-trip like `FormEventAbort`, so it does not — otherwise every
  first submit of a `review` form would spam error handlers.
- Never log answer values or verdict reasons; log the policy and the count only
  (`services/plausibility.py:196-197` sets the precedent: exception types only).
- `form.llm_validation` can be `None`: a `None` block means policy `annotate`.

### References in Codebase

- `services/submission_pipeline.py:150-163` — how `ValidationFailed` is raised
  after `_on_error(...)`: the pattern `reject` follows.
- `services/submission_pipeline.py:146-149` — `onBeforeSubmit`'s abort path:
  the pattern `review` follows (no `onError`).

---

## Implementation Blueprint

### Steps (in order)

1. Extend the `..core.llm_validation` import with `implausible_fields` — *why*:
   the gate's rule lives there (TASK-4623) and must not be re-implemented here.
2. Add `ImplausibleSubmission` next to `ValidationFailed`, and add it to
   `__all__` — *why*: handlers and audio import it from this module, exactly as
   they already import `PlausibilityBlocked` (line 38).
3. Add `gate_for()` directly below `_plausibility_enabled()` — *why*: both are
   small policy predicates over `form`, read together.
4. Add the `plausibility_ack` keyword to `submit()` after `merge_session_id`
   — *why*: it is a caller intent flag like `plausibility`, and appending it to
   the keyword-only block cannot break positional callers.
5. Raise at the declared site and record the ack — *why*: AC5 (no side effects)
   and AC7 (`acknowledged` recorded) both hinge on this exact position.
6. Write the tests — *why*: the policy matrix is 9 cells; only tests keep the
   `ack`/`reject` cell from regressing into a bypass.

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py` (MODIFY — 1 of 5)

```python
# occurrences: 1 (verified: grep -c 'from ..core.llm_validation import PlausibilityReport, llm_validation_enabled' packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py)
# REPLACE the line `from ..core.llm_validation import PlausibilityReport, llm_validation_enabled` (verified: services/submission_pipeline.py:18)
from ..core.llm_validation import PlausibilityReport, implausible_fields, llm_validation_enabled
```

**Why**: `implausible_fields` is the gate's only rule; importing it keeps the
threshold comparison in exactly one place in the codebase.

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py` (MODIFY — 2 of 5)

```python
# occurrences: 1 (verified: grep -c '__all__ = ["SubmissionPipeline", "SubmitOutcome", "SubmitSinkError", "ValidationFailed", "PlausibilityBlocked"]' packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py)
# REPLACE the `__all__` line (verified: services/submission_pipeline.py:38)
__all__ = [
    "SubmissionPipeline",
    "SubmitOutcome",
    "SubmitSinkError",
    "ValidationFailed",
    "PlausibilityBlocked",
    "ImplausibleSubmission",
]
```

**Why**: the module is the import surface for every channel; an unexported
exception would be imported from `services.submission_pipeline` anyway and drift
out of `__all__`.

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py` (MODIFY — 3 of 5)

```python
# occurrences: 1 (verified: grep -c 'class SubmitSinkError(Exception):' packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py)
# AFTER — insert below the body of `class SubmitSinkError(Exception):` (verified: services/submission_pipeline.py:63, body ends at :69)


_DEFAULT_IMPLAUSIBLE_MESSAGE = "This answer does not appear to answer the question."


class ImplausibleSubmission(Exception):
    """Gate refusal (422 class): answers flagged under a non-``annotate`` policy.

    Sibling of ``ValidationFailed`` — NOT a subclass, so the existing
    ``except ValidationFailed`` branches in the HTTP and audio channels cannot
    swallow it — and carries the same ``errors`` dict shape, so a client that
    already renders per-field validation errors renders these too.
    """

    def __init__(
        self,
        *,
        policy: Literal["review", "reject"],
        fields: list[str],
        report: PlausibilityReport,
    ) -> None:
        self.policy = policy
        self.fields = list(fields)
        self.report = report
        self.errors: dict[str, list[str]] = {
            field_id: [(report.items[field_id].reason or _DEFAULT_IMPLAUSIBLE_MESSAGE)]
            for field_id in self.fields
            if field_id in report.items
        }
        super().__init__(f"Implausible answers ({policy}): {', '.join(self.fields)}")

    @property
    def code(self) -> str:
        """``"PLAUSIBILITY_REVIEW"`` for ``review``, ``"PLAUSIBILITY_REJECTED"`` for ``reject``."""
        return "PLAUSIBILITY_REVIEW" if self.policy == "review" else "PLAUSIBILITY_REJECTED"
```

**Why this shape**: `errors` is derived here, once, so three call sites
(submit, validate, audio) cannot each invent a different message shape. The
`if field_id in report.items` guard keeps a caller-supplied `fields` list from
raising `KeyError`. `Literal` is already imported at line 14 — do not re-import.
Do NOT make this a `ValidationFailed` subclass.

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py` (MODIFY — 4 of 5)

```python
# occurrences: 1 (verified: grep -c '        return any(llm_validation_enabled(form, f) for f in form.iter_fields_recursive())' packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py)
# AFTER — insert below `        return any(llm_validation_enabled(form, f) for f in form.iter_fields_recursive())` (verified: services/submission_pipeline.py:98, the body of _plausibility_enabled)

    def gate_for(
        self, form: FormSchema, report: PlausibilityReport | None, *, ack: bool = False
    ) -> ImplausibleSubmission | None:
        """The enforcement decision for one report — pure, no I/O, safe to call twice.

        Returns ``None`` when the submission may proceed: no report, a report
        that flagged nothing, policy ``annotate``, or policy ``review`` with
        ``ack=True``. Returns the exception to raise otherwise. ``ack`` never
        clears ``reject``.

        Args:
            form: The form whose ``llm_validation.on_implausible`` decides.
            report: The plausibility outcome, or ``None`` when no check ran.
            ack: The client reconfirmed these answers (``review`` only).
        """
        if report is None:
            return None
        policy = form.llm_validation.on_implausible if form.llm_validation else "annotate"
        if policy == "annotate":
            return None
        flagged = implausible_fields(report)
        if not flagged:
            return None
        if policy == "review" and ack:
            return None
        return ImplausibleSubmission(policy=policy, fields=flagged, report=report)
```

**Why**: ordering the guards from cheapest to most expensive keeps the
`annotate` default — the overwhelmingly common case — free of any work beyond
one attribute read. `form.llm_validation` is optional
(`core/schema.py:491`), hence the `if … else "annotate"`.

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py` (MODIFY — 5 of 5)

```python
# occurrences: 1 (verified: grep -c '        merge_session_id: str | None,' packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py)
# AFTER — insert below `        merge_session_id: str | None,` in submit()'s signature (verified: services/submission_pipeline.py:130)
        plausibility_ack: bool = False,
```

```python
# occurrences: 1 (verified: grep -c '                plausibility = await self.plausibility.check(form, unwrap_voice(result.sanitized_data), locale=locale)' packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py)
# AFTER — insert below `                plausibility = await self.plausibility.check(form, unwrap_voice(result.sanitized_data), locale=locale)` (verified: services/submission_pipeline.py:189) and BEFORE the `outbound = …` line (:193)

            # FEAT-728 — the enforcement gate. Raised before the submission is built, so a
            # refusal touches no sink, no forwarder and no onAfterSubmit handler (AC5).
            gate = self.gate_for(form, plausibility, ack=plausibility_ack)
            if gate is not None:
                self.logger.info(
                    "Submission refused by plausibility policy %s for form %s (%d field(s))",
                    gate.policy,
                    form.form_id,
                    len(gate.fields),
                )
                # reject is a refusal (like ValidationFailed) and goes through onError;
                # review is a controlled client round-trip (like FormEventAbort) and does not (AC6).
                if gate.policy == "reject":
                    await _on_error(gate, "plausibility reject")
                raise gate
```

```python
# occurrences: 1 (verified: grep -c '                ctx["llm_validation"] = plausibility.model_dump(mode="json")' packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py)
# REPLACE the line `                ctx["llm_validation"] = plausibility.model_dump(mode="json")` (verified: services/submission_pipeline.py:198)
                ctx["llm_validation"] = plausibility.model_dump(mode="json")
                if plausibility_ack:
                    ctx["llm_validation"]["acknowledged"] = True
```

**Why**: the gate sits exactly between "we now know the verdict" and "we start
building the record". Logging the policy and the field *count* — never the ids'
values or the verdict reasons — follows the module's no-answer-logging
discipline. The ack is recorded inside the existing `llm_validation` context
block rather than as a new top-level key, so sinks that already read
`context["llm_validation"]` see it without a schema change.

### `packages/parrot-formdesigner/tests/formdesigner/test_plausibility_enforcement.py` (CREATE)

```python
"""Pipeline enforcement-gate tests (FEAT-728, TASK-4624)."""

from __future__ import annotations

import pytest
from parrot_formdesigner.core.llm_validation import (
    LLMValidationConfig,
    PlausibilityReport,
    PlausibilityVerdict,
)
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.submission_pipeline import (
    ImplausibleSubmission,
    SubmissionPipeline,
    ValidationFailed,
)
from parrot_formdesigner.services.validators import FormValidator


def _form(policy: str = "annotate", *, enabled: bool = True) -> FormSchema:
    """One-field form carrying an llm_validation block with the given policy."""
    # FILL IN: build FormSchema(..., llm_validation=LLMValidationConfig(enabled=enabled,
    #          on_implausible=policy), sections=[FormSection(fields=[FormField(...)])])
    #          — copy the shape from tests/formdesigner/test_http_plausibility.py::_form


def _report(*, plausible: bool = False, confidence: float = 0.1, threshold: float = 0.7) -> PlausibilityReport:
    """An ``ok`` report flagging (or not) the single field."""
    # FILL IN — bounded by AC2's rule; threshold has no model default


class TestGateFor:
    """gate_for() is pure: these need no storage and no LLM."""

    def test_annotate_always_passes(self) -> None:
        # FILL IN: flagged report + annotate -> None — bounded by AC3/AC4

    def test_review_without_ack_returns_review_code(self) -> None:
        # FILL IN: assert code == "PLAUSIBILITY_REVIEW" and errors keyed by field id — AC4/AC7

    def test_review_with_ack_passes(self) -> None:
        # FILL IN — bounded by AC4

    def test_reject_ignores_ack(self) -> None:
        # FILL IN: ack=True still returns code == "PLAUSIBILITY_REJECTED" — bounded by AC4

    def test_none_report_passes(self) -> None:
        # FILL IN — bounded by AC4

    def test_unflagged_report_passes(self) -> None:
        # FILL IN: plausible=True, confidence=1.0 — bounded by AC4

    def test_missing_llm_validation_block_is_annotate(self) -> None:
        # FILL IN: form.llm_validation is None -> None — bounded by AC4

    def test_errors_fall_back_to_default_message(self) -> None:
        # FILL IN: verdict.reason == "" -> the default sentence — bounded by AC7

    def test_not_a_validation_failed_subclass(self) -> None:
        """A subclass would be swallowed by the channels' existing except branches."""
        assert not issubclass(ImplausibleSubmission, ValidationFailed)


class TestSubmitGate:
    """The raise site: nothing may be written."""

    async def test_reject_stores_nothing(self) -> None:
        # FILL IN: fake storage/sink/forwarder recorders; assert no writes, no forward,
        #          no onAfterSubmit dispatch — bounded by AC5

    async def test_reject_dispatches_on_error(self) -> None:
        # FILL IN: dispatch_fn recorder sees exactly one onError — bounded by AC6

    async def test_review_does_not_dispatch_on_error(self) -> None:
        # FILL IN: recorder sees no onError — bounded by AC6

    async def test_ack_records_acknowledged_in_context(self) -> None:
        # FILL IN: stored submission context["llm_validation"]["acknowledged"] is True — AC7

    async def test_annotate_still_stores_with_verdicts(self) -> None:
        # FILL IN: regression for AC3 at pipeline level

    async def test_gate_runs_after_deterministic_422(self) -> None:
        # FILL IN: an invalid payload raises ValidationFailed and the checker is never called
        #          — bounded by AC16
```

**Why this shape**: `TestGateFor` needs no async machinery at all, which is the
point of making the gate pure — the expensive fixtures are confined to
`TestSubmitGate`. Reuse `tests/formdesigner/test_http_plausibility.py`'s
`FakeLLM` / `_form` shapes (verified: that file, lines 25-60) instead of
inventing new fakes.

### FILL IN checklist

- [ ] `test_plausibility_enforcement.py::_form` / `::_report` — fixtures mirroring `test_http_plausibility.py`; bounded by the Codebase Contract
- [ ] `TestGateFor::*` — 8 bodies covering the 9-cell policy matrix; bounded by AC4
- [ ] `TestSubmitGate::*` — 6 bodies; bounded by AC3, AC5, AC6, AC7, AC16

---

## Acceptance Criteria

- [ ] `gate_for()` returns `None` for: `report is None`, nothing flagged, policy `annotate`, or policy `review` with `ack=True`; and an `ImplausibleSubmission` otherwise. `ack=True` never clears `reject` (spec AC4).
- [ ] `ImplausibleSubmission.code` is `"PLAUSIBILITY_REVIEW"` / `"PLAUSIBILITY_REJECTED"`, `errors` is `{field_id: [reason-or-default]}`, and the class is NOT a subclass of `ValidationFailed`.
- [ ] A tripped gate raises before metadata enrichment, persistence, forwarding and `onAfterSubmit`: no sink write, no generic-storage write, no forward attempt, no `onAfterSubmit` dispatch (spec AC5).
- [ ] `onError` is dispatched for `reject` and NOT for `review` (spec AC6).
- [ ] An acknowledged `review` stores with `context["llm_validation"]["acknowledged"] is True` (spec AC7).
- [ ] With policy `annotate` the pipeline behaves exactly as before (spec AC3).
- [ ] A payload that fails deterministic validation never reaches the checker (spec AC16).
- [ ] `ImplausibleSubmission` is in `__all__`.
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py packages/parrot-formdesigner/tests/formdesigner/test_plausibility_enforcement.py`

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_plausibility_enforcement.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_submission_pipeline_parity.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_http_plausibility.py -q`

---

## Test Specification

See the CREATE block above. `TestGateFor` must stay synchronous and
fixture-free — if a test there needs a mock, the gate stopped being pure.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug formbuilder-llm-validation-enforcement --feature-id FEAT-728`)
2. **Read the spec** at the path listed above (§2 Overview's policy table, §3 Module 2, §7)
3. **Check dependencies** — `TASK-4623` must be `"done"` in
   `sdd/tasks/index/formbuilder-llm-validation-enforcement.json`; `implausible_fields`
   must be importable before you start.
4. **Verify the Codebase Contract** — re-run every `grep -c` in the blueprint.
   A count of `0` means the anchor moved: stop and report the drift.
5. **Update status** → `"in-progress"` (set `started_at`), commit only the index
6. **Implement** from the blueprint; complete every `# FILL IN:`. Tests inside a
   worktree need `PYTHONPATH=packages/parrot-formdesigner/src`.
7. **Verify** the Validation Commands pass
8. **Commit the code** — stage only the two files this task lists
9. **Close the task**: `scripts/sdd/close_task.sh TASK-4624 formbuilder-llm-validation-enforcement verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
