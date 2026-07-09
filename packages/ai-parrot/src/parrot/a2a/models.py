# parrot/a2a/models.py
"""A2A Protocol Data Models.

Supports both the A2A Protocol v1.0.0 specification
(https://a2a-protocol.org/v1.0.0/specification/) and the legacy v0.3 wire
format used by Microsoft Copilot Studio's ``a2a-dotnet`` parser.

Version-aware serialization: most ``to_dict()`` methods accept a
``version: str = "1.0"`` parameter. ``version="1.0"`` (default) emits the
ratified v1.0.0 ProtoJSON conventions (SCREAMING_SNAKE_CASE enums,
``supportedInterfaces``, etc). ``version="0.3"`` emits the legacy shape
(lowercase enums, flat ``url`` + ``preferredTransport``) for backward
compatibility with v0.3 clients/servers.

``from_dict()`` methods are version-agnostic: they auto-detect the wire
format and accept both v0.3 and v1.0 payloads without a version hint.
"""
from typing import Optional, List, Dict, Any, Union
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone
import base64
import uuid

@dataclass
class AgentConfig:
    """Configuration for an A2A agent."""
    name: str
    description: str
    port: int
    skills: List[Dict[str, Any]]
    system_prompt: str


class TaskState(str, Enum):
    """Task lifecycle states — A2A v1.0.0 ProtoJSON values.

    Values are SCREAMING_SNAKE_CASE with a ``TASK_STATE_`` prefix per the
    ratified v1.0.0 specification. ``CANCELLED`` (double-L, the legacy v0.3
    spelling) is kept as a deprecated *alias* for ``CANCELED`` (single-L,
    the v1.0 spelling) so existing code referencing ``TaskState.CANCELLED``
    keeps working — Python's ``Enum`` supports aliases natively when two
    members share the same value.
    """
    UNSPECIFIED = "TASK_STATE_UNSPECIFIED"
    SUBMITTED = "TASK_STATE_SUBMITTED"
    WORKING = "TASK_STATE_WORKING"
    COMPLETED = "TASK_STATE_COMPLETED"
    FAILED = "TASK_STATE_FAILED"
    CANCELED = "TASK_STATE_CANCELED"
    CANCELLED = "TASK_STATE_CANCELED"  # deprecated alias (v0.3 double-L spelling)
    INPUT_REQUIRED = "TASK_STATE_INPUT_REQUIRED"
    REJECTED = "TASK_STATE_REJECTED"
    AUTH_REQUIRED = "TASK_STATE_AUTH_REQUIRED"  # NEW in v1.0


class Role(str, Enum):
    """Message role — A2A v1.0.0 ProtoJSON values (``ROLE_`` prefix)."""
    UNSPECIFIED = "ROLE_UNSPECIFIED"
    USER = "ROLE_USER"
    AGENT = "ROLE_AGENT"


# ─────────────────────────────────────────────────────────────
# Enum compat (de)serialization helpers
#
# The A2A v1.0.0 spec renamed enum wire values from lowercase (v0.3,
# `"submitted"`) to SCREAMING_SNAKE_CASE with a type prefix (v1.0,
# `"TASK_STATE_SUBMITTED"`). These helpers translate both ways so the
# server/client can negotiate the wire format via the `A2A-Version` header
# while the canonical Python enum stays a single source of truth.
# ─────────────────────────────────────────────────────────────

_TASK_STATE_COMPAT: Dict[str, "TaskState"] = {
    # v0.3 lowercase (legacy)
    "unspecified": TaskState.UNSPECIFIED,
    "submitted": TaskState.SUBMITTED,
    "working": TaskState.WORKING,
    "completed": TaskState.COMPLETED,
    "failed": TaskState.FAILED,
    "cancelled": TaskState.CANCELED,  # v0.3 double-L maps to v1.0 single-L
    "canceled": TaskState.CANCELED,
    "input_required": TaskState.INPUT_REQUIRED,
    "rejected": TaskState.REJECTED,
    "auth_required": TaskState.AUTH_REQUIRED,
    # v1.0 SCREAMING_SNAKE_CASE
    "TASK_STATE_UNSPECIFIED": TaskState.UNSPECIFIED,
    "TASK_STATE_SUBMITTED": TaskState.SUBMITTED,
    "TASK_STATE_WORKING": TaskState.WORKING,
    "TASK_STATE_COMPLETED": TaskState.COMPLETED,
    "TASK_STATE_FAILED": TaskState.FAILED,
    "TASK_STATE_CANCELED": TaskState.CANCELED,
    "TASK_STATE_INPUT_REQUIRED": TaskState.INPUT_REQUIRED,
    "TASK_STATE_REJECTED": TaskState.REJECTED,
    "TASK_STATE_AUTH_REQUIRED": TaskState.AUTH_REQUIRED,
}


