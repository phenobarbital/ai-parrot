---
type: Wiki Overview
title: 'Brainstorm: parrot-formdesigner Structural Refactor'
id: doc:sdd-proposals-formdesigner-refactor-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: JSON REST endpoints in the same package. As the package matured and started
  to
---

---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: parrot-formdesigner Structural Refactor

**Date**: 2026-05-07
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: B

---

## Problem Statement

`parrot-formdesigner` started as a proof of concept that bundled HTML pages and
JSON REST endpoints in the same package. As the package matured and started to
be embedded in the `navigator` ecosystem, several design decisions that were
acceptable at POC stage now violate conventions and slow down evolution:

- **Eager top-level imports**: `src/parrot_formdesigner/__init__.py` (126 LoC)
  imports every renderer, extractor, tool, service and handler at module load
  time. Importing the package pulls in `aiogram`, `aiohttp`, validators, all
  three tool classes, and renderer templates whether the consumer needs them
  or not.
- **Conditional `navigator_auth` import**: `handlers/routes.py:31-35` does
  `try/except ImportError` for `navigator_auth.decorators` and falls back to
  open routes when the package is missing. The product is no longer expected
  to run unauthenticated; navigator-auth's own `noauth` backend covers the
  dev-mode escape hatch.
- **Per-format URLs**: `/api/v1/forms/{form_id}/html` is hard-coded
  (`handlers/routes.py:153`), and adding XML or PDF would mean adding a new
  route per format. There is no content negotiation and no single render
  dispatcher.
- **No toolbar API**: `tools/field_helpers.py` already has
  `list_supported_form_field_types()` and `get_form_field_schema_snippets()`,
  but they are only callable from Python — there is no REST helper a UI
  toolbar could consume to populate a control palette with metadata.
- **Missing renderers**: no XML output (XForms / XFA) and no PDF output
  (AcroForm-fillable). Both are real requirements for the form-designer use
  case (interoperability + offline form filling).
- **No granular edit API**: forms are edited via `PUT` (full replace) or
  `PATCH` with RFC 7396 merge semantics (`handlers/api.py:468-517`). There
  is no way to express atomic "move field", "add section", "duplicate
  field" operations from the UI without re-sending the whole form, and merge-
  patch on arrays replaces the whole list — fragile against concurrent
  edits.
- **HTML pages mixed with REST**: `FormPageHandler`, `templates.py`
  (457 LoC of inline HTML) and `TelegramWebAppHandler` live next to the
  pure JSON API in the same `handlers/` directory.

Affected: navigator-api consumers embedding the package, the form-designer UI
team that needs a stable control palette + edit API, and downstream agents
(MS Teams, Telegram) that need format negotiation per channel.

## Constraints & Requirements

- **No backwards compatibility**: the package is still in `0.1.x`; consumers
  are internal and can be migrated alongside. Breaking the public surface is
  allowed.
- **async-first** per `CLAUDE.md` / `.agent/CONTEXT.md`.
- **`navigator-auth` becomes a HARD dependency**. The conditional import is
  removed. Dev-mode unauthenticated runs are delegated to navigator-auth's
  `NoAuth` backend on the consumer side.
- **`__init__.py` must not eager-import submodules.** Public surface is
  reduced to `__version__` + metadata; consumers import from submodules.
- **Path-param render dispatcher** for presentation formats:
  `GET /api/v1/forms/{form_id}/render/{format}`. `/schema` and `/style`
  remain dedicated routes (they return contract artifacts, not visual
  renders).
- **XForms (W3C) export only in V1** — no round-trip import. XFA is out of
  V1 scope.
- **PDF rendering uses `reportlab` AcroForm** (already installed: 4.1.0)
  — interactive fillable PDFs from `FormSchema` directly, no HTML→PDF
  pipeline.
- **PATCH `/operations` is transactional**: all-or-nothing; if any operation
  fails (validation, missing target), the form is left untouched.
- **HTML / Telegram UI lives in `parrot_formdesigner.ui`**, REST in
  `parrot_formdesigner.api`. Same wheel, different sub-packages.
