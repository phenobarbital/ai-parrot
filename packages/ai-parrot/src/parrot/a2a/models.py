# parrot/a2a/models.py
"""A2A Protocol Data Models.

Upgraded to the A2A Protocol Specification v1.0.0 while retaining backward
compatibility with the pre-release v0.3 wire format used by Microsoft Copilot
Studio's ``a2a-dotnet`` parser.

Serialization is *version-aware*: every ``to_dict()`` accepts a ``version``
argument (``"1.0"`` by default). v1.0 emits ProtoJSON ``SCREAMING_SNAKE_CASE``
enum values (``"TASK_STATE_SUBMITTED"``) and v1.0 field shapes; v0.3 emits the
legacy lowercase values (``"submitted"``) and the flat card shape. Every
``from_dict()`` auto-detects the incoming format and accepts BOTH.
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
    """Task lifecycle states — v1.0.0 ProtoJSON values.

    The canonical member value is the v1.0 ``TASK_STATE_*`` string. The legacy
    v0.3 lowercase values (``"submitted"`` …) are handled by
    :func:`parse_task_state` on deserialization and :func:`serialize_task_state`
    on serialization.
    """
    UNSPECIFIED = "TASK_STATE_UNSPECIFIED"
    SUBMITTED = "TASK_STATE_SUBMITTED"
    WORKING = "TASK_STATE_WORKING"
    COMPLETED = "TASK_STATE_COMPLETED"
    FAILED = "TASK_STATE_FAILED"
    CANCELED = "TASK_STATE_CANCELED"            # was CANCELLED (double-L) in v0.3
    INPUT_REQUIRED = "TASK_STATE_INPUT_REQUIRED"
    REJECTED = "TASK_STATE_REJECTED"
    AUTH_REQUIRED = "TASK_STATE_AUTH_REQUIRED"  # NEW in v1.0
    # Deprecated alias: shares CANCELED's value so `TaskState.CANCELLED is
    # TaskState.CANCELED` and existing code keeps working.
    CANCELLED = "TASK_STATE_CANCELED"


class Role(str, Enum):
    """Message role — v1.0.0 ProtoJSON values."""
    UNSPECIFIED = "ROLE_UNSPECIFIED"
    USER = "ROLE_USER"
    AGENT = "ROLE_AGENT"


# --- Version-aware enum (de)serialization helpers ---------------------------

# Canonical member -> legacy v0.3 lowercase string.
_TASK_STATE_V03: Dict["TaskState", str] = {
    TaskState.UNSPECIFIED: "unspecified",
    TaskState.SUBMITTED: "submitted",
    TaskState.WORKING: "working",
    TaskState.COMPLETED: "completed",
    TaskState.FAILED: "failed",
    TaskState.CANCELED: "cancelled",           # v0.3 used the double-L spelling
    TaskState.INPUT_REQUIRED: "input_required",
    TaskState.REJECTED: "rejected",
    TaskState.AUTH_REQUIRED: "auth_required",
}

_ROLE_V03: Dict["Role", str] = {
    Role.UNSPECIFIED: "unspecified",
    Role.USER: "user",
    Role.AGENT: "agent",
}

# Compat lookup: accepts both v0.3 lowercase and v1.0 SCREAMING_SNAKE values.
_TASK_STATE_COMPAT: Dict[str, "TaskState"] = {}
for _member in TaskState:  # aliases (CANCELLED) are excluded from iteration
    _TASK_STATE_COMPAT[_member.value] = _member
for _member, _legacy in _TASK_STATE_V03.items():
    _TASK_STATE_COMPAT[_legacy] = _member

_ROLE_COMPAT: Dict[str, "Role"] = {}
for _member in Role:
    _ROLE_COMPAT[_member.value] = _member
for _member, _legacy in _ROLE_V03.items():
    _ROLE_COMPAT[_legacy] = _member


def serialize_task_state(state: "TaskState", version: str = "1.0") -> str:
    """Serialize a TaskState to the wire value for the target protocol version."""
    if version == "0.3":
        return _TASK_STATE_V03.get(state, state.value)
    return state.value


def serialize_role(role: "Role", version: str = "1.0") -> str:
    """Serialize a Role to the wire value for the target protocol version."""
    if version == "0.3":
        return _ROLE_V03.get(role, role.value)
    return role.value


def parse_task_state(value: Union[str, "TaskState"]) -> "TaskState":
    """Parse a TaskState from either the v0.3 or the v1.0 format."""
    if isinstance(value, TaskState):
        return value
    if value in _TASK_STATE_COMPAT:
        return _TASK_STATE_COMPAT[value]
    return TaskState(value)


def parse_role(value: Union[str, "Role"]) -> "Role":
    """Parse a Role from either the v0.3 or the v1.0 format."""
    if isinstance(value, Role):
        return value
    if value in _ROLE_COMPAT:
        return _ROLE_COMPAT[value]
    return Role(value)


@dataclass
class Part:
    """Atomic content unit."""
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

    def _to_dict_v1(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        if self.text is not None:
            result["kind"] = "text"
            result["text"] = self.text
        elif self.file_uri or self.file_bytes:
            result["kind"] = "file"
            # v1.0 renames fileWithUri -> url and fileWithBytes -> raw.
            if self.file_uri:
                result["url"] = self.file_uri
            if self.file_bytes:
                result["raw"] = base64.b64encode(self.file_bytes).decode()
            if self.file_media_type:
                result["mediaType"] = self.file_media_type
        elif self.data is not None:
            result["kind"] = "data"
            result["data"] = {"data": self.data}
        if self.filename is not None:
            result["filename"] = self.filename
        if self.metadata:
            result["metadata"] = self.metadata
        return result

    def _to_dict_v03(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        if self.text is not None:
            result["kind"] = "text"
            result["text"] = self.text
        elif self.file_uri or self.file_bytes:
            result["kind"] = "file"
            file_part: Dict[str, Any] = {}
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

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Part":
        part = cls()
        if "text" in data:
            part.text = data["text"]
        # v1.0 top-level file fields.
        if "url" in data:
            part.file_uri = data["url"]
        if "raw" in data:
            part.file_bytes = base64.b64decode(data["raw"])
        # v0.3 (and nested v1.0) `file` block.
        if "file" in data and isinstance(data["file"], dict):
            file_data = data["file"]
            part.file_uri = file_data.get("fileWithUri") or file_data.get("url") or part.file_uri
            if "fileWithBytes" in file_data:
                part.file_bytes = base64.b64decode(file_data["fileWithBytes"])
            elif "raw" in file_data:
                part.file_bytes = base64.b64decode(file_data["raw"])
            if file_data.get("mediaType"):
                part.file_media_type = file_data["mediaType"]
        if data.get("mediaType"):
            part.file_media_type = data["mediaType"]
        if "filename" in data:
            part.filename = data["filename"]
        if "data" in data:
            raw = data["data"]
            part.data = raw.get("data", raw) if isinstance(raw, dict) else raw
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
            "role": serialize_role(self.role, version),
            "parts": [p.to_dict(version) for p in self.parts],
            "contextId": self.context_id,
            "taskId": self.task_id,
            "metadata": self.metadata,
        }
        # v1.0-only additive fields.
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
            "state": serialize_task_state(self.state, version),
            "timestamp": self.timestamp,
            "message": self.message.to_dict(version) if self.message else None,
        }


# --- A2UI-A2A extension (FEAT-273 Module 13, display only) ----------------------
# Single owner of the A2UI-A2A extension identifiers. Display envelopes are carried
# in a data Part per the official A2UI-A2A extension; action/interaction legs are FEAT-B.
A2UI_EXTENSION_URI = "https://a2ui.org/extensions/a2a/display/v1"
A2UI_MEDIA_TYPE = "application/vnd.a2ui.envelope+json"


def _reject_action_components(envelope: Dict[str, Any]) -> None:
    """Raise if a display A2UI envelope contains action-bearing components (v1).

    Best-effort: consults the catalog registry when available; unknown components
    are left alone (their action-ness cannot be determined here).
    """
    try:
        from parrot.outputs.a2ui.catalog import get_component
    except ImportError:  # pragma: no cover - a2ui always present in core
        return
    for comp in envelope.get("components", []) or []:
        name = comp.get("component") if isinstance(comp, dict) else None
        if not name:
            continue
        try:
            entry = get_component(name)
        except KeyError:
            continue
        if entry.definition.requires_actions:
            raise ValueError(
                f"Display-only A2A emit (FEAT-273): component {name!r} is action-bearing; "
                "interactive A2UI over A2A is FEAT-B."
            )


@dataclass
class Artifact:
    """Output produced by an agent."""
    artifact_id: str
    parts: List[Part]
    name: Optional[str] = None
    description: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    @classmethod
    def from_a2ui_envelope(
        cls,
        envelope: Dict[str, Any],
        *,
        name: str = "a2ui-surface",
        artifact_id: Optional[str] = None,
    ) -> "Artifact":
        """Wrap a display A2UI ``CreateSurface`` envelope into an A2A Artifact.

        The already-serialized envelope dict (from ``AIMessage.a2ui_envelope``) is placed
        verbatim into a data :class:`Part` with the A2UI-A2A extension metadata — the a2a
        layer never re-shapes it (``parrot.outputs.a2ui.serialization`` owns ``version``).

        Args:
            envelope: The serialized ``createSurface`` envelope dict.
            name: Artifact name.
            artifact_id: Optional explicit id (a UUID4 is generated when omitted).

        Returns:
            An :class:`Artifact` carrying the envelope per the A2UI-A2A extension.

        Raises:
            TypeError: If ``envelope`` is not a dict.
            ValueError: If the envelope is not a display ``createSurface`` or contains
                action-bearing components (display-only in v1).
        """
        if not isinstance(envelope, dict):
            raise TypeError(f"A2UI envelope must be a dict, got {type(envelope)!r}.")
        message_type = envelope.get("messageType")
        if message_type not in (None, "createSurface"):
            raise ValueError(
                "Only display 'createSurface' envelopes may be emitted over A2A in v1; "
                f"got messageType={message_type!r}."
            )
        _reject_action_components(envelope)
        part = Part(
            data=envelope,
            metadata={"extensionUri": A2UI_EXTENSION_URI, "mediaType": A2UI_MEDIA_TYPE},
        )
        return cls(
            artifact_id=artifact_id or str(uuid.uuid4()),
            name=name,
            parts=[part],
            metadata={"extensionUri": A2UI_EXTENSION_URI},
        )

    @classmethod
    def from_response(cls, response: Any, name: str = "response") -> "Artifact":
        """Create artifact from an AIMessage or string response.

        FEAT-273: when the response carries an ``a2ui_envelope`` (display surface), it is
        wrapped via :meth:`from_a2ui_envelope`; otherwise the legacy text path is used
        (byte-identical to before).
        """
        envelope = getattr(response, "a2ui_envelope", None)
        if envelope:
            return cls.from_a2ui_envelope(envelope, name=name)

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
            "parts": [p.to_dict(version) for p in self.parts],
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
            "status": self.status.to_dict(version),
            "artifacts": [a.to_dict(version) for a in self.artifacts],
            "history": [m.to_dict(version) for m in self.history],
            "metadata": self.metadata,
        }


# --- New v1.0.0 model types --------------------------------------------------


@dataclass
class AgentExtension:
    """A protocol extension declared by an agent (v1.0)."""
    uri: str
    description: Optional[str] = None
    required: bool = False
    params: Optional[Dict[str, Any]] = None

    def to_dict(self, version: str = "1.0") -> Dict[str, Any]:
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
class AgentInterface:
    """v1.0 AgentCard interface entry."""
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
        if self.tenant:
            data["tenant"] = self.tenant
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentInterface":
        return cls(
            url=data["url"],
            # Accept both the v1.0 `protocolBinding` and the v0.3 `transport`.
            protocol_binding=data.get("protocolBinding") or data.get("transport", "JSONRPC"),
            protocol_version=data.get("protocolVersion", "1.0"),
            tenant=data.get("tenant"),
        )


@dataclass
class AgentProvider:
    """Organization that provides the agent (v1.0)."""
    url: str
    organization: str

    def to_dict(self, version: str = "1.0") -> Dict[str, Any]:
        return {"url": self.url, "organization": self.organization}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentProvider":
        return cls(url=data["url"], organization=data["organization"])


@dataclass
class SecurityScheme:
    """Base security scheme (v1.0 securitySchemes entry)."""
    type: str
    description: Optional[str] = None

    def to_dict(self, version: str = "1.0") -> Dict[str, Any]:
        data: Dict[str, Any] = {"type": self.type}
        if self.description is not None:
            data["description"] = self.description
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SecurityScheme":
        scheme_type = data.get("type", "")
        builders = {
            "apiKey": APIKeySecurityScheme,
            "http": HTTPAuthSecurityScheme,
            "oauth2": OAuth2SecurityScheme,
            "openIdConnect": OpenIdConnectSecurityScheme,
            "mutualTLS": MutualTlsSecurityScheme,
        }
        builder = builders.get(scheme_type)
        if builder is not None and builder is not cls:
            return builder.from_dict(data)
        return cls(type=scheme_type, description=data.get("description"))


@dataclass
class APIKeySecurityScheme(SecurityScheme):
    """API key security scheme."""
    name: str = ""
    location: str = "header"   # "header" | "query" | "cookie"

    def __init__(self, name: str = "", location: str = "header",
                 description: Optional[str] = None):
        super().__init__(type="apiKey", description=description)
        self.name = name
        self.location = location

    def to_dict(self, version: str = "1.0") -> Dict[str, Any]:
        data = super().to_dict(version)
        data["name"] = self.name
        data["in"] = self.location
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "APIKeySecurityScheme":
        return cls(
            name=data.get("name", ""),
            location=data.get("in", "header"),
            description=data.get("description"),
        )


@dataclass
class HTTPAuthSecurityScheme(SecurityScheme):
    """HTTP authentication security scheme (Bearer/Basic)."""
    scheme: str = "bearer"
    bearer_format: Optional[str] = None

    def __init__(self, scheme: str = "bearer", bearer_format: Optional[str] = None,
                 description: Optional[str] = None):
        super().__init__(type="http", description=description)
        self.scheme = scheme
        self.bearer_format = bearer_format

    def to_dict(self, version: str = "1.0") -> Dict[str, Any]:
        data = super().to_dict(version)
        data["scheme"] = self.scheme
        if self.bearer_format is not None:
            data["bearerFormat"] = self.bearer_format
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HTTPAuthSecurityScheme":
        return cls(
            scheme=data.get("scheme", "bearer"),
            bearer_format=data.get("bearerFormat"),
            description=data.get("description"),
        )


@dataclass
class OAuth2SecurityScheme(SecurityScheme):
    """OAuth 2.0 security scheme."""
    flows: Optional[Dict[str, Any]] = None

    def __init__(self, flows: Optional[Dict[str, Any]] = None,
                 description: Optional[str] = None):
        super().__init__(type="oauth2", description=description)
        self.flows = flows or {}

    def to_dict(self, version: str = "1.0") -> Dict[str, Any]:
        data = super().to_dict(version)
        data["flows"] = self.flows
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OAuth2SecurityScheme":
        return cls(flows=data.get("flows"), description=data.get("description"))


@dataclass
class OpenIdConnectSecurityScheme(SecurityScheme):
    """OpenID Connect security scheme."""
    open_id_connect_url: str = ""

    def __init__(self, open_id_connect_url: str = "",
                 description: Optional[str] = None):
        super().__init__(type="openIdConnect", description=description)
        self.open_id_connect_url = open_id_connect_url

    def to_dict(self, version: str = "1.0") -> Dict[str, Any]:
        data = super().to_dict(version)
        data["openIdConnectUrl"] = self.open_id_connect_url
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OpenIdConnectSecurityScheme":
        return cls(
            open_id_connect_url=data.get("openIdConnectUrl", ""),
            description=data.get("description"),
        )


@dataclass
class MutualTlsSecurityScheme(SecurityScheme):
    """Mutual TLS security scheme."""

    def __init__(self, description: Optional[str] = None):
        super().__init__(type="mutualTLS", description=description)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MutualTlsSecurityScheme":
        return cls(description=data.get("description"))


@dataclass
class SecurityRequirement:
    """A security requirement: a map of scheme name -> required scopes."""
    schemes: Dict[str, List[str]] = field(default_factory=dict)

    def to_dict(self, version: str = "1.0") -> Dict[str, Any]:
        return dict(self.schemes)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SecurityRequirement":
        return cls(schemes={k: list(v or []) for k, v in data.items()})


@dataclass
class AgentCardSignature:
    """A JWS signature over the AgentCard (v1.0). Signing itself is out of scope."""
    protected: str
    signature: str
    header: Optional[Dict[str, Any]] = None

    def to_dict(self, version: str = "1.0") -> Dict[str, Any]:
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


@dataclass
class AuthenticationInfo:
    """Authentication details for a push notification webhook (v1.0)."""
    scheme: str            # e.g., "Bearer", "Basic"
    credentials: Optional[str] = None

    def to_dict(self, version: str = "1.0") -> Dict[str, Any]:
        data: Dict[str, Any] = {"scheme": self.scheme}
        if self.credentials is not None:
            data["credentials"] = self.credentials
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AuthenticationInfo":
        return cls(scheme=data["scheme"], credentials=data.get("credentials"))


@dataclass
class TaskPushNotificationConfig:
    """Configuration for a task's push-notification webhook (v1.0)."""
    id: str
    task_id: str
    url: str
    authentication: Optional[AuthenticationInfo] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self, version: str = "1.0") -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "id": self.id,
            "taskId": self.task_id,
            "url": self.url,
        }
        if self.authentication is not None:
            data["authentication"] = self.authentication.to_dict(version)
        if self.metadata is not None:
            data["metadata"] = self.metadata
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskPushNotificationConfig":
        auth = data.get("authentication")
        return cls(
            id=data.get("id", ""),
            task_id=data.get("taskId") or data.get("task_id", ""),
            url=data["url"],
            authentication=AuthenticationInfo.from_dict(auth) if auth else None,
            metadata=data.get("metadata"),
        )


