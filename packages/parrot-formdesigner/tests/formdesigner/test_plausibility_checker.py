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
    _truncate,
    build_items,
    eligible_fields,
    select_fields,
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
        return type(
            "Msg",
            (),
            {"structured_output": self.result, "output": self.result, "model": "fake-model-1", "provider": "fake"},
        )()


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

    def test_select_fields_reports_cap_drops(self):
        """The max_fields tail is returned as not_examined, not silently dropped (FEAT-737 AC3)."""
        cfg = LLMValidationConfig(enabled=True, max_fields=2)
        picked, not_examined = select_fields(_make_form(cfg), SCALARS, cfg)
        assert [f.field_id for f in picked][0] == "name" and len(picked) == 2
        assert set(not_examined) == {"nick0", "name", "color", "doc"} - {f.field_id for f in picked}
        assert set(not_examined.values()) == {"max_fields_cap"}

    def test_select_fields_uncapped_drops_nothing(self, form):
        """Under the default cap every eligible field is sent, so not_examined is empty."""
        picked, not_examined = select_fields(form, SCALARS, form.llm_validation)
        assert {f.field_id for f in picked} == {"nick0", "name", "color", "doc"}
        assert not_examined == {}

    def test_eligible_fields_signature_unchanged(self, form):
        """eligible_fields still returns a bare list of fields (FEAT-737 AC8)."""
        got = eligible_fields(form, SCALARS, form.llm_validation)
        assert isinstance(got, list)
        assert {f.field_id for f in got} == {"nick0", "name", "color", "doc"}

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


class TestLengthCaps:
    """FEAT-737: the prompt's answers and the model's reason are both bounded."""

    def test_truncate_marks_cut_and_respects_limit(self):
        """Over-limit text is cut TO the limit with a marker; short text is untouched."""
        cut = _truncate("x" * 2000, 50)
        assert len(cut) == 50 and cut.endswith("…")
        assert _truncate("ab", 50) == "ab"
        assert _truncate("exactly10!", 10) == "exactly10!"
        assert _truncate("x" * 20, None) == "x" * 20

    def test_build_items_caps_answer(self, form):
        """max_answer_chars bounds the rendered answer; None leaves it verbatim."""
        scalars = {**SCALARS, "name": "y" * 2000}
        capped = build_items(
            form, eligible_fields(form, scalars, form.llm_validation), scalars, locale="en", max_answer_chars=50
        )
        answer = next(i for i in capped if i["field_id"] == "name")["answer"]
        assert len(answer) == 50 and answer.endswith("…")
        uncapped = build_items(form, eligible_fields(form, scalars, form.llm_validation), scalars, locale="en")
        assert next(i for i in uncapped if i["field_id"] == "name")["answer"] == "y" * 2000

    def test_option_labels_still_resolved_under_cap(self, form):
        """Truncation happens after option-label mapping, not instead of it."""
        items = build_items(
            form, eligible_fields(form, SCALARS, form.llm_validation), SCALARS, locale="en", max_answer_chars=50
        )
        assert next(i for i in items if i["field_id"] == "color")["answer"] == "Red"


