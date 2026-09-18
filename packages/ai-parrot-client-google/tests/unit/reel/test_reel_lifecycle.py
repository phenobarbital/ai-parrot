"""TASK-3331: reel deadlines, cancellation and resource-ownership tests.

Exercises `GoogleGeneration.generate_video_reel`'s lifecycle concerns that
TASK-3330's orchestration tests deliberately leave out: configurable
scene/job deadlines (`_reel_scene_deadline_seconds`/`_reel_job_deadline_seconds`
and `_ReelRunContext.effective_scene_timeout_seconds`), cancellation-safe
cleanup of the still-owned music task and per-job working directory, and
that every directly-created SDK client this module owns (`generate_image`,
the director call in `_breakdown_prompt_to_scenes`) is closed exactly once.

Mocks the provider-facing surface (`generate_image`, `generate_video_clip`,
`generate_speech`, `ReelMusicService.generate`, `reel.assembly.assemble_reel`)
the same way TASK-3330's `test_reel_orchestration.py` does; the REAL
`generate_video_reel`/`_process_scene`/`_ReelRunContext` lifecycle logic
runs end to end. No default test consumes a paid provider call.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.clients.google.generation import (
    GoogleGeneration,
    _ReelRunContext,
    _reel_job_deadline_seconds,
    _reel_scene_deadline_seconds,
)
from parrot.clients.google.reel.clip import GeneratedReelClip
from parrot.clients.google.reel.music import MusicOutcome
from parrot.models.google import VideoReelRequest, VideoReelScene


@pytest.fixture
def gg():
    obj = GoogleGeneration()
    obj.logger = MagicMock()
    obj.vertexai = False
    return obj


def _fake_clip(tmp_path: Path, index: int, *, duration: float = 5.0) -> GeneratedReelClip:
    path = tmp_path / f"clip_{index}.mp4"
    path.write_bytes(b"\x00" * 10)
    return GeneratedReelClip(
        local_path=path,
        model="veo-3.1-generate-preview",
        backend="veo",
        submitted_duration_seconds=duration,
        measured_duration_seconds=duration,
        has_audio=False,
        provider_operation_id=f"operations/scene-{index}",
    )


@pytest.fixture
def fake_file_manager():
    fm = AsyncMock()
    fm.create_from_bytes = AsyncMock()
    fm.get_file_url = AsyncMock(return_value="https://storage.example/final_reel.mp4?sig=abc123")
    return fm


@pytest.fixture
def mock_assemble(tmp_path):
    final_path = tmp_path / "final_reel.mp4"
    final_path.write_bytes(b"\x00" * 20)
    with patch("parrot.clients.google.reel.assembly.assemble_reel", new=AsyncMock(return_value=final_path)) as mocked:
        yield mocked, final_path


def _mock_scene_generation(gg, tmp_path):
    bg_img = tmp_path / "bg.jpg"
    bg_img.write_bytes(b"\x00")
    gg.generate_image = AsyncMock(return_value=MagicMock(images=[bg_img]))
    gg.generate_speech = AsyncMock(return_value=MagicMock(files=[]))

    clips_by_index: dict = {}

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
        clip = _fake_clip(tmp_path, index, duration=target_duration_seconds)
        clips_by_index[index] = clip
        return clip

    gg.generate_video_clip = AsyncMock(side_effect=_dispatch)
    return clips_by_index


class TestConfigurableDeadlines:
    def test_scene_deadline_defaults_to_600_seconds(self, monkeypatch):
        monkeypatch.delenv("VIDEO_REEL_SCENE_DEADLINE_SECONDS", raising=False)
        assert _reel_scene_deadline_seconds() == 600.0

    def test_scene_deadline_reads_env_override(self, monkeypatch):
        monkeypatch.setenv("VIDEO_REEL_SCENE_DEADLINE_SECONDS", "45")
        assert _reel_scene_deadline_seconds() == 45.0

    def test_job_deadline_defaults_to_3600_seconds(self, monkeypatch):
        monkeypatch.delenv("VIDEO_REEL_JOB_DEADLINE_SECONDS", raising=False)
        assert _reel_job_deadline_seconds() == 3600.0

    def test_job_deadline_reads_env_override(self, monkeypatch):
        monkeypatch.setenv("VIDEO_REEL_JOB_DEADLINE_SECONDS", "120")
        assert _reel_job_deadline_seconds() == 120.0

    def test_effective_scene_timeout_never_exceeds_scene_ceiling(self, tmp_path):
        request = VideoReelRequest(prompt="test", scenes=[])
        context = _ReelRunContext(
            request=request,
            registry=MagicMock(),
            api_surface="gemini_developer",
            output_directory=tmp_path,
            job_deadline=float("inf"),
            scene_deadline_seconds=30.0,
        )
        assert context.effective_scene_timeout_seconds() == 30.0

    def test_effective_scene_timeout_clamped_by_remaining_job_budget(self, tmp_path):
        """Late in a job, the per-scene budget shares whatever job time remains."""
        request = VideoReelRequest(prompt="test", scenes=[])
        context = _ReelRunContext(
            request=request,
            registry=MagicMock(),
            api_surface="gemini_developer",
            output_directory=tmp_path,
            job_deadline=0.0,  # already expired
            scene_deadline_seconds=600.0,
        )
        assert context.effective_scene_timeout_seconds() == 0.0

    async def test_public_reel_signature_unchanged_while_deadline_is_configured(
        self, gg, tmp_path, fake_file_manager, mock_assemble, monkeypatch
    ):
        """Enforcing the configurable job deadline must not alter generate_video_reel's signature."""
        monkeypatch.setenv("VIDEO_REEL_JOB_DEADLINE_SECONDS", "5")
        scenes = [VideoReelScene(background_prompt="a", video_prompt="x", duration=5.0)]
        request = VideoReelRequest(prompt="test", scenes=scenes)
        _mock_scene_generation(gg, tmp_path)
        with patch(
            "parrot.clients.google.reel.music.ReelMusicService.generate",
            new=AsyncMock(return_value=MusicOutcome(status="off")),
        ):
            result = await gg.generate_video_reel(
                request=request, output_directory=tmp_path, file_manager=fake_file_manager
            )

        assert result.metadata["video_reel"]["scenes"][0]["status"] == "succeeded"


