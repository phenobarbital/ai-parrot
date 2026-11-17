---
id: FEAT-774
title: "S-4 of FEAT-773: CLI-based agents and MCP-based tools in a CLI consuming delegated-auth connections"
slug: connections-cli-local-mcp
type: feature
mode: enrichment
status: accepted
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-10-30
  summary_oneline: "S-4 of FEAT-773: CLI-based agents and MCP-based tools in a CLI consuming delegated-auth connections"
overall_confidence: medium
base_branch: dev
projects: [ai-parrot, ai-parrot-tools, ai-parrot-integrations, ai-parrot-server, docs]
tags: [oauth2, connections, cli, mcp-local, stdio, agentd, device-code, principal]
research_state: sdd/state/FEAT-774/
depends_on: [FEAT-773]
created: 2026-10-30
updated: 2026-10-30
---

# FEAT-774 — Connections for CLI agents and local MCP toolkits (S-4 of FEAT-773)

> **Mode**: enrichment
> **Confidence**: medium (localization high; scope medium until U1–U5 — now resolved in §5)
> **Source**: `inline` — the S-4 bullet added to the FEAT-773 spec on 2026-10-30
> **Audit**: [`sdd/state/FEAT-774/`](../state/FEAT-774/)
> **Depends on**: FEAT-773 (`sdd/specs/delegated-auth-connections.spec.md`, S-1) being merged — every contract below (`Principal`, `PrincipalResolver`, `CredentialStore`, `AuthRequiredPayload`, `/api/v1/connections*`) is defined there.

---

## 0. Origin

The original request, preserved verbatim. The full source is at `sdd/state/FEAT-774/source.md`.

> S-4 of FEAT-773: CLI-based agents (AgentREPL, agent daemon) and MCP-based tools in a CLI
> (parrot mcp-local stdio servers for Claude Code / Codex) consuming delegated-auth connections.
> See sdd/specs/delegated-auth-connections.spec.md §1 Non-Goals S-4 bullet and
> sdd/proposals/delegated-auth-connections.proposal.md §6 S-4 row.

**Initial signals** (extracted, not interpreted):
- Verbs: "consuming", "connecting" → feature-shaped (enrichment)
- Named entities: AgentREPL, agent daemon (agentd), `parrot mcp-local`, `StdioMCPServer`, Claude Code, Codex, `PrincipalResolver`, `CredentialStore`, `/api/v1/connections`, `connection.*` bus, `O365_PRINCIPAL`, device code
- Components: `parrot/cli`, `parrot/mcp` (local servers), `parrot/integrations/agentd`, `parrot/auth`, `parrot_tools` (Jira CLI), ai-parrot-server MCP transport
- Acceptance criteria provided: no — the S-1 spec names three gaps (CLI principal, out-of-process connect, out-of-process credential retrieval)

---

## 1. Synthesis Summary

S-4 gives CLI-run agents and the stdio MCP toolkit servers that Claude Code / Codex launch a **Navigator-keyed principal** and a way to **use FEAT-773 connections from outside the server process**. Research shows the CLI has three identity regimes today and none is a Navigator `user_id`: `parrot agent` standalone uses `--user` or the literal `cli-user` (`parrot/cli/agent_repl.py::_run`), `--server` mode sends a hand-supplied bearer (`cli/loaders.py::ServerAgentProxy`), and `parrot/cli/identity.py::build_cli_permission_context` builds an Entra-keyed `channel="cli"` context only for O365 device-code bots. Stdio toolkit servers (`parrot/mcp/toolkit_server.py::create_toolkit_mcp_server`, `local_cli.py::mcp_local`, `local_server.py::StdioMCPServer`) carry no principal, broker or vault, and FEAT-485 forbids them from importing server code. Two precedents carry most of the design: agentd's connection-time principal binding (`agentd/server.py::JsonRpcUnixServer._resolve_identity`) and the FEAT-696 CLI 3LO flow (`parrot_tools/jira_cli.py::auth` + `jira_local_auth.py`), which is manual-paste, single-user `local:cli` and Jira-only. The recommendation is a `/sdd-spec FEAT-774` after FEAT-773 merges: `parrot login` (browser/device) as the principal source, a `CliPrincipalResolver`, an encrypted local token cache synced from the server, principal binding at stdio-server start, `parrot connect` with poll + paste completion, a generic RFC 8628 device-code engine, and agentd mapping through the per-OS-user login file.