def parse_task_state(value: str) -> TaskState:
    """Parse a :class:`TaskState` from either v0.3 or v1.0 wire format.

    Args:
        value: Either a v0.3 lowercase value (``"submitted"``) or a v1.0
            SCREAMING_SNAKE_CASE value (``"TASK_STATE_SUBMITTED"``).

    Returns:
        The matching :class:`TaskState` member.
    """
    try:
        return _TASK_STATE_COMPAT[value]
    except KeyError:
        return TaskState(value)  # fallback to direct enum lookup


def _serialize_task_state(state: "TaskState", version: str = "1.0") -> str:
    """Serialize a :class:`TaskState` for the given protocol version."""
    if version == "0.3":
        if state is TaskState.CANCELED:
            return "cancelled"
        return state.name.lower()
    return state.value


_ROLE_COMPAT: Dict[str, "Role"] = {
    # v0.3 lowercase (legacy)
    "unspecified": Role.UNSPECIFIED,
    "user": Role.USER,
    "agent": Role.AGENT,
    # v1.0 SCREAMING_SNAKE_CASE
    "ROLE_UNSPECIFIED": Role.UNSPECIFIED,
    "ROLE_USER": Role.USER,
    "ROLE_AGENT": Role.AGENT,
}


def parse_role(value: str) -> Role:
    """Parse a :class:`Role` from either v0.3 or v1.0 wire format."""
    try:
        return _ROLE_COMPAT[value]
    except KeyError:
        return Role(value)  # fallback to direct enum lookup


def _serialize_role(role: "Role", version: str = "1.0") -> str:
    """Serialize a :class:`Role` for the given protocol version."""
    if version == "0.3":
        return role.name.lower()
    return role.value


