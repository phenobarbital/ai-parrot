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
    """The example declares the eight verified widget queries and display types."""
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
    assert [component["value"] for component in components[:4]] == ["total", "total", "total", "multi_graduates"]
    assert all("people" in component["title"] for component in components[:4])
    assert "diplomas" in components[6]["title"]
    by_key = {widget["key"]: widget for widget in dashboard.WIDGETS}
    assert by_key["kpi_total"]["request"] == {"fields": ["count(*) as total"]}
    assert by_key["kpi_studio"]["request"]["filter"] == {"graduation_details": {"@>": [{"course": "Pilates Studio"}]}}
    assert by_key["kpi_mat"]["request"]["filter"] == {"graduation_details": {"@>": [{"course": "Pilates Mat"}]}}
    assert by_key["kpi_multi"]["request"] == {
        "fields": ["count(*) FILTER (WHERE jsonb_array_length(graduation_details) > 1) AS multi_graduates"]
    }
    assert by_key["by_country"]["request"] == {
        "fields": ["country", "count(*) as graduates"],
        "grouping": ["country"],
    }
    assert by_key["by_licensee"]["request"] == {
        "fields": ["licensee", "count(*) as graduates"],
        "grouping": ["licensee"],
    }
    assert by_key["by_course"]["slug"] == dashboard.BY_COURSE_SLUG
    assert by_key["graduates"]["request"] == {
        "fields": ["student_uid", "full_name", "country", "licensee", "is_requalified", "last_diploma_date"],
        "ordering": ["student_uid"],
        "limit": 500,
    }


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
