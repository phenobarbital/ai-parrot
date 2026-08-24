"""Unit tests for ThumbnailService (FEAT-460)."""

import uuid
import pytest
from io import BytesIO
from unittest.mock import AsyncMock
from PIL import Image
from parrot_formdesigner.services.thumbnail import ThumbnailService
from parrot_formdesigner.services.blob_storage import BlobMetadata


@pytest.fixture
def mock_storage():
    storage = AsyncMock()
    storage.put = AsyncMock(return_value="temp://thumb-ref")
    return storage


@pytest.fixture
def sample_metadata():
    return BlobMetadata(
        form_uid=uuid.uuid4(), form_id="test-form",
        field_uid=uuid.uuid4(), field_id="photo",
        content_type="image/jpeg", size_bytes=10000,
    )


@pytest.fixture
def valid_image_bytes():
    img = Image.new("RGB", (800, 600), color="red")
    buf = BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


class TestThumbnailService:
    @pytest.mark.asyncio
    async def test_generate_returns_blob_ref(self, mock_storage, sample_metadata, valid_image_bytes):
        svc = ThumbnailService(mock_storage)
        ref = await svc.generate(valid_image_bytes, sample_metadata)
        assert ref == "temp://thumb-ref"
        mock_storage.put.assert_called_once()

    @pytest.mark.asyncio
    async def test_thumbnail_dimensions(self, mock_storage, sample_metadata, valid_image_bytes):
        svc = ThumbnailService(mock_storage, max_width=150, max_height=150)
        await svc.generate(valid_image_bytes, sample_metadata)
        # Verify the stored bytes are a valid thumbnail
        call_args = mock_storage.put.call_args
        stream = call_args[0][0]  # first positional arg = async iterator
        chunks = []
        async for chunk in stream:
            chunks.append(chunk)
        thumb_bytes = b"".join(chunks)
        img = Image.open(BytesIO(thumb_bytes))
        assert img.width <= 150
        assert img.height <= 150

    @pytest.mark.asyncio
    async def test_corrupt_image_returns_none(self, mock_storage, sample_metadata):
        svc = ThumbnailService(mock_storage)
        result = await svc.generate(b"not an image", sample_metadata)
        assert result is None
        mock_storage.put.assert_not_called()

    @pytest.mark.asyncio
    async def test_metadata_uses_thumb_suffix(self, mock_storage, sample_metadata, valid_image_bytes):
        svc = ThumbnailService(mock_storage)
        await svc.generate(valid_image_bytes, sample_metadata)
        call_kwargs = mock_storage.put.call_args[1]
        meta = call_kwargs["metadata"]
        assert meta.field_id == f"{sample_metadata.field_id}__thumb"
        assert meta.content_type == "image/webp"
