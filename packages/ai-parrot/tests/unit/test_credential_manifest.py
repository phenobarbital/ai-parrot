"""Unit tests for TASK-1670: Manifest loader + AgentDefinition credential config.

Tests:
- Manifest loader parses a credentials: YAML block correctly
- Env-var substitution in option values
- ${VAR:-default} syntax
- Missing file returns empty list
- Agents without credential config are broker-less (no regression)
- Agent with credentials builds a CredentialBroker at configure() time
"""
import textwrap

from parrot.auth.credentials import ProviderCredentialConfig
from parrot.auth.manifest import load_credentials_manifest, parse_credentials_block


# ---------------------------------------------------------------------------
# parse_credentials_block
# ---------------------------------------------------------------------------


def test_parse_empty_block_returns_empty():
    """None/empty block returns empty list."""
    assert parse_credentials_block(None) == []
    assert parse_credentials_block([]) == []


def test_parse_single_provider():
    """Single entry parsed to one ProviderCredentialConfig."""
    block = [{"provider": "fireflies", "auth": "static_key",
              "options": {"capture_url": "https://app.fireflies.ai"}}]
    result = parse_credentials_block(block)
    assert len(result) == 1
    assert result[0].provider == "fireflies"
    assert result[0].auth == "static_key"
    assert result[0].options["capture_url"] == "https://app.fireflies.ai"


def test_parse_multiple_providers():
    """Multiple entries each become a ProviderCredentialConfig."""
    block = [
        {"provider": "workiq", "auth": "obo",
         "options": {"scope": "api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask"}},
        {"provider": "jira", "auth": "oauth2"},
        {"provider": "myservice", "auth": "mcp",
         "options": {"vault_key": "myservice:token", "auth_url": "https://svc.example.com"}},
    ]
    result = parse_credentials_block(block)
    assert len(result) == 3
    providers = {c.provider for c in result}
    assert providers == {"workiq", "jira", "myservice"}


def test_parse_returns_pydantic_models():
    """Each entry is a ProviderCredentialConfig (Pydantic model)."""
    block = [{"provider": "svc", "auth": "oauth2"}]
    result = parse_credentials_block(block)
    assert isinstance(result[0], ProviderCredentialConfig)


# ---------------------------------------------------------------------------
# Env-var expansion
# ---------------------------------------------------------------------------


def test_env_var_substitution(monkeypatch):
    """${VAR} is replaced with env value."""
    monkeypatch.setenv("TEST_CAPTURE_URL", "https://real.example.com")
    block = [{"provider": "svc", "auth": "static_key",
              "options": {"capture_url": "${TEST_CAPTURE_URL}"}}]
    result = parse_credentials_block(block)
    assert result[0].options["capture_url"] == "https://real.example.com"


def test_env_var_default_substitution(monkeypatch):
    """${VAR:-default} uses default when var is unset."""
    monkeypatch.delenv("MISSING_VAR", raising=False)
    block = [{"provider": "svc", "auth": "mcp",
              "options": {"auth_url": "${MISSING_VAR:-https://fallback.example.com}"}}]
    result = parse_credentials_block(block)
    assert result[0].options["auth_url"] == "https://fallback.example.com"


def test_env_var_expand_disabled():
    """expand_env=False leaves ${VAR} literals intact."""
    block = [{"provider": "svc", "auth": "mcp",
              "options": {"auth_url": "${SOME_URL}"}}]
    result = parse_credentials_block(block, expand_env=False)
    assert result[0].options["auth_url"] == "${SOME_URL}"


# ---------------------------------------------------------------------------
# load_credentials_manifest (YAML file)
# ---------------------------------------------------------------------------


def test_load_manifest_missing_file(tmp_path):
    """Missing file returns empty list (graceful degradation)."""
    result = load_credentials_manifest(tmp_path / "nonexistent.yaml")
    assert result == []


def test_load_manifest_parses_yaml(tmp_path):
    """Loads and parses a real YAML manifest file."""
    manifest = tmp_path / "creds.yaml"
    manifest.write_text(textwrap.dedent("""\
        credentials:
          - provider: workiq
            auth: obo
            options:
              scope: api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask
          - provider: jira
            auth: oauth2
    """))

    result = load_credentials_manifest(manifest)
    assert len(result) == 2
    assert result[0].provider == "workiq"
    assert result[0].auth == "obo"
    assert result[1].provider == "jira"
    assert result[1].auth == "oauth2"


def test_load_manifest_custom_key(tmp_path):
    """Custom top-level key is supported."""
    manifest = tmp_path / "config.yaml"
    manifest.write_text(textwrap.dedent("""\
        providers:
          - provider: svc
            auth: mcp
    """))
    result = load_credentials_manifest(manifest, key="providers")
    assert len(result) == 1
    assert result[0].provider == "svc"


def test_load_manifest_missing_key_returns_empty(tmp_path):
    """File exists but lacks the key → empty list."""
    manifest = tmp_path / "other.yaml"
    manifest.write_text("other_key: value\n")
    result = load_credentials_manifest(manifest)
    assert result == []


# ---------------------------------------------------------------------------
# Agent-level credential config: broker build logic (without AbstractBot import)
#
# AbstractBot.configure() is tested at the integration level via the installed
# package.  Here we verify the sub-components it delegates to:
#   1. CredentialBroker.from_config builds a broker from MCP config (no deps).
#   2. ToolManager.set_broker / .broker property — default is None; set works.
# The abstract.py change is 3 lines that wire these two together.
# ---------------------------------------------------------------------------


def test_credential_broker_builds_from_mcp_config():
    """CredentialBroker.from_config builds a broker from a MCP-type config (no deps).

    Verifies the pure-construction path that AbstractBot.configure() calls.
    """
    from parrot.auth.broker import CredentialBroker

    configs = [
        ProviderCredentialConfig(
            provider="myservice",
            auth="mcp",
            options={"vault_key": "myservice:token", "auth_url": "https://svc.example.com"},
        )
    ]
    broker = CredentialBroker.from_config(configs)
    assert broker is not None
    assert "myservice" in broker._resolvers


def test_tool_manager_no_broker_by_default():
    """ToolManager has no broker by default (agents without credentials config)."""
    from parrot.tools.manager import ToolManager

    tm = ToolManager()
    assert tm.broker is None


def test_tool_manager_set_broker_makes_broker_accessible():
    """ToolManager.set_broker() makes broker reachable via .broker property.

    This is the path AbstractBot.configure() exercises after CredentialBroker.from_config.
    """
    from parrot.tools.manager import ToolManager
    from parrot.auth.broker import CredentialBroker

    tm = ToolManager()
    broker = CredentialBroker()
    tm.set_broker(broker)
    assert tm.broker is broker
