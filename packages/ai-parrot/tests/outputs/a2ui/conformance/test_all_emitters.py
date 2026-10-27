"""A2UI v1.0 wire conformance suite (TASK-2548, spec §4 ``test_conformance_all_emitters``).

Every envelope this codebase EMITS must validate against the vendored official
``agent_to_renderer.json`` JSON Schema (spec G1, AC-G1: "todo mensaje emitido
valida contra agent_to_renderer.json"). This module sweeps every EMISSION
POINT named in the spec's Module 10 responsibility ("builders/adapters/
renderers -> todo sobre valida contra schema"):

* the public deterministic builders (``builders.py``);
* the Infographic adapter (``adapters/infographic.py``);
* a representative LLM-producer-shaped fixture (the bare ``CreateSurface``
  payload shape ``producer.py``'s ``_extract_envelope`` accepts — a live LLM
  call is deliberately NOT exercised here, see ``test_producer.py`` /
  ``artifacts/logs/feat-470-producer-rate.md`` for the opt-in spike);
* a recipe ``LayoutSpec`` v2 (and a migrated v1 layout), lowered into a wire
  ``Component`` the same way ``build_surface``/``build_infographic`` wrap one;
* ``bake_envelope``'s flattened, binding-free output, rewrapped into an
  envelope; and
* the envelope FED to each of the 6 satellite renderers (``ssr_html``,
  ``pdf``, ``interactive_html``, ``echarts``, ``folium_map``,
  ``adaptive_cards``) — plus a smoke check that ``render()`` does not raise.

Renderer OUTPUT is a separate concern from renderer INPUT: ``EChartsRenderer``
and ``AdaptiveCardsRenderer`` are the two renderers that emit
``application/json`` (an ECharts *option* document and an Adaptive Card
document, respectively) — both are DERIVED artifacts in an external JSON
vocabulary, not A2UI envelopes, and structurally cannot (and must not)
validate against ``agent_to_renderer.json``. Those outputs are checked here
for being well-formed JSON only; the A2UI envelope each renderer actually
*consumes* is what gets validated against the wire schema, exactly like
every other emitter in this module.

**Two-layer conformance, matching how this codebase actually enforces it**
(confirmed against ``catalog/test_validation_v1.py``'s own
``test_validate_message_agent_to_renderer``, which validates a
``catalogId=BASIC_CATALOG_ID`` envelope — never a Parrot-catalog one): the
vendored, pinned ``agent_to_renderer.json``'s ``Component`` definition
resolves ``catalog.json#/$defs/anyComponent`` against ONLY the 18 official
Basic Catalog primitives (that is how the upstream schema is written — one
pinned catalog, not "any registered catalog"). A raw Parrot-catalog envelope
(``Chart``/``InfoCard``/... at top level) therefore cannot — and must not be
expected to — validate against it directly. So ``_assert_conformant`` checks:

1. :func:`~parrot.outputs.a2ui.catalog.validate_envelope` — the catalog-level
   structural check that DOES span both catalogs (root/unique-ids/dangling-
   children/allowed-parent-child/action-gate). Every emitted envelope must
   pass this, Basic or Parrot.
2. The envelope's LOWERED form (every non-primitive Parrot component run
   through its own ``lower()`` + :func:`~parrot.outputs.a2ui.catalog.base.to_components`
   — the exact Basic-only shape every satellite renderer produces internally
   before baking, spec G3) validated against ``agent_to_renderer.json`` via
   :func:`~parrot.outputs.a2ui.catalog.validate_message`. For an
   already-Basic-only envelope this is a no-op pass-through.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from parrot.models.infographic import InfographicResponse
from parrot.outputs.a2ui.adapters import infographic_response_to_envelope
from parrot.outputs.a2ui.adapters.flow import flow_definition_to_graph
from parrot.outputs.a2ui.baking import bake_envelope
from parrot.outputs.a2ui.builders import (
    build_card,
    build_chart,
    build_c4_diagram,
    build_datatable,
    build_graph,
    build_infographic,
    build_kpicard,
    build_linked_surface,
    build_mermaid_diagram,
    build_surface,
)
from parrot.outputs.a2ui.catalog import (
    ProducerOrigin,
    get_component,
    validate_envelope,
    validate_message,
)
from parrot.outputs.a2ui.catalog.base import CatalogValidationError, to_components
from parrot.outputs.a2ui.catalog.parrot.form import FormField, FormSubmit, build_form
from parrot.outputs.a2ui.catalog.viz_core import VIZ_CORE_CATALOG_ID
from parrot.outputs.a2ui.graph import GraphSpec, from_mermaid, graph_spec_from_mermaid_source, to_mermaid
from parrot.outputs.a2ui.inline.emitter import PRESENTATION_EXTENSION, emit_inline_component
from parrot.outputs.a2ui.models import A2UIAgentMessage, Component, CreateSurface
from parrot.outputs.a2ui.recipes import SUPPORTED_SCHEMA_VERSION
from parrot.outputs.a2ui.recipes.migrate import migrate_layout
from parrot.outputs.a2ui.recipes.models import LayoutSpec

from .._v1 import DEFAULT_CATALOG_ID

_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def _lower_to_basic_components(envelope: CreateSurface) -> list[Component]:
    """Lower every non-primitive (Parrot catalog) top-level component to Basic form.

    Mirrors the lowering pass every satellite renderer runs internally before
    baking (e.g. ``SSRHTMLRenderer._lower_composites``) — built entirely from
    the PUBLIC catalog API (``get_component``, ``to_components``), the same
    pattern ``tests/outputs/a2ui/test_components_*.py`` already exercises
    per-component.
    """
    lowered: list[Component] = []
    for comp in envelope.components:
        entry = get_component(comp.component)
        if entry.definition.is_primitive:
            lowered.append(comp)
        else:
            tree = entry.component_cls().lower(comp, envelope.data_model)
            lowered.extend(to_components(tree, id_prefix=f"{comp.id}-lc"))
    return lowered


def _assert_conformant(envelope: CreateSurface, *, origin: ProducerOrigin = ProducerOrigin.TOOL) -> None:
    """Assert ``envelope`` is A2UI v1.0 wire-conformant (spec G1/AC-G1).

    See the module docstring for the two-layer rationale. ``origin`` is
    forwarded to :func:`~parrot.outputs.a2ui.catalog.validate_envelope`
    (defaults to ``TOOL``, the permissive case — pass ``LLM`` explicitly to
    additionally assert the D10b action gate).
    """
    validate_envelope(envelope, origin=origin)
    lowered = _lower_to_basic_components(envelope)
    lowered_envelope = envelope.model_copy(update={"components": lowered})
    message = A2UIAgentMessage(version="v1.0", create_surface=lowered_envelope)
    validate_message(message)


# ---------------------------------------------------------------------------
# Builders (builders.py) — public, deterministic tool-facing constructors.
# ---------------------------------------------------------------------------


class TestBuildersConformance:
    """Every public builder's output validates against the wire schema."""

    def test_build_surface_generic(self):
        envelope = build_surface("Text", {"text": "hello"}, surface_id="s")
        _assert_conformant(envelope)

    def test_build_chart(self):
        envelope = build_chart(chart_type="bar", x="month", y=["revenue"], title="Revenue")
        _assert_conformant(envelope)

    def test_build_kpicard(self):
        envelope = build_kpicard(label="Revenue", value=42, unit="$", trend="up")
        _assert_conformant(envelope)

    def test_build_card_emits_infocard(self):
        envelope = build_card(title="Hello", subtitle="World", body="Body text")
        assert envelope.components[0].component == "InfoCard"
        _assert_conformant(envelope)

    def test_build_datatable(self):
        envelope = build_datatable(
            columns=[{"key": "name", "label": "Name"}],
            data_binding="/rows",
            title="Table",
        )
        _assert_conformant(envelope)

    def test_build_infographic(self):
        envelope = build_infographic(
            title="Q1 Overview",
            sections=[{"heading": "Summary", "text": "Revenue grew."}],
        )
        _assert_conformant(envelope)

    def test_build_graph(self):
        """FEAT-529: build_graph()'s output validates against the wire
        schema (lowered — GraphComponent.lower() is a Basic-only tree)."""
        envelope = build_graph(
            nodes=[{"id": "a", "label": "Start"}, {"id": "b", "label": "End"}],
            edges=[{"from": "a", "to": "b", "label": "go"}],
            accessible_description="Tiny graph",
        )
        assert envelope.components[0].catalog_id == VIZ_CORE_CATALOG_ID
        _assert_conformant(envelope)

    @pytest.mark.parametrize("origin", [ProducerOrigin.TOOL, ProducerOrigin.LLM])
    def test_build_mermaid_diagram(self, origin):
        """FEAT-753: build_mermaid_diagram()'s output validates for both origins (lowered Basic-only tree)."""
        env = build_mermaid_diagram(source="sequenceDiagram\n    A->>B: hi\n", origin=origin)
        _assert_conformant(env, origin=origin)


