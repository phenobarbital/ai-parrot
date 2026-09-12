"""A2UIFormRenderer — lowers a FormSchema into an A2UI v1.0 createSurface envelope.

Spec: ``sdd/specs/a2ui-form-output-renderer.spec.md`` (FEAT-544), §3 Module 1.

``ai-parrot`` (and therefore ``parrot.outputs.a2ui``) is an OPTIONAL
dependency of parrot-formdesigner (see ``pyproject.toml``'s ``ai-parrot``
extra) — every ``parrot.*`` symbol this module needs is imported lazily,
inside :func:`_a2ui_ns`, so ``import parrot_formdesigner.renderers.a2ui``
never fails (or pulls ai-parrot) when the extra is not installed.

Field lowering (TASK-3072) is table-driven: :data:`FIELD_LOWERING` maps every
``FieldType`` to a Basic Catalog primitive (``TextField``/``CheckBox``/
``ChoicePicker``/``Slider``/``DateTimeInput``), to ``"hidden"`` (dataModel
only, no component), or to ``"notice"`` — an honest degradation to a ``Text``
notice + a ``RenderWarning`` for the FieldTypes Basic cannot express (spec §7,
hybrid decision U3). Rendering never raises for any ``FieldType``.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

from ..core.options import FieldOption
from ..core.schema import (
    FormField,
    FormSchema,
    FormSection,
    FormSubsection,
    RenderedForm,
    RenderWarning,
)
from ..core.style import StyleSchema
from ..core.types import FieldType, LocalizedString
from .base import AbstractFormRenderer

logger = logging.getLogger(__name__)

#: Default submit URL template — ``{tenant}``/``{form_uid}`` are filled in per-render.
DEFAULT_SUBMIT_URL_TEMPLATE = "/api/v1/{tenant}/forms/{form_uid}/data"

#: Fallback tenant slug used when ``form.tenant`` is unset.
_DEFAULT_TENANT = "public"


def _resolve(value: LocalizedString | None, locale: str = "en") -> str:
    """Resolve a LocalizedString to a plain string.

    Copied from ``renderers/adaptive_card.py:_resolve`` (module-private
    pattern; not shared via import — see spec §6 "Does NOT Exist").

    Args:
        value: str or dict with locale keys.
        locale: BCP 47 locale tag.

    Returns:
        Resolved string, or empty string if None.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if locale in value:
        return value[locale]
    lang = locale.split("-")[0]
    if lang in value:
        return value[lang]
    if "en" in value:
        return value["en"]
    return next(iter(value.values()), "")


def field_pointer(field_id: str) -> str:
    """Build the ``/answers/...`` JSON Pointer a field's value is bound at.

    Escapes RFC 6901 special characters in ``field_id`` — ``~`` -> ``~0``
    first, then ``/`` -> ``~1`` — before appending it to the ``/answers/``
    prefix.

    Args:
        field_id: The form field's ``field_id``.

    Returns:
        A well-formed JSON Pointer, e.g. ``"/answers/a~1b"`` for ``"a/b"``.
    """
    escaped = field_id.replace("~", "~0").replace("/", "~1")
    return f"/answers/{escaped}"


def field_id_from_pointer_token(token: str) -> str:
    """Inverse of :func:`field_pointer`'s escaping (RFC 6901 token unescape).

    Args:
        token: An escaped pointer reference token (e.g. ``"a~1b"``).

    Returns:
        The original, unescaped ``field_id`` (e.g. ``"a/b"``).
    """
    return token.replace("~1", "/").replace("~0", "~")


