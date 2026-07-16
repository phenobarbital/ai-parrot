---
type: Wiki Overview
title: 'Brainstorm: Form Designer — Conditional Sections (Pre/Post Dependencies)'
id: doc:sdd-proposals-formdesigner-conditional-sections-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: AI-Parrot's form designer (`parrot-formdesigner`) already models **pre-dependencies**
relates_to:
- concept: mod:parrot.forms
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Form Designer — Conditional Sections (Pre/Post Dependencies)

**Date**: 2026-06-11
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

AI-Parrot's form designer (`parrot-formdesigner`) already models **pre-dependencies**
in the schema: `DependencyRule` (`conditions` + `logic` + `effect`) can be attached to
`FormField`, `FormSubsection`, and `FormSection`, and the JSON Schema renderer serializes
them as `x-depends-on` / `x-section-depends-on` / `x-subsection-depends-on`. However:

1. **The model exists only because forms are *imported* from other platforms.** There is
   **no authoring infrastructure** — when a form is *built* inside AI-Parrot (via
   `CreateFormTool`, `EditToolkit`, the control registry, helpers), nothing lets an
   author *define*, *validate*, or *edit* dependencies. The capability is read-but-not-writable.

2. **The boolean logic is limited.** `DependencyRule.logic` is `Literal["and", "or"]`.
   The requirement calls for **XOR** and **NOT** as well.

3. **Dependencies can only show/hide/require/disable.** There is no notion of an
   **operation/calculation** — using the *current value* of a referenced `field_id` to
   compute or set another control's value (calculated/derived fields).

4. **There are no post-dependencies.** Nothing models how a control's *answered value*
   affects controls declared **after** it (set/calc a target value, reload its options,
   show/hide/require it, or cascade-clear dependents).

