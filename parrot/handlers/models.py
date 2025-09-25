"""
Database model for Managing Chatbots and Agents.
"""
from typing import List, Union, Optional
import uuid
import time
from datetime import datetime
from pathlib import Path, PurePath
from enum import Enum
from datamodel import Field
from asyncdb.models import Model
from ..bots.basic import BasicBot


def default_embed_model():
    return {
        "model_name": "sentence-transformers/all-MiniLM-L12-v2",
        "model_type": "huggingface"
    }


def created_at(*args, **kwargs) -> int:
    return int(time.time()) * 1000


# Chatbot Model:
class BotModel(Model):
    """
    Unified Bot Model combining chatbot and agent functionality.

    This model represents any AI bot that can operate in conversational mode,
    agentic mode, or adaptive mode based on the question content.

    SQL Table Creation:

    CREATE TABLE IF NOT EXISTS navigator.ai_bots (
        chatbot_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        name VARCHAR NOT NULL,
        description VARCHAR,
        avatar TEXT,
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        timezone VARCHAR DEFAULT 'UTC',

        -- Bot personality and behavior
        role VARCHAR DEFAULT 'AI Assistant',
        goal VARCHAR NOT NULL DEFAULT 'Help users accomplish their tasks effectively.',
        backstory VARCHAR NOT NULL DEFAULT 'I am an AI assistant created to help users with various tasks.',
        rationale VARCHAR NOT NULL DEFAULT 'I maintain a professional tone and provide accurate, helpful information.',
        capabilities VARCHAR DEFAULT 'I can engage in conversation, answer questions, and use tools when needed.',

        -- Prompt configuration
        system_prompt_template TEXT,
        human_prompt_template VARCHAR,
        pre_instructions JSONB DEFAULT '[]'::JSONB,

        -- LLM configuration
        llm VARCHAR DEFAULT 'google',
        model_name VARCHAR DEFAULT 'gemini-2.0-flash-001',
        temperature FLOAT DEFAULT 0.1,
        max_tokens INTEGER DEFAULT 1024,
        top_k INTEGER DEFAULT 41,
        top_p FLOAT DEFAULT 0.9,
        model_config JSONB DEFAULT '{}'::JSONB,

        -- Tool and agent configuration
        tools_enabled BOOLEAN DEFAULT TRUE,
        auto_tool_detection BOOLEAN DEFAULT TRUE,
        tool_threshold FLOAT DEFAULT 0.7,
        available_tools JSONB DEFAULT '[]'::JSONB,
        operation_mode VARCHAR DEFAULT 'adaptive' CHECK (operation_mode IN ('conversational', 'agentic', 'adaptive')),

        -- Vector store and retrieval configuration
        use_vector_context BOOLEAN DEFAULT FALSE,
        vector_store_config JSONB DEFAULT '{}'::JSONB,
        embedding_model JSONB DEFAULT '{"model_name": "sentence-transformers/all-MiniLM-L12-v2", "model_type": "huggingface"}',
        context_search_limit INTEGER DEFAULT 10,
        context_score_threshold FLOAT DEFAULT 0.7,

        -- Memory and conversation configuration
        memory_type VARCHAR DEFAULT 'memory' CHECK (memory_type IN ('memory', 'file', 'redis')),
        memory_config JSONB DEFAULT '{}'::JSONB,
        max_context_turns INTEGER DEFAULT 5,
        use_conversation_history BOOLEAN DEFAULT TRUE,

        -- Security and permissions
        permissions JSONB DEFAULT '{}'::JSONB,

        --- knowledge base:
        use_kb BOOLEAN DEFAULT FALSE,
        kb JSONB DEFAULT '[]'::JSONB,

        -- Metadata
        language VARCHAR DEFAULT 'en',
        disclaimer TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        created_by INTEGER,
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    -- Indexes for better performance
    CREATE INDEX IF NOT EXISTS idx_ai_bots_name ON navigator.ai_bots(name);
    CREATE INDEX IF NOT EXISTS idx_ai_bots_enabled ON navigator.ai_bots(enabled);
    CREATE INDEX IF NOT EXISTS idx_ai_bots_operation_mode ON navigator.ai_bots(operation_mode);
    CREATE INDEX IF NOT EXISTS idx_ai_bots_tools_enabled ON navigator.ai_bots(tools_enabled);

    -- Unique constraint on name
    ALTER TABLE navigator.ai_bots
    ADD CONSTRAINT unq_navigator_ai_bots_name UNIQUE (name);
    """

    # Primary key
    chatbot_id: uuid.UUID = Field(
        primary_key=True,
        required=False,
        default_factory=uuid.uuid4,
        ui_help="The bot’s unique identifier."
    )

    # Basic bot information
    name: str = Field(required=True)
    description: str = Field(required=False)
    avatar: str = Field(required=False)
    enabled: bool = Field(required=True, default=True)
    timezone: str = Field(required=False, max=75, default="UTC")

    # Bot personality and behavior
    role: str = Field(
        default="AI Assistant",
        ui_help="The bot’s function or identity from the user’s perspective.",
        required=False
    )
    goal: str = Field(
        default="Help users accomplish their tasks effectively.",
        required=True,
        ui_help="primary outcome the bot is designed to achieve. Keep it clear and specific. "
    )
    backstory: str = Field(
        default="I am an AI assistant created to help users with various tasks.",
        required=True,
        ui_help="Outlines the bot’s knowledge base, data sources, restrictions, and configuration rules (both technical and non-technical). Also, what is prohibited or undesirable behavior for the bot. "
    )
    rationale: str = Field(
        default="I maintain a professional tone and provide accurate, helpful information.",
        required=True,
        ui_help="Defines how the bot behaves in conversation — its tone, style, error handling, and hot it deals with off-topic inputs."
    )
    capabilities: str = Field(
        default="I can engage in conversation, answer questions, and use tools when needed.",
        required=False,
        ui_help="The bot’s capabilities and features."
    )

    # Prompt configuration
    system_prompt_template: Optional[str] = Field(
        default=None,
        required=False,
        ui_help="The bot’s system prompt template, which defines its role and behavior."
    )
    human_prompt_template: Optional[str] = Field(
        default=None,
        required=False
    )
    pre_instructions: List[str] = Field(
        default_factory=list,
        required=False,
        ui_help="Guidelines for consistent behavior and proper use of context. These ensure the bot uses only the predefined context to generate responses."
    )

    # LLM configuration
    llm: str = Field(default='google', required=False, ui_help="Large Language Model powering the bot. ")
    model_name: str = Field(default='gemini-2.5-flash', required=False, ui_help="Exact version or identifier of the model being used.")
    temperature: float = Field(default=0.1, required=False, ui_help="Controls how creative or constrained the bot’s responses are. Lower values (e.g., 0.1) keep answers close to the context. Higher values increase variation and creativity.")
    max_tokens: int = Field(default=1024, required=False, ui_help="The bot’s maximum number of tokens.")
    top_k: int = Field(default=41, required=False, ui_help="The bot’s top-k parameter.")
    top_p: float = Field(default=0.9, required=False, ui_help="The bot’s top-p parameter.")
    model_config: dict = Field(default_factory=dict, required=False, ui_help="The bot’s model configuration.")

    # Tool and agent configuration
    tools_enabled: bool = Field(default=True, required=False, ui_help="Whether the bot’s tools are enabled or not.")
    auto_tool_detection: bool = Field(default=True, required=False, ui_help="Whether the bot’s auto tool detection is enabled or not.")
    tool_threshold: float = Field(
        default=0.7,
        required=False,
        ui_help="The bot’s tool threshold."
    )
    tools: List[str] = Field(default_factory=list, required=False, ui_help="The bot’s tools.")
    operation_mode: str = Field(default='adaptive', required=False, ui_help="The bot’s operation mode.")  # 'conversational', 'agentic', 'adaptive'

    # Knowledge Base
    use_kb: bool = Field(
        default=False,
        required=False,
        ui_help="Whether the bot’s knowledge base is enabled or not."
    )
    kb: List[dict] = Field(
        default_factory=list,
        required=False,
        ui_help="The bot’s knowledge base facts."
    )
    custom_kbs: List[str] = Field(nullable=True, default=None)
    # Vector store and retrieval configuration
    use_vector: bool = Field(
        default=False,
        required=False,
        ui_help="Whether the bot’s vector store is enabled or not."
    )
    vector_store_config: dict = Field(
        default_factory=dict,
        required=False,
        ui_help="The bot’s vector store configuration."
    )
    embedding_model: dict = Field(
        default=default_embed_model,
        required=False,
        ui_help="The bot’s embedding model."
    )
    context_search_limit: int = Field(
        default=10,
        required=False,
        ui_help="The bot’s context search limit."
    )
    context_score_threshold: float = Field(
        default=0.7,
        required=False,
        ui_help="The bot’s context score threshold."
    )

    # Memory and conversation configuration
    memory_type: str = Field(
        default='memory',
        required=False,
        ui_help="The bot’s memory type."
    )  # 'memory', 'file', 'redis'
    memory_config: dict = Field(
        default_factory=dict,
        required=False,
        ui_help="The bot’s memory configuration."
    )
    max_context_turns: int = Field(
        default=5, required=False, ui_help="The bot’s maximum context turns."
    )
    use_conversation_history: bool = Field(
        default=True,
        required=False,
        ui_help="Whether the bot’s conversation history is enabled or not."
    )
    # advanced: Bot Class
    bot_class: Optional[str] = Field(
        required=False,
        default='BasicBot',
        ui_help="The bot’s class path, e.g., 'parrot.bots.unified.UnifiedBot'."
    )

    # Security and permissions
    permissions: dict = Field(
        required=False,
        default_factory=dict,
        ui_help="The bot’s user and group permissions."
    )

    # Metadata
    language: str = Field(
        default='en',
        required=False,
        ui_help="The bot’s language."
    )
    disclaimer: Optional[str] = Field(
        required=False,
        ui_help="Message shown to users before interacting with the bot. Use it for usage tips, limitations, or important notices."
    )
    created_at: datetime = Field(
        required=False,
        default=datetime.now,
        ui_help="The bot’s creation timestamp."
    )
    created_by: Optional[int] = Field(
        required=False,
        ui_help="The bot’s creator."
    )
    updated_at: datetime = Field(
        required=False,
        default=datetime.now,
        ui_help="The bot’s last update timestamp."
    )

    def __post_init__(self) -> None:
        super(BotModel, self).__post_init__()

        # Validate operation_mode
        valid_modes = ['conversational', 'agentic', 'adaptive']
        if self.operation_mode not in valid_modes:
            raise ValueError(f"operation_mode must be one of {valid_modes}")

        # Validate memory_type
        valid_memory_types = ['memory', 'file', 'redis']
        if self.memory_type not in valid_memory_types:
            raise ValueError(f"memory_type must be one of {valid_memory_types}")

        # Ensure tool_threshold is between 0 and 1
        if not 0 <= self.tool_threshold <= 1:
            raise ValueError("tool_threshold must be between 0 and 1")

    def to_bot_config(self) -> dict:
        """Convert model instance to bot configuration dictionary."""
        return {
            'name': self.name,
            'description': self.description,
            'role': self.role,
            'goal': self.goal,
            'backstory': self.backstory,
            'rationale': self.rationale,
            'capabilities': self.capabilities,
            'system_prompt': self.system_prompt_template,
            'human_prompt': self.human_prompt_template,
            'pre_instructions': self.pre_instructions,
            'llm': self.llm,
            'model': self.model_name,
            'temperature': self.temperature,
            'max_tokens': self.max_tokens,
            'top_k': self.top_k,
            'top_p': self.top_p,
            'model_config': self.model_config,
            'tools_enabled': self.tools_enabled,
            'auto_tool_detection': self.auto_tool_detection,
            'tool_threshold': self.tool_threshold,
            'tools': self.tools,
            'operation_mode': self.operation_mode,
            'use_vector': self.use_vector,
            'vector_store_config': self.vector_store_config,
            'embedding_model': self.embedding_model,
            'context_search_limit': self.context_search_limit,
            'context_score_threshold': self.context_score_threshold,
            'memory_type': self.memory_type,
            'memory_config': self.memory_config,
            'max_context_turns': self.max_context_turns,
            'use_conversation_history': self.use_conversation_history,
            'permissions': self.permissions,
            'language': self.language,
            'disclaimer': self.disclaimer,
        }

    def is_agent_enabled(self) -> bool:
        """Check if this bot has agent capabilities enabled."""
        return self.tools_enabled and len(self.tools) > 0

    def get_available_tool_names(self) -> List[str]:
        """Get list of available tool names."""
        return self.tools if self.tools else []

    def add_tool(self, tool_name: str) -> None:
        """Add a tool to the available tools list."""
        if tool_name not in self.tools:
            self.tools.append(tool_name)
            self.updated_at = datetime.now()

    def remove_tool(self, tool_name: str) -> bool:
        """Remove a tool from the available tools list."""
        if tool_name in self.tools:
            self.tools.remove(tool_name)
            self.updated_at = datetime.now()
            return True
        return False

    def enable_vector_store(self, config: dict) -> None:
        """Enable vector store with given configuration."""
        self.use_vector = True
        self.vector_store_config = config
        self.updated_at = datetime.now()

    def disable_vector_store(self) -> None:
        """Disable vector store."""
        self.use_vector = False
        self.vector_store_config = {}
        self.updated_at = datetime.now()

    class Meta:
        """Meta Bot Model."""
        driver = 'pg'
        name = "ai_bots"
        schema = "navigator"
        strict = True
        frozen = False


