"""Configuration models for MatrixCrewTransport.

Pydantic v2 models for configuring a multi-agent crew
operating on a Matrix homeserver via the Application Service protocol.
"""

import logging
import os
import re
from typing import Dict, List, Literal, Optional

import yaml
from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)

_ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _substitute_env_vars(value: str) -> str:
    """Replace ``${ENV_VAR}`` patterns with environment variable values.

    Args:
        value: String potentially containing ``${VAR}`` placeholders.

    Returns:
        String with placeholders replaced by their env-var values.
    """

    def _replace(match: re.Match) -> str:
        var_name = match.group(1)
        env_value = os.environ.get(var_name, "")
        if not env_value:
            logger.warning("Environment variable %s is not set", var_name)
        return env_value

    return _ENV_VAR_PATTERN.sub(_replace, value)


def _walk_and_substitute(obj):
    """Recursively walk a data structure and substitute env vars in strings.

    Args:
        obj: A string, dict, list, or scalar value.

    Returns:
        The same structure with all string values env-var substituted.
    """
    if isinstance(obj, str):
        return _substitute_env_vars(obj)
    if isinstance(obj, dict):
        return {k: _walk_and_substitute(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk_and_substitute(item) for item in obj]
    return obj


class MatrixCrewAgentEntry(BaseModel):
    """Configuration for a single agent in the Matrix crew.

    Attributes:
        chatbot_id: BotManager lookup key.
        display_name: Human-readable name shown in Matrix.
        mxid_localpart: Localpart of the virtual MXID (e.g. "analyst").
        avatar_url: Optional mxc:// URL for the agent's avatar.
        dedicated_room_id: Agent's own private room (optional).
        skills: Skill descriptions shown on the status board.
        tags: Routing tags for message routing.
        file_types: Accepted file MIME types.
    """

    chatbot_id: str = Field(..., description="BotManager lookup key")
    display_name: str = Field(..., description="Human-readable display name")
    mxid_localpart: str = Field(..., description="Localpart for virtual MXID (e.g. 'analyst')")
    avatar_url: Optional[str] = Field(default=None, description="mxc:// URL for agent avatar")
    dedicated_room_id: Optional[str] = Field(default=None, description="Agent's private dedicated room ID")
    skills: List[str] = Field(default_factory=list, description="Skill descriptions for status board")
    tags: List[str] = Field(default_factory=list, description="Routing tags")
    file_types: List[str] = Field(default_factory=list, description="Accepted file MIME types")


class CollaborativeConfig(BaseModel):
    """Configuration for collaborative multi-agent investigation sessions.

    Controls how ``!investigate`` commands trigger collaborative sessions,
    including round counts, timeouts, summarizer agent, and verbosity.

    Attributes:
        command_prefix: Trigger command that initiates a collaborative session.
        max_rounds: Number of cross-pollination rounds (1-10).
        agent_timeout: Per-agent response timeout in seconds.
        session_timeout: Maximum total session duration in seconds.
        summarizer_agent: Agent name for final synthesis (None = post raw results).
        session_verbosity: 'full' posts all announcements, 'minimal' reduces them.
        include_chat_context: Pass recent chat history to the summarizer.
        max_concurrent_sessions: Maximum number of concurrent sessions per room.
        cooldown_seconds: Minimum gap between session triggers in a room.
    """

    command_prefix: str = Field(
        default="!investigate",
        description="Trigger command that initiates a collaborative session",
    )
    max_rounds: int = Field(
        default=1,
        ge=1,
        le=10,
        description="Number of cross-pollination rounds",
    )
    agent_timeout: float = Field(
        default=120.0,
        description="Per-agent response timeout in seconds",
    )
    session_timeout: float = Field(
        default=600.0,
        description="Maximum total session duration in seconds",
    )
    summarizer_agent: Optional[str] = Field(
        default=None,
        description="Agent name for final synthesis (None = post raw results)",
    )
    session_verbosity: Literal["full", "minimal", "silent"] = Field(
        default="full",
        description="'full' posts all announcements, 'minimal' reduces them, 'silent' suppresses all",
    )
    include_chat_context: bool = Field(
        default=True,
        description="Pass recent chat history to the summarizer",
    )
    max_concurrent_sessions: int = Field(
        default=3,
        ge=1,
        le=20,
        description="Maximum number of concurrent collaborative sessions per room",
    )
    cooldown_seconds: float = Field(
        default=10.0,
        ge=0,
        description="Minimum gap between session triggers in a room",
    )


class ChannelConfig(BaseModel):
    """A declared agent channel materialised as a Matrix room.

    Attributes:
        name: Alias localpart (``#<name>:<server_name>``).
        visibility: ``public`` (anyone may join) or ``private`` (invite-only).
        agents: Member agent names (keys of ``MatrixCrewConfig.agents``).
        answer_policy: How un-mentioned human text is handled —
            ``mention`` (ignore unless @mentioned), ``swarm`` (start a
            collaborative session), or ``silent`` (never respond).
        room_id: Pre-existing room id; a new room is created when ``None``.
        topic: Optional room topic set at creation time.
    """

    name: str = Field(..., pattern=r"^[a-z0-9][a-z0-9_-]*$", description="alias localpart")
    visibility: Literal["public", "private"] = "public"
    agents: List[str] = Field(default_factory=list)
    answer_policy: Literal["mention", "swarm", "silent"] = "mention"
    room_id: Optional[str] = None
    topic: Optional[str] = None


class TunnelConfig(BaseModel):
    """Configuration for private agent-to-agent tunnels.

    Attributes:
        enabled: Whether tunnels may be created.
        ttl_minutes: Idle timeout before a tunnel is tombstoned (0 = forever).
        max_hops: Maximum number of relayed hops before a task is rejected.
        default_timeout: Default ``ask`` timeout in seconds.
        echo_summary_to_channel: Whether to post a one-line echo of a
            cross-pollination question in the originating channel.
    """

    enabled: bool = True
    ttl_minutes: int = Field(default=120, ge=0, description="0 = keep forever")
    max_hops: int = Field(default=3, ge=1, le=10)
    default_timeout: float = Field(default=60.0, gt=0)
    echo_summary_to_channel: bool = True


class SpaceConfig(BaseModel):
    """Optional Matrix Space grouping for channels and tunnels.

    Attributes:
        enabled: Whether a Space is created and children are linked.
        name: Space room name.
        room_id: Pre-existing Space room id; created when ``None``.
    """

    enabled: bool = False
    name: str = "Parrot Swarm"
    room_id: Optional[str] = None


class MatrixCrewConfig(BaseModel):
    """Root configuration for a Matrix multi-agent crew.

    Attributes:
        homeserver_url: Matrix homeserver URL.
        server_name: Server domain name (e.g. "example.com").
        as_token: Application Service token.
        hs_token: Homeserver token.
        bot_mxid: Coordinator bot MXID.
        general_room_id: Shared room for all agents.
        agents: Mapping of agent_name to MatrixCrewAgentEntry.
        appservice_port: AS HTTP listener port.
        pinned_registry: Whether to pin the status board in the general room.
        typing_indicator: Whether to show typing while processing.
        streaming: Whether to use edit-based streaming.
        unaddressed_agent: Default agent for unmentioned messages.
        max_message_length: Chunk responses beyond this length.
        collaborative: Optional collaborative session configuration.
        channels: Declared agent channels (public/private rooms with policy).
        tunnels: Configuration for private agent-to-agent tunnels.
        space: Optional Matrix Space grouping for channels and tunnels.
        human_namespace_patterns: Regex patterns identifying bridged human
            MXIDs (e.g. Slack/Signal/Discord puppets) so they are treated
            the same as native Matrix humans.
    """

    homeserver_url: str = Field(..., description="Matrix homeserver URL")
    server_name: str = Field(..., description="Server domain name (e.g. 'example.com')")
    as_token: str = Field(..., description="Application Service token")
    hs_token: str = Field(..., description="Homeserver token")
    bot_mxid: str = Field(..., description="Coordinator bot full MXID")
    general_room_id: str = Field(..., description="Shared room ID for all agents")
    agents: Dict[str, MatrixCrewAgentEntry] = Field(default_factory=dict, description="agent_name → configuration")
    appservice_port: int = Field(default=8449, description="AS HTTP listener port")
    pinned_registry: bool = Field(default=True, description="Pin status board in general room")
    typing_indicator: bool = Field(default=True, description="Show typing indicator while processing")
    streaming: bool = Field(default=True, description="Use edit-based streaming for responses")
    unaddressed_agent: Optional[str] = Field(default=None, description="Default agent for unmentioned messages")
    max_message_length: int = Field(default=4096, description="Chunk responses beyond this length")
    collaborative: Optional[CollaborativeConfig] = Field(
        default=None,
        description="Collaborative session configuration (optional, backward-compatible)",
    )
    channels: List[ChannelConfig] = Field(default_factory=list, description="Declared agent channels")
    tunnels: TunnelConfig = Field(
        default_factory=TunnelConfig,
        description="Private agent-to-agent tunnel configuration",
    )
    space: SpaceConfig = Field(
        default_factory=SpaceConfig,
        description="Optional Matrix Space grouping for channels and tunnels",
    )
    human_namespace_patterns: List[str] = Field(
        default_factory=lambda: [r"^@signal_", r"^@slack_", r"^@discord_"],
        description="Regex patterns identifying bridged human MXIDs",
    )

    @model_validator(mode="after")
    def validate_channels(self) -> "MatrixCrewConfig":
        """Validate declared channels.

        Ensures channel names are unique, every channel's ``agents`` entry
        refers to a known agent (only enforced when ``agents`` is
        non-empty, mirroring ``validate_summarizer_agent``), and any
        channel using ``answer_policy="swarm"`` has ``collaborative``
        configured.

        Returns:
            Self after validation.

        Raises:
            ValueError: On duplicate channel names, unknown member agents,
                or a ``swarm`` channel without ``collaborative`` configured.
        """
        names = [c.name for c in self.channels]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate channel names: {names}")
        for ch in self.channels:
            if self.agents:
                unknown = [a for a in ch.agents if a not in self.agents]
                if unknown:
                    raise ValueError(f"channel '{ch.name}' references unknown agents {unknown}")
            if ch.answer_policy == "swarm" and self.collaborative is None:
                raise ValueError(
                    f"channel '{ch.name}' uses answer_policy=swarm but " "'collaborative' is not configured"
                )
        return self

    def channel(self, name: str) -> Optional[ChannelConfig]:
        """Look up a declared channel by name.

        Args:
            name: Channel name (alias localpart).

        Returns:
            The matching ``ChannelConfig``, or ``None`` if not found.
        """
        return next((c for c in self.channels if c.name == name), None)

    @model_validator(mode="after")
    def validate_summarizer_agent(self) -> "MatrixCrewConfig":
        """Ensure summarizer_agent references a known agent in the agents dict.

        Validation is only enforced when ``agents`` is non-empty.  An empty
        ``agents`` dict is allowed (e.g. minimal / test configurations), so
        referencing a ``summarizer_agent`` before agents are declared is valid.

        Returns:
            Self after validation.

        Raises:
            ValueError: If ``collaborative.summarizer_agent`` is set, the
                ``agents`` dict is non-empty, and the summarizer name is not a
                key in ``agents``.
        """
        if self.collaborative and self.collaborative.summarizer_agent and self.agents:
            if self.collaborative.summarizer_agent not in self.agents:
                raise ValueError(
                    f"summarizer_agent '{self.collaborative.summarizer_agent}' "
                    f"not found in agents: {list(self.agents.keys())}"
                )
        return self

    @classmethod
    def from_yaml(cls, path: str) -> "MatrixCrewConfig":
        """Load configuration from a YAML file with ``${ENV_VAR}`` substitution.

        Args:
            path: Path to the YAML configuration file.

        Returns:
            A validated MatrixCrewConfig instance.

        Raises:
            FileNotFoundError: If the YAML file does not exist.
            yaml.YAMLError: If the YAML is malformed.
            ValidationError: If the data fails Pydantic validation.
            ValueError: If the YAML file is empty.
        """
        logger.info("Loading Matrix crew config from %s", path)
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        if raw is None:
            raise ValueError(f"Empty YAML file: {path}")
        data = _walk_and_substitute(raw)
        return cls(**data)
