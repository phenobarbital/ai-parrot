---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Unknown-Field Capture Policy for Form Submissions

**Date**: 2026-08-24
**Author**: Jesus
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

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

Why now: the silent-drop is the *worst* of the three possible behaviours. Dropping
is defensible; dropping *without saying so* means a data-loss bug is
indistinguishable from a healthy submission, and it can only be discovered by
someone noticing absent rows after the fact.

## Constraints & Requirements

- **Zero behaviour change on upgrade.** The default policy must be bit-for-bit
  today's silent drop. Capturing is opt-in per form.
- **The submit route is public and unauthenticated.** `submit_data` is mounted
  `tenant="public"` and calls `enforce_membership_unless_public`
  (`api/handlers.py:1471-1475`); the dry-run `validate` route is mounted the same
  way (`api/handlers.py:1002`). Any policy that retains caller-controlled keys
  MUST be bounded, or the endpoint becomes an arbitrary JSON sink for anonymous
  callers.
- **Additive only to `FormSchema`.** Existing stored form JSON must keep loading.
  Note `FormSchema` itself does **not** set `extra="forbid"` — that config is on
  `FormField` (`core/schema.py:78`), `FormSubsection` (`:123`) and
  `FormMetadataField` (`:290`) — so adding a field is safe, and unknown *definition*
  keys are already tolerated.
- **The "known field_id" set must come from the recursive traversal.**
  `_collect_fields` (`services/validators.py:944`) plus `_collect_nested_fields`
  (`:961`) descend into GROUP `children` and ARRAY `item_template`. A
  non-recursive traversal (e.g. `FormSchema.iter_all_fields`, `core/schema.py:376`,
  documented as layout-order only) would misclassify legitimately declared nested
  `field_id`s as extras.
- **The `visit_context` carve-out must run first.** `_extract_visit_context`
  (`api/handlers.py:390`) strips the reserved envelope key before validation, and
  has a documented collision guard for a form that declares a real field named
  `visit_context`. Extras computation must consume the already-stripped `data`,
  never the raw body, or the envelope key would be captured as an extra.
- **JSONB parameters require the `::text::jsonb` cast.** `_insert_sql`
  (`services/submissions.py:254-282`) passes `data` as `$5::text::jsonb` and
  `context` as `$21::text::jsonb` with a long comment explaining why: a
  host-provided asyncpg pool may register a json codec that double-encodes a bare
  parameter, storing a jsonb *string*. Any new JSONB column must follow the same
  pattern.
- **Hard sequencing dependency on FEAT-457** (see Parallelism Assessment) — it is
  in progress and touches the same two insertion points.
- Python 3.12.3, pydantic 2.12.5. No new third-party dependency is needed.

---

## Options Explored

### Option A: Policy enum on `FormSchema` + dedicated `extra_data` JSONB column

Add `unknown_fields: "drop" | "keep" | "reject"` to `FormSchema` (default
`"drop"`), and a nullable `extra_data JSONB` column to `navigator.form_data`.

`FormValidator.validate()` gains the payload-side view it currently lacks: after
the existing per-field loop, it diffs the payload's top-level keys against the
recursive declared-`field_id` set and reports the remainder on `ValidationResult`
as a new `extra_data` attribute. The three policies are then a single decision at
the handler:

- `drop` — the remainder is computed and **discarded**, exactly as today. Nothing
  is stored, nothing is forwarded. Optionally logged at debug.
- `keep` — the remainder is bounded against a key-count and serialized-byte cap;
  within the cap it is persisted verbatim to `extra_data`, and flat-merged into
  the forwarded body so the integrator gets its own superset back. Over the cap
  the submission is **rejected**, not truncated.
- `reject` — any undeclared key fails the submission with `422`, aligning `/submit`
  with the existing `/partial` contract.

`data` stays what its docstring promises: "The validated (sanitized) submission
data" (`services/submissions.py:97`). The split is internal — the wire keeps the
flat shape.

✅ **Pros:**
- `data` remains a pure, trustworthy answer map. A reader can tell an answer from
  an unsolicited key without knowing a convention.
- `extra_data` is independently queryable, independently indexable, and
  independently purgeable — which matters when the content is anonymous
  caller-controlled JSON with its own retention story.
- No shadowing hazard: when a future schema version *declares* one of the
  previously-extra `field_id`s, old rows keep the value in `extra_data` and new
  rows put it in `data`. The migration is a readable backfill instead of an
  ambiguity.
- The enum admits the third state (`reject`) that a boolean would have to grow
  later, and gives `/partial`'s existing strictness a name.
- Migration is the pattern already established in this file: one more
  `ADD COLUMN IF NOT EXISTS` line in `_alter_table_sql`
  (`services/submissions.py:237-247`), described in its own docstring as a
  metadata-only operation for a nullable column with no default.

❌ **Cons:**
- Widest blast radius of the options: `core/schema.py`, `services/validators.py`,
  `services/submissions.py`, `api/handlers.py`, plus the read path
  (`_SELECT_COLUMNS` `:372`, `_row_to_submission` `:380`) and the insert parameter
  list.
