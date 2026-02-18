"""Slack integration module."""

from .models import SlackAgentConfig
from .wrapper import SlackAgentWrapper

__all__ = ["SlackAgentConfig", "SlackAgentWrapper"]