@dataclass
class SendMessageConfiguration:
    """Configuration accompanying a `SendMessage` request (v1.0)."""
    accepted_output_modes: Optional[List[str]] = None
    task_push_notification_config: Optional[TaskPushNotificationConfig] = None
    history_length: Optional[int] = None
    return_immediately: bool = False

    def to_dict(self, version: str = "1.0") -> Dict[str, Any]:
        data: Dict[str, Any] = {"returnImmediately": self.return_immediately}
        if self.accepted_output_modes is not None:
            data["acceptedOutputModes"] = self.accepted_output_modes
        if self.task_push_notification_config is not None:
            data["pushNotificationConfig"] = self.task_push_notification_config.to_dict(version)
        if self.history_length is not None:
            data["historyLength"] = self.history_length
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SendMessageConfiguration":
        push = data.get("pushNotificationConfig") or data.get("taskPushNotificationConfig")
        return cls(
            accepted_output_modes=data.get("acceptedOutputModes"),
            task_push_notification_config=(
                TaskPushNotificationConfig.from_dict(push) if push else None
            ),
            history_length=data.get("historyLength"),
            return_immediately=data.get("returnImmediately", False),
        )


@dataclass
class A2AError:
    """A2A JSON-RPC error object."""
    code: int
    message: str
    data: Optional[Any] = None

    def to_dict(self, version: str = "1.0") -> Dict[str, Any]:
        result: Dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            result["data"] = self.data
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "A2AError":
        return cls(code=data["code"], message=data["message"], data=data.get("data"))


