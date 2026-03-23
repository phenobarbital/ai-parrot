# parrot/a2a/server.py
"""
A2A Server - Wraps an AI-Parrot Agent as an A2A-compliant HTTP service.
"""
from __future__ import annotations
from typing import Dict, List, Optional, Any, TYPE_CHECKING, Union
import uuid
import json
import contextlib
import asyncio
from aiohttp import web
from navconfig.logging import logging
from .models import (
    AgentCard,
    AgentSkill,
    AgentCapabilities,
    Task,
    TaskState,
    TaskStatus,
    Message,
    Part,
    Artifact,
    Role,
)

if TYPE_CHECKING:
    from ..bots.abstract import AbstractBot
    from ..tools.abstract import AbstractTool


class A2AServer:
    """
    Wraps an AI-Parrot Agent (BasicAgent/AbstractBot) as an A2A HTTP service.

    This server exposes your existing agent via the A2A protocol, automatically
    generating the AgentCard from the agent's properties and tools.

    Example:
        from parrot.bots import Agent
        from parrot.a2a import A2AServer

        # Create your agent as usual
        agent = Agent(
            name="CustomerSupport",
            llm="anthropic:claude-sonnet-4-20250514",
            tools=[QueryCustomersTool(), CreateTicketTool()]
        )
        await agent.configure()

        # Wrap it as A2A service
        a2a = A2AServer(agent)

        # Mount on your aiohttp app
        app = web.Application()
        a2a.setup(app)

        # Agent is now accessible at:
        # - GET  /.well-known/agent.json  (discovery)
        # - POST /a2a/message/send        (send message)
        # - POST /a2a/message/stream      (streaming)
        # - GET  /a2a/tasks/{id}          (get task)
        # etc.
    """

    def __init__(
        self,
        agent: "AbstractBot",
        *,
        base_path: str = "/a2a",
        version: str = "1.0.0",
        capabilities: Optional[AgentCapabilities] = None,
        extra_skills: Optional[List[AgentSkill]] = None,
        tags: Optional[List[str]] = None,
    ):
        """
        Initialize A2A server wrapper.

        Args:
            agent: The AI-Parrot agent to expose (BasicAgent, etc.)
            base_path: URL prefix for A2A endpoints (default: /a2a)
            version: Version string for the AgentCard
            capabilities: Override auto-detected capabilities
            extra_skills: Additional skills beyond auto-discovered tools
            tags: Tags for the AgentCard
        """
        self.agent = agent
        self.base_path = base_path.rstrip("/")
        self.version = version
        self.capabilities = capabilities or AgentCapabilities(streaming=True)
        self.extra_skills = extra_skills or []
        self.tags = tags or []

        # Runtime state
        self._tasks: Dict[str, Task] = {}
        self._app: Optional[web.Application] = None
        self._url: Optional[str] = None
        self._agent_card: Optional[AgentCard] = None

        self.logger = logging.getLogger(f"A2A.{agent.name}")

    def setup(self, app: web.Application, url: Optional[str] = None) -> None:
        """
        Register A2A routes on an aiohttp application.

        Args:
            app: The aiohttp Application
            url: Public URL where this agent is accessible (for AgentCard)
        """
        self._app = app
        self._url = url

        # Store reference in app
        app[f"a2a_server_{self.agent.name}"] = self

        # Well-known agent card endpoint
        app.router.add_get("/.well-known/agent.json", self._handle_agent_card)

        # A2A HTTP+JSON Binding endpoints
        app.router.add_post(f"{self.base_path}/message/send", self._handle_send_message)
        app.router.add_post(f"{self.base_path}/message/stream", self._handle_stream_message)
        app.router.add_get(f"{self.base_path}/tasks/{{task_id}}", self._handle_get_task)
        app.router.add_get(f"{self.base_path}/tasks", self._handle_list_tasks)
        app.router.add_post(f"{self.base_path}/tasks/{{task_id}}/cancel", self._handle_cancel_task)
        app.router.add_get(f"{self.base_path}/tasks/{{task_id}}/subscribe", self._handle_subscribe)

        # JSON-RPC binding (alternative)
        app.router.add_post(f"{self.base_path}/rpc", self._handle_jsonrpc)

        self.logger.info(
            f"A2A server mounted for agent '{self.agent.name}' at {self.base_path}"
        )

    # ─────────────────────────────────────────────────────────────
    # AgentCard Generation (from Agent properties)
    # ─────────────────────────────────────────────────────────────

    def get_agent_card(self) -> AgentCard:
        """Generate AgentCard from the wrapped agent's properties."""
        if self._agent_card:
            return self._agent_card

        # Build skills from agent's tools
        skills = self._build_skills_from_tools()
        skills.extend(self.extra_skills)

        # Add a default "chat" skill if no tools
        if not skills:
            skills.append(AgentSkill(
                id="chat",
                name="Chat",
                description=f"Have a conversation with {self.agent.name}",
                tags=["conversation", "chat"],
            ))

        # Build description from agent properties
        description_parts = []
        if hasattr(self.agent, 'description') and self.agent.description:
            description_parts.append(self.agent.description)
        if hasattr(self.agent, 'role') and self.agent.role:
            description_parts.append(f"Role: {self.agent.role}")
        if hasattr(self.agent, 'goal') and self.agent.goal:
            description_parts.append(f"Goal: {self.agent.goal}")

        description = " | ".join(description_parts) if description_parts else f"AI Agent: {self.agent.name}"

        self._agent_card = AgentCard(
            name=self.agent.name,
            description=description,
            version=self.version,
            url=self._url,
            skills=skills,
            capabilities=self.capabilities,
            tags=self.tags or getattr(self.agent, 'tags', []),
        )

        return self._agent_card

    def _build_skills_from_tools(self) -> List[AgentSkill]:
        """Convert agent's tools to A2A skills."""
        skills = []

        # Get tools from tool_manager if available
        if hasattr(self.agent, 'tool_manager'):
            tools = self.agent.tool_manager.list_tools()
            for tool_name in tools:
                if tool := self.agent.tool_manager.get_tool(tool_name):
                    if skill := self._tool_to_skill(tool):
                        skills.append(skill)

        # Also check direct tools attribute
        elif hasattr(self.agent, 'tools') and self.agent.tools:
            for tool in self.agent.tools:
                if skill := self._tool_to_skill(tool):
                    skills.append(skill)

        return skills

    def _tool_to_skill(self, tool: "AbstractTool") -> Optional[AgentSkill]:
        """Convert an AbstractTool to an AgentSkill."""
        try:
            name = getattr(tool, 'name', None)
            if not name:
                return None

            description = getattr(tool, 'description', f"Tool: {name}")

            # Try to get input schema from args_schema (Pydantic model)
            input_schema = None
            if hasattr(tool, 'args_schema') and tool.args_schema:
                with contextlib.suppress(Exception):
                    input_schema = tool.args_schema.model_json_schema()

            # Get tags if available
            tags = getattr(tool, 'tags', [])
            if isinstance(tags, str):
                tags = [tags]

            return AgentSkill(
                id=name,
                name=name.replace("_", " ").title(),
                description=description,
                tags=list(tags),
                input_schema=input_schema,
            )
        except Exception as e:
            self.logger.warning(f"Could not convert tool to skill: {e}")
            return None

    # ─────────────────────────────────────────────────────────────
    # Core Message Processing (delegates to Agent)
    # ─────────────────────────────────────────────────────────────

    async def process_message(self, message: Message) -> Task:
        """
        Process an A2A message by delegating to the wrapped agent.
        """
        task = Task.create(context_id=message.context_id)
        task.history.append(message)
        self._tasks[task.id] = task

        try:
            task.working(f"Processing with {self.agent.name}...")

            # Extract the question/input from message
            question = message.get_text()
            data = message.get_data()

            # If structured data with skill/tool request
            if data and "skill" in data:
                response = await self._invoke_skill(data["skill"], data.get("params", {}))
            elif data and "tool" in data:
                response = await self._invoke_tool(data["tool"], data.get("params", {}))
            else:
                # Default: use agent's ask/chat method
                response = await self._ask_agent(question, message)

            task.complete(response)

        except Exception as e:
            self.logger.error(f"Error processing message: {e}", exc_info=True)
            task.fail(str(e))

        return task

    async def _ask_agent(self, question: str, message: Message) -> Any:
        """Delegate question to agent's ask/chat method."""
        # Prepare kwargs for the agent
        kwargs = self._build_ask_kwargs(message)

        # Pass context_id as session_id if available
        if message.context_id:
            kwargs["session_id"] = message.context_id

        # Use ask() method (most compatible)
        if hasattr(self.agent, 'ask'):
            response = await self.agent.ask(question, **kwargs)
        elif hasattr(self.agent, 'chat'):
            response = await self.agent.chat(question, **kwargs)
        elif hasattr(self.agent, 'conversation'):
            response = await self.agent.conversation(question, **kwargs)
        else:
            raise NotImplementedError(
                f"Agent {self.agent.name} doesn't have ask/chat/conversation method"
            )

        return response

    async def _invoke_skill(self, skill_id: str, params: Dict[str, Any]) -> Any:
        """Invoke a specific skill (tool) by ID."""
        return await self._invoke_tool(skill_id, params)

    async def _invoke_tool(self, tool_name: str, params: Dict[str, Any]) -> Any:
        """Invoke a specific tool by name."""
        tool = None

        # Try tool_manager first
        if hasattr(self.agent, 'tool_manager'):
            tool = self.agent.tool_manager.get_tool(tool_name)

        # Try direct tools list
        if not tool and hasattr(self.agent, 'tools'):
            for t in self.agent.tools:
                if getattr(t, 'name', None) == tool_name:
                    tool = t
                    break

        if not tool:
            raise ValueError(f"Tool/skill '{tool_name}' not found")

        # Execute the tool
        if hasattr(tool, '_execute'):
            result = await tool._execute(**params)
        elif hasattr(tool, 'run'):
            result = await tool.run(**params)
        elif hasattr(tool, '_arun'):
            result = await tool._arun(**params)
        else:
            raise NotImplementedError(f"Tool {tool_name} has no executable method")

        return result

    # ─────────────────────────────────────────────────────────────
    # HTTP Handlers
    # ─────────────────────────────────────────────────────────────

    async def _handle_agent_card(self, request: web.Request) -> web.Response:
        """GET /.well-known/agent.json"""
        card = self.get_agent_card()
        return web.json_response(card.to_dict())

    async def _handle_send_message(self, request: web.Request) -> web.Response:
        """POST /a2a/message/send"""
        try:
            data = await request.json()
            message = Message.from_dict(data.get("message", {}))
            config = data.get("configuration", {})

            task = await self.process_message(message)

            # If blocking mode, wait for completion (already done in process_message)
            # but if we had async processing, we'd wait here

            return web.json_response(task.to_dict())

        except json.JSONDecodeError:
            return web.json_response(
                {"error": {"code": "InvalidJSON", "message": "Invalid JSON body"}},
                status=400
            )
        except Exception as e:
            self.logger.error(f"Error in send_message: {e}", exc_info=True)
            return web.json_response(
                {"error": {"code": "InternalError", "message": str(e)}},
                status=500
            )

    async def _handle_stream_message(self, request: web.Request) -> web.StreamResponse:
        """POST /a2a/message/stream - SSE streaming response."""
        response = web.StreamResponse(
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            }
        )
        await response.prepare(request)

        try:
            data = await request.json()
            message = Message.from_dict(data.get("message", {}))

            # Create task
            task = Task.create(context_id=message.context_id)
            task.history.append(message)
            self._tasks[task.id] = task

            # Send initial task
            await self._send_sse(response, {"task": task.to_dict()})

            # Send working status
            task.working(f"Processing with {self.agent.name}...")
            await self._send_sse(response, {
                "statusUpdate": {
                    "taskId": task.id,
                    "contextId": task.context_id,
                    "status": {"state": "working"},
                    "final": False
                }
            })

            # Process with streaming
            try:
                question = message.get_text()

                # Try to use streaming method
                if hasattr(self.agent, 'ask_stream'):
                    await self._stream_with_ask_stream(response, task, question, message)
                else:
                    # Fallback to non-streaming
                    await self._stream_fallback(response, task, question, message)

            except Exception as e:
                self.logger.error(f"Error in streaming: {e}", exc_info=True)
                task.fail(str(e))
                await self._send_sse(response, {
                    "statusUpdate": {
                        "taskId": task.id,
                        "contextId": task.context_id,
                        "status": {
                            "state": "failed",
                            "message": {"role": "agent", "parts": [{"text": str(e)}]}
                        },
                        "final": True
                    }
                })

        except Exception as e:
            self.logger.error(f"Error setting up stream: {e}", exc_info=True)
            await self._send_sse(response, {"error": {"message": str(e)}})

        await response.write_eof()
        return response

    async def _stream_with_ask_stream(
        self,
        response: web.StreamResponse,
        task: Task,
        question: str,
        message: Message
    ) -> None:
        """Stream using agent's ask_stream method with light buffering."""
        kwargs = {}
        if message.context_id:
            kwargs["session_id"] = message.context_id

        collected_text = []
        artifact_id = str(uuid.uuid4())

        # Light buffering - balance between responsiveness and efficiency
        buffer = []
        buffer_size = 0
        MIN_CHUNK_SIZE = 15  # ~3-4 words
        MAX_BUFFER_TIME = 0.1  # 100ms max wait
        last_flush = asyncio.get_event_loop().time()

        async def flush_buffer():
            nonlocal buffer, buffer_size, last_flush
            if buffer:
                chunk_text = "".join(buffer)
                collected_text.append(chunk_text)

                await self._send_sse(response, {
                    "artifactUpdate": {
                        "taskId": task.id,
                        "contextId": task.context_id,
                        "artifact": {
                            "artifactId": artifact_id,
                            "name": "response",
                            "parts": [{"text": chunk_text}]
                        },
                        "append": len(collected_text) > 1,
                        "lastChunk": False
                    }
                })

                buffer = []
                buffer_size = 0
                last_flush = asyncio.get_event_loop().time()

        try:
            async for chunk in self.agent.ask_stream(question, **kwargs):
                chunk_text = self._extract_chunk_text(chunk)

                if chunk_text:
                    buffer.append(chunk_text)
                    buffer_size += len(chunk_text)

                    current_time = asyncio.get_event_loop().time()
                    time_since_flush = current_time - last_flush

                    # Flush on size OR time threshold
                    if buffer_size >= MIN_CHUNK_SIZE or time_since_flush >= MAX_BUFFER_TIME:
                        await flush_buffer()

            # Flush remaining
            await flush_buffer()

            # Final artifact with complete text
            full_text = "".join(collected_text)
            artifact = Artifact(
                artifact_id=artifact_id,
                name="response",
                parts=[Part.from_text(full_text)]
            )
            task.artifacts.append(artifact)

            await self._send_sse(response, {
                "artifactUpdate": {
                    "taskId": task.id,
                    "contextId": task.context_id,
                    "artifact": artifact.to_dict(),
                    "append": False,
                    "lastChunk": True
                }
            })

            task.status = TaskStatus(state=TaskState.COMPLETED)
            await self._send_sse(response, {
                "statusUpdate": {
                    "taskId": task.id,
                    "contextId": task.context_id,
                    "status": {"state": "completed"},
                    "final": True
                }
            })

        except Exception as e:
            self.logger.error(f"Streaming error: {e}", exc_info=True)
            raise

    async def _stream_fallback(
        self,
        response: web.StreamResponse,
        task: Task,
        question: str,
        message: Message
    ) -> None:
        """Fallback when streaming is not available - use regular ask."""
        result = await self._ask_agent(question, message)

        # Send artifact
        artifact = Artifact.from_response(result)
        task.artifacts.append(artifact)
        await self._send_sse(response, {
            "artifactUpdate": {
                "taskId": task.id,
                "contextId": task.context_id,
                "artifact": artifact.to_dict(),
                "lastChunk": True
            }
        })

        # Send completed
        task.status = TaskStatus(state=TaskState.COMPLETED)
        await self._send_sse(response, {
            "statusUpdate": {
                "taskId": task.id,
                "contextId": task.context_id,
                "status": {"state": "completed"},
                "final": True
            }
        })

    def _build_ask_kwargs(self, message: Message) -> Dict[str, Any]:
        """Build kwargs for ask/ask_stream methods."""
        kwargs = {}

        # Get max_tokens from agent
        max_tokens = getattr(self.agent, 'max_tokens', None)
        if max_tokens is None and hasattr(self.agent, '_llm') and self.agent._llm:
            max_tokens = getattr(self.agent._llm, 'max_tokens', None)
        kwargs["max_tokens"] = max_tokens or 4096

        # Pass context_id as session_id
        if message.context_id:
            kwargs["session_id"] = message.context_id

        return kwargs

    def _extract_chunk_text(self, chunk: Any) -> Optional[str]:
        """Extract text content from a stream chunk."""
        if chunk is None:
            return None

        # String chunk
        if isinstance(chunk, str):
            return chunk

        # AIMessage or similar response object
        if hasattr(chunk, 'content'):
            return chunk.content
        if hasattr(chunk, 'text'):
            return chunk.text
        if hasattr(chunk, 'delta'):
            delta = chunk.delta
            if hasattr(delta, 'text'):
                return delta.text
            if hasattr(delta, 'content'):
                return delta.content

        # Dict chunk
        if isinstance(chunk, dict):
            return chunk.get('text') or chunk.get('content') or chunk.get('delta', {}).get('text')

        # Fallback
        return str(chunk) if chunk else None

    async def _send_sse(self, response: web.StreamResponse, data: Dict[str, Any]):
        """Send SSE event."""
        await response.write(f"data: {json.dumps(data)}\n\n".encode())

    async def _handle_get_task(self, request: web.Request) -> web.Response:
        """GET /a2a/tasks/{task_id}"""
        task_id = request.match_info["task_id"]
        if task := self._tasks.get(task_id):
            return web.json_response(task.to_dict())

        return web.json_response(
            {"error": {"code": "TaskNotFoundError", "message": f"Task {task_id} not found"}},
            status=404
        )

    async def _handle_list_tasks(self, request: web.Request) -> web.Response:
        """GET /a2a/tasks"""
        context_id = request.query.get("contextId")
        state = request.query.get("status")
        page_size = int(request.query.get("pageSize", 50))

        tasks = list(self._tasks.values())

        if context_id:
            tasks = [t for t in tasks if t.context_id == context_id]
        if state:
            tasks = [t for t in tasks if t.status.state.value == state]

        tasks = tasks[:page_size]

        return web.json_response({
            "tasks": [t.to_dict() for t in tasks],
            "totalSize": len(tasks),
            "pageSize": page_size,
            "nextPageToken": ""
        })

    async def _handle_cancel_task(self, request: web.Request) -> web.Response:
        """POST /a2a/tasks/{task_id}/cancel"""
        task_id = request.match_info["task_id"]
        task = self._tasks.get(task_id)

        if not task:
            return web.json_response(
                {"error": {"code": "TaskNotFoundError"}},
                status=404
            )

        terminal_states = {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}
        if task.status.state in terminal_states:
            return web.json_response(
                {"error": {"code": "TaskNotCancelableError"}},
                status=400
            )

        task.status = TaskStatus(state=TaskState.CANCELLED)
        return web.json_response(task.to_dict())

    async def _handle_subscribe(self, request: web.Request) -> web.StreamResponse:
        """GET /a2a/tasks/{task_id}/subscribe"""
        task_id = request.match_info["task_id"]
        task = self._tasks.get(task_id)

        if not task:
            return web.json_response(
                {"error": {"code": "TaskNotFoundError"}},
                status=404
            )

        response = web.StreamResponse(
            headers={"Content-Type": "text/event-stream"}
        )
        await response.prepare(request)

        # Send current state
        await self._send_sse(response, {"task": task.to_dict()})

        # For now, just close (in production, would subscribe to updates)
        await response.write_eof()
        return response

    async def _handle_jsonrpc(self, request: web.Request) -> web.Response:
        """POST /a2a/rpc - JSON-RPC 2.0 binding."""
        data = await request.json()
        method = data.get("method")
        params = data.get("params", {})
        req_id = data.get("id")

        try:
            if method == "message/send":
                message = Message.from_dict(params.get("message", {}))
                task = await self.process_message(message)
                result = task.to_dict()
            elif method == "tasks/get":
                task = self._tasks.get(params.get("id"))
                result = task.to_dict() if task else None
            elif method == "tasks/list":
                tasks = list(self._tasks.values())
                result = {"tasks": [t.to_dict() for t in tasks]}
            else:
                return web.json_response({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"}
                })

            return web.json_response({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": result
            })
        except Exception as e:
            return web.json_response({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32603, "message": str(e)}
            })


