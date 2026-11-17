# FEAT-774 citation checks (§4d/§5b)

Summary: {"verified": 141, "missing": 1, "stale": 1}

| check | class | evidence | findings |
|---|---|---|---|
| c0 | verified | packages/ai-parrot/src/parrot/cli/agent_repl.py:23 `build_cli_permission_context` (non-def symbol: constant/import/attribute/key) | F001 |
| c1 | verified | packages/ai-parrot/src/parrot/cli/identity.py:27 `CLI_CHANNEL` (non-def symbol: constant/import/attribute/key) | F001 |
| c2 | missing | packages/ai-parrot/tests/cli/test_identity.py — `test_identity` not found (probe + bare grep) | F001 |
| c3 | verified | packages/ai-parrot/src/parrot/cli/agent_repl.py:97 def agent( | F001 |
| c4 | verified | packages/ai-parrot/src/parrot/cli/agent_repl.py:134 async def _run( | F001, F001, F001 |
| c5 | verified | packages/ai-parrot/src/parrot/cli/agent_repl.py:5 `REPLConfig` (non-def symbol: constant/import/attribute/key) | F001 |
| c6 | verified | packages/ai-parrot/src/parrot/cli/session.py:105 def _identity_kwargs(self) -> dict[str, Any]: | F001 |
| c7 | verified | packages/ai-parrot/src/parrot/cli/identity.py (126 lines) | F002 |
| c8 | verified | packages/ai-parrot/src/parrot/cli/identity.py:24 `O365_PRINCIPAL_ENV_VAR` (non-def symbol: constant/import/attribute/key) | F002 |
| c9 | verified | packages/ai-parrot/src/parrot/cli/identity.py:45 def resolve_cli_o365_principal() -> str: | F002 |
| c10 | verified | packages/ai-parrot/src/parrot/cli/identity.py:76 def build_cli_permission_context(user_id: Optional[str] = None) -> PermissionContext: | F002 |
| c11 | verified | packages/ai-parrot/src/parrot/cli/identity.py:108 def bot_declares_o365_device_code(bot: object) -> bool: | F002 |
| c12 | verified | packages/ai-parrot-integrations/src/parrot/integrations/agentd/server.py:323 async def _resolve_identity( | F003 |
| c13 | verified | packages/ai-parrot-integrations/src/parrot/integrations/agentd/config.py:198 def to_permission_context(self, channel: str = "agentd") -> PermissionContext: | F003 |
| c14 | verified | packages/ai-parrot-integrations/src/parrot/integrations/agentd/service.py (779 lines) | F003 |
| c15 | verified | packages/ai-parrot/src/parrot/cli/repl.py:44 `permission_context` (non-def symbol: constant/import/attribute/key) | F003 |
| c16 | verified | packages/ai-parrot/src/parrot/cli/__init__.py:30 `_lazy_commands` (non-def symbol: constant/import/attribute/key) | F003, F040, F043 |
| c17 | verified | packages/ai-parrot-integrations/src/parrot/integrations/agentd/server.py — `imports` is a descriptive label, file exists | F003 |
| c18 | verified | packages/ai-parrot-integrations/src/parrot/integrations/agentd/server.py:62 def _read_peercred(sock: socket.socket) -> tuple[int, int, int]: | F003 |
| c19 | verified | packages/ai-parrot-integrations/src/parrot/integrations/agentd/server.py:116 class Session: | F003 |
| c20 | stale | packages/ai-parrot-integrations/src/parrot/integrations/agentd/server.py `__init__` ambiguous at lines [110, 137, 179, 228] | F003 |
| c21 | verified | packages/ai-parrot-integrations/src/parrot/integrations/agentd/server.py:250 async def start(self) -> None: | F003 |
| c22 | verified | packages/ai-parrot-integrations/src/parrot/integrations/agentd/server.py:363 async def _handle_connection( | F003 |
| c23 | verified | packages/ai-parrot-integrations/src/parrot/integrations/agentd/service.py:238 class AgentDaemon: | F003 |
| c24 | verified | packages/ai-parrot-integrations/src/parrot/integrations/agentd/mcp_server.py:182 async def run_mcp_proxy(name_or_socket: str) -> None: | F003 |
| c25 | verified | packages/ai-parrot-integrations/src/parrot/integrations/agentd/proxy.py:184 class DaemonAgentProxy: | F003, F038 |
| c26 | verified | packages/ai-parrot/src/parrot/mcp/oauth.py (280 lines) | F004 |
| c27 | verified | packages/ai-parrot/src/parrot/mcp/oauth2_config.py (204 lines) | F004 |
| c28 | verified | packages/ai-parrot/src/parrot/mcp/oauth2_storage.py:29 class VaultMCPTokenStorage(TokenStorage): | F004, F041 |
| c29 | verified | packages/ai-parrot/src/parrot/mcp/oauth2_config.py:27 class MCPOAuth2Config(BaseModel): | F004, F041 |
| c30 | verified | packages/ai-parrot/src/parrot/mcp/oauth.py (280 lines) | F004 |
| c31 | verified | packages/ai-parrot/src/parrot/mcp/client.py:242 `inject_broker_credential` (non-def symbol: constant/import/attribute/key) | F005 |
| c32 | verified | packages/ai-parrot/src/parrot/cli/__init__.py:19 class LazyGroup(click.Group): | F006 |
| c33 | verified | packages/ai-parrot/src/parrot/cli/agent_repl.py (367 lines) | F006 |
| c34 | verified | packages/ai-parrot/src/parrot/mcp/toolkit_config.py:46 `env` (non-def symbol: constant/import/attribute/key) | F007 |
| c35 | verified | packages/ai-parrot/src/parrot/mcp/toolkit_server.py (264 lines) | F007 |
| c36 | verified | packages/ai-parrot/src/parrot/mcp/hosts.py (245 lines) | F008 |
| c37 | verified | packages/ai-parrot/src/parrot/mcp/toolkit_install.py (248 lines) | F008 |
| c38 | verified | packages/ai-parrot-server/src/parrot/mcp/principal_guard.py:128 async def resolve_principal( | F009 |
| c39 | verified | packages/ai-parrot-server/src/parrot/mcp/principal_guard.py:192 async def published_principal(pctx: PermissionContext) -> AsyncIterator[PermissionContext]: | F009 |
| c40 | verified | packages/ai-parrot-server/src/parrot/mcp/session_store.py (411 lines) | F009 |
| c41 | verified | packages/ai-parrot-server/src/parrot/mcp/principal_guard.py (596 lines) | F009 |
| c42 | verified | packages/ai-parrot-server/src/parrot/mcp/principal_guard.py (596 lines) | F009 |
| c43 | verified | packages/ai-parrot-server/src/parrot/mcp/principal_guard.py:75 def resolve_tenant(token_info: dict[str, Any], mount_config: Any) -> str / None: | F009 |
| c44 | verified | packages/ai-parrot-server/src/parrot/mcp/principal_guard.py (596 lines) | F009 |
| c45 | verified | packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py:206 async def _run_device_flow(self, user_id: str) -> str: | F010 |
| c46 | verified | packages/ai-parrot/src/parrot/auth/o365_oauth.py (227 lines) | F010 |
| c47 | verified | packages/ai-parrot-integrations/src/parrot/integrations/agentd/ is a directory (exists) | F011 |
| c48 | verified | packages/ai-parrot/tests/cli/ is a directory (exists) | F012 |
| c49 | verified | packages/ai-parrot/tests/mcp/ is a directory (exists) | F012 |
| c50 | verified | packages/ai-parrot-integrations/tests/agentd/ is a directory (exists) | F012 |
| c51 | verified | packages/ai-parrot/src/parrot/cli/agent_repl.py (367 lines) | F013 |
| c52 | verified | packages/ai-parrot/src/parrot/mcp/local_cli.py:167 def mcp_local( | F014, F040 |
| c53 | verified | packages/ai-parrot/src/parrot/mcp/local_server.py (255 lines) | F015 |
| c54 | verified | packages/ai-parrot/src/parrot/mcp/toolkit_server.py:137 def create_toolkit_mcp_server( | F016 |
| c55 | verified | packages/ai-parrot/src/parrot/mcp/toolkit_server.py:37 class _ToolkitStdioMCPServer(StdioMCPServer): | F016 |
| c56 | verified | packages/ai-parrot/src/parrot/mcp/toolkit_server.py (264 lines) | F016 |
| c57 | verified | packages/ai-parrot/src/parrot/mcp/toolkit_server.py:148 `imports` (non-def symbol: constant/import/attribute/key) | F016 |
| c58 | verified | packages/ai-parrot/src/parrot/mcp/toolkit_config.py (175 lines) | F017 |
| c59 | verified | packages/ai-parrot/src/parrot/mcp/hosts.py (245 lines) | F018 |
| c60 | verified | packages/ai-parrot/src/parrot/mcp/oauth.py (280 lines) | F019 |
| c61 | verified | packages/ai-parrot/src/parrot/mcp/oauth.py:232 async def ensure_token(self, user_id: str = "m2m") -> str: | F019 |
| c62 | verified | packages/ai-parrot/src/parrot/mcp/oauth2_storage.py (172 lines) | F020 |
| c63 | verified | packages/ai-parrot/src/parrot/mcp/oauth2_config.py (204 lines) | F021 |
| c64 | verified | packages/ai-parrot/src/parrot/auth/oauth2/mcp_provider.py (152 lines) | F022 |
| c65 | verified | packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py (281 lines) | F023 |
| c66 | verified | packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py:57 def _default_prompt_callback(flow: Dict[str, Any]) -> None: | F023 |
| c67 | verified | packages/ai-parrot/src/parrot/auth/broker/factory.py:46 def build(self, cfg: ProviderCredentialConfig) -> CredentialResolver: | F024 |
| c68 | verified | packages/ai-parrot/src/parrot/auth/broker/factory.py:114 def _build_oauth2(self, cfg: ProviderCredentialConfig, opts: dict[str, Any]) -> CredentialResolver: | F024 |
| c69 | verified | packages/ai-parrot/src/parrot/auth/broker/factory.py:249 class _MCPVaultResolver(CredentialResolver): | F024 |
| c70 | verified | packages/ai-parrot-server/src/parrot/mcp/principal_guard.py (596 lines) | F025 |
| c71 | verified | packages/ai-parrot-integrations/src/parrot/integrations/agentd/server.py (507 lines) | F026 |
| c72 | verified | packages/ai-parrot-integrations/src/parrot/integrations/agentd/config.py:131 class ServiceIdentityConfig(BaseModel): | F026 |
| c73 | verified | packages/ai-parrot/src/parrot/cli/commands.py (482 lines) | F027 |
| c74 | verified | packages/ai-parrot/src/parrot/cli/session.py (329 lines) | F028 |
| c75 | verified | packages/ai-parrot/src/parrot/auth/session_identity.py (133 lines) | F029 |
| c76 | verified | packages/ai-parrot/src/parrot/mcp/context.py:15 class ReadonlyContext(BaseModel): | F030 |
| c77 | verified | packages/ai-parrot/src/parrot/mcp/context.py:132 def _session_key(self, headers: Optional[Dict[str, str]] = None) -> int: | F030 |
| c78 | verified | sdd/specs/expose-toolkits-as-local-mcp.spec.md (710 lines) | F031 |
| c79 | verified | sdd/specs/agent-cli-daemon.spec.md (617 lines) | F032 |
| c80 | verified | sdd/specs/delegated-auth-connections.spec.md (1349 lines) | F033 |
| c81 | verified | sdd/specs/delegated-auth-connections.spec.md (1349 lines) | F033 |
| c82 | verified | sdd/specs/delegated-auth-connections.spec.md (1349 lines) | F033 |
| c83 | verified | sdd/specs/delegated-auth-connections.spec.md (1349 lines) | F033 |
| c84 | verified | packages/ai-parrot/src/parrot/auth/permission.py:166 def build_principal_context( | F034 |
| c85 | verified | packages/ai-parrot/src/parrot/cli/loaders.py (594 lines) | F035 |
| c86 | verified | packages/ai-parrot/src/parrot/cli/loaders.py:249 async def ask( | F035 |
| c87 | verified | packages/ai-parrot/src/parrot/cli/session.py (329 lines) | F036 |
| c88 | verified | packages/ai-parrot/src/parrot/cli/__init__.py (159 lines) | F036 |
| c89 | verified | packages/ai-parrot/src/parrot/cli/agent_repl.py (367 lines) | F036 |
| c90 | verified | packages/ai-parrot/src/parrot/cli/loaders.py (594 lines) | F036 |
| c91 | verified | packages/ai-parrot/src/parrot/mcp/hosts.py:37 class HostAdapter(Protocol): | F037 |
| c92 | verified | packages/ai-parrot/src/parrot/mcp/local_cli.py (236 lines) | F037 |
| c93 | verified | packages/ai-parrot/src/parrot/mcp/local_server.py:54 class StdioMCPServer(LocalMCPServerBase): | F037 |
| c94 | verified | packages/ai-parrot/src/parrot/mcp/toolkit_server.py (264 lines) | F037 |
| c95 | verified | packages/ai-parrot-integrations/src/parrot/integrations/agentd/server.py (507 lines) | F038 |
| c96 | verified | packages/ai-parrot-integrations/src/parrot/integrations/agentd/config.py (426 lines) | F038 |
| c97 | verified | packages/ai-parrot-integrations/src/parrot/integrations/agentd/service.py (779 lines) | F038 |
| c98 | verified | packages/ai-parrot-integrations/src/parrot/integrations/agentd/client.py (403 lines) | F038 |
| c99 | verified | packages/ai-parrot-server/src/parrot/mcp/principal_guard.py:1 `_pctx_var` (non-def symbol: constant/import/attribute/key) | F039 |
| c100 | verified | packages/ai-parrot-server/src/parrot/mcp/session_store.py (411 lines) | F039 |
| c101 | verified | packages/ai-parrot/src/parrot/mcp/local_cli.py (236 lines) | F040 |
| c102 | verified | packages/ai-parrot/src/parrot/mcp/local_server.py (255 lines) | F040 |
| c103 | verified | packages/ai-parrot/src/parrot/mcp/local_server.py:129 async def _admit(self, request: dict[str, Any]) -> None: | F040 |
| c104 | verified | packages/ai-parrot/src/parrot/mcp/local_server.py:208 async def _handle_request(self, request: dict[str, Any]) -> dict[str, Any] / None: | F040 |
| c105 | verified | packages/ai-parrot/src/parrot/mcp/server_base.py:111 async def handle_tools_call(self, params: dict[str, Any]) -> dict[str, Any]: | F040 |
| c106 | verified | packages/ai-parrot/src/parrot/mcp/server_base.py:48 class LocalServerConfig: | F040 |
| c107 | verified | packages/ai-parrot/src/parrot/mcp/oauth.py:22 class TokenStore: | F041 |
| c108 | verified | packages/ai-parrot/src/parrot/mcp/oauth.py:48 def _key(user_id: str, server_name: str) -> str: | F041 |
| c109 | verified | packages/ai-parrot/src/parrot/mcp/oauth.py:81 def _vault_name(user_id: str, server_name: str) -> str: | F041 |
| c110 | verified | packages/ai-parrot/src/parrot/mcp/oauth.py:168 class NetSuiteM2MAuth: | F041 |
| c111 | verified | packages/ai-parrot-server/src/parrot/mcp/transports/http.py:221 async def _setup_oauth2(self) -> None: | F041 |
| c112 | verified | packages/ai-parrot/src/parrot/auth/oauth2/mcp_provider.py (152 lines) | F042 |
| c113 | verified | packages/ai-parrot/src/parrot/auth/oauth2/mcp_provider.py — `imports` is a descriptive label, file exists | F042 |
| c114 | verified | packages/ai-parrot/src/parrot/auth/oauth2/mcp_provider.py:36 class MCPOAuth2Provider(OAuth2Provider): | F042 |
| c115 | verified | packages/ai-parrot/src/parrot/auth/oauth2/mcp_provider.py:125 def register_mcp_oauth2_provider( | F042 |
| c116 | verified | packages/ai-parrot-tools/src/parrot_tools/jira_cli.py — `imports` is a descriptive label, file exists | F043 |
| c117 | verified | packages/ai-parrot-tools/src/parrot_tools/jira_cli.py:42 def parse_pasted_redirect(text: str) -> Tuple[str, Optional[str]]: | F043 |
| c118 | verified | packages/ai-parrot-tools/src/parrot_tools/jira_cli.py:283 def auth(site, scopes, env_file, client_id, client_secret, redirect_uri, allow_bare_code) -> None: | F043 |
| c119 | verified | packages/ai-parrot-tools/src/parrot_tools/jira_cli.py (428 lines) | F043 |
| c120 | verified | packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:1316 async def _pre_execute(self, tool_name: str, /, **kwargs) -> None: | F043 |
| c121 | verified | sdd/tasks/completed/TASK-1685-cli-devicecode-bootstrap.md (217 lines) | F044 |
| c122 | verified | packages/ai-parrot/src/parrot/tools/manager.py (3038 lines) | F044 |
| c123 | verified | packages/ai-parrot/src/parrot/bots/abstract.py:1601 async def configure(self, app=None) -> None: | F044 |
| c124 | verified | packages/ai-parrot/src/parrot/auth/identity.py:75 def to_canonical(raw_identity: Dict[str, Any]) -> Optional[str]: | F044 |
| c125 | verified | packages/ai-parrot/tests/cli/test_identity.py — `module` is a descriptive label, file exists | F045 |
| c126 | verified | packages/ai-parrot/tests/cli/test_agent_command.py — `module` is a descriptive label, file exists | F045 |
| c127 | verified | packages/ai-parrot/tests/cli/test_integration.py:247 class TestAgentREPLSend: | F045 |
| c128 | verified | packages/ai-parrot/tests/integration/test_cli_devicecode_e2e.py (208 lines) | F045 |
| c129 | verified | tests/mcp/test_local_cli.py:192 def test_serve_path_stub_toolkit(monkeypatch, tmp_path): | F045 |
| c130 | verified | packages/ai-parrot/tests/mcp/test_local_server.py — `module` is a descriptive label, file exists | F045 |
| c131 | verified | tests/mcp/test_oauth2_e2e.py:276 class TestVaultMCPTokenStorageRoundTrip: | F045 |
| c132 | verified | packages/ai-parrot-integrations/tests/agentd/test_e2e.py:188 async def test_mcp_stdio_ask_agent(self, echo_daemon): | F045 |
| c133 | verified | packages/ai-parrot-server/tests/mcp/test_principal_resolution.py — `module` is a descriptive label, file exists | F045 |
| c134 | verified | packages/ai-parrot-tools/tests/unit/test_oauth2_local_wiring.py:35 async def test_toolkit_runs_without_permission_context(self) -> None: | F045 |
| c135 | verified | sdd/specs/new-ui-cli-agents.spec.md (1508 lines) | F046 |
| c136 | verified | sdd/specs/console-cli-agents.spec.md (571 lines) | F046 |
| c137 | verified | sdd/specs/agent-cli-daemon.spec.md (617 lines) | F046 |
| c138 | verified | sdd/specs/expose-toolkits-as-local-mcp.spec.md (710 lines) | F046 |
| c139 | verified | sdd/specs/mcp-server-oauth2-support.spec.md (671 lines) | F046 |
| c140 | verified | sdd/tasks/index/mcp-as-agent.json (261 lines) | F046 |
| c141 | verified | sdd/specs/o365-auth-homologation.spec.md (451 lines) | F046 |
| c142 | verified | sdd/specs/jiratoolkit-upgrades.spec.md (592 lines) | F046 |
