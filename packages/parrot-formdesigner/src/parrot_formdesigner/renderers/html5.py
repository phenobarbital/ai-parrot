"""HTML5 form renderer for FormSchema.

Renders FormSchema + StyleSchema as HTML5 <form> fragments using Jinja2 templates.
Output is a form fragment (not a full page) ready to be embedded in a web application.
"""

from __future__ import annotations

import html
import json
import logging
from pathlib import Path
from typing import Any

import jinja2
import markdown2

from ..core.constraints import DependencyRule
from ..core.options import FieldOption
from ..core.schema import (
    FormField,
    FormSchema,
    FormSubsection,
    RenderedForm,
    RenderWarning,
)
from ..core.style import FieldSizeHint, LayoutType, StyleSchema
from ..core.types import FieldType, LocalizedString
from .base import AbstractFormRenderer, FallbackRenderer, FieldRenderer

logger = logging.getLogger(__name__)

# FieldType → HTML5 input type mapping
_INPUT_TYPE_MAP: dict[FieldType, str] = {
    FieldType.TEXT: "text",
    FieldType.NUMBER: "number",
    FieldType.INTEGER: "number",
    FieldType.BOOLEAN: "checkbox",
    FieldType.DATE: "date",
    FieldType.DATETIME: "datetime-local",
    FieldType.TIME: "time",
    FieldType.EMAIL: "email",
    FieldType.URL: "url",
    FieldType.PHONE: "tel",
    FieldType.PASSWORD: "password",
    FieldType.COLOR: "color",
    FieldType.HIDDEN: "hidden",
    FieldType.FILE: "file",
    FieldType.IMAGE: "file",
}


