"""Tests for the ``InfographicResponse`` → A2UI ``CreateSurface`` adapter.

Exercises the adapter against the REAL :class:`InfographicResponse` model (not
hand-rolled dicts) so a drift in either contract fails here, plus the purity,
sectioning and lossy-degradation rules the module documents.
"""

import json

import pytest

from parrot.models.infographic import InfographicResponse
from parrot.outputs.a2ui.adapters import (
    CHART_TYPE_MAP,
    infographic_response_to_envelope,
)
from parrot.outputs.a2ui.catalog import (
    ProducerOrigin,
    get_component,
    validate_envelope,
)
from parrot.outputs.a2ui.catalog import components as _all_components  # noqa: F401
from parrot.outputs.a2ui.models import Component


def _response(**overrides) -> InfographicResponse:
    payload = {
        "template": "quarterly",
        "theme": "ocean",
        "blocks": [
            {"type": "title", "title": "Q1 Overview", "subtitle": "Financials"},
            {"type": "summary", "content": "Revenue grew across every region."},
            {"type": "hero_card", "label": "Revenue", "value": "$1.2M",
             "trend": "up", "trend_value": "+8%"},
            {
                "type": "chart",
                "chart_type": "bar",
                "title": "Revenue by month",
                "labels": ["Jan", "Feb"],
                "series": [
                    {"name": "2026", "values": [10, 20]},
                    {"name": "2025", "values": [8, 15]},
                ],
            },
        ],
    }
    payload.update(overrides)
    return InfographicResponse(**payload)


def _infographic_props(envelope) -> dict:
    assert len(envelope.components) == 1
    component = envelope.components[0]
    assert component.component == "Infographic"
    return component.properties


def _sections(envelope) -> list:
    return _infographic_props(envelope)["sections"]


class TestSurfaceShape:
    def test_emits_a_single_validated_infographic_component(self):
        envelope = infographic_response_to_envelope(_response())
        props = _infographic_props(envelope)
        assert props["title"] == "Q1 Overview"
        assert props["subtitle"] == "Financials"
        assert props["theme"] == "ocean"
        # build_infographic validates; re-assert explicitly for the allowlist.
        validate_envelope(envelope, origin=ProducerOrigin.TOOL)

    def test_first_title_block_does_not_become_a_section(self):
        sections = _sections(infographic_response_to_envelope(_response()))
        assert all(s.get("heading") != "Q1 Overview" for s in sections)

    def test_title_falls_back_to_template_then_constant(self):
        no_title = InfographicResponse(
            template="quarterly", blocks=[{"type": "summary", "content": "x"}]
        )
        assert _infographic_props(
            infographic_response_to_envelope(no_title)
        )["title"] == "quarterly"

        bare = InfographicResponse(blocks=[{"type": "summary", "content": "x"}])
        assert _infographic_props(
            infographic_response_to_envelope(bare)
        )["title"] == "Infographic"

    def test_explicit_title_and_theme_override_the_response(self):
        envelope = infographic_response_to_envelope(
            _response(), title="Override", theme="petrol"
        )
        props = _infographic_props(envelope)
        assert props["title"] == "Override"
        assert props["theme"] == "petrol"

    def test_accepts_a_plain_mapping(self):
        envelope = infographic_response_to_envelope(
            {"blocks": [{"type": "hero_card", "label": "Users", "value": "42"}]}
        )
        assert _sections(envelope)[0]["components"][0]["component"] == "KPICard"

    def test_rejects_unsupported_input(self):
        with pytest.raises(TypeError):
            infographic_response_to_envelope(["not", "a", "response"])


class TestPurity:
    def test_same_input_yields_byte_identical_envelopes(self):
        first = infographic_response_to_envelope(_response())
        second = infographic_response_to_envelope(_response())
        assert json.dumps(first.model_dump(mode="json"), sort_keys=True) == json.dumps(
            second.model_dump(mode="json"), sort_keys=True
        )

    def test_adapter_does_not_mutate_the_source_response(self):
        response = _response()
        before = response.model_dump(mode="json")
        infographic_response_to_envelope(response)
        assert response.model_dump(mode="json") == before


class TestSectioning:
    def test_later_title_block_opens_a_section(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {"type": "title", "title": "Doc"},
                    {"type": "title", "title": "Part Two", "subtitle": "Detail"},
                    {"type": "hero_card", "label": "A", "value": "1"},
                ]
            )
        )
        section = _sections(envelope)[0]
        assert section["heading"] == "Part Two"
        assert section["text"] == "Detail"
        assert section["components"][0]["component"] == "KPICard"

    def test_divider_opens_an_anonymous_section(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {"type": "hero_card", "label": "A", "value": "1"},
                    {"type": "divider"},
                    {"type": "hero_card", "label": "B", "value": "2"},
                ]
            )
        )
        sections = _sections(envelope)
        assert len(sections) == 2
        assert "heading" not in sections[1]
        assert sections[1]["components"][0]["properties"]["label"] == "B"

    def test_leading_divider_emits_no_empty_section(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {"type": "divider"},
                    {"type": "hero_card", "label": "A", "value": "1"},
                ]
            )
        )
        assert len(_sections(envelope)) == 1

    def test_untitled_summary_fills_section_text_then_becomes_a_card(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {"type": "summary", "content": "First"},
                    {"type": "summary", "content": "Second"},
                ]
            )
        )
        section = _sections(envelope)[0]
        assert section["text"] == "First"
        card = section["components"][0]
        assert card["component"] == "Card"
        assert card["properties"]["body"] == "Second"

    def test_titled_summary_always_becomes_a_card(self):
        envelope = infographic_response_to_envelope(
            _response(blocks=[{"type": "summary", "title": "Notes", "content": "Body"}])
        )
        section = _sections(envelope)[0]
        assert "text" not in section
        assert section["components"][0]["properties"]["title"] == "Notes"


