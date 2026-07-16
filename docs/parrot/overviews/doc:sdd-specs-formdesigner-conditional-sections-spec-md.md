---
type: Wiki Overview
title: 'Feature Specification: Form Designer — Conditional Sections (Pre/Post Dependencies)'
id: doc:sdd-specs-formdesigner-conditional-sections-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: AI-Parrot's form designer (`parrot-formdesigner`) already models **pre-dependencies**
  in the
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

# Feature Specification: Form Designer — Conditional Sections (Pre/Post Dependencies)

**Feature ID**: FEAT-234
**Date**: 2026-06-11
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.4.0

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

AI-Parrot's form designer (`parrot-formdesigner`) already models **pre-dependencies** in the
schema: `DependencyRule` (`conditions` + `logic` + `effect`) can be attached to `FormField`,
`FormSubsection`, and `FormSection`, and the JSON Schema renderer serializes them as
`x-depends-on` / `x-section-depends-on` / `x-subsection-depends-on`. However, the capability is
**read-but-not-writable** and incomplete:

1. **The model exists only because forms are *imported* from other platforms.** There is **no
   authoring infrastructure** — when a form is *built* inside AI-Parrot (via `CreateFormTool`,
   `EditToolkit`, the control registry, helpers), nothing lets an author *define*, *validate*, or
   *edit* dependencies.
2. **Boolean logic is limited.** `DependencyRule.logic` is `Literal["and", "or"]`; the
   requirement calls for **XOR** and **NOT** as well.
3. **Dependencies can only show/hide/require/disable.** There is no notion of an
   **operation/calculation** — using the *current value* of a referenced `field_id` to compute or
   set another control's value (calculated/derived fields).
4. **There are no post-dependencies.** Nothing models how a control's *answered value* affects
   controls declared **after** it (set/calc a target value, reload its options, show/hide/require
   it, or cascade-clear dependents).

