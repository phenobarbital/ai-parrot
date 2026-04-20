"""S3 Overflow Manager for large artifact definitions.

Transparently offloads artifact definitions that exceed the DynamoDB
inline threshold (200 KB) to S3.  On retrieval the reference is
resolved back to the original dict.

FEAT-103: agent-artifact-persistency — Module 3.
"""

import io
import json
from typing import Any, Dict, Optional, Tuple

from navconfig.logging import logging

from parrot.interfaces.file.s3 import S3FileManager


class S3OverflowManager:
    """Transparent large-item offloading to S3.

    If an artifact's serialised definition is smaller than
    ``INLINE_THRESHOLD`` (200 KB), it stays inline in DynamoDB.
    Otherwise the JSON is uploaded to S3 and only the S3 key is
    stored in DynamoDB.

    Args:
        s3_file_manager: Pre-configured ``S3FileManager`` pointing at
            the artifact bucket.
    """

    INLINE_THRESHOLD: int = 200 * 1024  # 200 KB

    def __init__(self, s3_file_manager: S3FileManager) -> None:
        self._s3 = s3_file_manager
        self.logger = logging.getLogger("parrot.storage.S3OverflowManager")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def maybe_offload(
        self,
        data: Dict[str, Any],
        key_prefix: str,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Decide whether *data* fits inline or must be offloaded to S3.

        Args:
            data: The artifact definition dict to evaluate.
            key_prefix: S3 key prefix, e.g.
                ``"artifacts/USER#u1#AGENT#bot/THREAD#sess/chart-x1"``.

        Returns:
            A tuple ``(inline_data, None)`` when the payload is small,
            or ``(None, s3_key)`` when the data was uploaded to S3.
        """
        json_bytes = json.dumps(data, default=str).encode("utf-8")

        if len(json_bytes) < self.INLINE_THRESHOLD:
            return data, None

        # Offload to S3
        s3_key = f"{key_prefix}.json"
        try:
            await self._s3.create_from_bytes(
                json_bytes,
                s3_key,
                content_type="application/json",
            )
            self.logger.info(
                "Offloaded %d bytes to S3: %s", len(json_bytes), s3_key,
            )
            return None, s3_key
        except Exception as exc:
            self.logger.warning(
                "S3 offload failed for %s: %s — storing inline as fallback",
                s3_key, exc,
            )
            # Fallback: return inline even if large (DynamoDB may reject it)
            return data, None

    async def resolve(
        self,
        definition: Optional[Dict[str, Any]],
        definition_ref: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        """Resolve an artifact definition, fetching from S3 if needed.

        Args:
            definition: Inline definition dict (may be ``None``).
            definition_ref: S3 key for the offloaded definition.

        Returns:
            The artifact definition dict, or ``None`` if resolution fails.
        """
        if definition is not None:
            return definition

        if not definition_ref:
            return None

        try:
            buf = io.BytesIO()
            await self._s3.download_file(definition_ref, buf)
            buf.seek(0)
            return json.loads(buf.read().decode("utf-8"))
        except FileNotFoundError:
            self.logger.warning(
                "S3 object not found for ref: %s", definition_ref,
            )
            return None
        except Exception as exc:
            self.logger.warning(
                "S3 resolve failed for %s: %s", definition_ref, exc,
            )
            return None

    async def delete(self, definition_ref: Optional[str]) -> None:
        """Delete S3 object if ``definition_ref`` exists.

        This is a no-op when the artifact was stored inline.

        Args:
            definition_ref: S3 key to delete, or ``None``.
        """
        if not definition_ref:
            return
        try:
            await self._s3.delete_file(definition_ref)
            self.logger.debug("Deleted S3 overflow object: %s", definition_ref)
        except Exception as exc:
            self.logger.warning(
                "S3 delete failed for %s: %s", definition_ref, exc,
            )
