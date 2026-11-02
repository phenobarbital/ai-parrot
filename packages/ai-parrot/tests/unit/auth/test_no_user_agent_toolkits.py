"""Guards for the retired per-agent OAuth2 toolkit repository."""

from pathlib import Path


def test_no_user_agent_toolkits_reader_or_writer() -> None:
    """No package source retains the retired repository name."""
    root = Path(__file__).resolve().parents[4]
    hits = [path for path in root.glob("*/src/**/*.py") if "user_agent_toolkit" in path.read_text(errors="ignore")]
    assert hits == []


def test_new_oauth2_exports() -> None:
    """The new connection surface is importable from the OAuth2 package."""
    from parrot.auth.oauth2 import ConnectionEventPublisher, StandardOAuth2Manager, list_users_integrations

    assert ConnectionEventPublisher is not None
    assert StandardOAuth2Manager is not None
    assert list_users_integrations is not None
