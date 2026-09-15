# A2UI v1.0 Form Renderer (FEAT-544)

## Overview

`A2UIFormRenderer` lowers a `FormSchema` into a single A2UI v1.0
`createSurface` envelope composed exclusively of [Basic Catalog][a2ui-v1]
primitives — no `Form` catalog component exists (A2UI dialect spec G6: a
form is a composition, never a registered component). The whole
render → validate → submit → response cycle runs over A2UI envelopes: the
surface's own submit `Button` points back at the form's existing
`POST /data` endpoint, which is **dual-wire** — it accepts both the legacy
field_id-keyed JSON body and a v1.0 renderer→agent `action` envelope, and
replies in kind.

[a2ui-v1]: ../../../docs/outputs/a2ui-v1.md

## Installing

`ai-parrot` (and therefore `parrot.outputs.a2ui`) is an OPTIONAL dependency
of parrot-formdesigner. Install it via either extra (same pin, `a2ui` is an
alias chosen for discoverability):

```bash
pip install "parrot-formdesigner[a2ui]"
# or, equivalently:
pip install "parrot-formdesigner[ai-parrot]"
```

Without the extra, `parrot_formdesigner.api` still imports cleanly —
`"a2ui"` is simply absent from `supported_formats()`, and the render
dispatcher logs one INFO line explaining why.

## Usage

### Rendering a surface

```
GET /api/v1/{tenant}/forms/{form_uid}/render/a2ui
```

Returns `200 application/a2ui+json` — a `createSurface` envelope any
v1.0-compliant A2UI renderer can fill and submit.

Directly, from Python:

```python
from parrot_formdesigner.renderers.a2ui import A2UIFormRenderer

renderer = A2UIFormRenderer()
rendered = await renderer.render(
    form,
    locale="en",
    prefilled={"name": "Ada"},   # optional: field_id -> value, wins over default
    errors={"email": "Already taken."},  # optional: field_id -> message
)
rendered.content        # {"version": "v1.0", "createSurface": {...}}
rendered.content_type   # "application/a2ui+json"
rendered.metadata        # {"surface_id", "catalog_id", "field_paths", "degraded"}
rendered.warnings        # list[RenderWarning] — one per degraded field
```

`prefilled`/`errors` are v1's Python-API-only extension point — the
`handle_render` dispatcher itself still forwards only `locale` (no query-
param widening).

### Submitting an A2UI action

The rendered surface's submit `Button.action.event` already carries
everything a compliant renderer needs:

```jsonc
{
  "name": "form.submit",
  "context": {
    "form_uid": "...", "form_id": "...", "tenant": "...",
    "submit_url": "/api/v1/{tenant}/forms/{form_uid}/data",
    "method": "POST",
    "answers": {"path": "/answers"}
  }
}
```

The renderer resolves `answers` from the surface's `dataModel` and POSTs a
v1.0 `action` envelope to `submit_url` — the SAME endpoint legacy JSON
clients already use:

```jsonc
{"version": "v1.0", "action": {
  "name": "form.submit", "surfaceId": "form-<uid>",
  "sourceComponentId": "root-submit", "timestamp": "...",
  "context": {"form_uid": "..."},
  "dataModel": {"answers": {"name": "Ada", "email": "ada@example.com"}}
}}
```

- **422** (validation failed) → one `error` envelope per invalid field
  (`code: "VALIDATION_FAILED"`, `path: "/answers/<field_id>"`), plus a
  trailing `updateDataModel{path: "/errors"}`.
- **200** (accepted) → `updateDataModel{path: "/submission", value:
  {submission_id, is_valid, forwarded, forward_status}}` plus
  `updateComponents` replacing the surface's always-present `root-status`
  `Text` with a confirmation message (`parrot_state: "submitted"`).
- A `surfaceId` mismatch or unrecognized action name → **400**, a generic
  `error` envelope; nothing is persisted.
- `POST /validate` accepts the identical wire (dry run): the same 422 shape,
  or `200 {"messages": []}` when valid.

A single reply envelope is the response body
(`Content-Type: application/a2ui+json`); several are wrapped as
`{"messages": [...]}` (`Content-Type: application/json`) — the same framing
`A2UIHandler` uses on the ai-parrot side.

Legacy field_id-keyed JSON callers are completely unaffected — dual-wire
detection is by `Content-Type: application/a2ui+json` OR a body shaped
`{"version": "v1.0", "action": {...}}`; anything else takes the original
code path, byte-identical.

## FieldType coverage

