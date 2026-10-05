"""FEAT-608 TASK-3818 — opt-in live Google Drive round trips (PARROT_LIVE_GDRIVE=1)."""

import io
import os
import sys
import uuid

import pytest

sys.modules.pop("parrot.interfaces.file", None)

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.getenv("PARROT_LIVE_GDRIVE") != "1", reason="set PARROT_LIVE_GDRIVE=1 to run"),
]

ROOT_ID = os.getenv("PARROT_LIVE_GDRIVE_ROOT_ID")
ROOT_PATH = os.getenv("PARROT_LIVE_GDRIVE_ROOT_PATH")
SHARED_DRIVE = os.getenv("PARROT_LIVE_GDRIVE_SHARED_DRIVE")
SHARE_EMAIL = os.getenv("PARROT_LIVE_GDRIVE_SHARE_EMAIL")


def _manager(**kwargs):
    from parrot.interfaces.file.gdrive import GoogleDriveFileManager

    if not (ROOT_ID or ROOT_PATH):
        pytest.skip("PARROT_LIVE_GDRIVE_ROOT_ID or PARROT_LIVE_GDRIVE_ROOT_PATH is required")
    base = dict(root_id=ROOT_ID) if ROOT_ID else dict(root_path=ROOT_PATH)
    return GoogleDriveFileManager(**base, prefix=f"parrot-live/{uuid.uuid4().hex}/", permanent_delete=True, **kwargs)


async def test_live_roundtrip():
    """Test full Google Drive operation sequence: upload bytes → exists → metadata → list → find → get_file_url → download to BytesIO → copy → rename → delete; cleanup in finally."""
    manager = _manager()
    try:
        async with manager:
            # Create a test file
            test_path = "test_roundtrip.txt"
            test_content = b"Test content for Google Drive roundtrip"

            # Upload file from bytes
            await manager.upload_file_from_bytes(test_content, test_path)

            # Test exists
            assert await manager.exists(test_path)

            # Test get_file_metadata
            metadata = await manager.get_file_metadata(test_path)
            assert metadata.name == test_path
            assert metadata.size == len(test_content)

            # Test list_files
            files = await manager.list_files()
            assert any(f.name == test_path for f in files)

            # Test find_files by pattern
            found = await manager.find_files(pattern="test_*.txt")
            assert any(f.name == test_path for f in found)

            # Test get_file_url (must be https)
            url = await manager.get_file_url(test_path)
            assert url.startswith("https://")

            # Test download_file
            downloaded = io.BytesIO()
            await manager.download_file(test_path, downloaded)
            assert downloaded.getvalue() == test_content

            # Test copy_file
            copy_path = "test_roundtrip_copy.txt"
            copied_metadata = await manager.copy_file(test_path, copy_path)
            assert copied_metadata.name == copy_path
            assert await manager.exists(copy_path)

            # Test rename_file
            renamed_path = "test_roundtrip_renamed.txt"
            await manager.rename_file(copy_path, renamed_path)
            assert await manager.exists(renamed_path)
            assert not await manager.exists(copy_path)

            # Test delete_file
            assert await manager.delete_file(test_path)
            assert not await manager.exists(test_path)

            assert await manager.delete_file(renamed_path)
            assert not await manager.exists(renamed_path)
    finally:
        # Clean up the run folder
        try:
            await manager.remove_folder("")
        except Exception:
            pass


async def test_live_shared_drive_roundtrip():
    """Test full Google Drive operation sequence on a shared drive."""
    if not SHARED_DRIVE:
        pytest.skip("PARROT_LIVE_GDRIVE_SHARED_DRIVE is required for shared drive tests")

    manager = _manager(shared_drive_id=SHARED_DRIVE)
    try:
        async with manager:
            # Create a test file
            test_path = "test_shared_drive_roundtrip.txt"
            test_content = b"Test content for shared drive roundtrip"

            # Upload file from bytes
            await manager.upload_file_from_bytes(test_content, test_path)

            # Test exists
            assert await manager.exists(test_path)

            # Test get_file_metadata
            metadata = await manager.get_file_metadata(test_path)
            assert metadata.name == test_path
            assert metadata.size == len(test_content)

            # Test list_files
            files = await manager.list_files()
            assert any(f.name == test_path for f in files)

            # Test find_files by pattern
            found = await manager.find_files(pattern="test_shared_drive_*.txt")
            assert any(f.name == test_path for f in found)

            # Test get_file_url (must be https)
            url = await manager.get_file_url(test_path)
            assert url.startswith("https://")

            # Test download_file
            downloaded = io.BytesIO()
            await manager.download_file(test_path, downloaded)
            assert downloaded.getvalue() == test_content

            # Test copy_file
            copy_path = "test_shared_drive_roundtrip_copy.txt"
            copied_metadata = await manager.copy_file(test_path, copy_path)
            assert copied_metadata.name == copy_path
            assert await manager.exists(copy_path)

            # Test rename_file
            renamed_path = "test_shared_drive_roundtrip_renamed.txt"
            await manager.rename_file(copy_path, renamed_path)
            assert await manager.exists(renamed_path)
            assert not await manager.exists(copy_path)

            # Test delete_file
            assert await manager.delete_file(test_path)
            assert not await manager.exists(test_path)

            assert await manager.delete_file(renamed_path)
            assert not await manager.exists(renamed_path)
    finally:
        # Clean up the run folder
        try:
            await manager.remove_folder("")
        except Exception:
            pass


