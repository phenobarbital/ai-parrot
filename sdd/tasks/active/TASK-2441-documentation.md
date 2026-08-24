# TASK-2441: Document the unknown-fields policy and its two asymmetries

**Feature**: FEAT-458 — Unknown-Field Capture Policy for Form Submissions
**Spec**: `sdd/specs/formdesigner-unknown-fields-capture.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2440
**Assigned-to**: unassigned
**Implements**: Spec section 3 Module 9

---

## Context

Two things in this feature will read as bugs to the next person unless they are
written down, because in both cases the "obvious" fix is wrong:

1. **Split at rest, flat on the wire.** Extras are stored in their own column but
   flat-merged into the forwarded body. Someone will try to make these consistent.
2. **`/submit` is configurable, `/partial` is always strict.** `save_partial`
   rejects unknown `field_id`s under every policy, because it stores answers keyed
   by `field_uid` and an extra has none.

Plus one operational fact worth stating plainly: `extra_data` holds unvalidated,
caller-controlled JSON that arrived at a route reachable without authentication.
Anyone reading or exporting that column should know that before they trust it.

Implements spec section 3 Module 9.

---

## Scope

- Document, in the package's existing docs layout (find it — check
  `packages/parrot-formdesigner/docs/` and the package `README`; follow the
  convention already used for `metadata` and `persistence`, do not invent a new
  structure):
  - The three policies, their exact behaviour, and that `drop` is the default and
    identical to pre-0.12.0 behaviour.
  - The caps (`MAX_EXTRA_KEYS = 256`, `MAX_EXTRA_BYTES = 256 KiB`), that they are
    module-level constants, and that exceeding them **rejects** rather than
    truncates.
  - The storage/wire asymmetry, with the reason (the integrator's contract is its
    own payload shape).
  - The `/submit` vs `/partial` asymmetry, with the reason (`field_uid` keying).
  - That `extra_data` is unvalidated caller-controlled data from a potentially
    unauthenticated route, and that retention/purge is deliberately NOT provided.
  - That under `reject` the rendered JSON Schema carries
    `additionalProperties: false`, and that the policy field itself is not
    otherwise exposed to clients.
  - A worked `keep` example: request payload → stored `data` → stored `extra_data`
    → forwarded body.
- Add the `extra_data` column to any existing table/schema reference doc for
  `navigator.form_data`.
- Update `packages/parrot-formdesigner/version.py` `__version__` to `0.12.0` **only
  if** the package convention is for the feature branch to bump it; otherwise leave
  it and note that release tooling owns the bump.

**NOT in scope**: `scripts/gen_frontend_docs.py` — resolved: `unknown_fields` is
NOT surfaced to clients in this scope. Any production-code change. A migration
runbook (there is none: `initialize()` handles it).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/docs/…` | CREATE/MODIFY | Policy documentation (exact path per existing convention) |
| `packages/parrot-formdesigner/README.md` | MODIFY | Mention the policy if the README enumerates form-level options |
| `packages/parrot-formdesigner/src/parrot_formdesigner/version.py` | MODIFY | `__version__` → `0.12.0` (only per package convention) |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references. Do NOT invent a doc path or a constant value.

### Verified Imports

```python
# Nothing to import — this is a documentation task. Values to quote, verified:
#   services/unknown_fields.py   MAX_EXTRA_KEYS  = 256           (TASK-2433)
#   services/unknown_fields.py   MAX_EXTRA_BYTES = 256 * 1024    (TASK-2433)
#   core/schema.py               UnknownFieldsPolicy.DROP is the FormSchema default
#   version.py                   __version__ = "0.10.0"  (current, verified)
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/version.py — verified content:
__title__ = "parrot-formdesigner"
__description__ = "Platform-agnostic form design and rendering package for AI-Parrot"
__version__ = "0.10.0"
__author__ = "Jesus Lara"
__author_email__ = "jesuslara@phenobarbital.info"
__license__ = "MIT"

# Facts to document, each verified:
#   services/submissions.py:31-32   navigator.form_data is the default target
#   services/submissions.py:190     data JSONB      — validated answers only
#   services/submissions.py:205     context JSONB   — per-revision AUDIT context (NOT extras)
#   api/handlers.py:1471-1475       submit route mounted tenant="public" (unauthenticated)
#   api/handlers.py:1002            dry-run validate route, same public mounting
#   api/handlers.py:601-603         save_partial's permanent `["unknown field_id"]` reject
#   api/handlers.py:1629            forwarder call — flat-merged body under `keep`
#   api/handlers.py:1664            onAfterSubmit payload — merged view under `keep`
```

### Does NOT Exist

- ~~A `docs/` directory guaranteed to exist in this package~~ — `ls` it first. If
  there is none, follow whatever the sibling packages do rather than creating a
  one-off layout.
