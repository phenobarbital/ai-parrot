import logging
import subprocess
import sys

from parrot_formdesigner.core import (
    FieldType,
    FieldVoiceMeta,
    FormField,
    FormSchema,
    LLMValidationConfig,
    PlausibilityVerdict,
    VoiceFormConfig,
    field_voice_meta,
    is_sensitive,
    llm_validation_enabled,
    resolve_voice_config,
)


def _form(**kwargs) -> FormSchema:
    return FormSchema(form_id="f", title="F", sections=[], **kwargs)


def _field(**kwargs) -> FormField:
    return FormField(field_id="a", field_type=FieldType.TEXT, label="A", **kwargs)


class TestSchemaHintAndLLMValidationFields:
    def test_field_hint_roundtrip(self):
        f = _field(hint={"en": "Say it", "es": "Dilo"}, llm_validation=True)
        again = FormField.model_validate(f.model_dump())
        assert again.hint == {"en": "Say it", "es": "Dilo"}
        assert again.llm_validation is True

    def test_form_typed_blocks(self):
        form = _form(voice={"max_questions": 3}, llm_validation={"enabled": True})
        assert isinstance(form.voice, VoiceFormConfig) and form.voice.max_questions == 3
        assert isinstance(form.llm_validation, LLMValidationConfig) and form.llm_validation.on_error == "skip"
        assert _form().voice is None and _form().llm_validation is None

    def test_meta_voice_unknown_keys_one_warning(self, caplog):
        f = _field(meta={"voice": {"pause_ms": 300, "bogus": 1, "x": 2}})
        with caplog.at_level(logging.WARNING):
            meta = field_voice_meta(f)
        assert isinstance(meta, FieldVoiceMeta) and meta.pause_ms == 300
        assert len([r for r in caplog.records if "unknown meta.voice" in r.getMessage()]) == 1

    def test_meta_voice_absent_or_invalid_defaults(self, caplog):
        assert field_voice_meta(_field()) == FieldVoiceMeta()
        with caplog.at_level(logging.WARNING):
            meta = field_voice_meta(_field(meta={"voice": {"enumerate": "loud"}}))
        assert meta == FieldVoiceMeta()
        assert any("invalid meta.voice" in r.getMessage() for r in caplog.records)

    def test_llm_validation_inheritance(self):
        on = _form(llm_validation={"enabled": True})
        assert llm_validation_enabled(on, _field()) is True
        assert llm_validation_enabled(on, _field(llm_validation=False)) is False
        assert llm_validation_enabled(_form(), _field()) is False
        assert llm_validation_enabled(_form(), _field(llm_validation=True)) is True

    def test_verdict_confidence_clamped(self):
        assert PlausibilityVerdict(plausible=True, confidence=1.7, reason="r").confidence == 1.0
        assert PlausibilityVerdict(plausible=False, confidence=-0.2, reason="r").confidence == 0.0


class TestResolveVoiceConfig:
    def test_session_only_tightens(self):
        from parrot_formdesigner.audio.models import AudioSessionConfig

        form = _form(voice={"stt_confirm_threshold": 0.8, "enumerate_options": False})
        session = AudioSessionConfig(form_uid="u", stt_confirm_threshold=0.5, enumerate_options=True)
        cfg = resolve_voice_config(form, session)
        assert cfg.stt_confirm_threshold == 0.8 and cfg.enumerate_options is False
        stricter = AudioSessionConfig(form_uid="u", stt_confirm_threshold=0.9, tts_backend="google")
        cfg = resolve_voice_config(_form(), stricter)
        assert cfg.stt_confirm_threshold == 0.9 and cfg.tts_backend == "google"
        assert resolve_voice_config(_form(), None) == VoiceFormConfig()


class TestSensitivePolicy:
    def test_password_and_meta_flag(self):
        assert is_sensitive(FormField(field_id="p", field_type=FieldType.PASSWORD, label="P"))
        assert is_sensitive(_field(meta={"voice": {"sensitive": True}}))
        assert not is_sensitive(_field())


def test_core_does_not_import_audio():
    code = "import sys, parrot_formdesigner.core; assert 'parrot_formdesigner.audio' not in sys.modules"
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr


def test_hands_free_config_barge_in_default():
    from parrot_formdesigner.core.voice import HandsFreeConfig

    assert HandsFreeConfig().barge_in is True
    off = HandsFreeConfig(barge_in=False)
    assert off.model_dump() == {"auto_record": True, "silence_ms": 1200, "barge_in": False}
    assert HandsFreeConfig(**off.model_dump()).barge_in is False


def test_session_started_wire_carries_barge_in():
    from parrot_formdesigner.audio.events import SessionStarted
    from parrot_formdesigner.core.voice import HandsFreeConfig

    v2 = SessionStarted(session_id="s", total_questions=1, title="T", protocol_version=2,
                        hands_free=HandsFreeConfig()).to_wire()
    assert v2["hands_free"] == {"auto_record": True, "silence_ms": 1200, "barge_in": True}
    v1 = SessionStarted(session_id="s", total_questions=1, title="T").to_wire()
    assert "hands_free" not in v1


def test_voice_form_config_option_pause_default():
    import pytest
    from pydantic import ValidationError

    from parrot_formdesigner.core.voice import FieldVoiceMeta, VoiceFormConfig

    assert VoiceFormConfig().option_pause_ms == 500
    with pytest.raises(ValidationError):
        VoiceFormConfig(option_pause_ms=-1)
    assert FieldVoiceMeta(option_pause_ms=250).option_pause_ms == 250
    assert FieldVoiceMeta().option_pause_ms is None
    assert VoiceFormConfig(option_pause_ms=0).option_pause_ms == 0


def test_field_voice_meta_accepts_option_pause_without_warning(caplog):
    import logging

    from parrot_formdesigner.core.options import FieldOption
    from parrot_formdesigner.core.schema import FormField
    from parrot_formdesigner.core.types import FieldType
    from parrot_formdesigner.core.voice import field_voice_meta

    field = FormField(
        field_id="c", field_type=FieldType.SELECT, label="C",
        options=[FieldOption(value="a", label="A")], meta={"voice": {"option_pause_ms": 250}},
    )
    with caplog.at_level(logging.WARNING):
        meta = field_voice_meta(field)
    assert meta.option_pause_ms == 250
    assert not [r for r in caplog.records if "unknown" in r.getMessage().lower()]