class ChatbotUsage(Model):
    """ChatbotUsage.

    Saving information about Chatbot Usage.

    -- ScyllaDB CREATE TABLE Syntax --
    CREATE TABLE IF NOT EXISTS navigator.chatbots_usage (
        chatbot_id TEXT,
        user_id SMALLINT,
        sid TEXT,
        source_path TEXT,
        platform TEXT,
        origin inet,
        user_agent TEXT,
        question TEXT,
        response TEXT,
        used_at BIGINT,
        at TEXT,
        PRIMARY KEY ((chatbot_id, sid, at), used_at)
    ) WITH CLUSTERING ORDER BY (used_at DESC)
    AND default_time_to_live = 10368000;

    """
    chatbot_id: uuid.UUID = Field(primary_key=True, required=False)
    user_id: int = Field(primary_key=True, required=False)
    sid: uuid.UUID = Field(primary_key=True, required=False, default=uuid.uuid4)
    source_path: str = Field(required=False, default='web')
    platform: str = Field(required=False, default='web')
    origin: str = Field(required=False)
    user_agent: str = Field(required=False)
    question: str = Field(required=False)
    response: str = Field(required=False)
    used_at: int = Field(required=False, default=created_at)
    event_timestamp: datetime = Field(required=False, default=datetime.now)
    _at: str = Field(primary_key=True, required=False)

    class Meta:
        """Meta Chatbot."""
        driver = 'bigquery'
        name = "chatbots_usage"
        schema = "navigator"
        ttl = 10368000  # 120 days in seconds
        strict = True
        frozen = False

    def __post_init__(self) -> None:
        if not self._at:
            # Generate a unique session id
            self._at = f'{self.sid}:{self.used_at}'
        super(ChatbotUsage, self).__post_init__()