# ---------------------------------------------------------------------------
# Adapter (adapters/infographic.py)
# ---------------------------------------------------------------------------


class TestAdapterConformance:
    """``infographic_response_to_envelope`` output validates against the wire schema."""

    def test_infographic_adapter_conformant(self):
        response = InfographicResponse(
            template="quarterly",
            theme="ocean",
            blocks=[
                {"type": "title", "title": "Q1 Overview", "subtitle": "Financials"},
                {"type": "summary", "content": "Revenue grew across every region."},
                {
                    "type": "chart",
                    "chart_type": "bar",
                    "title": "Revenue by month",
                    "labels": ["Jan", "Feb"],
                    "series": [{"name": "2026", "values": [10, 20]}],
                },
                {"type": "checklist", "items": [{"text": "Done", "checked": True}]},
            ],
        )
        envelope = infographic_response_to_envelope(response)
        _assert_conformant(envelope)


# ---------------------------------------------------------------------------
# Producer-shaped fixture (producer.py) — no live LLM call (see module docstring).
# ---------------------------------------------------------------------------


class TestProducerFixtureConformance:
    """A representative LLM-producer output validates as both catalog- and schema-valid.

    Mirrors the BARE ``CreateSurface`` payload shape
    :func:`parrot.outputs.a2ui.producer._extract_envelope` accepts directly
    (no wire envelope wrapper) — the realistic shape a client's
    ``structured_output=StructuredOutputConfig(output_type=CreateSurface)``
    machinery returns. A live LLM call (the first-shot-rate spike, spec §4
    ``test_e2e_llm_producer_first_shot_rate``) is a separate, credential-gated
    concern handled by TASK-2547 — not re-exercised here.
    """

    def test_bare_producer_payload_is_catalog_and_schema_valid(self):
        payload = {
            "surfaceId": "main",
            "catalogId": DEFAULT_CATALOG_ID,
            "components": [
                {"id": "root", "component": "Column", "children": ["title", "chart"]},
                {"id": "title", "component": "Text", "text": "Quarterly Revenue", "variant": "body"},
                {
                    "id": "chart",
                    "component": "Chart",
                    "type": "bar",
                    "x": "month",
                    "y": ["revenue"],
                    "data": {"path": "/rows"},
                },
            ],
            "dataModel": {"rows": [{"month": "Jan", "revenue": 10}]},
        }
        envelope = CreateSurface.model_validate(payload)
        # Display-only LLM output must pass the LLM-origin catalog gate (D10b)
        # AND the (lowered) wire schema (spec G1).
        _assert_conformant(envelope, origin=ProducerOrigin.LLM)


