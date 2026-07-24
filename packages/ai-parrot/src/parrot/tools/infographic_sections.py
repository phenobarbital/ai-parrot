"""Section descriptor contract and fail-fast validation gate (FEAT-326, Module 1).

The :class:`SectionDescriptor` is the machine-enforced spine of the DataAgent
Infographic feature: it declares *which* data fills *each* section of an
infographic template (hero cards, tables, KPIs, …) and is consumed by the
data-splice render mode, the authoring mixin, and recipe publication.

Validation is **fail-fast and aggregating** (spec G-3): rendering must never
start with unmet datasets/columns, and any error enumerates *every* deficit
in a single raise — the philosophy of FEAT-324's ``$bind`` cross-check.

None of these models store executable code (resolved brainstorm decision):
:class:`ProvenanceDescriptor` records datasets/params/section mapping and
snapshot timestamps only.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Mapping, Optional, Tuple

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Descriptor models
# ---------------------------------------------------------------------------

class SectionSpec(BaseModel):
    """One template section and the data that must fill it.

    Attributes:
        name: Human/LLM-facing section identifier (e.g. ``"hero-cards"``).
        target: Payload JSON-pointer (data-splice mode) or Jinja context key
            (jinja mode) that receives this section's assembled data.
        datasets: Required :class:`DatasetManager` aliases feeding this section.
        columns: Required columns per dataset alias (alias -> column names).
        shape: Declared shape of the assembled section data.
        hint: Optional semantic guidance for the LLM (never enforced).
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Section identifier, e.g. 'hero-cards'.")
    target: str = Field(
        ...,
        description="Payload JSON-pointer (data-splice) or Jinja context key.",
    )
    datasets: List[str] = Field(
        default_factory=list,
        description="Required DatasetManager aliases for this section.",
    )
    columns: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Required columns per dataset alias.",
    )
    shape: Literal["records", "scalar", "mapping", "table"] = Field(
        ...,
        description="Declared shape of the assembled section data.",
    )
    hint: Optional[str] = Field(
        default=None,
        description="Semantic guidance for the LLM (non-enforced).",
    )


class SectionDescriptor(BaseModel):
    """Machine-enforced contract: template + render mode + sections.

    Attributes:
        template: Registered template name this descriptor targets.
        mode: Render mode — ``"jinja"`` (context render) or ``"data-splice"``
            (JSON payload injected into a script-tag marker).
        splice_marker_id: HTML ``id`` of the ``<script type="application/json">``
            marker for data-splice mode (ignored for jinja mode).
        sections: The ordered list of section specs.
        params: Free-form descriptor-level parameters (e.g. snapshot date).
    """

    model_config = ConfigDict(extra="forbid")

    template: str = Field(..., description="Registered template name.")
    mode: Literal["jinja", "data-splice"] = Field(..., description="Render mode.")
    splice_marker_id: str = Field(
        default="report-data",
        description="Marker script-tag id for data-splice mode.",
    )
    sections: List[SectionSpec] = Field(
        default_factory=list,
        description="Ordered section specs.",
    )
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description="Descriptor-level parameters.",
    )


class ProvenanceDescriptor(BaseModel):
    """Returned with every tier-1 artifact.

    Records the datasets/params/section mapping and dataset snapshot
    timestamps so the artifact can be understood and (for recipes)
    re-generated. It NEVER stores python source code (resolved brainstorm
    decision — spec §2 Data Models / §5).

    Attributes:
        descriptor: The :class:`SectionDescriptor` that produced the artifact.
        dataset_snapshots: alias -> ISO-8601 snapshot timestamp of the data
            actually used.
        artifact_id: Identifier of the persisted artifact.
        tier: ``"one-shot"`` (ad-hoc REPL) or ``"recipe"`` (published).
        recipe_ref: ``(name, owner)`` when ``tier == "recipe"``.
    """

    model_config = ConfigDict(extra="forbid")

    descriptor: SectionDescriptor
    dataset_snapshots: Dict[str, str] = Field(default_factory=dict)
    artifact_id: str
    tier: Literal["one-shot", "recipe"]
    recipe_ref: Optional[Tuple[str, Optional[str]]] = None


