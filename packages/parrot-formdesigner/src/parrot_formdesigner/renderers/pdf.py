"""PDF AcroForm fillable renderer for ``FormSchema`` (FEAT-152 Wave 2b).

Uses ``reportlab.pdfgen.canvas.Canvas`` + ``canvas.acroForm`` to emit a
fillable PDF (AcroForm). Layout: vertical single-column with section
headers and label-above-input blocks.

Per Q4 (resolved): fields not natively expressible in AcroForm
(``FILE``, ``IMAGE``, ``ARRAY``, ``GROUP``) become flat textfield
placeholders with a form-level meta note listing them.

Output format: ``RenderedForm(content=<pdf-bytes>, content_type="application/pdf",
metadata={"unsupported_fields": [...]})``.
"""

from __future__ import annotations

import logging
from io import BytesIO
from typing import Any

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

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
from .base import AbstractFormRenderer, FallbackRenderer, FieldRenderer


logger = logging.getLogger(__name__)


# AcroForm-unsupported FieldTypes — Q4 resolution.
_UNSUPPORTED_TYPES = frozenset({
    FieldType.FILE,
    FieldType.IMAGE,
    FieldType.ARRAY,
    FieldType.GROUP,
})

# New field types that emit RenderWarning in PDF (rendered as placeholder textfields)
_PDF_FALLBACK_NEW_TYPES = frozenset({
    FieldType.SIGNATURE,
    FieldType.REMOTE_RESPONSE,
    FieldType.AVAILABILITY,
    FieldType.TRANSFER_LIST,
    FieldType.DYNAMIC_SELECT,
    FieldType.REST,  # FEAT-170: REST upload not supported in PDF
})


def _localize(
    value: LocalizedString | None, locale: str, default: str = ""
) -> str:
    """Resolve a ``LocalizedString`` to a plain string."""
    if value is None:
        return default
    if isinstance(value, str):
        return value
    if locale in value:
        return value[locale]
    lang = locale.split("-")[0]
    if lang in value:
        return value[lang]
    if "en" in value:
        return value["en"]
    return next(iter(value.values()), default)


