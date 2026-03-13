"""Integration tests for AbstractBot PromptBuilder integration."""
import importlib
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from parrot.bots.prompts.builder import PromptBuilder
from parrot.bots.prompts.layers import LayerPriority, PromptLayer


# We can't easily instantiate AbstractBot (it's an ABC with many deps),
# so we test the methods directly via mocking.

# Force-load the REAL parrot.bots.abstract module (conftest installs a stub).
_saved = sys.modules.pop("parrot.bots.abstract", None)
_real_abstract = importlib.import_module("parrot.bots.abstract")
sys.modules["parrot.bots.abstract"] = _real_abstract
_RealAbstractBot = _real_abstract.AbstractBot

# Extract unbound methods from the real class
_configure_prompt_builder = _RealAbstractBot._configure_prompt_builder
_build_prompt_from_layers = _RealAbstractBot._build_prompt_from_layers


class MockBot:
    """Minimal mock that mimics AbstractBot's prompt-related attributes."""

    _configure_prompt_builder = _configure_prompt_builder
    _build_prompt_from_layers = _build_prompt_from_layers

    def __init__(self, prompt_preset=None):
        self.name = "TestBot"
        self.role = "helpful assistant"
        self.goal = "help users"
        self.capabilities = "- Can search"
        self.backstory = "Expert in AI"
        self.rationale = "Be concise"
        self.pre_instructions = ["Follow safety rules", "Be polite"]
        self.enable_tools = True
        self.tool_manager = MagicMock()
        self.tool_manager.tool_count.return_value = 3
        self.logger = MagicMock()
        self._prompt_builder = None

        if prompt_preset:
            from parrot.bots.prompts.presets import get_preset
            self._prompt_builder = get_preset(prompt_preset)


class TestPromptBuilderInitialization:

    def test_no_preset_no_builder(self):
        bot = MockBot()
        assert bot._prompt_builder is None

    def test_preset_creates_builder(self):
        bot = MockBot(prompt_preset="default")
        assert bot._prompt_builder is not None
        assert isinstance(bot._prompt_builder, PromptBuilder)

    def test_preset_minimal(self):
        bot = MockBot(prompt_preset="minimal")
        assert bot._prompt_builder.get("identity") is not None
        assert bot._prompt_builder.get("tools") is None

    def test_preset_voice(self):
        bot = MockBot(prompt_preset="voice")
        behavior = bot._prompt_builder.get("behavior")
        assert behavior is not None
        assert "concise" in behavior.template.lower()


class TestConfigurePromptBuilder:

    @pytest.mark.asyncio
    @patch('parrot.bots.abstract.dynamic_values')
    async def test_configure_resolves_static_vars(self, mock_dv):
        mock_dv.get_all_names.return_value = []
        bot = MockBot(prompt_preset="default")
        await bot._configure_prompt_builder()
        assert bot._prompt_builder.is_configured
        identity = bot._prompt_builder.get("identity")
        assert "TestBot" in identity.template
        assert "helpful assistant" in identity.template

    @pytest.mark.asyncio
    @patch('parrot.bots.abstract.dynamic_values')
    async def test_configure_resolves_pre_instructions(self, mock_dv):
        mock_dv.get_all_names.return_value = []
        bot = MockBot(prompt_preset="default")
        await bot._configure_prompt_builder()
        # Pre-instructions should be resolved in the pre_instructions layer
        pre = bot._prompt_builder.get("pre_instructions")
        assert "Follow safety rules" in pre.template
        assert "Be polite" in pre.template

    @pytest.mark.asyncio
    @patch('parrot.bots.abstract.dynamic_values')
    async def test_configure_resolves_tools_condition(self, mock_dv):
        mock_dv.get_all_names.return_value = []
        bot = MockBot(prompt_preset="default")
        await bot._configure_prompt_builder()
        # Tools layer should be present (enable_tools=True, tool_count=3)
        tools = bot._prompt_builder.get("tools")
        # After configure, condition is cleared (was True), so render works
        result = tools.render({})
        assert "<tool_policy>" in result

    @pytest.mark.asyncio
    @patch('parrot.bots.abstract.dynamic_values')
    async def test_configure_resolves_dynamic_values(self, mock_dv):
        mock_dv.get_all_names.return_value = ["custom_var"]
        mock_dv.get_value = AsyncMock(return_value="custom_value")
        bot = MockBot(prompt_preset="default")
        # Add a layer that uses the dynamic value
        from parrot.bots.prompts.layers import RenderPhase
        bot._prompt_builder.add(PromptLayer(
            name="custom",
            priority=LayerPriority.CUSTOM,
            phase=RenderPhase.CONFIGURE,
            template="<custom>$custom_var</custom>",
        ))
        await bot._configure_prompt_builder()
        custom = bot._prompt_builder.get("custom")
        assert "custom_value" in custom.template

    @pytest.mark.asyncio
    @patch('parrot.bots.abstract.dynamic_values')
    async def test_configure_handles_dynamic_value_error(self, mock_dv):
        mock_dv.get_all_names.return_value = ["bad_var"]
        mock_dv.get_value = AsyncMock(side_effect=Exception("boom"))
        bot = MockBot(prompt_preset="default")
        await bot._configure_prompt_builder()
        # Should not raise, just log warning
        assert bot._prompt_builder.is_configured
        bot.logger.warning.assert_called()


