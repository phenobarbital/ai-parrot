# TASK-4663: Wire the auth gate, UserContext and post_login into the Teams wrapper

**Feature**: FEAT-729 — MS Teams user authentication lane
**Spec**: `sdd/specs/msteams-user-auth-lane.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4659, TASK-4661, TASK-4662
**Assigned-to**: unassigned

---

## Context

Implements **spec §3 Module 5** — the task that actually makes the agent know
who it is talking to. Everything before it builds machinery; this one connects
it to the turn flow and replaces the Teams-scoped id with the Navigator id.

**Spec Q2 (resolved 2026-10-23)**: `auth_required` defaults to **`False`**. Auth
is opt-in, so every existing Teams deployment behaves exactly as today after the
upgrade. Fail-closed is what a deployment switches on deliberately.

> ### Two contract drifts found while writing this task — read before coding
> 1. **`on_message_activity` now occurs once, not twice.** The spec's §6 Edit
>    Sites row records 2 occurrences with a commented-out twin at line 718; that
>    twin is **gone** as of `0eb59926a`. The anchor is unambiguous at line 554.
>    The spec is deliberately not rewritten at task time, so trust this task.
> 2. **There are FOUR `"user_id"` context sites, not three.** The spec §3 M5 text
>    says "the three `{"user_id": …}` context dicts" and §6 lists 675 and 1025.
>    The real set is **420, 460, 675, 1025**. Missing line 420 would leave one
>    code path still passing the Teams-scoped id, which is exactly the bug this
>    module exists to remove. All four are in scope.

---

## Scope

- Add the four auth fields to `MSTeamsAgentConfig`.
- Construct the session store, the exchange client and the strategy in
  `MSTeamsAgentWrapper.__init__`, and register the auth commands there.
- In `on_message_activity`, **after** the `_is_authorized` gate, resolve the
  session; when `auth_required` and unauthenticated, send the sign-in card and
  return without reaching the agent.
- Build a `UserContext(channel="msteams", …)`; call `post_login` once per
  session (`post_login_ran` guard) and `clone_for_user` in the non-singleton mode.
- Replace **all four** `"user_id"` context values with the Navigator id when the
  session is authenticated, keeping today's value when it is not.
- Tests for the gate in both `auth_required` directions and for the
  once-per-session `post_login`.

**NOT in scope**: the strategy itself (TASK-4661); the command handlers
(TASK-4662); identity persistence (TASK-4664); the `msagentsdk` lane.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py` | MODIFY | Four auth fields on `MSTeamsAgentConfig` |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` | MODIFY | Construction, registration, the gate, four context sites |
| `packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_auth_gate.py` | CREATE | Gate + `post_login` tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.context import UserContext                      # verified: packages/ai-parrot/src/parrot/auth/context.py:39
from parrot.auth.token_exchange import TokenExchangeClient        # TASK-4660
from .auth import MSTeamsAuthStrategy, MSTeamsSessionStore, user_key   # TASK-4659/4661
from .commands.auth_commands import register_auth_commands        # TASK-4662
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py
class MSTeamsAgentWrapper(ActivityHandler, MessageHandler):                 # line 94
    self._command_router: MSTeamsCommandRouter = MSTeamsCommandRouter()     # line 180
    register_jira_commands(self._command_router, oauth_manager)             # line 192  <- registration precedent
    def _is_authorized(self, conversation_id: str, user_id: str) -> bool:   # line 311
    async def on_message_activity(self, turn_context: TurnContext):         # line 554

# The FOUR context sites (verified by grep on 0eb59926a):
#   line  420:  context={"user_id": user_id, "session_id": session_id},
#   line  460:  context={"user_id": user_id, "session_id": conversation_id},
#   line  675:  "user_id": turn_context.activity.from_property.id,
#   line 1025:  "user_id": turn_context.activity.from_property.id,

# packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py
class MSTeamsAgentConfig:                                                   # line 16

# packages/ai-parrot/src/parrot/auth/context.py:39
@dataclass(frozen=True)
class UserContext:
    channel: str
    user_id: str
    display_name: Optional[str] = None
    email: Optional[str] = None
    session_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

# packages/ai-parrot/src/parrot/bots/abstract.py
async def post_login(...)      # line 4561
def clone_for_user(...)        # line 4583
```

