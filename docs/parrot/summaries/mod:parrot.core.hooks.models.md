---
type: Wiki Summary
title: parrot.core.hooks.models
id: mod:parrot.core.hooks.models
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Pydantic models and configuration for the hooks system.
relates_to:
- concept: class:parrot.core.hooks.models.BrokerHookConfig
  rel: defines
- concept: class:parrot.core.hooks.models.FileUploadHookConfig
  rel: defines
- concept: class:parrot.core.hooks.models.FileWatchdogHookConfig
  rel: defines
- concept: class:parrot.core.hooks.models.FilesystemHookConfig
  rel: defines
- concept: class:parrot.core.hooks.models.GitHubWebhookConfig
  rel: defines
- concept: class:parrot.core.hooks.models.HookEvent
  rel: defines
- concept: class:parrot.core.hooks.models.HookType
  rel: defines
- concept: class:parrot.core.hooks.models.IMAPHookConfig
  rel: defines
- concept: class:parrot.core.hooks.models.JiraWebhookConfig
  rel: defines
- concept: class:parrot.core.hooks.models.MatrixHookConfig
  rel: defines
- concept: class:parrot.core.hooks.models.MessagingHookConfig
  rel: defines
- concept: class:parrot.core.hooks.models.PostgresHookConfig
  rel: defines
- concept: class:parrot.core.hooks.models.SchedulerHookConfig
  rel: defines
- concept: class:parrot.core.hooks.models.SharePointHookConfig
  rel: defines
- concept: class:parrot.core.hooks.models.TransitionAction
  rel: defines
- concept: class:parrot.core.hooks.models.TransitionActionType
  rel: defines
- concept: class:parrot.core.hooks.models.WhatsAppRedisHookConfig
  rel: defines
- concept: func:parrot.core.hooks.models.create_crew_whatsapp_hook
  rel: defines
- concept: func:parrot.core.hooks.models.create_multi_agent_whatsapp_hook
  rel: defines
- concept: func:parrot.core.hooks.models.create_simple_whatsapp_hook
  rel: defines
---

# `parrot.core.hooks.models`

Pydantic models and configuration for the hooks system.

## Classes

- **`HookType(str, Enum)`** — Supported hook types.
- **`HookEvent(BaseModel)`** — Unified event emitted by any hook into the orchestrator.
- **`SchedulerHookConfig(BaseModel)`** — Configuration for the APScheduler-based hook.
- **`FileWatchdogHookConfig(BaseModel)`** — Configuration for file-system watchdog hook.
- **`PostgresHookConfig(BaseModel)`** — Configuration for PostgreSQL LISTEN/NOTIFY hook.
- **`IMAPHookConfig(BaseModel)`** — Configuration for IMAP mailbox monitoring hook.
- **`TransitionActionType(str, Enum)`** — Supported action types for Jira transition handlers.
- **`TransitionAction(BaseModel)`** — A single transition-to-action mapping.
- **`JiraWebhookConfig(BaseModel)`** — Configuration for Jira webhook receiver.
- **`GitHubWebhookConfig(BaseModel)`** — Configuration for GitHub webhook receiver.
- **`FileUploadHookConfig(BaseModel)`** — Configuration for HTTP file upload hook.
- **`BrokerHookConfig(BaseModel)`** — Configuration for message broker hooks (Redis, RabbitMQ, MQTT, SQS).
- **`SharePointHookConfig(BaseModel)`** — Configuration for SharePoint webhook hook.
- **`MessagingHookConfig(BaseModel)`** — Configuration for messaging platform hooks (Telegram, WhatsApp, MS Teams).
- **`WhatsAppRedisHookConfig(BaseModel)`** — Configuration for WhatsApp Redis Bridge hook.
- **`MatrixHookConfig(BaseModel)`** — Configuration for Matrix protocol hook.
- **`FilesystemHookConfig(BaseModel)`** — Configuration for FilesystemTransport hook.

## Functions

- `def create_simple_whatsapp_hook(agent_name: str, allowed_phones: Optional[List[str]]=None, command_prefix: str='') -> WhatsAppRedisHookConfig` — Create a simple WhatsApp hook that routes all messages to one agent.
- `def create_multi_agent_whatsapp_hook(default_agent: str, routes: List[Dict[str, Any]], command_prefix: str='') -> WhatsAppRedisHookConfig` — Create a multi-agent WhatsApp hook with keyword/phone routing.
- `def create_crew_whatsapp_hook(crew_id: str, allowed_phones: Optional[List[str]]=None, command_prefix: str='!') -> WhatsAppRedisHookConfig` — Create a WhatsApp hook that routes messages to an AgentCrew.
