# Parity Suite — Golden Vectors Conformance Contract

This directory contains the **reference conformance suite** for FEAT-301
(Conditional Logic Engine).  The golden vectors in `vectors/*.json` define
the authoritative input → output mapping that **every evaluator** (Python,
JavaScript, native mobile) must produce identically.

---

## Motivation

FEAT-301 ships a server-side `RuleEvaluator` (Python) as the reference
implementation.  External consumers (the browser SPA's JS evaluator, native
mobile app evaluators, etc.) must reproduce the same results for the same
input.  Sharing static JSON vectors — rather than sharing code — ensures
cross-language conformance without coupling runtimes.

---

## Golden Vector Format

Each file in `vectors/` is a self-contained JSON vector:

```json
{
  "name": "short-unique-slug",
  "description": "Human-readable explanation of what this vector tests",
  "form": {
    "form_id": "...",
    "title": {"en": "..."},
    "sections": [
      {
        "section_id": "s1",
        "title": {"en": "..."},
        "fields": [
          {
            "field_id": "q1",
            "field_type": "text",
            "label": {"en": "..."}
          },
          {
            "field_id": "q2",
            "field_type": "text",
            "label": {"en": "..."},
            "depends_on": {
              "conditions": [
                {
                  "source": "field",
                  "field_id": "q1",
                  "operator": "eq",
                  "value": "yes"
                }
              ],
              "logic": "and",
              "effect": "show"
            }
          }
        ]
      }
    ]
  },
  "context": {
    "answers": {"q1": "yes"},
    "location_vars": {"store_type": "flagship"},
    "visit_context": {"visit_type": "audit"}
  },
  "expected": {
    "q2": {
      "effect": "show",
      "matched": true
    }
  }
}
```

### Field Descriptions

| Field | Type | Description |
|---|---|---|
| `name` | `string` | Unique kebab-case slug identifying this vector |
| `description` | `string` | Human description of what is being tested |
| `form` | `FormSchema` | Minimal form with at least one `depends_on` rule |
| `context.answers` | `object` | Map of `field_id → value` for submitted answers |
| `context.location_vars` | `object` | Map of Org Graph location variable `key → value` |
| `context.visit_context` | `object` | Map of visit metadata `key → value` |
| `expected` | `object` | Map of `field_id → {effect, matched}` for every field with `depends_on` |

### Condition Variants (`source` discriminator)

| `source` | Extra fields | Description |
|---|---|---|
| `"field"` | `field_id` | Condition over another field's answer |
| `"location_variable"` | `key` | Condition over an Org Graph location variable |
| `"visit_context"` | `key` | Condition over visit metadata |

### Operators (`operator`)

| Operator | Matches when |
|---|---|
| `eq` | `actual == value` |
| `neq` | `actual != value` |
| `gt` | `actual > value` (numeric) |
| `gte` | `actual >= value` (numeric) |
| `lt` | `actual < value` (numeric) |
| `lte` | `actual <= value` (numeric) |
| `in` | `actual` in `value` (list) |
| `not_in` | `actual` not in `value` (list) |
| `is_empty` | `actual` is `null`, `""`, `[]`, `{}`, or **key missing** |
| `is_not_empty` | `actual` is non-empty (key must be present and non-empty) |

### Key-Missing Semantics

When the source key is **absent** from the context (not present at all — not
`null`, not `""`):

- `is_empty` → `true`
- All other operators → `false` (no exception raised)

### Logic Combinators

| `logic` | Meaning |
|---|---|
| `"and"` | All conditions must be true (empty list → false) |
| `"or"` | At least one condition must be true (empty list → false) |

### Effects

| `effect` | Meaning |
|---|---|
| `"show"` | Field becomes visible (default outcome when rule fires) |
| `"hide"` | Field is hidden |
| `"require"` | Field becomes required |
| `"disable"` | Field is disabled (read-only) |

When a rule does **not** fire (conditions not met), the evaluator returns
`{"effect": "show", "matched": false}` — the field defaults to visible.

### Hidden-Field Exclusion (Downstream Masking)

When a field is resolved as `{"effect": "hide", "matched": true}`, its answer
is **excluded** from downstream condition evaluation (as if the key were absent).
This prevents stale values from silently activating downstream rules.

---

## Coverage Map

The 60 vectors cover:

| Category | Count |
|---|---|
| FieldRef × 10 operators | 12 |
| LocationVar × 10+ operators | 13 |
| VisitContext | 4 |
| AND / OR logic | 4 |
| All 4 effects (show/hide/require/disable) | 4 |
| Chained / nested rules (≥10) | 13 |
| Key-missing semantics | 5 |
| Hidden-field downstream exclusion | 2 |
| Cycle detection (fallback) | 1 |
| Legacy backward-compat (no source key) | 1 |
| Networkninja-style realistic vectors (≥5) | 5 |
| **Total** | **60** |

---

## Running the Suite

```bash
# From the ai-formdesigner repo root (or worktree):
source .venv/bin/activate
PYTHONPATH=$PWD/src python -m pytest tests/parity/ -v
```

Expected output: all tests pass with two assertions per vector (evaluator +
HTML5 embed), plus internal-consistency checks.

---

## Adding New Vectors

1. Create a new `tests/parity/vectors/<NN>_<slug>.json` file following the
   format above.
2. `expected` must cover **every** field in `form` that has a `depends_on`
   rule — the runner enforces this.
3. Re-run the suite to verify.
4. No changes to `test_golden_vectors.py` required — the runner is fully
   auto-discovering.

---

## Consuming from External Evaluators

External JS/native evaluators should:

1. Parse the `form` as a `FormSchema` (see schema documentation).
2. Build an `EvaluationContext` from `context`.
3. Walk fields in **topological order** (BFS/Kahn's algorithm on `depends_on`
   edges — see `LogicGraph`).
4. For each field with `depends_on`, evaluate the rule and record
   `{effect, matched}`.
5. **Mask hidden field answers** before evaluating downstream fields.
6. Assert result matches `expected` for each declared field.

The Python `RuleEvaluator` in `parrot_formdesigner.services.rule_evaluator`
is the reference implementation.  When in doubt, the Python result is
authoritative.

---

*Generated by FEAT-301 SDD Worker — 2026-06-11.*
