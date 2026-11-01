# TASK-5029: Staged combined login in the wrapper (primary first, pending candidate, final-success publication)

**Feature**: FEAT-776 — Connections on Telegram
**Spec**: `sdd/specs/connections-telegram.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5028, TASK-5026, TASK-5020
**Assigned-to**: unassigned

---

## Context

Spec §2 "Combined login", §3 Module 9 lifecycle §1–§7, AC-1 (combined path), AC-12. Today `handle_login` builds the
provider URL for an **unauthenticated** session (`_build_next_auth_url`, wrapper.py:2281), Azure/Google strategies
run the post-auth chain eagerly inside `handle_callback` (auth.py:683-684, :961-962), and `_handle_combined_auth`
mutates the active session before secondary steps finish. This task replaces that with the staged interaction:
primary login WebApp → validated primary callback → **pending candidate** (separate from `_user_sessions`) →
secondary Connect button(s) built only for the candidate → correlated completions (TASK-5028) → finalize once:
persist link (TASK-5020's `_persist_principal_link`), promote the candidate to the active session, apply deferred
session hooks, initialize user context.

---

## Scope

- `handle_login`: never call `_build_next_auth_url` on an unauthenticated session; show the primary login only
  (remove the `next_auth_url` kwargs path; YAML/provider names remain compatible).
- Primary callback (single-step, `_handle_combined_auth`, Composite/Azure/Google/Basic): when `post_auth_actions` are
  configured, run primary validation into a **candidate** `TelegramUserSession` (not stored in `_user_sessions`), then
  `coordinator.create(...)` and send the first secondary Connect button via `provider.build_auth_url(attempt, ...)`;
  `cap_expiry` with the state's `expires_in`. Re-verify the primary credential-to-user validation seam: never accept a
  Navigator user id only because it appears in WebApp JSON; if no seam exists, implement the verification before any
  provider state is minted (spec lifecycle §2).
- `auth.py`: Azure/Google strategies stop running `_run_post_auth_chain` eagerly (keep `supports_post_auth_chain`);
  primary validation is separated from post-auth execution for every strategy.
- `finalize(attempt)` (wrapper method injected into the coordinator): recheck validity → `_persist_principal_link(candidate)`
  (failure follows AC-3) → `self._user_sessions[tg_id] = candidate` → replay deferred hooks → `_initialize_user_context`;
  serialized with logout/cancel by the coordinator lock.
- `on_failed`: required failure/expiry → discard candidate, message "Login requires authorization for <providers>. Please
  try again with /login." (plain text); no link write, no unlink, no restore.
- `handle_logout` and a superseding `/login` cancel the pending attempt; `principal_for_session`, `_ensure_principal_link`,
  `_invoke_agent` and command principals never see a candidate.
- Wire `notifier.set_login_coordinator(self._login_coordinator)` when the app notifier exists.
- Tests: rewrite `packages/ai-parrot/tests/unit/test_wrapper_combined_auth.py`; update `test_azure_post_auth.py` and
  `test_post_auth_capability_gate.py`; new `test_staged_combined_login.py` with `test_combined_login_required_failure`,
  `test_pending_login_never_backfills`, `test_e2e_combined_login_from_unauthenticated`, `test_e2e_combined_required_failure_no_link`,
  and the combined half of `test_login_persists_link_both_paths`.

**NOT in scope**: coordinator internals (TASK-5028), provider internals (TASK-5027), docs (TASK-5031).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | staged flow + finalize |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py` | MODIFY | no eager post-auth chain |
| `packages/ai-parrot/tests/unit/test_wrapper_combined_auth.py` | MODIFY | staged semantics |
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_azure_post_auth.py` | MODIFY | no eager chain |
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_post_auth_capability_gate.py` | MODIFY | gate semantics |
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_staged_combined_login.py` | CREATE | lifecycle + e2e tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.telegram.post_auth_connection import (PendingLoginAttempt, PendingLoginCoordinator,
    ConnectionPostAuthProvider)                                                   # TASK-5027/5028
from parrot.integrations.telegram.auth import TelegramUserSession, CompositeAuthStrategy   # verified: auth.py:44, :1446
```

