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


class TestNewBlockConverters:
    """Tests for the explicit chain/steps/code/card_grid converters (FEAT-301 / TASK-2257)."""

    def test_a2ui_chain_to_card(self):
        envelope = infographic_response_to_envelope(
            _response(blocks=[
                {"type": "chain", "title": "Flow",
                 "nodes": [{"label": "A"}, {"label": "B"}]},
            ])
        )
        props = _sections(envelope)[0]["components"][0]["properties"]
        assert props["body"] == "A → B"
        assert props["title"] == "Flow"

    def test_a2ui_chain_vertical_direction_in_subtitle(self):
        envelope = infographic_response_to_envelope(
            _response(blocks=[
                {"type": "chain", "nodes": [{"label": "A"}], "direction": "vertical"},
            ])
        )
        props = _sections(envelope)[0]["components"][0]["properties"]
        assert props["subtitle"] == "vertical"

    def test_a2ui_chain_horizontal_omits_subtitle(self):
        envelope = infographic_response_to_envelope(
            _response(blocks=[{"type": "chain", "nodes": [{"label": "A"}]}])
        )
        props = _sections(envelope)[0]["components"][0]["properties"]
        assert "subtitle" not in props

    def test_a2ui_steps_to_card(self):
        envelope = infographic_response_to_envelope(
            _response(blocks=[
                {"type": "steps",
                 "steps": [{"label": "One", "description": "do it"}]},
            ])
        )
        props = _sections(envelope)[0]["components"][0]["properties"]
        assert props["body"] == "1. One — do it"

    def test_a2ui_code_to_card(self):
        envelope = infographic_response_to_envelope(
            _response(blocks=[
                {"type": "code", "code": "print(1)", "language": "python"},
            ])
        )
        props = _sections(envelope)[0]["components"][0]["properties"]
        assert props["body"] == "print(1)"
        assert props["badge"] == "python"

    def test_a2ui_code_omits_badge_without_language(self):
        envelope = infographic_response_to_envelope(
            _response(blocks=[{"type": "code", "code": "x"}])
        )
        props = _sections(envelope)[0]["components"][0]["properties"]
        assert "badge" not in props

    def test_a2ui_card_grid_to_cards(self):
        envelope = infographic_response_to_envelope(
            _response(blocks=[
                {"type": "card_grid", "columns": 2, "cards": [
                    {"title": "C1", "body": "b1"}, {"title": "C2", "body": "b2"},
                ]},
            ])
        )
        components = _sections(envelope)[0]["components"]
        assert [c["properties"]["title"] for c in components] == ["C1", "C2"]
        assert [c["component"] for c in components] == ["Card", "Card"]

    def test_only_known_card_properties(self):
        envelope = infographic_response_to_envelope(
            _response(blocks=[
                {"type": "code", "code": "x", "language": "py",
                 "highlight_lines": [1]},
            ])
        )
        props = _sections(envelope)[0]["components"][0]["properties"]
        allowed = {"title", "subtitle", "body", "image", "badge", "footer"}
        assert set(props) <= allowed

    def test_i18n_title_flattened(self):
        envelope = infographic_response_to_envelope(
            _response(blocks=[
                {"type": "code", "code": "x",
                 "title": {"en": "Title", "es": "Titulo"}},
            ])
        )
        props = _sections(envelope)[0]["components"][0]["properties"]
        assert props["title"] == "Title"

    def test_deterministic(self):
        payload = _response(blocks=[
            {"type": "chain", "nodes": [{"label": "A"}]},
        ])
        a = infographic_response_to_envelope(payload)
        b = infographic_response_to_envelope(payload)
        assert a.model_dump() == b.model_dump()


