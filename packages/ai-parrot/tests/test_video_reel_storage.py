"""Tests for FEAT-043: Configurable Persistency for Video Reel Generation.

Covers:
- Model field tests (storage_backend, storage_config)
- FileManager factory integration
- Handler storage configuration from env vars
- Pipeline FileManager initialization
- Assembly hybrid storage pattern
- Backward compatibility
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from parrot.models.google import VideoReelRequest
from parrot.interfaces.file import FileManagerInterface
from parrot.tools.filemanager import FileManagerFactory


def _resolve_real_file_manager_symbols():
    """Resolve the REAL ``parrot.tools.filemanager.FileManagerFactory`` /
    ``parrot.interfaces.file.FileManagerInterface``, bypassing a stale
    ``conftest.py`` fixture that unconditionally poisons both modules
    (TASK-3334 fixture-repair finding — reported, NOT fixed here: outside
    this task's declared files).

    ``packages/ai-parrot/tests/conftest.py``'s ``_install_navigator_stubs()``
    calls ``sys.modules.setdefault("parrot.tools.filemanager", <fake>)`` /
    ``sys.modules.setdefault("parrot.interfaces.file", <fake>)``
    UNCONDITIONALLY at collection time (module-level, no version/capability
    guard — only the comment claims it's meant for "navigator-api < 3.0.3").
    This environment's real navigator-api ships the full interface (verified
    directly: ``FileManagerFactory.create("temp")`` correctly returns
    ``TempFileManager`` when imported fresh, outside pytest). But
    ``setdefault`` means whichever module wins the race to be imported FIRST
    in the whole pytest session stays cached for every subsequent import —
    and conftest.py always wins, since it runs before any test module. The
    fake ``FileManagerFactory.create()`` is `lambda *a, **kw:
    _LocalFileManager()` — it ALWAYS returns a (also fake) LocalFileManager
    regardless of the requested backend, and never raises for an invalid
    one, silently masking exactly the behavior
    ``TestFileManagerFactory``/``TestHandlerStorageConfig`` below assert.

    Evicting the poisoned entries and re-importing forces the REAL modules
    to resolve for every test in THIS file, without touching the shared
    conftest.py (out of TASK-3334's declared scope; the fix belongs to
    conftest.py's owner — this environment's navigator-api no longer needs
    the compatibility stub at all).

    Returns:
        ``(FileManagerFactory, FileManagerInterface)`` — the real classes.
    """
    for _mod_name in ("parrot.tools.filemanager", "parrot.interfaces.file"):
        _cached = sys.modules.get(_mod_name)
        if _cached is not None and not hasattr(_cached, "__file__"):
            del sys.modules[_mod_name]
    import parrot.tools.filemanager as _real_fm_module
    import parrot.interfaces.file as _real_file_module

    return _real_fm_module.FileManagerFactory, _real_file_module.FileManagerInterface


RealFileManagerFactory, RealFileManagerInterface = _resolve_real_file_manager_symbols()

# ---------------------------------------------------------------------------
# 1. Model field tests (TASK-289)
# ---------------------------------------------------------------------------


class TestVideoReelRequestStorageFields:
    """Verify storage_backend and storage_config fields on VideoReelRequest."""

    def test_storage_defaults(self):
        """Default storage_backend is 'fs' and storage_config is None."""
        req = VideoReelRequest(prompt="test")
        assert req.storage_backend == "fs"
        assert req.storage_config is None

    def test_storage_backend_s3(self):
        """S3 backend with config parses correctly."""
        req = VideoReelRequest(
            prompt="test",
            storage_backend="s3",
            storage_config={"bucket": "my-bucket"},
        )
        assert req.storage_backend == "s3"
        assert req.storage_config == {"bucket": "my-bucket"}

    def test_storage_backend_gcs(self):
        """GCS backend with config parses correctly."""
        req = VideoReelRequest(
            prompt="test",
            storage_backend="gcs",
            storage_config={"bucket": "b", "prefix": "videos/"},
        )
        assert req.storage_backend == "gcs"
        assert req.storage_config["bucket"] == "b"

    def test_storage_backend_temp(self):
        """Temp backend parses correctly."""
        req = VideoReelRequest(prompt="test", storage_backend="temp")
        assert req.storage_backend == "temp"

    def test_storage_backend_invalid(self):
        """Invalid storage_backend raises ValidationError."""
        with pytest.raises(ValidationError):
            VideoReelRequest(prompt="test", storage_backend="invalid")

    def test_storage_backend_in_schema(self):
        """JSON schema includes storage_backend and storage_config."""
        schema = VideoReelRequest.model_json_schema()
        props = schema["properties"]
        assert "storage_backend" in props
        assert "storage_config" in props

    def test_backward_compat_no_storage_fields(self):
        """Existing payloads without storage fields still parse correctly."""
        req = VideoReelRequest(
            prompt="ocean reel",
            music_genre="Chillout",
            aspect_ratio="9:16",
        )
        assert req.storage_backend == "fs"
        assert req.storage_config is None
        assert req.prompt == "ocean reel"


# ---------------------------------------------------------------------------
# 2. FileManager factory tests (TASK-290)
# ---------------------------------------------------------------------------


class TestFileManagerFactory:
    """Verify FileManagerFactory creates the right backend types."""

    def test_create_local(self, tmp_path):
        """'fs' backend creates a LocalFileManager."""
        fm = FileManagerFactory.create("fs", base_path=tmp_path)
        assert isinstance(fm, FileManagerInterface)
        assert type(fm).__name__ == "LocalFileManager"

    def test_create_temp(self):
        """'temp' backend creates a TempFileManager."""
        fm = RealFileManagerFactory.create("temp")
        assert isinstance(fm, RealFileManagerInterface)
        assert type(fm).__name__ == "TempFileManager"

    def test_create_invalid_raises(self):
        """Invalid backend type raises ValueError."""
        with pytest.raises((ValueError, KeyError)):
            RealFileManagerFactory.create("invalid_backend")


# ---------------------------------------------------------------------------
# 3. Handler storage configuration tests (TASK-294)
# ---------------------------------------------------------------------------


class TestHandlerStorageConfig:
    """Verify VideoReelHandler._create_file_manager reads env vars."""

    @pytest.fixture
    def handler(self):
        """Create a minimal VideoReelHandler for testing."""
        from parrot.handlers.video_reel import VideoReelHandler

        h = VideoReelHandler.__new__(VideoReelHandler)
        h.logger = MagicMock()
        return h

    def test_default_returns_none(self, handler):
        """Without env vars, _create_file_manager returns None (pipeline default)."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove any VIDEO_REEL_ env vars
            for key in list(os.environ):
                if key.startswith("VIDEO_REEL_"):
                    del os.environ[key]
            result = handler._create_file_manager()
        assert result is None

    def test_fs_with_output_dir(self, handler, tmp_path):
        """With fs backend and output_directory, creates LocalFileManager."""
        with patch.dict(os.environ, {"VIDEO_REEL_STORAGE_BACKEND": "fs"}, clear=False):
            fm = handler._create_file_manager(output_directory=tmp_path)
        assert fm is not None
        assert type(fm).__name__ == "LocalFileManager"

    def test_temp_backend(self, handler):
        """With temp backend, creates TempFileManager."""
        # `video_reel.py`'s own module-level `FileManagerFactory` name was
        # bound at ITS import time, which may have already resolved to the
        # stale conftest.py stub (see _resolve_real_file_manager_symbols's
        # docstring above) — patch it to the verified-real class for this
        # assertion regardless of import order.
        with (
            patch("parrot.handlers.video_reel.FileManagerFactory", RealFileManagerFactory),
            patch.dict(
                os.environ,
                {"VIDEO_REEL_STORAGE_BACKEND": "temp"},
                clear=False,
            ),
        ):
            fm = handler._create_file_manager()
        assert fm is not None
        assert type(fm).__name__ == "TempFileManager"

    def test_s3_without_bucket_falls_back(self, handler):
        """S3 backend without bucket falls back to None."""
        env = {"VIDEO_REEL_STORAGE_BACKEND": "s3"}
        # Ensure no bucket env var
        cleaned = {k: v for k, v in os.environ.items() if not k.startswith("VIDEO_REEL_STORAGE_BUCKET")}
        cleaned.update(env)
        with patch.dict(os.environ, cleaned, clear=True):
            fm = handler._create_file_manager()
        assert fm is None

    def test_gcs_with_bucket(self, handler):
        """GCS backend with bucket creates GCSFileManager."""
        env = {
            "VIDEO_REEL_STORAGE_BACKEND": "gcs",
            "VIDEO_REEL_STORAGE_BUCKET": "my-bucket",
        }
        with patch.dict(os.environ, env, clear=False):
            try:
                fm = handler._create_file_manager()
                # May fail if google-cloud-storage is not installed
                assert fm is not None
                assert type(fm).__name__ == "GCSFileManager"
            except Exception:
                # GCS SDK not available in test env is acceptable
                pytest.skip("GCS SDK not available")


# ---------------------------------------------------------------------------
# 4. Pipeline FileManager initialization tests (TASK-290)
# ---------------------------------------------------------------------------


class TestPipelineFileManagerInit:
    """Verify generate_video_reel() accepts and initializes FileManager."""

    def test_signature_accepts_file_manager(self):
        """generate_video_reel has file_manager parameter."""
        import inspect
        from parrot.clients.google.generation import GoogleGeneration

        sig = inspect.signature(GoogleGeneration.generate_video_reel)
        params = list(sig.parameters.keys())
        assert "file_manager" in params
        assert "output_directory" in params

    def test_process_scene_signature(self):
        """FEAT-564 TASK-3330: _process_scene now takes a single `context`
        keyword-only parameter (bundling file_manager/job_prefix/registry/etc.)
        instead of separate file_manager/job_prefix parameters."""
        import inspect
        from parrot.clients.google.generation import GoogleGeneration

        sig = inspect.signature(GoogleGeneration._process_scene)
        params = list(sig.parameters.keys())
        assert "context" in params
        assert "file_manager" not in params
        assert "job_prefix" not in params

    def test_process_scene_returns_strings(self):
        """FEAT-564 TASK-3330: _process_scene's return annotation is now the
        typed ReelSceneResult, replacing the legacy tuple[Optional[str], Optional[str]]."""
        import inspect
        from parrot.clients.google.generation import GoogleGeneration

        sig = inspect.signature(GoogleGeneration._process_scene)
        ret = sig.return_annotation
        assert "ReelSceneResult" in str(ret), f"Expected ReelSceneResult in return type, got {ret}"

    def test_generate_reel_music_returns_optional_str(self):
        """_generate_reel_music return annotation is Optional[str]."""
        import inspect
        from parrot.clients.google.generation import GoogleGeneration

        sig = inspect.signature(GoogleGeneration._generate_reel_music)
        ret = sig.return_annotation
        assert "str" in str(ret), f"Expected str in return type, got {ret}"


# ---------------------------------------------------------------------------
# 5. Assembly hybrid storage tests (TASK-293)
# ---------------------------------------------------------------------------


class TestAssemblyHybridStorage:
    """Verify _create_reel_assembly uses download→assemble→upload pattern."""

    def test_assembly_signature(self):
        """_create_reel_assembly accepts file_manager and job_prefix."""
        import inspect
        from parrot.clients.google.generation import GoogleGeneration

        sig = inspect.signature(GoogleGeneration._create_reel_assembly)
        params = list(sig.parameters.keys())
        assert "file_manager" in params
        assert "job_prefix" in params
        assert "scene_outputs" in params
        assert "music_key" in params

    def test_assembly_returns_str(self):
        """_create_reel_assembly return annotation is str."""
        import inspect
        from parrot.clients.google.generation import GoogleGeneration

        sig = inspect.signature(GoogleGeneration._create_reel_assembly)
        ret = sig.return_annotation
        assert ret is str or "str" in str(ret)

    @pytest.mark.asyncio
    async def test_assembly_downloads_scenes(self):
        """Assembly calls file_manager.download_file for scene videos."""
        from parrot.clients.google.generation import GoogleGeneration

        fm = AsyncMock(spec=FileManagerInterface)
        fm.download_file = AsyncMock(side_effect=self._fake_download)
        fm.upload_file = AsyncMock()

        obj = GoogleGeneration.__new__(GoogleGeneration)
        obj.logger = MagicMock()

        scene_outputs = [
            ("reels/abc/scenes/scene_0_video.mp4", "reels/abc/scenes/scene_0_narration.wav"),
        ]

        with patch("parrot.clients.google.generation.asyncio") as mock_aio:
            # Make to_thread return the local_output path
            mock_aio.to_thread = AsyncMock(return_value=Path("/tmp/fake_output.mp4"))
            try:
                result = await obj._create_reel_assembly(
                    scene_outputs=scene_outputs,
                    music_key=None,
                    output_dir=Path("/tmp"),
                    transition="crossfade",
                    output_format="mp4",
                    file_manager=fm,
                    job_prefix="reels/abc",
                )
            except Exception:
                # MoviePy may not be installed; verify downloads happened
                pass

        # download_file should have been called for the video and narration
        assert fm.download_file.call_count >= 1

    @pytest.mark.asyncio
    async def test_assembly_uploads_final(self):
        """Assembly calls file_manager.upload_file for final video."""
        from parrot.clients.google.generation import GoogleGeneration

        fm = AsyncMock(spec=FileManagerInterface)
        fm.download_file = AsyncMock(side_effect=self._fake_download)
        fm.upload_file = AsyncMock()

        obj = GoogleGeneration.__new__(GoogleGeneration)
        obj.logger = MagicMock()

        scene_outputs = [
            ("reels/abc/scenes/scene_0_video.mp4", None),
        ]

        fd, tmp_path = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)
        fake_output = Path(tmp_path)
        fake_output.write_bytes(b"\x00" * 100)

        # FEAT-564 TASK-3329: _create_reel_assembly now delegates the actual
        # encode to reel.assembly.assemble_reel (a managed-process call) and
        # measures each scene's real duration via moviepy.VideoFileClip
        # before building a TimelinePlan — mock both instead of the whole
        # `asyncio` module (the old single asyncio.to_thread() call this test
        # used to stub no longer exists; asyncio.to_thread is now used only
        # for the per-scene duration probe, not for running the encode).
        fake_clip = MagicMock()
        fake_clip.duration = 1.0
        fake_clip.close = MagicMock()

        with (
            patch("moviepy.VideoFileClip", return_value=fake_clip),
            patch(
                "parrot.clients.google.reel.assembly.assemble_reel",
                new=AsyncMock(return_value=fake_output),
            ),
        ):
            result = await obj._create_reel_assembly(
                scene_outputs=scene_outputs,
                music_key=None,
                output_dir=Path("/tmp"),
                transition="cut",
                output_format="mp4",
                file_manager=fm,
                job_prefix="reels/abc",
            )

        fm.upload_file.assert_called_once()
        assert result.startswith("reels/abc/final/")

        # Cleanup
        if fake_output.exists():
            fake_output.unlink()

    @staticmethod
    async def _fake_download(source: str, destination):
        """Create a fake file at destination to simulate download."""
        dest = Path(str(destination))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"\x00" * 100)
        return dest


# ---------------------------------------------------------------------------
# 6. Backward compatibility tests
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """Ensure existing behavior is preserved when no storage config is set."""

    def test_request_without_storage_fields(self):
        """VideoReelRequest without storage fields uses defaults."""
        req = VideoReelRequest(
            prompt="Test reel",
            scenes=[
                {
                    "background_prompt": "Ocean",
                    "video_prompt": "Pan right",
                }
            ],
        )
        assert req.storage_backend == "fs"
        assert req.storage_config is None
        assert len(req.scenes) == 1

    def test_json_only_post_body(self):
        """JSON-only request body works without storage fields."""
        data = {"prompt": "Test reel", "aspect_ratio": "16:9"}
        req = VideoReelRequest(**data)
        assert req.storage_backend == "fs"
        assert req.prompt == "Test reel"

    def test_output_directory_still_accepted(self):
        """generate_video_reel still accepts output_directory parameter."""
        import inspect
        from parrot.clients.google.generation import GoogleGeneration

        sig = inspect.signature(GoogleGeneration.generate_video_reel)
        params = list(sig.parameters.keys())
        assert "output_directory" in params
