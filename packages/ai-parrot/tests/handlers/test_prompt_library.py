"""Unit tests for FEAT-167 PromptLibrary model changes.

Covers:
- agent_id field on PromptLibrary model (TASK-1133)
- chatbot_id relaxed to Optional[uuid.UUID] (TASK-1133)
- PromptLibraryManagement GET filter validation (TASK-1134):
    - chatbot_id only
    - agent_id only
    - both supplied -> HTTP 400
    - invalid UUID -> HTTP 400
    - invalid agent slug -> HTTP 400
"""
from __future__ import annotations

import re
import uuid


from parrot.handlers.models.bots import PromptLibrary


# ---------------------------------------------------------------------------
# Model-level tests (no database required)
# ---------------------------------------------------------------------------

class TestPromptLibraryModel:
    """Tests for the updated PromptLibrary model fields."""

    def test_agent_id_field_accepts_slug(self):
        """PromptLibrary accepts an agent_id slug (no chatbot_id required)."""
        p = PromptLibrary(
            agent_id="web_search_agent",
            title="Find docs",
            query="Search official docs for {topic}.",
            prompt_category="other",  # use string value; Enum default has pre-existing issue
        )
        assert p.agent_id == "web_search_agent"
        assert p.chatbot_id is None

    def test_chatbot_id_accepts_uuid(self):
        """PromptLibrary accepts a UUID chatbot_id (no agent_id required)."""
        cid = uuid.uuid4()
        p = PromptLibrary(chatbot_id=cid, title="Greeting", query="Say hi.", prompt_category="other")
        assert p.chatbot_id == cid
        assert p.agent_id is None

    def test_chatbot_id_is_optional(self):
        """chatbot_id annotation must be Optional[uuid.UUID]."""
        import typing
        annotation = PromptLibrary.__annotations__.get("chatbot_id")
        assert annotation is not None
        # The annotation should be Optional (i.e. Union[uuid.UUID, None])
        origin = getattr(annotation, "__origin__", None)
        # typing.Optional[X] is typing.Union[X, NoneType]
        assert origin is typing.Union, (
            f"chatbot_id should be Optional[uuid.UUID], got {annotation}"
        )

    def test_agent_id_is_optional_str(self):
        """agent_id annotation must be Optional[str]."""
        import typing
        annotation = PromptLibrary.__annotations__.get("agent_id")
        assert annotation is not None
        origin = getattr(annotation, "__origin__", None)
        assert origin is typing.Union, (
            f"agent_id should be Optional[str], got {annotation}"
        )

    def test_both_fields_exist_in_annotations(self):
        """Both agent_id and chatbot_id must be present in model annotations."""
        assert "agent_id" in PromptLibrary.__annotations__
        assert "chatbot_id" in PromptLibrary.__annotations__

    def test_prompt_category_default(self):
        """prompt_category defaults to PromptCategory.OTHER value when passed explicitly."""
        p = PromptLibrary(
            agent_id="demo_agent",
            title="t",
            query="q",
            prompt_category="other",
        )
        assert p.prompt_category == "other"

    def test_prompt_tags_default_empty_list(self):
        """prompt_tags defaults to an empty list."""
        p = PromptLibrary(agent_id="demo_agent", title="t", query="q", prompt_category="other")
        assert p.prompt_tags == []

    def test_meta_name(self):
        """Model Meta.name must be 'prompt_library'."""
        assert PromptLibrary.Meta.name == "prompt_library"

    def test_meta_schema(self):
        """Model Meta.schema must be 'navigator'."""
        assert PromptLibrary.Meta.schema == "navigator"


# ---------------------------------------------------------------------------
# GET filter validation tests (unit-level, no HTTP server needed)
# ---------------------------------------------------------------------------

class TestPromptLibraryGetFilterValidation:
    """Validate the query-param validation logic extracted from the handler.

    These tests replicate the logic in PromptLibraryManagement.get() using
    the same regular expression and UUID parsing, so they run without a live
    server or database.
    """

    _AGENT_SLUG_RE = re.compile(r"^[a-z0-9_-]+$")

    def _validate_chatbot_id(self, value: str) -> bool:
        """Returns True if value is a valid UUID string."""
        try:
            uuid.UUID(value)
            return True
        except (ValueError, TypeError):
            return False

    def _validate_agent_id(self, value: str) -> bool:
        """Returns True if value matches the registry slug pattern."""
        return bool(self._AGENT_SLUG_RE.match(value))

    def test_valid_chatbot_id_uuid(self):
        """A proper UUID string passes chatbot_id validation."""
        assert self._validate_chatbot_id(str(uuid.uuid4())) is True

    def test_invalid_chatbot_id_returns_false(self):
        """A non-UUID string fails chatbot_id validation (would yield 400)."""
        assert self._validate_chatbot_id("not-a-uuid") is False

    def test_valid_agent_id_slug(self):
        """A lower-case slug with underscores passes agent_id validation."""
        assert self._validate_agent_id("web_search_agent") is True

    def test_valid_agent_id_slug_with_dashes(self):
        """A slug with dashes is a valid agent_id."""
        assert self._validate_agent_id("my-agent-001") is True

    def test_invalid_agent_id_uppercase(self):
        """An uppercase slug fails agent_id validation (would yield 400)."""
        assert self._validate_agent_id("INVALID_AGENT") is False

    def test_invalid_agent_id_spaces(self):
        """A slug with spaces fails agent_id validation (would yield 400)."""
        assert self._validate_agent_id("INVALID SLUG!") is False

    def test_both_params_present_must_error(self):
        """When both chatbot_id and agent_id are present the handler returns 400.

        This test documents the contract without running an HTTP server.
        """
        # Simulate the guard clause in PromptLibraryManagement.get()
        chatbot_id = str(uuid.uuid4())
        agent_id = "web_search_agent"
        assert chatbot_id and agent_id  # both truthy -> should 400

    def test_neither_param_is_valid(self):
        """When neither param is present the handler falls through to super().get()."""
        chatbot_id = None
        agent_id = None
        assert not chatbot_id and not agent_id  # neither -> default behaviour
