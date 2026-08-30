# TASK-2574: Route deep-link resume through `dispatch` and mount the deep-link routes

**Feature**: FEAT-469 — A2UI Agent Functions Runtime (v1.0 RPC leg)
**Spec**: `sdd/specs/a2ui-agent-functions.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2573
**Assigned-to**: unassigned

---

## Context

Implements **spec §3 Module 7** — but at a **substantially reduced scope**, and
you must read why before starting.

The spec was written before FEAT-470 merged and claimed this task would migrate
`ResumePayload` / `build_structured_message` from an ad-hoc
`a2ui_action_resume` JSON shape to a v1.0 `action` envelope. **FEAT-470 already
did all of that** (its G6 / TASK-2545). Verified on `dev`:

- `ResumePayload.action_payload` is **already** a v1.0 `action` envelope, and a
  `field_validator` enforces it at construction (`outputs/a2ui/deeplink.py:53-90`).
- `build_structured_message` **already** emits
  `{"type": "a2ui_action", "action": payload.action_payload}`
  (`handlers/deeplink.py:51-63`) — the `a2ui_action_resume` tag is gone.
- That `a2ui_action` tag is a **shared wire contract** already consumed by Teams
  (`integrations/msteams/wrapper.py:414-428`), Telegram
  (`integrations/telegram/wrapper.py:1564`) and `integrations/a2ui_resume.py:34`.

So two things genuinely remain:
1. Route the resume through `A2UIRuntime.dispatch(..., transport="deeplink")`
   instead of handing the raw JSON string to the `invoker`, so a deep-link click
   persists surface state and produces a turn by exactly the same path as HTTP and A2A.
2. **Mount `setup_deeplink_routes`** — still verified unmounted: 
   `grep -rn "setup_deeplink_routes" packages/*/src` returns only its own
   definition (`handlers/deeplink.py:116`) and its docstring. The web deep-link
   route is not exposed by the manager today.

---

## Scope

- Make `DeepLinkResumeHandler.handle` dispatch through `A2UIRuntime` with
  `transport="deeplink"`.
- Mount `setup_deeplink_routes` in `manager.py`, guarding against double registration.
- Tests for both.

**NOT in scope** — and actively forbidden:
- **Do NOT change the `a2ui_action` tag or the payload shape.** Teams and Telegram
  depend on it; changing it breaks both.
- **Do NOT rewrite `ResumePayload`** — it is already v1.0 and self-validating.
- Any change to `outputs/a2ui/deeplink.py`'s token minting/consumption.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/deeplink.py` | MODIFY | Dispatch through `A2UIRuntime` |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | Call `setup_deeplink_routes` |
| `packages/ai-parrot-server/tests/test_deeplink_resume_web.py` | MODIFY | Dispatch-path tests |
| `packages/ai-parrot-server/tests/manager/test_deeplink_routes_mounted.py` | CREATE | Mount test |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` @ `ce716a032` (2026-08-29).

### Verified Imports
```python
from parrot.outputs.a2ui.deeplink import (            # outputs/a2ui/deeplink.py
    DeepLinkService,        # 92
    DeepLinkExpiredError,   # 49
    ResumePayload,          # 53
)
from parrot.handlers.deeplink import (                # ai-parrot-server/.../handlers/deeplink.py
    DeepLinkResumeHandler,   # 66
    build_structured_message,# 51   (spec said ~55 — corrected)
    setup_deeplink_routes,   # 116  (spec said 113 — corrected)
    ResumeInvoker,           # 32
)
from parrot.outputs.a2ui.runtime.dispatch import A2UIRuntime          # TASK-2569
from parrot.outputs.a2ui.runtime.models import A2UICallContext        # TASK-2568
```

### Existing Signatures to Use — read them before changing anything
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/deeplink.py
_KEY_TEMPLATE = "a2ui:deeplink:{token_id}"     # 41
_DEFAULT_TTL_SECONDS = 15 * 60                 # 42   (spec said "= 900"; same value, different literal)

class ResumePayload(BaseModel):                # 53
    session_id: str; user_id: str; agent_id: str; channel: str
    action_payload: dict[str, Any] = Field(default_factory=dict)
    @field_validator("action_payload")
    @classmethod
    def _validate_action_envelope(cls, value):
        """Already enforces: A2UIRendererMessage.model_validate(value) and
        envelope.action is not None  (FEAT-470 G6). Raises ValueError otherwise."""

class DeepLinkService:                         # 92
    def _resume_url(self, channel, token_id)   # ~109
    async def consume(self, token) -> ResumePayload   # raises DeepLinkExpiredError

# packages/ai-parrot-server/src/parrot/handlers/deeplink.py
ResumeInvoker = Callable[..., Awaitable[Any]]  # 32 — (agent_name, query, session_id, user_id)

def build_structured_message(payload: ResumePayload) -> str:   # 51
    return json.dumps({"type": "a2ui_action", "action": payload.action_payload},
                      sort_keys=True)          # 60-63   <- ALREADY v1.0. Do not change.

class DeepLinkResumeHandler:                   # 66
    def __init__(self, service: DeepLinkService, invoker: ResumeInvoker) -> None:  # 69
    async def handle(self, token: str) -> tuple[dict[str, Any], int]:              # 74
        # 400 on empty token; 410 + _EXPIRED_MESSAGE on DeepLinkExpiredError;
        # else: query = build_structured_message(payload)
        #       result = await self.invoker(agent_name=payload.agent_id, query=query,
        #                                   session_id=payload.session_id, user_id=payload.user_id)
        #       return {"status": "resumed", "session_id": ..., "result": result}, 200
    def render_landing(self, token: str) -> str:      # ~99
    async def landing(self, request) -> web.Response: # ~103  GET — NO state change (prescanner-safe)
    async def resume(self, request) -> web.Response:  # ~111  POST — consumes the single-use token

def setup_deeplink_routes(app, service, invoker, *,
                          path: str = "/api/v1/a2ui/resume/web") -> DeepLinkResumeHandler:  # 116
    app.router.add_get(path, handler.landing)    # confirm page — safe for prescanners
    app.router.add_post(path, handler.resume)    # consumes the token
```

### The confirm-before-consume design (do NOT collapse it)
`handlers/deeplink.py:38-50` documents why GET renders a landing page and only
POST consumes: email link prescanners (Defender Safe Links, Google Workspace)
**GET every link** before the user sees it, and would silently burn a single-use
token and show a false "expired" error. Keep GET side-effect-free.

### Does NOT Exist
- ~~`build_structured_message` emitting `a2ui_action_resume`~~ — **stale spec claim**; it emits `a2ui_action` and has since FEAT-470.
- ~~`ResumePayload` needing migration to v1.0~~ — already v1.0 with a validator.
- ~~any non-test caller of `setup_deeplink_routes`~~ — verified: only its own definition/docstring. This task adds the first one.
- ~~a `channel` argument on `ResumeInvoker`~~ — the signature is `(agent_name, query, session_id, user_id)`.

---

## Implementation Notes

### Dispatching the resume
In `handle()`, after `consume(token)` succeeds, build:
```python
A2UICallContext(
    agent_id=payload.agent_id, user_id=payload.user_id,
    session_id=payload.session_id, transport="deeplink",
    permission_context=build_principal_context(principal=payload.user_id, channel=payload.channel),
)
```
then `await runtime.dispatch(payload.action_payload, ctx)`. That gives a
deep-link click the same surface-state persistence and turn construction as the
HTTP and A2A paths — which is the entire point of the task.

`payload.action_payload` is already a validated `action` envelope, so hand it to
`dispatch` **directly**; do not re-wrap or re-serialize it.

Keep `build_structured_message` and the `invoker` call for turn injection — the
`a2ui_action` string is what the bot layer consumes. `dispatch` supplies the
`surface_state`; the invoker supplies the turn. Do not delete one in favour of
the other without a test proving the bot still sees both.

Preserve `handle()`'s existing return contract exactly: `(body, status)` with
400 / 410 / 200 and the `_EXPIRED_MESSAGE` text.

### Mounting
Register in `manager.py` alongside the other agent routes. `setup_deeplink_routes`
needs a `DeepLinkService` (Redis-backed) and a `ResumeInvoker` wrapping the
AgentTalk POST flow. Spec §7 warns: "al montarlo, cualquier despliegue que ya
expusiera la ruta por otro medio podría duplicarla — comprobar en `manager.py`
antes de registrar." So:
- Check whether `/api/v1/a2ui/resume/web` is already registered before adding it;
  skip with a warning if so (aiohttp raises on duplicate routes — an unguarded
  call would crash startup for such a deployment).
- Guard on the `DeepLinkService`'s dependencies being available (no Redis ⇒ log
  and skip, do not crash the manager).

### Key Constraints
- Do not change the `a2ui_action` wire tag or payload shape.
- Keep GET side-effect-free.
- async throughout; `self.logger`.

### References in Codebase
- `handlers/deeplink.py` — read the whole file; it is short and every design choice is documented in it.
- `integrations/msteams/wrapper.py:414-428` — the other end of the `a2ui_action` contract.
- `integrations/a2ui_resume.py:34` — the shared tag documentation.
- `manager/manager.py:1933-1942` — route-registration neighbourhood.
- `packages/ai-parrot-server/tests/test_deeplink_resume_web.py` — existing tests to extend.

---

## Acceptance Criteria

- [ ] `DeepLinkResumeHandler.handle` dispatches through `A2UIRuntime` with `transport="deeplink"`.
- [ ] A deep-link resume carrying a `dataModel` persists surface state, exactly as the HTTP path does.
- [ ] `build_structured_message` still emits `{"type": "a2ui_action", "action": ...}` — byte-identical to today.
- [ ] `handle()` still returns 400 (empty token) / 410 + `_EXPIRED_MESSAGE` (expired) / 200 (`{"status": "resumed", ...}`).
- [ ] GET the landing route does **not** consume the token; POST does.
- [ ] `setup_deeplink_routes` is called by `manager.py`; `/api/v1/a2ui/resume/web` resolves (GET and POST).
- [ ] Registering when the path already exists logs a warning and does not raise.
- [ ] A missing Redis/`DeepLinkService` logs and skips rather than crashing manager startup.
- [ ] Teams/Telegram resume paths are unaffected (their tests still pass).
- [ ] Tests pass: `pytest packages/ai-parrot-server/tests/test_deeplink_resume_web.py packages/ai-parrot-server/tests/manager -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-server/src/parrot/handlers/deeplink.py`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/test_deeplink_resume_web.py
class TestDispatchPath:
    async def test_resume_dispatches_action_v1(self, handler, spy_runtime):
        body, status = await handler.handle(token)
        assert status == 200
        env, ctx = spy_runtime.dispatch.call_args[0]
        assert "action" in env and ctx.transport == "deeplink"

    async def test_resume_persists_surface_state(self, handler, surfaces): ...

    def test_structured_message_shape_unchanged(self, payload):
        """Teams + Telegram depend on this exact string."""
        import json
        from parrot.handlers.deeplink import build_structured_message
        assert json.loads(build_structured_message(payload))["type"] == "a2ui_action"

    async def test_expired_token_still_410(self, handler_expired):
        body, status = await handler_expired.handle("tok")
        assert status == 410 and "expired" in body["detail"].lower()

    async def test_get_landing_does_not_consume(self, client, service): ...
```

```python
# packages/ai-parrot-server/tests/manager/test_deeplink_routes_mounted.py
async def test_deeplink_routes_mounted(app):
    paths = {r.resource.canonical for r in app.router.routes()}
    assert "/api/v1/a2ui/resume/web" in paths

async def test_duplicate_registration_warns_not_raises(app, caplog): ...
async def test_missing_redis_skips_gracefully(app_without_redis, caplog): ...
```

---

## Agent Instructions

1. **Read the spec** — §3 Module 7, **including its "CORRECCIÓN (verificado 2026-08-29)"** block, which explains why this task is smaller than the original text implies.
2. **Check dependencies** — TASK-2573 in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — re-read `handlers/deeplink.py` end to end and
   re-run `grep -rn "setup_deeplink_routes" packages/*/src` to confirm it is still unmounted.
4. **Update status** in the index → `"in-progress"`.
5. **Implement** per scope. Do not touch the `a2ui_action` tag or `ResumePayload`.
6. **Verify** every acceptance criterion, including that Teams/Telegram tests still pass.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-08-29
**Notes**: Did NOT touch `ResumePayload`, its `field_validator`, `build_structured_message`,
or the `a2ui_action` tag/payload shape — confirmed all three already v1.0
per the spec's own "CORRECCIÓN" note, and Teams/Telegram tests (6 passed)
prove they still work unmodified. Added `DeepLinkResumeHandler.__init__`'s
new optional `runtime_factory` param (`RuntimeFactory = Callable[[str, str],
Awaitable[A2UIRuntime]]`) and a `_dispatch()` helper: when set, `handle()`
now dispatches `payload.action_payload` (handed to `dispatch` directly, per
instruction — never re-wrapped) through `A2UIRuntime` with
`transport="deeplink"` and a `build_principal_context`-built
`PermissionContext`, BEFORE the existing `build_structured_message`+
`invoker` call (both kept, complementary as instructed — dispatch persists
surface state, the invoker still injects the conversational turn).
`_dispatch()` catches and logs any exception rather than raising: a
single-use token is already consumed by the time dispatch runs, so a
dispatch failure must not swallow the turn injection. `runtime_factory`
defaults to `None` (dispatch skipped, turn injection unaffected) — kept
every EXISTING call site (`DeepLinkResumeHandler(service, invoker)`, no
third arg) working byte-for-byte; all 5 original tests in
`test_deeplink_resume_web.py` pass unmodified.

`setup_deeplink_routes` gained a `runtime_factory` param and a
duplicate-registration guard (`{route.resource.canonical for route in
app.router.routes()}` before adding — verified this correctly detects an
existing path via a real aiohttp `Application`) — returns `None` and logs a
warning instead of letting aiohttp raise on the second `add_get`/`add_post`.
Mounted via a new `BotManager._register_a2ui_deeplink_routes()` (checks
`app.get("redis")` first — `None` logs and returns without calling
`setup_deeplink_routes` at all, so a Redis-less deployment never even
constructs a `DeepLinkService`), called from `setup()` right after the
A2UIHandler HTTP routes (TASK-2573). Two new `BotManager` methods
(`_a2ui_deeplink_invoker`, `_a2ui_deeplink_runtime_factory`) resolve the
agent via the manager's own `get_bot()` and build a fresh
`ToolManagerExecutor`/`ConversationMemorySurfaceStore`/`A2UIRuntime` per
call — same per-request-construction pattern as TASK-2572/2573, since
`ConversationMemorySurfaceStore` binds `user_id` at construction time.

Added `TestDispatchPath` (6 tests: dispatch call shape/transport, real
surface-state persistence via a `dataModel`-carrying action + a real
`FileConversationMemory`-backed store, `build_structured_message`
byte-shape unchanged, 410-on-expired skips dispatch entirely, landing GET
doesn't trigger dispatch, `runtime_factory=None` still resumes) to the
existing `test_deeplink_resume_web.py`, plus a new
`tests/manager/test_deeplink_routes_mounted.py` (mounted / duplicate-warns
/ missing-Redis-skips, exercising `_register_a2ui_deeplink_routes()`
directly against a real `aiohttp.web.Application` rather than the full
`BotManager.setup()` pipeline — lighter and more targeted). All 11 + 3 new
tests pass; full `ai-parrot-server` handlers+manager+a2a+deeplink slice
(433 passed) plus Teams/Telegram deep-link suites (6 passed) show zero
regressions — the only failures are the same 2 pre-existing
`test_agent_a2ui_stream.py` cases already confirmed unrelated in TASK-2573.
`ruff check`: zero new violations across all three pre-existing files
(`deeplink.py`, `manager.py`, `test_deeplink_resume_web.py` — diffed
per-rule counts against `git stash` baselines); the two brand-new test
files are fully clean.

**Deviations from spec**: none beyond what the task itself already flagged
as a scope correction (spec §3 Module 7's "CORRECCIÓN" — this task file
already narrowed the scope for me; I did not need to further correct
anything new). One implementation decision the task didn't fully specify:
`runtime_factory`'s exact type/injection mechanism. Modeled it as an async
`(agent_id, user_id) -> A2UIRuntime` factory rather than, e.g., passing a
`BotManager` reference into `handlers/deeplink.py` directly — keeps that
module free of any `BotManager`/agent-resolution import (pure
dependency-injection, consistent with the file's existing "thin transport"
design and its complete lack of agent-stack imports today).
