"""(login, --user, --server) identity matrix (FEAT-774 M7, AC-3, AC-4)."""

from unittest.mock import MagicMock

import pytest

from parrot.cli.agent_repl import _declared_providers


@pytest.mark.parametrize(
    "has_manager,providers,expected",
    [
        (False, (), set()),
        (True, ("o365", None, "jira"), {"o365", "jira"}),
    ],
)
def test_declared_provider_matrix(has_manager, providers, expected):
    """Only explicitly declared tool providers are selected for the broker."""
    bot = MagicMock()
    if not has_manager:
        del bot.tool_manager
    else:
        bot.tool_manager.get_all_tools.return_value = [
            type("Tool", (), {"credential_provider": provider})() for provider in providers
        ]
    assert _declared_providers(bot) == expected


def test_identity_o365_bootstrap_removed():
    """The previous O365 environment bootstrap remains absent."""
    import parrot.cli.identity as identity

    assert not hasattr(identity, "resolve_cli_o365_principal")
    assert not hasattr(identity, "bot_declares_o365_device_code")
