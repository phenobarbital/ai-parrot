import uuid

import pytest
from pydantic import ValidationError

from parrot_formdesigner.audio import (
    AudioAnswer,
    AudioQuestion,
    AudioSessionState,
    NarrationPlan,
    OptionMatch,
    Phase,
    ReviewItemData,
    UiCue,
)
from parrot_formdesigner.core.voice import UiCue as CoreUiCue


def _question(**kw) -> AudioQuestion:
    return AudioQuestion(index=0, field_id="q", field_uid=uuid.uuid4(), field_type="text", label="Q", **kw)


class TestAudioModelDeltas:
    def test_question_defaults(self):
        q = _question()
        assert q.hint is None and q.answer_modes == [] and q.llm_validation is False

    def test_question_with_narration_and_cue(self):
        q = _question(narration=NarrationPlan(text="Q", audio_keys=["q:x:label"]), ui_cue=UiCue(control="select"))
        assert q.narration.audio_keys == ["q:x:label"]

    def test_answer_any_value_and_evidence(self):
        a = AudioAnswer(
            field_id="c",
            value=["a", "b"],
            source="speech",
            blob_ref="voice-s-u",
            matched=OptionMatch(value="a", label="A", method="ordinal", score=1.0),
        )
        assert a.version == 1 and a.value == ["a", "b"]

    def test_state_defaults(self):
        s1 = AudioSessionState(session_id="s", form_uid="f", user_id="u")
        s2 = AudioSessionState(session_id="s", form_uid="f", user_id="u")
        assert s1.phase is Phase.IDLE and s1.protocol_version == 1 and s1.flagged == {}
        assert s1.submission_id != s2.submission_id

    def test_extra_still_forbidden(self):
        with pytest.raises(ValidationError):
            AudioAnswer(field_id="x", value="v", bogus=1)

    def test_phase_members_and_uicue_reexport(self):
        assert {p.name for p in Phase} == {
            "IDLE",
            "PLANNING",
            "ASKING",
            "ACCEPTING",
            "CONFIRMING",
            "PLAUSIBILITY",
            "REVIEW",
            "REVIEW_EDITING",
            "SUBMITTING",
            "COMPLETE",
            "ABORTED",
        }
        assert UiCue is CoreUiCue

    def test_review_item_position_is_one_based(self):
        with pytest.raises(ValidationError):
            ReviewItemData(position=0, field_id="f", label="L", answer_text="a")
        assert ReviewItemData(position=1, field_id="f", label="L", answer_text="a").position == 1


def test_session_state_submit_mode_default():
    base = dict(session_id="s", form_uid="f", user_id="u")
    assert AudioSessionState(**base).submit_mode == "server"
    assert AudioSessionState(**base, submit_mode="client").submit_mode == "client"
