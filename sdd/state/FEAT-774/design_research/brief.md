<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
S-4 gives CLI-run agents and the stdio MCP toolkit servers that Claude Code / Codex launch a **Navigator-keyed principal** and a way to **use FEAT-773 connections from outside the server process**. Research shows the CLI has three identity regimes today and none is a Navigator `user_id`: `parrot agent` standalone uses `--user` or the literal `cli-user` (`parrot/cli/agent_repl.py::_run`), `--server` mode sends a hand-supplied bearer (`cli/loaders.py::ServerAgentProxy`), and `parrot/cli/identity.py::build_cli_permission_context` builds an Entra-keyed `channel="cli"` context only for O365 device-code bots. Stdio toolkit servers (`parrot/mcp/toolkit_server.py::create_toolkit_mcp_server`, `local_cli.py::mcp_local`, `local_server.py::StdioMCPServer`) carry no principal, broker or vault, and FEAT-485 forbids them from importing server code. Two precedents carry most of the design: agentd's connection-time principal binding (`agentd/server.py::JsonRpcUnixServer._resolve_identity`) and the FEAT-696 CLI 3LO flow (`parrot_tools/jira_cli.py::auth` + `jira_local_auth.py`), which is manual-paste, single-user `local:cli` and Jira-only. The recommendation is a `/sdd-spec FEAT-774` after FEAT-773 merges: `parrot login` (browser/device) as the principal source, a `CliPrincipalResolver`, an encrypted local token cache synced from the server, principal binding at stdio-server start, `parrot connect` with poll + paste completion, a generic RFC 8628 device-code engine, and agentd mapping through the per-OS-user login file.

---

Origin:
S-4 of FEAT-773: CLI-based agents (AgentREPL, agent daemon) and MCP-based tools in a CLI
(parrot mcp-local stdio servers for Claude Code / Codex) consuming delegated-auth connections.
See sdd/specs/delegated-auth-connections.spec.md §1 Non-Goals S-4 bullet and
sdd/proposals/delegated-auth-connections.proposal.md §6 S-4 row.

### Constraints and goals
- **Lean stdio servers.** Never import ai-parrot-server, aiohttp-server or navconfig; stdout is the JSON-RPC channel.
  *Implication*: the CLI-side credential resolver is an aiohttp-client-only module in parrot core, imported under the existing stderr redirect; connect prompts are returned as an `AuthRequiredPayload` tool result or written to stderr, never printed like the O365 `prompt_callback`. *Evidence*: F031, F007, F016, F023
- **No principal on `tools/call`.** Claude Code / Codex send only tool name and arguments.
  *Implication*: a stdio server's principal is bound at process start from the login file (located via env written by `hosts.py` entries), mirroring agentd's connection-time binding. *Evidence*: F040, F015, F008, F017
- **S-1 fixes the contracts.** `Principal(user_id=Navigator id, channel ∈ {web, telegram, slack, msteams, a2a, cli})`, `AuthRequiredPayload` with `user_code` / `verification_uri` / `expires_in`, `OAuth2ProviderDescriptor` without a device-authorization endpoint.
  *Implication*: S-4 adds a CLI `PrincipalResolver` and a `device_authorization_url` descriptor field — never a parallel principal model. *Evidence*: F033
- **Every broker resolver kind needs in-process deps.** CLI, `parrot.mcp` and agentd never build a `CredentialBroker`; stdio servers never run `AbstractBot.configure()`.
  *Implication*: out-of-process consumers need a new resolver backed by the local encrypted cache + server API; the `ToolManager` seam (`set_broker` :517, injection :2178-2183) is reused, not re-implemented. *Evidence*: F024, F005, F016, F044, F047, F002
