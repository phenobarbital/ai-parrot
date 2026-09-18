"""TASK-3330: stage routing, scene policies and typed reel output tests.

Mocks the provider-facing surface (`generate_image`, `generate_video_clip`,
`generate_speech`, `ReelMusicService.generate`, `reel.assembly.assemble_reel`)
while the REAL `generate_video_reel`/`_process_scene`/
`_validate_known_video_profiles` orchestration logic runs end to end —
scene index preservation, fail/skip policy, director-unused/legacy-alias
warning propagation into the typed `ReelResult`, and exact artifact
serialization.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.clients.google.generation import GoogleGeneration
from parrot.clients.google.reel.clip import GeneratedReelClip
from parrot.clients.google.reel.errors import ReelErrorCode, ReelValidationError
from parrot.clients.google.reel.music import MusicOutcome
from parrot.models.google import VideoReelRequest, VideoReelScene


@pytest.fixture
def gg():
    obj = GoogleGeneration()
    obj.logger = MagicMock()
    obj.vertexai = False
    return obj


def _fake_clip(tmp_path: Path, index: int, *, backend: str = "veo", duration: float = 5.0) -> GeneratedReelClip:
    path = tmp_path / f"clip_{index}.mp4"
    path.write_bytes(b"\x00" * 10)
    return GeneratedReelClip(
        local_path=path,
        model="veo-3.1-generate-preview" if backend == "veo" else "gemini-omni-1.1-flash",
        backend=backend,
        submitted_duration_seconds=duration if backend == "veo" else None,
        measured_duration_seconds=duration,
        has_audio=False,
        provider_operation_id=f"operations/scene-{index}",
    )


@pytest.fixture
def fake_file_manager(tmp_path):
    fm = AsyncMock()
    fm.create_from_bytes = AsyncMock()
    fm.get_file_url = AsyncMock(return_value="https://storage.example/final_reel.mp4?sig=abc123")
    return fm


@pytest.fixture(autouse=True)
def _mock_music(tmp_path):
    with patch(
        "parrot.clients.google.reel.music.ReelMusicService.generate",
        new=AsyncMock(return_value=MusicOutcome(status="off")),
    ):
        yield


@pytest.fixture
def mock_assemble(tmp_path):
    final_path = tmp_path / "final_reel.mp4"
    final_path.write_bytes(b"\x00" * 20)
    with patch("parrot.clients.google.reel.assembly.assemble_reel", new=AsyncMock(return_value=final_path)) as mocked:
        mocked.return_value = final_path
        yield mocked, final_path


def _mock_scene_generation(gg, tmp_path, *, backends=None):
    """Wires generate_image/generate_video_clip/generate_speech with simple fakes."""
    bg_img = tmp_path / "bg.jpg"
    bg_img.write_bytes(b"\x00")
    gg.generate_image = AsyncMock(return_value=MagicMock(images=[bg_img]))
    gg.generate_speech = AsyncMock(return_value=MagicMock(files=[]))

    clips_by_index = {}

    async def _dispatch(
        *,
        prompt,
        model,
        output_directory,
        aspect_ratio,
        resolution,
        target_duration_seconds,
        starting_frame,
        audio_mode,
        timeout_seconds,
    ):
        index = len(clips_by_index)
        backend = (backends or {}).get(index, "veo")
        clip = _fake_clip(tmp_path, index, backend=backend, duration=target_duration_seconds)
        clips_by_index[index] = clip
        return clip

    gg.generate_video_clip = AsyncMock(side_effect=_dispatch)
    return clips_by_index


class TestDirectorUsageAndWarnings:
    async def test_director_unused_when_scenes_supplied(self, gg, tmp_path, fake_file_manager, mock_assemble):
        scenes = [VideoReelScene(background_prompt="a", video_prompt="x", duration=5.0)]
        request = VideoReelRequest(prompt="test", scenes=scenes)
        _mock_scene_generation(gg, tmp_path)
        gg._breakdown_prompt_to_scenes = AsyncMock()

        result = await gg.generate_video_reel(
            request=request, output_directory=tmp_path, file_manager=fake_file_manager
        )

        gg._breakdown_prompt_to_scenes.assert_not_called()
        reel_result = result.metadata["video_reel"]
        assert reel_result["director_unused"] is True
        assert reel_result["effective_models"]["director"] is None

    async def test_director_used_when_scenes_absent_and_model_forwarded(
        self, gg, tmp_path, fake_file_manager, mock_assemble
    ):
        request = VideoReelRequest(prompt="test", director_model="gemini-3.1-flash")
        _mock_scene_generation(gg, tmp_path)
        gg._breakdown_prompt_to_scenes = AsyncMock(
            return_value=[VideoReelScene(background_prompt="a", video_prompt="x", duration=5.0)]
        )

        result = await gg.generate_video_reel(
            request=request, output_directory=tmp_path, file_manager=fake_file_manager
        )

        gg._breakdown_prompt_to_scenes.assert_called_once_with("test", "gemini-3.1-flash")
        reel_result = result.metadata["video_reel"]
        assert reel_result["director_unused"] is False
        assert reel_result["effective_models"]["director"] == "gemini-3.1-flash"

    async def test_legacy_model_alias_warning_propagates_to_reel_result(
        self, gg, tmp_path, fake_file_manager, mock_assemble
    ):
        scenes = [VideoReelScene(background_prompt="a", video_prompt="x", duration=5.0)]
        request = VideoReelRequest(
            prompt="test", scenes=scenes, model="gemini-2.5-flash", director_model="gemini-2.5-flash"
        )
        _mock_scene_generation(gg, tmp_path)

        result = await gg.generate_video_reel(
            request=request, output_directory=tmp_path, file_manager=fake_file_manager
        )

        reel_result = result.metadata["video_reel"]
        assert any("deprecated" in w.lower() for w in reel_result["warnings"])

    async def test_image_model_forwarded_explicitly_to_both_image_calls(
        self, gg, tmp_path, fake_file_manager, mock_assemble
    ):
        scenes = [VideoReelScene(background_prompt="a", foreground_prompt="chart", video_prompt="x", duration=5.0)]
        request = VideoReelRequest(prompt="test", scenes=scenes, image_model="gemini-3.1-flash-image-preview")
        _mock_scene_generation(gg, tmp_path)
        gg._composite_images = AsyncMock(return_value=tmp_path / "composite.png")
        (tmp_path / "composite.png").write_bytes(b"\x00")

        await gg.generate_video_reel(request=request, output_directory=tmp_path, file_manager=fake_file_manager)

        assert gg.generate_image.call_count == 2
        for call in gg.generate_image.call_args_list:
            assert call.kwargs["model"] == "gemini-3.1-flash-image-preview"


class TestMixedVeoOmniDispatch:
    async def test_scene_video_model_override_dispatches_to_omni(self, gg, tmp_path, fake_file_manager, mock_assemble):
        scenes = [
            VideoReelScene(background_prompt="a", video_prompt="x", duration=5.0),
            VideoReelScene(background_prompt="b", video_prompt="y", duration=5.0, video_model="gemini-omni-1.1-flash"),
        ]
        request = VideoReelRequest(prompt="test", scenes=scenes, video_model="veo-3.1-generate-preview")
        _mock_scene_generation(gg, tmp_path, backends={0: "veo", 1: "omni"})

        result = await gg.generate_video_reel(
            request=request, output_directory=tmp_path, file_manager=fake_file_manager
        )

        scenes_out = result.metadata["video_reel"]["scenes"]
        assert scenes_out[0]["backend"] == "veo"
        assert scenes_out[1]["backend"] == "omni"
        call_models = [c.kwargs["model"] for c in gg.generate_video_clip.call_args_list]
        assert call_models == ["veo-3.1-generate-preview", "gemini-omni-1.1-flash"]


class TestProfileValidationBeforeDirectorAndGeneration:
    async def test_unknown_reel_video_model_rejected_before_director_work(self, gg, tmp_path, fake_file_manager):
        request = VideoReelRequest(prompt="test", video_model="not-a-real-model")
        gg._breakdown_prompt_to_scenes = AsyncMock()

        with pytest.raises(ReelValidationError) as exc_info:
            await gg.generate_video_reel(request=request, output_directory=tmp_path, file_manager=fake_file_manager)

        assert exc_info.value.code is ReelErrorCode.UNKNOWN_MODEL
        gg._breakdown_prompt_to_scenes.assert_not_called()

    async def test_unknown_known_scene_video_model_rejected_before_director_work(self, gg, tmp_path, fake_file_manager):
        """A caller-SUPPLIED scene's bad video_model is 'known' and validated before ANY work."""
        scenes = [VideoReelScene(background_prompt="a", video_prompt="x", duration=5.0, video_model="bogus-model")]
        request = VideoReelRequest(prompt="test", scenes=scenes)

        with pytest.raises(ReelValidationError):
            await gg.generate_video_reel(request=request, output_directory=tmp_path, file_manager=fake_file_manager)


