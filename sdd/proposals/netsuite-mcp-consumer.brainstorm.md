---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-server]
tags: [netsuite, mcp, oauth2, dataset-manager, pandas-agent]
---

# Brainstorm: NetSuite MCP Consumer — live-validated MCP driver + DatasetManager sources

**Date**: 2026-11-12
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

NetSuite exposes its data through the **AI Connector Service** (a remote MCP server): reports
(`ns_runReport`), saved searches (`ns_runSavedSearch`, e.g. the search behind
`https://4984231.app.netsuite.com/app/common/search/searchresults.nl?searchid=88796`) and
read-only SuiteQL (`ns_runCustomSuiteQL`).

ai-parrot already carries a NetSuite MCP driver (FEAT-135: Authorization Code + PKCE factory, an
M2M client-credentials variant, a registry entry) and a delegated-credential mode for MCP servers
(FEAT-773). **None of it has ever been run against a real NetSuite account**, and reading the code
shows it cannot work end to end as it stands (see *Known gaps*). Two things are needed:

1. **Part 1 — a working MCP consumer.** A user connects their NetSuite account from the web
   (OAuth2 Authorization Code + PKCE; the NetSuite consent screen is where the *role* is chosen),
   and the NetSuite MCP tools become usable from an agent's `ToolManager`.
2. **Part 2 — a DatasetManager source layer.** A `PandasAgent` names a report id or a saved-search
   id (plus parameters such as `dateFrom`, `dateTo`, `subsidiaryId`) and gets a DataFrame it can
   operate on, without the raw JSON ever passing through the LLM context.

Who is affected: developers building finance/ERP agents; end users asking a PandasAgent questions
about NetSuite reports and searches.

### Known gaps in the existing code (found during research — the answer to "what do we need?")