---

## 2. Codebase Findings

> All entries are grounded in `sdd/state/FEAT-774/findings/` (46 merged + 3 depth-2 findings, 143 citations probed: 141 verified, 1 stale, 1 missing — `citation_checks.md`).

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot/src/parrot/cli/agent_repl.py` | `_run` | 161-164, 218-221, 238-252 | `parrot agent` entry: chooses loader and identity inputs (`--user` / `cli-user`, `--token`, O365-only permission context) | F001, F013, F006 |
| 2 | `packages/ai-parrot/src/parrot/cli/identity.py` | `build_cli_permission_context` | 72-105 | today's only CLI identity bootstrap: Entra OID/e-mail from `O365_PRINCIPAL`, device-code bots only | F002, F001 |
| 3 | `packages/ai-parrot/src/parrot/cli/session.py` | `TurnRunner._identity_kwargs` | 105-114 | the single point where CLI identity enters `bot.ask` / `ask_stream` | F028, F001 |
| 4 | `packages/ai-parrot/src/parrot/cli/loaders.py` | `ServerAgentProxy.__init__ / headers` | 466-506 | the CLI's only server-authenticated identity: bearer header, `user_id` never sent | F035 |
| 5 | `packages/ai-parrot/src/parrot/cli/commands.py` | `CommandContext.suspend / register / _register_builtins` | 41-65, 131-138, 187-211 | slash-command registry (home for `/connect`) and `suspend()` for foreign prompts | F027 |
| 6 | `packages/ai-parrot/src/parrot/mcp/toolkit_server.py` | `create_toolkit_mcp_server` | 137-141 | stdio toolkit server factory — injection point for principal + credential resolver | F016, F007 |
| 7 | `packages/ai-parrot/src/parrot/mcp/local_cli.py` | `mcp_local` | 139-186, 217-234 | `parrot mcp-local`; no identity/token option; cwd = project root | F014, F040 |
| 8 | `packages/ai-parrot/src/parrot/mcp/local_server.py` | `StdioMCPServer._admit / _handle_request` | 129-141, 208-232 | JSON-RPC stdio dispatch; `tools/call` carries no principal | F015, F040 |
| 9 | `packages/ai-parrot/src/parrot/mcp/server_base.py` | `MCPServerBase.handle_tools_call` | 111-124 | tool name + arguments → `adapter.execute`; nothing identity-related threaded | F040 |
| 10 | `packages/ai-parrot/src/parrot/mcp/toolkit_config.py` | `ToolkitSection / load_toolkits_config` | 20-59, 90-123 | `.parrot/mcp-toolkits.yaml`; `env` is the only secret channel | F017, F007 |
| 11 | `packages/ai-parrot/src/parrot/mcp/hosts.py` | `HostAdapter / reconcile / get_adapter / detect_hosts` | 37-56, 95-98, 167-170, 228-245 | writes Claude `.mcp.json` / Codex `.codex/config.toml` entries (command + env) | F018, F008 |
| 12 | `packages/ai-parrot-integrations/src/parrot/integrations/agentd/server.py` | `JsonRpcUnixServer._resolve_identity` | 323-363 | SO_PEERCRED → OS username → `build_principal_context(channel="agentd")`, service-identity fallback | F003, F026 |
| 13 | `packages/ai-parrot-integrations/src/parrot/integrations/agentd/config.py` | `ServiceIdentityConfig` | 131-166 | agentd fallback identity (`user_id "1001"`, tenant `default`) | F026, F003 |
| 14 | `packages/ai-parrot-server/src/parrot/mcp/principal_guard.py` | `resolve_principal` | 128-175 | bearer / API key → Navigator principal (`channel "mcp"`, fail-closed tenant) | F009, F025 |
| 15 | `packages/ai-parrot-server/src/parrot/mcp/transports/base.py` | `_authenticate_request` | 174-182, 218, 233-267 | fills `request["mcp_user"]`: introspection `sub`, navigator-auth session userdata, or API-key record | F049, F025 |
| 16 | `packages/ai-parrot/src/parrot/auth/permission.py` | `build_principal_context` | 166-188 | shared helper for non-web principals; `tenant_id` defaults to the principal | F034 |
| 17 | `packages/ai-parrot/src/parrot/auth/session_identity.py` | `resolve_user_id` | 90-133 | backend-independent Navigator `user_id` from a server request/session | F029 |
| 18 | `packages/ai-parrot/src/parrot/auth/broker/factory.py` | `CredentialResolverFactory.build` | 46-76 | obo/oauth2/static_key/mcp/device_code — every kind needs in-process `oauth_manager` or vault | F024 |
| 19 | `packages/ai-parrot/src/parrot/tools/manager.py` | `ToolManager.set_broker` | 389, 515-523, 2178-2183 | the `_broker` / `_cred_channel` / `_cred_user_id` seam S-4 feeds (re-verified; TASK-1685 anchors ~870 lines stale) | F047, F044 |
| 20 | `packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py` | `O365DeviceCodeCredentialResolver._run_device_flow` | 1-7, 73-79, 206-222 | the only device-code engine (MSAL/O365-bound); `prompt_callback` prints to stdout | F010, F023 |
| 21 | `packages/ai-parrot-tools/src/parrot_tools/jira_cli.py` | `auth` | 283-351 | FEAT-696 working CLI 3LO: manual paste, CSRF state, local file store | F043 |
| 22 | `packages/ai-parrot-tools/src/parrot_tools/jira_local_auth.py` | `DEFAULT_SETTINGS_PATH / LocalSettings / LocalJiraTokenStore` | 24-41, 52, 100-106, 155-172 | `~/.parrot/jira/settings.local.json`, 0600 + lock file; `FileTokenCredentialResolver(allowed_channels={cli, local})` | F048, F043 |
| 23 | `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | `JiraToolkit._pre_execute` | 1316-1409 | local single-user mode under the fixed identity `local:cli` | F043 |
| 24 | `packages/ai-parrot/src/parrot/mcp/oauth.py` | `TokenStore / RedisTokenStore._key / VaultTokenStore` | 22-26, 42-49, 63-70 | MCP client-side token caches (`mcp:oauth:{server}:{user}`): third key family, no loopback OAuth | F004, F019, F041 |
| 25 | `packages/ai-parrot/src/parrot/auth/oauth2/mcp_provider.py` | `MCPOAuth2Provider / register_mcp_oauth2_provider` | 36-83, 89-99, 125-152 | remote MCP servers as `mcp:<server>` providers (parrot-as-client direction) | F022, F042 |
| 26 | `sdd/specs/delegated-auth-connections.spec.md` | `Principal (M1)` | 229-236 | S-1 contract: `Principal.channel` includes `cli`; `AuthRequiredPayload` has device-code fields; descriptor lacks `device_authorization_url` | F033 |
| 27 | `sdd/specs/expose-toolkits-as-local-mcp.spec.md` | `Goals / Non-Goals / Data Models / assets` | 41-55, 57-70, 160-179, 219-220 | FEAT-485 constraints: no server/aiohttp/navconfig imports; stdout pure JSON-RPC; host prompt is the human gate | F031 |

