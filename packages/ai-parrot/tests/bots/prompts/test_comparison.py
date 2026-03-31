"""Comparison tests: Legacy prompt templates vs Composable Layer outputs.

Verifies semantic equivalence — same sections present, same variable
values, correct ordering — without requiring exact string equality.
The composable system uses XML tags while legacy uses markdown headers,
so we compare structural content rather than formatting.
"""
import sys
import pytest
from string import Template
from unittest.mock import MagicMock, AsyncMock, patch
from parrot.bots.prompts.builder import PromptBuilder
from parrot.bots.prompts.layers import PromptLayer, LayerPriority, RenderPhase


# The real module is loaded by conftest.py in this package.
_RealAbstractBot = sys.modules["parrot.bots.abstract"].AbstractBot
_build_prompt = _RealAbstractBot._build_prompt
_configure_prompt_builder = _RealAbstractBot._configure_prompt_builder

# Import legacy template
from parrot.bots.prompts import BASIC_SYSTEM_PROMPT


class MockBot:
    """Minimal mock for both legacy and layer paths."""

    _build_prompt = _build_prompt
    _configure_prompt_builder = _configure_prompt_builder

    def __init__(self, use_layers=False):
        self.name = "CompareBot"
        self.role = "helpful assistant"
        self.goal = "help users with questions"
        self.capabilities = "- Answer questions\n- Analyze data"
        self.backstory = "Expert in many domains"
        self.rationale = "Be concise and accurate."
        self.pre_instructions = []
        self.enable_tools = False
        self.tool_manager = MagicMock()
        self.tool_manager.tool_count.return_value = 0
        self.logger = MagicMock()
        self._prompt_builder = None
        self.system_prompt_template = BASIC_SYSTEM_PROMPT

        if use_layers:
            self._prompt_builder = PromptBuilder.default()


def _render_legacy(bot, user_context="", vector_context="",
                   conversation_context="", kb_context=""):
    """Render legacy prompt path (simplified — mirrors AbstractBot logic)."""
    context_parts = []
    if vector_context:
        context_parts.extend(["\n## Document Context:", vector_context])
    chat_history = ""
    if conversation_context:
        chat_history = f"\n## Conversation Context:\n{conversation_context}"
    u_context = ""
    if user_context:
        u_context = f"\n### User Context:\n{user_context}"

    tmpl = Template(bot.system_prompt_template)
    return tmpl.safe_substitute(
        name=bot.name,
        role=bot.role,
        goal=bot.goal,
        capabilities=bot.capabilities,
        backstory=bot.backstory,
        rationale=bot.rationale,
        pre_context="",
        context="\n".join(context_parts),
        user_context=u_context,
        chat_history=chat_history,
    )


class TestLegacyVsLayerIdentity:
    """Both paths should include the same identity information."""

    @pytest.mark.asyncio
    @patch('parrot.bots.abstract.dynamic_values')
    async def test_both_include_bot_name(self, mock_dv):
        mock_dv.get_all_names.return_value = []
        legacy_bot = MockBot(use_layers=False)
        layer_bot = MockBot(use_layers=True)

        legacy_prompt = _render_legacy(legacy_bot)
        await layer_bot._configure_prompt_builder()
        layer_prompt = layer_bot._build_prompt()

        assert "CompareBot" in legacy_prompt
        assert "CompareBot" in layer_prompt

    @pytest.mark.asyncio
    @patch('parrot.bots.abstract.dynamic_values')
    async def test_both_include_role(self, mock_dv):
        mock_dv.get_all_names.return_value = []
        legacy_bot = MockBot(use_layers=False)
        layer_bot = MockBot(use_layers=True)

        legacy_prompt = _render_legacy(legacy_bot)
        await layer_bot._configure_prompt_builder()
        layer_prompt = layer_bot._build_prompt()

        assert "helpful assistant" in legacy_prompt
        assert "helpful assistant" in layer_prompt

    @pytest.mark.asyncio
    @patch('parrot.bots.abstract.dynamic_values')
    async def test_both_include_capabilities(self, mock_dv):
        mock_dv.get_all_names.return_value = []
        legacy_bot = MockBot(use_layers=False)
        layer_bot = MockBot(use_layers=True)

        legacy_prompt = _render_legacy(legacy_bot)
        await layer_bot._configure_prompt_builder()
        layer_prompt = layer_bot._build_prompt()

        assert "Answer questions" in legacy_prompt
        assert "Answer questions" in layer_prompt