- Touches the two exact lines FEAT-457 is rewriting (see Parallelism Assessment).
- Storage and wire shapes deliberately differ (split at rest, flat on the wire),
  which is one more thing to document or someone will "fix" it.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` | `FormSchema` field + enum, `ValidationResult` attribute | 2.12.5, already a core dependency |
| `asyncpg` | `ADD COLUMN IF NOT EXISTS` + one extra insert parameter | already used by `FormSubmissionStorage`; needs the `::text::jsonb` cast |
| — | no new dependency | policy is a `str` `Enum`; caps are `len()` and `len(json.dumps(...))` |

🔗 **Existing Code to Reuse:**
- `services/submissions.py:216-247` — `_alter_table_sql`, the idempotent
  `ADD COLUMN IF NOT EXISTS` migration block to extend.
- `services/submissions.py:254-282` — `_insert_sql`, and the `::text::jsonb`
  double-encoding lesson recorded in its comment.
- `services/validators.py:944-961` — `_collect_fields` / `_collect_nested_fields`,
  the recursive traversal that already produces the correct declared-`field_id` set
  inside `validate()` as `all_fields` (`:169-171`).
- `services/metadata_enricher.py:47` — `enrich_submission`'s
  `(core_overrides, extra_flat)` return is the established precedent for splitting
  "promoted to columns" from "the rest".
- `api/handlers.py:1552-1565` — the existing validation-failure path, including
  the best-effort `onError` dispatch before the early `422`, which `reject` should
  mirror exactly.

---

### Option B: Reuse the existing `context` JSONB column, handler-global toggle

No schema change and no migration: capture extras into the `context JSONB` column
that already exists (`services/submissions.py:205`, model field `:115`), gated by
a single `FormAPIHandler` constructor flag rather than a per-form declaration.

✅ **Pros:**
- Cheapest possible path to "stop losing data" — no DDL, no `FormSchema` change,
  therefore no collision with FEAT-457's `core/schema.py:374` insertion point.
- Deployment-wide switch: a tenant can turn capture on without touching a single
  stored form definition.

❌ **Cons:**
- Overloads a column whose documented purpose is different: "Optional
  per-revision audit context (free-form JSONB), e.g. geofence status, GPS
  coordinates, and a post-visit flag" (`services/submissions.py:86-88`). Mixing
  anonymous caller-controlled keys into the audit context is exactly the
  `data`-pollution problem, moved one column over — and this time into the column
  used for audit.
- No per-form granularity, which is the granularity that matters: a public survey
  form may want capture; a DB-backed insert form must not.
- No route to `reject`, so the `/submit` ⇄ `/partial` asymmetry stays unresolved.
- Collision risk with whatever writes `context` today for the same submission.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| — | none | reuses existing column and model field |

🔗 **Existing Code to Reuse:**
- `services/submissions.py:115` — `FormSubmission.context`, already wired through
  insert (`$21::text::jsonb`), `_SELECT_COLUMNS` (`:372`) and `_row_to_submission`
  (`:380`). Nothing on the storage path needs touching.
- `api/handlers.py:138` — `FormAPIHandler.__init__`, where the toggle would live.

---

### Option C: Flat-merge extras into `data`, mirroring metadata `extra_flat`

Capture undeclared keys and merge them straight into the submission blob, exactly
as metadata enrichment already does: `submission.data = {**submission.data,
**extra_flat}` (`api/handlers.py:1612-1613`, values from
`services/metadata_enricher.py:180`).

✅ **Pros:**
- Perfectly symmetric with an existing, shipped, reviewed behaviour in the same
  handler — the smallest conceptual addition to the codebase.
- No DDL and no read-path change; `data` is already JSONB and already round-trips.
- Extras automatically flow everywhere `data` flows: the forwarder, the
  `onAfterSubmit` payload (`api/handlers.py:1664`), and FEAT-457's future sink
  mappers — no per-consumer wiring.

❌ **Cons:**
- Destroys the property that makes `data` useful: an answer and an unsolicited
  anonymous key become indistinguishable after the fact. Every downstream reader
  inherits the ambiguity.
- Shadowing hazard. The day a schema version declares a `field_id` that used to
  arrive as an extra, old rows and new rows carry the same key with different
  provenance and different validation history, with nothing recording which is
  which.
- Metadata `extra_flat` is *not* really a precedent for this: its keys are
  server-resolved from a form's own declared `metadata` block, and
  `enrich_submission` explicitly raises when a resolved key would collide with an
  answer. Caller-supplied extras are unbounded, anonymous, and undeclared — the
  opposite provenance.
- Makes a future `reject` or a retention policy on extras effectively
  unimplementable, because by then nothing can identify them.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| — | none | reuses `data` JSONB |

🔗 **Existing Code to Reuse:**
- `api/handlers.py:1610-1613` — the `extra_flat` merge block, verbatim pattern.
- `services/metadata_enricher.py:47-182` — the split-and-merge shape.

---

### Option D (unconventional): An `EXTRAS` capture field, declared in the form itself

Rather than a policy flag plus a column, make the capture point a *field*. Add a
`FieldType.EXTRAS` whose `field_id` the form author chooses; the validator fills
that field's sanitized value with every undeclared top-level key it found. Opting
in means adding a field to the form — ordinary form authoring, no new top-level
schema concept. Renderers skip it (it has no UI).

✅ **Pros:**
- Zero DDL and zero read-path change, yet the extras are *named* and
  self-describing rather than magic: `data["_integrator_extras"]` because the
  author declared a field called `_integrator_extras`.
- Per-form opt-in falls out for free, at exactly the granularity that matters,
  with no new `FormSchema` field — so no collision with FEAT-457's
  `core/schema.py:374` insertion point.
- Extras flow automatically through the forwarder, `onAfterSubmit`, and FEAT-457's
  sink mappers, because to every consumer they are just an ordinary answer.
- The capture key is visible in the form definition, so an integrator reading the
  schema can see that its superset is being retained.

❌ **Cons:**
- Requires a new `FieldType` enum member — and `FieldType`/`FormField` are the
  hottest shared surface in the package right now, with FEAT-456 actively adding
  `FormField.relation` there (TASK-2411).
- A field that renders nothing, validates nothing, and cannot be filled by a user
  is a category error inside `FormField`; every renderer, extractor and the
  assembler must learn to skip it (`tests/unit/test_assembler.py:114` already
  asserts unknown field types fail).
- Still lands the extras inside `data` — Option C's ambiguity, merely under an
  author-chosen key instead of a magic one.
- No route to `reject`, and no natural place for the size cap.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| — | none | new enum member + validator branch |

🔗 **Existing Code to Reuse:**
- `core/types.py` — `FieldType` enum (imported at `services/validators.py:18`).
- `services/validators.py:190-218` — the per-field loop, where an `EXTRAS` branch
  would sit alongside the existing `REMOTE_RESPONSE` (`:203`) and `REST` (`:207`)
  special cases.

---

## Recommendation

**Option A** is recommended.

The decisive argument is provenance. Every cheap option (B, C, D) works by putting
anonymous, unvalidated, caller-controlled keys into a container that already means
something else — the audit context in B, the validated-answer map in C and D. That
buys a small diff now and pays for it permanently, because once the extras are
indistinguishable from their host, nothing downstream can apply a different
retention rule, a different access rule, or a different trust level to them. Given
that the producing endpoint is reachable **unauthenticated** (`api/handlers.py:1471-1475`),
"which of these keys did an anonymous caller choose" is a question the schema
should be able to answer, and only a separate column answers it cheaply.

What Option A trades away is honest and worth stating:

- **A wider diff and a DDL change.** Accepted because the DDL is one nullable
  column added through the block whose own docstring
  (`services/submissions.py:217-221`) explains it is metadata-only on existing
  rows, and because the read path is a mechanical two-line extension
  (`_SELECT_COLUMNS` `:372`, `_row_to_submission` `:380`).
- **A storage/wire asymmetry** — split at rest, flat-merged on the wire. Accepted
  because the integrator's contract is its own payload shape; making it learn an
  envelope in order to get its own field back would be a gratuitous break. This
  needs an explicit comment at the forward call site or it will be "corrected"
  later.
- **Direct overlap with in-flight FEAT-457.** Not accepted as a risk to absorb —
  handled by sequencing, below, which is why it is the first open question rather
  than an implementation note.

Option B is the right answer to a *different* question ("stop the bleeding this
week"). If the sequencing dependency on FEAT-457 turns out to block this feature
for longer than the data loss can be tolerated, B is the stopgap to reach for —
but as a stopgap, not as the design, and pointed at a scratch column rather than
`context`.

---

## Feature Description

### User-Facing Behavior

**Form author.** One new optional declaration on the form:

```yaml
unknown_fields: keep    # drop (default) | keep | reject
```

Omitting it preserves today's behaviour precisely, so no existing form changes
shape or behaviour on upgrade.

**Submitting client, `drop` (default).** Nothing changes. Undeclared keys are
ignored; the submission succeeds; the response body is unchanged.

**Submitting client, `keep`.** The submission succeeds. Declared answers are
validated and stored as always; undeclared top-level keys are stored verbatim,
separately from the answers. If the form forwards to an endpoint, the forwarded
body is the caller's original flat shape — declared answers plus extras — so an
integrator's superset survives the round trip. If the payload exceeds the
configured extras cap (key count or serialized bytes), the submission is rejected
with an explicit error naming the limit that was exceeded; nothing is silently
truncated.

**Submitting client, `reject`.** Any undeclared top-level key fails the submission
with `422` and a field-level error listing the offending keys — the same contract
`/partial` has had all along (`api/handlers.py:601-603`).

**Reader of stored submissions.** `data` continues to hold exactly the validated
answers. A new `extra_data` field holds the captured extras, or `null` when there
were none or the policy was not `keep`.

**Dry-run validation.** The `POST /api/v1/forms/{form_uid}/validate` endpoint
(`api/handlers.py:993`) honours the same policy, so a client can discover a
`reject` violation before attempting a real submission.

### Internal Behavior

1. **Payload arrives.** `submit_data` (`api/handlers.py:1440`) parses the body and
   `_extract_visit_context` (`:390`, called at `:1484`) strips the reserved
   `visit_context` envelope. Everything downstream sees pure answers — the extras
   diff must consume this stripped `data`, never the raw body.
2. **Partial merge and `onBeforeSubmit`** run unchanged (`:1498-1541`). Because the
   lifecycle hook may replace the payload wholesale (`resolution.payload` at
   `:1540`), the extras diff must happen *after* it, so a hook that legitimately
   injects declared fields is not punished.
3. **Validation computes the diff.** `FormValidator.validate()` already builds the
   full recursive declared-field list as `all_fields` (`services/validators.py:169-171`,
   via `_collect_fields` `:944` / `_collect_nested_fields` `:961`). The addition is
   the reverse view it has never had: the set of top-level payload keys with no
   matching declared `field_id`. That remainder is reported on `ValidationResult`
   (`:87`) as a new attribute, alongside the existing `is_valid` (`:96`), `errors`
   (`:97`) and `sanitized_data` (`:98`). The validator stays policy-free — it
   *reports* the remainder; it does not decide its fate. This keeps
   `FormValidator` platform-agnostic, as its docstring claims (`:101-115`), and
   makes the diff testable without a handler.
4. **The handler applies the policy.** Read from `form.unknown_fields`:
   - `reject` and the remainder is non-empty → early `422` on the existing
     validation-failure path (`:1552-1565`), reusing its best-effort `onError`
     dispatch, with the offending keys under a reserved error key.
   - `keep` → enforce the cap; over it, reject the same way. Within it, attach the
     remainder to the `FormSubmission` (`:1572`).
   - `drop` → discard; optionally a debug log recording how many keys were
     dropped, which is the observability the current silent path lacks.
5. **Metadata enrichment is unaffected.** `enrich_submission`
   (`services/metadata_enricher.py:47`) keeps returning
   `(core_overrides, extra_flat)` and `extra_flat` keeps merging into
   `submission.data` (`api/handlers.py:1612-1613`). Server-resolved metadata and
   caller-supplied extras stay distinct concepts in distinct containers — that
   distinction is a feature, not an inconsistency.
6. **Storage.** One nullable `extra_data JSONB` column, added to both
   `_create_table_sql` (`services/submissions.py:173`) and the idempotent
   `_alter_table_sql` block (`:237-247`) so legacy tables pick it up on
   `initialize()` (`:296-305`). `store()` (`:308`) `json.dumps` it exactly as it
   does `data` and `context`, and the new insert parameter takes the mandatory
   `::text::jsonb` cast (`:254-282`). Reads extend `_SELECT_COLUMNS` (`:372`) and
   `_row_to_submission` (`:380`), whose existing `_load_json` helper already
   handles the str-or-dict ambiguity.
7. **Forwarding.** The forward call currently passes `result.sanitized_data`
   (`:1629`) into `SubmissionForwarder.forward(data, submit_action)`
   (`services/forwarder.py:61`). Under `keep` it passes the flat merge of answers
   and extras, with declared answers winning any key collision.

### Edge Cases & Error Handling

- **A key collides with a declared `field_id` after coercion drops it.** The
  per-field loop omits a field from `sanitized_data` when its coerced value is
  `None` (`services/validators.py:216-218`). Such a key is **declared**, so it is
  not an extra — the diff must be computed against the declared-`field_id` set,
  never against `sanitized_data.keys()`. Getting this backwards would silently
  reclassify every empty optional answer as caller junk.
- **Nested GROUP / ARRAY children.** Their `field_id`s are declared and are
  reached by `_collect_fields`' recursion, so they must count as known even though
  their submitted values may be nested inside a parent's value.
- **`visit_context` on a form that declares a real field of that name.**
  `_extract_visit_context` deliberately leaves the key in `data` in that case
  (`api/handlers.py:441-452`). It is then a declared field, so it is not an extra.
  Correct by construction, provided the diff runs on the post-strip `data`.
- **Over-cap payload.** Rejected, never truncated. Truncation would reintroduce
  the exact defect this feature exists to remove: a `200` that quietly lost data.
- **`keep` with no extras.** `extra_data` is `NULL`, not `{}` — so "policy was on,
  nothing arrived" and "policy was off" are distinguishable from the row alone
  only in combination with the form version; an empty dict would falsely imply a
  capture attempt. (Flagged as an open question — the inverse convention is
  defensible.)
- **Legacy rows.** `extra_data` is `NULL` on every pre-existing row and the model
  field is optional, so `_row_to_submission` keeps working with no backfill.
- **The audio/WebSocket submission path needs nothing.** `_finish_session`
  (`api/audio_ws.py:1115`) builds `data` from `session.answers`, which are keyed by
  the manifest's own question ids and never from a client-supplied payload
  (`:1141-1147`), then calls `store()` directly (`:1149`). Extras cannot arise
  there; `extra_data` stays `None`.
- **`reject` and lifecycle hooks.** The rejection must dispatch `onError`
  best-effort before returning, matching how the existing validation and metadata
  failures behave (`api/handlers.py:1552-1565`, `:1596-1608`), so a form's error
  handler sees it.

---

## Capabilities

### New Capabilities
- `unknown-fields-policy`: a per-form `drop` | `keep` | `reject` declaration
  governing top-level submission keys that the schema does not declare.
- `submission-extra-data-storage`: verbatim persistence of captured undeclared
  keys in a dedicated `extra_data` JSONB column, separate from the validated
  answer map.
- `extras-payload-cap`: a key-count and serialized-byte bound on captured extras,
  enforced by rejection rather than truncation, protecting the public
  unauthenticated submit route.

### Modified Capabilities
- `parrot-formdesigner-post-method` — `submit_data`'s validate → build → enrich →
  store → forward pipeline gains a policy branch and a wider forwarded body.
- `formdesigner-partial-saves` — unchanged in behaviour, but its existing
  strict-reject becomes the documented `reject` policy rather than an
  undocumented asymmetry.
- `formbuilder-formschema-persistency` (FEAT-457, in progress) — its submission
  mappers and reserved-column validation must account for `extra_data`.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `core/schema.py:313` `FormSchema` | extends | New `unknown_fields` enum field, default `drop`. Insert after `is_public` (`:374`) — **the same line FEAT-457/TASK-2421 targets**. `FormSchema` sets no `extra="forbid"`, so purely additive. |
| `services/validators.py:87` `ValidationResult` | extends | New attribute carrying the undeclared-key remainder. Additive; existing three fields untouched. |
| `services/validators.py:122` `FormValidator.validate` | modifies | Adds the payload-side diff against the recursive declared-`field_id` set. Stays policy-free. |
| `services/submissions.py:50` `FormSubmission` | extends | New optional `extra_data: dict[str, Any] \| None = None`. |
| `services/submissions.py:173/216/254/308/372/380` | modifies | DDL, `ADD COLUMN IF NOT EXISTS`, insert (+1 param, `::text::jsonb`), `store()` `json.dumps`, `_SELECT_COLUMNS`, `_row_to_submission`. |
| `api/handlers.py:1440` `submit_data` | modifies | Policy branch after validation; extras attached at `:1572`; forwarded body widened at `:1629`. **`:1615-1622` is the block FEAT-457/TASK-2428 replaces wholesale.** |
| `api/handlers.py:993` `validate` (dry-run) | modifies | Must honour `reject` so clients can pre-flight. Public-mounted, same guard. |
| `api/handlers.py:530` `save_partial` | unchanged | Existing `unknown field_id` reject (`:601-603`) stays as-is; now documented as the `reject` policy. |
| `services/forwarder.py:61` `forward` | depends on | Signature unchanged; caller passes a wider dict. |
| `services/metadata_enricher.py:47` | unchanged | `extra_flat` → `data` merge (`api/handlers.py:1612-1613`) is a distinct concept and stays put. |
| `api/audio_ws.py:1115` `_finish_session` | unchanged | Manifest-keyed answers; extras cannot arise. |
| `renderers/jsonschema.py` | opportunity | Emits no `additionalProperties` today; could mirror the policy. Deferred — see Open Questions. |
| `navigator.form_data` (DB) | migrates | One nullable JSONB column, metadata-only on existing rows. No backfill. |

Breaking changes: **none** with the `drop` default. New dependencies: none.
Deployment: the column is added by the app's own `initialize()` path
(`services/submissions.py:296-305`), so no standalone migration script is
required — but a tenant whose table is created out-of-band needs the DDL applied.

---

## Code Context

### User-Provided Code

None — the user described the problem in prose and the design was settled through
the Round 1/Round 2 decisions recorded under Open Questions.

### Verified Codebase References

#### Classes & Signatures

```python
# From packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py:87
class ValidationResult(BaseModel):
    is_valid: bool                    # line 96
    errors: dict[str, list[str]]      # line 97
    sanitized_data: dict[str, Any]    # line 98

