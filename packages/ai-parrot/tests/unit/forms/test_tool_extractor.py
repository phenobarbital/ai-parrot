"""Unit tests for ToolExtractor."""

import pytest
from pydantic import BaseModel, Field

from parrot.forms import FieldType
from parrot.forms.extractors.tool import ToolExtractor


class MockArgsSchema(BaseModel):
    """Mock tool args schema with two fields."""

    query: str = Field(..., description="Search query")
    limit: int = Field(default=10, description="Max results")


class MockArgsSchemaWithContext(BaseModel):
    """Mock args schema with context fields."""

    query: str = Field(..., description="Search query")
    user_id: str = Field(default="", description="User context")

    _context_fields = frozenset({"user_id"})


class MockTool:
    """Mock tool with args_schema."""

    name = "search_tool"
    description = "Search for documents"
    args_schema = MockArgsSchema


class MockToolWithContext:
    """Mock tool with context fields in schema."""

    name = "context_tool"
    description = "Tool with context"
    args_schema = MockArgsSchemaWithContext


class MockToolNoSchema:
    """Mock tool without args_schema."""

    name = "no_schema"
    description = "No schema"
    args_schema = None


@pytest.fixture
def extractor():
    """ToolExtractor instance."""
    return ToolExtractor()


class TestToolExtractor:
    """Tests for ToolExtractor."""

    def test_basic_extraction(self, extractor):
        """Tool with args_schema produces FormSchema."""
        schema = extractor.extract(MockTool())
        assert schema.form_id == "search_tool_form"
        assert len(schema.sections[0].fields) == 2

    def test_form_id_format(self, extractor):
        """Form ID is '{tool.name}_form'."""
        schema = extractor.extract(MockTool())
        assert schema.form_id == "search_tool_form"

    def test_tool_description_in_schema(self, extractor):
        """Tool description is used as form description."""
        schema = extractor.extract(MockTool())
        assert schema.description == "Search for documents"

    def test_title_from_tool_name(self, extractor):
        """Form title derives from tool name."""
        schema = extractor.extract(MockTool())
        assert "Search" in schema.title
        assert "Tool" in schema.title

    def test_known_values_excluded(self, extractor):
        """known_values fields are excluded from the form."""
        schema = extractor.extract(MockTool(), known_values={"query": "test"})
        field_ids = [f.field_id for f in schema.sections[0].fields]
        assert "query" not in field_ids
        assert "limit" in field_ids

    def test_context_fields_excluded(self, extractor):
        """Fields listed in _context_fields are auto-excluded."""
        schema = extractor.extract(MockToolWithContext())
        field_ids = [f.field_id for f in schema.sections[0].fields]
        assert "user_id" not in field_ids
        assert "query" in field_ids

    def test_no_schema_raises(self, extractor):
        """Tool without args_schema raises ValueError."""
        with pytest.raises(ValueError, match="args_schema"):
            extractor.extract(MockToolNoSchema())

    def test_exclude_fields_parameter(self, extractor):
        """exclude_fields parameter removes specified fields."""
        schema = extractor.extract(MockTool(), exclude_fields={"limit"})
        field_ids = [f.field_id for f in schema.sections[0].fields]
        assert "limit" not in field_ids
        assert "query" in field_ids

    def test_field_types_correct(self, extractor):
        """Field types are correctly mapped from args_schema."""
        schema = extractor.extract(MockTool())
        fields_by_id = {f.field_id: f for f in schema.sections[0].fields}
        assert fields_by_id["query"].field_type == FieldType.TEXT
        assert fields_by_id["limit"].field_type == FieldType.INTEGER

    def test_custom_pydantic_extractor(self):
        """ToolExtractor accepts a custom PydanticExtractor instance."""
        from parrot.forms.extractors.pydantic import PydanticExtractor

        custom = PydanticExtractor()
        extractor = ToolExtractor(pydantic_extractor=custom)
        schema = extractor.extract(MockTool())
        assert schema.form_id == "search_tool_form"

    def test_section_id_is_parameters(self, extractor):
        """The generated section ID is 'parameters'."""
        schema = extractor.extract(MockTool())
        assert schema.sections[0].section_id == "parameters"
