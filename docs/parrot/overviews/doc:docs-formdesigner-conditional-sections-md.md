---
type: Wiki Overview
title: 'Form Designer — Conditional Sections: Pre/Post Dependencies'
id: doc:docs-formdesigner-conditional-sections-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This document is the authoritative reference for the conditional-logic system
relates_to:
- concept: mod:parrot.forms
  rel: mentions
---

# Form Designer — Conditional Sections: Pre/Post Dependencies

> **Feature**: FEAT-234  
> **Applies to**: `parrot-formdesigner` >= (version containing FEAT-234)

This document is the authoritative reference for the conditional-logic system
in Form Designer.  It covers:

- **Pre-dependencies** (`depends_on`) — a field controlling its own
  visibility/required state based on values of earlier fields.
- **Operations** (`DependencyOperation`) — computed/derived values.
- **Post-dependencies** (`post_depends`) — a field triggering effects on
  *other* fields.
- Authoring via `EditToolkit` and `get_dependency_rule_snippets`.
- Optional server-side resolution via `RuleEvaluator`.

---

## 1. Pre-dependencies (`FormField.depends_on`)

A pre-dependency (`DependencyRule`) decides whether the *owning* field is
visible, required, or disabled based on the current values of fields that
appear **earlier** in the form.

```python
from parrot_formdesigner.core import (
    DependencyRule, FieldCondition, ConditionOperator, DependencyOperation,
)

# Simple show/hide rule
rule = DependencyRule(
    conditions=[
        FieldCondition(field_id="has_dependents", operator=ConditionOperator.EQ, value="yes")
    ],
    logic="and",
    effect="show",   # "show" | "hide" | "require" | "disable"
)
```

### 1.1 Logic gates

| `logic` | Semantics |
|---------|-----------|
| `"and"` | All conditions must be true (default). |
| `"or"` | At least one condition must be true. |
| `"xor"` | Exactly one condition must be true. |
| `"not"` | Negates the AND-combination of conditions (**v1 default** per spec §8). |

> **NOT semantics**: `"not"` evaluates `not all(conditions)`.  It is *not*
> a prefix NOT on a single condition — it negates the whole group.

```python
# XOR: field only shown when exactly one category is selected
DependencyRule(
    conditions=[
        FieldCondition(field_id="cat_a", operator=ConditionOperator.EQ, value="selected"),
        FieldCondition(field_id="cat_b", operator=ConditionOperator.EQ, value="selected"),
    ],
    logic="xor",
    effect="show",
)
```

### 1.2 Effects

| `effect` | What happens when the rule fires |
|----------|----------------------------------|
| `"show"` | Field becomes visible. |
| `"hide"` | Field is hidden. |
| `"require"` | Field becomes required. |
| `"disable"` | Field is hidden (v1: surfaced as not-visible). |

### 1.3 Supported `ConditionOperator` values

`eq` · `neq` · `gt` · `lt` · `gte` · `lte` · `in` · `not_in` ·
`is_empty` · `is_not_empty`

Numeric operators (`gt`/`lt`/`gte`/`lte`) require the referenced field to hold
a coercible-to-float value; a non-numeric value evaluates to `False`
(safe no-op).

---

## 2. Operations (`DependencyOperation`)

An *operation* computes a derived value and writes it to a target field.
Operations can appear in two places:

1. **Inline in a `DependencyRule`** — applied when the rule fires.
2. **In a `PostDependency`** — for `effect="set"` or `effect="calc"`.

```python
from parrot_formdesigner.core import DependencyOperation

op = DependencyOperation(
    op="multiply",            # see table below
    operands=["price", "qty"],  # field_ids
    target="total",           # field_id to write the result to
    options=None,             # optional extra config (e.g. sep, template, unit)
)
```

### 2.1 Operation kinds