class TestFailSkipAllFailedPolicies:
    async def test_fail_policy_aborts_on_first_scene_failure(self, gg, tmp_path, fake_file_manager):
        scenes = [
            VideoReelScene(background_prompt="a", video_prompt="x", duration=5.0),
            VideoReelScene(background_prompt="b", video_prompt="y", duration=5.0),
        ]
        request = VideoReelRequest(prompt="test", scenes=scenes, partial_failure_policy="fail")
        _mock_scene_generation(gg, tmp_path)
        gg.generate_image = AsyncMock(return_value=MagicMock(images=[]))  # forces failure

        with pytest.raises(Exception):
            await gg.generate_video_reel(request=request, output_directory=tmp_path, file_manager=fake_file_manager)

    async def test_skip_policy_preserves_original_indices_and_sets_partial(
        self, gg, tmp_path, fake_file_manager, mock_assemble
    ):
        scenes = [
            VideoReelScene(background_prompt="a", video_prompt="x", duration=5.0),
            VideoReelScene(background_prompt="fail-me", video_prompt="y", duration=5.0),
            VideoReelScene(background_prompt="c", video_prompt="z", duration=5.0),
        ]
        request = VideoReelRequest(prompt="test", scenes=scenes, partial_failure_policy="skip")
        _mock_scene_generation(gg, tmp_path)

        bg_img = tmp_path / "bg.jpg"
        bg_img.write_bytes(b"\x00")

        async def _image_side_effect(*, prompt, **kwargs):
            if prompt == "fail-me":
                return MagicMock(images=[])
            return MagicMock(images=[bg_img])

        gg.generate_image = AsyncMock(side_effect=_image_side_effect)

        result = await gg.generate_video_reel(
            request=request, output_directory=tmp_path, file_manager=fake_file_manager
        )

        reel_result = result.metadata["video_reel"]
        assert reel_result["partial"] is True
        statuses = {s["index"]: s["status"] for s in reel_result["scenes"]}
        assert statuses == {0: "succeeded", 1: "failed", 2: "succeeded"}

    async def test_all_scenes_failed_always_fails_job_even_under_skip(self, gg, tmp_path, fake_file_manager):
        scenes = [VideoReelScene(background_prompt="a", video_prompt="x", duration=5.0)]
        request = VideoReelRequest(prompt="test", scenes=scenes, partial_failure_policy="skip")
        gg.generate_image = AsyncMock(return_value=MagicMock(images=[]))

        with pytest.raises(Exception):
            await gg.generate_video_reel(request=request, output_directory=tmp_path, file_manager=fake_file_manager)