@dataclass
class Part:
    """Atomic content unit.

    v1.0.0 renames the file-part wire fields (``fileWithUri`` → ``url``,
    ``fileWithBytes`` → ``raw``) and adds a ``filename`` field. The Python
    attribute names (``file_uri``, ``file_bytes``) are kept unchanged for
    backward compatibility — only the serialized wire format changes per
    ``version``.
    """
    text: Optional[str] = None
    file_uri: Optional[str] = None
    file_bytes: Optional[bytes] = None
    file_media_type: Optional[str] = None
    filename: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None

    @classmethod
    def from_text(cls, text: str) -> "Part":
        return cls(text=text)

    @classmethod
    def from_data(cls, data: Dict[str, Any]) -> "Part":
        return cls(data=data)

    def to_dict(self, version: str = "1.0") -> Dict[str, Any]:
        # A2A Part is a discriminated union: every part carries a `kind`
        # ("text" | "file" | "data"). Strict parsers (e.g. Copilot's a2a-dotnet
        # PartConverter) route on it, so it must be present.
        if version == "0.3":
            return self._to_dict_v03()
        return self._to_dict_v1()

    def _to_dict_v03(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        if self.text is not None:
            result["kind"] = "text"
            result["text"] = self.text
        elif self.file_uri or self.file_bytes:
            result["kind"] = "file"
            file_part = {}
            if self.file_uri:
                file_part["fileWithUri"] = self.file_uri
            if self.file_bytes:
                file_part["fileWithBytes"] = base64.b64encode(self.file_bytes).decode()
            if self.file_media_type:
                file_part["mediaType"] = self.file_media_type
            result["file"] = file_part
        elif self.data is not None:
            result["kind"] = "data"
            result["data"] = {"data": self.data}
        if self.metadata:
            result["metadata"] = self.metadata
        return result

    def _to_dict_v1(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        if self.text is not None:
            result["kind"] = "text"
            result["text"] = self.text
        elif self.file_uri or self.file_bytes:
            result["kind"] = "file"
            if self.file_uri:
                result["url"] = self.file_uri
            if self.file_bytes:
                result["raw"] = base64.b64encode(self.file_bytes).decode()
            if self.file_media_type:
                result["mediaType"] = self.file_media_type
        elif self.data is not None:
            result["kind"] = "data"
            result["data"] = self.data
        if self.filename is not None:
            result["filename"] = self.filename
        if self.metadata:
            result["metadata"] = self.metadata
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Part":
        part = cls()
        if "text" in data:
            part.text = data["text"]
        if "file" in data:
            # v0.3 nested file object: {"file": {"fileWithUri": ..., "fileWithBytes": ...}}
            file_data = data["file"]
            part.file_uri = file_data.get("fileWithUri") or file_data.get("url")
            if "fileWithBytes" in file_data:
                part.file_bytes = base64.b64decode(file_data["fileWithBytes"])
            elif "raw" in file_data:
                part.file_bytes = base64.b64decode(file_data["raw"])
            part.file_media_type = file_data.get("mediaType")
        else:
            # v1.0 flat file fields: {"kind": "file", "url": ..., "raw": ...}
            if "url" in data:
                part.file_uri = data["url"]
            if "raw" in data:
                part.file_bytes = base64.b64decode(data["raw"])
            if "mediaType" in data:
                part.file_media_type = data.get("mediaType")
        if "data" in data:
            raw = data["data"]
            part.data = raw.get("data", raw) if isinstance(raw, dict) else raw
        if "filename" in data:
            part.filename = data["filename"]
        if "metadata" in data:
            part.metadata = data["metadata"]
        return part


@dataclass
class Message:
    """Communication unit between agents."""
    message_id: str
    role: Role
    parts: List[Part]
    context_id: Optional[str] = None
    task_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    # v1.0.0 additions
    extensions: Optional[List[str]] = None
    reference_task_ids: Optional[List[str]] = None

    @classmethod
    def user(cls, content: Union[str, Dict, List[Part]], **kwargs) -> "Message":
        if isinstance(content, str):
            parts = [Part.from_text(content)]
        elif isinstance(content, dict):
            parts = [Part.from_data(content)]
        else:
            parts = content
        return cls(
            message_id=str(uuid.uuid4()),
            role=Role.USER,
            parts=parts,
            **kwargs
        )

    @classmethod
    def agent(cls, content: Union[str, Dict, List[Part]], **kwargs) -> "Message":
        if isinstance(content, str):
            parts = [Part.from_text(content)]
        elif isinstance(content, dict):
            parts = [Part.from_data(content)]
        else:
            parts = content
        return cls(
            message_id=str(uuid.uuid4()),
            role=Role.AGENT,
            parts=parts,
            **kwargs
        )

    def get_text(self) -> str:
        """Extract all text content from parts."""
        return " ".join(p.text for p in self.parts if p.text)

    def get_data(self) -> Optional[Dict[str, Any]]:
        """Extract structured data from parts."""
        return next((p.data for p in self.parts if p.data), None)

    def to_dict(self, version: str = "1.0") -> Dict[str, Any]:
        result: Dict[str, Any] = {
            # A2A discriminator for the Message/Task/event union. Strict clients
            # (e.g. Microsoft Copilot Studio's a2a-dotnet parser) route on it.
            "kind": "message",
            "messageId": self.message_id,
            "role": _serialize_role(self.role, version),
            "parts": [p.to_dict(version=version) for p in self.parts],
            "contextId": self.context_id,
            "taskId": self.task_id,
            "metadata": self.metadata,
        }
        if version != "0.3":
            if self.extensions is not None:
                result["extensions"] = self.extensions
            if self.reference_task_ids is not None:
                result["referenceTaskIds"] = self.reference_task_ids
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        return cls(
            message_id=data.get("messageId", str(uuid.uuid4())),
            role=parse_role(data.get("role", "user")),
            parts=[Part.from_dict(p) for p in data.get("parts", [])],
            context_id=data.get("contextId"),
            task_id=data.get("taskId"),
            metadata=data.get("metadata"),
            extensions=data.get("extensions"),
            reference_task_ids=data.get("referenceTaskIds"),
        )


@dataclass
class TaskStatus:
    """Current status of a task."""
    state: TaskState
    message: Optional[Message] = None
    timestamp: Optional[str] = None

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self, version: str = "1.0") -> Dict[str, Any]:
        return {
            "state": _serialize_task_state(self.state, version),
            "timestamp": self.timestamp,
            "message": self.message.to_dict(version=version) if self.message else None,
        }


@dataclass
class Artifact:
    """Output produced by an agent."""
    artifact_id: str
    parts: List[Part]
    name: Optional[str] = None
    description: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    @classmethod
    def from_response(cls, response: Any, name: str = "response") -> "Artifact":
        """Create artifact from an AIMessage or string response."""
        if hasattr(response, 'content'):
            # AIMessage
            text = response.content
        elif hasattr(response, 'response'):
            text = response.response
        else:
            text = str(response)

        return cls(
            artifact_id=str(uuid.uuid4()),
            name=name,
            parts=[Part.from_text(text)]
        )

    def to_dict(self, version: str = "1.0") -> Dict[str, Any]:
        return {
            # NOTE: `kind` is NOT part of the A2A Artifact schema (Artifact is not
            # in the discriminated event union). Emitted defensively; strict
            # parsers ignore unknown fields. Drop if it ever causes trouble.
            "kind": "artifact",
            "artifactId": self.artifact_id,
            "name": self.name,
            "description": self.description,
            "parts": [p.to_dict(version=version) for p in self.parts],
            "metadata": self.metadata,
        }


@dataclass
class Task:
    """Unit of work with lifecycle."""
    id: str
    context_id: str
    status: TaskStatus
    artifacts: List[Artifact] = field(default_factory=list)
    history: List[Message] = field(default_factory=list)
    metadata: Optional[Dict[str, Any]] = None

    @classmethod
    def create(cls, context_id: Optional[str] = None) -> "Task":
        return cls(
            id=str(uuid.uuid4()),
            context_id=context_id or str(uuid.uuid4()),
            status=TaskStatus(state=TaskState.SUBMITTED)
        )

    def working(self, message: Optional[str] = None) -> "Task":
        self.status = TaskStatus(
            state=TaskState.WORKING,
            message=Message.agent(message) if message else None
        )
        return self

    def complete(self, response: Any) -> "Task":
        self.status = TaskStatus(state=TaskState.COMPLETED)
        self.artifacts.append(Artifact.from_response(response))
        return self

    def fail(self, error: str) -> "Task":
        self.status = TaskStatus(
            state=TaskState.FAILED,
            message=Message.agent(error)
        )
        return self

    def to_dict(self, version: str = "1.0") -> Dict[str, Any]:
        return {
            # A2A discriminator — Copilot's parser deserializes a `message/send`
            # result by routing on `kind` ("task" vs "message").
            "kind": "task",
            "id": self.id,
            "contextId": self.context_id,
            "status": self.status.to_dict(version=version),
            "artifacts": [a.to_dict(version=version) for a in self.artifacts],
            "history": [m.to_dict(version=version) for m in self.history],
            "metadata": self.metadata,
        }


# ─────────────────────────────────────────────────────────────
# Security models (v1.0.0) — modeled but signing/verification and full
# scheme-specific validation are out of scope for this spec (deferred).
# ─────────────────────────────────────────────────────────────

@dataclass
class APIKeySecurityScheme:
    """API key security scheme (v1.0.0)."""
    name: str
    location: str = "header"  # "query" | "header" | "cookie"
    description: Optional[str] = None
    type: str = "apiKey"

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"type": self.type, "name": self.name, "in": self.location}
        if self.description is not None:
            data["description"] = self.description
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "APIKeySecurityScheme":
        return cls(
            name=data["name"],
            location=data.get("in", "header"),
            description=data.get("description"),
        )


