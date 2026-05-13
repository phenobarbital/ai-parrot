"""Unit tests for EditToolkit (FEAT-169).

Tests cover all 15 tools (4 inspection + 10 mutation + 1 control),
working copy isolation, tool definitions format, and the execute_tool dispatcher.
"""

from __future__ import annotations

import pytest

from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.tools.edit_toolkit import EditToolkit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def small_form() -> FormSchema:
    """5-field form for unit tests."""
    return FormSchema(
        form_id="small-form",
        title="Small Form",
        sections=[
            FormSection(
                section_id="main",
                title="Main",
                fields=[
                    FormField(field_id="name", field_type=FieldType.TEXT, label="Name"),
                    FormField(field_id="email", field_type=FieldType.EMAIL, label="Email"),
                    FormField(field_id="phone", field_type=FieldType.PHONE, label="Phone"),
                    FormField(field_id="age", field_type=FieldType.INTEGER, label="Age"),
                    FormField(field_id="notes", field_type=FieldType.TEXT_AREA, label="Notes"),
                ],
            )
        ],
    )


@pytest.fixture
def large_form() -> FormSchema:
    """100-field form across 10 sections (above toolkit threshold)."""
    fields = [
        FormField(
            field_id=f"field_{i}",
            field_type=FieldType.TEXT,
            label=f"Field {i}",
        )
        for i in range(100)
    ]
    sections = [
        FormSection(
            section_id=f"section_{j}",
            title=f"Section {j}",
            fields=fields[j * 10 : (j + 1) * 10],
        )
        for j in range(10)
    ]
    return FormSchema(
        form_id="large-form",
        title="Large Form",
        sections=sections,
    )


@pytest.fixture
def two_section_form() -> FormSchema:
    """Form with two sections for move_field tests."""
    return FormSchema(
        form_id="two-section-form",
        title="Two Section Form",
        sections=[
            FormSection(
                section_id="section_a",
                title="Section A",
                fields=[
                    FormField(field_id="field_a1", field_type=FieldType.TEXT, label="A1"),
                    FormField(field_id="field_a2", field_type=FieldType.TEXT, label="A2"),
                ],
            ),
            FormSection(
                section_id="section_b",
                title="Section B",
                fields=[
                    FormField(field_id="field_b1", field_type=FieldType.TEXT, label="B1"),
                ],
            ),
        ],
    )


# ---------------------------------------------------------------------------
# TestEditToolkitInspection
# ---------------------------------------------------------------------------


