---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Unknown-Field Capture Policy for Form Submissions

**Feature ID**: FEAT-458
**Date**: 2026-08-24
**Author**: Jesus
**Status**: draft
**Target version**: parrot-formdesigner 0.12.0

---

## 1. Motivation & Business Requirements

### Problem Statement

A form submission payload that carries keys the `FormSchema` does not declare
loses them **silently**. There is no error, no warning log, and no counter — the
submission returns `200` and the undeclared data is gone.

The mechanism is that `FormValidator.validate()` never iterates the payload. It
iterates the schema's fields and *pulls* each declared answer out of the payload
(`services/validators.py:190`, `data.get(field.field_id)`), building
`sanitized_data` from that pull. Anything in the payload without a matching
`field_id` is simply never looked at. `submit_data` then persists
`result.sanitized_data` (`api/handlers.py:1572-1580`) and the forwarder sends
`result.sanitized_data` (`api/handlers.py:1629`), so the extras reach **neither**
`navigator.form_data` **nor** the external endpoint.

Who is affected:

1. **External integrators posting supersets.** A third party (FieldSync, a mobile
   client, a partner system) POSTs its own richer payload, and this package only
   declares a subset of it. The undeclared remainder is discarded without either
   side being told.
2. **Client-side / computed extras.** The front end attaches derived, hidden, or
   telemetry keys (timings, device, geo hints) that no one modelled as a
   `FormField`. They vanish on arrival.

The same package is *strict* about this on a neighbouring route: the partial-save
path rejects an undeclared `field_id` outright with
`field_errors[field_id] = ["unknown field_id"]` (`api/handlers.py:601-603`). So
today `/partial` is **strict-reject** and `/submit` is **silent-drop** — two
opposite contracts on the same form, and neither is configurable.

The silent drop is the worst of the three possible behaviours. Dropping is
defensible; dropping *without saying so* makes a data-loss bug indistinguishable
from a healthy submission, discoverable only by someone noticing absent rows
after the fact.

### Goals

- **G1** — Make the treatment of undeclared submission keys an explicit, per-form
  declaration with three states: `drop`, `keep`, `reject`.
- **G2** — Default to `drop`, bit-for-bit identical to today's behaviour, so no
  existing form changes shape or behaviour on upgrade.
- **G3** — Under `keep`, persist undeclared keys verbatim in a container distinct
  from the validated answer map, preserving their provenance.
- **G4** — Under `keep`, return the caller's own flat payload shape when forwarding
  to an endpoint action, so an integrator's superset survives the round trip.
- **G5** — Bound retained extras with a hard cap enforced by **rejection**, never
  by truncation, because the public submit route is reachable unauthenticated.
- **G6** — Give `/submit` a `reject` policy that matches the contract `/partial`
  has always had, turning an accidental asymmetry into a declared one.
- **G7** — Cover **both** storage paths: the generic `FormSubmissionStorage` table
  and FEAT-457's autonomous sinks, so the feature is not silently half-working for
  forms that declare `persistence:`.

### Non-Goals (explicitly out of scope)

- **Changing the `/partial` contract.** `save_partial` keeps rejecting unknown
  `field_id`s regardless of policy (resolved in brainstorm — it stores by
  `field_uid`, which an extra has none of). The asymmetry becomes documented, not
  removed.
- **Flat-merging extras into `data`.** Rejected in brainstorm — see
  `sdd/proposals/formdesigner-unknown-fields-capture.brainstorm.md` Option C.
  It destroys the property that makes `data` useful.
- **Reusing the `context` JSONB column.** Rejected in brainstorm Option B — that
  column's documented purpose is per-revision audit context
  (`services/submissions.py:86-88`).
- **A new `FieldType` for capture.** Rejected in brainstorm Option D.
- **Retention / TTL / purge policy for captured extras.** Acknowledged as a real
  follow-up (§8) but not designed here.
- **Any change to the audio/WebSocket submission path.** `_finish_session`
  (`api/audio_ws.py:1115`) builds `data` from manifest-keyed session answers, never
  a client payload, so extras cannot arise there.
- **Resolving form-version skew.** A key matching a *renamed or removed* field is
  an extra like any other; mapping it back to its old field is not attempted.

---

## 2. Architectural Design

### Overview

Add `unknown_fields: "drop" | "keep" | "reject"` to `FormSchema` (default `drop`)
and a nullable `extra_data JSONB` column to `navigator.form_data`.

The design rests on a separation of duty:

- **`FormValidator` reports, it does not decide.** `validate()` gains the
  payload-side view it has never had — the set of top-level payload keys with no
  matching declared `field_id` — and reports it on `ValidationResult.extra_data`.
  It reads no policy. This keeps `FormValidator` platform-agnostic as its
  docstring claims (`services/validators.py:101-115`) and makes the diff unit-
  testable without an HTTP handler.
- **The handler applies the policy.** `submit_data` reads
  `form.unknown_fields` and chooses: discard (`drop`), cap-then-persist (`keep`),
  or fail with `422` (`reject`).

The decisive argument for a **dedicated column** over the cheaper alternatives is
provenance. Every cheap option puts anonymous, unvalidated, caller-controlled keys
into a container that already means something else — the audit context, or the
validated-answer map. That buys a small diff now and pays for it permanently:
once extras are indistinguishable from their host, nothing downstream can apply a
different retention rule, access rule, or trust level to them. Since the producing
endpoint is reachable **unauthenticated** (`api/handlers.py:1471-1475`), "which of
these keys did an anonymous caller choose?" is a question the schema must be able
to answer.

Two asymmetries are deliberate and must be preserved by anyone editing this code:

1. **Split at rest, flat on the wire.** Storage separates answers from extras;
   the forwarded body flat-merges them (`{**sanitized_data, **extras}`, answers
   winning collisions) because the integrator's contract is its own payload shape.
2. **Server-resolved metadata stays in `data`.** `enrich_submission`'s
   `extra_flat` keeps merging into `submission.data`
   (`api/handlers.py:1610-1613`). Its keys are resolved from the form's own
   declared `metadata` block and collision-checked; caller extras are unbounded,
   anonymous and undeclared. Distinct provenance, distinct containers.

### Component Diagram

