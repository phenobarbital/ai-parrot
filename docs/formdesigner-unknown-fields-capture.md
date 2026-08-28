# Form Designer — Unknown-Field Capture Policy for Form Submissions

> **Feature**: FEAT-458
> **Applies to**: `parrot-formdesigner` >= 0.11.0

This document is the authoritative reference for `FormSchema.unknown_fields`
— the mechanism that decides what happens to a submission payload's
top-level keys the form does not declare.

---

!!! warning "`extra_data` is unvalidated, caller-controlled data"
    Under `keep`, `extra_data` stores whatever an anonymous caller sent,
    verbatim. `POST /forms/{uid}/submit` and its dry-run twin
    `POST /forms/{uid}/validate` are both reachable **without
    authentication** for public forms. Nothing in this feature validates,
    sanitizes, or type-checks the contents of `extra_data` — it is raw
    JSON from the wire. There is **no retention, TTL, or purge mechanism**
    for it; that is a deliberate, acknowledged follow-up, not shipped here.

---

## 1. Overview

A form submission payload may carry keys the schema does not declare —
because an external integrator posts a richer superset than this package
models, or because the client attaches derived/telemetry keys no one
turned into a `FormField`. Before this feature, those keys were silently
discarded: no error, no log, no counter. `unknown_fields` makes that
behaviour an explicit, per-form choice with three states.

By default (`unknown_fields: drop`, or the field simply absent), a form's
behaviour is **byte-identical** to every release before 0.12.0 — no
breaking change for any existing form. Capture is strictly opt-in.

## 2. The three policies

| Policy | Behaviour |
|---|---|
| `drop` (default) | Undeclared keys are discarded. Identical to every release before 0.12.0, except a `self.logger.debug` call now records how many keys were dropped — the drop is no longer *silent*, even though it is still the default. |
| `keep` | Undeclared keys are stored verbatim in `FormSubmission.extra_data` (a dedicated column, never `{}` when policy is on but nothing arrived — see §3), and flat-merged into the body sent to an `endpoint` `submit` action and into the `onAfterSubmit` payload. |
| `reject` | The submission fails with `422` and `errors["__unknown__"]` lists the offending key names, sorted. `onError` is dispatched best-effort first. Nothing is persisted. |

`unknown_fields` lives on `FormSchema`:

```python
from parrot_formdesigner.core.schema import FormSchema, UnknownFieldsPolicy

form = FormSchema(
    form_id="partner-intake",
    title="Partner Intake",
    sections=[...],
    unknown_fields="keep",  # or UnknownFieldsPolicy.KEEP
)
```

`FormValidator.validate()` computes the payload-side diff
(`ValidationResult.extra_data`) but reads **no** policy field — it is
platform-agnostic and used outside HTTP. The policy decision is made by
the handler (`FormAPIHandler.submit_data` / `.validate`), which reads
`form.unknown_fields` and branches.

## 3. Caps — module-level constants, enforced by rejection

Under `keep`, extras are bounded by two module-level constants in
`services/unknown_fields.py`:

```python
MAX_EXTRA_KEYS: int = 256
MAX_EXTRA_BYTES: int = 256 * 1024   # 256 KiB, serialized JSON
```

There is **no per-form override** and no constructor knob on
`FormAPIHandler` — there is exactly one place to change them. A `keep`
submission exceeding either cap is **rejected with `422`**, naming the
exceeded limit, its actual value, and its maximum. Nothing is truncated:
a `200` that silently lost part of the payload is precisely the defect
this feature exists to remove. Exactly at either cap (256 keys, 256 KiB)
is accepted and stored unmodified.

## 4. Why storage and the wire disagree

At rest, `FormSubmission.data` holds only the validated, declared answers,
and `FormSubmission.extra_data` holds the undeclared keys — a dedicated
column, not a corner of `data` and not the audit `context` column, because
"which of these keys did an anonymous caller choose?" must stay answerable
for future retention and access decisions. `extra_data` is `None` (SQL
`NULL`), never `{}`, when the policy was not `keep`, or when `keep` was
active and no extras arrived — an empty dict would falsely imply a capture
attempt happened.

On the wire, the forwarded body and the `onAfterSubmit` payload are
flat-merged: `{**sanitized_data, **extras}`, with declared answers winning
any key collision (defensive, not load-bearing — an extra cannot collide
with a declared `field_id` by construction). Under `drop`, both are
exactly `sanitized_data`, unchanged.

This split-at-rest / flat-on-the-wire asymmetry is **deliberate**: the
storage layer's job is provenance (who sent what), while an integrator
posting a superset expects its own payload shape reflected back, not a
server-invented split. Someone will be tempted to "fix" this into
consistency — don't; it destroys the property that makes `data` useful
(a pure, validated answer map) or breaks round-tripping for the caller.

