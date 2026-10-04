"""FEAT-610 TASK-3848 — example dashboard module (extract_envelope, WIDGETS)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from parrot.models.basic import CompletionUsage, ToolCall
from parrot.models.responses import AIMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "examples" / "a2ui"))
import dashboard  # noqa: E402


def _message(*tool_calls: ToolCall) -> AIMessage:
    """Build an AI message with the supplied tool calls."""
    return AIMessage(
        input="Build a dashboard",
        output="Dashboard built.",
        model="test-model",
        provider="test-provider",
        usage=CompletionUsage(),
        tool_calls=list(tool_calls),
    )


def test_widgets_match_query_map() -> None:
    """The example declares two dashboard-owned sources and the eight verified widgets over them."""
    assert list(dashboard.SOURCES) == ["kpis", "geo"]
    assert [widget["key"] for widget in dashboard.WIDGETS] == [
        "kpi_total",
        "kpi_studio",
        "kpi_mat",
        "kpi_multi",
        "by_country",
        "by_licensee",
        "by_course",
        "graduates",
    ]
    components = [widget["component"] for widget in dashboard.WIDGETS]
    assert sum(component["component"] == "KPICard" for component in components) == 4
    assert sum(component["component"] == "Chart" for component in components) == 3
    assert sum(component["component"] == "DataTable" for component in components) == 1
    assert [component["value"] for component in components[:4]] == ["total", "studio", "mat", "multi_graduates"]
    assert all("people" in component["title"] for component in components[:4])
    assert "diplomas" in components[6]["title"]
    by_key = {widget["key"]: widget for widget in dashboard.WIDGETS}
    # Four KPIs, ONE query: every aggregate is a field of the shared `kpis` source.
    assert all(by_key[key]["source"] == "kpis" for key in ("kpi_total", "kpi_studio", "kpi_mat", "kpi_multi"))
    kpi_fields = dashboard.SOURCES["kpis"]["request"]["fields"]
    assert kpi_fields[0] == "count(*) as total"
    assert '@> \'[{"course": "Pilates Studio"}]\') as studio' in kpi_fields[1]
    assert '@> \'[{"course": "Pilates Mat"}]\') as mat' in kpi_fields[2]
    assert kpi_fields[3] == "count(*) FILTER (WHERE jsonb_array_length(graduation_details) > 1) AS multi_graduates"
    # Two charts, ONE grouped query: derived views aggregate the geo matrix client-side.
    assert dashboard.SOURCES["geo"]["request"] == {
        "fields": ["country", "licensee", "count(*) as graduates"],
        "grouping": ["country", "licensee"],
    }
    for key, column in (("by_country", "country"), ("by_licensee", "licensee")):
        assert by_key[key]["source"] == "geo"
        assert by_key[key]["transform"]["ops"][0] == {
            "op": "group_by",
            "by": [column],
            "aggregate": {"graduates": "sum"},
        }
    # The pie and the server-paged grid keep their own sources.
    assert by_key["by_course"]["slug"] == dashboard.BY_COURSE_SLUG
    assert by_key["graduates"]["request"] == {
        "fields": ["student_uid", "full_name", "country", "licensee", "is_requalified", "last_diploma_date"],
        "ordering": ["student_uid"],
        "limit": 500,
    }
    assert "sources" in dashboard.dashboard_question() and "widgets" in dashboard.dashboard_question()


def test_extract_envelope() -> None:
    """The dashboard helper returns the tool-produced linked envelope."""
    envelope = {"metadata": {"extensions": {"parrot_data_sources": {"kpi_total": {"slug": "polestar"}}}}}
    response = _message(
        ToolCall(id="call-1", name="qs_build_linked_dashboard", arguments={}, result={"a2ui_envelope": envelope})
    )

    assert dashboard.extract_envelope(response) == envelope


def test_extract_envelope_raises() -> None:
    """The helper rejects responses that omit the linked-dashboard tool call."""
    response = _message(ToolCall(id="call-1", name="qs_execute_slug", arguments={}, result={}))

    with pytest.raises(RuntimeError, match="did not call qs_build_linked_dashboard"):
        dashboard.extract_envelope(response)