class TestLegacyVsLayerSecurity:
    """Both paths should include security-related content."""

    @pytest.mark.asyncio
    @patch('parrot.bots.abstract.dynamic_values')
    async def test_legacy_has_security_rules(self, mock_dv):
        mock_dv.get_all_names.return_value = []
        bot = MockBot(use_layers=False)
        prompt = _render_legacy(bot)
        # Legacy template has inline security rules
        assert "security" in prompt.lower() or "SECURITY" in prompt

    @pytest.mark.asyncio
    @patch('parrot.bots.abstract.dynamic_values')
    async def test_layer_has_security_policy(self, mock_dv):
        mock_dv.get_all_names.return_value = []
        bot = MockBot(use_layers=True)
        await bot._configure_prompt_builder()
        prompt = bot._build_prompt()
        assert "<security_policy>" in prompt


class TestLegacyVsLayerKnowledge:
    """Both paths should include knowledge context when provided."""

    @pytest.mark.asyncio
    @patch('parrot.bots.abstract.dynamic_values')
    async def test_both_include_vector_context(self, mock_dv):
        mock_dv.get_all_names.return_value = []
        legacy_bot = MockBot(use_layers=False)
        layer_bot = MockBot(use_layers=True)

        legacy_prompt = _render_legacy(
            legacy_bot, vector_context="relevant documents here")
        await layer_bot._configure_prompt_builder()
        layer_prompt = layer_bot._build_prompt(
            vector_context="relevant documents here")

        assert "relevant documents here" in legacy_prompt
        assert "relevant documents here" in layer_prompt

    @pytest.mark.asyncio
    @patch('parrot.bots.abstract.dynamic_values')
    async def test_both_omit_context_when_empty(self, mock_dv):
        mock_dv.get_all_names.return_value = []
        legacy_bot = MockBot(use_layers=False)
        layer_bot = MockBot(use_layers=True)

        legacy_prompt = _render_legacy(legacy_bot)
        await layer_bot._configure_prompt_builder()
        layer_prompt = layer_bot._build_prompt()

        # Neither should contain document context markers
        assert "relevant documents" not in legacy_prompt
        assert "<knowledge_context>" not in layer_prompt


class TestLegacyVsLayerUserSession:
    """Both paths should include user context and chat history."""

    @pytest.mark.asyncio
    @patch('parrot.bots.abstract.dynamic_values')
    async def test_both_include_user_context(self, mock_dv):
        mock_dv.get_all_names.return_value = []
        legacy_bot = MockBot(use_layers=False)
        layer_bot = MockBot(use_layers=True)

        legacy_prompt = _render_legacy(
            legacy_bot, user_context="User prefers short answers")
        await layer_bot._configure_prompt_builder()
        layer_prompt = layer_bot._build_prompt(
            user_context="User prefers short answers")

        assert "User prefers short answers" in legacy_prompt
        assert "User prefers short answers" in layer_prompt

    @pytest.mark.asyncio
    @patch('parrot.bots.abstract.dynamic_values')
    async def test_both_include_conversation_history(self, mock_dv):
        mock_dv.get_all_names.return_value = []
        legacy_bot = MockBot(use_layers=False)
        layer_bot = MockBot(use_layers=True)

        legacy_prompt = _render_legacy(
            legacy_bot, conversation_context="Human: hi\nBot: hello")
        await layer_bot._configure_prompt_builder()
        layer_prompt = layer_bot._build_prompt(
            conversation_context="Human: hi\nBot: hello")

        assert "Human: hi" in legacy_prompt
        assert "Human: hi" in layer_prompt