| `op` | Description | Notable `options` |
|------|-------------|-------------------|
| `"copy"` | Copy first operand value to target. | — |
| `"add"` | Sum of all operand values. | — |
| `"subtract"` | First operand minus remainder. | — |
| `"multiply"` | Product of all operand values. | — |
| `"divide"` | First operand divided by remainder. Division by zero → no-op. | — |
| `"percent"` | `base * pct / 100` (operands[0] = base, operands[1] = percent). | — |
| `"concat"` | String concatenation of all operands. | `sep` (separator string) |
| `"format"` | Positional string template. | `template` (`"{0} {1}"`) |
| `"date_diff"` | Days (or weeks) between two ISO date operands. | `unit` (`"days"` / `"weeks"`) |
| `"lookup"` | Server-side table lookup (see open questions below). | — |
| `"aggregate"` | Numeric aggregate over flat operand list. | `fn` (`"sum"` / `"avg"` / `"min"` / `"max"` / `"count"`) |

### 2.2 Inline operation example (arithmetic)

```python
from parrot_formdesigner.core import DependencyRule, FieldCondition, ConditionOperator, DependencyOperation

DependencyRule(
    conditions=[],     # empty = unconditional
    logic="and",
    effect="show",
    operations=[
        DependencyOperation(
            op="add",
            operands=["base_salary", "bonus"],
            target="total_compensation",
        )
    ],
)
```

---

## 3. Post-dependencies (`FormField.post_depends`)

A post-dependency (`PostDependency`) makes the *owning* field trigger effects
on **other** (typically later) fields.  This is the "forward" direction —
`f1` controlling `f2`, `f3`, etc.

```python
from parrot_formdesigner.core import PostDependency, DependencyOperation

# When 'country' changes, reload 'city' options and clear 'zip'
PostDependency(
    target="city",
    effect="reload_options",  # see table below
)

PostDependency(
    target="zip",
    effect="cascade_clear",
)
```

### 3.1 Post-dependency effects

| `effect` | Description |
|----------|-------------|
| `"show"` | Make the target field visible. |
| `"hide"` | Hide the target field. |
| `"require"` | Make the target field required. |
| `"disable"` | Hide the target field (v1). |
| `"set"` | Write a value to the target field via an `operation`. `operation` is **required**. |
| `"calc"` | Compute and write a value; always fires (no condition check). `operation` is **required**. |
| `"reload_options"` | Signal that the target field's option list should be reloaded. |
| `"cascade_clear"` | Clear the target field's answer when this field changes. |

### 3.2 Conditions on post-dependencies

Post-dependencies MAY include their own `conditions` list (same format as
pre-dependencies).  When `conditions` is omitted, the rule fires whenever the
owning field has a non-empty answer.

### 3.3 Example: arithmetic `calc`

```python
PostDependency(
    target="total",
    effect="calc",
    operation=DependencyOperation(
        op="multiply",
        operands=["price", "qty"],
        target="total",
    ),
)
```

### 3.4 Constraints

- `post_depends` is only on `FormField` (not `FormSection` / `FormSubsection`)
  in v1.
- A `PostDependency` with `effect="set"` or `effect="calc"` **must** supply an
  `operation` — the Pydantic model validator raises `ValueError` otherwise.

---

## 4. End-to-end example

The following form has:

1. An `xor` pre-dependency (`amount_type` exactly one path active shows
   `fixed_amount` or `percentage_amount`).
2. An arithmetic operation computing `tax` = `price` × 0.21.
3. A `set` post-dependency cascading a computed `subtotal`.

```json
{
  "form_id": "invoice_line",
  "title": "Invoice Line",
  "sections": [
    {
      "section_id": "main",
      "fields": [
        { "field_id": "price",     "field_type": "number",  "label": "Unit Price" },
        { "field_id": "qty",       "field_type": "integer", "label": "Quantity" },
        {
          "field_id": "subtotal",
          "field_type": "number",
          "label": "Subtotal",
          "depends_on": {
            "conditions": [],
            "logic": "and",
            "effect": "show",
            "operations": [
              {
                "op": "multiply",
                "operands": ["price", "qty"],
                "target": "subtotal"
              }
            ]
          }
        },
        { "field_id": "amount_type", "field_type": "select", "label": "Amount Type",
          "options": [{"value": "fixed", "label": "Fixed"}, {"value": "pct", "label": "Percentage"}] },
        {
          "field_id": "fixed_amount",
          "field_type": "number",
          "label": "Fixed Amount",
          "depends_on": {
            "conditions": [
              { "field_id": "amount_type", "operator": "eq", "value": "fixed" }
            ],
            "logic": "and",
            "effect": "show"
          }
        },
        {
          "field_id": "percentage_amount",
          "field_type": "number",
          "label": "Percentage (%)",
          "depends_on": {
            "conditions": [
              { "field_id": "amount_type", "operator": "eq", "value": "pct" }
            ],
            "logic": "and",
            "effect": "show"
          }
        },
        {
          "field_id": "tax",
          "field_type": "number",
          "label": "VAT (21%)",
          "post_depends": []
        },
        {
          "field_id": "discount",
          "field_type": "number",
          "label": "Discount"
        }
      ]
    }
  ]
}
```