## 5. Why `POST /partial` is always strict

`POST /forms/{uid}/partial` (`save_partial`) rejects an undeclared
`field_id` under **every** policy — `unknown_fields` has no effect on it —
returning `field_errors[field_id] = ["unknown field_id"]`, exactly as it
did before this feature. Partial answers are persisted keyed by
`field_uid` (FEAT-393/TASK-2003), so a mid-session field rename cannot
orphan a saved answer; an undeclared key has no `field_uid` to be keyed
under, so there is nowhere for it to live. This asymmetry between
`/submit` (configurable) and `/partial` (always strict) is intentional
and documented here so it reads as a declared design decision, not an
oversight.

## 6. The rendered JSON Schema states `reject`

`JsonSchemaRenderer` emits no `additionalProperties` key for `drop` or
`keep` — output is byte-identical to every pre-0.12.0 form. Under
`reject`, the rendered schema adds `additionalProperties: false` at the
top level, so a standards-compliant client generating its payload from
the schema can validate locally instead of round-tripping a submission
the server will always refuse.

`unknown_fields` itself is **not** otherwise exposed to clients — it is
not surfaced by `scripts/gen_frontend_docs.py`, and there is no
`x-unknown-fields` extension anywhere in the renderer output. The
`additionalProperties: false` consequence under `reject` is the only
client-visible trace of the policy.

## 7. Both storage paths are covered

A form with no `persistence:` block writes to the shared
`navigator.form_data` table via `FormSubmissionStorage`, which has a
nullable `extra_data JSONB` column (added via the same additive
`ADD COLUMN IF NOT EXISTS` migration path `initialize()` already runs for
every other column — no standalone migration script, no backfill, and a
pre-existing row simply reads back with `extra_data IS NULL`).

A form declaring `persistence:` (FEAT-457) writes **exclusively** to its
own sink — `extra_data` is one of the reserved fields
`services/sinks/mapper.py` always emits: a tabular sink
(`flatten_submission`) gets it as one JSON-serialized column (mirroring
how `ARRAY` fields are handled; `None` stays SQL `NULL`, never the string
`"null"`); a document sink (`nest_submission`) gets it as a nested object,
never stringified. `extra_data` is also reserved in
`RESERVED_COLUMNS` — a form declaring a `field_id` (or a
`FormMetadataField.key`) literally named `extra_data` against a tabular
target is rejected at authoring time. Without this coverage, a form using
`persistence:` would keep losing extras even after upgrading — the same
class of silent loss this feature exists to remove, just for a different
storage path.

## 8. Worked example — `keep`

Given a form declaring one field, `name`, with `unknown_fields: keep`,
and this submission:

```json
POST /api/v1/forms/{form_uid}/submit
{"name": "Ana", "legacy_id": 42, "_client_ms": 1180}
```

The stored `FormSubmission`:

```python
FormSubmission(
    data={"name": "Ana"},                                # declared answers only
    extra_data={"legacy_id": 42, "_client_ms": 1180},     # everything else, verbatim
    ...
)
```

If the form has an `endpoint` submit action, the forwarded body is the
flat merge of both:

```json
{"name": "Ana", "legacy_id": 42, "_client_ms": 1180}
```

— the integrator's own superset comes back exactly as it went in, even
though it was split into two columns at rest.

## 9. `navigator.form_data` schema reference

The generic submissions table gains one nullable column, no default:

```sql
ALTER TABLE navigator.form_data
    ADD COLUMN IF NOT EXISTS extra_data JSONB;
```

Reads and writes MUST use `$n::text::jsonb` (never a bare `$n`) — a
host-provided `asyncpg` pool with a registered json/jsonb codec otherwise
double-encodes the parameter, storing a jsonb **string** instead of an
object (the same defect recorded at `services/submissions.py:255-273` for
`data`/`context`, fixed here for `extra_data` from day one).

## 10. What is NOT provided

- **No retention, TTL, or purge policy** for captured extras. Anonymous,
  caller-controlled JSON accumulating in a public-form column is a real
  operational question — acknowledged as a follow-up, not designed here.
- **No per-form cap override.** `MAX_EXTRA_KEYS` / `MAX_EXTRA_BYTES` are
  module-level constants; changing them changes them for every form.
- **No resolution of form-version skew.** A payload key matching a
  *renamed or removed* field is an extra like any other — it is not
  mapped back to its old field.
- **No effect on the audio/WebSocket submission path.** `_finish_session`
  builds `data` from manifest-keyed session answers, never a client
  payload, so `extra_data` stays `None` there unconditionally — no code
  change was needed or made.
