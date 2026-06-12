"""Tests for AudioFormRenderer (FEAT-224 TASK-1462, FEAT-236 TASK-1540)."""

from types import SimpleNamespace

import pytest

from parrot_formdesigner.audio.models import AudioSessionConfig, VoiceMode
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.renderers.audio import (
    AudioFormRenderer,
    build_audio_synthesizer,
    classify_voice_mode,
    synthesize_with_fallback,
)


@pytest.fixture
def simple_form() -> FormSchema:
    """A simple 3-field form: 2 visible + 1 hidden."""
    return FormSchema(
        form_id="test-001",
        title="Test Form",
        sections=[
            FormSection(
                section_id="s1",
                title="Section 1",
                fields=[
                    FormField(
                        field_id="name",
                        field_type=FieldType.TEXT,
                        label="What is your name?",
                        required=True,
                    ),
                    FormField(
                        field_id="age",
                        field_type=FieldType.NUMBER,
                        label="How old are you?",
                    ),
                    FormField(
                        field_id="secret",
                        field_type=FieldType.HIDDEN,
                        label="hidden",
                        default="x",
                    ),
                ],
            )
        ],
    )


@pytest.fixture
def form_with_select() -> FormSchema:
    """A form with a SELECT field."""
    from parrot_formdesigner.core.options import FieldOption

    return FormSchema(
        form_id="test-select",
        title="Select Form",
        sections=[
            FormSection(
                section_id="s1",
                fields=[
                    FormField(
                        field_id="color",
                        field_type=FieldType.SELECT,
                        label="Pick a color",
                        options=[
                            FieldOption(value="red", label="Red"),
                            FieldOption(value="blue", label="Blue"),
                        ],
                    ),
                ],
            )
        ],
    )


@pytest.fixture
def form_with_group() -> FormSchema:
    """A form with a GROUP field containing children."""
    return FormSchema(
        form_id="test-group",
        title="Group Form",
        sections=[
            FormSection(
                section_id="s1",
                fields=[
                    FormField(
                        field_id="address",
                        field_type=FieldType.GROUP,
                        label="Address",
                        children=[
                            FormField(
                                field_id="street",
                                field_type=FieldType.TEXT,
                                label="Street",
                            ),
                            FormField(
                                field_id="city",
                                field_type=FieldType.TEXT,
                                label="City",
                            ),
                        ],
                    ),
                ],
            )
        ],
    )


@pytest.fixture
def renderer() -> AudioFormRenderer:
    """AudioFormRenderer without TTS synthesizer."""
    return AudioFormRenderer()


class TestSplitIntoQuestions:
    """Tests for AudioFormRenderer.split_into_questions()."""

    def test_flat_form(self, renderer: AudioFormRenderer, simple_form: FormSchema) -> None:
        """HIDDEN field is excluded; 2 visible fields become 2 questions."""
        questions = renderer.split_into_questions(simple_form)
        assert len(questions) == 2
        assert questions[0].field_id == "name"
        assert questions[1].field_id == "age"

    def test_questions_are_indexed(
        self, renderer: AudioFormRenderer, simple_form: FormSchema
    ) -> None:
        """Questions have sequential zero-based indices."""
        questions = renderer.split_into_questions(simple_form)
        assert questions[0].index == 0
        assert questions[1].index == 1

    def test_required_flag(
        self, renderer: AudioFormRenderer, simple_form: FormSchema
    ) -> None:
        """required flag is propagated from FormField."""
        questions = renderer.split_into_questions(simple_form)
        assert questions[0].required is True
        assert questions[1].required is False

    def test_skips_hidden_fields(
        self, renderer: AudioFormRenderer, simple_form: FormSchema
    ) -> None:
        """HIDDEN fields are excluded from the question list."""
        questions = renderer.split_into_questions(simple_form)
        field_ids = [q.field_id for q in questions]
        assert "secret" not in field_ids

    def test_select_options_included(
        self, renderer: AudioFormRenderer, form_with_select: FormSchema
    ) -> None:
        """SELECT field includes options list in the question."""
        questions = renderer.split_into_questions(form_with_select)
        assert len(questions) == 1
        assert questions[0].options is not None
        assert len(questions[0].options) == 2
        assert questions[0].options[0]["value"] == "red"

    def test_group_children_expanded(
        self, renderer: AudioFormRenderer, form_with_group: FormSchema
    ) -> None:
        """GROUP field children become individual questions."""
        questions = renderer.split_into_questions(form_with_group)
        assert len(questions) == 2
        field_ids = [q.field_id for q in questions]
        assert "street" in field_ids
        assert "city" in field_ids
        assert "address" not in field_ids

    def test_field_type_is_string(
        self, renderer: AudioFormRenderer, simple_form: FormSchema
    ) -> None:
        """AudioQuestion.field_type is a string value (not enum)."""
        questions = renderer.split_into_questions(simple_form)
        assert questions[0].field_type == "text"
        assert questions[1].field_type == "number"


