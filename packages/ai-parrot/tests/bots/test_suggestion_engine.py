"""Tests for the suggestion engine (FEAT-752, TASK-4797)."""

import asyncio

import pytest

from parrot.bots.suggestions import SuggestionContext, SuggestionEngine, SuggestionProvider
from parrot.bots.suggestions import engine as engine_mod
from parrot.models import AIMessage, Suggestion
from parrot.models.basic import CompletionUsage
from parrot.models.outputs import OutputMode


class StaticProvider:
    """Provider returning a fixed list of chips."""

    def __init__(self, name, lane, chips):
        self.name, self.lane, self._chips = name, lane, chips

    async def suggest(self, ctx):
        return self._chips


class Boom:
    """Provider that always raises."""

    name, lane = "boom", "deterministic"

    async def suggest(self, ctx):
        raise RuntimeError("boom")


class Slow:
    """Provider that outlives any sensible timeout."""

    name, lane = "slow", "deterministic"

    async def suggest(self, ctx):
        await asyncio.sleep(1)
        return [Suggestion(label="never", prompt="never")]


class CostedLLM:
    """LLM-lane provider exposing ``last_cost``."""

    name, lane = "costed", "llm"
    last_cost = {"input_tokens": 3}

    async def suggest(self, ctx):
        return [Suggestion(label="L", prompt="l", source="llm")]


@pytest.fixture
def ctx():
    msg = AIMessage(input="q", output="a", model="fake", provider="fake", usage=CompletionUsage())
    return SuggestionContext(question="q", response=msg, output_mode=OutputMode.DEFAULT, bot=None)


async def test_engine_never_raises_and_records_status(ctx):
    eng = SuggestionEngine(timeout_s=0.05)
    eng.register(Boom())
    eng.register(StaticProvider("ok", "deterministic", [Suggestion(label="A", prompt="a")]))
    chips, meta = await eng.collect(ctx, lanes=frozenset({"skill", "deterministic"}))
    assert [c.label for c in chips] == ["A"]
    assert meta["providers"]["boom"]["status"] == "error"
    assert meta["providers"]["ok"]["status"] == "ok"
    assert meta["count"] == 1


async def test_engine_timeout_status(ctx):
    eng = SuggestionEngine(timeout_s=0.05)
    eng.register(Slow())
    eng.register(StaticProvider("ok", "deterministic", [Suggestion(label="A", prompt="a")]))
    chips, meta = await eng.collect(ctx, lanes=frozenset({"deterministic"}))
    assert meta["providers"]["slow"]["status"] == "timeout"
    assert [c.label for c in chips] == ["A"]


async def test_engine_lane_gating(ctx):
    eng = SuggestionEngine()
    eng.register(StaticProvider("s", "skill", [Suggestion(label="S", prompt="s")]))
    eng.register(StaticProvider("d", "deterministic", [Suggestion(label="D", prompt="d")]))
    eng.register(StaticProvider("l", "llm", [Suggestion(label="L", prompt="l")]))

    chips, meta = await eng.collect(ctx, lanes=frozenset({"skill"}))
    assert [c.label for c in chips] == ["S"]
    assert meta["providers"]["d"]["status"] == "skipped"
    assert meta["providers"]["l"]["status"] == "skipped"
    assert meta["enabled_lanes"] == ["skill"]

    chips, meta = await eng.collect(ctx, lanes=frozenset({"skill", "deterministic"}))
    assert [c.label for c in chips] == ["S", "D"]
    assert meta["providers"]["l"]["status"] == "skipped"


async def test_engine_lane_order_is_fixed_regardless_of_registration(ctx):
    eng = SuggestionEngine()
    eng.register(StaticProvider("l", "llm", [Suggestion(label="L", prompt="l")]))
    eng.register(StaticProvider("s", "skill", [Suggestion(label="S", prompt="s")]))
    eng.register(StaticProvider("d", "deterministic", [Suggestion(label="D", prompt="d")]))
    chips, _ = await eng.collect(ctx, lanes=frozenset({"skill", "deterministic", "llm"}))
    assert [c.label for c in chips] == ["S", "D", "L"]


