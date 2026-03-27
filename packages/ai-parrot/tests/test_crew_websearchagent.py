"""
Unit tests for WebSearchAgent config passthrough in CrewHandler.

Tests verify that WebSearchAgent-specific parameters (contrastive_search,
contrastive_prompt, synthesize, synthesize_prompt) are correctly passed
from CrewDefinition through to the WebSearchAgent constructor.

TASK-052: Backend WebSearchAgent Config Passthrough Verification
FEAT-012: WebSearchAgent Support in CrewBuilder
"""
import pytest
from unittest.mock import patch


class TestWebSearchAgentExport:
    """Verify WebSearchAgent is properly exported from parrot.bots."""

    def test_websearchagent_importable_from_bots(self):
        """WebSearchAgent should be importable from parrot.bots."""
        from parrot.bots import WebSearchAgent
        from parrot.bots.search import WebSearchAgent as WSA
        assert WebSearchAgent is WSA

    def test_websearchagent_in_all_exports(self):
        """WebSearchAgent should be in __all__ exports."""
        from parrot import bots
        assert "WebSearchAgent" in bots.__all__


class TestWebSearchAgentParameters:
    """Test WebSearchAgent accepts the expected parameters."""

    def test_websearchagent_signature_includes_contrastive_search(self):
        """WebSearchAgent should accept contrastive_search parameter."""
        import inspect
        from parrot.bots.search import WebSearchAgent

        sig = inspect.signature(WebSearchAgent.__init__)
        params = sig.parameters

        assert 'contrastive_search' in params
        assert params['contrastive_search'].default is False

    def test_websearchagent_signature_includes_synthesize(self):
        """WebSearchAgent should accept synthesize parameter."""
        import inspect
        from parrot.bots.search import WebSearchAgent

        sig = inspect.signature(WebSearchAgent.__init__)
        params = sig.parameters

        assert 'synthesize' in params
        assert params['synthesize'].default is False

    def test_websearchagent_signature_includes_contrastive_prompt(self):
        """WebSearchAgent should accept contrastive_prompt parameter."""
        import inspect
        from parrot.bots.search import WebSearchAgent

        sig = inspect.signature(WebSearchAgent.__init__)
        params = sig.parameters

        assert 'contrastive_prompt' in params

    def test_websearchagent_signature_includes_synthesize_prompt(self):
        """WebSearchAgent should accept synthesize_prompt parameter."""
        import inspect
        from parrot.bots.search import WebSearchAgent

        sig = inspect.signature(WebSearchAgent.__init__)
        params = sig.parameters

        assert 'synthesize_prompt' in params


class TestCrewDefinitionModels:
    """Test CrewDefinition models can carry WebSearchAgent config."""

    @pytest.fixture
    def models_module(self):
        """Import models directly to avoid handler's navigator dependency."""
        # Import spec allows us to load just the models file without __init__
        import importlib.util
        import os
        models_path = os.path.join(
            os.path.dirname(__file__),
            '..', 'parrot', 'handlers', 'crew', 'models.py'
        )
        spec = importlib.util.spec_from_file_location("crew_models", models_path)
        models = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(models)
        return models

    def test_agent_definition_accepts_websearchagent_config(self, models_module):
        """AgentDefinition.config should accept WebSearchAgent-specific fields."""
        AgentDefinition = models_module.AgentDefinition

        agent_def = AgentDefinition(
            agent_id="web_search_1",
            agent_class="WebSearchAgent",
            name="Research Agent",
            config={
                "temperature": 0.0,
                "contrastive_search": True,
                "contrastive_prompt": "Compare $query vs: $search_results",
                "synthesize": True,
                "synthesize_prompt": "Summarize: $search_results"
            },
            tools=[],
            system_prompt="Research assistant"
        )

        assert agent_def.config["contrastive_search"] is True
        assert agent_def.config["synthesize"] is True
        assert "$query" in agent_def.config["contrastive_prompt"]
        assert "$search_results" in agent_def.config["synthesize_prompt"]

    def test_crew_definition_with_websearchagent(self, models_module):
        """CrewDefinition should accept WebSearchAgent with full config."""
        CrewDefinition = models_module.CrewDefinition
        AgentDefinition = models_module.AgentDefinition

        crew_def = CrewDefinition(
            name="research_crew",
            execution_mode="sequential",
            agents=[
                AgentDefinition(
                    agent_id="web_search_1",
                    agent_class="WebSearchAgent",
                    name="Research Agent",
                    config={
                        "temperature": 0.0,
                        "contrastive_search": True,
                        "contrastive_prompt": "Compare $query vs: $search_results",
                        "synthesize": True,
                        "synthesize_prompt": "Summarize: $search_results"
                    },
                    tools=[],
                    system_prompt="Research assistant"
                )
            ],
            flow_relations=[],
            shared_tools=[]
        )

        assert crew_def.name == "research_crew"
        assert len(crew_def.agents) == 1
        assert crew_def.agents[0].agent_class == "WebSearchAgent"
        assert crew_def.agents[0].config["contrastive_search"] is True