class TestRender:
    """Tests for AudioFormRenderer.render()."""

    @pytest.mark.asyncio
    async def test_returns_rendered_form(
        self, renderer: AudioFormRenderer, simple_form: FormSchema
    ) -> None:
        """render() returns a RenderedForm with JSON content type."""
        result = await renderer.render(simple_form)
        assert result.content_type == "application/json"

    @pytest.mark.asyncio
    async def test_manifest_structure(
        self, renderer: AudioFormRenderer, simple_form: FormSchema
    ) -> None:
        """render() returns correct manifest structure."""
        result = await renderer.render(simple_form)
        assert result.content["form_id"] == "test-001"
        assert result.content["total_questions"] == 2
        assert "questions" in result.content

    @pytest.mark.asyncio
    async def test_manifest_has_ws_endpoint(
        self, renderer: AudioFormRenderer, simple_form: FormSchema
    ) -> None:
        """render() manifest includes WebSocket endpoint path."""
        result = await renderer.render(simple_form)
        assert "/audio/ws" in result.content["ws_endpoint"]
        assert "test-001" in result.content["ws_endpoint"]

    @pytest.mark.asyncio
    async def test_manifest_locale(
        self, renderer: AudioFormRenderer, simple_form: FormSchema
    ) -> None:
        """render() manifest uses the provided locale."""
        result = await renderer.render(simple_form, locale="es")
        assert result.content["locale"] == "es"

    @pytest.mark.asyncio
    async def test_audio_prompt_excluded_from_json(
        self, renderer: AudioFormRenderer, simple_form: FormSchema
    ) -> None:
        """audio_prompt bytes are excluded from the JSON manifest content."""
        result = await renderer.render(simple_form)
        for q in result.content["questions"]:
            assert "audio_prompt" not in q

    @pytest.mark.asyncio
    async def test_render_with_tts_synthesizer(
        self, simple_form: FormSchema
    ) -> None:
        """render() calls synthesizer.synthesize() for each question."""
        from unittest.mock import AsyncMock, MagicMock

        mock_synth = AsyncMock()
        mock_synth.synthesize.return_value = MagicMock(
            audio=b"fake-audio", mime_format="audio/ogg"
        )
        renderer = AudioFormRenderer(synthesizer=mock_synth)
        result = await renderer.render(simple_form)
        # 2 visible questions → 2 synthesis calls
        assert mock_synth.synthesize.call_count == 2
        assert result.content["total_questions"] == 2


# ---------------------------------------------------------------------------
# FEAT-236 TASK-1540: voice-mode classification + SuperTonic-first synthesizer
# ---------------------------------------------------------------------------


