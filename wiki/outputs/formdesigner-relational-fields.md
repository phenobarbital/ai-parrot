# Form Designer — Relational Fields

> **Feature**: FEAT-456
> **Applies to**: `parrot-formdesigner` >= 0.11.0

This document is the authoritative reference for **relational fields** in
Form Designer — an orthogonal `FormField.relation` aspect that expresses
Many2one, Many2many, and One2many semantics (in Odoo terms) without
introducing new `FieldType` enum members or overloading `OptionsSource`.

---

## 1. Why an aspect, not new field types

`FormSchema` previously had no way to say "this SELECT's value is a
reference to a record in another entity", only "this SELECT has these
options". Relations model that missing semantic as a second, independent
aspect on `FormField` — exactly like `constraints`, `options_source`, and
`depends_on` already are:

```python
class FormField(BaseModel):
    ...
    options_source: OptionsSource | None = None
    depends_on: DependencyRule | None = None
    relation: RelationSpec | None = None   # NEW (FEAT-456)
    ...
```

A relational `SELECT` is still a `SELECT` — every existing renderer keeps
rendering it exactly as before. `relation=None` (the default) changes
nothing; persisted `FormSchema` documents from before this feature load,
render, and validate unchanged.

## 2. `EntityRef` and `RelationSpec`

```python
from parrot_formdesigner.core import EntityRef, RelationSpec

target = EntityRef(
    namespace="odoo",          # see "Namespace conventions" below
    entity="res.partner",      # target entity identifier within namespace
    key_field=None,            # None = target's default key
)

relation = RelationSpec(
    cardinality="one",         # "one" | "many"
    target=target,
    mode="reference",          # "reference" | "embed"
    display_field="name",      # optional: target field shown to users
    inverse_field=None,        # required when mode="embed"
    on_delete=None,            # "restrict" | "cascade" | "set_null" — hint only
    filters=None,              # optional, consumer-interpreted target filters
)
```

Both models use `extra="forbid"` — unknown keys raise, they are not
silently dropped.

### Namespace conventions (`EntityRef.namespace`)

Free-form by design — there is no central registry, and a consumer that
does not recognize a namespace simply ignores the relation. Documented
conventions:

| Namespace | `entity` holds |
|---|---|
| `"odoo"` | An Odoo model name, e.g. `"res.partner"`. |
| `"db"` | A database table, typically `schema.table`, e.g. `"public.customers"`. |
| `"api"` | An external API resource identifier. |
| `"formdesigner"` | Another parrot-formdesigner form's `form_id`. |

## 3. Legal combinations (enforced on `FormField`)

`FormField`'s model-validator rejects any combination outside this table,
naming the offending `field_id` in the error:

| Odoo concept | `field_type` | `relation` |
|---|---|---|
| Many2one | `SELECT` / `DYNAMIC_SELECT` / `TREE_SELECT` | `cardinality="one", mode="reference"` |
| Many2many | `MULTI_SELECT` / `TAGS` / `TRANSFER_LIST` | `cardinality="many", mode="reference"` |
| One2many | `ARRAY` + `item_template` | `cardinality="many", mode="embed", inverse_field=...` |

```python
FormField(
    field_id="flag", field_type=FieldType.BOOLEAN, label="Flag",
    relation=RelationSpec(cardinality="one", target=target),
)
# ValueError: Field 'flag': relation mode='reference', cardinality='one'
# requires field_type in ['dynamic_select', 'select', 'tree_select']
# (got 'boolean')
```

`FormField.is_relational` is a convenience read-only property
(`relation is not None`).

## 4. Embed mode (One2many) and `inverse_field`

One2many does **not** introduce a parallel embedded-row engine — it reuses
the existing `ARRAY` + `item_template` machinery. `relation.inverse_field`
must name a field somewhere inside the field's own `item_template` tree
(the child field pointing back to the parent record). Because per-field
Pydantic validators cannot see the whole form, this existence check runs
at the form-level resolution boundary, alongside
`resolve_rule_references()`:

