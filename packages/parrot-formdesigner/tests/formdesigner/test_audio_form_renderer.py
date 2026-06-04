"""Tests for AudioFormRenderer (FEAT-224 TASK-1462)."""

import pytest

from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.renderers.audio import AudioFormRenderer


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
