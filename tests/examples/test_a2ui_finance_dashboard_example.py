"""A2UI finance example — the dashboard module (WIDGETS, agent prompt, extract_envelope, ensure_definition_only)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from parrot.models.basic import CompletionUsage, ToolCall
from parrot.models.responses import AIMessage

from ._finance_envelope import real_finance_envelope

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "examples" / "a2ui_finance"))
import finance_dashboard  # noqa: E402


def _message(*tool_calls: ToolCall) -> AIMessage:
    return AIMessage(
        input="Build a dashboard",
        output="Dashboard built.",
        model="test-model",
        provider="test-provider",
        usage=CompletionUsage(),
        tool_calls=list(tool_calls),
    )


def test_widgets_cover_the_finance_columns() -> None:
    """Eight widgets: four KPIs, a bar, a pie, a line trend and a server-paged grid, over the two seeded slugs."""
    keys = [widget["key"] for widget in finance_dashboard.WIDGETS]
    assert keys == [
        "kpi_rev_actual",
        "kpi_rev_budget",
        "kpi_rev_variance",
        "kpi_ebitda_variance",
        "by_division",
        "by_project",
        "trend",
        "latest_rows",
    ]
    components = [widget["component"] for widget in finance_dashboard.WIDGETS]
    assert sum(c["component"] == "KPICard" for c in components) == 4
    assert [c["type"] for c in components if c["component"] == "Chart"] == ["bar", "pie", "line"]
    assert sum(c["component"] == "DataTable" for c in components) == 1
    slugs = {widget["slug"] for widget in finance_dashboard.WIDGETS}
    assert slugs == {finance_dashboard.LATEST_SLUG, finance_dashboard.SNAPSHOTS_SLUG}
    by_key = {widget["key"]: widget for widget in finance_dashboard.WIDGETS}
    assert by_key["trend"]["slug"] == finance_dashboard.SNAPSHOTS_SLUG
    assert by_key["trend"]["request"]["grouping"] == ["snapshot_date"]
    assert by_key["by_division"]["component"]["y"] == ["rev_actual", "rev_budget"]
    grid = by_key[finance_dashboard.GRID_KEY]
    assert grid["request"] == {"fields": finance_dashboard.COLUMNS, "ordering": ["division", "project"], "limit": 500}
    assert [c["name"] for c in grid["component"]["columns"]] == finance_dashboard.COLUMNS
    assert finance_dashboard.PROGRAM == "troc"


def test_prompt_asks_for_a_definition_only_build() -> None:
    """The agent is told to call the tool once with snapshot=false; the question repeats the widgets verbatim."""
    prompt = finance_dashboard.agent_prompt()
    assert "qs_build_linked_dashboard exactly once" in prompt
    assert "snapshot=false" in prompt
    assert finance_dashboard.TITLE in prompt
    assert "snapshot=false" in finance_dashboard.dashboard_question()
    assert finance_dashboard.LATEST_SLUG in finance_dashboard.dashboard_question()


def test_extract_envelope_requires_the_tool_call() -> None:
    envelope = real_finance_envelope()
    call = ToolCall(id="1", name="qs_build_linked_dashboard", arguments={}, result={"a2ui_envelope": envelope})
    assert finance_dashboard.extract_envelope(_message(call)) is envelope
    other = ToolCall(id="2", name="qs_execute_slug", arguments={}, result={"rows": []})
    with pytest.raises(RuntimeError, match="did not call"):
        finance_dashboard.extract_envelope(_message(other))
    empty = ToolCall(id="3", name="qs_build_linked_dashboard", arguments={}, result={"a2ui_envelope": {"x": 1}})
    with pytest.raises(RuntimeError):
        finance_dashboard.extract_envelope(_message(empty))


def test_ensure_definition_only_strips_a_baked_snapshot() -> None:
    """Even if the LLM passed snapshot=true, the served envelope carries no rows and no snapshot stamps."""
    baked = real_finance_envelope(snapshot=True)
    assert baked["dataModel"]["kpi_rev_actual"]["rows"], "precondition: the baked envelope has rows"
    served = finance_dashboard.ensure_definition_only(baked)
    sources = served["metadata"]["extensions"]["parrot_data_sources"]
    assert all(served["dataModel"][key] == {"rows": []} for key in sources)
    assert all(source["snapshot_at"] is None and source["snapshot_truncated"] is False for source in sources.values())


def test_default_envelope_is_definition_only() -> None:
    envelope = real_finance_envelope()
    sources = envelope["metadata"]["extensions"]["parrot_data_sources"]
    assert set(sources) == {widget["key"] for widget in finance_dashboard.WIDGETS}
    assert all(envelope["dataModel"][key] == {"rows": []} for key in sources)
    assert "snapshot_at" not in sources["trend"] or sources["trend"]["snapshot_at"] is None
