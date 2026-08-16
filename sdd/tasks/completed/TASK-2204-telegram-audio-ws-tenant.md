# TASK-2204: Telegram WebApp and audio WebSocket tenant handling

**Feature**: FEAT-421 — Client-declared tenant in the forms URL
**Spec**: `sdd/specs/forms-tenant-in-url.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2199, TASK-2201
**Assigned-to**: unassigned

---

## Context

Implements spec Module 8 — the two surfaces the decorator cannot cover on its own.

1. **`ui/telegram.py` carries its own private copy of `_get_request_tenant`**
   (`:24`), duplicating the three-step fallback. Deleting `api/_utils`'s copy
   (TASK-2203) does not touch it. Miss this and a second guessing path survives
   the whole feature, silently.

2. **The audio WS route is not `_wrap_auth`-ed.** It is mounted bare because
   navigator-auth's decorators return HTTP 401, which is incompatible with the
   WebSocket upgrade handshake; JWT validation happens inside
   `AudioFormWSHandler` via `TokenValidator`. So its tenant check must be
   inline, after JWT validation — the decorator is not available here.

---

## Scope

- Delete the local `_get_request_tenant` in `ui/telegram.py:24` and use
  `declared_tenant` at both call sites (`:80`, `:122`).
- In `AudioFormWSHandler.handle_websocket`, read the tenant from
  `request.match_info["tenant"]` after JWT validation succeeds and before
  resolving the form. Missing tenant → close the socket with a policy-violation
  close code and a structured reason, NOT an HTTP 400 (the connection is already
  upgraded by then).
- Cross-check: if the resolved form's tenant differs from the declared one,
  close the socket the same way rather than serving the form.
- Tests for both surfaces.

**NOT in scope**: route path changes (TASK-2201 already re-prefixed them),
`api/_utils.py` (TASK-2203).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/ui/telegram.py` | MODIFY | Delete duplicate, use `declared_tenant` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py` | MODIFY | Inline tenant check |
| `packages/parrot-formdesigner/tests/unit/ui/test_telegram_tenant.py` | CREATE | Telegram tests |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_tenant.py` | CREATE | Audio WS tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Signatures

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/ui/telegram.py
def _get_request_tenant(request: web.Request) -> str | None:   # :24  DELETE THIS
    """Mirrors ``parrot_formdesigner.api._utils._get_request_tenant`` but is
    ..."""                                                     # :27  (its own docstring says so)
class TelegramWebAppHandler:
    async def serve_webapp(...):
        tenant = _get_request_tenant(request)                  # :80   -> declared_tenant
    async def rest_fallback(...):
        tenant = _get_request_tenant(request)                  # :122  -> declared_tenant

# packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py — the audio block
if synthesizer is not None or transcriber is not None or token_validator is not None:
    from .audio_ws import AudioFormWSHandler
    from ..services.validators import FormValidator
    audio_handler = AudioFormWSHandler(
        registry=registry, synthesizer=synthesizer, transcriber=transcriber,
        validator=FormValidator(), token_validator=token_validator,
        submission_storage=submission_storage, auto_synthesize=synthesizer is None,
    )
    app.router.add_get(
        f"{bp}/forms/{{form_uid}}/audio/ws",
        audio_handler.handle_websocket,     # <-- NOT wrapped with _wrap_auth
    )
```

### The Telegram routes (re-prefixed by TASK-2201)

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/ui/routes.py:109-116
app.router.add_get(f"{bp}/forms/{{form_uid}}/telegram", telegram.serve_webapp)
app.router.add_post(
    f"{bp}/api/v1/forms/{{form_uid}}/telegram-submit", telegram.rest_fallback,
)
# ^ note the nested api/v1 under the UI prefix on the second one — it is real,
#   not a typo. Both are PUBLIC (no auth), so they take tenant="public".
```

### Does NOT Exist

- ~~`ui/telegram.py` importing `_get_request_tenant` from `._utils`~~ — it does
  NOT import it; it defines its own. Deleting the `_utils` copy leaves this one
  compiling and wrong.
- ~~`_wrap_auth` on the audio WS route~~ — deliberately absent. Do not add it;
  navigator-auth's 401 breaks the upgrade handshake. Use the inline check.
- ~~an HTTP 400 response from an upgraded WebSocket~~ — once
  `web.WebSocketResponse.prepare()` has run, the HTTP status is already sent.
  Close with a WS close code instead.
- ~~`declared_tenant` working on the audio WS route~~ — that route has no
  `requires_tenant` decorator, so `request["tenant"]` is never set and
  `declared_tenant` would raise `RuntimeError`. Read `request.match_info`
  directly here.

---

## Implementation Notes

### Key Constraints

- Telegram routes are public (no session). They take `tenant="public"` in the
  wrapper — declaration still required (400 if absent), authorization skipped.
- For the WS close, use a policy-violation close code (1008) with a JSON reason
  naming the same `error` slugs as the HTTP errors, so clients can branch on one
  vocabulary across both transports.
- Order in `handle_websocket`: validate JWT → read declared tenant → resolve
  form → cross-check tenant → serve. Never resolve the form before the tenant
  is known; that is what allows a cross-tenant read.
- Run `grep -rn "_get_request_tenant" packages/parrot-formdesigner/src` at the
  end — it must return **nothing** once this task lands.

### References in Codebase

- `ui/telegram.py:24-40` — the duplicate to delete.
- `api/routes.py` audio block (FEAT-224/236) — the unwrapped route.
- `api/tenant.py` — `declared_tenant` (TASK-2199).

---

## Acceptance Criteria

