"""External hooks system for AutonomousOrchestrator.

All concrete hook imports are lazy to avoid pulling in heavy
transitive dependencies (asyncpg, watchdog, apscheduler, aioimaplib,
azure-identity, etc.) at package import time.
"""
import importlib
from .base import BaseHook
from .manager import HookManager
from .models import (
    BrokerHookConfig,
    FileUploadHookConfig,
    FileWatchdogHookConfig,
    HookEvent,
    HookType,
    IMAPHookConfig,
    JiraWebhookConfig,
    MatrixHookConfig,
    MessagingHookConfig,
    PostgresHookConfig,
    SchedulerHookConfig,
    SharePointHookConfig,
    WhatsAppRedisHookConfig,
    create_crew_whatsapp_hook,
    create_multi_agent_whatsapp_hook,
    create_simple_whatsapp_hook,
)


def __getattr__(name: str):
    """Lazy-import concrete hook classes on first access."""
    _lazy_map = {
        # Core hooks
        "SchedulerHook": ".scheduler",
        "FileWatchdogHook": ".file_watchdog",
        "PostgresListenHook": ".postgres",
        "IMAPWatchdogHook": ".imap",
        "JiraWebhookHook": ".jira_webhook",
        "FileUploadHook": ".file_upload",
        "SharePointHook": ".sharepoint",
        # Messaging hooks
        "TelegramHook": ".messaging",
        "WhatsAppHook": ".messaging",
        "MSTeamsHook": ".messaging",
        "WhatsAppRedisHook": ".whatsapp_redis",
        "MatrixHook": ".matrix",
        # Broker hooks
        "BaseBrokerHook": ".brokers.base",
        "RedisBrokerHook": ".brokers.redis",
        "RabbitMQBrokerHook": ".brokers.rabbitmq",
        "MQTTBrokerHook": ".brokers.mqtt",
        "SQSBrokerHook": ".brokers.sqs",
    }
    if name in _lazy_map:
        module = importlib.import_module(_lazy_map[name], package=__name__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Core
    "BaseHook",
    "HookManager",
    "HookEvent",
    "HookType",
    # Hooks (lazy)
    "SchedulerHook",
    "FileWatchdogHook",
    "PostgresListenHook",
    "IMAPWatchdogHook",
    "JiraWebhookHook",
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
    "FileUploadHookConfig",
    "BrokerHookConfig",
    "SharePointHookConfig",
    "MessagingHookConfig",
    "WhatsAppRedisHookConfig",
    "MatrixHookConfig",
    # Factory helpers
    "create_simple_whatsapp_hook",
    "create_multi_agent_whatsapp_hook",
    "create_crew_whatsapp_hook",
]
