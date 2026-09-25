"""FEAT-603 TASK-3767 — opt-in live round trips against a real tenant (skipped unless PARROT_LIVE_GRAPH=1)."""

import hashlib
import io
import os
import uuid

import pytest

pytestmark = pytest.mark.live


def _need(*names: str) -> None:
    """Ensure all required environment variables are set for live testing.

    Args:
        *names: Environment variable names to check.

    Raises:
        pytest.skip: If PARROT_LIVE_GRAPH != 1 or any required knob is missing.
    """
    if os.environ.get("PARROT_LIVE_GRAPH") != "1":
        pytest.skip("set PARROT_LIVE_GRAPH=1 to run live Graph tests")
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        pytest.skip(f"missing live knob(s): {', '.join(missing)}")


@pytest.fixture
async def sp():
    """SharePoint FileManager fixture with automatic cleanup.

    Yields:
        SharePointFileManager: Authenticated manager for live testing.
    """
    _need("PARROT_LIVE_SHAREPOINT_SITE")
    from parrot.interfaces.file.sharepoint import SharePointFileManager

    m = SharePointFileManager(
        site=os.environ["PARROT_LIVE_SHAREPOINT_SITE"],
        library=os.environ.get("PARROT_LIVE_SHAREPOINT_LIBRARY", "Documents"),
        prefix=f"parrot-live/{uuid.uuid4().hex}/",
    )
    async with m:
        yield m
        # Clean up the run folder only (never delete outside the prefix)
        try:
            await m.remove_folder("")
        except Exception:
            pass


@pytest.fixture
async def od():
    """OneDrive FileManager fixture with automatic cleanup.

    Yields:
        OneDriveFileManager: Authenticated manager for live testing.
    """
    _need("PARROT_LIVE_ONEDRIVE_USER")
    from parrot.interfaces.file.onedrive import OneDriveFileManager

    m = OneDriveFileManager(
        user=os.environ["PARROT_LIVE_ONEDRIVE_USER"],
        prefix=f"parrot-live/{uuid.uuid4().hex}/",
    )
    async with m:
        yield m
        # Clean up the run folder only (never delete outside the prefix)
        try:
            await m.remove_folder("")
        except Exception:
            pass


async def test_live_sharepoint_roundtrip(sp):
    """Test full SharePoint operation sequence: create/exists/metadata/list/find/url/download/copy/rename/delete.

    This test exercises the complete manager API on a real SharePoint tenant.
    """
    # Create a test file
    test_path = "test_roundtrip.txt"
    test_content = b"Test content for SharePoint roundtrip"

    assert await sp.create_file(test_path, test_content)

    # Test exists
    assert await sp.exists(test_path)

    # Test get_file_metadata
    metadata = await sp.get_file_metadata(test_path)
    assert metadata.name == test_path
    assert metadata.size == len(test_content)

    # Test list_files
    files = await sp.list_files()
    assert any(f.name == test_path for f in files)

    # Test find_files by pattern
    found = await sp.find_files(pattern="test_*.txt")
    assert any(f.name == test_path for f in found)

    # Test get_file_url (must be https)
    url = await sp.get_file_url(test_path)
    assert url.startswith("https://")

    # Test download_file
    downloaded = io.BytesIO()
    await sp.download_file(test_path, downloaded)
    assert downloaded.getvalue() == test_content

    # Test copy_file
    copy_path = "test_roundtrip_copy.txt"
    copied_metadata = await sp.copy_file(test_path, copy_path)
    assert copied_metadata.name == copy_path
    assert await sp.exists(copy_path)

    # Test rename_file
    renamed_path = "test_roundtrip_renamed.txt"
    await sp.rename_file(copy_path, renamed_path)
    assert await sp.exists(renamed_path)
    assert not await sp.exists(copy_path)

    # Test delete_file
    assert await sp.delete_file(test_path)
    assert not await sp.exists(test_path)

    assert await sp.delete_file(renamed_path)
    assert not await sp.exists(renamed_path)


