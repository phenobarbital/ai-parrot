# TASK-1725: Catalog components: Card, KPICard, Timeline, Form(schema-only)

**Feature**: FEAT-273 — A2UI Protocol Integration — Rendering Core (parrot.outputs.a2ui)
**Spec**: sdd/specs/a2ui-implementation.spec.md
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1721
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (Catalog v1 components + lowerings). This task implements
four of the nine v1 catalog components: **Card**, **KPICard**, **Timeline**,
and **Form**.

Card/KPICard/Timeline are simple display components (`requires_actions=False`)
with full schema + instructions + `lower()` + golden files. **Form is the one
`requires_actions=True` component in v1** (resolved OQ-B, spec §8): it ships
**schema + instructions only** — no renderer supports it in v1. Validation
must reject Form in LLM-produced envelopes and static renderers must
deep-link/strip it — but that **enforcement machinery lives in TASK-1721
(catalog validation) and the Module 5 renderer tasks**; this task only
*declares* the flag and *tests the declaration*.

Runs in parallel with TASK-1724 (Chart/DataTable/Map) and TASK-1726
(Infographic/Report); files are disjoint by construction.

---

## Scope

- Implement `Card`, `KPICard`, `Timeline` catalog components, one module each
  under `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/components/`:
  - JSON Schema per component (`ComponentDefinition.schema_`). Card may draw
    its visual vocabulary (title / subtitle / body / image / badge / footer
    fields) from the legacy card template — inspiration only, no code reuse.
  - Embedded LLM `instructions` string per component.
  - `requires_actions=False`.
  - Pure deterministic `lower(component, data_model) -> BasicTree` targeting
    Basic Catalog primitives (Text/Row/Column/Card/Image).
- Implement `Form` component: JSON Schema (fields, labels, input types,
  submit action descriptor) + `instructions` + **`requires_actions=True`**.
  - If TASK-1721's registry enforces G4 literally (components without a
    `lower()` cannot register — spec §5), Form's `lower()` is the minimal
    deterministic read-only degradation: a Column of field-label Texts plus a
    "form not available on this surface" notice Text, golden-file tested like
    the others. Verify TASK-1721's actual registration contract first; if it
    allows schema-only registration for `requires_actions` components, skip
    the lowering and its golden file.
- Register all four via `@register_component`.
- Golden-file lowering tests (byte-identical determinism) for every component
  that ships a `lower()`, under `packages/ai-parrot/tests/outputs/a2ui/golden/`.
- Test that the catalog reports `requires_actions=True` for Form and `False`
  for the other three (the declaration, not the enforcement).

**NOT in scope**:
- Enforcement of `requires_actions` rejection for LLM-produced envelopes —
  TASK-1721 (allowlist validation) and TASK-1737 (producer).
- Static-renderer deep-link degradation / action stripping — Module 5 renderer
  tasks + Module 8 deep-link service.
- Any Form rendering, submission, `action`/`actionResponse` dispatch — FEAT-B.
- The other five components (TASK-1724, TASK-1726).
- Registry/`ComponentDefinition` mechanics (TASK-1721).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/components/card.py` | CREATE | Card component: schema + instructions + `lower()` |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/components/kpicard.py` | CREATE | KPICard component: schema + instructions + `lower()` |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/components/timeline.py` | CREATE | Timeline component: schema + instructions + `lower()` |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/components/form.py` | CREATE | Form component: schema + instructions, `requires_actions=True` (lowering only if registry mandates it) |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/components/__init__.py` | CREATE or MODIFY | Import the four modules for registration side-effects (parallel tasks touch this file — add only your imports, one per line) |
| `packages/ai-parrot/tests/outputs/a2ui/test_components_card_kpicard_timeline_form.py` | CREATE | Schema, flag-declaration, and golden lowering tests |
| `packages/ai-parrot/tests/outputs/a2ui/golden/card_lowered.json` | CREATE | Golden lowered tree for Card |
| `packages/ai-parrot/tests/outputs/a2ui/golden/kpicard_lowered.json` | CREATE | Golden lowered tree for KPICard |
| `packages/ai-parrot/tests/outputs/a2ui/golden/timeline_lowered.json` | CREATE | Golden lowered tree for Timeline |
| `packages/ai-parrot/tests/outputs/a2ui/golden/form_lowered.json` | CREATE (conditional) | Golden degraded tree for Form, only if Form must ship a `lower()` |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports

No existing core imports are required by the component modules themselves.
Registration decorator and component contract come from **TASK-1721**
(`parrot.outputs.a2ui.catalog` — `register_component`, `ComponentDefinition`,
the `lower()`/BasicTree contract). Verify the exact import paths against
TASK-1721's committed code before writing any.

### Existing Signatures to Use

```python
# packages/ai-parrot-visualizations/src/parrot/outputs/formats/card.py — LEGACY, INSPIRATION ONLY
class CardRenderer(BaseRenderer):        # :43
    CARD_TEMPLATE = """<!DOCTYPE html>   # :49  — grid-of-cards HTML template (visual vocabulary source)
    SINGLE_CARD_TEMPLATE = """           # :164 — per-card fields: read for title/value/icon vocabulary
