"""SessionManager — BrowserContext lifecycle per session label.

Owns a single Playwright ``Browser`` and creates/caches/closes one
``BrowserContext`` per ``session`` label. Sessions sharing a label share
authentication state (cookies, storage); distinct labels are isolated.

Contexts are created lazily on first use and closed deterministically once the
last :class:`FlowNode` referencing a session has completed
(:meth:`close_if_last`), with :meth:`close_all` as a cleanup safety net
(FEAT-222, Module 7).
"""
from __future__ import annotations

import contextlib
import logging
from typing import Any, Dict, List, Optional

from .flow_models import FlowNode


class SessionManager:
    """Manage Playwright ``BrowserContext``s keyed by session label.

    Args:
        browser: A live Playwright ``Browser`` instance.
        default_context_kwargs: Keyword arguments applied to every context
            (viewport, locale, storage_state, proxy, …).
        session_configs: Optional per-session overrides merged on top of
            ``default_context_kwargs`` (e.g. a distinct ``storage_state`` for
            an authenticated session).
    """

    def __init__(
        self,
        browser: Any,
        default_context_kwargs: Optional[Dict[str, Any]] = None,
        session_configs: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> None:
        self._browser = browser
        self._default_context_kwargs = default_context_kwargs or {}
        self._session_configs = session_configs or {}
        self._contexts: Dict[str, Any] = {}
        self._last_use: Dict[str, str] = {}
        self.logger = logging.getLogger(__name__)

    async def get_context(self, session: str) -> Any:
        """Return the ``BrowserContext`` for *session*, creating it lazily.

        The first call for a label creates the context (merging
        ``default_context_kwargs`` with any per-session override); subsequent
        calls return the cached context.
        """
        if session in self._contexts:
            return self._contexts[session]

        kwargs = {
            **self._default_context_kwargs,
            **self._session_configs.get(session, {}),
        }
        context = await self._browser.new_context(**kwargs)
        self._contexts[session] = context
        self.logger.info("Created BrowserContext for session '%s'", session)
        return context

    async def new_page(self, session: str) -> Any:
        """Create and return a new ``Page`` within *session*'s context."""
        context = await self.get_context(session)
        return await context.new_page()

    def precompute_last_use(self, topo_order: List[FlowNode]) -> Dict[str, str]:
        """Record the last node id that uses each session, in topo order.

        Iterating in execution order means the final assignment per session
        is its last-used node — the point at which the context can be closed.

        Args:
            topo_order: Nodes in execution (topological) order.

        Returns:
            Mapping of ``session -> last node id``.
        """
        self._last_use = {}
        for node in topo_order:
            self._last_use[node.session] = node.id
        return dict(self._last_use)

    async def close_if_last(self, session: str, node_id: str) -> None:
        """Close *session*'s context if *node_id* was its last user.

        No-op when the session has more nodes pending or is unknown.
        """
        if self._last_use.get(session) != node_id:
            return
        context = self._contexts.pop(session, None)
        if context is not None:
            await context.close()
            self.logger.info(
                "Closed BrowserContext for session '%s' after node '%s'",
                session, node_id,
            )

    async def close_all(self) -> None:
        """Close every remaining context (cleanup safety net)."""
        for session, context in list(self._contexts.items()):
            with contextlib.suppress(Exception):
                await context.close()
            self.logger.debug("close_all: closed session '%s'", session)
        self._contexts.clear()
