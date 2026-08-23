# TASK-2334: `credit_card` — reject cardholder data, never sanitize it

**Feature**: FEAT-448 — field-type-catalog-reconciliation
**Spec**: `sdd/specs/field-type-catalog-reconciliation.spec.md` §4, AC8
**Status**: pending · **Priority**: high · **Effort**: S · **Depends-on**: TASK-2332

## Context

Decided by Juan, 2026-08-22: cardholder data is never stored.

`credit-card-field.svelte` today emits the CVV **and the full PAN in
cleartext** (`emit({ ...card, number: digits })`, 15–16 unmasked digits). Both
would be persisted in `fs_form_data.data` and copied to staging with any table
copy. A card verification value may never be stored after authorization; a PAN
may be stored only where it is unreadable. Nothing in this platform authorizes a
payment, so neither value has a purpose here.

Split out from TASK-2333 on purpose. This is the one branch in the feature that
is a legal exposure, and it must not be written as the tenth item on a list.

## Scope

Accepted value:

```
{"brand": str, "last4": str, "name": str, "expiry": str}
```

- `cvv` present → **validation error**. Not stripped.
- `number`, or a `last4` longer than 4 digits → **validation error**. Not
  truncated.
- `last4` must be exactly 4 digits.

**Reject, do not sanitize.** A validator that quietly drops `cvv` satisfies "it
is not stored" while leaving every client free to keep sending it over the wire
and into request logs, and it hides that a client still does. Truncating a PAN
server-side is worse still: it means the PAN reached the server, which is the
thing being prevented.

## Acceptance Criteria

- AC1 `{"brand","last4","name","expiry"}` validates.
- AC2 A payload carrying `cvv` produces an ERROR. Asserted as an error — a test
  that only checks the key is absent from the sanitized output would pass
  against a stripping implementation, which is exactly what this forbids.
- AC3 A payload carrying `number`, or a `last4` of 5+ digits, produces an ERROR.
- AC4 The error message names the field and the reason without echoing the
  offending value — an error that quotes the PAN back has moved it into the
  logs.

## Notes

No `credit_card` field is stored in any schema today (verified across epson,
flexroc, pokemon, navigator), so there is no cardholder data to purge. That
holds only until the type ships, which is why the shape must be right on the
first release.

navigator-svelte FEAT-515 Module 5 stops the client emitting either value. The
two land together.

### Completion Note

Added a dedicated `CREDIT_CARD` branch in `services/validators.py::_coerce_value`
(no `_validate_by_type` branch needed — the shape checks are absolute
rejections, not refinements, so they raise `ValueError` at coercion time
and never reach the sanitized-data path). Order of checks: non-dict → error;
`cvv` key present → error; `number` key present → error; `last4` not
exactly 4 digits (regex `\d{4}` fullmatch) → error. Every message is a
fixed string — none of them interpolate the submitted value, so the PAN or
CVV can never end up in a validation error / log line (AC4).

Tests: `tests/formdesigner/test_feat448_credit_card_rejects.py`, 9 cases.
Two tests are explicitly adversarial per the task's own warning: one proves
a `cvv`-stripping implementation would fail this suite (asserts an error
is raised, not merely that the key is absent from a sanitized value), and
one proves a `number`-truncating implementation would fail it the same
way. Full suite diffed against the TASK-2333 baseline: no regressions.
