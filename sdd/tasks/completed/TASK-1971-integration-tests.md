# TASK-1971: Integration Tests

**Feature**: FEAT-388 — Deterministic CreateFormTool
**Spec**: `sdd/specs/deterministic-creationformtool.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1968, TASK-1969, TASK-1970
**Assigned-to**: unassigned

---

## Context

This task adds integration and roundtrip tests that verify the full pipeline
works end-to-end: JSON Schema → FormAssembler → FormSchema → JsonSchemaRenderer
roundtrip, and native-shortcut vs explicit-FormSchema equivalence. These tests
validate that all three modules (FormAssembler, CreateFormTool integration,
EditToolkit expansion) work together correctly.

Implements spec Module 4 (integration test portion).

---

## Scope

- Write roundtrip test: JSON Schema → `FormAssembler` → `FormSchema` → `JsonSchemaRenderer` → compare
- Write equivalence test: same form built via native shortcuts and explicit `FormSchema` produce identical output
- Write end-to-end test: `CreateFormTool.execute(schema=...)` → `EditToolkit.add_field_from_schema()` on result
- Verify `FormValidator.check_schema()` runs correctly on deterministic output

**NOT in scope**:
- Modifying any implementation code (this is test-only)
- Testing LLM paths (covered by existing tests)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/tests/unit/test_deterministic_integration.py` | CREATE | Integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.assembler import FormAssembler       # assembler.py (TASK-1968)
from parrot_formdesigner.tools.create_form import CreateFormTool  # tools/create_form.py
from parrot_formdesigner.tools.edit_toolkit import EditToolkit    # tools/edit_toolkit.py
from parrot_formdesigner.renderers.jsonschema import JsonSchemaRenderer  # renderers/jsonschema.py
from parrot_formdesigner.extractors import JsonSchemaExtractor    # extractors/__init__.py:7
from parrot_formdesigner.core.schema import FormSchema, FormSection, FormField  # core/schema.py
from parrot_formdesigner.core.types import FieldType              # core/types.py
from parrot_formdesigner.services.validators import FormValidator  # services/validators.py
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/jsonschema.py:112
class JsonSchemaRenderer(AbstractFormRenderer):
    async def render(
        self,
        form: FormSchema,
        style: StyleSchema | None = None,
        *,
        locale: str = "en",
        prefilled: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> RenderedForm:
        # CORRECTED (was stale): render() is async and returns a RenderedForm
        # (core/schema.py), not a dict. The JSON Schema dict is on
        # RenderedForm.content — e.g. `(await renderer.render(form)).content["properties"]`.

# packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py
class FormValidator:
    def check_schema(self, form: FormSchema) -> list[str]:
        # Returns list of circular dependency error strings (empty if clean)
```

### Does NOT Exist
- ~~`JsonSchemaRenderer.to_dict()`~~ — use `render()` method, not `to_dict`
- ~~`FormValidator.validate()`~~ — use `check_schema()`, not `validate`
- ~~`JsonSchemaRenderer.render()` returning a plain `dict` synchronously~~ — CORRECTED:
  it is `async def render(...) -> RenderedForm`; call `await renderer.render(form)`
  and read `.content` for the JSON Schema dict (verified at
  `renderers/jsonschema.py:167`).

---

## Implementation Notes

### Roundtrip Test Strategy
JSON Schema → `JsonSchemaExtractor.extract()` → `FormSchema` → `JsonSchemaRenderer.render()`
→ compare structural equivalence (field names, types, constraints). Exact byte equality
is not expected because the renderer adds `x-` extensions and may reorder properties.

### Equivalence Test Strategy
Build the same form two ways:
1. Via shortcuts: `FormAssembler.assemble(native_with_shortcuts)`
2. Via explicit: `FormSchema(form_id=..., title=..., sections=[...])`
Compare `model_dump()` output — should be identical after shortcut expansion.

---

## Acceptance Criteria

- [ ] Roundtrip test: JSON Schema → assemble → render → field names and types preserved
- [ ] Equivalence test: shortcut form == explicit form after assembly
- [ ] End-to-end test: CreateFormTool(schema=...) → EditToolkit.add_field_from_schema works
- [ ] FormValidator produces no circular dependency errors on deterministic forms
- [ ] All tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_deterministic_integration.py -v`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_deterministic_integration.py
import pytest
from unittest.mock import MagicMock, AsyncMock
from parrot_formdesigner.assembler import FormAssembler
from parrot_formdesigner.tools.create_form import CreateFormTool
from parrot_formdesigner.tools.edit_toolkit import EditToolkit
from parrot_formdesigner.renderers.jsonschema import JsonSchemaRenderer
from parrot_formdesigner.core.schema import FormSchema, FormSection, FormField
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.validators import FormValidator


class TestRoundtrip:
    @pytest.mark.asyncio
    async def test_jsonschema_roundtrip(self):
        """JSON Schema → assemble → render preserves field structure."""
        original = {
            "type": "object",
            "title": "Feedback",
            "properties": {
                "name": {"type": "string", "minLength": 1},
                "email": {"type": "string", "format": "email"},
                "rating": {"type": "integer", "minimum": 1, "maximum": 5},
            },
            "required": ["name", "email"],
        }
        assembler = FormAssembler()
        form = assembler.assemble(original, form_id="feedback")

        renderer = JsonSchemaRenderer()
        # CORRECTED: render() is async and returns a RenderedForm — see the
        # Codebase Contract fix above (was documented as a sync dict-return).
        rendered = (await renderer.render(form)).content

        assert "name" in rendered.get("properties", {})
        assert "email" in rendered.get("properties", {})
        assert "rating" in rendered.get("properties", {})


class TestEquivalence:
    def test_shortcut_equals_explicit(self):
        """Same form via shortcuts and explicit construction are equivalent."""
        assembler = FormAssembler()
        shortcut_form = assembler.assemble({
            "form_id": "equiv-test",
            "title": "Test",
            "sections": [{
                "section_id": "main",
                "fields": [
                    {"field_id": "name", "field_type": "text", "label": "Name", "required": True},
                    {"field_id": "age", "field_type": "integer", "label": "Age"},
                ],
            }],
        })

        explicit_form = FormSchema(
            form_id="equiv-test",
            title="Test",
            sections=[FormSection(
                section_id="main",
                fields=[
                    FormField(field_id="name", field_type=FieldType.TEXT, label="Name", required=True),
                    FormField(field_id="age", field_type=FieldType.INTEGER, label="Age"),
                ],
            )],
        )

        assert shortcut_form.model_dump() == explicit_form.model_dump()


class TestEndToEnd:
    @pytest.mark.asyncio
    async def test_create_then_edit(self):
        """CreateFormTool produces form, EditToolkit adds field from schema."""
        mock_client = MagicMock()
        tool = CreateFormTool(client=mock_client)
        result = await tool.execute(
            schema={
                "form_id": "e2e-test",
                "title": "E2E",
                "sections": [{"section_id": "s1", "fields": [
                    {"field_id": "name", "field_type": "text", "label": "Name"},
                ]}],
            },
        )
        assert result.success is True

        form = FormSchema.model_validate(result.metadata["form"])
        toolkit = EditToolkit(form)
        add_result = await toolkit.add_field_from_schema(
            "s1",
            {"label": "Email", "field_type": "email", "required": True},
        )
        assert add_result["success"] is True
        assert len(toolkit.form.sections[0].fields) == 2


class TestValidatorIntegration:
    def test_no_circular_deps_on_deterministic(self):
        """Deterministic forms pass circular dependency check."""
        assembler = FormAssembler()
        form = assembler.assemble_from_fields(
            [
                {"label": "A", "field_type": "text"},
                {"label": "B", "field_type": "text"},
            ],
            title="Validator Test",
        )
        validator = FormValidator()
        errors = validator.check_schema(form)
        assert errors == []
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/deterministic-creationformtool.spec.md` for full context
2. **Check dependencies** — verify TASK-1968, TASK-1969, TASK-1970 are in `tasks/completed/`
3. **Verify** that `FormAssembler`, `CreateFormTool` deterministic path, and `EditToolkit`
   schema methods all exist and work
4. **Create** `test_deterministic_integration.py`
5. **Run tests**: `pytest packages/parrot-formdesigner/tests/unit/test_deterministic_integration.py -v`
6. **Run full suite**: `pytest packages/parrot-formdesigner/tests/ -v` (ensure no regressions)
7. **Update status** in per-spec index → `"done"`
8. **Move** this file to `sdd/tasks/completed/`

---

## Completion Note

**Completed by**: sdd-worker (session continuation)
**Date**: 2026-07-30
**Notes**: Created `test_deterministic_integration.py` exactly per the Test
Specification (roundtrip, equivalence, end-to-end, validator-integration).
Before implementing, verified the Codebase Contract against the actual
source: `JsonSchemaRenderer.render()` is `async` and returns a
`RenderedForm` (not a sync `dict`), so the contract's stale "Existing
Signatures" and the Test Specification's `renderer.render(form)` call were
corrected in-place to `(await renderer.render(form)).content` (this
correction had already been applied to the task file and test draft in a
prior session; verified accurate against `renderers/jsonschema.py:167` and
adopted as-is). All other imports/signatures (`FormAssembler.assemble` /
`assemble_from_fields`, `CreateFormTool.execute(schema=...)` via
`AbstractTool.execute()` → `_execute()`, `EditToolkit.add_field_from_schema`,
`FormValidator.check_schema`) were verified against source and matched the
contract exactly.

All 4 tests pass (`pytest packages/parrot-formdesigner/tests/unit/test_deterministic_integration.py -v`).
Ran the full `packages/parrot-formdesigner/tests/unit/` suite (1267 passed,
14 pre-existing failures in `controls/`, `test_core_models.py`,
`test_field_helpers.py`, `test_init_imports_metadata_only.py`,
`test_venue_service.py` — none of these files are touched by this feature
branch per `git diff dev...HEAD --stat`, confirming the failures pre-date
FEAT-388 and are unrelated).

Note: this worktree's `parrot-formdesigner` editable install resolves to
the main checkout, not the worktree — tests must be run with
`PYTHONPATH="$(pwd)/packages/parrot-formdesigner/src:$PYTHONPATH"` prefixed
to pick up the worktree's own source.

**Deviations from spec**: none
