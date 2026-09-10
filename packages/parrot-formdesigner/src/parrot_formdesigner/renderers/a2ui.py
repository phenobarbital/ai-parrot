"""A2UIFormRenderer — lowers a FormSchema into an A2UI v1.0 createSurface envelope.

Spec: ``sdd/specs/a2ui-form-output-renderer.spec.md`` (FEAT-544), §3 Module 1.

``ai-parrot`` (and therefore ``parrot.outputs.a2ui``) is an OPTIONAL
dependency of parrot-formdesigner (see ``pyproject.toml``'s ``ai-parrot``
extra) — every ``parrot.*`` symbol this module needs is imported lazily,
inside :func:`_a2ui_ns`, so ``import parrot_formdesigner.renderers.a2ui``
never fails (or pulls ai-parrot) when the extra is not installed.

Field lowering is a STUB in this module (TASK-3071): every field degrades to
a ``Text`` notice + a ``RenderWarning``. TASK-3072 replaces
:meth:`A2UIFormRenderer._lower_field` with the full ``FieldType`` ->
Basic-primitive lowering table (``FIELD_LOWERING``) while keeping this
method's signature stable.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from ..core.schema import (
    FormField,
    FormSchema,
    FormSection,
    FormSubsection,
    RenderedForm,
    RenderWarning,
)
from ..core.style import StyleSchema
from ..core.types import LocalizedString
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
            Component,
            ComponentMetadata,
            CreateSurface,
            EventAction,
            Extensions,
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
    ns.Component = Component
    ns.ComponentMetadata = ComponentMetadata
    ns.CreateSurface = CreateSurface
    ns.EventAction = EventAction
    ns.Extensions = Extensions
    ns.is_valid_pointer = is_valid_pointer
    ns.serialize = serialize
    return ns


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
            degraded: list[str] = []
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
                    # TASK-3071: field lowering is stubbed — every field
                    # currently degrades, so field_paths stays empty.
                    # TASK-3072 populates it for natively-lowered fields.
                    "field_paths": {},
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
        degraded: list[str],
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
            degraded: Accumulator of field_ids that used the degraded path.
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
                    field_components, warning = self._lower_field(field, section, item, locale, errors)
                    new_components.extend(field_components)
                    sub_children.extend(component.id for component in field_components)
                    if warning is not None:
                        warnings.append(warning)
                        degraded.append(field.field_id)
                    self._seed_data_model(field, prefilled, errors, data_model_answers, data_model_errors)

                sub_column_id = f"sub-{item.subsection_id}"
                new_components.append(m.Component(id=sub_column_id, component="Column", children=sub_children))
                body_children.append(sub_column_id)
            else:
                field = item
                field_components, warning = self._lower_field(field, section, None, locale, errors)
                new_components.extend(field_components)
                body_children.extend(component.id for component in field_components)
                if warning is not None:
                    warnings.append(warning)
                    degraded.append(field.field_id)
                self._seed_data_model(field, prefilled, errors, data_model_answers, data_model_errors)

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
        """Lower one ``FormField`` into its component(s).

        STUB (TASK-3071): every field degrades to a ``Text`` notice. TASK-3072
        replaces this method's body with the ``FIELD_LOWERING`` table while
        keeping this signature stable.

        Args:
            field: The field to lower.
            section: The field's owning section.
            subsection: The field's owning subsection, or ``None`` when the
                field is a direct child of ``section``.
            locale: BCP 47 locale tag.
            errors: Validation errors (field_id -> message).

        Returns:
            A tuple of (the component(s) created for this field, an optional
            ``RenderWarning`` when the field used a degraded/stub path).
        """
        m = self._m
        extensions: dict[str, Any] = {
            "parrot_role": "notice",
            "parrot_field_id": field.field_id,
            "parrot_field_uid": str(field.field_uid),
            "parrot_field_type": field.field_type.value,
            "parrot_section_id": section.section_id,
        }
        if subsection is not None:
            extensions["parrot_subsection_id"] = subsection.subsection_id

        notice = m.Component(
            id=f"f-{field.field_id}",
            component="Text",
            text=f"{_resolve(field.label, locale)} (A2UI field lowering not yet implemented)",
            metadata=_extensions(m, **extensions),
        )
        components: list[Any] = [notice]

        message = errors.get(field.field_id)
        if message is not None:
            components.append(
                m.Component(
                    id=f"f-{field.field_id}-error",
                    component="Text",
                    text=message,
                    metadata=_extensions(m, parrot_role="error", parrot_field_id=field.field_id),
                )
            )

        warning = RenderWarning(
            field_id=field.field_id,
            field_uid=field.field_uid,
            field_type=field.field_type.value,
            renderer="a2ui",
            reason="field lowering not implemented",
        )
        return components, warning

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
        else:
            value = None
        answers[field.field_id] = value

        message = errors.get(field.field_id)
        if message is not None:
            errors_out[field.field_id] = message
