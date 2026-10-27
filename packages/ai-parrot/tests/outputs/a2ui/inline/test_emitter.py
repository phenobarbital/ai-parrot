"""Inline emitter outcomes and marker (FEAT-755 TASK-4765)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Optional

import pytest
from pydantic import BaseModel, Field

from parrot.models.outputs import OutputMode
from parrot.outputs.a2ui.inline.emitter import (
    PRESENTATION_EXTENSION,
    emit_inline_component,
    extract_component_config,
    presentation_extension,
)


@pytest.fixture
def kpi_response() -> SimpleNamespace:
    """Return an AIMessage-like response carrying a fenced KPICard config."""
    return SimpleNamespace(
        output=(
            '```json\n{"label": "Worked hours", "value": 1234.5, "unit": "h", '
            '"delta": 0.12, "trend": "up"}\n```'
        ),
        content=None,
        structured_output=None,
        response="",
        data=None,
        metadata={},
        a2ui_envelope=None,
        output_mode=None,
    )


def _response(**overrides: object) -> SimpleNamespace:
    """Build a minimal mutable response for degradation tests."""
    values: dict[str, object] = {
        "output": None,
        "content": None,
        "structured_output": None,
        "response": "",
        "metadata": {},
        "a2ui_envelope": None,
        "output_mode": "unchanged",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _assert_degraded(response: SimpleNamespace, reason: str) -> None:
    """Assert the invariant shared by every degraded outcome."""
    assert response.a2ui_envelope is None
    assert response.output_mode == "unchanged"
    assert response.metadata["a2ui_inline"]["status"] == "degraded"
    assert response.metadata["a2ui_inline"]["reason"] == reason


class TestExtraction:
    """Config extraction source-order tests."""

    def test_base_model_wins_and_uses_aliases_without_none(self) -> None:
        """Structured Pydantic output wins and retains its wire representation."""

        class KPIConfig(BaseModel):
            label: str
            higher_is_better: Optional[bool] = Field(None, alias="higherIsBetter")

        response = _response(
            structured_output=KPIConfig(label="Hours"),
            output='{"label": "wrong", "value": 1}',
        )

        assert extract_component_config(response) == {"label": "Hours"}

    def test_structured_dict_is_taken_as_is(self) -> None:
        """A structured dictionary is returned before any text fallback."""
        config = {"label": "Hours", "value": 12}
        response = _response(structured_output=config, output='{"label": "wrong"}')

        assert extract_component_config(response) is config

    @pytest.mark.parametrize(
        ("attribute", "text"),
        [
            ("output", '```json\n{"label": "Hours", "value": 12}\n```'),
            ("output", '```\n{"label": "Hours", "value": 12}\n```'),
            ("content", '{"label": "Hours", "value": 12}'),
        ],
    )
    def test_text_fallbacks(self, attribute: str, text: str) -> None:
        """Fenced and bare objects parse from output and content."""
        response = _response(**{attribute: text})

        assert extract_component_config(response) == {"label": "Hours", "value": 12}

    def test_nothing_parseable_returns_none(self) -> None:
        """Malformed and non-object values do not become configs."""
        response = _response(output="not json", content="[1, 2]")

        assert extract_component_config(response) is None


class TestEmitted:
    """Successful emission tests."""

    def test_kpicard_emits_and_stamps_surface_marker(self, kpi_response: SimpleNamespace) -> None:
        """A valid config becomes a finalized A2UI surface with the marker."""
        outcome = emit_inline_component(kpi_response, "KPICard", surface_id="inline-kpi")

        assert outcome.status == "emitted"
        assert outcome.surface_id == "inline-kpi"
        assert kpi_response.output_mode is OutputMode.A2UI
        assert kpi_response.response
        assert kpi_response.metadata["a2ui_inline"]["status"] == "emitted"
        marker = kpi_response.a2ui_envelope["createSurface"]["metadata"]["extensions"][PRESENTATION_EXTENSION]
        assert marker == presentation_extension("KPICard")
        assert marker == {
            "kind": "widget",
            "inline": True,
            "origin": "chat_turn",
            "component": "KPICard",
        }


class TestDegraded:
    """Never-raise and degradation-invariant tests."""

    def test_component_not_inline(self) -> None:
        """A component outside the v1 allowlist is rejected before parsing."""
        response = _response(output='{"data": {"path": "/rows"}}')

        outcome = emit_inline_component(response, "DataTable")

        assert outcome.reason == "component_not_inline"
        _assert_degraded(response, "component_not_inline")

    def test_config_unparseable(self) -> None:
        """A response without a config degrades cleanly."""
        response = _response(output="not json")

        outcome = emit_inline_component(response, "KPICard")

        assert outcome.reason == "config_unparseable"
        _assert_degraded(response, "config_unparseable")

    @pytest.mark.parametrize(
        ("component", "config", "reason"),
        [
            ("KPICard", {"label": "Hours"}, "kpicard_value_missing"),
            ("InfoCard", {"title": " "}, "infocard_title_missing"),
            ("Timeline", {"events": []}, "timeline_events_missing"),
            ("Graph", {"nodes": []}, "graph_nodes_missing"),
            (
                "Graph",
                {"nodes": [{"id": "a", "label": "A"}], "edges": [{"from": "a", "to": "missing"}]},
                "graph_edge_dangling",
            ),
        ],
    )
    def test_feasibility_reasons(self, component: str, config: dict[str, object], reason: str) -> None:
        """Each feasibility reason propagates without mutating output mode."""
        response = _response(structured_output=config)

        outcome = emit_inline_component(response, component)

        assert outcome.reason == reason
        _assert_degraded(response, reason)

    def test_catalog_validation_failed(self) -> None:
        """Schema-invalid but feasible config maps to catalog validation failure."""
        response = _response(
            structured_output={
                "label": "Hours",
                "value": 12,
                "action": {"name": "forbidden_for_llm"},
            }
        )

        outcome = emit_inline_component(response, "KPICard")

        assert outcome.reason == "catalog_validation_failed"
        _assert_degraded(response, "catalog_validation_failed")

    def test_unexpected_error_rolls_back_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An unexpected dependency error neither escapes nor leaves partial A2UI state."""

        def fail_finalize(response: SimpleNamespace) -> None:
            response.output_mode = OutputMode.A2UI
            raise RuntimeError("boom")

        monkeypatch.setattr("parrot.outputs.a2ui.inline.emitter.finalize_a2ui_response", fail_finalize)
        response = _response(structured_output={"label": "Hours", "value": 12})

        outcome = emit_inline_component(response, "KPICard")

        assert outcome.reason == "unexpected_error"
        _assert_degraded(response, "unexpected_error")

    def test_malformed_response_never_raises(self) -> None:
        """Even an immutable, attribute-less response returns a degraded outcome."""
        outcome = emit_inline_component(object(), "KPICard")

        assert outcome.status == "degraded"
        assert outcome.reason == "config_unparseable"