class TestClassifyVoiceMode:
    """Tests for classify_voice_mode()."""

    @pytest.mark.parametrize(
        "ft",
        [
            FieldType.TEXT,
            FieldType.TEXT_AREA,
            FieldType.NUMBER,
            FieldType.INTEGER,
            FieldType.EMAIL,
            FieldType.PHONE,
            FieldType.URL,
            FieldType.DATE,
            FieldType.DATETIME,
            FieldType.TIME,
            FieldType.TAGS,
            FieldType.PASSWORD,
        ],
    )
    def test_voice_types(self, ft: FieldType) -> None:
        """Free-text-style fields classify as VOICE."""
        field = FormField(field_id="f", field_type=ft, label="L")
        assert classify_voice_mode(field) == VoiceMode.VOICE

    @pytest.mark.parametrize(
        "ft",
        [
            FieldType.SELECT,
            FieldType.MULTI_SELECT,
            FieldType.DYNAMIC_SELECT,
            FieldType.BOOLEAN,
            FieldType.RANKING,
            FieldType.LIKERT,
            FieldType.NPS,
            FieldType.COLOR,
        ],
    )
    def test_prompt_select_types(self, ft: FieldType) -> None:
        """Selection-style fields classify as PROMPT_SELECT."""
        field = FormField(field_id="f", field_type=ft, label="L")
        assert classify_voice_mode(field) == VoiceMode.PROMPT_SELECT

    @pytest.mark.parametrize(
        "ft",
        [
            FieldType.REST,
            FieldType.REMOTE_RESPONSE,
            FieldType.FILE,
            FieldType.IMAGE,
            FieldType.LOCATION,
            FieldType.SIGNATURE,
            FieldType.TRANSFER_LIST,
            FieldType.AVAILABILITY,
            FieldType.ARRAY,
        ],
    )
    def test_visual_fallback_types(self, ft: FieldType) -> None:
        """Structurally complex fields classify as VISUAL_FALLBACK."""
        field = FormField(field_id="f", field_type=ft, label="L")
        assert classify_voice_mode(field) == VoiceMode.VISUAL_FALLBACK

    def test_meta_override(self) -> None:
        """meta['voice_mode'] overrides the FieldType default."""
        field = FormField(
            field_id="f",
            field_type=FieldType.TEXT,
            label="L",
            meta={"voice_mode": "visual_fallback"},
        )
        assert classify_voice_mode(field) == VoiceMode.VISUAL_FALLBACK

    def test_meta_override_case_insensitive(self) -> None:
        """meta override matching is case-insensitive."""
        field = FormField(
            field_id="f",
            field_type=FieldType.TEXT,
            label="L",
            meta={"voice_mode": "Prompt_Select"},
        )
        assert classify_voice_mode(field) == VoiceMode.PROMPT_SELECT

    def test_invalid_meta_override_uses_default(self) -> None:
        """An invalid meta override falls back to the FieldType default."""
        field = FormField(
            field_id="f",
            field_type=FieldType.SELECT,
            label="L",
            meta={"voice_mode": "nonsense"},
        )
        assert classify_voice_mode(field) == VoiceMode.PROMPT_SELECT

    def test_none_meta_is_safe(self) -> None:
        """A field with meta=None classifies by FieldType."""
        field = FormField(field_id="f", field_type=FieldType.REST, label="L")
        assert field.meta is None
        assert classify_voice_mode(field) == VoiceMode.VISUAL_FALLBACK


