---
id: FEAT-563
title: A2UI v1.0 form renderer for FormDesigner — full render → submit → response cycle
slug: a2ui-form-output-renderer
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-09-10
  summary_oneline: A2UI v1.0 renderer for FormDesigner FormSchema — full form interaction cycle over A2UI surfaces
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-563/
created: 2026-09-10
updated: 2026-09-10
---

# FEAT-563 — A2UI v1.0 form renderer for FormDesigner (full interaction cycle)

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `inline` (invocation slug `a2ui-form-output-renderer`)
> **Audit**: [`sdd/state/FEAT-563/`](../state/FEAT-563/)
> **ID note**: FEAT-563 is a *provisional* proposal id (max existing + 1). `/sdd-spec` reserves the definitive id through `scripts/sdd/reserve_ids.py` (ledger `next_feature_id` is 542).

---

## 0. Origin

The original request, preserved verbatim. Full source at `sdd/state/FEAT-563/source.md`.

> Parrot-FormDesigner can export FormSchema objects into HTML, json-schema or other output formats, this proposal is for adding A2UI v1.0 compatible (with the extensions added by ai-parrot) renderer to output a form as a A2UI Surface with the "submit" pointing to the current endpoint for answering forms, is covering the entire cycle of interaction with Forms of FormDesigner using A2UI.

**Initial signals** (extracted, not interpreted):
- Verbs: "adding", "output", "covering the entire cycle" → additive capability (enrichment)
- Named entities: Parrot-FormDesigner, FormSchema, A2UI v1.0, A2UI Surface, "submit", "current endpoint for answering forms"
- Components / labels: parrot-formdesigner renderers; parrot.outputs.a2ui catalog + wire
- Acceptance criteria provided: no

---

## 1. Synthesis Summary

Add an `a2ui` output format to parrot-formdesigner that lowers any FormSchema into an A2UI v1.0 `createSurface` envelope (Basic Catalog primitives + ai-parrot `parrot_*` metadata extensions, no `Form` component), whose submit Button action targets the form's own answer endpoint, and make that endpoint speak A2UI back (validation errors / confirmation) so a v1.0 renderer can drive the whole fill-and-submit cycle without an LLM agent in the loop. On the FormDesigner side the plug-in points are `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/base.py` (`AbstractFormRenderer`) and the format-keyed registry in `packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py`, with the answer pipeline in `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` (`submit_data` / `validate`) behind `POST /api/v1/{tenant}/forms/{form_uid}/data`. On the A2UI side the wire models in `packages/ai-parrot/src/parrot/outputs/a2ui/models.py`, the Basic input primitives/functions and the existing `build_form()` lowering in `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/form.py` already express everything a form needs except a form-scoped action receiver — today every A2UI `action` is turned into an LLM agent turn by `A2UIRuntime`. The recommendation is a new `A2UIFormRenderer` registered as format `a2ui`, a hybrid FieldType→primitive mapping with honest degradation, and a dual-wire `/data` endpoint that accepts the standard A2UI `action` envelope and answers with A2UI envelopes.

---

## 2. Codebase Findings

