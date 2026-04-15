"""Unit tests for VectorStoreHandler PUT endpoint (data loading)."""
import json
import pytest
from collections import OrderedDict
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


def _make_handler(app_overrides=None):
    """Create a VectorStoreHandler with mocked app."""
    from parrot.handlers.stores.handler import (
        VectorStoreHandler,
        _STORE_CACHE_KEY,
        _JOB_MANAGER_KEY,
        _TEMP_FILE_KEY,
    )
    handler = VectorStoreHandler.__new__(VectorStoreHandler)
    mock_jm = MagicMock()
    mock_jm.create_job = MagicMock(return_value=MagicMock(job_id="test-job-id"))
    mock_jm.execute_job = AsyncMock()

    mock_tfm = MagicMock()
    mock_tfm.delete_file = AsyncMock(return_value=True)

    app = {
        _STORE_CACHE_KEY: OrderedDict(),
        _JOB_MANAGER_KEY: mock_jm,
        _TEMP_FILE_KEY: mock_tfm,
    }
    if app_overrides:
        app.update(app_overrides)

    request = MagicMock()
    request.app = app
    handler.request = request
    handler.logger = MagicMock()
    return handler, mock_jm, mock_tfm


def _make_mock_store():
    store = MagicMock()
    store._connected = True
    store.add_documents = AsyncMock()
    return store


def _make_file_info(name: str, size: int = 100, tmp_dir: str = "/tmp") -> dict:
    """Build a file_info dict as returned by handle_upload."""
    path = Path(tmp_dir) / name
    return {
        "file_path": path,
        "file_name": name,
        "mime_type": "application/octet-stream",
    }


class TestPutFileUpload:

    @pytest.mark.asyncio
    async def test_pdf_file_loads_immediately(self):
        """PDF file is loaded via PDFLoader and returns immediate result."""
        from parrot.stores.models import Document
        handler, jm, tfm = _make_handler()
        store = _make_mock_store()

        file_info = _make_file_info("test.pdf")
        mock_docs = [Document(page_content="page content", metadata={})]

        handler.handle_upload = AsyncMock(return_value=({"file": [file_info]}, {
            "table": "docs", "vector_store": "postgres",
            "dsn": "postgresql+asyncpg://test/db",
        }))
        with patch.object(handler, "_get_store", AsyncMock(return_value=store)):
            with patch.object(handler, "_load_file", AsyncMock(return_value=mock_docs)):
                handler.request.content_type = "multipart/form-data"
                response = await handler.put()

        data = json.loads(response.text)
        assert data["status"] == "loaded"
        assert data["documents"] == 1
        store.add_documents.assert_called_once()

    @pytest.mark.asyncio
    async def test_file_too_large_returns_413(self):
        """Rejects file exceeding max size."""
        # 25MB + 1 byte — exceeds default limit
        max_size = 25 * 1024 * 1024
        handler, jm, tfm = _make_handler()

        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"x" * 100)
            tmp_path = Path(f.name)

        file_info = {"file_path": tmp_path, "file_name": "big.pdf", "mime_type": "application/pdf"}

        try:
            handler.handle_upload = AsyncMock(return_value=({"file": [file_info]}, {
                "table": "docs", "vector_store": "postgres",
                "dsn": "postgresql+asyncpg://test/db",
            }))
            with patch("pathlib.Path.stat") as mock_stat:
                mock_stat.return_value.st_size = max_size + 1
                with patch("parrot.handlers.stores.handler.VECTOR_HANDLER_MAX_FILE_SIZE", max_size):
                    handler.request.content_type = "multipart/form-data"
                    response = await handler.put()
        finally:
            os.unlink(tmp_path)

        assert response.status == 413

    @pytest.mark.asyncio
    async def test_image_dispatches_background_job(self):
        """Image upload creates background job."""
        handler, jm, tfm = _make_handler()
        store = _make_mock_store()

        file_info = _make_file_info("photo.jpg")

        handler.handle_upload = AsyncMock(return_value=({"file": [file_info]}, {
            "table": "docs", "vector_store": "postgres",
            "dsn": "postgresql+asyncpg://test/db",
        }))
        with patch.object(handler, "_get_store", AsyncMock(return_value=store)):
            handler.request.content_type = "multipart/form-data"
            response = await handler.put()

        data = json.loads(response.text)
        assert "job_id" in data
        assert data["status"] == "pending"
        jm.create_job.assert_called_once()
        jm.execute_job.assert_called_once()

    @pytest.mark.asyncio
    async def test_video_dispatches_background_job(self):
        """Video upload creates background job."""
        handler, jm, tfm = _make_handler()
        store = _make_mock_store()

        file_info = _make_file_info("clip.mp4")

        handler.handle_upload = AsyncMock(return_value=({"file": [file_info]}, {
            "table": "docs", "vector_store": "postgres",
            "dsn": "postgresql+asyncpg://test/db",
        }))
        with patch.object(handler, "_get_store", AsyncMock(return_value=store)):
            handler.request.content_type = "multipart/form-data"
            response = await handler.put()

        data = json.loads(response.text)
        assert data["status"] == "pending"
        assert "job_id" in data


