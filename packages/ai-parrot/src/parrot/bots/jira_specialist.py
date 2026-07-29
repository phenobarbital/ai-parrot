"""
Jira Specialist Agent with Daily Standup Workflow.

Extends JiraSpecialist with:
- Daily ticket dispatch via Telegram inline keyboards
- Callback handlers for ticket selection
- Redis-based response tracking
- Manager escalation for non-responders

Workflow:
    CRON 08:00 → dispatch_daily_tickets()
        → For each developer, fetch open tickets from Jira
        → Send interactive message with InlineKeyboard to their Telegram chat
        → Record dispatch in Redis

    USER CLICKS BUTTON → on_ticket_selected() / on_ticket_skipped()
        → Transition selected ticket to "In Progress" in Jira
        → Mark developer as responded in Redis
        → Edit original message with confirmation

    CRON 10:00 → escalate_non_responders()
        → Check Redis for who responded
        → Notify manager about non-responders
        → Optionally nudge the developer directly
"""
import asyncio
from datetime import date, datetime
from typing import Any, Dict, List, Optional
import redis.asyncio as redis
from pydantic import BaseModel, Field
from navconfig import config
from parrot.bots import Agent
from parrot.bots._types import AgentDispatcher
from parrot.integrations.telegram.callbacks import (
    telegram_callback,
    CallbackContext,
    CallbackResult,
    build_inline_keyboard,
)
from parrot.conf import JIRA_USERS
from parrot.conf import JIRA_ALLOWED_REPORTERS, JIRA_DEFAULT_REPORTER
from parrot.conf import REDIS_URL
from parrot_tools.jiratoolkit import JiraToolkit
from parrot.tools.reminder import ReminderToolkit
from parrot.models.google import GoogleModel
from parrot.integrations.telegram import TelegramHumanTool, telegram_chat_scope
from parrot.auth.credentials import OAuthCredentialResolver
from parrot.auth.context import UserContext
# FEAT-317: HookEvent/TransitionAction(Type) moved to navigator_eventbus.hooks;
# imported here via the parrot.core.hooks re-export facade.
from parrot.core.hooks import HookEvent, TransitionAction, TransitionActionType

# ──────────────────────────────────────────────────────────────
# Models
# ──────────────────────────────────────────────────────────────

class JiraTicket(BaseModel):
    """Model representing a Jira Ticket."""
    project: str = Field(..., description="The project key (e.g., NAV).")
    issue_number: str = Field(..., description="The issue key (e.g., NAV-5972).")
    title: str = Field(..., description="Summary or title of the ticket.")
    description: str = Field(..., description="Description of the ticket.")
    assignee: Optional[str] = Field(None, description="The person assigned to the ticket.")
    reporter: Optional[str] = Field(None, description="The person who reported the ticket.")
    created_at: datetime = Field(..., description="Date of creation.")
    updated_at: datetime = Field(..., description="Date of last update.")
    labels: List[str] = Field(
        default_factory=list,
        description="List of labels associated with the ticket."
    )
    components: List[str] = Field(default_factory=list, description="List of components.")


class HistoryItem(BaseModel):
    """Model representing a history item."""
    field: str
    fromString: Optional[str]
    toString: Optional[str]

class HistoryEvent(BaseModel):
    """History of Events."""
    author: Optional[str]
    created: datetime
    items: List[HistoryItem]

class JiraTicketDetail(BaseModel):
    """Detailed Jira Ticket model with history."""
    issue_number: str = Field(..., alias="key")
    title: str = Field(..., alias="summary")
    description: Optional[str]
    status: str
    assignee: Optional[str]
    reporter: Optional[str]
    labels: List[str]
    created: datetime
    updated: datetime
    history: List[HistoryEvent] = Field(default_factory=list)

class JiraTicketResponse(BaseModel):
    """Model representing a Jira Ticket Response."""
    tickets: List[JiraTicket] = Field(
        default_factory=list,
        description="List of Jira tickets found."
    )

class Developer(BaseModel):
    """A developer in the team with Jira + Telegram mappings."""
    id: str = Field(..., description="Internal developer ID")
    name: str = Field(..., description="Display name")
    username: str = Field(..., description="Internal Username")
    jira_username: str = Field(..., description="Jira account username/email")
    telegram_chat_id: int = Field(..., description="Telegram private chat ID")
    manager_chat_id: Optional[int] = Field(
        None, description="Manager's Telegram chat ID for escalation"
    )


class DailyStandupConfig(BaseModel):
    """Configuration for the daily standup workflow."""
    jira_projects: List[str] = Field(
        default=["NAV", "NVP", "NVS", "AC"],
        description="Jira projects to search for tickets"
    )
    ticket_statuses: List[str] = Field(
        default=["Open", "To Do", "Reopened", "Selected for Development"],
        description="Jira statuses to include in daily message"
    )
    in_progress_transition: str = Field(
        default="In Progress",
        description="Target Jira status when dev selects a ticket"
    )
    response_window_hours: int = Field(
        default=2,
        description="Hours to wait before escalating non-responders"
    )
    redis_ttl_seconds: int = Field(
        default=43200,  # 12 hours
        description="TTL for Redis response tracking keys"
    )
    max_tickets_shown: int = Field(
        default=8,
        description="Maximum tickets to show in the message"
    )
    # Callback prefixes (keep short for 64-byte limit)
    prefix_select: str = "tsel"
    prefix_skip: str = "tskp"


# ──────────────────────────────────────────────────────────────
# System prompt
# ──────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────
# JiraSpecialist with Daily Standup
# ──────────────────────────────────────────────────────────────

