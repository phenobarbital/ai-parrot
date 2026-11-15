"""Data models for chat persistence.

Dedicated models that capture the full interaction payload
(user input, agent output, metadata, tool calls, sources, timing).

Also contains Pydantic models for artifact and thread persistence
(FEAT-103: agent-artifact-persistency).
"""

import json
from decimal import Decimal
from typing import List, Dict, Any, Mapping, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from parrot.memory.abstract import ConversationTurn
from parrot.memory.compaction.models import TokenCount, ToolInvocation, ToolStatus, TurnState
from parrot.memory.persistence import TurnPresentation
from .errors import InvalidTurnPayloadError


class MessageRole(str, Enum):
    """Role of the message sender."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


@dataclass
class ToolCall:
    """A single tool invocation within a turn."""
    name: str
    status: str = "completed"
    output: Optional[Any] = None
    arguments: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "name": self.name,
            "status": self.status,
            "output": self.output,
            "arguments": self.arguments,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolCall":
        """Deserialize from dictionary."""
        return cls(
            name=data.get("name", "unknown"),
            status=data.get("status", "completed"),
            output=data.get("output"),
            arguments=data.get("arguments"),
        )


@dataclass
class Source:
    """A source/reference returned by the agent."""
    content: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {"content": self.content, "metadata": self.metadata}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Source":
        """Deserialize from dictionary."""
        return cls(
            content=data.get("content", ""),
            metadata=data.get("metadata", {}),
        )


@dataclass
class ChatMessage:
    """Represents a single chat message (one direction: user OR assistant).

    This is the atomic persistence unit — one document per message in
    DocumentDB and one entry per message in the Redis turn list.
    """
    message_id: str
    session_id: str
    user_id: str
    agent_id: str
    role: str  # MessageRole value
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    # Agent-response specific fields (empty for user messages)
    output: Optional[Any] = None
    output_mode: Optional[str] = None
    data: Optional[Any] = None
    code: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    response_time_ms: Optional[int] = None
    tool_calls: List[ToolCall] = field(default_factory=list)
    sources: List[Source] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary suitable for DocumentDB storage."""
        return {
            "message_id": self.message_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "agent_id": self.agent_id,
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat()
            if isinstance(self.timestamp, datetime)
            else str(self.timestamp),
            "output": _safe_serialize(self.output),
            "output_mode": self.output_mode,
            "data": _safe_serialize(self.data),
            "code": self.code,
            "model": self.model,
            "provider": self.provider,
            "response_time_ms": self.response_time_ms,
            "tool_calls": [tc.to_dict() for tc in self.tool_calls],
            "sources": [s.to_dict() for s in self.sources],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatMessage":
        """Deserialize from dictionary."""
        ts = data.get("timestamp")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        elif not isinstance(ts, datetime):
            ts = datetime.now()

        return cls(
            message_id=data["message_id"],
            session_id=data["session_id"],
            user_id=data["user_id"],
            agent_id=data.get("agent_id", ""),
            role=data.get("role", MessageRole.ASSISTANT.value),
            content=data.get("content", ""),
            timestamp=ts,
            output=data.get("output"),
            output_mode=data.get("output_mode"),
            data=data.get("data"),
            code=data.get("code"),
            model=data.get("model"),
            provider=data.get("provider"),
            response_time_ms=data.get("response_time_ms"),
            tool_calls=[
                ToolCall.from_dict(tc)
                for tc in data.get("tool_calls", [])
            ],
            sources=[
                Source.from_dict(s) for s in data.get("sources", [])
            ],
            metadata=data.get("metadata", {}),
        )


@dataclass
class Conversation:
    """Conversation metadata — one document per session in DocumentDB.

    Tracks the lifecycle of a conversation session: when it started,
    when the last message was sent, token counts, title, etc.
    """
    session_id: str
    user_id: str
    agent_id: str
    title: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    message_count: int = 0
    last_user_message: Optional[str] = None
    last_assistant_message: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary suitable for DocumentDB storage."""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "agent_id": self.agent_id,
            "title": self.title,
            "created_at": self.created_at.isoformat()
            if isinstance(self.created_at, datetime)
            else str(self.created_at),
            "updated_at": self.updated_at.isoformat()
            if isinstance(self.updated_at, datetime)
            else str(self.updated_at),
            "message_count": self.message_count,
            "last_user_message": self.last_user_message,
            "last_assistant_message": self.last_assistant_message,
            "model": self.model,
            "provider": self.provider,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Conversation":
        """Deserialize from dictionary."""
        def _parse_dt(val: Any) -> datetime:
            if isinstance(val, datetime):
                return val
            if isinstance(val, str):
                return datetime.fromisoformat(val)
            return datetime.now()

        return cls(
            session_id=data["session_id"],
            user_id=data["user_id"],
            agent_id=data.get("agent_id", ""),
            title=data.get("title"),
            created_at=_parse_dt(data.get("created_at")),
            updated_at=_parse_dt(data.get("updated_at")),
            message_count=data.get("message_count", 0),
            last_user_message=data.get("last_user_message"),
            last_assistant_message=data.get("last_assistant_message"),
            model=data.get("model"),
            provider=data.get("provider"),
            metadata=data.get("metadata", {}),
        )


def _safe_serialize(obj: Any) -> Any:
    """Convert complex objects to serializable form."""
    if obj is None:
        return None
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "to_json"):
        return obj.to_json()
    try:
        # Covers primitives, lists, dicts
        return obj
    except Exception:
        return str(obj)


# ---------------------------------------------------------------------------
# Pydantic Models for Artifact & Thread Persistence (FEAT-103)
# ---------------------------------------------------------------------------


class ArtifactType(str, Enum):
    """Type of artifact produced by an agent or user."""
    CHART = "chart"
    MAP = "map"
    TABLE = "table"          # FEAT-224: structured table output
    CANVAS = "canvas"
    INFOGRAPHIC = "infographic"
    INTERACTIVE = "interactive"  # free-form, self-contained interactive HTML pages
    DATAFRAME = "dataframe"
    EXPORT = "export"


class ArtifactCreator(str, Enum):
    """Who created the artifact."""
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"


class ArtifactSummary(BaseModel):
    """Lightweight artifact reference for thread metadata.

    Used in list endpoints where the full definition is not needed.
    """
    id: str
    type: ArtifactType
    title: str
    created_at: datetime
    updated_at: Optional[datetime] = None


class Artifact(BaseModel):
    """Full artifact with definition payload.

    The ``definition`` field holds the artifact data inline.  For CHART
    artifacts the definition carries a :class:`~parrot.models.outputs.StructuredChartConfig`
    dump (camelCase, ``data`` excluded).  For other artifact types it holds
    the type-specific payload (canvas blocks, infographic response, …).
    When the serialised definition exceeds 200 KB it is offloaded to S3 and
    ``definition_ref`` holds the S3 URI instead.
    """
    artifact_id: str
    artifact_type: ArtifactType
    title: str
    created_at: datetime
    updated_at: datetime
    source_turn_id: Optional[str] = None
    created_by: ArtifactCreator = ArtifactCreator.USER
    definition: Optional[Dict[str, Any]] = None
    definition_ref: Optional[str] = None  # S3 URI if overflow

    @classmethod
    def from_structured_config(
        cls,
        cfg: Any,
        artifact_type: "ArtifactType",
        artifact_id: str,
        title: str,
        created_at: datetime,
        updated_at: datetime,
        **kwargs: Any,
    ) -> "Artifact":
        """Create an Artifact for any structured output type (chart / map / table).

        Serialises *cfg* with camelCase aliases and without the ``data`` key so
        that the wire definition carries only the *presentation config* (rows
        live in ``response.data``).  This is the canonical constructor for the
        ``artifacts[]`` envelope introduced by FEAT-224.

        Args:
            cfg: A ``Structured{Chart,Table,Map}Config`` instance.
            artifact_type: One of :attr:`ArtifactType.CHART`,
                :attr:`ArtifactType.MAP`, or :attr:`ArtifactType.TABLE`.
            artifact_id: Unique artifact identifier (mint once per turn).
            title: Display title for the artifact.
            created_at: Creation timestamp.
            updated_at: Last-updated timestamp.
            **kwargs: Additional :class:`Artifact` fields (e.g. ``source_turn_id``).

        Returns:
            An :class:`Artifact` whose ``definition`` is the camelCase config
            dict with ``data`` excluded.
        """
        return cls(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            title=title,
            created_at=created_at,
            updated_at=updated_at,
            definition=cfg.model_dump(mode="json", by_alias=True, exclude={"data"}),
            **kwargs,
        )

    @classmethod
    def from_chart_config(
        cls,
        cfg: Any,
        artifact_id: str,
        title: str,
        created_at: datetime,
        updated_at: datetime,
        **kwargs: Any,
    ) -> "Artifact":
        """Create a CHART Artifact whose definition carries the converged config.

        Backward-compatible wrapper around :meth:`from_structured_config` — returns
        an identical artifact to the pre-FEAT-224 implementation.

        Args:
            cfg: A :class:`~parrot.models.outputs.StructuredChartConfig` instance.
            artifact_id: Unique artifact identifier.
            title: Display title for the artifact.
            created_at: Creation timestamp.
            updated_at: Last-updated timestamp.
            **kwargs: Additional ``Artifact`` fields (e.g. ``source_turn_id``).

        Returns:
            An :class:`Artifact` of type :attr:`ArtifactType.CHART`.
        """
        return cls.from_structured_config(
            cfg, ArtifactType.CHART, artifact_id, title, created_at, updated_at, **kwargs,
        )

    def as_chart_config(self) -> Any:
        """Parse ``definition`` as a :class:`~parrot.models.outputs.StructuredChartConfig`.

        Returns ``None`` when this is not a CHART artifact, ``definition`` is
        absent, or parsing fails.

        Returns:
            A :class:`~parrot.models.outputs.StructuredChartConfig` on success,
            ``None`` otherwise.
        """
        if self.artifact_type != ArtifactType.CHART or not self.definition:
            return None
        try:
            from parrot.models.outputs import StructuredChartConfig
            return StructuredChartConfig.model_validate(self.definition)
        except Exception:  # noqa: BLE001
            return None


class ThreadMetadata(BaseModel):
    """Conversation thread metadata stored in DynamoDB.

    This is a *new* Pydantic model — it does NOT replace the existing
    ``Conversation`` dataclass which is used by the DocumentDB path.
    """
    session_id: str
    user_id: str
    agent_id: str
    title: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    turn_count: int = 0
    pinned: bool = False
    archived: bool = False
    tags: List[str] = Field(default_factory=list)


class CanvasBlockType(str, Enum):
    """Type of block within a canvas tab."""
    MARKDOWN = "markdown"
    HEADING = "heading"
    CHART_REF = "chart_ref"
    DATA_TABLE = "data_table"
    AGENT_RESPONSE = "agent_response"
    INFOGRAPHIC_REF = "infographic_ref"
    NOTE = "note"
    CODE = "code"
    IMAGE = "image"
    DIVIDER = "divider"


class CanvasBlock(BaseModel):
    """Individual block within a canvas tab."""
    block_id: str
    block_type: CanvasBlockType
    content: Optional[str] = None
    artifact_ref: Optional[str] = None
    source_turn_id: Optional[str] = None
    display_options: Optional[Dict[str, Any]] = None
    position: int = 0


class CanvasDefinition(BaseModel):
    """Complete canvas tab artifact definition."""
    tab_id: str
    title: str
    blocks: List[CanvasBlock] = Field(default_factory=list)
    layout: str = "vertical"
    export_config: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# FEAT-886: ChatStorageTurn — the full audit record of one turn
# ---------------------------------------------------------------------------

_EPOCH_SENTINEL = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _parse_utc(value: Any) -> Optional[datetime]:
    """Parse ``value`` into a tz-aware UTC datetime, or ``None`` when absent/unparseable.

    Naive datetimes and naive ISO strings are interpreted as UTC (spec §7).
    """
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _json_default(obj: Any) -> Any:
    """``json.dumps`` fallback: datetimes, model-ish objects, Decimals, sets/bytes, then ``str``."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    if isinstance(obj, (set, frozenset)):
        return sorted(obj, key=str)
    if isinstance(obj, (bytes, bytearray)):
        return bytes(obj).decode("utf-8", errors="replace")
    for attr in ("model_dump", "to_dict"):
        method = getattr(obj, attr, None)
        if callable(method):
            return method()
    return str(obj)


def _json_safe(obj: Any) -> Any:
    """Round-trip ``obj`` through JSON so the result holds only JSON types."""
    return json.loads(json.dumps(obj, default=_json_default))


_FAILED_TOOL_STATUSES = {"error", "failed", "failure"}


def _legacy_tool_call_to_invocation(call: Mapping[str, Any]) -> Dict[str, Any]:
    """Map a legacy ``{name, status, output, arguments}`` tool call onto ``ToolInvocation.to_dict()``."""
    output = call.get("output")
    if output is not None and not isinstance(output, str):
        output = json.dumps(output, default=_json_default, sort_keys=True)
    failed = str(call.get("status", "completed")).lower() in _FAILED_TOOL_STATUSES
    return ToolInvocation(
        tool_name=str(call.get("name") or "unknown"),
        input=dict(call.get("arguments") or {}),
        output=output,
        status=ToolStatus.ERROR if failed else ToolStatus.COMPLETED,
        error=(output if failed else None),
    ).to_dict()


class ChatStorageTurn(BaseModel):
    """Full audit record of one conversation turn (spec FEAT-886 §2 Data Models).

    ``agent_id`` is the agent NAME (the ChatStorage key); ``chatbot_id`` is the bot's
    ``memory_key_id`` and may differ. ``timestamp`` and ``sequence`` are emitter-owned
    and immutable once stored.
    """

    model_config = ConfigDict(extra="ignore")

    schema_version: int = 2
    turn_id: str
    user_id: str
    session_id: str
    agent_id: str
    chatbot_id: Optional[str] = None
    timestamp: datetime
    sequence: int = 0
    user_message: str
    assistant_response: str
    context_used: Optional[str] = None
    tools_used: List[str] = Field(default_factory=list)
    tool_invocations: List[Dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = None
    token_count: Optional[Dict[str, Any]] = None
    state: str = "raw"
    norm_version: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    presentation: TurnPresentation = Field(default_factory=TurnPresentation)

    @field_validator("timestamp", mode="after")
    @classmethod
    def _force_utc(cls, value: datetime) -> datetime:
        """Naive → UTC, aware → converted to UTC."""
        return _parse_utc(value) or value

    @classmethod
    def from_event_payload(cls, payload: Dict[str, Any]) -> "ChatStorageTurn":
        """Build from a ``TurnCompletedEvent`` payload.

        Raises:
            InvalidTurnPayloadError: ``turn_id``, ``user_id``, ``session_id``, ``agent_name``
                or a parseable timestamp is missing (permanent defect — never retried).
        """
        turn = payload.get("turn") if isinstance(payload, dict) else None
        if not isinstance(turn, dict):
            raise InvalidTurnPayloadError("turn event payload has no 'turn' object")
        ident = {
            "turn_id": turn.get("turn_id"),
            "user_id": payload.get("user_id") or turn.get("user_id"),
            "session_id": payload.get("session_id"),
            "agent_name": payload.get("agent_name"),
        }
        missing = [name for name, value in ident.items() if not value]
        timestamp = _parse_utc(turn.get("timestamp"))
        if missing or timestamp is None:
            bad = missing + ([] if timestamp else ["timestamp"])
            raise InvalidTurnPayloadError(
                f"turn {ident['turn_id']!r}: missing or invalid {', '.join(bad)}")
        try:
            return cls(
                turn_id=ident["turn_id"], user_id=ident["user_id"],
                session_id=ident["session_id"], agent_id=ident["agent_name"],
                chatbot_id=payload.get("chatbot_id") or turn.get("chatbot_id") or None,
                timestamp=timestamp, sequence=int(turn.get("sequence") or 0),
                user_message=turn.get("user_message", ""),
                assistant_response=turn.get("assistant_response", ""),
                context_used=turn.get("context_used"),
                tools_used=list(turn.get("tools_used") or []),
                tool_invocations=list(turn.get("tool_invocations") or []),
                error=turn.get("error"), token_count=turn.get("token_count"),
                state=str(turn.get("state") or "raw"), norm_version=turn.get("norm_version"),
                metadata=dict(turn.get("metadata") or {}),
                presentation=TurnPresentation.model_validate(payload.get("presentation") or {}),
            )
        except (ValidationError, TypeError, ValueError) as exc:
            raise InvalidTurnPayloadError(f"turn {ident['turn_id']!r}: {exc}") from exc

    @classmethod
    def from_row(cls, row: Dict[str, Any], *, user_id: str = "", agent_id: str = "",
                 session_id: str = "") -> "ChatStorageTurn":
        """Tolerant reader for rows written before and after FEAT-886.

        A row carrying ``schema_version >= 2`` is the current layout. A row without it is
        legacy: missing fields default, ``tool_calls`` map to ``tool_invocations`` and the
        reported ``schema_version`` is ``1``. ``user_id`` / ``agent_id`` / ``session_id`` are
        used only when the row itself does not carry them (legacy rows don't: they are key
        parts of the backend row).
        """
        if int(row.get("schema_version") or 1) >= 2:
            data = {k: v for k, v in row.items() if k != "updated_at"}
            data.setdefault("user_id", user_id)
            data.setdefault("agent_id", agent_id)
            data.setdefault("session_id", session_id)
            return cls.model_validate(data)
        return cls._from_legacy_row(row, user_id, agent_id, session_id)

    @classmethod
    def _from_legacy_row(cls, row: Dict[str, Any], user_id: str, agent_id: str,
                         session_id: str) -> "ChatStorageTurn":
        """Map the pre-FEAT-886 flat layout onto the model (``schema_version=1``)."""
        metadata = dict(row.get("metadata") or {})
        timestamp = _parse_utc(row.get("timestamp"))
        if timestamp is None:
            timestamp = _parse_utc(row.get("updated_at")) or _EPOCH_SENTINEL
            metadata["legacy_timestamp_missing"] = True
        calls = [c for c in (row.get("tool_calls") or []) if isinstance(c, dict)]
        return cls(
            schema_version=1,
            turn_id=str(row.get("turn_id") or ""),
            user_id=str(row.get("user_id") or user_id),
            session_id=str(row.get("session_id") or session_id),
            agent_id=str(row.get("agent_id") or agent_id),
            timestamp=timestamp,
            sequence=0,
            user_message=row.get("user_message") or "",
            assistant_response=row.get("assistant_response") or "",
            tools_used=[str(c.get("name") or "unknown") for c in calls],
            tool_invocations=[_legacy_tool_call_to_invocation(c) for c in calls],
            metadata=metadata,
            presentation=TurnPresentation(
                output=row.get("output"), output_mode=row.get("output_mode"),
                data=row.get("data"), code=row.get("code"),
                sources=list(row.get("sources") or []),
                response_time_ms=row.get("response_time_ms"),
                model=row.get("model"), provider=row.get("provider"),
            ),
        )

    def to_row(self) -> Dict[str, Any]:
        """JSON-safe dict for ``ConversationBackend.put_turn``.

        ``timestamp`` is ISO-8601 UTC and ``sequence`` an int: the backends derive their
        chronological index from exactly these two keys.
        """
        row = _json_safe(self.model_dump(exclude={"presentation"}))
        row["timestamp"] = self.timestamp.astimezone(timezone.utc).isoformat()
        row["presentation"] = _json_safe(self.presentation.model_dump())
        return row

    def to_conversation_turn(self) -> ConversationTurn:
        """Project onto the working-memory turn; ``presentation`` is dropped."""
        return ConversationTurn(
            turn_id=self.turn_id, user_id=self.user_id,
            user_message=self.user_message, assistant_response=self.assistant_response,
            context_used=self.context_used, tools_used=list(self.tools_used),
            timestamp=self.timestamp, metadata=dict(self.metadata),
            chatbot_id=self.chatbot_id,
            tool_invocations=[ToolInvocation.from_dict(d) for d in self.tool_invocations],
            error=self.error,
            token_count=TokenCount.from_dict(self.token_count) if self.token_count else None,
            state=TurnState(self.state), norm_version=self.norm_version,
            sequence=self.sequence or None,
        )

    def to_messages(self) -> List[Dict[str, Any]]:
        """The user + assistant dicts ``ChatStorage.load_conversation`` returns, with rich fields."""
        stamp = self.timestamp.astimezone(timezone.utc).isoformat()
        p = self.presentation
        legacy_calls = [
            {"name": inv.get("tool_name"), "status": inv.get("status", "completed"),
             "output": inv.get("output"), "arguments": inv.get("input")}
            for inv in self.tool_invocations
        ]
        user = {"role": MessageRole.USER.value, "content": self.user_message,
                "timestamp": stamp, "turn_id": self.turn_id}
        assistant = {
            "role": MessageRole.ASSISTANT.value, "content": self.assistant_response,
            "timestamp": stamp, "turn_id": self.turn_id,
            "output": p.output, "output_mode": p.output_mode, "data": p.data, "code": p.code,
            "model": p.model, "provider": p.provider, "response_time_ms": p.response_time_ms,
            "tool_calls": legacy_calls, "sources": list(p.sources), "metadata": dict(self.metadata),
            # --- FEAT-886 rich fields ---
            "tools_used": list(self.tools_used), "tool_invocations": list(self.tool_invocations),
            "usage": p.usage, "cost_usd": p.cost_usd, "tenant": p.tenant, "error": self.error,
            "sequence": self.sequence, "schema_version": self.schema_version,
        }
        return [user, assistant]
