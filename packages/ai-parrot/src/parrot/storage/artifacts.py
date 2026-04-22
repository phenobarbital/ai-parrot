"""High-level artifact CRUD operations.

Composes ``ConversationBackend`` (artifacts table) and
``OverflowStore`` to provide a single interface for saving,
loading, listing, updating, and deleting artifacts.

FEAT-116: Refactored to use ConversationBackend ABC and OverflowStore.
Removed the leaky ConversationDynamoDB-specific abstraction (FEAT-116).
See docs/storage-backends.md for backend configuration.
"""

from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from navconfig.logging import logging

from .backends.base import ConversationBackend
from .models import Artifact, ArtifactSummary, ArtifactType
from .overflow import OverflowStore


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