# A2A Protocol v1.0 error code table: name -> (json_rpc_code, http_status).
A2A_ERROR_CODES: Dict[str, tuple] = {
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
    input_modes: Optional[List[str]] = None
    output_modes: Optional[List[str]] = None
    security_requirements: Optional[List[SecurityRequirement]] = None

    def to_dict(self, version: str = "1.0") -> Dict[str, Any]:
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
        # v1.0 additive fields.
        if version != "0.3":
            if self.input_modes is not None:
                data["inputModes"] = self.input_modes
            if self.output_modes is not None:
                data["outputModes"] = self.output_modes
            if self.security_requirements is not None:
                data["securityRequirements"] = [
                    s.to_dict(version) for s in self.security_requirements
                ]
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentSkill":
        sec = data.get("securityRequirements")
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
                [SecurityRequirement.from_dict(s) for s in sec] if sec else None
            ),
        )


@dataclass
class AgentCapabilities:
    """Capabilities supported by an agent."""
    streaming: bool = True
    push_notifications: bool = False
    extended_agent_card: bool = False
    extensions: List[AgentExtension] = field(default_factory=list)

    def to_dict(self, version: str = "1.0") -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "streaming": self.streaming,
            "pushNotifications": self.push_notifications,
            "extendedAgentCard": self.extended_agent_card,
        }
        if self.extensions:
            result["extensions"] = [e.to_dict(version) for e in self.extensions]
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentCapabilities":
        exts = [AgentExtension.from_dict(e) for e in data.get("extensions", [])]
        return cls(
            streaming=data.get("streaming", True),
            push_notifications=data.get("pushNotifications", False),
            extended_agent_card=data.get("extendedAgentCard", False),
            extensions=exts,
        )


