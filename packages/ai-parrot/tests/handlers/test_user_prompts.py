"""Unit tests for FEAT-167 UserPrompts model and UserPromptsManagement.

Covers:
- UserPrompts model construction (TASK-1135):
    - chatbot_id accepts UUID strings
    - chatbot_id accepts registry agent slugs
    - is_public defaults to False
    - Meta.name and Meta.schema are correct
    - prompt_tags defaults to []
    - prompt_category defaults to PromptCategory.OTHER
- UserPromptsManagement class existence and shape (TASK-1137)
- user_id enforcement contract (documented, no live server required)
"""
from __future__ import annotations

import uuid


from parrot.handlers.models.users_prompts import UserPrompts
from parrot.handlers.models.bots import PromptCategory
from parrot.conf import PARROT_SCHEMA

# PYTHONPATH must include the worktree src for these imports to pick up
# the in-progress implementation.  Tests are designed to run with:
# PYTHONPATH=<worktree>/packages/ai-parrot/src pytest ...


# ---------------------------------------------------------------------------
# Model-level tests (no database required)
# ---------------------------------------------------------------------------

class TestUserPromptsModel:
    """Tests for the UserPrompts model fields and defaults."""

    def test_chatbot_id_accepts_uuid_string(self):
        """UserPrompts accepts a UUID string as chatbot_id."""
        cid = str(uuid.uuid4())
        p = UserPrompts(user_id=1, chatbot_id=cid, title="t", query="q")
        assert p.chatbot_id == cid

    def test_chatbot_id_accepts_slug(self):
        """UserPrompts accepts a registry agent slug as chatbot_id."""
        p = UserPrompts(
            user_id=1,
            chatbot_id="web_search_agent",
            title="My search",
            query="Search {topic}.",
        )
        assert p.chatbot_id == "web_search_agent"

    def test_is_public_defaults_false(self):
        """is_public must default to False."""
        p = UserPrompts(user_id=1, chatbot_id="x", title="t", query="q")
        assert p.is_public is False

    def test_is_public_can_be_true(self):
        """is_public can be explicitly set to True."""
        p = UserPrompts(user_id=1, chatbot_id="x", title="t", query="q", is_public=True)
        assert p.is_public is True

    def test_prompt_tags_default_empty_list(self):
        """prompt_tags must default to an empty list."""
        p = UserPrompts(user_id=1, chatbot_id="x", title="t", query="q")
        assert p.prompt_tags == []

    def test_prompt_category_default(self):
        """prompt_category must default to the string value of PromptCategory.OTHER."""
        p = UserPrompts(user_id=1, chatbot_id="x", title="t", query="q")
        assert p.prompt_category == PromptCategory.OTHER.value

    def test_user_id_is_required(self):
        """user_id annotation must be int (required)."""
        annotation = UserPrompts.__annotations__.get("user_id")
        assert annotation is int

    def test_chatbot_id_is_str(self):
        """chatbot_id annotation must be str (VARCHAR, not UUID)."""
        annotation = UserPrompts.__annotations__.get("chatbot_id")
        assert annotation is str, (
            f"chatbot_id should be str, got {annotation}"
        )

    def test_is_public_is_bool(self):
        """is_public annotation must be bool."""
        annotation = UserPrompts.__annotations__.get("is_public")
        assert annotation is bool

    def test_meta_name(self):
        """Model Meta.name must be 'users_prompts'."""
        assert UserPrompts.Meta.name == "users_prompts"

    def test_meta_schema_equals_parrot_schema(self):
        """Model Meta.schema must equal PARROT_SCHEMA constant."""
        assert UserPrompts.Meta.schema == PARROT_SCHEMA

    def test_meta_schema_is_navigator(self):
        """PARROT_SCHEMA resolves to 'navigator' in this environment."""
        assert UserPrompts.Meta.schema == "navigator"

    def test_all_required_fields_present(self):
        """All expected field names must appear in model annotations."""
        expected_fields = {
            "prompt_id", "user_id", "chatbot_id", "title", "query",
            "description", "prompt_category", "prompt_tags", "is_public",
            "created_at", "created_by", "updated_at",
        }
        actual_fields = set(UserPrompts.__annotations__.keys())
        missing = expected_fields - actual_fields
        assert not missing, f"Missing fields in UserPrompts: {missing}"

    def test_description_optional_none(self):
        """description is Optional and defaults to None."""
        p = UserPrompts(user_id=1, chatbot_id="x", title="t", query="q")
        assert p.description is None

    def test_prompt_id_is_uuid(self):
        """prompt_id is auto-generated as a UUID."""
        p = UserPrompts(user_id=1, chatbot_id="x", title="t", query="q")
        assert isinstance(p.prompt_id, uuid.UUID)

    def test_two_instances_have_different_prompt_ids(self):
        """Each instance gets a unique prompt_id from default_factory."""
        p1 = UserPrompts(user_id=1, chatbot_id="x", title="t1", query="q")
        p2 = UserPrompts(user_id=1, chatbot_id="x", title="t2", query="q")
        assert p1.prompt_id != p2.prompt_id


# ---------------------------------------------------------------------------
# UserPromptsManagement class shape tests (no HTTP server required)
# ---------------------------------------------------------------------------

class TestUserPromptsManagementShape:
    """Verify UserPromptsManagement class attributes match the spec."""

    def test_class_exists(self):
        """UserPromptsManagement must be importable from parrot.handlers.bots."""
        from parrot.handlers.bots import UserPromptsManagement  # noqa: F401

    def test_model_attribute(self):
        """UserPromptsManagement.model must be UserPrompts."""
        from parrot.handlers.bots import UserPromptsManagement
        assert UserPromptsManagement.model is UserPrompts

    def test_pk_attribute(self):
        """UserPromptsManagement.pk must be 'prompt_id'."""
        from parrot.handlers.bots import UserPromptsManagement
        assert UserPromptsManagement.pk == "prompt_id"

    def test_path_attribute(self):
        """UserPromptsManagement.path must be '/api/v1/agents/user_prompts'."""
        from parrot.handlers.bots import UserPromptsManagement
        assert UserPromptsManagement.path == "/api/v1/agents/user_prompts"

    def test_name_attribute(self):
        """UserPromptsManagement.name must be 'User Prompts Management'."""
        from parrot.handlers.bots import UserPromptsManagement
        assert UserPromptsManagement.name == "User Prompts Management"

    def test_has_set_user_id(self):
        """UserPromptsManagement must define _set_user_id."""
        from parrot.handlers.bots import UserPromptsManagement
        assert callable(getattr(UserPromptsManagement, "_set_user_id", None))

    def test_has_set_created_by(self):
        """UserPromptsManagement must define _set_created_by."""
        from parrot.handlers.bots import UserPromptsManagement
        assert callable(getattr(UserPromptsManagement, "_set_created_by", None))

    def test_has_get_override(self):
        """UserPromptsManagement must define a get() override."""
        from parrot.handlers.bots import UserPromptsManagement
        assert callable(getattr(UserPromptsManagement, "get", None))


# ---------------------------------------------------------------------------
# Export surface tests
# ---------------------------------------------------------------------------

class TestExportSurface:
    """Verify both UserPrompts and UserPromptsManagement are properly exported."""

    def test_user_prompts_exported_from_models(self):
        """UserPrompts must be importable from parrot.handlers.models."""
        from parrot.handlers.models import UserPrompts as _UP  # noqa: F401

    def test_user_prompts_in_all(self):
        """UserPrompts must appear in parrot.handlers.models.__all__."""
        import parrot.handlers.models as _m
        assert "UserPrompts" in _m.__all__
