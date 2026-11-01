# TASK-5028: Pending login coordinator + correlated completion dispatch in the notifier

**Feature**: FEAT-776 — Connections on Telegram
**Spec**: `sdd/specs/connections-telegram.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5027, TASK-5023
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9 "Lifecycle contract" §2/§4/§5/§6 and Module 7 ("For `extra_state.combined=True`, dispatch completion
to M9's attempt coordinator before ordinary session hooks; defer those hooks until final login success"). This task
builds the wrapper-independent lifecycle engine: create/expire/cancel attempts, correlate a FEAT-773 callback
completion with (attempt, principal, provider, bot), advance the chain, and finalize **exactly once** through an
injected `finalize` callback — serialized with cancellation so an in-flight completion cannot revive a cancelled
login. The wrapper (TASK-5029) supplies `finalize` (persist link + promote candidate) and the UI.

---

## Scope

- Add `PendingLoginCoordinator` to `post_auth_connection.py`: `create(...)`, `get(attempt_id)`, `cancel(attempt_id | telegram_id)`,
  `supersede(telegram_id)`, `on_provider_completed(event, state_payload) -> bool`, `on_provider_failed(...)`, expiry.
- Attempt expiry ≤ earliest outstanding OAuth state expiry (`ConnectInitResponse.expires_in`); missing attempts
  (restart) fail closed.
- Finalization: when every required action is complete and optional ones completed or skipped → `await finalize(attempt)`
  under a per-attempt `asyncio.Lock`, re-checking `cancelled`/`finalized`/expiry inside the lock; idempotent.
- Duplicate / stale / mismatched completions (wrong principal, provider, bot or attempt) return False and never activate.
- `TelegramConnectionNotifier.notify`: when `state_payload["extra"].get("combined")` → `await coordinator.on_provider_completed(...)`
  **before** sending; ordinary session hooks are deferred (the coordinator replays them after finalize); delivery errors
  never prevent finalization (dispatch lifecycle independently of sending). Add `set_login_coordinator(coordinator)`.
- Tests: `test_connection_post_auth_build_and_handle` (correlation part), `test_combined_login_callback_correlation`,
  `test_combined_login_notifier_send_failure`, plus expiry/cancel-race unit tests.

**NOT in scope**: wrapper UI/handlers and strategy changes (TASK-5029); link writes (only via injected `finalize`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_connection.py` | MODIFY | coordinator |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/connection_notifier.py` | MODIFY | combined dispatch |
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_pending_login_coordinator.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.telegram.post_auth_connection import PendingLoginAttempt, ConnectionPostAuthProvider   # TASK-5027
from parrot.integrations.telegram.connection_notifier import TelegramConnectionNotifier                        # TASK-5022
from parrot.auth.oauth2.events import ConnectionEvent                                                          # verified: events.py:17
```

### Existing Signatures to Use
```python
# ConnectionEvent: kind, user_id, provider, account_id, display_name, channel, occurred_at, reason   (events.py:17-30)
# state_payload["extra"] carries what start_connect stored: chat_id, bot_id, attempt_id, combined   (TASK-5027)
# PendingLoginAttempt fields (TASK-5027): attempt_id, telegram_id, chat_id, bot_id, principal, permission_context,
#   candidate, actions, expires_at, completed, failed, finalized, cancelled
# PostAuthAction: provider: str ; required: bool = False                                            (models.py:23)
```

