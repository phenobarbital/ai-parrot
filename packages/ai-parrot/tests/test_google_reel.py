"""FEAT-564 TASK-3330: updated for the new registry-backed reel orchestration.

Rewritten (not deleted) because generate_video_reel/_process_scene's internal
call chain changed structurally per this task's own Acceptance Criteria
(typed ReelSceneResult instead of tuple/None, generate_video_clip's registry
dispatch instead of a direct video_generation() call with a safety-block
retry, _breakdown_prompt_to_scenes gaining a model parameter, reel.assembly/
reel.music instead of _create_reel_assembly/_generate_reel_music). Every
test's original INTENT (reference-image assignment, sparse-slot handling,
narration precedence) is preserved; only the mocking surface changed to
match the new interfaces.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from pathlib import Path
from parrot.models.google import VideoReelRequest, VideoReelScene, AspectRatio, MusicGenre, MusicMood
from parrot.clients.google.generation import GoogleGeneration
from parrot.clients.google.reel.clip import GeneratedReelClip
from parrot.clients.google.reel.music import MusicOutcome


@pytest.fixture
def mock_google_generation():
    client = MagicMock()
    gg = GoogleGeneration()
    gg.client = client
    gg.logger = MagicMock()
    gg.vertexai = False
    return gg


def _fake_clip(tmp_path: Path, index: int, *, duration: float = 5.0) -> GeneratedReelClip:
    path = tmp_path / f"clip_{index}.mp4"
    path.touch()
    return GeneratedReelClip(
        local_path=path,
        model="veo-3.1-generate-preview",
        backend="veo",
        submitted_duration_seconds=duration,
        measured_duration_seconds=duration,
        has_audio=False,
        provider_operation_id=f"operations/scene-{index}",
    )


@pytest.fixture(autouse=True)
def _mock_reel_pipeline_tail(tmp_path):
    """Mocks the two pieces every test in this module needs regardless of what
    it's specifically verifying: the isolated music service (never touches a
    real Lyria session) and the managed-process assembly (never touches real
    ffmpeg) — both imported locally inside generate_video_reel."""
    final_path = tmp_path / "final_reel.mp4"
    final_path.touch()

    with (
        patch(
            "parrot.clients.google.reel.music.ReelMusicService.generate",
            new=AsyncMock(return_value=MusicOutcome(status="off")),
        ),
        patch(
            "parrot.clients.google.reel.assembly.assemble_reel",
            new=AsyncMock(return_value=final_path),
        ),
    ):
        yield final_path


@pytest.fixture
def fake_file_manager(tmp_path):
    fm = AsyncMock()
    fm.create_from_bytes = AsyncMock()
    fm.get_file_url = AsyncMock(return_value=str(tmp_path / "final_reel.mp4"))
    return fm


@pytest.mark.asyncio
async def test_generate_video_reel(mock_google_generation, tmp_path, fake_file_manager, _mock_reel_pipeline_tail):
    """Full happy path: director breakdown, image/video/narration calls, typed
    metadata/artifacts on the returned AIMessage."""
    mock_google_generation._breakdown_prompt_to_scenes = AsyncMock(
        return_value=[
            VideoReelScene(background_prompt="Scene 1 BG", video_prompt="Scene 1 Video", duration=5.0),
            VideoReelScene(
                background_prompt="Scene 2 BG",
                foreground_prompt="Scene 2 FG",
                video_prompt="Scene 2 Video",
                duration=5.0,
            ),
        ]
    )

    mock_google_generation.generate_image = AsyncMock()
    mock_google_generation.generate_image.return_value.images = [tmp_path / "mock_image.png"]
    (tmp_path / "mock_image.png").touch()

    mock_google_generation._composite_images = AsyncMock(return_value=tmp_path / "mock_composite.png")
    (tmp_path / "mock_composite.png").touch()

    clips = [_fake_clip(tmp_path, 0), _fake_clip(tmp_path, 1)]
    mock_google_generation.generate_video_clip = AsyncMock(side_effect=clips)

    mock_google_generation.generate_speech = AsyncMock()
    mock_google_generation.generate_speech.return_value.files = [tmp_path / "mock_audio.wav"]
    (tmp_path / "mock_audio.wav").touch()

    request = VideoReelRequest(
        prompt="A test video reel about AI",
        speech=["Scene 1 speech", "Scene 2 speech"],
        music_prompt="Upbeat techno",
        music_genre=MusicGenre.TECHNO,
        aspect_ratio=AspectRatio.RATIO_9_16,
    )

    result = await mock_google_generation.generate_video_reel(
        request=request, output_directory=tmp_path, file_manager=fake_file_manager
    )

    assert result.files == [_mock_reel_pipeline_tail]
    assert "video_reel" in result.metadata
    assert result.metadata["video_reel"]["director_unused"] is False
    assert len(result.artifacts) == 1

    mock_google_generation._breakdown_prompt_to_scenes.assert_called_once_with(
        "A test video reel about AI", "gemini-2.5-flash"
    )
    assert mock_google_generation.generate_image.call_count >= 2
    assert mock_google_generation.generate_video_clip.call_count == 2
    assert mock_google_generation.generate_speech.call_count == 2


@pytest.mark.asyncio
async def test_generate_video_reel_assigns_reference_images_to_scenes(
    mock_google_generation, tmp_path, fake_file_manager, _mock_reel_pipeline_tail
):
    """generate_video_reel assigns reference_images[i] to scenes[i].reference_image
    via VideoReelRequest.image_for_scene()."""
    scenes = [
        VideoReelScene(background_prompt="a", video_prompt="x", duration=5.0),
        VideoReelScene(background_prompt="b", video_prompt="y", duration=5.0),
    ]
    request = VideoReelRequest(
        prompt="test",
        scenes=scenes,
        reference_images=["/tmp/img0.jpg", "/tmp/img1.jpg"],
    )

    clips = [_fake_clip(tmp_path, 0), _fake_clip(tmp_path, 1)]

    async def _fake_process_scene(scene, index, *, context):
        context.clips[index] = clips[index]
        from parrot.models.google import ReelSceneResult

        return ReelSceneResult(
            index=index,
            video_model="veo-3.1-generate-preview",
            backend="veo",
            status="succeeded",
            requested_duration_seconds=scene.duration,
            measured_duration_seconds=5.0,
            final_duration_seconds=scene.duration,
        )

    mock_google_generation._process_scene = _fake_process_scene

    await mock_google_generation.generate_video_reel(
        request=request, output_directory=tmp_path, file_manager=fake_file_manager
    )

    assert request.scenes[0].reference_image == "/tmp/img0.jpg"
    assert request.scenes[1].reference_image == "/tmp/img1.jpg"


@pytest.mark.asyncio
async def test_generate_video_reel_fewer_images_than_scenes(
    mock_google_generation, tmp_path, fake_file_manager, _mock_reel_pipeline_tail
):
    """Scenes without a corresponding (sparse) image slot keep reference_image=None."""
    scenes = [
        VideoReelScene(background_prompt="a", video_prompt="x", duration=5.0),
        VideoReelScene(background_prompt="b", video_prompt="y", duration=5.0),
    ]
    request = VideoReelRequest(
        prompt="test",
        scenes=scenes,
        reference_images=["/tmp/img0.jpg"],  # Only 1 for 2 scenes
    )

    clips = [_fake_clip(tmp_path, 0), _fake_clip(tmp_path, 1)]

    async def _fake_process_scene(scene, index, *, context):
        context.clips[index] = clips[index]
        from parrot.models.google import ReelSceneResult

        return ReelSceneResult(
            index=index,
            video_model="veo-3.1-generate-preview",
            backend="veo",
            status="succeeded",
            requested_duration_seconds=scene.duration,
            measured_duration_seconds=5.0,
            final_duration_seconds=scene.duration,
        )

    mock_google_generation._process_scene = _fake_process_scene

    await mock_google_generation.generate_video_reel(
        request=request, output_directory=tmp_path, file_manager=fake_file_manager
    )

    assert request.scenes[0].reference_image == "/tmp/img0.jpg"
    assert request.scenes[1].reference_image is None


@pytest.mark.asyncio
async def test_generate_video_reel_no_reference_images(
    mock_google_generation, tmp_path, fake_file_manager, _mock_reel_pipeline_tail
):
    """When reference_images is None, scenes keep reference_image=None."""
    scenes = [VideoReelScene(background_prompt="a", video_prompt="x", duration=5.0)]
    request = VideoReelRequest(prompt="test", scenes=scenes)

    clip = _fake_clip(tmp_path, 0)

    async def _fake_process_scene(scene, index, *, context):
        context.clips[index] = clip
        from parrot.models.google import ReelSceneResult

        return ReelSceneResult(
            index=index,
            video_model="veo-3.1-generate-preview",
            backend="veo",
            status="succeeded",
            requested_duration_seconds=scene.duration,
            measured_duration_seconds=5.0,
            final_duration_seconds=scene.duration,
        )

    mock_google_generation._process_scene = _fake_process_scene

    await mock_google_generation.generate_video_reel(
        request=request, output_directory=tmp_path, file_manager=fake_file_manager
    )

    assert request.scenes[0].reference_image is None


@pytest.mark.asyncio
async def test_process_scene_passes_reference_image(mock_google_generation, tmp_path):
    """_process_scene calls generate_image with reference_images when scene.reference_image is set."""
    from parrot.clients.google.reel.profiles import VideoProfileRegistry
    from parrot.clients.google.generation import _ReelRunContext

    scene = VideoReelScene(
        background_prompt="beach",
        video_prompt="pan",
        duration=5.0,
        reference_image="/tmp/ref.jpg",
    )
    request = VideoReelRequest(prompt="test", scenes=[scene])

    mock_img_msg = MagicMock()
    mock_img_msg.images = [tmp_path / "bg.jpg"]
    (tmp_path / "bg.jpg").touch()

    mock_google_generation.generate_image = AsyncMock(return_value=mock_img_msg)
    mock_google_generation.generate_video_clip = AsyncMock(return_value=_fake_clip(tmp_path, 0))
    mock_google_generation.generate_speech = AsyncMock()

    context = _ReelRunContext(
        request=request,
        registry=VideoProfileRegistry.default(),
        api_surface="gemini_developer",
        output_directory=tmp_path,
        job_deadline=time.monotonic() + 3600.0,
    )
    await mock_google_generation._process_scene(scene, 0, context=context)

    call_kwargs = mock_google_generation.generate_image.call_args.kwargs
    assert call_kwargs.get("reference_images") == [Path("/tmp/ref.jpg")]


@pytest.mark.asyncio
async def test_process_scene_no_reference_image(mock_google_generation, tmp_path):
    """_process_scene calls generate_image with reference_images=None when no reference set."""
    from parrot.clients.google.reel.profiles import VideoProfileRegistry
    from parrot.clients.google.generation import _ReelRunContext

    scene = VideoReelScene(background_prompt="beach", video_prompt="pan", duration=5.0)
    request = VideoReelRequest(prompt="test", scenes=[scene])

    mock_img_msg = MagicMock()
    mock_img_msg.images = [tmp_path / "bg.jpg"]
    (tmp_path / "bg.jpg").touch()

    mock_google_generation.generate_image = AsyncMock(return_value=mock_img_msg)
    mock_google_generation.generate_video_clip = AsyncMock(return_value=_fake_clip(tmp_path, 0))
    mock_google_generation.generate_speech = AsyncMock()

    context = _ReelRunContext(
        request=request,
        registry=VideoProfileRegistry.default(),
        api_surface="gemini_developer",
        output_directory=tmp_path,
        job_deadline=time.monotonic() + 3600.0,
    )
    await mock_google_generation._process_scene(scene, 0, context=context)

    call_kwargs = mock_google_generation.generate_image.call_args.kwargs
    assert call_kwargs.get("reference_images") is None


@pytest.mark.asyncio
async def test_generate_video_reel_no_speech(
    mock_google_generation, tmp_path, fake_file_manager, _mock_reel_pipeline_tail
):
    """Test that no narration is generated when speech is not provided."""
    mock_google_generation._breakdown_prompt_to_scenes = AsyncMock(
        return_value=[
            VideoReelScene(
                background_prompt="Scene 1 BG",
                video_prompt="Scene 1 Video",
                narration_text="This will be cleared",  # cleared since no speech provided
                duration=5.0,
            ),
        ]
    )

    mock_google_generation.generate_image = AsyncMock()
    mock_google_generation.generate_image.return_value.images = [tmp_path / "mock_image.png"]
    (tmp_path / "mock_image.png").touch()

    mock_google_generation.generate_video_clip = AsyncMock(return_value=_fake_clip(tmp_path, 0))
    mock_google_generation.generate_speech = AsyncMock()

    request = VideoReelRequest(
        prompt="A test video reel without narration",
        music_prompt="Ambient music",
        aspect_ratio=AspectRatio.RATIO_9_16,
        # Note: speech is NOT provided
    )

    result = await mock_google_generation.generate_video_reel(
        request=request, output_directory=tmp_path, file_manager=fake_file_manager
    )

    assert result.files == [_mock_reel_pipeline_tail]
    mock_google_generation.generate_speech.assert_not_called()
