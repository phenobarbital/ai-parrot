"""``InfographicToolkit`` → A2UI adapter wiring (FEAT-273 Module 11).

Verifies that ``emit_a2ui=True`` now produces envelopes carrying REAL catalog
components (KPICard/Chart/DataTable…) rather than heading-only sections, and
that the A2UI lane stays additive: a build failure degrades to an HTML-only
result instead of breaking the render.

The toolkit is a heavy module (namespace packages + Cython) that resolves
inconsistently under the worktree pytest layout, so the import is deferred and
skipped the same way ``test_toolkits_a2ui_migration.py`` does.
"""

import importlib

import pytest
from parrot.models.infographic import InfographicResponse


def _toolkit_or_skip():
    try:
        module = importlib.import_module("parrot.tools.infographic_toolkit")
    except Exception as exc:  # noqa: BLE001 - Cython/namespace worktree limitation
        pytest.skip(f"cannot import parrot.tools.infographic_toolkit: {exc}")
    return module.InfographicToolkit


@pytest.fixture
def toolkit():
    """A toolkit instance built without running __init__ (no ArtifactStore needed).

    ``_build_a2ui_envelope`` only touches ``self.logger``, so bypassing the
    constructor keeps this a focused unit test of the wiring.
    """
    import logging

    cls = _toolkit_or_skip()
    instance = cls.__new__(cls)
    instance.logger = logging.getLogger("test.infographic_toolkit")
    return instance


def _response() -> InfographicResponse:
    return InfographicResponse(
        template="quarterly",
        theme="ocean",
        blocks=[
            {"type": "title", "title": "Q1 Overview", "subtitle": "Financials"},
            {"type": "summary", "content": "Revenue grew."},
            {"type": "hero_card", "label": "Revenue", "value": "$1.2M"},
            {
                "type": "chart",
                "chart_type": "bar",
                "labels": ["Jan"],
                "series": [{"name": "2026", "values": [10]}],
            },
            {
                "type": "table",
                "columns": ["Region", "Total"],
                "rows": [["North", 10]],
            },
        ],
    )


def _surface(envelope: dict) -> dict:
    """Unwrap the A2UI v1.0 envelope-by-key and return the inner surface.

    ``_build_a2ui_envelope*`` returns the wire envelope
    (``{"version": "v1.0", "createSurface": {...}}``, camelCase aliases) — the
    same shape ``AIMessage.a2ui_envelope`` carries and
    ``Artifact.from_a2ui_envelope`` accepts — not a bare ``model_dump()``.
    """
    assert set(envelope) == {"version", "createSurface"}
    assert envelope["version"] == "v1.0"
    return envelope["createSurface"]


def _infographic(envelope: dict) -> dict:
    """Return the root ``Infographic`` component's dict — A2UI v1.0 (FEAT-470):
    catalog props live top-level on the ``Component``, not nested under a
    legacy ``"properties"`` key (that shape survives only for the adapter's
    OWN nested ``sections[].components[]`` descriptors, which are not wire
    ``Component`` objects).
    """
    components = _surface(envelope)["components"]
    assert len(components) == 1
    assert components[0]["component"] == "Infographic"
    return components[0]