def _a2ui_ns() -> Any:
    """Lazily import the ai-parrot A2UI stack this renderer depends on.

    Returns:
        A namespace object exposing the required ``parrot.outputs.a2ui`` /
        ``parrot.a2a`` symbols as attributes.

    Raises:
        RuntimeError: If ``ai-parrot`` (the optional extra) is not installed.
    """
    try:
        from parrot.a2a.models import A2UI_MEDIA_TYPE
        from parrot.outputs.a2ui.catalog import validate_envelope
        from parrot.outputs.a2ui.catalog.base import DEFAULT_CATALOG_ID, ProducerOrigin
        from parrot.outputs.a2ui.models import (
            Action,
            CheckRule,
            Component,
            ComponentMetadata,
            CreateSurface,
            EventAction,
            Extensions,
            FunctionCall,
            is_valid_pointer,
        )
        from parrot.outputs.a2ui.serialization import serialize
    except ImportError as exc:
        raise RuntimeError("A2UIFormRenderer requires the 'ai-parrot' extra") from exc

    class _A2UINamespace:
        pass

    ns = _A2UINamespace()
    ns.A2UI_MEDIA_TYPE = A2UI_MEDIA_TYPE
    ns.validate_envelope = validate_envelope
    ns.DEFAULT_CATALOG_ID = DEFAULT_CATALOG_ID
    ns.ProducerOrigin = ProducerOrigin
    ns.Action = Action
    ns.CheckRule = CheckRule
    ns.Component = Component
    ns.ComponentMetadata = ComponentMetadata
    ns.CreateSurface = CreateSurface
    ns.EventAction = EventAction
    ns.Extensions = Extensions
    ns.FunctionCall = FunctionCall
    ns.is_valid_pointer = is_valid_pointer
    ns.serialize = serialize
    return ns


class A2UIFieldLowering(BaseModel):
    """How one ``FieldType`` lowers to a Basic Catalog primitive (or degrades).

    Attributes:
        primitive: The Basic Catalog component name, or ``"notice"`` for an
            honest degradation, or ``"hidden"`` for a dataModel-only field
            (no component emitted).
        props: Extra wire kwargs merged onto the constructed ``Component``
            (e.g. ``{"variant": "longText"}``, ``{"enableDate": True}``).
        check_functions: Extra Basic check functions always attached to this
            FieldType's ``checks`` (e.g. ``("email",)`` for EMAIL),
            independent of ``FieldConstraints``.
    """

    primitive: Literal["TextField", "CheckBox", "ChoicePicker", "Slider", "DateTimeInput", "notice", "hidden"]
    props: dict[str, Any] = Field(default_factory=dict)
    check_functions: tuple[str, ...] = ()


#: Conservative default `regex` patterns for URL/PHONE when the field has no
#: `pattern` constraint of its own (spec §8 Open Question, non-blocking).
_DEFAULT_URL_PATTERN = r"^https?://\S+$"
_DEFAULT_PHONE_PATTERN = r"^\+?[0-9()\-\s]{7,20}$"

#: Default Slider ``max`` per scale FieldType when `scale_max` is unset
#: (spec §7 implementation notes — "fallback 10 / NPS 10 / LIKERT 5").
_SLIDER_DEFAULT_MAX: dict[FieldType, float] = {
    FieldType.NPS: 10,
    FieldType.LIKERT: 5,
    FieldType.RANKING: 10,
}

#: FieldTypes that lower to ``ChoicePicker(variant="multipleSelection")`` —
#: their dataModel default is ``[]`` (not ``None``) when unset (spec §7
#: implementation notes).
_MULTI_SELECT_TYPES: frozenset[FieldType] = frozenset(
    {FieldType.MULTI_SELECT, FieldType.TAGS, FieldType.TRANSFER_LIST}
)

