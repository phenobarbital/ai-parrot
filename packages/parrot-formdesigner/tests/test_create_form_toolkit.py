"""Integration and routing tests for CreateFormTool toolkit path (FEAT-169).

Tests cover:
- _should_use_toolkit() always returning True (per spec Q3)
- _execute_toolkit_edit() producing the correct updated FormSchema
- Fallback to full-form path when toolkit fails (exhausted iterations / exception)
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.tools.create_form import CreateFormTool


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def small_form() -> FormSchema:
    """5-field form (below original spec threshold for reference)."""
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
    """100-field form across 10 sections."""
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
def mock_client():
    """Mock LLM client with an async ask() method."""
    client = MagicMock()
    client.ask = AsyncMock(return_value=MagicMock(to_text="{}"))
    return client


@pytest.fixture
def create_form_tool(mock_client) -> CreateFormTool:
    """CreateFormTool instance with mock client (no registry)."""
    return CreateFormTool(client=mock_client)


# ---------------------------------------------------------------------------
# TestToolkitRouting
# ---------------------------------------------------------------------------


class TestToolkitRouting:
    """Tests for _should_use_toolkit() routing decision."""

    def test_should_use_toolkit_always_true_for_small_form(
        self, create_form_tool: CreateFormTool, small_form: FormSchema
    ) -> None:
        """_should_use_toolkit returns True even for small forms (per spec Q3)."""
        assert create_form_tool._should_use_toolkit(small_form) is True

    def test_should_use_toolkit_always_true_for_large_form(
        self, create_form_tool: CreateFormTool, large_form: FormSchema
    ) -> None:
        """_should_use_toolkit returns True for large forms."""
        assert create_form_tool._should_use_toolkit(large_form) is True

    def test_should_use_toolkit_true_for_single_field_form(
        self, create_form_tool: CreateFormTool
    ) -> None:
        """_should_use_toolkit returns True for a single-field form."""
        tiny_form = FormSchema(
            form_id="tiny",
            title="Tiny Form",
            sections=[
                FormSection(
                    section_id="s",
                    title="S",
                    fields=[
                        FormField(
                            field_id="x",
                            field_type=FieldType.TEXT,
                            label="X",
                        )
                    ],
                )
            ],
        )
        assert create_form_tool._should_use_toolkit(tiny_form) is True


# ---------------------------------------------------------------------------
# TestToolkitIntegration
# ---------------------------------------------------------------------------


class TestToolkitIntegration:
    """Integration tests for _execute_toolkit_edit()."""

    async def test_toolkit_edit_returns_form_when_done_called(
        self, create_form_tool: CreateFormTool, small_form: FormSchema
    ) -> None:
        """_execute_toolkit_edit returns FormSchema when LLM calls done()."""
        # Simulate the LLM client calling the done tool via the toolkit.
        # We patch EditToolkit to set _done=True and return the form directly.

        async def fake_ask(prompt, **kwargs):
            # Retrieve the toolkit reference via the tools argument
            tools = kwargs.get("tools", [])
            # Find the 'done' tool and call it
            for tool in tools:
                if tool.name == "done":
                    await tool.execute()
                    break
            return MagicMock(to_text="OK")

        create_form_tool._client.ask = fake_ask

        result = await create_form_tool._execute_toolkit_edit(small_form, "Change name label")

        assert result is not None
        assert isinstance(result, FormSchema)
        assert result.form_id == small_form.form_id

    async def test_toolkit_edit_returns_none_when_done_not_called(
        self, create_form_tool: CreateFormTool, small_form: FormSchema
    ) -> None:
        """_execute_toolkit_edit returns None when LLM exhausts iterations without done()."""
        # Simulate LLM that never calls done
        create_form_tool._client.ask = AsyncMock(return_value=MagicMock(to_text="OK"))

        result = await create_form_tool._execute_toolkit_edit(small_form, "Update form")

        assert result is None

    async def test_toolkit_edit_raises_on_client_error(
        self, create_form_tool: CreateFormTool, small_form: FormSchema
    ) -> None:
        """_execute_toolkit_edit raises when the LLM client raises an unhandled error."""
        create_form_tool._client.ask = AsyncMock(side_effect=RuntimeError("LLM failure"))

        with pytest.raises(RuntimeError, match="LLM failure"):
            await create_form_tool._execute_toolkit_edit(small_form, "Update form")

    async def test_toolkit_edit_applies_mutation(
        self, create_form_tool: CreateFormTool, small_form: FormSchema
    ) -> None:
        """_execute_toolkit_edit applies mutations made by the LLM before done()."""

        async def fake_ask_with_mutation(prompt, **kwargs):
            tools = kwargs.get("tools", [])
            tool_map = {t.name: t for t in tools}
            # Simulate LLM calling update_field then done
            update_tool = tool_map.get("update_field")
            done_tool = tool_map.get("done")
            if update_tool:
                await update_tool.execute(
                    section_id="main",
                    field_id="name",
                    patch={"label": "Full Name"},
                )
            if done_tool:
                await done_tool.execute()
            return MagicMock(to_text="OK")

        create_form_tool._client.ask = fake_ask_with_mutation

        result = await create_form_tool._execute_toolkit_edit(small_form, "Rename name field")

        assert result is not None
        # Find the name field in the result
        for section in result.sections:
            for field in section.fields:
                if isinstance(field, FormField) and field.field_id == "name":
                    assert field.label == "Full Name", f"Expected 'Full Name', got {field.label}"

    async def test_fallback_on_toolkit_failure(
        self, small_form: FormSchema
    ) -> None:
        """_execute() falls back to full-form path when toolkit raises an exception."""
        # Build a mock registry that returns our small_form
        mock_registry = MagicMock()
        mock_registry.get = AsyncMock(return_value=small_form)
        mock_registry.register = AsyncMock()

        # Full-form JSON for the fallback path
        full_form_json = small_form.model_dump_json()

        async def ask_side_effect(prompt, **kwargs):
            if kwargs.get("use_tools"):
                raise RuntimeError("Toolkit LLM failure")
            # Fallback path — return a valid completion-style response
            return MagicMock(to_text=full_form_json)

        mock_client = MagicMock()
        mock_client.ask = ask_side_effect
        # Ensure client does NOT have a completion attribute so code routes to ask()
        del mock_client.completion

        tool = CreateFormTool(client=mock_client, registry=mock_registry)
        result = await tool._execute(
            prompt="Change something",
            refine_form_id="small-form",
            persist=False,
        )

        # The fallback full-form path should return success
        assert result.success is True

    async def test_toolkit_system_prompt_is_set(
        self, create_form_tool: CreateFormTool, small_form: FormSchema
    ) -> None:
        """_execute_toolkit_edit calls ask() with _TOOLKIT_SYSTEM_PROMPT."""
        from parrot_formdesigner.tools.create_form import _TOOLKIT_SYSTEM_PROMPT

        captured_kwargs: dict = {}

        async def capture_ask(prompt, **kwargs):
            captured_kwargs.update(kwargs)
            # Simulate done being called via toolkit
            for tool in kwargs.get("tools", []):
                if tool.name == "done":
                    await tool.execute()
                    break
            return MagicMock(to_text="OK")

        create_form_tool._client.ask = capture_ask

        await create_form_tool._execute_toolkit_edit(small_form, "Update form")

        assert captured_kwargs.get("system_prompt") == _TOOLKIT_SYSTEM_PROMPT
        assert captured_kwargs.get("use_tools") is True
        assert captured_kwargs.get("stateless") is True

    async def test_toolkit_model_passed_when_set(
        self, small_form: FormSchema
    ) -> None:
        """_execute_toolkit_edit passes model= to ask() when _model is set."""
        captured_kwargs: dict = {}

        async def capture_ask(prompt, **kwargs):
            captured_kwargs.update(kwargs)
            for tool in kwargs.get("tools", []):
                if tool.name == "done":
                    await tool.execute()
                    break
            return MagicMock(to_text="OK")

        mock_client = MagicMock()
        mock_client.ask = capture_ask
        tool = CreateFormTool(client=mock_client, model="gemini-2.5-flash")

        await tool._execute_toolkit_edit(small_form, "Update form")

        assert captured_kwargs.get("model") == "gemini-2.5-flash"