Python construction equivalent:

```python
from parrot_formdesigner.core import (
    DependencyOperation, DependencyRule, FieldCondition, ConditionOperator,
    FieldType, FormField, FormSchema, FormSection, PostDependency,
)

price = FormField(field_id="price", field_type=FieldType.NUMBER, label="Unit Price")

subtotal = FormField(
    field_id="subtotal",
    field_type=FieldType.NUMBER,
    label="Subtotal",
    depends_on=DependencyRule(
        conditions=[],
        logic="and",
        effect="show",
        operations=[
            DependencyOperation(op="multiply", operands=["price", "qty"], target="subtotal")
        ],
    ),
)

qty = FormField(
    field_id="qty",
    field_type=FieldType.INTEGER,
    label="Quantity",
    post_depends=[
        PostDependency(
            target="subtotal",
            effect="calc",
            operation=DependencyOperation(op="multiply", operands=["price", "qty"], target="subtotal"),
        )
    ],
)

form = FormSchema(
    form_id="invoice_line",
    title="Invoice Line",
    sections=[FormSection(section_id="main", fields=[price, qty, subtotal])],
)
```

---

## 5. Authoring via `EditToolkit`

The `EditToolkit` exposes five async methods for dependency CRUD:

```python
from parrot_formdesigner.tools import EditToolkit

toolkit = EditToolkit(form)

# Add a pre-dependency
await toolkit.add_dependency("subtotal", {
    "conditions": [{"field_id": "price", "operator": "neq", "value": None}],
    "logic": "and",
    "effect": "show",
})

# Update existing dependency (merge-patch)
await toolkit.update_dependency("subtotal", {"logic": "or"})

# Remove dependency
await toolkit.remove_dependency("subtotal")

# Add a post-dependency
await toolkit.add_post_dependency("qty", {
    "target": "subtotal",
    "effect": "calc",
    "operation": {"op": "multiply", "operands": ["price", "qty"], "target": "subtotal"},
})

# Remove a post-dependency by target
await toolkit.remove_post_dependency("qty", "subtotal")
```

All methods validate the rule via `FormValidator` (rule-integrity pass) before
applying.  Invalid rules return an error dict; the form is **not mutated**.

### 5.1 Rule capability metadata

The control registry exposes capability hints to guide authoring:

```python
from parrot_formdesigner.controls import get_controls

for ctrl in get_controls():
    print(ctrl.type, ctrl.supported_operators, ctrl.supported_operations)
```

`FieldControlMetadata` now carries:

| Field | Type | Description |
|-------|------|-------------|
| `supported_operators` | `list[str]` | Meaningful `ConditionOperator` values for this control. |
| `supported_effects` | `list[str]` | Applicable dependency effects. |
| `supported_operations` | `list[str]` | `DependencyOperation.op` values that make semantic sense. |

Empty list means "all values applicable" (extension controls default to `[]`).

### 5.2 Rule snippets

Quick-start skeletons for building rules:

```python
from parrot_formdesigner.tools import get_dependency_rule_snippets

snippets = get_dependency_rule_snippets()
# snippets["depends_on"]   — DependencyRule skeleton dict
# snippets["post_depends"] — list of PostDependency skeleton dicts
```

---

## 6. Server-side evaluation via `RuleEvaluator`

The `RuleEvaluator` is an **optional** authoritative Python evaluator.
Renderers (HTML5, Adaptive Card, JSON Schema) MAY interpret the rules
client-side; they may also ignore them if the client UI handles visibility
independently.