### Does NOT Exist
- ~~`MSTeamsAgentWrapper.post_login` / `.clone_for_user` / any `UserContext` use
  under `packages/ai-parrot-integrations/src/parrot/integrations/msteams/`~~ — 0 hits. The lane is identity-blind today; this task
  writes the first use.
- ~~a commented-out second `on_message_activity` at `wrapper.py:718`~~ — it was
  there when the spec was written and is **gone** now. Do not hunt for it.
- ~~only three `"user_id"` context sites~~ — there are four (420, 460, 675, 1025).
- ~~`MSTeamsAgentConfig.auth_required` and the other three fields~~ — they do not
  exist yet; this task adds them.
- ~~`parrot.integrations.msteams.build.lib...`~~ — `packages/ai-parrot-integrations/src/parrot/integrations/../build/lib/` holds a
  **stale duplicate** of these modules. Never edit or cite it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_auth_gate.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py#MSTeamsAgentWrapper",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py#MSTeamsAgentWrapper._is_authorized",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py#MSTeamsAgentWrapper.on_message_activity",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py#MSTeamsAgentConfig",
    "sym:packages/ai-parrot/src/parrot/auth/context.py#UserContext",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#post_login",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#clone_for_user"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The gate runs **after** `_is_authorized` (line 311), never before: that check
  is the existing allow-list and must keep first refusal.
- With `auth_required=False` an unauthenticated turn must behave **exactly** as
  today. AC-3 asserts it, and that is the whole safety argument for Q2's default.
- `post_login` runs at most once per session — the guard is
  `session.post_login_ran`, already on the dataclass from TASK-4659.
- **Never log a token.**

### Why four sites and not three
Lines 420 and 460 pass a `context={...}` dict built from a local `user_id`;
675 and 1025 read `turn_context.activity.from_property.id` directly. They are
different code paths (one is the agent invocation, the others are the voice and
proactive paths), so a fix applied to only two of them leaves the agent seeing a
Teams id on the rest.

---

## Implementation Blueprint

### Steps (in order)
1. Add the config fields first — *why*: the wrapper's constructor reads them, so
   the model must change before the wiring compiles.
2. Construct store → client → strategy in that order in `__init__`, then
   register the commands next to `register_jira_commands` — *why*: the strategy
   needs both of the others, and registration must happen where the router exists.
3. Insert the gate immediately after the `_is_authorized` check — *why*: AC-1.
4. Change the four context sites **last** — *why*: with the session resolved
   earlier in the turn, each site is a one-line substitution, and doing it last
   keeps the diff reviewable.

### `packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class MSTeamsAgentConfig' packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py)
# AFTER — add these fields to the existing dataclass `class MSTeamsAgentConfig`
#          (verified: packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py:16; it already carries 35 fields,
#          so append alongside them and keep the existing style)
    oauth_connection_name: Optional[str] = None  # Azure Bot OAuth connection (Graph-scoped)
    auth_required: bool = False                  # Q2: auth is opt-in; True fails closed
    navigator_auth_url: Optional[str] = None     # e.g. https://host/api/v1/login
    prefer_id_token: bool = True                 # send id_token for strong JWKS verification
