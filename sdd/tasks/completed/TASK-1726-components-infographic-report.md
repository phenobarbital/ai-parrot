# TASK-1726: Catalog components: Infographic, Report (+lowerings)

**Feature**: FEAT-273 — A2UI Protocol Integration — Rendering Core (parrot.outputs.a2ui)
**Spec**: sdd/specs/a2ui-implementation.spec.md
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1721
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (Catalog v1 components + lowerings). This task implements the
two **composite semantic components** of the v1 catalog: **Infographic** and
**Report**. These are Parrot's "exceeds-the-spec" citizens (spec §1): high-level
components that a section-structured document/visual layout is expressed in,
rather than raw primitive trees.

Because they are composites, their `lower()` to Basic Catalog primitives is
where degradation is most visible. Spec §8 leaves **OQ-C open — "lowered-tree
fidelity: golden-file review criteria for minimum acceptable Infographic/Report
degradation" — Owner: Module 3 implementer, first component task**. This task
owns OQ-C: the fidelity criteria must be PROPOSED in this task's Completion
Note (see Acceptance Criteria).

Legacy renderers `InfographicHTMLRenderer` and `TemplateReportRenderer` are
the vocabulary **inspiration** for what sections/blocks these components must
express — they are NOT code to reuse (they are `BaseRenderer` subclasses in
the raw-HTML pipeline FEAT-273 replaces).

Runs in parallel with TASK-1724 and TASK-1725; files are disjoint.

---

## Scope

- Implement `Infographic` and `Report` catalog components, one module each
  under `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/components/`:
  - JSON Schema per component. Infographic: header (title/subtitle/theme
    hints), ordered sections each hosting nested catalog components
    (KPICard rows, Chart, Text blocks, Image). Report: title/metadata,
    ordered sections (heading + rich text + embedded components + tables),
    optional summary. Nested children reference other catalog components by
    name — validation of children against the allowlist is TASK-1721's
    recursive validation, not re-implemented here.
  - Embedded LLM `instructions` per component (when to choose Infographic vs
    Report vs plain components; section structure rules; binding rules).
  - `requires_actions=False` for both.
  - Pure deterministic `lower(component, data_model) -> BasicTree`:
    section-preserving mapping onto Basic Catalog primitives (Text/Row/
    Column/Card/Image) — heading hierarchy as styled Text, sections as
    Cards/Columns, nested catalog children lowered via their own registered
    `lower()` (delegation through the registry, keeping composition
    deterministic).
- Register both via `@register_component`.
- Golden-file lowering tests (byte-identical determinism) under
  `packages/ai-parrot/tests/outputs/a2ui/golden/`.
