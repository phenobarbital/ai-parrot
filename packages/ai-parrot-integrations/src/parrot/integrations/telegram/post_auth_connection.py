"""Generic secondary-authorization provider for the staged Telegram /login (FEAT-776 M9)."""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Set

from parrot.auth.oauth2.registry import OAuth2ProviderRegistry
from parrot.auth.permission import PermissionContext
from parrot.auth.principal import Principal

if TYPE_CHECKING:  # pragma: no cover
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