class TestChartMapping:
    def test_rows_land_in_the_data_model_and_are_bound_by_pointer(self):
        envelope = infographic_response_to_envelope(_response())
        chart = _sections(envelope)[0]["components"][-1]
        assert chart["component"] == "Chart"
        assert chart["properties"]["data"] == {"$bind": "/charts/chart-0"}
        assert chart["properties"]["x"] == "label"
        assert chart["properties"]["y"] == ["2026", "2025"]
        assert envelope.data_model["charts"]["chart-0"] == [
            {"label": "Jan", "2026": 10, "2025": 8},
            {"label": "Feb", "2026": 20, "2025": 15},
        ]

    @pytest.mark.parametrize(
        "source,expected",
        [("donut", "pie"), ("gauge", "bar"), ("radar", "line"), ("area", "area")],
    )
    def test_unsupported_chart_types_degrade_to_the_nearest_neighbour(
        self, source, expected
    ):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {
                        "type": "chart",
                        "chart_type": source,
                        "labels": ["a"],
                        "series": [{"name": "s", "values": [1]}],
                    }
                ]
            )
        )
        assert _sections(envelope)[0]["components"][0]["properties"]["type"] == expected

    def test_every_mapped_type_is_in_the_a2ui_chart_enum(self):
        allowed = set(
            get_component("Chart").definition.schema_["properties"]["type"]["enum"]
        )
        assert set(CHART_TYPE_MAP.values()) <= allowed

    def test_series_named_label_does_not_collide_with_the_x_column(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {
                        "type": "chart",
                        "chart_type": "bar",
                        "labels": ["Jan"],
                        "series": [{"name": "label", "values": [7]}],
                    }
                ]
            )
        )
        chart = _sections(envelope)[0]["components"][0]["properties"]
        assert chart["y"] == ["label (2)"]
        assert envelope.data_model["charts"]["chart-0"] == [
            {"label": "Jan", "label (2)": 7}
        ]

    def test_short_series_pad_with_none(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {
                        "type": "chart",
                        "chart_type": "line",
                        "labels": ["a", "b", "c"],
                        "series": [{"name": "s", "values": [1]}],
                    }
                ]
            )
        )
        rows = envelope.data_model["charts"]["chart-0"]
        assert [row["s"] for row in rows] == [1, None, None]

    def test_multiple_charts_get_distinct_data_model_keys(self):
        chart = {
            "type": "chart",
            "chart_type": "bar",
            "labels": ["a"],
            "series": [{"name": "s", "values": [1]}],
        }
        envelope = infographic_response_to_envelope(_response(blocks=[chart, chart]))
        assert sorted(envelope.data_model["charts"]) == ["chart-0", "chart-1"]


class TestTableMapping:
    def test_columns_and_rows_map_with_total_rows(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {
                        "type": "table",
                        "title": "Regions",
                        "columns": ["Region", "Total"],
                        "rows": [["North", 10], ["South", 20]],
                    }
                ]
            )
        )
        table = _sections(envelope)[0]["components"][0]
        assert table["component"] == "DataTable"
        props = table["properties"]
        assert props["columns"] == [
            {"name": "Region", "title": "Region"},
            {"name": "Total", "title": "Total"},
        ]
        assert props["totalRows"] == 2
        assert props["data"] == {"$bind": "/tables/table-0"}
        assert envelope.data_model["tables"]["table-0"] == [
            {"Region": "North", "Total": 10},
            {"Region": "South", "Total": 20},
        ]

    def test_columndef_objects_use_their_header(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {
                        "type": "table",
                        "columns": [{"header": "Region"}, {"header": "Total"}],
                        "rows": [["North", 1]],
                    }
                ]
            )
        )
        props = _sections(envelope)[0]["components"][0]["properties"]
        assert [c["name"] for c in props["columns"]] == ["Region", "Total"]

    def test_ragged_rows_pad_with_none(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {
                        "type": "table",
                        "columns": ["A", "B", "C"],
                        "rows": [["only-a"]],
                    }
                ]
            )
        )
        assert envelope.data_model["tables"]["table-0"] == [
            {"A": "only-a", "B": None, "C": None}
        ]