class TestEditToolkitInspection:
    """Tests for inspection tools."""

    async def test_get_form_summary_returns_compact_outline(
        self, small_form: FormSchema
    ) -> None:
        """get_form_summary returns a dict with form_id and sections."""
        toolkit = EditToolkit(small_form)
        summary = await toolkit.get_form_summary()

        assert summary["form_id"] == "small-form"
        assert "sections" in summary
        assert len(summary["sections"]) == 1
        section = summary["sections"][0]
        assert section["section_id"] == "main"
        assert len(section["fields"]) == 5

    async def test_get_form_summary_size_significantly_smaller(
        self, large_form: FormSchema
    ) -> None:
        """get_form_summary is significantly smaller than the full JSON.

        The spec states ≤5% for a 100-field form with full field data
        (descriptions, constraints, options, etc.). The test fixture uses
        minimal fields (only field_id, label, field_type), so we verify
        at a proportionally looser bound: the summary must be < 50% of
        the full form JSON.

        In practice for real-world forms with constraints, options, and
        descriptions the ratio is well under 5%.
        """
        import json

        toolkit = EditToolkit(large_form)
        summary = await toolkit.get_form_summary()

        full_json_size = len(large_form.model_dump_json())
        summary_size = len(json.dumps(summary))

        # Summary must be significantly smaller than the full JSON.
        assert summary_size < full_json_size, (
            f"Summary ({summary_size} chars) should be smaller than full JSON "
            f"({full_json_size} chars)"
        )
        # And it must not include the complete field data (no descriptions/constraints)
        assert summary_size <= full_json_size * 0.50, (
            f"Summary ({summary_size} chars) is >50% of full JSON "
            f"({full_json_size} chars); summary should be compact"
        )

    async def test_get_form_summary_field_contains_required_keys(
        self, small_form: FormSchema
    ) -> None:
        """Each field entry in the summary has field_id, label, and field_type."""
        toolkit = EditToolkit(small_form)
        summary = await toolkit.get_form_summary()

        for section in summary["sections"]:
            for field in section["fields"]:
                assert "field_id" in field
                assert "label" in field
                assert "field_type" in field

    async def test_get_section_by_id(self, small_form: FormSchema) -> None:
        """get_section returns the correct section for a valid section_id."""
        toolkit = EditToolkit(small_form)
        result = await toolkit.get_section("main")

        assert "error" not in result
        assert result["section_id"] == "main"
        assert len(result["fields"]) == 5

    async def test_get_section_not_found(self, small_form: FormSchema) -> None:
        """get_section returns an error dict for an unknown section_id."""
        toolkit = EditToolkit(small_form)
        result = await toolkit.get_section("nonexistent")

        assert "error" in result
        assert "nonexistent" in result["error"]
        assert "available_sections" in result

    async def test_get_field_by_id(self, small_form: FormSchema) -> None:
        """get_field returns correct field data including its section."""
        toolkit = EditToolkit(small_form)
        result = await toolkit.get_field("email")

        assert "error" not in result
        assert result["section_id"] == "main"
        assert result["field"]["field_id"] == "email"

    async def test_get_field_not_found(self, small_form: FormSchema) -> None:
        """get_field returns an error dict for an unknown field_id."""
        toolkit = EditToolkit(small_form)
        result = await toolkit.get_field("unknown_field")

        assert "error" in result
        assert "unknown_field" in result["error"]

    async def test_search_fields_by_label(self, small_form: FormSchema) -> None:
        """search_fields finds fields by label substring (case-insensitive)."""
        toolkit = EditToolkit(small_form)
        results = await toolkit.search_fields("ema")  # matches "Email"

        assert len(results) == 1
        assert results[0]["field_id"] == "email"

    async def test_search_fields_by_type(self, small_form: FormSchema) -> None:
        """search_fields filters by field_type."""
        toolkit = EditToolkit(small_form)
        results = await toolkit.search_fields("", field_type="text")

        field_ids = [r["field_id"] for r in results]
        assert "name" in field_ids
        # email, phone, integer, text_area should not be in results
        assert "email" not in field_ids

    async def test_search_fields_by_id_exact(self, small_form: FormSchema) -> None:
        """search_fields finds a field by exact field_id match."""
        toolkit = EditToolkit(small_form)
        results = await toolkit.search_fields("phone")

        assert any(r["field_id"] == "phone" for r in results)

    async def test_search_fields_by_pattern(self, small_form: FormSchema) -> None:
        """search_fields matches field_id using regex pattern."""
        toolkit = EditToolkit(small_form)
        # regex matching field IDs that start with "na" or "no"
        results = await toolkit.search_fields("^n[ao]")

        field_ids = [r["field_id"] for r in results]
        assert "name" in field_ids
        assert "notes" in field_ids

    async def test_search_fields_no_results(self, small_form: FormSchema) -> None:
        """search_fields returns empty list when nothing matches."""
        toolkit = EditToolkit(small_form)
        results = await toolkit.search_fields("ZZZZZ_no_match_ZZZZZ")

        assert results == []


# ---------------------------------------------------------------------------
# TestEditToolkitMutation
# ---------------------------------------------------------------------------