class PdfRenderer(AbstractFormRenderer):
    """Render a ``FormSchema`` as a fillable PDF (AcroForm).

    Layout: single-column vertical, A4 portrait. Section headers in bold,
    label above each input. ``style`` / ``prefilled`` / ``errors`` are
    accepted (per the base contract) but only ``prefilled`` is used to
    seed default values on textfields where supported.

    The renderer logs warnings for unsupported field types
    (``FILE``/``IMAGE``/``ARRAY``/``GROUP``) and includes them in
    ``RenderedForm.metadata["unsupported_fields"]``.
    """

    # Layout constants
    PAGE_WIDTH, PAGE_HEIGHT = A4
    MARGIN_X = 20 * mm
    MARGIN_Y_TOP = 20 * mm
    MARGIN_Y_BOTTOM = 20 * mm
    LINE_HEIGHT = 6 * mm
    FIELD_WIDTH = 160 * mm
    FIELD_HEIGHT = 8 * mm
    SECTION_GAP = 8 * mm
    FIELD_GAP = 4 * mm

    def __init__(self) -> None:
        """Initialize PdfRenderer with per-type renderer registry."""
        self._fallback = FallbackRenderer()
        self._registry: dict[FieldType, FieldRenderer] = {}
        self._build_registry()

    def _build_registry(self) -> None:
        """Populate per-type renderer registry for PDF output.

        Each registered FieldRenderer wraps the existing AcroForm dispatch
        via _render_field. The PDF renderer's field rendering is stateful
        (canvas position), so entries are lightweight async stubs that
        delegate to _render_field.
        """

        class _PdfFieldRenderer:
            """Async FieldRenderer stub that delegates to PdfRenderer._render_field."""

            def __init__(self_, renderer: "PdfRenderer") -> None:
                self_._r = renderer

            async def render(self_, field: FormField, *, locale: str = "en", prefilled: Any = None, error: str | None = None) -> Any:
                # PDF rendering is canvas-stateful; direct invocation via render()
                # passes context via _render_field. This stub satisfies the protocol.
                return None

        renderer_inst = _PdfFieldRenderer(self)
        self._registry = {ft: renderer_inst for ft in FieldType}

    async def render(
        self,
        form: FormSchema,
        style: StyleSchema | None = None,
        *,
        locale: str = "en",
        prefilled: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> RenderedForm:
        """Render ``form`` as a fillable PDF.

        Args:
            form: The form schema.
            style: Ignored.
            locale: BCP 47 locale tag for label resolution.
            prefilled: Optional initial values keyed by ``field_id``.
            errors: Ignored.

        Returns:
            ``RenderedForm`` carrying the PDF bytes,
            ``content_type="application/pdf"``, and a
            ``metadata["unsupported_fields"]`` list.
        """
        buffer = BytesIO()
        c = canvas.Canvas(buffer, pagesize=A4)
        unsupported: list[dict[str, str]] = []
        render_warnings: list[RenderWarning] = []

        cursor_y = self.PAGE_HEIGHT - self.MARGIN_Y_TOP

        # Form title
        title_text = _localize(form.title, locale, default=form.form_id)
        c.setFont("Helvetica-Bold", 14)
        c.drawString(self.MARGIN_X, cursor_y, title_text)
        cursor_y -= self.LINE_HEIGHT * 2

        for section in form.sections:
            cursor_y = self._render_section(
                c, section, cursor_y, locale, prefilled, unsupported, render_warnings
            )

        # Trailing meta note for unsupported fields
        if unsupported:
            cursor_y = self._maybe_new_page(c, cursor_y, mm * 30)
            c.setFont("Helvetica-Bold", 10)
            c.drawString(
                self.MARGIN_X,
                cursor_y,
                "Fields not fillable in this PDF (use the web UI):",
            )
            cursor_y -= self.LINE_HEIGHT
            c.setFont("Helvetica", 9)
            for entry in unsupported:
                cursor_y = self._maybe_new_page(c, cursor_y, mm * 10)
                c.drawString(
                    self.MARGIN_X + 4 * mm,
                    cursor_y,
                    f"• {entry['section_id']}.{entry['field_id']} ({entry['field_type']})",
                )
                cursor_y -= self.LINE_HEIGHT

        c.showPage()
        c.save()

        return RenderedForm(
            content=buffer.getvalue(),
            content_type="application/pdf",
            metadata={"unsupported_fields": unsupported},
            warnings=render_warnings,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _maybe_new_page(
        self, c: canvas.Canvas, cursor_y: float, needed: float
    ) -> float:
        """Start a new page if there isn't enough vertical room.

        Returns the (possibly reset) ``cursor_y`` to draw at.
        """
        if cursor_y - needed < self.MARGIN_Y_BOTTOM:
            c.showPage()
            return self.PAGE_HEIGHT - self.MARGIN_Y_TOP
        return cursor_y

    def _render_section(
        self,
        c: canvas.Canvas,
        section: FormSection,
        cursor_y: float,
        locale: str,
        prefilled: dict[str, Any] | None,
        unsupported: list[dict[str, str]],
        render_warnings: list[RenderWarning] | None = None,
    ) -> float:
        """Render a section header + its fields. Returns updated ``cursor_y``."""
        if render_warnings is None:
            render_warnings = []
        # Section header
        cursor_y = self._maybe_new_page(c, cursor_y, mm * 30)
        section_title = _localize(
            section.title, locale, default=section.section_id
        )
        c.setFont("Helvetica-Bold", 11)
        c.drawString(self.MARGIN_X, cursor_y, section_title)
        cursor_y -= self.FIELD_GAP
        c.line(
            self.MARGIN_X,
            cursor_y,
            self.MARGIN_X + self.FIELD_WIDTH,
            cursor_y,
        )
        cursor_y -= self.LINE_HEIGHT

        for item in section.fields:
            if isinstance(item, FormSubsection):
                cursor_y = self._render_subsection(
                    c, section.section_id, item, cursor_y, locale, prefilled,
                    unsupported, render_warnings
                )
            else:
                cursor_y = self._render_field(
                    c, section.section_id, item, cursor_y, locale, prefilled,
                    unsupported, render_warnings
                )

        return cursor_y - self.SECTION_GAP

    def _render_subsection(
        self,
        c: canvas.Canvas,
        section_id: str,
        subsection: FormSubsection,
        cursor_y: float,
        locale: str,
        prefilled: dict[str, Any] | None,
        unsupported: list[dict[str, str]],
        render_warnings: list[RenderWarning] | None = None,
    ) -> float:
        """Render a subsection header and its fields. Returns new ``cursor_y``."""
        if render_warnings is None:
            render_warnings = []
        if subsection.title:
            cursor_y = self._maybe_new_page(c, cursor_y, mm * 20)
            title = _localize(subsection.title, locale, default=subsection.subsection_id)
            c.setFont("Helvetica-Bold", 10)
            c.drawString(self.MARGIN_X + mm * 4, cursor_y, title)
            cursor_y -= self.LINE_HEIGHT

        for field in subsection.fields:
            cursor_y = self._render_field(
                c, section_id, field, cursor_y, locale, prefilled,
                unsupported, render_warnings
            )
        return cursor_y

    def _render_field(
        self,
        c: canvas.Canvas,
        section_id: str,
        field: FormField,
        cursor_y: float,
        locale: str,
        prefilled: dict[str, Any] | None,
        unsupported: list[dict[str, str]],
        render_warnings: list[RenderWarning] | None = None,
    ) -> float:
        """Render a single field (label + AcroForm widget). Returns new ``cursor_y``."""
        if render_warnings is None:
            render_warnings = []
        cursor_y = self._maybe_new_page(c, cursor_y, mm * 25)

        label = _localize(field.label, locale, default=field.field_id)
        if field.required:
            label = f"{label} *"

        # Label
        c.setFont("Helvetica", 10)
        c.drawString(self.MARGIN_X, cursor_y, label)
        cursor_y -= self.FIELD_HEIGHT

        prefilled_value = (
            str(prefilled[field.field_id])
            if prefilled and field.field_id in prefilled
            else ""
        )

        form = c.acroForm
        x = self.MARGIN_X
        y = cursor_y
        width = self.FIELD_WIDTH
        height = self.FIELD_HEIGHT

        if field.field_type in _UNSUPPORTED_TYPES:
            unsupported.append({
                "section_id": section_id,
                "field_id": field.field_id,
                "field_type": field.field_type.value,
            })
            logger.warning(
                "PDF AcroForm: unsupported field type %s for %s.%s; "
                "emitting flat textfield placeholder",
                field.field_type.value,
                section_id,
                field.field_id,
            )
            form.textfield(
                name=field.field_id,
                tooltip=f"{field.field_type.value} (not natively fillable)",
                x=x, y=y, width=width, height=height, fontSize=10,
                value=prefilled_value or "",
            )
        elif field.field_type == FieldType.BOOLEAN:
            form.checkbox(
                name=field.field_id,
                tooltip=label,
                x=x, y=y, size=4 * mm,
                checked=bool(prefilled_value),
            )
        elif field.field_type == FieldType.SELECT:
            options = self._make_options(field)
            form.choice(
                name=field.field_id,
                tooltip=label,
                options=options or [("(none)", "")],
                x=x, y=y, width=width, height=height, fontSize=10,
                value=prefilled_value or (options[0][1] if options else ""),
            )
        elif field.field_type == FieldType.MULTI_SELECT:
            options = self._make_options(field)
            form.listbox(
                name=field.field_id,
                tooltip=label,
                options=options or [("(none)", "")],
                x=x, y=y, width=width, height=height * 3, fontSize=10,
                fieldFlags="multiSelect",
            )
            cursor_y -= height * 2  # listbox takes 3x vertical space
        elif field.field_type == FieldType.TEXT_AREA:
            form.textfield(
                name=field.field_id,
                tooltip=label,
                x=x, y=y - height * 2, width=width, height=height * 3,
                fontSize=10, fieldFlags="multiline",
                value=prefilled_value,
            )
            cursor_y -= height * 2  # multiline takes 3x vertical space
        elif field.field_type == FieldType.PASSWORD:
            form.textfield(
                name=field.field_id,
                tooltip=label,
                x=x, y=y, width=width, height=height, fontSize=10,
                fieldFlags="password",
                value=prefilled_value,
            )
        elif field.field_type == FieldType.HIDDEN:
            form.textfield(
                name=field.field_id,
                tooltip=label,
                x=x, y=y, width=width, height=height, fontSize=10,
                fieldFlags="hidden",
                value=prefilled_value,
            )

        # New field types (FEAT-167) — numeric input for NPS/LIKERT/RANKING
        elif field.field_type == FieldType.NPS:
            form.textfield(
                name=field.field_id,
                tooltip=f"{label} (0–10)",
                x=x, y=y, width=width, height=height, fontSize=10,
                value=prefilled_value or "",
            )
        elif field.field_type in (FieldType.LIKERT, FieldType.RANKING):
            c_obj = field.constraints
            scale_min = c_obj.scale_min if c_obj and c_obj.scale_min is not None else 0
            scale_max = c_obj.scale_max if c_obj and c_obj.scale_max is not None else 5
            form.textfield(
                name=field.field_id,
                tooltip=f"{label} ({scale_min}–{scale_max})",
                x=x, y=y, width=width, height=height, fontSize=10,
                value=prefilled_value or "",
            )
        elif field.field_type == FieldType.LOCATION:
            # Render location as text field — pycountry data cannot populate AcroForm choice
            form.textfield(
                name=field.field_id,
                tooltip=f"{label} (ISO country code)",
                x=x, y=y, width=width, height=height, fontSize=10,
                value=prefilled_value or "",
            )
        elif field.field_type == FieldType.TAGS:
            form.textfield(
                name=field.field_id,
                tooltip=f"{label} (comma-separated tags)",
                x=x, y=y, width=width, height=height, fontSize=10,
                value=prefilled_value or "",
            )

        elif field.field_type in _PDF_FALLBACK_NEW_TYPES:
            # Fallback: render as placeholder textfield + emit RenderWarning
            render_warnings.append(RenderWarning(
                field_id=field.field_id,
                field_type=field.field_type.value,
                renderer="pdf",
                reason=(
                    f"unsupported {field.field_type.value} in pdf"
                    " — rendered as placeholder"
                ),
            ))
            logger.warning(
                "PDF AcroForm: new field type %s for %s.%s rendered as placeholder",
                field.field_type.value,
                section_id,
                field.field_id,
            )
            form.textfield(
                name=field.field_id,
                tooltip=f"{field.field_type.value} (not natively fillable in PDF)",
                x=x, y=y, width=width, height=height, fontSize=10,
                value=prefilled_value or "",
            )

        else:
            # TEXT, NUMBER, INTEGER, EMAIL, URL, PHONE, DATE, DATETIME, TIME, COLOR
            tooltip = label
            if field.field_type in {FieldType.NUMBER, FieldType.INTEGER}:
                tooltip = f"{label} (number)"
            elif field.field_type in {FieldType.DATE, FieldType.DATETIME, FieldType.TIME}:
                tooltip = f"{label} ({field.field_type.value})"
            elif field.field_type == FieldType.COLOR:
                tooltip = f"{label} (hex color)"
            form.textfield(
                name=field.field_id,
                tooltip=tooltip,
                x=x, y=y, width=width, height=height, fontSize=10,
                value=prefilled_value,
            )

        return cursor_y - self.LINE_HEIGHT - self.FIELD_GAP

    def _make_options(self, field: FormField) -> list[tuple[str, str]]:
        """Build the ``options=`` list for ``acroForm.choice/listbox``."""
        if not field.options:
            return []
        out: list[tuple[str, str]] = []
        for option in field.options:
            label = (
                option.label
                if isinstance(option.label, str)
                else option.label.get("en", option.value)
                if isinstance(option.label, dict)
                else option.value
            )
            out.append((str(label), option.value))
        return out