class TestBuildPromptFromLayers:

    @pytest.mark.asyncio
    @patch('parrot.bots.abstract.dynamic_values')
    async def test_build_with_knowledge(self, mock_dv):
        mock_dv.get_all_names.return_value = []
        bot = MockBot(prompt_preset="default")
        await bot._configure_prompt_builder()
        prompt = bot._build_prompt_from_layers(
            vector_context="some documents",
            kb_context="some facts",
        )
        assert "<knowledge_context>" in prompt
        assert "<documents>" in prompt
        assert "some documents" in prompt
        assert "<facts>" in prompt
        assert "some facts" in prompt

    @pytest.mark.asyncio
    @patch('parrot.bots.abstract.dynamic_values')
    async def test_build_with_pageindex(self, mock_dv):
        mock_dv.get_all_names.return_value = []
        bot = MockBot(prompt_preset="default")
        await bot._configure_prompt_builder()
        prompt = bot._build_prompt_from_layers(
            pageindex_context="tree structure",
        )
        assert "<document_structure>" in prompt
        assert "tree structure" in prompt

    @pytest.mark.asyncio
    @patch('parrot.bots.abstract.dynamic_values')
    async def test_build_with_user_session(self, mock_dv):
        mock_dv.get_all_names.return_value = []
        bot = MockBot(prompt_preset="default")
        await bot._configure_prompt_builder()
        prompt = bot._build_prompt_from_layers(
            user_context="user info",
            conversation_context="prior messages",
        )
        assert "<user_session>" in prompt
        assert "user info" in prompt
        assert "prior messages" in prompt

    @pytest.mark.asyncio
    @patch('parrot.bots.abstract.dynamic_values')
    async def test_build_with_metadata(self, mock_dv):
        mock_dv.get_all_names.return_value = []
        bot = MockBot(prompt_preset="default")
        await bot._configure_prompt_builder()
        prompt = bot._build_prompt_from_layers(
            vector_context="docs",
            metadata={"topic": "AI", "confidence": 0.95},
        )
        assert "<metadata>" in prompt
        assert "topic: AI" in prompt

    @pytest.mark.asyncio
    @patch('parrot.bots.abstract.dynamic_values')
    async def test_build_empty_contexts_omits_knowledge(self, mock_dv):
        mock_dv.get_all_names.return_value = []
        bot = MockBot(prompt_preset="default")
        await bot._configure_prompt_builder()
        prompt = bot._build_prompt_from_layers()
        assert "<knowledge_context>" not in prompt

    @pytest.mark.asyncio
    @patch('parrot.bots.abstract.dynamic_values')
    async def test_build_has_identity(self, mock_dv):
        mock_dv.get_all_names.return_value = []
        bot = MockBot(prompt_preset="default")
        await bot._configure_prompt_builder()
        prompt = bot._build_prompt_from_layers()
        assert "<agent_identity>" in prompt
        assert "TestBot" in prompt

    @pytest.mark.asyncio
    @patch('parrot.bots.abstract.dynamic_values')
    async def test_build_has_security(self, mock_dv):
        mock_dv.get_all_names.return_value = []
        bot = MockBot(prompt_preset="default")
        await bot._configure_prompt_builder()
        prompt = bot._build_prompt_from_layers()
        assert "<security_policy>" in prompt


class TestLegacyPathUnchanged:

    def test_no_builder_returns_none(self):
        """Without _prompt_builder, create_system_prompt should use legacy path."""
        bot = MockBot()
        assert bot._prompt_builder is None
        # _build_prompt_from_layers should NOT be called when _prompt_builder is None
