"""DynamoDB backend implementing ConversationBackend.

Moved from parrot/storage/dynamodb.py in FEAT-116. Behavior is byte-identical
to the original; the only additions are:
  - Subclass of ``ConversationBackend`` ABC.
  - New ``delete_turn()`` method (extracted from ``chat.py:572-582``).
  - Override of ``build_overflow_prefix()`` to preserve existing S3 key layout.

FEAT-116: dynamodb-fallback-redis — Module 3 (ConversationDynamoDB refactor).
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import aioboto3
from botocore.exceptions import ClientError, BotoCoreError
from boto3.dynamodb.conditions import Attr, Key as DKey
from navconfig.logging import logging

from parrot.storage.backends.base import BackfillBatch, ConversationBackend
from parrot.storage.errors import (
    ConversationDeletedError,
    IndexNotReadyError,
    InvalidTurnPayloadError,
    StorageUnavailableError,
    StorageWriteError,
)

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_ONE_US = timedelta(microseconds=1)
_TS_WIDTH, _SEQ_WIDTH = 20, 12
_RESERVED_KEYS = frozenset({"PK", "SK", "type", "session_id", "turn_id", "ttl", "chrono_sk"})
_INTERNAL_KEYS = ("PK", "SK", "type", "ttl", "chrono_sk")


class _OrderingRace(Exception):
    """Internal: the canonical turn appeared between our read and our write — re-read and retry."""


def _chrono_fields(data: dict) -> Tuple[Optional[int], int]:
    """Return ``(timestamp_microseconds_utc, sequence)`` from a payload or stored item."""
    raw = data.get("timestamp")
    ts: Optional[datetime] = None
    if isinstance(raw, datetime):
        ts = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            ts = datetime.fromisoformat(raw.strip())
        except ValueError:
            ts = None
    micros: Optional[int] = None
    if ts is not None:
        ts = (ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts).astimezone(timezone.utc)
        micros = (ts - _EPOCH) // _ONE_US
        micros = micros if micros >= 0 else None
    seq = data.get("sequence")
    if isinstance(seq, Decimal):
        seq = int(seq)
    valid_seq = isinstance(seq, int) and not isinstance(seq, bool) and seq >= 0
    return micros, (seq if valid_seq else 0)


def _chrono_sk(session_id: str, micros: int, seq: int, turn_id: str) -> str:
    """Companion sort key: fixed-width timestamp and sequence so lexical order == chronological order."""
    if micros >= 10 ** _TS_WIDTH or seq >= 10 ** _SEQ_WIDTH:
        raise InvalidTurnPayloadError(f"turn {turn_id}: timestamp/sequence out of range for the chrono key")
    return f"THREAD#{session_id}#CHRONO#{micros:0{_TS_WIDTH}d}#{seq:0{_SEQ_WIDTH}d}#{turn_id}"


def _to_dynamo(value: Any) -> Any:
    """Recursively make ``value`` storable: ``float`` → ``Decimal`` (NaN/inf → ``None``), datetimes → ISO."""
    if isinstance(value, bool) or value is None or isinstance(value, (int, str, Decimal)):
        return value
    if isinstance(value, float):
        return Decimal(str(value)) if value == value and value not in (float("inf"), float("-inf")) else None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _to_dynamo(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_dynamo(v) for v in value]
    return str(value)


def _from_dynamo(value: Any) -> Any:
    """Recursively turn ``Decimal`` back into ``int`` (when integral) or ``float``."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _from_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_from_dynamo(v) for v in value]
    return value


