"""Generic secondary-authorization provider for the staged Telegram /login (FEAT-776 M9)."""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, List, Mapping, Optional, Set

from parrot.auth.oauth2.registry import OAuth2ProviderRegistry
from parrot.auth.permission import PermissionContext
from parrot.auth.principal import Principal

if TYPE_CHECKING:  # pragma: no cover
    from parrot.auth.oauth2.events import ConnectionEvent
    from parrot.auth.oauth2.service import IntegrationsService
    from parrot.integrations.telegram.connection_notifier import SessionHook
    from parrot.integrations.telegram.models import PostAuthAction


@dataclass
class PendingLoginAttempt:
    """A validated primary login awaiting its secondary authorizations (never an active session)."""

    attempt_id: str
    telegram_id: int
    chat_id: int
    bot_id: str
    principal: Principal
    permission_context: PermissionContext
    candidate: Any
    actions: List["PostAuthAction"]
    expires_at: float
    completed: Set[str] = field(default_factory=set)
    failed: Set[str] = field(default_factory=set)
    events: Dict[str, Any] = field(default_factory=dict)
    finalized: bool = False
    cancelled: bool = False


class ConnectionPostAuthProvider:
    """``PostAuthProvider`` for any registered OAuth2 provider; writes no identity rows or tokens."""

    def __init__(
        self,
        provider_id: str,
        *,
        service: "IntegrationsService",
        app: Mapping[str, Any],
        session_hook: Optional["SessionHook"] = None,
    ) -> None:
        self.provider_name = provider_id
        self._service = service
        self._app = app
        self.session_hook = session_hook
        self.logger = logging.getLogger(__name__)
        self._callback_lock = asyncio.Lock()
        self._consumed_states: "OrderedDict[str, None]" = OrderedDict()

    async def build_auth_url(self, session: Any, config: Any, callback_base_url: str) -> str:
        """Start a connect for a verified pending candidate; raise on any failure (required-step failure)."""
        del config, callback_base_url
        if not isinstance(session, PendingLoginAttempt):
            raise ValueError("secondary authorization requires a verified pending login attempt")

        response = await self._service.start_connect(
            session.principal.user_id,
            self.provider_name,
            channel="telegram",
            principal=session.principal,
            extra_state={
                "chat_id": session.chat_id,
                "bot_id": session.bot_id,
                "attempt_id": session.attempt_id,
                "combined": True,
            },
            permission_context=session.permission_context,
        )
        auth_url = getattr(response, "auth_url", None)
        if not isinstance(auth_url, str) or not auth_url:
            raise ValueError(f"provider {self.provider_name!r} does not support URL authorization")
        return auth_url

    async def handle_result(self, data: Dict[str, Any], session: Any, primary_auth_data: Dict[str, Any]) -> bool:
        """Route a retained code/state through the single FEAT-773 callback consumer, once."""
        del primary_auth_data
        if not isinstance(session, PendingLoginAttempt):
            return False

        code = data.get("code")
        state = data.get("state")
        if not code or not state:
            return False

        provider = OAuth2ProviderRegistry().get(self.provider_name)
        manager = getattr(provider, "manager", None) if provider is not None else None
        if manager is None:
            return False

        async with self._callback_lock:
            if state in self._consumed_states:
                return False
            self._consumed_states[state] = None
            self._consumed_states.move_to_end(state)
            if len(self._consumed_states) > 1024:
                self._consumed_states.popitem(last=False)
            try:
                _token_set, state_payload = await manager.handle_callback(code, state)
            except Exception:  # noqa: BLE001 - compatibility entry reports callback rejection to the wrapper
                self.logger.warning(
                    "Post-auth callback failed for provider %s",
                    self.provider_name,
                    exc_info=True,
                )
                return False

        extra = state_payload.get("extra") if isinstance(state_payload, dict) else None
        if not isinstance(extra, dict):
            return False
        return (
            state_payload.get("nav_user_id") == session.principal.user_id
            and extra.get("attempt_id") == session.attempt_id
            and str(extra.get("bot_id")) == session.bot_id
            and extra.get("combined") is True
        )