def _resolve(value: LocalizedString | None, locale: str = "en") -> str:
    """Resolve LocalizedString to plain string.

    Args:
        value: str or locale dict.
        locale: BCP 47 locale tag.

    Returns:
        Resolved string.
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


class HTML5Renderer(AbstractFormRenderer):
    """Renders FormSchema as an HTML5 <form> fragment.

    Uses Jinja2 templates (with autoescape=True) to produce HTML that can
    be served via API and embedded in any web page.

    Output:
    - A <form> fragment (no <html>, <head>, <body>)
    - HTML5 validation attributes (required, minlength, maxlength, min, max, pattern, step)
    - data-depends-on attributes for conditional visibility rules
    - CSS classes for layout (form-layout--single_column, form-layout--two_column, etc.)
    - content_type="text/html"

    Example:
        renderer = HTML5Renderer()
        result = await renderer.render(form_schema)
        html_fragment = result.content
    """

    def __init__(self, template_dir: str | Path | None = None) -> None:
        """Initialize HTML5Renderer.

        Args:
            template_dir: Optional path to Jinja2 templates directory.
                Defaults to the bundled templates/ directory via PackageLoader.
        """
        self.logger = logging.getLogger(__name__)
        if template_dir:
            loader = jinja2.FileSystemLoader(str(Path(template_dir)))
        else:
            loader = jinja2.PackageLoader(
                "parrot_formdesigner.renderers", "templates"
            )
        self._env = jinja2.Environment(
            loader=loader,
            autoescape=True,
        )
        # Register tojson filter
        self._env.filters["tojson"] = lambda v: json.dumps(v)
        self._fallback = FallbackRenderer()
        self._registry: dict[FieldType, FieldRenderer] = {}
        self._build_registry()

    def _build_registry(self) -> None:
        """Populate the per-type renderer registry with existing FieldType handlers.

        Each entry wraps an existing private render method in a FieldRenderer-
        compatible async callable. The HTML5 renderer's sync methods are wrapped
        transparently so they satisfy the FieldRenderer protocol.
        """

        class _SelectRenderer:
            def __init__(self_, renderer: "HTML5Renderer", multiple: bool = False) -> None:
                self_._r = renderer
                self_._multiple = multiple

            async def render(self_, field: FormField, *, locale: str = "en", prefilled: Any = None, error: str | None = None) -> Any:
                return self_._r._render_select(field, prefilled, locale, multiple=self_._multiple)

        class _TextAreaRenderer:
            def __init__(self_, renderer: "HTML5Renderer") -> None:
                self_._r = renderer

            async def render(self_, field: FormField, *, locale: str = "en", prefilled: Any = None, error: str | None = None) -> Any:
                return self_._r._render_textarea(field, prefilled, locale)

        class _CheckboxRenderer:
            def __init__(self_, renderer: "HTML5Renderer") -> None:
                self_._r = renderer

            async def render(self_, field: FormField, *, locale: str = "en", prefilled: Any = None, error: str | None = None) -> Any:
                return self_._r._render_checkbox(field, prefilled)

        class _InputRenderer:
            def __init__(self_, renderer: "HTML5Renderer") -> None:
                self_._r = renderer

            async def render(self_, field: FormField, *, locale: str = "en", prefilled: Any = None, error: str | None = None) -> Any:
                return self_._r._render_input(field, prefilled, locale)

        class _GroupRenderer:
            def __init__(self_, renderer: "HTML5Renderer") -> None:
                self_._r = renderer

            async def render(self_, field: FormField, *, locale: str = "en", prefilled: Any = None, error: str | None = None) -> Any:
                # Groups are rendered via _render_field_html with children context
                return None

        class _NoInputRenderer:
            """Renderer for field types that produce no interactive input (e.g. ARRAY)."""

            async def render(self_, field: FormField, *, locale: str = "en", prefilled: Any = None, error: str | None = None) -> Any:
                return ""

        class _TagsRenderer:
            """Renderer for TAGS field — text input with data-tags attribute."""

            def __init__(self_, renderer: "HTML5Renderer") -> None:
                self_._r = renderer

            async def render(self_, field: FormField, *, locale: str = "en", prefilled: Any = None, error: str | None = None) -> Any:
                return self_._r._render_tags(field, prefilled, locale)

        class _NpsRenderer:
            """Renderer for NPS field — radio group 0–10."""

            def __init__(self_, renderer: "HTML5Renderer") -> None:
                self_._r = renderer

            async def render(self_, field: FormField, *, locale: str = "en", prefilled: Any = None, error: str | None = None) -> Any:
                return self_._r._render_nps(field, prefilled)

        class _ScaleRenderer:
            """Renderer for LIKERT/RANKING fields — radio/range scale."""

            def __init__(self_, renderer: "HTML5Renderer") -> None:
                self_._r = renderer

            async def render(self_, field: FormField, *, locale: str = "en", prefilled: Any = None, error: str | None = None) -> Any:
                return self_._r._render_scale(field, prefilled)

        class _SignatureRenderer:
            """Renderer for SIGNATURE field — canvas + hidden inputs."""

            def __init__(self_, renderer: "HTML5Renderer") -> None:
                self_._r = renderer

            async def render(self_, field: FormField, *, locale: str = "en", prefilled: Any = None, error: str | None = None) -> Any:
                return self_._r._render_signature(field)

        class _DynamicSelectRenderer:
            """Renderer for DYNAMIC_SELECT — select with data-source attribute."""

            def __init__(self_, renderer: "HTML5Renderer") -> None:
                self_._r = renderer

            async def render(self_, field: FormField, *, locale: str = "en", prefilled: Any = None, error: str | None = None) -> Any:
                return self_._r._render_dynamic_select(field, prefilled, locale)

        class _TransferListRenderer:
            """Renderer for TRANSFER_LIST — dual multi-select."""

            def __init__(self_, renderer: "HTML5Renderer") -> None:
                self_._r = renderer

            async def render(self_, field: FormField, *, locale: str = "en", prefilled: Any = None, error: str | None = None) -> Any:
                return self_._r._render_transfer_list(field, prefilled, locale)

        class _ReadOnlyDivRenderer:
            """Renderer for REMOTE_RESPONSE — read-only div placeholder."""

            def __init__(self_, renderer: "HTML5Renderer") -> None:
                self_._r = renderer

            async def render(self_, field: FormField, *, locale: str = "en", prefilled: Any = None, error: str | None = None) -> Any:
                return self_._r._render_readonly_div(field)

        class _AvailabilityRenderer:
            """Renderer for AVAILABILITY — date range picker placeholder."""

            def __init__(self_, renderer: "HTML5Renderer") -> None:
                self_._r = renderer

            async def render(self_, field: FormField, *, locale: str = "en", prefilled: Any = None, error: str | None = None) -> Any:
                return self_._r._render_availability(field)

        class _RestUploaderRenderer:
            """Renderer for REST — file uploader with hidden answer/blob_ref inputs."""

            def __init__(self_, renderer: "HTML5Renderer") -> None:
                self_._r = renderer

            async def render(self_, field: FormField, *, locale: str = "en", prefilled: Any = None, error: str | None = None) -> Any:
                return self_._r._render_rest(field)

        class _LocationRenderer:
            """Renderer for LOCATION — country select."""

            def __init__(self_, renderer: "HTML5Renderer") -> None:
                self_._r = renderer

            async def render(self_, field: FormField, *, locale: str = "en", prefilled: Any = None, error: str | None = None) -> Any:
                return self_._r._render_location(field, prefilled, locale)

        input_renderer = _InputRenderer(self)
        self._registry = {
            FieldType.TEXT: input_renderer,
            FieldType.NUMBER: input_renderer,
            FieldType.INTEGER: input_renderer,
            FieldType.DATE: input_renderer,
            FieldType.DATETIME: input_renderer,
            FieldType.TIME: input_renderer,
            FieldType.EMAIL: input_renderer,
            FieldType.URL: input_renderer,
            FieldType.PHONE: input_renderer,
            FieldType.PASSWORD: input_renderer,
            FieldType.COLOR: input_renderer,
            FieldType.HIDDEN: input_renderer,
            FieldType.FILE: input_renderer,
            FieldType.IMAGE: input_renderer,
            FieldType.TEXT_AREA: _TextAreaRenderer(self),
            FieldType.BOOLEAN: _CheckboxRenderer(self),
            FieldType.SELECT: _SelectRenderer(self, multiple=False),
            FieldType.MULTI_SELECT: _SelectRenderer(self, multiple=True),
            FieldType.GROUP: _GroupRenderer(self),
            FieldType.ARRAY: _NoInputRenderer(),
            # New field types (FEAT-167)
            FieldType.SIGNATURE: _SignatureRenderer(self),
            FieldType.DYNAMIC_SELECT: _DynamicSelectRenderer(self),
            FieldType.TRANSFER_LIST: _TransferListRenderer(self),
            FieldType.REMOTE_RESPONSE: _ReadOnlyDivRenderer(self),
            FieldType.AVAILABILITY: _AvailabilityRenderer(self),
            FieldType.LOCATION: _LocationRenderer(self),
            FieldType.TAGS: _TagsRenderer(self),
            FieldType.NPS: _NpsRenderer(self),
            FieldType.LIKERT: _ScaleRenderer(self),
            FieldType.RANKING: _ScaleRenderer(self),
            # New field type (FEAT-170)
            FieldType.REST: _RestUploaderRenderer(self),
        }

    async def render(
        self,
        form: FormSchema,
        style: StyleSchema | None = None,
        *,
        locale: str = "en",
        prefilled: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> RenderedForm:
        """Render a FormSchema as an HTML5 form fragment.

        Args:
            form: The form schema.
            style: Style configuration.
            locale: Locale for i18n label resolution.
            prefilled: Pre-filled field values (field_id -> value).
            errors: Field-level error messages (field_id -> message).

        Returns:
            RenderedForm with HTML string as content and content_type="text/html".
        """
        style = style or StyleSchema()
        prefilled = prefilled or {}
        errors = errors or {}

        layout_class = style.layout.value
        submit_label = _resolve(style.submit_label, locale) or "Submit"
        cancel_label = _resolve(style.cancel_label, locale) or "Cancel"

        def resolve(value: LocalizedString | None) -> str:
            return _resolve(value, locale)

        def render_field(field: FormField | FormSubsection) -> str:
            if isinstance(field, FormSubsection):
                return self._render_subsection_html(field, prefilled, errors, style, locale)
            return self._render_field_html(field, prefilled, errors, style, locale)

        def depends_on_json(dep: DependencyRule) -> str:
            return dep.model_dump_json()

        # Collect render warnings for new field types rendered as fallbacks
        warnings: list[RenderWarning] = []
        _new_types = {
            FieldType.SIGNATURE, FieldType.DYNAMIC_SELECT, FieldType.TRANSFER_LIST,
            FieldType.REMOTE_RESPONSE, FieldType.AVAILABILITY, FieldType.LOCATION,
            FieldType.TAGS, FieldType.NPS, FieldType.LIKERT, FieldType.RANKING,
        }
        # HTML5 renders all new types natively; no warnings needed here.
        # (warnings are emitted only for renderers that use FallbackRenderer)

        template = self._env.get_template("form.html.j2")
        rendered_html = template.render(
            form=form,
            style=style,
            locale=locale,
            layout_class=layout_class,
            prefilled=prefilled,
            errors=errors,
            submit_label=submit_label,
            cancel_label=cancel_label,
            resolve=resolve,
            render_field=render_field,
        )

        return RenderedForm(
            content=rendered_html,
            content_type="text/html",
            metadata={"locale": locale, "layout": layout_class},
            warnings=warnings,
        )

    def _render_field_html(
        self,
        field: FormField,
        prefilled: dict[str, Any],
        errors: dict[str, str],
        style: StyleSchema,
        locale: str,
    ) -> str:
        """Render a single field as HTML string.

        Dispatches to the per-type renderer via ``_registry``. Falls back to
        ``_fallback`` for unknown or unregistered field types.

        Args:
            field: FormField to render.
            prefilled: Pre-filled values.
            errors: Field error messages.
            style: Style configuration.
            locale: Locale for i18n.

        Returns:
            HTML string for the field.
        """
        field_label = _resolve(field.label, locale) or field.field_id.replace("_", " ").title()
        value = prefilled.get(field.field_id, field.default)
        error = errors.get(field.field_id)
        description = _resolve(field.description, locale) if field.description else None

        # Size CSS class
        size_class = ""
        if style.field_styles and field.field_id in style.field_styles:
            size_hint = style.field_styles[field.field_id].size
            if size_hint:
                size_class = f" form-field--{size_hint.value}"

        # depends_on data attribute
        depends_attr = ""
        if field.depends_on:
            safe_json = html.escape(json.dumps(field.depends_on.model_dump()), quote=True)
            depends_attr = f' data-depends-on="{safe_json}"'

        # Required asterisk
        label_text = field_label + (" *" if field.required else "")

        render_as = (field.meta or {}).get("render_as", "")

        parts = [
            f'<div class="form-field form-field--{field.field_type.value}{size_class}'
            f' mb-4"'
            f'{depends_attr}>',
        ]

        ft = field.field_type

        # Read-only display fields: render content as HTML, no input element
        if field.read_only and render_as in ("display_text", "display_image"):
            # Label may arrive as HTML (sometimes entity-escaped) or as markdown.
            # Unescape entities first, then run through markdown2 — it converts
            # markdown markers to HTML and passes block-level HTML through.
            unescaped = html.unescape(field_label)
            display_content = markdown2.markdown(
                unescaped,
                extras=["fenced-code-blocks", "tables", "break-on-newline"],
            )
            parts.append(
                f'<div class="form-field__display text-gray-700" id="{field.field_id}">'
                f'{display_content}</div>'
            )

        # Subsection headers: render as heading divider, not fieldset
        elif ft == FieldType.GROUP and render_as == "subsection":
            parts.append(
                f'<div class="form-field__subsection border-b border-gray-200 pb-2 mb-3">'
                f'<h3 class="text-base font-semibold text-gray-800">{label_text}</h3></div>'
            )

        elif ft == FieldType.SELECT:
            parts.append(
                f'<label for="{field.field_id}" class="block text-sm font-medium text-gray-700 mb-1">'
                f'{label_text}</label>'
            )
            if description:
                parts.append(f'<span class="form-field__help text-xs text-gray-500 mb-1 block">{description}</span>')
            if render_as == "radio":
                parts.append(self._render_radio_group(field, value, locale))
            else:
                parts.append(self._render_select(field, value, locale, multiple=False))

        elif ft == FieldType.MULTI_SELECT:
            parts.append(
                f'<label for="{field.field_id}" class="block text-sm font-medium text-gray-700 mb-1">'
                f'{label_text}</label>'
            )
            if description:
                parts.append(f'<span class="form-field__help text-xs text-gray-500 mb-1 block">{description}</span>')
            parts.append(self._render_select(field, value, locale, multiple=True))

        elif ft == FieldType.TEXT_AREA:
            parts.append(
                f'<label for="{field.field_id}" class="block text-sm font-medium text-gray-700 mb-1">'
                f'{label_text}</label>'
            )
            if description:
                parts.append(f'<span class="form-field__help text-xs text-gray-500 mb-1 block">{description}</span>')
            parts.append(self._render_textarea(field, value, locale))

        elif ft == FieldType.BOOLEAN:
            parts.append(
                f'<label class="form-field__checkbox-label inline-flex items-center gap-2 text-sm text-gray-700 cursor-pointer">'
                f'{self._render_checkbox(field, value)}'
                f' {label_text}</label>'
            )

        elif ft == FieldType.GROUP:
            parts.append(
                f'<fieldset class="form-field__group border border-gray-200 rounded-lg p-4 space-y-3">'
                f'<legend class="text-sm font-semibold text-gray-800 px-1">{label_text}</legend>'
            )
            if field.children:
                for child in field.children:
                    parts.append(self._render_field_html(child, prefilled, errors, style, locale))
            parts.append('</fieldset>')

        # New field types (FEAT-167) dispatch
        elif ft == FieldType.SIGNATURE:
            parts.append(
                f'<label class="block text-sm font-medium text-gray-700 mb-1">{label_text}</label>'
            )
            if description:
                parts.append(f'<span class="form-field__help text-xs text-gray-500 mb-1 block">{description}</span>')
            parts.append(self._render_signature(field))

        elif ft == FieldType.DYNAMIC_SELECT:
            parts.append(
                f'<label for="{field.field_id}" class="block text-sm font-medium text-gray-700 mb-1">'
                f'{label_text}</label>'
            )
            if description:
                parts.append(f'<span class="form-field__help text-xs text-gray-500 mb-1 block">{description}</span>')
            parts.append(self._render_dynamic_select(field, value, locale))

        elif ft == FieldType.TRANSFER_LIST:
            parts.append(
                f'<label class="block text-sm font-medium text-gray-700 mb-1">{label_text}</label>'
            )
            if description:
                parts.append(f'<span class="form-field__help text-xs text-gray-500 mb-1 block">{description}</span>')
            parts.append(self._render_transfer_list(field, value, locale))

        elif ft == FieldType.REMOTE_RESPONSE:
            parts.append(
                f'<label class="block text-sm font-medium text-gray-700 mb-1">{label_text}</label>'
            )
            parts.append(self._render_readonly_div(field))

        elif ft == FieldType.AVAILABILITY:
            parts.append(
                f'<label class="block text-sm font-medium text-gray-700 mb-1">{label_text}</label>'
            )
            if description:
                parts.append(f'<span class="form-field__help text-xs text-gray-500 mb-1 block">{description}</span>')
            parts.append(self._render_availability(field))

        elif ft == FieldType.LOCATION:
            parts.append(
                f'<label for="{field.field_id}" class="block text-sm font-medium text-gray-700 mb-1">'
                f'{label_text}</label>'
            )
            if description:
                parts.append(f'<span class="form-field__help text-xs text-gray-500 mb-1 block">{description}</span>')
            parts.append(self._render_location(field, value, locale))

        elif ft == FieldType.TAGS:
            parts.append(
                f'<label for="{field.field_id}" class="block text-sm font-medium text-gray-700 mb-1">'
                f'{label_text}</label>'
            )
            if description:
                parts.append(f'<span class="form-field__help text-xs text-gray-500 mb-1 block">{description}</span>')
            parts.append(self._render_tags(field, value, locale))

        elif ft == FieldType.NPS:
            parts.append(
                f'<label class="block text-sm font-medium text-gray-700 mb-1">{label_text}</label>'
            )
            if description:
                parts.append(f'<span class="form-field__help text-xs text-gray-500 mb-1 block">{description}</span>')
            parts.append(self._render_nps(field, value))

        elif ft in (FieldType.LIKERT, FieldType.RANKING):
            parts.append(
                f'<label class="block text-sm font-medium text-gray-700 mb-1">{label_text}</label>'
            )
            if description:
                parts.append(f'<span class="form-field__help text-xs text-gray-500 mb-1 block">{description}</span>')
            parts.append(self._render_scale(field, value))

        # New field type (FEAT-170)
        elif ft == FieldType.REST:
            parts.append(
                f'<label class="block text-sm font-medium text-gray-700 mb-1">{label_text}</label>'
            )
            if description:
                parts.append(f'<span class="form-field__help text-xs text-gray-500 mb-1 block">{description}</span>')
            parts.append(self._render_rest(field))

        else:
            parts.append(
                f'<label for="{field.field_id}" class="block text-sm font-medium text-gray-700 mb-1">'
                f'{label_text}</label>'
            )
            if description:
                parts.append(f'<span class="form-field__help text-xs text-gray-500 mb-1 block">{description}</span>')
            parts.append(self._render_input(field, value, locale))

        if error:
            parts.append(f'<span class="form-field__error text-sm text-red-600 mt-1 block" role="alert">{error}</span>')

        parts.append('</div>')
        return "\n".join(parts)

    def _render_signature(self, field: FormField) -> str:
        """Render a SIGNATURE field as a canvas + hidden inputs.

        Args:
            field: SIGNATURE FormField.

        Returns:
            HTML canvas + hidden inputs string.
        """
        tw = "block w-full border border-gray-300 rounded-md"
        return (
            f'<canvas id="{field.field_id}" class="{tw}" '
            f'data-signature="true" width="400" height="150"></canvas>'
            f'<input type="hidden" id="{field.field_id}_svg" name="{field.field_id}_svg">'
            f'<input type="hidden" id="{field.field_id}_png" name="{field.field_id}_png">'
        )

    def _render_rest(self, field: FormField) -> str:
        """Render a REST field as a file-uploader widget with hidden answer/blob_ref inputs.

        Args:
            field: REST FormField.

        Returns:
            HTML markup for the REST uploader widget.
        """
        constraints = field.constraints
        accept = ",".join(constraints.allowed_mime_types) if constraints and constraints.allowed_mime_types else ""
        accept_attr = f' accept="{accept}"' if accept else ""
        required_attr = " required" if field.required else ""
        return (
            f'<div class="parrot-rest-uploader" data-field-id="{field.field_id}"'
            f' data-upload-url="/api/v1/forms/{{form_id}}/fields/{field.field_id}/upload">'
            f'<input type="file" name="{field.field_id}_file"{accept_attr}{required_attr}>'
            f'<input type="hidden" name="{field.field_id}.answer">'
            f'<input type="hidden" name="{field.field_id}.blob_ref">'
            f'<span class="rest-status"></span>'
            f'</div>'
        )

    def _render_dynamic_select(self, field: FormField, value: Any, locale: str) -> str:
        """Render a DYNAMIC_SELECT as a <select> with data-source attribute.

        Args:
            field: DYNAMIC_SELECT FormField.
            value: Pre-filled value.
            locale: Locale for i18n.

        Returns:
            HTML select element string.
        """
        tw = (
            "block w-full rounded-md border border-gray-300 px-3 py-2 text-sm "
            "shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        )
        attrs: list[str] = [
            f'id="{field.field_id}"',
            f'name="{field.field_id}"',
            f'class="{tw}"',
            'data-dynamic-select="true"',
        ]
        if field.options_source:
            source_ref = html.escape(field.options_source.source_ref, quote=True)
            attrs.append(f'data-source="{source_ref}"')
        if field.required:
            attrs.append("required")
        selected = str(value) if value is not None else ""
        placeholder = '<option value="" disabled selected>Loading...</option>'
        options_html = [placeholder]
        if field.options:
            for opt in field.options:
                opt_label = _resolve(opt.label, locale) or opt.value
                sel = " selected" if opt.value == selected else ""
                options_html.append(f'<option value="{opt.value}"{sel}>{opt_label}</option>')
        return f'<select {" ".join(attrs)}>\n' + "\n".join(options_html) + "\n</select>"

    def _render_transfer_list(self, field: FormField, value: Any, locale: str) -> str:
        """Render a TRANSFER_LIST as dual <select multiple> elements.

        Args:
            field: TRANSFER_LIST FormField.
            value: Pre-selected values (list or comma-separated string).
            locale: Locale for i18n.

        Returns:
            HTML dual-select string.
        """
        selected: set[str] = set()
        if isinstance(value, list):
            selected = {str(v) for v in value}
        elif isinstance(value, str):
            selected = {v.strip() for v in value.split(",") if v.strip()}

        tw = "block w-full rounded-md border border-gray-300 text-sm h-32"
        available_opts: list[str] = []
        selected_opts: list[str] = []
        if field.options:
            for opt in field.options:
                opt_label = _resolve(opt.label, locale) or opt.value
                opt_html = f'<option value="{opt.value}">{opt_label}</option>'
                if opt.value in selected:
                    selected_opts.append(opt_html)
                else:
                    available_opts.append(opt_html)

        available_html = "\n".join(available_opts)
        selected_html = "\n".join(selected_opts)
        return (
            f'<div class="form-field__transfer-list flex gap-2">'
            f'<div class="flex-1">'
            f'<label class="text-xs text-gray-500 mb-1 block">Available</label>'
            f'<select id="{field.field_id}_available" multiple class="{tw}">'
            f'{available_html}</select></div>'
            f'<div class="flex-1">'
            f'<label class="text-xs text-gray-500 mb-1 block">Selected</label>'
            f'<select id="{field.field_id}" name="{field.field_id}" multiple class="{tw}">'
            f'{selected_html}</select></div>'
            f'</div>'
        )

    def _render_readonly_div(self, field: FormField) -> str:
        """Render a REMOTE_RESPONSE as a read-only placeholder div.

        Args:
            field: REMOTE_RESPONSE FormField.

        Returns:
            HTML read-only div string.
        """
        return (
            f'<div id="{field.field_id}" '
            f'class="form-field__remote-response block w-full rounded-md border border-gray-200 '
            f'px-3 py-2 text-sm text-gray-500 bg-gray-50" '
            f'data-remote-response="true" aria-live="polite">'
            f'(Loading...)</div>'
        )

    def _render_availability(self, field: FormField) -> str:
        """Render an AVAILABILITY field as a date-range picker placeholder.

        Args:
            field: AVAILABILITY FormField.

        Returns:
            HTML availability picker div string.
        """
        return (
            f'<div id="{field.field_id}" '
            f'class="form-field__availability block w-full rounded-md border border-gray-300 '
            f'px-3 py-2 text-sm" '
            f'data-availability="true">'
            f'<input type="date" name="{field.field_id}_start" class="mr-2" placeholder="Start">'
            f'<input type="date" name="{field.field_id}_end" placeholder="End">'
            f'</div>'
        )

    def _render_location(self, field: FormField, value: Any, locale: str) -> str:
        """Render a LOCATION field as a country <select>.

        Args:
            field: LOCATION FormField.
            value: Pre-filled ISO country code.
            locale: Locale for i18n.

        Returns:
            HTML select element with country options (uses pycountry if available).
        """
        tw = (
            "block w-full rounded-md border border-gray-300 px-3 py-2 text-sm "
            "shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        )
        attrs: list[str] = [
            f'id="{field.field_id}"',
            f'name="{field.field_id}"',
            f'class="{tw}"',
        ]
        if field.required:
            attrs.append("required")

        selected = str(value).upper() if value is not None else ""
        options_html: list[str] = ['<option value="" disabled selected>Select country...</option>']

        try:
            import pycountry
            countries = sorted(pycountry.countries, key=lambda c: c.name)
            for country in countries:
                sel = " selected" if country.alpha_2 == selected else ""
                options_html.append(
                    f'<option value="{country.alpha_2}"{sel}>{html.escape(country.name)}</option>'
                )
        except ImportError:
            _FALLBACK = [("US", "United States"), ("GB", "United Kingdom"), ("ES", "Spain"),
                         ("VE", "Venezuela"), ("MX", "Mexico"), ("CA", "Canada")]
            for code, name in _FALLBACK:
                sel = " selected" if code == selected else ""
                options_html.append(f'<option value="{code}"{sel}>{name}</option>')

        return f'<select {" ".join(attrs)}>\n' + "\n".join(options_html) + "\n</select>"

    def _render_tags(self, field: FormField, value: Any, locale: str) -> str:
        """Render a TAGS field as a text input with data-tags attribute.

        Args:
            field: TAGS FormField.
            value: Pre-filled tags (list or comma-separated string).
            locale: Locale for i18n.

        Returns:
            HTML input element string.
        """
        tw = (
            "block w-full rounded-md border border-gray-300 px-3 py-2 text-sm "
            "shadow-sm placeholder-gray-400 "
            "focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        )
        if isinstance(value, list):
            tag_value = ", ".join(str(v) for v in value)
        elif value is not None:
            tag_value = str(value)
        else:
            tag_value = ""

        placeholder = _resolve(field.placeholder, locale) if field.placeholder else "Add tags..."
        attrs: list[str] = [
            'type="text"',
            f'id="{field.field_id}"',
            f'name="{field.field_id}"',
            f'class="{tw}"',
            'data-tags="true"',
            f'value="{html.escape(tag_value, quote=True)}"',
            f'placeholder="{placeholder}"',
        ]
        if field.required:
            attrs.append("required")
        return f'<input {" ".join(attrs)}>'

    def _render_nps(self, field: FormField, value: Any) -> str:
        """Render an NPS field as a radio group 0–10.

        Args:
            field: NPS FormField.
            value: Pre-filled value (0–10).

        Returns:
            HTML radio group string.
        """
        selected = str(value) if value is not None else ""
        parts: list[str] = [
            '<div class="form-field__nps flex gap-1 flex-wrap" role="radiogroup" '
            'aria-label="NPS 0 to 10">'
        ]
        for i in range(11):
            checked = " checked" if str(i) == selected else ""
            req = " required" if field.required and i == 0 else ""
            parts.append(
                f'<label class="form-field__nps-item flex flex-col items-center cursor-pointer">'
                f'<input type="radio" name="{field.field_id}" value="{i}"{checked}{req}>'
                f'<span class="text-xs">{i}</span>'
                f'</label>'
            )
        parts.append('</div>')
        return "\n".join(parts)

    def _render_scale(self, field: FormField, value: Any) -> str:
        """Render a LIKERT or RANKING field as a scale of radio inputs.

        Args:
            field: LIKERT or RANKING FormField.
            value: Pre-filled value.

        Returns:
            HTML scale radio group string.
        """
        c = field.constraints
        scale_min = c.scale_min if c and c.scale_min is not None else 0
        scale_max = c.scale_max if c and c.scale_max is not None else (
            4 if field.field_type == FieldType.LIKERT else 5
        )
        current = str(value) if value is not None else str(scale_min)
        anchor_labels = {}
        if c and c.anchor_labels:
            anchor_labels = c.anchor_labels

        parts: list[str] = [
            '<div class="form-field__scale flex gap-1 flex-wrap" role="radiogroup">'
        ]
        for i in range(scale_min, scale_max + 1):
            checked = " checked" if str(i) == current else ""
            req = " required" if field.required and i == scale_min else ""
            anchor = anchor_labels.get(i, "")
            label_extra = f' title="{html.escape(str(anchor), quote=True)}"' if anchor else ""
            parts.append(
                f'<label class="form-field__scale-item flex flex-col items-center cursor-pointer"'
                f'{label_extra}>'
                f'<input type="radio" name="{field.field_id}" value="{i}"{checked}{req}>'
                f'<span class="text-xs">{i}</span>'
                f'</label>'
            )
        parts.append('</div>')
        return "\n".join(parts)

    def _render_subsection_html(
        self,
        subsection: FormSubsection,
        prefilled: dict[str, Any],
        errors: dict[str, str],
        style: StyleSchema,
        locale: str,
    ) -> str:
        """Render a FormSubsection as an HTML sub-group."""
        title = _resolve(subsection.title, locale) if subsection.title else ""
        description = _resolve(subsection.description, locale) if subsection.description else ""

        depends_attr = ""
        if subsection.depends_on:
            import html as _html
            safe_json = _html.escape(json.dumps(subsection.depends_on.model_dump()), quote=True)
            depends_attr = f' data-depends-on="{safe_json}"'

        parts: list[str] = [
            f'<div class="form-subsection border-l-2 border-gray-200 pl-4 space-y-4 mb-4"'
            f' id="subsection-{subsection.subsection_id}"{depends_attr}>',
        ]
        if title:
            parts.append(
                f'<h3 class="form-subsection__title text-base font-semibold text-gray-800">'
                f'{title}</h3>'
            )
        if description:
            parts.append(
                f'<p class="form-subsection__description text-sm text-gray-500">'
                f'{description}</p>'
            )
        parts.append('<div class="form-subsection__fields space-y-4">')
        for field in subsection.fields:
            parts.append(self._render_field_html(field, prefilled, errors, style, locale))
        parts.append('</div>')
        parts.append('</div>')
        return "\n".join(parts)

    def _render_input(
        self,
        field: FormField,
        value: Any,
        locale: str,
    ) -> str:
        """Render an <input> element.

        Args:
            field: FormField definition.
            value: Pre-filled value.
            locale: Locale for i18n.

        Returns:
            HTML input element string.
        """
        input_type = _INPUT_TYPE_MAP.get(field.field_type, "text")
        placeholder = _resolve(field.placeholder, locale) if field.placeholder else ""

        tw = (
            "block w-full rounded-md border border-gray-300 px-3 py-2 text-sm "
            "shadow-sm placeholder-gray-400 "
            "focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        )
        attrs: list[str] = [
            f'type="{input_type}"',
            f'id="{field.field_id}"',
            f'name="{field.field_id}"',
            f'class="{tw}"',
        ]

        if value is not None:
            attrs.append(f'value="{html.escape(str(value), quote=True)}"')
        if placeholder:
            attrs.append(f'placeholder="{placeholder}"')
        if field.required:
            attrs.append("required")

        if field.constraints:
            c = field.constraints
            if c.min_length is not None:
                attrs.append(f'minlength="{c.min_length}"')
            if c.max_length is not None:
                attrs.append(f'maxlength="{c.max_length}"')
            if c.min_value is not None:
                attrs.append(f'min="{c.min_value}"')
            if c.max_value is not None:
                attrs.append(f'max="{c.max_value}"')
            if c.step is not None:
                attrs.append(f'step="{c.step}"')
            if c.pattern is not None:
                attrs.append(f'pattern="{c.pattern}"')

        return f'<input {" ".join(attrs)}>'

    def _render_checkbox(self, field: FormField, value: Any) -> str:
        """Render a checkbox <input>.

        Args:
            field: BOOLEAN FormField.
            value: Pre-filled value (truthy = checked).

        Returns:
            HTML checkbox input string.
        """
        tw = (
            "h-4 w-4 rounded border-gray-300 text-blue-600 "
            "focus:ring-blue-500"
        )
        attrs: list[str] = [
            'type="checkbox"',
            f'id="{field.field_id}"',
            f'name="{field.field_id}"',
            'value="true"',
            f'class="{tw}"',
        ]
        if field.required:
            attrs.append("required")
        if value in (True, "true", "True", "1", 1):
            attrs.append("checked")
        return f'<input {" ".join(attrs)}>'

    def _render_textarea(self, field: FormField, value: Any, locale: str) -> str:
        """Render a <textarea> element.

        Args:
            field: TEXT_AREA FormField.
            value: Pre-filled value.
            locale: Locale for i18n.

        Returns:
            HTML textarea element string.
        """
        tw = (
            "block w-full rounded-md border border-gray-300 px-3 py-2 text-sm "
            "shadow-sm placeholder-gray-400 "
            "focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        )
        placeholder = _resolve(field.placeholder, locale) if field.placeholder else ""
        attrs: list[str] = [
            f'id="{field.field_id}"',
            f'name="{field.field_id}"',
            f'class="{tw}"',
        ]
        if placeholder:
            attrs.append(f'placeholder="{placeholder}"')
        if field.required:
            attrs.append("required")
        if field.constraints:
            if field.constraints.min_length is not None:
                attrs.append(f'minlength="{field.constraints.min_length}"')
            if field.constraints.max_length is not None:
                attrs.append(f'maxlength="{field.constraints.max_length}"')

        text_content = html.escape(str(value)) if value is not None else ""
        return f'<textarea {" ".join(attrs)}>{text_content}</textarea>'

    def _render_select(
        self,
        field: FormField,
        value: Any,
        locale: str,
        multiple: bool = False,
    ) -> str:
        """Render a <select> element.

        Args:
            field: SELECT or MULTI_SELECT FormField.
            value: Pre-filled value(s).
            locale: Locale for i18n option labels.
            multiple: Whether to render as a multi-select.

        Returns:
            HTML select element string.
        """
        tw = (
            "block w-full rounded-md border border-gray-300 px-3 py-2 text-sm "
            "shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        )
        attrs: list[str] = [
            f'id="{field.field_id}"',
            f'name="{field.field_id}"',
            f'class="{tw}"',
        ]
        if multiple:
            attrs.append("multiple")
        if field.required:
            attrs.append("required")

        # Normalize selected values
        if multiple:
            selected_values: set[str] = set()
            if isinstance(value, list):
                selected_values = {str(v) for v in value}
            elif isinstance(value, str):
                selected_values = {v.strip() for v in value.split(",") if v.strip()}
        else:
            selected_single = str(value) if value is not None else ""

        options_html: list[str] = []
        if not multiple:
            options_html.append('<option value="" disabled selected>Select...</option>')

        if field.options:
            for opt in field.options:
                opt_label = _resolve(opt.label, locale) or opt.value
                disabled_attr = " disabled" if opt.disabled else ""
                if multiple:
                    sel = " selected" if opt.value in selected_values else ""
                else:
                    sel = " selected" if opt.value == selected_single else ""
                options_html.append(
                    f'<option value="{opt.value}"{sel}{disabled_attr}>{opt_label}</option>'
                )

        options_str = "\n".join(options_html)
        return f'<select {" ".join(attrs)}>\n{options_str}\n</select>'

    def _render_radio_group(
        self,
        field: FormField,
        value: Any,
        locale: str,
    ) -> str:
        """Render a group of radio button inputs for SELECT fields.

        Args:
            field: SELECT FormField with render_as=radio.
            value: Pre-filled value.
            locale: Locale for i18n option labels.

        Returns:
            HTML radio group string.
        """
        selected = str(value) if value is not None else ""
        parts: list[str] = ['<div class="form-field__radio-group space-y-2">']

        if field.options:
            for opt in field.options:
                opt_label = _resolve(opt.label, locale) or opt.value
                checked = " checked" if opt.value == selected else ""
                disabled = " disabled" if opt.disabled else ""
                required = " required" if field.required else ""
                parts.append(
                    f'<label class="form-field__radio-label inline-flex items-center gap-2 text-sm text-gray-700 cursor-pointer">'
                    f'<input type="radio" name="{field.field_id}" '
                    f'value="{opt.value}" class="h-4 w-4 border-gray-300 text-blue-600 focus:ring-blue-500"'
                    f'{checked}{disabled}{required}>'
                    f" {opt_label}</label>"
                )

        parts.append("</div>")
        return "\n".join(parts)
