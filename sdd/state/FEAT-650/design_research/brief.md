<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
parrot-formdesigner (née "formbuilder") predates ai-parrot's A2UI v1.0 support,
yet the two concepts are nearly identical: a `FormSchema` is served as a JSON
document and a frontend "renderer" turns it into HTML controls. The dialect
that is served today — `GET /forms/{uid}` returns the raw `FormSchema` dump and
`GET /forms/{uid}/schema` returns the `JsonSchemaRenderer` output with `x-*`
extensions — is **not** A2UI, so the existing A2UI renderers (admin UI,
`ssr_html`, `interactive_html`, Adaptive Cards bridge) cannot render a
FormDesigner form natively.

FEAT-544 (merged 2026-09-10, all 8 tasks `done`) already closed the first half
of the gap: `A2UIFormRenderer` lowers a `FormSchema` into a `createSurface`
envelope, `GET /forms/{uid}/render/a2ui` serves it, and `/data` + `/validate`
are dual-wire (legacy JSON **and** A2UI `action` envelopes). What is still
missing — and what this brainstorm scopes — is the **dialect layer around it**:

1. **A flag that makes the main form endpoints speak A2UI.** Today a client
   has to know about `/render/a2ui`. Consumers that fetch `/forms/{uid}` or
   `/forms/{uid}/schema` keep getting the legacy dialect with no way to opt
   in, and a form cannot declare "serve me as A2UI by default".
2. **A bulk export.** There is no way to export every form of a tenant as
   A2UI surfaces (library, API or CLI) — only one form at a time via HTTP.
3. **A translator from the legacy JSON-Schema dialect to A2UI.** Consumers
   such as Fieldsync hold the `JsonSchemaRenderer` output (with `x-field-type`,
   `x-section`, `x-options`, …), not a `FormSchema`. `JsonSchemaExtractor`
   exists but does not read `x-section`/`x-subsection`/`x-placeholder`/
   `x-read-only`, so a JSON-Schema → FormSchema → A2UI pipeline would silently
   flatten sections today.
4. **The reverse direction: A2UI surface → `FormSchema`.** Nothing exists.
   An A2UI form authored elsewhere (an agent, another A2UI producer, a
   hand-written surface) cannot become a FormDesigner form.

The legacy dialect **must not change**: Fieldsync and other consumers keep
reading `FormSchema` JSON / JSON Schema exactly as today. The A2UI dialect is
additive and opt-in.

**Who is affected**: frontend teams that already have an A2UI renderer (they
get FormDesigner forms for free), Fieldsync (must see zero change), operators
migrating forms between systems (bulk export, A2UI import), and agents that
author forms as A2UI surfaces.

### Constraints and goals
- **Zero change for legacy callers.** Default dialect of every existing and
  new form stays `json_schema`; `GET /forms/{uid}` and `/schema` return
  byte-for-byte what they return today unless the caller or the form opts in.
- **Reuse FEAT-544, do not fork it.** `A2UIFormRenderer`, the `FIELD_LOWERING`
  table, `api/a2ui_wire.py`, the `form-{uid}` surface id and the `parrot_*`
  extension vocabulary are the single source of A2UI truth. The dialect layer
  calls them; it never re-implements lowering.
- **ai-parrot stays an optional extra** for parrot-formdesigner (`[ai-parrot]`
  / `[a2ui]` extras, `ai-parrot>=1.2.1`). Every new module that touches
  `parrot.outputs.a2ui` imports it lazily; when the extra is missing the
  dialect flag is rejected with a clear 415/501, exactly like the render
  dispatcher does today.
- **Produced surfaces validate** with `validate_envelope(origin=ProducerOrigin.TOOL)`
  and `validate_message()`; no `Form` catalog component (dialect spec G6).
- **Reverse extraction is lossy-with-warnings, never silent.** Every dropped
  component, inferred type or guessed section is reported in the result;
  the API import still creates the form (user decision, Round 2).
- **Both translators are deterministic and testable as round-trips**:
  `FormSchema → A2UI → FormSchema` must be identity on the fields the surface
  can express (strict mode), and `FormSchema → JSON Schema → FormSchema → A2UI`
  must preserve sections/subsections once the extractor gaps are fixed.
- Tenant isolation rules of `FormRegistry` apply to bulk export (never
  aggregate across tenants in one call; iterate `list_tenants()`).
- Multitenant security: the dialect switch must not bypass
  `enforce_membership_unless_public` or the `onBeforeOpen` lifecycle hook.

---