### Existing Signatures to Use
```python
# telegram/wrapper.py
async def handle_login(self, message: Message) -> None                    # :2249 ; `next_url, required = await self._build_next_auth_url(session)` :2281
async def _build_next_auth_url(self, session) -> Tuple[Optional[str], bool]   # :639 (remove or restrict to attempts)
async def handle_logout(self, message: Message) -> None                   # :2315
async def handle_web_app_data(self, message: Message) -> None             # :2334 ; single-step `success = ...handle_callback(data, session)` :2367
def _is_combined_payload(self, data) -> bool                              # :634
async def _handle_combined_auth(self, message, data, session) -> None     # :2384 ; `basic_ok = ...handle_callback(basic_data, session)` :2409 ;
                                                                          #   `if failures_required:` :2450
async def _initialize_user_context(self, session, message=None)           # :1377
self._post_auth_registry: PostAuthRegistry                                # :198
# telegram/auth.py
class AbstractAuthStrategy: supports_post_auth_chain: bool = False ; async def handle_callback(self, data, session) -> bool   # :299, :316, :344
class AzureAuthStrategy: __init__(..., post_auth_registry=None) :552 ; eager chain :683-684 ; _run_post_auth_chain :688
class GoogleAuthStrategy: __init__(..., post_auth_registry=None) :835 ; eager chain :961-962 ; _run_post_auth_chain :966
class CompositeAuthStrategy: handle_callback :1572 (sets session.metadata["auth_method"] :1608)
```

### Does NOT Exist
- ~~A pending-candidate store in `_user_sessions`~~ — candidates live only in the coordinator.
- ~~Revoke-as-compensation for completed grants~~ — forbidden (lifecycle §7).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/test_wrapper_combined_auth.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/telegram/test_azure_post_auth.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/telegram/test_post_auth_capability_gate.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/telegram/test_staged_combined_login.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper.handle_login",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper.handle_web_app_data",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper._handle_combined_auth",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper._build_next_auth_url",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py#AzureAuthStrategy._run_post_auth_chain",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py#GoogleAuthStrategy._run_post_auth_chain"
  ]
}
```

---

## Implementation Notes

- The spec calls this flow a security decision (M9 not delegation-eligible). Implement the lifecycle contract
  literally; when a step is ambiguous, stop and write it in the Completion Note rather than improvising.
- `handle_callback(data, candidate)` populates a fresh `TelegramUserSession(telegram_id=...)` that is NOT the active
  session object; on success it becomes `attempt.candidate`.
- Single-step logins (no `post_auth_actions`) are unchanged from TASK-5020.
- Run `wikitoolkit symbols blast TelegramAgentWrapper._handle_combined_auth` and `... _build_next_auth_url` first.

---

## Implementation Blueprint

### Steps (in order)
1. Construct `self._login_coordinator = PendingLoginCoordinator(finalize=self._finalize_login_attempt, on_failed=self._fail_login_attempt)`
   in `__init__` after `_init_post_auth_providers()`; register it on the notifier.
2. `handle_login`: delete the `supports_post_auth_chain` / `_build_next_auth_url` block (anchor below).
3. `handle_web_app_data` / `_handle_combined_auth`: primary → candidate → attempt → first Connect button.
4. `auth.py`: remove eager chain calls; strategies only validate primary.
5. Finalize/fail/logout/supersede methods; tests.

### `telegram/wrapper.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '            next_url, required = await self._build_next_auth_url(session)' .../telegram/wrapper.py)
# DELETE the enclosing `if getattr(self._auth_strategy, "supports_post_auth_chain", False) and len(self._post_auth_registry) > 0:`
# block (:2279-2284) so `kwargs` stays empty — primary login is always shown first.