#: FieldType -> Basic primitive lowering table (spec §7, normative). Covers
#: every member of ``FieldType`` (45 as of this writing — see TASK-3072
#: Completion Note re: the spec's "47" figure) by construction; a future
#: FieldType addition without an entry here fails the module-level assertion
#: below, loudly, at import time.
FIELD_LOWERING: dict[FieldType, A2UIFieldLowering] = {
    # -- Text family --------------------------------------------------------
    FieldType.TEXT: A2UIFieldLowering(primitive="TextField", props={"variant": "shortText"}),
    FieldType.SEARCH: A2UIFieldLowering(primitive="TextField", props={"variant": "shortText"}),
    FieldType.MASKED: A2UIFieldLowering(primitive="TextField", props={"variant": "shortText"}),
    FieldType.COLOR: A2UIFieldLowering(primitive="TextField", props={"variant": "shortText"}),
    FieldType.COLOR_PICKER: A2UIFieldLowering(primitive="TextField", props={"variant": "shortText"}),
    FieldType.TEXT_AREA: A2UIFieldLowering(primitive="TextField", props={"variant": "longText"}),
    FieldType.NUMBER: A2UIFieldLowering(primitive="TextField", props={"variant": "number"}),
    FieldType.INTEGER: A2UIFieldLowering(primitive="TextField", props={"variant": "number"}),
    FieldType.PASSWORD: A2UIFieldLowering(primitive="TextField", props={"variant": "obscured"}),
    FieldType.EMAIL: A2UIFieldLowering(
        primitive="TextField", props={"variant": "shortText"}, check_functions=("email",)
    ),
    FieldType.URL: A2UIFieldLowering(
        primitive="TextField", props={"variant": "shortText"}, check_functions=("regex",)
    ),
    FieldType.PHONE: A2UIFieldLowering(
        primitive="TextField", props={"variant": "shortText"}, check_functions=("regex",)
    ),
    # -- Boolean --------------------------------------------------------------
    FieldType.BOOLEAN: A2UIFieldLowering(primitive="CheckBox"),
    # -- Date/time ------------------------------------------------------------
    FieldType.DATE: A2UIFieldLowering(primitive="DateTimeInput", props={"enableDate": True}),
    FieldType.TIME: A2UIFieldLowering(primitive="DateTimeInput", props={"enableTime": True}),
    FieldType.DATETIME: A2UIFieldLowering(primitive="DateTimeInput", props={"enableDate": True, "enableTime": True}),
    # -- Choice family ----------------------------------------------------------
    FieldType.SELECT: A2UIFieldLowering(primitive="ChoicePicker", props={"variant": "mutuallyExclusive"}),
    FieldType.DYNAMIC_SELECT: A2UIFieldLowering(primitive="ChoicePicker", props={"variant": "mutuallyExclusive"}),
    FieldType.MULTI_SELECT: A2UIFieldLowering(primitive="ChoicePicker", props={"variant": "multipleSelection"}),
    FieldType.TAGS: A2UIFieldLowering(
        primitive="ChoicePicker", props={"variant": "multipleSelection", "displayStyle": "chips"}
    ),
    FieldType.TRANSFER_LIST: A2UIFieldLowering(primitive="ChoicePicker", props={"variant": "multipleSelection"}),
    # -- Scale family (NPS / LIKERT / RANKING) -> Slider ----------------------
    FieldType.NPS: A2UIFieldLowering(primitive="Slider"),
    FieldType.LIKERT: A2UIFieldLowering(primitive="Slider"),
    FieldType.RANKING: A2UIFieldLowering(primitive="Slider"),
    # -- dataModel-only --------------------------------------------------------
    FieldType.HIDDEN: A2UIFieldLowering(primitive="hidden"),
    # -- Degraded: no A2UI v1.0 primitive (honest "notice" + RenderWarning) --
    FieldType.FILE: A2UIFieldLowering(primitive="notice"),
    FieldType.IMAGE: A2UIFieldLowering(primitive="notice"),
    FieldType.GROUP: A2UIFieldLowering(primitive="notice"),
    FieldType.ARRAY: A2UIFieldLowering(primitive="notice"),
    FieldType.SIGNATURE: A2UIFieldLowering(primitive="notice"),
    FieldType.REMOTE_RESPONSE: A2UIFieldLowering(primitive="notice"),
    FieldType.AVAILABILITY: A2UIFieldLowering(primitive="notice"),
    FieldType.LOCATION: A2UIFieldLowering(primitive="notice"),
    FieldType.REST: A2UIFieldLowering(primitive="notice"),
    FieldType.AUDIO: A2UIFieldLowering(primitive="notice"),
    FieldType.FORMULA: A2UIFieldLowering(primitive="notice"),
    FieldType.EMOJI: A2UIFieldLowering(primitive="notice"),
    FieldType.CRON: A2UIFieldLowering(primitive="notice"),
    FieldType.TREE_SELECT: A2UIFieldLowering(primitive="notice"),
    FieldType.SIGNATURE_PAD: A2UIFieldLowering(primitive="notice"),
    FieldType.CREDIT_CARD: A2UIFieldLowering(primitive="notice"),
    FieldType.IMAGE_DROPZONE: A2UIFieldLowering(primitive="notice"),
    FieldType.MULTI_UPLOAD: A2UIFieldLowering(primitive="notice"),
    FieldType.AI_CAPTURE: A2UIFieldLowering(primitive="notice"),
    FieldType.PLACE: A2UIFieldLowering(primitive="notice"),
}