class TestVoiceModeTagging:
    """Tests that split_into_questions tags questions with voice fields."""

    @pytest.fixture
    def mixed_form(self) -> FormSchema:
        """A form mixing VOICE, PROMPT_SELECT, VISUAL_FALLBACK, password, hidden."""
        return FormSchema(
            form_id="mixed-001",
            title="Mixed",
            sections=[
                FormSection(
                    section_id="s1",
                    fields=[
                        FormField(field_id="name", field_type=FieldType.TEXT, label="Name?"),
                        FormField(field_id="color", field_type=FieldType.SELECT, label="Color?"),
                        FormField(
                            field_id="doc", field_type=FieldType.REST,
                            label="Upload doc", required=True,
                        ),
                        FormField(field_id="pw", field_type=FieldType.PASSWORD, label="Password?"),
                        FormField(field_id="h", field_type=FieldType.HIDDEN, label="h"),
                    ],
                )
            ],
        )

    def test_keeps_rest_field(self, mixed_form: FormSchema) -> None:
        """A required REST field is NOT dropped; it is VISUAL_FALLBACK."""
        renderer = AudioFormRenderer()
        questions = renderer.split_into_questions(mixed_form)
        rest = next(q for q in questions if q.field_id == "doc")
        assert rest.voice_mode == VoiceMode.VISUAL_FALLBACK
        assert rest.render_mode == "visual"
        assert rest.required is True

    def test_only_hidden_excluded(self, mixed_form: FormSchema) -> None:
        """Only the HIDDEN field is excluded from the question list."""
        renderer = AudioFormRenderer()
        field_ids = [q.field_id for q in renderer.split_into_questions(mixed_form)]
        assert "h" not in field_ids
        assert {"name", "color", "doc", "pw"} <= set(field_ids)

    def test_voice_modes_tagged(self, mixed_form: FormSchema) -> None:
        """Each kept question carries the right VoiceMode/render_mode."""
        renderer = AudioFormRenderer()
        by_id = {q.field_id: q for q in renderer.split_into_questions(mixed_form)}
        assert by_id["name"].voice_mode == VoiceMode.VOICE
        assert by_id["name"].render_mode == "voice"
        assert by_id["color"].voice_mode == VoiceMode.PROMPT_SELECT
        assert by_id["color"].render_mode == "select"

    def test_password_is_sensitive(self, mixed_form: FormSchema) -> None:
        """PASSWORD questions are flagged sensitive (mute read-back)."""
        renderer = AudioFormRenderer()
        by_id = {q.field_id: q for q in renderer.split_into_questions(mixed_form)}
        assert by_id["pw"].sensitive is True
        assert by_id["name"].sensitive is False


class _FakeSynth:
    """Stub VoiceSynthesizer: raises on 'supertonic', returns WAV on 'google'."""

    backends_tried: list[str] = []

    def __init__(self, config=None) -> None:
        self.config = config
        self.backend = getattr(config, "backend", None)

    async def synthesize(self, text, *, language=None):
        _FakeSynth.backends_tried.append(self.backend)
        if self.backend == "supertonic":
            raise RuntimeError("SUPERTONIC_MODEL_PATH not configured")
        return SimpleNamespace(audio=b"GOOGLE_WAV", mime_format="audio/wav")

    async def close(self) -> None:
        return None


class _AlwaysFailSynth(_FakeSynth):
    """Stub that fails for every backend."""

    async def synthesize(self, text, *, language=None):
        _FakeSynth.backends_tried.append(self.backend)
        raise RuntimeError(f"{self.backend} unavailable")


class TestBuildAudioSynthesizer:
    """Tests for build_audio_synthesizer() and synthesize_with_fallback()."""

    def test_build_prefers_supertonic(self) -> None:
        """build_audio_synthesizer() returns a SuperTonic-configured synth."""
        synth = build_audio_synthesizer()
        assert synth is not None
        assert synth.config.backend == "supertonic"

    def test_build_honors_config_backend(self) -> None:
        """An explicit google config is reflected in the built synth."""
        cfg = AudioSessionConfig(form_id="f", tts_backend="google")
        synth = build_audio_synthesizer(cfg)
        assert synth is not None
        assert synth.config.backend == "google"

    @pytest.mark.asyncio
    async def test_falls_back_to_google(self, monkeypatch) -> None:
        """SuperTonic raising at synthesis time → Google backend used."""
        _FakeSynth.backends_tried = []
        monkeypatch.setattr(
            "parrot.voice.tts.synthesizer.VoiceSynthesizer", _FakeSynth
        )
        audio = await synthesize_with_fallback("hello")
        assert audio == b"GOOGLE_WAV"
        assert _FakeSynth.backends_tried == ["supertonic", "google"]

    @pytest.mark.asyncio
    async def test_returns_none_when_no_backend(self, monkeypatch) -> None:
        """All backends failing → None (text-only), no exception raised."""
        _FakeSynth.backends_tried = []
        monkeypatch.setattr(
            "parrot.voice.tts.synthesizer.VoiceSynthesizer", _AlwaysFailSynth
        )
        audio = await synthesize_with_fallback("hello")
        assert audio is None
        assert _FakeSynth.backends_tried == ["supertonic", "google"]
