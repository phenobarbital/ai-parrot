"""/login, /logout and /whoami for the MS Teams lane."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from botbuilder.core import TurnContext

from parrot.auth.token_exchange import (
    REASON_BACKEND_NOT_LOADED,
    REASON_USER_NOT_FOUND,
)

if TYPE_CHECKING:  # pragma: no cover
    from parrot.integrations.msteams.auth import MSTeamsAuthStrategy
    from parrot.integrations.msteams.commands import MSTeamsCommandRouter

logger = logging.getLogger(__name__)


async def _send_text(turn_context: TurnContext, text: str) -> None:
    """Send a plain-text Teams response.

    Args:
        turn_context: Active Bot Framework conversation context.
        text: User-visible response text.
    """
    from botbuilder.schema import Activity

    await turn_context.send_activity(Activity(type="message", text=text))


def register_auth_commands(
    router: "MSTeamsCommandRouter",
    strategy: "MSTeamsAuthStrategy",
) -> None:
    """Register /login, /logout and /whoami on the router.

    Args:
        router: Router that dispatches the MS Teams slash commands.
        strategy: Strategy that manages Navigator authentication sessions.
    """

    async def cmd_login(turn_context: TurnContext, *_args: object) -> None:
        """Sign the user in, or send the sign-in card."""
        session = await strategy.ensure_authenticated(turn_context)
        if session.authenticated and session.nav_user_id:
            email = session.nav_email or "email unavailable"
            await _send_text(
                turn_context,
                f"Signed in to Navigator as {session.nav_user_id} ({email}).",
            )
            return

        reason = session.metadata.get("auth_reason")
        if reason == REASON_USER_NOT_FOUND:
            await _send_text(
                turn_context,
                "Your account is not provisioned in Navigator. An administrator must create the account.",
            )
            return
        if reason == REASON_BACKEND_NOT_LOADED:
            await _send_text(
                turn_context,
                "The server is not configured for this sign-in method. Please contact an operator.",
            )
            return
        if reason in (None, "invalid_token"):
            await strategy.send_signin_card(turn_context)
            return

        await _send_text(turn_context, "Sign-in failed. Try `/login` again.")

    async def cmd_logout(turn_context: TurnContext, *_args: object) -> None:
        """Drop the Navigator session and the Token Service token."""
        await strategy.sign_out(turn_context)
        await _send_text(turn_context, "Signed out of Navigator.")

    async def cmd_whoami(turn_context: TurnContext, *_args: object) -> None:
        """Report the resolved Navigator identity and session expiry."""
        session = await strategy.store.get_or_create(turn_context)
        if not session.authenticated or strategy.store.is_expired(session):
            await _send_text(turn_context, "You are not signed in to Navigator. Use `/login` to sign in.")
            return

        email = session.nav_email or "not available"
        expiry = session.external_expires_at or "not available"
        await _send_text(
            turn_context,
            f"Navigator ID: {session.nav_user_id}\nEmail: {email}\nSession expires: {expiry}",
        )

    router.register("/login", cmd_login)
    router.register("/logout", cmd_logout)
    router.register("/whoami", cmd_whoami)
    logger.debug("Registered MS Teams authentication commands")
