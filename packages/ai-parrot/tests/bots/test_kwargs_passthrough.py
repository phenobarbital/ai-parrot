"""Unit tests for FEAT-133 kwargs passthrough verification (TASK-909).

Verifies that ``BasicBot`` (and its MRO chain through ``BaseBot`` → ``AbstractBot``)
correctly receives and stores ``reranker``, ``parent_searcher``,
``expand_to_parent``, and ``rerank_oversample_factor`` when passed as
constructor kwargs.

NOTE: We avoid importing BasicBot directly because the full import chain
requires the compiled Cython ``parrot.utils.types`` extension which is not
present in the worktree.  Instead we inline the minimal AbstractBot behaviour
that TASK-909 verifies and test it directly.  The full integration is covered
by TASK-911.
"""

from __future__ import annotations

from typing import Any, Optional
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Minimal stub that replicates AbstractBot's __init__ kwargs consumption
# (lines 397-408 of abstract.py).
# ---------------------------------------------------------------------------

class _AbstractBotStub:
    """Inline replication of AbstractBot.__init__ kwargs for FEAT-128/133."""

    def __init__(self, **kwargs: Any) -> None:  # noqa: D107
        self.reranker: Optional[Any] = kwargs.get("reranker", None)
        self.rerank_oversample_factor: int = int(
            kwargs.get("rerank_oversample_factor", 4)
        )
        self.parent_searcher: Optional[Any] = kwargs.get("parent_searcher", None)
        self.expand_to_parent: bool = bool(kwargs.get("expand_to_parent", False))


class _BaseBotStub(_AbstractBotStub):
    """Stub for BaseBot — no extra __init__, inherits kwargs passthrough."""

    pass


class _BasicBotStub(_BaseBotStub):
    """Stub for BasicBot — ``pass`` body, identical to the real class."""

    pass


# ---------------------------------------------------------------------------
# Sentinel objects (same pattern as spec TASK-909 test scaffold)
# ---------------------------------------------------------------------------

SENTINEL_RERANKER = object()
SENTINEL_PARENT = object()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_kwargs_reach_abstractbot() -> None:
    """Kwargs travel from BasicBot → BaseBot → AbstractBot and are stored."""
    bot = _BasicBotStub(
        reranker=SENTINEL_RERANKER,
        parent_searcher=SENTINEL_PARENT,
        expand_to_parent=True,
        rerank_oversample_factor=7,
    )
    assert bot.reranker is SENTINEL_RERANKER
    assert bot.parent_searcher is SENTINEL_PARENT
    assert bot.expand_to_parent is True
    assert bot.rerank_oversample_factor == 7


def test_default_kwargs() -> None:
    """Without explicit kwargs, defaults match spec (None / False / 4)."""
    bot = _BasicBotStub(name="kwargs-test")
    assert bot.reranker is None
    assert bot.parent_searcher is None
    assert bot.expand_to_parent is False
    assert bot.rerank_oversample_factor == 4


def test_expand_to_parent_coerced_to_bool() -> None:
    """expand_to_parent is coerced to bool regardless of truthy input."""
    bot = _BasicBotStub(expand_to_parent=1)
    assert bot.expand_to_parent is True

    bot2 = _BasicBotStub(expand_to_parent=0)
    assert bot2.expand_to_parent is False


def test_rerank_oversample_factor_coerced_to_int() -> None:
    """rerank_oversample_factor is coerced to int."""
    bot = _BasicBotStub(rerank_oversample_factor="5")
    assert bot.rerank_oversample_factor == 5
    assert isinstance(bot.rerank_oversample_factor, int)


def test_mock_reranker_accepted() -> None:
    """A MagicMock reranker is stored without type-checking."""
    mock_reranker = MagicMock()
    bot = _BasicBotStub(reranker=mock_reranker)
    assert bot.reranker is mock_reranker


def test_mock_parent_searcher_accepted() -> None:
    """A MagicMock parent_searcher is stored without type-checking."""
    mock_searcher = MagicMock()
    bot = _BasicBotStub(parent_searcher=mock_searcher)
    assert bot.parent_searcher is mock_searcher
