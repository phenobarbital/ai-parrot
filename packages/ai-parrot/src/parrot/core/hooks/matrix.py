"""Matrix protocol hook for AutonomousOrchestrator.

This module is a thin compatibility shim.  The concrete ``MatrixHook``
implementation lives in the satellite package ``ai-parrot-integrations``
(``parrot.integrations.matrix.hook``) and self-registers with
:class:`~parrot.core.hooks.base.HookRegistry` when that package is
imported.

Usage
-----
Install ``ai-parrot-integrations[matrix]`` and import the hook module
to trigger self-registration::

    import parrot.integrations.matrix.hook  # auto-registers MatrixHook
    from parrot.core.hooks import MatrixHook  # resolved via HookRegistry

.. deprecated::
    Direct use of this module is discouraged.  Use the
    :class:`~parrot.core.hooks.base.HookRegistry` instead.
"""
from __future__ import annotations

import logging
from typing import Any

from navigator_eventbus.hooks.base import BaseHook, HookRegistry
from navigator_eventbus.hooks.models import HookType, MatrixHookConfig

logger = logging.getLogger("parrot.hooks.matrix")


class MatrixHook(BaseHook):
    """Compatibility shim for MatrixHook.

    Delegates lifecycle calls to the concrete implementation registered
    in :class:`~parrot.core.hooks.base.HookRegistry` under the key
    ``"matrix"``.

    If ``ai-parrot-integrations[matrix]`` is not installed, ``start()``
    raises :class:`ImportError` with installation guidance.

    Args:
        config: Matrix hook configuration.
        **kwargs: Extra keyword arguments forwarded to :class:`BaseHook`.
    """

    hook_type = HookType.MATRIX

    def __init__(self, config: MatrixHookConfig, **kwargs: Any) -> None:
        super().__init__(
            name=config.name,
            enabled=config.enabled,
            target_type=config.target_type,
            target_id=config.target_id,
            metadata=config.metadata,
            **kwargs,
        )
        self._config = config
        self._delegate: BaseHook | None = None

    def _get_delegate(self) -> BaseHook:
        """Return (or lazily create) the concrete hook implementation.

        Raises:
            ImportError: If ``ai-parrot-integrations[matrix]`` is not installed.
        """
        if self._delegate is not None:
            return self._delegate

        hook_cls = HookRegistry.get("matrix")
        if hook_cls is None:
            raise ImportError(
                "MatrixHook requires ai-parrot-integrations[matrix]. "
                "Install with: pip install ai-parrot-integrations[matrix]\n"
                "Then ensure the module is imported to trigger registration:\n"
                "    import parrot.integrations.matrix.hook"
            )
        self._delegate = hook_cls(config=self._config)
        if self._callback is not None:
            self._delegate.set_callback(self._callback)
        return self._delegate

    def set_callback(self, callback: Any) -> None:
        """Forward callback to delegate if already created."""
        super().set_callback(callback)
        if self._delegate is not None:
            self._delegate.set_callback(callback)

    async def start(self) -> None:
        """Start the concrete Matrix hook implementation."""
        await self._get_delegate().start()

    async def stop(self) -> None:
        """Stop the concrete Matrix hook implementation."""
        if self._delegate is not None:
            await self._delegate.stop()
            self._delegate = None

    async def send_reply(self, room_id: str, message: str) -> bool:
        """Forward send_reply to the concrete delegate if available.

        Args:
            room_id: Target Matrix room ID.
            message: Message text.

        Returns:
            True if the reply was sent, False otherwise.
        """
        if self._delegate is None:
            logger.warning("MatrixHook.send_reply called before start()")
            return False
        send_fn = getattr(self._delegate, "send_reply", None)
        if send_fn is None:
            return False
        return await send_fn(room_id, message)
