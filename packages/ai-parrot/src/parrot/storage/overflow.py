"""Generic artifact overflow store backed by any FileManagerInterface.

Transparently offloads artifact definitions that exceed the inline threshold
(200 KB) to any FileManagerInterface implementation (S3, GCS, Local, Temp).
On retrieval the reference is resolved back to the original dict.

FEAT-116: dynamodb-fallback-redis — Module 2 (OverflowStore generalization).
See docs/storage-backends.md for overflow store configuration.
"""

import io
import json
from typing import Any, Dict, Optional, Tuple

from navconfig.logging import logging

from parrot.interfaces.file.abstract import FileManagerInterface


class OverflowStore:
    """Generic artifact overflow store backed by any FileManagerInterface.

    If an artifact's serialised definition is smaller than
    ``INLINE_THRESHOLD`` (200 KB), it stays inline in the storage backend.
    Otherwise the JSON is uploaded via the file manager and only the
    reference key is stored.

    Args:
        file_manager: Any ``FileManagerInterface`` implementation
            (S3, GCS, Local, Temp).
    """

    INLINE_THRESHOLD: int = 200 * 1024  # 200 KB

    def __init__(self, file_manager: FileManagerInterface) -> None:
        self._fm = file_manager
        self.logger = logging.getLogger("parrot.storage.OverflowStore")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def maybe_offload(
        self,
        data: Dict[str, Any],
        key_prefix: str,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Decide whether *data* fits inline or must be offloaded.

        Args:
            data: The artifact definition dict to evaluate.
            key_prefix: Key prefix for the file manager, e.g.
                ``"artifacts/USER#u1#AGENT#bot/THREAD#sess/chart-x1"``.

        Returns:
            A tuple ``(inline_data, None)`` when the payload is small,
            or ``(None, ref_key)`` when the data was uploaded.
        """
        json_bytes = json.dumps(data, default=str).encode("utf-8")

        if len(json_bytes) < self.INLINE_THRESHOLD:
            return data, None

        # Offload to the file manager
        ref_key = f"{key_prefix}.json"
        try:
            await self._fm.create_from_bytes(
                ref_key,
                json_bytes,
            )
            self.logger.info(
                "Offloaded %d bytes to file manager: %s", len(json_bytes), ref_key,
            )
            return None, ref_key
        except Exception as exc:
            self.logger.warning(
                "File manager offload failed for %s: %s — storing inline as fallback",
                ref_key, exc,
            )
            # Fallback: return inline even if large (backend may reject it)
            return data, None

    async def resolve(
        self,
        definition: Optional[Dict[str, Any]],
        definition_ref: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        """Resolve an artifact definition, fetching from file manager if needed.

        Args:
            definition: Inline definition dict (may be ``None``).
            definition_ref: Key for the offloaded definition.

        Returns:
            The artifact definition dict, or ``None`` if resolution fails.
        """
        if definition is not None:
            return definition

        if not definition_ref:
            return None

        try:
            buf = io.BytesIO()
            await self._fm.download_file(definition_ref, buf)
            buf.seek(0)
            return json.loads(buf.read().decode("utf-8"))
        except FileNotFoundError:
            self.logger.warning(
                "File not found for ref: %s", definition_ref,
            )
            return None
        except Exception as exc:
            self.logger.warning(
                "Resolve failed for %s: %s", definition_ref, exc,
            )
            return None

    async def delete(self, definition_ref: Optional[str]) -> bool:
        """Delete the file for ``definition_ref`` if it exists.

        This is a no-op when the artifact was stored inline.

        Args:
            definition_ref: Key to delete, or ``None``.

        Returns:
            True if a file was deleted, False otherwise.
        """
        if not definition_ref:
            return False
        try:
            result = await self._fm.delete_file(definition_ref)
            self.logger.debug("Deleted overflow object: %s", definition_ref)
            return bool(result)
        except Exception as exc:
            self.logger.warning(
                "Delete failed for %s: %s", definition_ref, exc,
            )
            return False
