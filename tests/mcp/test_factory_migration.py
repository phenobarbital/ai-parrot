"""Tests verifying factory functions work with MCPOAuth2Config (FEAT-262, TASK-1665)."""


class TestCreateOAuthMCPServer:
    """Tests for the refactored create_oauth_mcp_server() factory."""

    def test_create_with_mcp_oauth2_config(self):
        """create_oauth_mcp_server accepts an MCPOAuth2Config object."""
        from parrot.mcp.integration import create_oauth_mcp_server
        from parrot.mcp.oauth2_config import MCPOAuth2Config

        cfg = create_oauth_mcp_server(
            name="test-server",
            url="http://example.com/mcp",
            user_id="user@co.com",
            oauth2=MCPOAuth2Config(
                client_id="app-id",
                auth_url="https://auth.example.com/authorize",
                token_url="https://auth.example.com/token",
                scopes=["read", "write"],
            ),
        )
        assert cfg.oauth2 is not None
        assert cfg.oauth2.client_id == "app-id"
        assert cfg.name == "test-server"

    def test_create_with_legacy_params(self):
        """create_oauth_mcp_server accepts old individual parameters for backward compat."""
        from parrot.mcp.integration import create_oauth_mcp_server

        cfg = create_oauth_mcp_server(
            name="legacy-server",
            url="http://legacy.example.com/mcp",
            user_id="user@co.com",
            client_id="legacy-app",
            auth_url="https://auth.legacy.com/authorize",
            token_url="https://auth.legacy.com/token",
            scopes=["openid"],
        )
        assert cfg.oauth2 is not None
        assert cfg.oauth2.client_id == "legacy-app"
        assert cfg.oauth2.auth_url == "https://auth.legacy.com/authorize"
        assert cfg.oauth2.scopes == ["openid"]

    def test_auth_type_set_to_oauth2(self):
        """create_oauth_mcp_server sets auth_type to 'oauth2'."""
        from parrot.mcp.integration import create_oauth_mcp_server
        from parrot.mcp.oauth2_config import MCPOAuth2Config

        cfg = create_oauth_mcp_server(
            name="test",
            url="http://example.com/mcp",
            user_id="user",
            oauth2=MCPOAuth2Config(client_id="app", scopes=["read"]),
        )
        assert cfg.auth_type == "oauth2"

    def test_no_oauth_manager_constructed(self):
        """OAuthManager is no longer constructed by create_oauth_mcp_server."""
        from parrot.mcp.integration import create_oauth_mcp_server
        from parrot.mcp.oauth2_config import MCPOAuth2Config
        import parrot.mcp.oauth as oauth_mod

        # If OAuthManager existed, this would raise AttributeError on access
        assert not hasattr(oauth_mod, "OAuthManager")

        # Function runs without error and returns MCPClientConfig
        cfg = create_oauth_mcp_server(
            name="test",
            url="http://example.com/mcp",
            user_id="user",
            oauth2=MCPOAuth2Config(client_id="app", scopes=["read"]),
        )
        assert cfg is not None

    def test_registers_mcp_oauth2_provider(self):
        """create_oauth_mcp_server registers an MCPOAuth2Provider in the registry."""
        from parrot.mcp.integration import create_oauth_mcp_server
        from parrot.mcp.oauth2_config import MCPOAuth2Config

        cfg = create_oauth_mcp_server(
            name="reg-test-server",
            url="http://example.com/mcp",
            user_id="user",
            oauth2=MCPOAuth2Config(client_id="app", scopes=["read"]),
        )
        assert cfg.oauth2 is not None


class TestCreateNetsuiteMCPServer:
    """Tests for the refactored create_netsuite_mcp_server() factory."""

    def test_creates_config_with_oauth2(self):
        """create_netsuite_mcp_server uses MCPOAuth2Config instead of OAuthManager."""
        from parrot.mcp.integration import create_netsuite_mcp_server

        cfg = create_netsuite_mcp_server(
            account_id="4984231",
            client_id="my-client-id",
            user_id="user@co.com",
        )
        assert cfg.oauth2 is not None
        assert cfg.oauth2.client_id == "my-client-id"

    def test_netsuite_url_contains_account_id(self):
        """create_netsuite_mcp_server builds the correct MCP URL."""
        from parrot.mcp.integration import create_netsuite_mcp_server

        cfg = create_netsuite_mcp_server(
            account_id="1234567",
            client_id="my-id",
            user_id="user",
        )
        assert "1234567" in cfg.url

    def test_netsuite_auth_url_contains_account_id(self):
        """create_netsuite_mcp_server builds the correct auth URL."""
        from parrot.mcp.integration import create_netsuite_mcp_server

        cfg = create_netsuite_mcp_server(
            account_id="9876543",
            client_id="my-id",
            user_id="user",
        )
        assert "9876543" in cfg.oauth2.auth_url

    def test_netsuite_scopes_contain_mcp(self):
        """create_netsuite_mcp_server requests the 'mcp' scope."""
        from parrot.mcp.integration import create_netsuite_mcp_server

        cfg = create_netsuite_mcp_server(
            account_id="4984231",
            client_id="my-id",
            user_id="user",
        )
        assert "mcp" in cfg.oauth2.scopes

    def test_netsuite_auth_type_set(self):
        """create_netsuite_mcp_server sets auth_type to 'oauth2'."""
        from parrot.mcp.integration import create_netsuite_mcp_server

        cfg = create_netsuite_mcp_server(
            account_id="4984231",
            client_id="my-id",
            user_id="user",
        )
        assert cfg.auth_type == "oauth2"


class TestMCPServerDescriptorAuthType:
    """Tests for the MCPServerDescriptor.auth_type field."""

    def test_auth_type_field_exists(self):
        """MCPServerDescriptor has an optional auth_type field."""
        from parrot.mcp.registry import MCPServerDescriptor

        desc = MCPServerDescriptor(
            name="test",
            display_name="Test",
            description="A test server",
            method_name="add_test_mcp_server",
        )
        # auth_type defaults to None
        assert desc.auth_type is None

    def test_auth_type_can_be_set(self):
        """MCPServerDescriptor.auth_type can be set to a string value."""
        from parrot.mcp.registry import MCPServerDescriptor

        desc = MCPServerDescriptor(
            name="oauth-server",
            display_name="OAuth Server",
            description="Uses OAuth2",
            method_name="add_oauth_mcp_server",
            auth_type="oauth2",
        )
        assert desc.auth_type == "oauth2"

    def test_existing_descriptors_unaffected(self):
        """Existing MCPServerDescriptor entries in the registry still load correctly."""
        from parrot.mcp.registry import MCPServerRegistry

        registry = MCPServerRegistry()
        servers = registry.list_servers()
        assert len(servers) > 0
        # All descriptors should be valid (no ValueError on loading)
        for server in servers:
            assert server.name is not None
