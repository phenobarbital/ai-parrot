"""External hooks system for AutonomousOrchestrator.

FEAT-317: the generic hooks layer (``BaseHook``, ``HookRegistry``,
``HookManager``, ``HookableAgent``, models, ``SchedulerHook``,
``FileWatchdogHook``, and the broker hooks) was extracted to
``navigator_eventbus.hooks`` (FEAT-312/FEAT-316). This module re-exports
that surface and lazy-loads ai-parrot's own integration hooks (jira,
github, sharepoint, whatsapp, matrix, imap, messaging, postgres,
file_upload), which stay local.

All concrete hook imports are lazy to avoid pulling in heavy
transitive dependencies (asyncpg, watchdog, apscheduler, aioimaplib,
azure-identity, etc.) at package import time.
"""
import importlib
from navigator_eventbus.hooks import BaseHook, HookRegistry, MessagingHook
from navigator_eventbus.hooks import HookManager
from navigator_eventbus.hooks import HookableAgent
from navigator_eventbus.hooks import (
    BrokerHookConfig,
    FileUploadHookConfig,
    FileWatchdogHookConfig,
    GitHubWebhookConfig,
    HookEvent,
    HookType,
    IMAPHookConfig,
    JiraWebhookConfig,
    MatrixHookConfig,
    MessagingHookConfig,
    PostgresHookConfig,
    SchedulerHookConfig,
    SharePointHookConfig,
    TransitionAction,
    TransitionActionType,
    WhatsAppRedisHookConfig,
    create_crew_whatsapp_hook,
    create_multi_agent_whatsapp_hook,
    create_simple_whatsapp_hook,
)


def __getattr__(name: str):
    """Lazy-import concrete hook classes on first access."""
    _lazy_map = {
        # Generic hooks — now live in navigator_eventbus.hooks
        "SchedulerHook": "navigator_eventbus.hooks.scheduler",
        "FileWatchdogHook": "navigator_eventbus.hooks.file_watchdog",
        # Integration hooks — stay local
        "PostgresListenHook": ".postgres",
        "IMAPWatchdogHook": ".imap",
        "JiraWebhookHook": ".jira_webhook",
        "GitHubWebhookHook": ".github_webhook",
        "FileUploadHook": ".file_upload",
        "SharePointHook": ".sharepoint",
        # Messaging hooks — stay local
        "TelegramHook": ".messaging",
        "WhatsAppHook": ".messaging",
        "MSTeamsHook": ".messaging",
        "WhatsAppRedisHook": ".whatsapp_redis",
        "MatrixHook": ".matrix",
        # Broker hooks — now live in navigator_eventbus.hooks.brokers
        "BaseBrokerHook": "navigator_eventbus.hooks.brokers.base",
        "RedisBrokerHook": "navigator_eventbus.hooks.brokers.redis",
        "RabbitMQBrokerHook": "navigator_eventbus.hooks.brokers.rabbitmq",
        "MQTTBrokerHook": "navigator_eventbus.hooks.brokers.mqtt",
        "SQSBrokerHook": "navigator_eventbus.hooks.brokers.sqs",
    }
    if name in _lazy_map:
        target = _lazy_map[name]
        if target.startswith("."):
            module = importlib.import_module(target, package=__name__)
        else:
            module = importlib.import_module(target)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Core
    "BaseHook",
    "HookRegistry",
    "MessagingHook",
    "HookManager",
    "HookableAgent",
    "HookEvent",
    "HookType",
    # Hooks (lazy)
    "SchedulerHook",
    "FileWatchdogHook",
    "PostgresListenHook",
    "IMAPWatchdogHook",
    "JiraWebhookHook",
    "GitHubWebhookHook",
    "FileUploadHook",
    "SharePointHook",
    # Messaging hooks (lazy)
    "TelegramHook",
    "WhatsAppHook",
    "MSTeamsHook",
    "WhatsAppRedisHook",
    "MatrixHook",
    # Brokers (lazy)
    "BaseBrokerHook",
    "RedisBrokerHook",
    "RabbitMQBrokerHook",
    "MQTTBrokerHook",
    "SQSBrokerHook",
    # Configs (eagerly imported — lightweight Pydantic models)
    "SchedulerHookConfig",
    "FileWatchdogHookConfig",
    "PostgresHookConfig",
    "IMAPHookConfig",
    "JiraWebhookConfig",
    "GitHubWebhookConfig",
    "FileUploadHookConfig",
    "BrokerHookConfig",
    "SharePointHookConfig",
    "MessagingHookConfig",
    "WhatsAppRedisHookConfig",
    "MatrixHookConfig",
    # Transition action models
    "TransitionAction",
    "TransitionActionType",
    # Factory helpers
    "create_simple_whatsapp_hook",
    "create_multi_agent_whatsapp_hook",
    "create_crew_whatsapp_hook",
]