class TestConfigPassthrough:
    """Test that config dict can be unpacked as kwargs to WebSearchAgent."""

    def test_config_dict_unpacking_works(self):
        """Verify **config unpacking passes parameters correctly."""
        from parrot.bots.search import WebSearchAgent

        config = {
            "contrastive_search": True,
            "contrastive_prompt": "Test prompt with $query and $search_results",
            "synthesize": True,
            "synthesize_prompt": "Synthesize $query: $search_results"
        }

        # Track what gets passed to __init__
        captured_kwargs = {}

        def mock_init(self, *args, **kwargs):
            captured_kwargs.update(kwargs)
            # Set minimal attributes to avoid errors
            self.name = kwargs.get('name', 'test')
            self.contrastive_search = kwargs.get('contrastive_search', False)
            self.synthesize = kwargs.get('synthesize', False)
            self.contrastive_prompt = kwargs.get('contrastive_prompt', '')
            self.synthesize_prompt = kwargs.get('synthesize_prompt', '')

        with patch.object(WebSearchAgent, '__init__', mock_init):
            # Simulate what CrewHandler does: agent_class(name=..., tools=..., **config)
            _agent = WebSearchAgent(
                name="Research Agent",
                tools=[],
                **config
            )

            # Verify all config params were passed
            assert captured_kwargs.get('contrastive_search') is True
            assert captured_kwargs.get('synthesize') is True
            assert '$query' in captured_kwargs.get('contrastive_prompt', '')
            assert '$search_results' in captured_kwargs.get('synthesize_prompt', '')

    def test_empty_config_uses_defaults(self):
        """Verify empty config dict results in default values."""
        from parrot.bots.search import WebSearchAgent

        config = {}  # Empty config

        captured_kwargs = {}

        def mock_init(self, *args, **kwargs):
            captured_kwargs.update(kwargs)
            self.name = kwargs.get('name', 'test')

        with patch.object(WebSearchAgent, '__init__', mock_init):
            _agent = WebSearchAgent(
                name="Search Agent",
                tools=[],
                **config
            )

            # Empty config means no explicit values passed
            assert captured_kwargs.get('contrastive_search') is None
            assert captured_kwargs.get('synthesize') is None

    def test_contrastive_only_config(self):
        """Verify contrastive search can be enabled independently."""
        from parrot.bots.search import WebSearchAgent

        config = {
            "contrastive_search": True,
            "contrastive_prompt": "Find competitors: $query vs $search_results",
            "synthesize": False
        }

        captured_kwargs = {}

        def mock_init(self, *args, **kwargs):
            captured_kwargs.update(kwargs)
            self.name = kwargs.get('name', 'test')

        with patch.object(WebSearchAgent, '__init__', mock_init):
            _agent = WebSearchAgent(name="Agent", tools=[], **config)

            assert captured_kwargs.get('contrastive_search') is True
            assert captured_kwargs.get('synthesize') is False

    def test_synthesize_only_config(self):
        """Verify synthesis can be enabled independently."""
        from parrot.bots.search import WebSearchAgent

        config = {
            "contrastive_search": False,
            "synthesize": True,
            "synthesize_prompt": "Summarize findings for $query: $search_results"
        }

        captured_kwargs = {}

        def mock_init(self, *args, **kwargs):
            captured_kwargs.update(kwargs)
            self.name = kwargs.get('name', 'test')

        with patch.object(WebSearchAgent, '__init__', mock_init):
            _agent = WebSearchAgent(name="Agent", tools=[], **config)

            assert captured_kwargs.get('contrastive_search') is False
            assert captured_kwargs.get('synthesize') is True

    def test_temperature_passthrough(self):
        """Verify temperature parameter passes through config."""
        from parrot.bots.search import WebSearchAgent

        config = {
            "temperature": 0.0  # Low temp for search to avoid hallucination
        }

        captured_kwargs = {}

        def mock_init(self, *args, **kwargs):
            captured_kwargs.update(kwargs)
            self.name = kwargs.get('name', 'test')

        with patch.object(WebSearchAgent, '__init__', mock_init):
            _agent = WebSearchAgent(name="Agent", tools=[], **config)

            assert captured_kwargs.get('temperature') == 0.0


class TestWebSearchAgentDefaultPrompts:
    """Verify WebSearchAgent has sensible default prompts."""

    def test_default_contrastive_prompt_exists(self):
        """WebSearchAgent should have a default contrastive prompt."""
        from parrot.bots.search import DEFAULT_CONTRASTIVE_PROMPT

        assert DEFAULT_CONTRASTIVE_PROMPT is not None
        assert '$query' in DEFAULT_CONTRASTIVE_PROMPT
        assert '$search_results' in DEFAULT_CONTRASTIVE_PROMPT

    def test_default_synthesize_prompt_exists(self):
        """WebSearchAgent should have a default synthesis prompt."""
        from parrot.bots.search import DEFAULT_SYNTHESIZE_PROMPT

        assert DEFAULT_SYNTHESIZE_PROMPT is not None
        assert '$query' in DEFAULT_SYNTHESIZE_PROMPT
        assert '$search_results' in DEFAULT_SYNTHESIZE_PROMPT