class PendingLoginCoordinator:
    """Own pending login attempts; correlate completions; finalize exactly once."""

    def __init__(
        self,
        *,
        finalize: Callable[[PendingLoginAttempt], Awaitable[None]],
        on_failed: Optional[Callable[[PendingLoginAttempt, str], Awaitable[None]]] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._attempts: Dict[str, PendingLoginAttempt] = {}
        self._by_telegram: Dict[int, str] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._finalize = finalize
        self._on_failed = on_failed
        self._clock = clock
        self.logger = logging.getLogger(__name__)

    def _discard(self, attempt: PendingLoginAttempt) -> None:
        """Remove an attempt from lookup indexes without changing persisted state.

        The per-attempt lock is dropped too (a holder keeps its own reference), so finished and cancelled
        attempts do not accumulate locks for the life of the process.
        """
        self._attempts.pop(attempt.attempt_id, None)
        self._locks.pop(attempt.attempt_id, None)
        if self._by_telegram.get(attempt.telegram_id) == attempt.attempt_id:
            self._by_telegram.pop(attempt.telegram_id, None)

    def _cancel_attempt(self, attempt: PendingLoginAttempt) -> None:
        """Discard a candidate that must never become an authenticated session."""
        attempt.cancelled = True
        attempt.candidate = None
        self._discard(attempt)

    def _expired(self, attempt: PendingLoginAttempt) -> bool:
        """Expire an attempt and report whether it can no longer progress."""
        if self._clock() < attempt.expires_at:
            return False
        self._cancel_attempt(attempt)
        return True

    def _is_live(self, attempt: PendingLoginAttempt) -> bool:
        """Return whether an attempt is available for a new lifecycle event."""
        return not attempt.cancelled and not attempt.finalized and not self._expired(attempt)

    def create(self, **fields: Any) -> PendingLoginAttempt:
        """New attempt with an unpredictable id; supersedes any attempt for the same Telegram user."""
        telegram_id = fields["telegram_id"]
        self.supersede(telegram_id)
        attempt = PendingLoginAttempt(attempt_id=secrets.token_urlsafe(32), **fields)
        self._attempts[attempt.attempt_id] = attempt
        self._by_telegram[attempt.telegram_id] = attempt.attempt_id
        self._locks[attempt.attempt_id] = asyncio.Lock()
        return attempt

    def cap_expiry(self, attempt_id: str, state_expires_in: int) -> None:
        """Lower ``expires_at`` to the outstanding OAuth state's expiry."""
        attempt = self._attempts.get(attempt_id)
        if attempt is None or not self._is_live(attempt):
            return
        attempt.expires_at = min(attempt.expires_at, self._clock() + state_expires_in)

    def get(self, attempt_id: str) -> Optional[PendingLoginAttempt]:
        """Return a live, unexpired attempt, or ``None``."""
        attempt = self._attempts.get(attempt_id)
        if attempt is None or not self._is_live(attempt):
            return None
        return attempt

    def supersede(self, telegram_id: int) -> None:
        """Invalidate the currently indexed attempt for one Telegram user."""
        attempt_id = self._by_telegram.get(telegram_id)
        if attempt_id is None:
            return
        attempt = self._attempts.get(attempt_id)
        if attempt is not None and not attempt.finalized:  # an in-flight finalize is never cancelled mid-way
            self._cancel_attempt(attempt)

    async def cancel(self, *, attempt_id: Optional[str] = None, telegram_id: Optional[int] = None) -> None:
        """Invalidate under the attempt lock (serialized with finalize)."""
        if attempt_id is None and telegram_id is not None:
            attempt_id = self._by_telegram.get(telegram_id)
        if attempt_id is None:
            return
        attempt = self._attempts.get(attempt_id)
        lock = self._locks.get(attempt_id)
        if attempt is None or lock is None:
            return
        async with lock:
            self._cancel_attempt(attempt)

    @staticmethod
    def _all_actions_settled(attempt: PendingLoginAttempt) -> bool:
        """Return whether every required action completed and optionals settled."""
        for action in attempt.actions:
            if action.required and action.provider not in attempt.completed:
                return False
            if not action.required and action.provider not in attempt.completed | attempt.failed:
                return False
        return True

    async def on_provider_completed(self, event: "ConnectionEvent", state_payload: Dict[str, Any]) -> bool:
        """Correlate a completion and finalize the attempt when its chain is satisfied."""
        extra = state_payload.get("extra")
        if not isinstance(extra, dict) or event.kind != "connection.completed":
            return False
        attempt_id = extra.get("attempt_id")
        if not isinstance(attempt_id, str):
            return False
        attempt = self.get(attempt_id)
        lock = self._locks.get(attempt_id)
        if attempt is None or lock is None:
            return False

        async with lock:
            if not self._is_live(attempt):
                return False
            providers = {action.provider for action in attempt.actions}
            if (
                event.user_id != attempt.principal.user_id
                or event.provider not in providers
                or str(extra.get("bot_id")) != attempt.bot_id
            ):
                return False
            if event.provider in attempt.completed:
                return True

            attempt.completed.add(event.provider)
            attempt.events[event.provider] = event
            if not self._all_actions_settled(attempt):
                return True

            if attempt.cancelled or attempt.finalized or self._expired(attempt):
                return False
            attempt.finalized = True
            try:
                await self._finalize(attempt)
            except Exception:  # noqa: BLE001 - a finalizer must not duplicate activation on retry
                self.logger.exception("Pending Telegram login finalization failed (attempt=%s)", attempt.attempt_id)
            finally:
                # Stay registered while finalizing so cancel() waits on the attempt lock instead of racing it.
                self._discard(attempt)
            return True

    async def on_provider_failed(self, attempt_id: str, provider_id: str, reason: str) -> None:
        """Fail required actions or settle optional actions, then finalize if appropriate."""
        attempt = self.get(attempt_id)
        lock = self._locks.get(attempt_id)
        if attempt is None or lock is None:
            return
        async with lock:
            if not self._is_live(attempt):
                return
            action = next((item for item in attempt.actions if item.provider == provider_id), None)
            if action is None or provider_id in attempt.completed | attempt.failed:
                return

            attempt.failed.add(provider_id)
            if action.required:
                self._cancel_attempt(attempt)
                if self._on_failed is not None:
                    try:
                        await self._on_failed(attempt, reason)
                    except Exception:  # noqa: BLE001 - failure reporting cannot revive the pending login
                        self.logger.exception("Pending Telegram login failure callback failed (attempt=%s)", attempt_id)
                return

            if not self._all_actions_settled(attempt):
                return
            if attempt.cancelled or attempt.finalized or self._expired(attempt):
                return
            attempt.finalized = True
            try:
                await self._finalize(attempt)
            except Exception:  # noqa: BLE001 - a finalizer must not duplicate activation on retry
                self.logger.exception("Pending Telegram login finalization failed (attempt=%s)", attempt_id)
            finally:
                self._discard(attempt)