class TestCancellationCleanup:
    async def test_cancellation_during_scene_processing_cancels_music_and_cleans_job_dir(
        self, gg, tmp_path, fake_file_manager
    ):
        scenes = [VideoReelScene(background_prompt="a", video_prompt="x", duration=5.0)]
        request = VideoReelRequest(prompt="test", scenes=scenes)
        _mock_scene_generation(gg, tmp_path)
        gg.generate_video_clip = AsyncMock(side_effect=asyncio.CancelledError())

        music_gen = AsyncMock(return_value=MusicOutcome(status="off"))
        with patch("parrot.clients.google.reel.music.ReelMusicService.generate", new=music_gen):
            with pytest.raises(asyncio.CancelledError):
                await gg.generate_video_reel(request=request, output_directory=tmp_path, file_manager=fake_file_manager)

        # The per-job working directory (a fresh subdirectory nested under
        # the caller's output_directory, TASK-3331) must not survive an
        # aborted job.
        leftover_job_dirs = [p for p in tmp_path.iterdir() if p.is_dir()]
        assert leftover_job_dirs == []

    async def test_cancellation_propagates_as_cancelled_error_not_swallowed(self, gg, tmp_path, fake_file_manager):
        """CancelledError is a BaseException — JobManager relies on it surfacing unchanged."""
        scenes = [VideoReelScene(background_prompt="a", video_prompt="x", duration=5.0)]
        request = VideoReelRequest(prompt="test", scenes=scenes)
        _mock_scene_generation(gg, tmp_path)
        gg.generate_video_clip = AsyncMock(side_effect=asyncio.CancelledError())

        with patch(
            "parrot.clients.google.reel.music.ReelMusicService.generate",
            new=AsyncMock(return_value=MusicOutcome(status="off")),
        ):
            with pytest.raises(asyncio.CancelledError):
                await gg.generate_video_reel(request=request, output_directory=tmp_path, file_manager=fake_file_manager)

    async def test_scene_failure_cancels_still_running_music_task(self, gg, tmp_path, fake_file_manager):
        """A still-running (not-yet-awaited) music task must be cancelled+awaited on scene failure.

        `generate_video_reel` only reaches ``await music_task`` AFTER every
        scene has been processed, so a scene-processing failure — unlike an
        assembly failure, which can only happen once music has already been
        awaited to completion — is the one path where the music task can
        genuinely still be running when cleanup kicks in.
        """
        scenes = [VideoReelScene(background_prompt="a", video_prompt="x", duration=5.0)]
        request = VideoReelRequest(prompt="test", scenes=scenes)
        _mock_scene_generation(gg, tmp_path)

        async def _fail_clip(*args, **kwargs):
            # A real yield point (unlike a synchronous-return AsyncMock) so
            # the already-created music_task actually gets scheduled before
            # this raises — matching how real provider I/O always yields.
            await asyncio.sleep(0)
            raise RuntimeError("video generation blew up")

        gg.generate_video_clip = AsyncMock(side_effect=_fail_clip)

        music_started = asyncio.Event()
        music_cancelled = asyncio.Event()

        async def _slow_music(*args, **kwargs):
            music_started.set()
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                music_cancelled.set()
                raise
            return MusicOutcome(status="off")

        with patch("parrot.clients.google.reel.music.ReelMusicService.generate", new=_slow_music):
            with pytest.raises(Exception):
                await gg.generate_video_reel(request=request, output_directory=tmp_path, file_manager=fake_file_manager)

        assert music_started.is_set()
        assert music_cancelled.is_set()

    async def test_assembly_failure_still_cleans_up_job_directory(self, gg, tmp_path, fake_file_manager):
        """Assembly runs strictly after music is awaited — its failure must still clean up the job dir."""
        scenes = [VideoReelScene(background_prompt="a", video_prompt="x", duration=5.0)]
        request = VideoReelRequest(prompt="test", scenes=scenes)
        _mock_scene_generation(gg, tmp_path)

        with (
            patch(
                "parrot.clients.google.reel.music.ReelMusicService.generate",
                new=AsyncMock(return_value=MusicOutcome(status="off")),
            ),
            patch(
                "parrot.clients.google.reel.assembly.assemble_reel",
                new=AsyncMock(side_effect=RuntimeError("assembly blew up")),
            ),
        ):
            with pytest.raises(RuntimeError, match="assembly blew up"):
                await gg.generate_video_reel(request=request, output_directory=tmp_path, file_manager=fake_file_manager)

        leftover_job_dirs = [p for p in tmp_path.iterdir() if p.is_dir()]
        assert leftover_job_dirs == []

    async def test_successful_job_preserves_job_directory_for_local_backend(
        self, gg, tmp_path, fake_file_manager, mock_assemble
    ):
        """Cleanup must never run on the success path — local backends still need the directory."""
        scenes = [VideoReelScene(background_prompt="a", video_prompt="x", duration=5.0)]
        request = VideoReelRequest(prompt="test", scenes=scenes, storage_backend="fs")
        _mock_scene_generation(gg, tmp_path)

        with patch(
            "parrot.clients.google.reel.music.ReelMusicService.generate",
            new=AsyncMock(return_value=MusicOutcome(status="off")),
        ):
            await gg.generate_video_reel(request=request, output_directory=tmp_path, file_manager=fake_file_manager)

        job_dirs = [p for p in tmp_path.iterdir() if p.is_dir()]
        assert len(job_dirs) == 1