# ---------------------------------------------------------------------------
# Recipes (recipes/models.py LayoutSpec v2 + recipes/migrate.py)
# ---------------------------------------------------------------------------


class TestRecipesConformance:
    """A recipe ``LayoutSpec`` (v2, and migrated from v1) lowers to a conformant envelope."""

    def _layout_to_component(self, layout: LayoutSpec, *, component_id: str = "root") -> Component:
        """Wrap a ``LayoutSpec`` into a wire ``Component`` (same shape, spec TASK-2542).

        ``LayoutSpec`` mirrors the wire ``Component`` shape exactly (top-level
        props, ``child``/``children``, ``metadata``) — this is the same
        reverse transform :func:`parrot.tools.infographic_recipes.freeze
        <freeze the wire component into a LayoutSpec>` performs, applied
        forward.
        """
        return Component(
            id=component_id,
            component=layout.component,
            child=layout.child,
            children=layout.children,
            metadata=layout.metadata,
            **layout.props,
        )

    def test_layout_spec_v2_conformant(self):
        layout = LayoutSpec(component="InfoCard", title="Hello", subtitle="World")
        component = self._layout_to_component(layout)
        envelope = CreateSurface(
            surfaceId="recipe",
            catalogId=DEFAULT_CATALOG_ID,
            components=[component],
        )
        _assert_conformant(envelope)

    def test_migrated_v1_layout_conformant(self):
        assert SUPPORTED_SCHEMA_VERSION == 2
        v1_layout = {
            "component": "Card",
            "properties": {
                "title": {"$bind": "/title"},
                "subtitle": {"$bind": "/subtitle", "optional": True},
            },
        }
        v2_layout = migrate_layout(v1_layout, from_version=1)
        assert v2_layout["component"] == "InfoCard"
        layout = LayoutSpec(**v2_layout)
        component = self._layout_to_component(layout)
        envelope = CreateSurface(
            surfaceId="recipe",
            catalogId=DEFAULT_CATALOG_ID,
            components=[component],
            dataModel={"title": "Hello", "subtitle": "World"},
        )
        _assert_conformant(envelope)


# ---------------------------------------------------------------------------
# bake_envelope output (baking.py) — rewrapped, binding-free envelope.
# ---------------------------------------------------------------------------