```
POST /forms/{uid}/submit
        │
        ▼
_extract_visit_context ─────────────► strips reserved `visit_context` envelope
  (handlers.py:390, called :1484)      → downstream `data` is pure answers
        │
        ▼
merge_partials  ·  onBeforeSubmit ───► may REPLACE payload (`resolution.payload`)
  (handlers.py:1498-1541)              → the extras diff MUST run after this
        │
        ▼
FormValidator.validate ──────────────► ValidationResult
  (validators.py:122)                    ├─ sanitized_data  (declared answers)
   ├─ all_fields = _collect_fields()     ├─ errors
   │    (:169-171, recursive :944/:961)  └─ extra_data      ← NEW (reported, not judged)
   └─ NEW: payload keys ∖ declared field_ids
        │
        ▼
    ┌───────────────────── form.unknown_fields ─────────────────────┐
    │                          │                                   │
  "drop"                    "keep"                             "reject"
    │                          │                                   │
 discard                enforce_extras_cap()                 422 + onError
 (+debug log)          (256 keys / 256 KB)                (handlers.py:1552-1565
    │                     │         └─ over cap → 422           pattern reused)
    │                     ▼
    │              FormSubmission.extra_data  ← NEW
    │                     │
    └─────────┬───────────┘
              ▼
   ┌──────────────────────────────────────────────┐
   │  storage branch (FEAT-457 / TASK-2428 shape) │
   ├──────────────────────────────────────────────┤
   │  form.persistence is None                    │  form.persistence is set
   │       │                                      │       │
   │       ▼                                      │       ▼
   │  FormSubmissionStorage.store()               │  AbstractSubmissionSink.write()
   │   extra_data → its own JSONB column          │   extra_data via
   │   ($22::text::jsonb)                         │   flatten_submission / nest_submission
   └──────────────────────────────────────────────┴───────────────────────────────┘
              │
              ▼
   SubmissionForwarder.forward({**sanitized_data, **extra_data}, form.submit)
              │
              ▼
   onAfterSubmit  ·  200 response
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `FormSchema` (`core/schema.py:313`) | extends | New `unknown_fields` field, default `DROP`. Inserted after `persistence` (added by FEAT-457/TASK-2421 after `is_public`, `:374`). `FormSchema` sets no `extra="forbid"`, so purely additive. |
| `FormType` (`core/schema.py:26`) | pattern | Precedent for a `str, Enum` schema-level enum living in `core/schema.py` rather than `core/types.py`. |
| `ValidationResult` (`services/validators.py:87`) | extends | New `extra_data` attribute; the three existing fields are untouched. |
| `FormValidator.validate` (`services/validators.py:122`) | modifies | Adds the payload-side diff. Reuses the `all_fields` list already built at `:169-171`. Reads no policy. |
| `FormValidator._collect_fields` (`:944`) / `_collect_nested_fields` (`:961`) | uses | The recursive traversal that yields the correct declared-`field_id` set, including GROUP `children` and ARRAY `item_template`. |
| `FormSubmission` (`services/submissions.py:50`) | extends | New optional `extra_data: dict[str, Any] \| None = None`. |
| `FormSubmissionStorage` (`services/submissions.py:118`) | modifies | `_create_table_sql` (`:173`), `_alter_table_sql` (`:216-247`), `_insert_sql` (`:254`, +1 param with `::text::jsonb`), `store` (`:308`, `json.dumps`), `_SELECT_COLUMNS` (`:372`), `_row_to_submission` (`:380`). |
| `FormAPIHandler.submit_data` (`api/handlers.py:1440`) | modifies | Policy branch after validation (`:1549`); extras attached at `:1572`; forwarded body widened at `:1629`. Storage integration targets FEAT-457/TASK-2428's rewritten `:1615-1622`. |
| `FormAPIHandler.validate` (`api/handlers.py:993`) | modifies | Dry-run route must honour `reject` so a client can pre-flight. Public-mounted, same `enforce_membership_unless_public` guard (`:1002`). |
| `FormAPIHandler.save_partial` (`api/handlers.py:530`) | unchanged | Existing `unknown field_id` reject (`:601-603`) stays verbatim; now documented as the `reject` contract. |
| `SubmissionForwarder.forward` (`services/forwarder.py:61`) | depends on | Signature unchanged; the caller passes a wider dict. |
| `enrich_submission` (`services/metadata_enricher.py:47`) | unchanged | `extra_flat` → `data` merge stays put. Distinct concept. |
| `services/sinks/mapper.py` (**FEAT-457, planned**) | modifies | `extra_data` added to `RESERVED_COLUMNS`; emitted by `flatten_submission`, `nest_submission`, and `column_names_for`. |
| `api/audio_ws.py:1115` `_finish_session` | unchanged | Manifest-keyed answers; extras cannot arise. `extra_data` stays `None`. |
| `renderers/jsonschema.py` | deferred | Emits no `additionalProperties` today; policy mirroring is an open question (§8). |
| `navigator.form_data` (DB) | migrates | One nullable JSONB column, metadata-only on existing rows. No backfill. |

### Data Models

```python
# core/schema.py — new enum, sibling of FormType (:26)
class UnknownFieldsPolicy(str, Enum):
    """Policy for top-level submission keys the schema does not declare."""
    DROP = "drop"       # discard silently (default — today's behaviour)
    KEEP = "keep"       # capture into FormSubmission.extra_data, subject to caps
    REJECT = "reject"   # fail the submission with 422


# core/schema.py — FormSchema addition.
# Insert AFTER `persistence` (FEAT-457/TASK-2421 adds it after `is_public`, :374).
class FormSchema(BaseModel):
    ...
    is_public: bool = False
    persistence: FormPersistenceConfig | None = None   # FEAT-457 — planned
    # FEAT-458 — Unknown-Field Capture
    unknown_fields: UnknownFieldsPolicy = UnknownFieldsPolicy.DROP


# services/validators.py — ValidationResult addition
class ValidationResult(BaseModel):
    is_valid: bool
    errors: dict[str, list[str]]
    sanitized_data: dict[str, Any]
    # FEAT-458 — top-level payload keys with no matching declared field_id.
    # REPORTED, never judged: the validator reads no policy.
    extra_data: dict[str, Any] = Field(default_factory=dict)


# services/submissions.py — FormSubmission addition
class FormSubmission(BaseModel):
    ...
    context: dict[str, Any] | None = None
    # FEAT-458 — captured undeclared keys, verbatim. None when the policy was
    # not `keep`, or when `keep` was active and no extras arrived.
    extra_data: dict[str, Any] | None = None


# services/unknown_fields.py — NEW module: caps + pure enforcement
MAX_EXTRA_KEYS: int = 256
MAX_EXTRA_BYTES: int = 256 * 1024   # serialized JSON, 256 KiB


class ExtrasCapExceeded(ValueError):
    """Raised when captured extras exceed a configured cap.

    Attributes:
        limit: Which cap was exceeded — ``"keys"`` or ``"bytes"``.
        actual: The measured value.
        maximum: The configured ceiling.
    """
```

### New Public Interfaces

```python
# services/unknown_fields.py
def compute_extra_data(
    payload: dict[str, Any],
    declared_field_ids: set[str],
) -> dict[str, Any]:
    """Return the payload's top-level keys that no declared field_id covers.

    Pure, synchronous, and policy-free. ``declared_field_ids`` MUST come from
    the recursive traversal — never from ``sanitized_data.keys()``, which omits
    declared fields whose coerced value was ``None``.
    """


def enforce_extras_cap(
    extras: dict[str, Any],
    *,
    max_keys: int = MAX_EXTRA_KEYS,
    max_bytes: int = MAX_EXTRA_BYTES,
) -> None:
    """Raise ``ExtrasCapExceeded`` when ``extras`` exceeds either cap.

    Never truncates — truncation would reintroduce the silent-loss defect this
    feature exists to remove.
    """
```

---

## 3. Module Breakdown

### Module 1: `UnknownFieldsPolicy` + `FormSchema.unknown_fields`
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py`
- **Responsibility**: The enum and the single additive `FormSchema` field, default
  `DROP`. Export both from the package's public surface where `FormType` is
  exported. No validator changes beyond what pydantic gives for free.
