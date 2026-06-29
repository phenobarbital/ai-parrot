# Exposing an ai-parrot agent as a Microsoft Copilot agent (FEAT-259)

This example (`server.py`) wraps a simple ai-parrot `BasicAgent` with the
**Microsoft 365 Agents SDK** so it can be registered as a custom agent in
**Microsoft Copilot Studio** (and reached from Teams / Web Chat).

The integration lives in the `ai-parrot-integrations` satellite package under
`parrot.integrations.msagentsdk`:

- `MSAgentSDKConfig` — config dataclass (resolves Azure AD credentials from env).
- `ParrotM365Agent` — bridge: maps an inbound Activity → `agent.ask()` → reply.
- `MSAgentSDKWrapper` — owns the `CloudAdapter`, registers the HTTP route.

---

## 1. Install

The Microsoft SDK glue is an optional extra:

```bash
source .venv/bin/activate
uv pip install "ai-parrot-integrations[msagentsdk]"
```

This pulls `microsoft-agents-hosting-aiohttp~=0.9.0` and
`microsoft-agents-authentication-msal~=0.9.0` (the MSAL connection manager
needed for Azure AD auth). They are **not** installed by the default
`ai-parrot` install.

---

## 2. Run locally (anonymous mode — default)

For local development the server runs in anonymous mode by default (no JWT
validation, outbound replies use an empty token):

```bash
python examples/msagent/server.py
```

You'll see the messaging endpoint in the logs:

```
🚀 MS Agent SDK server running on http://localhost:3978
   Auth mode:  ANONYMOUS (dev)
   Messaging:  POST http://localhost:3978/api/msagentsdk/mscopilotagent/messages
```

> ⚠️ **Anonymous mode disables JWT validation. Never use it in production.**

The route's `safe_id` (`mscopilotagent`) is derived from the config `name`
(`MSCopilotAgent`) — lower-cased, with non-alphanumerics replaced by `_`.

### How replies are delivered (read this before testing)

The Microsoft 365 Agents protocol is **asynchronous**, like Bot Framework: the
agent does **not** return its answer in the HTTP response body. The incoming
POST only gets an acknowledgment (`200`/`202`); the actual answer is sent
**out-of-band**, in a separate POST the SDK makes to the channel's `serviceUrl`
(the Bot Connector REST API, `…/v3/conversations/{id}/activities/{id}`).

Consequences:

- **`curl` will never print the answer.** You'll see the turn run in the logs,
  then a `404`/`401` on `reply_to_activity` because your fake `serviceUrl`
  isn't a real Bot Connector. This is expected — not a bug.
- **Anonymous mode can only reply to the Bot Framework Emulator** (or any
  channel that accepts an empty token). Real channels — including **Copilot
  Studio** — reject the empty anonymous token with `401`, so the reply never
  arrives even though the inbound turn succeeded. To get replies from Copilot
  Studio you must run `--production` (Azure AD), so the MSAL connection manager
  can mint a real outbound token. See sections 4–5.

### Smoke test the turn pipeline

A raw `curl` can drive the inbound half of a turn — the agent receives the
message and runs `ask()` — but it **cannot receive the reply**: the SDK sends
the answer back out-of-band via the Bot Connector REST API at the activity's
`serviceUrl`. A localhost `serviceUrl` has no such API, so you'll see the agent
run and then a `404` on `reply_to_activity` in the logs. That confirms the
bridge works end to end; only the reply delivery needs a real channel.

```bash
curl -X POST http://localhost:3978/api/msagentsdk/mscopilotagent/messages \
  -H "Content-Type: application/json" \
  -d '{
        "type": "message",
        "text": "Hello!",
        "channelId": "emulator",
        "from": {"id": "user-1", "name": "User"},
        "conversation": {"id": "conv-1"},
        "recipient": {"id": "bot-1", "name": "Bot"},
        "serviceUrl": "http://localhost:3978",
        "id": "activity-1"
      }'
# Watch the server logs: you'll see "Message from user=..." and the agent's
# ask() run, then a 404 on reply_to_activity (expected with a fake serviceUrl).
```