@dataclass
class AgentCard:
    """Self-describing manifest for an agent (A2A v1.0 structure).

    Replaces the flat v0.3 ``url`` + ``preferredTransport`` with a structured
    ``supported_interfaces`` array. The flat accessors remain available as
    read-only backward-compat properties (``url``, ``preferred_transport``,
    ``protocol_version``) so existing consumers keep working.
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
    security_schemes: Optional[Dict[str, SecurityScheme]] = None
    security_requirements: Optional[List[SecurityRequirement]] = None
    signatures: Optional[List[AgentCardSignature]] = None
    icon_url: Optional[str] = None
    tags: List[str] = field(default_factory=list)

    @property
    def url(self) -> Optional[str]:
        """Backward-compat: first interface URL (the v0.3 flat `url`)."""
        if self.supported_interfaces:
            return self.supported_interfaces[0].url
        return None

    @url.setter
    def url(self, value: Optional[str]) -> None:
        """Backward-compat writable `url`: update (or create) the first interface.

        Existing callers (e.g. ``ToolManager.register_a2a_agent``) assign
        ``card.url`` directly; the setter keeps that contract working after the
        v1.0 ``supported_interfaces`` restructure.
        """
        if value is None:
            return
        if self.supported_interfaces:
            self.supported_interfaces[0].url = value
        else:
            self.supported_interfaces = [
                AgentInterface(
                    url=value, protocol_binding="JSONRPC", protocol_version="1.0"
                )
            ]

    @property
    def preferred_transport(self) -> str:
        """Backward-compat: first interface protocol binding."""
        if self.supported_interfaces:
            return self.supported_interfaces[0].protocol_binding
        return "JSONRPC"

    @preferred_transport.setter
    def preferred_transport(self, value: str) -> None:
        """Backward-compat writable `preferred_transport`."""
        if self.supported_interfaces:
            self.supported_interfaces[0].protocol_binding = value
        else:
            self.supported_interfaces = [
                AgentInterface(
                    url="", protocol_binding=value, protocol_version="1.0"
                )
            ]

    @property
    def protocol_version(self) -> str:
        """Backward-compat: first interface protocol version."""
        if self.supported_interfaces:
            return self.supported_interfaces[0].protocol_version
        return "0.3.0"

    def to_dict(self, version: str = "1.0") -> Dict[str, Any]:
        if version == "0.3":
            return self._to_dict_v03()
        return self._to_dict_v1()

    def _to_dict_v1(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "supportedInterfaces": [i.to_dict("1.0") for i in self.supported_interfaces],
            "capabilities": self.capabilities.to_dict("1.0"),
            "defaultInputModes": self.default_input_modes,
            "defaultOutputModes": self.default_output_modes,
            "skills": [s.to_dict("1.0") for s in self.skills],
            "tags": self.tags,
        }
        if self.provider is not None:
            data["provider"] = self.provider.to_dict("1.0")
        if self.documentation_url is not None:
            data["documentationUrl"] = self.documentation_url
        if self.security_schemes is not None:
            data["securitySchemes"] = {
                k: v.to_dict("1.0") for k, v in self.security_schemes.items()
            }
        if self.security_requirements is not None:
            data["securityRequirements"] = [
                s.to_dict("1.0") for s in self.security_requirements
            ]
        if self.signatures is not None:
            data["signatures"] = [s.to_dict("1.0") for s in self.signatures]
        if self.icon_url is not None:
            data["iconUrl"] = self.icon_url
        return data

    def _to_dict_v03(self) -> Dict[str, Any]:
        # Flat `url` + `preferredTransport` ARE the A2A v0.3 card shape that
        # Microsoft Copilot Studio's a2a-dotnet parser deserializes. Both are
        # `[JsonRequired]` in `A2A.V0_3/Models/AgentCard.cs`; `url` must point at
        # the JSON-RPC message endpoint (where `message/send` is POSTed), not at
        # the card itself. The v0.3 deserializer does NOT set
        # `JsonUnmappedMemberHandling.Disallow`, so unknown fields are ignored.
        data: Dict[str, Any] = {
            "protocolVersion": "0.3.0",
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "url": self.url,
            "preferredTransport": self.preferred_transport,
            "capabilities": self.capabilities.to_dict("0.3"),
            "defaultInputModes": self.default_input_modes,
            "defaultOutputModes": self.default_output_modes,
            "skills": [s.to_dict("0.3") for s in self.skills],
            "tags": self.tags,
        }
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

        # Auto-detect the card shape: `supportedInterfaces` => v1.0, flat `url`
        # => v0.3. `additionalInterfaces` (v0.3 optional) is also accepted.
        interfaces: List[AgentInterface] = []
        if data.get("supportedInterfaces"):
            interfaces = [
                AgentInterface.from_dict(i) for i in data["supportedInterfaces"]
            ]
        elif data.get("url"):
            interfaces = [
                AgentInterface(
                    url=data["url"],
                    protocol_binding=data.get("preferredTransport", "JSONRPC"),
                    protocol_version=data.get("protocolVersion", "0.3.0"),
                )
            ]
            for extra in data.get("additionalInterfaces", []):
                interfaces.append(AgentInterface.from_dict(extra))

        provider = data.get("provider")
        schemes = data.get("securitySchemes")
        sec_reqs = data.get("securityRequirements")
        sigs = data.get("signatures")

        return cls(
            name=data["name"],
            description=data["description"],
            version=data["version"],
            skills=skills,
            supported_interfaces=interfaces,
            capabilities=capabilities,
            default_input_modes=data.get("defaultInputModes", ["text/plain", "application/json"]),
            default_output_modes=data.get("defaultOutputModes", ["text/plain", "application/json"]),
            provider=AgentProvider.from_dict(provider) if provider else None,
            documentation_url=data.get("documentationUrl"),
            security_schemes=(
                {k: SecurityScheme.from_dict(v) for k, v in schemes.items()}
                if schemes else None
            ),
            security_requirements=(
                [SecurityRequirement.from_dict(s) for s in sec_reqs] if sec_reqs else None
            ),
            signatures=(
                [AgentCardSignature.from_dict(s) for s in sigs] if sigs else None
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
    # A2A protocol version the discovered agent speaks (FEAT-272 / TASK-1718).
    protocol_version: str = "0.3"
