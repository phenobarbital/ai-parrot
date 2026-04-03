"""HTML5 form renderer for FormSchema.

Renders FormSchema + StyleSchema as HTML5 <form> fragments using Jinja2 templates.
Output is a form fragment (not a full page) ready to be embedded in a web application.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import jinja2

from ..constraints import DependencyRule
from ..options import FieldOption
from ..schema import FormField, FormSchema, RenderedForm
from ..style import FieldSizeHint, LayoutType, StyleSchema
from ..types import FieldType, LocalizedString
from .base import AbstractFormRenderer

logger = logging.getLogger(__name__)

# Default templates directory (relative to this file)
_DEFAULT_TEMPLATES_DIR = Path(__file__).parent / "templates"

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
                Defaults to the bundled templates/ directory.
        """
        self.logger = logging.getLogger(__name__)
        resolved_dir = Path(template_dir) if template_dir else _DEFAULT_TEMPLATES_DIR
        self._env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(resolved_dir)),
            autoescape=True,
        )
        # Register tojson filter
        self._env.filters["tojson"] = lambda v: json.dumps(v)

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

        def render_field(field: FormField) -> str:
            return self._render_field_html(field, prefilled, errors, style, locale)

        def depends_on_json(dep: DependencyRule) -> str:
            return dep.model_dump_json()

        template = self._env.get_template("form.html.j2")
        html = template.render(
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
            content=html,
            content_type="text/html",
            metadata={"locale": locale, "layout": layout_class},
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
            depends_attr = f' data-depends-on="{json.dumps(field.depends_on.model_dump())}"'

        # Required asterisk
        label_text = field_label + (" *" if field.required else "")

        parts = [
            f'<div class="form-field form-field--{field.field_type.value}{size_class}"'
            f'{depends_attr}>',
        ]

        ft = field.field_type

        if ft == FieldType.SELECT:
            parts.append(f'<label for="{field.field_id}">{label_text}</label>')
            if description:
                parts.append(f'<span class="form-field__help">{description}</span>')
            parts.append(self._render_select(field, value, locale, multiple=False))

        elif ft == FieldType.MULTI_SELECT:
            parts.append(f'<label for="{field.field_id}">{label_text}</label>')
            if description:
                parts.append(f'<span class="form-field__help">{description}</span>')
            parts.append(self._render_select(field, value, locale, multiple=True))

        elif ft == FieldType.TEXT_AREA:
            parts.append(f'<label for="{field.field_id}">{label_text}</label>')
            if description:
                parts.append(f'<span class="form-field__help">{description}</span>')
            parts.append(self._render_textarea(field, value, locale))

        elif ft == FieldType.BOOLEAN:
            parts.append(
                f'<label class="form-field__checkbox-label">'
                f'{self._render_checkbox(field, value)}'
                f' {label_text}</label>'
            )

        elif ft == FieldType.GROUP:
            parts.append(f'<fieldset class="form-field__group"><legend>{label_text}</legend>')
            if field.children:
                for child in field.children:
                    parts.append(self._render_field_html(child, prefilled, errors, style, locale))
            parts.append('</fieldset>')

        else:
            parts.append(f'<label for="{field.field_id}">{label_text}</label>')
            if description:
                parts.append(f'<span class="form-field__help">{description}</span>')
            parts.append(self._render_input(field, value, locale))

        if error:
            parts.append(f'<span class="form-field__error" role="alert">{error}</span>')

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

        attrs: list[str] = [
            f'type="{input_type}"',
            f'id="{field.field_id}"',
            f'name="{field.field_id}"',
        ]

        if value is not None:
            attrs.append(f'value="{value}"')
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
        attrs: list[str] = [
            'type="checkbox"',
            f'id="{field.field_id}"',
            f'name="{field.field_id}"',
            'value="true"',
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
        placeholder = _resolve(field.placeholder, locale) if field.placeholder else ""
        attrs: list[str] = [
            f'id="{field.field_id}"',
            f'name="{field.field_id}"',
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

        text_content = str(value) if value is not None else ""
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
        attrs: list[str] = [
            f'id="{field.field_id}"',
            f'name="{field.field_id}"',
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
