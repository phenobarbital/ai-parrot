"""
Shared configuration models for Bot Integrations.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Any, Union
from .telegram.models import TelegramAgentConfig
from .msteams.models import MSTeamsAgentConfig


@dataclass
class IntegrationBotConfig:
    """
    Root configuration for all Bot Integrations.
    Supersedes TelegramBotsConfig.

    Loaded from {ENV_DIR}/integrations_bots.yaml.

    Example YAML structure:
        agents:
          MyTelegramBot:
            kind: telegram
            chatbot_id: hr_agent
            bot_token: "xxx"
          MyTeamsBot:
            kind: msteams
            chatbot_id: sales_agent
            client_id: "xxx"
            client_secret: "yyy"
    """
    agents: Dict[str, Union[TelegramAgentConfig, MSTeamsAgentConfig]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'IntegrationBotConfig':
        """Create config from dictionary (YAML parsed data)."""
        agents = {}
        agents_data = data.get('agents', {})
        for name, agent_data in agents_data.items():
            kind = agent_data.get('kind', 'telegram')
            if kind == 'telegram':
                agents[name] = TelegramAgentConfig.from_dict(name, agent_data)
            elif kind == 'msteams':
                agents[name] = MSTeamsAgentConfig.from_dict(name, agent_data)
        return cls(agents=agents)

    def validate(self) -> List[str]:
        """
        Validate configuration and return list of errors.
        """
        errors = []
        for name, agent_config in self.agents.items():
            if not agent_config.chatbot_id:
                errors.append(f"Agent '{name}': missing 'chatbot_id'")
            
            if isinstance(agent_config, TelegramAgentConfig):
                if not agent_config.bot_token:
                    errors.append(
                        f"Agent '{name}': missing bot_token"
                    )
            elif isinstance(agent_config, MSTeamsAgentConfig):
                if not agent_config.client_id or not agent_config.client_secret:
                    errors.append(
                        f"Agent '{name}': missing client_id/client_secret"
                    )
        return errors
