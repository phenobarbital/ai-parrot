"""Unit tests for PDF BOOLEAN → Yes / No radio choices (FEAT-800)."""

from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader

from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.pdf import PdfRenderer


def _form(required: bool = False) -> FormSchema:
    field = FormField(
        field_id="has_signage", field_type=FieldType.BOOLEAN, label={"en": "Has signage?"}, required=required
    )
    return FormSchema(form_id="t", title={"en": "T"}, sections=[FormSection(section_id="s", fields=[field])])


async def _reader(prefilled: dict | None = None, required: bool = False) -> PdfReader:
    out = await PdfRenderer().render(_form(required), prefilled=prefilled)
    return PdfReader(BytesIO(out.content))


def _kids(reader: PdfReader) -> list:
    field = reader.trailer["/Root"]["/AcroForm"]["/Fields"][0].get_object()
    return [k.get_object() for k in field["/Kids"]]


def _states(reader: PdfReader) -> dict[str, str]:
    """Map choice value -> appearance state (``/AS``) for each kid widget."""
    states: dict[str, str] = {}
    for kid in _kids(reader):
        value = [n for n in kid["/AP"]["/N"].keys() if n != "/Off"][0].lstrip("/")
        states[value] = str(kid["/AS"]).lstrip("/")
    return states


async def test_pdf_boolean_has_yes_no_choices():
    reader = await _reader()
    fields = reader.get_fields()
    assert "has_signage" in fields
    assert fields["has_signage"]["/FT"] == "/Btn"
    kids = _kids(reader)
    assert len(kids) == 2
    ff = int(reader.trailer["/Root"]["/AcroForm"]["/Fields"][0].get_object()["/Ff"])
    assert ff & (1 << 15), "radio flag must be set (not a checkbox)"
    assert set(_states(reader)) == {"true", "false"}
    words = reader.pages[0].extract_text().split()
    assert "Yes" in words and "No" in words


async def test_pdf_boolean_prefill_false_not_selected_yes():
    states = _states(await _reader({"has_signage": False}))
    assert states == {"true": "Off", "false": "false"}
    states = _states(await _reader({"has_signage": "False"}))
    assert states == {"true": "Off", "false": "false"}


async def test_pdf_boolean_prefill_true_selects_yes():
    assert _states(await _reader({"has_signage": True})) == {"true": "true", "false": "Off"}


async def test_pdf_boolean_none_selects_nothing():
    assert _states(await _reader()) == {"true": "Off", "false": "Off"}
    assert _states(await _reader({"has_signage": None})) == {"true": "Off", "false": "Off"}


async def test_pdf_boolean_required_flag_only_when_required():
    optional = await _reader(required=False)
    required = await _reader(required=True)
    def ff(r):
        return int(r.trailer["/Root"]["/AcroForm"]["/Fields"][0].get_object()["/Ff"])
    assert not ff(optional) & 2
    assert ff(required) & 2