class TestEnvelopeCarriesRealComponents:
    def test_blocks_become_catalog_components(self, toolkit):
        envelope = toolkit._build_a2ui_envelope(_response(), "art-1")
        assert envelope is not None
        section = _infographic(envelope)["sections"][0]
        assert [c["component"] for c in section["components"]] == [
            "KPICard",
            "Chart",
            "DataTable",
        ]

    def test_surface_carries_title_subtitle_and_theme(self, toolkit):
        props = _infographic(toolkit._build_a2ui_envelope(_response(), "art-1"))
        assert props["title"] == "Q1 Overview"
        assert props["subtitle"] == "Financials"
        assert props["theme"] == "ocean"

    def test_surface_id_derives_from_the_artifact_id(self, toolkit):
        envelope = toolkit._build_a2ui_envelope(_response(), "infographic-art-42")
        # The artifact id IS the surface id — it already carries the prefix, so
        # re-prefixing would yield "infographic-infographic-art-42".
        assert _surface(envelope)["surfaceId"] == "infographic-art-42"

    def test_chart_and_table_rows_reach_the_data_model(self, toolkit):
        envelope = toolkit._build_a2ui_envelope(_response(), "art-1")
        data_model = _surface(envelope)["dataModel"]
        assert data_model["charts"]["chart-0"] == [{"label": "Jan", "2026": 10}]
        assert data_model["tables"]["table-0"] == [{"Region": "North", "Total": 10}]

    def test_explicit_title_overrides_the_response(self, toolkit):
        envelope = toolkit._build_a2ui_envelope(_response(), "art-1", title="Custom")
        assert _infographic(envelope)["title"] == "Custom"

    def test_no_longer_dumps_raw_blocks_into_the_data_model(self, toolkit):
        # The pre-adapter implementation shipped data_model={"blocks": [...]}
        # with heading-only sections and zero components.
        envelope = toolkit._build_a2ui_envelope(_response(), "art-1")
        assert "blocks" not in (_surface(envelope).get("dataModel") or {})


class TestEnvelopeIsTheV1Wire:
    """The carried envelope must be the wire, not a bare ``model_dump()``.

    It previously shipped snake_case field names and no ``version`` wrapper, so
    ``Artifact.from_a2ui_envelope`` rejected it outright and any agent putting an
    infographic surface on A2A was broken.
    """

    def test_envelope_is_wrapped_by_key_with_a_version(self, toolkit):
        envelope = toolkit._build_a2ui_envelope(_response(), "infographic-art-1")
        assert set(envelope) == {"version", "createSurface"}
        assert envelope["version"] == "v1.0"

    def test_envelope_uses_camelcase_wire_aliases(self, toolkit):
        surface = _surface(toolkit._build_a2ui_envelope(_response(), "infographic-art-1"))
        assert "surfaceId" in surface and "surface_id" not in surface
        assert "catalogId" in surface and "catalog_id" not in surface
        assert "dataModel" in surface and "data_model" not in surface

    def test_envelope_is_accepted_over_a2a(self, toolkit):
        from parrot.a2a.models import Artifact

        envelope = toolkit._build_a2ui_envelope(_response(), "infographic-art-1")
        artifact = Artifact.from_a2ui_envelope(envelope)
        assert artifact.parts[0].data == envelope

    def test_data_splice_lane_is_the_wire_too(self, toolkit):
        envelope = toolkit._build_a2ui_envelope_from_layout(
            None, {"a": 1}, "infographic-art-2", title="T", template_name="dash"
        )
        assert set(envelope) == {"version", "createSurface"}
        assert _surface(envelope)["surfaceId"] == "infographic-art-2"


class TestSurfaceIdIsNotDoubled:
    """The artifact id already carries its ``infographic-`` prefix.

    ``f"infographic-{artifact_id}"`` produced ``infographic-infographic-<hex>``
    for every real render (ids are minted as ``f"infographic-{uuid4().hex[:12]}"``).
    """

    def test_real_artifact_id_is_used_verbatim(self, toolkit):
        artifact_id = "infographic-8a6354dbb959"
        surface = _surface(toolkit._build_a2ui_envelope(_response(), artifact_id))
        assert surface["surfaceId"] == artifact_id
        assert not surface["surfaceId"].startswith("infographic-infographic-")


class TestFailureIsAdditive:
    def test_build_failure_degrades_to_none(self, toolkit, caplog):
        # A block type the catalog cannot express as a known component would
        # normally raise; feeding a non-response object exercises the same
        # degradation path deterministically.
        envelope = toolkit._build_a2ui_envelope(object(), "art-1")
        assert envelope is None
        assert "falling back to HTML-only result" in caplog.text


