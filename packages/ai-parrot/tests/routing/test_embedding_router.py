"""Unit tests for the EmbeddingIntentRouter engine (FEAT-224, TASK-1484).

The real multilingual-e5 model is downloaded on first use. When it cannot be
loaded (offline CI / no network), the model-dependent tests skip gracefully —
the model-independent behaviours (empty-routes abstain) still run.
"""
from __future__ import annotations

import pytest

from parrot.models.outputs import OutputMode
from parrot.registry.routing.embedding_router import (
    EmbeddingIntentRouter,
    RouteScore,
)


def _build_router() -> EmbeddingIntentRouter:
    # 0.85 is the calibrated separator for multilingual-e5-small (on-topic
    # ~0.92+, off-topic ~0.82-); 0.5 would accept everything (e5 cosines run high).
    r = EmbeddingIntentRouter(threshold=0.85, margin=0.05)
    r.add_route(
        OutputMode.STRUCTURED_CHART,
        ["hazme una gráfica de pastel", "create a pie chart", "show this as a chart"],
    )
    r.add_route(OutputMode.STRUCTURED_MAP, ["muéstralo en un mapa", "plot it on a map"])
    r.add_route(OutputMode.STRUCTURED_TABLE, ["dame una tabla", "show it as a table"])
    return r


@pytest.fixture(scope="module")
def router() -> EmbeddingIntentRouter:
    try:
        return _build_router()
    except Exception as exc:  # noqa: BLE001 — offline / model unavailable
        pytest.skip(f"e5 model unavailable: {exc}")


class TestEmbeddingIntentRouter:
    def test_pie_chart_es_en(self, router):
        assert (
            router.route("hazme un gráfico de pastel de ventas").mode
            == OutputMode.STRUCTURED_CHART
        )
        assert (
            router.route("create a pie chart of Q1 sales").mode
            == OutputMode.STRUCTURED_CHART
        )

    def test_map_route(self, router):
        assert (
            router.route("muéstrame las tiendas en un mapa").mode
            == OutputMode.STRUCTURED_MAP
        )

    def test_above_threshold_score(self, router):
        rs = router.route("create a pie chart of Q1 sales")
        assert rs.score >= router.threshold

    def test_abstains_off_topic(self, router):
        rs = router.route("¿cuál es la política de devoluciones de la tienda?")
        assert rs.mode is None
        assert isinstance(rs, RouteScore)

    def test_ambiguous_flag_populated(self, router):
        # A query that leans chart but is close to "show it as a table/chart"
        rs = router.route("show this")
        # Either abstains (below threshold) or, if accepted, runner_up is real.
        if rs.mode is not None:
            assert rs.runner_up != -1.0
            assert isinstance(rs.ambiguous, bool)

    def test_encoder_loaded_once(self, router):
        enc_first = router._ensure_encoder()
        router.route("create a pie chart")
        enc_second = router._ensure_encoder()
        assert enc_first is enc_second  # never reinstantiated

    def test_empty_routes_abstain(self):
        # Model-independent: no routes -> abstain without loading the encoder.
        rs = EmbeddingIntentRouter().route("anything at all")
        assert rs.mode is None
        assert rs == RouteScore(None, -1.0, -1.0, False)

    def test_add_route_empty_utterances_noop(self):
        r = EmbeddingIntentRouter()
        r.add_route(OutputMode.STRUCTURED_CHART, [])
        assert r.route("create a pie chart").mode is None
