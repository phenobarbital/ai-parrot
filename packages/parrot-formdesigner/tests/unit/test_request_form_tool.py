"""Unit tests for RequestFormTool."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import BaseModel, Field
from parrot.formdesigner.core.schema import FormSchema, FormField, FormSection
from parrot.formdesigner.core.types import FieldType
from parrot.formdesigner.tools.request_form import RequestFormTool


# ---------------------------------------------------------------------------
# Mock target tool
# ---------------------------------------------------------------------------

class MockSchema(BaseModel):
    """Minimal args_schema for the mock target tool."""

    query: str = Field(..., description="Search query")
    limit: int = Field(default=10, description="Max results")


class MockTargetTool:
    """Duck-typed tool with name, description, args_schema."""

    name = "search"
    description = "Search documentation"
    args_schema = MockSchema


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_target_tool():
    return MockTargetTool()


@pytest.fixture
def tool_manager(mock_target_tool):
    mgr = MagicMock()
    mgr.get_tool = MagicMock(return_value=mock_target_tool)
    mgr.list_tools = MagicMock(return_value=["search"])
    return mgr


@pytest.fixture
def sample_form():
    """FormSchema as returned by ToolExtractor.extract()."""
    return FormSchema(
        form_id="search_form",
        title="Search",
        sections=[
            FormSection(
                section_id="s",
                fields=[
                    FormField(field_id="query", field_type=FieldType.TEXT, label="Query", required=True),
                    FormField(field_id="limit", field_type=FieldType.INTEGER, label="Limit"),
                ],
            )
        ],
    )


@pytest.fixture
def request_form_tool(tool_manager, sample_form):
    """RequestFormTool with mocked ToolExtractor."""
    mock_extractor = MagicMock()
    mock_extractor.extract = MagicMock(return_value=sample_form)
    tool = RequestFormTool(tool_manager=tool_manager, tool_extractor=mock_extractor)
    return tool, mock_extractor


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRequestFormToolSuccess:
    """Tests for successful form generation."""

    async def test_generates_form(self, request_form_tool):
        """execute() returns status=form_requested with form in metadata."""
        tool, _ = request_form_tool
        result = await tool.execute(target_tool="search")
        assert result.status == "form_requested"
        assert result.success is True
        assert "form" in result.metadata

    async def test_form_is_dict(self, request_form_tool):
        """Form in metadata is a dict (model_dump)."""
        tool, _ = request_form_tool
        result = await tool.execute(target_tool="search")
        form = result.metadata["form"]
        assert isinstance(form, dict)
        assert form["form_id"] == "search_form"

    async def test_target_tool_in_metadata(self, request_form_tool):
        """target_tool appears in result metadata."""
        tool, _ = request_form_tool
        result = await tool.execute(target_tool="search")
        assert result.metadata["target_tool"] == "search"

    async def test_known_values_excluded(self, tool_manager):
        """Fields in known_values are passed to extractor for exclusion."""
        # Build form without "query" (as if extractor filtered it)
        form_without_query = FormSchema(
            form_id="search_form",
            title="Search",
            sections=[FormSection(
                section_id="s",
                fields=[FormField(field_id="limit", field_type=FieldType.INTEGER, label="Limit")]
            )],
        )
        mock_extractor = MagicMock()
        mock_extractor.extract = MagicMock(return_value=form_without_query)
        tool = RequestFormTool(tool_manager=tool_manager, tool_extractor=mock_extractor)

        result = await tool.execute(target_tool="search", known_values={"query": "test"})
        assert result.status == "form_requested"
        # Extractor was called with known_values
        call_kwargs = mock_extractor.extract.call_args
        assert call_kwargs.kwargs.get("known_values") == {"query": "test"}

    async def test_custom_title(self, request_form_tool):
        """form_title overrides the form title in the result."""
        tool, _ = request_form_tool
        result = await tool.execute(target_tool="search", form_title="My Custom Form")
        form = result.metadata["form"]
        assert form["title"] == "My Custom Form"

    async def test_fields_to_collect(self, tool_manager, sample_form):
        """fields_to_collect is used to compute exclude_fields."""
        mock_extractor = MagicMock()
        mock_extractor.extract = MagicMock(return_value=sample_form)
        tool = RequestFormTool(tool_manager=tool_manager, tool_extractor=mock_extractor)

        result = await tool.execute(target_tool="search", fields_to_collect=["query"])
        assert result.status == "form_requested"
        # Extractor was called — exclude_fields should contain "limit" (not in fields_to_collect)
        call_kwargs = mock_extractor.extract.call_args
        exclude = call_kwargs.kwargs.get("exclude_fields") or set()
        # "limit" should be in the exclude set since it's not in fields_to_collect
        assert "limit" in exclude

    async def test_context_message_in_metadata(self, request_form_tool):
        """context_message appears in result metadata."""
        tool, _ = request_form_tool
        result = await tool.execute(
            target_tool="search",
            context_message="Please provide search parameters.",
        )
        assert result.metadata["context_message"] == "Please provide search parameters."


class TestRequestFormToolErrors:
    """Tests for error handling."""

    async def test_invalid_tool_returns_error(self, tool_manager, sample_form):
        """get_tool returning None produces error result."""
        tool_manager.get_tool.return_value = None
        mock_extractor = MagicMock()
        tool = RequestFormTool(tool_manager=tool_manager, tool_extractor=mock_extractor)
        result = await tool.execute(target_tool="nonexistent")
        assert result.success is False
        assert result.status == "error"
        assert "nonexistent" in str(result.metadata.get("error", ""))

    async def test_tool_without_args_schema(self, tool_manager):
        """Tool with no args_schema produces error result."""

        class NoSchemaTool:
            name = "no_schema"
            description = "No schema"
            args_schema = None

        tool_manager.get_tool.return_value = NoSchemaTool()
        mock_extractor = MagicMock()
        tool = RequestFormTool(tool_manager=tool_manager, tool_extractor=mock_extractor)
        result = await tool.execute(target_tool="no_schema")
        assert result.success is False
        assert result.status == "error"

    async def test_extractor_exception_returns_error(self, tool_manager):
        """Exception in ToolExtractor.extract produces error result."""
        mock_extractor = MagicMock()
        mock_extractor.extract = MagicMock(side_effect=RuntimeError("boom"))
        tool = RequestFormTool(tool_manager=tool_manager, tool_extractor=mock_extractor)
        result = await tool.execute(target_tool="search")
        assert result.success is False
        assert result.status == "error"
        assert "boom" in str(result.metadata.get("error", ""))