class TransformerGap(BaseModel):
    """One unmapped section build found during ``publish_recipe()``.

    Attributes:
        section: The section whose build could not be mapped to a registered
            transformer.
        proposed_name: Suggested transformer name for a developer to register.
        suggested_source: Transformer source skeleton for HUMAN registration.
            Never executed (spec G1).
    """

    model_config = ConfigDict(extra="forbid")

    section: str
    proposed_name: str
    suggested_source: str


class GapReport(BaseModel):
    """Result of a partial-coverage ``publish_recipe()``.

    Attributes:
        gaps: The unmapped section builds (recipe is NOT saved when non-empty).
        covered: Sections already mappable to registered transformers.
    """

    model_config = ConfigDict(extra="forbid")

    gaps: List[TransformerGap] = Field(default_factory=list)
    covered: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Fail-fast validation gate
# ---------------------------------------------------------------------------

_SCALAR_TYPES = (str, int, float, bool)


def _resolve_target(payload: Dict[str, Any], target: str) -> Any:
    """Resolve a section ``target`` against an assembled payload dict.

    Supports both a plain context key (jinja mode) and an RFC-6901
    JSON-pointer (data-splice mode; a leading ``/`` denotes a pointer).

    Args:
        payload: The assembled payload dictionary.
        target: A context key or JSON-pointer.

    Returns:
        The resolved value.

    Raises:
        KeyError: If the target cannot be resolved in the payload.
    """
    if target.startswith("/"):
        node: Any = payload
        for raw_token in target.lstrip("/").split("/"):
            token = raw_token.replace("~1", "/").replace("~0", "~")
            if isinstance(node, dict) and token in node:
                node = node[token]
            elif isinstance(node, list) and token.isdigit() and int(token) < len(node):
                node = node[int(token)]
            else:
                raise KeyError(target)
        return node
    if isinstance(payload, dict) and target in payload:
        return payload[target]
    raise KeyError(target)


def _shape_matches(value: Any, shape: str) -> bool:
    """Return True when ``value`` satisfies the declared ``shape``."""
    if shape == "records":
        return isinstance(value, list) and all(isinstance(item, dict) for item in value)
    if shape == "scalar":
        # Reject containers and None; note bool is a subclass of int (allowed).
        return isinstance(value, _SCALAR_TYPES)
    if shape == "mapping":
        return isinstance(value, dict)
    if shape == "table":
        return isinstance(value, list) and all(isinstance(item, list) for item in value)
    return False


def validate_descriptor_datasets(
    descriptor: SectionDescriptor,
    dataset_manager: Any,
) -> None:
    """Fail-fast check that every section's datasets/columns exist.

    Aggregates ALL deficits (dataset-level and column-level, across every
    section) into a single :class:`InfographicValidationError`. Rendering
    must not proceed when this raises.

    Args:
        descriptor: The descriptor to validate.
        dataset_manager: A :class:`DatasetManager`-like object exposing
            ``get_dataset_entry(name)`` returning an entry with a ``columns``
            attribute (or ``None`` when the alias is unknown).

    Raises:
        InfographicValidationError: With code ``"sections_unmet"`` and a
            ``detail`` dict listing every unmet section.
    """
    # Lazy import to avoid a circular import with infographic_toolkit
    # (which imports SectionDescriptor from this module).
    from parrot.tools.infographic_toolkit import InfographicValidationError

    deficits: List[Dict[str, Any]] = []
    for section in descriptor.sections:
        missing_datasets: List[str] = []
        missing_columns: Dict[str, List[str]] = {}
        for alias in section.datasets:
            entry = dataset_manager.get_dataset_entry(alias)
            if entry is None:
                missing_datasets.append(alias)
                continue
            required_cols = section.columns.get(alias, [])
            if required_cols:
                available = set(getattr(entry, "columns", []) or [])
                missing = [col for col in required_cols if col not in available]
                if missing:
                    missing_columns[alias] = missing
        if missing_datasets or missing_columns:
            deficits.append(
                {
                    "section": section.name,
                    "missing_datasets": missing_datasets,
                    "missing_columns": missing_columns,
                }
            )
    if deficits:
        logger.error("SectionDescriptor validation failed: %s", deficits)
        raise InfographicValidationError("sections_unmet", {"sections": deficits})