> All entries are grounded in `sdd/state/FEAT-563/findings/`. Each cites the finding ID(s) that justify its inclusion. **No fabricated paths or symbols.**

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/base.py` | `AbstractFormRenderer` | 57-89 | contract the new A2UIFormRenderer implements (render → RenderedForm) | F005 |
| 2 | `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/__init__.py` | `_LAZY_EXPORTS` | 9-44 | public export point; lazy slot fits an optional ai-parrot import | F006, F019 |
| 3 | `packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py` | `_seed_default_renderers / register_renderer` | 38-83 | format-keyed registry; add `"a2ui"` so GET .../render/a2ui serves the envelope | F007 |
| 4 | `packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py` | `handle_render` | 101-151 | passes only `locale`; serialises dict content via json.dumps with renderer content_type | F007 |
| 5 | `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` | `render/validate/data routes` | 386-400 | the public-form globs the A2UI submit must target (`POST {tp}/forms/{form_uid}/data`) | F008 |
| 6 | `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | `FormHandler.submit_data` | 1464-1615 | field_id-keyed submit pipeline (validate → lifecycle → persist → forward); the server half of the cycle to reuse | F009 |
| 7 | `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | `FormHandler.validate` | 1003-1040 | dry-run validation returning {is_valid, errors}; candidate for A2UI `error` envelope mapping | F009 |
| 8 | `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py` | `FieldType → element map` | 71-119 | precedent for a dict-output renderer with an explicit FieldType mapping and unsupported set | F014 |
| 9 | `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py` | `submit script` | 570-598 | existing client submit behaviour (POST FormData to form action) and lifecycle bridge the A2UI cycle should mirror | F015 |
| 10 | `packages/parrot-formdesigner/src/parrot_formdesigner/core/types.py` | `FieldType` | 16-70 | 47 field types the renderer must map or degrade | F018 |
| 11 | `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` | `FormSchema / FormField / SubmitAction / RenderedForm` | 65-143, 300-314, 401-475, 671-688 | input model (sections → fields, submit action_type/action_ref) and output wrapper | F018 |
| 12 | `packages/parrot-formdesigner/src/parrot_formdesigner/core/constraints.py` | `FieldConstraints` | 21-68 | source of `checks` (min/max_length → length, pattern → regex, min/max_value → numeric, required) | F018, F012 |
| 13 | `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/form.py` | `build_form / _lower_field` | 32-164 | existing 6-kind form composition helper; the lowering pattern (Column + inputs bound to dataModel + Button.action.event) to generalise | F010 |
| 14 | `packages/ai-parrot/src/parrot/outputs/a2ui/models.py` | `Component / Action / EventAction / CheckRule / DataBinding / CreateSurface / ActionMessage / ErrorMessage` | 155-292, 400-520, 585-690 | v1.0 wire models the renderer emits and the submit receiver parses | F011 |
| 15 | `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/basic/inputs.py` | `TextField / CheckBox / ChoicePicker / DateTimeInput / Slider / Button` | 29 | the only input primitives available in v1.0 | F012 |
| 16 | `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/basic/functions.py` | `required / regex / length / numeric / email` | — | check functions available for constraint lowering | F012 |
| 17 | `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py` | `validate_envelope / register_component` | 111-180, 455-520 | structural validation the renderer must pass (TOOL origin, exactly one root) and the hook for any new Parrot components | F017 |
| 18 | `packages/ai-parrot/src/parrot/outputs/a2ui/runtime/dispatch.py` | `A2UIRuntime._dispatch_action / _build_action_turn` | 365-412 | shows today's action sink is an LLM agent turn — the form cycle needs a form-scoped receiver instead | F016 |
| 19 | `packages/ai-parrot-server/src/parrot/handlers/a2ui.py` | `A2UIHandler` | 1-60, 156-240 | agent-scoped A2UI transport (POST /api/v1/agents/{agent_id}/a2ui); pattern for parsing R→A envelopes and replying with A2UI media type | F016 |
| 20 | `packages/ai-parrot/src/parrot/a2a/models.py` | `A2UI_MEDIA_TYPE` | 336 | `application/a2ui+json` — content_type for RenderedForm and the submit receiver | F016 |
| 21 | `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/adaptive_cards.py` | `Action.Submit{a2ui_action}` | 21-32, 216, 641 | only shipped renderer with supports_actions=True; the Teams wrapper unwraps a2ui_action — precedent for a channel submit path | F022 |
| 22 | `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py` | `RendererCapabilities(supports_actions=False)` | 603-628 | web renderers render inputs but do not dispatch actions today — a gap for the browser half of the cycle | F022 |
| 23 | `packages/parrot-formdesigner/pyproject.toml` | `optional-dependencies.ai-parrot` | 48-52 | ai-parrot core is optional for parrot-formdesigner; A2UI models must be imported lazily | F019 |

### 2.2 Constraints Discovered

- **K1.** No `Form` catalog component: a form is a composition of Basic input primitives plus a `Button.action.event` (spec G6). The renderer must lower, never register a Form.
  *Implication*: Reuse/generalise build_form's lowering; no new top-level Form schema.
  *Evidence*: F010, F023

- **K2.** Envelopes carrying `action` are TOOL-origin only; `validate_envelope(origin=ProducerOrigin.LLM)` rejects them.
  *Implication*: Renderer validates its output with origin=TOOL; the envelope must never be re-emitted through an LLM-origin producer path.
  *Evidence*: F017, F010, F013

- **K3.** ai-parrot presentation semantics live under `metadata.extensions.parrot_*`, never as bare top-level props.
  *Implication*: Form/section/field identity (form_uid, field_id, field_uid, section_id, FieldType, dependency hints) ride in `parrot_*` extension keys.
  *Evidence*: F013

- **K4.** Only 5 input primitives (TextField, CheckBox, ChoicePicker, DateTimeInput, Slider) and 5 validation functions (required, regex, length, numeric, email) exist vs 47 FieldTypes and ~15 FieldConstraints.
  *Implication*: A mapping table with an explicit degraded set is mandatory; renderers must record RenderedForm.warnings like other renderers.
  *Evidence*: F012, F018

- **K5.** `DataBinding.path` must be a valid JSON Pointer; the submit wire contract is field_id-keyed.
  *Implication*: field_ids containing `/` or `~` need RFC 6901 escaping in paths and un-escaping on receipt; dataModel keys map 1:1 to field_id.
  *Evidence*: F011, F009

- **K6.** Today every A2UI `action` is routed into an LLM agent turn (A2UIRuntime) at an agent-scoped endpoint; no form-scoped action receiver exists, and web renderers declare supports_actions=False.
  *Implication*: The 'submit points to the form endpoint' requirement needs the FormDesigner submit path to accept an A2UI action envelope (or a client that posts context to /data) — see U1.
  *Evidence*: F016, F022

- **K7.** The render dispatcher passes only `locale` and serialises dict content with the renderer's content_type; unknown format keys return 415.
  *Implication*: Registering `"a2ui"` is enough for GET .../render/a2ui; prefilled/errors are not reachable through this route today.
  *Evidence*: F007

- **K8.** ai-parrot core is an optional extra of parrot-formdesigner; the audio renderer imports parrot.* lazily inside try/except ImportError.
  *Implication*: A2UIFormRenderer imports parrot.outputs.a2ui lazily and is skipped/raises a clear error when the extra is absent.
  *Evidence*: F019

- **K9.** Submit responses are plain JSON: 200 composite on success, 422 {is_valid:false, errors:{field_id:[..]}} on validation failure; lifecycle hooks and persistence run inside submit_data.
  *Implication*: An A2UI response must be produced by translating this result, not by bypassing submit_data.
  *Evidence*: F009

### 2.3 Recent History (Relevant)

Commits on the affected paths in the last 60 days (5 most relevant of 25), newest first.

| Commit | When | Author | Message | Touched |
|--------|------|--------|---------|---------|
| `1450dda35` | 2026-09-05 | Jesus | feat(infographic-a2ui-migration): TASK-2863 — HtmlDocument Parrot catalog component + build_html_document() builder | `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot` |
| `5efc51fa7` | 2026-09-02 | Jesus Lara | feat(formfield-content-type): make VoiceAnswerEnvelope enforceable, close review gaps | `packages/parrot-formdesigner/src/parrot_formdesigner/renderers` |
| `74384aba9` | 2026-08-28 | Jesus Lara | feat(a2ui-v1-dialect): TASK-2540 — build_form(), export_catalog_definition(), builders emit root + catalogId | `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/form.py` |
| `2246eaa18` | 2026-08-28 | Jesus Lara | feat(a2ui-v1-dialect): TASK-2539 — parrot catalog moved to catalog/parrot/, lower() to v1.0 primitives | `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot` |
| `48227a5fd` | 2026-08-25 | Jesus Lara | feat(raw-upload-field-types): TASK-2449 — Other Renderers Update (html5/pdf/adaptive_card) | `packages/parrot-formdesigner/src/parrot_formdesigner/renderers` |

Nothing in flight targets A2UI forms; both areas are active (FEAT-527 catalog work, formfield-content-type renderer work). *Evidence*: F019, F020.

---

## 3. Probable Scope  *(mode = enrichment)*

### 3.0 Target interaction cycle

```
GET  /api/v1/{tenant}/forms/{form_uid}/render/a2ui        ──►  createSurface{surfaceId, catalogId, sendDataModel:true,
                                                                   components:[Column, Text(title), Card(section)…, TextField/ChoicePicker/…, Button(submit)],
                                                                   dataModel:{answers:{<field_id>: default…}}}
        client fills inputs (bound at /answers/<field_id>)
        client presses Button → action{name:"form.submit", surfaceId, context:{form_uid, tenant, submit_url, answers:…}, dataModel}
