"""FEAT-223 Module 1: Shared structured-output base mixin.

Extracts the deterministic row-extraction + envelope-routing contract common to
all ``structured_*`` renderers (table, chart, map) into a single reusable mixin.

Inherit alongside ``BaseChart`` to adopt the contract without changing
``@register_renderer`` wiring::

    class StructuredTableRenderer(StructuredOutputBase, BaseChart):
        ...
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

import pandas as pd

from ...outputs.formats.table import TableRenderer


_logger = logging.getLogger(__name__)


class StructuredOutputBase:
    """Mixin providing the shared contract for all structured-output renderers.

    Concrete renderers (table, chart, map) inherit this alongside ``BaseChart``.
    The mixin never touches ``@register_renderer`` wiring or the ``BaseChart``
    abstract method — it only adds extraction and envelope helpers.

    Methods:
        _extract_rows: Deterministic DataFrame extraction; never raises.
        _route_envelope: Shared envelope contract; never raises.
        _extract_json_code: JSON extraction from fenced or bare text.
    """

    def _extract_rows(self, response: Any) -> Optional[pd.DataFrame]:
        """Extract a DataFrame from *response* via ``TableRenderer._extract_data``.

        Delegates to the same deterministic extraction call that every
        structured renderer needs.  Never raises — on any failure returns
        ``None`` so the caller can apply its own graceful-degradation path.

        Args:
            response: AIMessage-like object with ``data``, ``output``, etc.

        Returns:
            A non-empty :class:`~pandas.DataFrame` on success, ``None`` otherwise.
        """
        try:
            table_renderer: TableRenderer = (
                getattr(self, "_table_renderer", None) or TableRenderer()
            )
            df: Optional[pd.DataFrame] = table_renderer._extract_data(response)
            if df is None or df.empty:
                return None
            return df
        except Exception as exc:  # noqa: BLE001
            _logger.warning("StructuredOutputBase._extract_rows failed: %s", exc)
            return None

    def _route_envelope(
        self,
        response: Any,
        cfg: Any,
        explanation: Optional[str],
    ) -> tuple[Optional[dict], Optional[str]]:
        """Apply the shared envelope contract to *cfg*.

        Serialises *cfg* to a dict (excluding the ``data`` key), routes
        ``cfg.data`` to ``response.data``, and returns ``(out, explanation)``
        as the ``wrapped`` pair consumed by the HTTP layer.

        Never raises.

        Args:
            response: AIMessage-like object; ``response.data`` is updated in-place.
            cfg: Pydantic model with a ``data`` field and a ``model_dump`` method
                (e.g. :class:`~parrot.models.outputs.StructuredTableConfig`).
            explanation: Prose explanation from the producing agent (may be ``None``).

        Returns:
            ``(out_dict_without_data, explanation)`` on success, or
            ``(None, explanation)`` on any error.
        """
        try:
            out: dict = cfg.model_dump(mode="json", by_alias=True, exclude={"data"})
            # Explicit check to avoid DataFrame truthiness crash if response.data
            # still holds a pd.DataFrame at this point.
            if cfg.data:
                response.data = cfg.data
            return out, explanation
        except Exception as exc:  # noqa: BLE001
            _logger.warning("StructuredOutputBase._route_envelope failed: %s", exc)
            return None, explanation

    @staticmethod
    def _extract_json_code(content: str) -> Optional[str]:
        """Extract a JSON object string from markdown code blocks or bare text.

        Checks, in order:
        1. An explicit ``json`` code fence.
        2. A generic code fence whose content looks like JSON.
        3. Bare text that is already a JSON object.

        Args:
            content: Raw text that may contain embedded JSON.

        Returns:
            The extracted JSON string, or ``None`` if nothing suitable was found.
        """
        # 1. Explicit JSON code block
        pattern = r"```json\n(.*?)```"
        if matches := re.findall(pattern, content, re.DOTALL):
            return matches[0].strip()

        # 2. Generic code block — accept if it looks like JSON
        pattern = r"```\n(.*?)```"
        if matches := re.findall(pattern, content, re.DOTALL):
            potential = matches[0].strip()
            if potential.startswith("{") or potential.startswith("["):
                return potential

        # 3. Bare JSON
        content = content.strip()
        if content.startswith("{") and content.endswith("}"):
            return content

        return None
