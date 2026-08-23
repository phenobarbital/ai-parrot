# TASK-2316: accept and propagate the store context through the HTTP surface

**Feature**: store-context-conditions (FEAT-440) · **Spec**: §3 Module 5
**Status**: done · **Effort**: M · **Depends on**: TASK-2313

## Why

`RuleEvaluator.resolve()` and `FormValidator.validate()` both accept
`visit_context`, and **no caller anywhere populates it** — verified across
the package. The evaluation path is complete and unreachable.

## What

The render and validate handlers accept a caller-supplied store context and
pass it through as `visit_context`. The caller is FieldSync, which knows
which store a visit belongs to; this package only accepts what it is handed
and never resolves a store itself.

## Notes

Absent context means no context: a rule that asks about a store the caller
did not describe does not fire. Failing closed is deliberate — the
alternative reveals store-gated questions to every store.

The contract for the key (`store_groups`) and its value shape (a list of
group names) is shared with the fieldsync half and must be agreed there
before this lands, not invented here.

## Acceptance

An end-to-end request carrying a store context resolves a store-gated rule
correctly; the same request without it leaves the rule unfired.

### Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-08-24

Added `FormAPIHandler._extract_visit_context(body)`: pulls an optional
top-level `"visit_context"` dict out of the same JSON body already used for
submitted answers, strips it from the answers before anything else touches
`data` (merge_partials, `onBeforeSubmit` payload, storage/forwarding), and
returns `(data, validate_kwargs)` where `validate_kwargs` is either
`{"visit_context": {...}}` or `{}`.

Wired into the two HTTP call sites that already invoke
`FormValidator.validate()` — `validate()` (`POST .../validate`) and
`submit_data()` (`POST .../data`) — via
`self.validator.validate(form, data, **validate_kwargs)`. Both were the
ONLY two places in `api/` that call `FormValidator.validate()`/
`RuleEvaluator.resolve()` at all (verified by grep across `api/` and
`services/`); no dedicated server-side "render with resolved visibility"
endpoint exists in this codebase — `GET .../schema` and
`GET .../render/{format}` both stay purely declarative (client evaluates
rules itself, per spec §1 Non-Goals), so neither was a candidate for this
wiring.

**Wire-format decision** (not specified by the spec — the spec explicitly
defers the `store_groups` *key* contract to fieldsync, but says nothing
about the HTTP *envelope*): a reserved top-level `visit_context` key in
the request body was chosen over a header or a `{"data": ..., "visit_context":
...}` wrapper because it requires zero change to the existing
`data = await request.json()` contract for every caller that doesn't send
it — `data` comes back byte-identical when the key is absent. Flagging
this as a design decision made without an explicit spec directive, for
review.

**Backward-compatibility fix found mid-task**: an unconditional
`visit_context=visit_context` kwarg on every call broke two pre-existing
tests (`test_lifecycle_events_submit.py::test_onbeforesubmit_payload_replacement`,
`test_lifecycle_events_e2e.py::test_replacement_payload_reaches_validator`)
whose mocked `validate()` doubles only accept `(form, data)` with no
`**kwargs`. Fixed by having `_extract_visit_context` return a
`**`-splattable kwargs dict that is EMPTY when no context was supplied, so
`validate()` is called with the exact same two positional arguments as
before this task for the common case — confirmed via the AC8 diff below
that this restored the pre-existing baseline exactly.

**Tests** (`tests/test_store_context_http.py`, 8 new): 5 with a mocked
validator asserting passthrough/stripping/None-when-absent/malformed-value
handling across both handlers; 3 true end-to-end using the REAL
`FormValidator` + `RuleEvaluator` against a store-gated required field
(same `groups`/`LogicGroup` shape TASK-2315's importer emits) — proving
the literal acceptance criterion: matching store context → 422 (rule
fired, field required and unanswered); non-matching store → 200; no
context at all → 200 (fails closed).

**Verification**: `pytest packages/parrot-formdesigner/tests/ -q` —
identical 40-failure baseline before/after (diffed explicitly), 2220
passed (2207 baseline + 5 from TASK-2315 + 8 here). `ruff check` on both
changed files — same 45 pre-existing findings in `handlers.py` (a large,
pre-existing file with unrelated import-sort/quote-annotation/TRY401
findings throughout), zero new; the new test file is fully clean.

**Deviations from spec**: none in behavior. The HTTP envelope shape
(reserved body key vs. header) is this implementation's own choice, made
explicit above since the spec intentionally left it open.

---

### Post-completion code-review fixes (2026-08-24)

Both remaining findings from the adversarial `code-reviewer` pass on the
full FEAT-440 diff were addressed (the third, CRITICAL, finding was
against TASK-2315's importer and is documented in that task's own
Completion Note):

**🟠 IMPORTANT — field-name-collision risk, fixed.** `_extract_visit_context`
now takes `form` and checks whether the TARGET FORM actually owns a field
literally named `visit_context` before treating that body key as context.
Nothing in `core/schema.py` reserves the name, so a hand-authored form
(via `create_blank_form`) could legally have one; without the guard, that
field's real submitted answer would have been silently intercepted and
stripped, with no error surfaced to the caller. Chose a per-form runtime
check over a global schema-level name reservation — smaller, stays inside
this task's file scope (`api/handlers.py` only), and degrades gracefully:
the colliding form's answer is preserved (not dropped), a warning is
logged naming the form, and that one form simply can't supply store
context via this channel until renamed — an explicit, traceable
limitation rather than a silent data-loss bug. 3 new tests
(`TestVisitContextFieldNameCollision`) cover: a real field named
`visit_context` preserved for both a scalar and (harder case) a
dict-shaped answer value indistinguishable in shape from real context,
plus a sanity check that non-colliding forms are unaffected.

**🟡 SUGGESTION — kwargs workaround, fixed.** Widened the two pre-existing
test doubles the review named
(`test_lifecycle_events_submit.py::TestOnBeforeSubmit::
test_onbeforesubmit_payload_replacement`'s `capturing_validate` and
`test_lifecycle_events_e2e.py::TestOnBeforeSubmitPayloadReplacement::
test_replacement_payload_reaches_validator`'s `capture`) to accept
`**kwargs` and forward them to the real `orig`/`original_validate` call —
one line each. This let `validate()`/`submit_data()` go back to calling
`FormValidator.validate(form, data, visit_context=visit_context)`
directly, removing the `**validate_kwargs`-splat indirection that existed
only to avoid breaking those two narrower fakes.

**Verification**: `pytest packages/parrot-formdesigner/tests/ -q` —
identical 40-failure baseline (diffed explicitly, unchanged from every
prior verification pass in this feature), 2225 passed (2222 prior + 3
new). `ruff check` — `handlers.py` still exactly 45 pre-existing
findings (zero new), all four touched test files fully clean.
