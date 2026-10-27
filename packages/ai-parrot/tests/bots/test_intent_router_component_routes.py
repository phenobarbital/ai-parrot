"""Composite-route wiring in IntentRouterMixin (FEAT-755 TASK-4760)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from parrot.bots.mixins.intent_router import IntentRouterMixin
from parrot.models.outputs import OutputMode
from parrot.registry.capabilities.models import IntentRouterConfig
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
        assert await agent._llm_disambiguate_output_mode(
            "table", ["structured_chart", "structured_table"]
        ) == "structured_table"

        async def off_list(prompt):
            return '{"output_mode": "default"}'

        agent.invoke = off_list
        assert await agent._llm_disambiguate_output_mode("table", ["structured_table"]) is None

    async def test_ambiguous_off_list_answer_abstains_to_embedding_winner(self, fake_router):
        agent = _Agent()
        agent.configure_output_router(_config())
        agent._output_router.score = RouteScore(
            OutputMode.STRUCTURED_CHART, 0.9, 0.89, True, "structured_chart"
        )
        agent._output_router.scores = [("structured_chart", 0.9), ("structured_table", 0.89)]

        async def invoke(prompt):
            return '{"output_mode": "not-a-candidate"}'

        agent.invoke = invoke
        assert await agent._resolve_output_mode("render this", None) is OutputMode.STRUCTURED_CHART
