"""DynamoDB backend for conversation and artifact storage.

Domain wrapper around aioboto3's DynamoDB client. Provides PK/SK
construction, TTL setting, and domain-specific query patterns for the
two-table design (conversations + artifacts).

FEAT-103: agent-artifact-persistency — Module 2.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import aioboto3
from botocore.exceptions import ClientError, BotoCoreError
from navconfig.logging import logging

from boto3.dynamodb.types import TypeSerializer, TypeDeserializer


class ConversationDynamoDB:
    """Domain wrapper around DynamoDB for conversation storage.

    Uses a single ``aioboto3`` session with two table targets — one for
    conversations (thread metadata + turns) and one for artifacts.

    All low-level DynamoDB operations (serialization, pagination, retries)
    are handled by aioboto3.  This class only adds PK/SK construction,
    TTL setting, and domain-specific query patterns.

    Args:
        conversations_table: DynamoDB table name for conversations.
        artifacts_table: DynamoDB table name for artifacts.
        dynamo_params: Dict with ``region_name``, ``aws_access_key_id``,
            ``aws_secret_access_key``, and optional ``endpoint_url``.
    """

    # TTL default: 180 days from last update
    DEFAULT_TTL_DAYS = 180

    def __init__(
        self,
        conversations_table: str,
        artifacts_table: str,
        dynamo_params: dict,
    ) -> None:
        self._conversations_table = conversations_table
        self._artifacts_table = artifacts_table
        self._dynamo_params = dynamo_params
        self._session: Optional[aioboto3.Session] = None
        self._resource = None
        self._conv_table = None
        self._art_table = None
        self.logger = logging.getLogger("parrot.storage.ConversationDynamoDB")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Open aioboto3 resource connections to both tables."""
        try:
            self._session = aioboto3.Session()
            resource_kwargs: Dict[str, Any] = {
                "region_name": self._dynamo_params.get("region_name"),
            }
            if "endpoint_url" in self._dynamo_params:
                resource_kwargs["endpoint_url"] = self._dynamo_params["endpoint_url"]
            if "aws_access_key_id" in self._dynamo_params:
                resource_kwargs["aws_access_key_id"] = self._dynamo_params["aws_access_key_id"]
            if "aws_secret_access_key" in self._dynamo_params:
                resource_kwargs["aws_secret_access_key"] = self._dynamo_params["aws_secret_access_key"]

            self._resource = await self._session.resource(
                "dynamodb", **resource_kwargs
            ).__aenter__()
            self._conv_table = await self._resource.Table(self._conversations_table)
            self._art_table = await self._resource.Table(self._artifacts_table)
            self.logger.info("DynamoDB backend initialized (tables: %s, %s)",
                             self._conversations_table, self._artifacts_table)
        except (ClientError, BotoCoreError, Exception) as exc:
            self.logger.warning("DynamoDB unavailable: %s", exc)
            self._resource = None
            self._conv_table = None
            self._art_table = None

    async def close(self) -> None:
        """Close aioboto3 resource connections."""
        try:
            if self._resource is not None:
                await self._resource.__aexit__(None, None, None)
                self._resource = None
                self._conv_table = None
                self._art_table = None
                self.logger.debug("DynamoDB backend closed")
        except Exception as exc:
            self.logger.warning("Error closing DynamoDB backend: %s", exc)

    @property
    def is_connected(self) -> bool:
        """Return True if the DynamoDB resource is available."""
        return self._conv_table is not None and self._art_table is not None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_pk(user_id: str, agent_id: str) -> str:
        """Build the partition key for a user+agent pair."""
        return f"USER#{user_id}#AGENT#{agent_id}"

    @staticmethod
    def _ttl_epoch(updated_at: datetime, days: int = 180) -> int:
        """Calculate TTL epoch seconds from a datetime.

        Args:
            updated_at: The reference datetime.
            days: Number of days to add for TTL expiration.

        Returns:
            Unix epoch timestamp as an integer.
        """
        return int((updated_at + timedelta(days=days)).timestamp())

    def _now(self) -> datetime:
        """Return current UTC datetime."""
        return datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # Conversations table — Thread metadata
    # ------------------------------------------------------------------

    async def put_thread(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        metadata: dict,
    ) -> None:
        """Create or replace a thread metadata item.

        Args:
            user_id: User identifier.
            agent_id: Agent/bot identifier.
            session_id: Conversation session identifier.
            metadata: Thread metadata dict (title, created_at, etc.).
        """
        if not self.is_connected:
            return
        pk = self._build_pk(user_id, agent_id)
        sk = f"THREAD#{session_id}"
        now = self._now()
        updated_at = metadata.get("updated_at", now)
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)
        item = {
            "PK": pk,
            "SK": sk,
            "type": "thread",
            "session_id": session_id,
            "user_id": user_id,
            "agent_id": agent_id,
            "ttl": self._ttl_epoch(updated_at, self.DEFAULT_TTL_DAYS),
            **metadata,
        }
        # Ensure datetimes are ISO strings for DynamoDB
        for key in ("created_at", "updated_at"):
            if key in item and isinstance(item[key], datetime):
                item[key] = item[key].isoformat()
        try:
            await self._conv_table.put_item(Item=item)
        except (ClientError, BotoCoreError, Exception) as exc:
            self.logger.warning(
                "DynamoDB put_thread failed for session %s: %s", session_id, exc
            )

    async def update_thread(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        **updates,
    ) -> None:
        """Update specific attributes on a thread metadata item.

        Args:
            user_id: User identifier.
            agent_id: Agent/bot identifier.
            session_id: Conversation session identifier.
            **updates: Key-value pairs to update.
        """
        if not self.is_connected or not updates:
            return
        pk = self._build_pk(user_id, agent_id)
        sk = f"THREAD#{session_id}"

        # Build update expression
        expr_parts = []
        expr_names = {}
        expr_values = {}
        for i, (key, value) in enumerate(updates.items()):
            alias_name = f"#k{i}"
            alias_value = f":v{i}"
            expr_parts.append(f"{alias_name} = {alias_value}")
            expr_names[alias_name] = key
            if isinstance(value, datetime):
                value = value.isoformat()
            expr_values[alias_value] = value

        update_expression = "SET " + ", ".join(expr_parts)

        try:
            await self._conv_table.update_item(
                Key={"PK": pk, "SK": sk},
                UpdateExpression=update_expression,
                ExpressionAttributeNames=expr_names,
                ExpressionAttributeValues=expr_values,
            )
        except (ClientError, BotoCoreError, Exception) as exc:
            self.logger.warning(
                "DynamoDB update_thread failed for session %s: %s", session_id, exc
            )

    async def query_threads(
        self,
        user_id: str,
        agent_id: str,
        limit: int = 50,
    ) -> List[dict]:
        """List thread metadata items for a user+agent pair.

        Args:
            user_id: User identifier.
            agent_id: Agent/bot identifier.
            limit: Maximum number of threads to return.

        Returns:
            List of thread metadata dicts, newest first.
        """
        if not self.is_connected:
            return []
        pk = self._build_pk(user_id, agent_id)
        try:
            from boto3.dynamodb.conditions import Key as DKey, Attr
            response = await self._conv_table.query(
                KeyConditionExpression=DKey("PK").eq(pk) & DKey("SK").begins_with("THREAD#"),
                FilterExpression=Attr("type").eq("thread"),
                ScanIndexForward=False,
                Limit=limit,
            )
            return response.get("Items", [])
        except (ClientError, BotoCoreError, Exception) as exc:
            self.logger.warning(
                "DynamoDB query_threads failed for user %s: %s", user_id, exc
            )
            return []

    # ------------------------------------------------------------------
    # Conversations table — Turns
    # ------------------------------------------------------------------

    async def put_turn(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        turn_id: str,
        data: dict,
    ) -> None:
        """Store a conversation turn.

        Args:
            user_id: User identifier.
            agent_id: Agent/bot identifier.
            session_id: Conversation session identifier.
            turn_id: Turn identifier (e.g. "001", "002").
            data: Turn payload (user_message, assistant_response, etc.).
        """
        if not self.is_connected:
            return
        pk = self._build_pk(user_id, agent_id)
        sk = f"THREAD#{session_id}#TURN#{turn_id}"
        now = self._now()
        timestamp = data.get("timestamp", now)
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        item = {
            "PK": pk,
            "SK": sk,
            "type": "turn",
            "session_id": session_id,
            "turn_id": turn_id,
            "ttl": self._ttl_epoch(timestamp, self.DEFAULT_TTL_DAYS),
            **data,
        }
        # Ensure datetimes are ISO strings
        for key in ("timestamp", "created_at", "updated_at"):
            if key in item and isinstance(item[key], datetime):
                item[key] = item[key].isoformat()
        try:
            await self._conv_table.put_item(Item=item)
        except (ClientError, BotoCoreError, Exception) as exc:
            self.logger.warning(
                "DynamoDB put_turn failed for session %s turn %s: %s",
                session_id, turn_id, exc,
            )

    async def query_turns(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        limit: int = 10,
        newest_first: bool = True,
    ) -> List[dict]:
        """Query conversation turns for a session.

        Args:
            user_id: User identifier.
            agent_id: Agent/bot identifier.
            session_id: Conversation session identifier.
            limit: Maximum number of turns to return.
            newest_first: If True, return newest turns first.

        Returns:
            List of turn dicts.
        """
        if not self.is_connected:
            return []
        pk = self._build_pk(user_id, agent_id)
        prefix = f"THREAD#{session_id}#TURN#"
        try:
            from boto3.dynamodb.conditions import Key as DKey
            response = await self._conv_table.query(
                KeyConditionExpression=DKey("PK").eq(pk) & DKey("SK").begins_with(prefix),
                ScanIndexForward=not newest_first,
                Limit=limit,
            )
            return response.get("Items", [])
        except (ClientError, BotoCoreError, Exception) as exc:
            self.logger.warning(
                "DynamoDB query_turns failed for session %s: %s", session_id, exc
            )
            return []

    async def delete_thread_cascade(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
    ) -> int:
        """Delete all items for a session from the conversations table.

        Queries all items with the session prefix and batch-deletes them.

        Args:
            user_id: User identifier.
            agent_id: Agent/bot identifier.
            session_id: Conversation session identifier.

        Returns:
            Number of items deleted.
        """
        if not self.is_connected:
            return 0
        pk = self._build_pk(user_id, agent_id)
        prefix = f"THREAD#{session_id}"
        deleted = 0
        try:
            from boto3.dynamodb.conditions import Key as DKey
            # Query all items for this session (thread meta + turns)
            response = await self._conv_table.query(
                KeyConditionExpression=DKey("PK").eq(pk) & DKey("SK").begins_with(prefix),
                ProjectionExpression="PK, SK",
            )
            items = response.get("Items", [])

            # Handle pagination
            while response.get("LastEvaluatedKey"):
                response = await self._conv_table.query(
                    KeyConditionExpression=DKey("PK").eq(pk) & DKey("SK").begins_with(prefix),
                    ProjectionExpression="PK, SK",
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                items.extend(response.get("Items", []))

            # Batch delete (max 25 per batch)
            for i in range(0, len(items), 25):
                batch = items[i:i + 25]
                async with self._conv_table.batch_writer() as writer:
                    for item in batch:
                        await writer.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})
                        deleted += 1

        except (ClientError, BotoCoreError, Exception) as exc:
            self.logger.warning(
                "DynamoDB delete_thread_cascade failed for session %s: %s",
                session_id, exc,
            )
        return deleted

    # ------------------------------------------------------------------
    # Artifacts table
    # ------------------------------------------------------------------

    async def put_artifact(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        artifact_id: str,
        data: dict,
    ) -> None:
        """Store an artifact item.

        Args:
            user_id: User identifier.
            agent_id: Agent/bot identifier.
            session_id: Conversation session identifier.
            artifact_id: Artifact identifier.
            data: Artifact payload dict.
        """
        if not self.is_connected:
            return
        pk = self._build_pk(user_id, agent_id)
        sk = f"THREAD#{session_id}#{artifact_id}"
        now = self._now()
        updated_at = data.get("updated_at", now)
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)
        item = {
            "PK": pk,
            "SK": sk,
            "type": "artifact",
            "session_id": session_id,
            "artifact_id": artifact_id,
            "ttl": self._ttl_epoch(updated_at, self.DEFAULT_TTL_DAYS),
            **data,
        }
        # Ensure datetimes are ISO strings
        for key in ("created_at", "updated_at"):
            if key in item and isinstance(item[key], datetime):
                item[key] = item[key].isoformat()
        try:
            await self._art_table.put_item(Item=item)
        except (ClientError, BotoCoreError, Exception) as exc:
            self.logger.warning(
                "DynamoDB put_artifact failed for %s/%s: %s",
                session_id, artifact_id, exc,
            )

    async def get_artifact(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        artifact_id: str,
    ) -> Optional[dict]:
        """Get a single artifact by its key.

        Args:
            user_id: User identifier.
            agent_id: Agent/bot identifier.
            session_id: Conversation session identifier.
            artifact_id: Artifact identifier.

        Returns:
            Artifact dict or None if not found.
        """
        if not self.is_connected:
            return None
        pk = self._build_pk(user_id, agent_id)
        sk = f"THREAD#{session_id}#{artifact_id}"
        try:
            response = await self._art_table.get_item(Key={"PK": pk, "SK": sk})
            return response.get("Item")
        except (ClientError, BotoCoreError, Exception) as exc:
            self.logger.warning(
                "DynamoDB get_artifact failed for %s/%s: %s",
                session_id, artifact_id, exc,
            )
            return None

    async def query_artifacts(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
    ) -> List[dict]:
        """List all artifacts for a session.

        Args:
            user_id: User identifier.
            agent_id: Agent/bot identifier.
            session_id: Conversation session identifier.

        Returns:
            List of artifact dicts.
        """
        if not self.is_connected:
            return []
        pk = self._build_pk(user_id, agent_id)
        prefix = f"THREAD#{session_id}#"
        try:
            from boto3.dynamodb.conditions import Key as DKey
            response = await self._art_table.query(
                KeyConditionExpression=DKey("PK").eq(pk) & DKey("SK").begins_with(prefix),
            )
            items = response.get("Items", [])

            # Handle pagination
            while response.get("LastEvaluatedKey"):
                response = await self._art_table.query(
                    KeyConditionExpression=DKey("PK").eq(pk) & DKey("SK").begins_with(prefix),
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                items.extend(response.get("Items", []))
            return items
        except (ClientError, BotoCoreError, Exception) as exc:
            self.logger.warning(
                "DynamoDB query_artifacts failed for session %s: %s",
                session_id, exc,
            )
            return []

    async def delete_artifact(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        artifact_id: str,
    ) -> None:
        """Delete a single artifact.

        Args:
            user_id: User identifier.
            agent_id: Agent/bot identifier.
            session_id: Conversation session identifier.
            artifact_id: Artifact identifier.
        """
        if not self.is_connected:
            return
        pk = self._build_pk(user_id, agent_id)
        sk = f"THREAD#{session_id}#{artifact_id}"
        try:
            await self._art_table.delete_item(Key={"PK": pk, "SK": sk})
        except (ClientError, BotoCoreError, Exception) as exc:
            self.logger.warning(
                "DynamoDB delete_artifact failed for %s/%s: %s",
                session_id, artifact_id, exc,
            )

    async def delete_session_artifacts(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
    ) -> int:
        """Delete all artifacts for a session.

        Args:
            user_id: User identifier.
            agent_id: Agent/bot identifier.
            session_id: Conversation session identifier.

        Returns:
            Number of artifacts deleted.
        """
        if not self.is_connected:
            return 0
        pk = self._build_pk(user_id, agent_id)
        prefix = f"THREAD#{session_id}#"
        deleted = 0
        try:
            from boto3.dynamodb.conditions import Key as DKey
            response = await self._art_table.query(
                KeyConditionExpression=DKey("PK").eq(pk) & DKey("SK").begins_with(prefix),
                ProjectionExpression="PK, SK",
            )
            items = response.get("Items", [])

            # Handle pagination
            while response.get("LastEvaluatedKey"):
                response = await self._art_table.query(
                    KeyConditionExpression=DKey("PK").eq(pk) & DKey("SK").begins_with(prefix),
                    ProjectionExpression="PK, SK",
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                items.extend(response.get("Items", []))

            # Batch delete
            for i in range(0, len(items), 25):
                batch = items[i:i + 25]
                async with self._art_table.batch_writer() as writer:
                    for item in batch:
                        await writer.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})
                        deleted += 1

        except (ClientError, BotoCoreError, Exception) as exc:
            self.logger.warning(
                "DynamoDB delete_session_artifacts failed for session %s: %s",
                session_id, exc,
            )
        return deleted
