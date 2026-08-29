"""FEAT-223 Module 1: Shared structured-output base mixin.

Extracts the deterministic row-extraction + envelope-routing contract common to
all ``structured_*`` renderers (table, chart, map) into a single reusable mixin.

Inherit alongside ``BaseChart`` to adopt the contract without changing
``@register_renderer`` wiring::

    class StructuredTableRenderer(StructuredOutputBase, BaseChart):
        ...

FEAT-473 (Module 4, G1/G4): :meth:`_route_envelope` is the single hook point
where every STRUCTURED_* response ADDITIONALLY dual-emits a spec-conformant
A2UI v1.0 ``CreateSurface`` (via the core
:mod:`parrot.outputs.a2ui.adapters.structured` adapter) alongside its
existing ``response.output``/``response.data`` contract. This never changes
``out``/``explanation`` on failure — the a2ui dual-emit is wrapped in its own
try/except and any error is logged at ``warning``, leaving
``response.a2ui_envelope`` unset (``None``).
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

import pandas as pd

from ...models.outputs import (
    OutputMode,
    StructuredChartConfig,
    StructuredMapConfig,
    StructuredTableConfig,
)
from ...outputs.a2ui.adapters.structured import (
    DEFAULT_ROW_LIMIT as _A2UI_DEFAULT_ROW_LIMIT,
)
from ...outputs.a2ui.adapters.structured import (
    chart_to_surface,
    map_to_surface,
    table_to_surface,
)
from ...outputs.a2ui.serialization import serialize
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

    def _extract_rows(self, response: Any) -> pd.DataFrame | None:
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
            table_renderer: TableRenderer = getattr(self, "_table_renderer", None) or TableRenderer()
            df: pd.DataFrame | None = table_renderer._extract_data(response)
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
        explanation: str | None,
        *,
        layer_features: list | None = None,
        row_limit: int | None = None,
    ) -> tuple[dict | None, str | None]:
        """Apply the shared envelope contract to *cfg*.

        Serialises *cfg* to a dict (excluding the ``data`` key), routes
        ``cfg.data`` to ``response.data``, and returns ``(out, explanation)``
        as the ``wrapped`` pair consumed by the HTTP layer.

        FEAT-473 (G1/G4): after the above, additionally dual-emits a v1.0
        A2UI ``CreateSurface`` — see :meth:`_emit_a2ui_envelope`. This
        addition never affects the ``(out, explanation)`` return value on
        failure; only a successful dual-emit injects ``out["surfaceId"]``.

        Never raises.

        Args:
            response: AIMessage-like object; ``response.data`` is updated in-place.
            cfg: Pydantic model with a ``data`` field and a ``model_dump`` method
                (e.g. :class:`~parrot.models.outputs.StructuredTableConfig`).
            explanation: Prose explanation from the producing agent (may be ``None``).
            layer_features: STRUCTURED_MAP only — one feature-dict list per
                ``cfg.layers`` entry (never ``SpatialResult``), as built by
                :meth:`~parrot.outputs.formats.structured_map.StructuredMapRenderer._build_rows_payload`.
                Ignored for Chart/Table configs.
            row_limit: Row/feature cap for the a2ui data model. Defaults to
                ``self.row_limit`` (set by :class:`StructuredTableRenderer`)
                or the adapter's own default (1000) when absent.

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
        except Exception as exc:  # noqa: BLE001
            _logger.warning("StructuredOutputBase._route_envelope failed: %s", exc)
            return None, explanation

        self._emit_a2ui_envelope(response, cfg, out, layer_features=layer_features, row_limit=row_limit)
        return out, explanation

    def _emit_a2ui_envelope(
        self,
        response: Any,
        cfg: Any,
        out: dict,
        *,
        layer_features: list | None,
        row_limit: int | None,
    ) -> None:
        """Dual-emit a v1.0 A2UI ``CreateSurface`` alongside ``out``/``response.data``.

        Mints ``surface_id = f"{mode}-{uuid4().hex[:8]}"`` (the FEAT-224 id
        pattern), calls the matching core adapter
        (:mod:`parrot.outputs.a2ui.adapters.structured`), stores
        ``serialize(surface)`` on ``response.a2ui_envelope``, injects
        ``out["surfaceId"]``, and sets ``response.artifact_id``.

        Never raises: any exception (unknown ``cfg`` type, adapter
        validation failure, ...) is logged at ``warning`` and swallowed —
        ``response.a2ui_envelope`` is simply left unset (``None``), and
        ``response.output_mode`` is never touched.

        Args:
            response: AIMessage-like object, mutated in place on success.
            cfg: The structured config (``StructuredChartConfig``/
                ``StructuredTableConfig``/``StructuredMapConfig``).
            out: The dict already returned to the caller — ``surfaceId`` is
                injected into it in place on success.
            layer_features: STRUCTURED_MAP per-layer feature lists (see
                :meth:`_route_envelope`).
            row_limit: Row/feature cap override (see :meth:`_route_envelope`).
        """
        try:
            effective_row_limit = (
                row_limit if row_limit is not None else (getattr(self, "row_limit", None) or _A2UI_DEFAULT_ROW_LIMIT)
            )

            surface = None
            surface_id: str | None = None
            if isinstance(cfg, StructuredChartConfig):
                surface_id = f"{OutputMode.STRUCTURED_CHART.value}-{uuid.uuid4().hex[:8]}"
                surface = chart_to_surface(
                    cfg, list(cfg.data or []), surface_id=surface_id, row_limit=effective_row_limit
                )
            elif isinstance(cfg, StructuredTableConfig):
                surface_id = f"{OutputMode.STRUCTURED_TABLE.value}-{uuid.uuid4().hex[:8]}"
                surface = table_to_surface(
                    cfg, list(cfg.data or []), surface_id=surface_id, row_limit=effective_row_limit
                )
            elif isinstance(cfg, StructuredMapConfig):
                surface_id = f"{OutputMode.STRUCTURED_MAP.value}-{uuid.uuid4().hex[:8]}"
                surface = map_to_surface(
                    cfg, layer_features or [], surface_id=surface_id, row_limit=effective_row_limit
                )

            if surface is not None:
                response.a2ui_envelope = serialize(surface)
                out["surfaceId"] = surface_id
                response.artifact_id = surface_id
        except Exception as exc:  # noqa: BLE001
            _logger.warning("StructuredOutputBase._emit_a2ui_envelope failed: %s", exc)

    @staticmethod
    def _extract_json_code(content: str) -> str | None:
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
