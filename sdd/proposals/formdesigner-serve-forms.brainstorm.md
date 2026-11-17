---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [ai-parrot-integrations, parrot-formdesigner, ai-parrot]
tags: [msteams, formdesigner, adaptive-card, mixin, toolkit, tenant]
---

# Brainstorm: Serve FormDesigner forms from a Teams agent (`/getform` mixin + toolkit)

**Date**: 2026-10-23
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

FEAT-551 (`msteams-formdesigner-renderer`, all 7 tasks done) built **half** of the
Teams form loop: FormDesigner can export any `FormSchema` as an Adaptive Card
(`GET …/forms/{uid}/render/teams`), the terminal `Action.Submit` carries a signed
`TeamsSubmitEnvelope`, and `MSTeamsAgentWrapper` verifies that envelope and forwards
the answers to `POST …/forms/{uid}/data`.

What is missing is **the agent side of the loop**:

1. **Nobody can ask for a form.** There is no `/getform` command, and no code path
   that *fetches* a form. The only FormDesigner HTTP traffic the bot makes is the
   submit-only POST on `wrapper.py` — there is no FormDesigner read client anywhere
   in the repository, and no `formdesigner_list_forms` / `formdesigner_get_form`
   tool for an LLM to call.
2. **The card has to be posted by hand.** The FEAT-551 documentation ends with
   *"post the returned Adaptive Card JSON to a Teams conversation (however your
   integration delivers proactive/interactive cards)"*. Serving the card is an
   exercise left to the operator.
3. **The submission is not the user's.** The forward is authenticated with a
   single process-wide service token (`formdesigner_submit_token`), so every
   submission reaches FormDesigner as the same principal. The Teams lane has no
   user identity at all: FEAT-729 (`msteams-user-auth-lane`) specs the whole
   `UserContext` / `/login` / token-exchange stack and was **approved on
   2026-10-23, but has no task index and zero tasks — nothing of it is
   implemented**. And `MSTeamsAgentConfig` has no FormDesigner tenant field — only
   `app_tenantid`, the Azure AD GUID.

> **Verified at commit `73ee6dc24`** (branch `dev`). `dev` moved twice while this
> document was being written: FEAT-729 was approved and FEAT-733 was decomposed
> into six tasks. Every reference below was re-checked at that commit.

**Who is affected**: operators who want a Teams-exposed parrot agent to *serve*
FieldSync/FormDesigner forms conversationally ("give me the store-visit form"),
and the end users who today have to leave Teams for the web form. Composing a
form-serving agent currently means hand-writing wrapper glue per deployment.

**Why now**: the renderer, the envelope, the submit path, the command router and
the per-tenant form registry all already exist. The missing piece is a *composable*
unit — a mixin plus a toolkit — that turns those parts into an agent capability.

## Constraints & Requirements

- **Reuse FEAT-551, do not fork it.** The signed `TeamsSubmitEnvelope` and
  `verify_envelope()`'s fixed check order (https → host allowlist → path/tenant/uid
  → signature) stay the security boundary, even when the final POST carries a
  per-user bearer. *(Round 2 decision.)*
- **The signature is becoming mandatory.** FEAT-733's six pending tasks
  (TASK-4653…TASK-4658) add `require_signature` to `verify_envelope()` and a
  `teams_signing_secret` pairing on `setup_form_api()`, so an unsigned envelope
  will be refused. Any card this feature produces — including the in-process
  render path — must therefore be signed, which makes `signing_secret`
  non-optional in `local` mode rather than a nicety.
- **Dual render.** Remote FormDesigner → HTTP `GET …/render/teams?with_meta=true`
  (the server signs). Embedded FormDesigner → in-process `TeamsFormRenderer` over
  the local `FormRegistry`. *(Round 1 decision.)*
- **Per-user bearer, blocking on FEAT-729.** The bearer is the authenticated
  user's Navigator session token (`MSTeamsUserSession.nav_session_token`), never a
  shared service token. This feature cannot ship before the FEAT-729 auth lane
  exists. *(Round 1 decision.)*
- **One package.** Mixin, client, cards and toolkit all live in
  `ai-parrot-integrations` under `parrot/integrations/msteams/`. *(Round 1
  decision.)*
- **The mixin wins, the wrapper falls back.** When the agent carries the mixin it
  owns `/getform`, the picker action and the card submission; when it does not, the
  existing FEAT-551/FEAT-733 wrapper branch keeps working unchanged. *(Round 2
  decision.)*
- **Tenant: user first.** Tenant comes from the authenticated principal, then the
  FEAT-733 `formdesigner_tenant_map` (AAD GUID → FormDesigner slug), then a static
  bot config value. *(Round 2 decision.)*
- **Degrade, never lie.** No session → a login card. Upload fields → the existing
  `TeamsFormRenderer` notice + `Action.OpenUrl` + `RenderWarning`, surfaced to the
  user. *(Round 2 decision.)*
- Async-only `aiohttp` (never `requests`/`httpx`); the new client's session must be
  closed on shutdown — the existing one is not (ledger `a9514c9232ad`).
- Teams caps Adaptive Cards at schema 1.6 and supports no file upload inputs.
- No core (`ai-parrot`) change required; `parrot/bots/mixins/` stays
  channel-agnostic.

---

## Options Explored

### Option A: `TeamsFormDesignerMixin` — agent-owned command, picker and submit, in `ai-parrot-integrations`

A single mixin, mixed into an agent that is exposed through the MS Teams
integration, contributes four things at once:

