# parrot/a2a/server.py
"""
A2A Server - Wraps an AI-Parrot Agent as an A2A-compliant HTTP service.

Identity contract (FEAT-260 / TASK-1643)
-----------------------------------------
Copilot Studio's low-code A2A connection delivers the authenticated end-user's
identity inside the A2A message metadata.  The canonical claim path (in order
of precedence) is:

1. ``message.metadata["user_id"]``             — explicitly set by callers or
                                                  parrot-internal routing.
2. ``message.metadata["from"]["email"]``        — A2A-spec sender object
                                                  (Copilot sets ``from`` dict).
3. ``message.metadata["from"]["id"]``           — fallback when email is absent
                                                  (OID / UPN from Entra token).
4. ``message.metadata["sender"]``               — alternate flat form.
5. ``message.metadata["x-ms-user-email"]``      — Microsoft-injected header
                                                  mirror (some Copilot configs).

If none of these are present the request is rejected — A2AServer never falls
back to a service identity (OQ#1 is resolved: identity IS present in Copilot
A2A messages; absence means an unexpected client).
"""
from __future__ import annotations
from typing import Dict, List, Optional, Any, TYPE_CHECKING
import uuid
import json
import contextlib
import asyncio
from aiohttp import web
from navconfig.logging import logging
from parrot.a2a.models import (
    AgentCard,
    AgentSkill,
    AgentCapabilities,
    Task,
    TaskState,
    TaskStatus,
    Message,
    Part,
    Artifact,
)