class JiraSpecialist(Agent):
    """Base class for Jira specialist agents.

    This class is **abstract by convention** — it is never instantiated or
    registered with the ``AgentRegistry`` directly. To deploy a concrete
    Jira agent, subclass it in ``agents/`` and apply the ``@register_agent``
    decorator on the subclass (e.g. ``class Jirachi(JiraSpecialist):``).

    Capabilities (all inherited by subclasses):

    - Jira ticket search, creation, and transitions (per-user OAuth2 3LO
      or service-account basic/token auth — see :meth:`post_configure`).
    - HITL flows via Telegram (:class:`TelegramHumanTool`) for approvals,
      single/multi choice, free-text and form interactions.
    - Daily standup:
        * Button-driven (Redis-tracked) flow:
          :meth:`dispatch_daily_tickets` → :meth:`escalate_non_responders`.
        * HITL flow via ``ask_human``:
          :meth:`run_morning_standup` / :meth:`run_eod_standup`.
    - Callback handlers for ticket selection.

    Prompt architecture (FEAT-138):
        Uses a composable :class:`~parrot.bots.prompts.PromptBuilder` with two
        Jira-specific layers installed via :meth:`_build_jira_prompt_builder`:

        * ``jira_workflow`` — all behavioural rules (posture, standup flow,
          cancellation, HITL rules, interaction type examples).
        * ``jira_grounding`` — anti-hallucination policy (sentinel phrases,
          no cross-ticket bleed, no apology-then-fabricate loop).

        To extend the prompt in a subclass, override
        :meth:`_build_jira_prompt_builder` or pass ``prompt_builder=`` in
        ``__init__``.
    """
    model = GoogleModel.GEMINI_3_FLASH_PREVIEW

    #: Declarative Jira credentials for subclasses. When set (non-empty
    #: dict), :meth:`_configure_jira` passes it verbatim as ``JiraToolkit``
    #: kwargs — no method override needed. ``server_url`` and
    #: ``default_project`` are filled from env when absent. Leave ``None``
    #: to use the env/OAuth auto-selection in :meth:`_configure_jira`.
    _credentials: Optional[Dict[str, Any]] = None

    @staticmethod
    def _build_jira_prompt_builder():
        """Build the default layered prompt for JiraSpecialist.

        Returns:
            PromptBuilder: A default builder with ``jira_workflow`` and
                ``jira_grounding`` layers installed.
        """
        from parrot.bots.prompts import PromptBuilder, get_domain_layer
        builder = PromptBuilder.default()
        builder.add(get_domain_layer("jira_workflow"))
        builder.add(get_domain_layer("jira_grounding"))
        return builder

    def __init__(self, **kwargs):
        # pytector (deBERTa) is trained on English and flags routine Spanish
        # imperatives ("Hazme el standup…", "Cierra NAV-6197", "Crea un ticket…")
        # as prompt injection with p > 0.98. Raise the threshold so only
        # clearly malicious prompts (p ≥ 0.995) trip the detector.
        kwargs.setdefault("injection_probability_threshold", 0.995)
        # Pop transition_actions before super() so the base class does not
        # receive an unknown keyword argument.
        _transition_actions = kwargs.pop("transition_actions", None) or []
        # Pop prompt_builder before super() so we can control precedence
        # explicitly. Builder precedence:
        #   1. an explicit caller-supplied prompt_builder=  (wins outright)
        #   2. an explicit caller-supplied prompt_preset=    (installed by
        #      AbstractBot — JiraSpecialist must not clobber it)
        #   3. JiraSpecialist's own default Jira layer stack (fallback)
        # NOTE: we cannot gate this on ``self._prompt_builder is None`` after
        # super(): Agent.__init__ (agent.py) installs a generic
        # ``PromptBuilder.agent()`` default whenever neither a builder nor a
        # preset was given, so the guard would always be False and the Jira
        # layers (jira_workflow / jira_grounding) would silently never load
        # (FEAT-268). Instead we decide here and overwrite after super().
        _caller_builder = kwargs.pop("prompt_builder", None)
        _has_preset = kwargs.get("prompt_preset") is not None
        _builder = _caller_builder or self._build_jira_prompt_builder()
        # Keep a copy of the construction kwargs so ``clone_for_user`` can
        # rebuild an identical instance without guessing at the subclass
        # signature. Copy is shallow; the values are expected to be
        # immutable or safe to share across clones (LLM presets, model
        # names, etc.).
        self._init_kwargs: Dict[str, Any] = dict(kwargs)
        super().__init__(**kwargs)
        # Install the Jira layer stack (default) or the caller's own builder,
        # overriding the generic default Agent.__init__ may have set. Only
        # step aside when the caller explicitly asked for a prompt_preset=
        # (and did not also pass an explicit prompt_builder=).
        if _caller_builder is not None or not _has_preset:
            self.prompt_builder = _builder
            # Record the effective builder so ``clone_for_user`` reproduces it
            # faithfully (a preset-only construction keeps prompt_preset in
            # _init_kwargs instead and lets super() rebuild the preset).
            self._init_kwargs["prompt_builder"] = _builder
        self._standup_config = DailyStandupConfig()
        self._redis: Optional[redis.Redis] = None
        self._developers: List[Developer] = []
        self._wrapper = None  # Set by TelegramAgentWrapper after init
        # Populated in post_configure() once self.app is attached.
        self.jira_toolkit: Optional[JiraToolkit] = None
        # Transition-to-action registry for jira.transitioned events.
        self._transition_actions: List[TransitionAction] = _transition_actions
        # Injectable async dispatcher used by the TRIGGER_AGENT transition
        # action to invoke another agent (e.g. AutonomousOrchestrator.execute_agent
        # from ai-parrot-server). Wired via set_agent_dispatcher(); without it,
        # TRIGGER_AGENT degrades to log-only.
        self._agent_dispatcher: Optional[AgentDispatcher] = None

    async def _get_redis(self) -> redis.Redis:
        """Lazy-init Redis connection."""
        if self._redis is None:
            redis_url = REDIS_URL
            if redis_url and not redis_url.startswith(("redis://", "rediss://", "unix://")):
                redis_url = f"redis://{redis_url}"
            self._redis = redis.from_url(redis_url, decode_responses=True)
        return self._redis

    def set_wrapper(self, wrapper) -> None:
        """
        Called by TelegramAgentWrapper to give the agent a reference
        to the wrapper for proactive messaging.
        """
        self._wrapper = wrapper

    def set_agent_dispatcher(self, dispatcher: AgentDispatcher) -> None:
        """Wire an async dispatcher so TRIGGER_AGENT actions can invoke
        other agents. Without this, TRIGGER_AGENT degrades to log-only.

        Typically called at application startup once both the concrete
        Jira agent and an orchestrator exist, e.g.::

            jira_agent.set_agent_dispatcher(orchestrator.execute_agent)

        Args:
            dispatcher: An async callable matching the :class:`AgentDispatcher`
                protocol shape (``agent_name``, ``task``, keyword-only
                ``user_id``/``session_id``). ``AutonomousOrchestrator.execute_agent``
                (``ai-parrot-server``) satisfies this shape.
        """
        self._agent_dispatcher = dispatcher

    async def load_developers(self) -> List[Developer]:
        """
        Load the developer list from config/database.
        Override this in a subclass or configure via external source.
        """
        # Example: load from environment or database
        # In production, this would query your HR system or a config table
        developers_config = config.getlist("STANDUP_DEVELOPERS")
        print('DEVELOPERS CONFIG', developers_config)
        print('JIRA USERS > ', JIRA_USERS)
        if not developers_config:
            developers_config = JIRA_USERS
        if isinstance(developers_config, list):
            self._developers = [Developer(**d) for d in developers_config]
        return self._developers

    def agent_tools(self):
        """Return agent-specific non-Jira tools.

        Only returns :class:`TelegramHumanTool` here. The :class:`JiraToolkit`
        is constructed later in :meth:`post_configure`, once ``self.app`` is
        attached and ``app['jira_oauth_manager']`` is reachable — this is
        what enables per-user OAuth2 3LO credentials.
        """
        return [TelegramHumanTool(source_agent=self.agent_id)]

    def _configure_jira(self) -> Optional[JiraToolkit]:
        """Build the :class:`JiraToolkit` with explicit credentials.

        Template-method hook called from :meth:`post_configure`.
        ``JiraToolkit`` performs no auth-fallback on its own, so every
        credential must be passed explicitly here. Subclasses have two
        extension points — toolkit registration, LLM sync, and the
        reminder toolkit always stay in :meth:`post_configure`:

        1. Set the :attr:`_credentials` class attribute (simple case):
           a dict of explicit ``JiraToolkit`` kwargs, used verbatim with
           ``server_url`` / ``default_project`` defaulted from env.
        2. Override this method (complex case: vault lookups, custom
           credential resolvers, per-instance auth).

        Default auth selection when :attr:`_credentials` is unset:

        * ``JIRA_AUTH_TYPE=oauth2_3lo`` (explicit) **or** ``JIRA_AUTH_TYPE``
          unset with ``app['jira_oauth_manager']`` present → per-user OAuth2
          3LO.  Every tool call resolves the caller's own tokens via
          :class:`OAuthCredentialResolver`, backed by :class:`JiraOAuthManager`.
        * ``JIRA_AUTH_TYPE=basic_auth`` / ``token_auth`` / ``oauth`` → a
          shared service-account client built from env config
          (``JIRA_INSTANCE`` + credentials).
        * Neither an OAuth manager nor an explicit ``JIRA_AUTH_TYPE`` → the
          toolkit is built unauthenticated (no silent default account); tool
          calls return an ``AuthorizationRequired`` error to the LLM.

        Returns:
            A configured :class:`JiraToolkit`, or ``None`` when credentials
            cannot be resolved (Jira tools stay unregistered).
        """
        if self._credentials:
            toolkit_kwargs = {
                "server_url": config.get("JIRA_INSTANCE"),
                "default_project": config.get("JIRA_PROJECT"),
                **self._credentials,
            }
            return JiraToolkit(**toolkit_kwargs)

        auth_type = (config.get("JIRA_AUTH_TYPE") or "").lower()
        oauth_manager = self.app.get("jira_oauth_manager") if self.app else None

        use_oauth = auth_type == "oauth2_3lo" or (
            not auth_type and oauth_manager is not None
        )

        if use_oauth:
            if oauth_manager is None:
                self.logger.warning(
                    "JiraSpecialist: JIRA_AUTH_TYPE=oauth2_3lo but "
                    "app['jira_oauth_manager'] is not set; Jira tools will "
                    "be unavailable. Check that JiraOAuthManager is wired "
                    "in app.py."
                )
                return None
            return JiraToolkit(
                auth_type="oauth2_3lo",
                credential_resolver=OAuthCredentialResolver(oauth_manager),
                default_project=config.get("JIRA_PROJECT"),
            )

        # No OAuth manager and no explicit JIRA_AUTH_TYPE → do NOT
        # fabricate a shared basic_auth service account. Pass only an
        # explicitly configured static mode; when none is set the toolkit
        # enters its unauthenticated state and surfaces a clear
        # AuthorizationRequired to the LLM on first tool use.
        toolkit_kwargs: Dict[str, Any] = {
            "server_url": config.get("JIRA_INSTANCE"),
            "default_project": config.get("JIRA_PROJECT"),
        }
        if auth_type:
            toolkit_kwargs["auth_type"] = auth_type
            if auth_type == "basic_auth":
                toolkit_kwargs["username"] = config.get("JIRA_USERNAME")
                toolkit_kwargs["password"] = config.get("JIRA_API_TOKEN")
            elif auth_type == "token_auth":
                toolkit_kwargs["token"] = (
                    config.get("JIRA_SECRET_TOKEN")
                    or config.get("JIRA_API_TOKEN")
                )
        return JiraToolkit(**toolkit_kwargs)

    async def post_configure(self) -> None:
        """Wire the :class:`JiraToolkit` using app-scoped credentials.

        Credential resolution is delegated to the :meth:`_configure_jira`
        hook (override it in subclasses to change auth). This method then
        registers the resulting tools with ``self.tool_manager``, syncs
        them back to the LLM so schemas are visible for the first user
        turn, and wires the reminder toolkit.
        """
        await super().post_configure()

        self.jira_toolkit = self._configure_jira()
        if self.jira_toolkit is None:
            return

        try:
            tools = self.tool_manager.register_toolkit(self.jira_toolkit)
        except Exception as exc:  # noqa: BLE001 - mirror Agent.__init__ tolerance
            self.logger.error(
                "Failed to register Jira tools: %s", exc, exc_info=True
            )
            return

        if not tools:
            return

        if not hasattr(self, "tools") or self.tools is None:
            self.tools = []
        self.tools.extend(tools)

        # Re-sync so the LLM client sees the newly-registered tool schemas.
        if self._llm is not None and hasattr(self._llm, "tool_manager"):
            try:
                self.sync_tools(self._llm)
            except Exception as exc:  # noqa: BLE001
                self.logger.error(
                    "Failed to sync Jira tools to LLM: %s", exc,
                    exc_info=True,
                )

        self.logger.info(
            "JiraSpecialist: registered %d Jira tools (auth_type=%s).",
            len(tools),
            self.jira_toolkit.auth_type,
        )

        # --- Reminder toolkit (FEAT-115) ---------------------------------
        scheduler_manager = self.app.get("scheduler_manager") if self.app else None
        if scheduler_manager is None:
            self.logger.warning(
                "JiraSpecialist: app['scheduler_manager'] is not set; "
                "the reminder toolkit will NOT be registered. Set up "
                "AgentSchedulerManager in app.py to enable reminders."
            )
            return

        reminder_toolkit = ReminderToolkit(scheduler_manager=scheduler_manager)
        try:
            reminder_tools = self.tool_manager.register_toolkit(reminder_toolkit)
        except Exception as exc:  # noqa: BLE001 - mirror JiraToolkit tolerance
            self.logger.error(
                "Failed to register Reminder tools: %s", exc, exc_info=True
            )
            return

        if reminder_tools:
            self.tools.extend(reminder_tools)

    async def clone_for_user(self, user_context: UserContext) -> "JiraSpecialist":
        """Return a fully isolated per-user clone of this agent.

        Called by :class:`TelegramAgentWrapper` when the YAML sets
        ``singleton_agent: false``. Giving every user their own agent
        removes the ``self._agent_lock`` serialization inside
        ``_invoke_agent`` — one user's hung tool call can no longer
        freeze the rest of the chat.

        The clone:

        * is built from the same ``__init__`` kwargs as the original
          (captured in :attr:`_init_kwargs`), so LLM config, model,
          system prompt, and injection threshold are preserved;
        * runs the full :meth:`configure` → :meth:`post_configure`
          pipeline so it gets its own LLM client, ``ToolManager``,
          conversation memory, :class:`JiraToolkit` and
          :class:`ReminderToolkit`;
        * inherits the read-only references the parent relies on at
          runtime (``self.app``, ``self._wrapper``, the developer roster,
          and :attr:`_standup_config`) without mutating the parent's
          state.

        Per-user authentication still flows through
        :class:`OAuthCredentialResolver` inside ``JiraToolkit._pre_execute``,
        so each clone's Jira calls use the caller's own OAuth2 3LO tokens.

        Args:
            user_context: Channel-agnostic identity snapshot provided by
                the integration wrapper. Not consumed directly here —
                per-user credential scoping is handled downstream by the
                OAuth resolver — but accepted to match the
                :class:`AbstractBot` contract.

        Returns:
            A fully configured :class:`JiraSpecialist` (or concrete
            subclass) instance that can service a single user without
            sharing mutable state with the original.
        """
        clone = self.__class__(**self._init_kwargs)

        # Carry over references the agent relies on but does not own.
        # These are process-scoped (app + wrapper) or effectively static
        # config (developer roster, standup config) — safe to share.
        clone._wrapper = self._wrapper
        clone._developers = list(self._developers)
        clone._standup_config = self._standup_config

        # Run the full configuration pipeline so the clone gets its own
        # LLM client, ToolManager, conversation memory, JiraToolkit and
        # ReminderToolkit. ``configure`` itself invokes ``post_configure``
        # internally, so this single call wires up everything.
        await clone.configure(self.app)

        self.logger.info(
            "JiraSpecialist: cloned for user %s (tool_count=%d)",
            getattr(user_context, "user_id", "unknown"),
            clone.tool_manager.tool_count() if clone.tool_manager else 0,
        )
        return clone

    # ──────────────────────────────────────────────────────────
    # HITL Daily Standup (ask_human-driven)
    # ──────────────────────────────────────────────────────────

    def _load_developers_sync(
        self, developer_id: Optional[str] = None
    ) -> List[Developer]:
        """Load the developer roster synchronously from config.

        Mirrors :meth:`load_developers` but (a) does not require async, and
        (b) accepts an optional ``developer_id`` filter so the HITL standup
        flows can target a single developer.
        """
        raw = config.getlist("STANDUP_DEVELOPERS") or JIRA_USERS or []
        developers = [
            Developer(**d) for d in raw if isinstance(d, dict) and d.get('is_developer') is True
        ]
        if developer_id:
            developers = [d for d in developers if d.id == developer_id]
        return developers

    async def _run_standup_for_dev(
        self,
        developer: Developer,
        instruction: str,
        *,
        session_prefix: str,
    ) -> Dict[str, Any]:
        """Invoke the agent for a single developer inside their Telegram scope.

        Uses :func:`telegram_chat_scope` so ``ask_human`` auto-targets the
        developer's chat. Returns a small dict summarizing the outcome so
        the scheduler can log per-developer results.
        """
        today = date.today().isoformat()
        session_id = f"{session_prefix}-{developer.id}-{today}"
        try:
            with telegram_chat_scope(developer.telegram_chat_id):
                message = await self.ask(
                    question=instruction,
                    user_id=developer.id,
                    session_id=session_id,
                )
            return {
                "developer_id": developer.id,
                "status": "ok",
                "output": getattr(message, "output", None),
            }
        except Exception as exc:
            self.logger.error(
                "Standup run failed for developer %s: %s",
                developer.id,
                exc,
                exc_info=True,
            )
            return {
                "developer_id": developer.id,
                "status": "error",
                "error": str(exc),
            }

    async def run_morning_standup(
        self,
        developer: Optional[dict] = None,
        developer_id: Optional[str] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """Run the morning standup for one or all configured developers.

        For each developer, the agent is asked to follow the "Morning
        check-in" section of its system prompt: fetch open tickets,
        present a shortlist via ``ask_human`` (inline buttons on Telegram),
        transition the picked ticket to ``In Progress``, post the standup
        comment, and collect a one-line plan.

        Args:
            developer_id: Run for a single developer if provided; otherwise
                fan out to every developer in parallel.

        Returns:
            List of per-developer result dicts.
        """
        if developer is not None:
            developers = [Developer(**developer)]
        else:
            developers = self._load_developers_sync(developer_id=developer_id)
            if not developers:
                self.logger.warning("run_morning_standup: no developers configured")
                return []

        today = date.today().isoformat()

        async def _one(dev: Developer) -> Dict[str, Any]:
            instruction = (
                f"Run the morning standup for {dev.name} "
                f"(jira_username={dev.jira_username}, date={today}).\n"
                f"Follow the 'Morning check-in' section of your system prompt. "
                f"Build the JQL using assignee = \"{dev.jira_account_id}\" "
                f"instead of currentUser(). "
                f"If blockers escalate to a manager, use "
                f"target_humans=[\"{dev.manager_chat_id or dev.telegram_chat_id}\"]. "
                f"End by posting a short confirmation message to the developer "
                f"summarizing what you did (ticket picked, plan captured, "
                f"or that they skipped)."
            )
            return await self._run_standup_for_dev(
                dev, instruction, session_prefix="standup-morning"
            )

        results = await asyncio.gather(
            *(_one(d) for d in developers),
            return_exceptions=False,
        )
        self.logger.info(
            "Morning standup completed for %d developer(s)", len(results)
        )
        return list(results)

    async def run_eod_standup(
        self,
        developer_id: Optional[str] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """Run the end-of-day standup wrap for one or all developers.

        For each developer, the agent collects a three-field status
        (``done_today`` / ``plan_tomorrow`` / ``blockers``) via the
        ``ask_human`` form interaction, posts it as a Jira comment on
        the primary ticket worked today, and flags blockers.

        Args:
            developer_id: Run for a single developer if provided; otherwise
                fan out to every developer in parallel.

        Returns:
            List of per-developer result dicts.
        """
        developers = self._load_developers_sync(developer_id=developer_id)
        if not developers:
            self.logger.warning("run_eod_standup: no developers configured")
            return []

        today = date.today().isoformat()

        async def _one(dev: Developer) -> Dict[str, Any]:
            instruction = (
                f"Run the end-of-day standup wrap for {dev.name} "
                f"(jira_username={dev.jira_username}, date={today}).\n"
                f"Follow the 'End-of-day wrap' section of your system prompt. "
                f"Use assignee = \"{dev.jira_username}\" in the JQL. "
                f"Collect the status via ask_human with interaction_type=\"form\" "
                f"and form_schema properties 'done_today', 'plan_tomorrow', "
                f"'blockers' (required: done_today, plan_tomorrow). "
                f"Post the answers as a single comment on the primary ticket "
                f"worked today under header "
                f"'**Daily Standup {today}**'. "
                f"If blockers are non-empty, transition the ticket to "
                f"'Blocked' when that status exists and notify the manager "
                f"with target_humans=[\"{dev.manager_chat_id or dev.telegram_chat_id}\"]."
            )
            return await self._run_standup_for_dev(
                dev, instruction, session_prefix="standup-eod"
            )

        results = await asyncio.gather(
            *(_one(d) for d in developers),
            return_exceptions=False,
        )
        self.logger.info(
            "EOD standup completed for %d developer(s)", len(results)
        )
        return list(results)

    # ──────────────────────────────────────────────────────────
    # CRON Job: Daily Ticket Dispatch
    # ──────────────────────────────────────────────────────────

    async def dispatch_daily_tickets(self) -> Dict[str, Any]:
        """
        CRON entry point: Send daily ticket messages to all developers.

        Scheduled to run at 08:00 AM.

        Returns:
            Summary dict with dispatch results.
        """
        if not self._wrapper:
            self.logger.error(
                "Cannot dispatch tickets: no TelegramWrapper attached. "
                "Call set_wrapper() first."
            )
            return {"error": "No wrapper attached"}

        if not self._developers:
            await self.load_developers()

        if not self._developers:
            self.logger.warning("No developers configured for daily standup.")
            return {"error": "No developers configured"}

        results = {
            "date": date.today().isoformat(),
            "dispatched": 0,
            "skipped": 0,
            "errors": 0,
            "details": [],
        }

        r = await self._get_redis()
        today = date.today().isoformat()

        for dev in self._developers:
            try:
                # Fetch open tickets for this developer
                tickets = await self._fetch_developer_tickets(dev)

                if not tickets:
                    self.logger.info(f"No open tickets for {dev.name}, skipping.")
                    results["skipped"] += 1
                    results["details"].append({
                        "developer": dev.name,
                        "status": "skipped",
                        "reason": "no open tickets",
                    })
                    continue

                # Build the interactive message
                text, keyboard = self._build_ticket_message(dev, tickets)

                # Send via wrapper
                message_id = await self._wrapper.send_interactive_message(
                    chat_id=dev.telegram_chat_id,
                    text=text,
                    keyboard=keyboard,
                )

                if message_id:
                    # Track that we dispatched to this dev (for escalation check)
                    dispatch_key = f"standup:dispatched:{today}:{dev.id}"
                    await r.set(
                        dispatch_key,
                        str(message_id),
                        ex=self._standup_config.redis_ttl_seconds,
                    )
                    results["dispatched"] += 1
                    results["details"].append({
                        "developer": dev.name,
                        "status": "sent",
                        "ticket_count": len(tickets),
                    })
                else:
                    results["errors"] += 1
                    results["details"].append({
                        "developer": dev.name,
                        "status": "error",
                        "reason": "send failed",
                    })

            except Exception as e:
                self.logger.error(
                    f"Error dispatching tickets to {dev.name}: {e}",
                    exc_info=True,
                )
                results["errors"] += 1
                results["details"].append({
                    "developer": dev.name,
                    "status": "error",
                    "reason": str(e)[:100],
                })

        self.logger.info(
            f"Daily standup dispatched: {results['dispatched']} sent, "
            f"{results['skipped']} skipped, {results['errors']} errors."
        )
        return results

    async def _fetch_developer_tickets(
        self, dev: Developer
    ) -> List[Dict[str, Any]]:
        """
        Fetch open tickets assigned to a developer via JQL.

        Returns a list of dicts with 'key', 'summary', 'status' fields.
        """
        projects = ", ".join(self._standup_config.jira_projects)
        statuses = '", "'.join(self._standup_config.ticket_statuses)
        jql = (
            f'project IN ({projects}) '
            f'AND assignee = "{dev.jira_username}" '
            f'AND status IN ("{statuses}") '
            f'ORDER BY priority DESC, updated DESC'
        )

        question = f"""
        Use the tool `jira_search_issues` with:
        - jql: '{jql}'
        - fields: 'key,summary,status,priority'
        - max_results: {self._standup_config.max_tickets_shown}
        - store_as_dataframe: True
        - dataframe_name: 'dev_tickets_{dev.id}'

        Execute the search and confirm when done.
        """
        await self.ask(question=question)

        try:
            df = self.tool_manager.get_shared_dataframe(f'dev_tickets_{dev.id}')
            if df is None or df.empty:
                return []
            return df.to_dict('records')
        except (KeyError, AttributeError):
            return []

    def _build_ticket_message(
        self,
        dev: Developer,
        tickets: List[Dict[str, Any]],
    ) -> tuple[str, Dict[str, Any]]:
        """
        Build the interactive Telegram message with inline keyboard.

        Returns:
            Tuple of (message_text, inline_keyboard_dict)
        """
        cfg = self._standup_config

        # Message text
        text = (
            f"☀️ Buenos días, *{dev.name}*!\n\n"
            f"Tienes *{len(tickets)}* tickets asignados. "
            f"¿Cuál trabajarás hoy?\n"
        )

        # Build buttons — one per ticket
        buttons = []
        for ticket in tickets[:cfg.max_tickets_shown]:
            key = ticket.get("key", "???")
            summary = ticket.get("summary", "No summary")
            status = ticket.get("status", "")
            priority = ticket.get("priority", "")

            # Status emoji
            status_emoji = {
                "Open": "🔵",
                "To Do": "📋",
                "Reopened": "🔄",
                "Selected for Development": "🎯",
            }.get(status, "⚪")

            # Truncate summary for button text
            label = f"{status_emoji} {key}: {summary[:35]} : {priority}"
            if len(summary) > 35:
                label += "…"

            buttons.append([{
                "text": label,
                "prefix": cfg.prefix_select,
                "payload": {
                    "t": key,
                    "d": dev.id,
                },
            }])

        # Skip button
        buttons.append([{
            "text": "⏭️ Ya tengo plan para hoy",
            "prefix": cfg.prefix_skip,
            "payload": {"d": dev.id},
        }])

        keyboard = build_inline_keyboard(buttons)
        return text, keyboard

    # ──────────────────────────────────────────────────────────
    # Callback Handlers (registered via @telegram_callback)
    # ──────────────────────────────────────────────────────────

    @telegram_callback(
        prefix="tsel",
        description="Developer selects a ticket to work on today",
    )
    async def on_ticket_selected(
        self, callback: CallbackContext
    ) -> CallbackResult:
        """
        Handle ticket selection.

        Payload keys:
            t: ticket key (e.g. "NAV-5972")
            d: developer ID
        """
        ticket_key = callback.payload.get("t", "???")
        developer_id = callback.payload.get("d", "")

        self.logger.info(
            f"Ticket selected: {ticket_key} by developer {developer_id} "
            f"(telegram user {callback.user_id})"
        )

        # 1. Transition ticket to In Progress via Jira
        try:
            transition_target = self._standup_config.in_progress_transition
            question = (
                f'Use the tool `jira_transition_issue` to transition '
                f'issue "{ticket_key}" to status "{transition_target}".'
            )
            await self.ask(question=question)
        except Exception as e:
            self.logger.error(
                f"Failed to transition {ticket_key}: {e}", exc_info=True
            )
            return CallbackResult(
                answer_text=f"⚠️ Error transicionando {ticket_key}",
                show_alert=True,
            )

        # 2. Mark as responded in Redis
        await self._mark_responded(developer_id, callback.user_id, ticket_key)

        # 3. Return result — edits original message + shows toast
        return CallbackResult(
            answer_text=f"✅ {ticket_key} → In Progress",
            edit_message=(
                f"✅ *{callback.display_name}*, tu ticket "
                f"*{ticket_key}* ha sido marcado como *In Progress*.\n\n"
                f"¡A trabajar! 💪"
            ),
            edit_parse_mode="Markdown",
            remove_keyboard=True,
        )

    @telegram_callback(
        prefix="tskp",
        description="Developer skips ticket selection (already has a plan)",
    )
    async def on_ticket_skipped(
        self, callback: CallbackContext
    ) -> CallbackResult:
        """Handle skip — developer already has a plan for today."""
        developer_id = callback.payload.get("d", "")

        # Mark as responded (skip counts as a response)
        await self._mark_responded(developer_id, callback.user_id, "skipped")

        return CallbackResult(
            answer_text="👍 Entendido",
            edit_message=(
                f"👍 *{callback.display_name}*, entendido. "
                f"Ya tienes tu plan para hoy."
            ),
            edit_parse_mode="Markdown",
            remove_keyboard=True,
        )

    async def _mark_responded(
        self,
        developer_id: str,
        telegram_user_id: int,
        ticket_key: str,
    ) -> None:
        """
        Record that a developer responded to the daily standup.

        Redis key: standup:responded:{today}:{developer_id}
        Value: JSON with timestamp, user ID, and selected ticket
        TTL: Configured in standup_config (default 12h)
        """
        r = await self._get_redis()
        today = date.today().isoformat()
        key = f"standup:responded:{today}:{developer_id}"

        import json
        value = json.dumps({
            "telegram_user_id": telegram_user_id,
            "ticket_key": ticket_key,
            "responded_at": datetime.now().isoformat(),
        })

        await r.set(key, value, ex=self._standup_config.redis_ttl_seconds)
        self.logger.info(
            f"Marked developer {developer_id} as responded "
            f"(ticket: {ticket_key})"
        )

    # ──────────────────────────────────────────────────────────
    # CRON Job: Escalation Check
    # ──────────────────────────────────────────────────────────

    async def escalate_non_responders(
        self,
        manager_chat_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        CRON entry point: Check for non-responders and escalate.

        Scheduled to run at 10:00 AM (2h after dispatch).

        Args:
            manager_chat_id: Override manager chat ID. If None, uses
            each developer's configured manager_chat_id.

        Returns:
            Summary of escalation results.
        """
        if not self._wrapper:
            return {"error": "No wrapper attached"}

        if not self._developers:
            await self.load_developers()

        r = await self._get_redis()
        today = date.today().isoformat()

        non_responders = []
        responders = []

        for dev in self._developers:
            # Check if we dispatched to this dev today
            dispatch_key = f"standup:dispatched:{today}:{dev.id}"
            was_dispatched = await r.exists(dispatch_key)

            if not was_dispatched:
                continue  # Wasn't sent a message today (no tickets, etc.)

            # Check if they responded
            response_key = f"standup:responded:{today}:{dev.id}"
            responded = await r.exists(response_key)

            if responded:
                responders.append(dev)
            else:
                non_responders.append(dev)

        result = {
            "date": today,
            "total_dispatched": len(responders) + len(non_responders),
            "responded": len(responders),
            "non_responders": [],
            "escalated_to": [],
        }

        if not non_responders:
            self.logger.info("All developers responded. No escalation needed.")
            return result

        # Group non-responders by manager
        by_manager: Dict[int, List[Developer]] = {}
        for dev in non_responders:
            mgr_chat = manager_chat_id or dev.manager_chat_id
            if mgr_chat:
                by_manager.setdefault(mgr_chat, []).append(dev)

            result["non_responders"].append(dev.name)

            # Nudge the developer
            try:
                await self._wrapper.send_interactive_message(
                    chat_id=dev.telegram_chat_id,
                    text=(
                        f"👋 *{dev.name}*, aún no has seleccionado tu ticket "
                        f"para hoy.\n\n"
                        f"¿Necesitas ayuda con la priorización?"
                    ),
                    keyboard={"inline_keyboard": []},  # No buttons for nudge
                    parse_mode="Markdown",
                )
            except Exception as e:
                self.logger.warning(f"Failed to nudge {dev.name}: {e}")

        # Notify each manager
        hours = self._standup_config.response_window_hours
        for mgr_chat_id, devs in by_manager.items():
            names = "\n".join(f"• {d.name}" for d in devs)
            try:
                await self._wrapper.bot.send_message(
                    chat_id=mgr_chat_id,
                    text=(
                        f"⚠️ *Escalación Daily Standup*\n\n"
                        f"Los siguientes devs no han seleccionado "
                        f"ticket tras {hours}h:\n\n"
                        f"{names}\n\n"
                        f"Puede que necesiten ayuda con priorización."
                    ),
                    parse_mode="Markdown",
                )
                result["escalated_to"].append(mgr_chat_id)
            except Exception as e:
                self.logger.error(
                    f"Failed to notify manager {mgr_chat_id}: {e}"
                )

        self.logger.info(
            f"Escalation complete: {len(non_responders)} non-responders, "
            f"notified {len(by_manager)} managers."
        )
        return result

    # ──────────────────────────────────────────────────────────
    # Utility: Get today's standup status
    # ──────────────────────────────────────────────────────────

    async def get_standup_status(self) -> Dict[str, Any]:
        """
        Get current daily standup status.

        Useful for debugging or a /standup_status command.
        """
        if not self._developers:
            await self.load_developers()

        r = await self._get_redis()
        today = date.today().isoformat()

        import json as _json
        status = {
            "date": today,
            "developers": [],
        }

        for dev in self._developers:
            dispatch_key = f"standup:dispatched:{today}:{dev.id}"
            response_key = f"standup:responded:{today}:{dev.id}"

            dispatched = await r.exists(dispatch_key)
            response_raw = await r.get(response_key)

            dev_status = {
                "name": dev.name,
                "dispatched": bool(dispatched),
                "responded": bool(response_raw),
            }

            if response_raw:
                try:
                    response_data = _json.loads(response_raw)
                    dev_status["ticket"] = response_data.get("ticket_key")
                    dev_status["responded_at"] = response_data.get("responded_at")
                except (ValueError, TypeError):
                    pass

            status["developers"].append(dev_status)

        return status

    # ──────────────────────────────────────────────────────────
    # Jira Webhook: Assignment Handler
    # ──────────────────────────────────────────────────────────

    async def handle_hook_event(self, event: HookEvent) -> Optional[Dict[str, Any]]:
        """Route :class:`HookEvent` instances emitted by ``JiraWebhookHook``.

        Dispatches each known event type to its dedicated handler:

        * ``jira.created`` → :meth:`handle_jira_ticket_created`
        * ``jira.assigned`` → :meth:`handle_jira_assignment`
        * ``jira.ready_for_test`` → :meth:`handle_ready_for_test`
        * ``jira.transitioned`` → :meth:`_dispatch_transition`
        * All others → logged at ``INFO`` level, returns ``None``.

        Args:
            event: The hook event forwarded by ``HookManager``.

        Returns:
            The result dict returned by the matched handler, or ``None`` when
            the event type is not recognised.
        """
        if event.event_type == "jira.created":
            return await self.handle_jira_ticket_created(event.payload)
        if event.event_type == "jira.assigned":
            return await self.handle_jira_assignment(event.payload)
        if event.event_type == "jira.ready_for_test":
            return await self.handle_ready_for_test(event.payload)
        if event.event_type == "jira.transitioned":
            return await self._dispatch_transition(event.payload)
        self.logger.info(
            "JiraSpecialist: ignoring hook event %s (hook_id=%s)",
            event.event_type,
            event.hook_id,
        )
        return None

    # ──────────────────────────────────────────────────────────
    # Jira Webhook: Transition Dispatch & Built-in Action Handlers
    # ──────────────────────────────────────────────────────────

    async def _dispatch_transition(
        self,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Match a transition event against the action registry and execute matches.

        Always calls :meth:`_action_log_transition` first to ensure every
        transition is observable, regardless of whether any registry actions
        fire.  Then iterates :attr:`_transition_actions`, skipping disabled
        entries and entries restricted to a different project, and dispatches
        to the appropriate built-in handler.

        Args:
            payload: The ``HookEvent.payload`` dict produced by
                :class:`~parrot.core.hooks.jira_webhook.JiraWebhookHook`.
                Must include ``from_status``, ``to_status``, and
                ``project_key``.

        Returns:
            A dict with ``status``, ``issue_key``, ``from_status``,
            ``to_status``, ``actions_matched``, and ``results`` keys.
        """
        from_status = (payload.get("from_status") or "").strip().lower()
        to_status = (payload.get("to_status") or "").strip().lower()
        project_key = (payload.get("project_key") or "").strip().upper()
        issue_key = payload.get("issue_key", "?")

        # Always log the transition for observability.
        self._action_log_transition(payload, {})

        results: List[Dict[str, Any]] = []
        for action in self._transition_actions:
            if not action.enabled:
                continue
            if action.project_key and action.project_key.upper() != project_key:
                continue
            from_match = (
                action.from_status == "*"
                or action.from_status.lower() == from_status
            )
            to_match = (
                action.to_status == "*"
                or action.to_status.lower() == to_status
            )
            if from_match and to_match:
                result = await self._invoke_transition_action(
                    action, payload
                )
                results.append(result)

        return {
            "status": "ok",
            "issue_key": issue_key,
            "from_status": payload.get("from_status"),
            "to_status": payload.get("to_status"),
            "actions_matched": len(results),
            "results": results,
        }

    async def _invoke_transition_action(
        self,
        action: TransitionAction,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Dispatch a single :class:`TransitionAction` to the correct handler.

        Args:
            action: The matched :class:`TransitionAction` entry.
            payload: The event payload forwarded to the handler.

        Returns:
            The result dict returned by the handler.
        """
        if action.action_type == TransitionActionType.NOTIFY_CHANNEL:
            return await self._action_notify_channel(payload, action.action_config)
        if action.action_type == TransitionActionType.TRIGGER_AGENT:
            return await self._action_trigger_agent(payload, action.action_config)
        if action.action_type == TransitionActionType.LOG:
            return self._action_log_transition(payload, action.action_config)
        if action.action_type == TransitionActionType.CALL_HANDLER:
            return await self._action_call_handler(payload, action.action_config)
        self.logger.warning(
            "Unknown transition action type: %s", action.action_type
        )
        return {"status": "skipped", "reason": f"unknown action_type={action.action_type}"}

    async def _action_notify_channel(
        self,
        payload: Dict[str, Any],
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Send a formatted Telegram notification about a status transition.

        Follows the same pattern as :meth:`handle_ready_for_test`: reads
        issue fields from *payload*, formats a Telegram message, and sends
        it via ``self._wrapper.bot.send_message``.

        Args:
            payload: Transition event payload with ``issue_key``, ``summary``,
                ``from_status``, ``to_status``, and ``assignee``.
            config: Action config dict; expected keys: ``channel_id`` (str),
                ``template`` (optional str with ``{issue_key}``,
                ``{summary}``, ``{from_status}``, ``{to_status}``,
                ``{assignee}`` placeholders).

        Returns:
            A dict with ``status`` (``"ok"`` / ``"skipped"``), ``channel_id``.
        """
        channel_id = config.get("channel_id")
        if not channel_id:
            return {"status": "skipped", "reason": "no channel_id in action_config"}
        if not self._wrapper or not getattr(self._wrapper, "bot", None):
            return {"status": "skipped", "reason": "no Telegram wrapper attached"}

        template = config.get("template") or (
            "\U0001f504 *{issue_key}* transitioned: {from_status} → {to_status}\n"
            "*{summary}*\nAssigned to: {assignee}"
        )
        assignee_name = (payload.get("assignee") or {}).get("display_name", "—")
        text = template.format(
            issue_key=payload.get("issue_key", "?"),
            summary=payload.get("summary", ""),
            from_status=payload.get("from_status", "?"),
            to_status=payload.get("to_status", "?"),
            assignee=assignee_name,
        )
        try:
            await self._wrapper.bot.send_message(
                chat_id=channel_id,
                text=text,
                parse_mode="Markdown",
            )
            return {"status": "ok", "channel_id": channel_id}
        except Exception as exc:
            self.logger.error(
                "Failed to notify channel %s for transition %s: %s",
                channel_id,
                payload.get("issue_key"),
                exc,
                exc_info=True,
            )
            return {
                "status": "error",
                "channel_id": channel_id,
                "error": str(exc),
            }

    async def _action_trigger_agent(
        self,
        payload: Dict[str, Any],
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Dispatch another agent for a transition event via the injected
        :attr:`_agent_dispatcher`.

        When a dispatcher has been wired (see :meth:`set_agent_dispatcher`),
        the resolved ``agent_id`` and rendered ``task`` are forwarded to it
        and awaited. Without a dispatcher, this degrades to a log-only
        no-op (backward compatible — does not raise).

        Args:
            payload: Transition event payload.
            config: Action config dict; expected keys: ``agent_id`` (str),
                ``task_template`` (optional str with the same placeholders
                as :meth:`_action_notify_channel`).

        Returns:
            A dict with ``status`` of ``"dispatched"``, ``"skipped"``, or
            ``"error"``, plus ``agent_id`` and (when applicable) ``task``,
            ``result``, or ``error``.
        """
        agent_id = config.get("agent_id")
        if not agent_id:
            return {"status": "skipped", "reason": "no agent_id in action_config"}
        task_template = config.get("task_template", "")
        assignee_name = (payload.get("assignee") or {}).get("display_name", "—")
        if task_template:
            try:
                task = task_template.format(
                    issue_key=payload.get("issue_key", "?"),
                    summary=payload.get("summary", ""),
                    from_status=payload.get("from_status", "?"),
                    to_status=payload.get("to_status", "?"),
                    assignee=assignee_name,
                )
            except KeyError:
                task = task_template
        else:
            task = (
                f"Transition: {payload.get('issue_key', '?')} "
                f"{payload.get('from_status', '?')} → {payload.get('to_status', '?')}"
            )
        if self._agent_dispatcher is None:
            self.logger.warning(
                "Transition trigger_agent: agent_id=%s task=%s "
                "(no dispatcher wired — degrading to log-only)",
                agent_id,
                task,
            )
            return {
                "status": "skipped",
                "reason": "no dispatcher wired",
                "agent_id": agent_id,
                "task": task,
            }
        try:
            self.logger.info(
                "Transition trigger_agent: dispatching agent_id=%s task=%s",
                agent_id,
                task,
            )
            # NOTE: Jira webhook payloads do not currently carry `user_id`/
            # `session_id` keys, so these will normally resolve to `None`.
            # They are forwarded here so a future actor-mapping feature can
            # populate them without changing this call site.
            result = await self._agent_dispatcher(
                agent_id,
                task,
                user_id=payload.get("user_id"),
                session_id=payload.get("session_id"),
            )
            return {
                "status": "dispatched",
                "agent_id": agent_id,
                "task": task,
                "result": str(result)[:500],
            }
        except Exception as exc:  # noqa: BLE001 — must not break the transition loop
            self.logger.error(
                "trigger_agent dispatch failed for %s: %s",
                agent_id,
                exc,
                exc_info=True,
            )
            return {"status": "error", "agent_id": agent_id, "error": str(exc)}

    def _action_log_transition(
        self,
        payload: Dict[str, Any],
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Emit a structured log entry for a Jira status transition.

        Args:
            payload: Transition event payload with ``issue_key``,
                ``from_status``, ``to_status``, and ``summary``.
            config: Action config dict; optional key: ``level`` (str,
                default ``"info"``). Any standard Python logging level
                name is accepted (``debug``, ``info``, ``warning``,
                ``error``, ``critical``).

        Returns:
            A dict with ``status="logged"`` and the effective ``level``.
        """
        level = config.get("level", "info")
        log_fn = getattr(self.logger, level, self.logger.info)
        log_fn(
            "Jira transition: %s %s → %s (%s)",
            payload.get("issue_key"),
            payload.get("from_status"),
            payload.get("to_status"),
            payload.get("summary", ""),
        )
        return {"status": "logged", "level": level}

    async def _action_call_handler(
        self,
        payload: Dict[str, Any],
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Invoke a named method on this instance for a transition event.

        The method is resolved via ``getattr(self, method_name)`` and called
        with ``(payload, config)``. This allows advanced deployments to wire
        custom handlers without subclassing.

        Args:
            payload: Transition event payload.
            config: Action config dict; required key: ``method_name`` (str).

        Returns:
            The result of the named method, or a ``status="skipped"`` dict
            if the method does not exist.
        """
        method_name = config.get("method_name")
        if not method_name:
            return {"status": "skipped", "reason": "no method_name in action_config"}
        handler = getattr(self, method_name, None)
        if handler is None:
            self.logger.warning(
                "Transition call_handler: method '%s' not found on JiraSpecialist",
                method_name,
            )
            return {
                "status": "skipped",
                "reason": f"method '{method_name}' not found",
            }
        result = handler(payload, config)
        if asyncio.iscoroutine(result):
            result = await result
        return result

    def _resolve_developer_from_assignee(
        self,
        assignee: Optional[Dict[str, Any]],
    ) -> Optional[Developer]:
        """Match an assignee dict against the configured developer roster.

        Tries, in order, ``email`` / ``name`` / ``display_name`` against the
        developer's ``jira_username`` / ``username`` / ``name`` (case-insensitive).

        Args:
            assignee: Dict with the Jira assignee fields (``email``,
                ``display_name``, ``name``, ``account_id``).

        Returns:
            The matching :class:`Developer` or ``None`` if no match.
        """
        if not assignee:
            return None
        if not self._developers:
            self._developers = self._load_developers_sync()
        if not self._developers:
            return None

        candidates = [
            (assignee.get("email") or "").lower(),
            (assignee.get("name") or "").lower(),
            (assignee.get("display_name") or "").lower(),
        ]
        candidates = [c for c in candidates if c]

        for dev in self._developers:
            fields = [
                (dev.jira_username or "").lower(),
                (dev.username or "").lower(),
                (dev.name or "").lower(),
            ]
            if any(c and c in fields for c in candidates):
                return dev
        return None

    async def handle_jira_assignment(
        self,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Kick off the assignment conversation with the developer on Telegram.

        Invoked by the :class:`JiraWebhookHook` when a ticket is assigned
        (either on creation with a non-null assignee or via an ``assignee``
        change in the changelog).

        The developer receives a prompt on Telegram asking them to provide:

        * a **due date** (ISO ``YYYY-MM-DD``),
        * an **original estimate** (``1d``, ``4h``, ``30m``…),
        * and to **accept** or **reject** the assignment.

        On accept, the agent posts the estimate as ``timetracking.originalEstimate``,
        writes the due date, and transitions the issue to ``In Progress``.
        On reject, the agent posts a Jira comment with the reason and leaves
        the ticket untouched so a manager can reassign.

        Args:
            payload: The ``HookEvent.payload`` emitted by
                :class:`JiraWebhookHook`. Must contain ``issue_key`` and
                either ``new_assignee`` or ``assignee`` dicts.

        Returns:
            Result dict with ``status`` (``ok``/``skipped``/``error``),
            ``issue_key``, and — on skip/error — ``reason``.
        """
        issue_key = payload.get("issue_key")
        if not issue_key:
            return {"status": "skipped", "reason": "missing issue_key"}

        assignee = payload.get("new_assignee") or payload.get("assignee")
        developer = self._resolve_developer_from_assignee(assignee)
        if developer is None:
            self.logger.info(
                "handle_jira_assignment: no developer mapping for %s on %s",
                (assignee or {}).get("display_name"),
                issue_key,
            )
            return {
                "status": "skipped",
                "issue_key": issue_key,
                "reason": "assignee is not a configured developer",
            }

        summary = payload.get("summary") or ""
        priority = payload.get("priority") or "—"
        _reporter_raw = payload.get("reporter")
        if isinstance(_reporter_raw, dict):
            reporter_display = _reporter_raw.get("display_name") or "—"
        else:
            reporter_display = _reporter_raw or "—"
        status = payload.get("status") or "—"

        instruction = (
            f"A Jira ticket has just been assigned to {developer.name} "
            f"(jira_username={developer.jira_username}).\n\n"
            f"Ticket: {issue_key}\n"
            f"Summary: {summary}\n"
            f"Priority: {priority}\n"
            f"Status: {status}\n"
            f"Reporter: {reporter_display}\n\n"
            "Run the assignment intake flow in Spanish:\n"
            "1. Greet the developer and show the ticket above.\n"
            "2. Call `ask_human` with interaction_type=\"form\" and "
            "form_schema properties `due_date` (string, ISO YYYY-MM-DD), "
            "`estimate` (string, e.g. '1d', '4h', '30m'), and `decision` "
            "(string enum: 'accept' or 'reject'). All three are required. "
            "The `question` field should clearly state that we need a due "
            f"date, a time estimate, and whether they accept {issue_key}.\n"
            "3. If `decision == 'accept'`:\n"
            "   - Call `jira_update_issue` to set `duedate` to the provided "
            "date and `timetracking.originalEstimate` to the provided "
            "estimate.\n"
            "   - Call `jira_add_comment` posting: 'Task accepted. Due: "
            "<date>. Estimate: <estimate>.'\n"
            "   - Call `jira_transition_issue` to move the ticket to "
            f"'{self._standup_config.in_progress_transition}'.\n"
            "   - Reply to the developer confirming the due date, estimate, "
            "and the new status.\n"
            "4. If `decision == 'reject'`:\n"
            "   - Call `ask_human` with interaction_type=\"free_text\" "
            "asking for the rejection reason (one sentence is enough).\n"
            "   - Call `jira_add_comment` posting: 'Task rejected by "
            "<developer>. Reason: <reason>.' Do NOT transition or reassign "
            "the ticket; leave it for a manager to reassign.\n"
            "   - Reply to the developer acknowledging the rejection.\n"
            "5. If `ask_human` returns a cancellation or timeout, follow "
            "the cancellation rule and stop immediately."
        )

        today = date.today().isoformat()
        session_id = f"assignment-{developer.id}-{issue_key}-{today}"

        try:
            with telegram_chat_scope(developer.telegram_chat_id):
                message = await self.ask(
                    question=instruction,
                    user_id=developer.id,
                    session_id=session_id,
                )
            self.logger.info(
                "Assignment intake completed for %s on %s",
                developer.name,
                issue_key,
            )
            return {
                "status": "ok",
                "issue_key": issue_key,
                "developer_id": developer.id,
                "output": getattr(message, "output", None),
            }
        except Exception as exc:
            self.logger.error(
                "Assignment intake failed for %s on %s: %s",
                developer.name,
                issue_key,
                exc,
                exc_info=True,
            )
            return {
                "status": "error",
                "issue_key": issue_key,
                "developer_id": developer.id,
                "error": str(exc),
            }

    async def handle_jira_ticket_created(
        self,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Auto-repoint the reporter of a freshly-created Jira ticket when
        the original reporter is not in ``JIRA_ALLOWED_REPORTERS``.

        Emits a Jira comment documenting the change and returns a result
        dict compatible with the other handle_* webhook methods.

        Args:
            payload: The hook event payload containing ``issue_key`` and a
                ``reporter`` dict with ``email``, ``display_name``,
                ``account_id``, and ``name`` keys (as enriched by TASK-808).

        Returns:
            A dict with ``status`` ∈ {``"ok"``, ``"skipped"``, ``"error"``}
            and optional fields ``issue_key``, ``original_reporter``,
            ``new_reporter``, ``reason``, and ``error``. Never raises.
        """
        issue_key = payload.get("issue_key")
        if not issue_key:
            return {"status": "skipped", "reason": "missing issue_key"}

        if self.jira_toolkit is None:
            self.logger.error(
                "handle_jira_ticket_created: jira_toolkit not attached; "
                "skipping %s.",
                issue_key,
            )
            return {
                "status": "error",
                "issue_key": issue_key,
                "reason": "jira_toolkit not attached",
            }

        allow_list = [e.lower() for e in (JIRA_ALLOWED_REPORTERS or []) if e]
        if not allow_list:
            return {
                "status": "skipped",
                "issue_key": issue_key,
                "reason": "JIRA_ALLOWED_REPORTERS is not configured",
            }

        reporter_obj = payload.get("reporter") or {}
        original_email = (reporter_obj.get("email") or "").strip().lower()
        original_display = reporter_obj.get("display_name") or "—"

        if not original_email:
            return {
                "status": "skipped",
                "issue_key": issue_key,
                "reason": "reporter email not available",
            }

        if original_email in allow_list:
            self.logger.info(
                "jira_ticket_created: reporter %s already in allow-list for %s; skipping.",
                original_email,
                issue_key,
            )
            return {
                "status": "skipped",
                "issue_key": issue_key,
                "reason": "reporter already allowed",
                "original_reporter": original_email,
            }

        # Pick replacement. JIRA_DEFAULT_REPORTER takes precedence iff itself on the list.
        default = (JIRA_DEFAULT_REPORTER or "").strip()
        if default and default.lower() in allow_list:
            replacement = default
        else:
            replacement = JIRA_ALLOWED_REPORTERS[0]

        try:
            await self.jira_toolkit.jira_set_reporter(
                issue=issue_key, email=replacement,
            )
            comment_body = (
                f"Reporter automatically updated from "
                f"{original_display} ({original_email}) to {replacement} "
                f"because the original reporter is not in the authorized list."
            )
            await self.jira_toolkit.jira_add_comment(
                issue=issue_key, body=comment_body,
            )
            self.logger.info(
                "jira_ticket_created: reassigned reporter on %s from %s to %s",
                issue_key,
                original_email,
                replacement,
            )
            return {
                "status": "ok",
                "issue_key": issue_key,
                "original_reporter": original_email,
                "new_reporter": replacement,
            }
        except Exception as exc:
            self.logger.error(
                "handle_jira_ticket_created failed for %s: %s",
                issue_key,
                exc,
                exc_info=True,
            )
            return {
                "status": "error",
                "issue_key": issue_key,
                "error": str(exc),
            }

    async def handle_ready_for_test(
        self,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Notify the QA channel when a ticket transitions to "Ready For Test".

        The destination channel id is read from ``navconfig.config`` key
        ``JIRA_TEST_WEBHOOK_CHANNEL``. The message announces that the
        developer has finished the development phase and the ticket is
        entering the testing phase.

        Args:
            payload: The ``HookEvent.payload`` emitted by
                :class:`JiraWebhookHook`. Expected to contain
                ``issue_key``, ``summary``, ``priority``, ``assignee`` and
                (optionally) ``user`` (the actor who moved the ticket).

        Returns:
            Result dict with ``status`` (``ok``/``skipped``/``error``),
            ``issue_key`` and, on skip/error, ``reason``.
        """
        issue_key = payload.get("issue_key")
        if not issue_key:
            return {"status": "skipped", "reason": "missing issue_key"}

        channel_id = config.get("JIRA_TEST_WEBHOOK_CHANNEL")
        if not channel_id:
            self.logger.warning(
                "handle_ready_for_test: JIRA_TEST_WEBHOOK_CHANNEL is not "
                "configured; skipping notification for %s.",
                issue_key,
            )
            return {
                "status": "skipped",
                "issue_key": issue_key,
                "reason": "JIRA_TEST_WEBHOOK_CHANNEL is not configured",
            }

        if not self._wrapper or not getattr(self._wrapper, "bot", None):
            self.logger.error(
                "handle_ready_for_test: no Telegram wrapper attached; "
                "cannot notify channel for %s.",
                issue_key,
            )
            return {
                "status": "error",
                "issue_key": issue_key,
                "reason": "no Telegram wrapper attached",
            }

        summary = payload.get("summary") or ""
        priority = payload.get("priority") or "—"
        assignee = payload.get("assignee") or {}
        actor = payload.get("user") or {}

        developer_name = (
            assignee.get("display_name")
            or assignee.get("name")
            or actor.get("displayName")
            or actor.get("name")
            or "El desarrollador"
        )

        text = (
            f"🧪 *Ready For Test*: `{issue_key}`\n\n"
            f"*{summary}*\n"
            f"Prioridad: {priority}\n"
            f"Asignado a: {developer_name}\n\n"
            f"✅ *{developer_name}* ha terminado la fase de desarrollo.\n"
            f"🚦 El ticket entra en la fase de *testing*."
        )

        try:
            await self._wrapper.bot.send_message(
                chat_id=channel_id,
                text=text,
                parse_mode="Markdown",
            )
            self.logger.info(
                "Ready-for-test notification sent for %s to channel %s",
                issue_key,
                channel_id,
            )
            return {
                "status": "ok",
                "issue_key": issue_key,
                "channel_id": channel_id,
            }
        except Exception as exc:
            self.logger.error(
                "Failed to notify ready-for-test for %s: %s",
                issue_key,
                exc,
                exc_info=True,
            )
            return {
                "status": "error",
                "issue_key": issue_key,
                "error": str(exc),
            }

    @telegram_callback(
        prefix="create_ticket",
        description="Simple callback to create a Jira ticket",
    )
    async def create_ticket(self, summary: str, description: str, **kwargs) -> str:
        """Create a Jira ticket using the JiraToolkit."""
        question = f"""
        Create a Jira ticket for project NAV type bug with summary:
        *{summary}*
        Description:
        *{description}*"
        """
        return await self.ask(
            question=question,
        )

    async def search_all_tickets(self, start_date: str = "2025-01-01", end_date: str = "2026-02-28", max_tickets: Optional[int] = None, **kwargs) -> List[JiraTicket]:
        """
        Search for due Jira tickets using the JiraToolkit and return structured output.
        Uses dataframe storage optimization to avoid token limits.
        """
        question = f"""
        Use the tool `jira_search_issues` to search for tickets with the following parameters:
        - jql: 'project IN (NAV, NVP, NVS, AC) AND created >= "{start_date}" AND created <= "{end_date}"'
        - fields: 'project,key,status,title,assignee,reporter,created,updated,labels,components'
        - max_results:  {max_tickets or 'None'}
        - store_as_dataframe: True
        - dataframe_name: 'all_jira_tickets'

        Just execute the search and confirm when done.
        Do not attempt to list the tickets.
        Avoid adding any additional text or comments to the response.
        """

        # Execute the tool call
        await self.ask(question=question)

        # Retrieve the stored DataFrame directly from the ToolManager
        try:
            df = self.tool_manager.get_shared_dataframe('all_jira_tickets')
        except (KeyError, AttributeError):
            # Fallback if dataframe wasn't stored or found
            return []

        return [] if df.empty else df

    async def weekly_ticket_count_report(self) -> Dict[str, Any]:
        """Month-to-date ticket count by Assignee grouped by Component.

        Decorated with :func:`schedule_weekly_report` so the scheduler runs
        it weekly (defaults to ``MON 09:00`` UTC; override via the
        ``{AGENT_ID}_WEEKLY_REPORT`` env var, format ``DDD HH:MM``).

        Pulls every ticket from the configured Jira projects created since
        the first day of the current month, groups the rows by
        ``component × assignee``, and emails a plain-text summary to
        ``jlara@trocglobal.com``.

        Returns:
            Dict with ``period``, ``total_tickets``, ``by_component``
            (nested ``{component: {assignee: count}}``) and a flat
            ``rows`` list — useful for tests and downstream consumers.
        """
        today = date.today()
        start_of_month = today.replace(day=1)
        start_str = start_of_month.isoformat()
        end_str = today.isoformat()

        projects = ", ".join(self._standup_config.jira_projects)
        df_name = f"jira_mtd_count_{end_str}"
        jql = (
            f'project IN ({projects}) '
            f'AND created >= "{start_str}" '
            f'AND created <= "{end_str}" '
            f'ORDER BY assignee ASC'
        )

        question = f"""
        Use the tool `jira_search_issues` with:
        - jql: '{jql}'
        - fields: 'key,assignee,components'
        - max_results: None
        - store_as_dataframe: True
        - dataframe_name: '{df_name}'

        Execute the search and confirm when done.
        Do not list the tickets or add commentary.
        """
        await self.ask(question=question)

        try:
            df = self.tool_manager.get_shared_dataframe(df_name)
        except (KeyError, AttributeError):
            df = None

        empty = df is None or (hasattr(df, "empty") and df.empty)

        period = {"start": start_str, "end": end_str}

        if empty:
            result: Dict[str, Any] = {
                "period": period,
                "total_tickets": 0,
                "by_component": {},
                "rows": [],
            }
            body = (
                f"Jira Weekly Ticket Report — Month-to-Date "
                f"({start_str} to {end_str})\n\n"
                f"No tickets found in projects: {projects}.\n"
            )
        else:
            exploded = df.copy()
            exploded["components"] = exploded["components"].apply(
                lambda c: c if isinstance(c, list) and c else ["(no component)"]
            )
            exploded["assignee"] = (
                exploded["assignee"].astype(object).where(exploded["assignee"].notna(), "(unassigned)")
            )
            exploded = exploded.explode("components").rename(
                columns={"components": "component"}
            )
            exploded["component"] = exploded["component"].apply(
                lambda c: c.get("name") if isinstance(c, dict) else (c or "(no component)")
            )

            grouped = (
                exploded.groupby(["component", "assignee"]).size().reset_index(name="count")
            )

            by_component: Dict[str, Dict[str, int]] = {}
            rows: List[Dict[str, Any]] = []
            for _, r in grouped.iterrows():
                component = str(r["component"])
                assignee = str(r["assignee"])
                count = int(r["count"])
                by_component.setdefault(component, {})[assignee] = count
                rows.append(
                    {"component": component, "assignee": assignee, "count": count}
                )

            result = {
                "period": period,
                "total_tickets": int(len(df)),
                "by_component": by_component,
                "rows": rows,
            }

            lines = [
                "Jira Weekly Ticket Report — Month-to-Date",
                f"Period: {start_str} to {end_str}",
                f"Projects: {projects}",
                f"Total tickets: {result['total_tickets']}",
                "",
            ]
            for component in sorted(by_component):
                lines.append(f"[{component}]")
                for assignee, count in sorted(
                    by_component[component].items(), key=lambda kv: (-kv[1], kv[0])
                ):
                    lines.append(f"  {assignee}: {count}")
                lines.append("")
            body = "\n".join(lines)

        subject = f"Jira Weekly Ticket Report — MTD {start_str} → {end_str}"

        self.logger.info(
            "Weekly MTD report generated: %d tickets across %d component(s).",
            result["total_tickets"],
            len(result["by_component"]),
        )
        return body, subject

    async def get_ticket(self, issue_number: str) -> JiraTicketDetail:
        """Get detailed information for a specific Jira ticket, including history."""
        question = f"""
        Use the tool `jira_get_issue` to retrieve details for issue {issue_number}.
        Parameters:
        - issue: "{issue_number}"
        - fields: "key,summary,description"
        - expand: "changelog"
        - include_history: True

        The tool will return the issue details including a 'history' list.
        """

        # We ask the LLM to call the tool and return the result formatted as JiraTicketDetail
        return await self.ask(
            question=question,
            structured_output=JiraTicketDetail
        )

    async def get_in_progress_by_assignee(
        self,
        projects: Optional[List[str]] = None,
        max_per_assignee: int = 3,
        statuses: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Return all "In Progress" Jira tickets grouped by assignee.

        Queries Jira directly via :attr:`jira_toolkit` for issues currently
        in the target status (default ``"In Progress"``), then groups them
        by assignee. For each assignee, returns up to ``max_per_assignee``
        tickets (default 3) with the ticket key, summary, creation time,
        due date, and — when available from the issue changelog — the
        most recent transition timestamp into the target status.

        Args:
            projects: Jira project keys to search. Defaults to
                :attr:`DailyStandupConfig.jira_projects`.
            max_per_assignee: Maximum number of tickets to include per
                assignee in the bullet list. Defaults to ``3``.
            statuses: Status names to filter on. Defaults to
                ``["In Progress"]``. The first entry is also the status
                whose transition timestamp is extracted from the
                changelog.

        Returns:
            A dict with two keys:

            * ``markdown``: A Markdown-formatted bullet list (one bullet
              per assignee, with up to ``max_per_assignee`` nested
              ticket bullets).
            * ``by_assignee``: Ordered mapping ``assignee -> list[ticket]``
              where each ticket dict contains ``key``, ``summary``,
              ``created``, ``due_date`` and ``in_progress_at``.

        Raises:
            RuntimeError: If :attr:`jira_toolkit` is not configured yet
                or the underlying Jira search returns an error envelope.
        """
        if self.jira_toolkit is None:
            raise RuntimeError(
                "JiraSpecialist.get_in_progress_by_assignee: jira_toolkit "
                "is not configured. Call post_configure() first."
            )

        project_list = projects or self._standup_config.jira_projects
        status_list = statuses or ["In Progress"]

        projects_clause = ", ".join(project_list)
        statuses_clause = '", "'.join(status_list)
        jql = (
            f'project IN ({projects_clause}) '
            f'AND status IN ("{statuses_clause}") '
            f'ORDER BY assignee ASC, updated DESC'
        )

        envelope = await self.jira_toolkit.jira_search_issues(
            jql=jql,
            fields="key,summary,assignee,status,created,duedate",
            expand="changelog",
            max_results=None,
            store_as_dataframe=False,
            json_result=True,
        )

        env_status = envelope.get("status")
        if env_status not in ("ok", "empty"):
            message = envelope.get("message") or "unknown error"
            raise RuntimeError(
                f"jira_search_issues failed for in-progress query: {message}"
            )

        issues: List[Dict[str, Any]] = (
            (envelope.get("data") or {}).get("issues") or []
        )
        target_status = (status_list[0] if status_list else "In Progress").lower()

        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for issue in issues:
            fields = issue.get("fields") or {}
            assignee_obj = fields.get("assignee") or {}
            assignee_name = (
                assignee_obj.get("displayName")
                or assignee_obj.get("name")
                or "Unassigned"
            )

            in_progress_at: Optional[str] = None
            changelog = issue.get("changelog") or {}
            for entry in changelog.get("histories") or []:
                for item in entry.get("items") or []:
                    if item.get("field") != "status":
                        continue
                    to_string = (item.get("toString") or "").lower()
                    if to_string != target_status:
                        continue
                    created = entry.get("created")
                    if created and (
                        in_progress_at is None or created > in_progress_at
                    ):
                        in_progress_at = created

            grouped.setdefault(assignee_name, []).append({
                "key": issue.get("key"),
                "summary": fields.get("summary"),
                "created": fields.get("created"),
                "due_date": fields.get("duedate"),
                "in_progress_at": in_progress_at,
            })

        def _sort_key(t: Dict[str, Any]) -> str:
            return t.get("in_progress_at") or t.get("created") or ""

        by_assignee: Dict[str, List[Dict[str, Any]]] = {}
        for assignee in sorted(grouped.keys(), key=lambda n: n.lower()):
            sorted_tickets = sorted(grouped[assignee], key=_sort_key, reverse=True)
            by_assignee[assignee] = sorted_tickets[:max_per_assignee]

        lines: List[str] = []
        for assignee, tickets in by_assignee.items():
            lines.append(f"- **{assignee}**")
            if not tickets:
                lines.append("  - _No in-progress tickets_")
                continue
            for t in tickets:
                key = t["key"] or "—"
                summary = t["summary"] or "(no summary)"
                created = t["created"] or "—"
                due = t["due_date"] or "—"
                ip_at = t["in_progress_at"] or "—"
                lines.append(
                    f"  - `{key}` — {summary} "
                    f"(created: {created}, due: {due}, "
                    f"in-progress since: {ip_at})"
                )

        return {
            "markdown": "\n".join(lines),
            "by_assignee": by_assignee,
        }
