from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from parrot_formdesigner.core import (
    VoiceAnswerEnvelope,
    VoiceEvidenceEnvelope,
    is_voice_envelope,
    unwrap_voice,
    wrap_voice,
)


class TestVoiceEvidenceEnvelopeSubclass:
    def test_base_contract_unchanged(self):
        with pytest.raises(ValidationError):
            VoiceAnswerEnvelope(answer=["a"])
        with pytest.raises(ValidationError):
            VoiceAnswerEnvelope(answer="x", foo=1)

    def test_subclass_accepts_typed_answers(self):
        assert VoiceEvidenceEnvelope(answer=["a", "b"]).answer == ["a", "b"]
        assert VoiceEvidenceEnvelope(answer=True).source == "speech"
        with pytest.raises(ValidationError):
            VoiceEvidenceEnvelope(answer="x", bogus=1)

    def test_is_voice_envelope_shape(self):
        assert is_voice_envelope({"answer": "x", "blob_ref": None})
        assert is_voice_envelope({"answer": 3, "source": "speech"})
        assert not is_voice_envelope({"answer": "x"})
        assert not is_voice_envelope("x")

    def test_unwrap_idempotent_and_pure(self):
        data = {"a": {"answer": 1, "source": "speech"}, "b": "plain"}
        once = unwrap_voice(data)
        assert once == {"a": 1, "b": "plain"}
        assert unwrap_voice(once) == once
        assert data["a"] == {"answer": 1, "source": "speech"}

    def test_wrap_only_speech_and_idempotent(self):
        evidence = {
            "a": SimpleNamespace(source="speech", confidence=0.9, blob_ref="voice-s-1", audio_mime="audio/webm"),
            "b": SimpleNamespace(source="text", confidence=None),
        }
        scalars = {"a": "red", "b": "typed"}
        wrapped = wrap_voice(scalars, evidence)
        assert wrapped["a"]["answer"] == "red"
        assert wrapped["a"]["blob_ref"] == "voice-s-1"
        assert wrapped["a"]["audio_mime"] == "audio/webm"
        assert wrapped["a"]["data_url"] is None
        assert wrapped["b"] == "typed"
        assert scalars == {"a": "red", "b": "typed"}
        assert wrap_voice(wrapped, evidence) == wrapped
