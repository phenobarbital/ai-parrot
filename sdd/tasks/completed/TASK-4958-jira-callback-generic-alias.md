# TASK-4958: /api/auth/jira/callback served by the generic callback; delete jira_oauth_callback

**Feature**: FEAT-773 — Delegated Auth Connections — S-1 Connections Core
**Spec**: `sdd/specs/delegated-auth-connections.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4955, TASK-4947
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 (AC-7, AC-14, U5). The Atlassian app's registered redirect URI is `/api/auth/jira/callback` and must
keep working, but it becomes an alias of the generic `make_oauth2_callback("jira")`. `jira_oauth_callback`, its
channel dispatch and the lazy `parrot.integrations` imports in `parrot/auth/routes.py` are deleted — completion now
flows through `ConnectionEventPublisher` → notifier adapters. The generic callback must also handle the provider's
`?error=` redirect (user denied consent), which the Jira callback handled and the generic one does not.

---

## Scope

- `routes.py`: `setup_jira_oauth_routes(app)` → `setup_oauth2_routes(app, "jira", "/api/auth/jira/callback")`, idempotent
  (skip if a GET route already exists for the path); delete `jira_oauth_callback`, `_handle_web_callback`,
  `_notify_telegram`, `_handle_oauth_error`, the TYPE_CHECKING integrations imports and dead templates; `routes.py`
  imports nothing from `parrot.integrations` (AC-7).
- `oauth2_routes.py`: in `make_oauth2_callback`, handle `?error=<code>&state=<nonce>`: consume the nonce if present,
  publish nothing, render the error page (400) — no channel notification (record that Telegram's "failure" DM on
  denied consent is dropped, or FILL IN: publish a `connection.refresh_failed`-like event only if the spec allows — it
  does not define one, so do not invent an event kind).
- Update `test_oauth_callback_routes.py` and `test_callback_web.py` (they exercise `jira_oauth_callback`).
- Test `test_jira_callback_alias_path`.

**NOT in scope**: removing the FEAT-083 placeholder tool (S-3a); notifier adapters (TASK-4953).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/routes.py` | MODIFY | alias + deletions |
| `packages/ai-parrot/src/parrot/auth/oauth2_routes.py` | MODIFY | provider ?error= branch |
| `packages/ai-parrot/tests/unit/test_oauth_callback_routes.py` | MODIFY | alias tests |
| `tests/unit/integrations/oauth2/test_callback_web.py` | MODIFY | use the generic callback |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `a848d5a73e` (2026-10-30) while writing this task.
> Use these exact imports and signatures. Anything not listed: VERIFY it exists before using it.

### Verified Imports
```python
from parrot.auth.oauth2_routes import setup_oauth2_routes, make_oauth2_callback   # verified: oauth2_routes.py:283, :200
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/routes.py
if TYPE_CHECKING: from .jira_oauth import JiraOAuthManager, JiraTokenSet; from parrot.integrations.telegram.jira_commands import TelegramOAuthNotifier  # :36-38
async def _handle_web_callback(...)       # :83   ; async def _notify_telegram(...) # :169 ; async def _handle_oauth_error(...) # :186
async def jira_oauth_callback(request: web.Request) -> web.Response:      # :232 anchor
def setup_jira_oauth_routes(app: web.Application) -> None:                # :333
    app.router.add_get("/api/auth/jira/callback", jira_oauth_callback)    # :341 anchor ; exclude_list append :346-349
# packages/ai-parrot/src/parrot/auth/oauth2_routes.py
def make_oauth2_callback(provider_id: str):                               # :200 — reads app[f"oauth2_manager_{provider_id}"]
def setup_oauth2_routes(app, provider_id, callback_path) -> None          # :283 — add_get + navigator_auth exclude_list
# JiraOAuthManager.setup (after TASK-4954) sets app["oauth2_manager_jira"] and calls setup_jira_oauth_routes(app)
```

