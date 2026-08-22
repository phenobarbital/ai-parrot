---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Reconcile the Field-Type Catalog with the Client

**Feature ID**: FEAT-448 (parrot)
**Date**: 2026-08-22
**Author**: Juan Franco (spec drafted with Claude Code)
**Status**: draft
**Pairs with**: navigator-svelte **FEAT-515** — the client half. Both ship
together; that rule is the one this whole situation broke.

> Supersedes the unpushed draft `location-field-contract-reconciliation.spec.md`,
> which carried a phantom FEAT-515 (a fieldsync-space number on a parrot spec)
> and scoped only `location`. Its analysis is folded in below.

---

## 1. Motivation

### One commit forked the catalog

```
1f457202  mendozajoser  2026-05-12
"feat: extend FieldType with new options and update FormDesignerConsole layout"
spec: navigator-svelte sdd/specs/formbuilder-field-library-extended.spec.md
task: TASK-383-fb-multivalue-selection-fields
```

That commit declared twelve new `FieldType` values on the client, each with a
value shape set out in a table, and built their controls. It is a good spec for
what it set out to do. It **mentions parrot zero times** — the server's enum and
its validator were never consulted.

Everything below is the bill for that.

### The measured state, 2026-08-22

| | count |
|---|---|
| parrot `FieldType` enum | 33 |
| navigator-svelte `FieldType` union | 37 |
| present in both | 26 |
| client-only | 11 |
| parrot-only | 7 |

### Two failure modes, and they are not symmetric

**Client-only → parrot cannot parse the FORM, not the field.**
`FormField.field_type: FieldType` is a strict enum, so an unknown value raises
`ValidationError` for the whole `FormSchema`. Verified for all eleven:

```
ai_capture  color_picker  credit_card  cron          emoji
image_dropzone  masked    multi_upload  search       signature_pad
tree_select
```

Latent today, and only by luck: a census of every stored `field_type` across
the `epson`, `flexroc`, `pokemon` and `navigator` schemas finds none of them.
The live palette comes from parrot's own `/api/v1/form-controls`
(`controls/builtin.py`), and the hardcoded list in `FormDesignerConsole.svelte`
is a fallback reached only when that call fails. One failed request away.

**Parrot-only → the client silently renders a text box.**
`normalizeFieldType` coerces anything outside `KNOWN_FIELD_TYPES` to `'text'`,
and none of the seven has a registered control:

```
audio  availability  dynamic_select  likert  nps  ranking  remote_response
```

**This one is not latent.** Eight stored fields are affected today, and one of
them is a real form: flexroc's `customer-satisfaction-survey` v1.0 carries a
configured `likert` (*"Overall, how satisfied are you with our service?"*,
`scale_min: 1`, `scale_max: 5`, `anchor_labels: {"1": "Very Dissatisfied",
"5": "Very Satisfied"}`) and a configured `nps` (0–10). Both render as plain
text inputs. The anchor labels and the scales are sitting in the schema,
unread.