1. **Commands** — `/getform [slug-or-uid]` and `/listforms`, registered on the
   existing `MSTeamsCommandRouter`.
2. **A toolkit** — `formdesigner_list_forms` (tenant-scoped) and
   `formdesigner_get_form`, contributed through the agent's `agent_tools()` seam so
   the LLM can reach the same capability without a slash command.
3. **Cards** — the rendered form card (remote `render/teams` or in-process
   `TeamsFormRenderer`) and a **picker card** (`Input.ChoiceSet` of the tenant's
   forms + Submit) whose action re-enters `formdesigner_get_form`.
4. **One card-submission handler** — consulted by the wrapper *before* its own
   FEAT-551 branch; it handles both the picker action and the real form submission,
   reusing `parse_envelope` / `verify_envelope` / `post_submission` /
   `RecentActivityCache` but with the current user's bearer.

A small, additive seam in the wrapper makes the delegation possible: at the
existing `if ENVELOPE_KEY in submitted_data:` branch the wrapper asks the agent
first (`handle_formdesigner_card(turn_context, submitted_data) -> bool`), and only
runs `_handle_formdesigner_submit` when the agent declines or has no mixin. A
second seam lets the agent contribute commands that need the `TurnContext` — the
existing `config.commands` mechanism cannot be reused for this, because
`_make_custom_handler` calls `method(**kwargs)` with text-parsed kwargs and never
passes the `TurnContext`, so a handler registered that way can neither send a card
nor read the Teams identity.

✅ **Pros:**
- Every FEAT-551 artifact is reused as-is: renderer, envelope, verifier, forwarder,
  reply cards, duplicate-activity cache.
- One drop-in unit: `class MyAgent(TeamsFormDesignerMixin, Agent)` plus Teams
  config is the whole operator story.
- The per-user bearer lands exactly where it matters (the final POST), with the
  HMAC envelope kept as defence in depth.
- Slash command and tool-calling share one implementation, so the LLM path and the
  `/getform` path cannot drift.
- Two wrapper seams only, both additive and `getattr`-guarded: an agent without the
  mixin behaves exactly as today.

❌ **Cons:**
- Hard-blocked on FEAT-729 (approved, **zero tasks**) for the bearer and coupled to
  FEAT-733 (approved, **six pending tasks**) for the tenant map and the mandatory
  signature — three in-flight features touching the same three files
  (`wrapper.py`, `models.py`, `formdesigner_submit.py`).
- Puts a concrete toolkit in `ai-parrot-integrations` rather than `parrot_tools`,
  bending the "concrete tools live in ai-parrot-tools" convention (accepted
  deliberately in Round 1 for cohesion).
- Dual render means two trust shapes: remote cards are signed by the server,
  in-process cards are signed by the agent, so the agent needs `signing_secret` and
  `public_base_url` in local mode.
- The mixin is Teams-specific; a Telegram or Slack equivalent would be a sibling,
  not a reuse.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiohttp` | FormDesigner read/submit client | already the only allowed HTTP client; the wrapper already holds a submit session |
| `botbuilder-core` / `botbuilder-schema` | `TurnContext`, `Activity`, `Attachment` | already a dependency of `ai-parrot-integrations` |
| `parrot-formdesigner` | `FormSchema`, `TeamsFormRenderer`, `TeamsSubmitEnvelope` | already a workspace dependency of `ai-parrot-integrations` (`pyproject.toml:61`, `:184`) |
| `pydantic` v2 | envelope / client response models | `TeamsSubmitEnvelope` and `SubmitOutcome` are already Pydantic v2 |

🔗 **Existing Code to Reuse:**
- `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/teams.py` —
  `TeamsFormRenderer`, `TeamsSubmitEnvelope`, `build_envelope()`, upload degradation.
- `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_submit.py`
  — `parse_envelope`, `verify_envelope`, `extract_answers`, `post_submission`,
  `build_reply_card`, `RecentActivityCache`.
- `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/__init__.py`
  — `MSTeamsCommandRouter.register()` / `try_dispatch()`.
- `packages/ai-parrot-integrations/src/parrot/integrations/msteams/handler.py` —
  `MessageHandler.send_card()`, inherited by the wrapper.
- `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` +
  `api/handlers.py` — `GET {tp}/forms` (`list_forms`), `GET {tp}/forms/{uid}`,
  `GET {tp}/forms/{uid}/render/{format}`, `POST {tp}/forms/{uid}/data`.
- `packages/ai-parrot/src/parrot/bots/agent.py` — `agent_tools()` tool-contribution
  seam; `packages/ai-parrot/src/parrot/tools/toolkit.py` — `AbstractToolkit`.

---

### Option B: Wrapper-only — a `/getform` command on `AgentCommandHandler`, no mixin

Add `getform` / `listforms` straight into the existing `AgentCommandHandler`
alongside `/function`, `/skill`, `/whoami`, and a FormDesigner read client on the
wrapper next to the submit session it already owns. The card is rendered over HTTP
and posted with `send_card()`; the submission keeps flowing through the existing
`_handle_formdesigner_submit` with the configured service token. No mixin, no
toolkit, no agent-side code at all.

✅ **Pros:**
- Smallest change by far, and entirely inside code FEAT-551 already owns.
- Ships *today*: no FEAT-729 dependency, because there is no per-user bearer.
- One render path (HTTP), one trust model (server-signed envelope), nothing new to
  secure.

❌ **Cons:**
- Not composable: the capability belongs to *every* Teams bot or none; an agent
  cannot opt in, cannot override the picker, cannot be tested without the Teams
  stack.
- No toolkit, so the LLM cannot reason about forms — `/getform` only works as a
  literal command, which is the opposite of the tool-centric architecture.
- Keeps the shared-service-token posture: FormDesigner sees one principal for all
  users, so audit trails and RLS stay blind (and the FEAT-732 validation audit
  trail records the bot, not the person).
- Requires an embedded FormDesigner to still be reached over HTTP (loopback),
  wasting the in-process registry.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiohttp` | read client on the wrapper | reuses `_get_formdesigner_session()` |