def validate_payload_shape(
    descriptor: SectionDescriptor,
    payload: Dict[str, Any],
) -> None:
    """Fail-fast check that an assembled payload matches each section's shape.

    Aggregates every mismatch (missing target or wrong shape) into a single
    :class:`InfographicValidationError`.

    Args:
        descriptor: The descriptor whose sections declare the expected shapes.
        payload: The assembled payload to validate against the descriptor.

    Raises:
        InfographicValidationError: With code ``"payload_shape_mismatch"`` and
            a ``detail`` dict listing every offending section.
    """
    from parrot.tools.infographic_toolkit import InfographicValidationError

    deficits: List[Dict[str, Any]] = []
    for section in descriptor.sections:
        try:
            value = _resolve_target(payload, section.target)
        except KeyError:
            deficits.append(
                {
                    "section": section.name,
                    "target": section.target,
                    "expected_shape": section.shape,
                    "problem": "target_missing",
                }
            )
            continue
        if not _shape_matches(value, section.shape):
            deficits.append(
                {
                    "section": section.name,
                    "target": section.target,
                    "expected_shape": section.shape,
                    "actual_type": type(value).__name__,
                    "problem": "shape_mismatch",
                }
            )
    if deficits:
        logger.error("Payload shape validation failed: %s", deficits)
        raise InfographicValidationError("payload_shape_mismatch", {"sections": deficits})


# ---------------------------------------------------------------------------
# Ad-hoc dataset adapter (FEAT-327, Module 1)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _AdhocEntry:
    """Minimal duck-typed dataset entry satisfying the validation gate.

    Attributes:
        columns: Column names of the wrapped DataFrame.
    """

    columns: List[str] = field(default_factory=list)


class AdhocDatasetAdapter:
    """``DatasetManager``-shaped adapter over ad-hoc DataFrames.

    :func:`validate_descriptor_datasets` is duck-typed: it only requires a
    ``dataset_manager.get_dataset_entry(name)`` method returning an object
    with a ``.columns`` attribute (or ``None`` when the alias is unknown).
    This adapter satisfies that contract for two ad-hoc sources that are NOT
    backed by a real ``DatasetManager``:

    - the HTTP render endpoint's ``{name: DataFrame}`` payload dict, and
    - the in-process authoring path's REPL namespace (e.g.
      :class:`~parrot.tools.pythonpandas.PythonPandasTool` ``df_locals`` /
      ``locals_dict``), from which only ``pandas.DataFrame`` values are
      exposed as datasets — every other local is invisible to the gate and
      is never executed or evaluated.

    When a name exists in both ``frames`` and ``repl_locals``, ``frames``
    takes precedence.

    Attributes:
        frames: Explicit ``{name: DataFrame}`` mapping.
        repl_locals: A REPL namespace (e.g. ``locals()``) to scan for
            ``pandas.DataFrame`` values by name.
    """

    def __init__(
        self,
        frames: Optional[Mapping[str, "pd.DataFrame"]] = None,
        repl_locals: Optional[Mapping[str, Any]] = None,
    ) -> None:
        """Initialize the adapter over ad-hoc frames and/or REPL locals.

        Args:
            frames: Explicit ``{name: DataFrame}`` mapping. Takes precedence
                over ``repl_locals`` on name collision.
            repl_locals: A namespace (e.g. a REPL's ``locals()``) scanned for
                ``pandas.DataFrame`` values; non-DataFrame locals are ignored.
        """
        self._frames: Dict[str, pd.DataFrame] = dict(frames) if frames else {}
        self._repl_locals: Dict[str, Any] = dict(repl_locals) if repl_locals else {}

    def get_dataset_entry(self, name: str) -> Optional[_AdhocEntry]:
        """Return a ``.columns``-exposing entry for ``name``, or ``None``.

        Args:
            name: Dataset alias to resolve.

        Returns:
            An :class:`_AdhocEntry` wrapping the DataFrame's columns, or
            ``None`` when ``name`` is not a known DataFrame in either
            ``frames`` or ``repl_locals``.
        """
        frame = self._frames.get(name)
        if frame is None:
            candidate = self._repl_locals.get(name)
            if isinstance(candidate, pd.DataFrame):
                frame = candidate
        if frame is None:
            return None
        return _AdhocEntry(columns=list(frame.columns))


__all__ = (
    "SectionSpec",
    "SectionDescriptor",
    "ProvenanceDescriptor",
    "TransformerGap",
    "GapReport",
    "validate_descriptor_datasets",
    "validate_payload_shape",
    "AdhocDatasetAdapter",
)