if TYPE_CHECKING:
    from parrot.bots.abstract import AbstractBot
    from parrot.tools.abstract import AbstractTool


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
        # FEAT-260 / TASK-1644 — credential gate
        credential_resolvers: Optional[Dict[str, Any]] = None,
        suspended_store: Optional[Any] = None,
        audit_ledger: Optional[Any] = None,
    ):
        """Initialize A2A server wrapper.

        Args:
            agent: The AI-Parrot agent to expose (BasicAgent, etc.)
            base_path: URL prefix for A2A endpoints (default: /a2a)
            version: Version string for the AgentCard
            capabilities: Override auto-detected capabilities
            extra_skills: Additional skills beyond auto-discovered tools
            tags: Tags for the AgentCard
            credential_resolvers: Optional mapping of provider_id →
                :class:`~parrot.auth.credentials.CredentialResolver`.
                When present, tools that declare ``credential_provider``
                are gated: missing credentials suspend the task and return
                a consent link (FEAT-260 / TASK-1644).
            suspended_store: Optional
                :class:`~parrot.human.suspended_store.SuspendedExecutionStore`
                for persisting suspended A2A executions (TASK-1644/1645).
            audit_ledger: Optional
                :class:`~parrot.security.audit_ledger.AuditLedger` for
                recording credentialed tool invocations (TASK-1642/1644).
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

        # FEAT-260 / TASK-1644 — credential gate components
        # provider_id → CredentialResolver
        self._credential_resolvers: Dict[str, Any] = credential_resolvers or {}
        # SuspendedExecutionStore for A2A suspend/resume
        self._suspended_store: Optional[Any] = suspended_store
        # AuditLedger for credentialed invocations
        self._audit_ledger: Optional[Any] = audit_ledger
        # Nonce → interaction_id map (for OAuth callback resume, TASK-1645)
        # The nonce is embedded in the consent URL; the callback correlates it.
        self._a2a_nonce_map: Dict[str, str] = {}

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

    #: Framework-internal tools that every BasicAgent auto-registers (e.g.
    #: BasicAgent._get_default_tools appends ToJsonTool). They are plumbing, not
    #: user-facing capabilities, so they must NOT be advertised as A2A skills:
    #: they clutter the AgentCard and, because their auto-generated `inputSchema`
    #: is a non-spec AgentSkill field, can trip strict consumers like Microsoft
    #: Copilot Studio's "update agent via card" validator.
    _INTERNAL_TOOL_NAMES = frozenset({"to_json"})

    def _build_skills_from_tools(self) -> List[AgentSkill]:
        """Convert agent's tools to A2A skills (excluding internal plumbing)."""
        skills = []

        # Get tools from tool_manager if available
        if hasattr(self.agent, 'tool_manager'):
            tools = self.agent.tool_manager.list_tools()
            for tool_name in tools:
                if tool_name in self._INTERNAL_TOOL_NAMES:
                    continue
                if tool := self.agent.tool_manager.get_tool(tool_name):
                    if skill := self._tool_to_skill(tool):
                        skills.append(skill)

        # Also check direct tools attribute
        elif hasattr(self.agent, 'tools') and self.agent.tools:
            for tool in self.agent.tools:
                if getattr(tool, 'name', None) in self._INTERNAL_TOOL_NAMES:
                    continue
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
            self.logger.warning("Could not convert tool to skill: %s", e)
            return None

    # ─────────────────────────────────────────────────────────────
    # Per-user identity extraction (FEAT-260 / TASK-1643)
    # ─────────────────────────────────────────────────────────────

    def _extract_identity(self, message: Message) -> Optional[str]:
        """Extract the verifiable per-user identity from an inbound A2A message.

        Copilot Studio's low-code A2A connection embeds the authenticated
        end-user identity inside ``message.metadata``.  The claim path
        (checked in precedence order) is documented in the module docstring
        and in the spec §3 Module A1.

        The caller is responsible for deciding what to do when ``None`` is
        returned.  ``process_message`` treats ``None`` as an unauthenticated
        request and fails closed (no service-identity fallback).

        Args:
            message: The inbound A2A :class:`~parrot.a2a.models.Message`.

        Returns:
            The canonical user identity (email) if found, ``None`` otherwise.
        """
        meta: Dict[str, Any] = message.metadata or {}

        # 1. Explicit user_id (set by parrot-internal routing or direct callers)
        if uid := meta.get("user_id"):
            self.logger.debug("A2A identity: user_id from metadata.user_id=%s", uid)
            return str(uid)

        # 2. A2A-spec sender object — Copilot sets `from` with email / OID
        from_obj = meta.get("from") or {}
        if isinstance(from_obj, dict):
            if email := from_obj.get("email"):
                self.logger.debug(
                    "A2A identity: user_id from metadata.from.email=%s", email
                )
                return str(email)
            if oid := from_obj.get("id"):
                self.logger.debug(
                    "A2A identity: user_id from metadata.from.id=%s", oid
                )
                return str(oid)

        # 3. Flat "sender" field
        if sender := meta.get("sender"):
            self.logger.debug(
                "A2A identity: user_id from metadata.sender=%s", sender
            )
            return str(sender)

        # 4. Microsoft-injected header mirror (some Copilot connector configs)
        if ms_email := meta.get("x-ms-user-email"):
            self.logger.debug(
                "A2A identity: user_id from metadata.x-ms-user-email=%s", ms_email
            )
            return str(ms_email)

        self.logger.warning(
            "A2A identity: no verifiable identity found in message.metadata; "
            "checked: user_id, from.email, from.id, sender, x-ms-user-email"
        )
        return None

    # ─────────────────────────────────────────────────────────────
    # Credential gate (FEAT-260 / TASK-1644)
    # ─────────────────────────────────────────────────────────────

    def register_credential_resolver(
        self,
        provider: str,
        resolver: Any,
    ) -> None:
        """Register a :class:`~parrot.auth.credentials.CredentialResolver` for *provider*.

        Tools that declare ``credential_provider = "<provider>"`` are gated
        by the resolver for that provider.  Missing credential → suspend +
        consent link; no service-identity fallback.

        Args:
            provider: Provider identifier, e.g. ``"jira"``, ``"stub"``.
            resolver: A :class:`~parrot.auth.credentials.CredentialResolver`
                implementation for this provider.
        """
        self._credential_resolvers[provider] = resolver
        self.logger.info(
            "A2AServer: registered credential resolver for provider=%s", provider
        )

    async def _on_missing_credential(
        self,
        tool_name: str,
        provider: str,
        channel: str,
        user_id: str,
        task: "Task",
    ) -> "Task":
        """Suspend the A2A task and return a TEXT consent link.

        Called when ``CredentialResolver.resolve()`` returns ``None`` for the
        current ``(channel, user_id)`` pair.  Persists a
        :class:`~parrot.human.suspended_store.SuspendedExecution` in Redis
        (if a ``suspended_store`` is configured) and sets the task state to
        ``INPUT_REQUIRED`` with a TEXT artifact containing the consent link.

        The ``interaction_id`` (UUID) is embedded in the consent URL as the
        ``a2a_state`` query parameter so the OAuth callback (TASK-1645) can
        correlate the callback to the suspended execution.

        Args:
            tool_name: Name of the tool that required credentials.
            provider: Provider identifier for the resolver.
            channel: A2A channel string (e.g. ``"a2a:copilot"``).
            user_id: Canonical per-user identity (email).
            task: The in-flight :class:`~parrot.a2a.models.Task`.

        Returns:
            The task with ``INPUT_REQUIRED`` status and a consent-link artifact.
            NEVER contains a raw token or secret.
        """
        resolver = self._credential_resolvers.get(provider)
        if resolver is None:
            self.logger.error(
                "A2AServer: no resolver for provider=%s; failing task", provider
            )
            task.fail(f"No credential resolver registered for provider={provider!r}.")
            return task

        # Get the auth URL from the resolver (never a secret — only the URL)
        auth_url: str = await resolver.get_auth_url(channel, user_id)

        # Generate the correlation nonce (interaction_id)
        interaction_id = str(uuid.uuid4())

        # Embed the nonce in the consent URL so the callback (TASK-1645) can
        # identify which suspended execution to resume.
        if "?" in auth_url:
            consent_url = f"{auth_url}&a2a_state={interaction_id}"
        else:
            consent_url = f"{auth_url}?a2a_state={interaction_id}"

        self.logger.info(
            "A2AServer: credential missing for provider=%s user=%s tool=%s; "
            "suspending interaction_id=%s",
            provider, user_id, tool_name, interaction_id,
        )

        # Persist the suspended execution (requires a SuspendedExecutionStore)
        if self._suspended_store is not None:
            from parrot.human.suspended_store import SuspendedExecution
            suspended = SuspendedExecution(
                interaction_id=interaction_id,
                session_id=task.context_id or task.id,
                user_id=user_id,
                agent_name=self.agent.name,
                tool_call_id=tool_name,
                messages=[],
            )
            await self._suspended_store.save(suspended, ttl=7200)
            self.logger.debug(
                "A2AServer: suspended execution saved interaction_id=%s", interaction_id
            )

        # Track nonce → interaction_id for resume (TASK-1645)
        self._a2a_nonce_map[interaction_id] = interaction_id

        # Return task with INPUT_REQUIRED status and TEXT consent link.
        # INVARIANT: consent_url may contain the auth URL; it does NOT
        # contain any credential/token/secret.
        consent_text = (
            f"To use {tool_name!r} you need to authorise {provider!r}.\n"
            f"Please visit this link: {consent_url}"
        )
        task.status = TaskStatus(state=TaskState.INPUT_REQUIRED)
        task.artifacts.append(
            Artifact(
                artifact_id=str(uuid.uuid4()),
                parts=[Part.from_text(consent_text)],
                name="consent_required",
                metadata={
                    "requires_auth": True,
                    "provider": provider,
                    "interaction_id": interaction_id,
                    # Never include the raw credential here
                },
            )
        )
        return task

    async def resume_from_oauth_callback(
        self,
        interaction_id: str,
        user_input: str = "",
    ) -> None:
        """Resume a suspended A2A task after a successful OAuth callback.

        Called by the OAuth callback hook (TASK-1645) once the per-user
        credential has been persisted to the vault.  Loads the
        :class:`~parrot.human.suspended_store.SuspendedExecution`, calls
        ``agent.resume(session_id, user_input, state)``, and cleans up the
        suspended entry.

        Args:
            interaction_id: The nonce that was embedded in the consent URL
                (``a2a_state`` query parameter).
            user_input: Optional user message to inject on resume (defaults
                to an empty string — agent re-runs the tool automatically).
        """
        if self._suspended_store is None:
            self.logger.warning(
                "A2AServer.resume_from_oauth_callback: no suspended_store configured; "
                "cannot resume interaction_id=%s",
                interaction_id,
            )
            return

        suspended = await self._suspended_store.load(interaction_id)
        if suspended is None:
            self.logger.warning(
                "A2AServer.resume_from_oauth_callback: "
                "interaction_id=%s not found (expired or already resumed)",
                interaction_id,
            )
            return

        self.logger.info(
            "A2AServer.resume_from_oauth_callback: resuming session=%s user=%s",
            suspended.session_id,
            suspended.user_id,
        )

        try:
            if hasattr(self.agent, "resume"):
                await self.agent.resume(
                    suspended.session_id,
                    user_input,
                    {"interaction_id": interaction_id, "user_id": suspended.user_id},
                )
            else:
                self.logger.warning(
                    "A2AServer.resume_from_oauth_callback: agent %s has no resume(); "
                    "re-asking instead",
                    self.agent.name,
                )
                await self.agent.ask(user_input, session_id=suspended.session_id)
        except Exception:
            self.logger.exception(
                "A2AServer.resume_from_oauth_callback: resume failed for "
                "interaction_id=%s",
                interaction_id,
            )
        finally:
            await self._suspended_store.delete(interaction_id)
            self._a2a_nonce_map.pop(interaction_id, None)

    # ─────────────────────────────────────────────────────────────
    # Core Message Processing (delegates to Agent)
    # ─────────────────────────────────────────────────────────────

    async def process_message(self, message: Message) -> Task:
        """Process an A2A message by delegating to the wrapped agent.

        FEAT-260 / TASK-1643: extracts the per-user identity at the entry
        point and threads ``user_id`` through the processing pipeline.

        FEAT-260 / TASK-1644: if the requested tool declares a
        ``credential_provider``, the credential gate is engaged.  A missing
        per-user credential suspends the task and returns a TEXT consent link;
        there is NEVER a service-identity fallback for per-user tools.
        """
        task = Task.create(context_id=message.context_id)
        task.history.append(message)
        self._tasks[task.id] = task

        # TASK-1643: extract the per-user identity (fail-closed gate seam).
        user_id: Optional[str] = self._extract_identity(message)

        try:
            task.working(f"Processing with {self.agent.name}...")

            # Extract the question/input from message
            question = message.get_text()
            data = message.get_data()

            # Determine A2A channel for credential lookups.
            channel = "a2a:copilot"

            # If structured data with skill/tool request — credential gate applies
            if data and "skill" in data:
                tool_name = data["skill"]
                params = data.get("params", {})
                suspended = await self._try_invoke_with_gate(
                    tool_name, params, user_id=user_id, channel=channel, task=task
                )
                if not suspended:
                    # Result was already set on task by _try_invoke_with_gate
                    pass
            elif data and "tool" in data:
                tool_name = data["tool"]
                params = data.get("params", {})
                suspended = await self._try_invoke_with_gate(
                    tool_name, params, user_id=user_id, channel=channel, task=task
                )
                if not suspended:
                    pass
            else:
                # Default: use agent's ask/chat method
                response = await self._ask_agent(question, message, user_id=user_id)
                task.complete(response)

        except Exception as e:
            self.logger.error("Error processing message: %s", e, exc_info=True)
            task.fail(str(e))

        return task

    async def _try_invoke_with_gate(
        self,
        tool_name: str,
        params: Dict[str, Any],
        *,
        user_id: Optional[str],
        channel: str,
        task: "Task",
    ) -> bool:
        """Invoke a named tool through the credential gate.

        If the tool declares ``credential_provider`` and the gate is
        configured, the per-user credential is resolved first:

        - **Resolved**: the tool runs; an ``AuditLedgerEntry`` is appended;
          ``task.complete(result)`` is called.
        - **Missing**: :meth:`_on_missing_credential` is called, which
          suspends the task and sets ``INPUT_REQUIRED`` status.
        - **No gate**: the tool runs without credential resolution (legacy path).
        - **No identity + gated tool**: fails closed (no service identity).

        Args:
            tool_name: Name of the tool to invoke.
            params: Tool invocation parameters.
            user_id: Canonical per-user identity from :meth:`_extract_identity`.
            channel: A2A channel string (e.g. ``"a2a:copilot"``).
            task: The in-flight :class:`~parrot.a2a.models.Task`.

        Returns:
            ``True`` if the task was suspended (INPUT_REQUIRED) and the
            caller should not call ``task.complete()`` again.
            ``False`` if the task was completed normally (or errored).
        """
        tool = self._find_tool(tool_name)
        if tool is None:
            task.fail(f"Tool/skill '{tool_name}' not found")
            return False

        # TASK-1644: check if this tool declares a credential requirement.
        provider: Optional[str] = getattr(tool, "credential_provider", None)

        if provider and self._credential_resolvers:
            # Gate is active for this tool.
            resolver = self._credential_resolvers.get(provider)
            if resolver is None:
                self.logger.warning(
                    "A2AServer: tool %s requires provider=%s but no resolver registered; "
                    "failing closed (no service-identity fallback)",
                    tool_name, provider,
                )
                task.fail(
                    f"No credential resolver for provider={provider!r}. "
                    "Cannot run a per-user tool without a resolver."
                )
                return False

            if user_id is None:
                # Fail closed — no identity, no service-identity fallback.
                self.logger.warning(
                    "A2AServer: gated tool %s requires identity but user_id is None; "
                    "failing closed",
                    tool_name,
                )
                task.fail(
                    "Identity required to resolve per-user credentials for "
                    f"{tool_name!r} but no identity was found in the request."
                )
                return False

            credential = await resolver.resolve(channel, user_id)

            if credential is None:
                # TASK-1644 invariant: missing credential → suspend, never fallback.
                self.logger.info(
                    "A2AServer: credential missing for %s/%s; suspending", provider, user_id
                )
                await self._on_missing_credential(tool_name, provider, channel, user_id, task)
                return True  # task is now suspended

            # Credential resolved — run the tool and audit.
            self.logger.info(
                "A2AServer: credential resolved for provider=%s user=%s tool=%s",
                provider, user_id, tool_name,
            )
            result = await self._execute_tool(tool, params)

            # Audit the credentialed invocation.
            if self._audit_ledger is not None:
                await self._audit_ledger.append(
                    user_id=user_id,
                    channel=channel,
                    tool=tool_name,
                    provider=provider,
                    credential_material=credential,
                )

            task.complete(result)
            return False

        else:
            # No credential gate — legacy path.
            result = await self._execute_tool(tool, params)
            task.complete(result)
            return False

    async def _ask_agent(
        self,
        question: str,
        message: Message,
        *,
        user_id: Optional[str] = None,
    ) -> Any:
        """Delegate question to agent's ask/chat method.

        Args:
            question: The text extracted from the A2A message.
            message: The original A2A :class:`~parrot.a2a.models.Message`.
            user_id: Canonical per-user identity (email) extracted by
                :meth:`_extract_identity` (FEAT-260 / TASK-1643).
                Forwarded so the credential gate (TASK-1644) can resolve
                per-user credentials inside the agent's tool-execution loop.
        """
        # Prepare kwargs for the agent
        kwargs = self._build_ask_kwargs(message)

        # Pass context_id as session_id if available
        if message.context_id:
            kwargs["session_id"] = message.context_id

        # Thread user_id so the credential gate (TASK-1644) can act on it.
        # AbstractBot.ask accepts **kwargs and may forward extra keys.
        if user_id is not None:
            kwargs["user_id"] = user_id

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

    def _find_tool(self, tool_name: str) -> Optional[Any]:
        """Locate a tool on the agent by name.

        Searches ``agent.tool_manager`` first, then ``agent.tools``.

        Args:
            tool_name: The tool name to look up.

        Returns:
            The tool instance, or ``None`` if not found.
        """
        # Try tool_manager first
        if hasattr(self.agent, 'tool_manager') and self.agent.tool_manager is not None:
            tool = self.agent.tool_manager.get_tool(tool_name)
            if tool:
                return tool

        # Try direct tools list
        if hasattr(self.agent, 'tools') and self.agent.tools:
            for t in self.agent.tools:
                if getattr(t, 'name', None) == tool_name:
                    return t

        return None

    async def _execute_tool(self, tool: Any, params: Dict[str, Any]) -> Any:
        """Execute a tool with the given parameters.

        Args:
            tool: The tool instance to execute.
            params: Keyword arguments forwarded to the tool.

        Returns:
            The tool result.

        Raises:
            NotImplementedError: If the tool has no known executable method.
        """
        if hasattr(tool, '_execute'):
            return await tool._execute(**params)
        elif hasattr(tool, 'run'):
            return await tool.run(**params)
        elif hasattr(tool, '_arun'):
            return await tool._arun(**params)
        else:
            raise NotImplementedError(
                f"Tool {getattr(tool, 'name', repr(tool))} has no executable method"
            )

    async def _invoke_skill(self, skill_id: str, params: Dict[str, Any]) -> Any:
        """Invoke a specific skill (tool) by ID (legacy direct-invocation path)."""
        return await self._invoke_tool(skill_id, params)

    async def _invoke_tool(self, tool_name: str, params: Dict[str, Any]) -> Any:
        """Invoke a specific tool by name (legacy direct-invocation path).

        This method does NOT apply the credential gate; it is the pre-FEAT-260
        direct-execution path.  The gated path goes through
        :meth:`_try_invoke_with_gate` (called from :meth:`process_message`).
        """
        tool = self._find_tool(tool_name)
        if not tool:
            raise ValueError(f"Tool/skill '{tool_name}' not found")
        return await self._execute_tool(tool, params)

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
            # configuration is accepted but not yet used; reserved for future
            # push-notification / streaming config per the A2A spec.
            _config = data.get("configuration", {})  # noqa: F841

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
            self.logger.error("Error in send_message: %s", e, exc_info=True)
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
                self.logger.error("Error in streaming: %s", e, exc_info=True)
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
            self.logger.error("Error setting up stream: %s", e, exc_info=True)
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
            self.logger.error("Streaming error: %s", e, exc_info=True)
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
