"""Unit tests for FEAT-393 Module 11 — RenderWarning.field_uid.

Spec §4 Module 11 (TASK-2005). Every ``RenderWarning`` emitted by the
html5, adaptive_card, and pdf renderers must carry ``field_uid`` alongside
``field_id`` — designer tooling gets stable identity while the
human-readable ``field_id`` stays for logging/messages.
"""

from __future__ import annotations

import pytest
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.html5 import HTML5Renderer
from parrot_formdesigner.renderers.pdf import PdfRenderer


@pytest.fixture
def formula_form() -> FormSchema:
    """A form with a FORMULA field — html5 renders it as a read-only
    placeholder and emits a RenderWarning (evaluator is FEAT-301)."""
    return FormSchema(
        form_id="formula-form",
        title={"en": "Formula Form"},
        sections=[
            FormSection(
                section_id="s1",
                fields=[
                    FormField(
                        field_id="total",
                        field_type=FieldType.FORMULA,
                        label={"en": "Total"},
                    ),
                ],
            )
        ],
    )


@pytest.fixture
def signature_form() -> FormSchema:
    """A form with a SIGNATURE field — pdf renders it as a placeholder
    textfield and emits a RenderWarning (unsupported AcroForm widget)."""
    return FormSchema(
        form_id="signature-form",
        title={"en": "Signature Form"},
        sections=[
            FormSection(
                section_id="s1",
                fields=[
                    FormField(
                        field_id="signee",
                        field_type=FieldType.SIGNATURE,
                        label={"en": "Sign here"},
                    ),
                ],
            )
        ],
    )


@pytest.mark.asyncio
async def test_render_warning_field_uid_html5(formula_form: FormSchema) -> None:
    """FEAT-393: html5's FORMULA RenderWarning carries field_uid."""
    field = formula_form.sections[0].fields[0]
    out = await HTML5Renderer().render(formula_form)
    formula_warnings = [w for w in out.warnings if w.field_type == "formula"]
    assert len(formula_warnings) == 1
    assert formula_warnings[0].field_id == "total"
    assert formula_warnings[0].field_uid == field.field_uid


@pytest.mark.asyncio
async def test_render_warning_field_uid_pdf(signature_form: FormSchema) -> None:
    """FEAT-393: pdf's SIGNATURE fallback RenderWarning carries field_uid."""
    field = signature_form.sections[0].fields[0]
    out = await PdfRenderer().render(signature_form)
    signature_warnings = [w for w in out.warnings if w.field_type == "signature"]
    assert len(signature_warnings) == 1
    assert signature_warnings[0].field_id == "signee"
    assert signature_warnings[0].field_uid == field.field_uid