- **Depends on**: FEAT-457/TASK-2421 merged (`FormSchema.persistence` must already
  occupy the insertion point so this lands cleanly after it).

### Module 2: Extras computation + cap enforcement
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/unknown_fields.py` (CREATE)
- **Responsibility**: `MAX_EXTRA_KEYS`, `MAX_EXTRA_BYTES`, `ExtrasCapExceeded`,
  `compute_extra_data()`, `enforce_extras_cap()`. Pure functions, no I/O, no
  policy reading — so the hardest logic in this feature is testable with no form,
  no handler, and no database.
- **Depends on**: nothing.

### Module 3: `ValidationResult.extra_data` + validator diff
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py`
- **Responsibility**: Add the `extra_data` attribute to `ValidationResult` (`:87`);
  in `validate()` (`:122`), derive the declared-`field_id` set from the existing
  `all_fields` list (`:169-171`) and call `compute_extra_data()` on the `data`
  argument, populating the new attribute on the returned result (`:220-224`).
  The validator remains policy-free and platform-agnostic.
- **Depends on**: Module 2.

### Module 4: `FormSubmission.extra_data` + storage column
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py`
- **Responsibility**: The optional model field; `extra_data JSONB` in
  `_create_table_sql` (`:173`); one more `ADD COLUMN IF NOT EXISTS extra_data
  JSONB` line in `_alter_table_sql` (`:237-247`); `_insert_sql` (`:254`) extended
  with `$22::text::jsonb` — **the cast is mandatory, see §7**; `store()` (`:308`)
  `json.dumps`-ing it exactly as it does `data` and `context`; `_SELECT_COLUMNS`
  (`:372`) and `_row_to_submission` (`:380`) extended, reusing the existing
  `_load_json` helper.
- **Depends on**: nothing (independent of Modules 1–3).

### Module 5: Policy branch in `submit_data`
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`
- **Responsibility**: After validation (`:1549`), read `form.unknown_fields` and
  branch. `reject` → early `422` on the existing validation-failure path
  (`:1552-1565`), reusing its best-effort `onError` dispatch. `keep` →
  `enforce_extras_cap()`, then attach to the `FormSubmission` at `:1572`; on
  `ExtrasCapExceeded` → `422` naming the exceeded limit. `drop` → discard, with a
  debug log recording the dropped key count (the observability today's path
  lacks). Update the `submit_data` docstring flow list (`:1443-1454`).
- **Depends on**: Modules 1, 2, 3, 4, and FEAT-457/TASK-2428 merged.

### Module 6: Dry-run `validate` endpoint honours `reject`
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`
- **Responsibility**: `FormAPIHandler.validate` (`:993`) applies the same `reject`
  decision to its `422`/`200` choice (`:1010-1015`) so a client can pre-flight a
  submission. `keep` and `drop` do not change this route's response.
- **Depends on**: Modules 1, 2, 3.

### Module 7: Forwarded-body flat merge
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`
- **Responsibility**: At `:1629`, pass `{**result.sanitized_data, **extras}` (with
  declared answers winning any key collision) instead of `result.sanitized_data`.
  Add a comment at the call site recording that the storage/wire asymmetry is
  deliberate, or it will be "corrected" later.
- **Depends on**: Module 5.

### Module 8: FEAT-457 sink coverage
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/mapper.py` (**created by FEAT-457/TASK-2420**)
- **Responsibility**: Add `extra_data` to `RESERVED_COLUMNS` so no `field_id` can
  collide with it in a tabular target; emit it from `flatten_submission()` as one
  column holding `json.dumps(...)` (the treatment `ARRAY` fields already get);
  include it in `nest_submission()`'s reserved fields; add it to
  `column_names_for()` so `ensure_target()` provisions it. Without this module a
  form declaring `persistence:` keeps losing extras, because it skips
  `FormSubmissionStorage` entirely.
- **Depends on**: Module 4 (for the field), FEAT-457/TASK-2420 + TASK-2421 merged.

### Module 9: Documentation
- **Path**: `packages/parrot-formdesigner/docs/` (follow the package's existing
  layout) and the frontend docs generator input if `unknown_fields` is
  client-visible (`scripts/gen_frontend_docs.py`).
- **Responsibility**: Document the three policies, the caps, the storage/wire
  asymmetry, the `/partial` asymmetry, and the fact that `extra_data` holds
  unvalidated caller-controlled data.
- **Depends on**: Modules 1–8.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_policy_enum_values` | 1 | `UnknownFieldsPolicy` members serialize as `"drop"`/`"keep"`/`"reject"` |
| `test_formschema_defaults_to_drop` | 1 | A form authored without `unknown_fields` gets `DROP` |
| `test_formschema_roundtrip_preserves_policy` | 1 | `model_dump` → `FormSchema(**dump)` keeps the policy |
| `test_legacy_form_json_loads` | 1 | Stored form JSON with no `unknown_fields` key still validates |
| `test_compute_extra_data_basic` | 2 | Keys absent from the declared set are returned; declared keys are not |
| `test_compute_extra_data_ignores_empty_declared_field` | 2 | A declared field whose coerced value is `None` is **not** an extra (the `sanitized_data.keys()` trap) |
| `test_compute_extra_data_nested_field_ids_are_known` | 2 | GROUP `children` / ARRAY `item_template` `field_id`s count as declared |
| `test_compute_extra_data_empty_payload` | 2 | Returns `{}`, not `None` |
| `test_enforce_cap_under_limit_passes` | 2 | 255 keys / 255 KB is accepted |
| `test_enforce_cap_key_count_raises` | 2 | 257 keys → `ExtrasCapExceeded(limit="keys")` |
| `test_enforce_cap_bytes_raises` | 2 | 256 KiB + 1 serialized → `ExtrasCapExceeded(limit="bytes")` |
| `test_enforce_cap_never_truncates` | 2 | The input dict is unmodified after a raise |
| `test_validation_result_extra_data_defaults_empty` | 3 | Existing construction sites keep working |
| `test_validate_reports_extra_data` | 3 | `validate()` populates `extra_data` for undeclared keys |
| `test_validate_extra_data_empty_when_payload_matches_schema` | 3 | No extras → `{}` |
| `test_validate_is_policy_blind` | 3 | Same `extra_data` regardless of `form.unknown_fields` |
| `test_validate_group_array_children_not_extras` | 3 | Recursive traversal is used, not `iter_all_fields` |
| `test_validate_extra_data_does_not_affect_is_valid` | 3 | Extras alone never flip `is_valid` in the validator |
| `test_submission_extra_data_optional` | 4 | `FormSubmission` builds without `extra_data` |
| `test_create_table_includes_extra_data` | 4 | DDL contains `extra_data JSONB` |
| `test_alter_table_adds_extra_data` | 4 | `ADD COLUMN IF NOT EXISTS extra_data JSONB` present |
| `test_insert_sql_casts_extra_data` | 4 | Insert uses `$22::text::jsonb`, not a bare `$22` |
| `test_store_serializes_extra_data` | 4 | `store()` passes `json.dumps(extra_data)`; `None` stays `None` |
| `test_row_to_submission_loads_extra_data` | 4 | Round-trips both a dict and a JSON string (codec-registered pool) |
| `test_row_to_submission_legacy_null_extra_data` | 4 | A row with `NULL` maps to `None` |
| `test_submit_drop_discards_extras` | 5 | `drop`: `200`, `extra_data is None`, nothing stored |
| `test_submit_drop_logs_dropped_count` | 5 | `drop` emits a debug log naming the count |
| `test_submit_keep_persists_extras` | 5 | `keep`: `200`, extras verbatim in `extra_data`, `data` unpolluted |
| `test_submit_keep_no_extras_is_none` | 5 | `keep` with a matching payload → `extra_data is None` |
| `test_submit_keep_over_cap_rejects` | 5 | Over cap → `422` naming the exceeded limit; nothing stored |
| `test_submit_reject_fails_with_422` | 5 | `reject` + extras → `422` listing the offending keys |
| `test_submit_reject_dispatches_on_error` | 5 | `onError` dispatched best-effort before the `422` |
| `test_submit_reject_clean_payload_succeeds` | 5 | `reject` + exact payload → `200` |
| `test_submit_extras_computed_after_on_before_submit` | 5 | A hook replacing `resolution.payload` is not punished |
| `test_submit_visit_context_not_captured_as_extra` | 5 | The reserved envelope key never lands in `extra_data` |
| `test_submit_visit_context_declared_field_is_not_extra` | 5 | A form with a real `visit_context` field keeps it as an answer |
| `test_validate_endpoint_reject_returns_422` | 6 | Dry-run route honours `reject` |
| `test_validate_endpoint_keep_unchanged` | 6 | `keep`/`drop` leave the dry-run response as today |
| `test_forward_body_flat_merges_extras` | 7 | Forwarded dict is `{**answers, **extras}` |
| `test_forward_answer_wins_key_collision` | 7 | A declared answer beats an extra of the same name |
| `test_forward_unchanged_under_drop` | 7 | `drop` forwards exactly `sanitized_data` |
| `test_reserved_columns_includes_extra_data` | 8 | `extra_data` in `RESERVED_COLUMNS` |
| `test_flatten_submission_emits_extra_data_json` | 8 | Tabular target gets one `json.dumps` column |
| `test_nest_submission_includes_extra_data` | 8 | Document target carries it among reserved fields |
| `test_column_names_for_includes_extra_data` | 8 | `ensure_target()` provisions the column |
| `test_field_id_named_extra_data_rejected` | 8 | Authoring-time collision check fires for a tabular target |

