"""Unit tests for parrot.storage.overflow.OverflowStore.

TASK-823: OverflowStore Generalization — FEAT-116.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.interfaces.file.abstract import FileManagerInterface
from parrot.storage.overflow import OverflowStore


@pytest.fixture
def mock_fm():
    fm = MagicMock(spec=FileManagerInterface)
    fm.create_from_bytes = AsyncMock(return_value=True)
    fm.download_file = AsyncMock(return_value=b"...")
    fm.delete_file = AsyncMock(return_value=True)
    return fm


@pytest.fixture
def store(mock_fm):
    return OverflowStore(file_manager=mock_fm)


async def test_inline_under_threshold(store, mock_fm):
    small = {"k": "v"}
    inline, ref = await store.maybe_offload(small, "prefix")
    assert inline == small
    assert ref is None
    mock_fm.create_from_bytes.assert_not_called()


async def test_offload_over_threshold(store, mock_fm):
    big = {"data": "x" * (OverflowStore.INLINE_THRESHOLD + 1)}
    inline, ref = await store.maybe_offload(big, "artifacts/test")
    assert inline is None
    assert ref is not None
    mock_fm.create_from_bytes.assert_awaited_once()


async def test_delete_calls_fm(store, mock_fm):
    ok = await store.delete("artifacts/test.json")
    assert ok is True
    mock_fm.delete_file.assert_awaited_once_with("artifacts/test.json")


async def test_delete_none_returns_false(store, mock_fm):
    ok = await store.delete(None)
    assert ok is False
    mock_fm.delete_file.assert_not_called()


async def test_resolve_returns_inline_when_present(store, mock_fm):
    inline = {"k": "v"}
    result = await store.resolve(inline, None)
    assert result == inline
    mock_fm.download_file.assert_not_called()


async def test_resolve_none_inline_and_no_ref(store, mock_fm):
    result = await store.resolve(None, None)
    assert result is None
    mock_fm.download_file.assert_not_called()


async def test_s3_overflow_manager_back_compat():
    from parrot.storage.s3_overflow import S3OverflowManager
    from parrot.interfaces.file.s3 import S3FileManager
    mock_s3 = MagicMock(spec=S3FileManager)
    mgr = S3OverflowManager(mock_s3)
    assert isinstance(mgr, OverflowStore)
    assert mgr._fm is mock_s3


async def test_inline_threshold_value():
    assert OverflowStore.INLINE_THRESHOLD == 200 * 1024


async def test_offload_fallback_on_upload_error(mock_fm):
    """When upload fails, data is returned inline as fallback."""
    mock_fm.create_from_bytes = AsyncMock(side_effect=Exception("upload failed"))
    store = OverflowStore(file_manager=mock_fm)
    big = {"data": "x" * (OverflowStore.INLINE_THRESHOLD + 1)}
    inline, ref = await store.maybe_offload(big, "artifacts/test")
    # Fallback: inline returned, no ref
    assert inline is not None
    assert ref is None
