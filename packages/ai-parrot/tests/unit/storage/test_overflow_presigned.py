"""Unit tests for OverflowStore.generate_presigned_url (FEAT-197, TASK-1321)."""
from __future__ import annotations

import sys
import pytest
from unittest.mock import AsyncMock, MagicMock


# Force real storage modules (bypass conftest stubs).
for _mod in ("parrot.storage.overflow",):
    sys.modules.pop(_mod, None)

import parrot.storage.overflow as _real_overflow
sys.modules["parrot.storage.overflow"] = _real_overflow

from parrot.storage.overflow import OverflowStore  # noqa: E402


@pytest.fixture
def overflow_store_with_mock_fm():
    """OverflowStore backed by a mock FileManagerInterface."""
    fm = MagicMock()
    fm.get_file_url = AsyncMock(return_value="https://s3.amazonaws.com/bucket/key?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=abc&X-Amz-Expires=604800")
    store = OverflowStore(file_manager=fm)
    return store, fm


@pytest.mark.asyncio
async def test_generate_presigned_url_returns_url(overflow_store_with_mock_fm):
    """Should return the URL from the file manager."""
    store, fm = overflow_store_with_mock_fm
    url = await store.generate_presigned_url("my/key.json")
    assert url.startswith("https://")
    fm.get_file_url.assert_called_once()


@pytest.mark.asyncio
async def test_generate_presigned_url_clamps_expiry(overflow_store_with_mock_fm):
    """Expiry over 604800 should be clamped to 604800."""
    store, fm = overflow_store_with_mock_fm
    await store.generate_presigned_url("my/key.json", expires_in=10_000_000)
    _, kwargs = fm.get_file_url.call_args
    assert kwargs["expiry"] == 604_800


@pytest.mark.asyncio
async def test_generate_presigned_url_honours_short_expiry(overflow_store_with_mock_fm):
    """Expiry under 604800 should be passed through unchanged."""
    store, fm = overflow_store_with_mock_fm
    await store.generate_presigned_url("my/key.json", expires_in=3600)
    _, kwargs = fm.get_file_url.call_args
    assert kwargs["expiry"] == 3600


@pytest.mark.asyncio
async def test_generate_presigned_url_uses_correct_key(overflow_store_with_mock_fm):
    """The key passed to the file manager should match the requested key."""
    store, fm = overflow_store_with_mock_fm
    await store.generate_presigned_url("artifacts/user/key.json")
    args, _ = fm.get_file_url.call_args
    assert args[0] == "artifacts/user/key.json"