### 2.2 Constraints Discovered

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

### 2.3 Recent History (Relevant)

| Commit | When | Author | Message | Touched files |
|--------|------|--------|---------|---------------|
| `b80ea3a98` | 2026-10-28 | Jesus Lara | HOTFIX sdd-coder stdin isolation | `mcp/local_cli.py`, `mcp/local_server.py` |
| `4a79623d6` | 2026-10-26 | Jesus Lara | cli session | `cli/session.py`, `cli/agent_repl.py`, `tests/cli/test_session.py` |
| `094ec8616` | 2026-10-16 | Jesus Lara | TASK-4422 (jiratoolkit-upgrades) — Jira CLI | `cli/__init__.py` |
| `52aa35dcf` | 2026-09-18 | Jesus Lara | TASK-3374 — HostAdapter contract + detect_hosts | `mcp/hosts.py`, `tests/mcp/test_hosts.py` |
| `8fa34ba3a` | 2026-09-18 | Jesus Lara | FEAT-573 review items (REPL, commands, session) | `cli/agent_repl.py`, `cli/commands.py`, `cli/session.py` |
| `6b593db31` | 2026-09-01 | Jesus Lara | TASK-2604 — principal resolution + tenant binding + `_pctx_var` | `mcp/principal_guard.py`, `tests/mcp/test_principal_resolution.py` |
| `9599c44ff` | 2026-08-20 | Jesus | TASK-2286 — agentd caller identity (SO_PEERCRED + service-identity fallback) | `agentd/config.py`, `agentd/server.py`, `tests/agentd/test_caller_identity.py` |
| `44497f159` / `473625b39` | 2026-06-26 | Jesus | TASK-1659/1665 — `MCPOAuth2Config`, MCP client OAuth | `mcp/oauth2_config.py`, `mcp/oauth2_storage.py`, `mcp/oauth.py` |