async def test_live_onedrive_user_roundtrip(od):
    """Test full OneDrive (app-only, user-targeted) operation sequence.

    This test exercises the complete manager API on a real OneDrive drive.
    """
    # Create a test file
    test_path = "test_onedrive_roundtrip.txt"
    test_content = b"Test content for OneDrive roundtrip"

    assert await od.create_file(test_path, test_content)

    # Test exists
    assert await od.exists(test_path)

    # Test get_file_metadata
    metadata = await od.get_file_metadata(test_path)
    assert metadata.name == test_path
    assert metadata.size == len(test_content)

    # Test list_files
    files = await od.list_files()
    assert any(f.name == test_path for f in files)

    # Test find_files by pattern
    found = await od.find_files(pattern="test_onedrive_*.txt")
    assert any(f.name == test_path for f in found)

    # Test get_file_url (must be https)
    url = await od.get_file_url(test_path)
    assert url.startswith("https://")

    # Test download_file
    downloaded = io.BytesIO()
    await od.download_file(test_path, downloaded)
    assert downloaded.getvalue() == test_content

    # Test copy_file
    copy_path = "test_onedrive_roundtrip_copy.txt"
    copied_metadata = await od.copy_file(test_path, copy_path)
    assert copied_metadata.name == copy_path
    assert await od.exists(copy_path)

    # Test rename_file
    renamed_path = "test_onedrive_roundtrip_renamed.txt"
    await od.rename_file(copy_path, renamed_path)
    assert await od.exists(renamed_path)
    assert not await od.exists(copy_path)

    # Test delete_file
    assert await od.delete_file(test_path)
    assert not await od.exists(test_path)

    assert await od.delete_file(renamed_path)
    assert not await od.exists(renamed_path)


async def test_live_batch_upload_download(sp):
    """Test batch upload and download with concurrency control and state verification.

    Uploads 12 small files concurrently (max_concurrency=3), verifies all succeeded
    with state='succeeded', then downloads them and verifies order preservation and
    content equality.
    """
    # Create 12 small test files
    test_files = []
    for i in range(12):
        name = f"batch_test_{i:02d}.txt"
        content = f"Batch test file {i}".encode()
        test_files.append((io.BytesIO(content), name))

    # Set max_concurrency on the manager
    sp.max_concurrency = 3

    # Test batch upload
    results = await sp.upload_files(test_files)

    # Verify all uploads succeeded
    assert len(results) == 12
    for result in results:
        assert result.state == "succeeded", f"Upload failed for {result.name}: {result.error}"

    # Verify order preservation
    for i, result in enumerate(results):
        assert result.name == f"batch_test_{i:02d}.txt", f"Order not preserved at index {i}"

    # Test batch download
    download_items = [(f"batch_test_{i:02d}.txt", io.BytesIO()) for i in range(12)]
    download_results = await sp.download_files(download_items)

    # Verify all downloads succeeded
    assert len(download_results) == 12
    for result in download_results:
        assert result.state == "succeeded", f"Download failed for {result.name}: {result.error}"

    # Verify order preservation and content equality
    for i, result in enumerate(download_results):
        assert result.name == f"batch_test_{i:02d}.txt", f"Order not preserved at download index {i}"
        # Verify content by re-downloading and comparing
        downloaded = io.BytesIO()
        await sp.download_file(f"batch_test_{i:02d}.txt", downloaded)
        expected = f"Batch test file {i}".encode()
        assert downloaded.getvalue() == expected, f"Content mismatch for batch_test_{i:02d}.txt"

    # Clean up
    for i in range(12):
        try:
            await sp.delete_file(f"batch_test_{i:02d}.txt")
        except Exception:
            pass


async def test_live_large_upload_session(sp):
    """Test large file upload using the session API and round-trip equality.

    Uploads a 12 MiB file, downloads it, and verifies SHA-256 equality to ensure
    the upload session path correctly handles large files.
    """
    # Create 12 MiB of random bytes
    file_size = 12 * 1024 * 1024  # 12 MiB
    file_data = os.urandom(file_size)

    # Compute SHA-256 of original
    original_sha256 = hashlib.sha256(file_data).hexdigest()

    # Upload the file
    test_path = "test_large_upload.bin"
    await sp.upload_file(io.BytesIO(file_data), test_path)

    # Verify file exists
    assert await sp.exists(test_path)

    # Download the file
    downloaded = io.BytesIO()
    await sp.download_file(test_path, downloaded)

    # Compute SHA-256 of downloaded
    downloaded_sha256 = hashlib.sha256(downloaded.getvalue()).hexdigest()

    # Verify equality
    assert original_sha256 == downloaded_sha256, "SHA-256 mismatch: file corrupted during round trip"

    # Clean up
    await sp.delete_file(test_path)
    assert not await sp.exists(test_path)
