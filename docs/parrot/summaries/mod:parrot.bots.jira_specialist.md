---
type: Wiki Summary
title: parrot.bots.jira_specialist
id: mod:parrot.bots.jira_specialist
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Jira Specialist Agent with Daily Standup Workflow.
relates_to:
- concept: class:parrot.bots.jira_specialist.DailyStandupConfig
  rel: defines
- concept: class:parrot.bots.jira_specialist.Developer
  rel: defines
- concept: class:parrot.bots.jira_specialist.HistoryEvent
  rel: defines
- concept: class:parrot.bots.jira_specialist.HistoryItem
  rel: defines
- concept: class:parrot.bots.jira_specialist.JiraSpecialist
  rel: defines
- concept: class:parrot.bots.jira_specialist.JiraTicket
  rel: defines
- concept: class:parrot.bots.jira_specialist.JiraTicketDetail
  rel: defines
- concept: class:parrot.bots.jira_specialist.JiraTicketResponse
  rel: defines
- concept: mod:parrot.auth.context
  rel: references
- concept: mod:parrot.auth.credentials
  rel: references
- concept: mod:parrot.bots
  rel: references
- concept: mod:parrot.bots._types
  rel: references
- concept: mod:parrot.bots.prompts
  rel: references
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.core.hooks.models
  rel: references
- concept: mod:parrot.integrations.telegram
  rel: references
- concept: mod:parrot.integrations.telegram.callbacks
  rel: references
- concept: mod:parrot.models.google
  rel: references
- concept: mod:parrot.tools.reminder
  rel: references
- concept: mod:parrot_tools.jiratoolkit
  rel: references
---

# `parrot.bots.jira_specialist`

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

## Classes

- **`JiraTicket(BaseModel)`** — Model representing a Jira Ticket.
- **`HistoryItem(BaseModel)`** — Model representing a history item.
- **`HistoryEvent(BaseModel)`** — History of Events.
- **`JiraTicketDetail(BaseModel)`** — Detailed Jira Ticket model with history.
- **`JiraTicketResponse(BaseModel)`** — Model representing a Jira Ticket Response.
- **`Developer(BaseModel)`** — A developer in the team with Jira + Telegram mappings.
- **`DailyStandupConfig(BaseModel)`** — Configuration for the daily standup workflow.
- **`JiraSpecialist(Agent)`** — Base class for Jira specialist agents.