| `parrot-formdesigner` | `FormSchema` only | already a dependency |

🔗 **Existing Code to Reuse:**
- `…/msteams/commands/agent_commands.py` — `AgentCommandHandler.register()`, the
  established place for built-in commands.
- `…/msteams/wrapper.py` — `_get_formdesigner_session()`,
  `_handle_formdesigner_submit()`, `_handle_card_submission()`.

---

### Option C: Channel-agnostic `FormServingMixin` in core + per-channel adapters

Put the capability in core (`packages/ai-parrot/src/parrot/bots/mixins/`) as a
channel-neutral mixin that resolves a form and returns an abstract *form artifact*
(the `FormSchema` plus a render intent), and let each integration adapt it: Teams →
`TeamsFormRenderer`, Telegram → the existing `renderers/telegram/` WebApp path
(FEAT-081, done), web/A2UI → `renderers/a2ui.py`. The toolkit lands in
`parrot_tools.formdesigner`, per the repository convention.

✅ **Pros:**
- One capability, every channel — Telegram already has a shipped form renderer, so
  the second channel is nearly free.
- Respects the documented layering: core mixin, concrete tools in `parrot_tools`,
  channel glue in `ai-parrot-integrations`.
- The mixin becomes unit-testable with no Bot Framework at all.

❌ **Cons:**
- Core would grow knowledge of form serving and of channel render intents, and
  `parrot/bots/mixins/` would gain a dependency direction it does not have today.
- Materially more design work: the abstract artifact has to cover Adaptive Card
  submit envelopes *and* Telegram WebApp round-trips *and* A2UI — three different
  return-path shapes, only one of which is needed now.
- Highest effort for a capability that has exactly one requested channel.
- Rejected in Round 1: the user chose a single package (`ai-parrot-integrations`).

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `parrot-formdesigner` | renderers for 3 channels | `renderers/teams.py`, `renderers/telegram/`, `renderers/a2ui.py` all exist |
| `aiohttp` | shared read client | would live in core or `parrot_tools` |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/bots/mixins/` — `IdentityMixin`,
  `ModelSwitchingMixin`, lazy-export pattern in `mixins/__init__.py`.
- `packages/ai-parrot/src/parrot/skills/mixin.py` — `SkillRegistryMixin`, the
  closest precedent for a mixin that owns configuration *and* contributes tools.
- `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/telegram/` —
  the shipped second-channel renderer (FEAT-081).

---

### Option D *(unconventional)*: Tool-only — the toolkit returns a card, the response parser serves it

No command, no card handler. `formdesigner_get_form` is an ordinary tool that
returns an Adaptive Card payload as its result; the agent's answer flows through
the wrapper's existing `parse_response()` / `parrot.outputs.cards` rendering path,
which already turns structured agent output into Teams attachments. `/getform`
degenerates into a one-line alias that asks the LLM to call the tool. The picker
is just another tool result.

✅ **Pros:**
- Maximum leverage of what exists: the wrapper already parses agent responses and
  already renders `CardSpec` output; no new wiring in `_handle_card_submission` for
  the *outbound* direction.
- Purely tool-centric — exactly the architecture the project documents, and the
  capability is immediately available to any channel that renders agent cards.
- Natural conversational UX: "do I have a store-visit form?" works without a
  command vocabulary.

❌ **Cons:**
- The **inbound** direction is unsolved: `Action.Submit` arrives as a Bot Framework
  activity, never as a tool result, so a card-submission handler is still required
  — the option removes the easy half and keeps the hard half.
- Non-deterministic: whether the user gets a form depends on the LLM choosing the
  tool, which is unacceptable for a compliance-adjacent flow ("fill this form").
- Card JSON as a tool result pollutes the conversation history with large payloads
  and burns context (FEAT-525 compaction would prune it unpredictably).
- No place for per-user bearer resolution, which needs the `TurnContext`.

📊 **Effort:** Low (outbound) / unresolved (inbound)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `parrot.outputs.cards` | `CardSpec`, `render`, `markdown_to_sections` | already imported by the Teams wrapper |
| `parrot-formdesigner` | render the card payload | already a dependency |

🔗 **Existing Code to Reuse:**
- `…/msteams/wrapper.py` — `parse_response()` / `_send_parsed_response()` and the
  `parrot.outputs.cards` import block.
- `packages/ai-parrot/src/parrot/tools/toolkit.py` — `AbstractToolkit.get_tools()`.

---

## Recommendation

**Option A** is recommended.

It is the only option that closes **both** directions of the loop with the parts
that already exist. Option D is attractive until the inbound `Action.Submit` is
considered: the Bot Framework delivers it as an activity, so a card handler is
unavoidable — and once that handler exists, the mixin of Option A is the natural
owner of it, with the toolkit of Option D kept as a *second* entry point rather
than the only one. Option B is genuinely cheaper and unblocked, but it buys that
speed by giving up both composability and per-user identity, which is precisely
what the request is about ("un Mixin que pueda ser incorporado a un agente", "las
credenciales del current-user"). Option C is the better long-term shape and should
be revisited when a second channel is actually requested; today it trades a large
abstraction cost for a channel nobody asked for, and Round 1 explicitly chose the
single-package layout.

What Option A trades away, stated plainly:

- **Schedule.** It is blocked by FEAT-729 and coupled to FEAT-733. Accepted: a
  service-token interim was offered in Round 1 and declined, because a form
  submission attributed to the bot instead of the person is worse than no feature
  (FEAT-732 is building an audit trail that would record the wrong principal).
- **Layering.** The toolkit sits in `ai-parrot-integrations`, not `parrot_tools`.
  Accepted for cohesion; the toolkit is written against the client, not against the
  Teams SDK, so a later move to `parrot_tools` (Option C's layout) is a file move
  plus a re-export, not a rewrite.
- **Two trust shapes** from dual rendering. Mitigated by routing both through the
  same `verify_envelope()` on the way back, so the agent can only accept an
  envelope it (or its configured server) could have signed.

---

## Feature Description

### User-Facing Behavior

In a Teams 1:1 or channel conversation with a parrot agent that carries the mixin:

| Input | Response |
|---|---|
| `/listforms` | A **picker card**: the tenant's forms as an `Input.ChoiceSet` (title + description), one Submit button. Choosing one and submitting posts that form's card. |
| `/getform` (no argument) | Same picker card. |
| `/getform store-visit` or `/getform <uid>` | The form rendered as an interactive Adaptive Card, filled in place. |
| "¿tengo algún formulario de visita a tienda?" | The LLM calls `formdesigner_list_forms` / `formdesigner_get_form` and answers; the picker or the form card follows. |
| Submit on a form card | The answers go to FormDesigner **as the speaking user**; a confirmation card reports success, validation errors (422, per-field) or rejection (403). |
| Any of the above with no session | A card stating that sign-in is required, pointing at `/login`. Nothing is fetched. |
| A form with upload fields | The card renders, with a notice and an **Open web form** button for the upload parts, plus a visible note that attachments must be added on the web. |

### Internal Behavior

```
/getform <slug>                      picker Submit                    form Submit
      │                                    │                                │
      ▼                                    ▼                                ▼
