"""
WhatsApp integration for AI-Parrot.

Exposes agents via WhatsApp Business API using pywa library.
"""
from .models import WhatsAppAgentConfig
from .wrapper import WhatsAppAgentWrapper

__all__ = [
    "WhatsAppAgentConfig",
    "WhatsAppAgentWrapper",
]
