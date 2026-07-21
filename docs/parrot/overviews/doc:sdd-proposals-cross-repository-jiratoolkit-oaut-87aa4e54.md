---
type: Wiki Overview
title: 'Brainstorm: Cross-Repository JiraToolkit OAuth2 3LO (Web AgentChat)'
id: doc:sdd-proposals-cross-repository-jiratoolkit-oauth2-3lo-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: integration (`/connect_jira` → inline button → `/api/auth/jira/callback`
  → token in
relates_to:
- concept: mod:parrot.auth.credentials
  rel: mentions
- concept: mod:parrot.auth.exceptions
  rel: mentions
- concept: mod:parrot.auth.jira_oauth
  rel: mentions
- concept: mod:parrot.handlers.agent
  rel: mentions
- concept: mod:parrot.handlers.integrations
  rel: mentions
- concept: mod:parrot.integrations
  rel: mentions
- concept: mod:parrot.tools.manager
  rel: mentions
- concept: mod:parrot_tools.jiratoolkit
  rel: mentions
---

# Brainstorm: Cross-Repository JiraToolkit OAuth2 3LO (Web AgentChat)

**Date**: 2026-05-04
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: B

---

## Problem Statement

`JiraToolkit` already runs in `oauth2_3lo` mode and is fully wired into the **Telegram**
integration (`/connect_jira` → inline button → `/api/auth/jira/callback` → token in
Redis → toolkit pre-execute resolves token per user). Web users of the Svelte
**`AgentChat`** component in the `navigator-frontend-next` repository have **no
equivalent path**: there is no UI to initiate OAuth2, no popup callback handling, and
no per-user toolkit registration mechanism reachable from the browser.

The web channel additionally lacks two pieces the Telegram channel did not need:

1. A **discovery surface** — a "+ Integrations" menu inside `AgentChat` that lists the
   OAuth2-capable toolkits the current user is allowed to connect (initially Jira, by
   design extensible to Slack, GitHub, Google Drive, Confluence…).
2. A **persistent registration** model — when a user connects Jira on agent X, that
   choice must survive Redis flushes and new browser sessions (a SaaS user expects
   "I connected Jira yesterday" to still be true today, even if the cache is cold).

**Who is affected**: Any user of the navigator-frontend-next AgentChat who needs a
JiraToolkit-using agent to act on their behalf. Today the only workaround is to also
authenticate via Telegram — not a viable UX for a web-first product.

**Why now**: The Telegram OAuth2 3LO flow has stabilised (FEAT in
`jiratoolkit-auth-telegram.brainstorm.md`), the underlying `JiraOAuthManager`,
`OAuthCredentialResolver`, `AuthorizationRequired` and the `/api/auth/jira/callback`
route are already in production. The cost of generalising to web is mostly UI plumbing
plus one new persistence collection — small relative to the user value.

---

## Constraints & Requirements

- **No regression of the Telegram flow.** `/api/auth/jira/callback` and
  `JiraOAuthManager.handle_callback` must keep working unchanged for `channel="telegram"`.
- **OAuth credentials are scoped per `(user_id, provider)`** — one Jira connection
  serves all the user's agents. **Per-agent toolkit *enablement* is a separate
  concern** scoped per `(user_id, agent_id, toolkit_id)`.
- **Web channel is isolated from Telegram channel.** A user who connects Jira on web
  does NOT inherit the Telegram connection (and vice-versa). Same Atlassian account
  is fine; channel namespacing is preserved (`jira:oauth:web:{user_id}` vs
  `jira:oauth:telegram:{telegram_id}`).
- **Persistence depth.** OAuth credential lives in Redis (90d TTL, fast path) AND in
  a new DocumentDB collection `users_integrations` (durable, source of truth for
  "connected?"). Per-agent enablement lives in `user_agent_toolkits` (durable).
- **Toolkit hydration is per-agent opt-in (resolved A=(iii)).** `JiraToolkit` is *not*
  injected into every agent — only into agents the user has explicitly enabled it for.
- **Auth surfacing.** When `_pre_execute` raises `AuthorizationRequired`, `AgentTalk`
  must catch it and emit a single structured response body:
  `{type: "auth_required", provider, auth_url, scopes, ...}`. AgentChat renders an
  inline "Connect Jira" button in the chat reply.
- **Popup OAuth UX.** `window.open(authUrl, 'jira-oauth', 'width=500,height=700')`.
  Callback HTML detects `channel="web"` from `extra_state` and renders a JS page that
  posts a message to `window.opener` then closes itself. **Origin allowlist enforced**
  via a new `PUBLIC_FRONTEND_ORIGINS` (or backend-side `WEB_OAUTH_ALLOWED_ORIGINS`)
  config var.
- **PBAC.** `/api/v1/agents/integrations/{agent_id}` endpoint family enforces PBAC
  via the existing `request.app['abac']` PDP (actions like `"integration:list"`,
  `"integration:connect"`, `"integration:disconnect"`).
- **No revoke at provider side on disconnect** (decision D). Just delete Redis token,
  delete DocumentDB row, drop session entry.
- **Cross-repo coordination.** Backend changes ship in `ai-parrot`; frontend changes
  ship in `navigator-frontend-next`. They must be releasable independently with feature
  flags / capability detection.
- **Async-first** everywhere (per CLAUDE.md), Pydantic for envelopes, no `requests`,
  use `aiohttp`.

---

## Options Explored

### Option A: Jira-Specific Web Plumbing (mirror Telegram literally)

Add a single `JiraWebConnector` class on the backend and a Jira-specific menu entry on
the frontend. The "+ Integrations" menu is hardcoded to show only Jira. The new
endpoints (`POST /api/v1/agents/integrations/{agent_id}/jira/connect`, etc.) are
purpose-built for Jira. Callback HTML gets a `channel == "web"` branch that emits
`postMessage`. No abstraction layer is built; Slack/GitHub/etc. would each repeat the
pattern when needed.

✅ **Pros:**
- Smallest surface area, fastest path to a working Jira connection on web.
- Mirrors the Telegram pattern almost line-for-line — easy to review.
- Zero risk of over-engineering.

❌ **Cons:**
- Adding the *next* OAuth provider (Slack, Google Drive…) requires repeating
  endpoints, persistence, popup glue, frontend menu entry, callback branching.
  Drift between providers is guaranteed within 2–3 additions.
- Decision (5) explicitly asks for **dynamic** listing from a registry. Hardcoding
  Jira contradicts that.
- The PBAC actions become provider-specific (`"jira:connect"` etc.) and don't compose.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiohttp` | New endpoint registration | already a core dep |
| `pydantic >= 2` | `JiraConnectInitRequest` etc. envelopes | already a core dep |
| `axios` (frontend) | menu + popup + state polling | already used |

🔗 **Existing Code to Reuse:**
- `parrot/auth/jira_oauth.py` — `JiraOAuthManager`, `JiraTokenSet` (verbatim, no change).
- `parrot/auth/credentials.py` — `OAuthCredentialResolver` (verbatim).
- `parrot/auth/routes.py` — extend `jira_oauth_callback` with a `channel == "web"` branch.
- `parrot/handlers/agent.py` — `UserObjectsHandler` session-key pattern for per-user `ToolManager`.
- `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` — `_pre_execute` already raises `AuthorizationRequired`; nothing to change here.
- Frontend: `src/lib/ui/components/AppDialog.svelte` for the menu; `src/lib/stores/toast.svelte.ts` for status.

---

### Option B: Generic OAuth2 Integrations Framework + Per-Agent Enablement (RECOMMENDED)

Introduce a small **OAuth2 Integrations** subsystem that abstracts the
provider-specific bits behind a registry. JiraToolkit is the first registered
provider; future toolkits register themselves the same way.

**Backend pieces:**
- `parrot/integrations/oauth2/` — new package.
  - `registry.py` — `OAuth2ProviderRegistry` discovers all registered providers
    (`register_oauth2_provider("jira", JiraOAuth2Provider)`). Each provider exposes
    `manager` (`JiraOAuthManager` for Jira), `display_name`, `icon`, `default_scopes`,
    `toolkit_factory(token_set) -> AbstractToolkit`, and `pbac_action_namespace`.
  - `service.py` — `IntegrationsService` orchestrates connect-init, status, disconnect
    against the registry; handles persistence to `users_integrations` and
    `user_agent_toolkits`.
- `parrot/handlers/integrations.py` — new `IntegrationsHandler(BaseView)` with:
  - `GET /api/v1/agents/integrations/{agent_id}` — list available providers + per-user
    connected/enabled status, PBAC-filtered.
  - `POST /api/v1/agents/integrations/{agent_id}/{provider}/connect` — returns
    `{auth_url, state}`; behind the scenes calls
    `manager.create_authorization_url(channel="web", user_id, extra_state={"channel": "web", "agent_id": agent_id, "return_origin": req.origin})`.
  - `POST /api/v1/agents/integrations/{agent_id}/{provider}/enable` — registers the
    toolkit on the per-(user, agent) record (called automatically after the popup
    completes successfully and the frontend confirms via this endpoint).
  - `DELETE /api/v1/agents/integrations/{agent_id}/{provider}` — disconnect (deletes
    DocumentDB row + Redis token + session entry; **no provider-side revoke**).
- `parrot/auth/routes.py` — extend `jira_oauth_callback`: branch on
  `extra_state["channel"]`. `"telegram"` keeps current behaviour; `"web"` renders
  `web_oauth_success.html` template containing JS that:
  1. Reads `target_origin` from a server-rendered constant (validated against
     `WEB_OAUTH_ALLOWED_ORIGINS`).
  2. Calls `window.opener.postMessage({type: "ai-parrot-oauth-callback", provider:
     "jira", success: true, account: "...", display_name: "..."}, target_origin)`.
  3. Calls `window.close()`.
  Errors render an analogous error template that posts `success: false, error: "..."`.
- `parrot/handlers/agent.py` — wrap the agent execution in `try / except
  AuthorizationRequired` and translate the exception into a single structured response
  body `{type: "auth_required", provider, auth_url, scopes, message}`. **Single
  response body** (decision B=ii confirmed: not streaming, not SSE).
- **Hydration on session start.** `UserObjectsHandler.configure_tool_manager()` (or
  the equivalent it already exposes) reads `user_agent_toolkits` for `(user_id,
  agent_id)`, instantiates the toolkit via `provider.toolkit_factory(...)` for each
  enabled provider, and registers it with the `OAuthCredentialResolver` so the
  toolkit's `_pre_execute` can resolve tokens. This is the "auto-rehydrate" decision (2).

**Persistence (new collections in DocumentDB):**

`users_integrations` — one row per `(user_id, provider)`:
```json
{
  "user_id": "...",
  "provider": "jira",
  "channel": "web",
  "status": "active",
  "account_id": "...",
  "display_name": "...",
  "email": "...",
  "scopes": ["read:jira-work", "write:jira-work", ...],
  "cloud_id": "...",
  "site_url": "...",
  "connected_at": "ISO-8601",
  "last_used_at": "ISO-8601"
}
```

`user_agent_toolkits` — one row per `(user_id, agent_id, toolkit_id)`:
```json
{
  "user_id": "...",
  "agent_id": "...",
  "toolkit_id": "jira",
  "provider": "jira",
  "enabled_at": "ISO-8601"
}
```

**Frontend pieces (`navigator-frontend-next`):**
- `src/lib/api/integrations.ts` — typed wrappers: `listIntegrations(agentId)`,
  `startIntegrationConnect(agentId, provider)`, `confirmIntegrationEnable(agentId, provider)`,
  `disconnectIntegration(agentId, provider)`.
- `src/lib/components/agents/integrations/IntegrationsMenu.svelte` — dropdown rendered
  from the toolbar, lists items returned by `listIntegrations`. Each item shows
  status badge ("Connected" / "Not connected"), action button.
- `src/lib/components/agents/integrations/OAuthPopup.svelte` (or pure helper module
  `src/lib/oauth/popup.ts`) — opens the popup, registers a `message` listener with
  origin validation, resolves a Promise on success/timeout (60s), closes popup, calls
  `confirmIntegrationEnable`, fires `toastStore.success("Connected to Jira as ...")`.
- AgentChat toolbar: insert a `<button>` between the existing Refresh and Canvas
  toggle buttons (lines 954-975) that opens `IntegrationsMenu`.
- AgentChat message renderer: detect `auth_required` envelope and render an inline
  "Connect Jira" pill that triggers the same popup helper.

✅ **Pros:**
- Satisfies **all** Round-1 + Round-2 decisions, including dynamic registry (5)
  and PBAC-filtered listing.
- Adding the **next** provider is a `register_oauth2_provider("slack", SlackOAuth2Provider)`
  call plus an icon — zero plumbing duplication.
- Clean separation of credential (`users_integrations`) vs enablement
  (`user_agent_toolkits`) reflects the real domain model and resolves the A/C
  tension surfaced in Round 2.
- Origin-allowlisted `postMessage` callback is reusable across all future providers.
- Structured `auth_required` envelope establishes a frontend contract that any future
  OAuth toolkit (or even non-OAuth gated toolkit) can reuse.

❌ **Cons:**
- Larger surface area than Option A — registry, service, two new collections, popup
  helper module, frontend menu component.
- Requires care to keep the `jira_oauth_callback` branching readable (Telegram vs
  web vs future channels). Mitigation: extract per-channel renderers.
- Two-collection persistence model needs a deletion-cascade rule (disconnecting Jira
  must also remove rows from `user_agent_toolkits` for that provider) — easy but
  must be specified in the spec.

📊 **Effort:** Medium-High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiohttp` | New endpoint registration | already a core dep |
| `pydantic >= 2` | `IntegrationDescriptor`, `AuthRequiredEnvelope`, etc. | already a core dep |
| `aiohttp_jinja2` (or string template) | `web_oauth_success.html` rendering | check existing pattern in `parrot/auth/routes.py` |
| navconfig `Kardex` | Read `WEB_OAUTH_ALLOWED_ORIGINS` (use `fallback=`, never `default=` — see memory) | already a core dep |
| `axios` (frontend) | menu + popup helper + integrations API client | already used |
| `bits-ui` Dialog (via existing `AppDialog.svelte`) | menu host (or use a lightweight popover) | already used |

🔗 **Existing Code to Reuse:**
- `parrot/auth/jira_oauth.py:86-443` — `JiraOAuthManager` (no change to internals;
  Jira provider thin-wraps it).
- `parrot/auth/jira_oauth.py:59-84` — `JiraTokenSet` schema — copied/projected into
  `users_integrations` row.
- `parrot/auth/credentials.py:27-67` — `CredentialResolver` / `OAuthCredentialResolver`
  abstractions become the resolver injected into every hydrated toolkit.
- `parrot/auth/exceptions.py:12-53` — `AuthorizationRequired` — already carries
  `auth_url`, `provider`, `scopes`; AgentTalk just needs to project it into a JSON
  envelope.
- `parrot/auth/routes.py:83-174` — `jira_oauth_callback` — extend with a `channel`
  switch.
- `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:866-937` —
  `JiraToolkit._pre_execute` (no change needed).
- `parrot/handlers/agent.py:50` (`AgentTalk`), `:1297-1326` (session/tool-manager
  load), `:1577+` (PATCH endpoint pattern) — model for new `IntegrationsHandler`.
- `parrot/tools/manager.py:203` (`ToolManager`), `:381` (`add_tool`), `:877`
  (`remove_tool`) — for hydration / disconnection.
- `parrot/integrations/telegram/post_auth_jira.py:208-237` — `_store_in_vault`
  pattern (kept for Telegram parity; web does **not** mirror to Vault — only Redis +
  DocumentDB).
- Frontend: `src/lib/api/http.ts` (axios + Bearer); `src/lib/config.ts` for
  `apiBaseUrl`; `src/lib/stores/toast.svelte.ts`; `src/lib/ui/components/AppDialog.svelte`.
- Frontend toolbar injection point: `AgentChat.svelte:954-975`.

---

### Option C: Always-On Lazy "Connect Pill" (no per-agent enablement)

`JiraToolkit` is auto-loaded into every agent's `ToolManager` at startup. There is no
per-agent toolkit registration. The "+ Integrations" menu is purely informational
(shows "Connected as user@example.com" or "Not connected"). On the first tool call
that requires Jira, `AuthorizationRequired` propagates to AgentTalk, which emits the
structured envelope, and AgentChat renders the inline connect pill. Connecting writes
to Redis + `users_integrations`. There is no `user_agent_toolkits` collection.

✅ **Pros:**
- Simplest backend persistence (single collection).
- No "register the toolkit on this agent" UX step — discoverability is automatic.
- Matches the "lazy global" pattern many SaaS chat products use.

❌ **Cons:**
- **Directly contradicts decision A=(iii)** ("only into agents the user has connected
  for"). User explicitly chose per-agent opt-in, so this option is non-conforming.
- Token-bloats every agent's system prompt with Jira tool descriptions even for
  agents that have nothing to do with Jira.
- No clean way to "remove Jira from agent X but keep it on agent Y".
- PBAC action surface flattens — you can't have an agent-specific allow rule for
  integrations because every agent loads every toolkit.

📊 **Effort:** Low

📦 **Libraries / Tools:** Same as Option A.

🔗 **Existing Code to Reuse:** Same as Option A, minus `user_agent_toolkits`.

---

## Recommendation

**Option B** is recommended.

It is the only option that satisfies the full decision set from Rounds 1–2 simultaneously:
the dynamic, PBAC-filtered registry (decision 5), per-agent toolkit opt-in (A=iii),
per-`(user, provider)` credential storage with per-`(user, agent, toolkit)` enablement
(C + reconciliation), structured `auth_required` envelope on a single response body
(B=ii), origin-allowlisted popup callback (E), and DocumentDB-backed auto-rehydration (2).

We trade a moderate amount of upfront framework work (one new package, two new
collections, one new handler family, one new frontend module) against:
1. **Repeated provider work.** Every future OAuth toolkit (Slack, GitHub, Confluence,
   Google Drive…) becomes a one-file registration.
2. **Drift risk.** Option A would diverge from Telegram's already-shipped pattern as
   each new provider is added — the registry centralises the abstractions that drift
   would corrode.
3. **UX consistency.** All providers share the same popup, the same connect pill, the
   same disconnect modal — users learn the pattern once.

Option C is rejected because it conflicts with explicit user decision A=(iii).
Option A is rejected because it conflicts with explicit user decision (5) (dynamic
registry) and would still require all the persistence + popup + envelope work to be
rebuilt per-provider later.

---

## Feature Description

### User-Facing Behavior

**Discovery & Connect (happy path)**

1. User opens an `AgentChat` (e.g., `/chat/finance-agent`). The toolbar shows a new
   `+ Integrations` button between the existing Refresh and Canvas-toggle buttons.
2. User clicks `+ Integrations`. A small dropdown / popover lists the OAuth2-capable
   integrations the user is allowed to connect (PBAC-filtered). Initially: just
   "Jira", with a status badge ("Not connected").
3. User clicks "Jira" → "Connect". A popup window opens at
   `https://auth.atlassian.com/authorize?...`. User consents in Atlassian.
4. Atlassian redirects the popup to `/api/auth/jira/callback?code=...&state=...`. The
   server exchanges the code, stores the token in Redis (key
   `jira:oauth:web:{user_id}`) and writes a `users_integrations` row.
5. The callback HTML detects `channel="web"` from `extra_state`, validates the
   target origin against `WEB_OAUTH_ALLOWED_ORIGINS`, posts
   `{type: "ai-parrot-oauth-callback", provider: "jira", success: true, account_id,
   display_name, email}` to `window.opener`, then closes itself.
6. AgentChat receives the message, validates `event.origin === window.location.origin`,
   calls `POST .../jira/enable` to add the row in `user_agent_toolkits`, and then
   refreshes the integrations menu (badge flips to "Connected as user@example.com").
   `toastStore.success("Jira connected")` fires.
7. The user can now ask the agent Jira-related questions and the toolkit works
   transparently on subsequent requests in the current and future sessions
   (auto-rehydrated from `user_agent_toolkits`).

**Inline auth-required pill (alternate trigger)**

If the user hasn't connected Jira yet but invokes a Jira-using agent, the agent
attempts a tool call, `JiraToolkit._pre_execute` raises `AuthorizationRequired`,
`AgentTalk` translates it into a JSON body, and AgentChat renders an inline pill
("Jira access required — Connect") in place of the agent's reply. Clicking the pill
opens the same popup as the menu flow. After success, the user is invited to retry the
prompt (we do **not** auto-retry — keeps the UX deterministic).

**Disconnect**

In the `+ Integrations` menu, a "Connected" item shows a "Disconnect" affordance.
Clicking it: deletes the Redis token, deletes the `users_integrations` row, deletes
all `user_agent_toolkits` rows for that `(user_id, provider)`, removes the toolkit
from the in-memory `ToolManager`, refreshes the menu, fires
`toastStore.info("Jira disconnected")`. **No provider-side revoke** (decision D).

### Internal Behavior

**Backend at request time:**
1. `IntegrationsHandler.list(GET …/integrations/{agent_id})` →
   `IntegrationsService.list_for_user(user_id, agent_id)`:
   - Iterate `OAuth2ProviderRegistry.providers()`.
   - For each, ask PBAC `(user, "integration:list", provider)`; filter out denials.
   - For each surviving provider, query `users_integrations` for `(user_id, provider)`
     to get `connected` + identity, and `user_agent_toolkits` for `(user_id, agent_id,
     provider)` to get `enabled_on_this_agent`.
   - Return `[IntegrationDescriptor(provider, display_name, icon, scopes, connected,
     enabled, account_id?, display_name?, email?), ...]`.
2. `IntegrationsHandler.connect_init(POST …/{provider}/connect)` →
   `IntegrationsService.start_connect(user_id, agent_id, provider, request_origin)`:
   - PBAC check `(user, "integration:connect", provider)`.
   - Validate `request_origin` is in `WEB_OAUTH_ALLOWED_ORIGINS`.
   - Call `provider.manager.create_authorization_url(channel="web", user_id,
     extra_state={"channel": "web", "agent_id": agent_id, "return_origin":
     request_origin})`.
   - Return `{auth_url, state, scopes, expires_in: 600}` (the state nonce expires in
     10min, mirrors current behaviour).
3. `IntegrationsHandler.confirm_enable(POST …/{provider}/enable)`:
   - PBAC check `(user, "integration:connect", provider)`.
   - Verify `users_integrations` row exists for `(user_id, provider)` (created by the
     callback). If not → 409 (popup never completed).
   - Upsert `user_agent_toolkits` row for `(user_id, agent_id, provider)`.
   - Hot-add the toolkit to the user's session `ToolManager` for this agent.
   - Return the updated `IntegrationDescriptor`.
4. `IntegrationsHandler.disconnect(DELETE …/{provider})`:
   - PBAC check `(user, "integration:disconnect", provider)`.
   - Delete Redis token, delete `users_integrations` row, delete all matching
     `user_agent_toolkits` rows, remove from session `ToolManager`.

**Backend at OAuth callback time** (`/api/auth/jira/callback`):
1. Existing flow runs unchanged through `manager.handle_callback(code, state)`. After
   token storage in Redis, `extra_state["channel"]` is inspected.
2. If `"telegram"` → existing `_notify_telegram` + `telegram_jira_session_stamper`
   (unchanged).
3. If `"web"` → call `IntegrationsService.persist_credential(user_id, "jira",
   token_set)` to upsert the `users_integrations` row, then render
   `web_oauth_success.html` with server-side context `{provider, account_id,
   display_name, email, target_origin: validated(extra_state["return_origin"]) }`.
4. Errors render `web_oauth_error.html` (same `postMessage` envelope with
   `success: false`).

**Backend at agent invocation** (`AgentTalk.post`):
1. Existing pattern loads per-user `ToolManager` from session.
2. **New** — if the session ToolManager doesn't yet contain the toolkits the user
   has enabled (cold session), `UserObjectsHandler.configure_tool_manager` consults
   `user_agent_toolkits` for `(user_id, agent_id)`, instantiates each toolkit via
   `provider.toolkit_factory(resolver)`, and registers them. This is the
   auto-rehydrate path.
3. Wrap the agent call with `try / except AuthorizationRequired`. On exception:
   return a single response body `AuthRequiredEnvelope(type="auth_required",
   provider, auth_url, scopes, message)` with HTTP 200 (the chat succeeded; the
   reply just happens to be a structured "I need permission" message).

**Frontend behaviour:**
- `IntegrationsMenu.svelte` calls `listIntegrations(agentId)` on open.
- Connect button → `startIntegrationConnect(agentId, provider)` → opens popup with
  returned `auth_url` → `OAuthPopupHelper.awaitCallback({allowedOrigin: window.location.origin,
  timeoutMs: 60000})` → on success → `confirmIntegrationEnable(agentId, provider)` →
  refresh menu + toast.
- AgentChat `MessageRenderer`: if `message.type === "auth_required"`, render

…(truncated)…