async def test_engine_dedupe_cap_and_renderer_check(ctx, monkeypatch):
    real_get_renderer = engine_mod.get_renderer

    def fake_get_renderer(mode):
        if mode == OutputMode.CARD:
            raise ValueError("no renderer")
        return real_get_renderer(mode)

    monkeypatch.setattr(engine_mod, "get_renderer", fake_get_renderer)

    eng = SuggestionEngine(max_suggestions=3, max_llm_suggestions=2)
    eng.register(
        StaticProvider(
            "det",
            "deterministic",
            [
                Suggestion(label="Table", prompt="t", output_mode=OutputMode.TABLE),
                Suggestion(label="table", prompt="dup of Table"),
                Suggestion(label="Card", prompt="c", output_mode=OutputMode.CARD),
            ],
        )
    )
    eng.register(
        StaticProvider(
            "llm",
            "llm",
            [Suggestion(label=f"Q{i}", prompt=f"q{i}", source="llm") for i in range(4)],
        )
    )
    chips, meta = await eng.collect(ctx, lanes=frozenset({"deterministic", "llm"}))
    labels = [c.label for c in chips]
    assert "Card" not in labels  # unregistered renderer dropped
    assert labels.count("Table") + labels.count("table") == 1  # case-insensitive dedupe, first wins
    assert labels[0] == "Table"
    assert len(chips) == 3  # total cap
    assert sum(1 for c in chips if c.source == "llm") <= 2  # llm cap
    assert meta["count"] == 3


async def test_llm_cost_is_copied_from_ok_llm_provider(ctx):
    eng = SuggestionEngine()
    eng.register(CostedLLM())
    _, meta = await eng.collect(ctx, lanes=frozenset({"llm"}))
    assert meta["llm"] == {"input_tokens": 3}


async def test_provider_defined_outside_package_registers_and_runs(ctx):
    class Extension:
        name = "ext"
        lane = "deterministic"

        async def suggest(self, ctx):
            return [Suggestion(label="Ext", prompt="ext", source="provider")]

    provider = Extension()
    assert isinstance(provider, SuggestionProvider)
    eng = SuggestionEngine()
    eng.register(provider)
    chips, _ = await eng.collect(ctx, lanes=frozenset({"deterministic"}))
    assert [c.label for c in chips] == ["Ext"]


def test_register_replaces_duplicate_name():
    eng = SuggestionEngine()
    first = StaticProvider("same", "deterministic", [])
    second = StaticProvider("same", "deterministic", [])
    other = StaticProvider("other", "deterministic", [])
    eng.register(first)
    eng.register(other)
    eng.register(second)
    assert [p.name for p in eng.providers] == ["other", "same"]
    assert eng.providers[1] is second


def test_register_prepend_goes_first_within_lane():
    eng = SuggestionEngine()
    eng.register(StaticProvider("a", "deterministic", []))
    eng.register(StaticProvider("b", "deterministic", []), prepend=True)
    assert [p.name for p in eng.providers] == ["b", "a"]


async def test_concurrent_collect_reports_independent_timings(ctx):
    eng = SuggestionEngine(timeout_s=0.5)
    eng.register(StaticProvider("ok", "deterministic", [Suggestion(label="A", prompt="a")]))
    results = await asyncio.gather(*(eng.collect(ctx, lanes=frozenset({"deterministic"})) for _ in range(5)))
    for chips, meta in results:
        assert [c.label for c in chips] == ["A"]
        assert meta["providers"]["ok"]["elapsed_ms"] >= 0.0


async def test_engine_total_timeout_bounds_stacked_providers(ctx):
    """Slow providers must not stack: collect() is bounded by the total deadline."""

    class Sleepy:
        lane = "deterministic"

        def __init__(self, name):
            self.name = name

        async def suggest(self, ctx):
            await asyncio.sleep(0.15)
            return []

    eng = SuggestionEngine(timeout_s=0.2, total_timeout_s=0.25)
    for n in ("a", "b", "c"):
        eng.register(Sleepy(n))
    loop = asyncio.get_running_loop()
    started = loop.time()
    _, meta = await eng.collect(ctx, lanes=frozenset({"deterministic"}))
    assert loop.time() - started < 0.45
    assert meta["providers"]["c"]["status"] == "timeout"
