"""Database model for per-user defined bots (``navigator.users_bots``).

Mirrors :class:`parrot.handlers.models.bots.BotModel` but is keyed by
``(user_id, chatbot_id)`` so each user owns their own private set of bots.

``mcp_config`` and ``tools_config`` are persisted as AES-GCM encrypted
base64 blobs because they may carry credentials.  The model exposes the
plaintext via :meth:`get_mcp_config` / :meth:`get_tools_config` and accepts
plaintext via :meth:`set_mcp_config` / :meth:`set_tools_config`; encryption
happens transparently at write time.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, List, Optional

from datamodel import Field
from asyncdb.models import Model

from parrot.conf import PARROT_SCHEMA

from ._encrypted_field import seal, unseal


class UserBotModel(Model):
    """Per-user bot definition.

    All fields mirror :class:`BotModel` semantics where applicable, plus
    ``user_id`` and the explicit ``mcp_config`` / ``tools_config`` /
    ``vector_config`` / ``documents`` columns asked for by the feature.
    """

    # Composite identity
    chatbot_id: uuid.UUID = Field(
        primary_key=True,
        required=False,
        default_factory=uuid.uuid4,
    )
    user_id: int = Field(primary_key=True, required=True)

    # Basic bot information
    name: str = Field(required=True)
    description: str = Field(required=False)
    avatar: str = Field(required=False)
    enabled: bool = Field(required=False, default=True)
    timezone: str = Field(required=False, default="UTC")

    # Personality
    role: str = Field(required=False, default="AI Assistant")
    goal: str = Field(
        required=False,
        default="Help users accomplish their tasks effectively.",
    )
    backstory: str = Field(
        required=False,
        default="I am an AI assistant created to help users with various tasks.",
    )
    rationale: str = Field(
        required=False,
        default="I maintain a professional tone and provide accurate, helpful information.",
    )
    capabilities: str = Field(
        required=False,
        default="I can engage in conversation, answer questions, and use tools when needed.",
    )

    # Prompt configuration (PromptBuilder)
    prompt_config: dict = Field(required=False, default_factory=dict)
    system_prompt_template: Optional[str] = Field(required=False, default=None)
    human_prompt_template: Optional[str] = Field(required=False, default=None)
    pre_instructions: List[str] = Field(required=False, default_factory=list)

    # LLM configuration
    llm: str = Field(required=False, default="google")
    model_config: dict = Field(required=False, default_factory=dict)

    # Vector store + uploaded documents.
    # The embedding model lives at vector_config['embedding_model']
    # (single source of truth — see migration
    # FEAT-fold-embedding-model-into-vector-store-config.sql).
    use_vector: bool = Field(required=False, default=False)
    vector_config: dict = Field(required=False, default_factory=dict)
    documents: List[dict] = Field(required=False, default_factory=list)
    context_search_limit: int = Field(required=False, default=10)
    context_score_threshold: float = Field(required=False, default=0.61)

    # MCP & tools — stored as ENCRYPTED TEXT.
    # Use the get_*/set_* accessors for plaintext I/O.
    mcp_config: Optional[str] = Field(required=False, default=None)
    tools_config: Optional[str] = Field(required=False, default=None)
    tools_enabled: bool = Field(required=False, default=True)
    auto_tool_detection: bool = Field(required=False, default=True)
    tool_threshold: float = Field(required=False, default=0.7)
    operation_mode: str = Field(required=False, default="adaptive")

    # Memory and conversation
    memory_type: str = Field(required=False, default="memory")
    memory_config: dict = Field(required=False, default_factory=dict)
    max_context_turns: int = Field(required=False, default=5)
    use_conversation_history: bool = Field(required=False, default=True)

    # Security and permissions
    permissions: dict = Field(required=False, default_factory=dict)

    # Metadata
    language: str = Field(required=False, default="en")
    disclaimer: Optional[str] = Field(required=False, default=None)
    created_at: datetime = Field(required=False, default=datetime.now)
    updated_at: datetime = Field(required=False, default=datetime.now)

    class Meta:
        driver = "pg"
        name = "users_bots"
        schema = PARROT_SCHEMA
        strict = True
        frozen = False

    # ------------------------------------------------------------------
    # Encrypted-field accessors
    # ------------------------------------------------------------------

    def get_mcp_config(self) -> List[dict]:
        """Return plaintext MCP server configurations."""
        value = unseal(
            self.mcp_config,
            user_id=self.user_id,
            chatbot_id=self.chatbot_id,
            field="mcp_config",
        )
        return value if isinstance(value, list) else []

    def set_mcp_config(self, value: Any) -> None:
        """Encrypt and store MCP server configurations."""
        self.mcp_config = seal(
            value or [],
            user_id=self.user_id,
            chatbot_id=self.chatbot_id,
            field="mcp_config",
        )

    def get_tools_config(self) -> List[dict]:
        """Return plaintext tool configurations."""
        value = unseal(
            self.tools_config,
            user_id=self.user_id,
            chatbot_id=self.chatbot_id,
            field="tools_config",
        )
        return value if isinstance(value, list) else []

    def set_tools_config(self, value: Any) -> None:
        """Encrypt and store tool configurations."""
        self.tools_config = seal(
            value or [],
            user_id=self.user_id,
            chatbot_id=self.chatbot_id,
            field="tools_config",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def to_bot_kwargs(self) -> dict:
        """Render a kwargs dict suitable for ``BasicBot(**kwargs)``.

        Decrypts ``mcp_config`` and ``tools_config`` so the bot constructor
        receives plaintext.
        """
        tools_config = self.get_tools_config()
        return {
            "chatbot_id": self.chatbot_id,
            "name": self.name,
            "description": self.description,
            "role": self.role,
            "goal": self.goal,
            "backstory": self.backstory,
            "rationale": self.rationale,
            "capabilities": self.capabilities,
            "system_prompt": self.system_prompt_template,
            "human_prompt": self.human_prompt_template,
            "pre_instructions": self.pre_instructions or [],
            "prompt_preset": (self.prompt_config or {}).get("preset"),
            "use_llm": self.llm,
            "model_config": self.model_config or {},
            "use_vectorstore": self.use_vector,
            "vector_store_config": self.vector_config or {},
            "context_search_limit": self.context_search_limit,
            "context_score_threshold": self.context_score_threshold,
            "tools_enabled": self.tools_enabled,
            "auto_tool_detection": self.auto_tool_detection,
            "tool_threshold": self.tool_threshold,
            "available_tools": [t.get("name") for t in tools_config if t.get("name")],
            "tools_config": tools_config,
            "mcp_servers": self.get_mcp_config(),
            "operation_mode": self.operation_mode,
            "memory_type": self.memory_type,
            "memory_config": self.memory_config or {},
            "max_context_turns": self.max_context_turns,
            "use_conversation_history": self.use_conversation_history,
            "permissions": self.permissions or {},
            "language": self.language,
            "disclaimer": self.disclaimer,
        }