```
**Why**: `auth_required=False` is Q2's resolution — the upgrade must be a no-op
for existing deployments. `prefer_id_token=True` is spec §2's answer to the
weak-verification finding: real Graph access tokens fail independent signature
verification, so the `id_token` is the only path to real cryptographic proof.

### `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` — construction (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'register_jira_commands(self._command_router, oauth_manager)' packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py)
# AFTER — insert below `            register_jira_commands(self._command_router, oauth_manager)`
#         (verified: packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py:192)

        # FEAT-729: user authentication lane (opt-in via config.auth_required)
        self._session_store = MSTeamsSessionStore(
            agent_name=config.name, store=getattr(self, "_state_store", None)
        )
        self._auth: Optional[MSTeamsAuthStrategy] = None
        if config.navigator_auth_url:
            self._auth = MSTeamsAuthStrategy(
                config=config,
                store=self._session_store,
                exchange=TokenExchangeClient(
                    config.navigator_auth_url,
                    prefer_id_token=config.prefer_id_token,
                ),
            )
            register_auth_commands(self._command_router, self._auth)
        else:
            self.logger.info(
                "MSTeams[%s]: no navigator_auth_url — auth lane disabled", config.name
            )
```
**Why**: the strategy is `None` when no auth URL is configured, so a deployment
that never opts in pays nothing and `/login` is not even registered. Keep the
`getattr` for the state store: a Redis-backed store is injected by configuration
(spec Q3) and must stay optional.

### `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` — the gate (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    async def on_message_activity(self, turn_context: TurnContext):' packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py)
# NOTE: the spec's §6 row says 2 occurrences; the commented-out twin at line 718
#       is gone as of 0eb59926a. Attach to the single definition at line 554.
# AFTER — inside `on_message_activity`, immediately below the existing
#         `_is_authorized(...)` refusal branch (verified: packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py:311
#         defines it; the call site is inside on_message_activity)

        session = None
        if self._auth is not None:
            session = await self._auth.ensure_authenticated(turn_context)
            if self.config.auth_required and not session.authenticated:
                # FILL IN: send the sign-in card via self._auth.send_signin_card
                # and RETURN before the agent is invoked — bounded by AC-2 (G6)
                raise NotImplementedError
            if session.authenticated and not session.post_login_ran:
                # FILL IN: build UserContext(channel="msteams", user_id=
                # session.nav_user_id, display_name=..., email=session.nav_email,
                # session_id=...) and await the bot's post_login with it; then
                # clone_for_user when singleton_agent is False; set
                # session.post_login_ran = True and persist via the store.
                # Bounded by AC-4, AC-5.
                raise NotImplementedError
```
**Why**: `ensure_authenticated` never raises and never prompts (TASK-4661 AC-2),
so this block is the only place that decides to refuse a turn. The
`post_login_ran` guard lives on the session, not on the wrapper, so it survives
a rehydration from the shared store.

### `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` — the four context sites (MODIFY)
```python
# FILL IN: disambiguate — each of the four sites below needs 2-3 lines of
# surrounding context quoted to make the edit unique, because two pairs are
# textually identical. Verified line numbers on 0eb59926a:
#   420:  context={"user_id": user_id, "session_id": session_id},
#   460:  context={"user_id": user_id, "session_id": conversation_id},
#   675:  "user_id": turn_context.activity.from_property.id,
#  1025:  "user_id": turn_context.activity.from_property.id,
# At each site, use the Navigator id when the session is authenticated and
# today's value otherwise — a single helper such as
#   def _effective_user_id(self, turn_context, session) -> str
# is preferred over four inline conditionals. Bounded by AC-6.
```
**Why**: the two pairs are byte-identical, so a bare one-line anchor would be
ambiguous — the blueprint deliberately refuses to guess which one a naive
replace would hit. A helper also means AC-6 can be asserted once.

### FILL IN checklist
- [ ] gate: sign-in card + early return under `auth_required`; bounded by AC-2
- [ ] gate: `UserContext` + `post_login` + `clone_for_user` + guard; bounded by AC-4, AC-5
- [ ] four context sites: disambiguated edits via `_effective_user_id`; bounded by AC-6

---

## Acceptance Criteria

- [ ] AC-1 the auth gate runs **after** `_is_authorized`, which keeps first refusal
- [ ] AC-2 with `auth_required=True` and an unauthenticated user, a sign-in card
      is sent and the agent is **never** invoked (G6)
- [ ] AC-3 with `auth_required=False` and an unauthenticated user, the turn
      proceeds exactly as before this feature — no card, no extra call
- [ ] AC-4 `post_login` receives a `UserContext` with `channel="msteams"`, the
      Navigator `user_id` and the email (G3)
- [ ] AC-5 `post_login` runs **once** across two turns for the same user
- [ ] AC-6 all four context sites carry the Navigator id when authenticated and
      the previous value when not
- [ ] AC-7 a deployment with no `navigator_auth_url` registers no `/login` and
      constructs no strategy
- [ ] `ruff check` clean on both modified modules; no token in any log
- [ ] `pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_auth_gate.py -q` passes

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_auth_gate.py -q`
- `pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_authorization.py -q`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_auth_gate.py
import pytest


