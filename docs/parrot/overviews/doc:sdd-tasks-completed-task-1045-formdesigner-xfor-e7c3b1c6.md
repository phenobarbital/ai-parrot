---
type: Wiki Overview
title: 'TASK-1045: XForms 1.1 renderer with `<xf:bind>` constraint expressions'
id: doc:sdd-tasks-completed-task-1045-formdesigner-xforms-renderer-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Wave 2a of FEAT-152 — parallelizable with TASK-1046 / 1047 / 1048.
---

# TASK-1045: XForms 1.1 renderer with `<xf:bind>` constraint expressions

**Feature**: FEAT-152 — parrot-formdesigner Structural Refactor
**Spec**: `sdd/specs/formdesigner-refactor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1044
**Assigned-to**: unassigned

---

## Context

Wave 2a of FEAT-152 — parallelizable with TASK-1046 / 1047 / 1048.

This task introduces a new `XFormsRenderer` (subclass of
`AbstractFormRenderer`) that exports a `FormSchema` to W3C XForms 1.1
XML using `lxml`. It registers itself with the render dispatcher
introduced in Wave 1 under the `"xml"` key.

**Q5 resolution (overrides Module 6's "structural only" wording in the
spec body):** V1 MUST emit `<xf:bind>` constraint expressions derived
from `FieldConstraints`, in addition to the structural model + UI
bindings. This task scope is bind-expressions-IN, not deferred.

Spec sections: §1 Goals (XForms 1.1 export); §3 Module 6; §6 Codebase
Contract (`AbstractFormRenderer.render()` signature); §8 Q5
(resolution: include).

---

## Scope

1. **Create** `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/xforms.py`
   defining `class XFormsRenderer(AbstractFormRenderer)` with
   `async def render(self, form, style=None, *, locale="en",
   prefilled=None, errors=None) -> RenderedForm`.
2. **Map structure**:
   - Root: `<xf:model>` with `<xf:instance>` containing the data tree
     (one element per form field, hierarchical by section).
   - Each `FormSection` → `<xf:group ref="<section_id>">` with the
     section title as `<xf:label>`.
   - Each `FormField` → an XForms control element keyed off `field_type`:

     | FieldType | XForms element |
     |---|---|
     | TEXT, EMAIL, URL, PHONE, PASSWORD, NUMBER, INTEGER | `<xf:input>` |
     | TEXT_AREA | `<xf:textarea>` |
     | BOOLEAN | `<xf:input>` with `<xf:hint>` "true/false" (no native checkbox in XForms 1.1; alternative `<xf:select1>` with two items also acceptable — pick one and document) |
     | DATE | `<xf:input>` with bind `type="xs:date"` |
     | DATETIME | `<xf:input>` with bind `type="xs:dateTime"` |
     | TIME | `<xf:input>` with bind `type="xs:time"` |
     | SELECT | `<xf:select1>` + `<xf:item>` per `FieldOption` |
     | MULTI_SELECT | `<xf:select>` + `<xf:item>` per `FieldOption` |
     | FILE, IMAGE | `<xf:upload>` (with `mediatype` attribute for IMAGE) |
     | COLOR | `<xf:input>` |
     | HIDDEN | `<xf:input class="hidden">` (XForms 1.1 has no native hidden) |
     | GROUP | `<xf:group>` (recurse into children) |
     | ARRAY | `<xf:repeat>` with `item_template` as the row layout |

3. **Map constraints (Q5)** — for each field, emit one `<xf:bind>` with:
   - `nodeset="<absolute path to the data node>"`.
   - `required="true()"` if `FormField.required`.
   - `readonly="true()"` if `FormField.read_only`.
   - `type="xs:<type>"` per the table above (`xs:string`,
     `xs:decimal`, `xs:integer`, `xs:date`, `xs:dateTime`, `xs:time`,
     `xs:boolean`, `xs:anyURI`).
   - `constraint="<xpath>"` derived from `FieldConstraints`:
     - `min_length` / `max_length` → `string-length(.) >= N` /
       `<= N`.
     - `min_value` / `max_value` → `. >= N` / `. <= N`.
     - `pattern` → `regex(., '<pattern>')`.
     - Multiple constraints joined by ` and `.
   - `relevant="<xpath>"` if `depends_on` is set (translated from
     the `DependencyRule` model — at least the `field_id == value`
     simple case; document any unsupported operators in a docstring).
4. **Namespace**: `xmlns:xf="http://www.w3.org/2002/xforms"`,
   `xmlns:xs="http://www.w3.org/2001/XMLSchema"`,
   `xmlns:ev="http://www.w3.org/2001/xml-events"`.
5. **Output**: `RenderedForm(content=<bytes>,
   content_type="application/xml")`. Pretty-printed XML
   (`pretty_print=True` in `lxml.etree.tostring`).
6. **Wire into dispatcher**: in `XFormsRenderer.__init__` or in a
   side-effect block at the bottom of the module, do:
   ```python
   from parrot_formdesigner.api.render import register_renderer
   register_renderer("xml", XFormsRenderer())
   ```
   But: **do NOT do this at module top-level if it triggers an import
   of `api/` from `renderers/`** — that creates a circular dep.
   Instead, register it in the `parrot_formdesigner.api.render` module
   itself by extending the seed dict (or expose a small
   `register_xforms()` helper called from `api/__init__.py` at import
   time).
   **Recommended pattern**: edit `api/render.py` to add `xforms`
   import lazily — see Implementation Notes below for the exact
   wiring.
7. **Tests** at `packages/parrot-formdesigner/tests/unit/renderers/test_xforms.py`:
   - Output declares `xmlns:xf` namespace.
   - Each section produces `<xf:group>`.
   - `FieldType.TEXT` → `<xf:input>`; `SELECT` → `<xf:select1>` with
     N `<xf:item>` (N = `len(options)`); `MULTI_SELECT` → `<xf:select>`.
   - `required=True` produces `<xf:bind required="true()" .../>`.
   - `FieldConstraints(max_length=10)` produces a bind with
     `constraint="string-length(.) <= 10"`.
   - Output is parseable by `lxml.etree.fromstring`.
   - `XFormsRenderer().render(form)` returns `RenderedForm` with
     `content_type == "application/xml"`.
8. **Integration test** at
   `packages/parrot-formdesigner/tests/integration/test_render_xml.py`:
   - Boot aiohttp app, `setup_form_api`, register a sample form,
     `GET /api/v1/forms/{id}/render/xml` returns 200 with
     `Content-Type: application/xml` and a parseable XForms doc.

**NOT in scope:**
- XForms parser / round-trip import (Non-Goal).
- XFA renderer (Non-Goal).
- Mapping the full `DependencyRule` AST — only `field_id == value`
  for `relevant=`. Anything more complex falls back to no `relevant`
  attribute and a docstring TODO.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/xforms.py` | CREATE | `XFormsRenderer` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py` | MODIFY | Register `xforms` under `"xml"` key |
| `packages/parrot-formdesigner/tests/unit/renderers/test_xforms.py` | CREATE | Unit tests |
| `packages/parrot-formdesigner/tests/integration/test_render_xml.py` | CREATE | E2E |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot_formdesigner.core.schema import (
    FormSchema, FormSection, FormField, RenderedForm,
)
# verified: packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:21,68,108,140
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.core.constraints import FieldConstraints  # path verified at packages/parrot-formdesigner/src/parrot_formdesigner/core/constraints.py
from parrot_formdesigner.core.options import FieldOption           # path verified at packages/parrot-formdesigner/src/parrot_formdesigner/core/options.py
from parrot_formdesigner.renderers.base import AbstractFormRenderer
# verified: packages/parrot-formdesigner/src/parrot_formdesigner/renderers/base.py:14
from lxml import etree                                              # already installed (6.1.0)
```