assert set(FIELD_LOWERING) == set(FieldType), (
    "FIELD_LOWERING is missing an entry for: " f"{sorted(t.value for t in set(FieldType) - set(FIELD_LOWERING))}"
)


def _choice_options(options: list[FieldOption] | None, locale: str) -> list[dict[str, Any]]:
    """Build ``ChoicePicker.options`` from ``FieldOption``s, skipping disabled ones.

    Args:
        options: The field's static options, or ``None``.
        locale: BCP 47 locale tag for label resolution.

    Returns:
        A list of ``{"label", "value"}`` dicts for every non-disabled option.
    """
    if not options:
        return []
    return [{"label": _resolve(option.label, locale), "value": option.value} for option in options if not option.disabled]


def _extensions(m: Any, **values: Any) -> Any:
    """Build a ``ComponentMetadata(extensions=...)`` from keyword values.

    Args:
        m: The namespace returned by :func:`_a2ui_ns`.
        **values: The ``parrot_*`` extension key/value pairs.

    Returns:
        A ``ComponentMetadata`` instance wrapping an ``Extensions`` root model.
    """
    return m.ComponentMetadata(extensions=m.Extensions(values))


class A2UIFormRenderer(AbstractFormRenderer):
    """Lower a ``FormSchema`` into an A2UI v1.0 ``createSurface`` envelope.

    The resulting surface is composed exclusively of Basic Catalog
    primitives (``Column``, ``Row``, ``Card``, ``Text``, ``Button``, plus the
    per-field input primitives added by TASK-3072) — no ``Form`` catalog
    component is ever emitted (A2UI dialect spec G6). ai-parrot semantics
    (form/field identity) ride exclusively in ``metadata.extensions.parrot_*``.

    Attributes:
        submit_url_template: ``str.format`` template for the submit URL,
            filled in with ``tenant`` and ``form_uid`` per render.
        catalog_id: Override for the surface's default ``catalogId``.
            ``None`` (default) uses ``DEFAULT_CATALOG_ID``.
    """

    RENDERER_NAME: ClassVar[str] = "a2ui"

    def __init__(
        self,
        *,
        submit_url_template: str = DEFAULT_SUBMIT_URL_TEMPLATE,
        catalog_id: str | None = None,
    ) -> None:
        """Initialize the renderer.

        Args:
            submit_url_template: ``str.format`` template with ``{tenant}``
                and ``{form_uid}`` placeholders for the submit Button's
                ``context.submit_url``.
            catalog_id: Override for the surface's default ``catalogId``.
        """
        self.logger = logging.getLogger(__name__)
        self.submit_url_template = submit_url_template
        self.catalog_id = catalog_id
        self._m: Any = None

    async def render(
        self,
        form: FormSchema,
        style: StyleSchema | None = None,
        *,
        locale: str = "en",
        prefilled: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> RenderedForm:
        """Render a ``FormSchema`` into an A2UI v1.0 ``createSurface`` envelope.

        Args:
            form: The form schema to render.
            style: Optional style configuration. Defaults to ``StyleSchema()``.
            locale: BCP 47 locale tag for i18n label resolution.
            prefilled: Pre-filled field values (field_id -> value).
            errors: Validation errors to display (field_id -> message).

        Returns:
            A ``RenderedForm`` whose ``content`` is the serialized
            ``createSurface`` envelope (``content_type ==
            "application/a2ui+json"``).
        """
        m = _a2ui_ns()
        self._m = m
        try:
            style = style or StyleSchema()
            prefilled = prefilled or {}
            errors = errors or {}

            tenant = form.tenant or _DEFAULT_TENANT
            submit_url = self.submit_url_template.format(tenant=tenant, form_uid=str(form.form_uid))
            catalog_id = self.catalog_id or m.DEFAULT_CATALOG_ID

            root_children: list[str] = []
            components: list[Any] = []
            warnings: list[RenderWarning] = []
            degraded: list[dict[str, Any]] = []
            field_paths: dict[str, str] = {}
            data_model_answers: dict[str, Any] = {}
            data_model_errors: dict[str, Any] = {}

            title_text = _resolve(form.title, locale)
            if title_text:
                components.append(
                    m.Component(
                        id="root-title",
                        component="Text",
                        text=title_text,
                        metadata=_extensions(m, parrot_role="title"),
                    )
                )
                root_children.append("root-title")

            description_text = _resolve(form.description, locale)
            if description_text:
                components.append(
                    m.Component(
                        id="root-description",
                        component="Text",
                        text=description_text,
                        metadata=_extensions(m, parrot_role="description"),
                    )
                )
                root_children.append("root-description")

            for section in form.sections:
                section_components, card_id = self._lower_section(
                    section,
                    locale,
                    errors,
                    prefilled,
                    data_model_answers,
                    data_model_errors,
                    field_paths,
                    degraded,
                    warnings,
                )
                components.extend(section_components)
                root_children.append(card_id)

            components.append(
                m.Component(
                    id="root-status",
                    component="Text",
                    text="",
                    metadata=_extensions(m, parrot_role="status"),
                )
            )
            root_children.append("root-status")

            components.append(
                m.Component(id="root-submit-label", component="Text", text=_resolve(style.submit_label, locale))
            )
            components.append(
                m.Component(
                    id="root-submit",
                    component="Button",
                    variant="primary",
                    child="root-submit-label",
                    action=m.Action(
                        event=m.EventAction(
                            name="form.submit",
                            context={
                                "form_uid": str(form.form_uid),
                                "form_id": form.form_id,
                                "tenant": tenant,
                                "submit_url": submit_url,
                                "method": "POST",
                                "answers": {"path": "/answers"},
                            },
                        )
                    ),
                )
            )
            actions_children = ["root-submit"]

            if form.cancel_allowed:
                components.append(
                    m.Component(id="root-cancel-label", component="Text", text=_resolve(style.cancel_label, locale))
                )
                components.append(
                    m.Component(
                        id="root-cancel",
                        component="Button",
                        variant="default",
                        child="root-cancel-label",
                        action=m.Action(
                            event=m.EventAction(name="form.cancel", context={"form_uid": str(form.form_uid)})
                        ),
                    )
                )
                actions_children.append("root-cancel")

            components.append(m.Component(id="root-actions", component="Row", children=actions_children))
            root_children.append("root-actions")

            root = m.Component(
                id="root",
                component="Column",
                children=root_children,
                metadata=_extensions(
                    m,
                    parrot_variant="form",
                    parrot_form_uid=str(form.form_uid),
                    parrot_form_id=form.form_id,
                    parrot_form_version=form.version,
                    parrot_tenant=tenant,
                    parrot_submit_url=submit_url,
                ),
            )

            surface = m.CreateSurface(
                surface_id=f"form-{form.form_uid}",
                catalog_id=catalog_id,
                send_data_model=True,
                components=[root, *components],
                data_model={"answers": data_model_answers, "errors": data_model_errors},
            )

            m.validate_envelope(surface, origin=m.ProducerOrigin.TOOL, surface_catalog_id=catalog_id)

            return RenderedForm(
                content=m.serialize(surface),
                content_type=m.A2UI_MEDIA_TYPE,
                metadata={
                    "surface_id": surface.surface_id,
                    "catalog_id": catalog_id,
                    "field_paths": field_paths,
                    "degraded": degraded,
                },
                warnings=warnings,
            )
        finally:
            self._m = None

    def _lower_section(
        self,
        section: FormSection,
        locale: str,
        errors: dict[str, str],
        prefilled: dict[str, Any],
        data_model_answers: dict[str, Any],
        data_model_errors: dict[str, Any],
        field_paths: dict[str, str],
        degraded: list[dict[str, Any]],
        warnings: list[RenderWarning],
    ) -> tuple[list[Any], str]:
        """Lower one ``FormSection`` into a ``Card`` wrapping its body ``Column``.

        Args:
            section: The section to lower.
            locale: BCP 47 locale tag.
            errors: Validation errors (field_id -> message).
            prefilled: Pre-filled field values (field_id -> value).
            data_model_answers: Accumulator for ``dataModel.answers``.
            data_model_errors: Accumulator for ``dataModel.errors``.
            field_paths: Accumulator of field_id -> JSON Pointer, for every
                field that is NOT degraded (natively rendered, or HIDDEN).
            degraded: Accumulator of ``{"id", "field_id", "field_type",
                "reason"}`` dicts, one per degraded field.
            warnings: Accumulator of ``RenderWarning`` instances.

        Returns:
            A tuple of (every new component created for this section, the
            section ``Card``'s component id).
        """
        m = self._m
        new_components: list[Any] = []
        body_children: list[str] = []

        section_title = _resolve(section.title, locale)
        if section_title:
            title_id = f"sec-{section.section_id}-title"
            new_components.append(
                m.Component(
                    id=title_id,
                    component="Text",
                    text=section_title,
                    metadata=_extensions(m, parrot_role="title"),
                )
            )
            body_children.append(title_id)

        def _lower_one(field: FormField, subsection: FormSubsection | None) -> list[str]:
            field_components, warning = self._lower_field(field, section, subsection, locale, errors)
            new_components.extend(field_components)
            if warning is not None:
                warnings.append(warning)
                degraded.append(
                    {
                        "id": field_components[0].id if field_components else f"f-{field.field_id}",
                        "field_id": field.field_id,
                        "field_type": field.field_type.value,
                        "reason": warning.reason,
                    }
                )
            else:
                field_paths[field.field_id] = field_pointer(field.field_id)
            self._seed_data_model(field, prefilled, errors, data_model_answers, data_model_errors)
            return [component.id for component in field_components]

        for item in section.fields:
            if isinstance(item, FormSubsection):
                sub_children: list[str] = []
                sub_title = _resolve(item.title, locale)
                if sub_title:
                    sub_title_id = f"sub-{item.subsection_id}-title"
                    new_components.append(
                        m.Component(
                            id=sub_title_id,
                            component="Text",
                            text=sub_title,
                            metadata=_extensions(m, parrot_role="title"),
                        )
                    )
                    sub_children.append(sub_title_id)

                for field in item.fields:
                    sub_children.extend(_lower_one(field, item))

                sub_column_id = f"sub-{item.subsection_id}"
                new_components.append(m.Component(id=sub_column_id, component="Column", children=sub_children))
                body_children.append(sub_column_id)
            else:
                body_children.extend(_lower_one(item, None))

        body_id = f"sec-{section.section_id}-body"
        new_components.append(m.Component(id=body_id, component="Column", children=body_children))

        card_id = f"sec-{section.section_id}"
        new_components.append(m.Component(id=card_id, component="Card", child=body_id))

        return new_components, card_id

    def _lower_field(
        self,
        field: FormField,
        section: FormSection,
        subsection: FormSubsection | None,
        locale: str,
        errors: dict[str, str],
    ) -> tuple[list[Any], RenderWarning | None]:
        """Lower one ``FormField`` into its component(s), via ``FIELD_LOWERING``.

        Args:
            field: The field to lower.
            section: The field's owning section.
            subsection: The field's owning subsection, or ``None`` when the
                field is a direct child of ``section``.
            locale: BCP 47 locale tag.
            errors: Validation errors (field_id -> message).

        Returns:
            A tuple of (the component(s) created for this field — empty for
            a HIDDEN field, an optional ``RenderWarning`` when the field
            degraded to a notice (``None`` for a natively-rendered or HIDDEN
            field).
        """
        m = self._m
        lowering = FIELD_LOWERING[field.field_type]

        base_extensions: dict[str, Any] = {
            "parrot_field_id": field.field_id,
            "parrot_field_uid": str(field.field_uid),
            "parrot_field_type": field.field_type.value,
            "parrot_section_id": section.section_id,
        }
        if subsection is not None:
            base_extensions["parrot_subsection_id"] = subsection.subsection_id
        if field.read_only:
            base_extensions["parrot_read_only"] = True

        if lowering.primitive == "hidden":
            return [], None

        if lowering.primitive == "notice":
            notice = m.Component(
                id=f"f-{field.field_id}",
                component="Text",
                text=f"{_resolve(field.label, locale)}: not available on this surface",
                metadata=_extensions(m, parrot_role="notice", **base_extensions),
            )
            components: list[Any] = [notice]
            message = errors.get(field.field_id)
            if message is not None:
                components.append(self._error_text(m, field, message))
            warning = RenderWarning(
                field_id=field.field_id,
                field_uid=field.field_uid,
                field_type=field.field_type.value,
                renderer="a2ui",
                reason=f"no A2UI v1.0 primitive for {field.field_type.value}",
            )
            return components, warning

        value_binding = {"path": field_pointer(field.field_id)}
        kwargs: dict[str, Any] = {
            "id": f"f-{field.field_id}",
            "component": lowering.primitive,
            "value": value_binding,
            "checks": self._lower_checks(field, value_binding, locale),
        }
        kwargs.update(lowering.props)

        if lowering.primitive in ("TextField", "CheckBox", "ChoicePicker", "Slider", "DateTimeInput"):
            kwargs["label"] = _resolve(field.label, locale)

        if lowering.primitive == "TextField" and field.placeholder is not None:
            kwargs["placeholder"] = _resolve(field.placeholder, locale)

        if lowering.primitive == "ChoicePicker":
            kwargs["options"] = _choice_options(field.options, locale)

        if lowering.primitive == "Slider":
            constraints = field.constraints
            scale_min = constraints.scale_min if constraints else None
            scale_max = constraints.scale_max if constraints else None
            scale_step = constraints.scale_step if constraints else None
            kwargs["min"] = scale_min if scale_min is not None else 0
            kwargs["max"] = scale_max if scale_max is not None else _SLIDER_DEFAULT_MAX[field.field_type]
            if scale_step is not None:
                kwargs["steps"] = scale_step
            anchor_labels = constraints.anchor_labels if constraints else None
            if anchor_labels:
                base_extensions["parrot_anchor_labels"] = {
                    str(point): _resolve(label, locale) for point, label in anchor_labels.items()
                }

        kwargs["metadata"] = _extensions(m, **base_extensions)

        components = [m.Component(**kwargs)]
        message = errors.get(field.field_id)
        if message is not None:
            components.append(self._error_text(m, field, message))
        return components, None

    @staticmethod
    def _error_text(m: Any, field: FormField, message: str) -> Any:
        """Build the ``f-<field_id>-error`` sibling ``Text`` for a field error.

        Args:
            m: The namespace returned by :func:`_a2ui_ns`.
            field: The field the error belongs to.
            message: The error message to display.

        Returns:
            A ``Text`` ``Component`` with ``parrot_role == "error"``.
        """
        return m.Component(
            id=f"f-{field.field_id}-error",
            component="Text",
            text=message,
            metadata=_extensions(m, parrot_role="error", parrot_field_id=field.field_id),
        )

    def _lower_checks(
        self,
        field: FormField,
        value_binding: dict[str, str],
        locale: str,
    ) -> list[Any] | None:
        """Lower ``field.required``/``FieldConstraints``/table check_functions into ``checks``.

        Args:
            field: The field whose constraints are lowered.
            value_binding: The ``{"path": ...}`` binding shared by every check
                (and the primitive's own ``value``).
            locale: BCP 47 locale tag (for ``pattern_message``/label resolution).

        Returns:
            A list of ``CheckRule`` instances, or ``None`` when there are none.
        """
        m = self._m
        label = _resolve(field.label, locale)
        checks: list[Any] = []

        if field.required:
            checks.append(
                m.CheckRule(
                    condition=m.FunctionCall(call="required", args={"value": value_binding}),
                    message=f"{label} is required.",
                )
            )

        constraints = field.constraints
        pattern_added = False
        if constraints is not None:
            if constraints.pattern is not None:
                message = _resolve(constraints.pattern_message, locale) or f"{label} has an invalid format."
                checks.append(
                    m.CheckRule(
                        condition=m.FunctionCall(
                            call="regex", args={"value": value_binding, "pattern": constraints.pattern}
                        ),
                        message=message,
                    )
                )
                pattern_added = True
            if constraints.min_length is not None or constraints.max_length is not None:
                checks.append(
                    m.CheckRule(
                        condition=m.FunctionCall(
                            call="length",
                            args={"value": value_binding, "min": constraints.min_length, "max": constraints.max_length},
                        ),
                        message=f"{label} length is out of range.",
                    )
                )
            if constraints.min_value is not None or constraints.max_value is not None:
                checks.append(
                    m.CheckRule(
                        condition=m.FunctionCall(
                            call="numeric",
                            args={"value": value_binding, "min": constraints.min_value, "max": constraints.max_value},
                        ),
                        message=f"{label} is out of range.",
                    )
                )

        for fn in FIELD_LOWERING[field.field_type].check_functions:
            if fn == "email":
                checks.append(
                    m.CheckRule(
                        condition=m.FunctionCall(call="email", args={"value": value_binding}),
                        message=f"{label} must be a valid email address.",
                    )
                )
            elif fn == "regex" and not pattern_added:
                default_pattern = (
                    _DEFAULT_URL_PATTERN if field.field_type is FieldType.URL else _DEFAULT_PHONE_PATTERN
                )
                checks.append(
                    m.CheckRule(
                        condition=m.FunctionCall(call="regex", args={"value": value_binding, "pattern": default_pattern}),
                        message=f"{label} has an invalid format.",
                    )
                )

        return checks or None

    @staticmethod
    def _seed_data_model(
        field: FormField,
        prefilled: dict[str, Any],
        errors: dict[str, str],
        answers: dict[str, Any],
        errors_out: dict[str, Any],
    ) -> None:
        """Seed ``dataModel.answers``/``dataModel.errors`` for one field.

        Precedence for the answer value: ``prefilled`` > ``field.default`` >
        ``None``.

        Args:
            field: The field being seeded.
            prefilled: Pre-filled field values (field_id -> value).
            errors: Validation errors (field_id -> message).
            answers: The ``dataModel.answers`` accumulator (mutated in place).
            errors_out: The ``dataModel.errors`` accumulator (mutated in place).
        """
        if field.field_id in prefilled:
            value = prefilled[field.field_id]
        elif field.default is not None:
            value = field.default
        elif field.field_type in _MULTI_SELECT_TYPES:
            value = []
        else:
            value = None
        answers[field.field_id] = value

        message = errors.get(field.field_id)
        if message is not None:
            errors_out[field.field_id] = message