### Integration Tests

| Test | Description |
|---|---|
| `test_e2e_keep_stores_and_forwards` | Real submit against a live table + stub endpoint: extras in `extra_data`, flat body forwarded, `data` pure |
| `test_e2e_drop_is_byte_identical_to_baseline` | Same payload against a `drop` form before/after the change produces an identical stored row and response |
| `test_e2e_legacy_table_gains_column_on_initialize` | A pre-FEAT-458 `form_data` table picks up `extra_data` via `initialize()` with no data loss |
| `test_e2e_reject_blocks_submission` | `reject` form: `422`, no row written, `onError` fired |
| `test_e2e_persistence_form_captures_extras` | A form with `persistence:` writes extras to its own sink (tabular and document driver) and never to `form_data` |
| `test_e2e_partial_then_merge_partials_submit` | `?merge_partials=true` with a `keep` form: merged answers validate, extras still captured, `/partial` still rejects unknown ids |
| `test_e2e_codec_registered_pool_roundtrip` | With a json-codec pool, `extra_data` stores as a jsonb object (`jsonb_typeof = 'object'`) and reads back as a dict |
| `test_e2e_audio_ws_submission_unaffected` | A WebSocket audio submission still stores with `extra_data IS NULL` |

### Test Data / Fixtures

```python
@pytest.fixture
def form_with_policy():
    """Factory: a two-field FormSchema at a chosen UnknownFieldsPolicy."""
    def _make(policy: str = "drop"):
        ...  # build FormSchema(sections=[...], unknown_fields=policy)
    return _make


@pytest.fixture
def payload_with_extras():
    """Declared answers plus two undeclared keys."""
    return {"name": "Ana", "email": "a@b.c", "legacy_id": 42, "_client_ms": 1180}


@pytest.fixture
def oversized_extras():
    """257 undeclared keys — one past MAX_EXTRA_KEYS."""
    return {f"k{i}": i for i in range(257)}
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All unit tests pass (`pytest packages/parrot-formdesigner/tests/unit/ -v`)
- [ ] All integration tests pass (`pytest packages/parrot-formdesigner/tests/integration/ -v`)
- [ ] `ruff check packages/parrot-formdesigner/` and `mypy` clean on changed files
- [ ] Documentation updated for the three policies, the caps, and the two
      deliberate asymmetries
- [ ] **AC1 — No breaking change.** A form that does not declare `unknown_fields`
      produces a byte-identical stored row and a byte-identical HTTP response for
      the same payload as before this feature
      (`test_e2e_drop_is_byte_identical_to_baseline`).
- [ ] **AC2 — Legacy form JSON loads.** A stored `FormSchema` JSON document
      written before this feature validates and defaults to `drop`.
- [ ] **AC3 — Legacy table migrates in place.** A pre-existing `form_data` table
      gains a nullable `extra_data JSONB` via `initialize()`, with no backfill and
      no data loss; existing rows read back with `extra_data is None`.
- [ ] **AC4 — Provenance preserved.** Under `keep`, `submission.data` contains
      exactly the validated answers and no undeclared key; every undeclared key
      appears in `submission.extra_data`.
- [ ] **AC5 — Caps enforced by rejection.** A `keep` form receiving more than
      **256** undeclared top-level keys, or extras exceeding **256 KiB**
      serialized, is rejected with `422` naming the exceeded limit. No submission
      row is written and no extras are truncated.
- [ ] **AC6 — Under the cap, capture is verbatim.** 256 keys / 256 KiB exactly is
      accepted and stored unmodified.
- [ ] **AC7 — `reject` matches `/partial`.** A `reject` form receiving any
      undeclared top-level key returns `422` listing the offending keys, dispatches
      `onError` best-effort first, and writes nothing.
- [ ] **AC8 — Declared-but-empty is not an extra.** A declared field whose coerced
      value is `None` (omitted from `sanitized_data` by `validators.py:216-218`) is
      never reported as an extra under any policy.
- [ ] **AC9 — Nested declarations are known.** GROUP `children` and ARRAY
      `item_template` `field_id`s are not reported as extras.
- [ ] **AC10 — `visit_context` is never captured.** The reserved envelope key does
      not appear in `extra_data`; and on a form that declares a real field named
      `visit_context`, that key remains an ordinary answer.
- [ ] **AC11 — Diff runs after `onBeforeSubmit`.** A hook that replaces
      `resolution.payload` with declared fields yields no extras.
- [ ] **AC12 — Forwarded body is the caller's flat shape.** Under `keep`, the
      forwarded JSON equals `{**sanitized_data, **extra_data}` with declared
      answers winning collisions; under `drop` it equals `sanitized_data` exactly.
- [ ] **AC13 — JSONB is stored as an object, not a string.** With a
      json-codec-registered asyncpg pool, `extra_data` round-trips such that
      `jsonb_typeof(extra_data) = 'object'` and `_row_to_submission` returns a dict.
- [ ] **AC14 — Both storage paths covered.** A form declaring `persistence:`
      persists extras to its own sink (tabular via `flatten_submission`, document
      via `nest_submission`) and writes nothing to `form_data`.
- [ ] **AC15 — `extra_data` is reserved.** A form declaring a `field_id` (or
      `FormMetadataField.key`) named `extra_data` against a tabular target is
      rejected at authoring time.
- [ ] **AC16 — The validator stays policy-free.** `FormValidator.validate()`
      returns the same `extra_data` for the same payload regardless of
      `form.unknown_fields`, and reads no policy field.
- [ ] **AC17 — `/partial` unchanged.** `save_partial` still returns
      `field_errors[field_id] = ["unknown field_id"]` for an undeclared key under
      every policy, and persists nothing for it.
- [ ] **AC18 — Audio path unchanged.** A WebSocket audio submission stores with
      `extra_data IS NULL` and its code path is untouched.
- [ ] **AC19 — Dry-run pre-flight.** `POST /forms/{uid}/validate` returns `422`
      for a `reject` form receiving undeclared keys.
- [ ] **AC20 — The drop is no longer silent.** Under `drop`, a debug log records
      how many undeclared keys were discarded.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified against `dev` on 2026-08-24 (HEAD `dd12d0bd8`). All paths are relative
> to `packages/parrot-formdesigner/src/parrot_formdesigner/` unless stated.
> Implementation agents MUST NOT reference imports, attributes, or methods not
> listed here without verifying them first.

### Verified Imports

```python
# Confirmed at services/validators.py:16-21
from ..core.constraints import ConditionOperator, DependencyOperation
from ..core.schema import FormField, FormSchema, FormSection
from ..core.types import FieldType, LocalizedString
from .auth_context import AuthContext
from .remote_response_resolver import RemoteResponseResolver, RemoteResponseSpec