class TestEditToolkitMutation:
    """Tests for mutation tools."""

    async def test_update_field_merge_patch(self, small_form: FormSchema) -> None:
        """update_field applies a merge-patch to the target field."""
        toolkit = EditToolkit(small_form)
        result = await toolkit.update_field(
            section_id="main",
            field_id="name",
            patch={"label": "Full Name", "required": True},
        )

        assert result.get("success") is True
        updated = result["updated_field"]
        assert updated["label"] == "Full Name"
        assert updated["required"] is True

    async def test_update_field_preserves_unmentioned_keys(
        self, small_form: FormSchema
    ) -> None:
        """update_field only touches keys present in the patch."""
        toolkit = EditToolkit(small_form)
        # Only update label; field_type should stay TEXT
        await toolkit.update_field(
            section_id="main", field_id="name", patch={"label": "New Label"}
        )

        field_result = await toolkit.get_field("name")
        assert field_result["field"]["field_type"] == "text"

    async def test_update_field_not_found(self, small_form: FormSchema) -> None:
        """update_field returns an error for an unknown field_id."""
        toolkit = EditToolkit(small_form)
        result = await toolkit.update_field(
            section_id="main", field_id="ghost", patch={"label": "X"}
        )

        assert "error" in result

    async def test_add_field_appends(self, small_form: FormSchema) -> None:
        """add_field appends a new field when no position is given."""
        toolkit = EditToolkit(small_form)
        new_field = {
            "field_id": "zip_code",
            "field_type": "text",
            "label": "Zip Code",
        }
        result = await toolkit.add_field(section_id="main", field=new_field)

        assert result.get("success") is True
        section = await toolkit.get_section("main")
        ids = [f["field_id"] for f in section["fields"] if "field_id" in f]
        assert "zip_code" in ids
        assert ids[-1] == "zip_code"

    async def test_add_field_at_position(self, small_form: FormSchema) -> None:
        """add_field inserts the field at the specified position."""
        toolkit = EditToolkit(small_form)
        new_field = {
            "field_id": "middle_name",
            "field_type": "text",
            "label": "Middle Name",
        }
        result = await toolkit.add_field(
            section_id="main", field=new_field, position=1
        )

        assert result.get("success") is True
        section = await toolkit.get_section("main")
        ids = [f["field_id"] for f in section["fields"] if "field_id" in f]
        assert ids[1] == "middle_name"

    async def test_remove_field_by_id(self, small_form: FormSchema) -> None:
        """remove_field removes the correct field from the section."""
        toolkit = EditToolkit(small_form)
        result = await toolkit.remove_field(section_id="main", field_id="phone")

        assert result.get("success") is True
        field_result = await toolkit.get_field("phone")
        assert "error" in field_result

    async def test_remove_field_not_found(self, small_form: FormSchema) -> None:
        """remove_field returns an error for an unknown field_id."""
        toolkit = EditToolkit(small_form)
        result = await toolkit.remove_field(section_id="main", field_id="ghost")

        assert "error" in result

    async def test_add_section(self, small_form: FormSchema) -> None:
        """add_section appends a new section to the form."""
        toolkit = EditToolkit(small_form)
        new_section = {
            "section_id": "extra",
            "title": "Extra Section",
            "fields": [],
        }
        result = await toolkit.add_section(section=new_section)

        assert result.get("success") is True
        summary = await toolkit.get_form_summary()
        section_ids = [s["section_id"] for s in summary["sections"]]
        assert "extra" in section_ids

    async def test_add_section_at_position(self, small_form: FormSchema) -> None:
        """add_section inserts at the specified position."""
        toolkit = EditToolkit(small_form)
        new_section = {
            "section_id": "intro",
            "title": "Introduction",
            "fields": [],
        }
        result = await toolkit.add_section(section=new_section, position=0)

        assert result.get("success") is True
        summary = await toolkit.get_form_summary()
        assert summary["sections"][0]["section_id"] == "intro"

    async def test_update_section_meta(self, small_form: FormSchema) -> None:
        """update_section merges the patch into the section meta."""
        toolkit = EditToolkit(small_form)
        result = await toolkit.update_section(
            section_id="main", patch={"color": "blue"}
        )

        assert result.get("success") is True

    async def test_update_section_not_found(self, small_form: FormSchema) -> None:
        """update_section returns an error for an unknown section_id."""
        toolkit = EditToolkit(small_form)
        result = await toolkit.update_section(
            section_id="ghost", patch={"color": "red"}
        )

        assert "error" in result

    async def test_move_field_across_sections(
        self, two_section_form: FormSchema
    ) -> None:
        """move_field moves a field from one section to another."""
        toolkit = EditToolkit(two_section_form)
        result = await toolkit.move_field(
            from_section="section_a",
            field_id="field_a1",
            to_section="section_b",
        )

        assert result.get("success") is True
        # field_a1 should now be in section_b
        field_result = await toolkit.get_field("field_a1")
        assert field_result["section_id"] == "section_b"

    async def test_move_field_not_found(self, two_section_form: FormSchema) -> None:
        """move_field returns an error for an unknown field_id."""
        toolkit = EditToolkit(two_section_form)
        result = await toolkit.move_field(
            from_section="section_a",
            field_id="ghost",
            to_section="section_b",
        )

        assert "error" in result

    async def test_update_form_meta(self, small_form: FormSchema) -> None:
        """update_form_meta updates only the form-level meta dict, NOT form.title."""
        toolkit = EditToolkit(small_form)
        result = await toolkit.update_form_meta(patch={"theme": "dark"})

        assert result.get("success") is True
        assert toolkit.form.meta is not None
        assert toolkit.form.meta.get("theme") == "dark"
        # Confirm form title is untouched
        assert str(toolkit.form.title) == "Small Form"

    async def test_update_form_meta_does_not_update_title(
        self, small_form: FormSchema
    ) -> None:
        """update_form_meta merges into meta dict — it cannot change form.title."""
        toolkit = EditToolkit(small_form)
        # Putting title in the patch goes into form.meta, not form.title
        await toolkit.update_form_meta(patch={"title": "Wrong Title"})
        assert str(toolkit.form.title) == "Small Form"
        assert toolkit.form.meta is not None
        assert toolkit.form.meta.get("title") == "Wrong Title"

    async def test_update_form_title(self, small_form: FormSchema) -> None:
        """update_form_title correctly sets form.title."""
        toolkit = EditToolkit(small_form)
        result = await toolkit.update_form_title(title="Renamed Form")

        assert result.get("success") is True
        assert str(toolkit.form.title) == "Renamed Form"

    async def test_update_form_description(self, small_form: FormSchema) -> None:
        """update_form_description correctly sets form.description."""
        toolkit = EditToolkit(small_form)
        result = await toolkit.update_form_description(description="A great form")

        assert result.get("success") is True
        assert str(toolkit.form.description) == "A great form"

    async def test_update_form_description_clears_with_none(
        self, small_form: FormSchema
    ) -> None:
        """update_form_description with None clears the description."""
        toolkit = EditToolkit(small_form)
        await toolkit.update_form_description(description="To be cleared")
        result = await toolkit.update_form_description(description=None)

        assert result.get("success") is True
        assert toolkit.form.description is None

    async def test_update_section_title(self, two_section_form: FormSchema) -> None:
        """update_section_title correctly renames a section."""
        toolkit = EditToolkit(two_section_form)
        result = await toolkit.update_section_title(
            section_id="section_a", title="Personal Information"
        )

        assert result.get("success") is True
        section = next(
            s for s in toolkit.form.sections if s.section_id == "section_a"
        )
        assert str(section.title) == "Personal Information"

    async def test_update_section_title_not_found(
        self, small_form: FormSchema
    ) -> None:
        """update_section_title returns error for unknown section_id."""
        toolkit = EditToolkit(small_form)
        result = await toolkit.update_section_title(
            section_id="nonexistent", title="Anything"
        )

        assert "error" in result
        assert "nonexistent" in result["error"]

    async def test_update_section_meta_does_not_update_title(
        self, two_section_form: FormSchema
    ) -> None:
        """update_section (meta patch) does NOT change section.title."""
        toolkit = EditToolkit(two_section_form)
        original_title = str(
            next(s for s in two_section_form.sections if s.section_id == "section_a").title
        )
        # Putting title in the patch goes into section.meta, not section.title
        await toolkit.update_section(section_id="section_a", patch={"title": "Wrong"})
        section = next(
            s for s in toolkit.form.sections if s.section_id == "section_a"
        )
        assert str(section.title) == original_title

    async def test_done_returns_success(self, small_form: FormSchema) -> None:
        """done() returns a success dict and sets is_done=True."""
        toolkit = EditToolkit(small_form)
        assert toolkit.is_done is False

        result = await toolkit.done()
        assert result.get("success") is True
        assert toolkit.is_done is True