### Test with replies: Bot Framework Emulator

To actually see the agent's reply, use the **Bot Framework Emulator**
(it hosts the Bot Connector callback the SDK posts back to):

1. Download the [Bot Framework Emulator](https://github.com/microsoft/BotFramework-Emulator/releases).
2. **Open Bot** → endpoint `http://localhost:3978/api/msagentsdk/mscopilotagent/messages`.
3. Leave App ID / Password blank (anonymous mode) and start chatting.

---

## 3. Expose the local server with a tunnel

Copilot Studio needs a **public HTTPS** messaging endpoint. Expose your local
port with any tunnel:

```bash
# ngrok
ngrok http 3978

# or Microsoft dev tunnels
devtunnel host -p 3978 --allow-anonymous
```

Your public messaging endpoint becomes:

```
https://<your-tunnel-host>/api/msagentsdk/mscopilotagent/messages
```

---

## 4. Register the Azure Bot (for Azure AD auth)

Copilot Studio authenticates inbound calls with Azure AD JWTs. For a
production-like setup you register an **Azure Bot** resource and run the server
**with** `--production`.

1. In the [Azure Portal](https://portal.azure.com) create an **Azure Bot**
   resource (single-tenant or multi-tenant).
2. Note the **Microsoft App ID**, create a **client secret**, and note the
   **Tenant ID**.
3. Set the bot's **Messaging endpoint** to your public tunnel URL + the route:
   `https://<your-tunnel-host>/api/msagentsdk/mscopilotagent/messages`.

Provide the credentials to the server via environment variables. The prefix is
the **upper-cased config `name`** (`MSCopilotAgent` → `MSCOPILOTAGENT`), because
`MSAgentSDKConfig.__post_init__` resolves them that way:

```bash
export MSCOPILOTAGENT_MICROSOFT_APP_ID="<app-id>"
export MSCOPILOTAGENT_MICROSOFT_APP_PASSWORD="<client-secret>"
export MSCOPILOTAGENT_MICROSOFT_TENANT_ID="<tenant-id>"

# IMPORTANT — match your App Registration's "Supported account types":
#   Single tenant  → "SingleTenant" (default) and keep TENANT_ID set
#   Multi-tenant   → "MultiTenant"  (mints the reply token against the
#                    botframework.com authority; required for Teams)
export MSCOPILOTAGENT_MICROSOFT_APP_TYPE="SingleTenant"   # or MultiTenant

python examples/msagent/server.py --production --host 0.0.0.0 --port 3978
```

Logs will now show `Auth mode: Azure AD JWT`. With `--debug` you'll also see the
effective outbound auth, e.g. `Outbound auth: client_id=… authority=…`.

> **Multi-tenant note:** keep `TENANT_ID` set (inbound JWT validation needs it
> for the issuer), but `APP_TYPE=MultiTenant` switches the **outbound** reply
> token to the shared `botframework.com` authority. Without this, multi-tenant
> bots get `401 "Authorization has been denied"` on replies (see Teams section).

---

## 5. Connect it inside Copilot Studio

1. Open [Copilot Studio](https://copilotstudio.microsoft.com) and select (or
   create) a copilot.
2. Go to **Agents** (or **Tools/Skills**, depending on your tenant's UI) →
   **Add an agent / Add a skill**.
3. Point it at your **Azure Bot** registration from step 4 (the same App ID).
   Copilot Studio routes user turns to the bot's messaging endpoint.
4. Save & publish. From the **Test** pane, send a message — it is delivered as
   an Activity to your endpoint, handled by `ParrotM365Agent.on_turn()`, and the
   ai-parrot agent's answer comes back into the chat.

> Channel reach: once registered, the same Azure Bot can be surfaced in Teams,
> Web Chat, etc. via the Azure Bot **Channels** blade — no code changes needed.

### 5b. Copilot Studio "Microsoft 365 Agents SDK" connection (API Key)

Copilot Studio's *"Conexión a un agente del SDK de agentes de Microsoft 365"*
dialog offers three auth schemes for how Copilot calls your agent: **None**,
**API Key**, **OAuth 2.0**. In practice **"None" is rejected** — testing fails
with `Authentication is not configured for this bot` /
`AuthenticationNotConfigured`. Use **API Key** (simplest):

1. In the connection dialog choose **API Key**, Type **Header**, header name
   `x-api-key` (or your choice), and a secret **value**.
2. Run the server with that same secret and your Azure credentials (the bot
   still needs them to authenticate the **reply** to the connector):
   ```bash
   export MSCOPILOTAGENT_MICROSOFT_APP_ID=...        # + _APP_PASSWORD / _TENANT_ID / _APP_TYPE
   export MSCOPILOTAGENT_API_KEY="<same secret>"
   export MSCOPILOTAGENT_API_KEY_HEADER="x-api-key"  # optional, this is the default
   python examples/msagent/server.py --production --host 0.0.0.0 --port 3978 --debug
   ```
3. Save & **publish** the Copilot agent, then test.

How it works: the wrapper accepts the request when the `x-api-key` header
matches (in addition to Bot Framework JWTs, so Teams/Web Chat keep working on
the same route). On an API-key match it attaches an **authenticated** identity so
the outbound reply is signed with the bot's real Azure AD token (not the
anonymous empty token). A wrong/missing key returns `401`.

> If the channel can only POST to the Bot Framework standard path, set
> `MSCOPILOTAGENT_ENDPOINT=/api/messages` — the wrapper registers it **in
> addition** to the per-bot `/api/msagentsdk/{safe_id}/messages` route.

---

## 6. Production: run inside the BotManager (recommended)

The standalone `server.py` is for demos. In a real deployment you declare the
bot in `env/integrations_bots.yaml` and the `IntegrationBotManager` starts it on
the shared aiohttp app (and excludes the route from the auth middleware):

```yaml
agents:
  MSCopilotAgent:
    kind: msagentsdk
    chatbot_id: main_agent          # an agent already known to the BotManager
    anonymous_auth: false           # use Azure AD in production
    app_type: MultiTenant           # or SingleTenant (default) — see Teams section
    welcome_message: "Hello! I'm ready to help."
    # client_id / client_secret / tenant_id / app_type fall back to env vars:
    #   MSCOPILOTAGENT_MICROSOFT_APP_ID / _MICROSOFT_APP_PASSWORD /
    #   _MICROSOFT_TENANT_ID / _MICROSOFT_APP_TYPE
```

---

## Teams: inbound works but the reply is `401 "Authorization has been denied"`

Symptom: in `--production` the inbound turn is processed (you see
`Message from user=…` and the agent runs), and the Azure Bot **Test in Web
Chat** even replies — but in **MS Teams** the bot's reply fails with:

```
Error replying to activity: {"message":"Authorization has been denied for this request."}
ClientResponseError: 401, url='https://smba.trafficmanager.net/amer/.../activities/...'
```

What it means: the bot **did** acquire and send an outbound token (an empty
token would instead raise `Failed to obtain token for user token client`), but
the Bot Connector for Teams **rejected** it. Inbound auth and token acquisition
are fine — this is an **Azure app-registration / Teams-channel** mismatch, not a
wrapper bug. Run with `--debug` to print the effective outbound auth at startup:

```
Outbound auth: client_id=1a2b3c4d… tenant_id=<guid> auth_type=client_secret authority=(default)
```

Checklist (most common first):

1. **App type vs outbound authority (most common cause).** Match the app
   registration's *Supported account types* via `MSCOPILOTAGENT_MICROSOFT_APP_TYPE`:
   - **Single tenant** → `APP_TYPE=SingleTenant` (default) and keep
     `MSCOPILOTAGENT_MICROSOFT_TENANT_ID` set.
   - **Multiple Entra ID tenants (multi-tenant)** → set
     `APP_TYPE=MultiTenant`. Keep `TENANT_ID` set (inbound validation needs it),
     but this switches the **outbound** reply token to the `botframework.com`
     authority. Pinning only your own tenant for a multi-tenant app makes Teams
     reject the reply with `401` while Web Chat still works — set `APP_TYPE` and
     restart.
2. **Client secret value, not its ID.** `_MICROSOFT_APP_PASSWORD` must be the
   secret **Value** (shown once at creation), not the secret ID — and not
   expired.
3. **Teams channel enabled** on the Azure Bot (Channels → Microsoft Teams), and
   the bot added to Teams via a manifest whose `bot id` equals your App ID.
4. **App ID = the one in your env.** Inbound already validated against it (the
   turn ran), so this is usually fine — but worth confirming the Teams manifest
   didn't pin a different bot id.

> Azure portal **Test in Web Chat** is more lenient than Teams about outbound
> auth, so "Web Chat works" does **not** prove the credentials are fully correct
> for Teams — trust the Teams `401`, work the checklist above.

---

## 7. Per-user auth with the Unified Credential Broker (FEAT-264)

`server.py` shows how to expose an agent with **two credentialed tools** —
Fireflies.ai (static API key) and Work IQ (Entra OBO) — on **both** the
MSAgentSDK chat surface and an optional A2A sub-agent surface, via a single
declarative `CredentialBroker` config.  No `wire_*()` calls.

### Architecture

```
aiohttp app
├── MSAgentSDKWrapper          POST /api/msagentsdk/.../messages
│     broker ──▶ fireflies (static_key → Adaptive Card + OOB capture)
│               ──▶ workiq   (obo       → OAuthCard + proactive resume)
├── A2AServer (optional)       POST /a2a/rpc
│     same broker config
└── Fireflies capture page     GET/POST /auth/fireflies/capture
```

### Declarative config (no wire_*)

```python
from parrot.auth.credentials import ProviderCredentialConfig
from parrot.auth.broker import CredentialBroker

broker = CredentialBroker.from_config(
    configs=[
        ProviderCredentialConfig(
            provider="fireflies",
            auth="static_key",
            options={"capture_url": "https://your-app/auth/fireflies/capture"},
        ),
        ProviderCredentialConfig(
            provider="workiq",
            auth="obo",
            options={},
        ),
    ],
    vault=vault,
    audit_ledger=audit_ledger,
)

wrapper = MSAgentSDKWrapper(agent=parrot_agent, config=config, app=app, broker=broker)
```

### Per-user auth UX

| Provider | First use (no credential) | After consent |
|---|---|---|
| **Fireflies** (static key) | Adaptive Card with "Authorise Fireflies" link | Bot resumes proactively |
| **Work IQ** (OBO) | OAuthCard — Bot Framework token service sign-in | Bot resumes proactively |

#### Static-key flow (Fireflies)

1. User asks a Fireflies question → no key stored → bot emits an **Adaptive Card**
   with a link to `GET /auth/fireflies/capture?nonce=<nonce>`.
2. User visits the capture page, pastes their API key, and submits.
3. `POST /auth/fireflies/capture` stores the key and calls
   `m365_agent.resume_by_nonce(nonce)`.
4. The bot **proactively** re-runs the original question and delivers the answer —
   the user never retypes.

#### OBO flow (Work IQ)

1. User asks a Work IQ question → no Entra token → bot emits an **OAuthCard**.
2. The Bot Framework Token Service handles the OAuth dance in-channel.
3. `signin/verifyState` or `signin/tokenExchange` invoke arrives.
4. The agent looks up the suspended turn by user ID and **proactively resumes**.

### Proactive resume stores

The `server.py` demo uses in-memory stores for suspend/resume state.  In
production, wire real Redis-backed stores:

```python
import redis.asyncio as aioredis
from parrot.human.suspended_store import SuspendedExecutionStore
from parrot.integrations.msagentsdk.resume import MsaConversationRefStore

redis_client = aioredis.from_url("redis://localhost:6379/1")
wrapper.m365_agent._suspended_store = SuspendedExecutionStore(redis_client)
wrapper.m365_agent._conv_ref_store  = MsaConversationRefStore(redis_client)
wrapper.m365_agent._adapter         = wrapper.adapter
wrapper.m365_agent._agent_app_id    = config.client_id
```

### A2A sub-agent surface

The same `CredentialBroker` is passed to `A2AServer` — no extra config needed:

```python
from parrot.a2a.server import A2AServer

a2a_server = A2AServer(agent=parrot_agent, broker=broker)
app.router.add_post("/a2a/rpc", a2a_server.handle)
```

A Copilot Studio orchestrator can call this agent as a sub-agent (A2A
protocol); user credentials resolve the same way as in the chat surface.

### Note on MCP stubs

Both tools (`workiq_ask`, `fireflies_search`) return demo responses in the
example.  Replace `_execute` bodies with real MCP calls once you have:
- **Work IQ**: a valid Entra OBO token in the resolved credential.
- **Fireflies**: a real API key and a running Fireflies MCP server endpoint.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `ModuleNotFoundError: microsoft_agents` | Install the extra: `uv pip install "ai-parrot-integrations[msagentsdk]"` |
| Copilot Studio: `AuthenticationNotConfigured` ("Authentication is not configured for this bot") even with **None** selected | Copilot's M365 Agents SDK connection does not accept "None". Configure **API Key** (or OAuth 2.0) on the connection and set `MSCOPILOTAGENT_API_KEY` on the server — see section 5b. |
| Teams reply `401 "Authorization has been denied"` (inbound OK, Web Chat OK) | Multi-tenant app minting the reply token against your tenant. Set `MSCOPILOTAGENT_MICROSOFT_APP_TYPE=MultiTenant` (keep `TENANT_ID`) and restart — see the dedicated section above. |
| `{"error": "Authorization header not found"}` from `curl` in `--production` | Expected: production mode requires a valid Azure AD JWT, which `curl` doesn't send. You **cannot** curl-test production (a hand-minted token has the wrong audience/issuer and is rejected too). Test from Copilot Studio's **Test** pane or Teams; for local `curl`/Emulator testing use the default anonymous mode. |
| `JWT validation failed: …` + `401` in `--production` | A token *was* sent but rejected — App ID / tenant in the env don't match the Azure Bot registration Copilot Studio uses. |
| `404` on `reply_to_activity` via `curl` | Expected: replies go out-of-band to `serviceUrl`, which a localhost/fake URL can't serve. The turn still ran — use the Emulator to see the reply. |
| `401` on `reply_to_activity` from Copilot Studio / Teams | Running in **anonymous** mode against a real channel — the empty token is rejected. Switch to `--production` with Azure AD credentials. |
| Inbound `401` from Copilot | App ID / secret / tenant mismatch in `--production` mode |
| "Connected" in Copilot Studio but no logs on a turn | You only validated the endpoint; send a message in the **Test** pane to generate a turn. Run with `--debug` to log every incoming request (incl. the real client IP from `CF-Connecting-IP`/`X-Forwarded-For`). |
| Endpoint reachable but no reply | Channel `serviceUrl` callback can't reach you — confirm the tunnel is up and the messaging endpoint matches the route exactly |
| Empty replies | Empty/whitespace message text is skipped before `ask()` (by design) |
| `CostCalculator: no pricing for provider='gemini'` | Harmless warning — the LLM ran fine; only token-cost accounting is skipped |
