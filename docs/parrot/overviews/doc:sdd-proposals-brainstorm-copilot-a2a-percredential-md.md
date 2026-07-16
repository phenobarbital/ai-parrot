---
type: Wiki Overview
title: 'Brainstorm: AI-Parrot ⇄ Microsoft 365 Copilot via A2A, with parrot-owned per-user
  tool credentials'
id: doc:sdd-proposals-brainstorm-copilot-a2a-percredential-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'We want an AI-Parrot agent — bundling `work-iq`, `fireflies.ai`, and `jira`
  tools — to be invokable from inside the Microsoft 365 Copilot surface. Microsoft
  exposes this via the **Agent-to-Agent (A2A) connection** in Copilot Studio (GA,
  April–May 2026): Copilot''s orchestrator del'
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.a2a
  rel: mentions
---

---
feat_id: FEAT-XXX          # ⚠️ assign real id before /sdd-spec
title: Publish AI-Parrot as an A2A connected agent in Microsoft 365 Copilot with per-user tool credential acquisition
status: brainstorm
owner: Jesus
created: 2026-06-24
artifact_type: brainstorm        # formal SDD input artifact; feeds /sdd-spec
target_packages:
  - ai-parrot-integrations       # A2A server surface, agent card, Copilot wrapper boundary
  - ai-parrot                    # core: CredentialResolver, ToolManager, HITL/Suspend store, AuditLedger
