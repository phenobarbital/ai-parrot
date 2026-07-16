---
type: Wiki Overview
title: FEAT-259 — Auth & OBO layer (MS Agents SDK path)
id: doc:sdd-proposals-auth-obo-research-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The Microsoft 365 Agents SDK uses **Azure Bot Service's OAuth capabilities**
  for user authentication. The **Bot Framework Token Service centrally manages tokens**
  — a per-user, server-side token store keyed by user + OAuth connection, with refresh
  handled for you. This is the sin
---

---
feat_id: FEAT-259
title: "Per-user authentication & OBO for ai-parrot agents exposed via the Microsoft 365 Agents SDK"
type: research
mode: spec-input
status: discussion
base_branch: dev
relates_to:
  - FEAT-259 proposal (microsoft-copilot-agent-sdk.proposal.md) — transport/bridge feasibility
  - FEAT-XXX A2A brainstorm (brainstorm-copilot-a2a-percredential.md) — the *other* Copilot path
research_state: sdd/state/FEAT-259/
supersedes_scope:
  - "Human-in-the-Loop bridging (listed OUT of scope in the proposal) is RE-OPENED for the auth layer:
     OAuth sign-in is an in-turn interactive flow and cannot be deferred."
spike_gate: OQ#1 (does Copilot Studio relay the OAuth sign-in card + tokens/response invoke to the connected SDK agent?)
---

# FEAT-259 — Auth & OBO layer (MS Agents SDK path)

## 1. Key finding — this path has a native token service; A2A did not

The Microsoft 365 Agents SDK uses **Azure Bot Service's OAuth capabilities** for user authentication. The **Bot Framework Token Service centrally manages tokens** — a per-user, server-side token store keyed by user + OAuth connection, with refresh handled for you. This is the single biggest divergence from the A2A path, and it collapses most of what we designed there.

| Concern | A2A path (FEAT-XXX) | MS Agents SDK path (FEAT-259) |
|---|---|---|
| OAuth dance owner | **parrot** (we build link-out + callback) | **Bot Framework Token Service** (managed) |
| Credential prompt UX | custom consent link in A2A response text | **native sign-in card** emitted by the SDK |
| Suspend/resume of the task | our `SuspendedExecutionStore` + nonce | SDK turn model + `tokens/response` invoke |
| Token storage | parrot vault | BF Token Service (managed), keyed by connection |
| OBO to Graph/Work IQ | manual Entra OBO off an inbound token | **native** (`OBOConnectionName` + `OBOScopes`) |
| What parrot still owns | everything | `CredentialResolver` as an *adapter* over the token service + audit |

**Consequence for the spec:** in this path, `CredentialResolver` should treat the BF Token Service as a credential backend (resolve the per-user token via the SDK token client), not own the OAuth flow. parrot still records `key_fingerprint` to `AuditLedger` and still gates per-tool authorization — but the acquisition, sign-in UI, storage, and refresh are Microsoft's. Much less to build; the cost is a hard dependency on Azure Bot Service OAuth connections and one critical unknown (OQ#1).

## 2. Per-resource auth design

Four tools, three distinct mechanisms — but unlike A2A, three of the four are native to the token service:

| Tool | IdP | Mechanism in THIS path | OAuth connection on Azure Bot | Sign-in UX |
|---|---|---|---|---|
| `o365` / Graph | Entra | Azure Bot OAuth connection (Entra v2) → user token; **OBO native** for Graph scopes | one connection (e.g. `graph_sso`) | native sign-in card / Teams SSO (silent) |
| `work-iq` | Entra | same Entra connection; OBO-exchange to Work IQ scopes | shared with `o365` (different `OBOScopes`) | shared sign-in |
| `jira` | Atlassian | Azure Bot OAuth connection with a **generic OAuth2 provider** (Atlassian auth/token URLs, scopes, client id/secret) | dedicated connection (e.g. `jira_oauth`) | native sign-in card |
| `fireflies` | none (static API key) | **does NOT fit the OAuth connection model** | — | custom capture (see §2.1) |

As with A2A, one Entra sign-in amortizes across `o365` + `work-iq` (same connection, OBO to different scopes). Jira is a separate connection but still native — no custom link-out, unlike A2A.

### 2.1 Fireflies (the one that stays custom)