### Does NOT Exist
- ~~`PendingLoginCoordinator`~~, ~~`TelegramConnectionNotifier.set_login_coordinator`~~ — created here.
- ~~Persistent attempt storage~~ — in-memory only; restart = fail closed (spec lifecycle §6).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_connection.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/connection_notifier.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/telegram/test_pending_login_coordinator.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/events.py#ConnectionEvent"
  ]
}
```

---

## Implementation Notes

- Correlation keys: `extra["attempt_id"]` → attempt; `event.user_id == attempt.principal.user_id`;
  `event.provider in {a.provider for a in attempt.actions}`; `str(extra["bot_id"]) == attempt.bot_id`.
- Completed provider grants remain principal-owned if a later required step fails — never revoke as compensation.
- Failure / cancel / expiry → discard candidate; do not touch any DB link (no unlink, no restore).
- Use `time.monotonic()` for expiry; inject a clock for tests.

---

## Implementation Blueprint

### Steps (in order)
1. Append the coordinator to `post_auth_connection.py`.
2. Add combined dispatch + deferred hooks to the notifier.
3. Tests, including a cancel-vs-finalize race (`asyncio.gather`).

### `telegram/post_auth_connection.py` (MODIFY — append after `ConnectionPostAuthProvider`)
```python
class PendingLoginCoordinator:
    """Own pending login attempts; correlate completions; finalize exactly once."""

    def __init__(self, *, finalize: Callable[[PendingLoginAttempt], Awaitable[None]],
                 on_failed: Optional[Callable[[PendingLoginAttempt, str], Awaitable[None]]] = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._attempts: Dict[str, PendingLoginAttempt] = {}
        self._by_telegram: Dict[int, str] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._finalize = finalize
        self._on_failed = on_failed
        self._clock = clock
        self.logger = logging.getLogger(__name__)

    def create(self, **fields: Any) -> PendingLoginAttempt:
        """New attempt with an unpredictable id; supersedes any attempt for the same Telegram user."""
        # FILL IN: attempt_id = secrets.token_urlsafe(32); supersede(telegram_id); store
        raise NotImplementedError

    def cap_expiry(self, attempt_id: str, state_expires_in: int) -> None:
        """Lower ``expires_at`` to the outstanding OAuth state's expiry."""
        # FILL IN
        raise NotImplementedError

    def get(self, attempt_id: str) -> Optional[PendingLoginAttempt]:
        """Live (not expired/cancelled/finalized) attempt or None."""
        # FILL IN
        raise NotImplementedError

    async def cancel(self, *, attempt_id: Optional[str] = None, telegram_id: Optional[int] = None) -> None:
        """Invalidate under the attempt lock (serialized with finalize)."""
        # FILL IN
        raise NotImplementedError

    async def on_provider_completed(self, event: "ConnectionEvent", state_payload: Dict[str, Any]) -> bool:
        """Correlate; mark completed; finalize when the chain is satisfied. False on any mismatch."""
        # FILL IN: bounded by spec M9 lifecycle §4/§5
        raise NotImplementedError

    async def on_provider_failed(self, attempt_id: str, provider_id: str, reason: str) -> None:
        """Required → discard + on_failed; optional → mark skipped, maybe finalize."""
        # FILL IN
        raise NotImplementedError
# imports to add at top: asyncio, secrets, time, Awaitable, Callable
```

### `telegram/connection_notifier.py` (MODIFY)
```python
# occurrences: 1 (verified after TASK-5022: grep -c '    async def notify(self, event: ConnectionEvent, state_payload: Dict\[str, Any\]) -> None:' .../connection_notifier.py)
# add:
    def set_login_coordinator(self, coordinator: Any) -> None:
        """Route ``extra.combined`` completions to the staged-login coordinator (TASK-5029 wires it)."""
        self._login_coordinator = coordinator
# in notify(), first step inside the try:
#   FILL IN: if extra.get("combined") and coordinator: await coordinator.on_provider_completed(event, state_payload)
#   in its own try/except (lifecycle independent of delivery); skip ordinary session hooks for combined events
#   (the wrapper's finalize applies them); then send the text as usual
```

### FILL IN checklist
- [ ] Coordinator bodies; `__init__` sets `self._login_coordinator = None` in the notifier
- [ ] Tests: correlation mismatches rejected, duplicate idempotent, late completion after cancel/restart cannot finalize,
      send failure still finalizes once, cancel-vs-finalize race

---

## Acceptance Criteria

- [ ] AC-12 correlation/duplicate/late handling at the coordinator level
- [ ] `ruff check` clean

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_pending_login_coordinator.py -q`

Also re-run TASK-5022's `test_connection_notifier.py` locally (not listed: the graph check only resolves this task's own files).

---

## Test Specification

Test names fixed by spec §4: `test_combined_login_callback_correlation`, `test_combined_login_notifier_send_failure`,
`test_connection_post_auth_build_and_handle` (correlation half).

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-5027 and TASK-5023 are `done`
2. Implement from the blueprint; validate with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`
3. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-5028 connections-telegram verified`

---

## Completion Note

**Completed by**: sdd-worker; coded by gpt-5.6-terra (codex), attempt 1, reviewed and corrected by the worker
**Date**: 2026-11-01
**Notes**:
- `post_auth_connection.py`: `PendingLoginCoordinator(finalize, on_failed, clock)` owns pending attempts. `create` issues an unpredictable id (`secrets.token_urlsafe(32)`) and supersedes any earlier attempt of the same Telegram user; `cap_expiry` lowers `expires_at` to the outstanding OAuth state's lifetime; `get` returns only live, unexpired attempts; `cancel`/`supersede` invalidate and drop the candidate; every transition runs under the attempt's lock.
- `on_provider_completed` accepts a `connection.completed` event only when the attempt is live and the event's `user_id`, provider and `extra.bot_id` match; a duplicate returns true without re-finalizing. Finalization runs once, after every required action completed and every optional one settled, and a finalizer error cannot re-run it. `on_provider_failed` cancels the attempt for a required action (reporting once via `on_failed`) and only settles an optional one.
- `connection_notifier.py`: `set_login_coordinator`; a `combined` completion is dispatched to the coordinator and skips the normal session hook, a coordinator error never blocks the notification.
- The coordinator is not wired into the wrapper yet (TASK-5029 does that).
- Review corrections (`b338000f6c`): the per-attempt lock was never released (now popped in the single discard path, with `test_finished_and_cancelled_attempts_release_their_locks`); `ConnectionEvent` was missing from the `TYPE_CHECKING` imports (the engine's `F821`). Recorded as `coder-feedback:bcaf52a35208be1ec67b014e`, review `coder-review:4b1d7d6a014bda292633055b`.
- Validation: 24 tests across the coordinator, notifier and provider files pass; a branch-vs-`dev` run over the Telegram-related test files shows no red that is not already red on `dev` (18 vs 29).

**Deviations from spec**: none.
