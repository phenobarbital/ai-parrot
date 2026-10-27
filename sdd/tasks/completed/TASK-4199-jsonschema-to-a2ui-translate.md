# TASK-4199: `translate_jsonschema_to_a2ui` (services/a2ui_translate.py)

**Feature**: FEAT-650 — A2UI dialect for parrot-formdesigner
**Spec**: `sdd/specs/a2ui-dialect-formbuilder.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4198
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (G5). The composition helper: JSON Schema →
`JsonSchemaExtractor` → tenant stamped → `A2UIFormRenderer`. It is the
library door shared by `POST /forms/translate` (TASK-4200) and the CLI
`translate` command (TASK-4204). Depends on TASK-4198 so the composition is
faithful (sections survive).

---

## Scope

- Create `services/a2ui_translate.py` with `translate_jsonschema_to_a2ui(...)`.
- Tests `tests/unit/services/test_a2ui_translate.py` (`importorskip` for the real renderer; one fake-renderer test for the missing-extra error).

**NOT in scope**: HTTP endpoint (TASK-4200), CLI (TASK-4204).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/a2ui_translate.py` | CREATE | composition helper |
| `packages/parrot-formdesigner/tests/unit/services/test_a2ui_translate.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.extractors import JsonSchemaExtractor           # extractors/__init__.py:8
from parrot_formdesigner.renderers.base import AbstractFormRenderer      # renderers/base.py:58
from parrot_formdesigner.core.schema import FormSchema, RenderedForm     # core/schema.py:401, 671
from parrot_formdesigner.api.render import get_renderer                  # api/render.py:104 (import lazily inside the function)
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/extractors/jsonschema.py
class JsonSchemaExtractor: def extract(self, schema: dict[str, Any], *, form_id: str | None = None, title: str | None = None) -> FormSchema   # line 86
# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
class FormSchema: tenant: str | None = None (463)  → stamp via form.model_copy(update={"tenant": tenant})
# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/base.py
class AbstractFormRenderer: async def render(self, form, style=None, *, locale="en", prefilled=None, errors=None) -> RenderedForm   # line 69
# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/a2ui.py
#   tenant for the submit URL = form.tenant or _DEFAULT_TENANT (line 361) — hence the stamping step
```

### Does NOT Exist
- ~~`JsonSchemaExtractor.extract(..., tenant=...)`~~ — no tenant kwarg; stamp after extraction.
- ~~a direct JSON-Schema → component translator~~ — rejected (brainstorm Option B); composition only.
- ~~`parrot_formdesigner.services.a2ui_translate`~~ — this task creates it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/services/a2ui_translate.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/tests/unit/services/test_a2ui_translate.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/extractors/jsonschema.py#JsonSchemaExtractor",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/renderers/base.py#AbstractFormRenderer",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py#RenderedForm"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- No top-level `parrot.*` import (AC12); the renderer is resolved lazily via `get_renderer("a2ui")` unless injected.
- `RuntimeError` wording identical to `a2ui_wire._a2ui_ns` ("requires the 'ai-parrot' extra").

---

## Implementation Blueprint

### Steps (in order)
1. Write the function — *why*: three call sites share it.
2. Tests: real renderer round-trip asserts one `Card` per section with the right `parrot_section_id`s and `validate_envelope(origin=TOOL)`; fake-free missing-extra test.

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/a2ui_translate.py` (CREATE)
```python
"""JSON Schema (legacy dialect) → A2UI createSurface by composition (FEAT-650, spec §3 M4)."""

from __future__ import annotations

import logging
from typing import Any

from ..core.schema import RenderedForm
from ..extractors import JsonSchemaExtractor
from ..renderers.base import AbstractFormRenderer

logger = logging.getLogger(__name__)