# occurrences: 1 (verified: grep -c '        basic_ok = await self._auth_strategy.handle_callback(basic_data, session)' ...)
# _handle_combined_auth: validate into a candidate, never the active session:
        candidate = TelegramUserSession(telegram_id=session.telegram_id, telegram_username=session.telegram_username)
        basic_ok = await self._auth_strategy.handle_callback(basic_data, candidate)
        # FILL IN: on success → await self._start_login_attempt(message, candidate); return
        # (the old per-provider handle_result loop and `if failures_required:` rollback (:2450) are replaced by the coordinator)

    async def _start_login_attempt(self, message: Message, candidate: TelegramUserSession) -> None:
        """Create the pending attempt and send the first secondary Connect button (URL authorization only)."""
        # FILL IN: principal from candidate.nav_user_id (validated); context = self._connection_permission_context(candidate, principal);
        # attempt = self._login_coordinator.create(...); for the first pending action: url = await provider.build_auth_url(attempt, self.config, ...)
        # → plain-text message + URL button; any exception on a required action → await self._login_coordinator.on_provider_failed(...)

    async def _finalize_login_attempt(self, attempt: PendingLoginAttempt) -> None:
        """Persist link, promote candidate, replay deferred hooks, init user context (called once by the coordinator)."""
        # FILL IN: bounded by spec M9 lifecycle §5 and AC-3

    async def _fail_login_attempt(self, attempt: PendingLoginAttempt, reason: str) -> None:
        """Discard the candidate; never touch DB links."""
        # FILL IN

# handle_logout (anchor `        old_name = session.display_name`, :2327 — TASK-5020 already inserted the unlink before clear_auth):
#   FILL IN: also `await self._login_coordinator.cancel(telegram_id=session.telegram_id)` (and answer even when not authenticated
#   but an attempt was pending)
```

### `telegram/auth.py` (MODIFY)
```python
# occurrences: 2 (verified: grep -c '            await self._run_post_auth_chain(data, session)' .../telegram/auth.py) — :684 (Azure), :962 (Google)
# FILL IN: disambiguate — quote the preceding comment line of each block ("# FEAT-109: invoke post-auth chain ..." :680 for Azure,
# "# Invoke post-auth chain if a registry was injected." :960 for Google) and delete both `if self._post_auth_registry ...` blocks;
# leave `_run_post_auth_chain` methods in place only if still referenced by tests, otherwise delete them too.
```

### FILL IN checklist
- [ ] Primary credential-to-user validation seam verified (document which call proves the nav user id)
- [ ] Coordinator wiring, finalize, fail, logout/supersede cancel
- [ ] Strategy eager-chain removal for Azure + Google (Basic/Composite verified to have none)
- [ ] Tests listed in Scope; `test_wrapper_combined_auth.py` rewritten for staged semantics

---

## Acceptance Criteria

- [ ] AC-12 end-to-end: fresh unauthenticated login completes without pre-primary provider state; required failure/cancel/expiry
      publishes no link and leaves existing links untouched; no candidate visible to principals/backfill/agent
- [ ] AC-1 combined path: link written exactly once at final success
- [ ] `ruff check` clean

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_staged_combined_login.py -q`
- `pytest packages/ai-parrot/tests/unit/test_wrapper_combined_auth.py -q`
- `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_azure_post_auth.py -q`
- `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_post_auth_capability_gate.py -q`

Also re-run TASK-5020's `test_principal_link_lifecycle.py` locally (not listed: the graph check only resolves this task's own files).

---

## Test Specification

Test names fixed by spec §4 (M9 rows, `test_pending_login_never_backfills`, the two `test_e2e_combined_*`).

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-5028, TASK-5026, TASK-5020 are `done`
2. Implement from the blueprint; validate with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src:packages/ai-parrot-server/src`
3. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-5029 connections-telegram verified`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