POST /api/v1/{tenant}/forms/{form_uid}/data  (A2UI action envelope OR plain field_id JSON)
        ──► 422: error{code, surfaceId, path:/answers/<field_id>, message} per field (+ updateDataModel)
        ──► 200: updateComponents / createSurface confirmation (A2UI callers) · composite JSON (legacy callers)
```

### What's New

- **`A2UIFormRenderer` (parrot_formdesigner/renderers/a2ui.py)** — AbstractFormRenderer producing RenderedForm{content: v1.0 createSurface envelope dict, content_type: application/a2ui+json}; lazy import of parrot.outputs.a2ui  *Evidence*: F005, F010, F011, F019
- **FieldType → Basic-primitive mapping + FieldConstraints → CheckRule lowering** — table-driven like adaptive_card.py; explicit degraded set with RenderedForm.warnings and `parrot_role: notice` placeholders  *Evidence*: F012, F014, F018
- **Surface layout lowering** — FormSchema.title → Text(parrot_role=title); sections/subsections → Card/Column with Text headers; fields bound at `/answers/<field_id>` in dataModel (prefilled defaults); `sendDataModel: true`  *Evidence*: F010, F011, F013
- **Submit Button action** — `Button.action.event{name: 'form.submit', context: {form_uid, tenant, submit_url: /api/v1/{tenant}/forms/{form_uid}/data, answers: {field_id: binding}}}` — the 'submit points to the current endpoint' half  *Evidence*: F008, F010, F011
- **A2UI-aware submit receiver (server half)** — accept a v1.0 renderer→agent `action` envelope on the form's answer path, unwrap context/dataModel into field_id answers, run the existing submit pipeline, answer with A2UI envelopes (error with path per field on 422; updateComponents/createSurface confirmation on 200)  *Evidence*: F009, F011, F016
- **`"a2ui"` format registration** — register_renderer('a2ui', A2UIFormRenderer()) in api/render.py seed + export in renderers/__init__.py  *Evidence*: F006, F007

### What Changes

- **`packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py`**::_seed_default_renderers — add `_RENDERERS.setdefault("a2ui", A2UIFormRenderer())`  *Evidence*: F007
- **`packages/parrot-formdesigner/src/parrot_formdesigner/renderers/__init__.py`**::_LAZY_EXPORTS / __all__ — export A2UIFormRenderer (lazy, optional dep)  *Evidence*: F006, F019
- **`packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`**::FormHandler.submit_data / FormHandler.validate — detect an A2UI action envelope body (or A2UI media type) and translate in/out; or delegate from a new sibling route — decision U1/U2  *Evidence*: F009, F011
- **`packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py`**::form routes — only if U1 chooses a dedicated `POST {tp}/forms/{form_uid}/a2ui` route (public-form glob, same membership rule)  *Evidence*: F008
- **`packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/form.py`**::build_form — optionally widen FormFieldInput / factor `_lower_field` so FormDesigner and tool-built forms share one lowering  *Evidence*: F010
- **`docs/outputs/a2ui-v1.md`**::docs — document the form cycle and any new `parrot_form_*` extension keys  *Evidence*: F013

### What's Untouched (Non-Goals)

- Registering a `Form` catalog component (spec G6 forbids it).
- Routing form submissions through an LLM agent turn / A2UIRuntime — the form endpoint is the sink.
- New browser-side A2UI renderer work in ai-parrot-visualizations (interactive_html stays supports_actions=False unless a later feature adds dispatch).
- Binary uploads (FILE/IMAGE/MULTI_UPLOAD/SIGNATURE_PAD/AUDIO) through the A2UI data model — degraded with a link/notice in v1.
- Partial saves, lifecycle-event bridge and conditional `depends_on` visibility unless U4 includes them.

### Patterns to Follow

- Table-driven FieldType mapping with an explicit unsupported set (adaptive_card.py)  *Evidence*: F014
- build_form lowering: Column root, inputs bound to dataModel paths, required → CheckRule(required), Button.action.event with context bindings  *Evidence*: F010
- `metadata.extensions.parrot_*` for presentation semantics; validate with validate_envelope(origin=TOOL)  *Evidence*: F013, F017
- Lazy optional import of ai-parrot inside the renderer (audio.py)  *Evidence*: F019
- A2UIHandler transport: parse JSON/JSONL envelopes, reply with A2UI_MEDIA_TYPE  *Evidence*: F016
- Telegram renderer spec: renderer owns the full cycle, reuses existing handlers, states non-goals  *Evidence*: F021

### Integration Risks

- **Action sink mismatch: standard A2UI clients POST actions to an agent endpoint; a form surface must tell the client where to send the action (context.submit_url) or FormDesigner must expose an A2UI-speaking receiver.** *Mitigation*: Decide U1; whichever is chosen, keep the standard `action` envelope shape so Adaptive Cards/Teams and deep-link paths keep working.  *Evidence*: F016, F022
- **47 → 5 primitive coverage gap; complex types (GROUP/ARRAY/relations/uploads) cannot be expressed natively.** *Mitigation*: Explicit degraded set + warnings; consider Parrot-catalog form components later (U3).  *Evidence*: F012, F014, F018
- **field_id → JSON Pointer escaping and dataModel size cap (A2UI_MAX_DATA_MODEL_BYTES) on large forms.** *Mitigation*: RFC 6901 escape helper with round-trip tests; keep dataModel to answers only.  *Evidence*: F011, F016
- **Tenant/public auth: the render route is a public-form glob; an A2UI receiver must apply the same enforce_membership_unless_public rule.** *Mitigation*: Reuse the existing wrappers on any new route.  *Evidence*: F007, F008
- **Optional dependency: parrot-formdesigner without the ai-parrot extra must not break at import.** *Mitigation*: Lazy import; seed registry only when import succeeds, log once.  *Evidence*: F019

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | Renderers plug in via AbstractFormRenderer + register_renderer(format_key); adding `a2ui` needs no new route for rendering. | F005, F007 | high | direct read of base.py and render.py |
| C2 | A2UI v1.0 forbids a Form component; forms are Basic-primitive compositions with Button.action.event (build_form is the in-repo precedent). | F010, F023 | high | spec G6 + form.py docstring |
| C3 | Only TextField/CheckBox/ChoicePicker/DateTimeInput/Slider inputs and required/regex/length/numeric/email checks exist to map 47 FieldTypes and FieldConstraints. | F012, F018 | high | grep of inputs.py/functions.py and types.py/constraints.py |
| C4 | The existing submit endpoint is `POST /api/v1/{tenant}/forms/{form_uid}/data` taking field_id-keyed JSON and returning 200/422 JSON. | F008, F009 | high | routes.py + submit_data docstring/returns |
| C5 | No A2UI action receiver exists outside the agent-scoped A2UIRuntime path; the runtime turns actions into LLM turns. | F016, F022 | high | dispatch.py _build_action_turn + handlers/a2ui.py |
| C6 | ai-parrot extensions belong in metadata.extensions.parrot_*; the renderer can carry form identity there without breaking official-schema validation. | F013 | high | docs section on extensions |
| C7 | parrot-formdesigner has zero A2UI code today and treats ai-parrot as an optional extra. | F019 | high | grep absence + pyproject |
| C8 | Adaptive Cards is the only shipped A2UI renderer that dispatches actions; browser renderers do not, so the browser half of the cycle depends on the consuming client. | F022 | high | RendererCapabilities flags |
| C9 | Prefilled values and per-field errors can ride in `dataModel` and `checks` respectively, but the render dispatcher does not pass prefilled/errors today. | F007, F011 | medium | inferred: models support it; handler signature omits it |
| C10 | A2UI `ErrorMessage` with surfaceId+path can express per-field 422 errors returned by submit_data. | F011, F009 | medium | model supports (surfaceId, path); mapping semantics not yet exercised in repo |
| C11 | Both code areas are actively changing (FEAT-527 catalog work on 2026-09-05; renderer content-type work 2026-09-02) but nothing in flight targets A2UI forms. | F020, F019 | high | git log 60 days + absence grep |
| C12 | build_form's `_lower_field` can be generalised to serve FormDesigner without duplicating lowering logic. | F010 | medium | inferred from structure; API widening not yet designed |

Distribution: **9** high, **3** medium, **0** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **Where does the A2UI submit action land? (the 'submit pointing to the current endpoint' requirement)** — *Resolved*: a) Dual-wire /data — extend POST /api/v1/{tenant}/forms/{form_uid}/data to also accept a v1.0 `action` envelope (detected by body shape or application/a2ui+json); Button.action.event.context carries the submit URL.
  *Resolves claims*: C4, C5

- [x] **What should the endpoint answer after an A2UI submit?** — *Resolved*: a) Full A2UI cycle — 422 → `error` envelopes with surfaceId+path per invalid field (plus updateDataModel); 200 → confirmation via updateComponents/createSurface; plain JSON stays for non-A2UI callers (content negotiation).
  *Resolves claims*: C10

- [x] **How should FieldTypes with no Basic primitive be handled in v1?** — *Resolved*: c) Hybrid — map everything Basic can express natively (NPS/LIKERT/RANKING→Slider, MULTI_SELECT/TAGS→multi ChoicePicker, HIDDEN→dataModel only, EMAIL/URL/PHONE→TextField+email/regex checks); degrade the rest with a `parrot_role: notice` Text + RenderedForm.warnings; Parrot-catalog form components in a follow-up.
  *Resolves claims*: C3

- [x] **Which parts of the interaction cycle beyond render → validate → submit are in scope for v1?** — *Resolved*: a) Core cycle only — partial saves, depends_on conditional visibility and the lifecycle-event bridge are explicit non-goals for v1.
  *Resolves claims*: C9

### Unresolved (defer to spec / implementation)

- [ ] **Exact `parrot_*` extension keys for form identity** (`parrot_form_uid`, `parrot_field_id`, `parrot_field_type`, `parrot_section_id`, …) and whether `build_form()`'s `_lower_field` is widened or a FormDesigner-local lowering table is kept. — *Owner*: spec
  *Blocks claims*: C12
- [ ] **Confirmation surface content on 200** (static "submitted" Text vs. echo of `submission_id`/forwarded status) and the `error.code` used for per-field validation failures. — *Owner*: spec
  *Blocks claims*: C10
- [ ] **How `prefilled`/`errors` reach the renderer** given `handle_render` passes only `locale` (query params vs. a session-bound partial lookup). — *Owner*: spec
  *Blocks claims*: C9

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-563`** — *Rationale*: Localization is high-confidence on both sides (renderer registry + submit pipeline; A2UI models + build_form); the remaining decisions (U1–U4) are product choices, not research gaps, and are answerable at spec time.

