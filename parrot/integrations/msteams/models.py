"""
Data models for MS Teams bot configuration.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from navconfig import config


@dataclass
class MSTeamsAgentConfig:
    """
    Configuration for a single agent exposed via MS Teams.

    Attributes:
        name: Agent name.
        chatbot_id: ID/name of the bot in BotManager.
        client_id: Microsoft App ID.
        client_secret: Microsoft App Password.
        kind: Integration type (msteams).
        welcome_message: Custom welcome message.
        commands: Custom commands map.
        dialog: Optional dialog configuration.
    """
    name: str
    chatbot_id: str
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    kind: str = "msteams"
    welcome_message: Optional[str] = None
    commands: Dict[str, str] = field(default_factory=dict)
    dialog: Optional[Any] = None
    forms_directory: Optional[str] = None

    def __post_init__(self):
        """
        Resolve credentials from environment variables if not provided.
        """
        if not self.client_id:
            env_var_name = f"{self.name.upper()}_MICROSOFT_APP_ID"
            self.client_id = config.get(env_var_name)
        if not self.client_secret:
            env_var_name = f"{self.name.upper()}_MICROSOFT_APP_PASSWORD"
            self.client_secret = config.get(env_var_name)

    @property
    def APP_ID(self) -> str:
        return self.client_id

    @property
    def APP_PASSWORD(self) -> str:
        return self.client_secret

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> 'MSTeamsAgentConfig':
        """Create config from dictionary."""
        return cls(
            name=name,
            chatbot_id=data.get('chatbot_id', name),
            client_id=data.get('client_id'),
            client_secret=data.get('client_secret'),
            welcome_message=data.get('welcome_message'),
            commands=data.get('commands', {}),
            dialog=data.get('dialog')
        )
