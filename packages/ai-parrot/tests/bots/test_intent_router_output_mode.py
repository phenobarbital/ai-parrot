"""IntentRouterMixin output-mode routing policy (FEAT-224, TASK-1488).

Exercises the evolved mixin directly (no heavy bot stack): configure-once,
abstain, clear-winner (no LLM), ambiguous (LLM consulted), super() chaining and
``ctx.intent_score``. Embedding-dependent tests skip gracefully when the e5
model cannot be loaded (offline).
"""
from __future__ import annotations

import pytest

from parrot.models.outputs import OutputMode
from parrot.registry.capabilities.models import IntentRouterConfig
from parrot.bots.mixins.intent_router import IntentRouterMixin


class _SuperSentinel:
    """Terminal of the cooperative MRO; records whether super() was reached."""

    def __init__(self, **kwargs):
        self.super_called = False
        super().__init__()

    async def _resolve_output_mode(self, query, ctx):
        self.super_called = True
        return None

    async def invoke(self, prompt):  # default stub LLM (overridden per test)
        return '{"output_mode": "structured_table"}'


class _Agent(IntentRouterMixin, _SuperSentinel):
    pass


class _Ctx:
    """Minimal RequestContext stand-in carrying the FEAT-224 attrs."""

    def __init__(self):
        self.output_mode = None
        self.intent_score = None


def _make_agent(threshold=0.85, margin=0.05) -> _Agent:
    a = _Agent()
    a.configure_output_router(
        IntentRouterConfig(
            enable_output_mode_routing=True,
            output_mode_threshold=threshold,
            discrepancy_margin=margin,
            output_mode_routes={
                "structured_chart": [
                    "create a pie chart",
                    "hazme una gráfica de pastel",
                    "show this as a chart",
                ],
                "structured_map": ["plot it on a map", "muéstralo en un mapa"],
                "structured_table": ["dame una tabla", "show it as a table"],
            },
        )
    )
    return a


@pytest.fixture(scope="module")
def agent() -> _Agent:
    try:
        return _make_agent()
    except Exception as exc:  # noqa: BLE001 — offline / model unavailable
        pytest.skip(f"e5 model unavailable: {exc}")


# ── Model-independent ──────────────────────────────────────────────────────────

def test_inactive_when_flag_off():
    a = _Agent()
    a.configure_output_router(IntentRouterConfig(enable_output_mode_routing=False))
    assert a._output_router is None


async def test_no_router_chains_super():
    a = _Agent()  # configure_output_router never called -> no router
    mode = await a._resolve_output_mode("create a pie chart", None)
    assert mode is None
    assert a.super_called is True


# ── Model-dependent ────────────────────────────────────────────────────────────

def test_configure_builds_router_once(agent):
    first = agent._output_router
    # Re-running route() must not rebuild the engine/encoder.
    enc1 = first._ensure_encoder()
    agent._output_router.route("create a pie chart")
    assert agent._output_router is first
    assert first._ensure_encoder() is enc1


async def test_clear_winner_no_llm(agent, monkeypatch):
    called = {"invoke": False}

    async def _no(*a, **k):
        called["invoke"] = True
        return ""

    monkeypatch.setattr(agent, "invoke", _no)
    mode = await agent._resolve_output_mode("create a pie chart of sales", None)
    assert mode == OutputMode.STRUCTURED_CHART
    assert called["invoke"] is False


async def test_sets_ctx_intent_score(agent):
    ctx = _Ctx()
    mode = await agent._resolve_output_mode("muéstrame las tiendas en un mapa", ctx)
    assert mode == OutputMode.STRUCTURED_MAP
    assert ctx.intent_score is not None and ctx.intent_score > 0.0


async def test_abstain_below_threshold_chains_super(agent):
    agent.super_called = False
    mode = await agent._resolve_output_mode(
        "¿cuál es la política de devoluciones de la tienda?", None
    )
    assert mode is None
    assert agent.super_called is True


async def test_ambiguous_consults_llm():
    # Force ambiguity with a large margin so the winner is never "clear".
    try:
        a = _make_agent(threshold=0.4, margin=1.0)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"e5 model unavailable: {exc}")

    calls = {"n": 0}

    async def _llm(prompt):
        calls["n"] += 1
        return '{"output_mode": "structured_table"}'

    a.invoke = _llm
    mode = await a._resolve_output_mode("create a pie chart", None)
    assert calls["n"] == 1  # consulted exactly once
    assert mode == OutputMode.STRUCTURED_TABLE  # LLM choice honored (if candidate)


async def test_tiebreak_abstains_without_invoke():
    try:
        a = _make_agent(threshold=0.4, margin=1.0)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"e5 model unavailable: {exc}")
    # No invoke attribute at all -> abstain to embedding winner, no crash.
    a.invoke = None
    mode = await a._resolve_output_mode("create a pie chart", None)
    assert mode is not None  # falls back to the embedding winner