The token service is OAuth-oriented; a static API key has no OAuth dance, so the BF connection doesn't apply. Options, in order of preference:
1. **Confirm Fireflies OAuth/MCP-OAuth exists** (carried over from A2A OQ#6). If it does, model it as a generic OAuth2 BF connection and it becomes native like Jira.
2. **Out-of-band link-out** to a parrot-owned key-capture surface (the A2A pattern) — keeps the secret off the conversational plane.
3. ~~Adaptive Card with a text input in chat~~ — REJECTED: the key would enter the Copilot transcript (the `python_repl`-incident invariant). Do not.

## 3. OBO configuration specifics (Microsoft cluster)

OBO is native but has a hard precondition. The initial user sign-in must return an **exchangeable** token, which requires the OAuth connection's scopes to include one matching a scope exposed by the downstream API — for a Teams-capable bot the exposed scope must be `api://botid-{clientId}/defaultScopes` (Azure-Bot-only bots may use `api://{appId}`). The SDK then performs the MSAL OBO exchange using `OBOConnectionName` + `OBOScopes`:
- when **both** are present in config, the exchange runs automatically and you read the final token via the turn-token accessor;
- if either is missing, do the exchange explicitly at runtime (resolve connection/scopes dynamically) — the right pattern here, since `work-iq` vs `o365` need different scopes off the same connection.

⚠️ VERIFY (Python SDK): the .NET names are `GetTurnTokenAsync` / `ExchangeTurnTokenAsync` / `UserAuthorization` / `OBOConnectionName` / `OBOScopes`. The docs state OAuth is supported "for all languages, details similar." Confirm the Python equivalents in `microsoft_agents.*` before speccing call sites.

## 4. The sign-in flow requires `invoke` handling (currently absent)

The native sign-in is a multi-activity, asynchronous round-trip:
1. tool needs a credential → SDK emits a **sign-in card** (OAuthCard / sign-in resource) as a reply;
2. user signs in against the token service's hosted OAuth;
3. completion arrives back as an **`invoke`** activity — `signin/verifyState` (magic-code / generic OAuth) or `signin/tokenExchange` (Teams SSO);
4. the turn resumes; the token is now retrievable for the connection.

`ParrotM365Agent.on_turn` today routes only `message` and `conversationUpdate` (VERIFIED, agent.py) — **`invoke` is unhandled**, so the sign-in round-trip cannot complete. The proposal already flagged "invoke activities require synchronous responses" as a constraint but did not implement it. This is now load-bearing.

## 5. Custody decision: `CredentialResolver` as adapter over the token service

Recommended: the BF Token Service owns the OAuth dance, sign-in UI, storage, and refresh. parrot's `CredentialResolver` becomes a thin adapter that, given the resolved user identity + a connection name, fetches the current user token from the SDK token client and hands tools a resolved client — **never the raw token into model/tool context** (same seam as A2A). `AuditLedger` still records `key_fingerprint`. The acquired token reaches ai-parrot's tool layer through the existing per-request context mechanism (`_pctx_var` ContextVar), set by the bridge before `ask()`.

This preserves the invariants without re-owning the flow:
- secrets never cross the conversational plane (sign-in is a card → hosted OAuth, token stays server-side);
- never fall back to service identity for a per-user tool (if the token client returns nothing → emit sign-in card, do not downgrade);
- per-tool authorization stays in parrot's `PolicyEnforcementPoint`.

## 6. Code gap analysis (against uploaded FEAT-259 code)

### What exists (VERIFIED in uploads)

```
VERIFIED  inbound JWT + API-key auth        parrot/integrations/msagentsdk/wrapper.py  handle_request()
VERIFIED  outbound reply token (MSAL)        wrapper.py  MsalConnectionManager{"SERVICE_CONNECTION"}
VERIFIED  multi-tenant authority fix         wrapper.py  app_type==multitenant → botframework.com authority
VERIFIED  anonymous dev path                 wrapper.py  _AnonymousConnectionManager
VERIFIED  MCS empty-200 reply patch          parrot/integrations/msagentsdk/_patches.py
VERIFIED  bridge message→ask()               parrot/integrations/msagentsdk/agent.py  _handle_message()
VERIFIED  config (creds/app_type/api_key)    parrot/integrations/msagentsdk/models.py  MSAgentSDKConfig
```

Note: the only MSAL connection today is `SERVICE_CONNECTION` — the **bot↔connector service** auth (outbound reply). There is **no user-facing OAuth connection** and **no user token acquisition** anywhere.

### What is missing (the gap to spec)

1. **No user OAuth connection(s).** Need ≥2 Azure Bot OAuth connections (Entra/Graph+WorkIQ; Atlassian/Jira) and config to name them. → new `MSAgentSDKConfig` fields: `oauth_connections: dict[tool→connection_name]`, `obo_scopes: dict`.
2. **No `UserAuthorization` / auto-sign-in.** The wrapper uses raw `CloudAdapter`. The native sign-in + OBO live in the SDK's `AgentApplication`/`UserAuthorization` layer. **Architecture fork (OQ#2):** adopt `AgentApplication` (gains auto-sign-in, OBO handlers) vs stay on raw `CloudAdapter` and drive the user-token client manually.
3. **No `invoke` handling** in `on_turn` (§4). `signin/verifyState` + `signin/tokenExchange` must be routed and answered.
4. **No identity extraction** beyond `from_property.id` (a channel id). Need `from.aad_object_id` (Entra object id) from validated claims as the canonical identity / vault key / OBO subject.
5. **No token→tool bridge.** Even once the SDK has a user token, `_handle_message` calls `ask(question, session_id, user_id)` with no path to inject the resolved token into `CredentialResolver` / `_pctx_var`. This seam does not exist.
6. **No `CredentialResolver` adapter** over the SDK token client (§5).
7. **Fireflies API-key capture** (§2.1) — none.
8. **Sign-in card emission** when a tool reports missing credentials — none.

## 7. Does NOT exist (anti-hallucination)

- Any user-facing OAuth connection or user-token acquisition in the integration (only the service connection exists).
- `invoke` activity routing in the bridge.
- A `CredentialResolver` backend that reads from the BF Token Service.
- Account-linking map (Entra identity ⇄ Atlassian/Fireflies account) — same as A2A, not assumed.
- Confirmation that the Python `microsoft_agents.*` SDK exposes the OBO/turn-token APIs by the names the .NET docs use.

## 8. Open Questions

1. **[SPIKE GATE] Does Copilot Studio relay the OAuth sign-in card + the `tokens/response`/`signin/*` invoke to a connected M365 Agents SDK agent?** The sign-in flow is documented for Teams/Web Chat channels of the Azure Bot; the Copilot path runs through the `pva-studio` MCS connector (the empty-200 patch is evidence of its quirks). If Copilot Studio does **not** relay sign-in cards/invokes, native OAuth is unavailable on the Copilot surface and we fall back to the A2A-style link-out even here. **Everything in §3–§5 depends on this. Spike first.**
2. Architecture fork: adopt `AgentApplication` + `UserAuthorization` (native auto-sign-in/OBO) vs keep raw `CloudAdapter` and drive the user-token client manually. The former is less code but a bigger structural change to the wrapper.
3. Does Copilot Studio forward the **end user's** identity (`aad_object_id`), or Copilot's service identity, through the connection? (A2A OQ#1 analogue — likely better here because the Activity protocol has first-class user identity, but unverified for the Copilot/pva-studio channel.)
4. Python SDK API surface for OBO/turn-token (§3 VERIFY).
5. Fireflies: OAuth/MCP-OAuth vs static key (carried from A2A OQ#6) — decides native-connection vs custom link-out.
6. Token-service vs parrot-vault custody for non-Microsoft tokens (Jira): rely solely on BF Token Service, or mirror into parrot vault for portability/audit independence?
7. `invoke` timeout: long-running ai-parrot turns vs the synchronous-response requirement of `invoke` activities (proposal risk, now concrete for sign-in invokes).

## 9. Spike plan

1. **Sign-in relay (the gate, OQ#1).** Configure one Azure Bot OAuth connection (Graph). Force a turn that requires the token; observe whether a sign-in card renders in the Copilot Studio test pane and whether a `signin/verifyState`/`tokenExchange` invoke comes back to the endpoint. Log the raw invoke. → resolves OQ#1/#3.
2. **OBO exchange** for one Graph scope, then a Work IQ scope off the same connection. → resolves §3 + OQ#4.
3. **Token→tool bridge**: set `_pctx_var` from the resolved token; confirm a Jira/Graph tool inside ai-parrot can use it via `CredentialResolver`.
4. **Fireflies decision** (OQ#5): probe for OAuth; if none, prototype the link-out capture.

Spike in a worktree; SDD state on `dev`.

## 10. Acceptance criteria (for the spec)

- A tool reporting a missing per-user credential causes a native sign-in card (or, if OQ#1 negative, a link-out) — never a service-identity fallback, never a secret in the transcript.
- Completed sign-in (`invoke` round-trip handled) yields a per-user token retrievable by connection; `o365` + `work-iq` both work off one Entra sign-in via OBO to distinct scopes.
- `CredentialResolver` hands tools resolved clients sourced from the BF Token Service; raw tokens never enter model/tool context; `_pctx_var` carries per-request credential context set by the bridge.
- `AuditLedger` records `key_fingerprint` per credentialed invocation.
- Canonical identity derived from `from.aad_object_id`; account-linking resolves Jira/Fireflies accounts.
- `on_turn` routes and correctly answers `signin/verifyState` and `signin/tokenExchange` invokes.

## 11. Sources

- Configure your agent to use OAuth (UserAuthorization, auto sign-in, OBO via OBOConnectionName/OBOScopes, exchangeable-token requirement): https://learn.microsoft.com/en-us/microsoft-365/agents-sdk/agent-oauth-configuration and .../agent-oauth-configuration-dotnet
- User Authentication (SDK uses Azure Bot Service OAuth; Authorization + MsalConnectionManager): https://deepwiki.com/microsoft/Agents/3.2-user-authentication
- Add user authorization via federated identity credential (connection setup, defaultScopes, api://botid-{appid}): https://learn.microsoft.com/en-us/microsoft-365/agents-sdk/azure-bot-user-authorization-federated-credentials
- Add authentication to a bot / OAuth connection settings + Graph OBO: https://learn.microsoft.com/azure/bot-service/bot-builder-authentication
- Bot Framework Token Service centrally manages tokens; SignOutUserAsync to reset: https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/plugin-authentication

## 12. Revision history

| Date | Author | Change |
|---|---|---|
| 2026-06-26 | Jesus / research | Initial auth/OBO research for FEAT-259. Native BF Token Service vs A2A contrast; per-resource design; OBO specifics; sign-in invoke gap; CredentialResolver-as-adapter custody; code gap analysis vs uploaded wrapper/agent/models/_patches; OQ#1 (Copilot sign-in relay) set as spike gate. |
