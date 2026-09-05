# TASK-2863: `HtmlDocument` Parrot catalog component + `build_html_document()` builder

**Feature**: FEAT-527 — Infographic → A2UI migration (dual-emit)
**Spec**: `sdd/specs/infographic-a2ui-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2862
**Assigned-to**: unassigned

---

## Context

Spec §1 G5, §2 Data Models ("HtmlDocument component props"), §2 New Public Interfaces, §3
Module 4. Resolved U4: the trusted HTML+Jinja lane is wrapped as an opaque HTML A2UI surface so
one envelope contract covers every infographic path. This task creates the component and its
builder; TASK-2864 wires the toolkit; TASK-2865 teaches the renderers.

---

## Scope

- Create `catalog/parrot/htmldocument.py`:
  - `HTMLDOCUMENT_SCHEMA` exactly as spec §2 Data Models (`title` required; `html` XOR `srcUrl` via
    `oneOf`; optional `theme`).
  - `HTMLDOCUMENT_INSTRUCTIONS` — states it is tool-only, display-only, and never LLM-authored.
  - `@register_component("HtmlDocument", allowed_parents=["root", "Column"], tool_only=True)
    class HtmlDocumentComponent` with `SCHEMA`, `INSTRUCTIONS`, and
    `lower(self, component, data_model) -> BasicTree` → `Card{child: Column[Text(title, parrot_role=title),
    Text("[HTML document: <title>]", extensions={"parrot_role": "html_document", "parrot_src_url": srcUrl|None,
    "parrot_inline_html": bool})]}`. The raw `html` string is **never** copied into the lowered tree
    (static renderers must not echo it); renderers that can embed it read `component.model_extra["html"]`
    before lowering (TASK-2865).
- Import it in `catalog/parrot/__init__.py` (`:13-23` list) so registration runs.
- `builders.py`: add `build_html_document(*, title, html=None, src_url=None, theme=None,
  surface_id="html-document", metadata=None) -> CreateSurface` — validates the XOR in Python
  (`ValueError`), calls `build_surface("HtmlDocument", props, surface_id=..., origin=ProducerOrigin.TOOL,
  metadata=...)`; add to `__all__` (`:31`).
- Golden: add `tests/outputs/a2ui/golden/htmldocument_lowered.json` + a golden test in
  `tests/outputs/a2ui/test_components_infographic_report.py` (or a new
  `test_components_htmldocument.py`).
- Tests: registration flags, LLM-origin rejection (via `validate_envelope`), builder XOR, lowering.
- Docs: none here (TASK-2869).

**NOT in scope**: toolkit emission (TASK-2864); renderer handling (TASK-2865); frontend (TASK-2867).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/htmldocument.py` | CREATE | component |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/__init__.py` | MODIFY | import for registration |
| `packages/ai-parrot/src/parrot/outputs/a2ui/builders.py` | MODIFY | `build_html_document` + `__all__` |
| `packages/ai-parrot/tests/outputs/a2ui/test_components_htmldocument.py` | CREATE | component + builder + golden tests |
| `packages/ai-parrot/tests/outputs/a2ui/golden/htmldocument_lowered.json` | CREATE | golden |
| `packages/ai-parrot/tests/outputs/a2ui/test_builders.py` | MODIFY | builder listed/behaves |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.outputs.a2ui.catalog import register_component, get_component, validate_envelope   # catalog/__init__.py:107,:386
from parrot.outputs.a2ui.catalog.base import BasicNode, BasicTree, ProducerOrigin, CatalogValidationError, DEFAULT_CATALOG_ID  # base.py:97,85,299,53
from parrot.outputs.a2ui.models import Component, CreateSurface                                 # a2ui/models.py
from parrot.outputs.a2ui.builders import build_surface, build_infographic                       # builders.py:50, :216
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/builders.py
__all__ = ["build_card", ...]                                                                    # :31
def build_surface(component: str, properties: dict[str, Any], *, surface_id: str,
                  component_id: str = _ROOT_COMPONENT_ID, data_model: dict | None = None,
                  origin: ProducerOrigin = ProducerOrigin.LLM, metadata: ComponentMetadata | None = None) -> CreateSurface  # :50-59  ← pass origin=TOOL
def build_infographic(*, title, ..., surface_id: str = "infographic", data_model=None, metadata=None) -> CreateSurface  # :216-242 (pattern)

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/infocard.py  (template for a small composite)
INFOCARD_SCHEMA = {"type": "object", "properties": {...}, "required": ["title"]}                 # :18-29
@register_component("InfoCard") class InfoCardComponent: SCHEMA; INSTRUCTIONS; def lower(self, component: Component, data_model) -> BasicTree  # :37-44
#   lowering wraps content in Basic `Card`; records metadata.extensions.parrot_variant = "card"      # docstring :5-7

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/__init__.py
from parrot.outputs.a2ui.catalog.parrot import (chart, datatable, filterbar, infocard, infographic, kpicard, map, report, timeline)  # :13-23 ← add htmldocument

# register_component(name, *, requires_actions=False, catalog_id=DEFAULT_CATALOG_ID, is_primitive=False,
#                    allowed_parents=None, allowed_children=None, tool_only=False)   # after TASK-2862
# component props are read as `component.model_extra or {}` (see infographic.py:153, chart.py:56)
```