### Does NOT Exist
- After this task: ~~`jira_oauth_callback`~~ — deleted (AC-14).
- ~~a `connection.failed` / `connection.denied` event kind~~ — not in the spec's `ConnectionEventKind`; do not add one.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/auth/routes.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/auth/oauth2_routes.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/test_oauth_callback_routes.py",
      "action": "MODIFY"
    },
    {
      "path": "tests/unit/integrations/oauth2/test_callback_web.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/routes.py#jira_oauth_callback",
    "sym:packages/ai-parrot/src/parrot/auth/routes.py#setup_jira_oauth_routes",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2_routes.py#make_oauth2_callback"
  ]
}
```

---

## Implementation Notes

- grep the repo for `jira_oauth_callback` / `setup_jira_oauth_routes` callers before deleting (tests under
  `tests/integration/oauth2/` are TASK-4964's).
- Do NOT change `JIRA_REDIRECT_URI` (spec §7).

---

## Implementation Blueprint

> Executor-ready starting point. Write each block to its declared path, then complete every
> `# FILL IN:` marker. Business branches, edge cases and test bodies are stubs by design.
> Never change a signature, class name or file path the blueprint fixes.

### Steps (in order)
1. Add the `?error=` branch to the generic callback — *why*: parity for denied consent.
2. Rewrite `setup_jira_oauth_routes` and delete the old handler + helpers — *why*: AC-14 / AC-7.
3. Update the two test files; add the alias test.

### `packages/ai-parrot/src/parrot/auth/routes.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    app.router.add_get("/api/auth/jira/callback", jira_oauth_callback)' routes.py → :341)
def setup_jira_oauth_routes(app: web.Application) -> None:
    """Mount the generic OAuth2 callback at Jira's registered redirect URI (alias, AC-14)."""
    from parrot.auth.oauth2_routes import setup_oauth2_routes
    # FILL IN: return early when app.router already has GET "/api/auth/jira/callback"; else
    #          setup_oauth2_routes(app, "jira", "/api/auth/jira/callback")
# occurrences: 1 (verified: 'async def jira_oauth_callback(request: web.Request) -> web.Response:' :232)
# DELETE jira_oauth_callback and every helper only it used (:75-331); drop the TYPE_CHECKING integrations import (:36-38)
```

### `packages/ai-parrot/src/parrot/auth/oauth2_routes.py` (MODIFY)
```python
# In make_oauth2_callback.handler, BEFORE the "Missing code or state" check:
        provider_error = request.query.get("error")
        if provider_error:
            # FILL IN: if state is present, best-effort delete the nonce key via manager._nonce_key(state);
            #          logger.info(provider, error code); return _error_response("Authorization was cancelled or
            #          denied at the provider.", status=400)
            pass
```

### FILL IN checklist
- [ ] idempotent `setup_jira_oauth_routes`
- [ ] delete old handler/helpers/imports
- [ ] `?error=` branch
- [ ] tests (`test_jira_callback_alias_path`, updated callback tests)

---

## Acceptance Criteria

- [ ] AC-14: `/api/auth/jira/callback` is served by the generic handler; `jira_oauth_callback` no longer exists
- [ ] AC-7: `parrot/auth/routes.py` imports nothing from `parrot.integrations`
- [ ] A `?error=access_denied` redirect renders the error page and writes nothing

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_oauth_callback_routes.py -q`
- `pytest tests/unit/integrations/oauth2/test_callback_web.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/test_oauth_callback_routes.py (add)
@pytest.mark.asyncio
async def test_jira_callback_alias_path(aiohttp_client): ...   # route resolves to make_oauth2_callback("jira") handler;
                                                               # `import parrot.auth.routes as r; not hasattr(r, "jira_oauth_callback")`
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug delegated-auth-connections --feature-id FEAT-773`)
2. **Read the spec** (`sdd/specs/delegated-auth-connections.spec.md`) — at least §2, the module section named in Context, §5 and §7
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/delegated-auth-connections.json`
4. **Verify the Codebase Contract** before writing ANY code (re-grep each anchor; line numbers drift). If an entry is stale, fix the contract in this file first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a signature or path the blueprint fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH` set to every touched `packages/<dist>/src` (the shared `.venv` imports the main checkout otherwise)
8. **Commit the code** — stage only the files listed above (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-ID> delegated-auth-connections verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker orchestrator; seat gpt-5.6-sol (codex)
**Date**: 2026-10-30
**Notes**: Implemented per task; merged, engine lint clean. Merge-tier validation: only reds are legacy tests/integration/oauth2/test_e2e_{web_connect,telegram_regression,auth_envelope}.py, intentionally rewritten by TASK-4964.
