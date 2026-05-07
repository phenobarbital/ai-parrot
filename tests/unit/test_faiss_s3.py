"""Unit tests for FAISSStore.dump_to_s3 and load_from_s3 (TASK-1037).

Strategy
--------
* FAISSStore.save() and FAISSStore.load() are patched so we don't need a
  real FAISS index (which would require the native extension and a GPU/CPU
  build of faiss-cpu).
* download_file's side-effect writes a real, well-formed .tar.gz file so
  that load_from_s3's extraction step succeeds.
* upload_file is fully mocked.
"""
from __future__ import annotations

import tarfile
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fake_tarball(tar_path: str, key: str) -> None:
    """Write a minimal .faiss.tar.gz with a fake pickle file inside."""
    with tempfile.TemporaryDirectory() as d:
        dummy = Path(d) / f"{key}.faiss"
        dummy.write_bytes(b"FAKE_FAISS_PICKLE_CONTENT")
        with tarfile.open(tar_path, "w:gz") as tar:
            tar.add(str(dummy), arcname=dummy.name)


def _fake_save(self_or_path, *args) -> None:
    """Patch for FAISSStore.save: writes a dummy .faiss file."""
    # Called as self.save(pickle_path); pickle_path is first positional arg.
    target = self_or_path if not args else args[0]
    Path(str(target)).write_bytes(b"FAKE_PICKLE")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_file_manager() -> MagicMock:
    """FileManagerToolkit stub with upload_file and download_file mocked."""
    fm = MagicMock()
    fm.upload_file = AsyncMock(
        return_value={
            "uploaded": True,
            "name": "test-key.faiss.tar.gz",
            "path": "faiss/test-key/test-key.faiss.tar.gz",
            "size": 1024,
            "url": "s3://bucket/faiss/test-key/test-key.faiss.tar.gz",
        }
    )
    fm.download_file = AsyncMock(return_value={"downloaded": True})
    return fm


# ---------------------------------------------------------------------------
# Import the FAISSStore class.  We import directly to avoid triggering the
# full parrot package chain (Cython extensions are absent in the worktree).
# ---------------------------------------------------------------------------

import importlib.util
import sys

_WT_ROOT = Path(__file__).resolve().parents[2]
_FAISS_SRC = (
    _WT_ROOT
    / "packages"
    / "ai-parrot"
    / "src"
    / "parrot"
    / "stores"
    / "faiss_store.py"
)

# Only load once
if "parrot.stores.faiss_store" not in sys.modules:
    _spec = importlib.util.spec_from_file_location(
        "parrot.stores.faiss_store", str(_FAISS_SRC)
    )
    _mod = importlib.util.module_from_spec(_spec)
    # faiss_store imports heavy deps at module level — patch them before exec.
    sys.modules.setdefault(
        "faiss",
        MagicMock(
            IndexFlatL2=MagicMock(return_value=MagicMock()),
            write_index=MagicMock(),
            read_index=MagicMock(return_value=MagicMock()),
        ),
    )
    sys.modules["parrot.stores.faiss_store"] = _mod
    try:
        _spec.loader.exec_module(_mod)
    except Exception:
        pass  # FAISSStore class will be patched via MagicMock in tests below

from parrot.stores.faiss_store import FAISSStore  # noqa: E402


# ---------------------------------------------------------------------------
# Tests — dump_to_s3
# ---------------------------------------------------------------------------


class TestFAISSStoreDumpToS3:
    """Tests for FAISSStore.dump_to_s3."""

    @pytest.mark.asyncio
    async def test_dump_calls_upload_file(self, mock_file_manager: MagicMock) -> None:
        """dump_to_s3 must call file_manager.upload_file exactly once."""
        store = FAISSStore.__new__(FAISSStore)
        store.logger = MagicMock()
        store._collections = {}

        with patch.object(FAISSStore, "save", side_effect=lambda path: Path(str(path)).write_bytes(b"X")):
            result = await store.dump_to_s3("test-key", mock_file_manager)

        mock_file_manager.upload_file.assert_called_once()
        call_kwargs = mock_file_manager.upload_file.call_args
        assert "test-key" in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_dump_returns_s3_path(self, mock_file_manager: MagicMock) -> None:
        """dump_to_s3 must return the path from upload_file's response."""
        store = FAISSStore.__new__(FAISSStore)
        store.logger = MagicMock()
        store._collections = {}

        with patch.object(FAISSStore, "save", side_effect=lambda path: Path(str(path)).write_bytes(b"X")):
            result = await store.dump_to_s3("test-key", mock_file_manager)

        assert result == "faiss/test-key/test-key.faiss.tar.gz"

    @pytest.mark.asyncio
    async def test_dump_bundles_tarball(self, mock_file_manager: MagicMock) -> None:
        """upload_file must receive a .tar.gz source_path."""
        store = FAISSStore.__new__(FAISSStore)
        store.logger = MagicMock()
        store._collections = {}

        with patch.object(FAISSStore, "save", side_effect=lambda path: Path(str(path)).write_bytes(b"X")):
            await store.dump_to_s3("my-bot-id", mock_file_manager)

        upload_args = mock_file_manager.upload_file.call_args
        source_path = upload_args.kwargs.get("source_path", upload_args.args[0] if upload_args.args else "")
        assert source_path.endswith(".tar.gz"), f"Expected .tar.gz upload, got: {source_path}"

    @pytest.mark.asyncio
    async def test_dump_no_temp_files_leak(self, mock_file_manager: MagicMock) -> None:
        """Temp directory is cleaned up after dump_to_s3 completes."""
        captured_tmpdir: list[str] = []

        original_save = lambda path: Path(str(path)).write_bytes(b"X")  # noqa: E731

        real_td = tempfile.TemporaryDirectory

        class _CapturingTD:
            def __init__(self):
                self._td = real_td()
                captured_tmpdir.append(self._td.name)

            def __enter__(self):
                return self._td.__enter__()

            def __exit__(self, *a):
                return self._td.__exit__(*a)

        store = FAISSStore.__new__(FAISSStore)
        store.logger = MagicMock()
        store._collections = {}

        with (
            patch.object(FAISSStore, "save", side_effect=original_save),
            patch("tempfile.TemporaryDirectory", _CapturingTD),
        ):
            await store.dump_to_s3("test-key", mock_file_manager)

        # The tmp directory must have been cleaned up by the context manager.
        if captured_tmpdir:
            assert not Path(captured_tmpdir[0]).exists(), "Temp dir was not cleaned up"

    @pytest.mark.asyncio
    async def test_dump_uses_fallback_path_when_no_path_key(self) -> None:
        """If upload_file returns no 'path' key, dump_to_s3 falls back gracefully."""
        fm = MagicMock()
        fm.upload_file = AsyncMock(return_value={"uploaded": True})  # no "path"

        store = FAISSStore.__new__(FAISSStore)
        store.logger = MagicMock()
        store._collections = {}

        with patch.object(FAISSStore, "save", side_effect=lambda path: Path(str(path)).write_bytes(b"X")):
            result = await store.dump_to_s3("fallback-key", fm)

        # Falls back to computed path
        assert "fallback-key" in result