class TestCoverageReporting:
    """FEAT-737: a status="ok" report can no longer over-claim coverage."""

    async def test_check_reports_unrenderable(self, form):
        """The dict-valued `doc` answer is reported, not silently omitted (AC4)."""
        client = FakeClient(_batch({"field_id": "name", "plausible": True, "confidence": 0.9, "reason": "ok"}))
        rep = await AnswerPlausibilityChecker(client, config=form.llm_validation).check(form, SCALARS, locale="en")
        assert rep.status == "ok"
        assert rep.not_examined == {"doc": "unrenderable_answer"}
        assert set(rep.items) & set(rep.not_examined) == set()

    async def test_check_reports_cap_and_unrenderable_together(self):
        """Both reason codes can appear at once, and items stays disjoint (AC5).

        ``blob`` is ``required``, so the required-first sort keeps it inside the
        ``max_fields=2`` window and it is dropped as unrenderable, while ``late``
        falls off the cap — the only arrangement that exercises both codes in one
        report.
        """
        cfg = LLMValidationConfig(enabled=True, max_fields=2)
        fields = [
            FormField(field_id="blob", field_type=FieldType.TEXT, label="Blob", required=True),
            FormField(field_id="keep", field_type=FieldType.TEXT, label="Keep"),
            FormField(field_id="late", field_type=FieldType.TEXT, label="Late"),
        ]
        form = FormSchema(
            form_id="f",
            title="F",
            sections=[FormSection(section_id="s", fields=fields)],
            llm_validation=cfg,
        )
        scalars = {"blob": {"blob_ref": "b1"}, "keep": "kept", "late": "cut"}
        client = FakeClient(_batch({"field_id": "keep", "plausible": True, "confidence": 0.9, "reason": "ok"}))
        rep = await AnswerPlausibilityChecker(client, config=cfg).check(form, scalars, locale="en")
        assert rep.status == "ok"
        assert rep.not_examined == {"blob": "unrenderable_answer", "late": "max_fields_cap"}
        assert set(rep.items) == {"keep"}
        assert set(rep.items) & set(rep.not_examined) == set()

    async def test_check_all_unrenderable_is_not_silent(self):
        """An all-unrenderable batch is distinguishable from a clean pass, and skips the LLM (AC4)."""
        fields = [FormField(field_id="doc", field_type=FieldType.TEXT, label="Doc")]
        form = FormSchema(
            form_id="f",
            title="F",
            sections=[FormSection(section_id="s", fields=fields)],
            llm_validation=LLMValidationConfig(enabled=True),
        )
        client = FakeClient()
        rep = await AnswerPlausibilityChecker(client, config=form.llm_validation).check(
            form, {"doc": {"blob_ref": "b1"}}, locale="en"
        )
        assert rep.status == "ok" and rep.items == {}
        assert rep.not_examined == {"doc": "unrenderable_answer"}
        assert client.calls == []

    async def test_check_truncates_reason(self, form):
        """A verbose model reason is capped before it is stored (AC7)."""
        cfg = LLMValidationConfig(enabled=True, max_reason_chars=20)
        form = _make_form(cfg)
        client = FakeClient(_batch({"field_id": "name", "plausible": True, "confidence": 0.9, "reason": "z" * 5000}))
        rep = await AnswerPlausibilityChecker(client, config=cfg).check(form, SCALARS, locale="en")
        assert len(rep.items["name"].reason) == 20 and rep.items["name"].reason.endswith("…")

    async def test_check_drops_verdict_for_unsent_field(self, form):
        """A verdict for an eligible-but-unsent field is dropped, keeping the two maps disjoint (AC5)."""
        client = FakeClient(_batch({"field_id": "doc", "plausible": True, "confidence": 0.9, "reason": "invented"}))
        rep = await AnswerPlausibilityChecker(client, config=form.llm_validation).check(form, SCALARS, locale="en")
        assert "doc" not in rep.items
        assert rep.not_examined == {"doc": "unrenderable_answer"}

    async def test_fail_path_has_empty_not_examined(self, form):
        """A skipped report leaves not_examined empty — status already says it all."""
        rep = await AnswerPlausibilityChecker(None, config=form.llm_validation).check(form, SCALARS, locale="en")
        assert rep.status == "skipped" and rep.not_examined == {}

    async def test_zero_eligible_has_empty_not_examined(self):
        """Nothing eligible means nothing cut — the map stays empty (AC3)."""
        form = _make_form(LLMValidationConfig(enabled=False))
        rep = await AnswerPlausibilityChecker(FakeClient(), config=form.llm_validation).check(
            form, SCALARS, locale="en"
        )
        assert rep.status == "ok" and rep.not_examined == {}