- **Propose OQ-C fidelity criteria** in the Completion Note: reviewable
  golden-file criteria for the minimum acceptable degradation (e.g. "every
  section title survives as a Text node", "section order preserved", "every
  KPI value visible in the lowered tree", "no data silently dropped").

**NOT in scope**:
- The seven other components (TASK-1724, TASK-1725) — but their `lower()`
  implementations are *used* by delegation if available; where a nested child
  type from a parallel task is not yet merged, golden fixtures for THIS task
  must nest only Text/Image children so the tests stand alone.
- The shared cross-component `infographic_envelope.json` fixture from spec §4
  (exercises Infographic + Chart + KPICard together) — it spans three parallel
  tasks; it belongs to whichever integration/renderer task first needs it,
  after Module 3 fully lands.
- Any HTML/PDF rendering (Module 5 satellite renderers; SPK-1).
- JSON Pointer resolution (Module 6 bake pass).
- Registry/allowlist/recursive-validation mechanics (TASK-1721).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/components/infographic.py` | CREATE | Infographic component: schema + instructions + `lower()` |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/components/report.py` | CREATE | Report component: schema + instructions + `lower()` |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/components/__init__.py` | CREATE or MODIFY | Import both modules for registration side-effects (parallel tasks touch this file — add only your two imports, one per line) |
| `packages/ai-parrot/tests/outputs/a2ui/test_components_infographic_report.py` | CREATE | Schema, composition, and golden lowering tests |
| `packages/ai-parrot/tests/outputs/a2ui/golden/infographic_lowered.json` | CREATE | Golden lowered tree for Infographic |
| `packages/ai-parrot/tests/outputs/a2ui/golden/report_lowered.json` | CREATE | Golden lowered tree for Report |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports

No existing core imports are required by the component modules themselves.
Registration decorator and component contract come from **TASK-1721**
(`parrot.outputs.a2ui.catalog`); verify exact import paths against its
committed code before writing any.

### Existing Signatures to Use

```python
# packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py
# LEGACY, INSPIRATION for schema vocabulary ONLY — do not import/extend
class InfographicHTMLRenderer(BaseRenderer):    # :632
    def render_to_html(                          # :700
        ...

# packages/ai-parrot-visualizations/src/parrot/outputs/formats/template_report.py
# LEGACY, INSPIRATION ONLY
@register_renderer(OutputMode.TEMPLATE_REPORT)  # :9
class TemplateReportRenderer(BaseRenderer):      # :10
    async def render(self, data: Any, **kwargs: Any) -> str  # :53
```

Spec §2 contract this task implements against (from TASK-1721):

```python
# parrot/outputs/a2ui/catalog/__init__.py (spec §2 "New Public Interfaces")
def register_component(name: str, *, requires_actions: bool = False): ...   # decorator
# each component implements: def lower(self, component, data_model) -> BasicTree  # pure, deterministic (D8)
```

### Does NOT Exist

- ~~Any A2UI `Infographic`/`Report` component on `dev`~~ — net-new; the legacy
  `InfographicHTMLRenderer`/`TemplateReportRenderer` are raw-HTML renderers in
  the pipeline being replaced (their `exec`/HTML paths are the G1 target).
- ~~`parrot.outputs.a2ui.catalog.components`~~ — created by this task and its
  parallel siblings.
- ~~A `BasicTree` model on `dev` today~~ — defined by TASK-1721; verify its
  real name/shape there.
- ~~`InfographicToolkit` envelope builders~~ — toolkit migration is Module 11
  (spec §3); today `parrot/tools/infographic_toolkit.py` still builds raw HTML.
- ~~`exec()`/`eval()` under `parrot/outputs/a2ui*`~~ — G1 invariant; never
  route through `BaseRenderer.execute_code`.

---

## Implementation Notes

### Pattern to Follow

Read the legacy sources for the section vocabulary these composites must
cover — e.g. what an infographic is made of in the current product
(`infographic_html.py:632-700+`: header, stat/KPI blocks, chart slots,
themed sections) and what a report template consumes
(`template_report.py:53+`: dict/dataclass context flattened into a
narrative template). Extract the *concepts* as JSON Schema; leave the HTML
behind.

### Key Constraints

- `lower()` MUST be pure and deterministic (no clocks/randomness/dict-order
  dependence/I/O/async); serialize goldens with sorted keys.
- Section order is author intent: lowering preserves it exactly.
- Composite delegation: nested catalog children lower via the registry's
  `lower()` for their type — this keeps the whole composite lowering pure as
  long as every child `lower()` is pure. Do not inline-copy sibling
  components' lowering logic.
- Lowered trees: Basic Catalog primitives only (Text/Row/Column/Card/Image).
- Data-model bindings pass through unresolved (bake pass is Module 6).
- `requires_actions=False` for both components.
- Pydantic v2, Google-style docstrings, strict type hints; no `print`.
- Golden test recipe: `lower()` twice → `json.dumps(tree, sort_keys=True)`
  bytes identical to each other and to the committed golden file.
- **OQ-C obligation**: the proposed fidelity criteria in the Completion Note
  must be concrete enough for a reviewer to accept/reject a future golden-file
  change (per-element survival rules + ordering rules + "nothing silently
  dropped" rule), and should be phrased so they can graduate into the docs
  page required by spec §5 (catalog authoring).

### References in Codebase

- `packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py:632` — `InfographicHTMLRenderer` (vocabulary inspiration).
- `packages/ai-parrot-visualizations/src/parrot/outputs/formats/template_report.py:10` — `TemplateReportRenderer` (vocabulary inspiration).
- Spec §4 `test_component_lowering_golden[component]`; spec §8 OQ-C (owned here).
- Spec §7 two-phase bake note — lowering ≠ baking; keep bindings live.

---

## Acceptance Criteria

- [ ] Infographic and Report registered with schema + instructions + `requires_actions=False` + `lower()` each.
- [ ] Composite lowering delegates nested children to their registered `lower()` (no inlined copies of sibling logic).
- [ ] Golden determinism: for each component, two consecutive `lower()` runs on the same input serialize to byte-identical JSON matching the committed golden file; golden fixtures nest only children available at merge time (Text/Image safe minimum).
- [ ] OQ-C fidelity criteria PROPOSED in the Completion Note (golden-file review criteria for minimum acceptable Infographic/Report degradation).
- [ ] All tests pass: `pytest packages/ai-parrot/tests/outputs/a2ui/test_components_infographic_report.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/outputs/a2ui/catalog/components/`
- [ ] G1 spot check: `grep -rn "exec(\|eval(" packages/ai-parrot/src/parrot/outputs/a2ui/` returns nothing.

---

## Test Specification

> Minimal test scaffold (names + one-line docstrings). The agent must make these pass.

```python
# packages/ai-parrot/tests/outputs/a2ui/test_components_infographic_report.py

class TestInfographicComponent:
    def test_infographic_registered_in_catalog(self):
        """Infographic is in the v1 catalog allowlist with requires_actions=False."""

    def test_infographic_schema_accepts_sectioned_payload(self):
        """A header + ordered-sections payload validates against the Infographic schema."""

    def test_infographic_lowering_golden(self):
        """Infographic lowers to golden/infographic_lowered.json; two runs are byte-identical."""

    def test_infographic_lowering_preserves_section_order(self):
        """Lowered tree keeps sections in authored order."""


class TestReportComponent:
    def test_report_registered_in_catalog(self):
        """Report is in the v1 catalog allowlist with requires_actions=False."""

    def test_report_lowering_golden(self):
        """Report lowers to golden/report_lowered.json deterministically."""

    def test_report_lowering_no_silent_drops(self):
        """Every section title and text block of the fixture survives in the lowered tree."""


class TestCompositeDelegation:
    def test_nested_child_lowered_via_registry(self):
        """A nested catalog child inside a section is lowered through its registered lower()."""

    def test_lowering_preserves_data_bindings(self):
        """JSON Pointer binding strings pass through lower() unresolved."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - Confirm TASK-1721's actual `register_component` / `lower()` / BasicTree contract and its recursive child validation
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in the per-spec index → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-1726-components-infographic-report.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-11
**Notes**: Implemented Infographic and Report composite components under
`catalog/components/`, each with JSON Schema (title/subtitle/theme/sections for
Infographic; title/metadata/summary/sections for Report), `INSTRUCTIONS`,
`requires_actions=False`, and a pure deterministic `lower()`. Sections carry a
`components` list of `{component, properties}` descriptors; lowering delegates each
nested child to its registered `lower()` via the catalog registry (`get_component`),
never inlining sibling logic. Section order preserved; data-model bindings pass
through unresolved. Golden files committed; 64 tests pass; ruff clean; no exec/eval.

**OQ-C fidelity criteria (spec §8) — PROPOSED**: A lowered Infographic/Report tree
is acceptable iff, comparing against the source envelope:
1. **Title survival** — the top-level `title` (and `subtitle`, if present) appears as
   a `Text` node with the corresponding `role`.
2. **Section completeness** — every source section produces exactly one `Column`
   node with `role="section"`; count(sections_in) == count(section columns_out).
3. **Section ordering** — section `Column` nodes appear in authored order, tagged
   with a monotonic `index` (0..n-1). Never re-sorted.
4. **Heading & text survival** — each section's `heading` and `text` survive as
   `Text` nodes (`role="heading"`/`role="body"`).
5. **Nested-child survival** — every nested catalog child yields a lowered subtree
   (delegated); count(children_in) == count(lowered child subtrees_out) per section.
6. **No silent data drop** — every KPI value, chart axis label, and table column
   title present in the source appears somewhere in the lowered tree (Text or
   preserved binding); the Report `summary` survives as a `role="summary"` Text.
7. **Binding preservation** — `{"$bind": "/pointer"}` expressions are copied verbatim
   (bake pass resolves them later); none are dropped or pre-resolved.
8. **Basic-primitive purity** — lowered nodes use only Basic Catalog component names
   (Card/Column/Row/Text/Image); no renderer-specific payloads (ECharts option, folium
   markup) appear.
A golden-file diff that violates any of 1–8 must be rejected in review. These
criteria are phrased to graduate directly into the spec §5 catalog-authoring docs.

**Deviations from spec**: none. Nested children are modeled as inline
`{component, properties}` descriptors inside `sections[].components` (rather than
wire-level id references) so that `lower(component, data_model)` stays a
self-contained pure function — consistent with the composite delegation the task
requires.
