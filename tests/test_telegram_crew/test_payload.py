"""Unit tests for DataPayload."""
import os

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.integrations.telegram.crew.payload import DataPayload, TELEGRAM_CAPTION_LIMIT


@pytest.fixture
def payload(tmp_path):
    return DataPayload(
        temp_dir=str(tmp_path),
        max_file_size_mb=50,
        allowed_mime_types=["text/csv", "application/json", "image/png"],
    )


@pytest.fixture
def mock_bot():
    bot = AsyncMock()
    bot.get_file = AsyncMock(return_value=MagicMock(file_path="documents/file123.csv"))
    bot.download_file = AsyncMock()
    bot.send_document = AsyncMock(return_value=MagicMock(message_id=42))
    bot.send_message = AsyncMock()
    return bot


def _make_document_message(
    file_id="file123",
    file_name="data.csv",
    mime_type="text/csv",
    file_size=1024,
):
    message = MagicMock()
    message.document.file_id = file_id
    message.document.file_name = file_name
    message.document.mime_type = mime_type
    message.document.file_size = file_size
    return message


class TestDataPayload:
    def test_mime_validation_allowed(self, payload):
        assert payload.validate_mime("text/csv") is True
        assert payload.validate_mime("application/json") is True
        assert payload.validate_mime("image/png") is True

    def test_mime_validation_rejected(self, payload):
        assert payload.validate_mime("application/x-executable") is False
        assert payload.validate_mime("text/html") is False
        assert payload.validate_mime("") is False

    def test_file_size_validation(self, payload):
        assert payload._validate_file_size(1024) is True  # 1 KB
        assert payload._validate_file_size(50 * 1024 * 1024) is True  # exactly 50 MB
        assert payload._validate_file_size(51 * 1024 * 1024) is False  # 51 MB

    def test_temp_dir_created(self, tmp_path):
        new_dir = str(tmp_path / "new_subdir")
        DataPayload(temp_dir=new_dir)
        assert os.path.isdir(new_dir)

    @pytest.mark.asyncio
    async def test_download_document(self, payload, mock_bot):
        message = _make_document_message()
        path = await payload.download_document(mock_bot, message)
        assert path is not None
        assert "data.csv" in path
        mock_bot.get_file.assert_called_once_with("file123")
        mock_bot.download_file.assert_called_once()

    @pytest.mark.asyncio
    async def test_download_document_rejected_mime(self, payload, mock_bot):
        message = _make_document_message(mime_type="application/x-executable")
        path = await payload.download_document(mock_bot, message)
        assert path is None
        mock_bot.get_file.assert_not_called()

    @pytest.mark.asyncio
    async def test_download_document_rejected_size(self, payload, mock_bot):
        message = _make_document_message(file_size=51 * 1024 * 1024)
        path = await payload.download_document(mock_bot, message)
        assert path is None
        mock_bot.get_file.assert_not_called()

    @pytest.mark.asyncio
    async def test_download_document_no_document(self, payload, mock_bot):
        message = MagicMock()
        message.document = None
        path = await payload.download_document(mock_bot, message)
        assert path is None

    @pytest.mark.asyncio
    async def test_send_document(self, payload, mock_bot, tmp_path):
        test_file = tmp_path / "test.csv"
        test_file.write_text("a,b\n1,2")
        await payload.send_document(
            mock_bot, chat_id=-100123, file_path=str(test_file), caption="Test data"
        )
        mock_bot.send_document.assert_called_once()
        call_kwargs = mock_bot.send_document.call_args
        assert call_kwargs.kwargs["chat_id"] == -100123
        assert call_kwargs.kwargs["caption"] == "Test data"

    @pytest.mark.asyncio
    async def test_send_document_with_reply(self, payload, mock_bot, tmp_path):
        test_file = tmp_path / "test.csv"
        test_file.write_text("a,b\n1,2")
        await payload.send_document(
            mock_bot,
            chat_id=-100123,
            file_path=str(test_file),
            caption="Reply data",
            reply_to_message_id=99,
        )
        call_kwargs = mock_bot.send_document.call_args
        assert call_kwargs.kwargs["reply_to_message_id"] == 99

    @pytest.mark.asyncio
    async def test_send_document_long_caption(self, payload, mock_bot, tmp_path):
        test_file = tmp_path / "test.csv"
        test_file.write_text("a,b\n1,2")
        long_caption = "x" * (TELEGRAM_CAPTION_LIMIT + 100)
        await payload.send_document(
            mock_bot, chat_id=-100123, file_path=str(test_file), caption=long_caption
        )
        # Document sent without caption, then caption as separate message
        mock_bot.send_document.assert_called_once()
        mock_bot.send_message.assert_called_once()
        msg_kwargs = mock_bot.send_message.call_args.kwargs
        assert msg_kwargs["text"] == long_caption

    @pytest.mark.asyncio
    async def test_send_csv(self, payload, mock_bot):
        import pandas as pd

        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        await payload.send_csv(
            mock_bot, chat_id=-100123, dataframe=df, filename="test.csv"
        )
        mock_bot.send_document.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_csv_cleanup(self, payload, mock_bot, tmp_path):
        import pandas as pd

        df = pd.DataFrame({"x": [1]})
        await payload.send_csv(
            mock_bot, chat_id=-100123, dataframe=df, filename="cleanup_test.csv"
        )
        # Temp CSV should be cleaned up
        csv_path = os.path.join(str(tmp_path), "cleanup_test.csv")
        assert not os.path.exists(csv_path)

    def test_cleanup_file(self, payload, tmp_path):
        f = tmp_path / "to_delete.txt"
        f.write_text("data")
        assert f.exists()
        payload.cleanup_file(str(f))
        assert not f.exists()

    def test_cleanup_file_nonexistent(self, payload):
        # Should not raise
        payload.cleanup_file("/nonexistent/path")

    def test_cleanup_all(self, payload, tmp_path):
        for i in range(3):
            (tmp_path / f"file_{i}.txt").write_text("data")
        assert len(os.listdir(str(tmp_path))) == 3
        payload.cleanup_all()
        assert len(os.listdir(str(tmp_path))) == 0

    def test_default_mime_types(self):
        p = DataPayload(temp_dir="/tmp/test_default")
        assert "text/csv" in p.allowed_mime_types
        assert "application/json" in p.allowed_mime_types
        assert len(p.allowed_mime_types) == 7
