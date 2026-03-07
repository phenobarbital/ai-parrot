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

    # Input request - provide speech texts for scenes
    # Speech is now required for narration; without it, no narration is generated
    request = VideoReelRequest(
        prompt="A test video reel about AI",
        speech=["Scene 1 speech", "Scene 2 speech"],  # Explicit speech for each scene
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

        # Check if speech was called for each scene (2 scenes with speech)
        assert mock_google_generation.generate_speech.call_count == 2


@pytest.mark.asyncio
async def test_generate_video_reel_assigns_reference_images_to_scenes(mock_google_generation, tmp_path):
    """_generate_video_reel assigns reference_images[i] to scenes[i].reference_image."""
    scenes = [
        VideoReelScene(background_prompt="a", video_prompt="x", duration=5.0),
        VideoReelScene(background_prompt="b", video_prompt="y", duration=5.0),
    ]
    request = VideoReelRequest(
        prompt="test",
        scenes=scenes,
        reference_images=["/tmp/img0.jpg", "/tmp/img1.jpg"],
    )

    mock_google_generation._process_scene = AsyncMock(return_value=(tmp_path / "clip.mp4", None))
    mock_google_generation._generate_reel_music = AsyncMock(return_value=None)
    mock_google_generation._create_reel_assembly = AsyncMock(return_value=tmp_path / "final.mp4")
    (tmp_path / "final.mp4").touch()

    with patch("parrot.clients.google.generation.AIMessageFactory") as MockFactory:
        mock_msg = MagicMock()
        mock_msg.files = [tmp_path / "final.mp4"]
        MockFactory.from_video.return_value = mock_msg

        await mock_google_generation.generate_video_reel(request=request, output_directory=tmp_path)

    assert request.scenes[0].reference_image == "/tmp/img0.jpg"
    assert request.scenes[1].reference_image == "/tmp/img1.jpg"


@pytest.mark.asyncio
async def test_generate_video_reel_fewer_images_than_scenes(mock_google_generation, tmp_path):
    """Scenes without a corresponding image keep reference_image=None."""
    scenes = [
        VideoReelScene(background_prompt="a", video_prompt="x", duration=5.0),
        VideoReelScene(background_prompt="b", video_prompt="y", duration=5.0),
    ]
    request = VideoReelRequest(
        prompt="test",
        scenes=scenes,
        reference_images=["/tmp/img0.jpg"],  # Only 1 for 2 scenes
    )

    mock_google_generation._process_scene = AsyncMock(return_value=(tmp_path / "clip.mp4", None))
    mock_google_generation._generate_reel_music = AsyncMock(return_value=None)
    mock_google_generation._create_reel_assembly = AsyncMock(return_value=tmp_path / "final.mp4")
    (tmp_path / "final.mp4").touch()

    with patch("parrot.clients.google.generation.AIMessageFactory") as MockFactory:
        mock_msg = MagicMock()
        mock_msg.files = [tmp_path / "final.mp4"]
        MockFactory.from_video.return_value = mock_msg

        await mock_google_generation.generate_video_reel(request=request, output_directory=tmp_path)

    assert request.scenes[0].reference_image == "/tmp/img0.jpg"
    assert request.scenes[1].reference_image is None


@pytest.mark.asyncio
async def test_generate_video_reel_no_reference_images(mock_google_generation, tmp_path):
    """When reference_images is None, scenes keep reference_image=None."""
    scenes = [
        VideoReelScene(background_prompt="a", video_prompt="x", duration=5.0),
    ]
    request = VideoReelRequest(prompt="test", scenes=scenes)

    mock_google_generation._process_scene = AsyncMock(return_value=(tmp_path / "clip.mp4", None))
    mock_google_generation._generate_reel_music = AsyncMock(return_value=None)
    mock_google_generation._create_reel_assembly = AsyncMock(return_value=tmp_path / "final.mp4")
    (tmp_path / "final.mp4").touch()

    with patch("parrot.clients.google.generation.AIMessageFactory") as MockFactory:
        mock_msg = MagicMock()
        mock_msg.files = [tmp_path / "final.mp4"]
        MockFactory.from_video.return_value = mock_msg

        await mock_google_generation.generate_video_reel(request=request, output_directory=tmp_path)

    assert request.scenes[0].reference_image is None


@pytest.mark.asyncio
async def test_process_scene_passes_reference_image(mock_google_generation, tmp_path):
    """_process_scene calls generate_image with reference_images when scene.reference_image is set."""
    scene = VideoReelScene(
        background_prompt="beach",
        video_prompt="pan",
        duration=5.0,
        reference_image="/tmp/ref.jpg",
    )

    mock_img_msg = MagicMock()
    mock_img_msg.images = [tmp_path / "bg.jpg"]
    (tmp_path / "bg.jpg").touch()

    mock_video_msg = MagicMock()
    mock_video_msg.files = [tmp_path / "clip.mp4"]
    (tmp_path / "clip.mp4").touch()

    mock_google_generation.generate_image = AsyncMock(return_value=mock_img_msg)
    mock_google_generation.video_generation = AsyncMock(return_value=mock_video_msg)
    mock_google_generation.generate_speech = AsyncMock()

    await mock_google_generation._process_scene(scene, 0, tmp_path, AspectRatio.RATIO_9_16)

    call_kwargs = mock_google_generation.generate_image.call_args.kwargs
    assert call_kwargs.get("reference_images") == [Path("/tmp/ref.jpg")]


@pytest.mark.asyncio
async def test_process_scene_no_reference_image(mock_google_generation, tmp_path):
    """_process_scene calls generate_image with reference_images=None when no reference set."""
    scene = VideoReelScene(background_prompt="beach", video_prompt="pan", duration=5.0)

    mock_img_msg = MagicMock()
    mock_img_msg.images = [tmp_path / "bg.jpg"]
    (tmp_path / "bg.jpg").touch()

    mock_video_msg = MagicMock()
    mock_video_msg.files = [tmp_path / "clip.mp4"]
    (tmp_path / "clip.mp4").touch()

    mock_google_generation.generate_image = AsyncMock(return_value=mock_img_msg)
    mock_google_generation.video_generation = AsyncMock(return_value=mock_video_msg)
    mock_google_generation.generate_speech = AsyncMock()

    await mock_google_generation._process_scene(scene, 0, tmp_path, AspectRatio.RATIO_9_16)

    call_kwargs = mock_google_generation.generate_image.call_args.kwargs
    assert call_kwargs.get("reference_images") is None


@pytest.mark.asyncio
async def test_generate_video_reel_no_speech(mock_google_generation, tmp_path):
    """Test that no narration is generated when speech is not provided."""
    # Mock helpers
    mock_google_generation._breakdown_prompt_to_scenes = AsyncMock(return_value=[
        VideoReelScene(
            background_prompt="Scene 1 BG",
            video_prompt="Scene 1 Video",
            narration_text="This will be cleared",  # Should be cleared since no speech provided
            duration=5.0
        ),
    ])

    mock_google_generation.generate_image = AsyncMock()
    mock_google_generation.generate_image.return_value.images = [tmp_path / "mock_image.png"]

    mock_google_generation.video_generation = AsyncMock()
    mock_google_generation.video_generation.return_value.files = [tmp_path / "mock_video.mp4"]

    mock_google_generation.generate_speech = AsyncMock()

    async def mock_music_gen(*args, **kwargs):
        yield b"mock_audio_bytes"
    mock_google_generation.generate_music = mock_music_gen

    (tmp_path / "mock_image.png").touch()
    (tmp_path / "mock_video.mp4").touch()

    mock_google_generation._create_reel_assembly = AsyncMock(return_value=tmp_path / "final_reel.mp4")
    (tmp_path / "final_reel.mp4").touch()

    # Request WITHOUT speech - no narration should be generated
    request = VideoReelRequest(
        prompt="A test video reel without narration",
        music_prompt="Ambient music",
        aspect_ratio=AspectRatio.RATIO_9_16
        # Note: speech is NOT provided
    )

    with patch('parrot.clients.google.generation.AIMessageFactory') as MockFactory:
        mock_msg = MagicMock()
        mock_msg.files = [tmp_path / "final_reel.mp4"]
        MockFactory.from_video.return_value = mock_msg

        result = await mock_google_generation.generate_video_reel(
            request=request,
            output_directory=tmp_path
        )

        assert result.files[0] == tmp_path / "final_reel.mp4"

        # Speech should NOT be called since speech was not provided
        mock_google_generation.generate_speech.assert_not_called()