class TestSurfaceMatchesTheRenderedResponse:
    def test_same_response_object_feeds_both_lanes(self, toolkit):
        # Guards the regression the wiring fixes: the envelope must be built
        # from the InfographicResponse the HTML renderer consumed, so the two
        # surfaces never diverge. Whitespace-tolerant so reformatting is safe.
        import inspect
        import re

        cls = _toolkit_or_skip()
        source = inspect.getsource(cls.render)
        assert re.search(
            r"_build_a2ui_envelope\(\s*infographic_response\b", source
        ), "render() must pass the InfographicResponse to _build_a2ui_envelope"


class TestDataSpliceLane:
    """``render_data_template`` used to hardcode ``a2ui_envelope=None``."""

    def _descriptor(self, layout=None):
        # LayoutSpec lives in recipes.models — infographic_sections only
        # forward-references it (circular-import workaround, FEAT-420).
        from parrot.outputs.a2ui.recipes.models import LayoutSpec
        from parrot.tools.infographic_sections import SectionDescriptor

        return SectionDescriptor(
            template="dash",
            mode="data-splice",
            layout=LayoutSpec(**layout) if layout else None,
        )

    def test_declared_layout_is_used_verbatim_against_the_payload(self, toolkit):
        # The spliced payload IS the data model, so the layout's binding
        # pointers resolve against it — the same contract RecipeRunner
        # honours. v2 (FEAT-470 TASK-2542): the OUTER layout's own props are
        # top-level; the nested Infographic section-component descriptor
        # (DataTable below) keeps its OWN "properties" wrapper — that is the
        # composite's own authored-descriptor shape, not the wire Component
        # shape the outer layout mirrors.
        descriptor = self._descriptor(
            {
                "component": "Infographic",
                "title": "Budget Variance",
                "sections": [
                    {
                        "heading": "Detail",
                        "components": [
                            {
                                "component": "DataTable",
                                "properties": {
                                    "columns": [{"name": "region"}],
                                    "data": {"path": "/rows"},
                                },
                            }
                        ],
                    }
                ],
            }
        )
        envelope = toolkit._build_a2ui_envelope_from_layout(
            descriptor, {"rows": [{"region": "North"}]}, "infographic-art-5", template_name="dash"
        )
        props = _infographic(envelope)
        assert props["title"] == "Budget Variance"
        table = props["sections"][0]["components"][0]
        assert table["properties"]["data"] == {"path": "/rows"}
        assert _surface(envelope)["dataModel"] == {"rows": [{"region": "North"}]}
        assert _surface(envelope)["surfaceId"] == "infographic-art-5"

    def test_non_infographic_layout_dispatches_to_build_surface(self, toolkit):
        descriptor = self._descriptor(
            {
                "component": "DataTable",
                "columns": [{"name": "region"}],
                "data": {"path": "/rows"},
            }
        )
        envelope = toolkit._build_a2ui_envelope_from_layout(
            descriptor, {"rows": [{"region": "N"}]}, "art-6", template_name="dash"
        )
        assert _surface(envelope)["components"][0]["component"] == "DataTable"
        assert _surface(envelope)["dataModel"] == {"rows": [{"region": "N"}]}

    def test_without_a_layout_it_falls_back_to_the_html_document_surface(self, toolkit):
        # FEAT-527: the layout-less fallback wraps the rendered HTML as an
        # opaque HtmlDocument surface — no more synthetic Infographic blocks.
        envelope = toolkit._build_a2ui_envelope_from_layout(
            None,
            {"beta": 1, "alpha": 2},
            "art-7",
            title="Dash",
            template_name="dash",
            html="<html><body>dash</body></html>",
            html_url="https://signed/art-7.html",
        )
        component = _surface(envelope)["components"][0]
        assert component["component"] == "HtmlDocument"
        assert component["title"] == "Dash"
        assert component["html"] == "<html><body>dash</body></html>"
        assert "srcUrl" not in component

    def test_descriptor_without_layout_uses_the_same_fallback(self, toolkit):
        envelope = toolkit._build_a2ui_envelope_from_layout(
            self._descriptor(),
            {"a": 1},
            "art-8",
            template_name="dash",
            html="<html/>",
            html_url="https://signed/art-8.html",
        )
        component = _surface(envelope)["components"][0]
        assert component["component"] == "HtmlDocument"
        assert component["title"] == "Infographic — dash"

    def test_empty_payload_yields_no_data_model(self, toolkit):
        envelope = toolkit._build_a2ui_envelope_from_layout(None, {}, "art-9", title="Empty", template_name="dash")
        assert not _surface(envelope).get("dataModel")

    def test_invalid_layout_degrades_to_none(self, toolkit, caplog):
        descriptor = self._descriptor({"component": "NotAnA2UIComponent"})
        assert toolkit._build_a2ui_envelope_from_layout(descriptor, {}, "art-10", template_name="dash") is None
        assert "falling back to HTML-only result" in caplog.text

    def test_lane_is_wired_and_respects_the_flag(self, toolkit):
        import inspect
        import re

        cls = _toolkit_or_skip()
        source = inspect.getsource(cls.render_data_template)
        assert re.search(r"if self\._emit_a2ui", source)
        assert re.search(
            r"_build_a2ui_envelope_from_layout\(", source
        ), "render_data_template must build the envelope from the descriptor layout"
        assert "a2ui_envelope=a2ui_envelope" in source


