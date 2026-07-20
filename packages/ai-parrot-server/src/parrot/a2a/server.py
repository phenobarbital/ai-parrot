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
from typing import Dict, List, Optional, Any, Union, TYPE_CHECKING
import uuid
import json
import contextlib
import asyncio
from aiohttp import web
from navconfig.logging import logging
from parrot.models.outputs import OutputMode
from parrot.outputs.formats.text import markdown_to_plain
from parrot.a2a.models import (
    AgentCard,
    AgentInterface,
    AgentSkill,
    AgentCapabilities,
    Task,
    TaskState,
    TaskStatus,
    Message,
    Part,
    Artifact,
    Role,
    SendMessageConfiguration,
    TaskPushNotificationConfig,
    serialize_task_state,
    serialize_role,
    parse_task_state,
    A2A_ERROR_CODES,
)

if TYPE_CHECKING:
    from parrot.bots.abstract import AbstractBot
    from parrot.tools.abstract import AbstractTool
    from parrot.a2a.push_notifications import PushNotificationStore


class _A2ARpcError(Exception):
    """Internal signal for an A2A error inside a JSON-RPC dispatch.

    ``error_name`` must be a key of ``A2A_ERROR_CODES``; the dispatcher maps it
    to the numeric JSON-RPC code.
    """

    def __init__(self, error_name: str, message: str = "", code: Optional[int] = None):
        self.error_name = error_name
        self.message = message or error_name
        # Optional explicit JSON-RPC code for errors outside A2A_ERROR_CODES
        # (e.g. the standard -32602 Invalid params).
        self.code = code
        super().__init__(self.message)


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
        # FEAT-264 — broker (preferred, surface-agnostic credential gate)
        broker: Optional[Any] = None,
        identity_mapper: Optional[Any] = None,
        # FEAT-260 / TASK-1644 — deprecated; pass a CredentialBroker via broker= instead
        credential_resolvers: Optional[Dict[str, Any]] = None,
        suspended_store: Optional[Any] = None,
        audit_ledger: Optional[Any] = None,
        push_store: Optional["PushNotificationStore"] = None,
        output_mode: Union[OutputMode, str, None] = OutputMode.TEXT,
    ):
        """Initialize A2A server wrapper.

        Args:
            agent: The AI-Parrot agent to expose (BasicAgent, etc.)
            base_path: URL prefix for A2A endpoints (default: /a2a)
            version: Version string for the AgentCard
            capabilities: Override auto-detected capabilities
            extra_skills: Additional skills beyond auto-discovered tools
            tags: Tags for the AgentCard
            output_mode: :class:`~parrot.models.outputs.OutputMode` requested
                from the agent for every A2A turn. Defaults to
                ``OutputMode.TEXT`` (markdown-free plain text) because A2A
                consumers — notably Microsoft Copilot — render ``TextPart``
                content literally, so markdown arrives as raw ``**bold**``
                and pipe tables. Pass ``OutputMode.DEFAULT``/``None`` (or the
                string ``"default"``) to restore the agent's native
                (typically markdown) output.
            broker: Optional :class:`~parrot.auth.broker.CredentialBroker`
                (FEAT-264).  When supplied, per-user credentials are resolved
                through the broker; missing credentials suspend the task and
                return a consent link.  Takes precedence over
                ``credential_resolvers``.
            identity_mapper: Optional
                :class:`~parrot.auth.identity.CanonicalIdentityMapper` for
                cross-surface identity normalisation (FEAT-264 / TASK-1671).
            credential_resolvers: Deprecated.  Pass a
                :class:`~parrot.auth.broker.CredentialBroker` via ``broker=``
                instead.  If supplied a broker is built from these resolvers
                for backward compatibility (FEAT-260 / TASK-1644).
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
        self._output_mode: OutputMode = self._coerce_output_mode(output_mode)

        # Runtime state
        self._tasks: Dict[str, Task] = {}
        self._app: Optional[web.Application] = None
        self._url: Optional[str] = None
        self._agent_card: Optional[AgentCard] = None
        # Strong references to fire-and-forget background tasks (returnImmediately)
        # so the event loop does not garbage-collect them mid-execution.
        self._background_tasks: set = set()

        # Push notification config store (FEAT-272 / TASK-1716). Auto-create an
        # in-memory store when the agent advertises push_notifications.
        self._push_store: Optional["PushNotificationStore"] = push_store
        if self._push_store is None and self.capabilities.push_notifications:
            from parrot.a2a.push_notifications import PushNotificationStore
            self._push_store = PushNotificationStore()

        # SuspendedExecutionStore for A2A suspend/resume
        self._suspended_store: Optional[Any] = suspended_store
        # AuditLedger — kept for backward-compat callers; broker uses its own ref.
        self._audit_ledger: Optional[Any] = audit_ledger
        # Nonce → interaction_id map (for OAuth callback resume, TASK-1645)
        # The nonce is embedded in the consent URL; the callback correlates it.
        self._a2a_nonce_map: Dict[str, str] = {}

        # FEAT-264 — credential broker (authoritative gate).
        # credential_resolvers= is a backward-compat shim: build a broker from the dict.
        # provider_id → resolver dict is preserved for register_credential_resolver() compat.
        self._credential_resolvers: Dict[str, Any] = {}
        if broker is not None:
            self._broker: Optional[Any] = broker
        elif credential_resolvers:
            from parrot.auth.broker import CredentialBroker as _CB
            _b = _CB(audit_ledger=audit_ledger)
            for _prov, _res in credential_resolvers.items():
                _b.register(_prov, _res)
                self._credential_resolvers[_prov] = _res
            self._broker = _b
        else:
            self._broker = None

        # CanonicalIdentityMapper for cross-surface identity normalisation (TASK-1671).
        self._identity_mapper: Optional[Any] = identity_mapper

        self.logger = logging.getLogger(f"A2A.{agent.name}")

    def setup(
        self,
        app: web.Application,
        url: Optional[str] = None,
        *,
        register_well_known: bool = True,
    ) -> None:
        """
        Register A2A routes on an aiohttp application.

        Args:
            app: The aiohttp Application
            url: Public URL where this agent is accessible (for AgentCard)
            register_well_known: When ``True`` (default), register the fixed
                ``GET /.well-known/agent.json`` discovery route serving this
                agent's card. Set to ``False`` when mounting additional agents
                on a shared app where the single well-known route has already
                been claimed by an earlier agent — those agents remain
                discoverable via a multi-agent directory endpoint. Prevents a
                redundant, unreachable duplicate route on the shared router.
        """
        self._app = app
        self._url = url

        # Store reference in app
        app[f"a2a_server_{self.agent.name}"] = self

        bp = self.base_path

        # Well-known agent card endpoints (single fixed route set per app):
        #   - /.well-known/agent-card.json  (A2A v1.0 discovery URI)
        #   - /.well-known/agent.json       (v0.3 compat)
        # Gated on register_well_known so additional agents mounted on a shared
        # app don't register redundant, unreachable duplicate routes.
        if register_well_known:
            app.router.add_get("/.well-known/agent-card.json", self._handle_agent_card)
            app.router.add_get("/.well-known/agent.json", self._handle_agent_card)

        # A2A HTTP+JSON Binding endpoints (v0.3 compat surface).
        app.router.add_post(f"{bp}/message/send", self._handle_send_message)
        app.router.add_post(f"{bp}/message/stream", self._handle_stream_message)
        app.router.add_get(f"{bp}/tasks/{{task_id}}", self._handle_get_task)
        app.router.add_get(f"{bp}/tasks", self._handle_list_tasks)
        app.router.add_post(f"{bp}/tasks/{{task_id}}/cancel", self._handle_cancel_task)
        app.router.add_get(f"{bp}/tasks/{{task_id}}/subscribe", self._handle_subscribe)

        # A2A v1.0 REST-binding routes (colon-suffixed method style). aiohttp
        # treats the colon as a literal in a fixed path segment.
        app.router.add_post(f"{bp}/message:send", self._handle_send_message)
        app.router.add_post(f"{bp}/message:stream", self._handle_stream_message)
        app.router.add_post(f"{bp}/tasks/{{task_id}}:cancel", self._handle_cancel_task)
        app.router.add_post(f"{bp}/tasks/{{task_id}}:subscribe", self._handle_subscribe)

        # Push notification config CRUD (v1.0). Registered only when the agent
        # advertises push_notifications (a store is present).
        if self._push_store is not None:
            app.router.add_post(
                f"{bp}/tasks/{{task_id}}/pushNotificationConfigs",
                self._handle_push_config_create,
            )
            app.router.add_get(
                f"{bp}/tasks/{{task_id}}/pushNotificationConfigs/{{config_id}}",
                self._handle_push_config_get,
            )
            app.router.add_get(
                f"{bp}/tasks/{{task_id}}/pushNotificationConfigs",
                self._handle_push_config_list,
            )
            app.router.add_delete(
                f"{bp}/tasks/{{task_id}}/pushNotificationConfigs/{{config_id}}",
                self._handle_push_config_delete,
            )

        # JSON-RPC binding (alternative)
        app.router.add_post(f"{bp}/rpc", self._handle_jsonrpc)

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

        # v1.0 AgentCard: describe the endpoint via a structured
        # `supported_interfaces` entry instead of the flat v0.3 `url`. Version
        # negotiation at serialization time (to_dict(version=)) reproduces the
        # flat shape for v0.3 clients.
        self._agent_card = AgentCard(
            name=self.agent.name,
            description=description,
            version=self.version,
            supported_interfaces=[
                AgentInterface(
                    url=self._url,
                    protocol_binding="JSONRPC",
                    protocol_version="1.0",
                )
            ],
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

        # Get tools from tool_manager if available (guard against a None
        # tool_manager so agents without one fall through to `tools`).
        if getattr(self.agent, 'tool_manager', None) is not None:
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

        # FEAT-264 / TASK-1671 — canonical identity mapper (cross-surface normalisation).
        # Try the mapper first; it handles OID / email precedence across A2A and MSAgentSDK.
        if self._identity_mapper is not None and meta:
            canonical = self._identity_mapper.to_canonical(meta)
            if canonical is not None:
                self.logger.debug(
                    "A2A identity: canonical via IdentityMapper=%s", canonical
                )
                return canonical

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
        # Keep broker in sync.
        if self._broker is not None:
            self._broker.register(provider, resolver)
        else:
            # Build broker lazily so existing resolvers are gated.
            from parrot.auth.broker import CredentialBroker as _CB
            self._broker = _CB(audit_ledger=self._audit_ledger)
            for _p, _r in self._credential_resolvers.items():
                self._broker.register(_p, _r)
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
        *,
        auth_url: Optional[str] = None,
    ) -> "Task":
        """Suspend the A2A task and return a TEXT consent link.

        Called when the credential gate (broker or legacy resolver dict) signals
        that the user has not yet authorised for *provider*.  Persists a
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
            auth_url: Consent URL to present.  When the broker path is used
                this is taken from :class:`~parrot.auth.credentials.NeedsAuth`.
                When ``None``, it is fetched from the legacy resolver dict.

        Returns:
            The task with ``INPUT_REQUIRED`` status and a consent-link artifact.
            NEVER contains a raw token or secret.
        """
        if auth_url is None:
            # Legacy path: obtain auth URL from the old-style resolver dict.
            resolver = self._credential_resolvers.get(provider)
            if resolver is None:
                self.logger.error(
                    "A2AServer: no resolver for provider=%s; failing task", provider
                )
                task.fail(f"No credential resolver registered for provider={provider!r}.")
                return task
            # Get the auth URL from the resolver (never a secret — only the URL)
            auth_url = await resolver.get_auth_url(channel, user_id)

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

    async def process_message(
        self, message: Message, task: Optional[Task] = None
    ) -> Task:
        """Process an A2A message by delegating to the wrapped agent.

        FEAT-260 / TASK-1643: extracts the per-user identity at the entry
        point and threads ``user_id`` through the processing pipeline.

        FEAT-260 / TASK-1644: if the requested tool declares a
        ``credential_provider``, the credential gate is engaged.  A missing
        per-user credential suspends the task and returns a TEXT consent link;
        there is NEVER a service-identity fallback for per-user tools.

        FEAT-272 / TASK-1714: an optional pre-created ``task`` may be supplied
        (used by the ``returnImmediately`` path so the caller and the background
        processor share the same task object). When omitted a new task is
        created and registered.
        """
        if task is None:
            task = Task.create(context_id=message.context_id)
            task.history.append(message)
            self._tasks[task.id] = task

        try:
            # TASK-1643: extract the per-user identity (fail-closed gate seam).
            # Kept inside the try so a malformed message (e.g. non-dict metadata)
            # fails the task instead of escaping — critical for the
            # returnImmediately background path where there is no outer handler.
            user_id: Optional[str] = self._extract_identity(message)

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

        # FEAT-264: check if this tool declares a credential requirement.
        provider: Optional[str] = getattr(tool, "credential_provider", None)

        if provider and self._broker is not None:
            # FEAT-264 broker path — surface-agnostic gating.
            from parrot.auth.credentials import NeedsAuth

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

            try:
                result = await self._broker.resolve(
                    provider, channel, user_id, tool_name=tool_name
                )
            except KeyError:
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

            if isinstance(result, NeedsAuth):
                # FEAT-264 invariant: missing credential → suspend, never fallback.
                self.logger.info(
                    "A2AServer: credential missing for %s/%s; suspending", provider, user_id
                )
                await self._on_missing_credential(
                    tool_name, provider, channel, user_id, task,
                    auth_url=result.auth_url,
                )
                return True  # task is now suspended

            # ResolvedCredential — broker already wrote the audit entry.
            # Inject the secret into the per-call ContextVar so tool
            # implementations can retrieve it via current_credential()
            # (FEAT-264 / Issue 1 fix).
            from parrot.tools.abstract import _CREDENTIAL_VAR as _CRED_VAR

            self.logger.info(
                "A2AServer: credential resolved for provider=%s user=%s tool=%s",
                provider, user_id, tool_name,
            )
            _token = _CRED_VAR.set(result.secret)
            try:
                tool_result = await self._execute_tool(tool, params)
            finally:
                _CRED_VAR.reset(_token)
            task.complete(tool_result)
            return False

        else:
            # No credential gate — passthrough (no broker or tool has no provider).
            tool_result = await self._execute_tool(tool, params)
            task.complete(tool_result)
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
    # Version negotiation (A2A v1.0)
    # ─────────────────────────────────────────────────────────────

    def _get_request_version(self, request: web.Request) -> str:
        """Resolve the A2A protocol version for a request.

        Reads the ``A2A-Version`` header. ``"1.0"`` → v1.0 serialization;
        empty or ``"0.3"`` → v0.3 (per spec: "empty = 0.3"); anything else
        raises ``VersionNotSupportedError`` (-32009, HTTP 400).
        """
        version = request.headers.get("A2A-Version", "").strip()
        if not version or version.startswith("0.3"):
            return "0.3"
        if version == "1" or version.startswith("1."):
            return "1.0"
        # Plain A2A error shape (matches _a2a_http_error), consistent across the
        # REST endpoints that call this. The numeric -32009 is what clients check.
        raise web.HTTPBadRequest(
            text=json.dumps({
                "error": {
                    "code": -32009,
                    "message": f"Version not supported: {version}",
                },
            }),
            content_type="application/json",
        )

    @staticmethod
    def _content_type_for(version: str) -> str:
        """v1.0 responses use ``application/a2a+json``; v0.3 uses plain JSON."""
        return "application/a2a+json" if version != "0.3" else "application/json"

    def _versioned_response(
        self, obj: Dict[str, Any], version: str, status: int = 200
    ) -> web.Response:
        """Build a JSON response with the version-appropriate Content-Type."""
        return web.json_response(
            obj, status=status, content_type=self._content_type_for(version)
        )

    def _a2a_http_error(self, error_name: str, message: str = "") -> web.Response:
        """Build a REST error response using the A2A v1.0 error code table."""
        code, http_status = A2A_ERROR_CODES[error_name]
        return web.json_response(
            {"error": {"code": code, "message": message or error_name}},
            status=http_status,
        )

    @staticmethod
    def _jsonrpc_error(req_id: Any, code: int, message: str) -> web.Response:
        """Build a JSON-RPC 2.0 error envelope (HTTP 200 transport)."""
        return web.json_response({
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": code, "message": message},
        })

    def _spawn_background(self, coro) -> "asyncio.Task":
        """Schedule a fire-and-forget coroutine, keeping a strong reference.

        Without holding a reference the event loop may garbage-collect the task
        before it finishes (see ``asyncio.create_task`` docs).
        """
        task = asyncio.ensure_future(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    # ─────────────────────────────────────────────────────────────
    # HTTP Handlers
    # ─────────────────────────────────────────────────────────────

    async def _handle_agent_card(self, request: web.Request) -> web.Response:
        """GET /.well-known/agent-card.json (v1.0) or /.well-known/agent.json (v0.3)."""
        version = self._get_request_version(request)
        card = self.get_agent_card()
        return self._versioned_response(card.to_dict(version), version)

    async def _handle_send_message(self, request: web.Request) -> web.Response:
        """POST /a2a/message:send (v1.0) or /a2a/message/send (v0.3)."""
        version = self._get_request_version(request)
        try:
            data = await request.json()
            message = Message.from_dict(data.get("message", {}))
            config = SendMessageConfiguration.from_dict(data.get("configuration") or {})

            if config.return_immediately:
                # Create the task, store it, return SUBMITTED immediately, and
                # process it in the background on the SAME task object.
                task = Task.create(context_id=message.context_id)
                task.history.append(message)
                self._tasks[task.id] = task
                self._spawn_background(self.process_message(message, task=task))
            else:
                task = await self.process_message(message)

            result = task.to_dict(version)
            # Honour historyLength by trimming the response history (keep newest).
            if config.history_length is not None:
                n = config.history_length
                result["history"] = result["history"][-n:] if n > 0 else []

            return self._versioned_response(result, version)

        except web.HTTPException:
            raise
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
        # Negotiate the version BEFORE preparing the response: an unsupported
        # A2A-Version must return HTTP 400 (-32009), which is impossible once
        # the SSE stream headers have been flushed.
        version = self._get_request_version(request)

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
            await self._emit_message_stream(response, message, version)
        except Exception as e:
            self.logger.error("Error setting up stream: %s", e, exc_info=True)
            await self._send_sse(response, {"error": {"message": str(e)}})

        await response.write_eof()
        return response

    async def _emit_message_stream(
        self,
        response: web.StreamResponse,
        message: Message,
        version: str,
    ) -> None:
        """Run the shared SSE message-streaming loop for an already-parsed message.

        Creates the task, emits the initial ``task`` + ``working`` frames, then
        streams the agent's response as ``artifactUpdate`` frames (via
        ``ask_stream`` when available, otherwise the non-streaming fallback).
        A failure mid-stream emits a terminal ``failed`` ``statusUpdate``.

        Shared by the REST ``message/stream`` binding (``_handle_stream_message``)
        and the JSON-RPC ``SendStreamingMessage`` binding (``_rpc_stream_message``)
        so both surfaces produce byte-identical SSE frames. The caller owns the
        ``StreamResponse`` lifecycle (``prepare()`` / ``write_eof()``).

        Args:
            response: The already-prepared SSE ``StreamResponse``.
            message: The parsed inbound ``Message``.
            version: Negotiated A2A protocol version.
        """
        # Create task
        task = Task.create(context_id=message.context_id)
        task.history.append(message)
        self._tasks[task.id] = task

        # Send initial task
        await self._send_sse(response, {"task": task.to_dict(version)})

        # Send working status
        task.working(f"Processing with {self.agent.name}...")
        await self._send_sse(response, {
            "statusUpdate": {
                "taskId": task.id,
                "contextId": task.context_id,
                "status": {"state": serialize_task_state(TaskState.WORKING, version)},
                "final": False
            }
        })

        # Process with streaming
        try:
            question = message.get_text()

            # Try to use streaming method
            if hasattr(self.agent, 'ask_stream'):
                await self._stream_with_ask_stream(response, task, question, message, version)
            else:
                # Fallback to non-streaming
                await self._stream_fallback(response, task, question, message, version)

        except Exception as e:
            self.logger.error("Error in streaming: %s", e, exc_info=True)
            task.fail(str(e))
            await self._send_sse(response, {
                "statusUpdate": {
                    "taskId": task.id,
                    "contextId": task.context_id,
                    "status": {
                        "state": serialize_task_state(TaskState.FAILED, version),
                        "message": {
                            "role": serialize_role(Role.AGENT, version),
                            "parts": [{"text": str(e)}]
                        }
                    },
                    "final": True
                }
            })

    async def _stream_with_ask_stream(
        self,
        response: web.StreamResponse,
        task: Task,
        question: str,
        message: Message,
        version: str = "0.3",
    ) -> None:
        """Stream using agent's ask_stream method with light buffering."""
        kwargs = {}
        if message.context_id:
            kwargs["session_id"] = message.context_id
        # Prompt-level lever: the mode's system prompt asks the model for
        # plain text, so streamed chunks come out markdown-free.
        if self._output_mode != OutputMode.DEFAULT:
            kwargs["output_mode"] = self._output_mode

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

            # Final artifact with complete text. Streamed chunks bypass the
            # bot's post-formatter, so in TEXT mode apply the deterministic
            # markdown→plain cleanup to the final artifact here.
            full_text = "".join(collected_text)
            if self._output_mode == OutputMode.TEXT:
                full_text = markdown_to_plain(full_text)
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
                    "artifact": artifact.to_dict(version),
                    "append": False,
                    "lastChunk": True
                }
            })

            task.status = TaskStatus(state=TaskState.COMPLETED)
            await self._send_sse(response, {
                "statusUpdate": {
                    "taskId": task.id,
                    "contextId": task.context_id,
                    "status": {"state": serialize_task_state(TaskState.COMPLETED, version)},
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
        message: Message,
        version: str = "0.3",
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
                "artifact": artifact.to_dict(version),
                "lastChunk": True
            }
        })

        # Send completed
        task.status = TaskStatus(state=TaskState.COMPLETED)
        await self._send_sse(response, {
            "statusUpdate": {
                "taskId": task.id,
                "contextId": task.context_id,
                "status": {"state": serialize_task_state(TaskState.COMPLETED, version)},
                "final": True
            }
        })

    @staticmethod
    def _coerce_output_mode(value: Union[OutputMode, str, None]) -> OutputMode:
        """Coerce an ``output_mode`` config value into an :class:`OutputMode`.

        Accepts an ``OutputMode`` member, its string value (e.g. ``"text"``,
        ``"markdown"``), or ``None`` (→ ``DEFAULT``). Unknown strings log a
        warning and fall back to ``DEFAULT`` (the agent's native output).
        """
        if value is None:
            return OutputMode.DEFAULT
        if isinstance(value, OutputMode):
            return value
        try:
            return OutputMode(str(value).lower())
        except ValueError:
            logging.getLogger(__name__).warning(
                "A2AServer: unknown output_mode %r — falling back to 'default'",
                value,
            )
            return OutputMode.DEFAULT

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

        # Request the configured output mode (TEXT by default so Copilot and
        # other A2A consumers get markdown-free plain text).
        if self._output_mode != OutputMode.DEFAULT:
            kwargs["output_mode"] = self._output_mode

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
        version = self._get_request_version(request)
        task_id = request.match_info["task_id"]
        if task := self._tasks.get(task_id):
            return self._versioned_response(task.to_dict(version), version)

        return self._a2a_http_error("TaskNotFoundError", f"Task {task_id} not found")

    async def _handle_list_tasks(self, request: web.Request) -> web.Response:
        """GET /a2a/tasks"""
        version = self._get_request_version(request)
        context_id = request.query.get("contextId")
        state = request.query.get("status")
        page_size = int(request.query.get("pageSize", 50))

        tasks = list(self._tasks.values())

        if context_id:
            tasks = [t for t in tasks if t.context_id == context_id]
        if state:
            # Accept both v0.3 lowercase and v1.0 SCREAMING_SNAKE filter values.
            wanted = parse_task_state(state)
            tasks = [t for t in tasks if t.status.state == wanted]

        tasks = tasks[:page_size]

        return self._versioned_response({
            "tasks": [t.to_dict(version) for t in tasks],
            "totalSize": len(tasks),
            "pageSize": page_size,
            "nextPageToken": ""
        }, version)

    async def _handle_cancel_task(self, request: web.Request) -> web.Response:
        """POST /a2a/tasks/{task_id}:cancel (v1.0) or /a2a/tasks/{task_id}/cancel (v0.3)."""
        version = self._get_request_version(request)
        task_id = request.match_info["task_id"]
        task = self._tasks.get(task_id)

        if not task:
            return self._a2a_http_error("TaskNotFoundError")

        terminal_states = {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELED}
        if task.status.state in terminal_states:
            return self._a2a_http_error("TaskNotCancelableError")

        task.status = TaskStatus(state=TaskState.CANCELED)
        return self._versioned_response(task.to_dict(version), version)

    async def _handle_subscribe(self, request: web.Request) -> web.StreamResponse:
        """GET/POST /a2a/tasks/{task_id}:subscribe (v1.0) or .../subscribe (v0.3)."""
        version = self._get_request_version(request)
        task_id = request.match_info["task_id"]
        task = self._tasks.get(task_id)

        if not task:
            return self._a2a_http_error("TaskNotFoundError")

        response = web.StreamResponse(
            headers={"Content-Type": "text/event-stream"}
        )
        await response.prepare(request)

        # Send current state
        await self._send_sse(response, {"task": task.to_dict(version)})

        # For now, just close (in production, would subscribe to updates)
        await response.write_eof()
        return response

    # ─────────────────────────────────────────────────────────────
    # Push notification config CRUD (A2A v1.0 / TASK-1716)
    # ─────────────────────────────────────────────────────────────

    async def _handle_push_config_create(self, request: web.Request) -> web.Response:
        """POST /a2a/tasks/{task_id}/pushNotificationConfigs"""
        version = self._get_request_version(request)
        if self._push_store is None:
            return self._a2a_http_error("PushNotificationNotSupportedError")
        task_id = request.match_info["task_id"]
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response(
                {"error": {"code": "InvalidJSON", "message": "Invalid JSON body"}},
                status=400,
            )
        # Accept either the bare config or a `{pushNotificationConfig: {...}}` wrap.
        payload = body.get("pushNotificationConfig", body)
        payload.setdefault("taskId", task_id)
        try:
            config = TaskPushNotificationConfig.from_dict(payload)
            created = await self._push_store.create(config)
        except (KeyError, ValueError) as e:
            # Standard JSON-RPC "Invalid params" (-32602) — kept consistent with
            # the JSON-RPC push-create path.
            return web.json_response(
                {"error": {"code": -32602, "message": str(e)}}, status=400
            )
        return self._versioned_response(created.to_dict(version), version)

    async def _handle_push_config_get(self, request: web.Request) -> web.Response:
        """GET /a2a/tasks/{task_id}/pushNotificationConfigs/{config_id}"""
        version = self._get_request_version(request)
        if self._push_store is None:
            return self._a2a_http_error("PushNotificationNotSupportedError")
        task_id = request.match_info["task_id"]
        config_id = request.match_info["config_id"]
        config = await self._push_store.get(task_id, config_id)
        if config is None:
            return self._a2a_http_error("TaskNotFoundError")
        return self._versioned_response(config.to_dict(version), version)

    async def _handle_push_config_list(self, request: web.Request) -> web.Response:
        """GET /a2a/tasks/{task_id}/pushNotificationConfigs"""
        version = self._get_request_version(request)
        if self._push_store is None:
            return self._a2a_http_error("PushNotificationNotSupportedError")
        task_id = request.match_info["task_id"]
        configs = await self._push_store.list_for_task(task_id)
        return self._versioned_response(
            {"configs": [c.to_dict(version) for c in configs]}, version
        )

    async def _handle_push_config_delete(self, request: web.Request) -> web.Response:
        """DELETE /a2a/tasks/{task_id}/pushNotificationConfigs/{config_id}"""
        version = self._get_request_version(request)
        if self._push_store is None:
            return self._a2a_http_error("PushNotificationNotSupportedError")
        task_id = request.match_info["task_id"]
        config_id = request.match_info["config_id"]
        deleted = await self._push_store.delete(task_id, config_id)
        if not deleted:
            return self._a2a_http_error("TaskNotFoundError")
        return self._versioned_response({"deleted": True}, version)

    # ─────────────────────────────────────────────────────────────
    # JSON-RPC 2.0 binding (A2A v1.0 / TASK-1715)
    # ─────────────────────────────────────────────────────────────

    #: Method name -> handler method name. v1.0 uses PascalCase; the
    #: slash-separated names are retained as v0.3 compat aliases.
    _JSONRPC_METHODS: Dict[str, str] = {
        # v1.0 PascalCase
        "SendMessage": "_rpc_send_message",
        "GetTask": "_rpc_get_task",
        "ListTasks": "_rpc_list_tasks",
        "CancelTask": "_rpc_cancel_task",
        "SubscribeToTask": "_rpc_subscribe_task",
        "CreateTaskPushNotificationConfig": "_rpc_push_create",
        "GetTaskPushNotificationConfig": "_rpc_push_get",
        "ListTaskPushNotificationConfigs": "_rpc_push_list",
        "DeleteTaskPushNotificationConfig": "_rpc_push_delete",
        "GetExtendedAgentCard": "_rpc_get_extended_card",
        # v0.3 compat aliases
        "message/send": "_rpc_send_message",
        "tasks/get": "_rpc_get_task",
        "tasks/list": "_rpc_list_tasks",
        "tasks/cancel": "_rpc_cancel_task",
    }

    #: JSON-RPC methods that stream their result as Server-Sent Events instead
    #: of returning a single JSON-RPC envelope. ``SendStreamingMessage`` (v1.0)
    #: and its v0.3 ``message/stream`` alias reuse the same SSE frames as the
    #: REST ``message/stream`` binding. (``SubscribeToTask`` is intentionally a
    #: unary method here — it returns a task snapshot via ``_rpc_subscribe_task``.)
    _JSONRPC_STREAMING_METHODS: frozenset = frozenset(
        {"SendStreamingMessage", "message/stream"}
    )

    async def _handle_jsonrpc(self, request: web.Request) -> web.StreamResponse:
        """POST /a2a/rpc - JSON-RPC 2.0 binding (all v1.0 methods + v0.3 aliases).

        Streaming methods (``SendStreamingMessage`` / ``message/stream``) return
        an SSE ``StreamResponse``; all other methods return a unary JSON-RPC
        envelope (``web.Response``, a subclass of ``StreamResponse``).
        """
        version = self._get_request_version(request)  # may raise HTTP 400 (-32009)

        try:
            data = await request.json()
        except json.JSONDecodeError:
            return self._jsonrpc_error(None, -32700, "Parse error")

        method = data.get("method")
        params = data.get("params") or {}
        req_id = data.get("id")

        if data.get("jsonrpc") != "2.0" or not isinstance(method, str):
            return self._jsonrpc_error(req_id, -32600, "Invalid Request")

        # Streaming binding: SSE response rather than a unary JSON-RPC envelope.
        if method in self._JSONRPC_STREAMING_METHODS:
            return await self._rpc_stream_message(request, params, version)

        handler_name = self._JSONRPC_METHODS.get(method)
        if handler_name is None:
            return self._jsonrpc_error(req_id, -32601, f"Method not found: {method}")

        try:
            result = await getattr(self, handler_name)(params, version)
        except _A2ARpcError as e:
            code = e.code if e.code is not None else A2A_ERROR_CODES[e.error_name][0]
            return self._jsonrpc_error(req_id, code, e.message)
        except web.HTTPException:
            raise
        except Exception as e:
            self.logger.error("JSON-RPC error in %s: %s", method, e, exc_info=True)
            return self._jsonrpc_error(req_id, -32603, str(e))

        return web.json_response(
            {"jsonrpc": "2.0", "id": req_id, "result": result},
            content_type=self._content_type_for(version),
        )

    async def _rpc_stream_message(
        self,
        request: web.Request,
        params: Dict[str, Any],
        version: str,
    ) -> web.StreamResponse:
        """JSON-RPC ``SendStreamingMessage`` — stream the reply over SSE.

        Reuses the shared ``_emit_message_stream`` core, so the JSON-RPC
        streaming binding emits byte-identical SSE frames to the REST
        ``message/stream`` route. Frames use the A2A event-object shapes
        (``task`` / ``statusUpdate`` / ``artifactUpdate``) rather than
        re-wrapping each frame in a JSON-RPC envelope, matching the REST
        binding for cross-binding consistency.

        Args:
            request: The inbound aiohttp request (for ``prepare()``).
            params: JSON-RPC ``params`` object; ``params["message"]`` is the
                inbound message.
            version: Negotiated A2A protocol version.

        Returns:
            The completed SSE ``StreamResponse``.
        """
        response = web.StreamResponse(
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            }
        )
        await response.prepare(request)

        try:
            message = Message.from_dict(params.get("message", {}))
            await self._emit_message_stream(response, message, version)
        except Exception as e:
            self.logger.error("Error in JSON-RPC streaming: %s", e, exc_info=True)
            await self._send_sse(response, {"error": {"message": str(e)}})

        await response.write_eof()
        return response

    # --- JSON-RPC method implementations ---

    async def _rpc_send_message(self, params: Dict[str, Any], version: str) -> Dict[str, Any]:
        message = Message.from_dict(params.get("message", {}))
        config = SendMessageConfiguration.from_dict(params.get("configuration") or {})
        if config.return_immediately:
            task = Task.create(context_id=message.context_id)
            task.history.append(message)
            self._tasks[task.id] = task
            self._spawn_background(self.process_message(message, task=task))
        else:
            task = await self.process_message(message)
        result = task.to_dict(version)
        if config.history_length is not None:
            n = config.history_length
            result["history"] = result["history"][-n:] if n > 0 else []
        return result

    async def _rpc_get_task(self, params: Dict[str, Any], version: str) -> Dict[str, Any]:
        task = self._tasks.get(params.get("id"))
        if task is None:
            raise _A2ARpcError("TaskNotFoundError", f"Task {params.get('id')} not found")
        return task.to_dict(version)

    async def _rpc_list_tasks(self, params: Dict[str, Any], version: str) -> Dict[str, Any]:
        tasks = list(self._tasks.values())
        context_id = params.get("contextId")
        state = params.get("status") or params.get("state")
        if context_id:
            tasks = [t for t in tasks if t.context_id == context_id]
        if state:
            wanted = parse_task_state(state)
            tasks = [t for t in tasks if t.status.state == wanted]
        page_size = int(params.get("pageSize", 50))
        tasks = tasks[:page_size]
        return {
            "tasks": [t.to_dict(version) for t in tasks],
            "totalSize": len(tasks),
            "nextPageToken": "",
        }

    async def _rpc_cancel_task(self, params: Dict[str, Any], version: str) -> Dict[str, Any]:
        task = self._tasks.get(params.get("id"))
        if task is None:
            raise _A2ARpcError("TaskNotFoundError", f"Task {params.get('id')} not found")
        terminal = {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELED}
        if task.status.state in terminal:
            raise _A2ARpcError("TaskNotCancelableError")
        task.status = TaskStatus(state=TaskState.CANCELED)
        return task.to_dict(version)

    async def _rpc_subscribe_task(self, params: Dict[str, Any], version: str) -> Dict[str, Any]:
        task = self._tasks.get(params.get("id"))
        if task is None:
            raise _A2ARpcError("TaskNotFoundError", f"Task {params.get('id')} not found")
        return task.to_dict(version)

    def _require_push_store(self) -> "PushNotificationStore":
        if self._push_store is None:
            raise _A2ARpcError("PushNotificationNotSupportedError")
        return self._push_store

    @staticmethod
    def _push_ids(params: Dict[str, Any]) -> tuple:
        task_id = params.get("taskId") or params.get("task_id")
        config_id = (
            params.get("pushNotificationConfigId")
            or params.get("configId")
            or params.get("id")
        )
        return task_id, config_id

    async def _rpc_push_create(self, params: Dict[str, Any], version: str) -> Dict[str, Any]:
        store = self._require_push_store()
        payload = params.get("pushNotificationConfig") or params
        payload = dict(payload)
        if params.get("taskId"):
            payload.setdefault("taskId", params["taskId"])
        try:
            config = TaskPushNotificationConfig.from_dict(payload)
            created = await store.create(config)
        except (KeyError, ValueError) as e:
            raise _A2ARpcError("InvalidParams", str(e), code=-32602)
        return created.to_dict(version)

    async def _rpc_push_get(self, params: Dict[str, Any], version: str) -> Dict[str, Any]:
        store = self._require_push_store()
        task_id, config_id = self._push_ids(params)
        config = await store.get(task_id, config_id)
        if config is None:
            raise _A2ARpcError("TaskNotFoundError")
        return config.to_dict(version)

    async def _rpc_push_list(self, params: Dict[str, Any], version: str) -> Dict[str, Any]:
        store = self._require_push_store()
        task_id = params.get("taskId") or params.get("task_id")
        configs = await store.list_for_task(task_id)
        return {"configs": [c.to_dict(version) for c in configs]}

    async def _rpc_push_delete(self, params: Dict[str, Any], version: str) -> Dict[str, Any]:
        store = self._require_push_store()
        task_id, config_id = self._push_ids(params)
        deleted = await store.delete(task_id, config_id)
        if not deleted:
            raise _A2ARpcError("TaskNotFoundError")
        return {"deleted": True}

    async def _rpc_get_extended_card(self, params: Dict[str, Any], version: str) -> Dict[str, Any]:
        if not self.capabilities.extended_agent_card:
            raise _A2ARpcError("ExtendedAgentCardNotConfiguredError")
        return self.get_agent_card().to_dict(version)


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