class TestLayerOrdering:
    """Layer-based output should maintain correct section ordering."""

    @pytest.mark.asyncio
    @patch('parrot.bots.abstract.dynamic_values')
    async def test_identity_before_security(self, mock_dv):
        mock_dv.get_all_names.return_value = []
        bot = MockBot(use_layers=True)
        await bot._configure_prompt_builder()
        prompt = bot._build_prompt(
            vector_context="docs",
            user_context="user info",
            conversation_context="chat",
        )
        id_pos = prompt.index("</agent_identity>")
        sec_pos = prompt.index("</security_policy>")
        assert id_pos < sec_pos

    @pytest.mark.asyncio
    @patch('parrot.bots.abstract.dynamic_values')
    async def test_security_before_knowledge(self, mock_dv):
        mock_dv.get_all_names.return_value = []
        bot = MockBot(use_layers=True)
        await bot._configure_prompt_builder()
        prompt = bot._build_prompt(
            vector_context="docs",
        )
        sec_pos = prompt.index("</security_policy>")
        know_pos = prompt.index("</knowledge_context>")
        assert sec_pos < know_pos

    @pytest.mark.asyncio
    @patch('parrot.bots.abstract.dynamic_values')
    async def test_knowledge_before_user_session(self, mock_dv):
        mock_dv.get_all_names.return_value = []
        bot = MockBot(use_layers=True)
        await bot._configure_prompt_builder()
        prompt = bot._build_prompt(
            vector_context="docs",
            user_context="user info",
        )
        know_pos = prompt.index("</knowledge_context>")
        session_pos = prompt.index("</user_session>")
        assert know_pos < session_pos


class TestFullContextComparison:
    """End-to-end: full context rendering with both paths."""

    @pytest.mark.asyncio
    @patch('parrot.bots.abstract.dynamic_values')
    async def test_full_context_both_include_all_content(self, mock_dv):
        mock_dv.get_all_names.return_value = []
        legacy_bot = MockBot(use_layers=False)
        layer_bot = MockBot(use_layers=True)

        legacy_prompt = _render_legacy(
            legacy_bot,
            user_context="admin user",
            vector_context="doc content here",
            conversation_context="Human: what?\nBot: that",
        )
        await layer_bot._configure_prompt_builder()
        layer_prompt = layer_bot._build_prompt(
            user_context="admin user",
            vector_context="doc content here",
            conversation_context="Human: what?\nBot: that",
        )

        # Both should contain all key content
        for content in ["CompareBot", "helpful assistant", "admin user",
                        "doc content here", "Human: what?"]:
            assert content in legacy_prompt, f"Legacy missing: {content}"
            assert content in layer_prompt, f"Layer missing: {content}"

    @pytest.mark.asyncio
    @patch('parrot.bots.abstract.dynamic_values')
    async def test_minimal_context_both_include_identity(self, mock_dv):
        """With minimal context, both paths still render identity."""
        mock_dv.get_all_names.return_value = []
        legacy_bot = MockBot(use_layers=False)
        layer_bot = MockBot(use_layers=True)

        legacy_prompt = _render_legacy(legacy_bot)
        await layer_bot._configure_prompt_builder()
        layer_prompt = layer_bot._build_prompt()

        assert "CompareBot" in legacy_prompt
        assert "CompareBot" in layer_prompt

    @pytest.mark.asyncio
    @patch('parrot.bots.abstract.dynamic_values')
    async def test_layer_uses_xml_tags(self, mock_dv):
        """Layer path should use structured XML tags."""
        mock_dv.get_all_names.return_value = []
        bot = MockBot(use_layers=True)
        await bot._configure_prompt_builder()
        prompt = bot._build_prompt(
            vector_context="docs",
            user_context="user",
            conversation_context="chat",
        )
        assert "<agent_identity>" in prompt
        assert "<security_policy>" in prompt
        assert "<knowledge_context>" in prompt
        assert "<user_session>" in prompt

    @pytest.mark.asyncio
    @patch('parrot.bots.abstract.dynamic_values')
    async def test_legacy_uses_template_vars(self, mock_dv):
        """Legacy path should resolve all $variable placeholders."""
        mock_dv.get_all_names.return_value = []
        bot = MockBot(use_layers=False)
        prompt = _render_legacy(bot)
        # No unresolved $name, $role, etc.
        assert "$name" not in prompt
        assert "$role" not in prompt
        assert "$capabilities" not in prompt