- **Form controls registry is extensible** — new control types can be
  registered with metadata (icon, category, snippet, render hints).

---

## Options Explored

### Option A: Big-bang Refactor

Re-organize the package and ship every new capability (render dispatcher,
controls registry, XForms, PDF, operations PATCH) in a single coordinated
release. Vacate `__init__.py`, split `api/` vs `ui/`, switch `navigator_auth`
to a hard dependency, all in one pass.

✅ **Pros:**
- Single coherent release — no transient incoherent state.
- One migration window for downstream consumers.
- All new capabilities ship together so the UI team can adopt the new model
  in one go.

❌ **Cons:**
- Very large change set; review fatigue and high integration risk.
- All sub-features become serially blocking — worker can't parallelize.
- A defect in one capability holds up the whole release.

📊 **Effort:** High (single concentrated effort)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `lxml` | XForms XML emission | already installed (6.1.0) |
| `reportlab` | PDF AcroForm generation | already installed (4.1.0) |
| `navigator-auth` | session auth (hard dep) | already used optionally; promote to required |
| `pydantic` | operation envelope models | already a hard dep (>=2.0) |

🔗 **Existing Code to Reuse:**
- `handlers/api.py:108-679` — current `FormAPIHandler` methods become the
  basis for `parrot_formdesigner.api.handlers`.
- `handlers/routes.py:82-164` — split into `setup_form_api()` and
  `setup_form_ui()`.
- `tools/field_helpers.py:152-164` — controls registry source-of-truth seed.
- `renderers/base.py:14-46` — `AbstractFormRenderer` extended for XML / PDF.

---

### Option B: Layered Refactor — Skeleton First, Capabilities In Waves

Two SDD waves on the same `dev` base branch (and worktrees of their own):

**Wave 1 — Skeleton & policy (blocking, single worktree):**
1. Split `parrot_formdesigner.api` and `parrot_formdesigner.ui`.
2. Empty `__init__.py` (only `__version__`, package metadata).
3. Promote `navigator_auth` to a hard dependency; remove the
   `try/except ImportError` block in `handlers/routes.py`.
4. Introduce the render dispatcher route shape
   `/api/v1/forms/{form_id}/render/{format}` (initially backed by existing
   `html` + `adaptive` renderers; XML / PDF return `415 Unsupported Media`).
5. Define the abstract registry for form controls (no new control types
   yet — the existing `FieldType` enum is the seed).

**Wave 2 — Independent capability tasks (parallelizable in worktrees):**
- 2a. **XForms exporter** (`renderers/xforms.py` — new). Plugged into the
  render dispatcher.
- 2b. **PDF AcroForm renderer** (`renderers/pdf.py` — new). Plugged into
  the render dispatcher.
- 2c. **Form controls REST endpoint** (`/api/v1/form-controls`) backed by
  the registry from Wave 1, returning the agreed metadata shape.
- 2d. **Edit operations API** (`PATCH /api/v1/forms/{form_id}/operations`)
  — atomic, transactional, domain-level operations
  (`add_section`, `move_field`, etc.).

✅ **Pros:**
- Wave 1 is small, mechanically reviewable, and unblocks every other task.
- Wave 2 tasks are independent — can run in parallel worktrees.
- Each wave delivers reviewable value; revert/rollback is per capability.
- Lower risk of "everything breaks at once".

❌ **Cons:**
- Transient incoherence: between Wave 1 and Wave 2, the render dispatcher
  exists but only serves `html` + `adaptive`. Documented and time-boxed.
- More PRs to coordinate (2 waves + 4 sub-features).
- Sequencing discipline required — Wave 2 cannot start before Wave 1 lands.

📊 **Effort:** High overall, but distributed and parallelizable

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `lxml` | XForms emission with namespaces | already installed (6.1.0) |
| `reportlab` | PDF AcroForm canvas | already installed (4.1.0) |
| `navigator-auth` | session auth (hard dep) | already used; promote to required |
| `pydantic` | operation envelope + plugin metadata models | already a hard dep |