class ConversationDynamoDB(ConversationBackend):
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
        """Open aioboto3 resource connections to both tables (idempotent)."""
        # Fix #9: guard against double-initialization to avoid resource leaks
        if self._conv_table is not None and self._art_table is not None:
            return
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
        except Exception as exc:
            # Broad catch intentional: DynamoDB may be unreachable on startup.
            # The backend enters a gracefully-degraded mode (is_connected=False)
            # rather than crashing the process.
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
        """Calculate TTL epoch seconds from a datetime."""
        return int((updated_at + timedelta(days=days)).timestamp())

    @staticmethod
    def _sk_turn(session_id: str, turn_id: str) -> str:
        return f"THREAD#{session_id}#TURN#{turn_id}"

    @staticmethod
    def _sk_tomb(session_id: str, turn_id: Optional[str] = None) -> str:
        """Tombstone SKs deliberately live OUTSIDE ``THREAD#<session>`` so the cascade cannot delete them."""
        return f"TOMB#{session_id}" if turn_id is None else f"TOMB#{session_id}#TURN#{turn_id}"

    @staticmethod
    def _sk_state(session_id: str) -> str:
        return f"INDEXSTATE#{session_id}"

    def _require_connection(self) -> None:
        """Raise ``StorageUnavailableError`` when the backend is not connected."""
        if not self.is_connected:
            raise StorageUnavailableError("DynamoDB conversation backend is not connected")

    def _require_resource(self) -> Any:
        """The boto resource (needed for transactions and batch reads), or ``StorageUnavailableError``."""
        if self._resource is None:
            raise StorageUnavailableError("DynamoDB resource is not available")
        return self._resource

    async def _get_item(self, pk: str, sk: str) -> Optional[dict]:
        """Strongly consistent ``GetItem``; transport/API failures are ``StorageUnavailableError``."""
        try:
            response = await self._conv_table.get_item(Key={"PK": pk, "SK": sk}, ConsistentRead=True)
        except (ClientError, BotoCoreError) as exc:
            raise StorageUnavailableError(f"DynamoDB get_item failed for {sk}: {exc}") from exc
        return response.get("Item") or None

    async def _has_unindexed(self, pk: str, session_id: str) -> bool:
        """Whether any turn item of the session lacks ``chrono_sk`` (session-bounded paginated Query)."""
        kwargs: Dict[str, Any] = {
            "KeyConditionExpression": DKey("PK").eq(pk) & DKey("SK").begins_with(f"THREAD#{session_id}#TURN#"),
            "FilterExpression": Attr("chrono_sk").not_exists(),
            "ProjectionExpression": "SK",
            "ConsistentRead": True,
        }
        try:
            while True:
                response = await self._conv_table.query(**kwargs)
                if response.get("Items"):
                    return True
                if not response.get("LastEvaluatedKey"):
                    return False
                kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        except (ClientError, BotoCoreError) as exc:
            raise StorageUnavailableError(f"DynamoDB index-state probe failed: {exc}") from exc

    async def _transact(self, labelled: List[Tuple[str, dict]]) -> None:
        """Run ``TransactWriteItems``; decode cancellations into typed errors (labels are positional)."""
        try:
            await self._require_resource().meta.client.transact_write_items(
                TransactItems=[item for _, item in labelled])
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "TransactionCanceledException":
                self._raise_for_cancellation(exc, [label for label, _ in labelled])
            raise StorageWriteError(f"DynamoDB transaction failed: {exc}") from exc
        except BotoCoreError as exc:
            raise StorageUnavailableError(f"DynamoDB transport failure: {exc}") from exc

    @staticmethod
    def _raise_for_cancellation(exc: ClientError, labels: List[str]) -> None:
        reasons = exc.response.get("CancellationReasons") or []
        codes = [r.get("Code") for r in reasons]
        for label, code in zip(labels, codes):
            if code != "ConditionalCheckFailed":
                continue
            if label.startswith("tombstone"):
                raise ConversationDeletedError("session or turn is tombstoned; write rejected") from exc
            if label == "canonical":
                raise _OrderingRace() from exc
        raise StorageWriteError(f"DynamoDB transaction cancelled: {codes}") from exc

    def _now(self) -> datetime:
        """Return current UTC datetime."""
        return datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # Overflow prefix (overrides ABC default to preserve S3 layout)
    # ------------------------------------------------------------------

    def build_overflow_prefix(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        artifact_id: str,
    ) -> str:
        """Return the S3 key prefix, byte-identical to the original layout.

        Preserves the existing ``artifacts/USER#u#AGENT#a/THREAD#s/aid``
        layout so existing S3 artifacts remain readable.
        """
        return (
            f"artifacts/{self._build_pk(user_id, agent_id)}"
            f"/THREAD#{session_id}/{artifact_id}"
        )

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
        """Create or replace a thread metadata item."""
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
        for key in ("created_at", "updated_at"):
            if key in item and isinstance(item[key], datetime):
                item[key] = item[key].isoformat()
        try:
            await self._conv_table.put_item(Item=item)
        except (ClientError, BotoCoreError) as exc:
            # Fix #10: removed bare Exception — only catch known DynamoDB errors
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
        """Update specific attributes on a thread metadata item."""
        if not self.is_connected or not updates:
            return
        pk = self._build_pk(user_id, agent_id)
        sk = f"THREAD#{session_id}"

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
        except (ClientError, BotoCoreError) as exc:
            self.logger.warning(
                "DynamoDB update_thread failed for session %s: %s", session_id, exc
            )

    async def query_threads(
        self,
        user_id: str,
        agent_id: str,
        limit: int = 50,
    ) -> List[dict]:
        """List thread metadata items for a user+agent pair, newest first.

        Fix #5: DynamoDB applies ``Limit`` before ``FilterExpression`` — a naïve
        ``Limit=limit`` query can return fewer items than requested even when
        more matching items exist.  We paginate until we have enough filtered
        results or exhaust the index.
        """
        if not self.is_connected:
            return []
        pk = self._build_pk(user_id, agent_id)
        try:
            from boto3.dynamodb.conditions import Key as DKey, Attr  # noqa: E501 pylint: disable=import-outside-toplevel
            items: List[dict] = []
            last_key = None
            while len(items) < limit:
                kwargs: Dict[str, Any] = {
                    "KeyConditionExpression": (
                        DKey("PK").eq(pk) & DKey("SK").begins_with("THREAD#")
                    ),
                    "FilterExpression": Attr("type").eq("thread"),
                    "ScanIndexForward": False,
                }
                if last_key:
                    kwargs["ExclusiveStartKey"] = last_key
                response = await self._conv_table.query(**kwargs)
                items.extend(response.get("Items", []))
                last_key = response.get("LastEvaluatedKey")
                if not last_key:
                    break
            return items[:limit]
        except (ClientError, BotoCoreError) as exc:
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
        """Idempotent transactional upsert of a turn and its chronological companion.

        Raises:
            StorageUnavailableError: not connected / transport failure.
            ConversationDeletedError: the session or this turn is tombstoned (nothing is written).
            InvalidTurnPayloadError: timestamp/sequence outside the chrono key range.
            StorageWriteError: the transaction failed (nothing is swallowed).
        """
        self._require_connection()
        pk = self._build_pk(user_id, agent_id)
        for _ in range(3):
            existing = await self._get_item(pk, self._sk_turn(session_id, turn_id))
            marker = await self._get_item(pk, self._sk_state(session_id))
            payload, micros, seq = self._resolve_ordering(data, existing)
            state_op = await self._state_op(pk, session_id, marker, indexed=micros is not None)
            items = self._plan_put(pk, session_id, turn_id, payload, micros, seq, existing, state_op)
            try:
                await self._transact(items)
                return
            except _OrderingRace:
                continue  # a concurrent first write won: re-read, reuse its ordering
        raise StorageWriteError(f"turn {turn_id}: lost the ordering race 3 times")

    @staticmethod
    def _resolve_ordering(data: dict, existing: Optional[dict]) -> Tuple[dict, Optional[int], int]:
        """Payload to store + the ordering to use (an existing turn's ordering always wins)."""
        payload = {k: (v.isoformat() if isinstance(v, datetime) else v)
                   for k, v in data.items() if k not in _RESERVED_KEYS}
        micros, seq = _chrono_fields(data)
        if existing is not None:
            e_micros, e_seq = _chrono_fields(existing)
            if e_micros is not None:
                micros, seq = e_micros, e_seq
                for name in ("timestamp", "sequence"):
                    if name in existing:
                        payload[name] = _from_dynamo(existing[name])
                    else:
                        payload.pop(name, None)
        return payload, micros, seq

    async def _state_op(self, pk: str, session_id: str, marker: Optional[dict], *, indexed: bool):
        """Marker update this write needs: ``None``, ``('set', state)`` or ``('init', state)``."""
        current = marker.get("state") if marker else None
        if not indexed:
            return None if current == "invalid" else ("set", "pending")
        if current is not None:
            return None
        return ("init", "pending" if await self._has_unindexed(pk, session_id) else "ready")

    def _plan_put(self, pk, session_id, turn_id, payload, micros, seq, existing, state_op):
        """Positional ``[(label, transact_item)]`` — see ``_raise_for_cancellation``."""
        table = self._conversations_table
        chrono_sk = _chrono_sk(session_id, micros, seq, turn_id) if micros is not None else None
        ts = _EPOCH + timedelta(microseconds=micros) if micros is not None else self._now()
        ttl = self._ttl_epoch(ts, self.DEFAULT_TTL_DAYS)
        item = {**_to_dynamo(payload), "PK": pk, "SK": self._sk_turn(session_id, turn_id), "type": "turn",
                "session_id": session_id, "turn_id": turn_id, "ttl": ttl}
        if chrono_sk is not None:
            item["chrono_sk"] = chrono_sk
        canonical: Dict[str, Any] = {"TableName": table, "Item": item}
        if existing is None:
            canonical["ConditionExpression"] = "attribute_not_exists(PK)"
        absent = "attribute_not_exists(PK)"
        planned = [
            ("tombstone-session", {"ConditionCheck": {"TableName": table, "ConditionExpression": absent,
                                   "Key": {"PK": pk, "SK": self._sk_tomb(session_id)}}}),
            ("tombstone-turn", {"ConditionCheck": {"TableName": table, "ConditionExpression": absent,
                                "Key": {"PK": pk, "SK": self._sk_tomb(session_id, turn_id)}}}),
            ("canonical", {"Put": canonical}),
        ]
        if chrono_sk is not None:
            companion = {"PK": pk, "SK": chrono_sk, "type": "chrono", "session_id": session_id,
                         "turn_id": turn_id, "timestamp": payload.get("timestamp"), "sequence": seq, "ttl": ttl}
            planned.append(("companion", {"Put": {"TableName": table, "Item": _to_dynamo(companion)}}))
        if state_op is not None:
            planned.append(("state", {"Update": self._state_update(pk, session_id, *state_op)}))
        return planned

    def _state_update(self, pk: str, session_id: str, mode: str, state: str) -> dict:
        """``set`` overwrites the state; ``init`` only fills an absent one. No ``ttl`` attribute, ever."""
        assign = "#s = :v" if mode == "set" else "#s = if_not_exists(#s, :v)"
        return {
            "TableName": self._conversations_table,
            "Key": {"PK": pk, "SK": self._sk_state(session_id)},
            "UpdateExpression": f"SET {assign}, #u = :now, #t = :t",
            "ExpressionAttributeNames": {"#s": "state", "#u": "updated_at", "#t": "type"},
            "ExpressionAttributeValues": {":v": state, ":now": self._now().isoformat(), ":t": "index_state"},
        }

    async def query_turns(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        limit: int = 10,
        newest_first: bool = True,
    ) -> List[dict]:
        """Query conversation turns for a session."""
        self._require_connection()
        pk = self._build_pk(user_id, agent_id)
        prefix = f"THREAD#{session_id}#TURN#"
        try:
            response = await self._conv_table.query(
                KeyConditionExpression=DKey("PK").eq(pk) & DKey("SK").begins_with(prefix),
                ScanIndexForward=not newest_first,
                Limit=limit,
            )
            return response.get("Items", [])
        except (ClientError, BotoCoreError) as exc:
            raise StorageUnavailableError(f"DynamoDB query_turns failed for session {session_id}: {exc}") from exc

    async def delete_turn(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        turn_id: str,
    ) -> bool:
        """Delete a single conversation turn.

        Fix #1: Use ``ReturnValues='ALL_OLD'`` so we can detect whether the item
        actually existed.  DynamoDB's ``delete_item`` is silent on missing keys
        without this flag — it would always return ``True`` when connected.

        Returns:
            True if the item existed and was deleted, False otherwise.
        """
        if not self.is_connected:
            return False
        pk = self._build_pk(user_id, agent_id)
        sk = f"THREAD#{session_id}#TURN#{turn_id}"
        try:
            response = await self._conv_table.delete_item(
                Key={"PK": pk, "SK": sk},
                ReturnValues="ALL_OLD",
            )
            attrs = response.get("Attributes")
            if attrs and attrs.get("chrono_sk"):
                await self._delete_companion(pk, attrs["chrono_sk"])
            return bool(attrs)
        except (ClientError, BotoCoreError) as exc:
            self.logger.warning(
                "DynamoDB delete_turn failed for %s: %s", turn_id, exc,
            )
            return False

    async def _delete_companion(self, pk: str, chrono_sk: str) -> None:
        """Best-effort: an orphan companion is harmless (the window skips companions without a canonical turn)."""
        try:
            await self._conv_table.delete_item(Key={"PK": pk, "SK": chrono_sk})
        except (ClientError, BotoCoreError) as exc:
            self.logger.warning("DynamoDB could not delete companion %s: %s", chrono_sk, exc)

    # ------------------------------------------------------------------
    # FEAT-886: ordered window, tombstones, index state, backfill
    # ------------------------------------------------------------------

    async def query_turn_window(
        self, user_id: str, agent_id: str, session_id: str, limit: int
    ) -> List[dict]:
        """Newest ``limit`` turns by (timestamp, sequence, turn_id), limit applied descending, returned ascending."""
        self._require_connection()
        if await self.is_deleted(user_id, agent_id, session_id):
            raise ConversationDeletedError(f"session {session_id} is tombstoned")
        if await self.get_index_state(user_id, agent_id, session_id) != "ready":
            raise IndexNotReadyError(f"chronological index of session {session_id} is not ready")
        if limit <= 0:
            return []
        pk = self._build_pk(user_id, agent_id)
        kwargs: Dict[str, Any] = {
            "KeyConditionExpression": DKey("PK").eq(pk) & DKey("SK").begins_with(f"THREAD#{session_id}#CHRONO#"),
            "ScanIndexForward": False, "Limit": limit, "ConsistentRead": True,
        }
        newest_first: List[dict] = []
        try:
            while len(newest_first) < limit:
                page = await self._conv_table.query(**kwargs)
                newest_first.extend(await self._load_turns(pk, session_id, page.get("Items", []),
                                                           limit - len(newest_first)))
                if not page.get("LastEvaluatedKey"):
                    break
                kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
        except (ClientError, BotoCoreError) as exc:
            raise StorageUnavailableError(f"DynamoDB query_turn_window failed: {exc}") from exc
        newest_first.reverse()
        return newest_first

    async def _load_turns(self, pk: str, session_id: str, companions: List[dict], room: int) -> List[dict]:
        """Resolve companions to canonical turns (newest first), dropping orphans and tombstoned turns."""
        found: Dict[str, dict] = {}
        for start in range(0, len(companions), 50):  # 2 keys per turn -> <= 100 per request
            chunk = companions[start:start + 50]
            keys = [{"PK": pk, "SK": self._sk_turn(session_id, c["turn_id"])} for c in chunk]
            keys += [{"PK": pk, "SK": self._sk_tomb(session_id, c["turn_id"])} for c in chunk]
            found.update(await self._batch_get(keys))
        turns: List[dict] = []
        for comp in companions:
            turn = found.get(self._sk_turn(session_id, comp["turn_id"]))
            if turn is None or self._sk_tomb(session_id, comp["turn_id"]) in found:
                continue  # orphan companion / tombstoned turn
            turns.append({k: _from_dynamo(v) for k, v in turn.items() if k not in _INTERNAL_KEYS})
            if len(turns) == room:
                break
        return turns

    async def _batch_get(self, keys: List[dict]) -> Dict[str, dict]:
        """``BatchGetItem`` (consistent) with bounded retry of ``UnprocessedKeys``; maps SK -> item."""
        table, out = self._conversations_table, {}
        request = {table: {"Keys": keys, "ConsistentRead": True}}
        for attempt in range(5):
            response = await self._require_resource().batch_get_item(RequestItems=request)
            out.update({i["SK"]: i for i in response.get("Responses", {}).get(table, [])})
            request = response.get("UnprocessedKeys") or {}
            if not request:
                return out
            await asyncio.sleep(0.05 * 2 ** attempt)
        raise StorageUnavailableError("DynamoDB batch_get_item left unprocessed keys")

    async def max_sequence(self, user_id: str, agent_id: str, session_id: str) -> int:
        """Highest stored sequence (companion items; session-bounded paginated Query), ``0`` when none."""
        self._require_connection()
        pk = self._build_pk(user_id, agent_id)
        kwargs: Dict[str, Any] = {
            "KeyConditionExpression": DKey("PK").eq(pk) & DKey("SK").begins_with(f"THREAD#{session_id}#CHRONO#"),
            "ProjectionExpression": "#q", "ExpressionAttributeNames": {"#q": "sequence"},  # SEQUENCE is reserved
            "ConsistentRead": True,
        }
        highest = 0
        try:
            while True:
                page = await self._conv_table.query(**kwargs)
                highest = max([highest] + [int(i.get("sequence", 0)) for i in page.get("Items", [])])
                if not page.get("LastEvaluatedKey"):
                    return highest
                kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
        except (ClientError, BotoCoreError) as exc:
            raise StorageUnavailableError(f"DynamoDB max_sequence failed: {exc}") from exc

    async def put_tombstone(
        self, user_id: str, agent_id: str, session_id: str, turn_id: Optional[str] = None
    ) -> None:
        """Durably record a session (``turn_id=None``) or turn deletion. Idempotent; NO ``ttl`` attribute."""
        self._require_connection()
        if turn_id == "":
            raise ValueError("turn_id must be non-empty (use None for a session tombstone)")
        item = {"PK": self._build_pk(user_id, agent_id), "SK": self._sk_tomb(session_id, turn_id),
                "type": "tombstone", "session_id": session_id, "created_at": self._now().isoformat()}
        if turn_id is not None:
            item["turn_id"] = turn_id
        try:
            await self._conv_table.put_item(Item=item, ConditionExpression="attribute_not_exists(PK)")
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return  # already tombstoned: first created_at wins
            raise StorageWriteError(f"DynamoDB put_tombstone failed: {exc}") from exc
        except BotoCoreError as exc:
            raise StorageUnavailableError(f"DynamoDB transport failure: {exc}") from exc

    async def deleted_turn_ids(self, user_id: str, agent_id: str, session_id: str) -> Set[str]:
        """Every turn-scoped tombstone of the session: ONE paginated, consistent Query (not a GetItem per turn)."""
        self._require_connection()
        kwargs: Dict[str, Any] = {
            "KeyConditionExpression": DKey("PK").eq(self._build_pk(user_id, agent_id))
            & DKey("SK").begins_with(f"TOMB#{session_id}#TURN#"),
            "ProjectionExpression": "turn_id", "ConsistentRead": True,
        }
        gone: Set[str] = set()
        try:
            while True:
                page = await self._conv_table.query(**kwargs)
                gone.update(i["turn_id"] for i in page.get("Items", []) if i.get("turn_id"))
                if not page.get("LastEvaluatedKey"):
                    return gone
                kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
        except (ClientError, BotoCoreError) as exc:
            raise StorageUnavailableError(f"DynamoDB deleted_turn_ids failed: {exc}") from exc

    async def deleted_session_ids(self, user_id: str, agent_id: str, session_ids: Sequence[str]) -> Set[str]:
        """The session-tombstoned members of ``session_ids``: consistent ``BatchGetItem`` of ``TOMB#<session>``
        keys, at most 100 keys per request, ``UnprocessedKeys`` retried by ``_batch_get``."""
        self._require_connection()
        pk = self._build_pk(user_id, agent_id)
        by_sk = {self._sk_tomb(s): s for s in dict.fromkeys(session_ids)}  # BatchGetItem rejects duplicate keys
        sks = list(by_sk)
        found: Dict[str, dict] = {}
        try:
            for start in range(0, len(sks), 100):
                found.update(await self._batch_get([{"PK": pk, "SK": sk} for sk in sks[start : start + 100]]))
        except (ClientError, BotoCoreError) as exc:
            raise StorageUnavailableError(f"DynamoDB deleted_session_ids failed: {exc}") from exc
        return {by_sk[sk] for sk in found if sk in by_sk}

    async def is_deleted(
        self, user_id: str, agent_id: str, session_id: str, turn_id: Optional[str] = None
    ) -> bool:
        """Whether the session (or session OR this turn) is tombstoned; raises when it cannot be determined.

        With ``turn_id`` both tombstone keys are read in ONE consistent ``BatchGetItem`` round trip.
        """
        self._require_connection()
        pk = self._build_pk(user_id, agent_id)
        if turn_id is None:
            return await self._get_item(pk, self._sk_tomb(session_id)) is not None
        keys = [{"PK": pk, "SK": self._sk_tomb(session_id)}, {"PK": pk, "SK": self._sk_tomb(session_id, turn_id)}]
        try:
            return bool(await self._batch_get(keys))
        except (ClientError, BotoCoreError) as exc:
            raise StorageUnavailableError(f"DynamoDB is_deleted failed: {exc}") from exc

    async def get_index_state(self, user_id: str, agent_id: str, session_id: str) -> str:
        """``'ready'`` | ``'pending'`` | ``'invalid'`` (marker fast path, otherwise derived)."""
        self._require_connection()
        pk = self._build_pk(user_id, agent_id)
        marker = await self._get_item(pk, self._sk_state(session_id))
        state = marker.get("state") if marker else None
        if state == "ready" or not await self._has_unindexed(pk, session_id):
            return "ready"
        return "invalid" if state == "invalid" else "pending"

    @staticmethod
    def _split_pk(pk: str) -> Tuple[str, str]:
        user_id, _, agent_id = pk[len("USER#"):].partition("#AGENT#")
        return user_id, agent_id

    async def _index_legacy_item(self, item: dict) -> str:
        """Index one legacy canonical turn: ``'indexed'`` | ``'invalid'`` | ``'skipped'`` (tombstoned / raced)."""
        micros, seq = _chrono_fields(item)
        if micros is None:
            return "invalid"
        pk, session_id, turn_id = item["PK"], item["session_id"], item["turn_id"]
        chrono_sk = _chrono_sk(session_id, micros, seq, turn_id)
        table, absent = self._conversations_table, "attribute_not_exists(PK)"
        companion = {"PK": pk, "SK": chrono_sk, "type": "chrono", "session_id": session_id, "turn_id": turn_id,
                     "timestamp": item.get("timestamp"), "sequence": seq, "ttl": item.get("ttl")}
        labelled = [
            ("tombstone-session", {"ConditionCheck": {"TableName": table, "ConditionExpression": absent,
                                   "Key": {"PK": pk, "SK": self._sk_tomb(session_id)}}}),
            ("tombstone-turn", {"ConditionCheck": {"TableName": table, "ConditionExpression": absent,
                                "Key": {"PK": pk, "SK": self._sk_tomb(session_id, turn_id)}}}),
            ("canonical", {"Update": {"TableName": table, "Key": {"PK": pk, "SK": item["SK"]},
                           "UpdateExpression": "SET chrono_sk = :c",
                           "ConditionExpression": "attribute_not_exists(chrono_sk)",
                           "ExpressionAttributeValues": {":c": chrono_sk}}}),
            ("companion", {"Put": {"TableName": table, "Item": _to_dynamo(companion)}}),
        ]
        try:
            await self._transact(labelled)
        except (ConversationDeletedError, _OrderingRace):
            return "skipped"
        return "indexed"

    async def _finalize_session(self, pk: str, session_id: str, saw_invalid: bool) -> None:
        """Write the marker ``invalid`` / ``ready`` for a session touched by a batch (else leave it pending)."""
        if saw_invalid:
            state = "invalid"
        elif not await self._has_unindexed(pk, session_id):
            state = "ready"
        else:
            return
        await self._conv_table.put_item(Item={"PK": pk, "SK": self._sk_state(session_id), "type": "index_state",
                                              "state": state, "updated_at": self._now().isoformat()})

    async def backfill_batch(self, cursor: Optional[str], batch_size: int) -> BackfillBatch:
        """Index up to ``batch_size`` scanned items after ``cursor`` (resumable; offline, never a request path).

        ``invalid_sessions`` entries are ``"<user_id>/<agent_id>/<session_id>"``; the cursor is the JSON-encoded
        ``LastEvaluatedKey`` of the ``Scan`` page.
        """
        self._require_connection()
        kwargs: Dict[str, Any] = {
            "FilterExpression": Attr("type").eq("turn") & Attr("chrono_sk").not_exists(),
            "Limit": batch_size, "ConsistentRead": True,
        }
        if cursor is not None:
            kwargs["ExclusiveStartKey"] = json.loads(cursor)
        touched: Dict[Tuple[str, str], bool] = {}
        indexed = 0
        try:
            page = await self._conv_table.scan(**kwargs)
            for item in page.get("Items", []):
                outcome = await self._index_legacy_item(item)
                key = (item["PK"], item["session_id"])
                indexed += outcome == "indexed"
                if outcome != "skipped":
                    touched[key] = touched.get(key, False) or outcome == "invalid"
            for (pk, session_id), saw_invalid in touched.items():
                await self._finalize_session(pk, session_id, saw_invalid)
        except (ClientError, BotoCoreError) as exc:
            raise StorageWriteError(f"DynamoDB backfill_batch failed: {exc}") from exc
        invalid = tuple("/".join((*self._split_pk(pk), session)) for (pk, session), bad in touched.items() if bad)
        last = page.get("LastEvaluatedKey")
        return BackfillBatch(processed=indexed, next_cursor=json.dumps(last, default=str) if last else None,
                             invalid_sessions=invalid)

    async def delete_thread_cascade(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
    ) -> int:
        """Delete all items for a session from the conversations table."""
        if not self.is_connected:
            return 0
        pk = self._build_pk(user_id, agent_id)
        prefix = f"THREAD#{session_id}"
        deleted = 0
        try:
            from boto3.dynamodb.conditions import Key as DKey  # noqa: E501 pylint: disable=import-outside-toplevel
            response = await self._conv_table.query(
                KeyConditionExpression=DKey("PK").eq(pk) & DKey("SK").begins_with(prefix),
                ProjectionExpression="PK, SK",
            )
            items = response.get("Items", [])

            while response.get("LastEvaluatedKey"):
                response = await self._conv_table.query(
                    KeyConditionExpression=DKey("PK").eq(pk) & DKey("SK").begins_with(prefix),
                    ProjectionExpression="PK, SK",
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                items.extend(response.get("Items", []))

            for i in range(0, len(items), 25):
                batch = items[i:i + 25]
                async with self._conv_table.batch_writer() as writer:
                    for item in batch:
                        await writer.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})
                        deleted += 1

        except (ClientError, BotoCoreError) as exc:
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
        """Store an artifact item."""
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
        for key in ("created_at", "updated_at"):
            if key in item and isinstance(item[key], datetime):
                item[key] = item[key].isoformat()
        try:
            await self._art_table.put_item(Item=item)
        except (ClientError, BotoCoreError) as exc:
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
        """Get a single artifact by its key."""
        if not self.is_connected:
            return None
        pk = self._build_pk(user_id, agent_id)
        sk = f"THREAD#{session_id}#{artifact_id}"
        try:
            response = await self._art_table.get_item(Key={"PK": pk, "SK": sk})
            return response.get("Item")
        except (ClientError, BotoCoreError) as exc:
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
        """List all artifacts for a session."""
        if not self.is_connected:
            return []
        pk = self._build_pk(user_id, agent_id)
        prefix = f"THREAD#{session_id}#"
        try:
            from boto3.dynamodb.conditions import Key as DKey  # noqa: E501 pylint: disable=import-outside-toplevel
            response = await self._art_table.query(
                KeyConditionExpression=DKey("PK").eq(pk) & DKey("SK").begins_with(prefix),
            )
            items = response.get("Items", [])

            while response.get("LastEvaluatedKey"):
                response = await self._art_table.query(
                    KeyConditionExpression=DKey("PK").eq(pk) & DKey("SK").begins_with(prefix),
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                items.extend(response.get("Items", []))
            return items
        except (ClientError, BotoCoreError) as exc:
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
        """Delete a single artifact."""
        if not self.is_connected:
            return
        pk = self._build_pk(user_id, agent_id)
        sk = f"THREAD#{session_id}#{artifact_id}"
        try:
            await self._art_table.delete_item(Key={"PK": pk, "SK": sk})
        except (ClientError, BotoCoreError) as exc:
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
        """Delete all artifacts for a session."""
        if not self.is_connected:
            return 0
        pk = self._build_pk(user_id, agent_id)
        prefix = f"THREAD#{session_id}#"
        deleted = 0
        try:
            from boto3.dynamodb.conditions import Key as DKey  # noqa: E501 pylint: disable=import-outside-toplevel
            response = await self._art_table.query(
                KeyConditionExpression=DKey("PK").eq(pk) & DKey("SK").begins_with(prefix),
                ProjectionExpression="PK, SK",
            )
            items = response.get("Items", [])

            while response.get("LastEvaluatedKey"):
                response = await self._art_table.query(
                    KeyConditionExpression=DKey("PK").eq(pk) & DKey("SK").begins_with(prefix),
                    ProjectionExpression="PK, SK",
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                items.extend(response.get("Items", []))

            for i in range(0, len(items), 25):
                batch = items[i:i + 25]
                async with self._art_table.batch_writer() as writer:
                    for item in batch:
                        await writer.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})
                        deleted += 1

        except (ClientError, BotoCoreError) as exc:
            self.logger.warning(
                "DynamoDB delete_session_artifacts failed for session %s: %s",
                session_id, exc,
            )
        return deleted
