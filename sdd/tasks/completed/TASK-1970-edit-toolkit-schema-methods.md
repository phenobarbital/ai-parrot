# TASK-1970: EditToolkit Schema-Aware Methods

**Feature**: FEAT-388 — Deterministic CreateFormTool
**Spec**: `sdd/specs/deterministic-creationformtool.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1968
**Assigned-to**: unassigned

---

## Context

This task adds schema-aware creation methods to `EditToolkit` so that LLM agents
(and programmatic callers) can add fields and sections from raw JSON dicts with
shortcut expansion — without needing to construct fully-validated `FormField` /
`FormSection` objects manually. The methods delegate to `FormAssembler` (TASK-1968)
for shortcut expansion, then to the existing `add_field()` / `add_section()` operations.

Implements spec Module 3.

---

## Scope

- Add `add_field_from_schema(section_id, field_schema, position)` method to `EditToolkit`
- Add `add_section_from_schema(section_schema, position)` method to `EditToolkit`
- Both methods accept raw dicts with shortcuts (auto-IDs, string field_types)
- Both delegate to `FormAssembler.assemble_field()` / `assemble_section()` for expansion
- Then delegate to existing `add_field()` / `add_section()` for the actual mutation
- Write unit tests

**NOT in scope**:
- Modifying `FormAssembler` (TASK-1968)
- Modifying `CreateFormTool` (TASK-1969)
- Integration/roundtrip tests (TASK-1971)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/tools/edit_toolkit.py` | MODIFY | Add two new methods |
| `packages/parrot-formdesigner/tests/unit/test_edit_toolkit_schema.py` | CREATE | Unit tests for new methods |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.assembler import FormAssembler  # assembler.py (created by TASK-1968)
from parrot_formdesigner.core.schema import FormSchema, FormSection, FormField  # core/schema.py
from parrot_formdesigner.tools.edit_toolkit import EditToolkit  # tools/edit_toolkit.py:50
from parrot.tools.toolkit import AbstractToolkit  # already imported in edit_toolkit.py
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/tools/edit_toolkit.py:50
class EditToolkit(AbstractToolkit):
    def __init__(self, form: FormSchema, **kwargs: Any) -> None:  # line 74
    @property
    def form(self) -> FormSchema:  # line 91

    async def add_field(self, section_id: str, field: dict,
                        position: int | None = None) -> dict:  # line 321
        # Validates via FormField.model_validate(field), then _apply_add_field

    async def add_section(self, section: dict,
                          position: int | None = None) -> dict:  # line 596
        # Validates via FormSection.model_validate(section), then _apply_add_section
```

### Does NOT Exist
- ~~`EditToolkit.add_field_from_schema()`~~ — does not exist yet; this task creates it
- ~~`EditToolkit.add_section_from_schema()`~~ — does not exist yet
- ~~`EditToolkit._assembler`~~ — no assembler attribute exists; create one or instantiate inline

---

## Implementation Notes

### Pattern to Follow

The new methods should follow the same pattern as `add_field()` (line 321) and
`add_section()` (line 596) — but add a shortcut expansion step before calling them:

```python
async def add_field_from_schema(
    self,
    section_id: str,
    field_schema: dict,
    position: int | None = None,
) -> dict:
    """Add a field from a raw schema dict with shortcut expansion.

    Args:
        section_id: ID of the section to add the field to.
        field_schema: Dict with field definition (supports shortcuts:
            auto-generated field_id from label, string field_type).
        position: Optional 0-based insertion index.

    Returns:
        Success dict with added field_id, or error dict on failure.
    """
    try:
        assembler = FormAssembler()
        validated_field = assembler.assemble_field(field_schema)
        return await self.add_field(section_id, validated_field.model_dump(), position)
    except (ValidationError, ValueError) as exc:
        return {"error": f"Invalid field schema: {exc}"}