# From .../services/validators.py:101
class FormValidator:
    def __init__(self) -> None: ...                                  # line 118
    async def validate(                                              # line 122
        self,
        form: FormSchema,
        data: dict[str, Any],
        *,
        locale: str = "en",
        auth_context: AuthContext | None = None,
        location_vars: dict[str, Any] | None = None,
        visit_context: dict[str, Any] | None = None,
    ) -> ValidationResult: ...
    async def validate_field(self, field, value, ...) -> list[str]: ...   # line 228
    def _collect_fields(self, section: FormSection) -> list[FormField]: ...      # line 944
    def _collect_nested_fields(self, field: FormField) -> list[FormField]: ...   # line 961
    def validate_rules(self, form: FormSchema) -> list[str]: ...                # line 999

# From .../core/schema.py:313 — NOTE: FormSchema sets NO model_config/extra="forbid"
class FormSchema(BaseModel):
    form_uid: uuid.UUID = Field(default_factory=uuid.uuid4)
    form_id: str
    version: str = "1.0"
    title: LocalizedString
    description: LocalizedString | None = None
    sections: list[FormSection]
    submit: SubmitAction | None = None            # line 362
    cancel_allowed: bool = True
    meta: dict[str, Any] | None = None
    created_at: datetime | None = None
    tenant: str | None = None
    metadata: list[FormMetadataField] | None = None
    events: FormEventsConfig | None = None
    form_type: FormType = FormType.SIMPLE
    product_bindings: list[str] | None = None
    published_version: str | None = None
    is_public: bool = False                       # line 374  <-- insert point
    def iter_all_fields(self) -> Iterator[FormField]: ...        # line 376 (layout order ONLY)
    def iter_fields_recursive(self) -> Iterator[FormField]: ...  # line 389 (full tree)

