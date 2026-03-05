"""
Paper Trading Mixin.

Provides paper-trading awareness to toolkit classes via mixin pattern.
Implements environment-based safety validation and mode properties.
"""

from __future__ import annotations

import os
from typing import Optional

from navconfig import config
from navconfig.logging import logging

from .models import ExecutionMode

# Development environment identifiers
_DEV_ENVIRONMENTS = frozenset({"development", "dev", "local", "test"})


class PaperTradingMixin:
    """Mixin for toolkits to add paper-trading awareness.

    Provides execution_mode, is_paper_trading, and validate_execution_mode
    methods. Designed to be mixed with AbstractToolkit subclasses without
    conflicting with its __init__ or MRO.
    """

    _execution_mode: ExecutionMode = ExecutionMode.PAPER

    # ------------------------------------------------------------------
    # Init helper (call from toolkit __init__)
    # ------------------------------------------------------------------

    def _init_paper_trading(
        self,
        mode: Optional[ExecutionMode] = None,
    ) -> None:
        """Initialize paper-trading state on the toolkit instance.

        Args:
            mode: Explicit execution mode. When *None*, reads from the
                ``PAPER_TRADING_MODE`` env var (via navconfig), falling
                back to ``ExecutionMode.PAPER``.
        """
        if mode is not None:
            self._execution_mode = mode
        else:
            env_mode = (
                config.get("PAPER_TRADING_MODE", fallback=None)
                or os.environ.get("PAPER_TRADING_MODE")
            )
            if env_mode is not None:
                try:
                    self._execution_mode = ExecutionMode(env_mode.strip().lower())
                except ValueError:
                    logging.warning(
                        "Invalid PAPER_TRADING_MODE=%r, defaulting to PAPER",
                        env_mode,
                    )
                    self._execution_mode = ExecutionMode.PAPER
            else:
                self._execution_mode = ExecutionMode.PAPER

        self.validate_execution_mode()
        logging.debug(
            "[PaperTradingMixin] execution_mode=%s for %s",
            self._execution_mode.value,
            type(self).__name__,
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def execution_mode(self) -> ExecutionMode:
        """Return the current execution mode."""
        return self._execution_mode

    @property
    def is_paper_trading(self) -> bool:
        """Return True when running in paper or dry-run mode."""
        return self._execution_mode in (ExecutionMode.PAPER, ExecutionMode.DRY_RUN)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_environment() -> str:
        """Detect the current deployment environment.

        Checks (in order): ``ENVIRONMENT`` env var, ``ENV`` env var,
        then ``parrot.conf.ENVIRONMENT`` (cached at import time),
        defaulting to ``development``.
        """
        # Prefer runtime env vars so callers (and tests) can override.
        env = os.environ.get("ENVIRONMENT") or os.environ.get("ENV")
        if env:
            return env.strip().lower()
        try:
            from parrot.conf import ENVIRONMENT  # noqa: WPS433
            return ENVIRONMENT.lower()
        except ImportError:
            return "development"

    def validate_execution_mode(self) -> None:
        """Raise RuntimeError if LIVE mode is used in a development environment.

        This is a safety gate: in dev/test environments, LIVE trading
        must be explicitly opt-in via setting ``fail_on_live_in_dev=False``
        in PaperTradingConfig.
        """
        if self._execution_mode != ExecutionMode.LIVE:
            return
        env = self._detect_environment()
        if env in _DEV_ENVIRONMENTS:
            raise RuntimeError(
                f"LIVE trading is not allowed in '{env}' environment. "
                f"Set PAPER_TRADING_MODE=paper or PAPER_TRADING_MODE=dry_run, "
                f"or deploy to a production environment."
            )