class TestAuthGate:
    async def test_fails_closed_when_required(self):
        """auth_required=True + unauthenticated: card sent, agent never invoked."""
        # FILL IN: assert the agent mock recorded zero calls

    async def test_proceeds_when_not_required(self):
        """auth_required=False: behaviour identical to pre-feature."""
        # FILL IN

    async def test_gate_runs_after_is_authorized(self):
        """An unauthorized conversation is refused before any auth work."""
        # FILL IN


class TestPostLogin:
    async def test_runs_once_per_session(self):
        """Two turns, one post_login call."""
        # FILL IN

    async def test_user_context_shape(self):
        """channel == "msteams", user_id == nav id, email populated."""
        # FILL IN


class TestContextSites:
    async def test_all_four_sites_use_nav_id(self):
        """No code path leaks the Teams-scoped id once authenticated."""
        # FILL IN
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug msteams-user-auth-lane --feature-id FEAT-729`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/msteams-user-auth-lane.json`
4. **Verify the Codebase Contract** before writing ANY code. Re-grep every
   anchor: this task was written on `dev @ 0eb59926a` and the spec's §6 was
   verified on `37dc1da44`, so two anchors had already drifted once (see
   Context where noted). If anything moved, fix the contract FIRST.
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`)
   and commit only that index file
6. **Implement** — start from the Implementation Blueprint, complete every
   `# FILL IN:` marker, never change a signature or path it fixes
7. **Verify** the Acceptance Criteria — run the Validation Commands with
   `PYTHONPATH` set per changed package (the shared `.venv` is editable-installed
   against the MAIN checkout, so a bare `pytest` in a worktree imports the wrong
   branch)
8. **Commit the code** — stage only the files this task lists (never `git add .`)
9. **Close the task** with
   `scripts/sdd/close_task.sh TASK-4663 msteams-user-auth-lane verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed**: Implemented by the orchestrator (sdd-worker) after both Codex seats returned empty_delivery twice; not an MCP seat attempt. Four auth fields on MSTeamsAgentConfig (+ from_dict), auth lane construction/registration in MSTeamsAgentWrapper.__init__, auth gate + UserContext + once-per-session post_login (clone_for_user when singleton_agent is False), and all four user_id context sites via `_effective_user_id`. 13 new tests; whole msteams suite 313 passed.
**Deviations from scope**: (1) The gate sits after command dispatch rather than directly under `_is_authorized`: placing it before would block /login, /logout and /whoami for unauthenticated users under auth_required=True. It still runs after `_is_authorized`, which keeps first refusal. (2) `from_dict` in models.py also reads the four new fields (same file) so YAML configs work. (3) Class-level `_auth = None` default added because existing tests build the wrapper via `__new__`. (4) `singleton_agent` is not a field of MSTeamsAgentConfig; read via getattr default True.
**Ambiguities found in the spec**: Spec said three context sites, task said four; four were wired. The spec's `singleton_agent` clone mode has no config field in the Teams lane.
**Follow-up needed**: In non-singleton mode the clone is stored on `session.user_agent` but `form_orchestrator` still uses the shared agent, so the clone is not yet used for answering. Add a `singleton_agent` field to MSTeamsAgentConfig and route the orchestrator to the per-user agent if that mode is wanted. Per-user ToolManager cloning (as Telegram does in singleton mode) is not done.