class TestBakeOutputConformance:
    """``bake_envelope``'s flattened, binding-resolved output re-validates as an envelope."""

    def test_baked_envelope_still_conformant(self):
        pytest.importorskip("jsonpointer")
        envelope = CreateSurface(
            surfaceId="main",
            catalogId=DEFAULT_CATALOG_ID,
            components=[
                Component(id="root", component="Column", children={"componentId": "row", "path": "/items"}),
                Component(
                    id="row",
                    component="Text",
                    text={"call": "formatString", "args": {"value": "#${@index}: ${name}"}},
                ),
            ],
            dataModel={"items": [{"name": "A"}, {"name": "B"}]},
        )
        baked = bake_envelope(envelope)
        rebuilt = CreateSurface(
            surfaceId=envelope.surface_id,
            catalogId=envelope.catalog_id,
            components=[Component.model_validate(entry) for entry in baked],
            dataModel=envelope.data_model,
        )
        _assert_conformant(rebuilt)


# ---------------------------------------------------------------------------
# Renderers (ai-parrot-visualizations satellite) — envelope IN, artifact OUT.
# ---------------------------------------------------------------------------


def _basic_display_envelope() -> CreateSurface:
    return build_card(title="Hello", subtitle="World", body="Body")


def _chart_envelope() -> CreateSurface:
    return build_chart(chart_type="bar", x="month", y=["revenue"], title="Revenue")


def _map_envelope() -> CreateSurface:
    return build_surface("Map", {"layers": [{"name": "base"}]}, surface_id="map")


def _form_envelope() -> CreateSurface:
    components = build_form(
        id_prefix="root",
        title="Signup",
        fields=[FormField(name="email", label="Email", input="text", required=True)],
        submit=FormSubmit(label="Send", action="signup"),
    )
    envelope = CreateSurface(
        surfaceId="form",
        catalogId=DEFAULT_CATALOG_ID,
        components=components,
        # The "required" check binds /root/email — a static renderer bakes
        # (resolves) every binding, including check conditions, so the field
        # must actually be present in the data model.
        dataModel={"root": {"email": "jane@example.com"}},
    )
    validate_envelope(envelope, origin=ProducerOrigin.TOOL)
    return envelope


class TestRendererConformance:
    """Every satellite renderer's INPUT envelope validates; ``render()`` never raises."""

    @pytest.mark.asyncio
    async def test_ssr_html_input_conformant_and_renders(self):
        from parrot.outputs.a2ui_renderers.ssr_html import SSRHTMLRenderer

        envelope = _basic_display_envelope()
        _assert_conformant(envelope)
        artifact = await SSRHTMLRenderer().render(envelope)
        assert artifact.content is not None

    @pytest.mark.asyncio
    async def test_pdf_input_conformant_and_renders(self):
        pytest.importorskip("weasyprint")
        from parrot.outputs.a2ui_renderers.pdf import PDFRenderer

        envelope = _basic_display_envelope()
        _assert_conformant(envelope)
        artifact = await PDFRenderer().render(envelope)
        assert artifact.mime_type == "application/pdf"

    @pytest.mark.asyncio
    async def test_interactive_html_input_conformant_and_renders(self):
        from parrot.outputs.a2ui_renderers.interactive_html import (
            InteractiveHTMLRenderer,
        )

        envelope = _basic_display_envelope()
        _assert_conformant(envelope)
        artifact = await InteractiveHTMLRenderer().render(envelope)
        assert artifact.mime_type == "text/html"

    @pytest.mark.asyncio
    async def test_echarts_input_conformant_and_output_is_well_formed_json(self):
        from parrot.outputs.a2ui_renderers.echarts import EChartsRenderer

        envelope = _chart_envelope()
        _assert_conformant(envelope)
        artifact = await EChartsRenderer().render(envelope)
        assert artifact.mime_type == "application/json"
        # The ECharts *option* document is a derived artifact in ECharts' own
        # vocabulary, not an A2UI envelope — only structural JSON well-formedness
        # applies here (see module docstring).
        option = json.loads(artifact.content)
        assert "series" in option

    @pytest.mark.asyncio
    async def test_folium_map_input_conformant_and_renders(self):
        pytest.importorskip("folium")
        from parrot.outputs.a2ui_renderers.folium_map import FoliumMapRenderer

        envelope = _map_envelope()
        _assert_conformant(envelope)
        artifact = await FoliumMapRenderer().render(envelope)
        assert artifact.mime_type == "text/html"

    @pytest.mark.asyncio
    async def test_adaptive_cards_input_conformant_and_output_is_well_formed_json(self):
        from parrot.outputs.a2ui_renderers.adaptive_cards import AdaptiveCardsRenderer

        envelope = _form_envelope()
        # This envelope is TOOL-origin only (it carries Button.action) — it is
        # still validated against the wire schema, just not the LLM-origin gate.
        _assert_conformant(envelope)
        artifact = await AdaptiveCardsRenderer().render(envelope)
        # The Adaptive Card document is a derived artifact in Microsoft's own
        # vocabulary, not an A2UI envelope (see module docstring).
        card = json.loads(artifact.content)
        assert card.get("type") == "AdaptiveCard" or "body" in card