```python
from parrot_formdesigner.core.resolution import resolve_rule_references

resolve_rule_references(form)
# ValueError: Field 'lines': relation.inverse_field 'nope' does not name
# any field in this field's item_template
```

## 5. `on_delete` — passthrough hint only

`RelationSpec.on_delete` (`"restrict"` / `"cascade"` / `"set_null"`) is
carried through untouched — parrot-formdesigner does not enforce it. It
exists for downstream consumers (e.g. a future Odoo renderer/toolkit) to
interpret.

## 6. Authoring: YAML

```yaml
fields:
  - field_id: customer
    type: select
    label: Customer
    relation:
      cardinality: one
      mode: reference
      target: {namespace: odoo, entity: res.partner}
      display_field: name
```

`YamlExtractor._parse_field` parses the `relation:` block strictly — a
malformed block (invalid `cardinality`, a `target` that is not a mapping,
etc.) raises naming the field, rather than silently degrading to a
plain (non-relational) field.

## 7. Authoring: JSON Schema (`x-relation`)

The JSON Schema extractor and `JsonSchemaRenderer` are symmetric — the
renderer emits, the extractor parses back losslessly:

```json
{
  "customer": {
    "type": "string",
    "title": "Customer",
    "x-field-type": "select",
    "x-relation": {
      "cardinality": "one",
      "mode": "reference",
      "target": {"namespace": "odoo", "entity": "res.partner"},
      "display_field": "name"
    }
  }
}
```

`JsonSchemaRenderer` is the **only** renderer that surfaces `relation` —
see the no-op convention below.

## 8. Renderer no-op convention

HTML5, Adaptive Card, XForms, PDF, Audio, and Telegram renderers all
**ignore** `FormField.relation` — a relational field renders exactly as
its `field_type` dictates, byte-identical to the same field without
`relation` (each renderer's `render()` docstring notes this explicitly,
the same convention `XFormsRenderer` already uses for `style`/`prefilled`).
Only `JsonSchemaRenderer` emits the `x-relation` extension.

## 9. Validation: shape only, no existence checks

`FormValidator` validates the **shape** of a reference-mode relational
submission — a scalar ID for `cardinality="one"`, a list of scalar IDs for
`cardinality="many"` — and nothing more. There is no I/O and no
existence check against the target system; verifying that a submitted ID
actually exists in `res.partner`, `public.tags`, etc. is the target
system's job, not parrot-formdesigner's.

Embed-mode (`mode="embed"`) values are untouched by relation-specific
validation — they flow through the pre-existing `ARRAY` recursive path.

## 10. Options fetching for reference-mode fields

Reference-mode relational fields use the existing `OptionsSource` /
`OptionsLoader` snapshot mechanism unchanged — there is no
paginated/autocomplete option search in v1. A relational field with
neither static `options` nor an `options_source` is legal (relation
semantics matter to non-web consumers even when the web select has
nothing to show); the renderer degrades to an empty select and logs a
warning, following `OptionsLoader`'s existing degrade-never-raise
convention.

## 11. Out of scope (v1)

- An Odoo renderer/toolkit that consumes `RelationSpec` — a separate
  follow-up feature.
- FK-aware DB-table-schema extraction into `FormSchema` — separate
  follow-up; today's `DatabaseFormTool` dispatches stored form
  definitions, it does not introspect table schemas.
- Server-side paginated option search/autocomplete.
- Referenced-ID existence validation.

## 12. Forward-compatibility caveat

`EntityRef` and `RelationSpec` both use `extra="forbid"`, and so does
`FormField`. Forward compatibility is **one-directional**: a
pre-FEAT-456 deployment of `parrot-formdesigner` will **reject** any
schema that carries a `relation` key on a field. Only newer readers can
load schemas produced by newer authors.