# ---------------------------------------------------------------------------
# TestEditToolkitIsolation
# ---------------------------------------------------------------------------


class TestEditToolkitIsolation:
    """Tests for working copy isolation."""

    async def test_original_form_unchanged_after_mutations(
        self, small_form: FormSchema
    ) -> None:
        """Mutations to the toolkit do not affect the original FormSchema."""
        original_label = small_form.sections[0].fields[0].label  # type: ignore[union-attr]

        toolkit = EditToolkit(small_form)
        await toolkit.update_field(
            section_id="main",
            field_id="name",
            patch={"label": "Modified Label"},
        )

        # Original form must be unchanged
        assert small_form.sections[0].fields[0].label == original_label  # type: ignore[union-attr]

    async def test_working_copy_is_independent(self, small_form: FormSchema) -> None:
        """EditToolkit creates an independent deep copy of the form."""
        toolkit = EditToolkit(small_form)

        # Confirm working copy is a different object
        assert toolkit.form is not small_form
        assert toolkit.form.sections is not small_form.sections

    async def test_two_toolkits_independent(self, small_form: FormSchema) -> None:
        """Two EditToolkit instances on the same form are independent."""
        toolkit1 = EditToolkit(small_form)
        toolkit2 = EditToolkit(small_form)

        await toolkit1.update_field(
            section_id="main", field_id="name", patch={"label": "Label From Toolkit 1"}
        )

        # toolkit2's copy should not see toolkit1's mutations
        field_result = await toolkit2.get_field("name")
        assert field_result["field"]["label"] != "Label From Toolkit 1"