### Alternatives

- **`/sdd-brainstorm FEAT-563`** — only if the dual-wire `/data` decision (U1) is reopened against a dedicated `/a2ui` route or an A2UIRuntime-based sink.
- **`/sdd-task FEAT-563`** — not suitable: the feature spans two packages (renderer + endpoint + docs + tests).
- **Manual review** — not needed; research completed without truncation.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-563/state.json` |
| Source (raw) | `sdd/state/FEAT-563/source.md` |
| Research plan | `sdd/state/FEAT-563/research_plan.json` |
| Findings (digests) | `F001-formdesigner-renderer-landscape.md`, `F002-a2ui-subsystem-landscape.md`, `F003-form-submission-surface.md`, `F004-a2ui-action-routing-landscape.md`, `F005-abstractformrenderer-contract.md`, `F006-renderers-init-exports.md`, `F007-render-dispatcher-registry.md`, `F008-form-rest-routes.md`, `F009-submit-data-contract.md`, `F010-build-form-helper.md`, `F011-a2ui-wire-models.md`, `F012-basic-catalog-primitives-functions.md`, `F013-a2ui-v1-docs.md`, `F014-adaptive-card-renderer-precedent.md`, `F015-html5-submit-wiring.md`, `F016-a2ui-runtime-and-server-handler.md`, `F017-catalog-registration-validation.md`, `F018-formschema-fieldtype-surface.md`, `F019-no-a2ui-in-formdesigner.md`, `F020-git-log-60-days.md`, `F021-telegram-renderer-spec-precedent.md`, `F022-renderer-action-dispatch-client-half.md`, `F023-spec-g6-form-retired.md` |
| Synthesis (JSON) | `sdd/state/FEAT-563/synthesis.json` |
| Synthesis reasoning | `sdd/state/FEAT-563/synthesis.thinking.log` |

**Budget consumed** (profile `default`):
- Files read: 24 / 40
- Grep calls: 22 / 25
- Git calls: 1 / 10
- Wiki calls: 6 (free)
- Wall time (research queries): ≈250s / 300s; ≈676s including finding persistence and synthesis
- Truncated: **no**

**Mode determination**: `auto` → resolved to `enrichment` (additive verbs: "adding … renderer", "covering the entire cycle").

**Gates**: plan gate skipped (unattended session; plan executed as written); review gate + Q&A executed as a single 4-question round (U1–U4 all answered).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Jesus Lara (via Claude Code) |
