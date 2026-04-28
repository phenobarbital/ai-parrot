"""Factory for creating AbstractParentSearcher instances from a config dict.

This module resolves a JSONB ``parent_searcher_config`` dict (as stored in
``navigator.ai_bots``) into a concrete ``AbstractParentSearcher`` instance.
An empty dict means "no parent searcher" and returns ``None``.  Unknown
``type`` values raise ``ConfigError`` immediately (fail-loud, FEAT-133 G5).

The factory receives the bot's already-configured ``store`` as a kwarg because
``InTableParentSearcher.__init__`` requires the store.  This means the factory
MUST be called AFTER ``bot.configure(app)`` — see FEAT-133 spec §2 R1 and the
sequencing note in ``parrot/manager/manager.py``.

Usage::

    from parrot.stores.parents.factory import create_parent_searcher

    searcher = create_parent_searcher(
        {"type": "in_table", "expand_to_parent": True},
        store=bot.store,
    )
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable, Optional

from parrot.exceptions import ConfigError
from parrot.stores.parents.abstract import AbstractParentSearcher

if TYPE_CHECKING:
    from parrot.stores.abstract import AbstractStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal builder functions (lazy-imported heavy dependencies)
# ---------------------------------------------------------------------------


def _build_in_table(
    config: dict,
    store: Optional["AbstractStore"],
) -> AbstractParentSearcher:
    """Build an ``InTableParentSearcher`` from a config dict.

    Args:
        config: Parent searcher config dict (without the ``type`` key).
            The ``expand_to_parent`` key, if present, is consumed by the
            manager (forwarded as a bot constructor kwarg) and is NOT
            consumed here.
        store: The bot's already-configured store.  Must not be ``None``.

    Returns:
        An ``InTableParentSearcher`` instance bound to ``store``.

    Raises:
        ConfigError: If ``store`` is ``None``.
    """
    if store is None:
        raise ConfigError(
            "in_table parent searcher requires store; "
            "call create_parent_searcher() AFTER bot.configure(app)."
        )

    # Lazy import — keeps this module cheap and avoids circular deps.
    from parrot.stores.parents.in_table import InTableParentSearcher  # noqa: PLC0415

    return InTableParentSearcher(store=store)


# ---------------------------------------------------------------------------
# Registry — maps ``type`` discriminator to builder callable
# ---------------------------------------------------------------------------

PARENT_SEARCHER_TYPES: dict[
    str,
    Callable[[dict, Optional["AbstractStore"]], AbstractParentSearcher],
] = {
    "in_table": _build_in_table,
}


# ---------------------------------------------------------------------------
# Public factory function
# ---------------------------------------------------------------------------


def create_parent_searcher(
    config: dict,
    *,
    store: Optional["AbstractStore"],
) -> Optional[AbstractParentSearcher]:
    """Instantiate a parent searcher from a config dict.

    Args:
        config: Parent searcher config (from
            ``navigator.ai_bots.parent_searcher_config``). Empty dict
            returns ``None``.
        store: The bot's already-configured store; required for
            ``type=in_table`` because ``InTableParentSearcher`` queries the
            same table where chunks live.  Pass ``None`` only if you are
            certain no store-dependent type is used (empty config).

    Returns:
        The parent searcher instance, or ``None`` if config is empty.

    Raises:
        ConfigError: If ``config['type']`` is missing or unknown, or
            ``store`` is ``None`` when required by the chosen type.

    Examples:
        >>> create_parent_searcher({}, store=my_store)
        None
        >>> create_parent_searcher({"type": "in_table"}, store=my_store)
        <InTableParentSearcher ...>
    """
    if not config:
        logger.debug("parent_searcher_config is empty — no parent searcher will be used.")
        return None

    cfg = dict(config)  # shallow copy — do not mutate caller's dict

    searcher_type = cfg.pop("type", None)
    if searcher_type is None:
        raise ConfigError(
            "missing 'type' in parent_searcher_config; supported types: "
            + ", ".join(PARENT_SEARCHER_TYPES)
        )

    builder = PARENT_SEARCHER_TYPES.get(searcher_type)
    if builder is None:
        raise ConfigError(
            f"unknown parent searcher type '{searcher_type}'; supported: "
            + ", ".join(PARENT_SEARCHER_TYPES)
        )

    logger.debug("Creating parent searcher of type '%s'.", searcher_type)
    return builder(cfg, store)