**Who is affected**: form authors (humans and LLMs building forms at runtime), every
renderer backend (which must interpret or ignore the new declarations), and server-side
submission/validation (which must evaluate rules authoritatively when a renderer can't).

## Constraints & Requirements

- **Backward compatibility is mandatory.** Existing `depends_on` rules (`logic: and|or`,
  `effect: show|hide|require|disable`) and imported forms must keep validating and rendering
  unchanged. New fields must be additive and optional.
- **Schema is always declarative.** Rules must remain expressible purely in the schema/JSON
  so any backend/renderer can interpret *or ignore* them ("operaciones de visualización/cálculo
  son menester de los renderers").
- **Dual evaluation.** The schema is the source of truth for clients; AI-Parrot must *also*
  provide an **optional Python evaluator** for authoritative server-side resolution at
  validation/submission time ("ambos según uso").
- **Pydantic-first, async-first**, `extra="forbid"` on models (consistent with current
  `FormField`/`FormSubsection`/`FieldConstraints`).
- **Logic shape is flat for v1**: extend `logic` to `and|or|xor|not`; a nested boolean tree
  is explicitly deferred to a future capability.
- **No new heavy runtime dependency** unless an option's value clearly justifies it.
- **Cycle safety**: the existing circular-dependency detector must be extended to cover
  `post_depends` edges and operation references (a `post_depends` can create new graph edges).

---

## Options Explored

### Option A: In-place extension of the formdesigner models + authoring infrastructure (+ optional evaluator)

Extend the **existing** `parrot_formdesigner.core` models rather than introducing a parallel
system. Concretely:

- Widen `DependencyRule.logic` to `Literal["and", "or", "xor", "not"]` (additive, default stays `"and"`).
- Add a new **`DependencyOperation`** model (copy/assign, arithmetic, string/date, lookup/aggregation)
  and an optional `operations: list[DependencyOperation] | None` on the rule (or on a new
  `post_depends` block), so a rule can both *gate* visibility and *compute* a value from the
  referenced `field_id`'s current value.
- Add a new **`PostDependency`** model and a `post_depends: list[PostDependency] | None`
  attribute to `FormField` (and optionally `FormSubsection`/`FormSection`): a forward mirror of
  `depends_on` declaring effects on *later* controls — `set`/`calc`, `reload_options`,
  `show`/`hide`/`require`, and `cascade_clear`.
- **Authoring infra** (the real gap): rule-validation in `FormValidator` (references resolve to
  real `field_id`s, pre/post ordering, type-compatible operators, no cycles incl. post edges);
  new `EditToolkit` methods (`add_dependency`, `update_dependency`, `add_post_dependency`, …) and
  `CreateFormTool` prompt/schema coverage; control-registry metadata exposing which
  operators/effects/operations each `FieldType` supports; and builder helpers/snippets.
- **Optional evaluator**: a small `RuleEvaluator` service that, given a `FormSchema` + current
  answers, resolves visibility/required/computed values server-side; renderers keep emitting
  `x-depends-on` / a new `x-post-depends` as client hints.

✅ **Pros:**
- Smallest blast radius; reuses every existing model, renderer extension point, and the
  circular-dependency DFS already in `FormValidator`.
- Fully backward-compatible — all additions are optional fields with safe defaults.
- Directly closes the stated gap (authoring), which no library can provide for us.
- `post_depends` as an explicit attribute matches the chosen data model and is trivially
  serializable as `x-post-depends` by existing renderers.

❌ **Cons:**
- Two related-but-separate constructs (`depends_on` + `post_depends`) can drift; needs clear
  docs and shared sub-models to stay consistent.
- Flat `logic` with `xor/not` is less expressive than a nested tree (accepted: deferred).
- The operations vocabulary is custom code we must validate and maintain.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` (v2, already a dep) | New models (`DependencyOperation`, `PostDependency`), validators | No new dependency |
| `python-dateutil` *(verify if already vendored)* | Date arithmetic for string/date operations (age, days-between) | Only if date ops land in v1; stdlib `datetime` may suffice |

🔗 **Existing Code to Reuse:**
- `packages/parrot-formdesigner/src/parrot_formdesigner/core/constraints.py` — `ConditionOperator`, `FieldCondition`, `DependencyRule` (extend `logic` here).
- `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` — `FormField`/`FormSubsection`/`FormSection` (`depends_on` already present; add `post_depends`).
- `packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py` — `FormValidator._detect_circular_dependencies` (extend graph to post edges + operation refs).
- `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/jsonschema.py` — `x-depends-on` emission at line 411 (add `x-post-depends`).
- `packages/parrot-formdesigner/src/parrot_formdesigner/tools/edit_toolkit.py` — `EditToolkit` (add dependency-editing methods).
- `packages/parrot-formdesigner/src/parrot_formdesigner/controls/registry.py` — `FieldControlMetadata` / `register_field_control` (add capability metadata).
- `packages/parrot-formdesigner/src/parrot_formdesigner/tools/field_helpers.py` — `get_form_field_schema_snippets`, `list_supported_form_field_types` (add rule snippets).

---

### Option B: Dedicated unified `RuleGraph` engine (form-level `rules` block)

Introduce a single form-level `rules` construct (`source` → `target` → `effect`/`operation`)
plus a `RuleGraph`/`RuleEngine` service. `depends_on` and `post_depends` become **derived views**
(computed indexes) over the unified rule set rather than per-element attributes.

✅ **Pros:**
- One canonical place for all conditional logic; pre/post are just edge directions.
- Natural home for a powerful evaluator, topological ordering, and cascade resolution.
- Easier to reason about global properties (cycles, unreachable fields, ordering).

❌ **Cons:**
- Larger refactor; diverges from the per-element `depends_on` already shipped and imported.
- Backward-compat shim required to keep emitting `x-depends-on` from a different internal model.
- Contradicts the chosen data model (user picked an explicit `post_depends` **attribute**, not a derived view).
- Higher coordination cost across renderers, extractors, storage, and tools.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `networkx` *(optional)* | Dependency graph, topological sort, cycle detection | Heavyweight for what a small DFS already does |
| `pydantic` (v2) | Unified `Rule`/`RuleGraph` models | Already a dep |

🔗 **Existing Code to Reuse:**
- Same modules as Option A, but mostly *rewritten/wrapped* rather than extended.
- `packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py` — graph logic generalized into a `RuleGraph`.

---

### Option C: Delegate evaluation to an external expression language (JSONLogic / CEL)

Keep thin schema attributes but express conditions/operations as an embedded expression
language — e.g. **JSONLogic** or **Google CEL** — and evaluate via a library on the server,
shipping the raw expression to clients as a hint.

✅ **Pros:**
- Very expressive (arbitrary boolean trees, arithmetic, string/date funcs) with little custom evaluator code.
- A documented, portable expression format; some front-ends already speak JSONLogic.

❌ **Cons:**
- Opaque to **authoring/validation** — the exact gap we must close. Validating that an arbitrary
  expression only references real `field_id`s, is type-safe, and is acyclic is *harder*, not easier.
- Breaks the structured `conditions/operator/value` shape that imported forms already use; needs a translation layer.
- New runtime dependency; CEL/JSONLogic Python libs vary in maturity and may not match JS-side semantics, risking render/eval divergence.
- Overkill for the v1 flat `and/or/xor/not` + bounded operation vocabulary.

📊 **Effort:** Medium (eval) but High (authoring/validation + migration)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `json-logic-py` / `panzi-json-logic` | Evaluate JSONLogic expressions in Python | Maturity varies — **verify** package + version before use |
| `cel-python` | Google CEL evaluation | Heavier; semantics must match any JS client |

🔗 **Existing Code to Reuse:**
- Minimal — mostly a new `expression` field + adapters; most existing `DependencyRule` plumbing would be bypassed.

---

## Recommendation

**Option A** is recommended because:

- The pain point is **authoring**, not expressiveness. The schema already carries `depends_on`;
  what's missing is the infrastructure to *define/validate/edit* rules at build time. Only
  custom, in-package work closes that — a library (Option C) can't.
- It is the **only fully backward-compatible** path: every change is an additive, optional model
  field with a safe default, so imported forms and existing renderers are untouched.
- It matches every design decision already made: `post_depends` as an **explicit new attribute**,
  flat `logic` with `xor/not` now (nested tree later), the full operation vocabulary
  (copy / arithmetic / string-date / lookup-aggregation), and **dual evaluation** (declarative
  schema + optional Python `RuleEvaluator`).
- It reuses the existing circular-dependency DFS, the renderer `x-` extension mechanism, the
  control registry, and `EditToolkit` — so the work is mostly *extension*, not *invention*.

What we trade off: two parallel constructs (`depends_on` + `post_depends`) that must be kept
consistent, and a bounded custom operation vocabulary to maintain. Option B's unified graph is
cleaner in theory but contradicts the chosen `post_depends`-attribute model and is a high-effort
refactor of shipped, imported-form-compatible code. We can still adopt B's *evaluator* ideas
(topological ordering, cascade resolution) inside Option A's optional `RuleEvaluator` without the refactor.

---

## Feature Description

### User-Facing Behavior

A form author (human via tools, or an LLM via `CreateFormTool`/`EditToolkit`) can:

- Attach a **pre-dependency** (`depends_on`) to any field, subsection, or section, combining
  conditions with `and` / `or` / **`xor`** / **`not`**, with effect `show` / `hide` /
  `require` / `disable`.
- Attach **operations** to a dependency so a target control's value is **computed from the
  current value** of referenced fields — copy/assign, arithmetic (sum, subtract, %, …),
  string/date (concat, format, age, days-between), and lookup/aggregation (external tool lookup,
  or sum/count/avg over arrays/repeated sections).
- Attach a **post-dependency** (`post_depends`) to a control declaring how *its answered value*
  affects controls **after** it: `set`/`calc` a target value, `reload_options`/fetch on the
  target, `show`/`hide`/`require` the target, or `cascade_clear` dependents on change.
- Get **immediate authoring feedback**: invalid references, forward/backward ordering violations
  (a `depends_on` may only reference earlier fields; a `post_depends` only later ones),
  type-incompatible operators, and cycles are reported when building/editing — not at runtime.

The end user filling the form experiences progressive disclosure (sections/fields appear,
hide, become required), auto-computed fields, and cascading option reloads — as interpreted by
whichever renderer/backend is in use. Renderers remain free to interpret or ignore any rule.

### Internal Behavior

- **Models** (`parrot_formdesigner.core`): `DependencyRule.logic` widened to `and|or|xor|not`;
  new `DependencyOperation` (op kind + operands referencing `field_id`s + target); new
  `PostDependency` + `post_depends` attribute on `FormField` (and optionally container levels).
- **Validation** (`FormValidator`): new rule-integrity pass — reference existence, pre/post
  ordering, operator/type compatibility, and an extended circular-dependency graph that adds
  `post_depends` and operation edges to the existing DFS.
- **Authoring tools**: `EditToolkit` gains dependency CRUD methods; `CreateFormTool` learns the
  rule schema; control registry advertises per-`FieldType` supported operators/effects/operations;
  `field_helpers` exposes rule snippets/builders.
- **Renderers**: `JsonSchemaRenderer` (and peers as feasible) emit `x-post-depends` and
  serialize operations alongside the existing `x-depends-on`.
- **Optional evaluator** (`RuleEvaluator` service): given a schema + answers, resolves
  visibility/required state and computed values server-side (topological order, cascade), used at
  validation/submission time; clients can rely on it or on the emitted hints.

### Edge Cases & Error Handling

- **Cycles** spanning `depends_on` ↔ `post_depends` ↔ operations → rejected by the extended detector.
- **Ordering violations** (`depends_on` referencing a later field, or `post_depends` targeting an
  earlier one) → validation error at authoring time.
- **Type mismatches** (e.g. `gt` on a non-numeric, arithmetic op on a text field) → validation error.
- **Missing/empty referenced values** during evaluation → operation yields a safe null/no-op; the
  rule must not crash submission.
- **Unknown operator/effect/op kind** from an imported form → preserved in schema but flagged;
  renderers ignore what they don't understand (forward-compatible).
- **Lookup/aggregation op failure** (external tool error) → degrade to no-op + recorded error,
  never block render.

---

## Capabilities

### New Capabilities
- `form-rule-logic-xor-not`: extend `DependencyRule.logic` to `and|or|xor|not` (flat; nested tree deferred).
- `form-rule-operations`: `DependencyOperation` model — copy/assign, arithmetic, string/date, lookup/aggregation — computing values from referenced field values.
- `form-postdepends`: `PostDependency` model + `post_depends` attribute (forward effects: set/calc, reload-options/fetch, show/hide/require, cascade-clear).
- `form-rule-authoring`: rule validation (refs, ordering, types, cycles), `EditToolkit` dependency CRUD, `CreateFormTool` coverage, control-registry capability metadata, and helper/snippet builders.
- `form-rule-evaluator`: optional server-side `RuleEvaluator` service (authoritative visibility/required/computed resolution) + renderer hints.

### Modified Capabilities
- Existing `depends_on` / `DependencyRule` (constraints model) — widened logic, optional operations.
- `FormValidator` circular-dependency detection — generalized to include post/operation edges.
- `JsonSchemaRenderer` (and other renderers) — emit `x-post-depends` + serialized operations.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot_formdesigner/core/constraints.py` | modifies | Widen `DependencyRule.logic`; add `DependencyOperation`. |
| `parrot_formdesigner/core/schema.py` | extends | Add `post_depends` to `FormField` (and maybe `FormSubsection`/`FormSection`). |
| `parrot_formdesigner/services/validators.py` | modifies | New rule-integrity pass; extend cycle DFS to post/operation edges. |
| `parrot_formdesigner/renderers/jsonschema.py` | extends | Emit `x-post-depends` + serialized operations. |
| Other renderers (`html5`, `adaptivecard`, `telegram`, `pdf`, `xforms`, `audio`) | depends on | Optionally interpret new declarations; safe to ignore. |
| `parrot_formdesigner/tools/edit_toolkit.py` | extends | Dependency/post-dependency CRUD methods. |
| `parrot_formdesigner/tools/create_form.py` | extends | Rule schema in generation prompt/contract. |
| `parrot_formdesigner/controls/registry.py` | extends | Per-`FieldType` supported operators/effects/operations metadata. |
| `parrot_formdesigner/tools/field_helpers.py` | extends | Rule/operation snippets + builders. |
| `parrot_formdesigner/extractors/yaml.py`, `jsonschema.py` | depends on | Parse `post_depends`/operations on import (round-trip). |
| `parrot.forms` (legacy re-exports) | depends on | Re-export new public symbols for backward-compat imports. |

---

## Code Context

### User-Provided Code

```json
// Source: user-provided (depends_on example, JSON Schema form of a pre-dependency)
"depends_on": {
    "conditions": [
        {
            "field_id": "field_9050",
            "operator": "eq",
            "value": "Compliance Audit"
        }
    ],
    "logic": "and",
    "effect": "show"
}
```

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/parrot-formdesigner/src/parrot_formdesigner/core/constraints.py
class ConditionOperator(str, Enum):                       # line 129
    EQ="eq"; NEQ="neq"; GT="gt"; LT="lt"; GTE="gte"; LTE="lte"
    IN="in"; NOT_IN="not_in"; IS_EMPTY="is_empty"; IS_NOT_EMPTY="is_not_empty"   # 132-141

class FieldCondition(BaseModel):                          # line 144
    field_id: str                                         # 153
    operator: ConditionOperator                           # 154
    value: Any = None                                     # 155

class DependencyRule(BaseModel):                          # line 158
    conditions: list[FieldCondition]                      # 167
    logic: Literal["and", "or"] = "and"                   # 168  ← widen to add "xor","not"
    effect: Literal["show","hide","require","disable"] = "show"  # 169

class FieldConstraints(BaseModel):                        # line 17 (extra="forbid")
    # min/max length, min/max value, step, pattern(+ ReDoS guard), min/max items,
    # allowed_mime_types, max_file_size_bytes, scale_min/max/step, anchor_labels

# From packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
class FormField(BaseModel):                               # line 24 (extra="forbid")
    field_id: str                                         # 50
    field_type: FieldType                                 # 51
    depends_on: DependencyRule | None = None              # 61  ← add post_depends sibling
    children: list[FormField] | None = None               # 62
    item_template: FormField | None = None                # 63
    meta: dict[str, Any] | None = None                    # 64
# FormField.model_rebuild()                               # line 68 (self-referential)

class FormSubsection(BaseModel):                          # line 71
    subsection_id: str; fields: list[FormField]           # 91,94
    depends_on: DependencyRule | None = None              # 95

class FormSection(BaseModel):                             # line 102
    section_id: str; fields: list[SectionItem]            # 121,124
    depends_on: DependencyRule | None = None              # 125
    def iter_fields(self) -> Iterator[FormField]: ...     # 128 (flattens subsections)
# SectionItem = Union[FormField, FormSubsection]          # line 99

# From packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py
class FormValidator:                                      # line 91
    async def validate(self, form, data, *, locale="en") -> ValidationResult   # 112 (calls cycle check @135)
    async def validate_field(self, field, value, *, all_data=None, locale) -> list[str]  # 179
    def detect_circular_dependencies(self, form) -> list[str]                   # ~775 (public wrapper)
    def _detect_circular_dependencies(self, form: FormSchema) -> list[str]      # 777 (DFS; only walks depends_on today)

# From packages/parrot-formdesigner/src/parrot_formdesigner/controls/registry.py
class FieldControlMetadata(BaseModel):                    # line 36 (extra="forbid")
    type:str; label:str; description:str; category:str; icon:str
    snippet:dict[str,Any]; render_hint:str; supports_constraints:bool; is_container:bool=False
def register_field_control(field_type, *, label, description, category, icon,
                           snippet, render_hint, supports_constraints, is_container=False) -> None  # 70
def get_controls() -> list[FieldControlMetadata]          # 116
def iter_controls() -> Iterator[FieldControlMetadata]     # 126

# From packages/parrot-formdesigner/src/parrot_formdesigner/tools/edit_toolkit.py
class EditToolkit(AbstractToolkit):                       # line 49
    async def add_field(...)   # 320   async def update_field(...)  # 281
    async def add_section(...) # 391   async def update_section(self, section_id, patch) # 426
    async def move_field(...)  # 459   async def remove_field(self, section_id, field_id) # 361
    # NOTE: no method edits depends_on / post_depends today → authoring gap

# From packages/parrot-formdesigner/src/parrot_formdesigner/tools/field_helpers.py
def list_supported_form_field_types() -> list[str]        # 250
def get_form_field_schema_snippets() -> dict[str, dict[str, Any]]  # 256

# From packages/parrot-formdesigner/src/parrot_formdesigner/renderers/jsonschema.py
# prop["x-depends-on"] = field.depends_on.model_dump()    # line 411  ← add x-post-depends nearby
```

#### Verified Imports
```python
# Confirmed public API (parrot_formdesigner.core re-exports):
from parrot_formdesigner.core import (
    FormField, FormSection, FormSubsection, FormSchema,
    FieldType, LocalizedString,
    ConditionOperator, FieldCondition, DependencyRule, FieldConstraints,
)
from parrot_formdesigner.services import FormValidator, ValidationResult
from parrot_formdesigner.controls import register_field_control, get_controls, iter_controls, FieldControlMetadata
from parrot_formdesigner.tools import EditToolkit, CreateFormTool, get_form_field_schema_snippets, list_supported_form_field_types
# Backward-compat: `from parrot.forms import FormField, DependencyRule, ...` (legacy re-export)
```

#### Key Attributes & Constants
- `DependencyRule.logic` → `Literal["and","or"]` (constraints.py:168) — to widen.
- `DependencyRule.effect` → `Literal["show","hide","require","disable"]` (constraints.py:169).
- `FormField.depends_on` → `DependencyRule | None` (schema.py:61) — `post_depends` sibling target.
- `FormSubsection.depends_on` (schema.py:95), `FormSection.depends_on` (schema.py:125).

…(truncated)…