class TestTemplateLane:
    def test_template_lane_models_only_what_it_knows(self, toolkit):
        # The Jinja lane has no typed blocks; it must still emit a valid,
        # title-bearing surface rather than fabricated structure.
        envelope = toolkit._build_a2ui_envelope(
            InfographicResponse(
                template="report",
                blocks=[
                    {"type": "title", "title": "Report"},
                    {"type": "summary", "content": "Data: alpha, beta"},
                ],
            ),
            "art-9",
        )
        props = _infographic(envelope)
        assert props["title"] == "Report"
        assert props["sections"][0]["text"] == "Data: alpha, beta"


class TestProductionConstructorsEmitByDefault:
    """FEAT-527: the three production call sites build ``InfographicToolkit``
    without an explicit ``emit_a2ui=`` kwarg, so flipping the default to
    ``True`` must flip THEIR behaviour too, with zero code changes at the
    call sites themselves (``bots/mixins/infographic_authoring.py:85-89``,
    ``handlers/infographic.py:535-538``, ``bots/flows/result_agent.py:142,171``).
    """

    def test_infographic_authoring_mixin_builds_an_emitting_toolkit(self):
        from unittest.mock import MagicMock

        from parrot.bots.mixins.infographic_authoring import InfographicAuthoringMixin

        class _StubBase:
            def __init__(self, *args, **kwargs):
                # Cooperative-mixin chain end: absorb tools=/other kwargs.
                pass

        class _StubAgent(InfographicAuthoringMixin, _StubBase):
            pass

        agent = _StubAgent(artifact_store=MagicMock())
        assert agent._infographic_toolkit is not None
        assert agent._infographic_toolkit._emit_a2ui is True

    def test_infographic_talk_get_render_toolkit_emits_by_default(self):
        import logging
        from unittest.mock import MagicMock

        from aiohttp import web

        from parrot.handlers.infographic import InfographicTalk

        app = web.Application()
        app["artifact_store"] = MagicMock()

        handler = InfographicTalk.__new__(InfographicTalk)
        handler.logger = logging.getLogger("test.infographic_talk_render_toolkit")
        handler._request = MagicMock(app=app)

        toolkit = handler._get_render_toolkit()
        assert toolkit._emit_a2ui is True

    def test_result_agent_toolkit_emits_by_default(self):
        from unittest.mock import MagicMock

        from parrot.bots.flows.result_agent import ResultAgent

        agent = ResultAgent.__new__(ResultAgent)
        agent._artifact_store = MagicMock()
        agent._toolkit = None

        tools = ResultAgent.agent_tools(agent)
        assert agent._toolkit._emit_a2ui is True
        assert tools == agent._toolkit.get_tools()