- [ ] `ui/telegram.py` has no local `_get_request_tenant`
- [ ] `grep -rn "_get_request_tenant" packages/parrot-formdesigner/src` returns **nothing**
- [ ] Both Telegram handlers resolve the declared tenant
- [ ] Telegram route with no tenant segment → 400 `tenant_not_declared`
- [ ] Audio WS with no tenant segment → socket closed with code 1008, not a 400 response
- [ ] Audio WS resolving a form from another tenant → socket closed, form not served
- [ ] Audio WS happy path still completes the handshake and serves the form
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/`

---

## Test Specification

```python
class TestTelegramTenant:
    def test_local_duplicate_is_gone(self):
        from parrot_formdesigner.ui import telegram
        assert not hasattr(telegram, "_get_request_tenant")

    async def test_serve_webapp_uses_declared_tenant(self, request_with_tenant):
        ...  # resolves "flexroc", not programs[0]

    async def test_rest_fallback_uses_declared_tenant(self, request_with_tenant):
        ...

    async def test_missing_tenant_is_400(self, bare_request):
        ...  # TenantNotDeclaredError


class TestAudioWSTenant:
    async def test_missing_tenant_closes_socket(self, ws_client):
        """Already upgraded — must close(1008), not return HTTP 400."""
        ...

    async def test_cross_tenant_form_closes_socket(self, ws_client, two_tenant_registry):
        ...  # form belongs to navigator, socket declared flexroc

    async def test_happy_path_serves_form(self, ws_client):
        ...
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/forms-tenant-in-url.spec.md` (Module 8, §7 audio WS note)
2. **Check dependencies** — TASK-2199 and TASK-2201 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/forms-tenant-in-url.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2204-telegram-audio-ws-tenant.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-16
**Notes**: Deleted `ui/telegram.py`'s local `_get_request_tenant` and its
docstring; both call sites use `declared_tenant` from `..api.tenant`. Also
fixed `serve_webapp`'s `fallback_url` construction, which hardcoded the
pre-TASK-2201 unprefixed path (`/api/v1/forms/{uid}/telegram-submit`) —
now `/api/v1/t/{tenant}/forms/{uid}/telegram-submit`, matching the actual
registered route. `AudioFormWSHandler.handle_websocket` reads
`request.match_info.get("tenant")` right after JWT auth succeeds (Step
1.5) and closes with WS code 1008 + a `TENANT_NOT_DECLARED` error message
when absent/empty — before the message loop, so `start_session` can never
be dispatched without a tenant. `_handle_start_session` now resolves the
form via the declared tenant (was `tenant=None` → silently
`registry.default_tenant`) and cross-checks `form.tenant != declared` →
close(1008) rather than serve (defense-in-depth, same rationale as
`_assert_form_tenant`, TASK-2202).

**Necessary correction beyond this task's file list**: also modified
`ui/routes.py` to wrap both Telegram routes with `_page_wrap(handler,
protect=False, tenant="public")`. TASK-2201 registered them completely
unwrapped; this task's own Scope required `declared_tenant()` to work in
`ui/telegram.py`, which only works if `requires_tenant` actually ran for
the request — otherwise it always raises `RuntimeError`. `protect=False`
means `_page_wrap` returns `requires_tenant(public=True)(handler)`
directly, skipping navigator-auth's `is_authenticated`/`user_session`
entirely (exactly what Telegram clients need, matching audio WS's own
"can't go through navigator-auth" rationale) while still validating +
stashing the declared tenant. This matches this task's own "Key
Constraints" text verbatim ("Telegram routes are public... They take
`tenant='public'` **in the wrapper**") — the Scope/AC were achievable no
other way. Documented rather than silently expanded scope.

**Flagged for spec-owner visibility** (discovered during this task,
pre-dates it): `test_ui_imports.py::test_importing_ui_does_not_pull_api`
has been failing since **TASK-2200**, not this task — `ui/routes.py`
importing `from ..api.tenant import requires_tenant` forces Python to
execute `api/__init__.py` (which seeds the controls registry and hard-
imports `navigator_auth` via `api/routes.py`), breaking the documented
"ui is independently importable without api" invariant. This is a direct,
unavoidable consequence of the spec's own Module 3 design ("`ui/routes.py`
gains the same decorator" from `api.tenant`) — not a bug in any single
task's implementation, and not something any of FEAT-421's 10 tasks lists
as owned. A real fix would mean relocating `tenant.py`/`errors.py` out of
`api/` into a neutral, dependency-light location both `ui` and `api` could
import without triggering `api/__init__.py`'s side effects — a much larger
refactor, out of scope for this feature. Recommend either retiring that
test's assumption or filing a follow-up ticket.

Full `tests/formdesigner/` suite: confirmed via before/after diff
(stash/pop) that my changes introduce **zero** new failures — the 20
already-failing `test_audio_integration.py` WS tests (hardcoded
pre-TASK-2201 unprefixed paths, e.g. `/api/v1/forms/integration-test/
audio/ws`) are unchanged, pre-dating this task, deferred to TASK-2206.
`tests/unit/`: zero new failures beyond the post-TASK-2203 baseline (46/46
unchanged). New test files: `test_telegram_tenant.py` (6/6, using a mocked
registry to isolate tenant-declaration behaviour from a pre-existing,
unrelated `form_uid` string/UUID coercion bug in `ui/telegram.py` — see
that file's module docstring) and `test_audio_tenant.py` (4/4, patching
`web.WebSocketResponse.prepare`/`close`/`send_json` at the class level to
exercise `handle_websocket` without a live transport). Lint diff-count
unchanged for `api/audio_ws.py` (44/44) and `ui/routes.py` (2/2);
`ui/telegram.py` verified back at its pre-existing baseline (2/2) after
fixing my own import-order addition.

**Deviations from spec**: none in intent — see the `ui/routes.py`
correction and the flagged `test_ui_imports.py` pre-existing regression
above, both fully documented rather than silently absorbed.
