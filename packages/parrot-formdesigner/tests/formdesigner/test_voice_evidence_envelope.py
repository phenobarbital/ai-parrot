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


PHOTO_LEGACY = {"answer": "a.jpg", "blob_ref": "s3://b/k", "display": "a.jpg"}
PHOTO_FILE = {"answer": "a.jpg", "filename": "a.jpg", "content_type": "image/jpeg", "blob_ref": "s3://b/k"}
V1_NULL = {"answer": "hi", "blob_ref": None}
V1_FULL = {"answer": "hi", "blob_ref": "voice-s-f", "data_url": None}
SPEECH = {"answer": 3, "source": "speech", "blob_ref": "voice-s-f", "confidence": 0.9}


def test_photo_shapes_are_not_voice():
    assert not is_voice_envelope(PHOTO_LEGACY)
    assert not is_voice_envelope(PHOTO_FILE)


def test_v1_and_speech_are_voice():
    assert is_voice_envelope(V1_NULL)
    assert is_voice_envelope(V1_FULL)
    assert is_voice_envelope(SPEECH)


def test_unwrap_voice_keeps_photos():
    data = {"photo": dict(PHOTO_LEGACY), "file": dict(PHOTO_FILE), "v": dict(V1_FULL), "s": dict(SPEECH)}
    assert unwrap_voice(data) == {"photo": PHOTO_LEGACY, "file": PHOTO_FILE, "v": "hi", "s": 3}
