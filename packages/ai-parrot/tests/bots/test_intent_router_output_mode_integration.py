"""End-to-end output-mode routing through ask()/conversation() (FEAT-224, TASK-1489).

The shared test harness heavily stubs the real bot stack (``parrot.bots.abstract``
/ ``.agent``), so driving the full real ``BaseBot.ask`` offline is impractical.
Instead we:

1. Exercise the routing contract end-to-end through a harness bot that replicates
   the EXACT call site added to ``BaseBot.ask`` / ``.conversation`` (FEAT-224),
   composed with the REAL ``IntentRouterMixin``.
2. Pin that harness to reality with source-fidelity assertions that the real
   ``bots/base.py`` and ``bots/data.py`` still contain the guarded call site — so
   the harness cannot silently drift from production.

Embedding-dependent assertions skip when the e5 model is unavailable (offline).
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from parrot.models.outputs import OutputMode
from parrot.registry.capabilities.models import IntentRouterConfig
from parrot.bots.mixins.intent_router import IntentRouterMixin

_SRC = Path(__file__).resolve().parents[2] / "src" / "parrot" / "bots"


class _Ctx:
    """RequestContext stand-in carrying the FEAT-224 attributes."""

    def __init__(self):
        self.output_mode = None
        self.intent_score = None


class _Resp:
    def __init__(self, question):
        self.input = question
        self.output_mode = OutputMode.DEFAULT


class _BaseHarness:
    """Replicates the FEAT-224 call site from BaseBot.ask / BaseBot.conversation."""

    async def _resolve_output_mode(self, query, ctx):  # MRO terminal no-op
        return None

    async def _drive(self, question, ctx, output_mode):
        # ── byte-for-byte mirror of the guarded call site in base.py ──
        if output_mode == OutputMode.DEFAULT:
            _resolved_mode = await self._resolve_output_mode(question, ctx)
            if _resolved_mode is not None:
                output_mode = _resolved_mode
                if ctx is not None:
                    ctx.output_mode = _resolved_mode
        resp = _Resp(question)
        resp.output_mode = output_mode
        return resp

    async def ask(self, question, ctx=None, output_mode=OutputMode.DEFAULT, **_):
        return await self._drive(question, ctx, output_mode)

    async def conversation(self, question, ctx=None, output_mode=OutputMode.DEFAULT, **_):
        return await self._drive(question, ctx, output_mode)


class _ChartAgent(IntentRouterMixin, _BaseHarness):
    pass


def _make_chart_agent() -> _ChartAgent:
    a = _ChartAgent()
    a.configure_output_router(
        IntentRouterConfig(
            enable_output_mode_routing=True,
            output_mode_threshold=0.85,
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
def chart_agent() -> _ChartAgent:
    try:
        return _make_chart_agent()
    except Exception as exc:  # noqa: BLE001 — offline / model unavailable
        pytest.skip(f"e5 model unavailable: {exc}")


# ── Source-fidelity: the harness must match the REAL production call sites ──────

def test_real_basebot_ask_has_call_site():
    src = (_SRC / "base.py").read_text(encoding="utf-8")
    assert "await self._resolve_output_mode(question, ctx)" in src
    assert "if output_mode == OutputMode.DEFAULT:" in src


def test_real_pandasagent_ask_has_call_site():
    src = (_SRC / "data.py").read_text(encoding="utf-8")
    assert "await self._resolve_output_mode(question, ctx)" in src


def test_abstractbot_declares_noop_hook():
    src = (_SRC / "abstract.py").read_text(encoding="utf-8")
    assert "async def _resolve_output_mode(" in src


# ── Precedence (model-independent): explicit mode is never overwritten ──────────

async def test_explicit_mode_not_overwritten():
    class _Raises(IntentRouterMixin, _BaseHarness):
        async def _resolve_output_mode(self, query, ctx):
            raise AssertionError("router must not run when caller set a mode")

    a = _Raises()
    ctx = _Ctx()
    resp = await a.ask("create a pie chart", ctx=ctx, output_mode=OutputMode.TABLE)
    assert resp.output_mode == OutputMode.TABLE
    assert ctx.output_mode is None  # never touched


# ── End-to-end (model-gated) ───────────────────────────────────────────────────

async def test_pie_chart_sets_structured_chart_via_ask(chart_agent):
    ctx = _Ctx()
    resp = await chart_agent.ask("create a pie chart of Q1 sales by region", ctx=ctx)
    assert ctx.output_mode == OutputMode.STRUCTURED_CHART
    assert resp.output_mode == OutputMode.STRUCTURED_CHART
    assert ctx.intent_score is not None


async def test_map_phrase_via_conversation(chart_agent):
    ctx = _Ctx()
    resp = await chart_agent.conversation("muéstralo en un mapa", ctx=ctx)
    assert ctx.output_mode == OutputMode.STRUCTURED_MAP
    assert resp.output_mode == OutputMode.STRUCTURED_MAP


async def test_below_threshold_leaves_default(chart_agent):
    ctx = _Ctx()
    resp = await chart_agent.ask(
        "¿cuál es la política de devoluciones de la tienda?", ctx=ctx
    )
    assert resp.output_mode == OutputMode.DEFAULT
    assert ctx.output_mode is None


async def test_encode_runs_off_event_loop(chart_agent, monkeypatch):
    # The mixin must dispatch the blocking route()/encode() via asyncio.to_thread.
    import parrot.bots.mixins.intent_router as mod

    used = {"to_thread": 0}
    real_to_thread = asyncio.to_thread

    async def _spy(func, /, *args, **kwargs):
        used["to_thread"] += 1
        return await real_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(mod.asyncio, "to_thread", _spy)
    await chart_agent.ask("create a pie chart of sales", ctx=_Ctx())
    assert used["to_thread"] >= 1
