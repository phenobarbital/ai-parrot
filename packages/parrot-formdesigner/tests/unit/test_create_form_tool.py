"""Unit tests for CreateFormTool."""

import json
import pytest
from unittest.mock import AsyncMock
from parrot_formdesigner.core.schema import FormSchema, FormField, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.tools.create_form import CreateFormTool


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

VALID_FORM_JSON = json.dumps({
    "form_id": "feedback",
    "title": "Customer Feedback",
    "sections": [
        {
            "section_id": "main",
            "fields": [
                {
                    "field_id": "name",
                    "field_type": "text",
                    "label": "Name",
                    "required": True,
                },
                {
                    "field_id": "rating",
                    "field_type": "integer",
                    "label": "Rating",
                    "constraints": {"min_value": 1, "max_value": 5},
                },
            ],
        }
    ],
})

INVALID_JSON = '{"invalid": "not a form schema"}'

# JSON that Pydantic will reject (missing required sections)
MISSING_SECTIONS_JSON = '{"form_id": "x", "title": "X"}'


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_client():
    """Mock LLM client returning valid form JSON."""
    client = AsyncMock()
    client.completion = AsyncMock(return_value=VALID_FORM_JSON)
    return client


@pytest.fixture
def tool(mock_client):
    """CreateFormTool with mocked client (no registry)."""
    return CreateFormTool(client=mock_client)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCreateFormToolBasic:
    """Tests for basic form creation."""

    async def test_basic_creation_success(self, tool):
        """execute() returns success with form in metadata."""
        result = await tool.execute(prompt="Create a customer feedback form")
        assert result.success is True
        assert "form" in result.metadata
        assert result.metadata["form"]["form_id"] == "feedback"

    async def test_result_is_dict(self, tool):
        """Form in metadata is a dict (not a FormSchema object)."""
        result = await tool.execute(prompt="Create a form")
        form = result.metadata["form"]
        assert isinstance(form, dict)

    async def test_custom_form_id(self, tool):
        """form_id parameter overrides the generated ID."""
        result = await tool.execute(
            prompt="Create a form", form_id="my-custom-form"
        )
        assert result.metadata["form"]["form_id"] == "my-custom-form"

    async def test_client_completion_called(self, tool, mock_client):
        """LLM client.completion is called at least once."""
        await tool.execute(prompt="Create a form")
        mock_client.completion.assert_called()


class TestCreateFormToolRetry:
    """Tests for retry-on-validation-failure behavior."""

    async def test_retry_on_invalid_json(self, mock_client):
        """Invalid JSON on first call retries with valid on second."""
        mock_client.completion.side_effect = [
            INVALID_JSON,  # missing required fields → Pydantic error
            VALID_FORM_JSON,
        ]
        tool = CreateFormTool(client=mock_client)
        result = await tool.execute(prompt="Create a form")
        assert result.success is True
        assert mock_client.completion.call_count == 2

    async def test_all_retries_exhausted(self, mock_client):
        """Returns error after all retries are exhausted."""
        mock_client.completion.return_value = INVALID_JSON
        tool = CreateFormTool(client=mock_client)
        result = await tool.execute(prompt="Create a form")
        assert result.success is False
        assert result.status == "error"
        # Should have tried MAX_RETRIES + 1 times
        assert mock_client.completion.call_count == CreateFormTool.MAX_RETRIES + 1

    async def test_markdown_json_extracted(self, mock_client):
        """JSON wrapped in markdown code blocks is extracted correctly."""
        markdown_response = f"```json\n{VALID_FORM_JSON}\n```"
        mock_client.completion.return_value = markdown_response
        tool = CreateFormTool(client=mock_client)
        result = await tool.execute(prompt="Create a form")
        assert result.success is True