class TestCustomLayerAtRuntime:
    """Test adding custom layers at runtime produces correct output."""

    @pytest.mark.asyncio
    @patch('parrot.bots.abstract.dynamic_values')
    async def test_custom_layer_appears_in_output(self, mock_dv):
        mock_dv.get_all_names.return_value = []
        bot = MockBot(use_layers=True)
        bot._prompt_builder.add(PromptLayer(
            name="custom_instructions",
            priority=LayerPriority.CUSTOM,
            phase=RenderPhase.CONFIGURE,
            template="<custom_instructions>Always cite sources.</custom_instructions>",
        ))
        await bot._configure_prompt_builder()
        prompt = bot._build_prompt()
        assert "<custom_instructions>" in prompt
        assert "Always cite sources" in prompt

    @pytest.mark.asyncio
    @patch('parrot.bots.abstract.dynamic_values')
    async def test_custom_layer_ordering(self, mock_dv):
        """Custom layer (priority 80) should come after behavior (70)."""
        mock_dv.get_all_names.return_value = []
        bot = MockBot(use_layers=True)
        bot.rationale = "Be helpful"
        bot._prompt_builder.add(PromptLayer(
            name="custom",
            priority=LayerPriority.CUSTOM,
            phase=RenderPhase.CONFIGURE,
            template="<custom>Extra instructions</custom>",
        ))
        await bot._configure_prompt_builder()
        prompt = bot._build_prompt()
        behavior_pos = prompt.index("</response_style>")
        custom_pos = prompt.index("<custom>")
        assert behavior_pos < custom_pos

    @pytest.mark.asyncio
    @patch('parrot.bots.abstract.dynamic_values')
    async def test_remove_layer_at_runtime(self, mock_dv):
        mock_dv.get_all_names.return_value = []
        bot = MockBot(use_layers=True)
        bot._prompt_builder.remove("tools")
        bot._prompt_builder.remove("output")
        await bot._configure_prompt_builder()
        prompt = bot._build_prompt()
        assert "<tool_policy>" not in prompt
        assert "<output_format>" not in prompt
        assert "<agent_identity>" in prompt


class TestVoicePresetComparison:
    """VoiceBot uses PromptBuilder.voice() — verify voice-specific behavior."""

    @pytest.mark.asyncio
    @patch('parrot.bots.abstract.dynamic_values')
    async def test_voice_preset_produces_concise_behavior(self, mock_dv):
        mock_dv.get_all_names.return_value = []
        bot = MockBot(use_layers=False)
        bot._prompt_builder = PromptBuilder.voice()
        await bot._configure_prompt_builder()
        prompt = bot._build_prompt()
        assert "<response_style>" in prompt
        assert "concise" in prompt.lower()
        assert "conversational" in prompt.lower()

    @pytest.mark.asyncio
    @patch('parrot.bots.abstract.dynamic_values')
    async def test_voice_preset_still_has_identity(self, mock_dv):
        mock_dv.get_all_names.return_value = []
        bot = MockBot(use_layers=False)
        bot._prompt_builder = PromptBuilder.voice()
        await bot._configure_prompt_builder()
        prompt = bot._build_prompt()
        assert "CompareBot" in prompt
        assert "<agent_identity>" in prompt
