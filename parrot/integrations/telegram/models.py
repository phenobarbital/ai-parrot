"""
Data models for Telegram bot configuration.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from navconfig import config


@dataclass
class TelegramAgentConfig:
    """
    Configuration for a single agent exposed via Telegram.

    Attributes:
        name: Agent name (used as key in YAML and for env var fallback).
        chatbot_id: ID/name of the bot in BotManager (used with get_bot()).
        bot_token: Telegram bot token. If not provided, reads from
                   {NAME}_TELEGRAM_TOKEN environment variable.
        allowed_chat_ids: Optional list of chat IDs that can use this bot.
                          If None, the bot is accessible to all chats.
        welcome_message: Custom message sent when user issues /start command.
        system_prompt_override: Override the agent's default system prompt.
        commands: Custom commands that map to agent methods.
                  Format: {"command_name": "agent_method_name"}
                  E.g.:   {"report": "generate_report"}
        enable_group_mentions: Allow bot to respond to @mentions in groups.
        enable_group_commands: Allow bot to respond to /ask command in groups.
        reply_in_thread: Reply as thread to original message in groups.
        enable_channel_posts: Allow bot to process channel posts with @mentions.
    """
    name: str
    chatbot_id: str
    bot_token: Optional[str] = None
    allowed_chat_ids: Optional[List[int]] = None
    welcome_message: Optional[str] = None
    system_prompt_override: Optional[str] = None
    kind: str = "telegram"
    commands: Dict[str, str] = field(default_factory=dict)
    # Group/channel support settings
    enable_group_mentions: bool = True
    enable_group_commands: bool = True
    reply_in_thread: bool = True
    enable_channel_posts: bool = False

    def __post_init__(self):
        """
        Resolve bot_token from environment variable if not provided in YAML.

        Falls back to {AGENT_NAME}_TELEGRAM_TOKEN environment variable.
        For example, HRAgent would look for HRAGENT_TELEGRAM_TOKEN.
        """
        if not self.bot_token:
            env_var_name = f"{self.name.upper()}_TELEGRAM_TOKEN"
            self.bot_token = config.get(env_var_name)

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> 'TelegramAgentConfig':
        """Create config from dictionary (YAML parsed data)."""
        return cls(
            name=name,
            chatbot_id=data.get('chatbot_id', name),  # Default to name if not specified
            bot_token=data.get('bot_token'),
            allowed_chat_ids=data.get('allowed_chat_ids'),
            welcome_message=data.get('welcome_message'),
            system_prompt_override=data.get('system_prompt_override'),
            commands=data.get('commands', {}),
            enable_group_mentions=data.get('enable_group_mentions', True),
            enable_group_commands=data.get('enable_group_commands', True),
            reply_in_thread=data.get('reply_in_thread', True),
            enable_channel_posts=data.get('enable_channel_posts', False),
        )


@dataclass
class TelegramBotsConfig:
    """
    Root configuration for all Telegram bots.

    Loaded from {ENV_DIR}/telegram_bots.yaml.

    Example YAML structure:
        agents:
          HRAgent:
            chatbot_id: hr_agent
            welcome_message: "Hello! I'm your HR Assistant."
            # bot_token: optional - defaults to HRAGENT_TELEGRAM_TOKEN env var
    """
    agents: Dict[str, TelegramAgentConfig] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TelegramBotsConfig':
        """Create config from dictionary (YAML parsed data)."""
        agents = {}
        agents_data = data.get('agents', {})
        for name, agent_data in agents_data.items():
            agents[name] = TelegramAgentConfig.from_dict(name, agent_data)
        return cls(agents=agents)

    def validate(self) -> List[str]:
        """
        Validate configuration and return list of errors.

        Returns:
            List of error messages (empty if valid).
        """
        errors = []
        for name, agent_config in self.agents.items():
            if not agent_config.chatbot_id:
                errors.append(f"Agent '{name}': missing 'chatbot_id'")
            if not agent_config.bot_token:
                errors.append(
                    f"Agent '{name}': missing bot_token (set in YAML or "
                    f"env var {name.upper()}_TELEGRAM_TOKEN)"
                )
        return errors
