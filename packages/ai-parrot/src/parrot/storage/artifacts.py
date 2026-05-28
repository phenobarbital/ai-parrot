"""High-level artifact CRUD operations.

Composes ``ConversationBackend`` (artifacts table) and
``OverflowStore`` to provide a single interface for saving,
loading, listing, updating, and deleting artifacts.

FEAT-116: Refactored to use ConversationBackend ABC and OverflowStore.
Removed the leaky ConversationDynamoDB-specific abstraction (FEAT-116).
See docs/storage-backends.md for backend configuration.
"""

import os
from datetime import datetime, timezone
from typing import Dict, Any, List, Literal, Optional, Union

from navconfig.logging import logging

from .backends.base import ConversationBackend
from .models import Artifact, ArtifactSummary, ArtifactType
from .overflow import OverflowStore

# Presigned URL expiry in seconds (default 7 days).
# Override via INFOGRAPHIC_URL_EXPIRY_SECONDS environment variable.
_URL_EXPIRY_SECONDS: int = int(os.environ.get("INFOGRAPHIC_URL_EXPIRY_SECONDS", "604800"))


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
