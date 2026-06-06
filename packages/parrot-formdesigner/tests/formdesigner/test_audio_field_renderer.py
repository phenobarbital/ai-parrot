"""Tests for AudioFieldRenderer (FEAT-224 TASK-1461)."""

import pytest

from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.core.schema import FormField
from parrot_formdesigner.renderers.base import FieldRenderer
from parrot_formdesigner.renderers.html5 import HTML5Renderer
from parrot_formdesigner.renderers.fields.audio import AudioFieldRenderer


@pytest.fixture
def audio_field() -> FormField:
    """Minimal AUDIO FormField for testing."""
    return FormField(
        field_id="voice_note",
        field_type=FieldType.AUDIO,
        label="Leave a voice note",
    )


@pytest.fixture
def renderer() -> HTML5Renderer:
    """HTML5Renderer instance."""
    return HTML5Renderer()


class TestAudioFieldInRegistry:
    """Tests that FieldType.AUDIO is registered in HTML5Renderer._registry."""

    def test_audio_in_registry(self, renderer: HTML5Renderer) -> None:
        """FieldType.AUDIO is present in the renderer registry."""
        assert FieldType.AUDIO in renderer._registry

    def test_audio_renderer_is_field_renderer(self, renderer: HTML5Renderer) -> None:
        """The registered AUDIO renderer implements FieldRenderer protocol."""
        assert isinstance(renderer._registry[FieldType.AUDIO], FieldRenderer)

    def test_audio_renderer_is_audio_field_renderer(self, renderer: HTML5Renderer) -> None:
        """The registered AUDIO renderer is an AudioFieldRenderer instance."""
        assert isinstance(renderer._registry[FieldType.AUDIO], AudioFieldRenderer)


class TestAudioFieldRendering:
    """Tests for the HTML output of AudioFieldRenderer."""

    @pytest.mark.asyncio
    async def test_render_produces_html(
        self, renderer: HTML5Renderer, audio_field: FormField
    ) -> None:
        """Rendering an AUDIO field produces a non-empty HTML string."""
        html = await renderer._registry[FieldType.AUDIO].render(audio_field)
        assert isinstance(html, str)
        assert len(html) > 0

    @pytest.mark.asyncio
    async def test_render_includes_button(
        self, renderer: HTML5Renderer, audio_field: FormField
    ) -> None:
        """Rendered HTML includes a <button> element."""
        html = await renderer._registry[FieldType.AUDIO].render(audio_field)
        assert "<button" in html

    @pytest.mark.asyncio
    async def test_render_includes_hidden_input(
        self, renderer: HTML5Renderer, audio_field: FormField
    ) -> None:
        """Rendered HTML includes a hidden <input> element."""
        html = await renderer._registry[FieldType.AUDIO].render(audio_field)
        assert 'type="hidden"' in html

    @pytest.mark.asyncio
    async def test_render_includes_field_id(
        self, renderer: HTML5Renderer, audio_field: FormField
    ) -> None:
        """Rendered HTML includes the field_id."""
        html = await renderer._registry[FieldType.AUDIO].render(audio_field)
        assert "voice_note" in html

    @pytest.mark.asyncio
    async def test_render_includes_mediarecorder(
        self, renderer: HTML5Renderer, audio_field: FormField
    ) -> None:
        """Rendered HTML includes MediaRecorder JavaScript."""
        html = await renderer._registry[FieldType.AUDIO].render(audio_field)
        assert "MediaRecorder" in html

    @pytest.mark.asyncio
    async def test_render_includes_data_field_type(
        self, renderer: HTML5Renderer, audio_field: FormField
    ) -> None:
        """Rendered HTML includes data-field-type='audio' attribute."""
        html = await renderer._registry[FieldType.AUDIO].render(audio_field)
        assert 'data-field-type="audio"' in html

    @pytest.mark.asyncio
    async def test_render_with_error(
        self, renderer: HTML5Renderer, audio_field: FormField
    ) -> None:
        """Rendered HTML includes error message when error is provided."""
        html = await renderer._registry[FieldType.AUDIO].render(
            audio_field, error="This field is required"
        )
        assert "This field is required" in html
        assert "field-error" in html

    @pytest.mark.asyncio
    async def test_render_with_prefilled(
        self, renderer: HTML5Renderer, audio_field: FormField
    ) -> None:
        """Rendered HTML includes prefilled value in the hidden input."""
        html = await renderer._registry[FieldType.AUDIO].render(
            audio_field, prefilled="Hello world"
        )
        assert "Hello world" in html

    @pytest.mark.asyncio
    async def test_standalone_audio_field_renderer(
        self, audio_field: FormField
    ) -> None:
        """AudioFieldRenderer can be instantiated and used standalone."""
        audio_renderer = AudioFieldRenderer()
        html = await audio_renderer.render(audio_field)
        assert "<button" in html
        assert "MediaRecorder" in html