### Recommended option / probable scope
**Option A** is recommended because:

- It keeps **one lowering table and one extension vocabulary** (FEAT-544's),
  so A2UI output is identical whether a form is rendered via `/render/a2ui`,
  served through the dialect flag, exported in bulk, or produced from a
  JSON-Schema document. Option B would inevitably drift.
- The user's Round-2 decisions map onto it directly: persisted form default +
  per-request override, export through service **and** API **and** CLI,
  JSON-Schema → A2UI by composition, lossy-with-warnings extractor with a
  dual-wire `POST /forms` import.
- Fixing `JsonSchemaExtractor`'s `x-section`/`x-placeholder`/`x-read-only`/
  `x-options` gaps is a small, well-bounded change that pays off beyond this
  feature.
- What we trade off: fidelity of JSON-Schema → A2UI is capped by the `x-*`
  extensions (style/snippets/events are not recoverable from JSON Schema),
  and heuristic extraction of generic surfaces will always need human review.
  Both are acceptable because the legacy path and the strict round-trip path
  remain exact, and the lossy paths report exactly what they lost.

Option C is rejected outright (contradicts the no-break constraint). Option D
does not satisfy the scope.

---

Treat `FormSchema` as the pivot and A2UI as a **dialect** of it, exactly as
JSON Schema already is. Four pieces, all inside parrot-formdesigner:

1. **Persisted flag + request negotiation.** New `FormSchema.dialect`
   (`FormDialect` enum: `json_schema` default, `a2ui`), stored in `schema_json`,
   patchable via the existing `PATCH /forms/{uid}` deep-merge. `GET /forms/{uid}`
   and `GET /forms/{uid}/schema` resolve the *effective* dialect as
   `?dialect=` query > `Accept: application/a2ui+json` > `form.dialect`, and
   when it is `a2ui` they delegate to the registered `"a2ui"` renderer (same
   object the render dispatcher uses) and answer `application/a2ui+json`.
   `?dialect=json_schema` always forces the legacy path, so a form flagged
   `a2ui` is still reachable by Fieldsync.
2. **Export service + API + CLI.** `A2UIExportService` (services/) wraps
   registry + renderer: `export_form()`, `export_tenant()` as an async
   iterator of `ExportedSurface(form_uid, form_id, version, envelope, warnings)`.
   `GET /forms?dialect=a2ui` adds the surface to each list entry;
   `POST /forms/export` (body: optional `form_uids`, `published_only`) streams
   NDJSON of envelopes. CLI `parrot formdesigner export --tenant X --out DIR`
   registered in `parrot.cli` `_lazy_commands` and shipped in
   parrot-formdesigner (`parrot_formdesigner/cli.py`, click group).
3. **JSON-Schema → A2UI by composition.** A thin
   `translate_jsonschema_to_a2ui(schema_dict, *, form_uid, tenant, …)` helper
   that runs `JsonSchemaExtractor.extract()` then `A2UIFormRenderer.render()`.
   The real work is **closing the extractor's fidelity gaps** so the
   composition is faithful: read `x-section`/`x-subsection` (rebuild the
   section tree instead of one flat `"fields"` section), `x-placeholder`,
   `x-read-only`, `x-options` (labels, not only `enum` values),
   `x-section-depends-on`/`x-subsection-depends-on`.
4. **A2UI → FormSchema extractor.** `A2UIExtractor` in `extractors/`
   (same shape as `JsonSchemaExtractor`): accepts a `createSurface` envelope
   (dict / JSON / `CreateSurface`), walks from `root`, and returns
   `ExtractedForm(form, warnings, dropped, mode)`. Two modes chosen
   automatically: **strict** when the root carries `parrot_variant: "form"`
   (identity, types, sections come from `parrot_*` extensions; a missing
   extension is a warning, never a guess), **heuristic** for any Basic
   surface (Card → section, nested Column/Row inside a Card → subsection,
   `TextField` variant → TEXT/TEXT_AREA/NUMBER/PASSWORD, `CheckBox` →
   BOOLEAN, `ChoicePicker` → SELECT / MULTI_SELECT, `Slider` → NUMBER with
   min/max constraints, `DateTimeInput` → DATE/TIME/DATETIME by
   `enableDate`/`enableTime`, `checks` → `FieldConstraints`, `{"path": …}`
   bindings → `field_id`, submit `Button` → `cancel_allowed`/ignored,
   Image/Video/AudioPlayer/Icon/Divider/List/Modal → dropped with a warning,
   Tabs → one section per TabItem). `POST /forms` becomes dual-wire: a body
   that is a v1.0 `createSurface` envelope (or `Content-Type:
   application/a2ui+json`) is imported through the extractor and registered;
   the legacy `{"prompt": …}` body is untouched.

✅ **Pros:**
- One lowering table, one extension vocabulary, one wire module — everything
  FEAT-544 fixed stays fixed here.
- Legacy dialect provably untouched (default + explicit `?dialect=json_schema`).
- The extractor gap fixes improve *every* JSON-Schema consumer, not only A2UI.
- Export and import are symmetric, so round-trip tests are cheap and strong.
- CLI reuses the existing `parrot` lazy-group mechanism; no new entry point.

❌ **Cons:**
- Fidelity of JSON-Schema → A2UI is capped by what `x-*` extensions carry;
  anything the JSON Schema dialect never encoded (style, snippets, lifecycle
  events) cannot be recovered.
- Heuristic extraction of generic surfaces is inherently lossy; needs honest
  documentation of what it infers.
- `get_form`/`get_schema` grow a branch each (lifecycle semantics for
  `onSchemaLoaded.schema_overrides` on the A2UI path need a decision).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `ai-parrot>=1.2.1` (optional extra) | `parrot.outputs.a2ui` models, `deserialize`, `validate_envelope`, catalog | already the FEAT-544 pin; stays optional |
| `pydantic` v2 | `FormDialect`, `ExportedSurface`, `ExtractedForm` models | already a dependency |
| `click` | `parrot formdesigner` group | already used by `parrot.cli` |
| `aiohttp` | NDJSON streaming for `POST /forms/export` | already the HTTP stack |

🔗 **Existing Code to Reuse:**
- `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/a2ui.py` — `A2UIFormRenderer`, `FIELD_LOWERING`, `field_pointer`/`field_id_from_pointer_token`, `_extensions`.
- `packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py` — `get_renderer("a2ui")`, `supported_formats()`, the optional-extra seeding pattern.
- `packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py` — `is_a2ui_request`, `a2ui_response`, `_a2ui_ns` lazy import pattern, `A2UI_MAX_BODY_BYTES`.
- `packages/parrot-formdesigner/src/parrot_formdesigner/extractors/jsonschema.py` — `JsonSchemaExtractor` (shape to mirror; gaps to fix).
- `packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py` — `FormRegistry.get/list_forms/list_tenants/register`.
- `packages/ai-parrot/src/parrot/cli/__init__.py` — `cli._lazy_commands` registration.

### Verified code anchors (paths only — open them yourself)
packages/ai-parrot/src/parrot/cli/__init__.py
packages/ai-parrot/src/parrot/cli/toolkits.py
packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py
packages/ai-parrot/src/parrot/outputs/a2ui/catalog/basic/inputs.py
packages/ai-parrot/src/parrot/outputs/a2ui/models.py
packages/ai-parrot/src/parrot/outputs/a2ui/serialization.py
packages/parrot-formdesigner/docs/a2ui-renderer.md
packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py
packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py
packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py
packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py
packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
packages/parrot-formdesigner/src/parrot_formdesigner/core/types.py
packages/parrot-formdesigner/src/parrot_formdesigner/extractors/jsonschema.py
packages/parrot-formdesigner/src/parrot_formdesigner/renderers/a2ui.py
packages/parrot-formdesigner/src/parrot_formdesigner/renderers/base.py
packages/parrot-formdesigner/src/parrot_formdesigner/renderers/jsonschema.py
packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py
packages/parrot-formdesigner/src/parrot_formdesigner/services/storage.py

### Questions still open in the exploration document
- [ ] Bulk export granularity: `POST /forms/export` NDJSON stream (proposed) vs a single JSON array response; and should the CLI also support `--all-tenants` (iterating `list_tenants()`)? — *Owner: Jesus Lara*
- [ ] Heuristic extractor: when a generic surface has a `Text` immediately before an input with no `label`, use it as the field label (proposed) or keep it as a section description? — *Owner: Jesus Lara*
- [ ] Should `translate_jsonschema_to_a2ui` get an HTTP endpoint in v1 (`POST /forms/translate`), or stay library + CLI only (proposed)? — *Owner: Jesus Lara*
- [ ] `click` is a transitive dependency of parrot-formdesigner today only through `ai-parrot`; declare it explicitly in the `ai-parrot`/`a2ui` extra or make the CLI module import it lazily? — *Owner: implementer*

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