# From .../core/schema.py:175
def walk_fields(items: Iterable[SectionItem]) -> Iterator[FormField]: ...
# The ONE canonical recursive traversal (FEAT-393 Module 2); its docstring notes
# validators.py's _collect_fields/_collect_nested_fields are slated to be re-keyed
# onto it by TASK-1998/1999, NOT replaced there.

# From .../services/submissions.py:50
class FormSubmission(BaseModel):
    submission_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    form_uid: uuid.UUID = Field(...)
    form_id: str
    form_version: str
    data: dict[str, Any]                      # line 97  "validated (sanitized) submission data"
    is_valid: bool                            # line 98
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
    context: dict[str, Any] | None = None     # line 115  per-revision AUDIT context

# From .../services/submissions.py:118
class FormSubmissionStorage:
    def _create_table_sql(self, tenant: str | None) -> str: ...   # line 173 (data JSONB :190, context JSONB :205)
    def _alter_table_sql(self, tenant: str | None) -> str: ...    # line 216 (ADD COLUMN block :237-247)
    def _insert_sql(self, tenant: str | None) -> str: ...         # line 254 ($5::text::jsonb, $21::text::jsonb)
    async def initialize(self, *, tenant: str | None = None) -> None: ...  # line 289
    async def store(self, submission: FormSubmission, *, tenant: str | None = None) -> str: ...  # line 308
    _SELECT_COLUMNS: str = ...                                    # line 372
    @staticmethod
    def _row_to_submission(row: Any) -> FormSubmission: ...       # line 380 (has _load_json helper)