### `AbstractFormRenderer` contract

```python
class AbstractFormRenderer(ABC):
    @abstractmethod
    async def render(
        self,
        form: FormSchema,
        style: StyleSchema | None = None,
        *,
        locale: str = "en",
        prefilled: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> RenderedForm: ...
```

`XFormsRenderer.render` MUST honour this exact signature. `style`,
`prefilled`, `errors` may be ignored by V1 of the XForms renderer
(they're a UI/HTML concern); document the no-op in the docstring.

### `FormField` attributes used

```python
# core/schema.py:21 — verified
field_id: str
field_type: FieldType
label: LocalizedString               # use _localize(label, locale)
description: LocalizedString | None
placeholder: LocalizedString | None  # → <xf:hint>
required: bool
read_only: bool
constraints: FieldConstraints | None
options: list[FieldOption] | None    # for SELECT / MULTI_SELECT
options_source: OptionsSource | None
depends_on: DependencyRule | None
children: list[FormField] | None     # for GROUP
item_template: FormField | None      # for ARRAY → xf:repeat
```

### `FieldConstraints` attributes

Verify by reading `packages/parrot-formdesigner/src/parrot_formdesigner/core/constraints.py`
before implementing the constraint mapping. Likely fields:
`min_length`, `max_length`, `min_value`, `max_value`, `pattern`,
plus possibly `enum_values` and custom validators. Map only the ones
you can express in XPath; ignore the rest with a logger warning.

### Does NOT Exist

- ~~`AbstractFormRenderer.format_name`~~ — not on the base class.
- ~~`FormSchema.to_xforms()`~~ — there is no convenience method;
  the renderer has to build the tree itself.
- ~~`FieldType.SECTION` / `FieldType.ROOT`~~ — sections are NOT
  field types.
- ~~`lxml.etree.XForms` helper~~ — `lxml` does not have an
  XForms-specific helper; you build elements with
  `etree.Element("{http://www.w3.org/2002/xforms}input")` or via the
  `nsmap=` argument.
- ~~A `tests/unit/renderers/` directory~~ — verify whether it exists;
  if not, create it with an `__init__.py`.

---

## Implementation Notes

### Pattern to Follow

Look at the existing `HTML5Renderer` and `AdaptiveCardRenderer`
(`packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py`,
`adaptive_card.py`) for:

- Locale resolution pattern (turning `LocalizedString` into a string).
- How `style`, `prefilled`, `errors` are typically handled / ignored.
- Module-level logger.

### Recommended Wiring (avoid circular imports)

Edit `api/render.py` to lazily import the renderers it owns, OR:

```python
# api/render.py
def _seed_renderers():
    global _RENDERERS
    if _RENDERERS:  # already seeded
        return
    from parrot_formdesigner.renderers.html5 import HTML5Renderer
    from parrot_formdesigner.renderers.adaptive_card import AdaptiveCardRenderer
    from parrot_formdesigner.renderers.xforms import XFormsRenderer
    _RENDERERS["html"] = HTML5Renderer()
    _RENDERERS["adaptive"] = AdaptiveCardRenderer()
    _RENDERERS["xml"] = XFormsRenderer()
```

Call `_seed_renderers()` from `api/__init__.py` AFTER the
`controls.builtin` side-effect import. This way `renderers/xforms.py`
does NOT import from `api/`, breaking the circular dependency.

### Key Constraints

- Async signature is required by the base class even though the
  rendering itself is sync; the body can be sync code wrapped in an
  async def. If you find a hot path > 50 ms, `await
  asyncio.to_thread(...)`.
- Pretty-print output for human-readability in tests.
- Use namespaces correctly — XForms validators are unforgiving.
- Each `<xf:bind>` MUST appear inside `<xf:model>` (not inside the
  control tree).

---

## Acceptance Criteria

- [ ] `from parrot_formdesigner.renderers.xforms import XFormsRenderer`
      succeeds.
- [ ] `XFormsRenderer` is a subclass of `AbstractFormRenderer`.
- [ ] `await XFormsRenderer().render(form)` returns
      `RenderedForm(content=<bytes>, content_type="application/xml")`.
- [ ] Output declares `xmlns:xf="http://www.w3.org/2002/xforms"` and
      is parseable by `lxml.etree.fromstring`.
- [ ] Each `FormSection` → `<xf:group>` with the section title as
      `<xf:label>`.
- [ ] `FieldType.TEXT` → `<xf:input>`; `SELECT` → `<xf:select1>`
      with one `<xf:item>` per option; `MULTI_SELECT` →
      `<xf:select>`; `FILE`/`IMAGE` → `<xf:upload>`.
- [ ] `required=True` on a field → corresponding `<xf:bind
      required="true()" .../>` inside `<xf:model>`.
- [ ] `FieldConstraints(max_length=10)` produces a bind with
      `constraint="string-length(.) <= 10"`.
- [ ] `FieldConstraints(min_value=0, max_value=100)` produces a bind
      with `constraint=". >= 0 and . <= 100"`.
- [ ] After Wave 2a is wired, `GET /api/v1/forms/{id}/render/xml`
      returns 200 with the rendered XForms doc.
- [ ] All unit tests in `tests/unit/renderers/test_xforms.py` pass.
- [ ] Integration test passes:
      `pytest packages/parrot-formdesigner/tests/integration/test_render_xml.py -v`.
- [ ] Metadata-only init test (TASK-1044) is still green —
      `parrot_formdesigner/__init__.py` does NOT pull `xforms.py` or
      `lxml`.
- [ ] No linting errors:
      `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/renderers/xforms.py`.

---

## Test Specification

```python
# tests/unit/renderers/test_xforms.py
import pytest
from lxml import etree
from parrot_formdesigner.core.schema import FormSchema, FormSection, FormField
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.core.constraints import FieldConstraints
from parrot_formdesigner.renderers.xforms import XFormsRenderer

XF = "{http://www.w3.org/2002/xforms}"


@pytest.fixture
def simple_form() -> FormSchema:
    return FormSchema(
        form_id="t", title={"en": "Test"},
        sections=[FormSection(section_id="s1", fields=[
            FormField(field_id="name", field_type=FieldType.TEXT,
                      label={"en": "Name"}, required=True),
            FormField(field_id="age", field_type=FieldType.INTEGER,
                      label={"en": "Age"},
                      constraints=FieldConstraints(min_value=0, max_value=120)),
        ])],
    )


async def test_render_returns_xml(simple_form):
    out = await XFormsRenderer().render(simple_form)
    assert out.content_type == "application/xml"
    root = etree.fromstring(out.content)
    assert root.nsmap.get("xf") == "http://www.w3.org/2002/xforms"


async def test_section_emits_xf_group(simple_form):
    out = await XFormsRenderer().render(simple_form)
    root = etree.fromstring(out.content)
    groups = root.findall(f".//{XF}group")
    assert len(groups) == 1


async def test_required_field_has_bind(simple_form):
    out = await XFormsRenderer().render(simple_form)
    root = etree.fromstring(out.content)
    binds = root.findall(f".//{XF}bind[@required='true()']")
    assert len(binds) >= 1


async def test_constraint_min_max(simple_form):
    out = await XFormsRenderer().render(simple_form)
    root = etree.fromstring(out.content)
    bind = next(b for b in root.findall(f".//{XF}bind")
                if b.get("nodeset", "").endswith("age"))
    assert ">= 0" in bind.get("constraint", "")
    assert "<= 120" in bind.get("constraint", "")
```

---

## Agent Instructions

1. Read the spec, especially Module 6 + §8 Q5 resolution.
2. Verify TASK-1044 is in `tasks/completed/` — Wave 1 must be done.
3. Read `core/constraints.py`, `core/options.py`, and the existing
   renderers (`html5.py`, `adaptive_card.py`) before writing
   `xforms.py`.
4. Build the renderer top-down: structure → control mapping → bind
   generation.
5. Wire into the dispatcher per the lazy-seed pattern in
   §Implementation Notes.
6. Move this task to `sdd/tasks/completed/`, update the index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-05-07
**Notes**:
- Created `parrot_formdesigner/renderers/xforms.py` with `XFormsRenderer(AbstractFormRenderer)`. Output is `RenderedForm(content=<bytes>, content_type="application/xml")`, pretty-printed with `xmlns:xf` and `xmlns:xs` namespaces.
- Field-type → XForms mapping per spec (TEXT → `<xf:input>`, SELECT → `<xf:select1>`, MULTI_SELECT → `<xf:select>`, FILE/IMAGE → `<xf:upload>`, GROUP → `<xf:group>`, ARRAY → `<xf:repeat>`, etc.).
- **Q5 RESOLVED**: emits `<xf:bind>` constraint expressions derived from `FieldConstraints` (min/max length → `string-length(.) >= N`, min/max value → `. >= N`, pattern → `regex(., '...')`, multiple constraints joined by ` and `).
- `<xf:bind>` also emits `required="true()"`, `readonly="true()"`, `type="xs:<type>"`, and `relevant="<xpath>"` for simple `field_id == value` dependencies (more complex AND/OR trees are skipped with a `logger.debug`).
- Wired into `api/render.py:_seed_default_renderers` under the `"xml"` key (lazy import to avoid circular dependency).
- All 13 unit tests pass; 1 integration test passes (`tests/integration/test_render_xml.py`).
- Metadata-only init contract (TASK-1044) verified still green.