class TestConcurrentJobIsolation:
    async def test_two_concurrent_jobs_get_disjoint_working_directories(self, gg, tmp_path, fake_file_manager):
        """Two jobs sharing the same caller-supplied output_directory must never collide."""
        seen_dirs: list[Path] = []

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
            seen_dirs.append(Path(output_directory))
            return _fake_clip(Path(output_directory), 0, duration=target_duration_seconds)

        async def _gen_image(*, prompt, output_directory=None, **kwargs):
            img_dir = Path(output_directory) if output_directory else tmp_path
            img_dir.mkdir(parents=True, exist_ok=True)
            img_path = img_dir / "bg.jpg"
            img_path.write_bytes(b"\x00")
            return MagicMock(images=[img_path])

        gg.generate_video_clip = AsyncMock(side_effect=_dispatch)
        gg.generate_image = AsyncMock(side_effect=_gen_image)
        gg.generate_speech = AsyncMock(return_value=MagicMock(files=[]))

        request_1 = VideoReelRequest(
            prompt="job one", scenes=[VideoReelScene(background_prompt="a", video_prompt="x", duration=5.0)]
        )
        request_2 = VideoReelRequest(
            prompt="job two", scenes=[VideoReelScene(background_prompt="b", video_prompt="y", duration=5.0)]
        )

        final_path_1 = tmp_path / "final_1.mp4"
        final_path_2 = tmp_path / "final_2.mp4"
        final_path_1.write_bytes(b"\x00")
        final_path_2.write_bytes(b"\x00")
        assemble_mock = AsyncMock(side_effect=[final_path_1, final_path_2])

        with (
            patch(
                "parrot.clients.google.reel.music.ReelMusicService.generate",
                new=AsyncMock(return_value=MusicOutcome(status="off")),
            ),
            patch("parrot.clients.google.reel.assembly.assemble_reel", new=assemble_mock),
        ):
            results = await asyncio.gather(
                gg.generate_video_reel(request=request_1, output_directory=tmp_path, file_manager=fake_file_manager),
                gg.generate_video_reel(request=request_2, output_directory=tmp_path, file_manager=fake_file_manager),
            )

        assert len(seen_dirs) == 2
        assert seen_dirs[0] != seen_dirs[1]
        assert seen_dirs[0].parent == tmp_path
        assert seen_dirs[1].parent == tmp_path
        for result in results:
            assert result.metadata["video_reel"]["scenes"][0]["status"] == "succeeded"


