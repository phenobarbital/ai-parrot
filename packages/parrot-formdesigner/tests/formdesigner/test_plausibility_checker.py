"""Unit tests for AnswerPlausibilityChecker (FEAT-649 Module 8)."""

import asyncio

import pytest

from parrot_formdesigner.core.llm_validation import LLMValidationConfig
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.core.options import FieldOption
from parrot_formdesigner.services.plausibility import (
    AnswerPlausibilityChecker,
    PlausibilityBatch,
    PlausibilityBlocked,
    build_items,
    eligible_fields,
)


class FakeClient:
    """Records ask() calls; returns a configurable batch, raises, or sleeps."""

    def __init__(self, result=None, exc=None, delay=0.0):
        self.calls, self.result, self.exc, self.delay = [], result, exc, delay

    async def ask(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.exc:
            raise self.exc
        return type("Msg", (), {"structured_output": self.result, "output": self.result})()


def _make_form(cfg: LLMValidationConfig | None = None) -> FormSchema:
    fields = [
        FormField(field_id="nick0", field_type=FieldType.TEXT, label="Optional"),
        FormField(field_id="name", field_type=FieldType.TEXT, label="Name", required=True),
        FormField(
            field_id="color",
            field_type=FieldType.SELECT,
            label="Color",
            options=[FieldOption(value="r", label="Red"), FieldOption(value="b", label="Blue")],
        ),
        FormField(field_id="pin", field_type=FieldType.PASSWORD, label="Pin"),
        FormField(field_id="h", field_type=FieldType.HIDDEN, label="H"),
        FormField(field_id="nick", field_type=FieldType.TEXT, label="Nick", read_only=True),
        FormField(field_id="secret", field_type=FieldType.TEXT, label="Secret", meta={"voice": {"sensitive": True}}),
        FormField(field_id="doc", field_type=FieldType.TEXT, label="Doc"),
    ]
    return FormSchema(
        form_id="f",
        title="F",
        sections=[FormSection(section_id="s", fields=fields)],
        llm_validation=cfg or LLMValidationConfig(enabled=True),
    )


SCALARS = {
    "nick0": "x",
    "name": "Ann",
    "color": "r",
    "pin": "1234",
    "h": "hid",
    "nick": "n",
    "secret": "TOPSECRET",
    "doc": {"blob_ref": "b1", "data_url": "data:x"},
}


@pytest.fixture
def form() -> FormSchema:
    return _make_form()


def _batch(*items):
    return PlausibilityBatch.model_validate({"items": list(items)})


class TestEligibility:
    def test_privacy_exclusions(self, form):
        ids = {f.field_id for f in eligible_fields(form, SCALARS, form.llm_validation)}
        assert ids == {"nick0", "name", "color", "doc"}

    def test_required_first_and_max_fields(self):
        cfg = LLMValidationConfig(enabled=True, max_fields=2)
        form = _make_form(cfg)
        got = [f.field_id for f in eligible_fields(form, SCALARS, cfg)]
        assert got[0] == "name" and len(got) == 2

    def test_only_subset(self, form):
        got = eligible_fields(form, SCALARS, form.llm_validation, only={"color"})
        assert [f.field_id for f in got] == ["color"]

    def test_prompt_has_no_blob_or_data_url(self, form):
        fields = eligible_fields(form, SCALARS, form.llm_validation)
        items = build_items(form, fields, SCALARS, locale="en")
        text = str(items)
        assert "blob_ref" not in text and "data_url" not in text and "TOPSECRET" not in text
        assert {i["field_id"] for i in items} == {"nick0", "name", "color"}
        color = next(i for i in items if i["field_id"] == "color")
        assert color["answer"] == "Red" and color["options"] == ["Red", "Blue"]


class TestCheck:
    async def test_single_batched_call(self, form):
        client = FakeClient(_batch({"field_id": "name", "plausible": True, "confidence": 0.9, "reason": "ok"}))
        rep = await AnswerPlausibilityChecker(client, config=form.llm_validation).check(form, SCALARS, locale="en")
        assert len(client.calls) == 1
        assert client.calls[0][1]["structured_output"] is PlausibilityBatch
        assert "blob_ref" not in client.calls[0][0] and "TOPSECRET" not in client.calls[0][0]
        assert rep.status == "ok" and "name" in rep.items

    async def test_zero_eligible_no_call(self):
        form = _make_form(LLMValidationConfig(enabled=False))
        client = FakeClient()
        rep = await AnswerPlausibilityChecker(client, config=form.llm_validation).check(form, SCALARS, locale="en")
        assert client.calls == [] and rep.status == "ok" and rep.items == {}

    async def test_skip_on_none_client(self, form):
        rep = await AnswerPlausibilityChecker(None, config=form.llm_validation).check(form, SCALARS, locale="en")
        assert rep.status == "skipped" and rep.reason

    async def test_block_raises(self):
        cfg = LLMValidationConfig(enabled=True, on_error="block")
        form = _make_form(cfg)
        with pytest.raises(PlausibilityBlocked):
            await AnswerPlausibilityChecker(None, config=cfg).check(form, SCALARS, locale="en")
        with pytest.raises(PlausibilityBlocked):
            await AnswerPlausibilityChecker(FakeClient(exc=RuntimeError("x")), config=cfg).check(
                form, SCALARS, locale="en"
            )

    async def test_timeout_maps_on_error(self):
        cfg = LLMValidationConfig(enabled=True, timeout_s=0.05)
        form = _make_form(cfg)
        rep = await AnswerPlausibilityChecker(FakeClient(delay=1.0), config=cfg).check(form, SCALARS, locale="en")
        assert rep.status == "skipped"
        cfg2 = LLMValidationConfig(enabled=True, timeout_s=0.05, on_error="block")
        with pytest.raises(PlausibilityBlocked):
            await AnswerPlausibilityChecker(FakeClient(delay=1.0), config=cfg2).check(
                _make_form(cfg2), SCALARS, locale="en"
            )

    async def test_unparsable_skips(self, form):
        rep = await AnswerPlausibilityChecker(FakeClient("not json"), config=form.llm_validation).check(
            form, SCALARS, locale="en"
        )
        assert rep.status == "skipped"

    async def test_unknown_id_dropped_and_clamped(self, form):
        client = FakeClient(
            _batch(
                {"field_id": "name", "plausible": False, "confidence": 1.7, "reason": "noise"},
                {"field_id": "ghost", "plausible": True, "confidence": 0.5},
            )
        )
        rep = await AnswerPlausibilityChecker(client, config=form.llm_validation).check(form, SCALARS, locale="en")
        assert set(rep.items) == {"name"} and rep.items["name"].confidence == 1.0
