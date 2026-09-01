# TASK-2682: XForms Renderer — Emit content_type in <xf:bind>

**Feature**: FEAT-488 — FormField Content-Type
**Spec**: `sdd/specs/formfield-content-type.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2677
**Assigned-to**: unassigned

---

## Context

The XForms renderer exports `FormSchema` as a W3C XForms 1.1 document.
This task extends it to emit `content_type` and `accept_content_types`
as plain string attributes on `<xf:bind>` elements for fields that declare
them — making the declared MIME type visible to XForms consumers.

Implements spec §3 Module 6.

---

## Scope

- In `renderers/xforms.py`, when generating `<xf:bind>` elements for a field,
  check `field.content_type` and `field.accept_content_types`.
- If `field.content_type` is set, add attribute `x-content-type="<value>"` to
  the `<xf:bind>` element.
- If `field.accept_content_types` is set, add attribute
  `x-accept-content-types="<comma-joined-value>"` (join the list with `,`).
- Use plain string attributes (no custom XML namespace required for v1).
- Both attributes are omitted when the corresponding `FormField` attributes are `None`.

**NOT in scope**: hard MIME-type validation, new `FieldType` mappings,
or changes to any other renderer.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/xforms.py` | MODIFY | Emit `x-content-type` / `x-accept-content-types` attributes on `<xf:bind>` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# renderers/xforms.py — existing imports (verified at file head)
from lxml import etree
from ..core.constraints import (ConditionOperator, DependencyRule, FieldConstraints)
from ..core.options import FieldOption
from ..core.schema import FormField, FormSchema, FormSection, FormSubsection, RenderedForm
from ..core.style import StyleSchema
from ..core.types import FieldType, LocalizedString
from .base import AbstractFormRenderer, FallbackRenderer, FieldRenderer

# No new imports required
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/xforms.py

XF_NS = "http://www.w3.org/2002/xforms"   # line ~52
XS_NS = "http://www.w3.org/2001/XMLSchema" # line ~53
EV_NS = "http://www.w3.org/2001/xml-events" # line ~54

NSMAP = {"xf": XF_NS, "xs": XS_NS, "ev": EV_NS}  # line ~56

def _qn(local: str) -> str:
    """Return Clark-notation XForms qualified name."""
    return f"{{{XF_NS}}}{local}"  # line ~60

_FIELD_TO_XFORMS: dict[FieldType, tuple[str, str | None]] = {
    FieldType.TEXT: ("input", "string"),
    FieldType.TEXT_AREA: ("textarea", "string"),
    # ...
}

class XFormsRenderer(AbstractFormRenderer):
    # Read the file to find the <xf:bind> construction site before editing.
    # Typical pattern: etree.SubElement(model, _qn("bind"), ref=field_id, ...)
    ...
```

**CRITICAL**: Read `xforms.py` to find where `<xf:bind>` elements are built
(look for `_qn("bind")` or `"bind"`). The `<xf:bind>` construction is the
exact insertion point for the new attributes.

### Does NOT Exist

- ~~`XFormsRenderer._emit_content_type()`~~ — no such helper; add inline at the bind construction site.
- ~~Custom XML namespace for `x-content-type`~~ — use plain string attributes in v1; no new namespace required.
- ~~`field.content_type` as required~~ — it is `str | None`; always guard with `is not None`.

---

## Implementation Notes

### Pattern to Follow

After building the `<xf:bind>` element for a field, add attributes conditionally:

```python
bind_el = etree.SubElement(model_el, _qn("bind"), ref=field.field_id, ...)

# FEAT-488: emit content-type metadata as plain attributes
if field.content_type is not None:
    bind_el.set("x-content-type", field.content_type)
if field.accept_content_types is not None:
    bind_el.set("x-accept-content-types", ",".join(field.accept_content_types))
```

Use `",".join(field.accept_content_types)` to serialize the list as a
comma-separated string (consistent with XForms attribute value conventions).

### Key Constraints

- Plain string attributes (no Clark-notation namespace wrapping) — `x-content-type`,
  not `{http://...}x-content-type`.
- Omit both attributes entirely (do not set to empty string) when `None`.
- Read the actual `<xf:bind>` construction site in the file before editing —
  line numbers in this contract are approximate.

### References in Codebase

- `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/xforms.py` — target file
- `packages/parrot-formdesigner/tests/unit/test_renderers.py` — existing test style

---

## Acceptance Criteria

- [ ] `<xf:bind>` element has `x-content-type` attribute when `field.content_type` is set.
- [ ] `<xf:bind>` element has `x-accept-content-types` attribute (comma-joined) when `field.accept_content_types` is set.
- [ ] Neither attribute appears when the corresponding `FormField` attribute is `None`.
- [ ] Existing XForms output for fields without content-type metadata is unchanged.
- [ ] All existing XForms renderer tests pass: `pytest packages/parrot-formdesigner/tests/unit/ -k xforms -v`
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/renderers/xforms.py`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/ (add to xforms test file)

from lxml import etree
from parrot_formdesigner.core.schema import FormField, FormSchema
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.xforms import XFormsRenderer


def test_xforms_bind_has_x_content_type():
    field = FormField(
        field_id="notes", field_type=FieldType.TEXT_AREA, label="Notes",
        content_type="text/markdown",
    )
    # wrap in minimal FormSchema (check existing xforms tests for construction)
    rendered = XFormsRenderer().render_sync(schema)
    xml = etree.fromstring(rendered.content)
    bind_els = xml.findall(".//{http://www.w3.org/2002/xforms}bind")
    notes_bind = next(b for b in bind_els if b.get("ref") == "notes")
    assert notes_bind.get("x-content-type") == "text/markdown"


def test_xforms_bind_no_x_content_type_when_none():
    field = FormField(field_id="notes", field_type=FieldType.TEXT_AREA, label="Notes")
    ...
    assert notes_bind.get("x-content-type") is None


def test_xforms_bind_x_accept_content_types_comma_joined():
    field = FormField(
        field_id="answer", field_type=FieldType.TEXT_AREA, label="Answer",
        accept_content_types=["text/plain", "application/json"],
    )
    ...
    assert answer_bind.get("x-accept-content-types") == "text/plain,application/json"
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/formfield-content-type.spec.md`.
2. **Check dependencies** — verify TASK-2677 is in `sdd/tasks/completed/`.
3. **Read `renderers/xforms.py`** — find the `<xf:bind>` construction site (search for `_qn("bind")` or `"bind"`).
4. **Update status** → `"in_progress"`.
5. **Implement** the conditional attribute additions.
6. **Verify** all acceptance criteria.
7. **Move** to `sdd/tasks/completed/TASK-2682-xforms-renderer-bind-metadata.md`.
8. **Update index** → `"completed"`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: —
**Date**: —
**Notes**: —
**Deviations from spec**: none