Affected: form authors (humans and LLMs building forms at runtime), every renderer backend (which
must interpret or ignore the new declarations), and server-side submission/validation (which must
evaluate rules authoritatively when a renderer can't).

### Goals
- Widen `DependencyRule.logic` to `and | or | xor | not` (flat), fully backward-compatible.
- Add a `DependencyOperation` model supporting copy/assign, arithmetic, string/date, and
  lookup/aggregation operations that compute values from referenced field values.
- Add a `PostDependency` model + `post_depends` attribute on `FormField` for forward effects
  (set/calc, reload-options/fetch, show/hide/require, cascade-clear).
- Provide **authoring infrastructure**: rule validation (refs resolve, pre/post ordering,
  type-compatible operators, no cycles incl. post/operation edges), `EditToolkit` dependency CRUD,
  `CreateFormTool` coverage, control-registry capability metadata, and helper/snippet builders.
- Provide an **optional server-side `RuleEvaluator`** that resolves visibility/required/computed
  values authoritatively at validation/submission time; renderers emit `x-post-depends` + serialized
  operations as client hints.
- Preserve full backward compatibility for existing/imported `depends_on` rules.

### Non-Goals (explicitly out of scope)
- **Nested boolean condition trees** — v1 keeps `logic` flat (`and|or|xor|not`); a recursive tree
  is a documented future capability.
- **A unified form-level `rules` engine** with `depends_on`/`post_depends` as derived views —
  rejected in brainstorm (Option B); we keep explicit per-element attributes. See
  `proposals/formdesigner-conditional-sections.brainstorm.md` Option B.
- **Delegating evaluation to an external expression language** (JSONLogic/CEL) — rejected in
  brainstorm (Option C) because it makes authoring/validation harder, not easier.
- **Full client-side reactive evaluation** — AI-Parrot ships the declarative schema + an optional
  Python evaluator; rich client reactivity is the renderer/front-end's responsibility.

---

## 2. Architectural Design

### Overview

Extend the **existing** `parrot_formdesigner.core` models in place (Option A) rather than
introducing a parallel system. The schema stays the declarative source of truth so any
backend/renderer may interpret or ignore rules; AI-Parrot *additionally* provides an optional
Python `RuleEvaluator` for authoritative server-side resolution (dual evaluation, resolved in
brainstorm). All schema changes are additive, optional fields with safe defaults, keeping
imported forms and existing renderers untouched.

Concretely:
- `DependencyRule.logic` widens to `Literal["and", "or", "xor", "not"]`.
- A new `DependencyOperation` model expresses copy/assign, arithmetic, string/date, and
  lookup/aggregation operations; rules/post-dependencies may carry `operations`.
- A new `PostDependency` model + `post_depends: list[PostDependency] | None` on `FormField`
  declares forward effects on later controls.
- `FormValidator` gains a rule-integrity pass and an extended circular-dependency graph that
  includes `post_depends` and operation edges.
- Authoring surfaces (`EditToolkit`, `CreateFormTool`, control registry, `field_helpers`) gain the
  ability to create/validate/edit rules.
- `JsonSchemaRenderer` emits `x-post-depends` + serialized operations alongside `x-depends-on`.

### Component Diagram
```
core/constraints.py                core/schema.py
  DependencyRule (logic+xor/not)     FormField.post_depends ─┐
  DependencyOperation  ──────────────┐                       │
  PostDependency  ───────────────────┤                       │
                                     ▼                        ▼
                          services/validators.py      renderers/jsonschema.py
                            FormValidator                 x-depends-on
                            ├─ rule-integrity pass        x-post-depends (NEW)
                            └─ _detect_circular_*  ◄─ extended (post+op edges)
                                     │
                                     ▼
                          services/rule_evaluator.py  (NEW, optional)
                            RuleEvaluator.resolve(form, answers)
                                     ▲
   Authoring surfaces ──────────────┘
     tools/edit_toolkit.py   (add/update dependency + post_dependency)
     tools/create_form.py    (rule schema coverage)
     controls/registry.py    (per-FieldType capability metadata)
     tools/field_helpers.py  (rule snippets / builders)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `DependencyRule` (`core/constraints.py:158`) | extends | Widen `logic`; optional `operations`. |
| `FieldCondition` / `ConditionOperator` (`core/constraints.py:144/129`) | reuses | Condition shape unchanged; reused by post-deps. |
| `FormField` (`core/schema.py:24`) | extends | Add `post_depends` attribute (sibling of `depends_on:61`). |
| `FormSubsection`/`FormSection` (`core/schema.py:71/102`) | depends on | Container-level `post_depends` deferred (see §8); their `depends_on` already exists. |
| `FormValidator` (`services/validators.py:91`) | modifies | Rule-integrity pass; extend `_detect_circular_dependencies:777`. |
| `JsonSchemaRenderer` (`renderers/jsonschema.py:411`) | extends | Emit `x-post-depends` + operations. |
| Other renderers (html5/adaptivecard/telegram/pdf/xforms/audio) | depends on | Optionally interpret; safe to ignore (pass-through). |
| `EditToolkit` (`tools/edit_toolkit.py:49`) | extends | Dependency/post-dependency CRUD methods. |
| `CreateFormTool` (`tools/create_form.py:226`) | extends | Rule schema in generation contract. |
| `register_field_control` / `FieldControlMetadata` (`controls/registry.py:70/36`) | extends | Per-`FieldType` supported operators/effects/operations metadata. |
| `field_helpers` (`tools/field_helpers.py:250/256`) | extends | Rule/operation snippets + builders. |
| `extractors/yaml.py`, `extractors/jsonschema.py` | depends on | Round-trip `post_depends`/operations on import. |
| `parrot.forms` (legacy re-exports) | depends on | Re-export new public symbols. |

### Data Models
```python
# parrot_formdesigner/core/constraints.py — widened + new models (illustrative, not final)

class DependencyRule(BaseModel):
    conditions: list[FieldCondition]
    logic: Literal["and", "or", "xor", "not"] = "and"          # widened (was "and"|"or")
    effect: Literal["show", "hide", "require", "disable"] = "show"
    operations: list["DependencyOperation"] | None = None      # NEW (optional)


class DependencyOperation(BaseModel):
    # op kind drives how `operands` (referencing field_ids) produce a value for `target`
    op: Literal[
        "copy", "add", "subtract", "multiply", "divide", "percent",
        "concat", "format", "date_diff", "lookup", "aggregate",
    ]
    operands: list[str]                 # referenced field_ids (or literals via a tagged form)
    target: str                         # field_id receiving the computed value
    options: dict[str, Any] | None = None   # op-specific options (e.g. date unit, fmt string,
                                            #   lookup tool ref, aggregate fn)


class PostDependency(BaseModel):
    # forward effect: this control's value affects a control declared AFTER it
    target: str                                     # field_id affected (must be later)
    effect: Literal["set", "calc", "reload_options", "show", "hide", "require", "cascade_clear"]
    conditions: list[FieldCondition] | None = None  # optional gating on this control's value
    logic: Literal["and", "or", "xor", "not"] = "and"
    operation: DependencyOperation | None = None    # required when effect in {"set","calc"}
```

```python
# parrot_formdesigner/core/schema.py — additive attribute

class FormField(BaseModel):
    # ... existing fields unchanged ...
    depends_on: DependencyRule | None = None          # existing (line 61)
    post_depends: list[PostDependency] | None = None  # NEW (forward effects)
```

### New Public Interfaces
```python
# parrot_formdesigner/services/rule_evaluator.py  (NEW, optional server-side evaluator)

class RuleResolution(BaseModel):
    visible: dict[str, bool]            # field_id -> visible
    required: dict[str, bool]           # field_id -> required (after rule application)
    computed: dict[str, Any]            # field_id -> computed value (from operations)
    cleared: list[str]                  # field_ids cascade-cleared this resolution

class RuleEvaluator:
    async def resolve(
        self,
        form: FormSchema,
        answers: dict[str, Any],
        *,
        locale: str = "en",
    ) -> RuleResolution:
        """Authoritatively resolve visibility/required/computed values for a form
        given current answers. Processes pre-deps, post-deps, and operations in
        topological order; safe no-op on missing/empty referenced values."""
        ...
```

```python
# parrot_formdesigner/tools/edit_toolkit.py — new authoring methods (illustrative)

class EditToolkit(AbstractToolkit):
    async def add_dependency(self, field_id: str, rule: dict) -> dict: ...
    async def update_dependency(self, field_id: str, patch: dict) -> dict: ...
    async def remove_dependency(self, field_id: str) -> dict: ...
    async def add_post_dependency(self, field_id: str, post: dict) -> dict: ...
    async def remove_post_dependency(self, field_id: str, target: str) -> dict: ...
```

---

## 3. Module Breakdown

> One module per capability as a starting point (capabilities from the brainstorm).

### Module 1: Logic widening — `form-rule-logic-xor-not`
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/core/constraints.py`
- **Responsibility**: Widen `DependencyRule.logic` to `Literal["and","or","xor","not"]`; define
  `xor`/`not` evaluation semantics (see §7 + §8). Default stays `"and"` (backward-compatible).
- **Depends on**: existing `DependencyRule` (constraints.py:158).

### Module 2: Operations model — `form-rule-operations`
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/core/constraints.py` (or a new
  `core/operations.py` if it grows large; re-exported from `core/__init__.py`).
- **Responsibility**: `DependencyOperation` model + validators for op-kind/operand/target shape.
  Vocabulary: copy/assign, arithmetic (add/subtract/multiply/divide/percent), string/date
  (concat/format/date_diff), lookup/aggregate.
- **Depends on**: Module 1 (shared rule models), `FieldType` (`core/types.py`).

### Module 3: PostDependency model + schema attribute — `form-postdepends`
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/core/constraints.py` +
  `core/schema.py`.
- **Responsibility**: `PostDependency` model; add `post_depends: list[PostDependency] | None` to
  `FormField`; ensure `FormField.model_rebuild()` (schema.py:68) still resolves.
- **Depends on**: Modules 1 & 2.

### Module 4: Validation & cycle extension — `form-rule-authoring` (validation slice)
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py`
- **Responsibility**: Rule-integrity pass (references resolve to real `field_id`s; `depends_on`
  references only earlier fields, `post_depends` targets only later fields; operator/type
  compatibility); extend `_detect_circular_dependencies` (validators.py:777) to add `post_depends`
  and operation edges to the DFS graph.
- **Depends on**: Modules 1–3.

### Module 5: Renderer emission
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/jsonschema.py`
- **Responsibility**: Emit `x-post-depends` and serialized `operations` next to `x-depends-on`
  (jsonschema.py:411). Other renderers treat new declarations as pass-through hints in v1.
- **Depends on**: Modules 1–3.

### Module 6: Authoring tools & control metadata — `form-rule-authoring` (tools slice)
- **Path**: `tools/edit_toolkit.py`, `tools/create_form.py`, `controls/registry.py` +
  `controls/builtin.py`, `tools/field_helpers.py`.
- **Responsibility**: `EditToolkit` dependency/post-dependency CRUD; `CreateFormTool` rule schema
  coverage; per-`FieldType` capability metadata on `FieldControlMetadata`; rule/operation snippets
  and builder helpers.
- **Depends on**: Modules 1–4.

### Module 7: Optional `RuleEvaluator` service — `form-rule-evaluator`
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/rule_evaluator.py`
  (re-exported from `services/__init__.py`).
- **Responsibility**: Server-side authoritative resolution of visibility/required/computed values
  (topological order, cascade-clear); safe no-op on missing values and on lookup/op failure.
- **Depends on**: Modules 1–4.

### Module 8: Extractor round-trip + legacy re-exports
- **Path**: `extractors/yaml.py`, `extractors/jsonschema.py`, `core/__init__.py`,
  `packages/ai-parrot/src/parrot/forms/__init__.py`.
- **Responsibility**: Parse/serialize `post_depends`/operations on import/export; re-export new
  public symbols (`DependencyOperation`, `PostDependency`, `RuleEvaluator`, `RuleResolution`).
- **Depends on**: Modules 1–3, 7.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_dependencyrule_logic_xor_not_accepted` | M1 | `logic="xor"`/`"not"` construct; `"and"`/`"or"` still valid (backward-compat). |
| `test_dependencyrule_legacy_roundtrip` | M1 | Existing imported `depends_on` (and/or, show/hide) unchanged after model load. |
| `test_dependency_operation_kinds` | M2 | Each op kind (copy/add/.../aggregate) validates operand/target shape. |
| `test_dependency_operation_invalid_op_rejected` | M2 | Unknown op / missing target raises. |
| `test_postdependency_model_valid` | M3 | `PostDependency` with each effect; `set`/`calc` require `operation`. |
| `test_formfield_post_depends_optional_and_default_none` | M3 | `FormField` without `post_depends` still valid; `model_rebuild` resolves. |
| `test_validate_reference_must_exist` | M4 | Condition/operand referencing unknown `field_id` → error. |
| `test_validate_pre_post_ordering` | M4 | `depends_on` referencing later field, or `post_depends` targeting earlier field → error. |
| `test_validate_operator_type_compatibility` | M4 | `gt` on text / arithmetic op on non-numeric → error. |
| `test_cycle_detection_includes_post_and_operation_edges` | M4 | Cycle via `post_depends`/operation detected. |
| `test_jsonschema_emits_x_post_depends` | M5 | Renderer outputs `x-post-depends` + serialized operations. |
| `test_jsonschema_legacy_x_depends_on_unchanged` | M5 | Existing `x-depends-on` output unchanged. |
| `test_edit_toolkit_add_update_remove_dependency` | M6 | CRUD on `depends_on` via toolkit; invalid rule rejected. |
| `test_edit_toolkit_add_post_dependency` | M6 | Add/remove `post_depends`; ordering enforced. |
| `test_control_registry_exposes_rule_capabilities` | M6 | Capability metadata present per `FieldType`. |
| `test_rule_evaluator_visibility_and_required` | M7 | `resolve()` returns correct visible/required for and/or/xor/not. |
| `test_rule_evaluator_computed_values` | M7 | copy/arithmetic/string-date/aggregate produce expected `computed`. |
| `test_rule_evaluator_cascade_clear` | M7 | Changing source clears dependents. |
| `test_rule_evaluator_safe_on_missing_values` | M7 | Missing/empty referenced value → no-op, no crash. |
| `test_yaml_extractor_roundtrip_post_depends` | M8 | Import/export preserves `post_depends`/operations. |

### Integration Tests
| Test | Description |
|---|---|
| `test_authored_form_with_rules_validates_and_renders` | Build a form via `EditToolkit` with `depends_on` (xor) + `post_depends` (calc), validate, render to JSON Schema, evaluate via `RuleEvaluator`. |
| `test_imported_legacy_form_unaffected` | Load a pre-existing imported form; validation/render output is byte-stable vs. before. |
| `test_create_form_tool_emits_rules` | `CreateFormTool` produces a schema containing valid `depends_on`/`post_depends`. |

### Test Data / Fixtures
```python
@pytest.fixture
def form_with_pre_and_post_rules() -> FormSchema:
    """A FormSchema exercising xor logic, an arithmetic operation, and a
    post_depends 'set' effect targeting a later field."""
    ...

@pytest.fixture
def legacy_imported_depends_on() -> dict:
    """The user-provided depends_on JSON (and/or, show) — must round-trip unchanged."""
    return {
        "conditions": [{"field_id": "field_9050", "operator": "eq", "value": "Compliance Audit"}],
        "logic": "and",
        "effect": "show",
    }
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `DependencyRule.logic` accepts `and|or|xor|not`; `and`/`or` behavior is unchanged.
- [ ] `DependencyOperation` supports copy/assign, arithmetic, string/date, and lookup/aggregation,
      with validation of operand/target shape.
- [ ] `PostDependency` model exists and `FormField.post_depends` is an optional list defaulting to
      `None`; `set`/`calc` effects require an `operation`.
- [ ] `FormValidator` rejects: unknown references, pre/post ordering violations, operator/type
      mismatches, and cycles that include `post_depends`/operation edges.
- [ ] `JsonSchemaRenderer` emits `x-post-depends` + serialized operations; existing `x-depends-on`
      output is unchanged.
- [ ] `EditToolkit` can add/update/remove `depends_on` and add/remove `post_depends`, rejecting
      invalid rules at authoring time.
- [ ] Control registry exposes per-`FieldType` supported operators/effects/operations metadata.
- [ ] `field_helpers` exposes rule/operation snippets/builders.
- [ ] Optional `RuleEvaluator.resolve()` returns correct visibility/required/computed/cleared for
      and/or/xor/not and all operation kinds, and is a safe no-op on missing values / op failure.
- [ ] **Backward compatibility**: existing/imported `depends_on` forms validate, render, and
      round-trip with byte-stable output (no breaking change to existing public API).
- [ ] Schema remains purely declarative — a renderer that ignores the new keys still produces a
      valid form (renderers MAY ignore rules).
- [ ] All unit tests pass (`pytest packages/parrot-formdesigner/tests/ -v`).
- [ ] All integration tests pass.
- [ ] Documentation updated (formdesigner docs: dependency/operation/post-dependency reference).
- [ ] New public symbols re-exported from `parrot_formdesigner.core`/`.services` and legacy
      `parrot.forms`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Re-verified against the working tree on 2026-06-11 (line numbers current).

### Verified Imports
```python
# Confirmed public API (parrot_formdesigner.core re-exports):
from parrot_formdesigner.core import (
    FormField, FormSection, FormSubsection, FormSchema,
    FieldType, LocalizedString,
    ConditionOperator, FieldCondition, DependencyRule, FieldConstraints,
)
from parrot_formdesigner.services import FormValidator, ValidationResult
from parrot_formdesigner.controls import (
    register_field_control, get_controls, iter_controls, FieldControlMetadata,
)
from parrot_formdesigner.tools import (
    EditToolkit, CreateFormTool,
    get_form_field_schema_snippets, list_supported_form_field_types,
)
# Backward-compat (legacy re-export):
from parrot.forms import FormField, DependencyRule  # ...etc
```

### Existing Class Signatures
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/constraints.py
class ConditionOperator(str, Enum):                       # line 129
    EQ="eq"; NEQ="neq"; GT="gt"; LT="lt"; GTE="gte"; LTE="lte"
    IN="in"; NOT_IN="not_in"; IS_EMPTY="is_empty"; IS_NOT_EMPTY="is_not_empty"  # 132-141
class FieldCondition(BaseModel):                          # line 144
    field_id: str                                         # 153
    operator: ConditionOperator                           # 154
    value: Any = None                                     # 155
class DependencyRule(BaseModel):                          # line 158
    conditions: list[FieldCondition]                      # 167
    logic: Literal["and", "or"] = "and"                   # 168  ← WIDEN to add "xor","not"
    effect: Literal["show","hide","require","disable"] = "show"  # 169
class FieldConstraints(BaseModel):                        # line 17 (extra="forbid")

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
class FormField(BaseModel):                               # line 24 (extra="forbid")
    field_id: str                                         # 50
    field_type: FieldType                                 # 51
    depends_on: DependencyRule | None = None              # 61  ← ADD post_depends sibling
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

# packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py
class FormValidator:                                      # line 91
    async def validate(self, form, data, *, locale="en") -> ValidationResult  # 112 (cycle check @135)
    async def validate_field(self, field, value, *, all_data=None, locale) -> list[str]  # 179
    def _detect_circular_dependencies(self, form: FormSchema) -> list[str]    # 777 (DFS; walks depends_on only)

…(truncated)…
