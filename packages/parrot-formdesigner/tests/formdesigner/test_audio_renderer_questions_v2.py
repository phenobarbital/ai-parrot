from __future__ import annotations

from parrot_formdesigner.core.options import FieldOption
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection, FormSubsection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.audio import AudioFormRenderer


def _form() -> FormSchema:
    color = FormField(
        field_id="color", field_type=FieldType.SELECT, label="Color",
        options=[FieldOption(value="r", label="Red"), FieldOption(value="g", label="Green", disabled=True)],
    )
    name = FormField(field_id="name", field_type=FieldType.TEXT, label="Name", hint={"en": "First name", "es": "Nombre"},
                     meta={"voice": {"prompt": "{n}/{total}: {label} {{ 7*7 }}"}})
    pin = FormField(field_id="pin", field_type=FieldType.TEXT, label="PIN", meta={"voice": {"sensitive": True}})
    return FormSchema(
        form_id="demo", title="Demo", tenant="acme",
        sections=[
            FormSection(section_id="a", title="About you", fields=[name, FormSubsection(subsection_id="sub", title="Prefs", fields=[color])]),
            FormSection(section_id="b", title="Security", fields=[pin]),
        ],
    )


def test_section_context_and_order():
    qs = AudioFormRenderer().split_into_questions(_form())
    assert [q.field_id for q in qs] == ["name", "color", "pin"]
    assert qs[0].section_title == "About you" and qs[1].subsection_title == "Prefs"
    assert qs[2].section_title == "Security"


def test_hint_localized_and_prompt_not_jinja():
    qs = AudioFormRenderer().split_into_questions(_form(), locale="es")
    assert qs[0].hint == "Nombre"
    assert qs[0].prompt.startswith("1/3: Name")
    assert "49" not in qs[0].prompt


def test_disabled_option_kept_with_flag():
    color = AudioFormRenderer().split_into_questions(_form())[1]
    assert {o["value"]: o["disabled"] for o in color.options} == {"r": False, "g": True}


def test_sensitive_via_voice_meta_and_answer_modes():
    qs = AudioFormRenderer().split_into_questions(_form())
    assert qs[2].sensitive is True
    assert qs[1].answer_modes == ["voice", "selection"]


def test_group_children_inherit_section():
    kids = [
        FormField(field_id="k1", field_type=FieldType.TEXT, label="K1"),
        FormField(field_id="k2", field_type=FieldType.TEXT, label="K2"),
    ]
    grp = FormField(field_id="g", field_type=FieldType.GROUP, label="G", children=kids)
    sec = FormSection(section_id="s", title="Sec", fields=[grp])
    form = FormSchema(form_id="f", title="F", tenant="acme", sections=[sec])
    qs = AudioFormRenderer().split_into_questions(form)
    assert [q.field_id for q in qs] == ["k1", "k2"]
    assert all(q.section_uid == str(sec.section_uid) and q.section_title == "Sec" for q in qs)