class TestCreateFormToolRefinement:
    """Tests for iterative form refinement."""

    async def test_refinement_with_existing_form(self, mock_client):
        """refine_form_uid loads existing form and includes it in prompt."""
        existing = FormSchema(
            form_id="existing",
            title="Existing Form",
            sections=[
                FormSection(
                    section_id="s",
                    fields=[
                        FormField(
                            field_id="f",
                            field_type=FieldType.TEXT,
                            label="F",
                        )
                    ],
                )
            ],
        )
        registry = AsyncMock()
        registry.get = AsyncMock(return_value=existing)
        registry.register = AsyncMock()

        tool = CreateFormTool(client=mock_client, registry=registry)
        result = await tool.execute(
            prompt="Add a phone field",
            refine_form_uid="existing",
        )
        assert result.success is True
        # Verify the prompt to the LLM included the existing form
        call_args = mock_client.completion.call_args
        messages_str = str(call_args)
        # The existing form JSON (or its title) should be in the messages
        assert "Existing Form" in messages_str or "existing" in messages_str.lower()

    async def test_refinement_nonexistent_form(self, mock_client):
        """refine_form_uid pointing to nonexistent form returns error."""
        registry = AsyncMock()
        registry.get = AsyncMock(return_value=None)

        tool = CreateFormTool(client=mock_client, registry=registry)
        result = await tool.execute(
            prompt="Add a field",
            refine_form_uid="nonexistent",
        )
        assert result.success is False
        assert result.status == "error"


class TestCreateFormToolPersist:
    """Tests for persistence via registry."""

    async def test_persist_registers_form(self, mock_client):
        """persist=True calls registry.register()."""
        registry = AsyncMock()
        registry.register = AsyncMock()

        tool = CreateFormTool(client=mock_client, registry=registry)
        await tool.execute(prompt="Create a form", persist=True)
        registry.register.assert_called_once()

    async def test_no_persist_skips_register(self, mock_client):
        """persist=False (default) does not call registry.register()."""
        registry = AsyncMock()
        registry.register = AsyncMock()

        tool = CreateFormTool(client=mock_client, registry=registry)
        await tool.execute(prompt="Create a form")
        registry.register.assert_not_called()

    async def test_persist_without_registry(self, mock_client):
        """persist=True without registry still returns success."""
        tool = CreateFormTool(client=mock_client, registry=None)
        result = await tool.execute(prompt="Create a form", persist=True)
        assert result.success is True


class TestCreateFormToolFormUid:
    """Tests for form_uid generation and propagation (FEAT-389, TASK-1978)."""

    async def test_create_form_auto_generates_uid(self, tool):
        """CreateFormTool generates form_uid when not provided."""
        import uuid as _uuid

        result = await tool.execute(prompt="Create a contact form")
        assert result.success is True
        assert "form_uid" in result.metadata
        assert result.metadata["form_uid"] == result.metadata["form"]["form_uid"]
        _uuid.UUID(result.metadata["form_uid"])  # valid UUID — does not raise

    async def test_create_form_with_explicit_uid(self, tool):
        """CreateFormTool uses the provided form_uid instead of generating one."""
        uid = "550e8400-e29b-41d4-a716-446655440000"
        result = await tool.execute(prompt="Create a form", form_uid=uid)
        assert result.metadata["form_uid"] == uid
        assert result.metadata["form"]["form_uid"] == uid

    async def test_two_forms_get_different_uids(self, mock_client):
        """Two separately-created forms get distinct auto-generated form_uids."""
        tool = CreateFormTool(client=mock_client)
        r1 = await tool.execute(prompt="Create form A")
        r2 = await tool.execute(prompt="Create form B")
        assert r1.metadata["form_uid"] != r2.metadata["form_uid"]

    async def test_refine_form_uid_preserves_identity(self, mock_client):
        """Refining an existing form preserves its form_uid unchanged."""
        existing = FormSchema(
            form_uid="fixed-existing-uid",
            form_id="existing",
            title="Existing Form",
            sections=[
                FormSection(
                    section_id="s",
                    fields=[
                        FormField(field_id="f", field_type=FieldType.TEXT, label="F"),
                    ],
                )
            ],
        )
        registry = AsyncMock()
        registry.get = AsyncMock(return_value=existing)
        registry.register = AsyncMock()

        tool = CreateFormTool(client=mock_client, registry=registry)
        result = await tool.execute(
            prompt="Add a phone field",
            refine_form_uid="fixed-existing-uid",
        )

        assert result.success is True
        assert result.metadata["form_uid"] == "fixed-existing-uid"
        assert result.metadata["form"]["form_uid"] == "fixed-existing-uid"
        # form_id (slug) is preserved too, since no explicit form_id= override.
        assert result.metadata["form"]["form_id"] == "existing"

    def test_create_form_input_has_form_uid_field(self):
        """CreateFormInput schema includes form_uid and refine_form_uid."""
        from parrot_formdesigner.tools.create_form import CreateFormInput

        fields = CreateFormInput.model_fields
        assert "form_uid" in fields
        assert "refine_form_uid" in fields
        assert "refine_form_id" not in fields  # renamed away
