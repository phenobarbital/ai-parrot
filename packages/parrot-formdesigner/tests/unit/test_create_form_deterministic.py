"""Unit tests for CreateFormTool's deterministic input paths (FEAT-388, TASK-1969)."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from parrot_formdesigner.tools.create_form import CreateFormTool


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.completion = AsyncMock()
    return client


@pytest.fixture
def tool(mock_client):
    return CreateFormTool(client=mock_client)


class TestDeterministicInput:
    @pytest.mark.asyncio
    async def test_schema_input_no_llm(self, tool, mock_client):
        result = await tool.execute(
            schema={
                "form_id": "test",
                "title": "Test",
                "sections": [{"section_id": "s1", "fields": [
                    {"field_id": "name", "field_type": "text", "label": "Name"},
                ]}],
            },
        )
        assert result.success is True
        assert result.metadata["form"]["form_id"] == "test"
        mock_client.completion.assert_not_called()

    @pytest.mark.asyncio
    async def test_schema_input_resolves_depends_on_to_field_uid(self, tool, mock_client):
        """FEAT-393 code review regression: the deterministic schema= path
        must resolve authored field_id rule references to field_uid,
        same as the LLM path — previously only the LLM-generation path
        called resolve_rule_references()."""
        result = await tool.execute(
            schema={
                "form_id": "test-rules",
                "title": "Test",
                "sections": [{"section_id": "s1", "fields": [
                    {"field_id": "country", "field_type": "text", "label": "Country"},
                    {
                        "field_id": "state",
                        "field_type": "text",
                        "label": "State",
                        "depends_on": {
                            "conditions": [
                                {"field_id": "country", "operator": "eq", "value": "US"}
                            ]
                        },
                    },
                ]}],
            },
        )
        assert result.success is True
        fields = result.metadata["form"]["sections"][0]["fields"]
        country_uid = next(f["field_uid"] for f in fields if f["field_id"] == "country")
        state = next(f for f in fields if f["field_id"] == "state")
        assert state["depends_on"]["conditions"][0]["field_uid"] == country_uid

    @pytest.mark.asyncio
    async def test_sections_input(self, tool, mock_client):
        result = await tool.execute(
            sections=[{"title": "Info", "fields": [
                {"label": "Name", "field_type": "text"},
            ]}],
            form_id="test-sections",
        )
        assert result.success is True
        mock_client.completion.assert_not_called()

    @pytest.mark.asyncio
    async def test_fields_input(self, tool, mock_client):
        result = await tool.execute(
            fields=[
                {"label": "Name", "field_type": "text", "required": True},
                {"label": "Age", "field_type": "integer"},
            ],
            form_id="test-fields",
        )
        assert result.success is True
        assert len(result.metadata["form"]["sections"]) == 1
        mock_client.completion.assert_not_called()

    @pytest.mark.asyncio
    async def test_prompt_unchanged_uses_llm_path(self, tool, mock_client):
        mock_client.completion.return_value = (
            '{"form_id": "p", "title": "Prompted", "sections": []}'
        )
        result = await tool.execute(prompt="Make a form")
        assert result.success is True
        mock_client.completion.assert_called_once()

    @pytest.mark.asyncio
    async def test_prompt_and_schema_error(self, tool):
        result = await tool.execute(
            prompt="Make a form",
            schema={"form_id": "x", "title": "X", "sections": []},
        )
        assert result.success is False
        assert "not both" in result.metadata["error"]

    @pytest.mark.asyncio
    async def test_neither_prompt_nor_schema_error(self, tool):
        result = await tool.execute()
        assert result.success is False
        assert "required" in result.metadata["error"].lower()

    @pytest.mark.asyncio
    async def test_invalid_schema_fails_fast(self, tool):
        result = await tool.execute(schema={"invalid": "data"})
        assert result.success is False

    @pytest.mark.asyncio
    async def test_persist_with_schema(self, tool):
        mock_registry = AsyncMock()
        tool._registry = mock_registry
        await tool.execute(
            schema={
                "form_id": "persist-test",
                "title": "Persist",
                "sections": [{"section_id": "s", "fields": [
                    {"field_id": "x", "field_type": "text", "label": "X"},
                ]}],
            },
            persist=True,
        )
        mock_registry.register.assert_called_once()
