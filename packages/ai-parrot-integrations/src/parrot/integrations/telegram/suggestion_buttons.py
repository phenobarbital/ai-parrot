"""Telegram inline-keyboard rendering of follow-up suggestion chips (FEAT-752).

``callback_data`` is capped at 64 bytes, so each button carries ``sg:<token>`` and the chip itself lives in a TTL
store keyed by that token. Only non-action chips are rendered (Telegram has no explain path).
"""

from __future__ import annotations

import json
import logging
import secrets
from typing import Any, Optional, Sequence

from ..core.state import InMemoryStateStore
from .callbacks import CallbackData, build_inline_keyboard

SUGGESTION_PREFIX = "sg"
MAX_BUTTONS = 6
BUTTONS_PER_ROW = 2
MAX_LABEL = 40


class SuggestionButtonStore:
    """Token → chip mapping with expiry. ``store`` must expose async ``set/get/delete`` (InMemoryStateStore API)."""

    def __init__(self, ttl_s: int = 86400, store: Optional[Any] = None) -> None:
        self.ttl_s = int(ttl_s)
        self._store = store if store is not None else InMemoryStateStore()
        self.logger = logging.getLogger(__name__)

    @staticmethod
    def _key(token: str) -> str:
        return f"telegram:suggestion:{token}"

    @staticmethod
    def _new_token() -> str:
        """12 URL-safe characters that can never parse as JSON.

        ``CallbackData.decode`` runs ``json.loads`` on the part after the separator and only falls back to
        ``{"raw": <str>}`` on failure. A purely numeric token (e.g. ``123456789012``) would parse as an int, so the
        token always starts with a letter that cannot begin a JSON literal.
        """
        return "s" + secrets.token_urlsafe(8)

    async def put(self, *, prompt: str, output_mode: Optional[str], chat_id: int, user_id: int) -> str:
        """Store one chip and return its token."""
        token = self._new_token()
        record = {"prompt": prompt, "output_mode": output_mode, "chat_id": int(chat_id), "user_id": int(user_id)}
        await self._store.set(self._key(token), json.dumps(record), expire=self.ttl_s)
        return token

    async def get(self, token: str) -> Optional[dict]:
        """Return the stored chip, or None when unknown/expired/corrupt."""
        raw = await self._store.get(self._key(token))
        if raw is None:
            return None
        try:
            record = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            self.logger.warning("Corrupt suggestion button record for token %s", token)
            return None
        return record if isinstance(record, dict) else None


def _kind_of(chip: Any) -> str:
    kind = chip.get("kind") if isinstance(chip, dict) else getattr(chip, "kind", None)
    return str(getattr(kind, "value", kind) or "")


def _field(chip: Any, name: str) -> Any:
    return chip.get(name) if isinstance(chip, dict) else getattr(chip, name, None)


async def build_suggestion_keyboard(
    suggestions: Sequence[Any], store: SuggestionButtonStore, *, chat_id: int, user_id: int
) -> Optional[dict]:
    """Build a ``build_inline_keyboard`` dict for the non-action chips, or None when nothing is renderable.

    Chips are read duck-typed (``label``, ``prompt``, ``output_mode``, ``kind``) so plain dicts work too.
    """
    buttons: list[dict[str, str]] = []
    for chip in suggestions:
        if len(buttons) >= MAX_BUTTONS:
            break
        if _kind_of(chip) == "action":
            continue
        label = str(_field(chip, "label") or "")[:MAX_LABEL]
        prompt = _field(chip, "prompt")
        if not label or not prompt:
            continue
        mode = _field(chip, "output_mode")
        mode = str(getattr(mode, "value", mode)) if mode is not None else None
        token = await store.put(prompt=str(prompt), output_mode=mode, chat_id=chat_id, user_id=user_id)
        callback_data = f"{SUGGESTION_PREFIX}{CallbackData.SEPARATOR}{token}"
        if len(callback_data.encode("utf-8")) > CallbackData.MAX_BYTES:
            continue  # unreachable with the 12-char token; never send an invalid callback_data
        buttons.append({"text": label, "callback_data": callback_data})
    if not buttons:
        return None
    rows = [buttons[i : i + BUTTONS_PER_ROW] for i in range(0, len(buttons), BUTTONS_PER_ROW)]
    return build_inline_keyboard(rows)