class TestMalformedNestedItemsDegradeGracefully:
    """Malformed nested items (raw-dict input path) are skipped, not fatal.

    ``infographic_response_to_envelope`` also accepts a plain mapping (not
    just a validated ``InfographicResponse``), so a plausible LLM
    hallucination — a flat string where a mapping was expected inside
    ``steps``/``nodes``/``cards``/``events``/items/tabs — must degrade by
    skipping that entry rather than raising ``TypeError`` and aborting the
    whole envelope build (FEAT-301 / TASK-2257 code-review follow-up).
    """

    def test_steps_with_flat_string_items_does_not_raise(self):
        envelope = infographic_response_to_envelope({
            "blocks": [{"type": "steps", "steps": ["Do it", {"label": "Real"}]}],
        })
        props = _sections(envelope)[0]["components"][0]["properties"]
        assert props["body"] == "1. Real"

    def test_chain_with_malformed_node_does_not_raise(self):
        envelope = infographic_response_to_envelope({
            "blocks": [{"type": "chain", "nodes": ["oops", {"label": "A"}]}],
        })
        props = _sections(envelope)[0]["components"][0]["properties"]
        assert props["body"] == "A"

    def test_card_grid_with_malformed_card_does_not_raise(self):
        envelope = infographic_response_to_envelope({
            "blocks": [{"type": "card_grid", "cards": [42, {"title": "Real"}]}],
        })
        components = _sections(envelope)[0]["components"]
        assert [c["properties"].get("title") for c in components] == ["Real"]

    def test_timeline_with_malformed_event_does_not_raise(self):
        envelope = infographic_response_to_envelope({
            "blocks": [{"type": "timeline", "events": [
                "oops", {"date": "2026-01", "title": "Real"},
            ]}],
        })
        props = _sections(envelope)[0]["components"][0]["properties"]
        assert props["events"] == [{"timestamp": "2026-01", "title": "Real"}]

    def test_progress_with_malformed_item_does_not_raise(self):
        envelope = infographic_response_to_envelope({
            "blocks": [{"type": "progress", "items": [
                "oops", {"label": "Real", "value": 50},
            ]}],
        })
        components = _sections(envelope)[0]["components"]
        assert [c["properties"]["label"] for c in components] == ["Real"]

    def test_checklist_with_malformed_item_does_not_raise(self):
        envelope = infographic_response_to_envelope({
            "blocks": [{"type": "checklist", "items": [
                "oops", {"text": "Real", "checked": True},
            ]}],
        })
        body = _sections(envelope)[0]["components"][0]["properties"]["body"]
        assert body == "[x] Real"

    def test_malformed_top_level_block_is_skipped(self):
        envelope = infographic_response_to_envelope({
            "blocks": ["oops", {"type": "hero_card", "label": "Real", "value": "1"}],
        })
        components = _sections(envelope)[0]["components"]
        assert [c["properties"]["label"] for c in components] == ["Real"]

    def test_accordion_with_malformed_item_does_not_raise(self):
        envelope = infographic_response_to_envelope({
            "blocks": [{"type": "accordion", "items": [
                "oops", {"title": "Real", "content_blocks": []},
            ]}],
        })
        assert _sections(envelope)[0]["heading"] == "Real"

    def test_tab_view_with_malformed_pane_does_not_raise(self):
        envelope = infographic_response_to_envelope({
            "blocks": [{"type": "tab_view", "tabs": [
                "oops", {"label": "Real", "blocks": []},
            ]}],
        })
        assert _sections(envelope)[0]["heading"] == "Real"

    def test_table_with_malformed_column_does_not_raise(self):
        envelope = infographic_response_to_envelope({
            "blocks": [{"type": "table", "columns": [42, "Real"], "rows": [[1, 2]]}],
        })
        table = _sections(envelope)[0]["components"][0]
        assert [c["name"] for c in table["properties"]["columns"]] == ["column", "Real"]


class TestAllBlocksEnvelope:
    """Full 19-block-type payload lowers without error (FEAT-301 / TASK-2257)."""

    def test_a2ui_envelope_new_blocks(self):
        envelope = infographic_response_to_envelope(
            _response(blocks=[
                {"type": "title", "title": "Test Infographic"},
                {"type": "hero_card", "label": "Metric", "value": "42"},
                {"type": "summary", "content": "Summary text"},
                {"type": "chart", "chart_type": "bar", "labels": ["A"],
                 "series": [{"name": "s", "values": [1]}]},
                {"type": "bullet_list", "items": ["item 1"]},
                {"type": "table", "columns": ["A"], "rows": [["1"]]},
                {"type": "image", "url": "data:image/png;base64,AA==", "alt": "img"},
                {"type": "quote", "text": "Quote", "author": "Author"},
                {"type": "callout", "level": "info", "content": "Info"},
                {"type": "divider"},
                {"type": "timeline", "events": [{"date": "2026-01-01", "title": "Event"}]},
                {"type": "progress", "items": [{"label": "Task", "value": "80"}]},
                {"type": "accordion", "items": [{"title": "Section", "content_blocks": []}]},
                {"type": "checklist", "items": [{"text": "Done", "checked": True}]},
                {"type": "tab_view", "tabs": [
                    {"id": "t1", "label": "Tab1", "blocks": []},
                    {"id": "t2", "label": "Tab2", "blocks": []},
                ]},
                {"type": "chain", "nodes": [{"label": "A"}, {"label": "B"}]},
                {"type": "steps", "steps": [{"label": "Step 1", "description": "Do thing"}]},
                {"type": "code", "code": "print('hello')", "language": "python"},
                {"type": "card_grid", "cards": [{"title": "Card 1", "body": "Content"}],
                 "columns": 2},
            ])
        )
        assert envelope is not None
        validate_envelope(envelope, origin=ProducerOrigin.TOOL)


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