The remainder are designer placeholders: one `ranking` and one `nps` in
`untitled-form-2`, and four `remote_response` rows that are really **two**
fields (one across three versions of navigator's `employee-onboarding-form`),
**all four with no `meta` at all** — no endpoint, no `RemoteResponseSpec`.

### Two shared types whose VALUE shapes disagree

`location` and `signature` exist on both sides and mean different things. Both
are settled in §3.

---

## 2. Direction (Juan, 2026-08-22)

**Extend both catalogs. Retire nothing.** Every type that exists on either side
survives; the union becomes the catalog on both sides. Where a name carries two
meanings, the richer meaning gets its own name rather than displacing the
simpler one.

|  | parrot | svelte |
|---|---|---|
| shared today | 26 | 26 |
| absorbs from the other side | +11 | +7 |
| `place` (new) | +1 | +1 |
| **total** | **45** | **45** |

---

## 3. The two shape disagreements

### `location` — parrot keeps it, the granular one becomes `place`

parrot's `LOCATION` is not one validator branch; it is a country picker wired
through eleven sites — `_location_data.py` (pycountry, flag emoji, dial codes),
the coercion `str(value).strip().upper()`, the 2-char check, the registry entry
*"Country or location selector using ISO codes"*, a `field_helpers` snippet
whose `field_id` is literally `country_code`, `format: "iso-country"` in JSON
Schema, and six renderers that each paint a country list.

The client's `location` is a Country → State → City cascade over the
`country-state-city` package, value `{country, state, city}`.

**Neither is wrong and neither displaces the other.** `LOCATION` stays exactly
what its reference data says it is. The cascade becomes a new type:

```
PLACE = "place"     value: {"country": str, "state": str | None, "city": str | None}
```

`place`, not `address`: there is no street line and no postal code, so
`address` would misdescribe it. `country` inside a `place` delegates to
`is_valid_iso_country_code`, so the two types agree on their common field.

Measured exposure of the disagreement, so the size is on the record: **one
field, in one form** — `untitled-form-2` / "ML Test #1", which looks like eight
only because that form has eight versions. Two stored submissions hold
`{"country":"CA","state":"ON","city":"Ottawa"}`. The NetworkNinja importer
never emits `LOCATION` (no reference to the type in `networkninja.py`).

### `signature` — parrot adopts the client's shape

| | |
|---|---|
| parrot declares | `{"svg": str, "png": str}`, both keys required (`validators.py:478`) |
| the client emits | `canvasEl.toDataURL('image/png')` — a string (`signature-field.svelte:123`, `signature-pad-field.svelte:156`) |

On paper parrot's is richer: a vector scales, re-renders at print DPI, and
weighs kilobytes instead of hundreds of KB of base64.

**In practice nobody produces the SVG and nothing reads either half:**

- Both client controls draw straight to `<canvas>` and retain only
  `lastX`/`lastY` — no stroke paths, so they could not emit SVG if asked.
- parrot's own html5 renderer emits `<canvas data-signature="true">` plus two
  hidden inputs `_svg` and `_png`, and ships no script to fill them
  (`html5.py:794`).
- The PDF renderer lists `SIGNATURE` in `_PDF_FALLBACK_NEW_TYPES` — a
  placeholder textfield, not an image.
- A search of the monorepo for any read of `["svg"]` or `["png"]` returns
  nothing outside tests.

So `{svg, png}` is declared in the validator and the JSON Schema and has zero
producers and zero consumers. **`SIGNATURE` becomes a PNG data-URL string.**
By the same rule §3 applies to `location`: a vector signature is a *different
type* to be named when someone needs one, not an existing type widened. You
cannot preserve the richer option when the richer option was never built.

This is the more urgent of the two. parrot's NN importer maps
`FIELD_SIGNATURE_CAPTURE → FieldType.SIGNATURE` (FEAT-300), and flexroc's
imported `db-form-7-74` has `field_8770` as a **required** signature. Nothing
has been signed yet and the execution path does not validate — so it is latent
exactly until fieldsync FEAT-513 turns validation on, which is the thing that
would expose it.

---

## 4. The eleven types parrot absorbs

Value shapes read from the controls, not from the client spec's table (two of
them are undocumented there). Each needs an enum value, a validator branch and
a registry entry.

| type | value the control emits | verified at |
|---|---|---|
| `search` | `string \| null` — the chosen option's value | `search-field.svelte:133` |
| `masked` | `string` (raw or masked, per config) | `masked-field.svelte` |
| `color_picker` | `string` — lowercase hex | `color-picker-field.svelte` |
| `emoji` | `string \| null` — one emoji | `emoji-field.svelte` |
| `cron` | `string` — a 5-part expression | `cron-field.svelte` |
| `tree_select` | `string[] \| null` (multi); single yields the node value | `tree-select-field.svelte` |
| `signature_pad` | `string \| null` — PNG data URL | `signature-pad-field.svelte:156` |
| `credit_card` | `{number, name, expiry, cvv}` — all strings | `credit-card-field.svelte:23` |
| `image_dropzone` | `{name,type,size,dataUrl}` or an array of them | `image-dropzone-field.svelte:43` |
| `multi_upload` | `Array<{answer, blob_ref, display}>` | `multi-upload-field.svelte:162` |
| `ai_capture` | the capture API's JSON response, unconstrained | `ai-capture-field.svelte:158` |

### Three that need a decision, not just a branch

**`credit_card` carries `cvv`.** The control emits it and a form submission
would persist it in `data` jsonb. Storing a CVV after authorization is
prohibited by PCI DSS, and nothing here is doing an authorization. Absorbing
this type as-is writes card verification values into `fs_form_data`. Options:
adopt the type but drop `cvv` at the boundary; adopt it and never persist;
or adopt the shape and mark the field type unusable outside a PCI scope. **This
must be answered before the branch is written** — it is the one item in this
feature that is a liability rather than a gap.

**`image_dropzone` emits inline base64.** A `dataUrl` per file in the
submission payload is the wrong carrier at any real photo count, and the
platform already has the right one (`blob_ref`). Absorb the type so schemas
parse; the carrier is fieldsync **FEAT-514**'s problem and must not be
pre-empted here.

**`multi_upload` is already the answer FEAT-514 is looking for.** It emits a
LIST of REST envelopes `{answer, blob_ref, display}` while
`_validate_rest_field` accepts a singular `{answer, blob_ref, status?}`. That
is the whole of FEAT-514's blocker, already built on the client. Absorbing the
type here is a precondition for that feature, not a substitute for it.

### Renderers are not eleven times seven

