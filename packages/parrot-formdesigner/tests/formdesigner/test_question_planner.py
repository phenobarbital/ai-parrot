"""Tests for QuestionPlanner (FEAT-649, TASK-4217)."""

import logging

import pytest

from parrot_formdesigner.audio.models import AudioAnswer, AudioFormManifest
from parrot_formdesigner.audio.planner import QuestionPlanner
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection, FormSubsection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.core.voice import VoiceFormConfig
from parrot_formdesigner.renderers.audio import AudioFormRenderer
from parrot_formdesigner.services.rule_evaluator import RuleResolution


def _f(fid: str, required: bool = False, **kw) -> FormField:
    return FormField(field_id=fid, field_type=kw.pop("field_type", FieldType.TEXT), label=fid, required=required, **kw)


@pytest.fixture
def form_and_manifest():
    form = FormSchema(
        form_id="plan",
        title="Plan",
        sections=[
            FormSection(
                section_id="s1",
                title="One",
                fields=[
                    _f("r1", True),
                    _f("o1"),
                    _f("r2", True),
                    FormSubsection(subsection_id="sub", title="Sub", fields=[_f("o2")]),
                ],
            ),
            FormSection(
                section_id="s2",
                title="Two",
                fields=[
                    _f("r3", True),
                    _f("r4", True),
                    _f("grp", field_type=FieldType.GROUP, children=[_f("c1"), _f("c2")]),
                    _f("o3"),
                ],
            ),
        ],
    )
    questions = AudioFormRenderer().split_into_questions(form)
    manifest = AudioFormManifest(
        form_uid=str(form.form_uid),
        title="Plan",
        total_questions=len(questions),
        questions=questions,
        ws_endpoint="/ws",
    )
    return form, manifest


def _ans(fid: str) -> AudioAnswer:
    return AudioAnswer(field_id=fid, value="x")


async def test_planner_cap_keeps_required(form_and_manifest, caplog):
    form, manifest = form_and_manifest
    planner = QuestionPlanner(form, manifest, VoiceFormConfig(max_questions=3))
    with caplog.at_level(logging.WARNING):
        plan, delta = await planner.replan({}, locale="en", resolution=RuleResolution())
    assert plan == ["r1", "r2", "r3", "r4"]
    assert "required_exceeds_cap" in caplog.text
    assert "o1" in delta.hidden_by_cap and "o3" in delta.hidden_by_cap


async def test_cap_fills_optional_in_order(form_and_manifest):
    form, manifest = form_and_manifest
    planner = QuestionPlanner(form, manifest, VoiceFormConfig(max_questions=6))
    plan, delta = await planner.replan({}, locale="en", resolution=RuleResolution())
    assert plan[:2] == ["r1", "o1"] and len(plan) == 6
    assert plan == [f for f in planner._order if f in plan]
    assert set(delta.hidden_by_cap).isdisjoint(plan)


async def test_planner_replan_cascade_clear_and_sections(form_and_manifest):
    form, manifest = form_and_manifest
    planner = QuestionPlanner(form, manifest, VoiceFormConfig(max_questions=None))
    answers = {"o1": _ans("o1"), "r1": _ans("r1")}
    res = RuleResolution(visible={"o1": False}, cleared=["r2"], computed={"k": 1})
    plan, delta = await planner.replan(answers, locale="en", resolution=res)
    assert "o1" not in plan and delta.hidden == ["o1"]
    assert delta.cleared == ["o1", "r2"] and delta.computed == {"k": 1}
    assert planner.next_cursor(plan, answers) == "r2"
    assert planner.section_of("r1") != planner.section_of("r3")
    assert planner.section_of("o2") == planner.section_of("r1")
    assert planner.next_cursor(plan, {f: _ans(f) for f in plan}) is None


async def test_required_changed_and_effective_required(form_and_manifest):
    form, manifest = form_and_manifest
    planner = QuestionPlanner(form, manifest, VoiceFormConfig(max_questions=None))
    await planner.replan({}, locale="en", resolution=RuleResolution(required={"o1": False, "r1": True}))
    _, delta = await planner.replan({}, locale="en", resolution=RuleResolution(required={"o1": True, "r1": False}))
    assert delta.required_changed["o1"] is True and delta.required_changed["r1"] is False
    assert planner.effective_required("r1") is False  # dynamic, static flag is True


async def test_group_children_inherit_parent_visibility(form_and_manifest):
    form, manifest = form_and_manifest
    planner = QuestionPlanner(form, manifest, VoiceFormConfig(max_questions=None))
    plan, _ = await planner.replan({}, locale="en", resolution=RuleResolution(visible={"grp": False}))
    assert "c1" not in plan and "c2" not in plan
    await planner.replan({}, locale="en", resolution=RuleResolution(required={"grp": True}))
    assert planner.effective_required("c1") is True


async def test_subsection_depends_on_ignored_q1(form_and_manifest):
    form, manifest = form_and_manifest
    planner = QuestionPlanner(form, manifest, VoiceFormConfig(max_questions=None))
    plan, _ = await planner.replan({}, locale="en", resolution=RuleResolution())
    assert "o2" in plan


async def test_replan_calls_rule_evaluator(form_and_manifest):
    form, manifest = form_and_manifest
    planner = QuestionPlanner(form, manifest, VoiceFormConfig(max_questions=None))
    plan, _ = await planner.replan({"r1": _ans("r1")}, locale="en")
    assert "r1" in plan


def test_previous(form_and_manifest):
    form, manifest = form_and_manifest
    planner = QuestionPlanner(form, manifest, VoiceFormConfig())
    plan = ["a", "b", "c"]
    assert planner.previous(plan, ["a", "b"], "a") == "a"
    assert planner.previous(plan, ["a", "x", "b"], "zzz") == "a"
    assert planner.previous(plan, ["b"], None) is None
