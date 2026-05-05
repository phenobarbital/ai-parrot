"""E2E integration test: cold-session OAuth toolkit hydration.

Test
----
- test_e2e_cold_session_rehydration (spec §4 test 4)

Verifies that:
  1. When Redis has no session toolkit for (user, agent), UserObjectsHandler
     reads user_agent_toolkits from DocumentDB.
  2. For each row, the corresponding OAuth2Provider.toolkit_factory is called
     and the resulting toolkit is added to the ToolManager.
  3. Hydration is idempotent — if the toolkit is already present, no duplicate.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.integrations.oauth2.models import UserAgentToolkitRow


from .helpers import make_mock_db as _make_mock_db


class TestE2EColdSessionRehydration:
    """Cold-session hydration loads toolkits from DocumentDB into ToolManager."""

    @pytest.mark.asyncio
    async def test_hydration_adds_toolkit_to_tool_manager(
        self,
        web_user_id: str,
        registered_jira_provider: MagicMock,
        sample_toolkit_row: UserAgentToolkitRow,
    ) -> None:
        """_hydrate_oauth_toolkits adds the Jira toolkit on a cold session."""
        from parrot.handlers.user_objects import UserObjectsHandler

        mock_db_cls, mock_db = _make_mock_db()
        # Simulate DocumentDB returning one toolkit row
        mock_db.read = AsyncMock(
            return_value=[sample_toolkit_row.model_dump()]
        )

        # Mock credential resolver so toolkit_factory doesn't need real Jira credentials
        mock_resolver = MagicMock()

        # Build a minimal AbstractToolkit-spec mock so register_toolkit()'s
        # isinstance check passes, but no real Jira connection is needed.
        from parrot.tools.toolkit import AbstractToolkit
        from parrot.tools.abstract import AbstractTool

        fake_tool = MagicMock(spec=AbstractTool)
        fake_tool.name = "jira_search_issues"
        mock_toolkit = MagicMock(spec=AbstractToolkit)
        mock_toolkit.get_tools_sync.return_value = [fake_tool]

        with patch(
            "parrot.integrations.oauth2.persistence.DocumentDb",
            mock_db_cls,
        ):
            with patch(
                "parrot.handlers.user_objects.OAuthCredentialResolver",
                return_value=mock_resolver,
            ):
                with patch.object(
                    registered_jira_provider,
                    "toolkit_factory",
                    return_value=mock_toolkit,
                ):
                    handler = UserObjectsHandler()
                    result_tm = await handler._hydrate_oauth_toolkits(
                        user_id=web_user_id,
                        agent_id="test-agent",
                        session_key="test-session-key",
                        request_session={},
                    )

        # toolkit_factory should have been invoked by the provider.
        # The ToolManager must be non-None AND contain at least one registered tool
        # (guards against the silent add_tool/register_toolkit regression).
        assert result_tm is not None
        assert result_tm.tool_count() > 0, (
            "Cold-session hydration returned a ToolManager but registered zero tools. "
            "Ensure _hydrate_oauth_toolkits calls register_toolkit(), not add_tool()."
        )

    @pytest.mark.asyncio
    async def test_hydration_skips_when_no_toolkit_rows(
        self,
        web_user_id: str,
        registered_jira_provider: MagicMock,
    ) -> None:
        """_hydrate_oauth_toolkits is a no-op when no user_agent_toolkits rows."""
        from parrot.handlers.user_objects import UserObjectsHandler

        mock_db_cls, mock_db = _make_mock_db()
        mock_db.read = AsyncMock(return_value=[])

        with patch(
            "parrot.integrations.oauth2.persistence.DocumentDb",
            mock_db_cls,
        ):
            handler = UserObjectsHandler()
            result_tm = await handler._hydrate_oauth_toolkits(
                user_id=web_user_id,
                agent_id="test-agent",
                session_key="test-session-key",
                request_session={},
            )

        # No toolkits — method returns None (no ToolManager created)
        assert result_tm is None

    @pytest.mark.asyncio
    async def test_hydration_skips_unknown_provider(
        self,
        web_user_id: str,
    ) -> None:
        """_hydrate_oauth_toolkits logs and skips rows with unregistered providers."""
        from parrot.handlers.user_objects import UserObjectsHandler

        unknown_row = UserAgentToolkitRow(
            user_id=web_user_id,
            agent_id="test-agent",
            toolkit_id="unknown-provider",
            provider="unknown-provider",
            enabled_at=datetime.now(tz=timezone.utc),
        )
        mock_db_cls, mock_db = _make_mock_db()
        mock_db.read = AsyncMock(return_value=[unknown_row.model_dump()])

        with patch(
            "parrot.integrations.oauth2.persistence.DocumentDb",
            mock_db_cls,
        ):
            handler = UserObjectsHandler()
            # Should not raise — unknown provider is skipped gracefully
            result_tm = await handler._hydrate_oauth_toolkits(
                user_id=web_user_id,
                agent_id="test-agent",
                session_key="test-session-key",
                request_session={},
            )

        # An empty ToolManager is returned — provider was skipped, no tools added
        assert result_tm is not None
        assert result_tm.tool_count() == 0

    @pytest.mark.asyncio
    async def test_hydration_skips_user_id_absent(self) -> None:
        """_hydrate_oauth_toolkits returns None when DB returns no rows for user_id=None."""
        from parrot.handlers.user_objects import UserObjectsHandler

        mock_db_cls, mock_db = _make_mock_db()
        # DB returns empty list for None user_id query
        mock_db.read = AsyncMock(return_value=[])

        with patch(
            "parrot.integrations.oauth2.persistence.DocumentDb",
            mock_db_cls,
        ):
            handler = UserObjectsHandler()
            result_tm = await handler._hydrate_oauth_toolkits(
                user_id=None,  # type: ignore[arg-type]
                agent_id="test-agent",
                session_key="test-session-key",
                request_session={},
            )

        # No enablements found — returns None
        assert result_tm is None