🔗 **Existing Code to Reuse:**
- `core/schema.py:108-137` — `FormSchema` is unchanged; refactor is purely
  around it.
- `core/types.py:16-39` — `FieldType` enum becomes the seed of the controls
  registry (extension via `register_field_control(...)` decorator).
- `handlers/api.py:31-679` — methods migrate to `api/handlers.py`; the
  `_deep_merge`, `_loc_to_str`, `_bump_version` helpers move to
  `api/_utils.py`.
- `handlers/routes.py:82-164` — split into `api/routes.py` (REST routes
  with hard-imported `is_authenticated` + `user_session`) and
  `ui/routes.py` (HTML + Telegram routes, opt-in).
- `tools/field_helpers.py:16-164` — provides the initial snippet payload
  for the controls registry.
- `renderers/base.py:14-46` — `AbstractFormRenderer` extended by
  `XFormsRenderer`, `PdfRenderer`.
- `services/registry.py:105-371` — `FormRegistry` API stays; only callers
  move (no model changes).
- `services/validators.py:446-510` — `FormValidator.check_schema()` reused
  to validate the post-operation form before commit.

---

### Option C: Plugin / Extension Architecture First

Recast the entire package around three explicit plugin layers before
shipping any feature:

- **`FieldControlPlugin`** (entry-point + decorator) — every field type is
  a plugin contributing snippet, icon, category, render hints, allowed
  constraints.
- **`RendererPlugin`** — every output format (`html`, `xml`, `pdf`,
  `adaptive`, ...) is a plugin discovered by the render dispatcher.
- **`EditOperationPlugin`** — every domain operation
  (`add_section`, `move_field`, ...) is a handler the PATCH endpoint
  dispatches to.

Discovery via `importlib.metadata` entry points (`parrot_formdesigner.field_controls`,
`parrot_formdesigner.renderers`, `parrot_formdesigner.operations`),
fallback to in-package registration with a decorator.

✅ **Pros:**
- Real third-party extensibility from day one.
- Maximum architectural cohesion — every new control / renderer / operation
  follows the same registration contract.
- Easy to evolve in the future (e.g., XFA renderer ships as its own wheel).

❌ **Cons:**
- Significant over-engineering for V1 — there are no third-party
  consumers yet asking for plugin extensibility.
- Bootstrapping cost: entry-point manifests, plugin lifecycles, isolation,
  registration ordering, conflict resolution all need to be designed and
  tested before any user-visible feature ships.
- High risk that the abstraction is wrong before we have the experience to
  shape it.
- Competes with effort that should go to the actual missing capabilities
  (XForms, PDF, operations).

📊 **Effort:** Very High — meta-architecture before features

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `importlib.metadata` | entry-point discovery | stdlib (Python 3.10+) |
| `lxml` | XForms emission | already installed |
| `reportlab` | PDF AcroForm | already installed |
| `pydantic` | plugin contract validation | already a hard dep |

🔗 **Existing Code to Reuse:**
- `renderers/__init__.py:10-22` — current renderer registration becomes
  three entry-points exposed by the package itself.
- `tools/field_helpers.py` — moved into the field-control plugin contract.

---

## Recommendation

**Option B** is recommended.

It delivers the same end state as Option A but in a sequence that:

1. **De-risks the rest of the work** — Wave 1's mechanical changes
   (package split, lazy imports, hard auth dep, dispatcher route) are easy
   to review in isolation, and once they land everything else can move in
   parallel. Option A bundles all of that into one fragile PR.
2. **Unlocks parallelism** for Wave 2 — XForms, PDF, controls REST and
   operations PATCH are genuinely independent capabilities that don't share
   files (different renderer modules, separate route handlers). One per
   worktree, no coordination tax.
3. **Avoids the over-engineering trap of Option C** — we don't need a
   plugin runtime today. The registry pattern (`register_field_control`,
   `register_renderer`, `register_operation`) introduced in Wave 1 is
   already extensible enough for in-tree growth, and we can promote it to
   entry-point-based discovery later if a real third-party need shows up.