@dataclass
class HTTPAuthSecurityScheme:
    """HTTP authentication security scheme (v1.0.0), e.g. Bearer/Basic."""
    scheme: str
    bearer_format: Optional[str] = None
    description: Optional[str] = None
    type: str = "http"

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"type": self.type, "scheme": self.scheme}
        if self.bearer_format is not None:
            data["bearerFormat"] = self.bearer_format
        if self.description is not None:
            data["description"] = self.description
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HTTPAuthSecurityScheme":
        return cls(
            scheme=data["scheme"],
            bearer_format=data.get("bearerFormat"),
            description=data.get("description"),
        )


@dataclass
class OAuth2SecurityScheme:
    """OAuth2 security scheme (v1.0.0)."""
    flows: Dict[str, Any]
    description: Optional[str] = None
    type: str = "oauth2"

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"type": self.type, "flows": self.flows}
        if self.description is not None:
            data["description"] = self.description
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OAuth2SecurityScheme":
        return cls(flows=data.get("flows", {}), description=data.get("description"))


@dataclass
class OpenIdConnectSecurityScheme:
    """OpenID Connect security scheme (v1.0.0)."""
    open_id_connect_url: str
    description: Optional[str] = None
    type: str = "openIdConnect"

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "type": self.type,
            "openIdConnectUrl": self.open_id_connect_url,
        }
        if self.description is not None:
            data["description"] = self.description
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OpenIdConnectSecurityScheme":
        return cls(
            open_id_connect_url=data["openIdConnectUrl"],
            description=data.get("description"),
        )


