"""Database model for per-user prompts (``navigator.users_prompts``).

Mirrors :class:`parrot.handlers.models.bots.PromptLibrary` but is keyed
by ``(user_id, prompt_id)`` so each user owns their own private prompt
collection. ``chatbot_id`` is typed as a plain string so it can hold
either a DB-backed chatbot UUID (stringified) or a registry agent slug
(e.g. ``"web_search_agent"``).
"""
import uuid
from datetime import datetime
from typing import Optional

from datamodel import Field
from asyncdb.models import Model

from parrot.conf import PARROT_SCHEMA
from .bots import PromptCategory


class UserPrompts(Model):
    """Per-user prompt definition.

    All fields mirror :class:`PromptLibrary` semantics where applicable,
    plus ``user_id`` and the future-promotion flag ``is_public``.
    """

    # Composite identity
    prompt_id: uuid.UUID = Field(
        primary_key=True,
        required=False,
        default_factory=uuid.uuid4,
    )
    user_id: int = Field(primary_key=True, required=True)

    # Bot / agent binding — VARCHAR so both UUIDs and agent slugs fit.
    chatbot_id: str = Field(required=True)

    # Prompt body
    title: str = Field(required=True)
    query: str = Field(required=True)
    description: Optional[str] = Field(required=False, default=None)
    prompt_category: str = Field(
        required=False,
        default=PromptCategory.OTHER.value,
    )
    prompt_tags: list = Field(required=False, default_factory=list)

    # Reserved for future "promote to public" workflow
    is_public: bool = Field(required=False, default=False)

    # Metadata
    created_at: datetime = Field(required=False, default=datetime.now)
    created_by: Optional[int] = Field(required=False, default=None)
    updated_at: datetime = Field(required=False, default=datetime.now)

    class Meta:
        """Meta UserPrompts."""

        driver = "pg"
        name = "users_prompts"
        schema = PARROT_SCHEMA
        strict = True
        frozen = False

    def __post_init__(self) -> None:
        super(UserPrompts, self).__post_init__()
