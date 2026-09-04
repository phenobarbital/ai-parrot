"""Stage 0.5 token counting for conversation turns (FEAT-525).

Every memory instance counts every written turn, always-on. The default
counter is ``tiktoken``'s ``o200k_base`` encoding; when ``tiktoken`` is
unavailable or the encoding cannot be loaded (e.g. offline), a cheap
heuristic (bytes // 4) is used instead, named ``"heuristic"`` so callers
can tell the two apart.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Protocol

import orjson

from parrot.memory.abstract import ConversationTurn
from parrot.memory.compaction.models import TokenCount

logger = logging.getLogger(__name__)

#: Lazy per-encoding-name cache of loaded ``tiktoken.Encoding`` instances.
#: Never populated at import time — ``tiktoken.get_encoding`` may hit the
#: network on first use (precedent: ``knowledge/wiki/store.py:187-202``).
_ENCODINGS: Dict[str, Any] = {}
_DEFAULT: Optional["TokenCounter"] = None
_WARNED = False


class TokenCounter(Protocol):
    """A named, synchronous text tokenizer."""

    name: str

    def count(self, text: str) -> int:
        """Return the token count for ``text``."""
        ...


class TiktokenCounter:
    """Counts tokens using a named ``tiktoken`` encoding (default ``o200k_base``)."""

    def __init__(self, encoding: str = "o200k_base") -> None:
        """Initialize the counter.

        Args:
            encoding: The ``tiktoken`` encoding name.
        """
        self.name = encoding

    def count(self, text: str) -> int:
        """Return the ``tiktoken`` token count for ``text``.

        Args:
            text: The text to count.

        Returns:
            ``0`` for empty text; otherwise the number of BPE tokens.
        """
        if not text:
            return 0
        enc = _ENCODINGS.get(self.name)
        if enc is None:
            import tiktoken

            enc = _ENCODINGS[self.name] = tiktoken.get_encoding(self.name)
        return len(enc.encode(text, disallowed_special=()))


class HeuristicCounter:
    """Cheap, deterministic token estimate: ``bytes // 4``, minimum 1 for non-empty text."""

    name = "heuristic"

    def count(self, text: str) -> int:
        """Return the heuristic token estimate for ``text``.

        Args:
            text: The text to count.

        Returns:
            ``0`` for empty text; otherwise ``max(1, len(text.encode("utf-8")) // 4)``.
        """
        if not text:
            return 0
        return max(1, len(text.encode("utf-8")) // 4)


def get_default_counter() -> TokenCounter:
    """Return the process-wide default :class:`TokenCounter`.

    Returns a :class:`TiktokenCounter` (``o200k_base``) when ``tiktoken``
    can be imported and the encoding loads; otherwise a
    :class:`HeuristicCounter`, logging one warning per process on the
    first fallback. The result is cached per process.

    Returns:
        The resolved default counter.
    """
    global _DEFAULT, _WARNED
    if _DEFAULT is not None:
        return _DEFAULT

    try:
        import tiktoken

        tiktoken.get_encoding("o200k_base")
        _DEFAULT = TiktokenCounter("o200k_base")
    except Exception:  # noqa: BLE001 — tokenizer optional, any failure falls back
        if not _WARNED:
            logger.warning(
                "tiktoken unavailable or 'o200k_base' failed to load; "
                "falling back to heuristic token counting"
            )
            _WARNED = True
        _DEFAULT = HeuristicCounter()
    return _DEFAULT


def count_turn(turn: ConversationTurn, counter: TokenCounter) -> TokenCount:
    """Count the tokens in one turn.

    ``context_used`` is deliberately excluded (spec decision).

    Args:
        turn: The turn to count.
        counter: The counter to use.

    Returns:
        A :class:`TokenCount` with ``user``, ``assistant``, ``tools`` and
        ``total`` (their sum), stamped with ``counter.name``.
    """
    user = counter.count(turn.user_message)
    assistant = counter.count(turn.assistant_response)

    tools = 0
    for inv in turn.tool_invocations:
        canonical_input = orjson.dumps(inv.input, option=orjson.OPT_SORT_KEYS).decode()
        tools += counter.count(canonical_input)
        tools += counter.count(inv.output or "")
        tools += counter.count(inv.error or "")

    total = user + assistant + tools
    return TokenCount(user=user, assistant=assistant, tools=tools, total=total, tokenizer=counter.name)


def needs_recount(turn: ConversationTurn, counter: TokenCounter) -> bool:
    """Return whether ``turn`` must be (re)counted with ``counter``.

    Args:
        turn: The turn to check.
        counter: The counter that would be used to (re)count it.

    Returns:
        ``True`` when the turn has no ``token_count`` yet, or its
        tokenizer differs from ``counter.name``.
    """
    return turn.token_count is None or turn.token_count.tokenizer != counter.name
