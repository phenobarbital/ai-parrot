"""FEAT-593 docs presence check."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_studio_api_doc_mentions_endpoints():
    text = (ROOT / "docs/agent_studio_api.md").read_text(encoding="utf-8")
    for needle in (
        "/toolkits/{slug}/options/{param}",
        "/mcp-servers",
        "/me",
        "read_only_definition",
        "not_overridable",
        "use_studio_endpoint",
    ):
        assert needle in text, needle


def test_yaml_doc_mentions_toolkit_entries():
    text = (ROOT / "docs/agent_config_creation.md").read_text(encoding="utf-8")
    assert "user_overridable" in text and "vault" in text.lower()
