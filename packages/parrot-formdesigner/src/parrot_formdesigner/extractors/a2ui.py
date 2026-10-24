"""A2UI createSurface → FormSchema extractor (FEAT-650, spec §3 M5).

Strict mode (root ``parrot_variant == "form"``) reads the FEAT-544 ``parrot_*``
extensions; heuristic mode (TASK-4202) maps any Basic-catalog surface. Every
loss is reported in :class:`ExtractedForm`. ``parrot.outputs.a2ui`` is an
OPTIONAL extra — imported lazily in :func:`_a2ui_ns` only.
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Iterator
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from ..core.constraints import FieldConstraints
from ..core.options import FieldOption
from ..core.resolution import resolve_rule_references
from ..core.schema import FormField, FormSchema, FormSection, FormSubsection
from ..core.types import FieldType

logger = logging.getLogger(__name__)

A2UI_MAX_COMPONENTS = int(os.environ.get("A2UI_MAX_IMPORT_COMPONENTS", "2000"))
A2UI_MAX_DEPTH = int(os.environ.get("A2UI_MAX_IMPORT_DEPTH", "32"))
_STRICT_WARNING = "strict_projection_only"

_INPUT_PRIMITIVES = frozenset({"TextField", "CheckBox", "ChoicePicker", "Slider", "DateTimeInput"})
_CONTAINERS = frozenset({"Column", "Row", "Card", "List", "Tabs", "Modal"})
# Text roles emitted by the FEAT-544 renderer that carry no form structure of their own.
_SILENT_ROLES = frozenset({"status", "error", "description"})

#: Basic primitive (+ variant / flag qualifier) -> FieldType (spec section 7).
HEURISTIC_PRIMITIVE_MAP: dict[str, FieldType] = {
    "TextField": FieldType.TEXT,
    "TextField:shortText": FieldType.TEXT,
    "TextField:longText": FieldType.TEXT_AREA,
    "TextField:number": FieldType.NUMBER,
    "TextField:obscured": FieldType.PASSWORD,
    "CheckBox": FieldType.BOOLEAN,
    "ChoicePicker": FieldType.SELECT,
    "ChoicePicker:multipleSelection": FieldType.MULTI_SELECT,
    "Slider": FieldType.NUMBER,
    "DateTimeInput:date": FieldType.DATE,
    "DateTimeInput:time": FieldType.TIME,
    "DateTimeInput:datetime": FieldType.DATETIME,
}
#: Basic check function -> how it lands on the FormField.
CHECK_FUNCTION_TO_CONSTRAINT: dict[str, str] = {
    "required": "required",
    "regex": "pattern",
    "length": "min_length/max_length",
    "numeric": "min_value/max_value",
    "email": "field_type=EMAIL",
}
_UNSUPPORTED = {"Image", "Video", "AudioPlayer", "Icon", "Divider", "List", "Modal"}
_INPUTS = {"TextField", "CheckBox", "ChoicePicker", "Slider", "DateTimeInput"}


def _primitive_key(comp: Any, props: dict[str, Any]) -> str:
    """Return the ``component:variant`` key used by the heuristic map."""
    if comp.component == "DateTimeInput":
        date, time = bool(props.get("enableDate")), bool(props.get("enableTime"))
        suffix = "datetime" if date and time else "time" if time else "date"
        return f"DateTimeInput:{suffix}"
    variant = props.get("variant")
    return f"{comp.component}:{variant}" if variant else comp.component


def _component_children(component: Any) -> list[str]:
    """Return static child ids from a component."""
    children: list[str] = []
    if component.child:
        children.append(component.child)
    if isinstance(component.children, list):
        children.extend(component.children)
    for tab in (component.model_extra or {}).get("tabs") or []:
        if isinstance(tab, dict) and isinstance(tab.get("child"), str):
            children.append(tab["child"])
    return children


class ExtractionMode(str, Enum):
    """How a surface was interpreted."""

    STRICT = "strict"
    HEURISTIC = "heuristic"


class DroppedComponent(BaseModel):
    """A surface component that could not be represented in the FormSchema."""

    component_id: str
    component: str
    # unsupported_component | not_in_basic_catalog | unreachable | no_binding | cycle | heuristic_not_implemented
    reason: str


class ExtractedForm(BaseModel):
    """Result of an extraction: the form plus everything that was lost."""

    form: FormSchema
    mode: ExtractionMode
    warnings: list[str] = Field(default_factory=list)
    dropped: list[DroppedComponent] = Field(default_factory=list)


def _a2ui_ns() -> Any:
    """Lazy ai-parrot namespace (pattern: renderers/a2ui.py)."""
    try:
        from parrot.outputs.a2ui.catalog import validate_envelope
        from parrot.outputs.a2ui.catalog.base import CatalogValidationError, ProducerOrigin
        from parrot.outputs.a2ui.models import CreateSurface
        from parrot.outputs.a2ui.serialization import deserialize
    except ImportError as exc:
        raise RuntimeError("A2UIExtractor requires the 'ai-parrot' extra") from exc

    class _NS:
        pass

    ns = _NS()
    ns.validate_envelope = validate_envelope
    ns.CatalogValidationError = CatalogValidationError
    ns.ProducerOrigin = ProducerOrigin
    ns.CreateSurface = CreateSurface
    ns.deserialize = deserialize
    return ns


def _ext(component: Any) -> dict[str, Any]:
    """``metadata.extensions`` as a plain dict (empty when absent)."""
    meta = getattr(component, "metadata", None)
    exts = getattr(meta, "extensions", None)
    return dict(getattr(exts, "root", None) or {})


def _text(component: Any) -> str | None:
    """The literal ``text`` prop of a Text component (None when bound/absent)."""
    value = (component.model_extra or {}).get("text")
    return value if isinstance(value, str) else None


class A2UIExtractor:
    """Convert an A2UI v1.0 ``createSurface`` into a ``FormSchema`` (strict or heuristic)."""

    def __init__(
        self,
        *,
        default_section_id: str = "fields",
        max_components: int = A2UI_MAX_COMPONENTS,
        max_depth: int = A2UI_MAX_DEPTH,
    ) -> None:
        self.logger = logging.getLogger(__name__)
        self.default_section_id = default_section_id
        self.max_components = max_components
        self.max_depth = max_depth

    def extract(
        self,
        surface: Any,
        *,
        form_id: str | None = None,
        title: str | None = None,
        tenant: str | None = None,
    ) -> ExtractedForm:
        """Parse, validate (S6), walk, build.

        Args:
            surface: A ``createSurface`` envelope (dict, JSON str/bytes or ``CreateSurface``).
            form_id: Override for the resulting ``form_id``.
            title: Override for the resulting form title.
            tenant: Tenant stamped on the form (never read from the surface).

        Returns:
            The extracted form with warnings and dropped components.

        Raises:
            ValueError: Non-surface, invalid or oversized payload.
        """
        m = _a2ui_ns()
        cs = self._parse(surface, m)
        if len(cs.components) > self.max_components:
            raise ValueError(f"surface has {len(cs.components)} components > max {self.max_components}")
        try:
            m.validate_envelope(cs, origin=m.ProducerOrigin.TOOL)
        except m.CatalogValidationError as exc:
            raise ValueError(f"invalid surface: {exc}") from exc
        by_id = {c.id: c for c in cs.components}
        root = by_id.get("root")
        if root is None:
            raise ValueError("surface has no 'root' component")
        warnings: list[str] = []
        dropped: list[DroppedComponent] = []
        strict = _ext(root).get("parrot_variant") == "form"
        mode = ExtractionMode.STRICT if strict else ExtractionMode.HEURISTIC
        if strict:
            warnings.append(_STRICT_WARNING)
        data_model = cs.data_model if isinstance(cs.data_model, dict) else {}
        reached: set[str] = set()
        self._seen_field_ids: set[str] = set()
        # sections_meta[sid] = {"title": str|None, "order": [FormField | ssid]}
        sections_meta: dict[str, dict[str, Any]] = {}
        # subsections_meta[(sid, ssid)] = {"title": str|None, "fields": [FormField]}
        subsections_meta: dict[tuple[str, str], dict[str, Any]] = {}
        state: dict[str, Any] = {"title": None, "description": None, "cancel": False, "hints": {}}

        def section(sid: str) -> dict[str, Any]:
            return sections_meta.setdefault(sid, {"title": None, "order": []})

        def subsection(sid: str, ssid: str) -> dict[str, Any]:
            key = (sid, ssid)
            if key not in subsections_meta:
                subsections_meta[key] = {"title": None, "fields": []}
                section(sid)["order"].append(ssid)
            return subsections_meta[key]

        def first_text_descendant(component: Any) -> tuple[str, str] | None:
            """Find the first literal Text descendant in depth-first order."""
            pending = list(reversed(_component_children(component)))
            visited: set[str] = set()
            while pending:
                child_id = pending.pop()
                if child_id in visited or child_id not in by_id:
                    continue
                visited.add(child_id)
                child = by_id[child_id]
                if child.component == "Text":
                    value = _text(child)
                    if value is not None:
                        return child_id, value
                pending.extend(reversed(_component_children(child)))
            return None

        inferred_labels: dict[str, tuple[str, str]] = {}
        consumed_text_ids: set[str] = set()
        tab_sections: dict[str, str] = {}
        for parent in by_id.values():
            children = _component_children(parent)
            for previous_id, next_id in zip(children, children[1:], strict=False):
                previous = by_id.get(previous_id)
                next_component = by_id.get(next_id)
                next_props = dict(next_component.model_extra or {}) if next_component else {}
                if (
                    previous is not None
                    and previous.component == "Text"
                    and next_component is not None
                    and next_component.component in _INPUTS
                    and not next_props.get("label")
                ):
                    label = _text(previous)
                    if label is not None:
                        inferred_labels[next_id] = (previous_id, label)

        def card_of(ancestors: list[str]) -> str | None:
            for aid in reversed(ancestors):
                if aid.startswith("sec-") and by_id[aid].component == "Card":
                    return aid[4:]
            return None

        for comp, ancestors in self._walk(root, by_id, reached, dropped, warnings):
            if comp.id == "root":
                continue
            ext = _ext(comp)
            role = ext.get("parrot_role")
            cid = comp.id
            if mode is ExtractionMode.HEURISTIC:
                if comp.component == "Card":
                    section_id = cid.removeprefix("sec-")
                    section_meta = section(section_id)
                    text = first_text_descendant(comp)
                    if text is not None:
                        section_meta["title"] = text[1]
                        consumed_text_ids.add(text[0])
                    continue
                if comp.component == "TabItem":
                    text = first_text_descendant(comp)
                    section_meta = section(cid)
                    if text is not None:
                        section_meta["title"] = text[1]
                        consumed_text_ids.add(text[0])
                    warnings.append("tabs_flattened") if "tabs_flattened" not in warnings else None
                    continue
                if comp.component == "Tabs":
                    warnings.append("tabs_flattened") if "tabs_flattened" not in warnings else None
                    for tab in (comp.model_extra or {}).get("tabs") or []:
                        if not isinstance(tab, dict) or not isinstance(tab.get("child"), str):
                            continue
                        child_id = tab["child"]
                        tab_sections[child_id] = child_id
                        section_meta = section(child_id)
                        title_value = tab.get("title")
                        if isinstance(title_value, str):
                            section_meta["title"] = title_value
                        text = first_text_descendant(by_id[child_id]) if child_id in by_id else None
                        if text is not None:
                            section_meta["title"] = section_meta["title"] or text[1]
                            consumed_text_ids.add(text[0])
                    continue
                if comp.component in {"Column", "Row"}:
                    first_child = _component_children(comp)[:1]
                    in_card = next((aid for aid in reversed(ancestors) if by_id[aid].component == "Card"), None)
                    if in_card and first_child and by_id[first_child[0]].component == "Text":
                        sid = in_card.removeprefix("sec-")
                        ssid = cid
                        title_text = _text(by_id[first_child[0]])
                        subsection_meta = subsection(sid, ssid)
                        subsection_meta["title"] = title_text
                        consumed_text_ids.add(first_child[0])
                    continue
                if comp.component == "Text":
                    if cid in consumed_text_ids or cid in {text_id for text_id, _ in inferred_labels.values()}:
                        continue
                    dropped.append(DroppedComponent(component_id=cid, component=comp.component, reason="unsupported_component"))
                    continue
                if comp.component == "Button":
                    event = getattr(getattr(comp.action, "event", None), "name", None)
                    if event == "form.cancel":
                        state["cancel"] = True
                    elif event != "form.submit":
                        dropped.append(
                            DroppedComponent(component_id=cid, component=comp.component, reason="unsupported_component")
                        )
                    continue
                if comp.component in _INPUTS:
                    field_props = dict(comp.model_extra or {})
                    inferred = inferred_labels.get(cid)
                    if inferred is not None:
                        field_props["label"] = inferred[1]
                        warning = f"label_inferred_from_text:{cid}"
                        if warning not in warnings:
                            warnings.append(warning)
                    field = self._field_from_component(comp, mode, data_model, warnings, dropped, props=field_props)
                    if field is None:
                        continue
                    tab_id = next(
                        (aid for aid in reversed(ancestors) if aid in tab_sections),
                        next((aid for aid in reversed(ancestors) if by_id[aid].component == "TabItem"), None),
                    )
                    card_id = next((aid for aid in reversed(ancestors) if by_id[aid].component == "Card"), None)
                    if tab_id:
                        section(tab_id)["order"].append(field)
                    elif card_id:
                        sid = card_id.removeprefix("sec-")
                        ssid = next(
                            (
                                aid
                                for aid in reversed(ancestors)
                                if (sid, aid) in subsections_meta
                            ),
                            None,
                        )
                        if ssid:
                            subsection(sid, ssid)["fields"].append(field)
                        else:
                            section(sid)["order"].append(field)
                    else:
                        section(self.default_section_id)["order"].append(field)
                    continue
                dropped.append(
                    DroppedComponent(
                        component_id=cid,
                        component=comp.component,
                        reason="unsupported_component" if comp.component in _UNSUPPORTED else "not_in_basic_catalog",
                    )
                )
                continue
            if mode is ExtractionMode.STRICT:
                if comp.component == "Card" and cid.startswith("sec-"):
                    section(cid[4:])
                    continue
                if comp.component == "Column" and cid.startswith("sub-"):
                    sid = card_of(ancestors) or self.default_section_id
                    subsection(sid, cid[4:])
                    continue
                if comp.component == "Text" and role == "title":
                    if cid == "root-title":
                        state["title"] = _text(comp)
                    elif cid.startswith("sec-") and cid.endswith("-title"):
                        section(cid[4:-6])["title"] = _text(comp)
                    elif cid.startswith("sub-") and cid.endswith("-title"):
                        sid = card_of(ancestors) or self.default_section_id
                        subsection(sid, cid[4:-6])["title"] = _text(comp)
                    continue
                if comp.component == "Text" and role == "description" and cid == "root-description":
                    state["description"] = _text(comp)
                    continue
                if comp.component == "Text" and role == "hint":
                    state["hints"][ext.get("parrot_field_id")] = _text(comp)
                    continue
                if comp.component == "Text" and role in _SILENT_ROLES:
                    continue
                if cid == "root-cancel" and comp.component == "Button":
                    state["cancel"] = True
                    continue
                if comp.component in _CONTAINERS or cid in ("root-submit", "root-submit-label", "root-cancel-label"):
                    continue
                is_field = comp.component in _INPUT_PRIMITIVES or "parrot_field_type" in ext or role == "notice"
                if not is_field:
                    dropped.append(
                        DroppedComponent(component_id=cid, component=comp.component, reason="unsupported_component")
                    )
                    continue
            else:
                if comp.component in _CONTAINERS:
                    continue
                if comp.component == "Button" and cid == "root-cancel":
                    state["cancel"] = True
                    continue
            field = self._field_from_component(comp, mode, data_model, warnings, dropped)
            if field is None:
                continue
            sid = ext.get("parrot_section_id") or card_of(ancestors) or self.default_section_id
            ssid = ext.get("parrot_subsection_id")
            if ssid:
                subsection(sid, ssid)["fields"].append(field)
            else:
                section(sid)["order"].append(field)
        for cid in sorted(set(by_id) - reached):
            dropped.append(DroppedComponent(component_id=cid, component=by_id[cid].component, reason="unreachable"))
        if state["hints"]:
            every = [i for sec in sections_meta.values() for i in sec["order"] if isinstance(i, FormField)]
            for sub in subsections_meta.values():
                every.extend(sub["fields"])
            for item in every:
                hint = state["hints"].get(item.field_id)
                if hint and item.hint is None:
                    item.hint = hint
        form = self._build_form(root, mode, form_id, title, tenant, sections_meta, subsections_meta, state, warnings)
        return ExtractedForm(form=resolve_rule_references(form), mode=mode, warnings=warnings, dropped=dropped)

    def _parse(self, surface: Any, m: Any) -> Any:
        """dict/str/bytes/CreateSurface → CreateSurface (ValueError when it is not a createSurface)."""
        if isinstance(surface, m.CreateSurface):
            return surface
        try:
            parsed = m.deserialize(
                surface
            )  # legacy payloads emit DeprecationWarning → surfaced by the caller's warnings
        except (ValueError, TypeError) as exc:
            raise ValueError(f"payload is not an A2UI createSurface envelope: {exc}") from exc
        msg = parsed[0] if isinstance(parsed, list) and parsed else parsed
        cs = getattr(msg, "create_surface", None)
        if cs is None:
            raise ValueError("payload is not an A2UI createSurface envelope")
        return cs

    def _walk(
        self,
        root: Any,
        by_id: dict[str, Any],
        reached: set[str],
        dropped: list[DroppedComponent],
        warnings: list[str],
    ) -> Iterator[tuple[Any, list[str]]]:
        """Depth-first from root; cycles → dropped("cycle"); depth > max_depth → ValueError."""
        stack: list[tuple[str, list[str]]] = [(root.id, [])]
        while stack:
            cid, ancestors = stack.pop()
            if cid in reached:
                dropped.append(DroppedComponent(component_id=cid, component=by_id[cid].component, reason="cycle"))
                warnings.append(f"cycle_at:{cid}")
                continue
            if len(ancestors) > self.max_depth:
                raise ValueError(f"surface nesting exceeds max depth {self.max_depth}")
            reached.add(cid)
            comp = by_id[cid]
            yield comp, ancestors
            kids = _component_children(comp)
            children = comp.children
            if children is not None and not isinstance(children, list):
                tpl_id = getattr(children, "component_id", None)
                if tpl_id is not None:
                    tpl = by_id.get(tpl_id)
                    reached.add(tpl_id)
                    dropped.append(
                        DroppedComponent(
                            component_id=tpl_id,
                            component=tpl.component if tpl is not None else "unknown",
                            reason="no_binding",
                        )
                    )
            for kid in reversed(kids):
                stack.append((kid, [*ancestors, cid]))

    def _field_from_component(
        self,
        comp: Any,
        mode: ExtractionMode,
        data_model: dict[str, Any],
        warnings: list[str],
        dropped: list[DroppedComponent],
        props: dict[str, Any] | None = None,
    ) -> FormField | None:
        """Strict: parrot_* extensions decide identity/type; missing → heuristic hook (warning)."""
        ext = _ext(comp)
        props = props if props is not None else dict(comp.model_extra or {})
        raw_type = ext.get("parrot_field_type")
        if mode is ExtractionMode.STRICT and raw_type in {t.value for t in FieldType}:
            from ..renderers.a2ui import FIELD_LOWERING  # lazy: keep module import light
            from ..renderers import a2ui as _r

            field_type = FieldType(raw_type)
            lowering = FIELD_LOWERING[field_type]
            expected = lowering.primitive
            is_notice = ext.get("parrot_role") == "notice"
            if not is_notice and expected not in (comp.component, "hidden") and expected != "notice":
                warnings.append(f"strict_primitive_mismatch:{comp.id}")
            field_id = ext.get("parrot_field_id") or comp.id.removeprefix("f-")
            label = props.get("label")
            if is_notice:
                warnings.append(f"degraded_field_restored:{comp.id}")
                text = props.get("text") if isinstance(props.get("text"), str) else None
                if text:
                    label = text.removesuffix(": not available on this surface")
            # checks -> required / constraints
            required = False
            cons: dict[str, Any] = {}
            default_patterns = {_r._DEFAULT_URL_PATTERN, _r._DEFAULT_PHONE_PATTERN}
            for check in comp.checks or []:
                cond = check.condition
                call = getattr(cond, "call", None)
                args = getattr(cond, "args", None) or {}
                if call == "required":
                    required = True
                elif call == "regex":
                    pattern = args.get("pattern")
                    if pattern and not ("regex" in lowering.check_functions and pattern in default_patterns):
                        cons["pattern"] = pattern
                        if check.message:
                            cons.setdefault("pattern_message", check.message)
                elif call == "length":
                    if args.get("min") is not None:
                        cons["min_length"] = args["min"]
                    if args.get("max") is not None:
                        cons["max_length"] = args["max"]
                elif call == "numeric":
                    if args.get("min") is not None:
                        cons["min_value"] = args["min"]
                    if args.get("max") is not None:
                        cons["max_value"] = args["max"]
            # pattern_message is the renderer's own fallback text when absent; only keep an authored-looking one
            if "pattern_message" in cons and cons["pattern_message"].endswith("has an invalid format."):
                cons.pop("pattern_message")
            constraints = FieldConstraints(**cons) if cons else None
            options: list[FieldOption] = []
            if comp.component == "ChoicePicker":
                for opt in props.get("options") or []:
                    if isinstance(opt, dict) and "value" in opt:
                        options.append(FieldOption(value=str(opt["value"]), label=str(opt.get("label", opt["value"]))))
            answers = data_model.get("answers") if isinstance(data_model.get("answers"), dict) else {}
            default = answers.get(field_id)
            if default in (None, []):
                default = None
            field_uid = ext.get("parrot_field_uid")
            try:
                field_uid = uuid.UUID(str(field_uid)) if field_uid else None
            except ValueError:
                warnings.append(f"invalid_field_uid:{comp.id}")
                field_uid = None
            kwargs: dict[str, Any] = {}
            if field_uid is not None:
                kwargs["field_uid"] = field_uid
            placeholder = props.get("placeholder") if comp.component == "TextField" else None
            return FormField(
                field_id=field_id,
                field_type=field_type,
                label=label or str(field_id),
                required=required,
                read_only=bool(ext.get("parrot_read_only", False)),
                placeholder=placeholder if isinstance(placeholder, str) else None,
                options=options or None,
                constraints=constraints,
                default=default,
                **kwargs,
            )
        if mode is ExtractionMode.STRICT:
            warnings.append(f"strict_missing_extension:{comp.id}")
        return self._heuristic_field(comp, props, data_model, warnings, dropped)

    def _heuristic_field(
        self,
        comp: Any,
        props: dict[str, Any],
        data_model: dict[str, Any],
        warnings: list[str],
        dropped: list[DroppedComponent],
    ) -> FormField | None:
        """Map a Basic Catalog input into a lossy :class:`FormField`."""
        if comp.component in _UNSUPPORTED or comp.component not in _INPUTS:
            reason = (
                "unsupported_component"
                if comp.component in _UNSUPPORTED
                or comp.component in {"Text", "Button", "Card", "Column", "Row", "Tabs", "TabItem"}
                else "not_in_basic_catalog"
            )
            dropped.append(DroppedComponent(component_id=comp.id, component=comp.component, reason=reason))
            return None
        from ..renderers.a2ui import field_id_from_pointer_token

        key = _primitive_key(comp, props)
        field_type = HEURISTIC_PRIMITIVE_MAP.get(key, HEURISTIC_PRIMITIVE_MAP.get(comp.component, FieldType.TEXT))
        binding = props.get("value")
        if isinstance(binding, dict) and isinstance(binding.get("path"), str) and binding["path"].startswith("/answers/"):
            field_id = field_id_from_pointer_token(binding["path"].rsplit("/", 1)[-1])
            default = (data_model.get("answers") or {}).get(field_id)
        else:
            field_id = comp.id.removeprefix("f-")
            default = binding if not isinstance(binding, dict) else None
            warnings.append(f"no_binding:{comp.id}")
        field_id = self._unique_field_id(field_id, warnings)
        required = False
        constraints = FieldConstraints()
        for rule in comp.checks or []:
            condition = rule.condition
            call = getattr(condition, "call", None)
            args = getattr(condition, "args", None) or {}
            if call == "required":
                required = True
            elif call == "regex":
                constraints.pattern = args.get("pattern")
            elif call == "length":
                constraints.min_length = args.get("min")
                constraints.max_length = args.get("max")
            elif call == "numeric":
                constraints.min_value = args.get("min")
                constraints.max_value = args.get("max")
            elif call == "email" and comp.component == "TextField":
                field_type = FieldType.EMAIL
        if comp.component == "Slider":
            constraints.min_value = float(props.get("min", 0))
            constraints.max_value = float(props["max"]) if "max" in props else None
            steps = props.get("steps")
            if steps and constraints.max_value is not None:
                constraints.step = (constraints.max_value - constraints.min_value) / float(steps)
        if comp.component == "DateTimeInput" and (props.get("min") is not None or props.get("max") is not None):
            warnings.append(f"datetime_bounds_dropped:{comp.id}")
        options = [
            FieldOption(value=str(option.get("value")), label=option.get("label") or str(option.get("value")))
            for option in props.get("options") or []
            if isinstance(option, dict)
        ] or None
        has_constraints = any(value is not None for value in constraints.model_dump().values())
        return FormField(
            field_id=field_id,
            field_type=field_type,
            label=props.get("label") or field_id.replace("_", " ").title(),
            required=required,
            placeholder=props.get("placeholder") if comp.component == "TextField" else None,
            options=options,
            constraints=constraints if has_constraints else None,
            default=default,
        )

    def _unique_field_id(self, field_id: str, warnings: list[str]) -> str:
        """Suffix field-id collisions deterministically and report the loss."""
        seen = self._seen_field_ids
        if field_id not in seen:
            seen.add(field_id)
            return field_id
        suffix = 2
        while f"{field_id}_{suffix}" in seen:
            suffix += 1
        warnings.append(f"field_id_collision:{field_id}")
        unique_id = f"{field_id}_{suffix}"
        seen.add(unique_id)
        return unique_id

    def _build_form(
        self,
        root: Any,
        mode: ExtractionMode,
        form_id: str | None,
        title: str | None,
        tenant: str | None,
        sections_meta: dict[str, dict[str, Any]],
        subsections_meta: dict[tuple[str, str], dict[str, Any]],
        state: dict[str, Any],
        warnings: list[str],
    ) -> FormSchema:
        """Assemble sections (empty ones survive — ids come from Cards) and the FormSchema identity."""
        ext = _ext(root)
        sections: list[FormSection] = []
        for sid, meta in sections_meta.items():
            items: list[Any] = []
            for entry in meta["order"]:
                if isinstance(entry, FormField):
                    items.append(entry)
                else:
                    sub = subsections_meta[(sid, entry)]
                    items.append(FormSubsection(subsection_id=entry, title=sub["title"], fields=sub["fields"]))
            sections.append(FormSection(section_id=sid, title=meta["title"], fields=items))
        if not sections:
            sections.append(FormSection(section_id=self.default_section_id, fields=[]))
        kwargs: dict[str, Any] = {}
        if mode is ExtractionMode.STRICT and ext.get("parrot_form_uid"):
            try:
                kwargs["form_uid"] = uuid.UUID(str(ext["parrot_form_uid"]))
            except ValueError:
                warnings.append("invalid_form_uid")
        resolved_id = form_id or (ext.get("parrot_form_id") if mode is ExtractionMode.STRICT else None) or "form"
        version = (ext.get("parrot_form_version") if mode is ExtractionMode.STRICT else None) or "1.0"
        return FormSchema(
            form_id=resolved_id,
            version=str(version),
            title=title or state["title"] or resolved_id,
            description=state["description"],
            sections=sections,
            cancel_allowed=bool(state["cancel"]),
            tenant=tenant,
            **kwargs,
        )
