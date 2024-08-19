from typing import Union, Optional
import uuid
import time
from datetime import datetime
from pathlib import Path, PurePath
from enum import Enum
from langchain_core.agents import AgentAction

from datamodel import BaseModel, Field
from datamodel.types import Text  # pylint: disable=no-name-in-module
from asyncdb.models import Model

def created_at(*args, **kwargs) -> int:
    return int(time.time()) * 1000


class AgentResponse(BaseModel):
    """AgentResponse.
    dict_keys(
        ['input', 'chat_history', 'output', 'intermediate_steps']
    )

    Response from Chatbots.
    """
    question: str = Field(required=False)
    input: str = Field(required=False)
    output: str = Field(required=False)
    response: str = Field(required=False)
    intermediate_steps: list = Field(default_factory=list)
    chat_history: list = Field(repr=True, default_factory=list)
    source_documents: list = Field(required=False, default_factory=list)

    def __post_init__(self) -> None:
        if self.intermediate_steps:
            steps = []
            for item, result in self.intermediate_steps:
                if isinstance(item, AgentAction):
                    # convert into dictionary:
                    steps.append(
                        {
                            "tool": item.tool,
                            "tool_input": item.tool_input,
                            "result": result,
                            "log": str(item.log)
                        }
                    )
            if steps:
                self.intermediate_steps = steps


class ChatResponse(BaseModel):
    """ChatResponse.
    dict_keys(
        ['question', 'chat_history', 'answer', 'source_documents', 'generated_question']
    )

    Response from Chatbots.
    """
    query: str = Field(required=False)
    result: str = Field(required=False)
    question: str = Field(required=False)
    generated_question: str = Field(required=False)
    answer: str = Field(required=False)
    response: str = Field(required=False)
    chat_history: list = Field(repr=True, default_factory=list)
    source_documents: list = Field(required=False, default_factory=list)
    documents: dict = Field(required=False, default_factory=dict)
    sid: uuid.UUID = Field(primary_key=True, required=False, default=uuid.uuid4)
    at: int = Field(default=created_at)

    def __post_init__(self) -> None:
        if self.result and not self.answer:
            self.answer = self.result
        if self.question and not self.generated_question:
            self.generated_question = self.question
        return super().__post_init__()


# Chatbot Model:
class ChatbotModel(Model):
    """Chatbot.
    CREATE TABLE IF NOT EXISTS navigator.chatbots (
        chatbot_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        name VARCHAR NOT NULL DEFAULT 'Nav',
        description VARCHAR,
        config_file VARCHAR DEFAULT 'config.toml',
        company_information JSONB DEFAULT '{}'::JSONB,
        contact_information VARCHAR,
        contact_form VARCHAR,
        contact_email VARCHAR,
        company_website VARCHAR,
        avatar TEXT,
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        timezone VARCHAR DEFAULT 'UTC',
        attributes JSONB DEFAULT '{}'::JSONB,
        role VARCHAR DEFAULT 'a Human Resources Assistant',
        goal VARCHAR NOT NULL DEFAULT 'Bring useful information to Users.',
        backstory VARCHAR NOT NULL DEFAULT 'I was created by a team of developers to assist with users tasks.',
        rationale VARCHAR NOT NULL DEFAULT 'Remember to maintain a professional tone. Please provide accurate and relevant information.',
        language VARCHAR DEFAULT 'en',
        template_prompt VARCHAR,
        pre_instructions JSONB DEFAULT '[]'::JSONB,
        llm VARCHAR DEFAULT 'VertexLLM',
        model_name VARCHAR DEFAULT 'gemini-pro',
        model_config JSONB DEFAULT '{}'::JSONB,
        embedding_name VARCHAR DEFAULT 'thenlper/gte-base',
        tokenizer VARCHAR DEFAULT 'thenlper/gte-base',
        summarize_model VARCHAR DEFAULT 'facebook/bart-large-cnn',
        classification_model VARCHAR DEFAULT 'facebook/bart-large-cnn',
        database JSONB DEFAULT '{"vector_database": "MilvusStore", "database": "TROC", "collection_name": "troc_information"}'::JSONB,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        created_by INTEGER,
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );
    """
    chatbot_id: uuid.UUID = Field(primary_key=True, required=False, default_factory=uuid.uuid4)
    name: str = Field(default='Nav', required=True)
    description: str = Field(default='Nav Chatbot', required=False)
    config_file: str = Field(default='config.toml', required=False)
    custom_class: str = Field(required=False)
    company_information: dict = Field(default_factory=dict, required=False)
    avatar: Text
    enabled: bool = Field(required=True, default=True)
    timezone: str = Field(required=False, max=75, default="UTC", repr=False)
    attributes: Optional[dict] = Field(required=False, default_factory=dict)
    # Chatbot Configuration
    role: str = Field(
        default="a Human Resources Assistant",
        required=False
    )
    goal: str = Field(
        default="Bring useful information to Users.",
        required=True
    )
    backstory: str = Field(
        default="I was created by a team of developers to assist with users tasks.",
        required=True
    )
    rationale: str = Field(
        default=(
            "Remember to maintain a professional tone."
            " Please provide accurate and relevant information."
        ),
        required=True
    )
    language: str = Field(default='en', required=False)
    template_prompt: Union[str, PurePath] = Field(
        default=None,
        required=False
    )
    pre_instructions: list = Field(
        default_factory=list,
        required=False
    )
    # Model Configuration:
    llm: str = Field(default='VertexLLM', required=False)
    llm_config: dict = Field(default_factory=dict, required=False)
    embedding_name: str = Field(default="thenlper/gte-base", required=False)
    tokenizer: str = Field(default='thenlper/gte-base', required=False)
    summarize_model: str = Field(default="facebook/bart-large-cnn", required=False)
    classification_model: str = Field(default="facebook/bart-large-cnn", required=False)
    # Database Configuration
    database: dict = Field(default='TROC', required=False, default_factory=dict)
    # Bot/Agent type
    bot_type: str = Field(default='chatbot', required=False)
    # When created
    created_at: datetime = Field(required=False, default=datetime.now())
    created_by: int = Field(required=False)
    updated_at: datetime = Field(required=False, default=datetime.now())

    def __post_init__(self) -> None:
        super(ChatbotModel, self).__post_init__()
        if isinstance(self.config_file, str):
            self.config_file = Path(self.config_file).resolve()
        if isinstance(self.config_file, PurePath):
            self.config_file = str(self.config_file)

    class Meta:
        """Meta Chatbot."""
        driver = 'pg'
        name = "chatbots"
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

    Categorization of Prompts, as "tech", "tech-or-explain", "idea", "explain", "action", "command", "other".
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