Tradeoff accepted: a transient window between Wave 1 and Wave 2 where
`/render/xml` and `/render/pdf` return `415`. Documented in the spec and
covered by a test that asserts the supported-formats list matches what the
dispatcher actually serves.

---

## Feature Description

### User-Facing Behavior

- A consumer of the package installs `parrot-formdesigner` and gets a
  package whose top-level import is **cheap** — just metadata. They import
  what they use:
  `from parrot_formdesigner.core import FormSchema`,
  `from parrot_formdesigner.api import setup_form_api`.
- A navigator-api host calls `setup_form_api(app, registry=...)` to mount
  the REST surface. They optionally call `setup_form_ui(app, ...)` to mount
  the form-designer HTML pages and Telegram WebApp.
- An authenticated UI client lists supported controls via
  `GET /api/v1/form-controls` and gets a JSON array of objects, one per
  control, including `type`, `label`, `description`, `category`, `icon`,
  `snippet`, `render_hint`, `supports_constraints`, `is_container`. The
  shape is suitable for populating a drag-and-drop toolbar.
- The UI client renders a form to the channel it needs:
  `GET /api/v1/forms/{id}/render/html`,
  `GET /api/v1/forms/{id}/render/xml` (XForms),
  `GET /api/v1/forms/{id}/render/pdf` (download a fillable PDF),
  `GET /api/v1/forms/{id}/render/adaptive` (Adaptive Card JSON for Teams).
  An unsupported format returns `415` with the supported list in the body.
- The form designer UI sends batched edits via
  `PATCH /api/v1/forms/{id}/operations` with a JSON envelope
  `{"operations": [...]}`. Either every operation applies and the form
  version bumps, or none do and the response is `409 Conflict` /
  `422 Unprocessable Entity` with per-operation errors.
- `/api/v1/forms/{id}/schema` and `/api/v1/forms/{id}/style` keep their
  current semantics (JSON Schema served, StyleSchema + layout) — they are
  contract endpoints, not render formats.
- All REST endpoints require a navigator-auth session (no fallback open
  mode). Hosts that need dev-mode unauthenticated access configure the
  `NoAuth` backend on the navigator-auth side.

### Internal Behavior

**Package layout (post-refactor):**

```
src/parrot_formdesigner/
├── __init__.py              # only __version__ + metadata. NO submodule imports.
├── core/                    # unchanged — FormSchema, types, constraints, options, style, auth
├── extractors/              # unchanged — pydantic, yaml, jsonschema, tool
├── services/                # unchanged — registry, storage, validators, cache, submissions, forwarder
├── tools/                   # unchanged — Python tools (CreateFormTool, DatabaseFormTool, RequestFormTool, field_helpers)
├── renderers/               # extended: existing html5/jsonschema/adaptive_card/telegram + new xforms.py + new pdf.py
├── controls/                # NEW — registry of form-control plugins + metadata
│   ├── registry.py          # register_field_control(), get_controls(), iter_controls()
│   └── builtin.py           # registers every FieldType with default metadata + render_hint
├── api/                     # NEW — REST handlers, no HTML
│   ├── handlers.py          # FormAPIHandler (split from current handlers/api.py)
│   ├── operations.py        # PatchOperationsHandler — atomic batch domain ops
│   ├── controls.py          # GET /api/v1/form-controls
│   ├── render.py            # render dispatcher (path param /render/{format})
│   ├── routes.py            # setup_form_api(); HARD imports navigator_auth decorators
│   └── _utils.py            # _bump_version, _loc_to_str helpers
└── ui/                      # NEW — HTML pages + Telegram WebApp (opt-in)
    ├── handlers.py          # FormPageHandler (ex-handlers/forms.py)
    ├── telegram.py          # TelegramWebAppHandler (ex-handlers/telegram.py)
    ├── templates.py         # ex-handlers/templates.py
    └── routes.py            # setup_form_ui()
```

**Render dispatcher (`api/render.py`):**