Every `FieldType` lowers to a Basic Catalog primitive, to `"hidden"`
(`dataModel`-only, no component), or degrades honestly to a `Text` notice
plus a `RenderWarning` — rendering never raises for any `FieldType`. The
table below is the `FIELD_LOWERING` module constant in
`renderers/a2ui.py`; `test_every_fieldtype_has_a_lowering_entry` asserts
`set(FIELD_LOWERING) == set(FieldType)` at import time, so a future
`FieldType` addition without an entry here fails loudly rather than
silently degrading.

| FieldType(s) | Primitive | Notes |
|---|---|---|
| `TEXT`, `SEARCH`, `MASKED`, `COLOR`, `COLOR_PICKER` | `TextField` | `variant="shortText"` |
| `TEXT_AREA` | `TextField` | `variant="longText"` |
| `NUMBER`, `INTEGER` | `TextField` | `variant="number"` |
| `PASSWORD` | `TextField` | `variant="obscured"` |
| `EMAIL` | `TextField` | `variant="shortText"`; always adds an `email` check |
| `URL`, `PHONE` | `TextField` | `variant="shortText"`; adds a `regex` check (from `constraints.pattern`, else a conservative default) |
| `BOOLEAN` | `CheckBox` | |
| `DATE` | `DateTimeInput` | `enableDate=true` |
| `TIME` | `DateTimeInput` | `enableTime=true` |
| `DATETIME` | `DateTimeInput` | `enableDate=true`, `enableTime=true` |
| `SELECT`, `DYNAMIC_SELECT` | `ChoicePicker` | `variant="mutuallyExclusive"` (static options only — dynamic sourcing is out of scope for v1) |
| `MULTI_SELECT`, `TRANSFER_LIST` | `ChoicePicker` | `variant="multipleSelection"` |
| `TAGS` | `ChoicePicker` | `variant="multipleSelection"`, `displayStyle="chips"` |
| `NPS` | `Slider` | `min=scale_min or 0`, `max=scale_max or 10` |
| `LIKERT` | `Slider` | `min=scale_min or 0`, `max=scale_max or 5` |
| `RANKING` | `Slider` | `min=scale_min or 0`, `max=scale_max or 10` |
| `HIDDEN` | — (dataModel only) | seeded in `dataModel.answers`; listed in `metadata["field_paths"]`; no component |
| `FILE`, `IMAGE`, `IMAGE_DROPZONE`, `MULTI_UPLOAD`, `SIGNATURE`, `SIGNATURE_PAD`, `AUDIO`, `AI_CAPTURE` | `Text` notice (degraded) | no A2UI v1.0 primitive for uploads/capture |
| `GROUP`, `ARRAY`, `REMOTE_RESPONSE`, `AVAILABILITY`, `LOCATION`, `PLACE`, `REST`, `FORMULA`, `EMOJI`, `CRON`, `TREE_SELECT`, `CREDIT_CARD` | `Text` notice (degraded) | GROUP/ARRAY children are NOT recursed in v1 |

`FieldConstraints` lower to `checks` using the Basic Catalog validation
functions: `required` → `required`; `pattern` → `regex` (message from
`pattern_message` when set); `min_length`/`max_length` → `length`;
`min_value`/`max_value` → `numeric`. `NPS`/`LIKERT`/`RANKING`'s
`anchor_labels` (when set) surface as the `parrot_anchor_labels` extension.

## v1 non-goals

- **Parrot-catalog form components** (FileUpload, Signature, Rating, ...) —
  the hybrid decision (U3) defers these to a follow-up feature; the types
  above degrade honestly instead.
- **Partial saves** (`/partial`), **`depends_on` conditional visibility**,
  and the **lifecycle-event bridge** (`/events/{name}`) over the A2UI wire —
  explicit v1 non-goals (U4). `/partial` and lifecycle events are unaffected
  and keep working over the legacy JSON wire.
- **Routing through `A2UIRuntime`** — the form endpoint is the sink for a
  submit action (U1); no agent/LLM turn is ever involved in a form
  submission.

## See also

- [`docs/outputs/a2ui-v1.md`](../../../docs/outputs/a2ui-v1.md) — the A2UI
  v1.0 wire reference (envelopes, catalogs, validation, degradation),
  including the "Forms from FormDesigner" section this doc expands on.
- [`lifecycle-events.md`](lifecycle-events.md) — the five lifecycle hooks
  `submit_data`/`validate` still dispatch, unchanged for A2UI callers.
- `sdd/specs/a2ui-form-output-renderer.spec.md` (FEAT-544) — the full design
  spec.
- `sdd/proposals/a2ui-form-output-renderer.proposal.md` — the accepted
  proposal (decisions U1-U4).
