"""Slack integration module."""

from .assistant import SlackAssistantHandler
from .dedup import EventDeduplicator, RedisEventDeduplicator
from .files import (
    download_slack_file,
    upload_file_to_slack,
    extract_files_from_event,
    is_processable_file,
    PROCESSABLE_MIME_TYPES,
)
from .interactive import (
    ActionRegistry,
    SlackInteractiveHandler,
    build_feedback_blocks,
    build_clear_button,
)
from .models import SlackAgentConfig
from .security import verify_slack_signature_raw
from .socket_handler import SlackSocketHandler
from .wrapper import SlackAgentWrapper

__all__ = [
    # Assistant (Agents & AI Apps)
    "SlackAssistantHandler",
    # Deduplication
    "EventDeduplicator",
    "RedisEventDeduplicator",
    # File handling
    "download_slack_file",
    "upload_file_to_slack",
    "extract_files_from_event",
    "is_processable_file",
    "PROCESSABLE_MIME_TYPES",
    # Interactive (Block Kit)
    "ActionRegistry",
    "SlackInteractiveHandler",
    "build_feedback_blocks",
    "build_clear_button",
    # Config and wrapper
    "SlackAgentConfig",
    "SlackAgentWrapper",
    # Socket Mode
    "SlackSocketHandler",
    # Security
    "verify_slack_signature_raw",
]