```

### Key Constraints
- Instantiate `FormAssembler()` inline (stateless, cheap) — no need to store as attribute
- Delegate to existing `add_field()` / `add_section()` — reuse all their validation and error handling
- Return the same dict format as the existing methods (success/error dicts)
- These methods should be async (matching the existing toolkit pattern)

---

## Acceptance Criteria

- [ ] `add_field_from_schema(section_id, field_schema)` creates a field from raw dict with shortcuts
- [ ] `add_section_from_schema(section_schema, position)` creates a section from raw dict with shortcuts
- [ ] Auto-generated `field_id` from label works through the new method
- [ ] String `field_type` values accepted (e.g., `"email"` → `FieldType.EMAIL`)
- [ ] Invalid field dict returns error dict (same format as `add_field`)
- [ ] All tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_edit_toolkit_schema.py -v`
- [ ] Existing EditToolkit tests still pass: `pytest packages/parrot-formdesigner/tests/test_edit_toolkit.py -v`
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/tools/edit_toolkit.py`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_edit_toolkit_schema.py
import pytest
from parrot_formdesigner.tools.edit_toolkit import EditToolkit
from parrot_formdesigner.core.schema import FormSchema, FormSection, FormField
from parrot_formdesigner.core.types import FieldType


@pytest.fixture
def base_form():
    return FormSchema(
        form_id="test-form",
        title="Test Form",
        sections=[
            FormSection(
                section_id="main",
                title="Main",
                fields=[
                    FormField(
                        field_id="existing",
                        field_type=FieldType.TEXT,
                        label="Existing Field",
                    ),
                ],
            ),
        ],
    )


@pytest.fixture
def toolkit(base_form):
    return EditToolkit(base_form)


class TestAddFieldFromSchema:
    @pytest.mark.asyncio
    async def test_with_shortcuts(self, toolkit):
        result = await toolkit.add_field_from_schema(
            "main",
            {"label": "Email Address", "field_type": "email", "required": True},
        )
        assert result["success"] is True
        assert result["field_id"] == "email_address"

    @pytest.mark.asyncio
    async def test_with_full_field(self, toolkit):
        result = await toolkit.add_field_from_schema(
            "main",
            {"field_id": "custom_id", "field_type": "text", "label": "Custom"},
        )
        assert result["success"] is True
        assert result["field_id"] == "custom_id"

    @pytest.mark.asyncio
    async def test_with_position(self, toolkit):
        result = await toolkit.add_field_from_schema(
            "main",
            {"label": "First", "field_type": "text"},
            position=0,
        )
        assert result["success"] is True
        assert toolkit.form.sections[0].fields[0].field_id == "first"

    @pytest.mark.asyncio
    async def test_invalid_schema(self, toolkit):
        result = await toolkit.add_field_from_schema("main", {})
        assert "error" in result


class TestAddSectionFromSchema:
    @pytest.mark.asyncio
    async def test_with_shortcuts(self, toolkit):
        result = await toolkit.add_section_from_schema({
            "title": "Contact Info",
            "fields": [
                {"label": "Phone", "field_type": "phone"},
            ],
        })
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_with_position(self, toolkit):
        result = await toolkit.add_section_from_schema(
            {"title": "First Section", "fields": []},
            position=0,
        )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_invalid_section(self, toolkit):
        result = await toolkit.add_section_from_schema({"invalid": True})
        assert "error" in result
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/deterministic-creationformtool.spec.md` for full context
2. **Check dependencies** — verify TASK-1968 is in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm `EditToolkit` signatures and `FormAssembler` exists
4. **Modify** `edit_toolkit.py` — add two new methods
5. **Create** `test_edit_toolkit_schema.py`
6. **Run tests**: `pytest packages/parrot-formdesigner/tests/unit/test_edit_toolkit_schema.py -v`
7. **Run existing tests**: `pytest packages/parrot-formdesigner/tests/test_edit_toolkit.py -v`
8. **Update status** in per-spec index → `"done"`
9. **Move** this file to `sdd/tasks/completed/`

---

## Completion Note

**Completed by**: sdd-worker (Sonnet)
**Date**: 2026-07-30
**Notes**: Added `add_field_from_schema(section_id, field_schema, position=None)`
and `add_section_from_schema(section_schema, position=None)` to `EditToolkit`,
following the exact pattern given in the task: instantiate `FormAssembler()`
inline, catch `(ValidationError, ValueError)` and return an error dict, then
delegate to the existing `add_field()`/`add_section()` via
`validated.model_dump()`. Added `from ..assembler import FormAssembler`.
Created 7 unit tests in `test_edit_toolkit_schema.py` matching the task's Test
Specification exactly. All 7 pass; the pre-existing 65 tests across
`tests/test_edit_toolkit.py` and `tests/unit/test_edit_toolkit_rules.py` still
pass unchanged. `ruff check` on `edit_toolkit.py` shows the same 11
pre-existing findings (10 `BLE001` + 1 `RUF059`) that existed before this
task (verified via `git show HEAD~4:...edit_toolkit.py`) — no new findings.

Because `EditToolkit` (`AbstractToolkit`) auto-discovers every public async
method as an LLM-callable tool, the two new methods are automatically
exposed as `add_field_from_schema`/`add_section_from_schema` tools — this
is the intended behavior per the task's own Context ("so that LLM agents
... can add fields and sections from raw JSON dicts"), not a deviation.
This surfaced that `tests/test_edit_toolkit.py::TestEditToolkitTools::
test_tool_definitions_count` and `::test_tool_definitions_has_required_names`
hard-code a stale tool count/name set (documented as "15 tools") that was
**already wrong before this task** — the toolkit actually exposes 20 tools
today (5 dependency-rule tools — `add_dependency`, `update_dependency`,
`remove_dependency`, `add_post_dependency`, `remove_post_dependency` — were
added by a prior feature without updating this test). Verified via
`git stash` that both tests fail identically on the pre-TASK-1970 commit.
Since `test_edit_toolkit.py` is not in this task's declared file list and
the failure is pre-existing/unrelated, I left it untouched per the File
Fidelity rule and reverted an earlier over-eager fix attempt. Flagging here
for a follow-up task to refresh that test against the toolkit's actual
tool surface (now 22 with this task's 2 additions).

**Deviations from spec**: none.