```

Spec §2 contract this task implements against (from TASK-1721):

```python
# parrot/outputs/a2ui/catalog/__init__.py (spec §2 "New Public Interfaces")
def register_component(name: str, *, requires_actions: bool = False): ...   # decorator
# each component implements: def lower(self, component, data_model) -> BasicTree  # pure, deterministic (D8)

# parrot/outputs/a2ui/catalog/base.py (spec §2 "Data Models")
class ComponentDefinition(BaseModel):
    name: str
    catalog_id: str = "https://parrot.dev/catalogs/v1"
    schema_: Dict[str, Any]
    instructions: str
    requires_actions: bool = False     # D10b — Form sets True
```

### Does NOT Exist

- ~~Any `KPICard`/`Timeline` model or renderer anywhere in `parrot.*`~~ —
  verified by grep 2026-07-10; these are net-new vocabulary (design their
  schemas from scratch: KPICard = label/value/delta/trend/unit; Timeline =
  ordered events with timestamp/title/description).
- ~~`parrot.outputs.a2ui.catalog.components`~~ — created by this task and its
  parallel siblings.
- ~~A `BasicTree` model on `dev` today~~ — defined by TASK-1721; verify its
  real name/shape there.
- ~~Form rendering support, `ActionRouter`, action dispatch~~ — FEAT-B
  territory (spec Non-Goals); v1 ships Form *schema* only.
- ~~`exec()`/`eval()` under `parrot/outputs/a2ui*`~~ — G1 invariant.
- ~~Reusable card Pydantic model in core~~ — `CARD_TEMPLATE` is an HTML string
  inside a legacy renderer, not a data model; do not import from
  `parrot.outputs.formats.card` in A2UI code.

---

## Implementation Notes

### Pattern to Follow

Card visual vocabulary — quoted anchor from the legacy template (INSPIRATION
for schema field names, never code to embed):

```python
# packages/ai-parrot-visualizations/src/parrot/outputs/formats/card.py:49 — EXISTING code
CARD_TEMPLATE = """<!DOCTYPE html>
...
```

Read `card.py:49-390` to extract which visual slots the legacy cards support
(title, value, icon, color accents, grid layout) and encode the useful subset
as JSON Schema properties.

### Key Constraints

- `lower()` MUST be pure and deterministic (no clocks/randomness/dict-order
  dependence/I/O/async); serialize goldens with sorted keys.
- Lowered trees: Basic Catalog primitives only (Text/Row/Column/Card/Image).
- KPICard lowering guidance: Card containing label Text + prominent value Text
  + optional delta/trend Text. Timeline lowering guidance: Column of Rows
  (timestamp Text + title/description Texts) in input order — never re-sort
  (determinism + author intent).
- Form is the only component here with `requires_actions=True`; the flag must
  be visible on its registered `ComponentDefinition` — that is what the
  declaration test asserts. Do NOT implement rejection logic here.
- `instructions` for Form must tell the LLM the component is NOT available for
  display-only surfaces in v1 (defense in depth on top of validation).
- Pydantic v2, Google-style docstrings, strict type hints; no `print`.
- Golden test recipe: `lower()` twice → `json.dumps(tree, sort_keys=True)`
  bytes identical to each other and to the committed golden file.

### References in Codebase

- `packages/ai-parrot-visualizations/src/parrot/outputs/formats/card.py:49` — `CARD_TEMPLATE` visual vocabulary.
- Spec §4 rows `test_component_lowering_golden[component]` and `test_llm_envelope_rejects_requires_actions` (the latter is TASK-1721/TASK-1737 scope; this task supplies the flag it depends on).
- Spec §7 "Known Risks": `requires_actions` on a static surface renders with actions stripped + visible notice — Form's degraded lowering (if required) is that notice.

---

## Acceptance Criteria

- [ ] Card, KPICard, Timeline registered with schema + instructions + `requires_actions=False` + `lower()` + golden file each.
- [ ] Form registered with schema + instructions + `requires_actions=True`; lowering shipped if-and-only-if TASK-1721's registry mandates `lower()` at registration (decision recorded in the Completion Note).
- [ ] Catalog lookup reports the correct `requires_actions` value for all four components.
- [ ] Golden determinism: for each shipped `lower()`, two consecutive runs on the same input serialize to byte-identical JSON matching the committed golden file.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/outputs/a2ui/test_components_card_kpicard_timeline_form.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/outputs/a2ui/catalog/components/`
- [ ] G1 spot check: `grep -rn "exec(\|eval(" packages/ai-parrot/src/parrot/outputs/a2ui/` returns nothing.

---

## Test Specification

> Minimal test scaffold (names + one-line docstrings). The agent must make these pass.

```python
# packages/ai-parrot/tests/outputs/a2ui/test_components_card_kpicard_timeline_form.py

class TestCardComponent:
    def test_card_registered_in_catalog(self):
        """Card is in the v1 catalog allowlist with requires_actions=False."""

    def test_card_lowering_golden(self):
        """Card lowers to golden/card_lowered.json; two runs are byte-identical."""


class TestKPICardComponent:
    def test_kpicard_registered_in_catalog(self):
        """KPICard is in the v1 catalog allowlist with requires_actions=False."""

    def test_kpicard_lowering_golden(self):
        """KPICard lowers to golden/kpicard_lowered.json deterministically."""


class TestTimelineComponent:
    def test_timeline_registered_in_catalog(self):
        """Timeline is in the v1 catalog allowlist with requires_actions=False."""

    def test_timeline_lowering_golden(self):
        """Timeline lowers to golden/timeline_lowered.json deterministically."""

    def test_timeline_preserves_event_order(self):
        """Lowered Timeline keeps events in input order, never re-sorted."""


class TestFormComponent:
    def test_form_registered_with_requires_actions_true(self):
        """Form's ComponentDefinition declares requires_actions=True."""

    def test_form_schema_validates_field_payload(self):
        """A form payload with fields/labels/input types validates against the Form schema."""

    def test_form_instructions_flag_display_only_v1(self):
        """Form's embedded instructions state it is unavailable for display-only surfaces in v1."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - Confirm TASK-1721's actual `register_component` / `lower()` mandate for `requires_actions` components
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in the per-spec index → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-1725-components-card-kpicard-timeline-form.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-11
**Notes**: Implemented Card, KPICard, Timeline (display-only, `requires_actions=False`)
and Form (`requires_actions=True`) under `catalog/components/`, each with JSON Schema,
`INSTRUCTIONS`, and a pure deterministic `lower()` to Basic Catalog primitives. Timeline
preserves input event order (never re-sorted). Form's instructions explicitly state it
is unavailable on display-only surfaces in v1. Golden files committed; determinism +
committed-golden equality asserted. 55 tests pass; ruff clean; no exec/eval.

**Form lowering decision**: TASK-1721's registry enforces the mandatory `lower()`
contract literally (a class without a callable `lower()` cannot register), so Form
SHIPS a degraded read-only `lower()` — a Column of field-label Texts plus a
"form not available on this surface" notice (spec §7) — with a committed golden file.

**Deviations from spec**: Also renamed a colliding dummy component `"Card"` →
`"DisplayOnlyDummy"` in `test_catalog.py` (TASK-1721's test file). That test's
`cleanup_catalog` teardown called `unregister_component("Card")`, which removed the
real Card component registered by this task and broke `test_card_registered_in_catalog`
under full-suite ordering. The rename is a test-isolation fix only (no production code
touched).
