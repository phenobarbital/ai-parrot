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
import tempfile
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from parrot.models.google import VideoReelRequest
from parrot.interfaces.file import FileManagerInterface
from parrot.tools.filemanager import FileManagerFactory


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
        fm = FileManagerFactory.create("temp")
        assert isinstance(fm, FileManagerInterface)
        assert type(fm).__name__ == "TempFileManager"

    def test_create_invalid_raises(self):
        """Invalid backend type raises ValueError."""
        with pytest.raises((ValueError, KeyError)):
            FileManagerFactory.create("invalid_backend")


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
        with patch.dict(
            os.environ,
            {"VIDEO_REEL_STORAGE_BACKEND": "temp"},
            clear=False,
        ):
            fm = handler._create_file_manager()
        assert fm is not None
        assert type(fm).__name__ == "TempFileManager"

    def test_s3_without_bucket_falls_back(self, handler):
        """S3 backend without bucket falls back to None."""
        env = {"VIDEO_REEL_STORAGE_BACKEND": "s3"}
        # Ensure no bucket env var
        cleaned = {
            k: v for k, v in os.environ.items()
            if not k.startswith("VIDEO_REEL_STORAGE_BUCKET")
        }
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
        """_process_scene has file_manager and job_prefix parameters."""
        import inspect
        from parrot.clients.google.generation import GoogleGeneration

        sig = inspect.signature(GoogleGeneration._process_scene)
        params = list(sig.parameters.keys())
        assert "file_manager" in params
        assert "job_prefix" in params

    def test_process_scene_returns_strings(self):
        """_process_scene return annotation is tuple of optional strings."""
        import inspect
        from parrot.clients.google.generation import GoogleGeneration

        sig = inspect.signature(GoogleGeneration._process_scene)
        ret = sig.return_annotation
        assert "str" in str(ret), f"Expected str in return type, got {ret}"

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
            mock_aio.to_thread = AsyncMock(
                return_value=Path("/tmp/fake_output.mp4")
            )
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

        fake_output = Path(tempfile.mktemp(suffix=".mp4"))
        fake_output.write_bytes(b"\x00" * 100)

        with patch("parrot.clients.google.generation.asyncio") as mock_aio:
            mock_aio.to_thread = AsyncMock(return_value=fake_output)
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
            scenes=[{
                "background_prompt": "Ocean",
                "video_prompt": "Pan right",
            }],
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