class TestOwnedClientClosure:
    async def test_generate_image_closes_directly_created_client_on_success(self, gg):
        client = MagicMock()
        client.aio = MagicMock()
        client.aio.aclose = AsyncMock()
        response = MagicMock()
        response.parts = []
        client.aio.models.generate_content = AsyncMock(return_value=response)
        gg.get_client = AsyncMock(return_value=client)
        gg._format_history = MagicMock(return_value=())

        await gg.generate_image(prompt="a cat", model="gemini-3.1-flash-image-preview")

        client.aio.aclose.assert_awaited_once()

    async def test_generate_image_closes_directly_created_client_on_failure(self, gg):
        client = MagicMock()
        client.aio = MagicMock()
        client.aio.aclose = AsyncMock()
        client.aio.models.generate_content = AsyncMock(side_effect=RuntimeError("provider exploded"))
        gg.get_client = AsyncMock(return_value=client)
        gg._format_history = MagicMock(return_value=())

        with pytest.raises(RuntimeError, match="provider exploded"):
            await gg.generate_image(prompt="a cat", model="gemini-3.1-flash-image-preview")

        client.aio.aclose.assert_awaited_once()

    async def test_breakdown_prompt_to_scenes_closes_director_client(self, gg):
        client = MagicMock()
        client.aio = MagicMock()
        client.aio.aclose = AsyncMock()
        response = MagicMock()
        response.text = "[]"
        client.aio.models.generate_content = AsyncMock(return_value=response)
        gg.get_client = AsyncMock(return_value=client)

        await gg._breakdown_prompt_to_scenes("prompt", "gemini-3.1-flash")

        client.aio.aclose.assert_awaited_once()

    async def test_breakdown_prompt_to_scenes_closes_director_client_on_failure(self, gg):
        client = MagicMock()
        client.aio = MagicMock()
        client.aio.aclose = AsyncMock()
        client.aio.models.generate_content = AsyncMock(side_effect=RuntimeError("director exploded"))
        gg.get_client = AsyncMock(return_value=client)

        with pytest.raises(RuntimeError, match="director exploded"):
            await gg._breakdown_prompt_to_scenes("prompt", "gemini-3.1-flash")

        client.aio.aclose.assert_awaited_once()