class FeedbackType(Enum):
    """FeedbackType."""
    # Good Feedback
    GOOD_COMPLETE = "Completeness"
    GOOD_CORRECT = "Correct"
    GOOD_FOLLOW = "Follow the instructions"
    GOOD_UNDERSTAND = "Understandable"
    GOOD_USEFUL = "very useful"
    GOOD_OTHER = "Please Explain"
    # Bad Feedback
    BAD_DONTLIKE = "Don't like the style"
    BAD_INCORRECT = "Incorrect"
    BAD_NOTFOLLOW = "Didn't follow the instructions"
    BAD_LAZY = "Being lazy"
    BAD_NOTUSEFUL = "Not useful"
    BAD_UNSAFE = "Unsafe or problematic"
    BAD_OTHER = "Other"

    @classmethod
    def list_feedback(cls, feedback_category):
        """Return a list of feedback types based on the given category (Good or Bad)."""
        prefix = feedback_category.upper() + "_"
        return [feedback for feedback in cls if feedback.name.startswith(prefix)]

class ChatbotFeedback(Model):
    """ChatbotFeedback.

    Saving information about Chatbot Feedback.

    -- ScyllaDB CREATE TABLE Syntax --
    CREATE TABLE IF NOT EXISTS navigator.chatbots_feedback (
        chatbot_id UUID,
        user_id INT,
        sid UUID,
        at TEXT,
        rating TINYINT,
        like BOOLEAN,
        dislike BOOLEAN,
        feedback_type TEXT,
        feedback TEXT,
        created_at BIGINT,
        PRIMARY KEY ((chatbot_id, user_id, sid), created_at)
    ) WITH CLUSTERING ORDER BY (created_at DESC)
    AND default_time_to_live = 7776000;

    """
    chatbot_id: uuid.UUID = Field(primary_key=True, required=False)
    user_id: int = Field(required=False)
    sid: uuid.UUID = Field(primary_key=True, required=False)
    _at: str = Field(primary_key=True, required=False)
    # feedback information:
    rating: int = Field(required=False, default=0)
    _like: bool = Field(required=False, default=False)
    _dislike: bool = Field(required=False, default=False)
    feedback_type: FeedbackType = Field(required=False)
    feedback: str = Field(required=False)
    created_at: int = Field(required=False, default=created_at)
    expiration_timestamp: datetime = Field(required=False, default=datetime.now)

    class Meta:
        """Meta Chatbot."""
        driver = 'bigquery'
        name = "chatbots_feedback"
        schema = "navigator"
        ttl = 7776000  # 3 months in seconds
        strict = True
        frozen = False

    def __post_init__(self) -> None:
        if not self._at:
            # Generate a unique session id
            if not self.created_at:
                self.created_at = created_at()
            self._at = f'{self.sid}:{self.created_at}'
        super(ChatbotFeedback, self).__post_init__()