```python
import asyncio
from parrot_formdesigner.services import RuleEvaluator

evaluator = RuleEvaluator()
resolution = asyncio.run(evaluator.resolve(form, answers={"qty": 3, "price": 10}))

print(resolution.visible)   # dict[str, bool]  — True = visible
print(resolution.required)  # dict[str, bool]
print(resolution.computed)  # dict[str, Any]   — computed/operation results
print(resolution.cleared)   # list[str]        — cascade-cleared field ids
```

`RuleResolution` fields:

| Field | Type | Default |
|-------|------|---------|
| `visible` | `dict[str, bool]` | All `True` |
| `required` | `dict[str, bool]` | From `FormField.required` |
| `computed` | `dict[str, Any]` | `{}` |
| `cleared` | `list[str]` | `[]` |

---

## 7. YAML serialization

Pre/post-dependencies are fully supported in YAML forms:

```yaml
form_id: invoice_line
title: Invoice Line
sections:
  - section_id: main
    fields:
      - field_id: price
        field_type: number
        label: Unit Price
      - field_id: qty
        field_type: integer
        label: Quantity
        post_depends:
          - target: subtotal
            effect: calc
            operation:
              op: multiply
              operands: [price, qty]
              target: subtotal
      - field_id: subtotal
        field_type: number
        label: Subtotal
        depends_on:
          conditions:
            - field_id: price
              operator: neq
              value: null
          logic: and
          effect: show
          operations:
            - op: multiply
              operands: [price, qty]
              target: subtotal
```

---

## 8. JSON Schema rendering (`x-` extensions)

`JsonSchemaRenderer` emits `depends_on` and `post_depends` as vendor extensions
on each property:

```json
{
  "properties": {
    "subtotal": {
      "type": "number",
      "x-depends-on": { "conditions": [...], "logic": "and", "effect": "show" },
      "x-post-depends": [{ "target": "...", "effect": "..." }]
    }
  }
}
```

`JsonSchemaExtractor` reconstructs `DependencyRule` / `PostDependency` models
from these extensions on import (round-trip lossless).

> **Note**: Renderers that do not understand these extensions will silently
> ignore them.  The rendered schema remains a valid JSON Schema.

---

## 9. Open questions / Future work

The following behaviours are marked as **TODO(FEAT-234 open question)** in the
code and should be revisited in a future spec revision:

- **`reload_options` timing**: The server-side evaluator sets a sentinel value
  (`"__reload__"`) in `computed[target]` to signal that option reload is needed.
  The timing and mechanism for actually reloading options (e.g., async callback)
  is not yet specified.
- **ARRAY-operand aggregation scope**: The `aggregate` operation currently
  aggregates over a flat list of operand values.  Aggregating over repeated
  ARRAY row values (e.g., sum all values of a specific sub-field across rows)
  is a future extension.
- **Nested boolean condition trees**: v1 uses a flat list of conditions under a
  single `logic` gate.  Nested boolean trees (AND of ORs, etc.) are a Non-Goal
  in v1 (spec §1 Non-Goals) and may be addressed in a later feature.
- **`lookup` operation server-side**: The `lookup` operation produces `None`
  server-side (conservative no-op); the lookup table format and resolution
  mechanism are not yet defined.

---

## 10. Validation

Rule integrity is validated by `FormValidator.validate()` (or the standalone
`FormValidator.validate_rules()` / `check_schema()`):

- **Unknown references**: conditions, operation operands, and post-dep targets
  must reference existing `field_id` values.
- **Ordering violations**: `depends_on` conditions must reference earlier fields;
  `post_depends` targets must reference later fields.
- **Type compatibility**: numeric operators (`gt`/`lt`/`gte`/`lte`) must only
  be used on numeric field types.
- **Cycle detection**: the validator detects and rejects circular dependency
  graphs.

```python
from parrot_formdesigner.services import FormValidator

validator = FormValidator()
errors = validator.validate_rules(form)  # list[str] — empty = clean
```

---

## 11. Legacy `parrot.forms` re-exports

All new public symbols are re-exported from the `parrot.forms` backward-compat
shim:

```python
from parrot.forms import (
    DependencyOperation,
    PostDependency,
    RuleEvaluator,
    RuleResolution,
    get_dependency_rule_snippets,
)
```
