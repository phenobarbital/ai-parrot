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

import pytest
from parrot.models.infographic import InfographicResponse
from parrot.outputs.a2ui.adapters import infographic_response_to_envelope
from parrot.outputs.a2ui.baking import bake_envelope
from parrot.outputs.a2ui.builders import (
    build_card,
    build_chart,
    build_datatable,
    build_infographic,
    build_kpicard,
    build_surface,
)
from parrot.outputs.a2ui.catalog import (
    ProducerOrigin,
    get_component,
    validate_envelope,
    validate_message,
)
from parrot.outputs.a2ui.catalog.base import to_components
from parrot.outputs.a2ui.catalog.parrot.form import FormField, FormSubmit, build_form
from parrot.outputs.a2ui.models import A2UIAgentMessage, Component, CreateSurface
from parrot.outputs.a2ui.recipes import SUPPORTED_SCHEMA_VERSION
from parrot.outputs.a2ui.recipes.migrate import migrate_layout
from parrot.outputs.a2ui.recipes.models import LayoutSpec

from .._v1 import DEFAULT_CATALOG_ID


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