Adding a type to the enum does **not** oblige a native renderer in each of the
seven. Every renderer already has a documented, precedented fallback posture:
`xforms` maps unsupported types to plain text with an explicit `# fallback`
comment; `adaptive_card` has a fallback branch covering `SIGNATURE`,
`REMOTE_RESPONSE` and `AVAILABILITY`; `pdf` has `_PDF_FALLBACK_NEW_TYPES`
(placeholder textfields); `audio` and `telegram` carry explicit unsupported
sets.

What is mandatory per type is enum + validator + registry. The renderer work is
to **choose a posture per type and record it**, with "fallback" a legitimate
answer. A native renderer only where the type is genuinely used in that channel.

---

## 5. Scope

1. Eleven enum values, eleven validator branches, eleven registry entries in
   `controls/builtin.py` (which is what `/api/v1/form-controls` serves, so the
   client palette follows automatically).
2. `PLACE`, with `country` delegating to `is_valid_iso_country_code`.
3. `SIGNATURE` relaxed to a PNG data-URL string.
4. A renderer posture recorded for each of the twelve new types.
5. A shared fixture the client half asserts against, so the two catalogs cannot
   drift again silently.

### Non-Goals

- **Retiring anything.** Explicit direction.
- **The client's seven.** navigator-svelte FEAT-515.
- **The multi-photo carrier.** fieldsync FEAT-514.
- **Rule enforcement.** fieldsync FEAT-513.
- **A vector signature type.** Named if and when someone needs one.
- **Giving `list_country_options()` a consumer.** Noted in §8.

---

## 6. Acceptance Criteria

- **AC1** A `FormSchema` containing any of the eleven types parses. Asserted
  type by type, since today every one of them fails the whole schema.
- **AC2** A value produced by each client control validates on the server.
- **AC3** `LOCATION` behaviour is byte-identical to today — the country picker
  is untouched. Asserted, not assumed.
- **AC4** `PLACE` accepts `{country, state, city}` and rejects an invalid
  country code.
- **AC5** `SIGNATURE` accepts a PNG data-URL string; the two-key dict is no
  longer required.
- **AC6** Every new type has a recorded renderer posture in all seven
  renderers, native or fallback, and none raises.
- **AC7** A test enumerates both catalogs and fails if they diverge — the
  ratchet this feature exists to install.
- **AC8** The `cvv` decision is implemented, whichever way it went, and the
  test states which.

---

## 7. Codebase Contract

### Verified 2026-08-22

```
core/types.py                   FieldType, 33 values, strict on FormField
core/_location_data.py          is_valid_iso_country_code / get_country_info /
                                list_country_options — the last has NO
                                production caller; the renderers each
                                `import pycountry` inline instead
services/validators.py:428,478  SIGNATURE requires a {svg, png} dict
services/validators.py:425,519  LOCATION coerces .upper() and demands 2 chars
services/validators.py:601      RemoteResponseResolver is instantiated HERE and
                                nowhere else — REMOTE_RESPONSE resolution runs
                                only on a path that calls FormValidator
controls/builtin.py:367         the LOCATION registry entry both repos read
api/controls.py                 GET /api/v1/form-controls — the palette source
tools/services/networkninja.py  no LOCATION mapping; FIELD_SIGNATURE_CAPTURE
                                -> SIGNATURE (FEAT-300)
renderers/{xforms,adaptive_card,pdf,audio,telegram}
                                existing fallback / unsupported postures
```

### On `REMOTE_RESPONSE` vs `REST` — they are peers

Recorded because the opposite was assumed while drafting this and it was wrong.
`sdd/proposals/new-formdesigner-field-rest.brainstorm.md` (jesuslara,
2026-05-14): *"This is a peer of `REMOTE_RESPONSE` (display) and `FILE`/`IMAGE`
(raw upload), not a replacement for either."* `REMOTE_RESPONSE` is read-only
and display-oriented; `REST` is an active uploader whose answer is the
processed response. The client half builds both.

---

## 8. Follow-ups, not in scope

**One canonical country list.** `list_country_options()` was written to serve
exactly this and has no production caller: `html5`, `adaptive_card` and
`xforms` each `import pycountry` inline with their own ordering and their own
fallback list. If the client's country select sources its options from
`country-state-city` (already a dependency), that becomes a fourth list. Small,
real, and separable.

---

## 9. Risks

- **Shipping one side.** The two repos release independently. Shipping half of
  this reproduces the original defect with a new set of names.
- **Absorbing `credit_card` without answering the `cvv` question**, and
  discovering later that card verification values are sitting in
  `fs_form_data`. AC8 exists for this.
- **Letting "fallback" become the answer everywhere.** It is legitimate per
  type and negligent as a blanket. AC6 requires a recorded choice, not a
  default.
- **Treating the census as proof of safety.** "No client-only type is stored"
  is true today and holds only while `/api/v1/form-controls` keeps answering.
  The hardcoded fallback palette is one failed request from writing an
  unparseable schema.