async def translate_jsonschema_to_a2ui(
    schema: dict[str, Any],
    *,
    form_id: str | None = None,
    title: str | None = None,
    tenant: str | None = None,
    locale: str = "en",
    renderer: AbstractFormRenderer | None = None,
) -> RenderedForm:
    """``JsonSchemaExtractor.extract`` → tenant stamp → ``A2UIFormRenderer.render``.

    Args:
        schema: A JSON Schema document (typically ``JsonSchemaRenderer`` output).
        form_id: Slug for the resulting form (default ``"form"``).
        title: Title override.
        tenant: Stamped on the FormSchema so the surface's submit URL and
            ``parrot_tenant`` carry the caller's tenant (never read from the document).
        locale: BCP 47 tag for label resolution.
        renderer: Injected renderer (tests); default = the registered ``"a2ui"`` one.

    Raises:
        RuntimeError: when no ``"a2ui"`` renderer is available (ai-parrot extra missing).
    """
    if renderer is None:
        from ..api.render import get_renderer  # lazy: avoid api↔services import cycle

        renderer = get_renderer("a2ui")
        if renderer is None:
            raise RuntimeError("translate_jsonschema_to_a2ui requires the 'ai-parrot' extra")
    form = JsonSchemaExtractor().extract(schema, form_id=form_id, title=title)
    if tenant is not None:
        form = form.model_copy(update={"tenant": tenant})
    logger.debug("translate_jsonschema_to_a2ui: %s sections, tenant=%s", len(form.sections), tenant)
    return await renderer.render(form, locale=locale)
```
**Why this shape**: pure composition (brainstorm decision); tenant stamping after extraction is the §7 "Tenant stamping" rule.

### `packages/parrot-formdesigner/tests/unit/services/test_a2ui_translate.py` (CREATE)
```python
"""translate_jsonschema_to_a2ui — FEAT-650 TASK-4199."""

from __future__ import annotations

import pytest

from parrot_formdesigner.services.a2ui_translate import translate_jsonschema_to_a2ui


async def test_missing_extra_raises(monkeypatch):
    import parrot_formdesigner.api.render as render
    monkeypatch.setattr(render, "_RENDERERS", {})
    with pytest.raises(RuntimeError, match="ai-parrot"):
        await translate_jsonschema_to_a2ui({"type": "object", "properties": {}})


async def test_composition_preserves_sections_and_validates():
    pytest.importorskip("parrot.outputs.a2ui")
    from parrot.outputs.a2ui.catalog import validate_envelope
    from parrot.outputs.a2ui.serialization import deserialize
    from parrot_formdesigner.renderers import A2UIFormRenderer, JsonSchemaRenderer
    # FILL IN: build the 2-section fixture form from tests/unit/extractors/test_jsonschema_sections.py, render it with
    #          JsonSchemaRenderer, feed .content to translate_jsonschema_to_a2ui(tenant="acme", renderer=A2UIFormRenderer());
    #          assert Card components with parrot_section_id == "s1"/"s2" (via field extensions), root parrot_tenant == "acme",
    #          validate_envelope(deserialize(rendered.content).create_surface) passes — bounded by G5/AC8
```

### FILL IN checklist
- [ ] `test_a2ui_translate.py::test_composition_preserves_sections_and_validates` — bounded by G5/AC8.

---

## Acceptance Criteria

- [ ] Returns a `RenderedForm` whose surface passes `validate_envelope(origin=TOOL)` with sections preserved; tenant stamped from the argument only.
- [ ] Missing extra → `RuntimeError` mentioning `ai-parrot`; module imports without ai-parrot.
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/unit/services/test_a2ui_translate.py -v`; `ruff check` clean.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/services/test_a2ui_translate.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/extractors/test_jsonschema_sections.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug a2ui-dialect-formbuilder --feature-id FEAT-650`)
2. **Read the spec** §3 M4 and §7 "Tenant stamping"
3. **Check dependencies** — TASK-4198 `"done"`
4. **Verify the Codebase Contract** — `grep -n 'def extract' packages/parrot-formdesigner/src/parrot_formdesigner/extractors/jsonschema.py`
5. **Update status** in the per-spec index → `"in-progress"`, commit only the index
6. **Implement** from the blueprint; complete every `# FILL IN:`
7. **Verify** with `PYTHONPATH=packages/parrot-formdesigner/src:packages/ai-parrot/src` + Validation Commands
8. **Commit the code** — only the two files
9. **Close** with `scripts/sdd/close_task.sh TASK-4199 a2ui-dialect-formbuilder verified`
10. **Fill in the Completion Note**, commit the staged SDD state

---

## Completion Note

Implemented by codex gpt-5.6-sol; merged by sdd-worker orchestrator; merge-tier validation green (171 passed).

**Completed by**: sdd-worker orchestrator
**Date**: 2026-10-24
**Notes**:

**Deviations from spec**: none