# From .../services/forwarder.py:36
class SubmissionForwarder:
    async def forward(self, data: dict[str, Any], submit_action: SubmitAction) -> ForwardResult: ...  # line 61

# From .../services/metadata_enricher.py:47
async def enrich_submission(
    *, request: "web.Request", form: "FormSchema", submission: "FormSubmission",
    answers: dict[str, Any], auth_context: "AuthContext",
) -> tuple[dict[str, Any], dict[str, Any]]: ...   # -> (core_overrides, extra_flat)

# From .../api/handlers.py
class FormAPIHandler:
    def __init__(self, ...): ...                                  # line 138 (self._submission_storage at :154)
    def _extract_visit_context(self, form, body) -> tuple[dict, dict | None]: ...  # line 390
    async def save_partial(self, request) -> web.Response: ...    # line 530 (unknown field_id reject :601-603)
    async def validate(self, request) -> web.Response: ...        # line 993 (dry-run; validate() call :1010)
    async def submit_data(self, request) -> web.Response: ...     # line 1440
```

#### Key line references inside `submit_data` (`api/handlers.py`)

- `:1471-1475` — `enforce_membership_unless_public`; route is also mounted `tenant="public"`.
- `:1484` — `data, visit_context = self._extract_visit_context(form, body)`.
- `:1498-1520` — optional `merge_partials` merge of cached partial answers.
- `:1528-1541` — `onBeforeSubmit` dispatch; `resolution.payload` may replace `data`.
- `:1549` — `result = await self.validator.validate(form, data, visit_context=visit_context)`.
- `:1552-1565` — validation-failure path: best-effort `onError`, then `422`.
- `:1572-1580` — `FormSubmission(...)` construction, `data=result.sanitized_data`.
- `:1586-1608` — `enrich_submission` + `MetadataResolutionError` → `422`.
- `:1610-1613` — `if extra_flat: submission.data = {**submission.data, **extra_flat}`.
- `:1615-1622` — `if self._submission_storage is not None: await ...store(submission)` — **the block FEAT-457/TASK-2428 replaces**.
- `:1624-1631` — forwarder block; `forward(result.sanitized_data, form.submit)` at `:1629`.
- `:1658-1665` — `onAfterSubmit` dispatch with `payload=submission.data`.
- `:1668-1675` — success response: `submission_id`, `is_valid`, `forwarded`, `forward_status`, `forward_error`.

#### Verified Imports

```python
# Confirmed present at services/validators.py:16-21
from ..core.constraints import ConditionOperator, DependencyOperation
from ..core.schema import FormField, FormSchema, FormSection
from ..core.types import FieldType, LocalizedString
from .auth_context import AuthContext
from .remote_response_resolver import RemoteResponseResolver, RemoteResponseSpec

