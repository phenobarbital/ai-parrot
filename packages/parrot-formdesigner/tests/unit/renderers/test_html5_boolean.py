"""Unit tests for HTML5 BOOLEAN → Yes / No radios (FEAT-800)."""

from __future__ import annotations

import re

import pytest

from parrot_formdesigner.core.constraints import DependencyRule, FieldCondition
from parrot_formdesigner.core.options import FieldOption
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.html5 import HTML5Renderer


def _form(*fields: FormField) -> FormSchema:
    return FormSchema(form_id="t", title={"en": "T"}, sections=[FormSection(section_id="s", fields=list(fields))])


@pytest.fixture
def boolean_field() -> FormField:
    return FormField(field_id="has_signage", field_type=FieldType.BOOLEAN, label={"en": "Has signage?"})


async def _render(field: FormField, prefilled: dict | None = None) -> str:
    out = await HTML5Renderer().render(_form(field), prefilled=prefilled)
    return out.content


def _radios(html: str) -> list[str]:
    return re.findall(r"<input type=\"radio\"[^>]*>", html)


async def test_boolean_renders_two_radios_yes_no(boolean_field):
    html = await _render(boolean_field)
    radios = _radios(html)
    assert len(radios) == 2
    assert 'value="true"' in radios[0] and 'value="false"' in radios[1]
    assert all('name="has_signage"' in r for r in radios)
    assert "> Yes</label>" in html and "> No</label>" in html
    assert 'type="checkbox"' not in html
    assert "form-field__radio-group" in html and "form-field__radio-label" in html


async def test_boolean_none_checks_nothing(boolean_field):
    html = await _render(boolean_field, {"has_signage": None})
    assert all("checked" not in r for r in _radios(html))
    html = await _render(boolean_field)
    assert all("checked" not in r for r in _radios(html))


@pytest.mark.parametrize("raw", [True, "true", "True", 1, "1"])
async def test_boolean_true_checks_yes(boolean_field, raw):
    radios = _radios(await _render(boolean_field, {"has_signage": raw}))
    assert "checked" in radios[0] and "checked" not in radios[1]


@pytest.mark.parametrize("raw", [False, "false", "False", 0, "0"])
async def test_boolean_false_checks_no(boolean_field, raw):
    radios = _radios(await _render(boolean_field, {"has_signage": raw}))
    assert "checked" not in radios[0] and "checked" in radios[1]


async def test_boolean_required_on_radios():
    field = FormField(field_id="b", field_type=FieldType.BOOLEAN, label={"en": "B"}, required=True)
    assert all(" required" in r for r in _radios(await _render(field)))
    optional = FormField(field_id="b", field_type=FieldType.BOOLEAN, label={"en": "B"})
    assert all("required" not in r for r in _radios(await _render(optional)))


async def test_boolean_label_once(boolean_field):
    html = await _render(boolean_field)
    assert html.count("Has signage?") == 1
    assert html.index("Has signage?") < html.index("form-field__radio-group")


async def test_boolean_depends_on_emitted():
    field = FormField(
        field_id="b",
        field_type=FieldType.BOOLEAN,
        label={"en": "B"},
        depends_on=DependencyRule(conditions=[FieldCondition(field_id="other", operator="eq", value="x")]),
    )
    html = await _render(field)
    assert "data-depends-on=" in html
    assert len(_radios(html)) == 2


async def test_boolean_registry_path_matches(boolean_field):
    registry = HTML5Renderer()._registry
    out = await registry[FieldType.BOOLEAN].render(boolean_field, prefilled=True)
    text = out if isinstance(out, str) else str(getattr(out, "content", out))
    radios = _radios(text)
    assert len(radios) == 2 and "checked" in radios[0]
    assert 'type="checkbox"' not in text


async def test_select_radio_unchanged():
    field = FormField(
        field_id="color",
        field_type=FieldType.SELECT,
        label={"en": "Color"},
        meta={"render_as": "radio"},
        options=[FieldOption(value="r", label={"en": "Red"}), FieldOption(value="g", label={"en": "Green"})],
    )
    group = HTML5Renderer()._render_radio_group(field, "g", "en")
    label_cls = "form-field__radio-label inline-flex items-center gap-2 text-sm text-gray-700 cursor-pointer"
    input_cls = "h-4 w-4 border-gray-300 text-blue-600 focus:ring-blue-500"
    expected = (
        '<div class="form-field__radio-group space-y-2">\n'
        f'<label class="{label_cls}"><input type="radio" name="color" value="r" class="{input_cls}"> Red</label>\n'
        f'<label class="{label_cls}"><input type="radio" name="color" value="g" class="{input_cls}" checked> Green</label>\n'
        "</div>"
    )
    assert group == expected
