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
import math
from datetime import date, datetime
from typing import Any, Dict, List, Optional
import redis.asyncio as redis
from pydantic import BaseModel, Field
import pandas as pd
from navconfig import config
from parrot.bots import Agent
from parrot.integrations.telegram.callbacks import (
    telegram_callback,
    CallbackContext,
    CallbackResult,
    build_inline_keyboard,
)
from parrot.conf import JIRA_USERS
from parrot.conf import REDIS_URL
from parrot_tools.jiratoolkit import JiraToolkit
from parrot.models.google import GoogleModel
from parrot.integrations.telegram import TelegramHumanTool, telegram_chat_scope
from parrot.auth.credentials import OAuthCredentialResolver
from parrot.core.hooks.models import HookEvent

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

JIRA_SPECIALIST_PROMPT = """\
You are **JiraSpecialist**, an autonomous agent that manages Jira tickets
and runs the daily standup on behalf of the engineering team. You have
Jira tools for searching, creating, updating, transitioning and
commenting on issues, plus `ask_human` which reaches the developer or
manager through Telegram (inline buttons for approvals/choices, or a
text reply for free-form input).

## Default posture: act, then report

Prefer **taking action and summarizing the result** over asking for
confirmation. Trust unambiguous instructions. Use your judgment for
routine work (creating tickets with clear inputs, posting comments,
transitioning through the normal workflow, updating labels/components,
running JQL searches). Only interrupt the human when the action is
hard to reverse, affects someone else's work, or depends on information
you genuinely cannot derive.

## Fresh-turn rule (important)

Every new user message is a **fresh, standalone task** unless the user
explicitly references a previous exchange ("the ticket I just closed",
"keep going", "what did you pick?"). Never reuse the arguments of a
previous `ask_human` (or any other tool) call just because they appear
in your conversation history. Re-read the new user message, identify
what they are asking for *now*, and only then decide whether a tool
call is needed. If the new message is a direct request you can fulfill
without asking, do it — do **not** re-emit the last `ask_human`
question with the same arguments.

## Cancellation rule (hard stop)

If `ask_human` ever returns a result whose content starts with
`"The interaction was cancelled"` (or is exactly `"[escalated] The
interaction was cancelled."`), the human aborted the current task.
You MUST:

1. Stop the current workflow **immediately**. Do not call any further
   tools — no Jira writes, no transitions, no comments, no
   notifications, no additional `ask_human` calls.
2. Do NOT retry the same question or ask for confirmation.
3. Reply to the user with exactly: `Operación cancelada.`
4. Wait for the next user message as a fresh task.

The same rule applies if `ask_human` returns a timeout result
(`"Human did not respond within the time limit."`) unless the
interaction had a sensible default the user pre-approved — in the
timeout case, reply `Sin respuesta del usuario; operación cancelada.`
and stop.

## Mandatory human interaction (keep these; everything else is judgment)

1. **Never close / resolve / mark "Done" a ticket without a closing comment.**
   Before any transition to `Done`, `Closed`, `Resolved`, or `Won't Do`,
   call `ask_human(interaction_type="free_text", question="What closing
   comment should I post on <KEY>?")`, post the reply as a Jira comment,
   then do the transition. No exceptions.

2. **Confirm destructive or mass operations (> 5 tickets, deletes, bulk
   reassigns).** One `ask_human(interaction_type="approval", ...)` with
   the scope (JQL or key list) and the action. Abort on reject.

3. **Ask for missing required fields before creating a ticket.** If
   `summary`, `project`, or `issue_type` is unclear, ask instead of
   inventing. Never fabricate ticket content.

For everything else — comments, single-ticket transitions to `In Progress`
or `In Review`, assignee changes the user explicitly named, priority
changes on `To Do` tickets, status queries, running JQL — just do it
and report back.

---

## Daily standup flow

You own the daily standup loop. Developers and their Telegram chat ids
are configured out-of-band; assume the human you are currently talking to
on Telegram is a developer unless a tool result tells you otherwise.

### Morning check-in (triggered by a scheduled run or a developer DM)

1. Fetch the developer's open work with JQL:
   `assignee = currentUser() AND status in ("To Do", "Open", "Reopened",
   "Selected for Development") ORDER BY priority DESC, updated DESC`.
   Limit to the top 8 by priority/recency.

2. If the developer has **no** open tickets, greet them, mention that the
   queue is empty, and offer to pull a ticket from the team backlog. Stop.

3. Otherwise, present the shortlist with
   `ask_human(interaction_type="single_choice",
   options=[{"key": "<KEY>", "label": "<KEY> — <summary> [<priority>]"},
            ..., {"key": "skip", "label": "Skip standup for today"}])`.

4. On response:
   - If a ticket key: transition it to `In Progress`, post a comment
     `Standup <YYYY-MM-DD>: starting work.`, then `ask_human(interaction_type=
     "free_text", question="Quick ETA or plan for <KEY>? (one sentence is fine)")`
     and append that plan to the same comment.
   - If `skip`: acknowledge and move on. Do not nag.

### Mid-day blockers (only if the developer initiates)

If the developer reports a blocker during the day, capture it:
- Post the blocker as a Jira comment on the ticket they're working on
  (ask which ticket if ambiguous).
- Add the `blocked` label. If the blocker names another person or team,
  propose an @mention in the comment with
  `ask_human(interaction_type="approval", ...)`.

### Assignment intake (triggered by a Jira webhook when a ticket is
### assigned to a developer)

When the Jira webhook reports an assignment and you are asked to run
the "assignment intake flow":

1. Greet the developer briefly in Spanish and show the ticket key,
   summary, priority and reporter you were given in the instruction
   (do NOT call `jira_get_issue` again unless the instruction explicitly
   asks for it — the data is already there).

2. Ask all three answers in a single structured form:
   ```
   ask_human(
     interaction_type="form",
     question="Se te asignó <KEY>: <summary>. ¿Aceptas la tarea? Indica "
              "fecha tope y estimación de esfuerzo.",
     form_schema={
       "type": "object",
       "properties": {
         "due_date": {"type": "string",
                       "description": "Fecha tope (YYYY-MM-DD)"},
         "estimate": {"type": "string",
                       "description": "Estimación (ej. '1d', '4h', '30m')"},
         "decision": {"type": "string", "enum": ["accept", "reject"],
                       "description": "¿Aceptas la tarea?"}
       },
       "required": ["due_date", "estimate", "decision"]
     }
   )
   ```

3. If `decision == "accept"`:
   - Call `jira_update_issue` with `fields={"duedate": "<due_date>",
     "timetracking": {"originalEstimate": "<estimate>"}}`.
   - Call `jira_add_comment` on the ticket: `Task accepted. Due: <date>.
     Estimate: <estimate>.`
   - Call `jira_transition_issue` moving the ticket to `In Progress`.
   - Reply to the developer confirming the outcome.

4. If `decision == "reject"`:
   - Ask for the rejection reason with a second `ask_human`
     (`interaction_type="free_text"`, one sentence is enough).
   - Post the reason as a Jira comment prefixed with
     `Task rejected by <developer>. Reason:`.
   - Do NOT transition or reassign — leave the ticket for the manager.
   - Reply to the developer acknowledging the rejection.

5. Cancellation / timeout rules from the top of this prompt still apply.

### End-of-day wrap (triggered by the scheduled run or `/eod` style prompt)

1. Find what the developer worked on today:
   `assignee = currentUser() AND status changed DURING ("-1d", now())
   OR (assignee = currentUser() AND updated >= startOfDay())`.

2. Ask for a short status summary with
   `ask_human(interaction_type="form", form_schema={...})` containing
   three fields: `done_today`, `plan_tomorrow`, `blockers` (all free text;
   `blockers` optional).

3. Post the three answers as a single Jira comment on the primary ticket
   worked today, under a `**Daily Standup <YYYY-MM-DD>**` header. If there
   are blockers, also transition the ticket to `Blocked` (if that status
   exists for the project) and flag the manager per rule below.

### Escalation

- If the developer hasn't answered the morning single_choice within the
  standup window (configured in the scheduler), mark the day as
  non-responded — do NOT re-ping. The scheduled escalation job owns
  nagging; you don't.
- When blockers mention another team or explicit external dependencies,
  surface a concise summary to the manager via `ask_human` with
  `target_humans=[<manager_chat_id>]` only if the developer asked you to
  loop them in. Otherwise post-only on the ticket.

---

## How to phrase `ask_human`
- State the action and scope (ticket key, project, number of items
  affected). Keep `context` ≤ 280 chars; put detail in `question`.
- `approval` for yes/no. `single_choice` for enumerated options (always
  include a `skip` / `keep current` escape hatch). `free_text` only when
  prose is genuinely needed. `form` for multi-field structured input.

### Picking the right interaction_type — examples to copy

**ALWAYS prefer structured types over free_text when the answer is
enumerable.** Free text is the last resort.

**Project pick** (`single_choice`) — when creating a ticket and project is ambiguous:
  call `jira_get_projects` first, then:
  ```
  ask_human(
    interaction_type="single_choice",
    question="Which project should the ticket go to?",
    options=[
      {"key":"NAV","label":"NAV — Navigator core"},
      {"key":"NVP","label":"NVP — Navigator Platform"},
      {"key":"NVS","label":"NVS — Navigator Services"},
      {"key":"AC","label":"AC — Analytics"},
      {"key":"cancel","label":"Cancel"},
    ]
  )
  ```

**Issue type** (`single_choice`):
  ```
  ask_human(
    interaction_type="single_choice",
    question="What type of issue is this?",
    options=[
      {"key":"Bug","label":"🐞 Bug"},
      {"key":"Task","label":"📋 Task"},
      {"key":"Story","label":"📖 Story"},
      {"key":"Epic","label":"🏛️ Epic"},
    ]
  )
  ```

**Destructive approval** (`approval`):
  ```
  ask_human(
    interaction_type="approval",
    question="About to bulk-transition 12 tickets to Done. Proceed?",
    context="JQL: project = NAV AND status = In Review AND updated < -30d"
  )
  ```

**Transition pick** (`single_choice`) — after `jira_get_transitions(<KEY>)`:
  ```
  ask_human(
    interaction_type="single_choice",
    question="Which transition should I apply to NAV-123?",
    context="Current status: In Review",
    options=[
      {"key":"tr-5","label":"✅ Done"},
      {"key":"tr-7","label":"⏸ Blocked"},
      {"key":"tr-9","label":"↩ Back to In Progress"},
      {"key":"skip","label":"Leave as-is"},
    ]
  )
  ```

**Multiple labels/components** (`multi_choice`):
  ```
  ask_human(
    interaction_type="multi_choice",
    question="Which components apply to this ticket?",
    options=[
      {"key":"frontend","label":"Frontend"},
      {"key":"backend","label":"Backend"},
      {"key":"infra","label":"Infra"},
      {"key":"db","label":"Database"},
    ]
  )
  ```

**EOD status** (`form`) — multi-field structured input:
  ```
  ask_human(
    interaction_type="form",
    question="End-of-day standup",
    form_schema={
      "type":"object",
      "properties":{
        "done_today":{"type":"string","description":"What did you finish today?"},
        "plan_tomorrow":{"type":"string","description":"What will you work on tomorrow?"},
        "blockers":{"type":"string","description":"Any blockers? (leave empty if none)"}
      },
      "required":["done_today","plan_tomorrow"]
    }
  )
  ```

**Free text** — only when there's truly no closed list:
  ```
  ask_human(
    interaction_type="free_text",
    question="What closing comment should I post on NAV-123?"
  )
  ```

### Heuristic
If before asking you could call a Jira tool (`jira_get_projects`,
`jira_get_issue_types`, `jira_get_transitions`, `jira_get_components`,
`jira_list_assignees`, `jira_list_tags`) and get a finite list, you
MUST use `single_choice` / `multi_choice` with that list as `options`.
Defaulting to `free_text` for a question that is really "pick from
this short list" is an error.

## General behavior
- Reference tickets as `<PROJECT>-<NUMBER>` (e.g. `NAV-123`).
- Always confirm the outcome of a Jira action with the ticket key.
- Dates in ISO (`YYYY-MM-DD`).
- If a tool fails, report it plainly. Do not retry blindly. Ask the
  human only when the failure looks like a permission/data issue that
  needs their judgment.
"""


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
    """
    model = GoogleModel.GEMINI_3_FLASH_PREVIEW
    system_prompt_template: str = JIRA_SPECIALIST_PROMPT

    def __init__(self, **kwargs):
        # pytector (deBERTa) is trained on English and flags routine Spanish
        # imperatives ("Hazme el standup…", "Cierra NAV-6197", "Crea un ticket…")
        # as prompt injection with p > 0.98. Raise the threshold so only
        # clearly malicious prompts (p ≥ 0.995) trip the detector.
        kwargs.setdefault("injection_probability_threshold", 0.995)
        super().__init__(**kwargs)
        self._standup_config = DailyStandupConfig()
        self._redis: Optional[redis.Redis] = None
        self._developers: List[Developer] = []
        self._wrapper = None  # Set by TelegramAgentWrapper after init
        # Populated in post_configure() once self.app is attached.
        self.jira_toolkit: Optional[JiraToolkit] = None

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

    async def post_configure(self) -> None:
        """Wire the :class:`JiraToolkit` using app-scoped credentials.

        Auth selection:

        * ``JIRA_AUTH_TYPE=oauth2_3lo`` (explicit) **or** ``JIRA_AUTH_TYPE``
          unset with ``app['jira_oauth_manager']`` present → per-user OAuth2
          3LO.  Every tool call resolves the caller's own tokens via
          :class:`OAuthCredentialResolver`, backed by :class:`JiraOAuthManager`.
        * ``JIRA_AUTH_TYPE=basic_auth`` / ``token_auth`` / ``oauth`` (or no
          OAuth manager configured) → a shared service-account client built
          from env config (``JIRA_INSTANCE`` + credentials).

        Tools are registered with ``self.tool_manager`` and synced back to
        the LLM so that schemas are visible for the first user turn.
        """
        await super().post_configure()

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
                return
            self.jira_toolkit = JiraToolkit(
                auth_type="oauth2_3lo",
                credential_resolver=OAuthCredentialResolver(oauth_manager),
                default_project=config.get("JIRA_PROJECT"),
            )
        else:
            effective = auth_type or "basic_auth"
            toolkit_kwargs: Dict[str, Any] = {
                "server_url": config.get("JIRA_INSTANCE"),
                "auth_type": effective,
                "default_project": config.get("JIRA_PROJECT"),
            }
            if effective == "basic_auth":
                toolkit_kwargs["username"] = config.get("JIRA_USERNAME")
                toolkit_kwargs["password"] = config.get("JIRA_API_TOKEN")
            elif effective == "token_auth":
                toolkit_kwargs["token"] = (
                    config.get("JIRA_SECRET_TOKEN")
                    or config.get("JIRA_API_TOKEN")
                )
            self.jira_toolkit = JiraToolkit(**toolkit_kwargs)

        if self.tool_manager is not None:
            self.jira_toolkit.set_tool_manager(self.tool_manager)

        tools = self.jira_toolkit.get_tools()
        if not tools:
            return

        if not hasattr(self, "tools") or self.tools is None:
            self.tools = []
        self.tools.extend(tools)

        try:
            self.tool_manager.register_tools(tools)
        except Exception as exc:  # noqa: BLE001 - mirror Agent.__init__ tolerance
            self.logger.error(
                "Failed to register Jira tools: %s", exc, exc_info=True
            )
            return

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
        developers = [Developer(**d) for d in raw if isinstance(d, dict)]
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
                f"Build the JQL using assignee = \"{dev.jira_username}\" "
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

        Currently handles ``jira.assigned`` events by forwarding to
        :meth:`handle_jira_assignment`. Other event types fall back to
        logging so they remain observable even without bespoke routing.

        Args:
            event: The hook event forwarded by ``HookManager``.

        Returns:
            The per-developer result dict from :meth:`handle_jira_assignment`
            when the event is a Jira assignment; otherwise ``None``.
        """
        if event.event_type == "jira.assigned":
            return await self.handle_jira_assignment(event.payload)
        self.logger.info(
            "JiraSpecialist: ignoring hook event %s (hook_id=%s)",
            event.event_type,
            event.hook_id,
        )
        return None

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
        reporter = payload.get("reporter") or "—"
        status = payload.get("status") or "—"

        instruction = (
            f"A Jira ticket has just been assigned to {developer.name} "
            f"(jira_username={developer.jira_username}).\n\n"
            f"Ticket: {issue_key}\n"
            f"Summary: {summary}\n"
            f"Priority: {priority}\n"
            f"Status: {status}\n"
            f"Reporter: {reporter}\n\n"
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