async def test_live_batch_upload_download():
    """Test batch upload and download with concurrency control and state verification.

    Uploads 12 small files concurrently (max_concurrency=3), verifies all succeeded
    with state='succeeded', then downloads them and verifies order preservation and
    content equality.
    """
    manager = _manager(max_concurrency=3)
    try:
        async with manager:
            # Create 12 small test files
            test_files = []
            for i in range(12):
                name = f"batch_test_{i:02d}.txt"
                content = f"Batch test file {i}".encode()
                test_files.append((io.BytesIO(content), name))

            # Test batch upload
            results = await manager.upload_files(test_files)

            # Verify all uploads succeeded
            assert len(results) == 12
            for result in results:
                assert result.state == "succeeded", f"Upload failed for {result.name}: {result.error}"

            # Verify order preservation
            for i, result in enumerate(results):
                assert result.name == f"batch_test_{i:02d}.txt", f"Order not preserved at index {i}"

            # Test batch download
            download_items = [(f"batch_test_{i:02d}.txt", io.BytesIO()) for i in range(12)]
            download_results = await manager.download_files(download_items)

            # Verify all downloads succeeded
            assert len(download_results) == 12
            for result in download_results:
                assert result.state == "succeeded", f"Download failed for {result.name}: {result.error}"

            # Verify order preservation and content equality
            for i, result in enumerate(download_results):
                assert result.name == f"batch_test_{i:02d}.txt", f"Order not preserved at download index {i}"
                # Verify content by re-downloading and comparing
                downloaded = io.BytesIO()
                await manager.download_file(f"batch_test_{i:02d}.txt", downloaded)
                expected = f"Batch test file {i}".encode()
                assert downloaded.getvalue() == expected, f"Content mismatch for batch_test_{i:02d}.txt"

            # Clean up
            for i in range(12):
                try:
                    await manager.delete_file(f"batch_test_{i:02d}.txt")
                except Exception:
                    pass
    finally:
        # Clean up the run folder
        try:
            await manager.remove_folder("")
        except Exception:
            pass


async def test_live_large_resumable_upload():
    """Test large file upload using the resumable API and round-trip equality.

    Uploads a 12 MiB file, downloads it, and verifies SHA-256 equality to ensure
    the resumable upload path correctly handles large files.
    """
    import hashlib

    manager = _manager()
    try:
        async with manager:
            # Create 12 MiB of random bytes
            file_size = 12 * 1024 * 1024  # 12 MiB
            file_data = os.urandom(file_size)

            # Compute SHA-256 of original
            original_sha256 = hashlib.sha256(file_data).hexdigest()

            # Upload the file
            test_path = "test_large_upload.bin"
            await manager.upload_file(io.BytesIO(file_data), test_path)

            # Verify file exists
            assert await manager.exists(test_path)

            # Download the file
            downloaded = io.BytesIO()
            await manager.download_file(test_path, downloaded)

            # Compute SHA-256 of downloaded
            downloaded_sha256 = hashlib.sha256(downloaded.getvalue()).hexdigest()

            # Verify equality
            assert original_sha256 == downloaded_sha256, "SHA-256 mismatch: file corrupted during round trip"

            # Clean up
            await manager.delete_file(test_path)
            assert not await manager.exists(test_path)
    finally:
        # Clean up the run folder
        try:
            await manager.remove_folder("")
        except Exception:
            pass


async def test_live_sharing_link_user_scope():
    """Test creating a sharing link with user scope and expiry.

    Creates a sharing link with user scope and 1-hour expiry, verifies the link
    is returned and is a valid URL.
    """
    if not SHARE_EMAIL:
        pytest.skip("PARROT_LIVE_GDRIVE_SHARE_EMAIL is required for sharing link tests")

    manager = _manager()
    try:
        async with manager:
            # Create a test file
            test_path = "test_sharing_link.txt"
            test_content = b"Test content for sharing link"

            # Upload file from bytes
            await manager.upload_file_from_bytes(test_content, test_path)

            # Test create_sharing_link with user scope and expiry
            url = await manager.create_sharing_link(
                test_path, scope="user", role="reader", email_address=SHARE_EMAIL, expiry=3600
            )

            # Verify the link is returned and is a valid URL
            assert url, "create_sharing_link should return a URL"
            assert url.startswith("https://"), "Sharing link should be a valid HTTPS URL"

            # Clean up
            await manager.delete_file(test_path)
            assert not await manager.exists(test_path)
    finally:
        # Clean up the run folder
        try:
            await manager.remove_folder("")
        except Exception:
            pass