- **The Navigator `user_id` is produced server-side.** Session userdata / `resolve_user_id` behind navigator-auth; the IdP `sub` behind external introspection; the CLI's only server-authenticated identity is the hand-supplied bearer and no `parrot login` exists.
  *Implication*: the CLI identity endpoint sits behind navigator-auth session or bearer auth, not behind the `OAUTH2_EXTERNAL` MCP mount; local Entra/OS mapping cannot yield the Navigator id. *Evidence*: F009, F025, F049, F029, F035, F006
- **FEAT-696 precedent.** `parrot jiratoolkit auth`: manual paste with `hmac.compare_digest` state check, `~/.parrot/jira/settings.local.json` 0600 + lock file, consumed under `local:cli`; it imports `parrot.auth.jira_oauth` helpers that S-1 M7 rewrites.
  *Implication*: S-4 generalizes this flow to any descriptor provider, keys it by principal, and must re-verify the Jira helpers after FEAT-773 merges. *Evidence*: F043, F048
- **agentd principal model.** OS username per UDS connection (SO_PEERCRED), service-identity fallback, forwarded on every RPC; `build_principal_context` defaults `tenant_id` to the principal.
  *Implication*: agentd reads the peer OS user's login file (U5); every CLI resolver passes the real tenant explicitly. *Evidence*: F003, F026, F034
- **Device code is O365-only.** No RFC 8628 engine; `MCPOAuth2GrantType` has two grants.
  *Implication*: the generic engine (U4) is new work surfaced through the existing `AuthRequiredPayload` device fields. *Evidence*: F010, F023, F021
- **Surface in flight.** Local-MCP files had a hotfix on 2026-10-28; `tools/manager.py` anchors cited by TASK-1685 were stale.
  *Implication*: S-4 edit sites are re-anchored at spec time. *Evidence*: F037, F044, F047
- **Third key family.** MCP client-side token stores (`mcp:oauth:*`, `mcp_oauth_*`) and `MCPOAuth2Provider` are the parrot-as-client direction.
  *Implication*: explicit non-goal; "MCP" in S-4 means parrot tools consumed by an external host. *Evidence*: F041, F019, F022, F042

### Recommended option / probable scope
> Decisions U1–U5 (§5) are folded in.

### What's New

- **`parrot login` / `parrot logout`** (U1) — completes a navigator-auth browser or device login and stores a CLI token in a 0600 file under `~/.parrot/` (atomic write + lock file, as `LocalJiraTokenStore` does); `logout` removes it. The CLI's principal source.
- **`CliPrincipalResolver`** — implements the S-1 `PrincipalResolver`: presents the login token to a navigator-auth-authenticated server endpoint, receives the Navigator `user_id` and tenant (via `resolve_user_id`), returns `Principal(channel="cli")` and a `PermissionContext` through `build_principal_context` with the tenant passed explicitly.
- **Encrypted local connection cache** (U2) — `parrot connect` pulls the connected token set from the server into a local encrypted file keyed from the login token; the Identity Vault remains the durable owner; when a token is expired the resolver asks the server to refresh and re-pulls. A new aiohttp-client-only `CredentialResolver` in parrot core reads this cache and feeds the `ToolManager` seam.
- **Principal binding for stdio toolkit servers** — `create_toolkit_mcp_server` resolves the principal and resolver at process start from the login file (located via env written into the `hosts.py` entries, never the token itself); credentialed tools return `AuthRequiredPayload` as the tool result for the host to show.
- **Connect from the CLI** (U3) — `parrot connect <provider>` and a `/connect <provider>` slash command (registered through `SlashCommandDispatcher.register`) call `start_connect(channel="cli")` through the server API, print/open the authorize URL, poll `GET /api/v1/connections` until the connection appears; the paste fallback posts the redirected URL's code to the server (FEAT-696 state check).
- **Generic RFC 8628 device-code engine** (U4) — `device_authorization_url` on the S-1 descriptor and a poller that surfaces `user_code` / `verification_uri` / `expires_in` through `AuthRequiredPayload`; `CommandContext.suspend()` yields the terminal for the prompt.
- **agentd principal mapping** (U5) — `JsonRpcUnixServer._resolve_identity` reads the peer OS user's `~/.parrot` login file and resolves the Navigator principal through the same `CliPrincipalResolver`; service identity remains the fallback.

