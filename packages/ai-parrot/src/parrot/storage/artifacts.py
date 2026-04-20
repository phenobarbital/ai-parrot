"""High-level artifact CRUD operations.

Composes ``ConversationDynamoDB`` (artifacts table) and
``S3OverflowManager`` to provide a single interface for saving,
loading, listing, updating, and deleting artifacts.

FEAT-103: agent-artifact-persistency — Module 4.
"""

from datetime import datetime
from typing import Dict, Any, List, Optional

from navconfig.logging import logging

from .dynamodb import ConversationDynamoDB
from .models import Artifact, ArtifactSummary, ArtifactType
from .s3_overflow import S3OverflowManager


class ArtifactStore:
    """Artifact CRUD operations against the artifacts DynamoDB table.

    Serialises / deserialises ``Artifact`` Pydantic models and
    transparently delegates large definitions to ``S3OverflowManager``.

    Args:
        dynamodb: Initialised ``ConversationDynamoDB`` instance.
        s3_overflow: Initialised ``S3OverflowManager`` instance.
    """

    def __init__(
        self,
        dynamodb: ConversationDynamoDB,
        s3_overflow: S3OverflowManager,
    ) -> None:
        self._db = dynamodb
        self._overflow = s3_overflow
        self.logger = logging.getLogger("parrot.storage.ArtifactStore")

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def save_artifact(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        artifact: Artifact,
    ) -> None:
        """Persist an artifact, offloading to S3 if necessary.

        Args:
            user_id: User identifier.
            agent_id: Agent/bot identifier.
            session_id: Conversation session identifier.
            artifact: The ``Artifact`` model to persist.
        """
        data = artifact.model_dump(mode="json")
        definition = data.pop("definition", None)
        definition_ref = data.pop("definition_ref", None)

        # S3 overflow check for the definition payload
        if definition is not None:
            pk = ConversationDynamoDB._build_pk(user_id, agent_id)
            key_prefix = f"artifacts/{pk}/THREAD#{session_id}/{artifact.artifact_id}"
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
        """Retrieve a single artifact with its full definition.

        S3 references are resolved transparently.

        Args:
            user_id: User identifier.
            agent_id: Agent/bot identifier.
            session_id: Conversation session identifier.
            artifact_id: Artifact identifier.

        Returns:
            An ``Artifact`` instance or ``None`` if not found.
        """
        raw = await self._db.get_artifact(user_id, agent_id, session_id, artifact_id)
        if raw is None:
            return None

        # Resolve S3 if needed
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
        """List all artifacts for a session as lightweight summaries.

        Does NOT include full definitions — only id, type, title, and dates.

        Args:
            user_id: User identifier.
            agent_id: Agent/bot identifier.
            session_id: Conversation session identifier.

        Returns:
            List of ``ArtifactSummary`` instances.
        """
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
        """Replace the definition of an existing artifact.

        Performs S3 overflow check on the new definition. If the old
        artifact had an S3 reference, the old S3 object is deleted.

        Args:
            user_id: User identifier.
            agent_id: Agent/bot identifier.
            session_id: Conversation session identifier.
            artifact_id: Artifact identifier.
            definition: New definition dict.
        """
        # Get existing item to check for old S3 ref
        existing = await self._db.get_artifact(user_id, agent_id, session_id, artifact_id)
        if existing is not None:
            old_ref = existing.get("definition_ref")
            if old_ref:
                await self._overflow.delete(old_ref)

        # Overflow check for new definition
        pk = ConversationDynamoDB._build_pk(user_id, agent_id)
        key_prefix = f"artifacts/{pk}/THREAD#{session_id}/{artifact_id}"
        inline, ref = await self._overflow.maybe_offload(definition, key_prefix)

        # Build updated data
        update_data = {}
        if existing:
            update_data = {k: v for k, v in existing.items()
                          if k not in ("PK", "SK", "type", "ttl")}
        update_data["definition"] = inline
        update_data["definition_ref"] = ref
        now = datetime.utcnow().isoformat()
        update_data["updated_at"] = now

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
        """Delete an artifact from DynamoDB and clean up any S3 data.

        Args:
            user_id: User identifier.
            agent_id: Agent/bot identifier.
            session_id: Conversation session identifier.
            artifact_id: Artifact identifier.

        Returns:
            ``True`` if the artifact was found and deleted, ``False`` otherwise.
        """
        # Get the item first to check for S3 ref
        existing = await self._db.get_artifact(user_id, agent_id, session_id, artifact_id)
        if existing is None:
            return False

        # Delete S3 object first (if exists)
        ref = existing.get("definition_ref")
        if ref:
            await self._overflow.delete(ref)

        # Delete from DynamoDB
        await self._db.delete_artifact(user_id, agent_id, session_id, artifact_id)
        return True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _deserialize(raw: dict, resolved_definition: Optional[dict]) -> Artifact:
        """Build an ``Artifact`` model from a raw DynamoDB item.

        Args:
            raw: The DynamoDB item dict.
            resolved_definition: The resolved definition (inline or from S3).

        Returns:
            An ``Artifact`` instance.
        """
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