@dataclass
class MutualTlsSecurityScheme:
    """Mutual TLS security scheme (v1.0.0)."""
    description: Optional[str] = None
    type: str = "mutualTLS"

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"type": self.type}
        if self.description is not None:
            data["description"] = self.description
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MutualTlsSecurityScheme":
        return cls(description=data.get("description"))


# Union type alias for the security scheme subtypes above.
SecurityScheme = Union[
    APIKeySecurityScheme,
    HTTPAuthSecurityScheme,
    OAuth2SecurityScheme,
    OpenIdConnectSecurityScheme,
    MutualTlsSecurityScheme,
]

#: Maps the `type` discriminator to the concrete SecurityScheme dataclass.
_SECURITY_SCHEME_TYPES: Dict[str, Any] = {
    "apiKey": APIKeySecurityScheme,
    "http": HTTPAuthSecurityScheme,
    "oauth2": OAuth2SecurityScheme,
    "openIdConnect": OpenIdConnectSecurityScheme,
    "mutualTLS": MutualTlsSecurityScheme,
}


def security_scheme_from_dict(data: Dict[str, Any]) -> Any:
    """Parse a `SecurityScheme` union member from its `type` discriminator."""
    scheme_type = data.get("type")
    scheme_cls = _SECURITY_SCHEME_TYPES.get(scheme_type)
    if scheme_cls is None:
        raise ValueError(f"Unknown security scheme type: {scheme_type!r}")
    return scheme_cls.from_dict(data)


@dataclass
class SecurityRequirement:
    """A single security requirement entry (v1.0.0).

    Maps scheme name -> list of required scopes (empty for non-OAuth2
    schemes).
    """
    schemes: Dict[str, List[str]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.schemes)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SecurityRequirement":
        return cls(schemes=dict(data))


@dataclass
class AgentExtension:
    """A protocol extension declared by an agent (v1.0.0).

    Modeled per spec; custom extension execution is out of scope.
    """
    uri: str
    description: Optional[str] = None
    required: bool = False
    params: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"uri": self.uri, "required": self.required}
        if self.description is not None:
            data["description"] = self.description
        if self.params is not None:
            data["params"] = self.params
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentExtension":
        return cls(
            uri=data["uri"],
            description=data.get("description"),
            required=data.get("required", False),
            params=data.get("params"),
        )


@dataclass
class AgentCardSignature:
    """A JWS signature over an AgentCard (v1.0.0).

    Modeled per spec; signing/verification (RFC 7515) is out of scope.
    """
    protected: str
    signature: str
    header: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"protected": self.protected, "signature": self.signature}
        if self.header is not None:
            data["header"] = self.header
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentCardSignature":
        return cls(
            protected=data["protected"],
            signature=data["signature"],
            header=data.get("header"),
        )


# ─────────────────────────────────────────────────────────────
# Push notification models (v1.0.0)
# ─────────────────────────────────────────────────────────────

@dataclass
class AuthenticationInfo:
    """Authentication info for a push notification webhook (v1.0.0)."""
    scheme: str  # e.g., "Bearer", "Basic"
    credentials: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"scheme": self.scheme}
        if self.credentials is not None:
            data["credentials"] = self.credentials
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AuthenticationInfo":
        return cls(scheme=data["scheme"], credentials=data.get("credentials"))


@dataclass
class TaskPushNotificationConfig:
    """A push notification configuration for a task (v1.0.0)."""
    id: str
    task_id: str
    url: str
    authentication: Optional[AuthenticationInfo] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "id": self.id,
            "taskId": self.task_id,
            "url": self.url,
        }
        if self.authentication is not None:
            data["authentication"] = self.authentication.to_dict()
        if self.metadata is not None:
            data["metadata"] = self.metadata
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskPushNotificationConfig":
        auth_data = data.get("authentication")
        return cls(
            id=data.get("id", ""),
            task_id=data.get("taskId", ""),
            url=data["url"],
            authentication=AuthenticationInfo.from_dict(auth_data) if auth_data else None,
            metadata=data.get("metadata"),
        )