### What Changes

- **`packages/ai-parrot/src/parrot/cli/agent_repl.py`::`_run`** — build the permission context from `CliPrincipalResolver` for every agent, not only O365 device-code bots. *Evidence*: F001, F013
- **`packages/ai-parrot/src/parrot/cli/identity.py`::`build_cli_permission_context`** — generalize or retire the `O365_PRINCIPAL`-only bootstrap; the Entra id becomes `Principal.canonical_identity`, not the key. *Evidence*: F002
- **`packages/ai-parrot/src/parrot/cli/session.py`::`TurnRunner._identity_kwargs`** — unchanged shape; receives a Navigator-keyed context. *Evidence*: F028
- **`packages/ai-parrot/src/parrot/mcp/toolkit_server.py`::`create_toolkit_mcp_server`** — inject principal + cache-backed resolver into the toolkit under the stderr redirect. *Evidence*: F016
- **`packages/ai-parrot/src/parrot/mcp/local_cli.py`::`mcp_local`** — locate the login file; no secrets in argv. *Evidence*: F014
- **`packages/ai-parrot/src/parrot/mcp/hosts.py`::`HostAdapter`** — host entries carry the env needed to locate the login file. *Evidence*: F018, F008
- **`packages/ai-parrot/src/parrot/cli/commands.py`::`SlashCommandDispatcher`** — `/connect`, `/connections` built-ins. *Evidence*: F027
- **`packages/ai-parrot-integrations/src/parrot/integrations/agentd/server.py`::`JsonRpcUnixServer._resolve_identity`** — add the login-file → Navigator step before the service-identity fallback. *Evidence*: F003, F026
- **`packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`::`JiraToolkit._pre_execute`** — replace the fixed `local:cli` identity with the principal-keyed path. *Evidence*: F043
- **`packages/ai-parrot-tools/src/parrot_tools/jira_cli.py`::`auth`** — fold into the generic `parrot connect` flow (paste kept as the fallback). *Evidence*: F043
- **`packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py`** — becomes one provider of the generic device-code engine; `prompt_callback` output moves off stdout. *Evidence*: F010, F023
- **`packages/ai-parrot-server/src/parrot/mcp/principal_guard.py`::`resolve_principal`** (reuse) — pattern for the new CLI identity endpoint; no behavior change. *Evidence*: F009, F025

### What's Untouched (Non-Goals)

- MCP client-side OAuth (`parrot.mcp.oauth` TokenStore trio, `VaultMCPTokenStorage`, `MCPOAuth2Config`, `MCPOAuth2Provider`) — parrot-as-client direction.
- HTTP MCP server PBAC guard, session store and transports (FEAT-477).
- agentd UDS transport and SO_PEERCRED binding itself (only the login-file step is added).
- FEAT-485 stdout-purity and lean-import rules; the Claude Code / Codex permission prompt stays the human gate.
- S-1 internals: `AbstractOAuth2Manager`, `CredentialStore`, `IntegrationsService`, `ConnectionsHandler` (consumed over HTTP, extended only by the identity and token-pull endpoints).

### Patterns to Follow

- agentd connection-time principal binding with fallback and `identity_source` audit. *Evidence*: F003, F026
- `principal_guard`: bearer → `build_principal_context`, fail-closed tenant, `_pctx_var` publication. *Evidence*: F009, F025
- FEAT-696 manual-paste 3LO with `hmac.compare_digest` state check; `~/.parrot/<x>/settings.local.json` written atomically with 0600 + lock file. *Evidence*: F043, F048
- O365 resolver `prompt_callback` injection and cache-hit / refresh / flow ladder. *Evidence*: F023
- FEAT-485 lazy import under `redirect_stdout(stderr)` for anything that may print. *Evidence*: F016, F031
- `TurnRunner._identity_kwargs` as the only identity injection point into `bot.ask`. *Evidence*: F028