class TestArtifactAndFileSerialization:
    async def test_local_backend_files_contains_local_path_and_url_preserved_exactly(
        self, gg, tmp_path, fake_file_manager, mock_assemble
    ):
        scenes = [VideoReelScene(background_prompt="a", video_prompt="x", duration=5.0)]
        request = VideoReelRequest(prompt="test", scenes=scenes, storage_backend="fs")
        _mock_scene_generation(gg, tmp_path)
        _, final_path = mock_assemble

        result = await gg.generate_video_reel(
            request=request, output_directory=tmp_path, file_manager=fake_file_manager
        )

        assert result.files == [final_path]
        artifact = result.artifacts[0]
        assert artifact["download_url"] == "https://storage.example/final_reel.mp4?sig=abc123"
        assert artifact["storage_backend"] == "fs"
        assert isinstance(artifact["download_url"], str)

    async def test_cloud_backend_files_is_empty(self, gg, tmp_path, fake_file_manager, mock_assemble):
        scenes = [VideoReelScene(background_prompt="a", video_prompt="x", duration=5.0)]
        request = VideoReelRequest(prompt="test", scenes=scenes, storage_backend="gcs")
        _mock_scene_generation(gg, tmp_path)

        result = await gg.generate_video_reel(
            request=request, output_directory=tmp_path, file_manager=fake_file_manager
        )

        assert result.files == []

    async def test_reel_result_json_mode_round_trip_compatible_with_artifacts_dict(
        self, gg, tmp_path, fake_file_manager, mock_assemble
    ):
        scenes = [VideoReelScene(background_prompt="a", video_prompt="x", duration=5.0)]
        request = VideoReelRequest(prompt="test", scenes=scenes)
        _mock_scene_generation(gg, tmp_path)

        result = await gg.generate_video_reel(
            request=request, output_directory=tmp_path, file_manager=fake_file_manager
        )

        assert isinstance(result.metadata["video_reel"], dict)
        assert isinstance(result.artifacts, list)
        assert all(isinstance(a, dict) for a in result.artifacts)
        assert result.metadata["video_reel"]["sdk_version"] != ""
        assert result.metadata["video_reel"]["api_surface"] == "gemini_developer"
