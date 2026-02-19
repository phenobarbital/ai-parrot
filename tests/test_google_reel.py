import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from pathlib import Path
from parrot.models.google import VideoReelRequest, VideoReelScene, AspectRatio, MusicGenre, MusicMood
# Import after patching if possible, or patch where used
from parrot.clients.google.generation import GoogleGeneration

@pytest.fixture
def mock_google_generation():
    client = MagicMock()
    # Create an instance with mocked client
    gg = GoogleGeneration()
    gg.client = client
    gg.logger = MagicMock()
    return gg

@pytest.mark.asyncio
async def test_generate_video_reel(mock_google_generation, tmp_path):
    # Mock helpers
    mock_google_generation._breakdown_prompt_to_scenes = AsyncMock(return_value=[
        VideoReelScene(
            background_prompt="Scene 1 BG",
            video_prompt="Scene 1 Video",
            duration=5.0
        ),
        VideoReelScene(
            background_prompt="Scene 2 BG",
            foreground_prompt="Scene 2 FG",
            video_prompt="Scene 2 Video",
            narration_text="Scene 2 Narration",
            duration=5.0
        )
    ])

    # Mock methods used in _process_scene and _generate_reel_music
    mock_google_generation.generate_image = AsyncMock()
    mock_google_generation.generate_image.return_value.images = [tmp_path / "mock_image.png"]

    mock_google_generation.video_generation = AsyncMock()
    mock_google_generation.video_generation.return_value.files = [tmp_path / "mock_video.mp4"]

    mock_google_generation.generate_speech = AsyncMock()
    mock_google_generation.generate_speech.return_value.files = [tmp_path / "mock_audio.wav"]

    # Mock generator for music
    async def mock_music_gen(*args, **kwargs):
        yield b"mock_audio_bytes"
    mock_google_generation.generate_music = mock_music_gen

    # Create dummy files for moviepy to "read"
    (tmp_path / "mock_image.png").touch()
    (tmp_path / "mock_video.mp4").touch()
    (tmp_path / "mock_audio.wav").touch()

    # Mock composite images (because PIL needs real images otherwise)
    mock_google_generation._composite_images = AsyncMock(return_value=tmp_path / "mock_composite.png")
    (tmp_path / "mock_composite.png").touch()

    # Mock _create_reel_assembly to avoid real moviepy dependency/processing
    mock_google_generation._create_reel_assembly = AsyncMock(return_value=tmp_path / "final_reel.mp4")
    (tmp_path / "final_reel.mp4").touch()

    # Input request
    request = VideoReelRequest(
        prompt="A test video reel about AI",
        music_prompt="Upbeat techno",
        music_genre=MusicGenre.TECHNO,
        aspect_ratio=AspectRatio.RATIO_9_16
    )

    # Patch AIMessageFactory in the module where it is used
    with patch('parrot.clients.google.generation.AIMessageFactory') as MockFactory:
        # Mock the return value of from_video
        mock_msg = MagicMock()
        mock_msg.files = [tmp_path / "final_reel.mp4"]
        MockFactory.from_video.return_value = mock_msg

        # Run
        result = await mock_google_generation.generate_video_reel(
            request=request,
            output_directory=tmp_path
        )

        # Verifications
        assert result.files[0] == tmp_path / "final_reel.mp4"

        # Check if breakdown was called
        mock_google_generation._breakdown_prompt_to_scenes.assert_called_once_with("A test video reel about AI")

        # Check if music generation was called
        assert mock_google_generation.generate_image.call_count >= 2

        # Check if video_generation was called for scenes
        assert mock_google_generation.video_generation.call_count == 2

        # Check if speech was called for scene 2
        mock_google_generation.generate_speech.assert_called_once()