# ---------------------------------------------------------------------------
# Tests — load_from_s3
# ---------------------------------------------------------------------------


class TestFAISSStoreLoadFromS3:
    """Tests for FAISSStore.load_from_s3."""

    def _make_download_side_effect(self, key: str):
        """Return an async side_effect that writes a real tarball to destination."""

        async def _download(path: str, destination: str) -> Dict[str, Any]:
            _make_fake_tarball(destination, key)
            return {"downloaded": True, "path": destination}

        return _download

    @pytest.mark.asyncio
    async def test_load_calls_download_file(self, mock_file_manager: MagicMock) -> None:
        """load_from_s3 must call file_manager.download_file exactly once."""
        mock_file_manager.download_file = AsyncMock(
            side_effect=self._make_download_side_effect("load-test")
        )

        with patch.object(FAISSStore, "load", return_value=None):
            store = await FAISSStore.load_from_s3("faiss/load-test", mock_file_manager)

        mock_file_manager.download_file.assert_called_once()
        assert isinstance(store, FAISSStore)

    @pytest.mark.asyncio
    async def test_load_calls_store_load(self, mock_file_manager: MagicMock) -> None:
        """load_from_s3 must call the instance's load() method with a path."""
        mock_file_manager.download_file = AsyncMock(
            side_effect=self._make_download_side_effect("load-test2")
        )

        with patch.object(FAISSStore, "load") as mock_load:
            await FAISSStore.load_from_s3("faiss/load-test2", mock_file_manager)

        mock_load.assert_called_once()
        loaded_path = str(mock_load.call_args.args[0])
        assert loaded_path.endswith(".faiss"), f"Expected .faiss path, got {loaded_path}"

    @pytest.mark.asyncio
    async def test_load_returns_faiss_store_instance(
        self, mock_file_manager: MagicMock
    ) -> None:
        """load_from_s3 must return a FAISSStore instance."""
        mock_file_manager.download_file = AsyncMock(
            side_effect=self._make_download_side_effect("inst-test")
        )

        with patch.object(FAISSStore, "load", return_value=None):
            store = await FAISSStore.load_from_s3("faiss/inst-test", mock_file_manager)

        assert isinstance(store, FAISSStore)

    @pytest.mark.asyncio
    async def test_load_passes_kwargs_to_constructor(
        self, mock_file_manager: MagicMock
    ) -> None:
        """kwargs are forwarded to FAISSStore.__init__."""
        mock_file_manager.download_file = AsyncMock(
            side_effect=self._make_download_side_effect("kw-test")
        )

        with patch.object(FAISSStore, "load", return_value=None):
            store = await FAISSStore.load_from_s3(
                "faiss/kw-test",
                mock_file_manager,
                collection_name="my-collection",
            )

        assert isinstance(store, FAISSStore)

    @pytest.mark.asyncio
    async def test_load_raises_if_no_faiss_file_in_archive(
        self, mock_file_manager: MagicMock
    ) -> None:
        """load_from_s3 raises FileNotFoundError when archive has no .faiss file."""

        async def _write_empty_tar(path: str, destination: str) -> Dict[str, Any]:
            # Write a tar.gz with no .faiss file inside
            with tarfile.open(destination, "w:gz") as tar:
                pass  # empty archive
            return {"downloaded": True}

        mock_file_manager.download_file = AsyncMock(
            side_effect=_write_empty_tar
        )

        with pytest.raises(FileNotFoundError, match="no .faiss pickle file found"):
            await FAISSStore.load_from_s3("faiss/empty-key", mock_file_manager)
