"""SSR-HTML renderer (Module 5/7, satellite).

Turns a validated ``CreateSurface`` envelope into a single self-contained, baked HTML
document. It is the backbone of static delivery (G5): the PDF renderer rasterizes its
output and email attaches it directly.

Security invariants (spec G1):

* Subclasses the core :class:`AbstractA2UIRenderer` — never the legacy ``BaseRenderer``
  (which holds the arbitrary-code sink FEAT-273 exists to kill).
* Every data value is HTML-escaped — envelope data is data, never markup/JS.
* Output is self-contained — all CSS inline, no external CDN/script/style/font refs.

v1.0 dispatch (FEAT-470 TASK-2543): :meth:`SSRHTMLRenderer.render` first
LOWERS every non-primitive/Parrot composite component in the envelope via
its own registered ``lower()`` + :func:`~parrot.outputs.a2ui.catalog.base.to_components`
(flattening each composite's nested ``BasicNode`` tree into the envelope's
own flat wire component list, in place of the composite — this is the ONLY
correct order: a composite like ``DataTable`` lowers to a row
``ChildTemplate``, and template/binding expansion is exclusively
:func:`~parrot.outputs.a2ui.baking.bake_envelope`'s job, which must run
AFTER lowering, never before — see ``test_datatable_row_materialization.py``
for the pinned lowering -> bake contract). It THEN bakes the fully-lowered,
flat envelope (resolving every binding and expanding every template),
reconstructs a nested :class:`BasicNode` tree rooted at ``"root"`` from the
baked flat dicts (pure id-reference resolution — every node is already a
Basic Catalog primitive at this point), and dispatches each of the 18
official primitives to a dedicated ``_render_<Name>`` method. A component
this renderer does not know how to render natively degrades to a visible
``Text`` placeholder (never a silent failure or an exception) via
:func:`parrot.outputs.a2ui.renderers.degrade.degrade`; every degradation is
recorded in ``RenderedArtifact.metadata["degraded"]``.
"""

from __future__ import annotations

import html
import logging
from typing import Any

# Ensure the v1.0 catalogs (Basic primitives + Parrot composites) are
# registered so lowering/dispatch can resolve every component name.
import parrot.outputs.a2ui.catalog.basic
import parrot.outputs.a2ui.catalog.parrot  # noqa: F401 — ensure registration
from parrot.outputs.a2ui.artifacts import DeepLink, RenderedArtifact
from parrot.outputs.a2ui.baking import bake_envelope
from parrot.outputs.a2ui.catalog import get_component
from parrot.outputs.a2ui.catalog.base import BasicNode, TabSpec, to_components
from parrot.outputs.a2ui.models import Component, CreateSurface
from parrot.outputs.a2ui.renderers import (
    AbstractA2UIRenderer,
    RendererCapabilities,
    register_a2ui_renderer,
)
from parrot.outputs.a2ui.renderers.degrade import degradation_record, degrade
from parrot.outputs.formats.assets.design_system import DesignSystem

from ._semantics import (
    is_kpi_row,
    kpi_unit_html,
    node_extensions,
    semantic_card_class,
    semantic_text_class,
    trend_attr_html,
)
from ._shell import document_shell
from ._table_format import format_cell, is_numeric_column

logger = logging.getLogger(__name__)

_SURFACE_NAME = "ssr_html"

#: Basic Catalog composite/container primitives whose children render
#: recursively (the CSS class used for the wrapping ``<div>``).
_CONTAINER_COMPONENTS = {"Column": "a2ui-col", "Row": "a2ui-row"}


def _esc(value: Any) -> str:
    """HTML-escape any baked (already-resolved) value as a display string."""
    return html.escape("" if value is None else str(value))