# Confirmed present at services/submissions.py:22-25
from pydantic import BaseModel, Field
from ._identifiers import qualified_table, validate_identifier
```

#### Key Attributes & Constants

- `CORE_METADATA_COLUMNS` → `tuple[str, ...]` = `("user_id", "username", "org_id",
  "submitted_at", "ip", "user_agent", "locale")` (`services/submissions.py:39-47`).
  Order is significant — it matches the `_insert_sql` column order.
- `DEFAULT_SCHEMA = "navigator"`, `DEFAULT_TABLE = "form_data"`
  (`services/submissions.py:31-32`).
- `model_config = ConfigDict(extra="forbid")` on `FormField` (`core/schema.py:78`),
  `FormSubsection` (`:123`), `FormMetadataField` (`:290`) — **not** on `FormSchema`.
- Environment: Python 3.12.3, pydantic 2.12.5 (verified in the active `.venv`).
- The `$n::text::jsonb` cast on JSONB insert parameters is **mandatory**, not
  stylistic — `_insert_sql`'s comment (`services/submissions.py:255-273`) records a
  measured 2026-08-14 production defect where a host-registered json codec
  double-encoded `data` and `context`, after which `get_submission` raised
  `ValidationError` reading back its own rows.

### Does NOT Exist (Anti-Hallucination)

- ~~`FormSchema.unknown_fields`~~ / ~~`FormSchema.extra_fields`~~ — no such field
  today. Repo-wide grep for `unknown_fields` matches only two unrelated test
  function names (`packages/ai-parrot/tests/bots/flows/authoring/test_handler_contract.py:40`,
  `packages/ai-parrot/tests/outputs/a2ui/recipes/test_models.py:79`).
- ~~`FormSubmission.extra_data`~~ and ~~the `extra_data` column~~ — neither the
  model field nor the DDL exists. Existing JSONB columns are `data` (`:190`) and
  `context` (`:205`) only.
- ~~`ValidationResult.extra_data`~~ / ~~`ValidationResult.unknown_keys`~~ — the
  model has exactly three fields (`:96-98`).
- ~~Any payload-key iteration in the validator~~ — `validate()` only ever *pulls*
  by declared `field_id` (`services/validators.py:190`). There is no code anywhere
  in the submit path that enumerates the submitted payload's keys.
- ~~A warning log for dropped keys~~ — the drop is entirely silent; no log, no
  metric, no counter.
- ~~`RestCallbackInput.extra_fields` as a precedent~~ — it exists
  (`services/rest_field_resolver.py:235`, also `api/uploads.py:374,400` and
  `scripts/gen_frontend_docs.py:245`) but is **unrelated**: it is the outbound
  extra args of a REST *field resolver* call, not submission extras. This is the
  name clash that motivated choosing `unknown_fields` for the policy knob.
- ~~`additionalProperties` in any renderer~~ — grep over `renderers/` returns
  nothing; the JSON Schema renderer says nothing about extra keys today.
- ~~A second submission-insert path~~ — only two callers of
  `_submission_storage.store()` exist: `api/handlers.py:1617` and
  `api/audio_ws.py:1149`. There is no revision-insert path to update separately.
- ~~`FormSchema.persistence`~~, ~~`flatten_submission`~~, ~~`nest_submission`~~,
  ~~`RESERVED_COLUMNS`~~, ~~`sink_factory`~~ — **planned but NOT YET IMPLEMENTED**
  by FEAT-457 (TASK-2417/2420/2421/2428, all `in-progress`). Do not import or
  reference them; check their landed state before touching the submit path.

---

## Parallelism Assessment

- **Internal parallelism**: Limited but real. The storage layer
  (`services/submissions.py` — model field, DDL, `ADD COLUMN`, insert, read
  mapping) is separable from the validator diff (`services/validators.py` +
  `ValidationResult`). The `FormSchema` field and the handler policy branch are
  the join point and must come after both. Tests split cleanly per layer. Roughly:
  schema field → (validator diff ∥ storage column) → handler policy branch →
  forwarder widening → integration.

- **Cross-feature independence**: **Poor — two in-flight features overlap, one
  severely.**

  - **FEAT-457 `formbuilder-formschema-persistency`** (15 tasks, all
    `in-progress`, base `dev`) is a direct collision on both insertion points:
    - TASK-2421 adds `FormSchema.persistence` *"after `is_public` (currently
      `core/schema.py:374`)"* — byte-for-byte the line this feature wants, and its
      own task text calls `core/schema.py` *"the hottest shared file in this
      package"*.
    - TASK-2428 *"Replace the block at `api/handlers.py:1615-1622`"* with a sink
      branch — the storage call site this feature extends.
    - TASK-2420 introduces `flatten_submission` / `nest_submission` mappers. A
      form using `persistence:` writes **only** to its own sink and skips
      `FormSubmissionStorage` entirely (the exclusivity guarantee named as
      FEAT-457's central acceptance criterion). So an `extra_data` column on
      `form_data` alone leaves this feature **half-working**: extras would be
      captured for generic-storage forms and lost again for autonomous ones.
    - TASK-2421 also adds `RESERVED_COLUMNS` collision checks for tabular
      targets — `extra_data` must be reserved there, or a form could declare a
      `field_id` named `extra_data` and collide in the sink.
  - **FEAT-456 `formbuilder-fieldtype-cardinality`** (7 tasks, all
    `in-progress`, base `dev`) shares files but not lines: TASK-2411 adds
    `FormField.relation` in `core/schema.py`, TASK-2415 adds relational shape
    validation in `services/validators.py`, TASK-2414 touches
    `renderers/jsonschema.py`. Textual merge conflicts are likely; semantic
    conflict is not. Notably it makes Option D materially worse, since it is
    actively working the `FieldType`/`FormField` surface.

  Shared files: `core/schema.py`, `services/validators.py`, `api/handlers.py`
  (all three features); `renderers/jsonschema.py` (FEAT-456 + a deferred
  opportunity here).

- **Recommended isolation**: `per-spec` — one worktree, tasks sequential.

- **Rationale**: The feature is small enough (~6 files) that splitting it across
  worktrees would cost more in merge coordination than it saves, and its two
  hottest files are already contended by two active features. A single worktree
  keeps this feature's conflict surface to one rebase against `dev` rather than
  several. More importantly, the sequencing question dominates the parallelism
  question: this should be planned to land **after** FEAT-457's submit-path
  rewrite (TASK-2428) and `FormSchema.persistence` (TASK-2421) are merged, then
  written against the *new* shape of `api/handlers.py:1615-1622` — including
  teaching FEAT-457's submission mappers about `extra_data`. Starting before that
  means writing the integration twice and reviewing a conflict-heavy diff.

---

## Open Questions

Resolved during Round 0–2 of this brainstorm:

- [x] Flow type and base branch — *Owner: Jesus*: `type: feature`, `base_branch: dev`. Features never base on `main`.
- [x] Where do the extra fields actually come from? — *Owner: Jesus*: external integrators POSTing supersets, plus client-side/computed keys (telemetry, derived, hidden). Not primarily form-version skew, and not DB-form drift.
- [x] Where do kept extras land? — *Owner: Jesus*: a dedicated `extra_data JSONB` column on `form_data`, added via the existing `ADD COLUMN IF NOT EXISTS` block. `data` stays a pure validated-answer map.
- [x] Default policy for forms that declare nothing? — *Owner: Jesus*: `drop` — bit-for-bit current behaviour. Capture is strictly opt-in per form.
- [x] Are kept extras forwarded to endpoint-action targets? — *Owner: Jesus*: yes.
- [x] What wire shape does the forwarded body take? — *Owner: Jesus*: flat-merge — `{**sanitized_data, **extras}`, declared answers winning on collision, so the integrator gets its own superset back verbatim. The storage split stays internal.
- [x] Where does the policy knob live and what is it called? — *Owner: Jesus*: `FormSchema.unknown_fields` as a `"drop" | "keep" | "reject"` enum. Avoids the `RestCallbackInput.extra_fields` name clash.
- [x] What happens when a `keep` form is sent 4,000 keys / 8 MB? — *Owner: Jesus*: reject the submission (413/422) on a hard key-count and byte cap. No silent truncation — that is the defect this feature removes.
- [x] Does `/partial` honour the policy? — *Owner: Jesus*: no — out of scope. It keeps rejecting unknown `field_id`s regardless of policy (it stores by `field_uid`, which extras have none of). The asymmetry becomes documented rather than accidental.

Still open:

- [ ] **Sequencing against FEAT-457.** Land this after TASK-2421 + TASK-2428 merge and write against the rewritten `api/handlers.py:1615-1622`, or start now and absorb the conflict? Recommendation: wait. — *Owner: Jesus*
- [ ] **Does `extra_data` flow into FEAT-457's sinks?** If a `persistence:` form skips `FormSubmissionStorage` entirely, extras need a home in `flatten_submission` / `nest_submission` (TASK-2420) and `extra_data` needs adding to `RESERVED_COLUMNS` (TASK-2421) — otherwise the feature only works for generic-storage forms. Is that in scope here, or a follow-up on FEAT-457? — *Owner: Jesus*
- [ ] **Exact cap values, and per-form or global?** e.g. 64 keys / 64 KB serialized. A `FormAPIHandler` constructor default with an optional per-form override, or a single global constant? — *Owner: Jesus*
- [ ] **Should `onAfterSubmit` see the extras?** It currently receives `payload=submission.data` (`api/handlers.py:1664`). Passing the merged view is consistent with the forwarder; passing `data` alone is consistent with "answers only". — *Owner: Jesus*
- [ ] **`NULL` vs `{}` for a `keep` form that received no extras.** `NULL` conflates "none arrived" with "policy off"; `{}` distinguishes them at the cost of a row-level lie about a capture attempt. — *Owner: Jesus*
- [ ] **Error-key convention for `reject`.** The existing reserved keys are `__circular__` and `__rules__` (`services/validators.py:158`, `:164`). Follow with `__unknown__`, or report per-offending-key so a client can map errors to inputs? — *Owner: Jesus*
- [ ] **Should the JSON Schema renderer emit `additionalProperties: false` under `reject`?** It emits nothing about extra keys today. Cheap alignment, but it changes rendered output for existing consumers. — *Owner: Jesus*
- [ ] **Retention.** Anonymous caller-controlled JSON in a public-form column invites a purge/TTL story. Out of scope for v1, or a stated non-goal? — *Owner: Jesus*