@dataclass
class SendMessageConfiguration:
    """Configuration options for `SendMessage` / `message:send` (v1.0.0)."""
    accepted_output_modes: Optional[List[str]] = None
    task_push_notification_config: Optional[TaskPushNotificationConfig] = None
    history_length: Optional[int] = None
    return_immediately: bool = False

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"returnImmediately": self.return_immediately}
        if self.accepted_output_modes is not None:
            data["acceptedOutputModes"] = self.accepted_output_modes
        if self.task_push_notification_config is not None:
            data["taskPushNotificationConfig"] = self.task_push_notification_config.to_dict()
        if self.history_length is not None:
            data["historyLength"] = self.history_length
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SendMessageConfiguration":
        push_config = data.get("taskPushNotificationConfig")
        return cls(
            accepted_output_modes=data.get("acceptedOutputModes"),
            task_push_notification_config=(
                TaskPushNotificationConfig.from_dict(push_config) if push_config else None
            ),
            history_length=data.get("historyLength"),
            return_immediately=data.get("returnImmediately", False),
        )


# ─────────────────────────────────────────────────────────────
# A2A protocol-level error model (v1.0.0)
# ─────────────────────────────────────────────────────────────

@dataclass
class A2AError:
    """A JSON-RPC-style A2A protocol error (v1.0.0 error code table)."""
    code: int
    message: str
    data: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            result["data"] = self.data
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "A2AError":
        return cls(code=data["code"], message=data["message"], data=data.get("data"))


#: A2A Protocol v1.0.0 error code table (spec §2 / §7; TASK-1715).
#: Maps a symbolic error name to its ``(json_rpc_code, http_status)`` pair.
A2A_ERRORS: Dict[str, "tuple[int, int]"] = {
    "TaskNotFoundError": (-32001, 404),
    "TaskNotCancelableError": (-32002, 400),
    "PushNotificationNotSupportedError": (-32003, 400),
    "UnsupportedOperationError": (-32004, 400),
    "ContentTypeNotSupportedError": (-32005, 400),
    "InvalidAgentResponseError": (-32006, 500),
    "ExtendedAgentCardNotConfiguredError": (-32007, 400),
    "ExtensionSupportRequiredError": (-32008, 400),
    "VersionNotSupportedError": (-32009, 400),
}


@dataclass
class AgentSkill:
    """A capability exposed by an agent (maps to a tool)."""
    id: str
    name: str
    description: str
    tags: List[str] = field(default_factory=list)
    input_schema: Optional[Dict[str, Any]] = None
    examples: List[str] = field(default_factory=list)
    # v1.0.0 additions
    input_modes: Optional[List[str]] = None
    output_modes: Optional[List[str]] = None
    security_requirements: Optional[List[SecurityRequirement]] = None

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "tags": self.tags,
            "examples": self.examples,
        }
        # `inputSchema` is not part of the A2A AgentSkill schema; emit it only
        # when populated so strict consumers (e.g. Microsoft Copilot Studio's
        # System.Text.Json parser) don't choke on a stray `null`. A2ARemoteSkill
        # still reads it back via `from_dict` when present.
        if self.input_schema is not None:
            data["inputSchema"] = self.input_schema
        if self.input_modes is not None:
            data["inputModes"] = self.input_modes
        if self.output_modes is not None:
            data["outputModes"] = self.output_modes
        if self.security_requirements is not None:
            data["securityRequirements"] = [s.to_dict() for s in self.security_requirements]
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentSkill":
        security_requirements = data.get("securityRequirements")
        return cls(
            id=data["id"],
            name=data["name"],
            description=data["description"],
            tags=data.get("tags", []),
            input_schema=data.get("inputSchema"),
            examples=data.get("examples", []),
            input_modes=data.get("inputModes"),
            output_modes=data.get("outputModes"),
            security_requirements=(
                [SecurityRequirement.from_dict(s) for s in security_requirements]
                if security_requirements else None
            ),
        )


@dataclass
class AgentCapabilities:
    """Capabilities supported by an agent."""
    streaming: bool = True
    push_notifications: bool = False
    extended_agent_card: bool = False
    extensions: List[AgentExtension] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "streaming": self.streaming,
            "pushNotifications": self.push_notifications,
            "extendedAgentCard": self.extended_agent_card,
            "extensions": [e.to_dict() for e in self.extensions],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentCapabilities":
        extensions = data.get("extensions", [])
        return cls(
            streaming=data.get("streaming", True),
            push_notifications=data.get("pushNotifications", False),
            extended_agent_card=data.get("extendedAgentCard", False),
            extensions=[AgentExtension.from_dict(e) for e in extensions],
        )


