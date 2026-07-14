---
type: Wiki Entity
title: JiraSpecialist
id: class:parrot.bots.jira_specialist.JiraSpecialist
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Base class for Jira specialist agents.
relates_to:
- concept: class:parrot.bots.agent.Agent
  rel: extends
---

# JiraSpecialist

Defined in [`parrot.bots.jira_specialist`](../summaries/mod:parrot.bots.jira_specialist.md).

```python
class JiraSpecialist(Agent)
```

Base class for Jira specialist agents.

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

## Methods

- `def set_wrapper(self, wrapper) -> None` — Called by TelegramAgentWrapper to give the agent a reference
- `def set_agent_dispatcher(self, dispatcher: AgentDispatcher) -> None` — Wire an async dispatcher so TRIGGER_AGENT actions can invoke
- `async def load_developers(self) -> List[Developer]` — Load the developer list from config/database.
- `def agent_tools(self)` — Return agent-specific non-Jira tools.
- `async def post_configure(self) -> None` — Wire the :class:`JiraToolkit` using app-scoped credentials.
- `async def clone_for_user(self, user_context: UserContext) -> 'JiraSpecialist'` — Return a fully isolated per-user clone of this agent.
- `async def run_morning_standup(self, developer: Optional[dict]=None, developer_id: Optional[str]=None, **kwargs: Any) -> List[Dict[str, Any]]` — Run the morning standup for one or all configured developers.
- `async def run_eod_standup(self, developer_id: Optional[str]=None, **kwargs: Any) -> List[Dict[str, Any]]` — Run the end-of-day standup wrap for one or all developers.
- `async def dispatch_daily_tickets(self) -> Dict[str, Any]` — CRON entry point: Send daily ticket messages to all developers.
- `async def on_ticket_selected(self, callback: CallbackContext) -> CallbackResult` — Handle ticket selection.
- `async def on_ticket_skipped(self, callback: CallbackContext) -> CallbackResult` — Handle skip — developer already has a plan for today.
- `async def escalate_non_responders(self, manager_chat_id: Optional[int]=None) -> Dict[str, Any]` — CRON entry point: Check for non-responders and escalate.
- `async def get_standup_status(self) -> Dict[str, Any]` — Get current daily standup status.
- `async def handle_hook_event(self, event: HookEvent) -> Optional[Dict[str, Any]]` — Route :class:`HookEvent` instances emitted by ``JiraWebhookHook``.
- `async def handle_jira_assignment(self, payload: Dict[str, Any]) -> Dict[str, Any]` — Kick off the assignment conversation with the developer on Telegram.
- `async def handle_jira_ticket_created(self, payload: Dict[str, Any]) -> Dict[str, Any]` — Auto-repoint the reporter of a freshly-created Jira ticket when
- `async def handle_ready_for_test(self, payload: Dict[str, Any]) -> Dict[str, Any]` — Notify the QA channel when a ticket transitions to "Ready For Test".
- `async def create_ticket(self, summary: str, description: str, **kwargs) -> str` — Create a Jira ticket using the JiraToolkit.
- `async def search_all_tickets(self, start_date: str='2025-01-01', end_date: str='2026-02-28', max_tickets: Optional[int]=None, **kwargs) -> List[JiraTicket]` — Search for due Jira tickets using the JiraToolkit and return structured output.
- `async def weekly_ticket_count_report(self) -> Dict[str, Any]` — Month-to-date ticket count by Assignee grouped by Component.
- `async def get_ticket(self, issue_number: str) -> JiraTicketDetail` — Get detailed information for a specific Jira ticket, including history.
- `async def get_in_progress_by_assignee(self, projects: Optional[List[str]]=None, max_per_assignee: int=3, statuses: Optional[List[str]]=None) -> Dict[str, Any]` — Return all "In Progress" Jira tickets grouped by assignee.
