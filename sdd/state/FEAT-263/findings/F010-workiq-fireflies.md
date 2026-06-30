# F010 — work-iq tool absent; fireflies is MCP-based (SCOPE-DEFINING)

**Query**: Q016 (grep work-iq / fireflies across packages)
**Verdict**: work-iq ABSENT; fireflies = MCP integration, not native toolkit.

- `work.iq|workiq|WorkIQ|work_iq`: **ZERO matches** in any package. The flagship tool of the brainstorm does not exist.
- `fireflies`: matches only under `parrot/mcp/*` (`integration.py`, `filtering.py`, `client.py`, `registry.py`), `bots/agent.py`, and telegram MCP (`mcp_commands.py`, `wrapper.py`). No native `FirefliesToolkit`.
- Telegram already has MCP credential persistence: `integrations/telegram/mcp_persistence.py` (`vault_credential_name`, per-user MCP server config) and `post_auth_jira.py` (nonce→callback→`VaultTokenSync.store_tokens`).
- Jira: native path exists — `auth/jira_oauth.py`, `auth/oauth2/jira_provider.py`, `tools/jira_connect_tool.py`, `bots/jira_specialist.py`.

**Implication**: Resolves OQ#6 — **fireflies is consumed via MCP**, so its auth surface is MCP-credential/MCP-OAuth (telegram's `mcp_persistence` is the precedent), not a bespoke api-key form. work-iq must be BUILT as a tool (OBO via F009). Of the three tools: jira = mostly reuse, fireflies = MCP-credential reuse, work-iq = greenfield.
