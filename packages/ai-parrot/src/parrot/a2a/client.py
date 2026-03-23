# parrot/a2a/client.py
"""
A2A Client - Connect to remote A2A agents from AI-Parrot.
"""
from __future__ import annotations
import json
import asyncio
from typing import Dict, List, Optional, Any, AsyncIterator, Type
from dataclasses import dataclass, field
import aiohttp
from pydantic import BaseModel, Field
from navconfig.logging import logging
from ..tools.abstract import AbstractTool, AbstractToolArgsSchema
from .models import (
    AgentCard,
    AgentSkill,
    Task,
    TaskStatus,
    TaskState,
    Artifact,
    Message,
    Part,
)



@dataclass
class A2AAgentConnection:
    """Represents a connection to a remote A2A agent."""
    url: str
    card: AgentCard
    client: "A2AClient"
    name: str = ""

    def __post_init__(self):
        self.name = self.card.name


class A2AClient:
    """
    Client for communicating with remote A2A agents.

    Example:
        async with A2AClient("https://remote-agent:8080") as client:
            # Discover agent
            card = await client.discover()
            print(f"Connected to: {card.name}")

            # Send message
            task = await client.send_message("Hello!")
            print(task.artifacts[0].parts[0].text)

            # Stream response
            async for chunk in client.stream_message("Explain quantum computing"):
                print(chunk, end="", flush=True)
    """

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 60.0,
        headers: Optional[Dict[str, str]] = None,
        auth_token: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        """
        Initialize A2A client.

        Args:
            base_url: Base URL of the A2A agent (e.g., "https://agent.example.com")
            timeout: Request timeout in seconds
            headers: Additional headers to send with requests
            auth_token: Bearer token for authentication
            api_key: API key for authentication (sent as X-API-Key header)
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: Optional[aiohttp.ClientSession] = None
        self._agent_card: Optional[AgentCard] = None
        self._owns_session = False

        # Build headers
        self.headers = {"Content-Type": "application/json"}
        if headers:
            self.headers.update(headers)
        if auth_token:
            self.headers["Authorization"] = f"Bearer {auth_token}"
        if api_key:
            self.headers["X-API-Key"] = api_key

        self.logger = logging.getLogger(f"A2AClient.{base_url}")

    async def __aenter__(self) -> "A2AClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()

    async def connect(self, session: Optional[aiohttp.ClientSession] = None) -> None:
        """Establish connection and discover remote agent."""
        if session:
            self._session = session
            self._owns_session = False
        else:
            self._session = aiohttp.ClientSession(
                timeout=self.timeout,
                headers=self.headers
            )
            self._owns_session = True

        # Discover agent card
        self._agent_card = await self.discover()
        self.logger.info(f"Connected to A2A agent: {self._agent_card.name}")

    async def disconnect(self) -> None:
        """Close the connection."""
        if self._session and self._owns_session:
            await self._session.close()
            self._session = None
        self._agent_card = None

    @property
    def agent_card(self) -> Optional[AgentCard]:
        """Get the cached agent card."""
        return self._agent_card

    @property
    def is_connected(self) -> bool:
        return self._session is not None and not self._session.closed

    # ─────────────────────────────────────────────────────────────
    # Discovery
    # ─────────────────────────────────────────────────────────────

    async def discover(self) -> AgentCard:
        """Fetch the remote agent's card."""
        url = f"{self.base_url}/.well-known/agent.json"

        async with self._session.get(url) as resp:
            resp.raise_for_status()
            data = await resp.json()

        # Parse into AgentCard
        skills = [
            AgentSkill(
                id=s.get("id", ""),
                name=s.get("name", ""),
                description=s.get("description", ""),
                tags=s.get("tags", []),
                input_schema=s.get("inputSchema"),
            )
            for s in data.get("skills", [])
        ]

        return AgentCard(
            name=data.get("name", "Unknown"),
            description=data.get("description", ""),
            version=data.get("version", "1.0.0"),
            url=data.get("url") or self.base_url,
            skills=skills,
            protocol_version=data.get("protocolVersion", "0.3"),
        )

    def get_skills(self) -> List[AgentSkill]:
        """Get available skills from the remote agent."""
        if not self._agent_card:
            return []
        return self._agent_card.skills

    def get_skill(self, skill_id: str) -> Optional[AgentSkill]:
        """Get a specific skill by ID."""
        for skill in self.get_skills():
            if skill.id == skill_id:
                return skill
        return None

    # ─────────────────────────────────────────────────────────────
    # Messaging
    # ─────────────────────────────────────────────────────────────

    async def send_message(
        self,
        content: str,
        *,
        context_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Task:
        """
        Send a message to the remote agent and wait for response.

        Args:
            content: The message content
            context_id: Optional context ID for multi-turn conversations
            metadata: Optional metadata to include

        Returns:
            Task with the response
        """
        url = f"{self.base_url}/a2a/message/send"

        message = Message.user(content, context_id=context_id, metadata=metadata)

        payload = {
            "message": message.to_dict()
        }

        async with self._session.post(url, json=payload) as resp:
            resp.raise_for_status()
            data = await resp.json()

        return self._parse_task(data)

    async def stream_message(
        self,
        content: str,
        *,
        context_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[str]:
        """
        Send a message and stream the response.

        Args:
            content: The message content
            context_id: Optional context ID
            metadata: Optional metadata

        Yields:
            Text chunks as they arrive
        """
        url = f"{self.base_url}/a2a/message/stream"

        message = Message.user(content, context_id=context_id, metadata=metadata)

        payload = {
            "message": message.to_dict()
        }

        async with self._session.post(
            url,
            json=payload,
            headers={"Accept": "text/event-stream"}
        ) as resp:
            resp.raise_for_status()

            async for line in resp.content:
                line = line.decode("utf-8").strip()

                if not line or not line.startswith("data:"):
                    continue

                try:
                    data = json.loads(line[5:].strip())

                    # Extract text from artifact updates
                    if "artifactUpdate" in data:
                        artifact = data["artifactUpdate"].get("artifact", {})
                        parts = artifact.get("parts", [])
                        for part in parts:
                            if "text" in part:
                                yield part["text"]

                    # Check for completion/failure
                    if "statusUpdate" in data:
                        status = data["statusUpdate"]
                        if status.get("final"):
                            state = status.get("status", {}).get("state")
                            if state == "failed":
                                error_msg = status.get("status", {}).get("message", {})
                                error_text = error_msg.get("parts", [{}])[0].get("text", "Unknown error")
                                raise RuntimeError(f"Remote agent failed: {error_text}")
                            break

                except json.JSONDecodeError:
                    continue

    async def invoke_skill(
        self,
        skill_id: str,
        params: Optional[Dict[str, Any]] = None,
        *,
        context_id: Optional[str] = None,
    ) -> Any:
        """
        Invoke a specific skill on the remote agent.

        Args:
            skill_id: The skill ID to invoke
            params: Parameters to pass to the skill
            context_id: Optional context ID

        Returns:
            The skill result (extracted from artifacts)
        """
        message = Message.user(
            {"skill": skill_id, "params": params or {}},
            context_id=context_id
        )

        url = f"{self.base_url}/a2a/message/send"
        payload = {"message": message.to_dict()}

        async with self._session.post(url, json=payload) as resp:
            resp.raise_for_status()
            data = await resp.json()

        task = self._parse_task(data)

        if task.status.state == TaskState.FAILED:
            error_msg = task.status.message.get_text() if task.status.message else "Unknown error"
            raise RuntimeError(f"Skill invocation failed: {error_msg}")

        # Extract result from artifacts
        if task.artifacts:
            artifact = task.artifacts[0]
            if artifact.parts:
                part = artifact.parts[0]
                if part.data:
                    return part.data
                return part.text

        return None

    # ─────────────────────────────────────────────────────────────
    # Task Management
    # ─────────────────────────────────────────────────────────────

    async def get_task(self, task_id: str) -> Task:
        """Get a task by ID."""
        url = f"{self.base_url}/a2a/tasks/{task_id}"

        async with self._session.get(url) as resp:
            resp.raise_for_status()
            data = await resp.json()

        return self._parse_task(data)

    async def list_tasks(
        self,
        context_id: Optional[str] = None,
        status: Optional[str] = None,
        page_size: int = 50,
    ) -> List[Task]:
        """List tasks with optional filtering."""
        url = f"{self.base_url}/a2a/tasks"
        params = {"pageSize": page_size}
        if context_id:
            params["contextId"] = context_id
        if status:
            params["status"] = status

        async with self._session.get(url, params=params) as resp:
            resp.raise_for_status()
            data = await resp.json()

        return [self._parse_task(t) for t in data.get("tasks", [])]

    async def cancel_task(self, task_id: str) -> Task:
        """Cancel a running task."""
        url = f"{self.base_url}/a2a/tasks/{task_id}/cancel"

        async with self._session.post(url) as resp:
            resp.raise_for_status()
            data = await resp.json()

        return self._parse_task(data)

    # ─────────────────────────────────────────────────────────────
    # JSON-RPC
    # ─────────────────────────────────────────────────────────────

    async def rpc_call(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Make a JSON-RPC call to the remote agent."""
        url = f"{self.base_url}/a2a/rpc"

        payload = {
            "jsonrpc": "2.0",
            "id": str(id(self)),
            "method": method,
            "params": params or {}
        }

        async with self._session.post(url, json=payload) as resp:
            resp.raise_for_status()
            data = await resp.json()

        if "error" in data:
            raise RuntimeError(f"RPC error: {data['error']}")

        return data.get("result")

    # ─────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────

    def _parse_task(self, data: Dict[str, Any]) -> Task:
        """Parse a task from JSON response."""
        status_data = data.get("status", {})
        status = TaskStatus(
            state=TaskState(status_data.get("state", "submitted")),
            message=Message.from_dict(status_data["message"]) if status_data.get("message") else None,
            timestamp=status_data.get("timestamp"),
        )

        artifacts = []
        for a in data.get("artifacts", []):
            parts = [Part.from_dict(p) for p in a.get("parts", [])]
            artifacts.append(Artifact(
                artifact_id=a.get("artifactId", ""),
                name=a.get("name"),
                description=a.get("description"),
                parts=parts,
                metadata=a.get("metadata"),
            ))

        history = [Message.from_dict(m) for m in data.get("history", [])]

        return Task(
            id=data.get("id", ""),
            context_id=data.get("contextId", ""),
            status=status,
            artifacts=artifacts,
            history=history,
            metadata=data.get("metadata"),
        )


# ─────────────────────────────────────────────────────────────
# A2A Remote Tools - AbstractTool Implementations
# ─────────────────────────────────────────────────────────────


class A2ARemoteAgentInput(AbstractToolArgsSchema):
    """Input schema for A2A remote agent tool."""
    question: str = Field(
        ...,
        description="The question to ask the remote A2A agent"
    )
    context_id: Optional[str] = Field(
        None,
        description="Optional context ID for multi-turn conversations"
    )


class A2ARemoteAgentTool(AbstractTool):
    """
    Wraps a remote A2A agent as a tool that can be used by local agents.

    This creates a tool that, when invoked, sends the query to the remote agent.
    Properly inherits from AbstractTool for ToolManager compatibility.
    """

    name: str = "ask_remote_agent"
    description: str = "Ask a question to a remote A2A agent"
    args_schema: Type[BaseModel] = A2ARemoteAgentInput

    def __init__(
        self,
        client: A2AClient,
        *,
        tool_name: Optional[str] = None,
        tool_description: Optional[str] = None,
        use_streaming: bool = False,
        **kwargs
    ):
        """
        Initialize A2A Remote Agent Tool.

        Args:
            client: Connected A2AClient instance
            tool_name: Custom name for the tool (defaults to ask_<agent_name>)
            tool_description: Custom description (defaults to agent card description)
            use_streaming: Whether to use streaming for responses
        """
        self.client = client
        self.use_streaming = use_streaming
        self.tags = ["a2a", "remote-agent"]

        card = client.agent_card
        name = tool_name or f"ask_{card.name.lower().replace(' ', '_')}"
        description = tool_description or (
            f"Ask the remote agent '{card.name}': {card.description}"
        )

        # Store for cloning
        self._tool_name_override = tool_name
        self._tool_description_override = tool_description

        super().__init__(name=name, description=description, **kwargs)

    def _get_clone_kwargs(self) -> Dict[str, Any]:
        """Get kwargs for cloning this tool."""
        base_kwargs = super()._get_clone_kwargs()
        base_kwargs.update({
            'tool_name': self._tool_name_override,
            'tool_description': self._tool_description_override,
            'use_streaming': self.use_streaming,
        })
        return base_kwargs

    def clone(self) -> "A2ARemoteAgentTool":
        """Clone this tool (shares the client reference)."""
        clone_kwargs = self._get_clone_kwargs()
        # Remove standard AbstractTool params that we handle differently
        clone_kwargs.pop('name', None)
        clone_kwargs.pop('description', None)
        return A2ARemoteAgentTool(client=self.client, **clone_kwargs)

    async def _execute(self, question: str, context_id: Optional[str] = None, **kwargs) -> str:
        """Execute the tool by sending a message to the remote agent."""
        # Also support session_id as an alias
        ctx_id = context_id or kwargs.get("session_id")

        if self.use_streaming:
            chunks = []
            async for chunk in self.client.stream_message(question, context_id=ctx_id):
                chunks.append(chunk)
            return "".join(chunks)
        else:
            task = await self.client.send_message(question, context_id=ctx_id)

            if task.status.state == TaskState.FAILED:
                error = task.status.message.get_text() if task.status.message else "Unknown error"
                return f"Error from remote agent: {error}"

            if task.artifacts:
                return task.artifacts[0].parts[0].text if task.artifacts[0].parts else ""

            return ""


def _create_skill_input_model(skill: AgentSkill) -> Type[AbstractToolArgsSchema]:
    """
    Dynamically create a Pydantic model from an AgentSkill's input_schema.

    Args:
        skill: The AgentSkill with optional input_schema

    Returns:
        A Pydantic model class for the skill's inputs
    """
    # Base fields that are always available
    field_definitions: Dict[str, Any] = {
        'context_id': (
            Optional[str],
            Field(None, description="Optional context ID for multi-turn conversations")
        ),
    }

    # Parse input_schema if available
    if skill.input_schema and isinstance(skill.input_schema, dict):
        properties = skill.input_schema.get('properties', {})
        required = skill.input_schema.get('required', [])

        for prop_name, prop_info in properties.items():
            if prop_name == 'context_id':
                continue  # Already handled

            prop_type = prop_info.get('type', 'string')
            prop_desc = prop_info.get('description', f"Parameter: {prop_name}")

            # Map JSON schema types to Python types
            type_mapping = {
                'string': str,
                'integer': int,
                'number': float,
                'boolean': bool,
                'array': list,
                'object': dict,
            }
            python_type = type_mapping.get(prop_type, str)

            if prop_name in required:
                field_definitions[prop_name] = (
                    python_type,
                    Field(..., description=prop_desc)
                )
            else:
                field_definitions[prop_name] = (
                    Optional[python_type],
                    Field(None, description=prop_desc)
                )

    # Create dynamic model
    model_name = f"{skill.name.replace(' ', '')}Input"
    # Use create_model from pydantic if available, otherwise use type
    try:
        from pydantic import create_model
        return create_model(model_name, __base__=AbstractToolArgsSchema, **field_definitions)
    except ImportError:
        # Fallback: create a simple class
        return type(model_name, (AbstractToolArgsSchema,), {
            '__annotations__': {k: v[0] for k, v in field_definitions.items()}
        })


class A2ARemoteSkillTool(AbstractTool):
    """
    Wraps a specific skill from a remote A2A agent as a tool.

    Properly inherits from AbstractTool for ToolManager compatibility.
    Dynamically generates input schema from the skill's input_schema.
    """

    name: str = "remote_skill"
    description: str = "Invoke a remote skill"
    args_schema: Type[BaseModel] = AbstractToolArgsSchema

    def __init__(
        self,
        client: A2AClient,
        skill: AgentSkill,
        **kwargs
    ):
        """
        Initialize A2A Remote Skill Tool.

        Args:
            client: Connected A2AClient instance
            skill: The AgentSkill to wrap as a tool
        """
        self.client = client
        self.skill = skill
        self.tags = ["a2a", "remote-skill"] + skill.tags

        name = f"remote_{skill.id}"
        description = skill.description or f"Invoke remote skill: {skill.name}"

        # Dynamically create the args schema from skill.input_schema
        self.args_schema = _create_skill_input_model(skill)

        super().__init__(name=name, description=description, **kwargs)

    def _get_clone_kwargs(self) -> Dict[str, Any]:
        """Get kwargs for cloning this tool."""
        base_kwargs = super()._get_clone_kwargs()
        # Remove AbstractTool params we handle in __init__
        base_kwargs.pop('name', None)
        base_kwargs.pop('description', None)
        return base_kwargs

    def clone(self) -> "A2ARemoteSkillTool":
        """Clone this tool (shares the client and skill references)."""
        clone_kwargs = self._get_clone_kwargs()
        return A2ARemoteSkillTool(client=self.client, skill=self.skill, **clone_kwargs)

    async def _execute(self, context_id: Optional[str] = None, **kwargs) -> Any:
        """Execute the remote skill."""
        # Also support session_id as an alias
        ctx_id = context_id or kwargs.pop("session_id", None)
        return await self.client.invoke_skill(self.skill.id, kwargs, context_id=ctx_id)

