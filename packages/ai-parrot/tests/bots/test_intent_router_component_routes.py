"""Composite-route wiring in IntentRouterMixin (FEAT-755 TASK-4760)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from parrot.bots.mixins.intent_router import IntentRouterMixin
from parrot.bots.data import DEFAULT_OUTPUT_MODE_ROUTES, PandasAgent
from parrot.conf import AGENTS_DIR
from parrot.models.outputs import OutputMode
from parrot.registry.capabilities.models import IntentRouterConfig
from parrot.registry.routing.route_bank import ResolvedRouteBanks
from parrot.registry.routing.embedding_router import RouteScore


class _FakeRouter:
    """In-memory router that exposes the production router contract."""

    encoder_loads = 0

    def __init__(self, model, threshold, margin, *, encoder=None):
        self.threshold = threshold
        self.margin = margin
        self._encoder = encoder
        self.routes = {}
        self.score = RouteScore(None, -1.0, -1.0, False)
        self.scores = []

    def _ensure_encoder(self):
        if self._encoder is None:
            type(self).encoder_loads += 1
            self._encoder = object()
        return self._encoder

    def add_route(self, label, utterances):
        self._ensure_encoder()
        self.routes[str(label)] = utterances

    def route(self, query):
        return self.score

    def route_label_scores(self, query):
        return self.scores


class _SuperSentinel:
    """Terminal cooperative MRO member used to assert abstain behavior."""

    def __init__(self, **kwargs):
        self.super_called = False
        super().__init__()

    async def _resolve_output_mode(self, query, ctx):
        self.super_called = True
        return None


class _Agent(IntentRouterMixin, _SuperSentinel):
    pass


@pytest.fixture
def fake_router(monkeypatch):
    """Replace embeddings with a deterministic router contract."""
    _FakeRouter.encoder_loads = 0
    monkeypatch.setattr("parrot.bots.mixins.intent_router.EmbeddingIntentRouter", _FakeRouter)
    return _FakeRouter


def _config(**kwargs):
    values = {
        "enable_output_mode_routing": True,
        "output_mode_routes": {"structured_table": ["make a table"]},
    }
    values.update(kwargs)
    return IntentRouterConfig(**values)


class TestConfigureValidation:
    """Configuration rejects invalid route labels without disabling routing."""

    def test_invalid_labels_are_skipped_while_router_is_built(self, fake_router, monkeypatch, caplog):
        monkeypatch.setattr(
            "parrot.bots.mixins.intent_router.is_inline_component",
            lambda component: component == "KPICard",
        )
        agent = _Agent()

        agent.configure_output_router(
            _config(
                output_mode_routes={
                    "unknown": ["bad"],
                    "a2ui: ": ["bad"],
                    "a2ui:ActionForm": ["bad"],
                    "a2ui:KPICard": ["good"],
                }
            )
        )

        assert agent._output_router is not None
        assert agent._output_router.routes == {"a2ui:KPICard": ["good"]}
        assert caplog.text.count("Invalid route label") == 2
        assert "action-bearing; skipping" in caplog.text


class TestTenantRouters:
    """Tenant phrase banks reuse the global router encoder."""

    def test_tenant_routers_share_one_encoder(self, fake_router):
        agent = _Agent()
        agent.configure_output_router(
            _config(
                tenant_output_mode_routes={
                    "north": {"structured_chart": ["chart"]},
                    "south": {"structured_map": ["map"]},
                }
            )
        )

        global_router = agent._output_router
        assert global_router is not None
        assert set(agent._tenant_output_routers) == {"north", "south"}
        assert _FakeRouter.encoder_loads == 1
        assert all(router._encoder is global_router._encoder for router in agent._tenant_output_routers.values())

    def test_current_tenant_precedes_context_tenant_and_unknown_warns_once(self, fake_router, monkeypatch, caplog):
        agent = _Agent()
        agent.configure_output_router(_config(tenant_output_mode_routes={"north": {}}))
        ctx = SimpleNamespace(kwargs={"tenant": "north"})

        monkeypatch.setattr("parrot.bots.mixins.intent_router.current_skill_tenant", lambda: "unknown")
        assert agent._select_output_router(ctx) is agent._output_router
        assert agent._select_output_router(ctx) is agent._output_router
        assert caplog.text.count("Unknown output-router tenant") == 1

        monkeypatch.setattr("parrot.bots.mixins.intent_router.current_skill_tenant", lambda: None)
        assert agent._select_output_router(ctx) is agent._tenant_output_routers["north"]


class TestResolution:
    """Composite and plain output routes preserve the public return type."""

    async def test_composite_win_sets_hint_and_returns_a2ui(self, fake_router):
        agent = _Agent()
        agent.configure_output_router(_config(output_mode_routes={"a2ui:KPICard": ["kpi"]}))
        agent._output_router.score = RouteScore(OutputMode.A2UI, 0.9, 0.2, False, "a2ui:KPICard", "KPICard")
        ctx = SimpleNamespace(kwargs={}, intent_score=None, a2ui_component=None)

        assert await agent._resolve_output_mode("show kpis", ctx) is OutputMode.A2UI
        assert ctx.a2ui_component == "KPICard"
        assert ctx.intent_score == 0.9

    async def test_plain_win_and_abstain_preserve_existing_behavior(self, fake_router):
        agent = _Agent()
        agent.configure_output_router(_config())
        agent._output_router.score = RouteScore(OutputMode.STRUCTURED_TABLE, 0.9, 0.2, False, "structured_table")
        assert await agent._resolve_output_mode("make table", None) is OutputMode.STRUCTURED_TABLE

        agent._output_router.score = RouteScore(None, 0.4, 0.2, False)
        assert await agent._resolve_output_mode("abstain", None) is None
        assert agent.super_called is True


class TestTieBreaker:
    """The bounded LLM tie-breaker operates on route labels."""

    async def test_label_candidates_accept_plain_label_and_reject_off_list(self, fake_router):
        agent = _Agent()

        async def invoke(prompt):
            return '{"output_mode": "structured_table"}'

        agent.invoke = invoke
        assert (
            await agent._llm_disambiguate_output_mode("table", ["structured_chart", "structured_table"])
            == "structured_table"
        )

        async def off_list(prompt):
            return '{"output_mode": "default"}'

        agent.invoke = off_list
        assert await agent._llm_disambiguate_output_mode("table", ["structured_table"]) is None

    async def test_ambiguous_off_list_answer_abstains_to_embedding_winner(self, fake_router):
        agent = _Agent()
        agent.configure_output_router(_config())
        agent._output_router.score = RouteScore(OutputMode.STRUCTURED_CHART, 0.9, 0.89, True, "structured_chart")
        agent._output_router.scores = [("structured_chart", 0.9), ("structured_table", 0.89)]

        async def invoke(prompt):
            return '{"output_mode": "not-a-candidate"}'

        agent.invoke = invoke
        assert await agent._resolve_output_mode("render this", None) is OutputMode.STRUCTURED_CHART


class TestDefaultBankAndConfigure:
    """PandasAgent builds component routing from the resolved route banks."""

    def test_default_component_banks_are_bilingual_and_complete(self):
        component_routes = ("a2ui:KPICard", "a2ui:InfoCard", "a2ui:Timeline", "a2ui:Graph")

        for route in component_routes:
            utterances = DEFAULT_OUTPUT_MODE_ROUTES[route]
            english_utterances = utterances[:8]
            spanish_utterances = utterances[8:]
            assert len(utterances) >= 16
            assert all(utterance.strip() for utterance in utterances)
            assert len(english_utterances) >= 8
            assert len(spanish_utterances) >= 8

    @staticmethod
    def _stub_configure_dependencies(monkeypatch):
        async def configure_parent(self, app=None):
            return None

        monkeypatch.setattr("parrot.bots.data.BasicAgent.configure", configure_parent)
        monkeypatch.setattr(PandasAgent, "_sync_dataframes_from_dm", lambda self: None)
        monkeypatch.setattr(PandasAgent, "_define_prompt", lambda self: None)

    async def test_configure_resolves_and_forwards_global_and_tenant_banks(self, monkeypatch):
        self._stub_configure_dependencies(monkeypatch)
        resolved = ResolvedRouteBanks(
            routes={"a2ui:KPICard": ["total revenue"]},
            tenant_routes={"north": {"a2ui:InfoCard": ["account summary"]}},
            threshold=0.81,
            margin=0.09,
        )
        calls = []
        configured = []

        def resolve(agent_root, *, defaults, tenant_based):
            calls.append((agent_root, defaults, tenant_based))
            return resolved

        agent = PandasAgent(name="route-bank-test", output_routing=True)
        agent.tenant_based = True
        monkeypatch.setattr("parrot.bots.data.resolve_route_banks", resolve)
        monkeypatch.setattr(agent, "configure_output_router", configured.append)

        await agent.configure()

        assert calls == [(AGENTS_DIR.joinpath(agent.agent_id), DEFAULT_OUTPUT_MODE_ROUTES, True)]
        assert configured == [
            IntentRouterConfig(
                enable_output_mode_routing=True,
                output_mode_routes=resolved.routes,
                tenant_output_mode_routes=resolved.tenant_routes,
                output_mode_threshold=0.81,
                discrepancy_margin=0.09,
            )
        ]

    async def test_configure_keeps_explicit_routing_config(self, monkeypatch):
        self._stub_configure_dependencies(monkeypatch)
        explicit = IntentRouterConfig(
            enable_output_mode_routing=True,
            output_mode_routes={"structured_table": ["show a table"]},
        )
        configured = []
        agent = PandasAgent(name="explicit-route-config-test", output_routing_config=explicit)
        monkeypatch.setattr(
            "parrot.bots.data.resolve_route_banks",
            lambda *args, **kwargs: pytest.fail("explicit config must skip route-bank resolution"),
        )
        monkeypatch.setattr(agent, "configure_output_router", configured.append)

        await agent.configure()

        assert configured == [explicit]


class _RecordingClient:
    """Async client double recording each ask() call's prompt and structured_output."""

    def __init__(self) -> None:
        self.calls: list = []

    async def __aenter__(self) -> "_RecordingClient":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def close(self) -> None:
        return None

    async def ask(self, prompt, system_prompt=None, structured_output=None, **kwargs):
        from parrot.models.basic import CompletionUsage
        from parrot.models.responses import AIMessage

        self.calls.append({"system_prompt": system_prompt or "", "structured_output": structured_output})
        return AIMessage(
            input=prompt,
            output="prose answer",
            response="prose answer",
            model="fake",
            provider="fake",
            usage=CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        )


