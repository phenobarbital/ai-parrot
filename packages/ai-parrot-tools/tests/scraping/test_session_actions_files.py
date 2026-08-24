"""Tests for session_actions — file upload & download actions (Module 1,
part 3/3).

FEAT-453 TASK-2386.
"""

from unittest.mock import AsyncMock

import pytest
from parrot_tools.scraping.models import UploadFile, WaitForDownload
from parrot_tools.scraping.session_actions import (
    exec_upload_file,
    exec_wait_for_download,
)


@pytest.fixture
def mock_driver():
    driver = AsyncMock()
    driver.fill = AsyncMock(return_value=None)
    driver.click = AsyncMock(return_value=None)
    driver.wait_for_selector = AsyncMock(return_value=None)
    return driver


class TestUpload:
    async def test_single_file(self, mock_driver, tmp_path):
        f = tmp_path / "receipt.pdf"
        f.write_bytes(b"%PDF-")
        assert await exec_upload_file(mock_driver, UploadFile(selector="#f", file_path=str(f))) is True
        mock_driver.fill.assert_awaited_once_with("#f", str(f.resolve()))

    async def test_missing_file_fails_before_driver(self, mock_driver):
        action = UploadFile(selector="#f", file_path="/nope/missing.pdf")
        assert await exec_upload_file(mock_driver, action) is False
        mock_driver.click.assert_not_awaited()
        mock_driver.fill.assert_not_awaited()

    async def test_multiple_files(self, mock_driver, tmp_path):
        f1 = tmp_path / "a.pdf"
        f1.write_bytes(b"%PDF-")
        f2 = tmp_path / "b.pdf"
        f2.write_bytes(b"%PDF-")
        action = UploadFile(selector="#f", file_path=str(f1), multiple_files=True, file_paths=[str(f1), str(f2)])
        assert await exec_upload_file(mock_driver, action) is True
        args, _kwargs = mock_driver.fill.call_args
        assert str(f1.resolve()) in args[1]
        assert str(f2.resolve()) in args[1]

    async def test_wait_after_upload_selector(self, mock_driver, tmp_path):
        f = tmp_path / "receipt.pdf"
        f.write_bytes(b"%PDF-")
        action = UploadFile(selector="#f", file_path=str(f), wait_after_upload="#done", wait_timeout=5)
        assert await exec_upload_file(mock_driver, action) is True
        mock_driver.wait_for_selector.assert_awaited_once_with("#done", timeout=5)

    async def test_wait_after_upload_missing_still_succeeds(self, mock_driver, tmp_path):
        f = tmp_path / "receipt.pdf"
        f.write_bytes(b"%PDF-")
        mock_driver.wait_for_selector = AsyncMock(side_effect=RuntimeError("not found"))
        action = UploadFile(selector="#f", file_path=str(f), wait_after_upload="#done")
        assert await exec_upload_file(mock_driver, action) is True

    async def test_driver_failure_returns_false(self, mock_driver, tmp_path):
        f = tmp_path / "receipt.pdf"
        f.write_bytes(b"%PDF-")
        mock_driver.fill = AsyncMock(side_effect=RuntimeError("no such element"))
        assert await exec_upload_file(mock_driver, UploadFile(selector="#f", file_path=str(f))) is False

    async def test_path_escaping_root_is_rejected(self, mock_driver, tmp_path, monkeypatch):
        root = tmp_path / "sandbox"
        root.mkdir()
        outside = tmp_path / "outside.pdf"
        outside.write_bytes(b"%PDF-")
        monkeypatch.setenv("PARROT_SCRAPING_FILES_ROOT", str(root))
        action = UploadFile(selector="#f", file_path=str(outside))
        assert await exec_upload_file(mock_driver, action) is False
        mock_driver.fill.assert_not_awaited()

    async def test_path_inside_root_is_accepted(self, mock_driver, tmp_path, monkeypatch):
        root = tmp_path / "sandbox"
        root.mkdir()
        inside = root / "receipt.pdf"
        inside.write_bytes(b"%PDF-")
        monkeypatch.setenv("PARROT_SCRAPING_FILES_ROOT", str(root))
        action = UploadFile(selector="#f", file_path=str(inside))
        assert await exec_upload_file(mock_driver, action) is True


class TestDownload:
    async def test_pattern_and_move_to(self, mock_driver, tmp_path):
        dl = tmp_path / "dl"
        dl.mkdir()
        dest = tmp_path / "kept"
        dest.mkdir()
        (dl / "factura-001.pdf").write_bytes(b"%PDF-")
        action = WaitForDownload(filename_pattern="*.pdf", download_path=str(dl), move_to=str(dest), timeout=2)
        assert await exec_wait_for_download(mock_driver, action) is True
        assert (dest / "factura-001.pdf").exists()

    async def test_timeout_returns_false(self, mock_driver, tmp_path):
        action = WaitForDownload(download_path=str(tmp_path), timeout=1)
        assert await exec_wait_for_download(mock_driver, action) is False

    async def test_ignores_incomplete_download_suffixes(self, mock_driver, tmp_path):
        dl = tmp_path / "dl"
        dl.mkdir()
        (dl / "report.crdownload").write_bytes(b"partial")
        action = WaitForDownload(download_path=str(dl), timeout=1)
        assert await exec_wait_for_download(mock_driver, action) is False

    async def test_delete_after(self, mock_driver, tmp_path):
        dl = tmp_path / "dl"
        dl.mkdir()
        target = dl / "report.pdf"
        target.write_bytes(b"%PDF-")
        action = WaitForDownload(download_path=str(dl), timeout=2, delete_after=True)
        assert await exec_wait_for_download(mock_driver, action) is True
        assert not target.exists()

    async def test_path_escaping_root_is_rejected(self, mock_driver, tmp_path, monkeypatch):
        root = tmp_path / "sandbox"
        root.mkdir()
        outside = tmp_path / "outside_dl"
        outside.mkdir()
        monkeypatch.setenv("PARROT_SCRAPING_FILES_ROOT", str(root))
        action = WaitForDownload(download_path=str(outside), timeout=1)
        assert await exec_wait_for_download(mock_driver, action) is False