`cli/identity.py` has not changed in 180 days (frozen at FEAT-266); the MCP client-side OAuth files have not changed since 2026-06-26; the server-side principal guard has not changed since 2026-09-01. *Evidence*: F036, F037, F038, F039, F004

---

## 3. Probable Scope  *(mode = enrichment)*

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

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | The only CLI identity today is `--user` / `cli-user`, a hand-supplied bearer, or an Entra id from `O365_PRINCIPAL` for device-code bots; none is a Navigator `user_id` | F001, F013, F006, F002, F035 | high | direct reads + grep |
| C2 | No `parrot login` / auth command exists | F006, F027 | high | grep over cli entry, commands, session |
| C3 | Stdio toolkit servers carry no principal, broker or vault; secrets only via `ToolkitSection.env` | F040, F015, F016, F007, F017, F005 | high | full reads + grep absence |
| C4 | agentd binds an OS-username principal per connection with a service-identity fallback | F003, F026, F038 | high | read of server/config + TASK-2286 commit |
| C5 | `parrot.mcp` has no loopback/webbrowser OAuth; its token stores are parrot-as-client caches needing Redis or the vault | F004, F019, F020, F041 | high | grep + reads |
| C6 | Device code is O365-only; no RFC 8628 engine | F010, F023, F021 | high | read of resolver, grep of o365_oauth, two grant types |
| C7 | `principal_guard.resolve_principal` is the existing bearer → Navigator principal path | F009, F025, F039 | high | read |
| C8 | Every broker resolver kind requires in-process `oauth_manager` or vault deps | F024 | high | read of factory |
| C9 | FEAT-696 `parrot jiratoolkit auth` is a working CLI 3LO flow under the fixed identity `local:cli` | F043 | high | wiki + confirming reads |
| C10 | S-1 contracts admit `channel="cli"` and device-code fields; descriptor lacks a device endpoint | F033 | high | read of S-1 spec |
| C11 | CLI identity frozen at FEAT-266; local-MCP surface has a 2026-10-28 hotfix | F036, F037 | high | git log |
| C12 | `hosts.py` entries (command + env) are the only process-start channel for binding identity into a stdio server | F008, F018, F031 | medium | installers not read |
| C13 | The `ToolManager` seam (`set_broker` :517, injection :2178-2183) is the reusable path; injection only when a broker is set | F047, F044, F002 | high | re-grepped |
| C14 | Which identity a CLI token yields depends on the auth method: navigator-auth session (Navigator family) vs external introspection `sub` | F049, F025, F029 | high | read of transports/base.py |
| C15 | Generalizing FEAT-696's flow, keyed by principal and synced through S-1, covers connect-from-CLI without a loopback listener | F043, F033, F027 | medium | design inference |
| C16 | A FEAT-485-compliant stdio server cannot reach the Identity Vault; it needs either a server-vended token or a local cache | F031, F024, F020, F040 | medium | follows from lean-import rule; U2 chose the cache |
| C17 | agentd callers map to a Navigator user only via a login-file or envelope step | F003, F026, F032 | medium | inferred; U5 chose the login file |
| C18 | No existing test covers a per-user credential inside a stdio toolkit server | F012, F045 | low | absence from the test map |