# Confirmed at services/submissions.py:22-25
from pydantic import BaseModel, Field
from ._identifiers import qualified_table, validate_identifier

# Environment verified in the active .venv
# Python 3.12.3 · pydantic 2.12.5 · parrot-formdesigner __version__ = "0.10.0"
```

### Existing Class Signatures

```python
# services/validators.py:87
class ValidationResult(BaseModel):
    is_valid: bool                    # line 96
    errors: dict[str, list[str]]      # line 97
    sanitized_data: dict[str, Any]    # line 98

# services/validators.py:101
class FormValidator:
    def __init__(self) -> None: ...                                   # line 118
    async def validate(                                               # line 122
        self,
        form: FormSchema,
        data: dict[str, Any],
        *,
        locale: str = "en",
        auth_context: AuthContext | None = None,
        location_vars: dict[str, Any] | None = None,
        visit_context: dict[str, Any] | None = None,
    ) -> ValidationResult: ...
    async def validate_field(self, field, value, ...) -> list[str]: ...           # line 228
    def _collect_fields(self, section: FormSection) -> list[FormField]: ...        # line 944
    def _collect_nested_fields(self, field: FormField) -> list[FormField]: ...     # line 961
    def validate_rules(self, form: FormSchema) -> list[str]: ...                   # line 999

# Inside validate(): the pieces this feature reuses
#   :152-153   errors / sanitized dicts initialised
#   :156-166   __circular__ and __rules__ early returns (reserved error keys)
#   :169-171   all_fields built from _collect_fields(section) per section
#   :184-187   RuleEvaluator().resolve(...) — conditional visibility
#   :190       for field in all_fields:   ← the PULL loop; payload never iterated
#   :216-218   coerced = self._coerce_value(...); `if coerced is not None`
#   :220-224   return ValidationResult(is_valid=..., errors=..., sanitized_data=...)

# core/schema.py:26 — precedent for a schema-level str Enum in this module
class FormType(str, Enum): ...

# core/schema.py:313 — NOTE: FormSchema sets NO model_config / extra="forbid"
class FormSchema(BaseModel):
    form_uid: uuid.UUID = Field(default_factory=uuid.uuid4)
    form_id: str
    version: str = "1.0"
    title: LocalizedString
    description: LocalizedString | None = None
    sections: list[FormSection]
    submit: SubmitAction | None = None                 # line 362
    cancel_allowed: bool = True
    meta: dict[str, Any] | None = None
    created_at: datetime | None = None
    tenant: str | None = None
    metadata: list[FormMetadataField] | None = None
    events: FormEventsConfig | None = None
    form_type: FormType = FormType.SIMPLE
    product_bindings: list[str] | None = None
    published_version: str | None = None
    is_public: bool = False                            # line 374  ← FEAT-457 inserts after this
    def iter_all_fields(self) -> Iterator[FormField]: ...        # line 376 — LAYOUT ORDER ONLY
    def iter_fields_recursive(self) -> Iterator[FormField]: ...  # line 389 — full tree

# core/schema.py:175 — the ONE canonical recursive traversal (FEAT-393 Module 2)
def walk_fields(items: Iterable[SectionItem]) -> Iterator[FormField]: ...
# Its docstring notes validators.py's _collect_fields/_collect_nested_fields are
# slated to be re-keyed onto it by TASK-1998/1999, NOT replaced there.

# core/schema.py — extra="forbid" locations (form DEFINITION strictness, not payload)
#   FormField          model_config = ConfigDict(extra="forbid")   # line 78
#   FormSubsection     model_config = ConfigDict(extra="forbid")   # line 123
#   FormMetadataField  model_config = ConfigDict(extra="forbid")   # line 290

# services/submissions.py:50
class FormSubmission(BaseModel):
    submission_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    form_uid: uuid.UUID = Field(...)
    form_id: str
    form_version: str
    data: dict[str, Any]                    # line 97 — "validated (sanitized) submission data"
    is_valid: bool                          # line 98
    forwarded: bool = False
    forward_status: int | None = None
    forward_error: str | None = None
    created_at: datetime = Field(default_factory=...)
    tenant: str | None = None
    user_id: str | None = None
    username: str | None = None
    org_id: int | None = None
    submitted_at: datetime | None = None
    ip: str | None = None
    user_agent: str | None = None
    locale: str | None = None
    root_submission_id: str | None = None
    revision: int | None = None
    context: dict[str, Any] | None = None   # line 115 — per-revision AUDIT context

# services/submissions.py:118
class FormSubmissionStorage:
    def _create_table_sql(self, tenant: str | None) -> str: ...   # line 173 (data JSONB :190, context JSONB :205)
    def _alter_table_sql(self, tenant: str | None) -> str: ...    # line 216 (ADD COLUMN block :237-247)
    def _insert_sql(self, tenant: str | None) -> str: ...         # line 254 ($5::text::jsonb, $21::text::jsonb)
    async def initialize(self, *, tenant: str | None = None) -> None: ...   # line 289 (CREATE then ALTER, :301-303)
    async def store(self, submission: FormSubmission, *, tenant: str | None = None) -> str: ...  # line 308
    _SELECT_COLUMNS: str = ...                                    # line 372
    @staticmethod
    def _row_to_submission(row: Any) -> FormSubmission: ...       # line 380 (has a _load_json helper)

