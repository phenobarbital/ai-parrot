"""Backward compatibility tests for MS Teams voice module (TASK-266).

Verifies that all existing import paths from `parrot.integrations.msteams.voice`
still resolve after the refactor to `parrot.voice.transcriber`.
"""


class TestMSTeamsVoiceBackwardCompat:
    """All existing MS Teams voice imports must still work."""

    def test_msteams_imports_still_work(self):
        """Top-level imports from msteams.voice resolve."""
        from parrot.integrations.msteams.voice import (
            VoiceTranscriber,
            AbstractTranscriberBackend,
            FasterWhisperBackend,
            OpenAIWhisperBackend,
            TranscriberBackend,
            VoiceTranscriberConfig,
            TranscriptionResult,
            AudioAttachment,
        )
        assert VoiceTranscriber is not None
        assert AbstractTranscriberBackend is not None
        assert FasterWhisperBackend is not None
        assert OpenAIWhisperBackend is not None
        assert TranscriberBackend is not None
        assert VoiceTranscriberConfig is not None
        assert TranscriptionResult is not None
        assert AudioAttachment is not None

    def test_audio_attachment_stays_in_msteams(self):
        """AudioAttachment is importable from msteams.voice."""
        from parrot.integrations.msteams.voice import AudioAttachment
        from parrot.integrations.msteams.voice.models import AudioAttachment as AA2

        assert AudioAttachment is AA2

    def test_voice_transcriber_importable_from_msteams(self):
        """VoiceTranscriber importable from old submodule path."""
        from parrot.integrations.msteams.voice.transcriber import VoiceTranscriber
        from parrot.voice.transcriber import VoiceTranscriber as VT2

        assert VoiceTranscriber is VT2

    def test_config_importable_from_msteams_models(self):
        """VoiceTranscriberConfig importable from old models path."""
        from parrot.integrations.msteams.voice.models import VoiceTranscriberConfig
        from parrot.voice.transcriber import VoiceTranscriberConfig as VTC2

        assert VoiceTranscriberConfig is VTC2

    def test_backend_importable_from_msteams(self):
        """AbstractTranscriberBackend importable from old backend path."""
        from parrot.integrations.msteams.voice.backend import AbstractTranscriberBackend
        from parrot.voice.transcriber import AbstractTranscriberBackend as ATB2

        assert AbstractTranscriberBackend is ATB2

    def test_faster_whisper_importable_from_msteams(self):
        """FasterWhisperBackend importable from old path."""
        from parrot.integrations.msteams.voice.faster_whisper_backend import FasterWhisperBackend
        from parrot.voice.transcriber import FasterWhisperBackend as FWB2

        assert FasterWhisperBackend is FWB2

    def test_openai_whisper_importable_from_msteams(self):
        """OpenAIWhisperBackend importable from old path."""
        from parrot.integrations.msteams.voice.openai_backend import OpenAIWhisperBackend
        from parrot.voice.transcriber import OpenAIWhisperBackend as OWB2

        assert OpenAIWhisperBackend is OWB2

    def test_audio_attachment_not_in_shared_module(self):
        """AudioAttachment must NOT exist in the shared module."""
        from parrot.voice.transcriber import __all__

        assert "AudioAttachment" not in __all__