A small dispatcher keeps a `dict[str, AbstractFormRenderer]` keyed by
format name (`html`, `adaptive`, `xml`, `pdf`, ...). The route
`/api/v1/forms/{form_id}/render/{format}` looks up the format,
delegates to the renderer's `async render()` method, and returns the
`RenderedForm.content` with the correct `Content-Type`. Unknown formats
return `415` with `{"supported": ["html", "adaptive", "xml", "pdf"]}`.

**Controls registry (`controls/`):**

`register_field_control(field_type: FieldType | str, *, label, description,
category, icon, snippet, render_hint, supports_constraints,
is_container=False)` adds an entry to a module-level dict.
`controls/builtin.py` calls it once per `FieldType` value at import time
(seeded from `tools/field_helpers._FIELD_SCHEMA_SNIPPETS`).
`GET /api/v1/form-controls` returns `{"controls": [<entry>, ...]}`.

**Edit operations PATCH (`api/operations.py`):**

```jsonc
PATCH /api/v1/forms/{form_id}/operations
Body: {
  "operations": [
    {"op": "add_section", "section": {...}, "position": 0},
    {"op": "add_field", "section_id": "personal", "field": {...}, "position": 0},
    {"op": "move_field", "from": {"section_id": "personal", "field_id": "email"}, "to": {"section_id": "contact", "position": 0}},
    {"op": "remove_field", "section_id": "contact", "field_id": "old_phone"},
    {"op": "update_field", "section_id": "personal", "field_id": "email", "patch": {"required": true}},
    {"op": "update_section_meta", "section_id": "personal", "patch": {"title": "Personal info"}},
    {"op": "update_form_meta", "patch": {"title": {"en": "Onboarding"}}},
    {"op": "duplicate_field", "from": {"section_id": "personal", "field_id": "phone"}, "as_field_id": "phone_2"}
  ]
}
```

Algorithm:

1. Validate the operations envelope with a Pydantic discriminated union
   (`Operation = AddSection | AddField | MoveField | ... `).
2. Take a snapshot of the current `FormSchema` from the registry.
3. Apply each operation **in-memory** to a working copy. If any operation
   fails (target not found, would create duplicate `field_id`, etc.),
   abort and return `422` with `{"errors": [{"index": i, "op": op_name,
   "message": ...}]}`.
4. Run `FormValidator.check_schema(working_copy)` after the last
   operation; if structural errors (e.g., circular dep) appear, abort with
   `422`.
5. Bump version (`_bump_version`), call
   `registry.register(working_copy, persist=True, overwrite=True)`,
   return the new full `FormSchema`.

Optional optimistic concurrency: if `If-Match: <version>` header is sent
and doesn't match the current version, return `412 Precondition Failed`.

**XForms renderer (`renderers/xforms.py`):**

Maps `FormSchema` → XForms 1.1 (W3C) using `lxml`. Each `FormSection`
becomes an `<xf:group>`, each `FormField` becomes the appropriate XForms
control (`<xf:input>`, `<xf:select1>`, `<xf:upload>`, etc.) with bind
expressions for required/constraints. Returns `RenderedForm(content=<xml-bytes>,
content_type="application/xml")`. V1 is export-only; no XForms parser.

**PDF AcroForm renderer (`renderers/pdf.py`):**