### Does NOT Exist
- ~~an `Html`/`RawHtml`/`Iframe` Basic Catalog primitive~~ — the 18 primitives have no HTML container; `HtmlDocument` is a Parrot composite.
- ~~`build_surface(...)` defaulting to TOOL origin~~ — default is `ProducerOrigin.LLM`; `build_html_document` MUST pass `origin=ProducerOrigin.TOOL` or validation fails under the TASK-2862 gate.
- ~~`Component.properties`~~ — props are extra fields on `Component` (`model_extra`), not a nested `properties` key (v2 LayoutSpec note at `infographic_toolkit.py:960-962`).
- ~~`catalog/parrot/htmldocument.py`~~ — created here.

---

## Implementation Notes

### Pattern to Follow
```python
# catalog/parrot/infocard.py:37-44 — composite shape
@register_component("InfoCard")
class InfoCardComponent:
    SCHEMA = INFOCARD_SCHEMA
    INSTRUCTIONS = INFOCARD_INSTRUCTIONS
    def lower(self, component: Component, data_model: dict[str, Any]) -> BasicTree:
        props = component.model_extra or {}
        ...
        return BasicTree(root=BasicNode(component="Card", child=..., metadata={"extensions": {...}}))
```

### Key Constraints
- Lowering is pure and never embeds the raw HTML (security + static renderers).
- `oneOf` in the JSON Schema plus a Python-level check in the builder (clear `ValueError`).
- 50 KB inline threshold is the toolkit's concern (TASK-2864), not the component's.

### References in Codebase
- `packages/ai-parrot/tests/outputs/a2ui/test_components_card_kpicard_timeline_form.py:75-103` — golden test style.
- `packages/ai-parrot/tests/outputs/a2ui/test_builders.py` — builder test style.

---

## Acceptance Criteria

- [ ] `get_component("HtmlDocument")` resolves; `definition.tool_only is True`, `requires_actions is False`, `allowed_parents == ["root","Column"]`
- [ ] `build_html_document(title="T", html="<html>…")` returns a validated `CreateSurface`; `src_url` variant works; both/neither → `ValueError`
- [ ] An LLM-origin envelope containing `HtmlDocument` fails `validate_envelope`
- [ ] Lowered tree contains the title and the `[HTML document: T]` placeholder with `parrot_role: html_document`, and does **not** contain the raw HTML string
- [ ] Golden `htmldocument_lowered.json` added and matched
- [ ] `timeout -s KILL 600 pytest packages/ai-parrot/tests/outputs/a2ui -q` green; `ruff check packages/ai-parrot/src/parrot/outputs/a2ui`

---

## Test Specification

```python
# tests/outputs/a2ui/test_components_htmldocument.py
from parrot.outputs.a2ui.builders import build_html_document
from parrot.outputs.a2ui.catalog import get_component, validate_envelope
from parrot.outputs.a2ui.catalog.base import ProducerOrigin, CatalogValidationError

def test_registration_flags():
    entry = get_component("HtmlDocument")
    assert entry.definition.tool_only and not entry.definition.requires_actions

def test_builder_inline_and_url():
    env = build_html_document(title="Report", html="<html><body>x</body></html>")
    assert env.components[0].component == "HtmlDocument"
    env2 = build_html_document(title="Report", src_url="https://x/infographic-a.html")
    assert env2.components[0].model_extra["srcUrl"].endswith(".html")

def test_builder_xor():
    with pytest.raises(ValueError): build_html_document(title="R")
    with pytest.raises(ValueError): build_html_document(title="R", html="<p/>", src_url="https://x")

def test_llm_origin_rejected():
    env = build_html_document(title="R", html="<p>hi</p>")
    with pytest.raises(CatalogValidationError): validate_envelope(env, origin=ProducerOrigin.LLM)

def test_lowering_never_embeds_html():
    env = build_html_document(title="R", html="<script>evil()</script>")
    tree = get_component("HtmlDocument").component_class().lower(env.components[0], {})   # verify attribute name for the class on RegisteredComponent (base.py:275)
    assert "evil()" not in tree.model_dump_json()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2862 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — read `catalog/base.py:275-286` (`RegisteredComponent` attribute names) and `builders.py:50-96`
4. **Update status** in `sdd/tasks/index/infographic-a2ui-migration.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2863-htmldocument-component-builder.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