| # | Gap | Evidence |
|---|---|---|
| G1 | **Web connect flow is not wired for MCP providers.** `IntegrationsService.start_connect` calls `provider.manager.create_authorization_url(...)`, but `MCPOAuth2Provider.manager` returns `None`. `mcp:netsuite` is registered, yet it cannot be connected through `/api/v1/connections`. | `auth/oauth2/service.py:398`, `auth/oauth2/mcp_provider.py` (`manager` property) |
| G2 | **Tool discovery needs a token that delegated mode does not have at connect time.** `ToolManager.add_mcp_server` → `MCPClient.connect()` runs `initialize` + `list_tools()` with no `Authorization` (delegated tokens exist only per call). NetSuite rejects unauthenticated requests, so the agent would register zero tools (or fail to start). | `tools/mcp_mixin.py:57`, `mcp/integration.py` `MCPClient.connect`, `mcp/transports/http.py:346` |
| G3 | **Tool visibility is per role.** NetSuite only lists a tool when the logged-in role has its permissions, so one static tool list per agent is not accurate for every user. | Oracle docs, "Available Tools in the MCP Standard Tools SuiteApp" |
| G4 | **Protocol version.** The HTTP transport offers `protocolVersion: "2024-11-05"`; NetSuite documents `2025-06-18` + Streamable HTTP as required. Negotiation may or may not succeed — unverified. | `mcp/transports/http.py:385`, `:605` |
| G5 | **M2M against the MCP endpoint is undocumented.** Oracle's FAQ lists only Authorization Code + PKCE (public client) for the AI Connector Service. `NetSuiteM2MAuth` (client credentials + certificate, scope `mcp`) may be refused by the MCP endpoint. Only a live test settles it. | `mcp/oauth.py:168`, Oracle FAQ |
| G6 | **Registry entry is pre-delegation.** The `netsuite` `MCPServerDescriptor` still requires a `user_id` param, while delegated mode is `user_id=None` + `credential_provider`. | `mcp/registry.py:226-256` |
| G7 | **Role is invisible to ai-parrot.** Nothing records which role/account a connection was authorized with. `ns_getSessionInfo` (Runtime Tools) can supply it. | — |
| G8 | **DatasetManager cache is keyed by `source.cache_key` only** — not by fetch params, not by user. A NetSuite source whose data depends on `dateFrom`/`dateTo`/`subsidiaryId` *and* on the caller's role would serve one user's (or one period's) frame to another. | `dataset_manager/tool.py:4270-4335` |
| G9 | **`MCPToolProxy` returns text.** `_execute` flattens the MCP result via `_extract_result_text`; a source needs the structured payload, so it must call `MCPClient.call_tool` directly. | `mcp/integration.py:255-300` |

## Constraints & Requirements

- **Identity: both.** Per-user delegated credential (OAuth2 3LO + role) when a user is in session;
  M2M service identity as fallback for user-less jobs — *if* NetSuite accepts it (G5).
- **Transport: the NetSuite MCP tools.** The source calls `ns_runReport` / `ns_runSavedSearch` /
  `ns_runCustomSuiteQL` through the MCP session; no parallel REST client.
- **Registration: both.** Developer pre-registers named datasets (report/search id + default
  params) *and* the LLM can load one ad hoc by id at runtime.
- **Role: one connection per user, role visible.** Store and show the role/account the user
  connected with; switching role = reconnect.
- **DataFrame shape: flat + hierarchy columns.** One row per report line, with hierarchy metadata
  and one column per `reportColumns` entry.
- **Live validation is available**: integration record + client_id, M2M certificate, and a
  non-admin role with MCP permission all exist for account `4984231`. Validation comes first.
- NetSuite-side rules (Oracle docs): Administrator roles are refused; the role needs *MCP Server
  Connection*, *OAuth 2.0 Access Tokens*, *REST Web Services* and (for searches) *Perform Search*;
  the integration record must be a Public Client with Authorization Code Grant, a redirect URI and
  the AI Connector Service scope; scope is fixed to `mcp`.
- Report tool limits (Oracle docs): custom filters and accounting periods are not supported;
  `dateTo` is always required, `dateFrom` for from-to reports; `subsidiaryId` negative = consolidated.
- Repo rules: aiohttp only, async-first, Pydantic v2, no secrets in code, tokens never logged or
  placed in LLM-visible kwargs, per-principal isolation (no cross-user cache or session reuse).
- `parrot/clients/base.py` untouched.

---

## Options Explored

### Option A: MCP-backed NetSuite sources on top of a repaired delegated MCP driver

Three phases, each shippable:

- **Phase 0 — live harness.** A scripted, opt-in live check against account `4984231` that walks
  the real flow (authorize → callback → token → `initialize` → `tools/list` → `ns_getSessionInfo` →
  `ns_runReport` 178) for both the delegated and the M2M identity, and records real payloads as
  test fixtures. It answers G4, G5, token/refresh lifetimes and the report/search JSON shapes
  before anything is designed on assumptions.
- **Phase 1 — MCP consumer.** NetSuite becomes a descriptor-backed OAuth2 provider (public client,
  PKCE required, account-templated endpoints, scope `mcp`) so the existing `/api/v1/connections`
  web flow, vault storage, refresh and `AuthRequired` envelope drive it (closes G1). A post-exchange
  step calls `ns_getSessionInfo` and stores role/account on the connection (G7). Tool discovery for
  delegated servers gets an explicit strategy (G2/G3): discover with the M2M identity when
  available, otherwise register from a pinned tool catalog, and let per-call authorization errors
  surface as the standard needs-auth signal. Protocol version and registry entry are corrected
  (G4/G6).
- **Phase 2 — dataset sources.** A NetSuite `DataSource` family (report / saved search / SuiteQL)
  that calls the MCP tools through the agent's MCP client with the caller's credential, normalizes
  the payload to a DataFrame, and owns a cache key that includes the parameters and the identity
  partition (G8). DatasetManager gains a registration method for pre-declared datasets and, only
  when a NetSuite connection is configured, LLM-facing tools to load a report or search by id.

✅ **Pros:**
- One authentication path and one permission model (the NetSuite role) for tools and datasets.
- Reuses FEAT-773 end to end: connections handler, vault, principal partitioning, needs-auth UX.
- Reports are reachable — they exist only through the MCP tools, not through SuiteTalk REST.
- Raw report JSON never enters the LLM context; the agent gets a named DataFrame.
- Phase 0 turns today's unknowns into fixtures; later phases are designed on facts.

❌ **Cons:**
- Depends on NetSuite's MCP tool contract (names, params, payload shape), which Oracle documents
  only partially and may change between SuiteApp versions.
- Tool discovery for delegated servers touches shared MCP machinery (`ToolManager`, HTTP session).
- M2M fallback may turn out impossible (G5); the feature must degrade to delegated-only.

📊 **Effort:** High (Phase 0 Low, Phase 1 Medium, Phase 2 Medium)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiohttp` | MCP Streamable HTTP + OAuth token calls | already in use |
| `pandas` | payload → DataFrame | already in use |
| `pydantic` v2 | report/search payload + param models | already in use |
| `PyJWT` / `cryptography` | M2M `client_assertion` | already used by `NetSuiteM2MAuth` |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/mcp/integration.py` — `create_netsuite_mcp_server`, `create_netsuite_m2m_mcp_server`, `MCPClient.call_tool`, delegated-mode checks
- `packages/ai-parrot/src/parrot/auth/oauth2/descriptor.py` — `OAuth2ProviderDescriptor`, `StandardOAuth2Manager`, post-exchange hook registry
- `packages/ai-parrot/src/parrot/auth/oauth2/service.py` — `IntegrationsService.start_connect` and the generic callback
- `packages/ai-parrot/src/parrot/auth/broker/core.py` — `CredentialBroker.resolve`
- `packages/ai-parrot-server/src/parrot/mcp/transports/http.py` — per-principal session partitions
- `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/base.py` — `DataSource` contract
- `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/smartsheet.py` + `DatasetManager.add_smartsheet_source` — template for an API-backed source and its registration method

---

### Option B: Standalone NetSuite toolkit over SuiteTalk REST / SuiteQL (no MCP)

A `parrot_tools` NetSuite toolkit with its own REST client: SuiteQL through
`/services/rest/query/v1/suiteql`, saved searches and reports through a custom RESTlet deployed in
the account. The DatasetManager source uses that client. The MCP driver is left as is.

✅ **Pros:**
- Independent of the MCP tool contract and of the AI Connector Service's role restrictions.
- M2M (client credentials + certificate) is a documented, first-class path for REST.
- SuiteQL paging is explicit (`limit`/`offset`, `hasMore`).

❌ **Cons:**
- Reports are not exposed by REST; saved searches need a RESTlet — a SuiteScript deployment the
  customer must install and maintain in every account.
- A second auth surface (different scopes: `rest_webservices`, `restlets`) and a second integration record.
- Does not deliver Part 1 at all: the MCP tools still do not work in `ToolManager`.
- Abandons the stated direction (data through the MCP).

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiohttp` | REST / RESTlet calls | already in use |
| SuiteScript 2.1 RESTlet | run reports / saved searches server-side | customer-side deployment |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/mcp/oauth.py` — `NetSuiteM2MAuth` token minting
- `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/base.py` — `DataSource`

---

### Option C: Generic `MCPToolSource` — any MCP tool as a DatasetManager source

Instead of NetSuite-specific sources, add one source type that binds *(MCP server, tool name,
default arguments, result normalizer)*. NetSuite ships as a set of normalizers (hierarchical
report, saved-search rows, SuiteQL rows). Any other MCP server returning tabular JSON becomes a
dataset by configuration. Part 1 is the same as in Option A.

✅ **Pros:**
- Every future data-bearing MCP server (CRM, BI, ticketing) is covered by the same mechanism.
- NetSuite specifics shrink to normalizers and parameter models.

❌ **Cons:**
- Designing a general contract from a single, not-yet-validated consumer invites the wrong abstraction.
- Per-server concerns (paging, parameter validation, hierarchy, identity partitioning of the cache)
  do not generalize cleanly; the generic layer either leaks or grows hooks.
- Harder LLM guidance: a generic "call tool X with args" surface is less self-explanatory than
  "load report N for a date range".

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pandas` | normalizers | already in use |
| `jsonpath-ng` (optional) | declarative row extraction for config-only normalizers | new dependency, avoidable |

🔗 **Existing Code to Reuse:**
- same as Option A, plus `packages/ai-parrot/src/parrot/tools/mcp_mixin.py` (`_mcp_clients` lookup by server name)

---

### Option D: No new source — the LLM calls the MCP tool and imports the result (unconventional)

Fix Part 1 only. The PandasAgent calls `mcp_netsuite_ns_runReport` itself; a small bridge lets it
register a previous tool result as a DataFrame (the working-memory toolkit already has an
"import from tool" notion). DatasetManager is not extended.

✅ **Pros:**
- Smallest change; nothing NetSuite-specific in DatasetManager.
- Works immediately for any MCP tool.

❌ **Cons:**
- The full report JSON goes through the tool result and the LLM context — large reports blow the
  context budget and get pruned/offloaded by compaction before they can be imported.
- No pre-registered catalog, no schema, no caching, no routing metadata for dataset selection.
- Hierarchy normalization is left to LLM-written pandas code, different on every run.
- Fails the stated requirement (developer pre-registration of datasets).

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| — | — | no new packages |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/mcp/integration.py` — `MCPToolProxy`
- `packages/ai-parrot/src/parrot/tools/working_memory/` — tool-result import

---

## Recommendation

**Option A** is recommended because:

- It is the only option that satisfies every decision taken in discovery: MCP transport, both
  identities, both registration modes, role visible, flat-plus-hierarchy frames.
- Reports — the user's primary example — are reachable only through the MCP tools, which rules out
  B as the main path, and D fails on payload size and on pre-registration.
- C's generalization is attractive but premature: the first consumer has never run. Option A keeps
  the seam cheap (a source that takes a tool name, arguments and a normalizer internally) so that
  promoting it to a generic `MCPToolSource` later is a refactor, not a redesign.
- Phase 0 is deliberately first. Several gaps (G4, G5, token lifetimes, payload semantics) cannot
  be resolved by reading code or Oracle's docs; the credentials to test them exist today.

What is traded off: coupling to an under-documented vendor tool contract (mitigated by recorded
fixtures and a pinned tool catalog), and a change to shared MCP discovery machinery (mitigated by
making the delegated-discovery strategy opt-in per server config).

If Phase 0 shows that M2M is refused by the MCP endpoint, the feature ships delegated-only and the
M2M fallback moves to a follow-up using Option B's REST path for SuiteQL only.

---

## Feature Description

### User-Facing Behavior

- **Connecting.** In the web UI a user opens Connections, picks *NetSuite* and is sent to
  NetSuite's login/consent page, where they choose the **role** to authorize. On return the
  connection shows as connected, with the account id and the role name. Asking an agent for
  NetSuite data without a connection yields the standard "authorization required" prompt with a
  connect link; after connecting, the request can be retried. Choosing an Administrator role, or a
  role without the MCP permission, produces a clear message naming the missing requirement.
  Switching role means disconnect + reconnect.
- **Tools.** An agent configured with the NetSuite MCP server exposes the NetSuite tools
  (`mcp_netsuite_ns_*`) in its `ToolManager`; each call runs as the calling user and role.
  Developers can restrict the set with the existing allowed/blocked tool lists (e.g. read-only).
- **Datasets — pre-registered.** A developer declares named datasets on the agent's
  DatasetManager: a report id, a saved-search id, or a SuiteQL statement, with default parameters
  and a description. They appear in the dataset catalog like any other source; the PandasAgent
  fetches them, optionally overriding parameters (`dateFrom`, `dateTo`, `subsidiaryId`, …).
- **Datasets — ad hoc.** When NetSuite is configured, the PandasAgent also has tools to load a
  report or a saved search by id ("bring report 178 for October, subsidiary 5") and to list the
  available reports, saved searches and subsidiaries so it can resolve names to ids.
- **Result.** A DataFrame. For a report: one row per report line with `line_id`, `label`, `alias`,
  `parent_id`, `parent_label`, `level`, `is_detail`, `is_summary`, `is_opening`, plus one column per
  report column; report `title` and `currency` travel as dataset metadata. For a saved search or
  SuiteQL: one row per result row. An empty report (as in the example payload, a single header
  line with null totals) yields a valid, correctly-typed frame and a "no data for these
  parameters" note rather than an error.

### Internal Behavior

- **Provider.** NetSuite is described as an OAuth2 provider descriptor (public client, PKCE
  required, scope `mcp`, endpoints templated by account id). The descriptor-backed manager gives
  `IntegrationsService` a real manager for `start_connect` / callback / refresh / revoke; tokens
  land in the Identity Vault keyed by principal. The MCP server config for NetSuite points its
  `credential_provider` at this provider.
- **Role capture.** After the code exchange, a post-exchange step opens an MCP session with the
  new token, calls `ns_getSessionInfo` and stores role/account identifiers on the connection row.
- **Discovery.** On agent start, a delegated NetSuite server discovers tools with the service
  identity when one is configured; otherwise it registers proxies from a pinned catalog captured
  by the live harness. A tool a user's role cannot see fails at call time with a permission error
  that is reported as such (not as "tool not found").
- **Calls.** Tool calls keep the FEAT-773 path: the broker resolves the caller's credential, the
  bearer is injected per call, and the HTTP session partitions MCP sessions per credential.
- **Sources.** A NetSuite source holds: kind (report / search / suiteql), the object id or
  statement, default params, and a reference to the agent's NetSuite MCP client. `fetch(**params)`
  merges defaults with overrides, validates them against a param model, resolves the caller's
  credential (delegated first, service identity as fallback when allowed), calls the tool directly
  on the MCP client to get the structured result, and hands the payload to a normalizer.
  Saved searches page with `range_start` / `range_end` until exhausted or a row cap is reached.
- **Schema.** `prefetch_schema()` stays cheap: reports resolve columns from `ns_listAllReports`
  metadata when available, else schema is unknown until first fetch (the base-class default).
- **Caching.** The source's cache key includes kind, id, a hash of the effective params and an
  identity partition (role/account for delegated, a fixed marker for service identity), so frames
  never cross users or periods. Parameterized fetches always re-fetch on changed params.
- **Policy.** The opaque-source resolver learns the NetSuite source so PBAC/data-plane policies can
  name `netsuite` resources (`report:178`, `search:88796`).

### Edge Cases & Error Handling

- **Not connected / token expired / refresh token expired** → standard needs-auth envelope with the
  NetSuite provider; never a silent fallback from a user identity to the service identity unless
  the dataset explicitly allows it.
- **Administrator role or missing permission** → explicit, user-readable error; connection is not
  stored as healthy.
- **Missing required report filters** (`dateTo`, `subsidiaryId` on subsidiary-aware reports, nexus,
  second book) → validation error listing the missing params and how to obtain valid values
  (`ns_getSubsidiaries` etc.), returned to the LLM as a fixable hint.
- **Unsupported report features** (custom filters, accounting periods, custom-segment columns
  returning nulls) → documented in the dataset guidance; nulls preserved, not coerced to zero.
- **Large results** → row cap + truncation flag on searches/SuiteQL; reports are returned whole.
- **Rate limiting / concurrency limits** → existing `-32429` backoff in `MCPClient.call_tool`;
  beyond the wait cap the fetch fails fast with a retryable classification.
- **Tool result is an error or non-JSON text** → surfaced as a source error with the tool name and
  a truncated message; no partial frame.
- **Duplicate column labels / hierarchical column paths** → columns named from `path`, de-duplicated.
- **Standalone saved-search types** → `type` is required by the tool; the registration accepts it.
- **Account differences** (no subsidiaries, no multi-book) → params optional per account features.

---

## Capabilities

### New Capabilities
- `netsuite-live-harness`: opt-in live validation of the NetSuite MCP flow (delegated + M2M) that records fixtures and the pinned tool catalog.
- `netsuite-oauth2-connection`: NetSuite as a descriptor-backed OAuth2 provider connectable from `/api/v1/connections`, with role/account captured on the connection.
- `mcp-delegated-tool-discovery`: discovery strategy for delegated MCP servers (service-identity discovery or pinned catalog) and protocol-version negotiation fit for NetSuite.
- `netsuite-dataset-sources`: report, saved-search and SuiteQL `DataSource`s with payload normalization, parameter models, paging and identity-partitioned caching.
- `netsuite-dataset-tools`: DatasetManager registration method plus conditional LLM tools to load/list NetSuite reports and searches by id.

### Modified Capabilities
- `netsuite-mcp-integration` (FEAT-135): factories, registry entry and URL/protocol details corrected against the live service.
- `delegated-auth-connections` (FEAT-773): MCP OAuth2 providers gain a working manager for the connect flow.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/mcp/integration.py` | modifies | NetSuite factories; delegated discovery hook |
| `parrot/mcp/registry.py` | modifies | `netsuite` descriptor params for delegated mode |
| `parrot/auth/oauth2/mcp_provider.py` | modifies | provider must expose a real manager (or be replaced by a descriptor provider for NetSuite) |
| `parrot/auth/oauth2/descriptor.py` | depends on | descriptor + post-exchange hook for role capture |
| `parrot/mcp/transports/http.py` (ai-parrot-server) | modifies | protocol version offered; discovery under a credential |
| `parrot/tools/mcp_mixin.py` | modifies | `add_mcp_server` discovery path for delegated servers |
| `parrot/tools/dataset_manager/sources/` | extends | new NetSuite source module (lazy import like other optional sources) |
| `parrot/tools/dataset_manager/tool.py` | extends | registration method; conditional NetSuite tools; cache key use |
| `parrot/tools/dataset_manager/sources/opaque.py` | extends | resource identity for policies |
| `parrot/conf.py` | extends | redirect URI / default role-policy settings if needed |
| Admin UI connections page | depends on | shows role/account; no new screen expected |
| NetSuite account `4984231` | configuration | redirect URI on the integration record; role permissions |

No breaking changes are expected for existing agents. No new runtime dependency.

---

## Code Context

### User-Provided Code

```json
// Source: user-provided — ns_runReport arguments
{
  "reportId": 178,
  "dateFrom": "2026-10-01",
  "dateTo": "2026-10-31",
  "subsidiaryId": 5
}
```

```json
// Source: user-provided — ns_runReport result (empty report, zero data)
{"reportData":{"0":{"label":"Category","alias":null,"isDetailLine":false,"value":null,"parent":null,"summaryLine":null,"openingLine":null,"summaryLineValues":[{"Total":null}]}},"reportColumns":[{"id":"Total","label":"Total","path":"Total"}],"currency":"$","title":"Lead Source Analysis Summary"}
```

Saved-search example (user-provided): `https://4984231.app.netsuite.com/app/common/search/searchresults.nl?searchid=88796&saverun=T&whence=` → `searchId = "88796"`, account `4984231`.

### Verified Codebase References

All paths are relative to `packages/ai-parrot/src/` unless another package is named.

#### Classes & Signatures
```python
# parrot/mcp/integration.py
NETSUITE_MCP_URL = "https://{account_id}.suitetalk.api.netsuite.com/services/mcp/v1/suiteapp/com.netsuite.mcpstandardtools"  # :831
NETSUITE_AUTH_URL = "https://{account_id}.app.netsuite.com/app/login/oauth2/authorize.nl"   # :834
NETSUITE_TOKEN_URL = "https://{account_id}.suitetalk.api.netsuite.com/services/rest/auth/oauth2/v1/token"  # :835
NETSUITE_SCOPES = ["mcp"]                                                                    # :836

def _is_delegated(config: Any) -> bool: ...                                                  # :92
class MCPToolProxy(AbstractTool): ...                                                        # :97  (_execute flattens result to text)
class MCPClient:                                                                             # :378
    def __init__(self, config: MCPServerConfig, tool_name_prefix: Optional[str] = None): ...
    async def connect(self): ...            # runs session.connect() then session.list_tools()
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any],
                        headers: Optional[Dict[str, str]] = None): ...                       # :451

def create_netsuite_mcp_server(*, account_id: str, client_id: str, user_id: Optional[str] = None,
                               name: str = "netsuite", headers: Optional[Dict[str, Any]] = None,
                               credential_provider: Optional[str] = None) -> MCPServerConfig: ...   # :839
def create_netsuite_m2m_mcp_server(*, account_id: str, client_id: str, certificate_id: str,
                                   private_key_path: str, name: str = "netsuite",
                                   token_store: Optional[TokenStore] = None,
                                   headers: Optional[Dict[str, Any]] = None) -> MCPServerConfig: ...  # :917
# mixin methods on the MCP-enabled agent:
async def add_mcp_server(self, config: MCPServerConfig) -> List[str]: ...                    # :1406
async def add_netsuite_mcp_server(self, account_id: str, client_id: str, user_id: Optional[str] = None,
                                  credential_provider: Optional[str] = None, **kwargs) -> List[str]: ...  # :1751
async def add_netsuite_m2m_mcp_server(self, account_id: str, client_id: str, certificate_id: str,
                                      private_key_path: str, **kwargs) -> List[str]: ...     # :1791

# parrot/mcp/client.py — MCPServerConfig fields
user_id: Optional[str]                    # M2M only
inject_broker_credential: bool = False    # :242
credential_provider: Optional[str] = None
async def get_headers(self, context=None) -> Dict[str, str]: ...   # injects "Authorization: Bearer <current_credential()>" when inject_broker_credential

# parrot/mcp/oauth.py
class TokenStore: ...            # :22
class VaultTokenStore(TokenStore): ...   # :63
class NetSuiteM2MAuth:           # :168
    async def ensure_token(self, user_id: str = "m2m") -> str: ...   # :232
    def token_supplier(self) -> str | None: ...                      # :266

# parrot/auth/oauth2/mcp_provider.py
class MCPOAuth2Provider(OAuth2Provider):
    provider_id = f"mcp:{server_name}"
    @property
    def manager(self) -> Any: ...   # returns None
def register_mcp_oauth2_provider(server_name: str, config: MCPOAuth2Config, storage=None) -> MCPOAuth2Provider: ...

# parrot/auth/oauth2/descriptor.py
class OAuth2ProviderDescriptor(BaseModel):          # :61
    provider_id: str; display_name: str; icon: str = ""
    authorization_url: str; token_url: str; revoke_url: Optional[str] = None
    default_scopes: List[str]
    client_type: Literal["confidential", "public"] = "confidential"
    pkce: Literal["required", "optional", "none"] = "required"
    refresh_policy: RefreshPolicy; identity_probe: Optional[IdentityProbe] = None
    extra_authorize_params: Dict[str, str]; post_exchange: Optional[str] = None
class StandardOAuth2Manager(AbstractOAuth2Manager):  # :163
    def __init__(self, descriptor, *, client_id: str, client_secret: Optional[str], redirect_uri: str,
                 hooks: Optional[PostExchangeHookRegistry] = None, **manager_kwargs): ...
class DescriptorOAuth2Provider: ...                  # :436

# parrot/auth/oauth2/service.py
class IntegrationsService:                           # :71
    async def start_connect(self, user_id: str, provider_id: str, return_origin: Optional[str] = None, *,
                            channel=..., principal=None, scopes=None, request=None,
                            extra_state=None, permission_context=None) -> ConnectInitResponse: ...  # :323
    # :398  auth_url, nonce = await provider.manager.create_authorization_url(...)

# parrot/auth/broker/core.py
class CredentialBroker:                              # :32
    async def resolve(...): ...                      # :156

# parrot/tools/abstract.py
def current_credential() -> Optional[Any]: ...       # :46

# parrot/tools/mcp_mixin.py  (ToolManager side)
async def add_mcp_server(self, config: 'MCPServerConfig', context=None) -> List[str]: ...   # :57
self._mcp_clients: Dict[str, 'MCPClient']            # :52

# packages/ai-parrot-server/src/parrot/mcp/transports/http.py
class HttpMCPSession:                                # :204
    async def connect(self): ...                     # :346
    # "protocolVersion": "2024-11-05"                # :385 and :605
    async def _ensure_partition_initialized(self, partition, headers) -> None: ...   # :594
    async def list_tools(self): ...                  # :668
    async def call_tool(self, tool_name: str, arguments: dict, *, headers=None): ... # :683

# parrot/tools/dataset_manager/sources/base.py
class DataSource(ABC):
    def __init__(self, routing_meta: Dict | None = None) -> None: ...
    async def prefetch_schema(self) -> Dict[str, str]: ...      # default {}
    async def fetch(self, **params) -> pd.DataFrame: ...         # abstract
    def describe(self) -> str: ...                               # abstract
    @property
    def has_builtin_cache(self) -> bool: ...                     # default False
    @property
    def cache_key(self) -> str: ...                              # abstract

# parrot/tools/dataset_manager/tool.py
class DatasetEntry: ...                                          # :208
    async def materialize(self, force: bool = False, **params) -> pd.DataFrame: ...   # :337
class DatasetManager(AbstractToolkit):                           # :582
    def _make_source(self, source: "DataSource") -> "DataSource": ...                 # :682
    def add_source(self, source, capability_registry=None) -> str: ...                # :1433
    async def add_smartsheet_source(self, name: str, sheet_id: str, access_token=None, description=None,
                                    metadata=None, cache_ttl: int = 3600, fetch_on_create: bool = True,
                                    computed_columns=None) -> str: ...                # :1726
    async def fetch_dataset(self, name: str, sql: Optional[str] = None,
                            conditions: Optional[Dict[str, Any]] = None,
                            force_refresh: bool = False) -> Dict[str, Any]: ...       # :3415  (conditions are merged into source.fetch params)
    async def _cache_df(self, source: DataSource, df: pd.DataFrame, ttl: int) -> None: ...   # :4244
    async def _get_cached_df(self, source: DataSource) -> Optional[pd.DataFrame]: ...        # :4255
    async def materialize(self, name: str, force_refresh: bool = False, **params) -> pd.DataFrame: ...  # :4270

# parrot/tools/dataset_manager/sources/opaque.py
def resolve_opaque_source(source: "DataSource") -> "PhysicalResources": ...            # :35
# parrot/tools/dataset_manager/sources/authorizing.py
class AuthorizingDataSource(DataSource): ...                                           # :41
# parrot/tools/dataset_manager/sources/scoped_copy.py
def request_scoped_copy(source: DataSource) -> DataSource: ...
```

#### Verified Imports
```python
from parrot.mcp.integration import create_netsuite_mcp_server, create_netsuite_m2m_mcp_server, MCPClient
from parrot.mcp.client import MCPServerConfig
from parrot.mcp.oauth import NetSuiteM2MAuth, TokenStore, VaultTokenStore
from parrot.mcp.oauth2_config import get_mcp_oauth2_preset
from parrot.auth.oauth2.mcp_provider import MCPOAuth2Provider, register_mcp_oauth2_provider
from parrot.auth.oauth2.descriptor import OAuth2ProviderDescriptor, StandardOAuth2Manager, DescriptorOAuth2Provider
from parrot.auth.oauth2.service import IntegrationsService
from parrot.auth.broker.core import CredentialBroker
from parrot.auth.exceptions import AuthorizationRequired
from parrot.tools.abstract import current_credential
from parrot.tools.dataset_manager.sources import DataSource, SmartsheetSource, request_scoped_copy
```

#### Key Attributes & Constants
- `parrot.conf.NETSUITE_ACCOUNT_ID`, `NETSUITE_CLIENT_ID`, `NETSUITE_CERTIFICATE_ID`, `NETSUITE_PRIVATE_KEY_PATH` (`parrot/conf.py:718-721`)
- `JIRA_DESCRIPTOR` (`parrot/auth/jira_oauth.py:49`) — the only existing `OAuth2ProviderDescriptor` instance; template for a NetSuite one
- `mcp/oauth2_config.py` `netsuite` preset: scopes `["mcp"]`, grant `AUTHORIZATION_CODE`, `required_params=["account_id", "client_id"]`
- Registry entry `netsuite` → `method_name="add_netsuite_mcp_server"`, params `account_id`, `client_id`, `user_id` (all required) (`parrot/mcp/registry.py:226-256`)
- DatasetManager Redis cache is keyed by `source.cache_key`; `fetch` params are not part of the key (`tool.py:4270-4335`)

#### External contract (Oracle NetSuite docs, fetched 2026-11-12 — not yet verified live)
- MCP URLs: `https://<accountid>.suitetalk.api.netsuite.com/services/mcp/v1/all` (all tools) or `/services/mcp/v1/suiteapp/<applicationid>`.
- Client requirements: remote MCP, protocol `2025-06-18`, Streamable HTTP, OAuth 2.0 Authorization Code + PKCE (public client).
- Report tools: `ns_listAllReports`, `ns_runReport`, `ns_getSubsidiaries`, `ns_getAccountingBooks`, `ns_getAccountingContexts`, `ns_getNexusIds`.
- `ns_runReport` params: `reportId` (number, required), `dateTo` (string, required), `dateFrom` (string, required for from-to reports), `subsidiaryId` (number, conditional; negative = consolidated), `accountingContext`, `book`, `book2`, `nexusId`, `periodEndTransactionReportMode` (bool), `range` (string), `taxCashBasisMode` (`T`/`F`/`NEXUS`). Date format undocumented; the user's working example uses `YYYY-MM-DD`.
- Saved-search tools: `ns_listSavedSearches`, `ns_runSavedSearch` (`searchId` string required; `type` required for standalone search types; `range_start`, `range_end` optional numbers). Needs *Perform Search (View)*.
- SuiteQL tools: `ns_runCustomSuiteQL` (read-only), `ns_getSuiteQLMetadata`.
- Runtime: `ns_getSessionInfo`. Record tools (`ns_createRecord`, `ns_getRecord`, `ns_updateRecord`, …) exist but are out of scope for datasets.
- Response schemas for `ns_runReport` / `ns_runSavedSearch` are **not documented**; the only known sample is the user-provided payload above.

### Does NOT Exist (Anti-Hallucination)
- ~~`NetSuiteSource` / `NetSuiteReportSource` / any NetSuite module under `parrot/tools/dataset_manager/`~~ — does not exist
- ~~`DatasetManager.add_netsuite_source`~~ — does not exist
- ~~`NETSUITE_DESCRIPTOR`~~ — no `OAuth2ProviderDescriptor` for NetSuite exists
- ~~any NetSuite toolkit in `parrot_tools`~~ — the only `netsuite` hits there are Workday ID fields
- ~~`ns_runReport` / `ns_getSessionInfo` referenced anywhere in the repo~~ — no NetSuite tool name appears in code
- ~~`"2025-06-18"` in any `packages/*/src` file~~ — the HTTP MCP transport only offers `2024-11-05`
- ~~a working `manager` on `MCPOAuth2Provider`~~ — the property returns `None`
- ~~live or recorded NetSuite fixtures / a live harness~~ — FEAT-135 tests are mocks only
- ~~NetSuite redirect-URI or role settings in `parrot/conf.py`~~ — only the four `NETSUITE_*` values above

---

## Parallelism Assessment

- **Internal parallelism**: Phase 0 (live harness) gates everything and must run first. After it,
  two lanes are independent: *auth/MCP* (descriptor provider, role capture, delegated discovery,
  protocol version — `parrot/auth/`, `parrot/mcp/`, `ai-parrot-server` transport) and *datasets*
  (normalizers + param models built against recorded fixtures — `parrot/tools/dataset_manager/sources/`).
  They meet only at the final wiring task (source ↔ MCP client ↔ credential) and the live E2E.
- **Cross-feature independence**: touches `mcp/integration.py`, `tools/mcp_mixin.py` and
  `dataset_manager/tool.py` — all hot files. FEAT-877 (agent-local MCP, just merged) worked in the
  MCP area; check for in-flight specs on `dataset_manager/tool.py` before task decomposition.
- **Recommended isolation**: `per-spec` — and consider **two specs**: (1) `netsuite-mcp-consumer`
  (Phases 0–1) and (2) `netsuite-dataset-sources` (Phase 2), the second depending on the first's
  fixtures and connection.
- **Rationale**: the dataset layer's payload model depends on facts only the live harness can
  produce; splitting keeps Part 2 from being specified on guesses and keeps each worktree small.

---

## Open Questions

- [x] Flow type / base branch — *Owner: Jesus Lara*: feature on `dev`.
- [x] Where did the previous attempt stall? — *Owner: Jesus Lara*: never tested live; code exists (FEAT-135/773) but is unvalidated.
- [x] Identity for dataset reads — *Owner: Jesus Lara*: both — delegated per user when in session, M2M as fallback.
- [x] Data transport for the source — *Owner: Jesus Lara*: the NetSuite MCP tools.
- [x] Registration mode — *Owner: Jesus Lara*: both pre-registered datasets and ad hoc load by id.
- [x] Role handling — *Owner: Jesus Lara*: one connection per user, role/account stored and shown; reconnect to switch.
- [x] Report DataFrame shape — *Owner: Jesus Lara*: flat rows + hierarchy columns, one column per report column.
- [x] Live validation assets — *Owner: Jesus Lara*: integration record + client_id, M2M certificate and a non-admin MCP role are ready on account 4984231.
- [ ] Does the NetSuite MCP endpoint accept client-credentials (M2M) tokens with scope `mcp`? Oracle documents only Authorization Code + PKCE. — *Owner: live harness (Phase 0)*
- [ ] Does the server accept a client offering protocol `2024-11-05`, or must the transport offer `2025-06-18`? Any Streamable-HTTP behavior (session id header, SSE responses) the current `HttpMCPSession` mishandles? — *Owner: live harness (Phase 0)*
- [ ] Access-token and refresh-token lifetimes for the public-client PKCE grant (how often must a user re-consent?), and whether refresh tokens rotate. — *Owner: live harness (Phase 0)*
- [ ] Exact redirect URI to register on the integration record (generic `/api/v1/connections` callback vs. a NetSuite-specific path), per environment. — *Owner: Jesus Lara*
- [ ] Semantics of the report payload fields (`value`, `parent`, `summaryLine`, `openingLine`, `summaryLineValues`, `alias`, column `path` for nested/grouped columns) on a non-empty, multi-level report; and the result shape of `ns_runSavedSearch` / `ns_runCustomSuiteQL` and `ns_getSessionInfo`. — *Owner: live harness (Phase 0)*
- [ ] Delegated tool discovery when no service identity is available: pinned catalog vs. lazy discovery at the first authenticated call. — *Owner: spec*
- [ ] Where the ad hoc "load report/search by id" tools live: conditional tools on `DatasetManager` vs. a small NetSuite dataset toolkit in `parrot_tools` that holds a DatasetManager reference. — *Owner: spec*
- [ ] How a `DataSource.fetch` obtains the caller's delegated credential (DatasetManager tools do not declare a `credential_provider`): broker lookup by request principal vs. declaring the provider on the fetch tools. — *Owner: spec*
- [ ] May a dataset fall back from a missing user connection to the service identity, or is that an explicit per-dataset opt-in? (Default proposed: explicit opt-in.) — *Owner: Jesus Lara*
- [ ] Row caps and paging defaults for saved searches / SuiteQL, and NetSuite concurrency limits for the MCP endpoint. — *Owner: live harness (Phase 0)*
- [ ] One spec or two (consumer vs. dataset sources)? — *Owner: Jesus Lara*