@dataclass
class AgentInterface:
    """v1.0 AgentCard interface entry.

    Replaces the flat `url` + `preferredTransport` shape used by v0.3.
    """
    url: str
    protocol_binding: str   # "JSONRPC" | "GRPC" | "HTTP+JSON"
    protocol_version: str = "1.0"
    tenant: Optional[str] = None

    def to_dict(self, version: str = "1.0") -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "url": self.url,
            "protocolBinding": self.protocol_binding,
            "protocolVersion": self.protocol_version,
        }
        if self.tenant is not None:
            data["tenant"] = self.tenant
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentInterface":
        return cls(
            url=data["url"],
            protocol_binding=data.get("protocolBinding", "JSONRPC"),
            protocol_version=data.get("protocolVersion", "1.0"),
            tenant=data.get("tenant"),
        )


@dataclass
class AgentProvider:
    """Organization/provider metadata for an AgentCard (v1.0.0)."""
    url: str
    organization: str

    def to_dict(self) -> Dict[str, Any]:
        return {"url": self.url, "organization": self.organization}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentProvider":
        return cls(url=data["url"], organization=data["organization"])


@dataclass
class AgentCard:
    """Self-describing manifest for an agent.

    v1.0.0 replaces the flat ``url`` + ``preferredTransport`` shape (v0.3)
    with a ``supportedInterfaces`` array of :class:`AgentInterface` objects,
    and adds ``provider``, ``documentationUrl``, ``securitySchemes``,
    ``securityRequirements``, ``signatures``.

    For backward compatibility, ``url`` and ``preferred_transport`` remain
    available as *properties* derived from ``supported_interfaces[0]`` — many
    existing consumers (:class:`~parrot.a2a.client.A2AClient`,
    :class:`~parrot.a2a.mesh.A2AMeshDiscovery`,
    :class:`~parrot.a2a.router.A2AProxyRouter`) read (and, in one case, write)
    ``card.url`` directly. ``url`` also supports assignment
    (``card.url = "..."``) for that reason.
    """
    name: str
    description: str
    version: str
    skills: List[AgentSkill]
    supported_interfaces: List[AgentInterface] = field(default_factory=list)
    capabilities: AgentCapabilities = field(default_factory=AgentCapabilities)
    default_input_modes: List[str] = field(default_factory=lambda: ["text/plain", "application/json"])
    default_output_modes: List[str] = field(default_factory=lambda: ["text/plain", "application/json"])
    provider: Optional[AgentProvider] = None
    documentation_url: Optional[str] = None
    security_schemes: Optional[Dict[str, Any]] = None
    security_requirements: Optional[List[SecurityRequirement]] = None
    signatures: Optional[List[AgentCardSignature]] = None
    icon_url: Optional[str] = None
    tags: List[str] = field(default_factory=list)

    @property
    def url(self) -> Optional[str]:
        """Backward-compat accessor: the first interface's URL (or ``None``)."""
        return self.supported_interfaces[0].url if self.supported_interfaces else None

    @url.setter
    def url(self, value: Optional[str]) -> None:
        if self.supported_interfaces:
            self.supported_interfaces[0].url = value
        elif value is not None:
            self.supported_interfaces.append(
                AgentInterface(url=value, protocol_binding="JSONRPC", protocol_version="1.0")
            )

    @property
    def preferred_transport(self) -> str:
        """Backward-compat accessor: the first interface's protocol binding."""
        if self.supported_interfaces:
            return self.supported_interfaces[0].protocol_binding
        return "JSONRPC"

    def to_dict(self, version: str = "1.0") -> Dict[str, Any]:
        if version == "0.3":
            return self._to_dict_v03()
        return self._to_dict_v1()

    def _to_dict_v1(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "supportedInterfaces": [i.to_dict() for i in self.supported_interfaces],
            "capabilities": self.capabilities.to_dict(),
            "defaultInputModes": self.default_input_modes,
            "defaultOutputModes": self.default_output_modes,
            "skills": [s.to_dict() for s in self.skills],
            "tags": self.tags,
        }
        if self.provider is not None:
            data["provider"] = self.provider.to_dict()
        if self.documentation_url is not None:
            data["documentationUrl"] = self.documentation_url
        if self.security_schemes is not None:
            data["securitySchemes"] = {
                name: scheme.to_dict() for name, scheme in self.security_schemes.items()
            }
        if self.security_requirements is not None:
            data["securityRequirements"] = [r.to_dict() for r in self.security_requirements]
        if self.signatures is not None:
            data["signatures"] = [s.to_dict() for s in self.signatures]
        if self.icon_url is not None:
            data["iconUrl"] = self.icon_url
        return data

    def _to_dict_v03(self) -> Dict[str, Any]:
        first = self.supported_interfaces[0] if self.supported_interfaces else None
        data: Dict[str, Any] = {
            # A2A protocol version. Use the fully-qualified "0.3.0" (the
            # a2a-dotnet v0.3 `AgentCard.ProtocolVersion` default that
            # Microsoft Copilot Studio validates), not the abbreviated "0.3".
            "protocolVersion": "0.3.0",
            "name": self.name,
            "description": self.description,
            "version": self.version,
            # Flat `url` + `preferredTransport` ARE the A2A v0.3 card shape that
            # Microsoft Copilot Studio's a2a-dotnet parser deserializes. Both are
            # `[JsonRequired]` in `A2A.V0_3/Models/AgentCard.cs`; `url` must point
            # at the JSON-RPC message endpoint (where `message/send` is POSTed),
            # not at the card itself.
            "url": first.url if first else None,
            "preferredTransport": first.protocol_binding if first else "JSONRPC",
            "capabilities": self.capabilities.to_dict(),
            "defaultInputModes": self.default_input_modes,
            "defaultOutputModes": self.default_output_modes,
            "skills": [s.to_dict() for s in self.skills],
            "tags": self.tags,
        }
        # NOTE: we deliberately do NOT emit `supportedInterfaces`. Verified
        # against the a2a-dotnet source (the library Copilot Studio uses): the
        # v0.3 `AgentCard` model has NO `supportedInterfaces` field — the correct,
        # OPTIONAL field is `additionalInterfaces` (`{url, transport}`), and the
        # required flat `url`+`preferredTransport` already fully describe the
        # JSON-RPC endpoint, so the extra array is redundant. (`supportedInterfaces`
        # exists only in the unreleased a2aproject v1 `main` model, which Copilot
        # does not use; the official Microsoft A2A sample card omits it entirely.)
        # The v0.3 deserializer does NOT set `JsonUnmappedMemberHandling.Disallow`,
        # so unknown fields are ignored rather than rejected.
        # Omit `iconUrl` when unset rather than emitting `null` (strict parsers).
        if self.icon_url is not None:
            data["iconUrl"] = self.icon_url
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentCard":
        skills = []
        for s in data.get("skills", []):
            if isinstance(s, dict):
                skills.append(AgentSkill.from_dict(s))
            else:
                skills.append(s)

        caps = data.get("capabilities", {})
        if isinstance(caps, dict):
            capabilities = AgentCapabilities.from_dict(caps)
        else:
            capabilities = caps or AgentCapabilities()

        # Auto-detect wire format: `supportedInterfaces` -> v1.0, flat `url` -> v0.3.
        if "supportedInterfaces" in data:
            supported_interfaces = [
                AgentInterface.from_dict(i) for i in data["supportedInterfaces"]
            ]
        elif data.get("url"):
            supported_interfaces = [
                AgentInterface(
                    url=data["url"],
                    protocol_binding=data.get("preferredTransport", "JSONRPC"),
                    protocol_version=data.get("protocolVersion", "1.0"),
                )
            ]
        else:
            supported_interfaces = []

        provider_data = data.get("provider")
        security_schemes_data = data.get("securitySchemes")
        security_requirements_data = data.get("securityRequirements")
        signatures_data = data.get("signatures")

        return cls(
            name=data["name"],
            description=data["description"],
            version=data["version"],
            skills=skills,
            supported_interfaces=supported_interfaces,
            capabilities=capabilities,
            default_input_modes=data.get("defaultInputModes", ["text/plain", "application/json"]),
            default_output_modes=data.get("defaultOutputModes", ["text/plain", "application/json"]),
            provider=AgentProvider.from_dict(provider_data) if provider_data else None,
            documentation_url=data.get("documentationUrl"),
            security_schemes=(
                {
                    name: security_scheme_from_dict(scheme)
                    for name, scheme in security_schemes_data.items()
                }
                if security_schemes_data else None
            ),
            security_requirements=(
                [SecurityRequirement.from_dict(r) for r in security_requirements_data]
                if security_requirements_data else None
            ),
            signatures=(
                [AgentCardSignature.from_dict(s) for s in signatures_data]
                if signatures_data else None
            ),
            icon_url=data.get("iconUrl"),
            tags=data.get("tags", []),
        )


@dataclass
class RegisteredAgent:
    """Definition about a Registered Agent."""
    url: str
    card: AgentCard
    last_seen: datetime = field(default_factory=datetime.utcnow)
    healthy: bool = True
