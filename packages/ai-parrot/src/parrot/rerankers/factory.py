"""Factory for creating AbstractReranker instances from a config dict.

This module resolves a JSONB ``reranker_config`` dict (as stored in
``navigator.ai_bots``) into a concrete ``AbstractReranker`` instance.
An empty dict means "no reranker" and returns ``None``.  Unknown ``type``
values raise ``ConfigError`` immediately (fail-loud, per FEAT-133 G5).

Lazy imports keep this module cheap to import — ``transformers`` / ``torch``
are never loaded unless ``type=local_cross_encoder`` is actually requested.

Usage::

    from parrot.rerankers.factory import create_reranker

    reranker = create_reranker({"type": "local_cross_encoder",
                                "model_name": "cross-encoder/ms-marco-MiniLM-L-6-v2",
                                "device": "cpu"})
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable, Optional

from parrot.exceptions import ConfigError
from parrot.rerankers.abstract import AbstractReranker

if TYPE_CHECKING:
    from parrot.clients.abstract_client import AbstractClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal builder functions (lazy-imported heavy dependencies)
# ---------------------------------------------------------------------------


def _build_local_cross_encoder(
    config: dict,
    bot_llm_client: Optional["AbstractClient"],  # noqa: F821 — not used here
) -> AbstractReranker:
    """Build a ``LocalCrossEncoderReranker`` from a config dict.

    Args:
        config: Reranker config dict (without the ``type`` key).
        bot_llm_client: Unused for this reranker type; accepted for
            API uniformity.

    Returns:
        A configured ``LocalCrossEncoderReranker`` instance.
    """
    # Lazy import to avoid pulling torch/transformers at module load time.
    from parrot.rerankers.local import LocalCrossEncoderReranker  # noqa: PLC0415

    return LocalCrossEncoderReranker(**config)


def _build_llm_reranker(
    config: dict,
    bot_llm_client: Optional["AbstractClient"],
) -> AbstractReranker:
    """Build an ``LLMReranker`` from a config dict.

    ``client=None`` is allowed here.  The manager patches the client
    post-configure (after ``bot.llm_client`` is available), so the guard
    lives in ``LLMReranker.rerank()`` rather than here.

    Args:
        config: Reranker config dict (without the ``type`` key).
            ``client_ref`` key is consumed here; remaining keys are forwarded.
        bot_llm_client: The bot's already-instantiated LLM client, reused
            when ``client_ref`` is ``"bot"`` (or absent).  May be ``None``
            when called before the bot's LLM client is configured.

    Returns:
        A configured ``LLMReranker`` instance (``client`` may be ``None``).

    Raises:
        ConfigError: If ``client_ref`` refers to an unsupported source.
    """
    # Lazy import to avoid unnecessary LLM client deps at import time.
    from parrot.rerankers.llm import LLMReranker  # noqa: PLC0415

    cfg = dict(config)  # shallow copy — do not mutate caller's dict
    client_ref = cfg.pop("client_ref", "bot")

    if client_ref == "bot" or client_ref is None:
        client = bot_llm_client
    else:
        raise ConfigError(
            f"client_ref='{client_ref}' is not yet supported; use 'bot'"
        )

    return LLMReranker(client=client, **cfg)


# ---------------------------------------------------------------------------
# Registry — maps ``type`` discriminator to builder callable
# ---------------------------------------------------------------------------

RERANKER_TYPES: dict[
    str,
    Callable[[dict, Optional["AbstractClient"]], AbstractReranker],
] = {
    "local_cross_encoder": _build_local_cross_encoder,
    "llm": _build_llm_reranker,
}


# ---------------------------------------------------------------------------
# Public factory function
# ---------------------------------------------------------------------------


def create_reranker(
    config: dict,
    *,
    bot_llm_client: Optional["AbstractClient"] = None,
) -> Optional[AbstractReranker]:
    """Instantiate a reranker from a config dict.

    Args:
        config: Reranker config (typically loaded from
            ``navigator.ai_bots.reranker_config``). An empty dict means
            "no reranker" and returns ``None``.
        bot_llm_client: Reused for ``type=llm`` when ``client_ref="bot"``
            (avoids a second LLM client instantiation).

    Returns:
        The reranker instance, or ``None`` if config is empty.

    Raises:
        ConfigError: If ``config['type']`` is missing or unknown, or if a
            required dependency (e.g. LLM client) is absent.

    Examples:
        >>> create_reranker({})
        None
        >>> create_reranker({"type": "local_cross_encoder",
        ...                   "model_name": "cross-encoder/ms-marco-MiniLM-L-6-v2",
        ...                   "device": "cpu"})  # doctest: +ELLIPSIS
        <parrot.rerankers.local.LocalCrossEncoderReranker object at 0x...>
    """
    if not config:
        logger.debug("reranker_config is empty — no reranker will be used.")
        return None

    cfg = dict(config)  # shallow copy — do not mutate caller's dict

    reranker_type = cfg.pop("type", None)
    if reranker_type is None:
        raise ConfigError(
            "missing 'type' in reranker_config; supported types: "
            + ", ".join(RERANKER_TYPES)
        )

    builder = RERANKER_TYPES.get(reranker_type)
    if builder is None:
        raise ConfigError(
            f"unknown reranker type '{reranker_type}'; supported: "
            + ", ".join(RERANKER_TYPES)
        )

    logger.debug("Creating reranker of type '%s'.", reranker_type)
    return builder(cfg, bot_llm_client)
