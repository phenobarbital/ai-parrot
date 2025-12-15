# parrot/a2a/models.py
"""A2A Protocol Data Models."""
from typing import Optional, List, Dict, Any, Union
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone
import base64
import uuid


class TaskState(str, Enum):
    """Task lifecycle states."""
    SUBMITTED = "submitted"
    WORKING = "working"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INPUT_REQUIRED = "input_required"
    REJECTED = "rejected"


class Role(str, Enum):
    """Message role."""
    USER = "user"
    AGENT = "agent"


@dataclass
class Part:
    """Atomic content unit."""
    text: Optional[str] = None
    file_uri: Optional[str] = None
    file_bytes: Optional[bytes] = None
    file_media_type: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None

    @classmethod
    def from_text(cls, text: str) -> "Part":
        return cls(text=text)

    @classmethod
    def from_data(cls, data: Dict[str, Any]) -> "Part":
        return cls(data=data)

    def to_dict(self) -> Dict[str, Any]:
        result = {}
        if self.text is not None:
            result["text"] = self.text
        if self.file_uri or self.file_bytes:
            file_part = {}
            if self.file_uri:
                file_part["fileWithUri"] = self.file_uri
            if self.file_bytes:
                file_part["fileWithBytes"] = base64.b64encode(self.file_bytes).decode()
            if self.file_media_type:
                file_part["mediaType"] = self.file_media_type
            result["file"] = file_part
        if self.data is not None:
            result["data"] = {"data": self.data}
        if self.metadata:
            result["metadata"] = self.metadata
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Part":
        part = cls()
        if "text" in data:
            part.text = data["text"]
        if "file" in data:
            file_data = data["file"]
            part.file_uri = file_data.get("fileWithUri")
            if "fileWithBytes" in file_data:
                part.file_bytes = base64.b64decode(file_data["fileWithBytes"])
            part.file_media_type = file_data.get("mediaType")
        if "data" in data:
            part.data = data["data"].get("data", data["data"])
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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "messageId": self.message_id,
            "role": self.role.value,
            "parts": [p.to_dict() for p in self.parts],
            "contextId": self.context_id,
            "taskId": self.task_id,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        return cls(
            message_id=data.get("messageId", str(uuid.uuid4())),
            role=Role(data.get("role", "user")),
            parts=[Part.from_dict(p) for p in data.get("parts", [])],
            context_id=data.get("contextId"),
            task_id=data.get("taskId"),
            metadata=data.get("metadata"),
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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state.value,
            "timestamp": self.timestamp,
            "message": self.message.to_dict() if self.message else None,
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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifactId": self.artifact_id,
            "name": self.name,
            "description": self.description,
            "parts": [p.to_dict() for p in self.parts],
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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "contextId": self.context_id,
            "status": self.status.to_dict(),
            "artifacts": [a.to_dict() for a in self.artifacts],
            "history": [m.to_dict() for m in self.history],
            "metadata": self.metadata,
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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "tags": self.tags,
            "inputSchema": self.input_schema,
            "examples": self.examples,
        }


@dataclass
class AgentCapabilities:
    """Capabilities supported by an agent."""
    streaming: bool = True
    push_notifications: bool = False
    state_transition_history: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "streaming": self.streaming,
            "pushNotifications": self.push_notifications,
            "pushNotifications": self.push_notifications,
            "stateTransitionHistory": self.state_transition_history,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentCapabilities":
        return cls(
            streaming=data.get("streaming", True),
            push_notifications=data.get("pushNotifications", False),
            state_transition_history=data.get("stateTransitionHistory", False),
        )


@dataclass
class AgentCard:
    """Self-describing manifest for an agent."""
    name: str
    description: str
    version: str
    skills: List[AgentSkill]
    url: Optional[str] = None
    capabilities: AgentCapabilities = field(default_factory=AgentCapabilities)
    default_input_modes: List[str] = field(default_factory=lambda: ["text/plain", "application/json"])
    default_output_modes: List[str] = field(default_factory=lambda: ["text/plain", "application/json"])
    protocol_version: str = "0.3"
    icon_url: Optional[str] = None
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "protocolVersion": self.protocol_version,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "url": self.url,
            "capabilities": self.capabilities.to_dict(),
            "defaultInputModes": self.default_input_modes,
            "defaultOutputModes": self.default_output_modes,
            "skills": [s.to_dict() for s in self.skills],
            "iconUrl": self.icon_url,
            "iconUrl": self.icon_url,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentCard":
        skills = []
        for s in data.get("skills", []):
            if isinstance(s, dict):
                # Handle Skill dict
                skills.append(AgentSkill(
                    id=s["id"],
                    name=s["name"],
                    description=s["description"],
                    tags=s.get("tags", []),
                    input_schema=s.get("inputSchema"),
                    examples=s.get("examples", [])
                ))
            else:
                skills.append(s)
        
        caps = data.get("capabilities", {})
        if isinstance(caps, dict):
            capabilities = AgentCapabilities.from_dict(caps)
        else:
            capabilities = caps or AgentCapabilities()

        return cls(
            name=data["name"],
            description=data["description"],
            version=data["version"],
            skills=skills,
            url=data.get("url"),
            capabilities=capabilities,
            default_input_modes=data.get("defaultInputModes", ["text/plain", "application/json"]),
            default_output_modes=data.get("defaultOutputModes", ["text/plain", "application/json"]),
            protocol_version=data.get("protocolVersion", "0.3"),
            icon_url=data.get("iconUrl"),
            tags=data.get("tags", []),
        )


@dataclass
class RegisteredAgent:
    """Data about a A2A registered agent."""
    url: str
    card: AgentCard
    last_seen: datetime = field(default_factory=datetime.utcnow)
    healthy: bool = True