- ~~A retention/TTL/purge mechanism for `extra_data`~~ — explicitly NOT built. Say
  so; do not document a feature that does not exist.
- ~~A per-form cap override~~ — module-level constants only.
- ~~`unknown_fields` in the frontend docs~~ — resolved as out of scope; do not add
  it to `scripts/gen_frontend_docs.py`.
- ~~A migration script~~ — `FormSubmissionStorage.initialize()` (`:289`) applies the
  column on startup.

---

## Implementation Notes

### Pattern to Follow

```markdown
## Unknown fields

A submission payload may carry keys the form does not declare. `unknown_fields`
decides what happens to them.

| Policy | Behaviour |
|---|---|
| `drop` (default) | Discarded. Identical to every release before 0.12.0, except a debug log now records how many keys were dropped. |
| `keep` | Stored verbatim in `form_data.extra_data`, and flat-merged into the body sent to an `endpoint` submit action. |
| `reject` | The submission fails with `422` and `errors.__unknown__` lists the offending keys. |

Under `keep`, extras are capped at **256 keys** and **256 KiB** serialized.
Exceeding either cap **rejects the submission** — nothing is truncated, because a
`200` that quietly lost data is the exact defect this feature removes.

### Why storage and the wire disagree

At rest, answers live in `data` and extras in `extra_data`, so you can always tell
which keys a caller chose. On the wire the forwarded body is flat
(`{...answers, ...extras}`), because an integrator posting a superset expects its
own payload shape back. This asymmetry is deliberate.

### Why `/partial` is always strict

`POST /forms/{uid}/partial` rejects an undeclared `field_id` under **every** policy.
Partial answers are stored keyed by `field_uid` so a mid-session rename cannot
orphan them — and an undeclared key has no `field_uid` to store it under.
```

### Key Constraints

- Quote the constants by value AND name, so a reader can find them in code.
- State the security posture plainly: `extra_data` is unvalidated, caller-supplied,
  and can arrive from an unauthenticated request. Do not soften it.
- Do not document `x-unknown-fields` or any client-facing exposure of the policy
  field — only the `additionalProperties: false` consequence exists.
- Only bump `version.py` if that is this package's established branch convention;
  check `git log -- packages/parrot-formdesigner/src/parrot_formdesigner/version.py`
  to see whether feature branches or release tooling own it.

### References in Codebase

- Existing docs for the `metadata` and `persistence` form-level blocks — match
  their depth and structure.
- `sdd/specs/formdesigner-unknown-fields-capture.spec.md` §2 Overview — the
  provenance argument, in case the docs need to explain *why* a separate column.

---

## Acceptance Criteria

- [ ] All three policies documented with exact behaviour and `drop` named as the
      default and as pre-0.12.0-identical.
- [ ] Caps documented by name and value, with rejection-not-truncation stated.
- [ ] The storage/wire asymmetry documented WITH its reason.
- [ ] The `/submit` vs `/partial` asymmetry documented WITH its reason.
- [ ] `extra_data` described as unvalidated caller-controlled data, and the absence
      of a retention mechanism stated explicitly.
- [ ] `additionalProperties: false` under `reject` documented; no client-facing
      exposure of the policy field claimed.
- [ ] A worked `keep` example shows payload → `data` → `extra_data` → forwarded body.
- [ ] The `extra_data` column appears in any `navigator.form_data` schema reference.
- [ ] Docs live in the package's existing layout — no new one-off structure.
- [ ] Every code reference in the docs resolves (paths and names checked).
- [ ] `__version__` handled per package convention, with the choice noted in the
      Completion Note.

---

## Test Specification

> Documentation task — no automated tests. Verification is manual:

```bash
# Every code path referenced in the docs must exist
grep -rn "extra_data" packages/parrot-formdesigner/src/parrot_formdesigner/ | head
grep -n "MAX_EXTRA_KEYS\|MAX_EXTRA_BYTES" \
  packages/parrot-formdesigner/src/parrot_formdesigner/services/unknown_fields.py

# Docs render without broken internal links (use the repo's existing docs check
# if one is wired into CI; otherwise review by eye)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/formdesigner-unknown-fields-capture.spec.md` for full context.
2. **Check dependencies** — verify every `Depends-on` task is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before writing ANY code: confirm each import
   still resolves and each listed signature still has the listed attributes. Line
   numbers were verified on `dev` at `72490fa14` (2026-08-24) and WILL drift once
   FEAT-456/FEAT-457 land — re-`grep` rather than trusting a number.
4. **Update status** in `sdd/tasks/index/formdesigner-unknown-fields-capture.json` → `"in-progress"`.
5. **Implement** following the scope and contract above. Nothing outside scope.
6. **Verify** every acceptance criterion.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update the index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