# ---------------------------------------------------------------------------
# FEAT-529: viz-core Graph — cross-cutting acceptance (Module 8, TASK-2891).
# ---------------------------------------------------------------------------


def _graph_envelope() -> CreateSurface:
    return build_graph(
        nodes=[{"id": "a", "label": "Start"}, {"id": "b", "label": "End"}],
        edges=[{"from": "a", "to": "b", "label": "go"}],
        accessible_description="Tiny graph",
    )


class TestFlowToGraphToMermaidRoundtrip:
    """The dev-loop FlowDefinition fixture -> Graph -> mermaid -> Graph
    round-trips (modulo accessibleDescription/size, per the codec's own
    contract), and the adapter's own build_graph() output is conformant."""

    def test_flow_to_graph_to_mermaid_roundtrip(self):
        definition = json.loads((_FIXTURES_DIR / "dev_loop_flow.json").read_text())
        spec = flow_definition_to_graph(definition)

        envelope = build_graph(
            nodes=spec.nodes,
            edges=spec.edges,
            accessible_description=spec.accessible_description,
        )
        _assert_conformant(envelope)

        mermaid_text = to_mermaid(spec)
        roundtripped = from_mermaid(mermaid_text)

        def _normalize(graph_spec):
            dumped = graph_spec.model_dump(by_alias=True, exclude={"accessible_description", "size"})
            # The mermaid codec never collapses an edge's `kind` back to
            # `None` (an edge operator is always unambiguously explicit in
            # text) — normalize the two equivalent representations before
            # comparing (documented in graph/mermaid.py's module docstring;
            # flow_definition_to_graph legitimately leaves `kind=None` on
            # every non-on_error/on_timeout edge).
            for edge in dumped.get("edges", []):
                if edge.get("kind") is None:
                    edge["kind"] = "solid"
            return dumped

        assert _normalize(roundtripped) == _normalize(spec)


class TestGraphRendersOnEveryRegisteredRenderer:
    """A viz-core Graph envelope renders (natively, or via exactly one
    recorded, readable degradation) on every registered satellite renderer."""

    @pytest.mark.asyncio
    async def test_graph_renders_on_every_registered_renderer(self):
        from parrot.outputs.a2ui_renderers.adaptive_cards import AdaptiveCardsRenderer
        from parrot.outputs.a2ui_renderers.echarts import EChartsRenderer
        from parrot.outputs.a2ui_renderers.interactive_html import InteractiveHTMLRenderer
        from parrot.outputs.a2ui_renderers.ssr_html import SSRHTMLRenderer

        envelope = _graph_envelope()
        _assert_conformant(envelope)

        for renderer in (SSRHTMLRenderer(), InteractiveHTMLRenderer(), EChartsRenderer()):
            artifact = await renderer.render(envelope)
            assert not artifact.metadata.get("degraded"), type(renderer).__name__

        try:
            import weasyprint  # noqa: F401
        except ImportError:
            pass
        else:
            from parrot.outputs.a2ui_renderers.pdf import PDFRenderer

            pdf_artifact = await PDFRenderer().render(envelope)
            assert not pdf_artifact.metadata.get("degraded")

        ac_artifact = await AdaptiveCardsRenderer().render(envelope)
        ac_degraded = ac_artifact.metadata.get("degraded") or []
        assert len(ac_degraded) == 1
        assert VIZ_CORE_CATALOG_ID in ac_degraded[0]["reason"]

        try:
            import folium  # noqa: F401
        except ImportError:
            pass
        else:
            from parrot.outputs.a2ui_renderers.folium_map import FoliumMapRenderer

            map_and_graph = build_surface(
                "Map",
                {"layers": [{"layer": "base"}]},
                surface_id="map",
            )
            graph_component = envelope.components[0].model_copy(update={"id": "graph"})
            combined = map_and_graph.model_copy(update={"components": [*map_and_graph.components, graph_component]})
            map_artifact = await FoliumMapRenderer().render(combined)
            map_degraded = map_artifact.metadata.get("degraded") or []
            graph_records = [record for record in map_degraded if record["component"] == "Graph"]
            assert len(graph_records) == 1
            assert VIZ_CORE_CATALOG_ID in graph_records[0]["reason"]


_MERMAID_SRC = 'flowchart TD\n    a["a < b & c"] --> b\n'