## Prompt Library:

class PromptCategory(Enum):
    """
    Prompt Category.

    Categorization of Prompts, as "tech",
    "tech-or-explain", "idea", "explain", "action", "command", "other".
    """
    TECH = "tech"
    TECH_OR_EXPLAIN = "tech-or-explain"
    IDEA = "idea"
    EXPLAIN = "explain"
    ACTION = "action"
    COMMAND = "command"
    OTHER = "other"

class PromptLibrary(Model):
    """PromptLibrary.

    Saving information about Prompt Library.

    -- PostgreSQL CREATE TABLE Syntax --
    CREATE TABLE IF NOT EXISTS navigator.prompt_library (
            prompt_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            chatbot_id UUID,
            title varchar,
            query varchar,
            description TEXT,
            prompt_category varchar,
            prompt_tags varchar[],
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            created_by INTEGER,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
    );
    """
    prompt_id: uuid.UUID = Field(primary_key=True, required=False, default_factory=uuid.uuid4)
    chatbot_id: uuid.UUID = Field(required=True)
    title: str = Field(required=True)
    query: str = Field(required=True)
    description: str = Field(required=False)
    prompt_category: str = Field(required=False, default=PromptCategory.OTHER)
    prompt_tags: list = Field(required=False, default_factory=list)
    created_at: datetime = Field(required=False, default=datetime.now)
    created_by: int = Field(required=False)
    updated_at: datetime = Field(required=False, default=datetime.now)

    class Meta:
        """Meta Prompt Library."""
        driver = 'pg'
        name = "prompt_library"
        schema = "navigator"
        strict = True
        frozen = False


    def __post_init__(self) -> None:
        super(PromptLibrary, self).__post_init__()


# Factory function to create bot instances from database records
def create_bot(bot_model: BotModel, bot_class=None):
    """
    Create a BasicBot instance from a BotModel database record.

    Args:
        bot_model: BotModel instance from database
        bot_class: Optional bot class to use (defaults to UnifiedBot)

    Returns:
        Configured bot instance
    """
    if bot_class is None:
        bot_class = BasicBot

    # Convert model to configuration
    config = bot_model.to_bot_config()

    # Create and return bot instance
    bot = bot_class(**config)
    bot.model_id = bot_model.chatbot_id

    return bot
