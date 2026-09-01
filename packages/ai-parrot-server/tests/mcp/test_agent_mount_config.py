"""Unit tests for `AgentMCPMountConfig` (FEAT-477, TASK-2601)."""
import pytest
from parrot.mcp.config import AgentMCPMountConfig, MCPServerConfig
from pydantic import ValidationError


class TestAgentMCPMountConfig:
    """Validation tests for `AgentMCPMountConfig`."""

    def test_defaults(self):
        c = AgentMCPMountConfig(
            agents=["finance"], resource_server_url="https://h/mcp/agents/finance"
        )
        assert c.base_path == "/mcp/agents"
        assert c.aggregate_enabled is False
        assert c.max_result_tokens == 25_000
        assert c.call_deadline_seconds == 240.0
        assert c.default_tenant_id is None

    @pytest.mark.parametrize("url", ["mcp/agents", "", "not-a-uri"])
    def test_rejects_relative_resource_url(self, url):
        with pytest.raises(ValidationError):
            AgentMCPMountConfig(agents=["a"], resource_server_url=url)

    def test_rejects_deadline_at_or_above_client_ceiling(self):
        with pytest.raises(ValidationError):
            AgentMCPMountConfig(
                agents=["a"],
                resource_server_url="https://h/x",
                call_deadline_seconds=300.0,
            )

    def test_accepts_deadline_below_client_ceiling(self):
        c = AgentMCPMountConfig(
            agents=["a"],
            resource_server_url="https://h/x",
            call_deadline_seconds=299.9,
        )
        assert c.call_deadline_seconds == 299.9

    def test_rejects_max_result_tokens_at_or_above_connector_ceiling(self):
        with pytest.raises(ValidationError):
            AgentMCPMountConfig(
                agents=["a"],
                resource_server_url="https://h/x",
                max_result_tokens=30_000,
            )

    def test_rejects_agent_name_with_separator(self):
        with pytest.raises(ValidationError, match="__"):
            AgentMCPMountConfig(agents=["fin__ance"], resource_server_url="https://h/x")

    def test_existing_config_untouched(self):
        assert MCPServerConfig().base_path == "/mcp"
        assert MCPServerConfig().session_ttl == 3600
        assert MCPServerConfig().agent_mount is None
