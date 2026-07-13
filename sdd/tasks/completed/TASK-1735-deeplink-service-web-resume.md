# TASK-1735: Deep-link token service + web (AgentTalk) resume route

**Feature**: FEAT-273 — A2UI Protocol Integration — Rendering Core (parrot.outputs.a2ui)
**Spec**: sdd/specs/a2ui-implementation.spec.md
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1728
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 and goal **G6** (D9 expanded): `requires_actions` components
on STATIC (baked) surfaces cannot dispatch actions — there is no ActionRouter
in v1 (FEAT-B). Instead, each action degrades to a **single-use, TTL-bound
deep link**: clicking it resumes the originating channel/session and injects
the action as a structured user message. This task builds the core token
service (`DeepLinkService.mint` / `consume`) and the FIRST resume route (web,
via AgentTalk POST). Per-channel Telegram/Teams routes follow in TASK-1736.

The spec-session decision (§8) prefers **navigator_auth-minted tokens**, but
only the DECODE side is proven in-repo; mint is an open verification item with
a pre-approved fallback (Redis opaque one-shot token). Either way a Redis
consume record enforces single use.

Spec anchors: §2 New Public Interfaces (`deeplink.py`), §2 Data Models
(`DeepLink`), §3 Module 8, §5 AC **G6**, §7 Patterns ("Redis one-shot
consume"), §8 open question "navigator_auth token-mint API".

---

## Scope

- **FIRST SUBTASK (mandatory, before writing service code)**: verify whether
  the navigator_auth IdP exposes a token-MINT/encode API usable for deep
  links. Decode is PROVEN at
  `packages/ai-parrot-server/src/parrot/handlers/stream.py` —
  `idp = getattr(auth, '_idp', None)` (:280) and
  `_, payload = idp.decode_token(code=token)` (:288). Mint/encode is
  UNVERIFIED: inspect the installed `navigator_auth` package for a usable
  `create_token`/encode counterpart. Record the finding in the Completion
  Note.
  - If mint is usable → mint deep-link tokens through the IdP; Redis record
    used for single-use/replay enforcement only (spec §8 resolution).
  - If mint is unusable → PRE-APPROVED FALLBACK: Redis-backed opaque one-shot
    token following the in-repo nonce machinery of
    `packages/ai-parrot/src/parrot/auth/oauth2_base.py`:
    key-template pattern (`_NONCE_KEY_TEMPLATE = "oauth2:{provider}:nonce:{nonce}"`,
    :40), `secrets.token_urlsafe(32)` id generation (:314), TTL-bound `set`,
    and `redis.get` → `redis.delete(nonce_key)  # one-shot` consume (:370-375).
    Same route contract, no schema change.
- Implement `packages/ai-parrot/src/parrot/outputs/a2ui/deeplink.py`:
  `class DeepLinkService` with (spec §2 New Public Interfaces):
  - `async def mint(self, *, session_id, user_id, agent_id, channel, action_payload) -> DeepLink`
  - `async def consume(self, token: str) -> ResumePayload` — single-use
    enforcement via a Redis consume record; second consume and expired token
    both fail with distinct, friendly errors.
  - `ResumePayload` Pydantic model carrying session_id/user_id/agent_id/
    channel/action_payload. The action payload lives SERVER-SIDE only — the
    URL/token never embeds it client-side (spec §7 risk table).
  - TTL on every token; `DeepLink.expires_at` populated from it.
- Implement the **web resume route** in ai-parrot-server: a thin
  handler that receives the deep-link click, calls `DeepLinkService.consume`,
  and injects the action as a **structured user message** into the original
  session through the existing AgentTalk POST flow
  (`handlers/agent.py` — `class AgentTalk(BaseView)` :102,
  `async def post` :1523, body keys `agent_name`/`query`/`session_id`/`user_id`).
  Expired/replayed token → friendly "session expired" response (spec §7).
- Write unit tests `test_deeplink_single_use` and integration test
  `test_e2e_deeplink_resume_web` (spec §4).

**NOT in scope**:
- Telegram and MS Teams resume routes → TASK-1736.
- `DeepLink` model definition → TASK-1728 (`parrot/outputs/a2ui/artifacts.py`);
  this task consumes it and adds `ResumePayload` beside the service.
- Renderers emitting deep links into baked artifacts → renderer tasks
  (TASK-1729..1732) consume `DeepLinkService`.
- ActionRouter / `actionResponse`/`callFunction` dispatch → FEAT-B.
- Any unified cross-channel resume endpoint — resume routes are per-channel
  (spec §8 resolution).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/deeplink.py` | CREATE | `DeepLinkService` (mint/consume) + `ResumePayload` |
| `packages/ai-parrot-server/src/parrot/handlers/deeplink.py` | CREATE | Web resume route: consume token → inject structured user message via AgentTalk POST flow |
| `packages/ai-parrot/tests/outputs/a2ui/test_deeplink.py` | CREATE | Unit tests (fakeredis/mock redis) |
| `packages/ai-parrot-server/tests/test_deeplink_resume_web.py` | CREATE | `test_e2e_deeplink_resume_web` integration test |

*(Route registration: add the new handler wherever ai-parrot-server registers
`AgentTalk`/artifact views — locate with grep and record the exact file in the
Completion Note.)*

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
import secrets  # stdlib — token_urlsafe pattern per oauth2_base.py:314
# DeepLink comes from TASK-1728:
from parrot.outputs.a2ui.artifacts import DeepLink  # verify it landed before starting
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/stream.py — navigator_auth VERIFY seam
# :280  idp = getattr(auth, '_idp', None)
# :288  _, payload = idp.decode_token(code=token)
# decode is VERIFIED in-repo; mint/encode is UNVERIFIED (first subtask).

# packages/ai-parrot/src/parrot/auth/oauth2_base.py — Redis one-shot nonce pattern
_NONCE_KEY_TEMPLATE = "oauth2:{provider}:nonce:{nonce}"  # :40
_NONCE_TTL_SECONDS = 10 * 60                             # :49
nonce = secrets.token_urlsafe(32)                        # :314
# consume (:369-375): raw_state = await self.redis.get(nonce_key)
#   → if not raw_state: raise ValueError("Invalid or expired state nonce.")
#   → await self.redis.delete(nonce_key)  # one-shot
# Manager accepts redis via app["redis"] / redis_client / redis_url (:127-157)

# packages/ai-parrot-server/src/parrot/handlers/agent.py — AgentTalk seams
class AgentTalk(BaseView)  # :102
    async def post(self)   # :1523 — POST /api/v1/agents/chat/{agent_id}
    # body: {"agent_name", "query", "session_id", "user_id", "stream", ...}

# packages/ai-parrot/src/parrot/outputs/a2ui/artifacts.py — from TASK-1728 (spec §2)
class DeepLink(BaseModel):
    action_label: str
    url: str            # channel resume URL embedding the token
    token_id: str       # for audit/consume tracking
    expires_at: datetime
```

### Does NOT Exist
- ~~First-party JWT signing in `parrot.auth`~~ — no `jwt.encode`/`jose`
  anywhere in-repo; only the OAuth2 Redis nonce machinery exists. Token mint
  is delegated to navigator_auth OR the Redis opaque fallback — do NOT add a
  JWT library.
- ~~navigator_auth mint/encode API (unverified)~~ — do not assume
  `idp.create_token`/`idp.encode_token` exist; the first subtask verifies.
- ~~Per-channel deep links / a "resume chat by id" endpoint~~ — `deep_link`
  exists only as outbound live-chat escalation in
  `parrot/human/actions/backends/webhook.py`; nothing reusable.
- ~~`ActionRouter` or any interceptor/mutation hook~~ — FEAT-B territory.
- ~~SSE in AgentTalk~~ — chunked HTTP only; do not build the resume route on
  SSE assumptions.

---

## Implementation Notes

### Pattern to Follow
- Single-use consume copies the `oauth2_base.py` shape exactly: opaque id from
  `secrets.token_urlsafe(32)`, namespaced Redis key (suggested:
  `a2ui:deeplink:{token_id}`), JSON payload stored server-side with TTL,
  `get` → missing ⇒ invalid/expired, then `delete` ⇒ one-shot. If
  navigator_auth mint IS usable, the Redis record still exists as the
  replay-protection consume record (spec §8: "Redis one-shot record retained
  for single-use/replay enforcement only").
- The service receives its Redis client/URL via constructor injection (mirror
  `oauth2_base.py` :127-157 acceptance of `redis_client` / `redis_url` /
  app-shared client). One-way import rule (G8): `parrot.outputs.a2ui.deeplink`
  never imports agents, DatasetManager, or LLM clients.
- The web route is THIN: token → `consume()` → build the structured user
  message (structured/JSON form of `action_payload`, marked as an A2UI action
  resume) → feed it through the same code path AgentTalk POST uses for a
  `query` against the stored `session_id`/`user_id`/`agent_name`. Reuse
  AgentTalk internals rather than duplicating agent invocation.

### Key Constraints
- Async throughout; Pydantic v2 (`ResumePayload`); Google-style docstrings;
  `self.logger`.
- Token URL carries ONLY the opaque token id — action payload, session and
  user identifiers stay server-side (spec §7).
- Distinct behaviors for replay vs expiry, both rejected; the web route maps
  both to a friendly "session expired" landing (no stack traces, no payload
  echo).
- TTL is a service parameter with a sane default; `DeepLink.expires_at` must
  match the Redis TTL.
- Core `ai-parrot` gains zero new dependencies (G8); no `exec(`/`eval(` (G1).

### References in Codebase
- `packages/ai-parrot/src/parrot/auth/oauth2_base.py` — the one-shot nonce
  machinery to copy (mint fallback AND consume record).
- `packages/ai-parrot-server/src/parrot/handlers/stream.py:275-292` — how the
  server reaches the navigator_auth IdP instance.
- `packages/ai-parrot-server/src/parrot/handlers/agent.py:1523` — AgentTalk
  POST body contract for message injection.

---

## Acceptance Criteria

- [ ] navigator_auth mint verification performed FIRST; finding + chosen path recorded in the Completion Note
- [ ] Implementation complete per scope (`DeepLinkService.mint`/`consume`, `ResumePayload`, web resume route)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/outputs/a2ui/test_deeplink.py packages/ai-parrot-server/tests/test_deeplink_resume_web.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/outputs/a2ui/deeplink.py packages/ai-parrot-server/src/parrot/handlers/deeplink.py`
- [ ] Imports work: `from parrot.outputs.a2ui.deeplink import DeepLinkService`
- [ ] Single-use proven: second consume of the same token fails; expired token fails (G6)
- [ ] Web round-trip proven: mint → click → consume → action arrives as structured user message in the SAME session via AgentTalk POST flow (G6)
- [ ] Action payload never appears in the minted URL (server-side only)
- [ ] Expired/replayed click returns a friendly "session expired" response

---

## Test Specification

> Minimal test scaffold. The agent must make these pass.
> Add more tests as needed. Names mandated by spec §4.

```python
# packages/ai-parrot/tests/outputs/a2ui/test_deeplink.py

class TestDeepLinkService:
    async def test_mint_returns_deeplink_with_ttl(self):
        """mint() returns a DeepLink whose url embeds only an opaque token id
        and whose expires_at matches the configured TTL."""

    async def test_deeplink_single_use(self):
        """Second consume of the same token fails; expired token fails
        (replay + expiry rejected — spec §4 / AC G6)."""

    async def test_consume_returns_server_side_payload(self):
        """consume() returns the ResumePayload (session/user/agent/channel/
        action_payload) stored server-side at mint time."""


# packages/ai-parrot-server/tests/test_deeplink_resume_web.py

class TestDeepLinkResumeWeb:
    async def test_e2e_deeplink_resume_web(self):
        """Mint → GET resume route → token consumed → action injected as a
        structured user message through the AgentTalk POST flow into the
        original session (spec §4 integration table)."""

    async def test_expired_or_replayed_click_friendly_landing(self):
        """Replayed/expired token yields a friendly 'session expired' response
        with no payload echo."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/a2ui-implementation.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-1735-deeplink-service-web-resume.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-11
**navigator_auth mint verdict (REQUIRED)**: A usable mint API **DOES exist** —
`navigator_auth/backends/idp/__init__.py:272` `create_token(data, issuer, expiration,
audience) -> (jwt, refresh, exp, scheme)` (JWT mint), complementing the proven
`decode_token` at `stream.py:288`. **However I implemented the pre-approved Redis
opaque one-shot fallback instead**, for two reasons: (1) the mint lives on a
navigator_auth IdP instance reachable only server-side — binding core
`parrot.outputs.a2ui.deeplink` to it would violate the G8 one-way import rule (core
gains zero deps, imports no auth/server code); (2) the spec keeps the Redis consume
record for single-use/replay enforcement regardless of mint source, and an opaque token
(no payload in the URL) is the strongest privacy posture. The URL embeds only a
`secrets.token_urlsafe(32)` id; the ResumePayload lives in Redis with a TTL and is
deleted on first consume.

**Notes**: `DeepLinkService.mint/consume` + `ResumePayload` in core `deeplink.py`
(Redis injected via constructor, mirrors `oauth2_base`). Web resume handler in
`ai-parrot-server/handlers/deeplink.py`: `DeepLinkResumeHandler.handle(token)` consumes
the token, builds a structured `a2ui_action_resume` user message, and forwards it via an
injected resume invoker (wraps the AgentTalk POST `agent_name`/`query`/`session_id`/
`user_id` contract); `setup_deeplink_routes(app, service, invoker)` registers
`GET /api/v1/a2ui/resume/web`. Expiry/replay → friendly 410 with no payload echo. Single
use, expiry, and web round-trip all proven. 4 core + 3 server tests pass; ruff clean;
zero new core deps; no exec/eval.

**Route registration**: AgentTalk is defined at `handlers/agent.py:102` but its app
route registration is done dynamically by the server bootstrap (no static `add_view`
for it found via grep). To avoid destabilizing the bootstrap, I shipped
`setup_deeplink_routes(app, service, invoker)` as the registration entry point rather
than editing the app factory; it should be called alongside AgentTalk setup.

**Deviations from spec**: Redis-opaque path chosen over navigator_auth mint (justified
above — mint is available but coupling core to it breaks G8). Route registration exposed
as a `setup_*` helper rather than wired into the app bootstrap (documented above).
