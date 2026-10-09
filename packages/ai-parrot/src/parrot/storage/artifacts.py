"""High-level artifact CRUD operations.

Composes ``ConversationBackend`` (artifacts table) and
``OverflowStore`` to provide a single interface for saving,
loading, listing, updating, and deleting artifacts.

FEAT-116: Refactored to use ConversationBackend ABC and OverflowStore.
Removed the leaky ConversationDynamoDB-specific abstraction (FEAT-116).
See docs/storage-backends.md for backend configuration.
"""

import io
import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Any, List, Literal, Optional, Union

from navconfig.logging import logging

from .backends.base import ConversationBackend
from .exports import (
    DEFAULT_URL_BASE,
    EXPORT_PREFIX,
    ExportRef,
    ExportTooLarge,
    InvalidExportKey,
    build_export_key,
    guess_content_type,
    max_bytes,
    parse_export_key,
    partition_segment,
    ttl_seconds,
)
from .models import Artifact, ArtifactSummary, ArtifactType
from .overflow import OverflowStore

# Presigned URL expiry in seconds (default 7 days).
# Override via INFOGRAPHIC_URL_EXPIRY_SECONDS environment variable.
_URL_EXPIRY_SECONDS: int = int(os.environ.get("INFOGRAPHIC_URL_EXPIRY_SECONDS", "604800"))


@dataclass(frozen=True)
class ExportFile:
    """A stored export: its bytes and metadata (:meth:`ArtifactStore.get_export`)."""

    data: bytes
    filename: str
    content_type: str