class A2AEnabledMixin:
    """
    Mixin to add A2A server capabilities to an agent class.

    Similar to MCPEnabledMixin, this adds A2A methods directly to your agent.

    Example:
        class MyAgent(A2AEnabledMixin, BasicAgent):
            pass

        agent = MyAgent(name="test", llm="openai:gpt-4")
        await agent.configure()

        # Start A2A server
        app = web.Application()
        agent.setup_a2a(app, url="https://my-agent.example.com")
    """

    _a2a_server: Optional[A2AServer] = None

    def setup_a2a(
        self,
        app: web.Application,
        url: Optional[str] = None,
        base_path: str = "/a2a",
        **kwargs
    ) -> A2AServer:
        """
        Setup A2A server for this agent.

        Args:
            app: aiohttp Application to mount routes on
            url: Public URL for AgentCard
            base_path: URL prefix for A2A endpoints
            **kwargs: Additional A2AServer options

        Returns:
            The A2AServer instance
        """
        self._a2a_server = A2AServer(
            self,
            base_path=base_path,
            **kwargs
        )
        self._a2a_server.setup(app, url=url)
        return self._a2a_server

    def get_a2a_server(self) -> Optional[A2AServer]:
        """Get the A2A server instance if setup."""
        return self._a2a_server

    def get_agent_card(self) -> Optional[AgentCard]:
        """Get the AgentCard if A2A is setup."""
        return self._a2a_server.get_agent_card() if self._a2a_server else None