class TestBlockMappings:
    def test_hero_card_carries_trend_and_delta(self):
        envelope = infographic_response_to_envelope(_response())
        kpi = _sections(envelope)[0]["components"][0]
        assert kpi["component"] == "KPICard"
        assert kpi["properties"] == {
            "label": "Revenue",
            "value": "$1.2M",
            "delta": "+8%",
            "trend": "up",
        }

    def test_timeline_maps_date_to_timestamp(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {
                        "type": "timeline",
                        "title": "Roadmap",
                        "events": [
                            {"date": "2026-01", "title": "Kickoff", "description": "Go"}
                        ],
                    }
                ]
            )
        )
        props = _sections(envelope)[0]["components"][0]["properties"]
        assert props["events"] == [
            {"timestamp": "2026-01", "title": "Kickoff", "description": "Go"}
        ]

    def test_progress_expands_to_one_kpicard_per_item(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {
                        "type": "progress",
                        "items": [
                            {"label": "Onboarding", "value": 80},
                            {"label": "Migration", "value": 45},
                        ],
                    }
                ]
            )
        )
        components = _sections(envelope)[0]["components"]
        assert [c["component"] for c in components] == ["KPICard", "KPICard"]
        assert components[0]["properties"]["label"] == "Onboarding"

    def test_bullet_list_ordered_and_unordered_bodies(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {"type": "bullet_list", "items": ["one", "two"]},
                    {"type": "bullet_list", "items": ["one"], "ordered": True},
                ]
            )
        )
        components = _sections(envelope)[0]["components"]
        assert components[0]["properties"]["body"] == "• one\n• two"
        assert components[1]["properties"]["body"] == "1. one"

    def test_checklist_marks_checked_items(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {
                        "type": "checklist",
                        "items": [
                            {"text": "Done", "checked": True},
                            {"text": "Pending"},
                        ],
                    }
                ]
            )
        )
        body = _sections(envelope)[0]["components"][0]["properties"]["body"]
        assert body == "[x] Done\n[ ] Pending"

    def test_callout_level_becomes_a_badge(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[{"type": "callout", "level": "warning", "content": "Careful"}]
            )
        )
        props = _sections(envelope)[0]["components"][0]["properties"]
        assert props["badge"] == "warning"
        assert props["body"] == "Careful"

    def test_quote_attribution_lands_in_the_footer(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {"type": "quote", "text": "Ship it", "author": "Ana",
                     "source": "Retro"}
                ]
            )
        )
        props = _sections(envelope)[0]["components"][0]["properties"]
        assert props["body"] == "Ship it"
        assert props["footer"] == "Ana — Retro"
        assert "title" not in props

    def test_image_maps_url_alt_and_caption(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {
                        "type": "image",
                        "url": "https://example.test/a.png",
                        "alt": "Chart",
                        "caption": "Fig 1",
                    }
                ]
            )
        )
        props = _sections(envelope)[0]["components"][0]["properties"]
        assert props == {
            "title": "Chart",
            "image": "https://example.test/a.png",
            "footer": "Fig 1",
        }


class TestContainerFlattening:
    def test_accordion_items_become_sibling_sections(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {
                        "type": "accordion",
                        "title": "Phases",
                        "items": [
                            {
                                "title": "Phase 1",
                                "content_blocks": [
                                    {"type": "hero_card", "label": "A", "value": "1"}
                                ],
                            },
                            {
                                "title": "Phase 2",
                                "content_blocks": [
                                    {"type": "summary", "content": "Later"}
                                ],
                            },
                        ],
                    }
                ]
            )
        )
        sections = _sections(envelope)
        assert [s["heading"] for s in sections] == ["Phases — Phase 1", "Phase 2"]
        assert sections[0]["components"][0]["component"] == "KPICard"
        assert sections[1]["text"] == "Later"

    def test_tab_panes_become_sibling_sections(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {
                        "type": "tab_view",
                        "tabs": [
                            {
                                "id": "a",
                                "label": "Overview",
                                "blocks": [
                                    {"type": "hero_card", "label": "A", "value": "1"}
                                ],
                            },
                            {"id": "b", "label": "Detail", "blocks": []},
                        ],
                    }
                ]
            )
        )
        sections = _sections(envelope)
        assert [s["heading"] for s in sections] == ["Overview", "Detail"]

    def test_nested_title_block_inside_a_pane_does_not_hijack_the_surface_title(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {"type": "title", "title": "Real Title"},
                    {
                        "type": "tab_view",
                        "tabs": [
                            {
                                "id": "a",
                                "label": "Tab",
                                "blocks": [{"type": "title", "title": "Nested"}],
                            },
                            {"id": "b", "label": "Other", "blocks": []},
                        ],
                    },
                ]
            )
        )
        assert _infographic_props(envelope)["title"] == "Real Title"


class TestLowering:
    def test_adapted_envelope_lowers_to_a_basic_tree(self):
        envelope = infographic_response_to_envelope(_response())
        component = envelope.components[0]
        tree = get_component("Infographic").component_cls().lower(
            Component(
                id=component.id,
                component=component.component,
                properties=component.properties,
            ),
            envelope.data_model or {},
        )
        assert tree.component == "Card"
        # Lowering is pure: the nested KPICard/Chart children resolved through
        # their own registered lower() without raising.
        assert tree.children