### Integration Risks

- **Provider tokens on the laptop.** The encrypted cache holds a token set outside the Identity Vault. *Mitigation*: key derived from the login token, 0600 file, refresh only through the server, `parrot logout` wipes the cache, audit event on every pull. *Evidence*: F048, F031
- **stdout corruption in stdio servers.** *Mitigation*: `AuthRequiredPayload` as tool result; stderr for everything else. *Evidence*: F023, F031, F040
- **Anchors in flight.** S-1 M7 rewrites `parrot.auth.jira_oauth` helpers that `jira_cli.py` imports; local-MCP files have a hotfix from 2026-10-28; `tools/manager.py` anchors moved. *Mitigation*: write S-4 after FEAT-773 merges; re-verify at spec time. *Evidence*: F043, F037, F047
- **`build_principal_context` tenant default.** *Mitigation*: the CLI resolver always passes the server-returned tenant. *Evidence*: F034
- **Two MCP test trees.** *Mitigation*: new tests next to the surface; list both trees in the validation contract. *Evidence*: F045

---

### Verified code anchors (paths only — open them yourself)
packages/ai-parrot/src/parrot/cli/agent_repl.py
packages/ai-parrot/src/parrot/cli/identity.py
packages/ai-parrot/src/parrot/cli/session.py
packages/ai-parrot/src/parrot/cli/loaders.py
packages/ai-parrot/src/parrot/cli/commands.py
packages/ai-parrot/src/parrot/mcp/toolkit_server.py
packages/ai-parrot/src/parrot/mcp/local_cli.py
packages/ai-parrot/src/parrot/mcp/local_server.py
packages/ai-parrot/src/parrot/mcp/server_base.py
packages/ai-parrot/src/parrot/mcp/toolkit_config.py
packages/ai-parrot/src/parrot/mcp/hosts.py
packages/ai-parrot-integrations/src/parrot/integrations/agentd/server.py
packages/ai-parrot-integrations/src/parrot/integrations/agentd/config.py
packages/ai-parrot-server/src/parrot/mcp/principal_guard.py
packages/ai-parrot-server/src/parrot/mcp/transports/base.py
packages/ai-parrot/src/parrot/auth/permission.py
packages/ai-parrot/src/parrot/auth/session_identity.py
packages/ai-parrot/src/parrot/auth/broker/factory.py
packages/ai-parrot/src/parrot/tools/manager.py
packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py
packages/ai-parrot-tools/src/parrot_tools/jira_cli.py
packages/ai-parrot-tools/src/parrot_tools/jira_local_auth.py
packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
packages/ai-parrot/src/parrot/mcp/oauth.py
packages/ai-parrot/src/parrot/auth/oauth2/mcp_provider.py
sdd/specs/delegated-auth-connections.spec.md
sdd/specs/expose-toolkits-as-local-mcp.spec.md

### Questions still open in the exploration document
- [ ] **Login token shape** — what navigator-auth issues to `parrot login` (session token, long-lived API key, or a dedicated CLI grant) and how the server-side identity endpoint introspects it. — *Owner*: Jesus (navigator-auth side)
- [ ] **Cache encryption key derivation** — HKDF from the login token vs an OS keyring; behaviour when the login token rotates. — *Owner*: tbd (spec §2)
- [ ] **Token-pull endpoint policy** — PBAC action (`integration:use`?), audit event, whether the refresh token is ever included in the pulled set or only access tokens with server-side refresh. — *Owner*: Jesus
- [ ] **Which providers get `device_authorization_url` first** (Microsoft, Google) and how Atlassian (no device grant) falls back to poll + paste. — *Owner*: implementer of the descriptor work

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