class TestAskWiring:
    """PandasAgent.ask() behaviour for component hints, through a stub client."""

    @staticmethod
    def _agent():
        from parrot.bots.data import PandasAgent

        agent = PandasAgent(name="a2ui-component-probe", llm="google:gemini-2.5-flash")
        client = _RecordingClient()
        agent._llm = client
        return agent, client

    async def _ask(self, agent, **kwargs):
        return await agent.ask("show total hours", use_conversation_history=False, **kwargs)

    @pytest.mark.asyncio
    async def test_explicit_component_injects_prompt_in_single_llm_call(self):
        """G1/G2: the hint adds the catalog addon to the one and only LLM call."""
        from parrot.outputs.a2ui.inline.prompt import build_component_prompt

        agent, client = self._agent()
        await self._ask(agent, a2ui_component="KPICard")

        assert len(client.calls) == 1
        assert build_component_prompt("KPICard") in client.calls[0]["system_prompt"]

    @pytest.mark.asyncio
    async def test_unregistered_component_degrades_without_raising(self):
        """G3: an unknown component never reaches the prompt builders or escapes ask()."""
        from parrot.outputs.a2ui.inline.prompt import build_component_prompt

        agent, client = self._agent()
        response = await self._ask(agent, a2ui_component="Bogus")

        assert response is not None
        assert len(client.calls) == 1
        assert "Bogus" not in client.calls[0]["system_prompt"]
        assert build_component_prompt("KPICard") not in client.calls[0]["system_prompt"]

    @pytest.mark.asyncio
    async def test_explicit_output_mode_wins_over_component_hint(self):
        """G2: an explicit output_mode is never overridden by a component hint."""
        from parrot.models.outputs import OutputMode
        from parrot.outputs.a2ui.inline.prompt import build_component_prompt

        agent, client = self._agent()
        await self._ask(agent, output_mode=OutputMode.TEXT, a2ui_component="KPICard")

        assert len(client.calls) == 1
        assert build_component_prompt("KPICard") not in client.calls[0]["system_prompt"]

    @pytest.mark.asyncio
    async def test_explicit_a2ui_mode_keeps_component_hint(self):
        """An explicit A2UI mode agrees with the hint, so the catalog addon is still injected."""
        from parrot.models.outputs import OutputMode
        from parrot.outputs.a2ui.inline.prompt import build_component_prompt

        agent, client = self._agent()
        await self._ask(agent, output_mode=OutputMode.A2UI, a2ui_component="KPICard")

        assert len(client.calls) == 1
        assert build_component_prompt("KPICard") in client.calls[0]["system_prompt"]

    @pytest.mark.asyncio
    async def test_non_string_component_degrades_without_raising(self):
        """G3: an unhashable hint must not escape ask()."""
        agent, client = self._agent()
        response = await self._ask(agent, a2ui_component=["KPICard"])

        assert response is not None
        assert len(client.calls) == 1
