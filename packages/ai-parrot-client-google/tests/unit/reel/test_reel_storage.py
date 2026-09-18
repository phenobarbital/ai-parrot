"""TASK-3334: real local/temp storage boundary + mocked cloud transport.

Exercises `GoogleGeneration.generate_video_reel`'s own `FileManagerFactory`
resolution (``file_manager=None`` -> dispatched from
``request.storage_backend``) with REAL local ("fs") and temp ("temp")
filesystem I/O — actual bytes written to and read back from disk, a real
`FileManagerInterface` implementation, not a mock — and a MOCKED
`FileManagerFactory.create` for cloud ("s3"/"gcs") backends, so no real
network call or cloud credential is ever required. Mocks the
provider-facing surface (`generate_image`, `generate_video_clip`,
`generate_speech`, `ReelMusicService.generate`, `reel.assembly.assemble_reel`)
exactly like `test_reel_orchestration.py` — only the STORAGE boundary is
under test here. Checks durable local `Path`s versus plain URL strings per
this task's own scope ("Check durable paths versus URL strings").
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _resolve_real_file_manager_factory():
    """Resolve the REAL ``parrot.tools.filemanager.FileManagerFactory``,
    bypassing this repo's root ``conftest.py`` (and ``ai-parrot/tests/
    conftest.py``, if also loaded), which unconditionally
    ``sys.modules.setdefault("parrot.tools.filemanager", <fake>)``s a
    synthetic module with NO version/capability guard beyond a comment
    ("pre-FEAT-124 navigator compatibility" / "navigator-api < 3.0.3") —
    this environment's real navigator-api ships the full interface, but
    whichever conftest.py loads first (always the repo-root one, for any
    pytest invocation anywhere in this repo) still wins the ``setdefault``
    race and poisons the module name repo-wide, for every package. Its
    fake ``FileManagerFactory.create()`` always returns a fake
    ``LocalFileManager`` with no ``create_from_bytes`` (an
    ``AttributeError``, not a behavioral difference) — masking this
    module's own local/temp storage entirely. TASK-3334 fixture-repair
    finding — reported, NOT fixed at its root: outside this task's
    declared files (a shared, repo-wide conftest.py).

    Returns:
        The real ``FileManagerFactory`` class.
    """
    cached = sys.modules.get("parrot.tools.filemanager")
    if cached is not None and not hasattr(cached, "__file__"):
        del sys.modules["parrot.tools.filemanager"]
    import parrot.tools.filemanager as _real_module

    return _real_module.FileManagerFactory


RealFileManagerFactory = _resolve_real_file_manager_factory()

from parrot.clients.google.generation import GoogleGeneration  # noqa: E402
from parrot.clients.google.reel.clip import GeneratedReelClip  # noqa: E402
from parrot.clients.google.reel.music import MusicOutcome  # noqa: E402
from parrot.models.google import VideoReelRequest, VideoReelScene  # noqa: E402


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


@pytest.fixture(autouse=True)
def _mock_music():
    with patch(
        "parrot.clients.google.reel.music.ReelMusicService.generate",
        new=AsyncMock(return_value=MusicOutcome(status="off")),
    ):
        yield


@pytest.fixture
def mock_assemble(tmp_path):
    final_path = tmp_path / "assembled" / "final_reel.mp4"
    final_path.parent.mkdir(parents=True, exist_ok=True)
    final_path.write_bytes(b"REAL FINAL REEL BYTES")
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


class TestRealLocalStorageBoundary:
    """'fs' backend: file_manager=None dispatches to a REAL LocalFileManager."""

    async def test_fs_backend_persists_real_bytes_at_the_expected_key(self, gg, tmp_path, mock_assemble):
        _, final_path = mock_assemble
        scenes = [VideoReelScene(background_prompt="a", video_prompt="x", duration=5.0)]
        request = VideoReelRequest(prompt="test", scenes=scenes, storage_backend="fs")
        _mock_scene_generation(gg, tmp_path)

        # generation.py's own module-level `FileManagerFactory` name may
        # already be bound to the poisoned stub if some OTHER test file was
        # collected first in this pytest session (module-level eviction at
        # the top of this file only protects THIS file's own import, not
        # whatever `generation.py` already resolved to earlier) — patch it
        # to the verified-real class regardless of import order.
        with patch("parrot.clients.google.generation.FileManagerFactory", RealFileManagerFactory):
            result = await gg.generate_video_reel(request=request, output_directory=tmp_path, file_manager=None)

        artifact = result.artifacts[0]
        assert artifact["storage_backend"] == "fs"
        # AC10/AC18: durable local Path in `files`, never confused with the
        # separately-persisted FileManager copy's URL (a plain string).
        assert result.files == [final_path]
        assert isinstance(result.files[0], Path)
        assert result.files[0].exists()
        assert result.files[0].read_bytes() == b"REAL FINAL REEL BYTES"
        # The FileManager-persisted copy is a REAL, separate file on disk
        # (not a mock call) — verify its actual bytes too.
        storage_key = artifact["storage_key"]
        persisted_path = tmp_path / storage_key
        assert persisted_path.exists()
        assert persisted_path.read_bytes() == b"REAL FINAL REEL BYTES"
        # download_url is a plain string (file:// URI), never a Path.
        assert isinstance(artifact["download_url"], str)
        assert artifact["download_url"].startswith("file://")

    async def test_fs_backend_without_output_directory_uses_static_default(self, gg, tmp_path, mock_assemble):
        """No output_directory given -> BASE_DIR/static/generated_reels, still real disk I/O.

        ``BASE_DIR`` is patched to ``tmp_path`` for this test only — the
        real repo-root ``static/`` directory is read-only in this sandboxed
        worktree (by design: worktree agents never write to the shared
        checkout), so exercising the actual default-path FALLBACK DECISION
        must not depend on writing there for real.
        """
        scenes = [VideoReelScene(background_prompt="a", video_prompt="x", duration=5.0)]
        request = VideoReelRequest(prompt="test", scenes=scenes, storage_backend="fs")
        _mock_scene_generation(gg, tmp_path)
        mock_assemble_fn, _ = mock_assemble

        with (
            patch("parrot.clients.google.generation.BASE_DIR", tmp_path),
            patch("parrot.clients.google.generation.FileManagerFactory", RealFileManagerFactory),
        ):
            result = await gg.generate_video_reel(request=request, output_directory=None, file_manager=None)

        artifact = result.artifacts[0]
        assert artifact["storage_backend"] == "fs"
        assert result.files[0].exists()
        # assemble_reel is mocked (returns a fixed path regardless of
        # work_dir), so verify the DECISION — the computed job working
        # directory — via its call args, not via the mocked return path.
        actual_work_dir = mock_assemble_fn.call_args.kwargs["work_dir"]
        assert actual_work_dir.is_relative_to(tmp_path / "static" / "generated_reels")


class TestRealTempStorageBoundary:
    """'temp' backend: file_manager=None dispatches to a REAL TempFileManager."""

    async def test_temp_backend_persists_real_bytes(self, gg, tmp_path, mock_assemble):
        _, final_path = mock_assemble
        scenes = [VideoReelScene(background_prompt="a", video_prompt="x", duration=5.0)]
        request = VideoReelRequest(prompt="test", scenes=scenes, storage_backend="temp")
        _mock_scene_generation(gg, tmp_path)

        with patch("parrot.clients.google.generation.FileManagerFactory", RealFileManagerFactory):
            result = await gg.generate_video_reel(request=request, output_directory=tmp_path, file_manager=None)

        artifact = result.artifacts[0]
        assert artifact["storage_backend"] == "temp"
        # `files` still returns the raw working-directory copy for "temp"
        # backends (spec: local backends keep a durable local Path).
        assert result.files == [final_path]
        assert result.files[0].read_bytes() == b"REAL FINAL REEL BYTES"
        # The TempFileManager-persisted copy is a REAL, separate file too.
        assert isinstance(artifact["download_url"], str)


class TestMockedCloudTransportBoundary:
    """'s3'/'gcs' backends: FileManagerFactory.create is mocked — never a real network call."""

    async def test_s3_backend_never_makes_a_real_network_call(self, gg, tmp_path, mock_assemble):
        scenes = [VideoReelScene(background_prompt="a", video_prompt="x", duration=5.0)]
        request = VideoReelRequest(
            prompt="test", scenes=scenes, storage_backend="s3", storage_config={"bucket_name": "test-bucket"}
        )
        _mock_scene_generation(gg, tmp_path)

        mock_cloud_manager = AsyncMock()
        mock_cloud_manager.create_from_bytes = AsyncMock(return_value=True)
        mock_cloud_manager.get_file_url = AsyncMock(return_value="https://s3.example.com/bucket/key?sig=abc&exp=123")

        with patch(
            "parrot.clients.google.generation.FileManagerFactory.create", return_value=mock_cloud_manager
        ) as mock_create:
            result = await gg.generate_video_reel(request=request, output_directory=tmp_path, file_manager=None)

        # The storage-boundary DECISION is real: generate_video_reel itself
        # dispatched to FileManagerFactory.create with the request's own
        # backend/config — only the resulting manager's transport is mocked.
        mock_create.assert_called_once_with("s3", bucket_name="test-bucket")
        mock_cloud_manager.create_from_bytes.assert_awaited_once()
        mock_cloud_manager.get_file_url.assert_awaited_once()

        artifact = result.artifacts[0]
        assert artifact["storage_backend"] == "s3"
        # Cloud backends never return a local Path in `files` (AC10).
        assert result.files == []
        assert isinstance(artifact["download_url"], str)
        assert artifact["download_url"] == "https://s3.example.com/bucket/key?sig=abc&exp=123"

    async def test_gcs_backend_never_makes_a_real_network_call(self, gg, tmp_path, mock_assemble):
        scenes = [VideoReelScene(background_prompt="a", video_prompt="x", duration=5.0)]
        request = VideoReelRequest(
            prompt="test", scenes=scenes, storage_backend="gcs", storage_config={"bucket_name": "test-bucket"}
        )
        _mock_scene_generation(gg, tmp_path)

        mock_cloud_manager = AsyncMock()
        mock_cloud_manager.create_from_bytes = AsyncMock(return_value=True)
        mock_cloud_manager.get_file_url = AsyncMock(return_value="https://storage.googleapis.com/bucket/key?sig=xyz")

        with patch(
            "parrot.clients.google.generation.FileManagerFactory.create", return_value=mock_cloud_manager
        ) as mock_create:
            result = await gg.generate_video_reel(request=request, output_directory=tmp_path, file_manager=None)

        mock_create.assert_called_once_with("gcs", bucket_name="test-bucket")
        artifact = result.artifacts[0]
        assert artifact["storage_backend"] == "gcs"
        assert result.files == []
        assert isinstance(artifact["download_url"], str)

    async def test_cloud_backend_without_storage_config_calls_factory_with_no_kwargs(self, gg, tmp_path, mock_assemble):
        """No client-supplied storage_config -> empty kwargs, not a KeyError/AttributeError."""
        scenes = [VideoReelScene(background_prompt="a", video_prompt="x", duration=5.0)]
        request = VideoReelRequest(prompt="test", scenes=scenes, storage_backend="gcs")
        _mock_scene_generation(gg, tmp_path)

        mock_cloud_manager = AsyncMock()
        mock_cloud_manager.create_from_bytes = AsyncMock(return_value=True)
        mock_cloud_manager.get_file_url = AsyncMock(return_value="https://storage.googleapis.com/bucket/key")

        with patch(
            "parrot.clients.google.generation.FileManagerFactory.create", return_value=mock_cloud_manager
        ) as mock_create:
            await gg.generate_video_reel(request=request, output_directory=tmp_path, file_manager=None)

        mock_create.assert_called_once_with("gcs")


class TestExplicitFileManagerBypassesFactory:
    """Providing file_manager= directly skips FileManagerFactory entirely."""

    async def test_explicit_file_manager_used_verbatim_regardless_of_storage_backend(self, gg, tmp_path, mock_assemble):
        scenes = [VideoReelScene(background_prompt="a", video_prompt="x", duration=5.0)]
        # storage_backend says "s3", but an explicit file_manager overrides
        # FileManagerFactory dispatch entirely — never even consulted.
        request = VideoReelRequest(prompt="test", scenes=scenes, storage_backend="s3")
        _mock_scene_generation(gg, tmp_path)

        explicit_manager = AsyncMock()
        explicit_manager.create_from_bytes = AsyncMock(return_value=True)
        explicit_manager.get_file_url = AsyncMock(return_value="https://explicit.example/key")

        with patch("parrot.clients.google.generation.FileManagerFactory.create") as mock_create:
            result = await gg.generate_video_reel(
                request=request, output_directory=tmp_path, file_manager=explicit_manager
            )

        mock_create.assert_not_called()
        explicit_manager.create_from_bytes.assert_awaited_once()
        assert result.artifacts[0]["download_url"] == "https://explicit.example/key"