def _card_texts(node) -> list[str]:
    """Every ``text`` string in an Adaptive Card document (raw, not JSON-escaped)."""
    found: list[str] = []
    if isinstance(node, dict):
        if isinstance(node.get("text"), str):
            found.append(node["text"])
        for value in node.values():
            found.extend(_card_texts(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_card_texts(value))
    return found


def _mermaid_envelope() -> CreateSurface:
    return build_mermaid_diagram(source=_MERMAID_SRC, accessible_description="a to b")


class TestGraphToMermaidDiagramRoundtrip:
    """FEAT-753 AC-5: Graph -> to_mermaid -> MermaidDiagram -> graph_spec_from_mermaid_source round-trips."""

    @staticmethod
    def _normalize(graph_spec):
        dumped = graph_spec.model_dump(by_alias=True, exclude={"accessible_description", "size"})
        for edge in dumped.get("edges", []):
            if edge.get("kind") is None:
                edge["kind"] = "solid"
        if dumped.get("kind") == "dag":
            dumped["kind"] = "flowchart"
        return dumped

    def _specs(self):
        from parrot.outputs.a2ui.graph import GraphSpec

        flow = flow_definition_to_graph(json.loads((_FIXTURES_DIR / "dev_loop_flow.json").read_text()))
        flowchart = GraphSpec.model_validate(
            {
                "kind": "flowchart",
                "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                "edges": [{"from": "a", "to": "b", "label": "go"}],
            }
        )
        state = from_mermaid("stateDiagram-v2\n[*] --> idle\nidle --> done\n")
        sequence = from_mermaid(
            "sequenceDiagram\n    participant A as Alice\n    participant B as Bob\n    A->>B: hello\n"
        )
        return [flow, flowchart, state, sequence]

    def test_graph_to_mermaid_diagram_roundtrip(self):
        for spec in self._specs():
            text = to_mermaid(spec)
            envelope = build_mermaid_diagram(source=text)
            _assert_conformant(envelope)
            assert envelope.components[0].model_extra["diagramType"] in {"flowchart", "state", "sequence"}
            back = graph_spec_from_mermaid_source(envelope.components[0].model_extra["source"])
            assert self._normalize(back) == self._normalize(spec)


class TestCatalogDefinitionIncludesMermaidDiagram:
    def test_catalog_definition_includes_mermaid_diagram(self):
        from parrot.outputs.a2ui.catalog.export import export_catalog_definition

        parrot_doc = export_catalog_definition()  # DEFAULT_CATALOG_ID
        assert "MermaidDiagram" in parrot_doc["components"]
        viz_core_doc = export_catalog_definition(catalog_id=VIZ_CORE_CATALOG_ID)
        assert "MermaidDiagram" not in viz_core_doc["components"]


class TestMermaidDiagramFallbackRenderers:
    """MermaidDiagram renders (readable source + exactly ONE degraded record) on every fallback renderer."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("renderer_name", ["ssr_html", "pdf", "adaptive_cards", "interactive_html"])
    async def test_mermaid_degrades_once_with_readable_source(self, renderer_name):
        if renderer_name == "pdf":
            pytest.importorskip("weasyprint")
            from parrot.outputs.a2ui_renderers.pdf import PDFRenderer as Renderer
        elif renderer_name == "ssr_html":
            from parrot.outputs.a2ui_renderers.ssr_html import SSRHTMLRenderer as Renderer
        elif renderer_name == "adaptive_cards":
            from parrot.outputs.a2ui_renderers.adaptive_cards import AdaptiveCardsRenderer as Renderer
        else:
            from parrot.outputs.a2ui_renderers.interactive_html import InteractiveHTMLRenderer as Renderer

        envelope = _mermaid_envelope()
        _assert_conformant(envelope)
        artifact = await Renderer().render(envelope)
        degraded = [d for d in (artifact.metadata.get("degraded") or []) if "mermaid" in d.get("reason", "").lower()]
        assert len(degraded) == 1, renderer_name
        if renderer_name == "pdf":
            assert artifact.mime_type == "application/pdf"
        elif renderer_name == "adaptive_cards":
            assert _MERMAID_SRC in _card_texts(json.loads(artifact.content))
        else:
            assert "a &lt; b &amp; c" in artifact.content.decode()


class TestMermaidDiagramFocalRendererCompatibility:
    """echarts / folium_map are focal-component renderers: a Mermaid-only envelope keeps their existing errors."""

    @pytest.mark.asyncio
    async def test_echarts_keeps_missing_focal_error(self):
        from parrot.outputs.a2ui_renderers.echarts import EChartsRenderer

        with pytest.raises(ValueError, match="requires a 'Chart' or viz-core 'Graph'"):
            await EChartsRenderer().render(_mermaid_envelope())

    @pytest.mark.asyncio
    async def test_folium_map_keeps_missing_focal_error(self):
        pytest.importorskip("folium")
        from parrot.outputs.a2ui_renderers.folium_map import FoliumMapRenderer

        with pytest.raises(ValueError, match="requires a 'Map' component"):
            await FoliumMapRenderer().render(_mermaid_envelope())


class TestCatalogDefinitionIncludesGraph:
    def test_catalog_definition_includes_graph(self):
        from parrot.outputs.a2ui.catalog.export import export_catalog_definition

        viz_core_doc = export_catalog_definition(catalog_id=VIZ_CORE_CATALOG_ID)
        assert "Graph" in viz_core_doc["components"]

        parrot_doc = export_catalog_definition()  # DEFAULT_CATALOG_ID
        assert "Graph" not in parrot_doc["components"]


def _c4_envelope() -> CreateSurface:
    """Build the C4 fixture through the public C4 diagram builder."""
    fixture = json.loads((_FIXTURES_DIR / "c4_container_diagram.json").read_text())
    return build_c4_diagram(
        level=fixture["level"],
        nodes=fixture["nodes"],
        edges=fixture["edges"],
        boundaries=fixture["groups"],
        title=fixture["title"],
        accessible_description=fixture["accessibleDescription"],
    )


class TestC4GraphConformance:
    """C4 graphs remain conformant across the existing renderer fleet."""

    def test_build_c4_diagram_conformant(self) -> None:
        _assert_conformant(_c4_envelope())

    def test_c4_mermaid_roundtrip_byte_stable(self) -> None:
        component = _c4_envelope().components[0]
        props = component.model_dump(
            by_alias=True,
            exclude={"id", "component", "catalog_id"},
            exclude_none=True,
        )
        spec = GraphSpec(**props)
        source = to_mermaid(spec)
        assert to_mermaid(from_mermaid(source)) == source

    @pytest.mark.asyncio
    async def test_c4_graph_renders_on_every_registered_renderer(self) -> None:
        from parrot.outputs.a2ui_renderers.adaptive_cards import AdaptiveCardsRenderer
        from parrot.outputs.a2ui_renderers.echarts import EChartsRenderer
        from parrot.outputs.a2ui_renderers.interactive_html import InteractiveHTMLRenderer
        from parrot.outputs.a2ui_renderers.ssr_html import SSRHTMLRenderer

        envelope = _c4_envelope()
        _assert_conformant(envelope)

        for renderer in (SSRHTMLRenderer(), InteractiveHTMLRenderer(), EChartsRenderer()):
            artifact = await renderer.render(envelope)
            assert not artifact.metadata.get("degraded"), type(renderer).__name__

        ac_artifact = await AdaptiveCardsRenderer().render(envelope)
        ac_degraded = ac_artifact.metadata.get("degraded") or []
        assert len(ac_degraded) == 1
        assert VIZ_CORE_CATALOG_ID in ac_degraded[0]["reason"]

        try:
            import folium  # noqa: F401
        except ImportError:
            return

        from parrot.outputs.a2ui_renderers.folium_map import FoliumMapRenderer

        map_and_graph = build_surface(
            "Map",
            {"layers": [{"layer": "base"}]},
            surface_id="map",
        )
        graph_component = envelope.components[0].model_copy(update={"id": "graph"})
        combined = map_and_graph.model_copy(update={"components": [*map_and_graph.components, graph_component]})
        map_artifact = await FoliumMapRenderer().render(combined)
        map_degraded = map_artifact.metadata.get("degraded") or []
        graph_records = [record for record in map_degraded if record["component"] == "Graph"]
        assert len(graph_records) == 1
        assert VIZ_CORE_CATALOG_ID in graph_records[0]["reason"]


class TestMixedCatalogSurfaceValidates:
    def test_mixed_catalog_surface_validates(self):
        from parrot.outputs.a2ui.catalog.basic import BASIC_CATALOG_ID

        graph_component = Component(
            id="graph",
            component="Graph",
            catalogId=VIZ_CORE_CATALOG_ID,
            nodes=[{"id": "a"}, {"id": "b"}],
            edges=[{"from": "a", "to": "b"}],
        )
        root = Component(id="root", component="Column", children=["graph"])
        surface = CreateSurface(
            surfaceId="s",
            catalogId=BASIC_CATALOG_ID,
            components=[root, graph_component],
        )
        validate_envelope(surface)  # must not raise — mixed-catalog shape

        graph_without_catalog_id = graph_component.model_copy(update={"catalog_id": None})
        bad_surface = surface.model_copy(update={"components": [root, graph_without_catalog_id]})
        with pytest.raises(CatalogValidationError) as exc:
            validate_envelope(bad_surface)
        assert "Graph" in exc.value.unknown_components


# ---------------------------------------------------------------------------
# FEAT-598 — linked surfaces (build_linked_surface, TOOL origin only).
# ---------------------------------------------------------------------------


def _linked_source(key: str, **extra):
    """A minimal LinkedDataSource whose conditions are derived from its request (S5)."""
    from parrot.outputs.a2ui.linked.conditions import derive_conditions
    from parrot.outputs.a2ui.linked.models import LinkedDataSource, SourceRequest

    request = SourceRequest(placeholders={"firstdate": "YESTERDAY", "lastdate": "TODAY"})
    return LinkedDataSource(
        slug="epson_field_activity",
        conditions=derive_conditions(request, locked={}),
        request=request,
        target=f"/{key}/rows",
        **extra,
    )


def _activity_frame():
    import pandas as pd

    return pd.DataFrame({"day": pd.date_range("2026-09-01", periods=3), "visits": [1, 2, 3], "program": ["a"] * 3})


class TestLinkedSurfaceConformance:
    """build_linked_surface output is wire-conformant for chart, table and a two-source join dashboard."""

    def test_build_linked_surface_conformant_chart(self):
        envelope = build_linked_surface(
            [
                {
                    "id": "root",
                    "component": "Chart",
                    "type": "bar",
                    "x": "day",
                    "y": ["visits"],
                    "data": {"path": "/activity/rows"},
                }
            ],
            {"activity": _linked_source("activity")},
            {"activity": _activity_frame()},
            surface_id="linked-chart",
        )
        _assert_conformant(envelope, origin=ProducerOrigin.TOOL)

    def test_build_linked_surface_conformant_table(self):
        envelope = build_linked_surface(
            [
                {
                    "id": "root",
                    "component": "DataTable",
                    "columns": [{"name": "day"}, {"name": "visits"}],
                    "data": {"path": "/activity/rows"},
                }
            ],
            {"activity": _linked_source("activity")},
            {"activity": _activity_frame()},
            surface_id="linked-table",
        )
        _assert_conformant(envelope, origin=ProducerOrigin.TOOL)

    def test_build_linked_surface_conformant_dashboard_join(self):
        import pandas as pd

        from parrot.outputs.a2ui.linked.models import TransformSpec

        targets_frame = pd.DataFrame({"program": ["a"], "target": [100]})
        activity = _linked_source(
            "activity",
            transform=TransformSpec(
                ops=[{"op": "join", "with": "targets", "how": "left", "on": [{"left": "program", "right": "program"}]}]
            ),
        )
        targets = _linked_source("targets")
        envelope = build_linked_surface(
            [
                {"id": "root", "component": "Column", "children": ["chart", "table"]},
                {
                    "id": "chart",
                    "component": "Chart",
                    "type": "bar",
                    "x": "day",
                    "y": ["visits"],
                    "data": {"path": "/activity/rows"},
                },
                {
                    "id": "table",
                    "component": "DataTable",
                    "columns": [{"name": "program"}, {"name": "target"}],
                    "data": {"path": "/targets/rows"},
                },
            ],
            {"activity": activity, "targets": targets},
            {"activity": _activity_frame(), "targets": targets_frame},
            surface_id="linked-dashboard-join",
        )
        _assert_conformant(envelope, origin=ProducerOrigin.TOOL)


# ---------------------------------------------------------------------------
# Inline emitter (inline/emitter.py, FEAT-755) — LLM-origin producer.
# ---------------------------------------------------------------------------

_INLINE_CASES: list[tuple[str, dict]] = [
    ("KPICard", {"label": "Worked hours", "value": 1234.5, "unit": "h", "trend": "up"}),
    ("InfoCard", {"title": "Release status", "body": "All checks are green."}),
    ("Timeline", {"events": [{"title": "Kickoff", "timestamp": "2026-10-27"}]}),
    (
        "Graph",
        {
            "nodes": [{"id": "a", "label": "Start"}, {"id": "b", "label": "End"}],
            "edges": [{"from": "a", "to": "b", "label": "go"}],
            "accessibleDescription": "Two-step flow from Start to End",
        },
    ),
]


@pytest.mark.parametrize(("component", "config"), _INLINE_CASES, ids=[c for c, _ in _INLINE_CASES])
def test_inline_emitter_envelopes_conform(component: str, config: dict) -> None:
    """FEAT-755 G7: every inline-emitted envelope is catalog- and wire-conformant.

    The inline emitter is an LLM-origin producer, so it is validated with LLM-origin
    semantics — the same gates that reject an `action` or `parrot_data_sources` from
    a model-authored surface.
    """
    response = SimpleNamespace(
        structured_output=config,
        output=None,
        content=None,
        response="",
        data=None,
        metadata={},
        a2ui_envelope=None,
        output_mode=None,
    )
    outcome = emit_inline_component(response, component)
    assert outcome.status == "emitted", f"{component}: {outcome.reason}"

    message = A2UIAgentMessage.model_validate(response.a2ui_envelope)
    envelope = message.create_surface
    assert envelope is not None
    _assert_conformant(envelope, origin=ProducerOrigin.LLM)

    extensions = envelope.metadata.extensions.root
    assert PRESENTATION_EXTENSION in extensions
