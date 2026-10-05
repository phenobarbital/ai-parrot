"""Server-side Python transformers for linked sources (FEAT-636 M2).

One shared code path for every Python lane — executor bake/refresh, ``LinkedSurfaceService.fetch_source`` and
the toolkit build gate — so all lanes produce identical frames by construction. Transformers are resolved BY
REGISTERED NAME from ``transformer_registry`` (G1: never stored or dynamically imported code).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    import pandas as pd

    from parrot.outputs.a2ui.linked.models import PythonTransform

logger = logging.getLogger(__name__)

TRANSFORMER_NOT_REGISTERED = "transformer_not_registered"
TRANSFORM_FAILED = "transform_failed"
TRANSFORM_INVALID_OUTPUT = "transform_invalid_output"


class TransformStageError(Exception):
    """A transform-stage failure; ``code`` is a stable key of ``executor.ERROR_STATUS`` (all map to 422)."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def validate_python_transform(spec: "PythonTransform") -> list[str]:
    """Build/persist-time gate: registry membership + ``input_alias`` vs manifest. Never executes.

    Returns:
        Human-readable problems; an empty list means the spec passes.
    """
    from parrot.outputs.a2ui.recipes.transformers import transformer_registry

    try:
        registered = transformer_registry.get(spec.transformer)
    except KeyError as exc:
        return [str(exc)]
    aliases = list(registered.manifest.requires_columns)
    if len(aliases) > 1:
        return [f"multi-input transformer {spec.transformer!r} is not supported for linked sources in v1"]
    if len(aliases) == 1 and aliases[0] != spec.input_alias:
        return [f"transformer {spec.transformer!r} expects input alias {aliases[0]!r}; set python.input_alias"]
    return []


def select_output_frame(result: Any, output: str | None) -> "pd.DataFrame":
    """Reduce a transformer's returned dict to ONE frame (rule twin of ``fetch.ts::selectFrame``).

    ``output`` override → ``"result"`` key → sole key → ambiguous. The selected value must be a DataFrame
    or a list of row mappings.

    Raises:
        TransformStageError: ``transform_invalid_output`` on a non-mapping result, a missing/ambiguous key,
            or a value that is neither a DataFrame nor a list of mappings.
    """
    import pandas as pd

    if not isinstance(result, Mapping):
        raise TransformStageError(TRANSFORM_INVALID_OUTPUT, f"transformer returned {type(result).__name__}, not a dict")
    keys = sorted(result)
    if output is not None:
        if output not in result:
            raise TransformStageError(
                TRANSFORM_INVALID_OUTPUT,
                f"transformer output {output!r} is missing (available: {keys!r})",
            )
        selected = result[output]
    elif "result" in result:
        selected = result["result"]
    elif len(result) == 1:
        selected = next(iter(result.values()))
    else:
        raise TransformStageError(
            TRANSFORM_INVALID_OUTPUT,
            f"transformer returned multiple outputs ({keys!r}); specify output",
        )
    if isinstance(selected, pd.DataFrame):
        return selected
    if isinstance(selected, list) and all(isinstance(row, Mapping) for row in selected):
        return pd.DataFrame(selected)
    raise TransformStageError(TRANSFORM_INVALID_OUTPUT, "selected output is not a frame or a list of rows")


async def apply_python_transform(frame: "pd.DataFrame", spec: "PythonTransform", *, max_rows: int) -> "pd.DataFrame":
    """Run the registered transformer off-thread on ``{spec.input_alias: frame}`` and cap the result.

    Raises:
        TransformStageError: ``transformer_not_registered`` | ``transform_failed`` | ``transform_invalid_output``.
    """
    from parrot.outputs.a2ui.recipes.transformers import transformer_registry

    try:
        registered = transformer_registry.get(spec.transformer)
    except KeyError as exc:
        raise TransformStageError(TRANSFORMER_NOT_REGISTERED, str(exc)) from exc
    try:
        result = await asyncio.to_thread(registered, {spec.input_alias: frame}, dict(spec.params))
    except Exception as exc:  # noqa: BLE001 — any transformer failure is transform-stage (S7)
        raise TransformStageError(TRANSFORM_FAILED, f"{spec.transformer}: {exc}") from exc
    out = select_output_frame(result, spec.output)
    if len(out) > max_rows:
        logger.warning("python transformer %r produced %d rows; capped at %d", spec.transformer, len(out), max_rows)
        out = out.head(max_rows)
    return out
