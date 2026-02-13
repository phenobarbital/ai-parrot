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
from parrot.tools.jiratoolkit import JiraToolkit
from parrot.integrations.telegram.callbacks import (
    telegram_callback,
    CallbackContext,
    CallbackResult,
    build_inline_keyboard,
)
from parrot.conf import JIRA_USERS

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
# JiraSpecialist with Daily Standup
# ──────────────────────────────────────────────────────────────

class JiraSpecialist(Agent):
    """
    A specialist agent for Jira integration with daily standup workflow.

    Provides:
    - Jira ticket search, creation, and transitions
    - Daily standup: sends tickets to devs via Telegram inline buttons
    - Callback handlers for ticket selection
    - Redis-based tracking and manager escalation
    """
    model = 'gemini-3-flash-preview'
    max_tokens = 16000

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._standup_config = DailyStandupConfig()
        self._redis: Optional[redis.Redis] = None
        self._developers: List[Developer] = []
        self._wrapper = None  # Set by TelegramAgentWrapper after init

    async def _get_redis(self) -> redis.Redis:
        """Lazy-init Redis connection."""
        if self._redis is None:
            redis_url = config.get("REDIS_URL", "redis://localhost:6379/0")
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
        """Return the agent-specific Jira tools."""
        jira_instance = config.get("JIRA_INSTANCE")
        jira_api_token = config.get("JIRA_API_TOKEN")
        jira_username = config.get("JIRA_USERNAME")
        jira_project = config.get("JIRA_PROJECT")

        auth_type = "basic_auth"
        self.jira_toolkit = JiraToolkit(
            server_url=jira_instance,
            auth_type=auth_type,
            username=jira_username,
            password=jira_api_token,
            default_project=jira_project,
        )

        if hasattr(self, 'tool_manager') and self.tool_manager:
            self.jira_toolkit.set_tool_manager(self.tool_manager)

        return self.jira_toolkit.get_tools()

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

    async def create_ticket(self, summary: str, description: str, **kwargs) -> str:
        """Create a Jira ticket using the JiraToolkit."""
        question = f"""
        Create a Jira ticket for project NAV type bug with summary:
        *{summary}*
        Description:
        *{description}*"
        """
        response = await self.ask(
            question=question,
        )
        return response

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

        if df.empty:
            return []

        return df

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

    async def process_chunk(
        self,
        chunk_df: pd.DataFrame,
        chunk_index: int,
        delay: float = 2.0
    ) -> pd.DataFrame:
        """Process a chunk of tickets, retrieving details and history."""
        self.logger.info(
            f"Starting processing chunk {chunk_index} with {len(chunk_df)} tickets"
        )

        # Ensure history column exists
        if 'history' not in chunk_df.columns:
            chunk_df['history'] = None

        for idx, ticket in chunk_df.iterrows():
            issue_number = ticket['key']
            repeat = 0
            detailed_ticket = None

            # Retry logic: Try up to 3 times (initial + 2 retries)
            while repeat < 3:
                try:
                    response = await self.get_ticket(issue_number=issue_number)
                    detailed_ticket = response.output

                    if isinstance(detailed_ticket, str):
                        # Some error or unexpected string response
                        self.logger.warning(f"Got string response for {issue_number}, retrying... ({repeat+1}/3)")
                        repeat += 1
                        await asyncio.sleep(delay * (repeat + 1)) # Exponential-ish backoff
                        continue

                    if detailed_ticket is None or not hasattr(detailed_ticket, 'description'):
                        self.logger.warning(f"Invalid ticket data for {issue_number}, retrying... ({repeat+1}/3)")
                        repeat += 1
                        await asyncio.sleep(delay * (repeat + 1))
                        continue

                    break  # Success

                except Exception as e:
                    self.logger.error(f"Error processing ticket {issue_number}: {e}")
                    repeat += 1
                    await asyncio.sleep(delay * (repeat + 1))

            if detailed_ticket is None or isinstance(detailed_ticket, str):
                self.logger.error(f"Failed to retrieve ticket {issue_number} after retries. Skipping.")
                continue

            if detailed_ticket:
                # Update DataFrame with detailed info
                chunk_df.at[idx, 'summary'] = detailed_ticket.title
                chunk_df.at[idx, 'description'] = detailed_ticket.description

                # Filter and process history
                filtered_events = []
                for event in detailed_ticket.history:
                    if filtered_items := [
                        item for item in event.items
                        if item.field.lower() in ["status", "assignee", "reporter", "resolution"]
                    ]:
                        filtered_event = HistoryEvent(
                            author=event.author,
                            created=event.created,
                            items=filtered_items
                        )
                        filtered_events.append(filtered_event)

                # Sort history by creation date
                filtered_events.sort(key=lambda x: x.created)

                # Store as list of dicts
                chunk_df.at[idx, 'history'] = [event.model_dump() for event in filtered_events]
            else:
                 self.logger.error(f"Failed to retrieve ticket {issue_number} after retries. Skipping.")

            # Respect rate limit between tickets
            await asyncio.sleep(delay)

        # Save partial result
        filename = f"jira_tickets_part_{chunk_index}.csv"
        chunk_df.to_csv(filename, index=False)
        self.logger.info(f"Saved chunk {chunk_index} to {filename}")

        return chunk_df

    async def extract_all_tickets(self, max_tickets: Optional[int] = None, chunk_size: int = 50, delay: float = 2.0, concurrency: int = 5, **kwargs) -> List[pd.DataFrame]:
        """Extract all Jira tickets created in 2025 using chunked processing with rate limiting."""
        tickets_df = await self.search_all_tickets(max_tickets=max_tickets)

        if tickets_df.empty:
            return []

        # Split DataFrame into chunks
        num_chunks = math.ceil(len(tickets_df) / chunk_size)
        chunks = [
            tickets_df.iloc[i * chunk_size : (i + 1) * chunk_size].copy()
            for i in range(num_chunks)
        ]

        self.logger.info(f"Split {len(tickets_df)} tickets into {num_chunks} chunks.")

        # Semaphore for concurrency control
        sem = asyncio.Semaphore(concurrency)

        async def sem_process(chunk, i):
            async with sem:
                return await self.process_chunk(chunk, i, delay=delay)

        # Create tasks for all chunks
        tasks = [sem_process(chunk, i) for i, chunk in enumerate(chunks)]

        # Execute in parallel
        processed_chunks = await asyncio.gather(*tasks)

        return processed_chunks