Uses `reportlab.pdfgen.canvas.Canvas` + `canvas.acroForm` to emit a
fillable PDF. Layout: vertical single-column with a section header per
`FormSection` and a label-above-input block per `FormField`. Field type
mapping: `text/email/url/phone/password → textfield`, `number/integer →
textfield (number)`, `boolean → checkbox`, `select → choice`,
`multi_select → listbox`, `date → textfield (with format hint)`,
`hidden → hidden field`, `file/image → text annotation` (PDF AcroForm
doesn't support file upload natively). Returns
`RenderedForm(content=<pdf-bytes>, content_type="application/pdf")`.

### Edge Cases & Error Handling

- **`/render/{format}` for an unsupported format** → `415` with the
  supported list.
- **PATCH operations targeting a missing section/field** → `422` with the
  index of the offending operation; the form is unchanged.
- **PATCH operation that would duplicate `field_id` within a section** →
  `422`. (Note: `field_id` is unique within section per `FormSchema`
  conventions; the validator must check this.)
- **PATCH operation that would create a circular `depends_on`** → caught
  by `FormValidator.check_schema()` at step 4; `422`.
- **`If-Match` mismatch** → `412 Precondition Failed`.
- **Concurrent PATCH on the same form** → second writer either gets
  `412` (if it sent `If-Match`) or wins last-write (if not). Atomicity is
  per-request, not cross-request.
- **`navigator_auth` import failure at startup** (no longer caught) →
  package fails to import. This is the desired behavior post-refactor —
  navigator-auth is a hard dep declared in `pyproject.toml`.
- **`reportlab` / `lxml` missing** → since both are already installed in
  the venv and used elsewhere in `ai-parrot`, they become hard deps in
  `parrot-formdesigner/pyproject.toml`. No optional-extras for V1.
- **Telegram WebApp routes** (`/forms/{id}/telegram` and the REST
  fallback) are public by design — those move to `ui/` but keep their
  unauthenticated registration so Telegram can hit them.
- **HTML page routes** (`/`, `/gallery`, `/forms/{id}`,
  `/forms/{id}/schema`, `/forms/{id}` POST) move to `ui/` and keep their
  optional `_page_wrap` auth based on `protect_pages=`.

---

## Capabilities

### New Capabilities

- `formdesigner-package-restructure`: Split `parrot_formdesigner` into
  `core/`, `services/`, `extractors/`, `tools/`, `renderers/`,
  `controls/`, `api/`, `ui/`. Empty `__init__.py`. (Wave 1)
- `formdesigner-auth-hard-dep`: Promote `navigator-auth` to a required
  dependency; remove the conditional import in `routes.py`. (Wave 1)
- `formdesigner-render-dispatcher`: Add path-param render route
  `/api/v1/forms/{form_id}/render/{format}` and dispatcher logic; keep
  `/schema` and `/style` as dedicated routes. (Wave 1)
- `formdesigner-controls-registry`: Add `controls/registry.py` and
  `GET /api/v1/form-controls` returning the agreed metadata shape.
  (Wave 2)
- `formdesigner-xforms-renderer`: New `renderers/xforms.py` (W3C XForms
  1.1 export only) plugged into the render dispatcher. (Wave 2)
- `formdesigner-pdf-renderer`: New `renderers/pdf.py` (reportlab AcroForm
  fillable PDF) plugged into the render dispatcher. (Wave 2)
- `formdesigner-edit-operations`: New `PATCH /api/v1/forms/{id}/operations`
  endpoint with a Pydantic-discriminated operations envelope, atomic
  transactional semantics, optional `If-Match` concurrency control.
  (Wave 2)

### Modified Capabilities

- `formdesigner-package` — current package shell is restructured.
- `formdesigner-package-fixes` — superseded by Wave 1.
- `formdesigner-authentication` — hard dep replaces conditional import.
- `form-designer-edition` — current PUT/PATCH edit endpoints coexist with
  the new operations endpoint; PATCH semantics (RFC 7396 merge) remain
  available for whole-form patches but the recommended path becomes
  `/operations` for granular UI edits.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot_formdesigner/__init__.py` | rewrites | empties to metadata only |
| `parrot_formdesigner/handlers/` | removes (folder) | content split into `api/` and `ui/` |
| `parrot_formdesigner/api/` | new | REST surface, hard-imports `navigator_auth` |
| `parrot_formdesigner/ui/` | new | HTML pages + Telegram WebApp, opt-in |
| `parrot_formdesigner/controls/` | new | controls registry + builtin seed |
| `parrot_formdesigner/renderers/xforms.py` | new | XForms 1.1 export |
| `parrot_formdesigner/renderers/pdf.py` | new | reportlab AcroForm |
| `parrot_formdesigner/pyproject.toml` | modifies | promote `navigator-auth`, `lxml`, `reportlab` to hard deps |

…(truncated)…