Distribution: **13** high, **4** medium, **1** low. Overall **medium** = min(median high, localization high, scope medium).

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **U1 — How does a CLI user obtain the login token that yields the Navigator user_id?** — *Resolved*: `parrot login` (browser/device): a new `parrot login` completes a navigator-auth browser or device login and stores a CLI token in a 0600 file under `~/.parrot/`; `parrot logout` removes it.
  *Resolves claims*: C1, C2, C14
- [x] **U2 — How do stdio MCP toolkit servers inside Claude Code / Codex get provider tokens?** — *Resolved*: local encrypted token file, as an encrypted cache synced from the server: the server completes the 3LO and the Identity Vault stays the durable owner; `parrot connect` pulls the token set into a local encrypted file (key derived from the login token); refresh goes through the server when expired.
  *Resolves claims*: C3, C16
- [x] **U3 — How does a CLI connect complete?** — *Resolved*: poll + paste fallback: print/open the authorize URL and poll `GET /api/v1/connections` until the connection appears; when the browser cannot reach back (SSH), paste the redirected URL and the CLI posts the code to the server.
  *Resolves claims*: C15
- [x] **U4 — Generic RFC 8628 device code in S-4?** — *Resolved*: generic engine in S-4: add `device_authorization_url` to the S-1 descriptor and an RFC 8628 poller surfaced through the `AuthRequiredPayload` device fields (Microsoft, Google).
  *Resolves claims*: C6, C10
- [x] **U5 — Is agentd in S-4 scope?** — *Resolved*: yes, per-OS-user login file: the daemon resolves the peer's OS user (SO_PEERCRED) and reads that user's `~/.parrot` login file to obtain the Navigator principal.
  *Resolves claims*: C4, C17

### Unresolved (defer to spec / implementation)

- [ ] **Login token shape** — what navigator-auth issues to `parrot login` (session token, long-lived API key, or a dedicated CLI grant) and how the server-side identity endpoint introspects it. — *Owner*: Jesus (navigator-auth side)
  *Blocks claims*: C14
- [ ] **Cache encryption key derivation** — HKDF from the login token vs an OS keyring; behaviour when the login token rotates. — *Owner*: tbd (spec §2)
- [ ] **Token-pull endpoint policy** — PBAC action (`integration:use`?), audit event, whether the refresh token is ever included in the pulled set or only access tokens with server-side refresh. — *Owner*: Jesus
- [ ] **Which providers get `device_authorization_url` first** (Microsoft, Google) and how Atlassian (no device grant) falls back to poll + paste. — *Owner*: implementer of the descriptor work

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-774`** — *Rationale*: localization and constraints are high-confidence, the S-1 contracts fix the shape, and U1–U5 are decided; the spec can be written as soon as FEAT-773 merges to `dev`, re-verifying the anchors in the in-flight local-MCP files and the rewritten Jira helpers.

Sequencing: `/sdd-done FEAT-773` → merge → `/sdd-spec FEAT-774` (this proposal is picked up by slug; the spec reuses FEAT-774 via `reuse_feature_id` or lets `/sdd-spec` keep this id).

### Alternatives

- **`/sdd-brainstorm FEAT-774`** — if the U2 cache design (tokens on the laptop) should be weighed against a server-vended-token-only design before specifying.
- **Manual review** — not indicated; research completed within budget.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-774/state.json` |
| Source (raw) | `sdd/state/FEAT-774/source.md` |
| Research plan | `sdd/state/FEAT-774/research_plan.json` (52 queries) |
| Findings (digests) | `sdd/state/FEAT-774/findings/F001-*.md` … `F049-*.md` (lane originals in `findings/.audit/`) |
| Citation checks | `sdd/state/FEAT-774/citation_checks.md`, `probe_sheet.json`, `probes/report_*.json` |
| Synthesis (JSON) | `sdd/state/FEAT-774/synthesis.json` |

**Budget consumed** (default profile):
- Files read: 27 / 40
- Grep calls: 22 / 25
- Git calls: 10 / 10
- Depth reached: 2 / 2
- Truncated: **no**

**Research mode**: parallel lanes (codebase 35 findings, git 5, wiki 12) merged 52 → 46, plus 3 depth-2 follow-ups by the parent. **Mode determination**: `auto` → `enrichment` (additive verbs, no negation).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` (FEAT-708 parallel lanes) |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Jesus Lara (with Claude Fable 5.1) |