# services/submissions.py:39-47 — order is significant, matches _insert_sql
CORE_METADATA_COLUMNS: tuple[str, ...] = (
    "user_id", "username", "org_id", "submitted_at", "ip", "user_agent", "locale",
)
DEFAULT_SCHEMA = "navigator"   # line 31
DEFAULT_TABLE = "form_data"    # line 32

# services/forwarder.py:36
class SubmissionForwarder:
    async def forward(self, data: dict[str, Any], submit_action: SubmitAction) -> ForwardResult: ...  # line 61

# services/metadata_enricher.py:47
async def enrich_submission(
    *, request: "web.Request", form: "FormSchema", submission: "FormSubmission",
    answers: dict[str, Any], auth_context: "AuthContext",
) -> tuple[dict[str, Any], dict[str, Any]]: ...   # -> (core_overrides, extra_flat); extra_flat filled at :180

# api/handlers.py
class FormAPIHandler:
    def __init__(self, ...): ...                                   # line 138 (self._submission_storage at :154)
    def _extract_visit_context(self, form, body) -> tuple[dict, dict | None]: ...  # line 390
    async def save_partial(self, request) -> web.Response: ...     # line 530
    async def validate(self, request) -> web.Response: ...         # line 993
    async def submit_data(self, request) -> web.Response: ...      # line 1440
```

### Key line references inside `api/handlers.py`

| Lines | What |
|---|---|
| `:601-603` | `save_partial`'s `field_errors[field_id] = ["unknown field_id"]` — the existing strict-reject |
| `:1002` | dry-run `validate`'s `enforce_membership_unless_public` — route also mounted `tenant="public"` |
| `:1010-1015` | dry-run `validate`'s `validate()` call and `200`/`422` choice |
| `:1443-1454` | `submit_data` docstring flow list — must be updated |
| `:1471-1475` | `submit_data`'s `enforce_membership_unless_public` — unauthenticated reachability |
| `:1484` | `data, visit_context = self._extract_visit_context(form, body)` |
| `:1498-1520` | optional `merge_partials` merge of cached partial answers |
| `:1528-1541` | `onBeforeSubmit` dispatch; `resolution.payload` may REPLACE `data` (`:1540`) |
| `:1549` | `result = await self.validator.validate(form, data, visit_context=visit_context)` |
| `:1552-1565` | validation-failure path — best-effort `onError`, then `422`. Pattern for `reject` |
| `:1572-1580` | `FormSubmission(...)` construction, `data=result.sanitized_data` |
| `:1586-1608` | `enrich_submission` + `MetadataResolutionError` → `422` |
| `:1610-1613` | `if extra_flat: submission.data = {**submission.data, **extra_flat}` |
| `:1615-1622` | `if self._submission_storage is not None: await ...store(submission)` — **FEAT-457/TASK-2428 replaces this block** |
| `:1624-1631` | forwarder block; `forward(result.sanitized_data, form.submit)` at `:1629` |
| `:1658-1665` | `onAfterSubmit` dispatch with `payload=submission.data` (`:1664`) |
| `:1668-1675` | success response: `submission_id`, `is_valid`, `forwarded`, `forward_status`, `forward_error` |

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `UnknownFieldsPolicy` | `FormSchema` | new field, default `DROP` | `core/schema.py:374` (insertion point) |
| `compute_extra_data()` | `FormValidator.validate()` | called on `data` with the `all_fields` id set | `services/validators.py:169-171`, `:220-224` |
| `ValidationResult.extra_data` | `submit_data` | read after validation | `api/handlers.py:1549` |
| `enforce_extras_cap()` | `submit_data` `keep` branch | raises `ExtrasCapExceeded` → `422` | `api/handlers.py:1552-1565` (pattern) |
| `FormSubmission.extra_data` | `FormSubmissionStorage.store()` | `json.dumps` + `$22::text::jsonb` | `services/submissions.py:254-282`, `:308` |
| extras flat-merge | `SubmissionForwarder.forward()` | widened first argument | `services/forwarder.py:61`; call at `api/handlers.py:1629` |
| `extra_data` column emission | `flatten_submission` / `nest_submission` / `column_names_for` | **planned** — FEAT-457 | `sdd/tasks/active/TASK-2420-submission-mapper.md` |
| `extra_data` reservation | `RESERVED_COLUMNS` collision validator | **planned** — FEAT-457 | `sdd/tasks/active/TASK-2421-formschema-persistence-field.md` |

### Planned but NOT YET IMPLEMENTED (FEAT-457 — verify before use)

FEAT-457 `formbuilder-formschema-persistency` has 15 tasks, all `in-progress` as
of 2026-08-24. Every name below is **specified, not landed** — check its real
signature before importing. Source: `sdd/specs/formbuilder-formschema-persistency.spec.md`.

```python
# services/sinks/mapper.py — spec §3 Module 5 / TASK-2420  (file does not exist yet)
RESERVED_COLUMNS: frozenset[str]   # submission_id, form_uid, form_id, form_version,
                                   # created_at, tenant, user_id, username, org_id,
                                   # submitted_at, ip, user_agent, locale,
                                   # root_submission_id, revision, context
                                   # → FEAT-458 adds: extra_data
def flatten_submission(form: FormSchema, submission: FormSubmission) -> dict[str, Any]: ...   # spec :400
def nest_submission(form: FormSchema, submission: FormSubmission) -> dict[str, Any]: ...      # spec :403
def column_names_for(form: FormSchema) -> list[str]: ...                                      # TASK-2420 scope

# core/schema.py — TASK-2421
class FormPersistenceConfig(BaseModel): ...            # spec :310
    # FormSchema.persistence: FormPersistenceConfig | None = None   # spec :321, inserted after is_public (:374)

# services/sinks/ — spec §3 Modules 3-4 / TASK-2418, TASK-2419
class SinkCapability(str, Enum): ...                   # spec :249
class SinkError(Exception): ...                        # spec :329
class SinkUnavailableError(SinkError): ...             # spec :330  → 503 + Retry-After
class SinkNotCapableError(SinkError): ...              # spec :332  → 501
class SinkTargetMismatchError(SinkError): ...          # spec :334  → 422
class AbstractSubmissionSink(ABC):                     # spec :338
    async def ensure_target(self, form: FormSchema) -> None: ...          # spec :346
    async def write(self, submission: FormSubmission, payload: Any) -> str: ...  # spec :350
class SinkAliasRegistry: ...                           # spec :365
class SinkFactory: ...                                 # spec :387

