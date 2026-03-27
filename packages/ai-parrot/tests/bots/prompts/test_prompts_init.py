"""Tests for prompts package __init__.py re-exports."""
import pytest


class TestNewImports:

    def test_prompt_layer_import(self):
        from parrot.bots.prompts import PromptLayer
        assert PromptLayer is not None

    def test_prompt_builder_import(self):
        from parrot.bots.prompts import PromptBuilder
        assert PromptBuilder is not None

    def test_layer_priority_import(self):
        from parrot.bots.prompts import LayerPriority
        assert LayerPriority is not None

    def test_render_phase_import(self):
        from parrot.bots.prompts import RenderPhase
        assert RenderPhase is not None

    def test_builtin_layers_import(self):
        from parrot.bots.prompts import (
            IDENTITY_LAYER,
            SECURITY_LAYER,
            KNOWLEDGE_LAYER,
            USER_SESSION_LAYER,
            TOOLS_LAYER,
            OUTPUT_LAYER,
            BEHAVIOR_LAYER,
        )
        assert IDENTITY_LAYER.name == "identity"
        assert SECURITY_LAYER.name == "security"

    def test_domain_layers_import(self):
        from parrot.bots.prompts import (
            DATAFRAME_CONTEXT_LAYER,
            SQL_DIALECT_LAYER,
            COMPANY_CONTEXT_LAYER,
            CREW_CONTEXT_LAYER,
            STRICT_GROUNDING_LAYER,
            get_domain_layer,
        )
        assert DATAFRAME_CONTEXT_LAYER.name == "dataframe_context"
        assert callable(get_domain_layer)


class TestPresetImports:

    def test_get_preset_import(self):
        from parrot.bots.prompts import get_preset
        assert callable(get_preset)

    def test_register_preset_import(self):
        from parrot.bots.prompts import register_preset
        assert callable(register_preset)

    def test_list_presets_import(self):
        from parrot.bots.prompts import list_presets
        names = list_presets()
        assert "default" in names
        assert "minimal" in names
        assert "voice" in names
        assert "agent" in names


class TestLegacyImports:

    def test_basic_system_prompt(self):
        from parrot.bots.prompts import BASIC_SYSTEM_PROMPT
        assert isinstance(BASIC_SYSTEM_PROMPT, str)
        assert "$name" in BASIC_SYSTEM_PROMPT

    def test_agent_prompt(self):
        from parrot.bots.prompts import AGENT_PROMPT
        assert isinstance(AGENT_PROMPT, str)

    def test_output_system_prompt(self):
        from parrot.bots.prompts import OUTPUT_SYSTEM_PROMPT
        assert isinstance(OUTPUT_SYSTEM_PROMPT, str)

    def test_company_system_prompt(self):
        from parrot.bots.prompts import COMPANY_SYSTEM_PROMPT
        assert isinstance(COMPANY_SYSTEM_PROMPT, str)
        assert "$company_information" in COMPANY_SYSTEM_PROMPT

    def test_default_constants(self):
        from parrot.bots.prompts import (
            DEFAULT_CAPABILITIES,
            DEFAULT_GOAL,
            DEFAULT_ROLE,
            DEFAULT_BACKHISTORY,
            DEFAULT_RATIONALE,
        )
        assert isinstance(DEFAULT_CAPABILITIES, str)
        assert isinstance(DEFAULT_GOAL, str)
        assert isinstance(DEFAULT_ROLE, str)


class TestIdentityLayerFromLayers:

    def test_direct_layer_import(self):
        """from parrot.bots.prompts.layers import IDENTITY_LAYER should work."""
        from parrot.bots.prompts.layers import IDENTITY_LAYER
        assert IDENTITY_LAYER.name == "identity"

    def test_no_import_errors(self):
        """Importing the package should not raise."""
        import parrot.bots.prompts
        assert hasattr(parrot.bots.prompts, "PromptBuilder")
        assert hasattr(parrot.bots.prompts, "BASIC_SYSTEM_PROMPT")
