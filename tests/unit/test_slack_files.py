"""Unit tests for Slack file handling module.

Tests the download and upload functionality for Slack files,
including authentication, MIME type filtering, and error handling.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.integrations.slack.files import (
    download_slack_file,
    upload_file_to_slack,
    extract_files_from_event,
    is_processable_file,
    get_file_extension,
    PROCESSABLE_MIME_TYPES,
)


class TestExtractFilesFromEvent:
    """Tests for extract_files_from_event helper."""

    def test_extracts_files_array(self):
        """Extracts files from standard files array."""
        event = {
            "type": "message",
            "files": [
                {"id": "F123", "name": "doc.pdf"},
                {"id": "F456", "name": "image.png"},
            ],
        }
        files = extract_files_from_event(event)
        assert len(files) == 2
        assert files[0]["id"] == "F123"

    def test_extracts_file_share_event(self):
        """Extracts file from file_share subtype."""
        event = {
            "type": "message",
            "subtype": "file_share",
            "file": {"id": "F789", "name": "shared.pdf"},
        }
        files = extract_files_from_event(event)
        assert len(files) == 1
        assert files[0]["id"] == "F789"

    def test_returns_empty_for_no_files(self):
        """Returns empty list when no files present."""
        event = {"type": "message", "text": "Hello"}
        files = extract_files_from_event(event)
        assert files == []


class TestDownloadSlackFile:
    """Tests for download_slack_file function."""

    @pytest.fixture
    def mock_aiohttp_session(self):
        """Create a properly mocked aiohttp ClientSession."""
        def create_mock(status=200, content=b"file content"):
            # Create async iterator for content chunks
            class MockContent:
                def __init__(self, data):
                    self._data = data
                    self._returned = False

                async def iter_chunked(self, size):
                    if not self._returned:
                        self._returned = True
                        yield self._data

            mock_resp = MagicMock()
            mock_resp.status = status
            mock_resp.content = MockContent(content)

            # Create the response context manager
            resp_cm = MagicMock()
            resp_cm.__aenter__ = AsyncMock(return_value=mock_resp)
            resp_cm.__aexit__ = AsyncMock(return_value=None)

            # Create the session
            mock_session = MagicMock()
            mock_session.get = MagicMock(return_value=resp_cm)

            # Create the session context manager
            session_cm = MagicMock()
            session_cm.__aenter__ = AsyncMock(return_value=mock_session)
            session_cm.__aexit__ = AsyncMock(return_value=None)

            return session_cm, mock_session

        return create_mock

    @pytest.mark.asyncio
    async def test_downloads_supported_file(self, tmp_path, mock_aiohttp_session):
        """Downloads file with correct auth header."""
        file_info = {
            "url_private_download": "https://files.slack.com/file123",
            "mimetype": "application/pdf",
            "name": "document.pdf",
        }

        session_cm, mock_session = mock_aiohttp_session(
            status=200, content=b"PDF content here"
        )

        with patch(
            "parrot.integrations.slack.files.ClientSession",
            return_value=session_cm,
        ):
            result = await download_slack_file(
                file_info, "xoxb-test-token", str(tmp_path)
            )

            assert result is not None
            assert result.name == "document.pdf"
            assert result.exists()
            assert result.read_bytes() == b"PDF content here"

            # Verify auth header was used
            mock_session.get.assert_called_once()
            call_args = mock_session.get.call_args
            assert call_args[1]["headers"]["Authorization"] == "Bearer xoxb-test-token"

    @pytest.mark.asyncio
    async def test_skips_unsupported_mimetype(self):
        """Returns None for unsupported MIME types."""
        file_info = {
            "url_private_download": "https://files.slack.com/file123",
            "mimetype": "application/x-executable",
            "name": "program.exe",
        }

        result = await download_slack_file(file_info, "xoxb-token")
        assert result is None

    @pytest.mark.asyncio
    async def test_handles_download_error(self, mock_aiohttp_session):
        """Returns None on HTTP error."""
        file_info = {
            "url_private_download": "https://files.slack.com/file123",
            "mimetype": "application/pdf",
            "name": "doc.pdf",
        }

        session_cm, _ = mock_aiohttp_session(status=403)

        with patch(
            "parrot.integrations.slack.files.ClientSession",
            return_value=session_cm,
        ):
            result = await download_slack_file(file_info, "xoxb-token")
            assert result is None

    @pytest.mark.asyncio
    async def test_handles_missing_url(self):
        """Returns None when no download URL available."""
        file_info = {
            "mimetype": "application/pdf",
            "name": "doc.pdf",
            # No url_private_download or url_private
        }

        result = await download_slack_file(file_info, "xoxb-token")
        assert result is None

    @pytest.mark.asyncio
    async def test_uses_url_private_fallback(self, tmp_path, mock_aiohttp_session):
        """Falls back to url_private when url_private_download not available."""
        file_info = {
            "url_private": "https://files.slack.com/file123",
            "mimetype": "text/plain",
            "name": "readme.txt",
        }

        session_cm, mock_session = mock_aiohttp_session(
            status=200, content=b"text content"
        )

        with patch(
            "parrot.integrations.slack.files.ClientSession",
            return_value=session_cm,
        ):
            result = await download_slack_file(
                file_info, "xoxb-token", str(tmp_path)
            )

            assert result is not None
            mock_session.get.assert_called_once()
            call_args = mock_session.get.call_args
            assert call_args[0][0] == "https://files.slack.com/file123"

    @pytest.mark.asyncio
    async def test_custom_allowed_types(self, tmp_path, mock_aiohttp_session):
        """Respects custom allowed MIME types."""
        file_info = {
            "url_private_download": "https://files.slack.com/file123",
            "mimetype": "application/custom",
            "name": "custom.dat",
        }

        # Should skip with default types
        result = await download_slack_file(file_info, "xoxb-token")
        assert result is None

        # Should download with custom types
        session_cm, _ = mock_aiohttp_session(
            status=200, content=b"custom data"
        )

        with patch(
            "parrot.integrations.slack.files.ClientSession",
            return_value=session_cm,
        ):
            result = await download_slack_file(
                file_info,
                "xoxb-token",
                str(tmp_path),
                allowed_types={"application/custom"},
            )

            assert result is not None


class TestUploadFileToSlack:
    """Tests for upload_file_to_slack function."""

    @pytest.fixture
    def mock_upload_session(self):
        """Create a properly mocked aiohttp session for upload tests."""
        def create_mock(
            get_url_ok=True,
            upload_ok=True,
            complete_ok=True,
            capture_complete_payload=None,
        ):
            call_order = []

            def mock_get(*args, **kwargs):
                url = args[0] if args else ""
                call_order.append(("get", url))

                mock_resp = MagicMock()
                if get_url_ok:
                    mock_resp.json = AsyncMock(return_value={
                        "ok": True,
                        "upload_url": "https://upload.slack.com/xyz",
                        "file_id": "F123456",
                    })
                else:
                    mock_resp.json = AsyncMock(return_value={
                        "ok": False,
                        "error": "not_allowed",
                    })

                resp_cm = MagicMock()
                resp_cm.__aenter__ = AsyncMock(return_value=mock_resp)
                resp_cm.__aexit__ = AsyncMock(return_value=None)
                return resp_cm

            def mock_post(*args, **kwargs):
                url = args[0] if args else ""
                call_order.append(("post", url))

                mock_resp = MagicMock()

                if "completeUploadExternal" in str(url):
                    # Capture payload if requested
                    if capture_complete_payload is not None:
                        import json
                        data = kwargs.get("data", "{}")
                        capture_complete_payload.update(json.loads(data))

                    if complete_ok:
                        mock_resp.json = AsyncMock(return_value={"ok": True})
                    else:
                        mock_resp.json = AsyncMock(return_value={
                            "ok": False,
                            "error": "failed",
                        })
                else:
                    # Upload step
                    mock_resp.status = 200 if upload_ok else 500

                resp_cm = MagicMock()
                resp_cm.__aenter__ = AsyncMock(return_value=mock_resp)
                resp_cm.__aexit__ = AsyncMock(return_value=None)
                return resp_cm

            mock_session = MagicMock()
            mock_session.get = mock_get
            mock_session.post = mock_post

            session_cm = MagicMock()
            session_cm.__aenter__ = AsyncMock(return_value=mock_session)
            session_cm.__aexit__ = AsyncMock(return_value=None)

            return session_cm, call_order

        return create_mock

    @pytest.mark.asyncio
    async def test_three_step_upload(self, tmp_path, mock_upload_session):
        """Completes the 3-step v2 upload flow."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        session_cm, call_order = mock_upload_session()

        with patch(
            "parrot.integrations.slack.files.ClientSession",
            return_value=session_cm,
        ):
            result = await upload_file_to_slack(
                bot_token="xoxb-token",
                channel="C123",
                file_path=test_file,
                title="Test File",
                initial_comment="Here's the file",
            )

            assert result is True
            # Verify all three steps were called
            get_calls = [c for c in call_order if c[0] == "get"]
            post_calls = [c for c in call_order if c[0] == "post"]
            assert len(get_calls) >= 1  # Step 1: getUploadURLExternal
            assert len(post_calls) >= 2  # Steps 2 and 3: upload + complete

    @pytest.mark.asyncio
    async def test_upload_fails_on_missing_file(self, tmp_path):
        """Returns False when file doesn't exist."""
        nonexistent = tmp_path / "nonexistent.txt"

        result = await upload_file_to_slack(
            bot_token="xoxb-token",
            channel="C123",
            file_path=nonexistent,
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_upload_fails_on_get_url_error(self, tmp_path, mock_upload_session):
        """Returns False when getUploadURLExternal fails."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        session_cm, _ = mock_upload_session(get_url_ok=False)

        with patch(
            "parrot.integrations.slack.files.ClientSession",
            return_value=session_cm,
        ):
            result = await upload_file_to_slack(
                bot_token="xoxb-token",
                channel="C123",
                file_path=test_file,
            )

            assert result is False

    @pytest.mark.asyncio
    async def test_upload_with_thread_ts(self, tmp_path, mock_upload_session):
        """Includes thread_ts in complete upload request."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        captured_payload = {}
        session_cm, _ = mock_upload_session(capture_complete_payload=captured_payload)

        with patch(
            "parrot.integrations.slack.files.ClientSession",
            return_value=session_cm,
        ):
            result = await upload_file_to_slack(
                bot_token="xoxb-token",
                channel="C123",
                file_path=test_file,
                thread_ts="1234567890.123456",
            )

            assert result is True
            assert captured_payload.get("thread_ts") == "1234567890.123456"


class TestIsProcessableFile:
    """Tests for is_processable_file helper."""

    def test_pdf_is_processable(self):
        """PDF files are processable."""
        file_info = {"mimetype": "application/pdf", "name": "doc.pdf"}
        assert is_processable_file(file_info) is True

    def test_image_is_processable(self):
        """Image files are processable."""
        for mimetype in ["image/png", "image/jpeg", "image/gif", "image/webp"]:
            file_info = {"mimetype": mimetype}
            assert is_processable_file(file_info) is True

    def test_executable_not_processable(self):
        """Executable files are not processable."""
        file_info = {"mimetype": "application/x-executable"}
        assert is_processable_file(file_info) is False

    def test_empty_mimetype_not_processable(self):
        """Files without mimetype are not processable."""
        file_info = {"name": "unknown"}
        assert is_processable_file(file_info) is False


class TestGetFileExtension:
    """Tests for get_file_extension helper."""

    def test_gets_from_filetype(self):
        """Gets extension from filetype field."""
        file_info = {"filetype": "pdf", "name": "document"}
        assert get_file_extension(file_info) == ".pdf"

    def test_gets_from_name(self):
        """Gets extension from name when filetype not available."""
        file_info = {"name": "document.docx"}
        assert get_file_extension(file_info) == ".docx"

    def test_gets_from_mimetype(self):
        """Gets extension from mimetype as fallback."""
        file_info = {"mimetype": "image/png"}
        assert get_file_extension(file_info) == ".png"

    def test_returns_empty_for_unknown(self):
        """Returns empty string when extension cannot be determined."""
        file_info = {"id": "F123"}
        assert get_file_extension(file_info) == ""


class TestProcessableMimeTypes:
    """Tests for PROCESSABLE_MIME_TYPES constant."""

    def test_includes_common_document_types(self):
        """Contains common document MIME types."""
        assert "application/pdf" in PROCESSABLE_MIME_TYPES
        assert "text/plain" in PROCESSABLE_MIME_TYPES
        assert "text/csv" in PROCESSABLE_MIME_TYPES

    def test_includes_office_formats(self):
        """Contains Office document MIME types."""
        assert (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            in PROCESSABLE_MIME_TYPES
        )
        assert (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            in PROCESSABLE_MIME_TYPES
        )

    def test_includes_image_types(self):
        """Contains image MIME types."""
        assert "image/png" in PROCESSABLE_MIME_TYPES
        assert "image/jpeg" in PROCESSABLE_MIME_TYPES
        assert "image/gif" in PROCESSABLE_MIME_TYPES

    def test_excludes_executables(self):
        """Does not contain executable types."""
        assert "application/x-executable" not in PROCESSABLE_MIME_TYPES
        assert "application/x-msdownload" not in PROCESSABLE_MIME_TYPES