class ArtifactStore:
    """Artifact CRUD operations against the configured storage backend.

    Args:
        dynamodb: Initialised ``ConversationBackend`` instance (param name
            kept for backward compatibility with existing callers).
        s3_overflow: Initialised ``OverflowStore`` instance (param name
            kept for backward compatibility).
    """

    def __init__(
        self,
        dynamodb: ConversationBackend,
        s3_overflow: OverflowStore,
    ) -> None:
        self._db = dynamodb
        self._overflow = s3_overflow
        self.logger = logging.getLogger("parrot.storage.ArtifactStore")

    async def save_artifact(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        artifact: Artifact,
    ) -> None:
        """Persist an artifact, offloading to overflow store if necessary."""
        data = artifact.model_dump(mode="json")
        definition = data.pop("definition", None)
        definition_ref = data.pop("definition_ref", None)

        if definition is not None:
            key_prefix = self._db.build_overflow_prefix(
                user_id, agent_id, session_id, artifact.artifact_id,
            )
            inline, ref = await self._overflow.maybe_offload(definition, key_prefix)
            data["definition"] = inline
            data["definition_ref"] = ref
        else:
            data["definition"] = None
            data["definition_ref"] = definition_ref

        await self._db.put_artifact(
            user_id=user_id,
            agent_id=agent_id,
            session_id=session_id,
            artifact_id=artifact.artifact_id,
            data=data,
        )

    async def get_artifact(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        artifact_id: str,
    ) -> Optional[Artifact]:
        """Retrieve a single artifact with its full definition."""
        raw = await self._db.get_artifact(user_id, agent_id, session_id, artifact_id)
        if raw is None:
            return None
        definition = raw.get("definition")
        definition_ref = raw.get("definition_ref")
        resolved = await self._overflow.resolve(definition, definition_ref)
        return self._deserialize(raw, resolved)

    async def list_artifacts(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
    ) -> List[ArtifactSummary]:
        """List all artifacts for a session as lightweight summaries."""
        items = await self._db.query_artifacts(user_id, agent_id, session_id)
        summaries = []
        for item in items:
            try:
                summary = ArtifactSummary(
                    id=item.get("artifact_id", ""),
                    type=item.get("artifact_type", ArtifactType.CHART),
                    title=item.get("title", ""),
                    created_at=item.get("created_at", ""),
                    updated_at=item.get("updated_at"),
                )
                summaries.append(summary)
            except Exception as exc:
                self.logger.warning(
                    "Failed to parse artifact summary: %s — %s", item, exc,
                )
        return summaries

    async def update_artifact(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        artifact_id: str,
        definition: Dict[str, Any],
    ) -> None:
        """Replace the definition of an existing artifact."""
        existing = await self._db.get_artifact(user_id, agent_id, session_id, artifact_id)
        if existing is not None:
            old_ref = existing.get("definition_ref")
            if old_ref:
                await self._overflow.delete(old_ref)

        key_prefix = self._db.build_overflow_prefix(
            user_id, agent_id, session_id, artifact_id,
        )
        inline, ref = await self._overflow.maybe_offload(definition, key_prefix)

        # Fix #4/#13: strip backend-internal storage fields that some backends
        # (e.g. DynamoDB) embed in returned dicts but are not part of the
        # domain model.  Non-DynamoDB backends won't have these keys, so the
        # filter is harmless but keeps the update_data payload clean.
        _INTERNAL_FIELDS = frozenset({"PK", "SK", "type", "ttl"})
        update_data: Dict[str, Any] = {}
        if existing:
            update_data = {k: v for k, v in existing.items() if k not in _INTERNAL_FIELDS}
        update_data["definition"] = inline
        update_data["definition_ref"] = ref
        # Fix #4: use timezone-aware UTC datetime (datetime.utcnow() is deprecated
        # in Python 3.12 and returns a naive datetime).
        update_data["updated_at"] = datetime.now(timezone.utc).isoformat()

        await self._db.put_artifact(
            user_id=user_id,
            agent_id=agent_id,
            session_id=session_id,
            artifact_id=artifact_id,
            data=update_data,
        )

    async def delete_artifact(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        artifact_id: str,
    ) -> bool:
        """Delete an artifact from storage and clean up any overflow data."""
        existing = await self._db.get_artifact(user_id, agent_id, session_id, artifact_id)
        if existing is None:
            return False
        ref = existing.get("definition_ref")
        if ref:
            await self._overflow.delete(ref)
        await self._db.delete_artifact(user_id, agent_id, session_id, artifact_id)
        return True

    async def get_public_url(
        self,
        user_id: Union[str, int],
        agent_id: str,
        session_id: str,
        artifact_id: str,
        *,
        format: Literal["html", "json"] = "html",  # noqa: A002
    ) -> str:
        """Return a presigned URL for the artifact's overflow object.

        Generates an S3 sigv4 presigned URL (max 7 days / 604 800 s) so that
        the artifact can be fetched by any caller with the URL — no session or
        auth required.  The URL does NOT embed ``user_id``; signature alone
        authorises access.

        For the ``"html"`` format the URL points to the same overflow JSON
        object that ``save_artifact`` uploaded (which contains the full
        definition including the ``html`` field).  TASK-1322's public route
        provides the HTML-specific serving endpoint on top of this.

        Args:
            user_id: Owning user identifier (used to locate the artifact).
            agent_id: Agent that produced the artifact.
            session_id: Session that owns the artifact.
            artifact_id: Unique artifact identifier.
            format: ``"html"`` (default) or ``"json"``.  v1 treats both
                identically; both return a presigned URL to the overflow JSON.
                ``"json"`` is kept for future use; raises ``NotImplementedError``
                if distinct JSON-only storage is requested.

        Returns:
            A presigned URL string starting with ``https://``.

        Raises:
            KeyError: When the artifact does not exist.
            ValueError: When the artifact has no overflow reference (stored
                inline, i.e. small enough to skip S3).
        """
        artifact = await self.get_artifact(user_id, agent_id, session_id, artifact_id)
        if artifact is None:
            raise KeyError(f"Artifact {artifact_id!r} not found")

        ref = artifact.definition_ref
        if not ref:
            raise ValueError(
                f"Artifact {artifact_id!r} has no overflow reference; "
                "cannot generate a presigned URL for an inline artifact."
            )

        self.logger.info(
            "Issuing presigned URL for artifact=%s format=%s", artifact_id, format,
        )
        return await self._overflow.generate_presigned_url(
            ref, expires_in=_URL_EXPIRY_SECONDS,
        )

    # ------------------------------------------------------------------
    # File exports (PA-12): tenant-partitioned, TTL-bound, size-capped
    # ------------------------------------------------------------------

    @property
    def file_manager(self):
        """The ``FileManagerInterface`` the store keeps files in (the overflow store's)."""
        return self._overflow._fm  # pylint: disable=protected-access

    @staticmethod
    def _export_path(key: str) -> str:
        return f"{EXPORT_PREFIX}/{key}"

    async def save_export(
        self,
        tenant: Optional[str],
        agent: Optional[str],
        filename: str,
        data: bytes,
        *,
        content_type: Optional[str] = None,
        url_base: Optional[str] = None,
        ttl: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> ExportRef:
        """Store ``data`` under ``{tenant}/{agent}/{uuid}/{filename}`` (server-chosen parts only).

        Raises:
            InvalidExportKey: a tenant/agent segment that cannot be a partition name.
            ExportTooLarge: ``data`` is above the per-file cap (``STUDIO_ARTIFACT_MAX_BYTES``).
        """
        cap = limit if limit is not None else max_bytes()
        if len(data) > cap:
            raise ExportTooLarge(f"export is {len(data)} bytes; the limit is {cap}")
        key = build_export_key(tenant, agent, uuid.uuid4().hex, filename)
        _, _, _, name = parse_export_key(key)
        ctype = content_type or guess_content_type(name)
        expires_at = time.time() + (ttl if ttl is not None else ttl_seconds())
        meta = {"tenant": key.split("/")[0], "filename": name, "content_type": ctype, "bytes": len(data),
                "expires_at": expires_at}
        path = self._export_path(key)
        await self.file_manager.create_from_bytes(path, data)
        await self.file_manager.create_from_bytes(f"{path}.meta.json", json.dumps(meta).encode("utf-8"))
        base = (url_base or DEFAULT_URL_BASE).rstrip("/")
        return ExportRef(key=key, url=f"{base}/{key}", filename=name, bytes=len(data), content_type=ctype,
                         expires_at=expires_at)

    async def get_export(self, key: str, *, tenant: Optional[str]) -> Optional[ExportFile]:
        """The export ``key`` for a caller of ``tenant``; ``None`` when it is unknown, expired, crafted or another
        tenant's (a caller cannot tell those apart: the route answers 404 for all of them)."""
        try:
            key_tenant, _, _, _ = parse_export_key(key)
            if key_tenant != partition_segment(tenant, what="tenant"):
                return None
        except InvalidExportKey:
            return None
        path = self._export_path(key)
        try:
            raw = io.BytesIO()
            await self.file_manager.download_file(f"{path}.meta.json", raw)
            meta = json.loads(raw.getvalue().decode("utf-8"))
        except Exception:  # pylint: disable=broad-except
            return None
        if meta.get("tenant") != key_tenant:
            return None
        if float(meta.get("expires_at", 0)) <= time.time():
            await self.delete_export(key)
            return None
        try:
            body = io.BytesIO()
            await self.file_manager.download_file(path, body)
        except Exception:  # pylint: disable=broad-except
            return None
        return ExportFile(data=body.getvalue(), filename=meta.get("filename", key.rsplit("/", 1)[-1]),
                          content_type=meta.get("content_type") or guess_content_type(key))

    async def delete_export(self, key: str) -> bool:
        """Remove an export and its metadata (best effort); ``True`` when the file existed."""
        path = self._export_path(key)
        existed = False
        for item in (path, f"{path}.meta.json"):
            try:
                existed = bool(await self.file_manager.delete_file(item)) or existed
            except Exception:  # pylint: disable=broad-except
                continue
        return existed

    @staticmethod
    def _deserialize(raw: dict, resolved_definition: Optional[dict]) -> Artifact:
        """Build an ``Artifact`` model from a raw storage item."""
        return Artifact(
            artifact_id=raw.get("artifact_id", ""),
            artifact_type=raw.get("artifact_type", ArtifactType.CHART),
            title=raw.get("title", ""),
            created_at=raw.get("created_at", ""),
            updated_at=raw.get("updated_at", ""),
            source_turn_id=raw.get("source_turn_id"),
            created_by=raw.get("created_by", "user"),
            definition=resolved_definition,
            definition_ref=raw.get("definition_ref"),
        )
