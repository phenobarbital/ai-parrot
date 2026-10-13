import typing

import pytest
from pydantic import ValidationError

from parrot_formdesigner.audio import events as ev
from parrot_formdesigner.audio.models import Phase as ModelsPhase


def _all_type_literals() -> list[str]:
    models = []
    for union in (ev.InboundEvent, ev.WireMessage, ev.IORequest):
        args = typing.get_args(union)
        members = typing.get_args(args[0]) if typing.get_origin(union) is typing.Annotated else args
        models.extend(members)
    return [typing.get_args(m.model_fields["type"].annotation)[0] for m in models]


class TestEventsDiscriminatedUnionAndForbid:
    def test_type_literals_unique(self):
        literals = _all_type_literals()
        assert len(literals) == len(set(literals))

    def test_v2_rejects_unknown_key(self):
        with pytest.raises(ValidationError):
            ev.parse_inbound({"type": "answer_text", "field_id": "a", "value": "x", "extra": 1}, protocol_version=2)

    def test_internal_types_not_parseable(self):
        with pytest.raises(ev.UnknownMessageType):
            ev.parse_inbound(
                {"type": "_transcript", "field_id": "a", "text": "x", "audio_mime": "a", "audio_bytes_len": 1}
            )

    def test_v1_message_names_parse(self):
        samples = [
            {"type": "start_session", "form_uid": "u", "locale": "es", "tts_backend": "google"},
            {"type": "answer_text", "field_id": "a", "value": "x"},
            {"type": "answer_selection", "field_id": "a", "values": ["x", "y"]},
            {"type": "answer_payload", "field_id": "a", "value": {"k": 1}},
            {"type": "confirm_answer", "field_id": "a", "confirmed": True},
            {"type": "skip_question"},
            {"type": "go_back", "to_index": 0},
            {"type": "repeat_question"},
            {"type": "end_session"},
            {"type": "ping"},
        ]
        for sample in samples:
            for version in (1, 2):
                assert ev.parse_inbound(sample, protocol_version=version).type == sample["type"]

    def test_question_to_wire_omits_none(self):
        q = ev.Question(
            index=0,
            field_id="a",
            label="A",
            required=True,
            field_type="text",
            voice_mode="voice",
            render_mode="voice",
            sensitive=False,
        )
        wire = q.to_wire()
        assert wire["type"] == "question" and "audio" not in wire and "options" not in wire

    def test_phase_reexport(self):
        assert ev.Phase is ModelsPhase

    def test_io_request_marker(self):
        assert ev.is_io_request(ev.Replan()) and not ev.is_io_request(ev.Pong())


class TestLegacyInboundIgnoresUnknownKeys:
    def test_v1_start_session_extra_keys_accepted(self):
        msg = ev.parse_inbound(
            {"type": "start_session", "form_uid": "u", "client": "old-app", "foo": 1}, protocol_version=1
        )
        assert msg.form_uid == "u"

    def test_v2_start_session_extra_keys_rejected(self):
        with pytest.raises(ValidationError):
            ev.parse_inbound(
                {"type": "start_session", "form_uid": "u", "client": "old-app", "foo": 1}, protocol_version=2
            )


def test_error_wire_session_ids_optional():
    assert set(ev.Error(code="X", message="m").to_wire()) == {"type", "code", "message"}
    wire = ev.Error(code="SESSION_ACTIVE", message="m", session_id="s", form_uid="f").to_wire()
    assert wire["session_id"] == "s" and wire["form_uid"] == "f"


def test_start_session_submit_mode_default_and_validation():
    assert ev.StartSession(type="start_session", form_uid="f").submit_mode == "server"
    assert ev.StartSession(type="start_session", form_uid="f", submit_mode="client").submit_mode == "client"
    with pytest.raises(ValidationError):
        ev.StartSession(type="start_session", form_uid="f", submit_mode="bogus")


def test_answers_ready_wire_and_union_membership():
    w = ev.AnswersReady(data={"qty": 1}).to_wire()
    # absent optionals are omitted on the wire (_Wire.to_wire, v1 parity)
    assert w == {"type": "answers_ready", "data": {"qty": 1}}
    assert ev.AnswersReady(data={}, plausibility_summary={"flagged": 1}).to_wire()["plausibility_summary"] == {"flagged": 1}
    assert ev.AnswersReady in typing.get_args(ev.WireMessage)