related_specs:
  - TeamsHumanChannel (HITL spec order #1)         # email-as-canonical-id reused here
  - web HITL (SUSPEND / HOT_THEN_SUSPEND)          # SuspendedExecutionStore reused, new trigger
  - CredentialResolver / multi-tenant key isolation
decision_state: Model B (credential custody in parrot) — CLOSED
spike_gate: Open Question #1 (inbound user identity) must be resolved empirically before /sdd-spec
---

# Brainstorm: AI-Parrot ⇄ Microsoft 365 Copilot via A2A, with parrot-owned per-user tool credentials

## 1. Problem statement

We want an AI-Parrot agent — bundling `work-iq`, `fireflies.ai`, and `jira` tools — to be invokable from inside the Microsoft 365 Copilot surface. Microsoft exposes this via the **Agent-to-Agent (A2A) connection** in Copilot Studio (GA, April–May 2026): Copilot's orchestrator delegates a task over A2A to an external agent that advertises an agent card on the standard `.well-known` URL.

The hard part is **not** the connection. It is per-user tool authentication. Two of the three tools require credentials scoped to the *individual end user*, not to a shared service identity:

- `work-iq` → Microsoft Entra (delegated, on-behalf-of the user)
- `jira` → Atlassian OAuth2 3LO (different IdP)
- `fireflies.ai` → static API key (no OAuth2 flow per current observation; MCP-OAuth variant exists — see OQ#6)

A2A does not carry user identity in the payload, and Copilot's connector framework only manages credentials for tools **Copilot itself knows about**. Tools that live inside an A2A connected agent are invisible to Copilot. Therefore parrot must own the full credential lifecycle for its own tools.

## 2. Goals / Non-goals

**Goals**
- Stand up parrot as an A2A server, expose it publicly (ngrok for the spike), connect it as an A2A agent in Copilot Studio.
- Acquire and persist per-user credentials for `work-iq` / `jira` / `fireflies` under parrot's custody.
- Reuse existing primitives (`CredentialResolver`, `SuspendedExecutionStore`, `AuditLedger`, `ToolManager`, user vault) rather than introduce parallel machinery.

**Non-goals (this feature)**
- Making parrot appear as a *standalone* agent in the Copilot/Outlook sidebar (that needs a published wrapper — separate track).
- Re-implementing tool orchestration in Copilot. Orchestration stays in parrot; Copilot only delegates a task and transports the response.
- Supporting credential custody inside Copilot's connection store (explicitly rejected — see §3).

## 3. Core architectural decision — CLOSED

### Decision: Model B — credential custody in parrot

For every per-user credential there is a binary custody choice. They are mutually exclusive for the same secret:

| | Model A: custody in Copilot | Model B: custody in parrot (**chosen**) |
|---|---|---|
| Where secret lives | Power Platform connection store | parrot user vault |
| Acquisition UX | Inline secure auth card rendered by Copilot's connector framework | Link-out to parrot's own authenticated web surface (OOB) |
| Who orchestrates the tool | Copilot | parrot |
| `CredentialResolver` / `key_fingerprint` / `AuditLedger` | Not available — parrot never holds the credential | Fully preserved |
| Multi-tenant isolation per client | Governed by Power Platform, outside our boundary | Governed by our PBAC/`PermissionContext` |
| Cost | Loses our audit + isolation story | No inline card; link-out is the price of custody |

**Rationale:** The inline API-key input observed today in Copilot exists *because the tool is a Copilot-side connector* (Copilot renders the card, secret → connection store). That affordance does not extend to tools inside an A2A agent. Given the multi-tenant isolation invariant and the `AuditLedger` requirement to record `key_fingerprint`, custody must stay in parrot. The link-out pattern is therefore not a limitation — it is the necessary consequence of owning custody. (Direct lineage to the `python_repl` env-leak incident: secrets must never traverse a surface where the model or the transcript can observe them.)

## 4. Auth surface decision table

Three IdP surfaces, but the Microsoft cluster shares one sign-in:

| Tool | IdP | Mechanism | Consent surface | Token store | Notes |
|---|---|---|---|---|---|
| `work-iq` | Microsoft Entra | Entra OBO (token exchange) → Work IQ scopes | **Shared** Microsoft Entra sign-in (link-out) | vault, per-user | ⚠️ VERIFY Work IQ (public preview) OBO support + resource/scope ids |
| `o365` / Graph | Microsoft Entra | Entra OBO → Graph scopes | **Shared** Microsoft Entra sign-in (same as work-iq) | vault, per-user | One Entra sign-in amortized across both MS resources |
| `jira` | Atlassian | OAuth2 3LO authorization code (+PKCE) | Dedicated link-out → Atlassian redirect → parrot callback | vault, per-user (incl. refresh token) | No Entra↔Atlassian federation; cannot OBO from Entra token |
| `fireflies` | none | static API key capture | Dedicated link-out → key form (HTTPS POST to parrot) | vault, per-user | ⚠️ VERIFY MCP-OAuth variant (OQ#6) before fixing to api-key only |

**Key consequence:** a single Microsoft Entra sign-in produces the OBO *source* token, from which **both** `o365` and `work-iq` are obtained by exchanging for different resource scopes. That sign-in also establishes parrot's own user identity, partially mitigating OQ#1 for the Microsoft cluster.

## 5. Credential acquisition flow (link-out, OOB)

```
Copilot ── A2A task ──▶ parrot.handle_task()
                          │
                          ├─ resolve user identity  ─────────────▶ [OQ#1 gate]
                          │
                          ├─ tool requires credential not in vault?
                          │     │
                          │     ├─ suspend task   ─▶ SuspendedExecutionStore (Redis TTL)
                          │     │                     key: nonce  ⇄  {task_id, user_identity, tool}
                          │     │
                          │     └─ A2A response = TEXT + consent link
                          │           "Connect <tool>: https://parrot/auth/<nonce>"
                          │
   user clicks link (browser, OOB) ──▶ parrot auth surface
        │
        ├─ Microsoft Entra sign-in  → OBO source token → vault (covers o365 + work-iq)
        ├─ Atlassian 3LO redirect   → callback → vault (jira)
        └─ API-key form (HTTPS POST)→ vault (fireflies)
        │
        └─ on success: resume suspended task via nonce correlation
                          │
                          ▼
              parrot re-runs tool with CredentialResolver-provided client
                          │
                          ▼
              A2A response = result;  AuditLedger ← key_fingerprint
```

**HITL credential-acquisition is a NEW interaction type.** It reuses `SuspendedExecutionStore` (suspend → persist → resume) but the resume trigger is an **OAuth callback / form POST**, not a human-approver message. It must be modeled distinctly from the existing approval/escalation HITL, which assume parrot's own channels (Teams/web). Here the "human" is on the Copilot surface; the chat only carries the link and the final state.

**Nonce correlation:** the consent link carries a one-time, short-TTL nonce (the OAuth `state` param) binding the web session → the suspended-execution entry. Callback/POST presents the nonce → parrot correlates → resumes. This is also the user↔credential↔task binding for audit.

## 6. Invariants (Pydantic-level where enforceable)

1. **No secrets in the conversational plane.** Credentials are acquired only on parrot's authenticated web surface, OOB. The A2A channel carries links and states only. (Copilot re-sends full chat history every turn — anything typed into chat is persisted and re-transmitted.)
2. **Never fall back to service identity for a per-user tool.** If no per-user credential exists, emit a credential-acquisition interaction. A `client_credentials` fallback silently downgrades attribution and breaks RLS + audit. Freeze as invariant.
3. **`CredentialResolver` mediates all tool credentials.** Tools receive a resolved client / handle, never a raw token in context. (Same seam discipline as the output scrubber at `AbstractTool`.)
4. **`AuditLedger` records `key_fingerprint`, never the secret.** Append-only, KMS-signed; strictly separated from any behavioral `EpisodicMemory`.
5. **Vault keyed by canonical identity** (email, consistent with `TeamsHumanChannel`). Values are per-provider tokens. Requires an account-linking map (Entra identity ⇄ {atlassian_account, fireflies_account}).

## 7. Codebase Contract (⚠️ VERIFY — grep anchors, never line numbers)

These symbols are referenced from working memory of the platform vocabulary; **paths and signatures are unverified**. Confirm each before /sdd-spec.

```
⚠️ VERIFY  CredentialResolver           grep -rn "class CredentialResolver"        ai-parrot/
⚠️ VERIFY  SuspendedExecutionStore       grep -rn "class SuspendedExecutionStore"   ai-parrot/
⚠️ VERIFY  AuditLedger                   grep -rn "class AuditLedger"               ai-parrot/
⚠️ VERIFY  ToolManager                   grep -rn "class ToolManager"               ai-parrot/
⚠️ VERIFY  PermissionContext             grep -rn "class PermissionContext"         ai-parrot/ (navigator-auth?)
⚠️ VERIFY  AbstractTool (scrubber seam)  grep -rn "class AbstractTool"              ai-parrot-tools/
⚠️ VERIFY  A2A server surface            grep -rn "well-known"                      ai-parrot-integrations/
⚠️ VERIFY  agent card construction       grep -rn "agent_card\|AgentCard"           ai-parrot-integrations/
⚠️ VERIFY  user vault abstraction        grep -rn "vault\|CredentialStore"          ai-parrot/
⚠️ VERIFY  Entra OBO helper (if any)     grep -rn "on_behalf_of\|obo\|token_exchange" ai-parrot-integrations/
```

## 8. Does NOT exist (must be built — to prevent implementation hallucination)

- A credential-acquisition HITL interaction type. Existing HITL = approval/escalation only. This is new.
- An OAuth-callback / form-POST resume trigger on `SuspendedExecutionStore`. Existing resume triggers assume human-approver messages on parrot channels.
- An account-linking map (canonical identity ⇄ per-provider account). Not assumed to exist.
- A parrot-owned authenticated web surface for credential capture (Entra sign-in, Atlassian 3LO redirect+callback, API-key form). Endpoints, nonce issuance, TTL.
- Work IQ OBO client (resource id + scopes). Public-preview API; unverified it supports delegated OBO at all (OQ#5).

## 9. Open Questions (resolve before / during /sdd-spec)

1. **[SPIKE GATE] Does Copilot's low-code A2A connection deliver a stable, verifiable per-user identity to parrot?** Docs show payload = chat history + locale + routing metadata; per-user identity passthrough is documented for *Foundry Agent Service*, not the Copilot Studio low-code A2A connection. If absent, parrot must run its own Entra sign-in (link-out) to establish identity, and every subsequent A2A turn must still map to it. **The whole vault-keying premise depends on this. Spike answers it empirically.**
2. Does Copilot's A2A *client* support the A2A `input-required` state and resume it after an OOB flow? If not, fall back to "link in response → user re-prompts after consent." (Robust default regardless.)
3. Wrapper surface: Copilot Studio low-code agent vs Foundry-hosted agent. Foundry gives documented OAuth identity passthrough (helps OQ#1) but couples us to Foundry. Decide per the identity finding.
4. ngrok reserved domain (stable redirect URI) for the spike — free ngrok rotates the subdomain per restart and will invalidate registered OAuth redirect URIs. Reserve before spiking.
5. Work IQ (public preview): does it support Entra OBO? Resource id + required scopes? Admin consent path?
6. Fireflies: confirm api-key only vs an MCP-OAuth variant. If MCP, parrot is an MCP client and the auth surface changes (MCP-OAuth authorization code).
7. Account-linking UX: how does the user assert their Atlassian/Fireflies identity relative to their Entra identity? Implicit at consent time, or explicit linking step?
8. Token refresh + revocation: refresh-token lifecycle for jira; key rotation/invalidation for fireflies; re-consent triggers surfaced back through the A2A channel.
9. Which AgentCard schema version does Copilot's a2a-dotnet resolver pin — v0.3 (`url`+`preferredTransport`) or v1.0 (`supportedInterfaces`)? Partially characterized in §11; confirm empirically via card dump + autopopulate result. Determines whether dual-emit suffices or a v1.0-only card is required.

## 10. Spike plan (ngrok, validation-first)

Before /sdd-spec, empirically establish:
0. **AgentCard discovery** (transport spike, IN PROGRESS) — connection + invocation already work; name/description do NOT autopopulate. Dump the served card (`curl -s <tunnel>/.well-known/agent-card.json | jq`) and read the access-log line for the `agent-card.json` GET. Confirms fetch-vs-parse and shows casing + schema shape at a glance. → resolves OQ#9. See §11.
1. **Payload inspection** — log the full A2A request (body + headers) Copilot sends. Confirm presence/absence of a verifiable user identity claim. → resolves OQ#1, the gate.
2. `input-required` round-trip — does Copilot prompt + resume, or must we use link-then-reprompt? → OQ#2.
3. Agent-card `securityScheme` behavior — does declaring an apiKey/oauth2 scheme trigger a per-user connection capture in Copilot, and at what timing (setup vs runtime)? → confirms Model A is genuinely unsuitable for our custody goal.
4. End-to-end link-out for one tool (fireflies, simplest) — task → suspend → link → form POST → vault → resume → result.

Spike is throughput-validation only; code in worktree, SDD state on `dev`.

## 11. AgentCard discovery — schema research (v0.3 ↔ v1.0)

**Observed symptom (spike, current).** Copilot Studio connects to parrot as an A2A sub-agent and successfully *invokes* it (task delegated, processed, response returned), but does **not** autopopulate the agent name/description from the card — i.e. discovery/parse fails while transport succeeds.

**Why transport works but discovery doesn't (the key decoupling).** Copilot's PowerFx A2A connector POSTs `message/send` to the connector **host origin** (`/`), not the `url` declared in the card. (Confirmed empirically: `POST / [405] ua=CopilotStudio PowerFx/...` before the root JSON-RPC handler was mounted.) So invocation never depends on parsing the card correctly. Only autopopulate does. This cleanly separates the two failure domains.

**Root cause — two incompatible AgentCard shapes:**

| | A2A v0.3.x | A2A v1.0 |
|---|---|---|
| Endpoint declaration | top-level `url` + `preferredTransport: "JSONRPC"` | `supportedInterfaces: [{ url, protocolBinding, protocolVersion }]` (no top-level `url`/`preferredTransport`) |
| `protocolVersion` | `"0.3.0"` (top-level, default) | `"1.0"` (per interface) |
| What `parrot.a2a` currently emits | **this shape** (per `server.py` docstring + `preferredTransport: JSONRPC`) | — |
| What a2a-dotnet (Copilot's SDK) expects | tolerant of? ⚠️ VERIFY | **this shape** — README example uses `SupportedInterfaces` only; "A2A v1 Is Here" devblog: resolver negotiates transport from `supportedInterfaces` |

a2a-dotnet migrated to A2A v1.0. If its resolver looks for `supportedInterfaces` and parrot emits only the v0.3 top-level `url`/`preferredTransport`, name/description/transport never bind → no autopopulate. **This is hypothesis #1.**

**Second silent failure mode — serialization casing.** The A2A spec mandates **camelCase** for all JSON wire serializations ("MUST use camelCase, not the snake_case Protocol Buffer convention"). If `AgentCard.to_dict()` emits snake_case (`preferred_transport`, `default_input_modes`, `protocol_version`, `supported_interfaces`), the .NET `System.Text.Json` (camelCase) parser binds nothing → empty card, silently. The snake_case examples circulating (e.g. A2A Registry) are Python-side API payloads, not the wire card. **Hypothesis #2; check first because it's a one-line confirm.**

**Third — missing required fields.** Strict typed deserializers empty the object if `protocolVersion`, `capabilities`, `defaultInputModes`, or `defaultOutputModes` are absent.

### Decision: dual-emit + camelCase

Emit **both** shapes in one card. A v1.0 parser reads `supportedInterfaces`; a tolerant v0.3 parser reads the top-level fields. Unknown extra fields are ignored by `System.Text.Json` defaults, so duplication is safe. Fall back to **v1.0-only** (drop top-level `url`/`preferredTransport`) only if a strict v1 parser rejects the duplicate top-level `url`.

Reference card (camelCase, dual-emit) — the known-good to diff the served card against:

```jsonc
{
  "protocolVersion": "0.3.0",
  "name": "BotanistAgent",
  "description": "Answers plant-care questions; looks up sunlight needs.",
  "version": "1.0.0",
  "url": "https://<tunnel>/a2a/rpc",                      // v0.3 compat
  "preferredTransport": "JSONRPC",                        // v0.3 compat
  "supportedInterfaces": [                                // v1.0 (a2a-dotnet)
    { "url": "https://<tunnel>/a2a/rpc", "protocolBinding": "JSONRPC", "protocolVersion": "1.0" }
  ],
  "capabilities": { "streaming": false },
  "defaultInputModes": ["text/plain"],
  "defaultOutputModes": ["text/plain"],
  "skills": [
    { "id": "get_plant_light_needs", "name": "Plant light needs",
      "description": "Daily sunlight requirement for a plant.", "tags": ["botany"] }
  ]
}
```

### Where the fix lands (anchors verified from `examples/a2a/server.py`)

```
VERIFIED   AgentCard model + serialization   grep -rn "class AgentCard"            parrot/a2a/models.py     # emits to_dict()
VERIFIED   card accessor                     grep -rn "def get_agent_card"         parrot/a2a/             # a2a.get_agent_card().to_dict()
VERIFIED   card to_dict serialization        grep -rn "def to_dict"                parrot/a2a/models.py     # ← assert camelCase + supportedInterfaces here
VERIFIED   well-known route / setup          grep -rn "def setup"                  parrot/a2a/             # a2a.setup(app, url=...)
VERIFIED   JSON-RPC handler                  grep -rn "_handle_jsonrpc"            parrot/a2a/             # mounted at /, /a2a, /a2a/rpc
⚠️ VERIFY  AgentCapabilities serialization   grep -rn "class AgentCapabilities"    parrot/a2a/models.py
```

The fix is a change to `parrot.a2a` (the `AgentCard` model / `to_dict`), **not** `server.py` — the card is auto-generated by `A2AServer` from the agent's tools. `server.py`'s well-known catch-all middleware is correct and can stay; it only serves whatever `to_dict()` produces.

### Decisive diagnostic (one command + one log line)

```bash
curl -s https://<tunnel>/.well-known/agent-card.json | jq
```

Read: (1) are fields camelCase? (2) is `supportedInterfaces` present, or only `url`+`preferredTransport`? Cross-check the access-log line `GET …/.well-known/agent-card.json [200]` → a 200 with no autopopulate proves parse-failure, not fetch-failure. (Cannot be inferred from source; must be observed — `to_dict()` output is not visible without dumping it.)

### Sources

- A2A v0.3 spec (AgentCard, transport rules, camelCase MUST): https://a2a-protocol.org/v0.3.0/specification/ and https://github.com/a2aproject/A2A/blob/main/docs/specification.md
- a2a-dotnet SDK (v1.0 `SupportedInterfaces` card shape): https://github.com/a2aproject/a2a-dotnet
- "A2A v1 Is Here" — Microsoft Agent Framework for .NET (resolver negotiates from `supportedInterfaces`): https://devblogs.microsoft.com/agent-framework/a2a-v1-is-here-cross-platform-agent-communication-in-microsoft-agent-framework-for-net/
- Copilot Studio A2A connection quickstart: https://learn.microsoft.com/en-us/microsoft-copilot-studio/add-agent-agent-to-agent

## 12. Acceptance criteria (for the eventual spec)

- A2A task that needs a missing credential suspends and returns a consent link; no secret ever appears in any A2A payload or Copilot transcript.
- OOB consent (Entra / Atlassian / api-key form) persists a per-user credential in the vault keyed by canonical identity; suspended task resumes via nonce.
- One Microsoft Entra sign-in yields working OBO for both `o365` and `work-iq`.
- `CredentialResolver` returns resolved clients to tools; raw tokens never enter model/tool context.
- `AuditLedger` records `key_fingerprint` for every credentialed tool invocation; no `client_credentials` fallback path exists for per-user tools.
- Negative test: a tool with no per-user credential never executes under a service identity.

## 13. Revision history

| Date | Author | Change |
|---|---|---|
| 2026-06-24 | Jesus / brainstorm | Initial. Model B closed; auth table; OBO unification for MS cluster; OQ#1 set as spike gate. |
| 2026-06-26 | Jesus / spike | Transport spike: Copilot connects + invokes as A2A sub-agent (POSTs to host origin `/`, not card `url`). Card discovery still failing. Added §11 AgentCard schema research (v0.3↔v1.0 fork + camelCase MUST + dual-emit decision + reference card); added OQ#9; added spike step 0. Fix lands in `parrot.a2a` model/`to_dict`, not `server.py`. |
