"""Adaptive Cards renderer (Module 5/7, satellite, FEAT-470 TASK-2543/TASK-2545).

Transcodes A2UI v1.0 envelopes into Adaptive Card 1.4+ JSON for Teams-style
surfaces. Like :mod:`~parrot.outputs.a2ui_renderers.ssr_html`, it LOWERS every
non-primitive (Parrot composite) component before baking (composite -> nested
``BasicNode`` tree -> :func:`~parrot.outputs.a2ui.catalog.base.to_components`
flattening into the envelope's own flat wire list, in place of the composite
— template/binding expansion is exclusively :func:`bake_envelope`'s job and
must run AFTER lowering), bakes the fully-lowered flat envelope, reconstructs
a nested :class:`BasicNode` tree rooted at ``"root"``, and dispatches each
node to a dedicated ``_render_<Name>`` method. A component this renderer does
not know how to render natively degrades to a visible ``Text`` placeholder
(never a silent failure or an exception) via
:func:`parrot.outputs.a2ui.renderers.degrade.degrade`; every degradation is
recorded in ``RenderedArtifact.metadata["degraded"]``.

**TASK-2545 — native inputs + actions**: unlike the purely-static SSR/PDF
renderers, this renderer now emits REAL Adaptive Card inputs/actions instead
of a read-only presentation:

* ``TextField`` -> ``Input.Text`` (``variant="longText"`` -> ``isMultiline``,
  ``variant="obscured"`` -> ``style="Password"``, ``variant="number"`` ->
  ``Input.Number`` instead — Adaptive Cards has no numeric ``Input.Text``
  style, only a dedicated ``Input.Number`` element).
* ``CheckBox`` -> ``Input.Toggle``; ``ChoicePicker`` -> ``Input.ChoiceSet``
  (``isMultiSelect``, compact/expanded ``style``); ``Slider`` -> ``Input.Number``
  (``min``/``max``); ``DateTimeInput`` -> ``Input.Date``/``Input.Time``.
* ``Button{action.event}`` -> a top-level ``Action.Submit`` (Adaptive Cards has
  no inline action element in this codebase's ``cards`` module — every Button
  action collapses into the card's bottom action bar) whose ``data`` carries
  ``{"a2ui_action": <v1.0 "action" envelope>, "surfaceId": ...}``.
* ``Button{action.functionCall: openUrl}`` -> a top-level ``Action.OpenUrl``.
* An input's ``id`` is the JSON-Pointer ``path`` of its (pre-bake) ``value``
  binding — RFC 6901 tilde-escaped (``~`` -> ``~0``, ``/`` -> ``~1``) since
  some Teams clients reject a literal ``/`` in an element id (spec §7 Known
  Risks) — so a Teams ``activity.value`` submission can be decoded back into
  a partial ``dataModel`` update by the receiving wrapper.

Deep links (rendered when a component with a degraded action is paired with
one) are STILL rendered as display text (``TextBlock``), never
``Action.OpenUrl`` — that remains TASK-2546's job; only a Button's own
``action`` produces a real Adaptive Card action here.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# Ensure the v1.0 catalogs (Basic primitives + Parrot composites) are
# registered so lowering/dispatch can resolve every component name.
import parrot.outputs.a2ui.catalog.basic
import parrot.outputs.a2ui.catalog.parrot  # noqa: F401 — ensure registration
from parrot.outputs.a2ui.artifacts import DeepLink, RenderedArtifact
from parrot.outputs.a2ui.baking import bake_envelope
from parrot.outputs.a2ui.catalog import get_component
from parrot.outputs.a2ui.catalog.base import BasicNode, TabSpec, to_components
from parrot.outputs.a2ui.models import ActionMessage, Component, CreateSurface
from parrot.outputs.a2ui.renderers import (
    AbstractA2UIRenderer,
    RendererCapabilities,
    register_a2ui_renderer,
)
from parrot.outputs.a2ui.renderers.degrade import degradation_record, degrade
from parrot.outputs.a2ui.serialization import serialize as serialize_a2ui_message
from parrot.outputs.cards import (
    DEFAULT_ADAPTIVE_CARD_VERSION,
    ActionOpenUrl,
    ActionSubmit,
    CardSpec,
    Column,
    ColumnSet,
    Container,
    Image,
    InputChoice,
    InputChoiceSet,
    InputDate,
    InputNumber,
    InputText,
    InputTime,
    InputToggle,
    RawElementsSection,
    TextBlock,
)
from parrot.outputs.cards import render as render_card
from parrot.outputs.cards.actions import ACAction
from parrot.outputs.cards.elements import ACElement

logger = logging.getLogger(__name__)

_SURFACE_NAME = "adaptive_cards"
_AC_SCHEMA = "http://adaptivecards.io/schemas/adaptive-card.json"
_AC_VERSION = DEFAULT_ADAPTIVE_CARD_VERSION
_AC_MIME = "application/vnd.microsoft.card.adaptive"

# Text roles that get emphasized styling in the card.
_TITLE_ROLES = {"title"}
_HEADING_ROLES = {"heading", "subtitle", "label"}

#: The five Basic Catalog primitives whose `value` may carry a data-model
#: binding — this renderer records each one's (pre-bake) binding path so the
#: baked `Input.id` can be built from it (spec §7: "Input.id = path del
#: binding").
_INPUT_PRIMITIVES = frozenset({"TextField", "CheckBox", "ChoicePicker", "Slider", "DateTimeInput"})


def _encode_binding_id(path: str) -> str:
    """Encode a JSON-Pointer binding path as a Teams-safe Adaptive Card element id.

    Some Teams client versions reject a literal ``/`` inside an ``Input``
    element's ``id`` (spec §7 Known Risks). Escapes it using the same
    tilde convention RFC 6901 uses for a JSON Pointer reference token
    (``~`` -> ``~0``, ``/`` -> ``~1``), applied to the whole pointer rather
    than per-segment — the result still round-trips to the original path
    via :func:`_decode_binding_id`.

    Args:
        path: A JSON Pointer (e.g. ``"/form/email"``), or any other plain
            component id used as a fallback when no binding is present.

    Returns:
        A ``/``-free string safe to use as an Adaptive Card element id.
    """
    return path.replace("~", "~0").replace("/", "~1")


def _decode_binding_id(encoded: str) -> str:
    """Inverse of :func:`_encode_binding_id`.

    Args:
        encoded: A tilde-escaped id produced by :func:`_encode_binding_id`.

    Returns:
        The original JSON Pointer (or plain component id).
    """
    return encoded.replace("~1", "/").replace("~0", "~")


def _resolve_bindings(value: Any, data_model: dict[str, Any]) -> Any:
    """Resolve every ``{"path": "..."}`` JSON-Pointer binding in ``value``.

    A minimal, LOCAL resolver for values that must bypass
    :func:`~parrot.outputs.a2ui.baking.bake_envelope`'s generic pass (a
    Button's ``action`` — see
    :meth:`AdaptiveCardsRenderer._button_actions` for why). Recurses through
    nested dicts/lists. Deliberately does NOT evaluate ``{"call": ...}``
    function-call expressions (out of scope here — a Button's dynamic event
    context / ``functionCall`` args are expected to be literal values or
    plain bindings, not nested function calls).

    Args:
        value: A property value (possibly nested dict/list) to resolve.
        data_model: The envelope's data model.

    Returns:
        ``value`` with every ``{"path": ...}`` binding replaced by its
        resolved value (``None`` if the pointer does not resolve).
    """
    if isinstance(value, dict):
        if set(value) == {"path"}:
            import jsonpointer

            try:
                return jsonpointer.resolve_pointer(data_model, value["path"])
            except jsonpointer.JsonPointerException:
                return None
        return {key: _resolve_bindings(item, data_model) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_bindings(item, data_model) for item in value]
    return value


@dataclass
class _RenderState:
    """Per-``render()`` mutable state threaded through the recursive dispatch.

    Attributes:
        surface_id: The envelope's ``surfaceId`` (embedded in every
            ``Action.Submit`` payload).
        timestamp: ISO 8601 render time, used as the ``ActionMessage.timestamp``
            for every ``Action.Submit`` built during this render — this
            renderer is static (no client-side JS), so it cannot know the
            actual future click time; the receiving wrapper may re-stamp it.
        binding_paths: Pre-bake ``{component_id: json_pointer}`` for every
            input primitive whose ``value`` was a live binding.
        button_actions: Pre-bake ``{component_id: Action}`` for every
            ``Button`` (see :meth:`AdaptiveCardsRenderer._button_actions` for
            why Buttons are excluded from the generic bake pass).
        data_model: The envelope's data model, used to resolve any live
            bindings inside a Button's ``action`` (see :func:`_resolve_bindings`).
        actions: Accumulates top-level ``Action.Submit``/``Action.OpenUrl``
            built while walking the tree (every Button collapses into the
            card's bottom action bar — this codebase's ``cards`` module has
            no inline action element).
        degradations: Accumulates one record per unsupported component.
    """

    surface_id: str
    timestamp: str
    binding_paths: dict[str, str] = field(default_factory=dict)
    button_actions: dict[str, Any] = field(default_factory=dict)
    data_model: dict[str, Any] = field(default_factory=dict)
    actions: list[ACAction] = field(default_factory=list)
    degradations: list[dict[str, Any]] = field(default_factory=list)


@register_a2ui_renderer(
    _SURFACE_NAME,
    RendererCapabilities(
        interactive=False,
        supports_actions=True,
        supports_updates=False,
        output=_AC_MIME,
        supported_components={
            "Text",
            "Image",
            "Row",
            "Column",
            "Card",
            "TextField",
            "CheckBox",
            "ChoicePicker",
            "Slider",
            "DateTimeInput",
            "Button",
        },
    ),
)
class AdaptiveCardsRenderer(AbstractA2UIRenderer):
    """Basic-tree -> Adaptive Card JSON renderer with native inputs/actions."""

    async def render(
        self,
        envelope: CreateSurface,
        *,
        bake: bool = True,
        deep_links: list[DeepLink] | None = None,
    ) -> RenderedArtifact:
        """Render an envelope to a baked Adaptive Card ``RenderedArtifact``.

        Args:
            envelope: The validated ``createSurface`` envelope.
            bake: Always effectively ``True`` for this static renderer (bindings
                are resolved regardless); kept for ABC compatibility.
            deep_links: Deep links to render as display text (never
                ``Action.OpenUrl`` — that is TASK-2546's job).

        Returns:
            A ``RenderedArtifact`` with ``mime_type="application/vnd.microsoft.card.adaptive"``;
            any component this renderer degraded is recorded in
            ``metadata["degraded"]``.
        """
        # Lower every composite BEFORE baking (same order as SSR-HTML,
        # TASK-2543) — binding-path extraction below must also see the
        # LOWERED (but not yet baked) input primitives, since they are
        # themselves Basic Catalog primitives and lowering never touches them.
        lowered_envelope = self._lower_composites(envelope)
        binding_paths = self._binding_paths(lowered_envelope.components)
        button_actions = self._button_actions(lowered_envelope.components)
        baked_components = bake_envelope(lowered_envelope)
        by_id = {bc["id"]: bc for bc in baked_components}

        state = _RenderState(
            surface_id=envelope.surface_id,
            timestamp=datetime.now(UTC).isoformat(),
            binding_paths=binding_paths,
            button_actions=button_actions,
            data_model=envelope.data_model,
        )

        elements: list[ACElement] = []
        if "root" in by_id:
            root = self._reconstruct(by_id["root"]["id"], by_id)
            rendered = self._render_basic(root, state)
            if rendered is not None:
                elements.append(rendered)

        for link in deep_links or []:
            # Deep links are rendered as DISPLAY text (never Action.OpenUrl) in v1.
            elements.append(TextBlock(text=f"{link.action_label}: {link.url}"))

        spec = CardSpec(sections=[RawElementsSection(elements=elements)], actions=state.actions)
        card = render_card(spec)
        content = json.dumps(card, sort_keys=True).encode("utf-8")
        return RenderedArtifact(
            artifact_id=f"{_SURFACE_NAME}-{envelope.surface_id}",
            mime_type=_AC_MIME,
            content=content,
            filename=f"{envelope.surface_id}.card.json",
            title=envelope.surface_id,
            surface=_SURFACE_NAME,
            deep_links=list(deep_links or []),
            metadata={"degraded": state.degradations} if state.degradations else {},
        )

    # -- lowering (composites -> flat primitives, BEFORE baking) -------------

    def _lower_composites(self, envelope: CreateSurface) -> CreateSurface:
        """Replace every non-primitive (Parrot composite) component with its
        lowered + flattened primitive equivalents, in place, in the envelope's
        own flat component list. Mirrors
        :meth:`~parrot.outputs.a2ui_renderers.ssr_html.SSRHTMLRenderer._lower_composites`.
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

    # -- binding-path extraction (BEFORE baking resolves them away) ----------

    @staticmethod
    def _binding_paths(components: list[Component]) -> dict[str, str]:
        """Map each input primitive's component id -> its (pre-bake) `value`
        binding JSON Pointer, for components whose `value` is a live
        `{"path": ...}` `DataBinding` (spec §7: `Input.id` = the binding path
        so a Teams submit can be applied as a partial `updateDataModel`).
        """
        paths: dict[str, str] = {}
        for comp in components:
            if comp.component not in _INPUT_PRIMITIVES:
                continue
            value = (comp.model_extra or {}).get("value")
            if isinstance(value, dict) and set(value) == {"path"}:
                paths[comp.id] = value["path"]
        return paths

    def _input_id(self, node: BasicNode, state: _RenderState) -> str:
        """The Teams-safe Adaptive Card element id for an input primitive `node`."""
        path = state.binding_paths.get(node.id or "")
        raw = path if path is not None else (node.id or "")
        return _encode_binding_id(raw)

    @staticmethod
    def _button_actions(components: list[Component]) -> dict[str, Any]:
        """Map each ``Button``'s component id -> its raw (unbaked) ``Action``.

        ``bake_envelope``'s generic resolver evaluates EVERY
        ``{"call": ..., "args": {...}}``-shaped dict it finds anywhere in a
        component, agnostic of field semantics — that is correct for a
        property VALUE that happens to be a function call (e.g.
        ``Text.text={"call": "formatCurrency", ...}``), but wrong for a
        Button's own ``action.functionCall`` (a client-dispatched action
        descriptor, e.g. ``openUrl``, that must NOT be evaluated ahead of
        time — ``openUrl``'s agent-side evaluator is a deliberate no-op that
        would silently erase it). Buttons are therefore excluded from the
        generic bake pass for their ``action`` field entirely; this renderer
        resolves any live bindings inside ``action.event.context`` /
        ``action.functionCall.args`` itself, via :func:`_resolve_bindings`
        (see :meth:`_render_Button`).
        """
        actions: dict[str, Any] = {}
        for comp in components:
            if comp.component == "Button" and comp.action is not None:
                actions[comp.id] = comp.action
        return actions

    # -- tree reconstruction (mirrors ssr_html.SSRHTMLRenderer._reconstruct) -

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

    def _render_basic(self, node: BasicNode, state: _RenderState) -> ACElement | None:
        """Dispatch a reconstructed :class:`BasicNode` to its ``_render_<Name>`` method.

        Returns ``None`` for a ``Button`` (it is collapsed into
        ``state.actions``, never rendered inline) or for a Button whose
        action this renderer cannot represent (recorded as a degradation).
        """
        component = node.component
        method = getattr(self, f"_render_{component}", None)
        if method is None:
            state.degradations.append(degradation_record(node, f"{_SURFACE_NAME} has no renderer for {component}"))
            return self._render_Text(degrade(node, "no renderer available"), state)
        return method(node, state)

    def _render_children(self, node: BasicNode, state: _RenderState) -> list[ACElement]:
        children = node.children if isinstance(node.children, list) else []
        rendered = [self._render_basic(child, state) for child in children]
        return [element for element in rendered if element is not None]

    # -- text/media/layout ----------------------------------------------------

    def _render_Text(self, node: BasicNode, state: _RenderState) -> ACElement:
        props = node.model_extra or {}
        role = None
        if node.metadata is not None and node.metadata.extensions is not None:
            role = node.metadata.extensions.root.get("parrot_role")
        kwargs: dict[str, Any] = {}
        if role in _TITLE_ROLES:
            kwargs["size"] = "Large"
            kwargs["weight"] = "Bolder"
        elif role in _HEADING_ROLES:
            kwargs["weight"] = "Bolder"
        text = props.get("text")
        return TextBlock(text="" if text is None else str(text), **kwargs)

    def _render_Image(self, node: BasicNode, state: _RenderState) -> ACElement:
        props = node.model_extra or {}
        return Image(url=str(props.get("url", "")), alt_text=str(props.get("description") or ""))

    def _render_Row(self, node: BasicNode, state: _RenderState) -> ACElement:
        return ColumnSet(columns=[Column(items=[item]) for item in self._render_children(node, state)])

    def _render_Column(self, node: BasicNode, state: _RenderState) -> ACElement:
        return Container(items=self._render_children(node, state))

    def _render_Card(self, node: BasicNode, state: _RenderState) -> ACElement:
        inner = self._render_basic(node.child, state) if node.child is not None else None
        return Container(items=[inner] if inner is not None else [], style="Emphasis")

    # -- native inputs (TASK-2545) --------------------------------------------

    def _render_TextField(self, node: BasicNode, state: _RenderState) -> ACElement:
        props = node.model_extra or {}
        variant = props.get("variant", "shortText")
        input_id = self._input_id(node, state)
        label = props.get("label")
        label_str = None if label is None else str(label)
        value = props.get("value")

        if variant == "number":
            # Adaptive Cards has no numeric `Input.Text` style — a "number"
            # TextField variant maps to the dedicated `Input.Number` element.
            return InputNumber(
                id=input_id,
                label=label_str,
                value=value if isinstance(value, (int, float)) else None,
            )

        kwargs: dict[str, Any] = {}
        if variant == "longText":
            kwargs["is_multiline"] = True
        elif variant == "obscured":
            kwargs["style"] = "Password"
        return InputText(
            id=input_id,
            label=label_str,
            value="" if value is None else str(value),
            **kwargs,
        )

    def _render_CheckBox(self, node: BasicNode, state: _RenderState) -> ACElement:
        props = node.model_extra or {}
        input_id = self._input_id(node, state)
        label = props.get("label")
        label_str = None if label is None else str(label)
        checked = bool(props.get("value", False))
        return InputToggle(
            id=input_id,
            title=label_str or "",
            label=label_str,
            value="true" if checked else "false",
        )

    def _render_ChoicePicker(self, node: BasicNode, state: _RenderState) -> ACElement:
        props = node.model_extra or {}
        input_id = self._input_id(node, state)
        label = props.get("label")
        label_str = None if label is None else str(label)
        options = props.get("options") or []
        choices = [
            InputChoice(title=str(option.get("label", option.get("value", ""))), value=str(option.get("value", "")))
            for option in options
            if isinstance(option, dict)
        ]
        is_multi = props.get("variant") == "multipleSelection"
        display_style = props.get("displayStyle", "checkbox")
        style = "expanded" if is_multi or display_style == "chips" else "compact"

        value = props.get("value")
        selected: str | None = None
        if isinstance(value, list) and value:
            selected = ",".join(str(v) for v in value) if is_multi else str(value[0])
        elif value is not None:
            selected = str(value)

        return InputChoiceSet(
            id=input_id,
            label=label_str,
            choices=choices,
            value=selected,
            is_multi_select=is_multi,
            style=style,
        )

    def _render_Slider(self, node: BasicNode, state: _RenderState) -> ACElement:
        props = node.model_extra or {}
        input_id = self._input_id(node, state)
        label = props.get("label")
        label_str = None if label is None else str(label)
        value = props.get("value")
        return InputNumber(
            id=input_id,
            label=label_str,
            value=value if isinstance(value, (int, float)) else None,
            min=props.get("min"),
            max=props.get("max"),
        )

    def _render_DateTimeInput(self, node: BasicNode, state: _RenderState) -> ACElement:
        props = node.model_extra or {}
        input_id = self._input_id(node, state)
        label = props.get("label")
        label_str = None if label is None else str(label)
        value = props.get("value")
        value_str = None if not value else str(value)
        enable_time = bool(props.get("enableTime", False))
        enable_date = bool(props.get("enableDate", False))
        if enable_time and not enable_date:
            return InputTime(id=input_id, label=label_str, value=value_str)
        return InputDate(id=input_id, label=label_str, value=value_str)

    # -- actions (TASK-2545) ---------------------------------------------------

    def _render_Button(self, node: BasicNode, state: _RenderState) -> None:
        """Collapse a ``Button``'s ``action`` into ``state.actions``.

        Adaptive Cards renders every top-level action in one bottom action
        bar (this codebase's ``cards`` module has no inline ``ActionSet``
        element) — a ``Button`` never produces an inline element itself.
        Reads the RAW (unbaked) ``Action`` from ``state.button_actions``
        (see :meth:`_button_actions`), resolving any live bindings itself.
        """
        title = self._button_title(node.child)
        action = state.button_actions.get(node.id or "")
        if action is None:
            state.degradations.append(degradation_record(node, "Button has no action"))
            return

        if action.event is not None:
            event = action.event
            context = _resolve_bindings(event.context or {}, state.data_model)
            user_message = (
                _resolve_bindings(event.user_message, state.data_model) if event.user_message is not None else None
            )
            message = ActionMessage(
                name=event.name,
                user_message=None if user_message is None else str(user_message),
                surface_id=state.surface_id,
                source_component_id=node.id or "",
                timestamp=state.timestamp,
                context=context if isinstance(context, dict) else {},
            )
            state.actions.append(
                ActionSubmit(
                    title=title,
                    data={
                        "a2ui_action": serialize_a2ui_message(message),
                        "surfaceId": state.surface_id,
                    },
                )
            )
        elif action.function_call is not None and action.function_call.call == "openUrl":
            args = _resolve_bindings(action.function_call.args or {}, state.data_model)
            url = str((args or {}).get("url", "")) if isinstance(args, dict) else ""
            state.actions.append(ActionOpenUrl(title=title, url=url))
        else:
            call_name = action.function_call.call if action.function_call is not None else None
            state.degradations.append(
                degradation_record(node, f"unsupported Button action (functionCall={call_name!r})")
            )
        return

    def _button_title(self, child: BasicNode | None) -> str:
        """Best-effort human title for a Button's action, from its child node."""
        if child is None:
            return ""
        props = child.model_extra or {}
        if child.component == "Text":
            text = props.get("text")
            return "" if text is None else str(text)
        return str(props.get("name") or child.component)
