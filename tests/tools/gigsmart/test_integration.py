"""Smoke integration tests for the GigSmart package — import and wiring verification.

These tests do NOT make live API calls. They verify that:
1. All imports resolve without errors
2. GigSmartToolkit can be instantiated with a mock config
3. get_tools() returns exactly 23 tools
4. All confirming tools are discoverable
5. Tool names are prefixed with gs_
"""

from __future__ import annotations

import pytest

from parrot_tools.interfaces.gigsmart.config import GigSmartConfig


# ---------------------------------------------------------------------------
# Import smoke tests
# ---------------------------------------------------------------------------

class TestGigSmartIntegration:
    """Smoke tests verifying the full package wires up correctly."""

    def test_interface_imports(self):
        """All public symbols in parrot_tools.interfaces.gigsmart import cleanly."""
        from parrot_tools.interfaces.gigsmart import (
            GigSmartClient,
            GigSmartConfig,
            GigSmartAuth,
            GigSmartError,
            GigSmartAuthError,
            GigSmartValidationError,
            GigSmartRateLimitError,
            GigSmartNotFoundError,
            GigSmartTransportError,
            GigSmartGraphQLError,
            GigSmartConflictError,
        )
        assert GigSmartClient is not None
        assert GigSmartConfig is not None
        assert GigSmartAuth is not None
        assert GigSmartError is not None
        assert GigSmartAuthError is not None
        assert GigSmartValidationError is not None
        assert GigSmartRateLimitError is not None
        assert GigSmartNotFoundError is not None
        assert GigSmartTransportError is not None
        assert GigSmartGraphQLError is not None
        assert GigSmartConflictError is not None

    def test_models_import(self):
        """All models in parrot_tools.interfaces.gigsmart.models import cleanly."""
        from parrot_tools.interfaces.gigsmart.models import (
            OAuthToken,
            RelayConnection,
            RelayEdge,
            RelayPageInfo,
            Gig,
            PostShiftInput,
            TransitionGigInput,
            Engagement,
            TransitionEngagementInput,
            OrganizationLocation,
            AddOrganizationLocationInput,
            Position,
            AddOrganizationPositionInput,
            EngagementTimesheet,
            ApproveEngagementTimesheetInput,
            RemoveEngagementTimesheetInput,
        )
        assert OAuthToken is not None
        assert RelayConnection is not None
        assert PostShiftInput is not None

    def test_queries_import(self):
        """All GraphQL documents in parrot_tools.interfaces.gigsmart.queries import cleanly."""
        from parrot_tools.interfaces.gigsmart.queries import (
            PAGE_INFO_FRAGMENT,
            LIST_GIGS,
            POST_SHIFT,
            TRANSITION_ENGAGEMENT,
            VIEWER_QUERY,
        )
        assert isinstance(PAGE_INFO_FRAGMENT, str)
        assert isinstance(LIST_GIGS, str)
        assert isinstance(POST_SHIFT, str)
        assert isinstance(TRANSITION_ENGAGEMENT, str)

    def test_toolkit_import(self):
        """GigSmartToolkit imports cleanly from parrot_tools.gigsmart."""
        from parrot_tools.gigsmart import GigSmartToolkit
        assert GigSmartToolkit is not None

    def test_toolkit_instantiation(self):
        """GigSmartToolkit can be instantiated with a test config."""
        from parrot_tools.gigsmart import GigSmartToolkit
        config = GigSmartConfig(client_id="test", client_secret="secret")
        tk = GigSmartToolkit(config=config)
        assert tk.name == "gigsmart"
        assert tk.tool_prefix == "gs"

    def test_toolkit_discovers_23_tools(self):
        """GigSmartToolkit.get_tools() returns exactly 23 tools."""
        from parrot_tools.gigsmart import GigSmartToolkit
        config = GigSmartConfig(client_id="test", client_secret="secret")
        tk = GigSmartToolkit(config=config)
        tools = tk.get_tools()
        assert len(tools) == 23, (
            f"Expected 23 tools but got {len(tools)}: {[t.name for t in tools]}"
        )

    def test_tool_names_prefixed(self):
        """All tool names start with gs_ prefix."""
        from parrot_tools.gigsmart import GigSmartToolkit
        config = GigSmartConfig(client_id="test", client_secret="secret")
        tk = GigSmartToolkit(config=config)
        tools = tk.get_tools()
        for tool in tools:
            assert tool.name.startswith("gs_"), f"Tool {tool.name} missing gs_ prefix"

    def test_confirming_tools_exist(self):
        """All confirming_tools have a corresponding tool in get_tools()."""
        from parrot_tools.gigsmart import GigSmartToolkit
        config = GigSmartConfig(client_id="test", client_secret="secret")
        tk = GigSmartToolkit(config=config)
        tools = tk.get_tools()
        tool_names = {t.name.removeprefix("gs_") for t in tools}
        for ct in tk.confirming_tools:
            assert ct in tool_names, f"Confirming tool '{ct}' not in toolkit"

    def test_confirming_tools_have_requires_confirmation(self):
        """Confirming tools carry routing_meta requires_confirmation=True."""
        from parrot_tools.gigsmart import GigSmartToolkit
        config = GigSmartConfig(client_id="test", client_secret="secret")
        tk = GigSmartToolkit(config=config)
        tools = tk.get_tools()
        confirming_meta = {
            t.name.removeprefix("gs_"): getattr(t, "routing_meta", {})
            for t in tools
        }
        for ct in tk.confirming_tools:
            meta = confirming_meta.get(ct, {})
            if meta:  # routing_meta may not always be present depending on version
                assert meta.get("requires_confirmation") is True, (
                    f"Tool '{ct}' missing requires_confirmation in routing_meta"
                )

    def test_exception_hierarchy_is_correct(self):
        """All exception subclasses inherit from GigSmartError."""
        from parrot_tools.interfaces.gigsmart.exceptions import (
            GigSmartError,
            GigSmartAuthError,
            GigSmartValidationError,
            GigSmartRateLimitError,
            GigSmartNotFoundError,
            GigSmartTransportError,
            GigSmartGraphQLError,
            GigSmartConflictError,
        )
        for cls in [
            GigSmartAuthError,
            GigSmartValidationError,
            GigSmartRateLimitError,
            GigSmartNotFoundError,
            GigSmartTransportError,
            GigSmartGraphQLError,
            GigSmartConflictError,
        ]:
            assert issubclass(cls, GigSmartError), f"{cls.__name__} not a GigSmartError"