MSTeamsCommandRouter            _handle_card_submission          _handle_card_submission
      │ try_dispatch                       │ agent-first seam               │ agent-first seam
      ▼                                    ▼                                ▼
TeamsFormDesignerMixin.handle_getform / handle_formdesigner_card
      │
      ├── resolve_tenant()   session.tenant → formdesigner_tenant_map[aad_guid] → config fallback
      ├── resolve_bearer()   MSTeamsUserSession.nav_session_token  (no session → login card)
      │
      ├── mode == "remote":  GET {base}/{api}/{tenant}/forms/{uid}/render/teams?with_meta=true
      │                      → {"content", "content_type", "warnings", "metadata.envelope"}
      │
      └── mode == "local":   FormRegistry.get() / get_by_slug()
                             → TeamsFormRenderer(public_base_url, signing_secret).render(form, tenant=…)
      │
      ▼
send_card(card)                      ──►  user fills it, taps Submit
      │
      ▼  (inbound)
parse_envelope → verify_envelope(allowed_hosts, secret, api_base_path)
RecentActivityCache.seen(activity.id)?  → drop duplicate
extract_answers → post_submission(session, env, answers, bearer_token=<user's>, timeout)
      ▼
build_reply_card(outcome, env) → send_card
```

Responsibilities:

- **`TeamsFormDesignerMixin`** — configuration (mode, base URL, api/ui base paths,
  public URL, signing secret, tenant fallback, registry handle), tenant and bearer
  resolution, the two command handlers, the single card handler, and the toolkit
  contribution through `agent_tools()`.
- **`FormDesignerClient`** (new, `aiohttp`) — `list_forms`, `get_form`,
  `render_teams`; one session, created lazily, closed on agent/integration
  shutdown. The POST keeps using the FEAT-551 `post_submission()` helper so the
  SSRF bounds (`allow_redirects=False`, bounded body) are not re-implemented.
- **Picker card builder** — forms → `Input.ChoiceSet` + a Submit whose `data`
  carries a *distinct* action key (not `_formdesigner`, so the wrapper's envelope
  detection cannot mistake a picker for a submission).
- **Toolkit** — `formdesigner_list_forms(tenant?)` and
  `formdesigner_get_form(slug_or_uid)` over the same client; the LLM gets metadata,
  the card is sent by the mixin.
- **Wrapper** — two additive, `getattr`-guarded seams: "ask the agent first" in the
  `ENVELOPE_KEY` branch, and a command-contribution hook that passes the
  `TurnContext`.

### Edge Cases & Error Handling

| Condition | Behavior |
|---|---|
| No authenticated session | Login card; nothing fetched, no card rendered. |
| Tenant unresolvable (no session tenant, no map hit, no config fallback) | Error card naming the missing configuration; never a guessed tenant. |
| `local` mode without `FORMDESIGNER_PUBLIC_URL` / `public_base_url` | `TeamsRenderConfigError` → operator-facing error card (the envelope's absolute URLs cannot be built). |
| `remote` mode and the server has no `teams` format registered | FormDesigner answers `415`; card explains that the server lacks a public URL. |
| Slug matches nothing | "No form found" card; `list_forms?slug=` returning `{"forms": []}` is not an error. |
| Tenant has no forms | Picker is replaced by an empty-state card. |
| Form contains upload fields | Card is still served; `RenderWarning`s from the renderer are surfaced as a visible note with the web-form link. |
| Form too large for one card | Serve the first section (`render_section`) or fall back to the web-form link — see Open Questions. |
| Private form, bearer rejected | `403` → `build_reply_card` rejection card; the bearer is never swapped for the service token as a fallback. |
| Validation failure | `422` body mapped per field by `build_reply_card`. |
| Duplicate Submit delivery | `RecentActivityCache.seen(activity.id)` drops it before the POST. |
| Envelope fails verification | Rejection card; the reason is logged, not shown. |
| FormDesigner unreachable / times out | `SubmitOutcome(status=0, error=…)` → timeout card; no exception escapes into the adapter. |
| Agent without the mixin | The wrapper's existing FEAT-551 branch runs, unchanged. |
| Shutdown | The client session is closed; this must be wired into `IntegrationManager.shutdown()`, which today fails to close even the existing one (ledger `a9514c9232ad`). |

---

## Capabilities

### New Capabilities
- `formdesigner-serve-forms`: a Teams-exposed agent serves FormDesigner forms as
  Adaptive Cards via `/getform`, a tenant-scoped picker, and a form toolkit, and
  submits the answers as the speaking user.

### Modified Capabilities
- `msteams-formdesigner-renderer` (FEAT-551): the wrapper's `ENVELOPE_KEY` branch
  gains an agent-first delegation seam; `AgentCommandHandler`-style command
  registration gains a `TurnContext`-carrying contribution hook.
- `msteams-submit-envelope-fail-closed` (FEAT-733, approved, 6 tasks pending —
  TASK-4653…TASK-4658): shares `resolve_submit_tenant()`,
  `formdesigner_tenant_map`, `require_signature` and the `teams_signing_secret`
  pairing on `setup_form_api()`; the mixin's tenant resolution and card signing
  must compose with it rather than duplicate it.
- `msteams-user-auth-lane` (FEAT-729, approved, **no tasks yet**): this feature is
  its first FormDesigner consumer and needs `MSTeamsUserSession.nav_session_token`
  plus `/login`.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/integrations/msteams/formdesigner_mixin.py` | **new** | `TeamsFormDesignerMixin` |
| `parrot/integrations/msteams/formdesigner_client.py` | **new** | `aiohttp` read client (`list_forms`, `get_form`, `render_teams`) |
| `parrot/integrations/msteams/formdesigner_cards.py` | **new** | picker card + login/error/empty-state cards |
| `parrot/integrations/msteams/tools/` | **new** | `formdesigner_list_forms`, `formdesigner_get_form` toolkit |
| `parrot/integrations/msteams/wrapper.py` | modifies | agent-first seam at the `ENVELOPE_KEY` branch; command-contribution hook |
| `parrot/integrations/msteams/models.py` | modifies | FormDesigner read/render config on `MSTeamsAgentConfig` (base URL, mode, tenant fallback, signing secret) |
| `parrot/integrations/msteams/formdesigner_submit.py` | depends on | reused unchanged; FEAT-733 will edit the same file |
| `parrot/integrations/manager.py` | modifies | close the new client on shutdown (and fix the existing leak) |
| `parrot_formdesigner/renderers/teams.py` | depends on | `TeamsFormRenderer`, `TeamsSubmitEnvelope` — no change expected |
| `parrot_formdesigner/api/routes.py` | depends on | `GET {tp}/forms`, `…/render/{format}`, `…/data` — no change expected |
| FEAT-729 | **blocked by** | per-user bearer (`MSTeamsUserSession.nav_session_token`); spec approved, no tasks yet |
| FEAT-733 | **blocked by / shares files** | tenant map + mandatory signature; 6 tasks pending (TASK-4653…TASK-4658) |
| Configuration | new env vars | `{NAME}_FORMDESIGNER_BASE_URL`, `{NAME}_FORMDESIGNER_TENANT`, … following the existing `{NAME}_FORMDESIGNER_*` convention |
| Deployment | none | no new service, no new port; one more outbound HTTPS target |

---

## Code Context

### User-Provided Code

No code was pasted during discovery; the request was prose (Spanish), captured in
the Problem Statement and Constraints above.

### Verified Codebase References

#### Classes & Signatures

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/teams.py
ENVELOPE_KEY: str = "_formdesigner"                                      # line 36
RESERVED_CONTROL_KEYS: frozenset[str] = frozenset({"_action", ENVELOPE_KEY})  # line 37
PUBLIC_URL_ENV: str = "FORMDESIGNER_PUBLIC_URL"                          # line 38

class TeamsSubmitEnvelope(BaseModel):                                    # line 52
    v: Literal[1] = 1
    wire: Literal["legacy"] = "legacy"
    form_uid: uuid.UUID
    tenant: str = Field(min_length=1)
    form_version: str
    is_public: bool
    submit_url: HttpUrl
    form_url: HttpUrl
    sig: str | None = None
    def canonical_payload(self) -> bytes: ...                            # line 65
    def sign(self, secret: str) -> "TeamsSubmitEnvelope": ...            # line 71
    def verify(self, secret: str) -> bool: ...                           # line 76

class TeamsRenderConfigError(ValueError): ...                            # line 84

class TeamsFormRenderer(AdaptiveCardRenderer):                           # line 88
    RENDERER_NAME = "teams"
    accepts_tenant = True
    def __init__(                                                        # line 94
        self,
        public_base_url: str | None = None,
        *,
        api_base_path: str = "/api/v1",
        ui_base_path: str = "",
        signing_secret: str | None = None,
        version: str | None = None,
    ) -> None: ...
    def build_envelope(self, form: FormSchema, tenant: str) -> TeamsSubmitEnvelope: ...   # line 112
    async def render(                                                    # line 126
        self,
        form: FormSchema,
        style: StyleSchema | None = None,
        *,
        locale: str = "en",
        prefilled: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
        tenant: str | None = None,
    ) -> RenderedForm: ...
    async def render_section(..., show_back: bool = False, show_skip: bool = False,
                             tenant: str | None = None) -> RenderedForm: ...  # line 150
    def _submit_action_data(self, form: FormSchema | None, *, terminal: bool) -> dict[str, Any]: ...  # line 185
    def _build_upload_element(self, field: FormField, value: Any, locale: str) -> dict[str, Any] | None: ...  # line 192
```

```python
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_submit.py
class EnvelopeRejected(Exception): ...                                   # line 28
def parse_envelope(submitted_data: dict[str, Any]) -> TeamsSubmitEnvelope: ...  # line 32
def verify_envelope(                                                     # line 44
    env: TeamsSubmitEnvelope, *, allowed_hosts: list[str], secret: str | None,
    api_base_path: str = "/api/v1",
) -> None: ...
def extract_answers(submitted_data: dict[str, Any]) -> dict[str, Any]: ...  # line 60

class SubmitOutcome(BaseModel):                                          # line 65
    status: int
    body: dict[str, Any] | None = None
    error: str | None = None

async def post_submission(                                               # line 73
    session: aiohttp.ClientSession,
    env: TeamsSubmitEnvelope,
    answers: dict[str, Any],
    *,
    bearer_token: str | None,
    timeout: float,
    max_response_bytes: int = MAX_RESPONSE_BYTES,
) -> SubmitOutcome: ...

def build_reply_card(outcome: SubmitOutcome, env: TeamsSubmitEnvelope) -> dict[str, Any]: ...  # line 122

class RecentActivityCache:                                               # line 201
    def __init__(self, ttl_seconds: float = 300.0, max_items: int = 2048) -> None: ...  # line 204
    def seen(self, activity_id: str) -> bool: ...                        # line 209
```

```python
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/__init__.py
class MSTeamsCommandRouter:                                              # line 30
    def register(self, command: str, handler: Callable) -> None: ...      # line 56
    async def try_dispatch(self, text: str, turn_context: "TurnContext") -> bool: ...  # line 74
    def registered_commands(self) -> list[str]: ...                      # line 153
```

```python
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/agent_commands.py
class AgentCommandHandler:                                               # line 26
    def __init__(self, agent: Any, wrapper: Any) -> None: ...            # line 43
    def register(self, router: "MSTeamsCommandRouter") -> None:          # line 48
        router.register("function", self.handle_function)                # line 50
        ...
        router.register("question", self.handle_question)                # line 58
    # Custom commands from config.commands — NOTE: the closure calls
    # `method(**kwargs)` with text-parsed kwargs and never passes the
    # TurnContext, so a command registered this way cannot send a card
    # nor read the Teams identity.
    def _register_custom_commands(self, router: "MSTeamsCommandRouter") -> None: ...  # line 449
    def _make_custom_handler(self, cmd_name: str, method_name: str): ...
```

```python
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py
@dataclass
class MSTeamsAgentConfig:
    name: str                                                            # line 32
    chatbot_id: str                                                      # line 33
    app_tenantid: Optional[str] = None     # Azure AD GUID, NOT a FormDesigner tenant  # line 37
    commands: Dict[str, str] = field(default_factory=dict)               # line 40
    adaptive_card_version: str = DEFAULT_ADAPTIVE_CARD_VERSION           # line 51
    formdesigner_allowed_hosts: Optional[List[str]] = None  # None/[] disables the branch  # line 62
    formdesigner_submit_token: Optional[str] = None                      # line 63
    formdesigner_submit_secret: Optional[str] = None                     # line 64
    formdesigner_submit_timeout: float = 15.0                            # line 65
    formdesigner_api_base_path: str = "/api/v1"                          # line 66
```

```python
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py
class MSTeamsAgentWrapper(ActivityHandler, MessageHandler):
    self._formdesigner_session: Optional[aiohttp.ClientSession] = None   # line 163
    self._formdesigner_recent = RecentActivityCache()                    # line 164
    self._command_router: MSTeamsCommandRouter = MSTeamsCommandRouter()  # line 180
    agent_cmd_handler.register(self._command_router)                     # line 182
    async def _handle_card_submission(self, turn_context, dialog_context): ...   # line 385
        if ENVELOPE_KEY in submitted_data:                               # line 473
            await self._handle_formdesigner_submit(turn_context, submitted_data)  # line 474
            return
        command = submitted_data.get("command")                          # card buttons → router
    async def on_message_activity(self, turn_context: TurnContext): ...   # line 554
        dispatched = await self._command_router.try_dispatch(clean_text, turn_context)  # line 575
    async def _handle_formdesigner_submit(self, turn_context, submitted_data) -> None: ...  # line 1057
    async def _get_formdesigner_session(self) -> aiohttp.ClientSession: ...  # line 1091
    async def close_formdesigner_client(self) -> None: ...               # line 1097
```

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py   (tp = tenant-prefixed base path)
app.router.add_get(f"{tp}/forms", _wrap_auth(handler.list_forms))                            # line 383
app.router.add_get(f"{tp}/forms/{{form_uid}}", _wrap_auth(handler.get_form, tenant="public")) # lines 393-396
app.router.add_get(f"{tp}/forms/{{form_uid}}/render/{{format}}",
                   _wrap_auth(render_module.handle_render, tenant="public"))                  # lines 416-418
app.router.add_post(f"{tp}/forms/{{form_uid}}/data",
                    _wrap_auth(handler.submit_data, tenant="public"))                         # lines 431-433
def _wrap_auth(handler: _Handler, *, tenant: str = "required") -> _Handler: ...                # line 85

# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py
async def list_forms(self, request: web.Request) -> web.Response: ...    # line 851
#   GET /forms → {"forms": [{form_uid, form_id, title, description, version, source, created_at}]}
#   supports ?slug=<form_id> (FEAT-389), resolved via FormRegistry.get_by_slug()
```

```python
# packages/ai-parrot/src/parrot/bots/agent.py
def agent_tools(self) -> List[AbstractTool]:   # line 469 — the tool-contribution seam
    """Return the agent-specific tools."""
    return []

# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ServerManagedToolkit, ABC):   # line 225
    def get_tools(...)                              # line 522

# packages/ai-parrot/src/parrot/skills/mixin.py
class SkillRegistryMixin:    # line 47 — precedent: a mixin that owns config AND contributes tools

# packages/ai-parrot-integrations/src/parrot/integrations/msteams/handler.py
async def send_card(                 # line 60 — on MessageHandler, inherited by the wrapper
    self,
    card_data: Dict[str, Any],       # NOTE: card first, turn_context second
    turn_context: TurnContext,
) -> None: ...
```

#### Verified Imports

```python
# Confirmed to resolve in the current tree:
from parrot_formdesigner.renderers.teams import ENVELOPE_KEY            # wrapper.py:38 already does this
from parrot.forms import FormSchema, FormCache                          # wrapper.py:46, :48 (shim → parrot_formdesigner.core)
from parrot.outputs.cards import CardSpec, render, markdown_to_sections # wrapper.py:50-60
from parrot.bots.mixins import ModelSwitchingMixin                      # parrot/bots/mixins/__init__.py:17
# packages/ai-parrot-integrations/pyproject.toml:61  "parrot-formdesigner"
# packages/ai-parrot-integrations/pyproject.toml:184 parrot-formdesigner = { workspace = true }
```

#### Key Attributes & Constants
- `TeamsFormRenderer.RENDERER_NAME` → `"teams"`; `accepts_tenant` → `True`
  (`renderers/teams.py:91-92`).
- `ENVELOPE_KEY` → `"_formdesigner"` — the wrapper's routing discriminator
  (`renderers/teams.py:36`, consumed at `wrapper.py:471`).
- `RESERVED_CONTROL_KEYS` → `{"_action", "_formdesigner"}`; everything else in the
  Submit payload is an answer (`renderers/teams.py:37`, `extract_answers`).
- `UPLOAD_NOTICE_TEXT` (en/es) and `UPLOAD_WARNING_REASON` — the existing upload
  degradation strings (`renderers/teams.py:40-48`).
- `FORMDESIGNER_API_BASE_PATH = "/api/v1"` — wrapper fallback, config wins
  (`wrapper.py:71`).
- `MSTeamsUserSession.nav_session_token` — the intended per-user bearer, **specced
  only** (`sdd/specs/msteams-user-auth-lane.spec.md`, §2).
- `formdesigner_tenant_map: Optional[Dict[str, str]]` — `{aad_guid: fd_slug}`,
  **specced only** (`sdd/specs/msteams-submit-envelope-fail-closed.spec.md`, M6).

### Does NOT Exist (Anti-Hallucination)

- ~~`MSTeamsUserSession`~~, ~~`MSTeamsSessionStore`~~, ~~`MSTeamsAuthStrategy`~~,
  ~~`/login`~~ — specced in FEAT-729 (`msteams-user-auth-lane.spec.md`, **Status:
  approved, but no task index and no tasks**). Nothing of the Teams auth lane is
  implemented; 0 source hits for each name.
- ~~`parrot.auth.token_exchange.TokenExchangeClient`~~ /
  ~~`TokenExchangeResult`~~ — FEAT-729 new interfaces, not in the tree.
- ~~`resolve_submit_tenant()`~~, ~~`MSTeamsAgentConfig.formdesigner_tenant_map`~~,
  ~~`require_signature`~~ — FEAT-733 (`msteams-submit-envelope-fail-closed.spec.md`,
  **approved, 6 tasks still pending**). Specced, not yet in the source.
- ~~`MSTeamsAgentConfig.tenant`~~ — there is **no** FormDesigner tenant field on the
  Teams config. Only `app_tenantid` (an Azure AD GUID, `models.py:37`), which is a
  different namespace from FormDesigner's tenant slug.
- ~~`FormDesignerToolkit`~~, ~~`formdesigner_list_forms`~~,
  ~~`formdesigner_get_form`~~ — no FormDesigner toolkit or tool exists anywhere
  (not in `parrot_tools`, not in `parrot/tools`, not in the integrations package).
- ~~A FormDesigner **read** client~~ — the only FormDesigner HTTP code is
  `post_submission()` plus the submit-only session at `wrapper.py:1091`. There is
  no `list_forms` / `get_form` / `render_teams` client.
- ~~`MSTeamsAgentWrapper.send_card`~~ as a locally-defined method — `send_card` is
  defined on `MessageHandler` (`handler.py:60`) and on
  `dialogs/presets/base.py:182`; the wrapper inherits it.
- ~~An agent→wrapper command seam that passes the `TurnContext`~~ — the only agent
  command mechanism is `config.commands` → `_make_custom_handler`, which calls
  `method(**kwargs)` without the `TurnContext`.
- ~~`parrot_tools.formdesigner`~~ — no such module.
- ~~A card-submission hook on the agent~~ — `_handle_card_submission` consults
  dialogs, the `_formdesigner` envelope and the command router; it never asks the
  agent.

---

## Parallelism Assessment

- **Internal parallelism**: partial. The `FormDesignerClient` + toolkit + card
  builders are pure, testable units with no Bot Framework dependency and could be
  built in parallel with the mixin/wrapper seams. The mixin, the wrapper seams and
  the config changes are one sequential chain (they share `wrapper.py` and
  `models.py`).
- **Cross-feature independence**: **low** — this feature collides with two
  in-flight features on the same files. FEAT-733 (6 pending tasks) edits
  `formdesigner_submit.py` (`verify_envelope` + `require_signature`, new
  `resolve_submit_tenant`), `models.py` (`formdesigner_tenant_map`), `wrapper.py`
  (TASK-4655) and `setup_form_api` (TASK-4656); FEAT-729 (no tasks yet) edits
  `wrapper.py` (`on_message_activity`, `UserContext`/`post_login`), `models.py` and
  adds `msteams/auth.py`. Shared files: `wrapper.py`, `models.py`,
  `formdesigner_submit.py`. FEAT-733 is the nearer hazard — its tasks are already
  decomposed and will likely land first.
- **Recommended isolation**: `per-spec`.
- **Rationale**: every task touches at least one of the three files that FEAT-729
  and FEAT-733 also rewrite, so sub-worktrees would only multiply the merge
  surface. One worktree, sequential tasks, rebased after FEAT-729/733 land.

---

## Open Questions

- [x] Is this a feature or a hotfix, and on which base? — *Owner: Jesus Lara*:
  `type: feature`, `base_branch: dev`.
- [x] How does the mixin obtain the card — HTTP or in-process? — *Owner: Jesus
  Lara*: **dual** — HTTP `GET …/render/teams` when FormDesigner is remote,
  in-process `TeamsFormRenderer` when it is embedded.
- [x] What do we assume about the per-user bearer? — *Owner: Jesus Lara*: **depend
  on FEAT-729 (blocking)**; no service-token interim.
- [x] Where does the code live? — *Owner: Jesus Lara*: all of it in
  `ai-parrot-integrations`, under `parrot/integrations/msteams/`.
- [x] How do the picker and the submit route back? — *Owner: Jesus Lara*: the mixin
  owns a single handler for both; the wrapper's FEAT-551 branch becomes the
  fallback for agents without the mixin.
- [x] What travels in the card's `Action.Submit`? — *Owner: Jesus Lara*: keep the
  signed `TeamsSubmitEnvelope` + `verify_envelope()` as defence in depth, with the
  per-user bearer on the POST.
- [x] Where does the tenant come from? — *Owner: Jesus Lara*: the authenticated
  user, with the bot's static value as fallback.
- [x] Behavior with no session / unrenderable fields? — *Owner: Jesus Lara*: login
  card; FEAT-551-style upload degradation (notice + `Action.OpenUrl` +
  `RenderWarning`).
- [ ] How does the mixin compose with FEAT-733's `resolve_submit_tenant()` once it
  lands — does the user's session tenant outrank the AAD-map hit, or the reverse?
  The map is the *server-asserted* value, the session is the *authenticated* one;
  the precedence must be written down before either is implemented. — *Owner:
  Jesus Lara*
- [ ] Does the mixin need a static FormDesigner tenant on `MSTeamsAgentConfig` at
  all, given FEAT-733 adds `formdesigner_tenant_map`? A bot-level default and a
  GUID map overlap. — *Owner: Jesus Lara*
- [ ] Is a single-card render enough for v1, or must large forms use
  `render_section()` wizard steps? The Teams card payload size cap needs to be
  confirmed against current Microsoft documentation before deciding (the renderer
  caps at Adaptive Card schema 1.6, which is verified; the byte cap is not). —
  *Owner: Jesus Lara*
- [ ] Should `/getform` accept a slug, a `form_uid`, or both? `list_forms` supports
  `?slug=`, `get_form` is keyed by `form_uid` — accepting both means a resolution
  step with an ambiguity rule. — *Owner: Jesus Lara*
- [ ] Should the toolkit's `formdesigner_get_form` *send* the card as a
  side effect, or only return metadata and let the mixin send it? Sending from a
  tool makes the tool channel-aware; returning metadata risks the LLM paraphrasing
  a form instead of serving it. — *Owner: Jesus Lara*
- [ ] In `local` mode, how does the mixin reach the `FormRegistry` — injected at
  construction, read from the aiohttp app, or resolved from a registry singleton? —
  *Owner: Jesus Lara*
- [ ] Should the new client's session be owned by the mixin (agent lifecycle) or by
  the wrapper (integration lifecycle)? The existing submit session is already
  leaked on shutdown (ledger `a9514c9232ad`); whichever owner we pick must be wired
  into `IntegrationManager.shutdown()`. — *Owner: Jesus Lara*
- [ ] Sequencing: FEAT-733's six tasks (TASK-4653…TASK-4658) are already decomposed
  and touch the same three files. Should this feature wait for FEAT-733 to merge,
  wait for FEAT-729 (which has no tasks yet and is the hard blocker anyway), or be
  specced now and rebased? — *Owner: Jesus Lara*
- [ ] Does serving a form need to work in channel/group conversations, or 1:1 only?
  Group scope affects who may submit and whose bearer is used. — *Owner: Jesus
  Lara*