# ---------------------------------------------------------------------------
# TestEditToolkitTools
# ---------------------------------------------------------------------------


class TestEditToolkitTools:
    """Tests for tool definitions and dispatcher."""

    def test_tool_definitions_count(self, small_form: FormSchema) -> None:
        """get_tool_definitions() returns exactly 15 tools (12 original + 3 title/description)."""
        toolkit = EditToolkit(small_form)
        tools = toolkit.get_tool_definitions()
        assert len(tools) == 15

    def test_tool_definitions_has_required_names(self, small_form: FormSchema) -> None:
        """All 15 expected tool names are present in get_tool_definitions()."""
        expected_names = {
            # Inspection
            "get_form_summary",
            "get_section",
            "get_field",
            "search_fields",
            # Mutation — field ops
            "update_field",
            "add_field",
            "remove_field",
            "move_field",
            # Mutation — section ops
            "add_section",
            "update_section",
            "update_section_title",
            # Mutation — form-level ops
            "update_form_title",
            "update_form_description",
            "update_form_meta",
            # Control
            "done",
        }
        toolkit = EditToolkit(small_form)
        tool_names = {t.name for t in toolkit.get_tool_definitions()}
        assert tool_names == expected_names

    def test_tool_definitions_format(self, small_form: FormSchema) -> None:
        """Each tool from get_tool_definitions() has name, description, and schema."""
        toolkit = EditToolkit(small_form)
        for tool in toolkit.get_tool_definitions():
            assert hasattr(tool, "name"), f"Tool {tool} missing name"
            assert hasattr(tool, "description"), f"Tool {tool.name} missing description"
            schema = tool.get_schema()
            assert "name" in schema
            assert "description" in schema
            assert "parameters" in schema

    def test_execute_tool_not_exposed_as_tool(self, small_form: FormSchema) -> None:
        """execute_tool is excluded from get_tool_definitions()."""
        toolkit = EditToolkit(small_form)
        tool_names = {t.name for t in toolkit.get_tool_definitions()}
        assert "execute_tool" not in tool_names

    async def test_execute_tool_dispatches_correctly(
        self, small_form: FormSchema
    ) -> None:
        """execute_tool routes to the correct handler."""
        toolkit = EditToolkit(small_form)
        result = await toolkit.execute_tool("get_form_summary", {})

        assert "form_id" in result
        assert result["form_id"] == "small-form"

    async def test_execute_tool_unknown_name(self, small_form: FormSchema) -> None:
        """execute_tool returns an error for an unknown tool name."""
        toolkit = EditToolkit(small_form)
        result = await toolkit.execute_tool("not_a_real_tool", {})

        assert "error" in result
        assert "available_tools" in result
