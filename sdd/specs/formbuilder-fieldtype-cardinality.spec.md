---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Relational Field Cardinality for parrot-formdesigner

**Feature ID**: FEAT-456
**Date**: 2026-08-24
**Author**: Jesus Lara
**Status**: draft
**Target version**: parrot-formdesigner 0.11.0

---

## 1. Motivation & Business Requirements

> Source: `sdd/proposals/formbuilder-fieldtype-cardinality.brainstorm.md`
> (Recommended Option C — carried forward as authoritative).

### Problem Statement

`FormSchema` cannot express **relational fields** — a field whose value is a
reference to a record in another entity (Odoo's `Many2one`), a list of such
references (`Many2many`), or a set of embedded child rows owned by the parent
record (`One2many`). The current vocabulary stops at:

- `FieldType.SELECT` / `MULTI_SELECT` / `DYNAMIC_SELECT` — choose from
  options, but the schema does not know the options *are records of another
  entity*.
- `OptionsSource` — knows *where* to fetch options (tool / endpoint / query)
  but carries no cardinality, no target-entity identity, and no semantics
  beyond "list of value/label pairs".
- `FieldType.ARRAY` + `item_template` — embedded repeating rows, with no way
  to state "these rows are child records of entity X related back to the
  parent".

This blocks three consumers: (1) the future **Odoo renderer/toolkit** — the
primary motivation — which must know a field is `Many2one('res.partner')`,
not "a select"; (2) **database-driven form extraction**, where foreign keys
should become relational fields; (3) **current web renderers**, which should
surface relation metadata to frontends. Without a first-class relational
concept, every consumer invents its own convention inside `FormField.meta`,
fragmenting the semantics the abstraction layer exists to unify.

### Goals

- Add a typed, orthogonal relation aspect (`FormField.relation`) able to
  express Many2one, Many2many, and One2many semantics.
- One2many reuses the existing `ARRAY` + `item_template` machinery
  (embed mode) — no parallel embedded-row engine.
- All 7 existing renderers keep working unchanged; relation-unaware
  renderers render the field exactly as today (SELECT/MULTI_SELECT/ARRAY
  paths).
- YAML and JSON Schema extractors can declare and round-trip relations
  (`x-relation` extension on the JSON Schema side).
- `FormValidator` validates the **shape** of relational submissions (scalar
  ID for cardinality one, list of IDs for many).
- Persisted `FormSchema` documents load unchanged (`relation` optional,
  default `None`).

### Non-Goals (explicitly out of scope)

- The Odoo renderer/toolkit itself — a separate follow-up feature that
  consumes `RelationSpec`.
- FK-aware DB-table-schema → `FormSchema` extraction — separate follow-up
  (today's `DatabaseFormTool` is a stored-form-definition dispatcher, not a
  table-schema extractor).
- Server-side paginated option search / autocomplete — v1 uses the existing
  `OptionsSource`/`OptionsLoader` snapshot mechanism (resolved in
  brainstorm).
- Referenced-ID **existence** validation — the target system's job
  (resolved in brainstorm: shape-only in v1).
- New relational `FieldType` enum members and `OptionsSource` overloading —
  rejected as brainstorm Options A and B (see
  `sdd/proposals/formbuilder-fieldtype-cardinality.brainstorm.md`).
- Relational inference from Pydantic/Tool extractor type hints (open
  question, deferred).

---

## 2. Architectural Design

### Overview

Relations are modeled as a new optional aspect on `FormField` — exactly like
`constraints`, `options_source`, and `depends_on` already are — instead of
new enum types or `OptionsSource` overloading. A new `core/relations.py`
defines two Pydantic models:

- **`EntityRef`** — identifies the relation target: free-form
  `namespace: str` (documented conventions: `"odoo"`, `"db"`, `"api"`,
  `"formdesigner"`) + `entity: str` (e.g. `"res.partner"`,
  `"public.customers"`, or a `form_id` when `namespace="formdesigner"`) +
  optional `key_field`. No central registry — consumers that don't
  recognize a namespace ignore the relation.
- **`RelationSpec`** — `cardinality` (`"one" | "many"`), `target:
  EntityRef`, `mode` (`"reference" | "embed"`), optional `display_field`,
  `inverse_field` (embed mode), `on_delete` hint (passthrough, no
  enforcement in v1), and `filters`.

Canonical combinations, enforced by a model-validator on `FormField`:

| Odoo concept | field_type | relation |
|---|---|---|
| Many2one | `SELECT` / `DYNAMIC_SELECT` / `TREE_SELECT` | `cardinality="one", mode="reference"` |
| Many2many | `MULTI_SELECT` / `TAGS` / `TRANSFER_LIST` | `cardinality="many", mode="reference"` |
| One2many | `ARRAY` + `item_template` | `cardinality="many", mode="embed", inverse_field=...` |

Renderers need zero changes to keep working: a relational SELECT is still a
SELECT whose options come from static `options` or `OptionsSource` (the
static-options case is precisely what made extending `OptionsSource`
unworkable — the relation metadata needs a home even when no source exists).
The JSON Schema renderer additionally emits an `x-relation` extension so
frontends can build richer pickers later; all other renderers ignore
`relation` in v1 as a documented no-op (same convention `XFormsRenderer`
uses for `style`/`prefilled`).

**Decisions carried from the brainstorm (do not re-open):**
- One2many = existing `ARRAY`+`item_template` with relation metadata.
- Option fetching v1 = existing `OptionsSource` snapshot via
  `OptionsLoader`; no pagination/autocomplete.
- Validation v1 = shape only (well-formed ID / list of IDs).
- Schema migration: permitted but not needed — `relation` defaults to
  `None`, persisted schemas round-trip untouched.

### Component Diagram

```
core/relations.py (NEW: EntityRef, RelationSpec)
        │
        ▼
core/schema.py: FormField.relation ──── model-validator (legal combinations)
        │                                        │
        │                                        ▼
        │                        core/resolution.py: inverse_field
        │                        existence check (embed mode)
        │
        ├──→ extractors/yaml.py        (parse `relation:` block)
        ├──→ extractors/jsonschema.py  (parse/emit `x-relation`)
        ├──→ renderers/jsonschema.py   (emit `x-relation`)
        ├──→ services/validators.py    (ID / ID-list shape validation)
        └──→ [future consumers: Odoo renderer/toolkit, FK extractor]
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `core/schema.py` `FormField` | extends | new optional `relation` field + combination validator |
| `core/__init__.py` | extends | export `EntityRef`, `RelationSpec` |
| `core/resolution.py` | extends | form-level `inverse_field` existence check alongside `resolve_rule_references` |
| `extractors/yaml.py` `YamlExtractor` | extends | `_parse_field` gains `relation:` block parsing |
| `extractors/jsonschema.py` | extends | parse/emit `x-relation` (mirrors `x-options-source` handling at line 245) |
| `renderers/jsonschema.py` `JsonSchemaRenderer` | extends | emit `x-relation` per relational field |
| `services/validators.py` `FormValidator` | extends | shape validation for reference values |
| renderers html5 / adaptive_card / telegram / pdf / xforms / audio | none | documented no-op; existing SELECT/ARRAY paths render the field |
| `controls/builtin.py`, `FieldType` enum | none | deliberately untouched — no new types |
| `services/options_loader.py` `OptionsLoader` | uses (unchanged) | option fetching for `mode="reference"` fields |
| persisted FormSchema storage / registry | compatible | optional field, `None` default; no migration |

### Data Models

```python
# core/relations.py (NEW — shapes, not implementation)

class EntityRef(BaseModel):
    """Identifies the target entity of a relation."""
    model_config = ConfigDict(extra="forbid")
    namespace: str          # "odoo" | "db" | "api" | "formdesigner" | ... (free-form)
    entity: str             # "res.partner" | "public.customers" | form_id
    key_field: str | None = None   # target's key field; None = target's default key

class RelationSpec(BaseModel):
    """Relational semantics of a field's value, orthogonal to field_type."""
    model_config = ConfigDict(extra="forbid")
    cardinality: Literal["one", "many"]
    target: EntityRef
    mode: Literal["reference", "embed"] = "reference"
    display_field: str | None = None       # target field shown to users
    inverse_field: str | None = None       # embed mode: child field pointing back
    on_delete: Literal["restrict", "cascade", "set_null"] | None = None  # hint only
    filters: dict[str, Any] | None = None  # consumer-interpreted target filters
```

```python
# core/schema.py — FormField gains (after item_template, before meta):
relation: RelationSpec | None = None

# model-validator (FormField level) enforcing:
#  - mode="reference" → field_type in {SELECT, DYNAMIC_SELECT, TREE_SELECT}
#    for cardinality="one"; in {MULTI_SELECT, TAGS, TRANSFER_LIST} for "many"
#  - mode="embed" → field_type == ARRAY, item_template is not None,
#    cardinality == "many", inverse_field is not None
#  - any other combination → ValueError naming field_id and the violated rule
```

### New Public Interfaces

```python
# from parrot_formdesigner.core import EntityRef, RelationSpec  (new exports)

# Helper predicate on FormField (convenience for consumers):
#   FormField.is_relational -> bool   (property: relation is not None)

# YAML authoring surface (extractors/yaml.py):
#   fields:
#     - field_id: customer
#       type: select
#       relation:
#         cardinality: one
#         mode: reference
#         target: {namespace: odoo, entity: res.partner}
#         display_field: name

# JSON Schema extension (extractors + renderer, symmetric):
#   "x-relation": {"cardinality": "one", "mode": "reference",
#                   "target": {"namespace": "odoo", "entity": "res.partner"}}
```

---

## 3. Module Breakdown

### Module 1: Relation core models
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/core/relations.py` (NEW)
- **Responsibility**: `EntityRef` and `RelationSpec` Pydantic models
  (`extra="forbid"`), including model-level validation local to the spec
  (e.g. `mode="embed"` requires `inverse_field`).
- **Depends on**: nothing new (pydantic only).

### Module 2: FormField integration + combination validation
- **Path**: `core/schema.py`, `core/__init__.py`
- **Responsibility**: add `FormField.relation: RelationSpec | None = None`,
  the `is_relational` property, the (field_type × cardinality × mode)
  model-validator, and public exports. `FormField.model_rebuild()` already
  exists at schema.py:100.
- **Depends on**: Module 1.

### Module 3: Form-level resolution check (embed mode)
- **Path**: `core/resolution.py`
- **Responsibility**: alongside `resolve_rule_references(form)`, verify that
  an embed-mode field's `inverse_field` names an existing field inside its
  `item_template` tree; raise `ValueError` naming field_id otherwise.
- **Depends on**: Module 2.

### Module 4: Extractor mappings (YAML + JSON Schema)
- **Path**: `extractors/yaml.py`, `extractors/jsonschema.py`
- **Responsibility**: `YamlExtractor._parse_field` parses an optional
  `relation:` block; the JSON Schema extractor parses `x-relation`
  (mirroring the `x-options-source` pattern at jsonschema.py:245). Both
  round-trip all `RelationSpec` fields.
- **Depends on**: Module 2.

### Module 5: JSON Schema renderer emission
- **Path**: `renderers/jsonschema.py`
- **Responsibility**: emit `x-relation` for relational fields (symmetric
  with Module 4's parsing). Other renderers get a one-line docstring note
  that `relation` is intentionally ignored.
- **Depends on**: Module 2.

### Module 6: Shape validation
- **Path**: `services/validators.py`
- **Responsibility**: in `FormValidator.validate` / `validate_field`,
  reference-mode values must be a scalar ID (cardinality one) or a list of
  IDs (many); embed-mode values flow through the existing ARRAY recursive
  path unchanged. No existence checks, no I/O.
- **Depends on**: Module 2.

### Module 7: Documentation
- **Path**: `docs/` (formdesigner section) + module docstrings
- **Responsibility**: document the relation aspect, the namespace
  conventions (`odoo`/`db`/`api`/`formdesigner`), the legal-combination
  table, and the renderer no-op convention.
- **Depends on**: Modules 1–6.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_relation_spec_valid` | 1 | RelationSpec accepts all documented shapes |
| `test_relation_embed_requires_inverse` | 1 | `mode="embed"` without `inverse_field` rejected |
| `test_formfield_relation_reference_one` | 2 | SELECT + cardinality=one validates |
| `test_formfield_relation_reference_many` | 2 | MULTI_SELECT/TAGS/TRANSFER_LIST + many validates |
| `test_formfield_relation_embed_array` | 2 | ARRAY + item_template + embed validates |
| `test_formfield_relation_illegal_combo` | 2 | BOOLEAN+relation, MULTI_SELECT+one, embed w/o ARRAY → ValueError naming field_id |
| `test_relation_none_default_roundtrip` | 2 | pre-FEAT-456 schema dict loads; `model_dump()` round-trips without `relation` noise |
| `test_resolution_inverse_field_exists` | 3 | inverse_field naming a child field passes |
| `test_resolution_inverse_field_missing` | 3 | unknown inverse_field → ValueError naming field_id |
| `test_yaml_relation_block` | 4 | YAML `relation:` block parses to RelationSpec |
| `test_jsonschema_x_relation_roundtrip` | 4+5 | extractor(renderer(form)) preserves RelationSpec |
| `test_jsonschema_renderer_emits_x_relation` | 5 | relational field carries `x-relation` in output |
| `test_validator_reference_scalar_id` | 6 | cardinality=one accepts scalar, rejects list |
| `test_validator_reference_id_list` | 6 | cardinality=many accepts list of IDs, rejects scalar |
| `test_validator_embed_recurses_array` | 6 | embed values validate via existing ARRAY path |
| `test_relational_select_renders_unchanged` | 5 (regression) | HTML5/AdaptiveCard output for a relational SELECT is byte-identical to the same field without `relation` |

### Integration Tests

| Test | Description |
|---|---|
| `test_relational_form_end_to_end` | YAML with all three relation kinds → extract → register → render (html + jsonschema) → validate a submission; only jsonschema output differs from the non-relational baseline |
| `test_persisted_schema_backcompat` | a stored pre-relation FormSchema JSON loads, renders, and validates unchanged |

### Test Data / Fixtures

```python
@pytest.fixture
def relational_form() -> FormSchema:
    """One section with: customer (SELECT, one/reference/odoo:res.partner),
    tags (MULTI_SELECT, many/reference/db:public.tags),
    lines (ARRAY+item_template, many/embed, inverse_field='order_id')."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `from parrot_formdesigner.core import EntityRef, RelationSpec` works.
- [ ] `FormField` accepts `relation=` and enforces the legal-combination
      table; every rejection names the offending `field_id`.
- [ ] One2many is expressed as `ARRAY` + `item_template` +
      `RelationSpec(mode="embed", inverse_field=...)` — no new FieldType
      enum members and no `controls/builtin.py` changes exist in the diff.
- [ ] `OptionsSource` is unmodified (7 fields, options.py:45-52).
- [ ] A schema serialized before this feature loads, renders, and validates
      unchanged (no migration script shipped or needed).
- [ ] For every renderer except `jsonschema`, rendering a relational field
      produces output identical to the same field without `relation`.
- [ ] `JsonSchemaRenderer` emits `x-relation`; the JSON Schema extractor
      parses it back losslessly (round-trip test green).
- [ ] YAML `relation:` block parses to an equivalent `RelationSpec`.
- [ ] `FormValidator` rejects a list where cardinality="one" expects a
      scalar and vice versa; performs no I/O and no existence checks.
- [ ] Embed-mode `inverse_field` referencing a nonexistent child field is
      rejected at the resolution boundary.
- [ ] All unit + integration tests pass
      (`pytest packages/parrot-formdesigner/tests/ -v`).
- [ ] `ruff check` clean on all touched files.
- [ ] Documentation updated (Module 7).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified against dev on 2026-08-24 (post-merge 22cf4f43b). Implementation
> agents MUST NOT reference imports, attributes, or methods not listed here
> without first verifying via `grep` or `read`.

### Verified Imports

```python
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection, RenderedForm
from parrot_formdesigner.core.types import FieldType, LocalizedString
from parrot_formdesigner.core.options import FieldOption, OptionsSource
from parrot_formdesigner.core.constraints import FieldConstraints
from parrot_formdesigner.renderers.base import AbstractFormRenderer, FallbackRenderer
# all verified this session against packages/parrot-formdesigner/src/parrot_formdesigner/
```

### Existing Class Signatures

```python
# core/schema.py:44
class FormField(BaseModel):
    model_config = ConfigDict(extra="forbid")        # line 78
    field_uid: uuid.UUID                              # line 80 (FEAT-393, default_factory=uuid4)
    field_id: str                                     # line 81
    field_type: FieldType                             # line 82
    required: bool = False                            # line 86
    constraints: FieldConstraints | None = None       # line 89
    options: list[FieldOption] | None = None          # line 90
    options_source: OptionsSource | None = None       # line 91
    depends_on: DependencyRule | None = None          # line 92
    post_depends: list[PostDependency] | None = None  # line 93
    children: list[FormField] | None = None           # line 94  (GROUP)
    item_template: FormField | None = None            # line 95  (ARRAY)
    meta: dict[str, Any] | None = None                # line 96
# FormField.model_rebuild() at core/schema.py:100 — extend, don't duplicate

# core/options.py:32 — MUST REMAIN UNCHANGED (acceptance criterion)
class OptionsSource(BaseModel):
    source_type: str                                  # line 45
    source_ref: str                                   # line 46
    value_field: str = "value"                        # line 47
    label_field: str = "label"                        # line 48
    cache_ttl_seconds: int | None = None              # line 49
    http_method: Literal["GET", "POST"] = "GET"       # line 51 (FEAT-167)
    auth_ref: str | None = None                       # line 52

# core/types.py:16 — FieldType members relevant here (NO new members allowed):
#   SELECT=27  MULTI_SELECT=28  GROUP=37  ARRAY=38  DYNAMIC_SELECT=41
#   TRANSFER_LIST=42  TAGS=46  TREE_SELECT=62

# core/resolution.py:28
def resolve_rule_references(form: FormSchema) -> FormSchema:
    # build-time field_id → field_uid rewriting; add the embed
    # inverse_field existence check at this same boundary

# services/validators.py:101
class FormValidator:
    async def validate(...)        # line 122
    async def validate_field(...)  # line 228
    def validate_rules(self, form: FormSchema) -> list[str]:  # line 999

# extractors/yaml.py (class YamlExtractor):
    def extract(self, content: str) -> FormSchema:              # line 131
    def _parse_field(self, data: Any) -> FormField | None:      # line 267
    def _parse_options(self, field_config) -> list[FieldOption] | None:  # line 416

# extractors/jsonschema.py:240-253 — x-options-source parsing (FEAT-167):
#   the exact pattern to mirror for x-relation

# renderers/base.py — AbstractFormRenderer.render signature (all renderers):
    async def render(self, form: FormSchema, style: StyleSchema | None = None,
                     *, locale: str = "en", prefilled: dict[str, Any] | None = None,
                     errors: dict[str, str] | None = None) -> RenderedForm

# services/options_loader.py:30 — OptionsLoader (unchanged consumer):
#   aiohttp fetch of FieldOption lists; TTL cache (source_ref, auth_ref);
#   single-flight; failure-safe (returns [] and logs — never raises)
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `RelationSpec` | `FormField.relation` | new optional field + model-validator | core/schema.py:44-100 |
| embed check | `resolve_rule_references()` | same resolution boundary | core/resolution.py:28 |
| YAML `relation:` | `YamlExtractor._parse_field()` | block parsing | extractors/yaml.py:267 |
| `x-relation` parse | jsonschema extractor prop loop | mirrors `x-options-source` | extractors/jsonschema.py:240 |
| `x-relation` emit | `JsonSchemaRenderer` field emission | extension key | renderers/jsonschema.py:510 (DYNAMIC_SELECT precedent) |
| shape checks | `FormValidator.validate_field()` | per-field type dispatch | services/validators.py:228 |

### Does NOT Exist (Anti-Hallucination)

- ~~Any relational `FieldType`~~ (`MANY_TO_ONE`, `RELATION`, `REFERENCE`,
  `FOREIGN_KEY`) — no such enum members, and this feature must NOT add any.
- ~~`core/relations.py` / `RelationSpec` / `EntityRef`~~ — created BY this
  feature (Module 1); do not import before Module 1 lands.
- ~~`OptionsSource.target_entity` / `.relation_kind` / `.cardinality`~~ —
  `OptionsSource` has exactly the 7 fields listed above and stays that way.
- ~~A DB-table-schema → FormSchema extractor with FK awareness~~ —
  `DatabaseFormTool` (tools/database_form.py:76) dispatches registered
  `AbstractFormService`s fetching *stored form definitions*; extractors/
  contains only `jsonschema.py`, `pydantic.py`, `tool.py`, `yaml.py`.
- ~~An Odoo renderer or toolkit~~ — nothing Odoo-related exists in the repo.
- ~~Server-side paginated option search~~ — `OptionsLoader` fetches full
  snapshot lists only.
- ~~`FormField.is_relational`~~ — does not exist yet; added by Module 2.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Aspect composition on `FormField` — `relation` sits beside `constraints`
  / `options_source` / `depends_on`; follow their optional-with-None style.
- `x-*` extension keys in JSON Schema — mirror the `x-options-source`
  handling (extractors/jsonschema.py:240-253) for `x-relation`, both
  directions.
- Renderer no-op convention — `XFormsRenderer` documents ignoring
  `style`/`prefilled` in its docstring; do the same for `relation` in the
  six untouched renderers (docstring note only, no code).
- Resolution-boundary validation — form-level checks that need the whole
  field tree live where `resolve_rule_references` runs (core/resolution.py),
  not in per-field Pydantic validators.
- Pydantic v2 `model_config = ConfigDict(extra="forbid")` on all new models;
  Google-style docstrings; async signatures preserved.

### Known Risks / Gotchas

- **`extra="forbid"` + old readers**: a deployed pre-FEAT-456
  parrot-formdesigner will REJECT schemas that carry `relation`. Forward
  compatibility is one-directional — note in release notes; acceptable per
  the brainstorm's migration-allowed decision.
- **Illegal combinations must fail loudly**: the aspect approach makes
  nonsense representable (relation on BOOLEAN); the model-validator is the
  only guard — its error messages must name `field_id` and the violated
  rule (test-covered).
- **Relational field with no options and no source** (reference mode) is
  legal: relation semantics matter to Odoo/DB consumers even when the web
  select is empty. Renderers render the empty select and log a warning —
  follow the `OptionsLoader` degrade-never-raise convention.
- **`inverse_field` check placement**: per-field Pydantic validators cannot
  see the whole form; putting the existence check anywhere but the
  resolution pass either misses it or duplicates traversal.
- **Unknown namespaces are allowed by design** — consumers ignore what they
  don't recognize; do not add namespace validation.
- **Byte-identical regression**: the "renderers unchanged" criterion is
  strict — resist the temptation to sneak `data-relation-*` attributes into
  HTML5 in this feature (open question §8; decide separately).

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `pydantic` | `>=2.0` (already in project) | RelationSpec/EntityRef models + validators |

No new dependencies.

---

## 8. Open Questions

> Resolved items were decided in the brainstorm
> (`sdd/proposals/formbuilder-fieldtype-cardinality.brainstorm.md`) and are
> reflected in the spec body — do not re-open.

- [x] Modeling approach: new FieldTypes vs OptionsSource extension vs
      orthogonal aspect — *Resolved in brainstorm*: Option C — orthogonal
      `FormField.relation: RelationSpec` aspect.
- [x] One2many semantics — *Resolved in brainstorm*: reuse
      `ARRAY`+`item_template` (embed mode) with `inverse_field`; references
      covered by `cardinality="many", mode="reference"`.
- [x] Server-side autocomplete for large tables in v1 — *Resolved in
      brainstorm*: no — v1 uses the existing OptionsSource/OptionsLoader
      snapshot; paginated search is a later feature.
- [x] Referenced-ID existence validation — *Resolved in brainstorm*: no in
      v1 — shape only (scalar ID / list of IDs); existence is the target
      system's job.
- [x] Persisted-schema migration acceptable? — *Resolved in brainstorm*:
      yes, permitted — though Option C requires none (optional field,
      default None).
- [ ] Should `PydanticExtractor`/`ToolExtractor` infer relations from type
      hints (e.g. a field typed as another model) in a later phase? —
      *Owner: Jesus Lara* (deferred; does not block v1)
- [ ] `EntityRef` namespace catalog (`odoo`, `db`, `api`, `formdesigner`):
      free documentation or exported constants? — *Owner: Jesus Lara*
      (spec default: documented conventions only, field stays `str`;
      revisit if consumers proliferate)
- [ ] Should HTML5Renderer emit `data-relation-*` attributes (like
      `data-depends-on`) already in v1, or wait for the autocomplete
      feature? — *Owner: Jesus Lara* (spec default: no — byte-identical
      criterion holds; revisit with the autocomplete feature)
- [ ] `on_delete` semantics (restrict/cascade/set_null): enforcement or
      passthrough hint? — *Owner: Jesus Lara* (spec default: passthrough
      hint only in v1, consumers interpret; field exists in RelationSpec)

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-24 | Jesus Lara | Initial draft from brainstorm (Option C) |
