"""Unit tests for S3OverflowManager (TASK-719).

All tests use mocked S3FileManager to avoid requiring real S3.
"""

import io
import json
import pytest
from unittest.mock import AsyncMock

from parrot.storage.s3_overflow import S3OverflowManager


@pytest.fixture
def mock_s3():
    """Mocked S3FileManager."""
    s3 = AsyncMock()
    s3.create_from_bytes = AsyncMock(return_value=None)
    s3.download_file = AsyncMock(return_value=None)
    s3.delete_file = AsyncMock(return_value=True)
    return s3


@pytest.fixture
def overflow(mock_s3):
    """S3OverflowManager with mocked S3."""
    return S3OverflowManager(s3_file_manager=mock_s3)


class TestMaybeOffload:
    """Tests for maybe_offload method."""

    @pytest.mark.asyncio
    async def test_small_data_stays_inline(self, overflow, mock_s3):
        small_data = {"key": "value"}
        definition, ref = await overflow.maybe_offload(small_data, "prefix/art-1")
        assert definition == small_data
        assert ref is None
        mock_s3.create_from_bytes.assert_not_called()

    @pytest.mark.asyncio
    async def test_large_data_offloaded(self, overflow, mock_s3):
        # Create data > 200KB
        large_data = {"data": "x" * (250 * 1024)}
        definition, ref = await overflow.maybe_offload(large_data, "prefix/art-1")
        assert definition is None
        assert ref is not None
        assert ref == "prefix/art-1.json"
        mock_s3.create_from_bytes.assert_called_once()

        # Verify the upload call
        call_args = mock_s3.create_from_bytes.call_args
        uploaded_bytes = call_args.args[0] if call_args.args else call_args.kwargs.get("data")
        assert isinstance(uploaded_bytes, bytes)
        assert len(uploaded_bytes) >= 250 * 1024

    @pytest.mark.asyncio
    async def test_exactly_at_threshold_stays_inline(self, overflow, mock_s3):
        """Data exactly at threshold (200KB - 1 byte of overhead) stays inline."""
        # Need to create data that serializes to just under 200KB
        # The JSON overhead means we need slightly less data
        target_size = 200 * 1024 - 100  # safely under
        small_data = {"d": "a" * target_size}
        json_size = len(json.dumps(small_data).encode("utf-8"))
        assert json_size < 200 * 1024, f"Test data too large: {json_size}"

        definition, ref = await overflow.maybe_offload(small_data, "prefix/art-1")
        assert definition == small_data
        assert ref is None

    @pytest.mark.asyncio
    async def test_s3_failure_returns_inline_fallback(self, overflow, mock_s3):
        """If S3 upload fails, fall back to returning inline data."""
        mock_s3.create_from_bytes.side_effect = Exception("S3 unavailable")
        large_data = {"data": "x" * (250 * 1024)}
        definition, ref = await overflow.maybe_offload(large_data, "prefix/art-1")
        # Should fallback to inline
        assert definition == large_data
        assert ref is None

    @pytest.mark.asyncio
    async def test_s3_key_includes_json_extension(self, overflow, mock_s3):
        large_data = {"data": "x" * (250 * 1024)}
        _, ref = await overflow.maybe_offload(large_data, "artifacts/user/session/chart-x1")
        assert ref == "artifacts/user/session/chart-x1.json"


class TestResolve:
    """Tests for resolve method."""

    @pytest.mark.asyncio
    async def test_inline_definition_returned_as_is(self, overflow):
        data = {"key": "value"}
        result = await overflow.resolve(definition=data, definition_ref=None)
        assert result == data

    @pytest.mark.asyncio
    async def test_inline_takes_precedence_over_ref(self, overflow):
        """If both definition and ref are provided, inline wins."""
        data = {"key": "value"}
        result = await overflow.resolve(definition=data, definition_ref="some/key.json")
        assert result == data

    @pytest.mark.asyncio
    async def test_s3_ref_downloads_and_parses(self, overflow, mock_s3):
        s3_data = {"engine": "echarts", "spec": {"xAxis": {}}}
        json_bytes = json.dumps(s3_data).encode("utf-8")

        # Mock download_file to write bytes into the BytesIO
        async def mock_download(path, buf):
            buf.write(json_bytes)
            return None

        mock_s3.download_file.side_effect = mock_download

        result = await overflow.resolve(definition=None, definition_ref="artifacts/chart.json")
        assert result == s3_data
        from unittest.mock import ANY
        mock_s3.download_file.assert_called_once_with("artifacts/chart.json", ANY)

    @pytest.mark.asyncio
    async def test_s3_not_found_returns_none(self, overflow, mock_s3):
        mock_s3.download_file.side_effect = FileNotFoundError("Not found")
        result = await overflow.resolve(definition=None, definition_ref="missing/key.json")
        assert result is None

    @pytest.mark.asyncio
    async def test_s3_error_returns_none(self, overflow, mock_s3):
        mock_s3.download_file.side_effect = Exception("Connection error")
        result = await overflow.resolve(definition=None, definition_ref="bad/key.json")
        assert result is None

    @pytest.mark.asyncio
    async def test_both_none_returns_none(self, overflow):
        result = await overflow.resolve(definition=None, definition_ref=None)
        assert result is None


class TestDelete:
    """Tests for delete method."""

    @pytest.mark.asyncio
    async def test_calls_s3_delete(self, overflow, mock_s3):
        await overflow.delete("artifacts/chart.json")
        mock_s3.delete_file.assert_called_once_with("artifacts/chart.json")

    @pytest.mark.asyncio
    async def test_none_ref_is_noop(self, overflow, mock_s3):
        await overflow.delete(None)
        mock_s3.delete_file.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_ref_is_noop(self, overflow, mock_s3):
        await overflow.delete("")
        mock_s3.delete_file.assert_not_called()

    @pytest.mark.asyncio
    async def test_s3_error_does_not_raise(self, overflow, mock_s3):
        mock_s3.delete_file.side_effect = Exception("S3 error")
        # Should not raise
        await overflow.delete("artifacts/chart.json")


class TestThreshold:
    """Tests for threshold configuration."""

    def test_default_threshold(self):
        assert S3OverflowManager.INLINE_THRESHOLD == 200 * 1024