@register_a2ui_renderer(
    _SURFACE_NAME,
    RendererCapabilities(
        interactive=False,
        supports_actions=False,
        supports_updates=False,
        output="text/html",
        supported_components={
            "AudioPlayer",
            "Button",
            "Card",
            "CheckBox",
            "ChoicePicker",
            "Column",
            "DateTimeInput",
            "Divider",
            "Icon",
            "Image",
            "List",
            "Modal",
            "Row",
            "Slider",
            "Tabs",
            "Text",
            "TextField",
            "Video",
        },
    ),
)
class SSRHTMLRenderer(AbstractA2UIRenderer):
    """Static, self-contained HTML renderer for A2UI v1.0 envelopes."""

    #: Components this renderer forces to degrade regardless of its own
    #: dispatch table (e.g. :class:`PDFRenderer` excludes Video/AudioPlayer —
    #: weasyprint cannot play media in a rasterized PDF).
    _UNSUPPORTED: frozenset[str] = frozenset()

    def __init__(self, *, theme: str = "light", layout: str = "analytics") -> None:
        """Initialize the renderer with a default ``(theme, layout)`` pair.

        Args:
            theme: Default theme name resolved by
                :class:`~parrot.outputs.formats.assets.design_system.DesignSystem`.
            layout: Default layout name.

        Both keyword arguments MUST default — ``RecipeRunner`` calls
        ``renderer_cls()`` with no arguments (``runner.py``), and
        :class:`~parrot.outputs.a2ui_renderers.pdf.PDFRenderer` subclasses
        this renderer without its own ``__init__``, so it inherits these
        same defaults.
        """
        self.theme = theme
        self.layout = layout
        #: ``id(cell_node) -> (col_type, col_format)`` for every materialized
        #: DataTable cell Text node, populated fresh by :meth:`render` each
        #: call (TASK-2711) — see :meth:`_collect_table_columns` for why this
        #: is re-derived from the original envelope rather than read off the
        #: lowered node's own metadata.
        self._table_cell_columns: dict[int, tuple[str | None, str | None]] = {}

    async def render(
        self,
        envelope: CreateSurface,
        *,
        bake: bool = True,
        deep_links: list[DeepLink] | None = None,
    ) -> RenderedArtifact:
        """Render an envelope to a baked, self-contained HTML ``RenderedArtifact``.

        Args:
            envelope: The validated ``createSurface`` envelope.
            bake: Always effectively ``True`` for this static renderer (bindings are
                resolved regardless); kept for ABC compatibility.
            deep_links: Deep links to render as anchors for degraded actions.

        Returns:
            A ``RenderedArtifact`` with ``mime_type="text/html"``; any
            component this renderer degraded is recorded in
            ``metadata["degraded"]``.
        """
        # Column type/format lives on the ORIGINAL (not-yet-lowered)
        # DataTable component — DataTableComponent.lower()'s row template is
        # a single BasicNode materialized once per data-model row, with no
        # room to carry per-column type/format without changing lower()'s
        # own pinned output (breaking `datatable_lowered.json`). Capture it
        # here so cell rendering can re-derive it later (TASK-2711).
        table_columns_by_id = self._collect_table_columns(envelope)

        # Lower every composite BEFORE baking — a composite (e.g. DataTable)
        # may lower to a row `ChildTemplate`, and template/binding expansion
        # is exclusively `bake_envelope`'s job, which must see the fully
        # flattened wire graph (never a still-composite one).
        lowered_envelope = self._lower_composites(envelope)
        # Static renderer: always bake so the document has zero live bindings.
        baked_components = bake_envelope(lowered_envelope)
        by_id = {bc["id"]: bc for bc in baked_components}

        self._table_cell_columns = {}
        degradations: list[dict[str, Any]] = []
        body_parts: list[str] = []
        if "root" in by_id:
            root = self._reconstruct(by_id["root"]["id"], by_id)
            if table_columns_by_id:
                self._index_datatable_cells(root, table_columns_by_id)
            body_parts.append(self._render_basic(root, degradations))

        for link in deep_links or []:
            body_parts.append(
                f'<a class="a2ui-deeplink" href="{html.escape(link.url, quote=True)}">'
                f"{html.escape(link.action_label)}</a>"
            )

        theme, layout = DesignSystem.resolve(
            envelope, theme_default=self.theme, layout_default=self.layout
        )
        style = DesignSystem.stylesheet(theme, layout)
        document = document_shell(
            title=envelope.surface_id,
            style=style,
            body="".join(body_parts),
            theme=theme,
            layout=layout,
        )
        return RenderedArtifact(
            artifact_id=f"{_SURFACE_NAME}-{envelope.surface_id}",
            mime_type="text/html",
            content=document.encode("utf-8"),
            filename=f"{envelope.surface_id}.html",
            title=envelope.surface_id,
            surface=_SURFACE_NAME,
            deep_links=list(deep_links or []),
            metadata={"degraded": degradations} if degradations else {},
        )

    # -- lowering (composites -> flat primitives, BEFORE baking) -------------

    def _lower_composites(self, envelope: CreateSurface) -> CreateSurface:
        """Replace every non-primitive (Parrot composite) component with its
        lowered + flattened primitive equivalents, in place, in the envelope's
        own flat component list.

        A composite's own registered ``lower()`` preserves the composite's
        original id on its own outermost node (see e.g.
        ``catalog/parrot/datatable.py``), so any OTHER component's
        ``child``/``children`` reference into that id remains valid after
        lowering — no cross-reference rewriting is needed.
        """
        new_components: list[Component] = []
        for comp in envelope.components:
            try:
                entry = get_component(comp.component)
            except KeyError:
                entry = None
            if entry is not None and not entry.definition.is_primitive:
                tree = entry.component_cls().lower(comp, envelope.data_model)
                new_components.extend(to_components(tree, id_prefix=f"{comp.id}-lc"))
            else:
                new_components.append(comp)
        return envelope.model_copy(update={"components": new_components})

    # -- DataTable column type/format re-derivation (TASK-2711) -------------
    # DataTableComponent.lower() cannot carry per-column type/format on its
    # materialized row cells without changing its own pinned lowering
    # output (breaking `datatable_lowered.json`) — so these helpers
    # independently re-derive the column contract from the ORIGINAL,
    # not-yet-lowered envelope and match it back onto the lowered/baked
    # tree via the `parrot_component_id` extension `lower()` already
    # stamps on the table's Card.

    @staticmethod
    def _collect_table_columns(envelope: CreateSurface) -> dict[str, list[dict[str, Any]]]:
        """DataTable component id -> its declared ``columns``, envelope-wide.

        ``envelope.components`` is a FLAT adjacency list (every component,
        nested or not, is a top-level entry referenced by id) — so a single
        pass over it finds every ``DataTable``, regardless of nesting depth.
        """
        columns_by_id: dict[str, list[dict[str, Any]]] = {}
        for comp in envelope.components:
            if comp.component == "DataTable":
                props = comp.model_extra or {}
                columns = props.get("columns")
                if isinstance(columns, list):
                    columns_by_id[comp.id] = [c for c in columns if isinstance(c, dict)]
        return columns_by_id

    def _index_datatable_cells(
        self, node: BasicNode, columns_by_id: dict[str, list[dict[str, Any]]]
    ) -> None:
        """Walk a reconstructed tree, populating ``self._table_cell_columns``.

        A ``Card`` carrying ``parrot_component_id`` is a lowered DataTable —
        descend into it and record each materialized row's cells.
        """
        table_id = node_extensions(node).get("parrot_component_id") if node.component == "Card" else None
        columns = columns_by_id.get(table_id) if table_id else None
        if columns:
            self._index_table_rows(node, columns)
        for child in self._children_of(node):
            self._index_datatable_cells(child, columns_by_id)

    def _index_table_rows(self, node: BasicNode, columns: list[dict[str, Any]]) -> None:
        """Record ``id(cell) -> (type, format)`` for every cell of every
        materialized ``parrot_role: "row"`` Row under ``node``, matching
        column contracts to cells POSITIONALLY (the row template emits
        exactly one cell per declared column, in declared order)."""
        if node.component == "Row" and node_extensions(node).get("parrot_role") == "row":
            cells = node.children if isinstance(node.children, list) else []
            for col, cell in zip(columns, cells):
                if isinstance(cell, BasicNode):
                    self._table_cell_columns[id(cell)] = (col.get("type"), col.get("format"))
        for child in self._children_of(node):
            self._index_table_rows(child, columns)

    @staticmethod
    def _children_of(node: BasicNode) -> list[BasicNode]:
        """Every immediate ``BasicNode`` child of ``node`` (``child``, list
        ``children``, and ``tabs[].child``), for tree-walking purposes."""
        kids: list[BasicNode] = []
        if isinstance(node.child, BasicNode):
            kids.append(node.child)
        if isinstance(node.children, list):
            kids.extend(c for c in node.children if isinstance(c, BasicNode))
        for tab in node.tabs or []:
            if isinstance(tab.child, BasicNode):
                kids.append(tab.child)
        return kids

    # -- tree reconstruction -------------------------------------------------

    def _reconstruct(self, node_id: str, by_id: dict[str, dict[str, Any]]) -> BasicNode:
        """Reconstruct a nested :class:`BasicNode` from the flat baked dict list.

        Every node reaching this point is already a Basic Catalog primitive
        (composites were lowered+flattened by :meth:`_lower_composites`
        BEFORE baking) — this is pure id-reference resolution, never a
        ``lower()`` call.
        """
        data = dict(by_id[node_id])
        name = data.pop("component")
        data.pop("id", None)
        child_id = data.pop("child", None)
        children_ids = data.pop("children", None)
        metadata = data.pop("metadata", None)

        tabs: list[TabSpec] | None = None
        if "tabs" in data:
            tabs = [
                TabSpec(title=tab["title"], child=self._reconstruct(tab["child"], by_id)) for tab in data.pop("tabs")
            ]

        # Modal's `content`/`trigger` are prop-level id REFERENCES (not
        # `child`/`children`) — resolve `content` here so `_render_Modal`
        # can render it inline without needing `by_id` in scope (spec:
        # "Modal→inline"). `trigger` (which opens the modal, meaningless
        # without client-side interactivity) is left as a bare id.
        if name == "Modal" and isinstance(data.get("content"), str):
            data["content"] = self._reconstruct(data["content"], by_id)

        child = self._reconstruct(child_id, by_id) if isinstance(child_id, str) else None
        children = [self._reconstruct(cid, by_id) for cid in children_ids] if isinstance(children_ids, list) else None
        return BasicNode(
            id=node_id,
            component=name,
            child=child,
            children=children,
            tabs=tabs,
            metadata=metadata,
            **data,
        )

    # -- dispatch -------------------------------------------------------------

    def _render_basic(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        """Dispatch a reconstructed :class:`BasicNode` to its ``_render_<Name>`` method."""
        component = node.component
        if component in self._UNSUPPORTED:
            degradations.append(degradation_record(node, f"{_SURFACE_NAME} does not support {component}"))
            return self._render_Text(degrade(node, "unsupported here"), degradations)

        method = getattr(self, f"_render_{component}", None)
        if method is None:
            degradations.append(degradation_record(node, f"{_SURFACE_NAME} has no renderer for {component}"))
            return self._render_Text(degrade(node, "no renderer available"), degradations)
        return method(node, degradations)

    def _render_children(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        children = node.children if isinstance(node.children, list) else []
        return "".join(self._render_basic(child, degradations) for child in children)

    # -- text/media -------------------------------------------------------

    def _render_Text(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        props = node.model_extra or {}
        role = None
        if node.metadata is not None and node.metadata.extensions is not None:
            role = node.metadata.extensions.root.get("parrot_role")
        cls = f"a2ui-text a2ui-{_esc(role)}" if role else "a2ui-text"
        semantic_cls = semantic_text_class(node)
        if semantic_cls:
            cls = f"{cls} {semantic_cls}"
        extra = kpi_unit_html(node) if role == "value" else ""
        attrs = trend_attr_html(node) if role == "delta" else ""

        raw_value = props.get("text")
        col = self._table_cell_columns.get(id(node)) if role == "cell" else None
        if col is not None:
            col_type, col_format = col
            # Additive, matching the TASK-2710 convention: "a2ui-cell" is
            # never replaced, only appended to — a table with no `type`
            # declared per column renders byte-identical to before this
            # task (`format_cell` degrades to `str(value)`/"" exactly like
            # the previous `_esc(raw_value)`).
            if is_numeric_column(col_type):
                cls = f"{cls} num"
                raw_attr = html.escape("" if raw_value is None else str(raw_value), quote=True)
                attrs += f' data-v="{raw_attr}"'
            display = html.escape(format_cell(raw_value, col_type=col_type, col_format=col_format))
        else:
            display = _esc(raw_value)

        return f'<p class="{cls}"{attrs}>{display}{extra}</p>'

    def _render_Image(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        props = node.model_extra or {}
        src = str(props.get("url", ""))
        alt = _esc(props.get("description"))
        if src.startswith("data:"):
            return f'<img src="{html.escape(src, quote=True)}" alt="{alt}">'
        # Self-contained: never emit external src; keep URL in a data attribute.
        return f'<div class="a2ui-image" data-image-url="{html.escape(src, quote=True)}">{alt or "[image]"}</div>'

    def _render_Icon(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        props = node.model_extra or {}
        name = props.get("name")
        if isinstance(name, dict) and "svgPath" in name:
            return f'<span class="a2ui-icon" data-svg-path="{html.escape(str(name["svgPath"]), quote=True)}"></span>'
        return f'<span class="a2ui-icon" data-icon="{_esc(name)}"></span>'

    def _render_Video(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        props = node.model_extra or {}
        url = str(props.get("url", ""))
        poster = props.get("posterUrl")
        poster_attr = f' poster="{html.escape(str(poster), quote=True)}"' if poster else ""
        return f'<video controls{poster_attr} data-video-url="{html.escape(url, quote=True)}">' f"</video>"

    def _render_AudioPlayer(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        props = node.model_extra or {}
        url = str(props.get("url", ""))
        description = props.get("description")
        parts = [f'<audio controls data-audio-url="{html.escape(url, quote=True)}"></audio>']
        if description:
            parts.append(f'<span class="a2ui-audio-desc">{_esc(description)}</span>')
        return "".join(parts)

    # -- layout/containers --------------------------------------------------

    def _render_Row(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        cls = "a2ui-row kpi-grid" if is_kpi_row(node) else "a2ui-row"
        return f'<div class="{cls}">{self._render_children(node, degradations)}</div>'

    def _render_Column(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        inner = self._render_children(node, degradations)
        inner += self._table_truncation_notice(node)
        return f'<div class="a2ui-col">{inner}</div>'

    @staticmethod
    def _table_truncation_notice(node: BasicNode) -> str:
        """The "showing N of M rows" notice for a DataTable's materialized
        row Column (``parrot_role: "rows"``), or ``""`` when the table is
        not truncated. ``parrot_total_rows``/``parrot_truncated`` are
        already stamped on this Column's OWN metadata by
        ``DataTableComponent.lower()`` — no extra lookup needed."""
        ext = node_extensions(node)
        if ext.get("parrot_role") != "rows" or not ext.get("parrot_truncated"):
            return ""
        total = ext.get("parrot_total_rows")
        if total is None:
            return ""
        shown = len(node.children) if isinstance(node.children, list) else 0
        return f'<p class="a2ui-table-notice">showing {shown} of {_esc(total)} rows</p>'

    def _render_List(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        props = node.model_extra or {}
        direction = props.get("direction", "vertical")
        cls = "a2ui-list-horizontal" if direction == "horizontal" else "a2ui-list-vertical"
        return f'<div class="{cls}">{self._render_children(node, degradations)}</div>'

    def _render_Card(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        inner = self._render_basic(node.child, degradations) if node.child is not None else ""
        cls = "a2ui-card"
        variant_cls = semantic_card_class(node)
        if variant_cls:
            cls = f"{cls} {variant_cls}"
        return f'<div class="{cls}">{inner}</div>'

    def _render_Tabs(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        panes = []
        for tab in node.tabs or []:
            panes.append(
                f'<div class="a2ui-tab"><div class="a2ui-tab-title">{_esc(tab.title)}</div>'
                f"{self._render_basic(tab.child, degradations)}</div>"
            )
        return f'<div class="a2ui-tabs">{"".join(panes)}</div>'

    def _render_Modal(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        # Static SSR has no client-side trigger/dialog behavior — the
        # content renders inline (spec: "Modal→inline"); `content` was
        # resolved to a nested BasicNode during `_reconstruct`.
        props = node.model_extra or {}
        content_node = props.get("content")
        inner = self._render_basic(content_node, degradations) if isinstance(content_node, BasicNode) else ""
        return f'<div class="a2ui-modal">{inner}</div>'

    def _render_Divider(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        props = node.model_extra or {}
        axis = props.get("axis", "horizontal")
        if axis == "vertical":
            return '<span class="a2ui-divider-v"></span>'
        return '<hr class="a2ui-divider-h">'

    # -- actionable/input (read-only presentation) --------------------------

    def _render_Button(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        inner = self._render_basic(node.child, degradations) if node.child is not None else ""
        return f'<span class="a2ui-button">{inner}</span>'

    def _render_TextField(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        props = node.model_extra or {}
        return self._render_labeled_value(props.get("label"), props.get("value"))

    def _render_CheckBox(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        props = node.model_extra or {}
        checked = "☑" if props.get("value") else "☐"
        return self._render_labeled_value(props.get("label"), checked)

    def _render_ChoicePicker(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        props = node.model_extra or {}
        value = props.get("value")
        display = ", ".join(str(v) for v in value) if isinstance(value, list) else value
        return self._render_labeled_value(props.get("label"), display)

    def _render_Slider(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        props = node.model_extra or {}
        return self._render_labeled_value(props.get("label"), props.get("value"))

    def _render_DateTimeInput(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        props = node.model_extra or {}
        return self._render_labeled_value(props.get("label"), props.get("value"))

    def _render_labeled_value(self, label: Any, value: Any) -> str:
        label_html = f'<span class="a2ui-field-label">{_esc(label)}</span>' if label else ""
        return f'<div class="a2ui-field">{label_html}<span class="a2ui-field-value">{_esc(value)}</span></div>'