# api/handlers.py — TASK-2428 rewrites :1615-1622 into a sink branch and adds a
# `sink_factory` constructor argument alongside self._submission_storage (:154).
# A form with `persistence:` set writes ONLY to its sink and SKIPS
# FormSubmissionStorage entirely — FEAT-457's central acceptance criterion.
```

### Does NOT Exist (Anti-Hallucination)

- ~~`FormSchema.unknown_fields`~~ / ~~`FormSchema.extra_fields`~~ — no such field
  today. Repo-wide grep for `unknown_fields` matches only two unrelated test
  function names (`packages/ai-parrot/tests/bots/flows/authoring/test_handler_contract.py:40`,
  `packages/ai-parrot/tests/outputs/a2ui/recipes/test_models.py:79`).
- ~~`UnknownFieldsPolicy`~~ — the enum does not exist anywhere.
- ~~`FormSubmission.extra_data`~~ and ~~the `extra_data` column~~ — neither the
  model field nor the DDL exists. Existing JSONB columns are `data` (`:190`) and
  `context` (`:205`) only.
- ~~`ValidationResult.extra_data`~~ / ~~`ValidationResult.unknown_keys`~~ — the
  model has exactly three fields (`:96-98`).
- ~~`services/unknown_fields.py`~~ — new file, does not exist.
- ~~Any payload-key iteration in the submit path~~ — `validate()` only ever
  *pulls* by declared `field_id` (`services/validators.py:190`). No code anywhere
  in the submit path enumerates the submitted payload's keys.
- ~~A warning or debug log for dropped keys~~ — the drop is entirely silent: no
  log, no metric, no counter.
- ~~`RestCallbackInput.extra_fields` as a precedent~~ — it exists
  (`services/rest_field_resolver.py:235`, also `api/uploads.py:374,400` and
  `scripts/gen_frontend_docs.py:245`) but is **unrelated**: it is the outbound
  extra args of a REST *field resolver* call, not submission extras. This name
  clash is why the policy knob is `unknown_fields`, not `extra_fields`.
- ~~`additionalProperties` in any renderer~~ — grep over `renderers/` returns
  nothing; the JSON Schema renderer says nothing about extra keys today.
- ~~A third submission-insert path~~ — only two callers of
  `_submission_storage.store()` exist: `api/handlers.py:1617` and
  `api/audio_ws.py:1149`. There is no revision-insert path to update separately.
- ~~`FormSchema.iter_all_fields()` as the traversal to use~~ — it exists
  (`core/schema.py:376`) but its own docstring says it is layout-order only and
  does **not** recurse into GROUP `children` or ARRAY `item_template`. Using it
  would misclassify declared nested fields as extras.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Async-first**; Google-style docstrings and strict type hints on every new
  function; `self.logger` (never `print`).
- **Pydantic for all structured data**; the new enum is a `str, Enum` following
  `FormType` (`core/schema.py:26`).
- **The policy decision belongs to the handler, not the validator.** Keep
  `FormValidator` policy-free — it is documented as platform-agnostic
  (`services/validators.py:101-115`) and is used outside HTTP.
- **Keep the hard logic pure.** `compute_extra_data()` and
  `enforce_extras_cap()` take plain dicts and return/raise — no form, no request,
  no pool — so the tricky cases are unit-testable without fixtures.
- **Follow the existing migration pattern**: extend `_alter_table_sql`
  (`services/submissions.py:216-247`), whose docstring explains that
  `ADD COLUMN IF NOT EXISTS` on a nullable column with no default is
  metadata-only, and let `initialize()` (`:289`, running CREATE then ALTER at
  `:301-303`) apply it on startup. No standalone migration script.
- **Mirror the `reject` error path on the existing one.** `:1552-1565` dispatches
  `onError` best-effort *before* the early `422` and preserves the status code.
  Reuse that shape rather than inventing a new failure style.
- **Reserved error-key convention.** `validate()` already uses `__circular__`
  (`:158`) and `__rules__` (`:164`) for form-level errors. Follow that shape for
  the `reject` error key (exact choice is an open question, §8).

### Known Risks / Gotchas

- **`$n::text::jsonb` is mandatory, not stylistic.** `_insert_sql`'s comment
  (`services/submissions.py:255-273`) records a measured 2026-08-14 production
  defect: a host-provided asyncpg pool with a registered json codec re-encoded a
  bare parameter, storing a jsonb **string** instead of an object, after which
  `get_submission` raised `ValidationError` reading back its own rows. The new
  `extra_data` parameter must be `$22::text::jsonb` and `json.dumps`-ed in
  `store()`. AC13 exists to catch a regression here.
- **Do not derive extras from `sanitized_data.keys()`.** The per-field loop omits
  a declared field whose coerced value is `None` (`:216-218`). Keying the diff off
  `sanitized_data` would reclassify every empty optional answer as caller junk —
  a data-corruption bug wearing the costume of this feature. Use the declared-
  `field_id` set from `all_fields`.
- **Use the recursive traversal.** `_collect_fields` (`:944`) +
  `_collect_nested_fields` (`:961`) descend into GROUP `children` and ARRAY
  `item_template`; `FormSchema.iter_all_fields` (`:376`) does not.
- **Ordering matters twice.** The diff must run (a) on the post-
  `_extract_visit_context` `data`, or the reserved envelope key is captured as an
  extra; and (b) *after* `onBeforeSubmit`, because the hook may replace the
  payload wholesale (`:1540`).
- **The public route is unauthenticated.** `submit_data` (`:1471-1475`) and the
  dry-run `validate` (`:1002`) are both mounted `tenant="public"`. `keep` retains
  caller-controlled JSON, which is why AC5 rejects rather than truncates, and why
  retention is flagged in §8.
- **Half-working risk if Module 8 is skipped.** A form with `persistence:` skips
  `FormSubmissionStorage` entirely. Shipping Modules 1–7 without 8 means extras are
  captured for generic-storage forms and lost for autonomous ones — the same class
  of silent loss this feature removes.
- **`extra_data` must be reserved before a tabular sink can be trusted.** Without
  the `RESERVED_COLUMNS` addition, a form could declare a `field_id` named
  `extra_data` and collide with the reserved column in its own sink.
- **Merge pressure on three shared files.** `core/schema.py`,
  `services/validators.py` and `api/handlers.py` are contended by FEAT-456 and
  FEAT-457. See Worktree Strategy — this spec is *blocked* on FEAT-457, not merely
  adjacent to it.
- **The storage/wire asymmetry will look like a bug to a future reader.** Split at
  rest, flat-merged on the wire, by design. It needs a comment at
  `api/handlers.py:1629` or someone will "fix" it.
- **`NULL` vs `{}`** for a `keep` form that received no extras is unresolved (§8);
  the tests above assume `None`. Settle it before Module 4 lands, since it is a
  storage semantic, not a detail.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `pydantic` | `>=2.12` | enum + model fields; already a core dependency (2.12.5 verified) |
| `asyncpg` | (existing) | one added insert parameter and one added column; already used by `FormSubmissionStorage` |

No new third-party dependency is introduced. Caps are `len()` and
`len(json.dumps(...).encode())`.

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — all tasks run sequentially in one
  worktree.
- **Rationale**: ~6 files, and the two hottest (`core/schema.py`,
  `api/handlers.py`) are already contended by two active features. A single
  worktree keeps this feature's conflict surface to one rebase against `dev`
  rather than several. Splitting would cost more in merge coordination than it
  saves.
- **Internal ordering** (sequential, but Modules 2 and 4 are genuinely
  independent and may be done in either order):

  ```
  Module 1 (schema field)
  Module 2 (pure extras logic)  ─┐
  Module 4 (storage column)     ─┤ independent of each other
                                 ▼
  Module 3 (validator diff, needs 2)
                                 ▼
  Module 5 (handler policy branch, needs 1-4)
                                 ▼
  Module 6 (dry-run validate) · Module 7 (forwarder merge)
                                 ▼
  Module 8 (FEAT-457 sink coverage)
                                 ▼
  Module 9 (docs)
  ```

- **Cross-feature dependencies — MUST be merged first:**
  - **FEAT-457 `formbuilder-formschema-persistency`** — hard blocker, resolved
    decision. Two reasons:
    1. **Line collision.** TASK-2421 adds `FormSchema.persistence` *"after
       `is_public` (currently `core/schema.py:374`)"* — byte-for-byte this
       spec's insertion point. TASK-2428 *"Replace the block at
       `api/handlers.py:1615-1622`"* — this spec's storage integration site.
    2. **Semantic dependency.** Module 8 edits `services/sinks/mapper.py`, a file
       FEAT-457/TASK-2420 creates. It cannot be written before that file exists.
  - **FEAT-456 `formbuilder-fieldtype-cardinality`** — *not* a blocker. It shares
    `core/schema.py` (TASK-2411 `FormField.relation`) and
    `services/validators.py` (TASK-2415 relational shape validation), so textual
    conflicts are likely, but there is no semantic dependency in either
    direction. Rebase, do not wait.
- **Worktree creation** (only after FEAT-457 has merged to `dev`):
  ```bash
  git checkout dev && git pull --ff-only origin dev
  git worktree add -b feat-458-formdesigner-unknown-fields-capture \
    .claude/worktrees/feat-458-formdesigner-unknown-fields-capture HEAD
  ```

---

## 8. Open Questions

### Resolved

- [x] Flow type and base branch — *Resolved in brainstorm*: `type: feature`,
      `base_branch: dev`. Features never base on `main`. → spec frontmatter.
- [x] Where do the extra fields actually come from? — *Resolved in brainstorm*:
      external integrators POSTing supersets, plus client-side/computed keys
      (telemetry, derived, hidden). Not primarily form-version skew, and not
      DB-form drift. → §1 Problem Statement, §1 Non-Goals (version skew).
- [x] Where do kept extras land? — *Resolved in brainstorm*: a dedicated
      `extra_data JSONB` column on `form_data`, added via the existing
      `ADD COLUMN IF NOT EXISTS` block. `data` stays a pure validated-answer map.
      → §2 Overview, §2 Data Models, Module 4, AC3, AC4.
- [x] Default policy for forms that declare nothing? — *Resolved in brainstorm*:
      `drop`, bit-for-bit current behaviour. Capture is strictly opt-in per form.
      → §1 G2, Module 1, AC1, AC2.
- [x] Are kept extras forwarded to endpoint-action targets? — *Resolved in
      brainstorm*: yes. → §1 G4, Module 7, AC12.
- [x] What wire shape does the forwarded body take? — *Resolved in brainstorm*:
      flat-merge, `{**sanitized_data, **extras}`, declared answers winning
      collisions, so the integrator gets its own superset back verbatim. The
      storage split stays internal. → §2 Overview (asymmetry 1), Module 7, AC12.
- [x] Where does the policy knob live and what is it called? — *Resolved in
      brainstorm*: `FormSchema.unknown_fields`, a `"drop" | "keep" | "reject"`
      enum. Avoids the `RestCallbackInput.extra_fields` name clash. → Module 1,
      §6 Does NOT Exist.
- [x] What happens when a `keep` form is sent a huge payload? — *Resolved in
      brainstorm*: reject the submission on a hard key-count and byte cap. No
      silent truncation — that is the defect this feature removes. → §1 G5,
      Module 2, AC5, AC6.
- [x] Does `/partial` honour the policy? — *Resolved in brainstorm*: no, out of
      scope. It keeps rejecting unknown `field_id`s regardless of policy (it
      stores by `field_uid`, which extras have none of). The asymmetry becomes
      documented rather than accidental. → §1 Non-Goals, AC17.
- [x] How does this sequence against FEAT-457? — *Resolved in /sdd-spec*: hard
      dependency. FEAT-457 must merge first; tasks are written against the
      post-TASK-2428 shape of the submit path. → Worktree Strategy, Module 1
      and Module 5 depends-on.
- [x] Is FEAT-457 sink coverage in scope? — *Resolved in /sdd-spec*: yes, in
      scope. `extra_data` is added to `RESERVED_COLUMNS` and emitted by
      `flatten_submission` / `nest_submission` / `column_names_for`, so the
      feature works for autonomous forms too. → §1 G7, Module 8, AC14, AC15.
- [x] What are the concrete caps? — *Resolved in /sdd-spec*: **256 undeclared
      top-level keys** and **256 KiB serialized**. → §2 Data Models
      (`MAX_EXTRA_KEYS`, `MAX_EXTRA_BYTES`), AC5, AC6.
- [x] Target version? — *Resolved in /sdd-spec*: parrot-formdesigner 0.12.0
      (current 0.10.0; FEAT-456 and FEAT-457 both target 0.11.0 and this lands
      after FEAT-457). → spec header.

### Unresolved

- [ ] **`NULL` vs `{}` for a `keep` form that received no extras.** `NULL`
      conflates "none arrived" with "policy off"; `{}` distinguishes them at the
      cost of a row-level lie about a capture attempt. Tests above assume `None`
      — settle before Module 4 lands. — *Owner: Jesus*
- [ ] **Error-key convention for `reject`.** Follow the existing form-level
      reserved keys `__circular__` (`validators.py:158`) and `__rules__` (`:164`)
      with a `__unknown__` entry, or report per-offending-key so a client can map
      errors onto its own inputs? — *Owner: Jesus*
- [ ] **Should `onAfterSubmit` see the extras?** It currently receives
      `payload=submission.data` (`api/handlers.py:1664`). Passing the merged view
      is consistent with the forwarder; passing `data` alone is consistent with
      "answers only". — *Owner: Jesus*
- [ ] **Are the caps per-form overridable, or a single global constant?** The spec
      assumes module-level constants with an optional `FormAPIHandler` override;
      a per-form override would be a second schema field. — *Owner: Jesus*
- [ ] **Should the JSON Schema renderer emit `additionalProperties: false` under
      `reject`?** It emits nothing about extra keys today. Cheap alignment, but it
      changes rendered output for existing consumers. — *Owner: Jesus*
- [ ] **Retention for captured extras.** Anonymous caller-controlled JSON in a
      public-form column invites a purge/TTL story. Stated as a Non-Goal here —
      confirm it stays a follow-up rather than a v1 requirement. — *Owner: Jesus*
- [ ] **Is `unknown_fields` client-visible?** If the rendered form or the
      frontend docs (`scripts/gen_frontend_docs.py`) should expose the policy so a
      client knows whether its extras will be kept, Module 9 grows. — *Owner: Jesus*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-24 | Jesus | Initial draft from `sdd/proposals/formdesigner-unknown-fields-capture.brainstorm.md` (Option A); FEAT-457 sequencing, sink coverage, caps (256/256 KiB) and target version resolved during /sdd-spec |
