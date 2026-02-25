"""
Data models for MS Teams bot configuration.
"""
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, Optional, Any
from navconfig import config

if TYPE_CHECKING:
    from .voice.models import VoiceTranscriberConfig


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
        voice_config: Optional voice transcription configuration.
    """
    name: str
    chatbot_id: str
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    app_type: str = "MultiTenant"
    app_tenantid: Optional[str] = None
    kind: str = "msteams"
    welcome_message: Optional[str] = None
    commands: Dict[str, str] = field(default_factory=dict)
    dialog: Optional[Any] = None
    forms_directory: Optional[str] = None
    enable_group_mentions: bool = True
    enable_group_commands: bool = True
    voice_config: Optional["VoiceTranscriberConfig"] = None

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

    @property
    def APP_TYPE(self) -> str:
        return self.app_type

    @property
    def APP_TENANTID(self) -> Optional[str]:
        return self.app_tenantid

    @property
    def voice_enabled(self) -> bool:
        """Check if voice transcription is enabled."""
        return self.voice_config is not None and self.voice_config.enabled

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> 'MSTeamsAgentConfig':
        """Create config from dictionary."""
        # Parse voice_config if provided
        voice_config = None
        if voice_data := data.get('voice_config'):
            from .voice.models import VoiceTranscriberConfig
            if isinstance(voice_data, dict):
                voice_config = VoiceTranscriberConfig(**voice_data)
            elif isinstance(voice_data, VoiceTranscriberConfig):
                voice_config = voice_data

        return cls(
            name=name,
            chatbot_id=data.get('chatbot_id', name),
            client_id=data.get('client_id'),
            client_secret=data.get('client_secret'),
            app_type=data.get('app_type', 'MultiTenant'),
            app_tenantid=data.get('app_tenantid'),
            welcome_message=data.get('welcome_message'),
            commands=data.get('commands', {}),
            dialog=data.get('dialog'),
            enable_group_mentions=data.get('enable_group_mentions', True),
            enable_group_commands=data.get('enable_group_commands', True),
            voice_config=voice_config,
        )
