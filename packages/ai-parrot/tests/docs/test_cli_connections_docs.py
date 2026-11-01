"""AC-15 smoke test: the FEAT-774 docs carry their required sections."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize(
    "rel,heading",
    [
        ("docs/cli/parrot-login-and-connections.md", "## Deployment prerequisites"),
        ("docs/cli/parrot-login-and-connections.md", "## agentd"),
        ("docs/mcp-local-toolkits.md", "## Credentials and identity"),
        ("docs/auth/connections.md", "## CLI consumers"),
        ("docs/cli/parrot-agent.md", "## Identity"),
    ],
)
def test_cli_connections_docs_sections(rel: str, heading: str) -> None:
    """Assert that each AC-15 documentation section is present."""
    assert heading in (ROOT / rel).read_text(encoding="utf-8")
