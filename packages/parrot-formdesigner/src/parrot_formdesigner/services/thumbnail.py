"""Server-side thumbnail generation for image uploads (FEAT-460).

Uses Pillow to resize images to a bounded max size and re-encode them
(WebP by default), persisting the result to blob storage. All CPU-bound
Pillow work runs in a worker thread via ``asyncio.to_thread`` to avoid
blocking the event loop.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from io import BytesIO

from PIL import Image

from parrot_formdesigner.services.blob_storage import AbstractBlobStorage, BlobMetadata

logger = logging.getLogger(__name__)


class ThumbnailService:
    """Server-side thumbnail generator for image uploads.

    Uses Pillow to resize images to 150x150 max, outputs WebP
    (quality 80). Persists thumbnails to blob storage and returns
    a relative URL.
    """

    def __init__(
        self,
        blob_storage: AbstractBlobStorage,
        max_width: int = 150,
        max_height: int = 150,
        quality: int = 80,
        output_format: str = "WEBP",
    ) -> None:
        """Initialize the thumbnail service.

        Args:
            blob_storage: Blob storage backend used to persist thumbnails.
            max_width: Maximum thumbnail width in pixels.
            max_height: Maximum thumbnail height in pixels.
            quality: Output encoding quality (0-100).
            output_format: Pillow format name used to encode the thumbnail
                (e.g. "WEBP").
        """
        self._storage = blob_storage
        self._max_width = max_width
        self._max_height = max_height
        self._quality = quality
        self._format = output_format

    async def generate(
        self,
        image_bytes: bytes,
        metadata: BlobMetadata,
    ) -> str | None:
        """Generate and persist a thumbnail.

        Args:
            image_bytes: Raw bytes of the source image.
            metadata: Metadata describing the original upload; used to
                derive thumbnail-specific metadata.

        Returns:
            The thumbnail's blob_ref, or None if generation failed (e.g.
            corrupt image or unsupported format). Failures are logged as
            warnings and are non-fatal to the caller.
        """
        try:
            thumb_bytes = await asyncio.to_thread(self._resize, image_bytes)
        except Exception:
            logger.warning(
                "Thumbnail generation failed for %s", metadata.field_id, exc_info=True
            )
            return None

        thumb_meta = BlobMetadata(
            form_uid=metadata.form_uid,
            form_id=metadata.form_id,
            field_uid=metadata.field_uid,
            field_id=f"{metadata.field_id}__thumb",
            submission_id=metadata.submission_id,
            tenant=metadata.tenant,
            content_type=f"image/{self._format.lower()}",
            size_bytes=len(thumb_bytes),
        )

        async def _stream() -> AsyncIterator[bytes]:
            yield thumb_bytes

        return await self._storage.put(_stream(), metadata=thumb_meta)

    def _resize(self, image_bytes: bytes) -> bytes:
        """Resize and re-encode an image (synchronous; runs in a thread).

        Args:
            image_bytes: Raw bytes of the source image.

        Returns:
            The encoded thumbnail bytes.
        """
        img = Image.open(BytesIO(image_bytes))
        img.thumbnail((self._max_width, self._max_height))
        buf = BytesIO()
        img.save(buf, format=self._format, quality=self._quality)
        return buf.getvalue()
