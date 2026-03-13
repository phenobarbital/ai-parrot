"""Tests for PandasAgent prompt migration to composable layers.

Since PandasAgent has heavy dependencies (pandas, redis, aiohttp, etc.),
we test via AST inspection + PromptBuilder unit tests.
"""
import ast
import pytest
from pathlib import Path
from parrot.bots.prompts.builder import PromptBuilder
from parrot.bots.prompts.layers import LayerPriority, RenderPhase
from parrot.bots.prompts.domain_layers import DATAFRAME_CONTEXT_LAYER, STRICT_GROUNDING_LAYER


DATA_PY_SOURCE = Path(__file__).resolve().parents[3] / "parrot" / "bots" / "data.py"


class TestPandasAgentHasPromptBuilder:

    def test_source_has_prompt_builder_assignment(self):
        """PandasAgent class should have _prompt_builder set."""
        source = DATA_PY_SOURCE.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "PandasAgent":
                class_src = ast.get_source_segment(source, node)
                assert "_prompt_builder" in class_src
                break
        else:
            pytest.fail("PandasAgent class not found")

    def test_source_imports_dataframe_context_layer(self):
        """data.py should import DATAFRAME_CONTEXT_LAYER."""
        source = DATA_PY_SOURCE.read_text()
        assert "DATAFRAME_CONTEXT_LAYER" in source

    def test_source_imports_strict_grounding_layer(self):
        """data.py should import STRICT_GROUNDING_LAYER."""
        source = DATA_PY_SOURCE.read_text()
        assert "STRICT_GROUNDING_LAYER" in source

    def test_source_imports_prompt_builder(self):
        """data.py should import PromptBuilder."""
        source = DATA_PY_SOURCE.read_text()
        assert "PromptBuilder" in source


class TestPandasPromptBuilder:
    """Test the pandas PromptBuilder configuration directly."""

    def _build_pandas_builder(self):
        """Replicate the PandasAgent builder setup."""
        from parrot.bots.prompts.domain_layers import (
            DATAFRAME_CONTEXT_LAYER,
            STRICT_GROUNDING_LAYER,
        )
        builder = PromptBuilder.default()
        builder.add(DATAFRAME_CONTEXT_LAYER)
        builder.add(STRICT_GROUNDING_LAYER)
        return builder

    def test_has_dataframe_context_layer(self):
        builder = self._build_pandas_builder()
        assert builder.get("dataframe_context") is not None

    def test_has_strict_grounding_layer(self):
        builder = self._build_pandas_builder()
        assert builder.get("strict_grounding") is not None

    def test_has_identity_layer(self):
        builder = self._build_pandas_builder()
        assert builder.get("identity") is not None

    def test_has_security_layer(self):
        builder = self._build_pandas_builder()
        assert builder.get("security") is not None

    def test_dataframe_context_renders_when_schemas_present(self):
        """When dataframe_schemas provided, <dataframe_context> appears."""
        builder = self._build_pandas_builder()
        # Configure with static vars
        builder.configure({
            "name": "TestBot",
            "role": "data analyst",
            "goal": "analyze data",
            "capabilities": "pandas analysis",
            "backstory": "expert",
            "rationale": "",
            "pre_instructions": "",
            "has_tools": True,
        })
        # Build with dataframe schemas
        prompt = builder.build({
            "dataframe_schemas": "Column: sales (float), Column: date (datetime)",
            "knowledge_content": "",
            "user_context": "",
            "chat_history": "",
        })
        assert "<dataframe_context>" in prompt
        assert "sales" in prompt

    def test_dataframe_context_omitted_when_no_schemas(self):
        """When no dataframe_schemas, <dataframe_context> should not appear."""
        builder = self._build_pandas_builder()
        builder.configure({
            "name": "TestBot",
            "role": "data analyst",
            "goal": "analyze data",
            "capabilities": "pandas analysis",
            "backstory": "expert",
            "rationale": "",
            "pre_instructions": "",
            "has_tools": True,
        })
        prompt = builder.build({
            "knowledge_content": "",
            "user_context": "",
            "chat_history": "",
        })
        assert "<dataframe_context>" not in prompt

    def test_strict_grounding_always_present(self):
        """Strict grounding layer should always render."""
        builder = self._build_pandas_builder()
        builder.configure({
            "name": "TestBot",
            "role": "data analyst",
            "goal": "analyze data",
            "capabilities": "",
            "backstory": "",
            "rationale": "",
            "pre_instructions": "",
            "has_tools": False,
        })
        prompt = builder.build({
            "knowledge_content": "",
            "user_context": "",
            "chat_history": "",
        })
        assert "<grounding_policy>" in prompt
        assert "Data not available" in prompt


class TestPandasAgentCreateSystemPromptOverride:

    def test_source_has_create_system_prompt_override(self):
        """PandasAgent should override create_system_prompt to inject schemas."""
        source = DATA_PY_SOURCE.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "PandasAgent":
                methods = [
                    n.name for n in ast.walk(node)
                    if isinstance(n, ast.AsyncFunctionDef)
                ]
                assert "create_system_prompt" in methods
                break