class TestPutJsonContent:

    @pytest.mark.asyncio
    async def test_inline_content_creates_document(self):
        """JSON with content field creates Document directly."""
        handler, jm, tfm = _make_handler()
        store = _make_mock_store()

        handler.request.content_type = "application/json"
        handler.request.json = AsyncMock(return_value={
            "content": "Some text content",
            "table": "docs",
            "vector_store": "postgres",
            "dsn": "postgresql+asyncpg://test/db",
        })

        with patch.object(handler, "_get_store", AsyncMock(return_value=store)):
            response = await handler.put()

        data = json.loads(response.text)
        assert data["status"] == "loaded"
        assert data["documents"] == 1
        store.add_documents.assert_called_once()
        # No background job created
        jm.create_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_url_list_dispatches_job(self):
        """JSON with url list creates background job."""
        handler, jm, tfm = _make_handler()
        store = _make_mock_store()

        handler.request.content_type = "application/json"
        handler.request.json = AsyncMock(return_value={
            "url": ["https://example.com/page"],
            "table": "docs",
            "vector_store": "postgres",
            "dsn": "postgresql+asyncpg://test/db",
        })

        with patch.object(handler, "_get_store", AsyncMock(return_value=store)):
            response = await handler.put()

        data = json.loads(response.text)
        assert data["status"] == "pending"
        assert "job_id" in data
        jm.create_job.assert_called_once()

    def test_youtube_url_detection(self):
        """_is_youtube_url correctly identifies YouTube URLs."""
        from parrot.handlers.stores.handler import VectorStoreHandler
        assert VectorStoreHandler._is_youtube_url("https://www.youtube.com/watch?v=abc") is True
        assert VectorStoreHandler._is_youtube_url("https://youtu.be/abc123") is True
        assert VectorStoreHandler._is_youtube_url("https://vimeo.com/123") is False

    @pytest.mark.asyncio
    async def test_missing_table_returns_400(self):
        """Returns 400 when table is missing in JSON body."""
        handler, jm, tfm = _make_handler()
        handler.request.content_type = "application/json"
        handler.request.json = AsyncMock(return_value={
            "content": "Some text",
            "vector_store": "postgres",
        })

        response = await handler.put()
        assert response.status == 400

    @pytest.mark.asyncio
    async def test_no_content_or_url_returns_400(self):
        """Returns 400 when body has neither content nor url."""
        handler, jm, tfm = _make_handler()
        store = _make_mock_store()
        handler.request.content_type = "application/json"
        handler.request.json = AsyncMock(return_value={
            "table": "docs",
            "vector_store": "postgres",
            "dsn": "postgresql+asyncpg://test/db",
        })

        with patch.object(handler, "_get_store", AsyncMock(return_value=store)):
            response = await handler.put()

        assert response.status == 400


