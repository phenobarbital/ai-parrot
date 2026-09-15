"""Internal engine classes for WorkingMemoryToolkit.

Contains catalog storage, operation execution, and shape limiting components.
These are internal implementation details — consumers should use WorkingMemoryToolkit
from the package directly.

Two catalog configurations coexist (FEAT-538):

**Legacy (default).** No backend is attached. ``put``/``put_generic``/
``get``/``drop``/``list_entries`` behave exactly as they always have: a
plain dict, no locks, no versions, no I/O. Every existing caller — the
nine direct ``_catalog.put*`` sites in ``tool.py``, and
``bots/flows/plan/node.py``'s direct ``_catalog`` reads — is unaffected.

**Enabled (opt-in).** A :class:`~parrot.interfaces.artifact_store.ArtifactStore`
backend is attached, making the catalog *versioned and persistent*. Writes
then go through the awaited API (:meth:`WorkingMemoryCatalog.aput`,
:meth:`~WorkingMemoryCatalog.aput_generic`, :meth:`~WorkingMemoryCatalog.aget`,
:meth:`~WorkingMemoryCatalog.adrop`), and a *synchronous* write is refused
outright rather than being allowed to fire-and-forget the persistence half
or block the event loop. That refusal is deliberate: a sync ``put`` that
silently skipped the backend would publish an alias with no artifact
version behind it, which is precisely the phantom-evidence failure
versioning exists to prevent.

Reads stay synchronous in both configurations, because
``PlanToolNode._read_key`` / ``_has_key`` reach into the catalog directly
and must keep working.
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

import numpy as np
import pandas as pd

from .models import AggFunc, EntryType, FilterSpec, JoinHow, OperationSpecInput

if TYPE_CHECKING:  # pragma: no cover - typing only
    from datetime import datetime

    from parrot.interfaces.artifact_store import ArtifactStore
    from parrot.tools.working_memory.task_memory.models import (
        ArtifactAvailability,
        ArtifactDescriptor,
        ArtifactKind,
        Attribution,
        ReplBinding,
        TaskScope,
    )


# ─────────────────────────────────────────────────────────────
# Enabled-catalog errors
# ─────────────────────────────────────────────────────────────


class SyncCatalogWriteError(RuntimeError):
    """A synchronous write was attempted against an enabled catalog (FEAT-538).

    Raised by :meth:`WorkingMemoryCatalog.put`,
    :meth:`~WorkingMemoryCatalog.put_generic` and
    :meth:`~WorkingMemoryCatalog.drop` once an artifact-store backend is
    attached.

    The alternatives were both worse. Writing to the local dict and
    scheduling the backend write in the background would publish an alias
    with no committed artifact version behind it — a phantom alias, which
    is exactly the failure versioned evidence exists to rule out. Driving
    the coroutine to completion from a sync frame would block the event
    loop. So the call is refused, and the message names the awaited method
    to use instead.
    """


class CatalogNotEnabledError(RuntimeError):
    """An awaited catalog operation was used without a configured backend.

    The awaited API is meaningful only when a backend and a trusted scope
    are attached; without them there is no version to allocate and no
    scope to attribute the write to.
    """


# ─────────────────────────────────────────────────────────────
# Version metadata (shared by both entry types)
# ─────────────────────────────────────────────────────────────


@dataclass
class VersionMetadata:
    """Version and evidence facts captured when an entry was registered.

    Shared by :class:`CatalogEntry` **and** :class:`GenericEntry`. Both
    need it: plan node results and compression-tee payloads are stored as
    generic entries, so attaching versions only to the DataFrame entry
    would leave most of the catalog unversioned.

    Every field here is *captured at registration time* by the artifact
    store and then frozen. Nothing is recomputed from the live payload
    later, which is what lets :meth:`to_descriptor` stay cheap enough for
    recall's hot path — and what makes a descriptor describe the value as
    it was when its fingerprint was taken, rather than as it is now.

    ``captured_shape`` is deliberately a separate field rather than a
    reuse of :attr:`CatalogEntry.shape`. That property reads
    ``self.df.shape`` live; shadowing it would mean a mutated frame
    silently reported a shape its fingerprint never covered.

    Attributes:
        artifact_id: Stable identity allocated by the backend.
        version: 1-based version within that identity.
        scope: Trusted :class:`TaskScope` the write was attributed to.
        kind: Captured :class:`ArtifactKind`.
        availability: Captured :class:`ArtifactAvailability`.
        created_at: When this version was registered (UTC).
        task_id: Owning task, when one was selected.
        producer_call_id: Physical attempt that produced the value.
        attribution: How that attempt was attributed.
        fingerprint: Canonical content fingerprint, when computable.
        fingerprint_algorithm: Algorithm identity and version.
        evidence_verifiable: Whether the fingerprint actually proves
            content integrity.
        invalidated: Whether this version's evidence was invalidated.
        binding_invalid: Whether its REPL binding is stale.
        byte_size: Recorded payload size.
        captured_shape: Shape as captured, e.g. ``(rows, cols)``.
        schema_summary: Bounded captured schema description.
        storage_ref: Backend storage reference, when persisted.
        repl_binding: Current REPL binding, when one exists.
        invalidated_at: When it was invalidated, if it was.
    """

    artifact_id: str
    version: int
    scope: "TaskScope"
    kind: "ArtifactKind"
    availability: "ArtifactAvailability"
    created_at: "datetime"
    task_id: Optional[str] = None
    producer_call_id: Optional[str] = None
    attribution: Optional["Attribution"] = None
    fingerprint: Optional[str] = None
    fingerprint_algorithm: Optional[str] = None
    evidence_verifiable: bool = False
    invalidated: bool = False
    binding_invalid: bool = False
    byte_size: Optional[int] = None
    captured_shape: Optional[tuple[int, ...]] = None
    schema_summary: Optional[dict] = None
    storage_ref: Optional[str] = None
    repl_binding: Optional["ReplBinding"] = None
    invalidated_at: Optional["datetime"] = None

    @classmethod
    def from_descriptor(cls, descriptor: "ArtifactDescriptor") -> "VersionMetadata":
        """Capture the facts an entry keeps from a backend descriptor.

        Args:
            descriptor: What the artifact store returned for this write.

        Returns:
            The captured metadata.
        """
        return cls(
            artifact_id=descriptor.ref.artifact_id,
            version=descriptor.ref.version,
            scope=descriptor.scope,
            kind=descriptor.kind,
            availability=descriptor.availability,
            created_at=descriptor.created_at,
            task_id=descriptor.task_id,
            producer_call_id=descriptor.producer_call_id,
            attribution=descriptor.attribution,
            fingerprint=descriptor.fingerprint,
            fingerprint_algorithm=descriptor.fingerprint_algorithm,
            evidence_verifiable=descriptor.evidence_verifiable,
            invalidated=descriptor.invalidated,
            binding_invalid=descriptor.binding_invalid,
            byte_size=descriptor.byte_size,
            captured_shape=descriptor.shape,
            schema_summary=descriptor.schema_summary,
            storage_ref=descriptor.storage_ref,
            repl_binding=descriptor.repl_binding,
            invalidated_at=descriptor.invalidated_at,
        )

    def to_descriptor(self, *, alias: Optional[str] = None) -> "ArtifactDescriptor":
        """Rebuild the read projection from the captured facts.

        Args:
            alias: Current working-memory key. Passed by the owning entry
                so a renamed or dropped alias is reported truthfully.

        Returns:
            The :class:`ArtifactDescriptor` for this version.
        """
        # Imported lazily — see the note on `_artifact_descriptor_cls`.
        descriptor_cls = _artifact_descriptor_cls()
        evidence_ref_cls = _evidence_ref_cls()
        return descriptor_cls(
            ref=evidence_ref_cls(artifact_id=self.artifact_id, version=self.version),
            alias=alias,
            scope=self.scope,
            task_id=self.task_id,
            producer_call_id=self.producer_call_id,
            attribution=self.attribution if self.attribution is not None else _default_attribution(),
            kind=self.kind,
            availability=self.availability,
            fingerprint=self.fingerprint,
            fingerprint_algorithm=self.fingerprint_algorithm,
            evidence_verifiable=self.evidence_verifiable,
            invalidated=self.invalidated,
            binding_invalid=self.binding_invalid,
            byte_size=self.byte_size,
            shape=self.captured_shape,
            schema_summary=self.schema_summary,
            storage_ref=self.storage_ref,
            repl_binding=self.repl_binding,
            created_at=self.created_at,
            invalidated_at=self.invalidated_at,
        )


def _task_memory_models() -> Any:
    """Import the task-memory domain models lazily.

    ``internals.py`` is imported by ``tool.py``, which is imported by this
    package's ``__init__``. The task-memory models live *under* that same
    package, so importing them at module scope would make this module's
    import depend on its own package being further along in initialization
    than it is. Deferring the import to call time removes that ordering
    constraint entirely, and keeps the legacy configuration — which never
    builds a descriptor — from paying for the import at all.

    Returns:
        The ``parrot.tools.working_memory.task_memory.models`` module.
    """
    from parrot.tools.working_memory.task_memory import models as task_memory_models

    return task_memory_models


def _artifact_descriptor_cls() -> Any:
    """Return the :class:`ArtifactDescriptor` class (lazily imported)."""
    return _task_memory_models().ArtifactDescriptor


def _evidence_ref_cls() -> Any:
    """Return the ``EvidenceRef`` class (lazily imported)."""
    return _task_memory_models().EvidenceRef


def _default_attribution() -> Any:
    """Return ``Attribution.NONE`` (lazily imported)."""
    return _task_memory_models().Attribution.NONE


# ─────────────────────────────────────────────────────────────
# Type Detection Helper
# ─────────────────────────────────────────────────────────────


def _detect_entry_type(data: Any) -> EntryType:
    """Infer the EntryType for arbitrary Python data.

    Detection order (first match wins):
    - str  → TEXT
    - bytes → BINARY
    - dict | list → JSON
    - has both .content and .role attributes → MESSAGE
    - pd.DataFrame → DATAFRAME
    - anything else → OBJECT

    Args:
        data: The Python object to classify.

    Returns:
        The inferred EntryType enum value.
    """
    if isinstance(data, str):
        return EntryType.TEXT
    if isinstance(data, bytes):
        return EntryType.BINARY
    if isinstance(data, (dict, list)):
        return EntryType.JSON
    if hasattr(data, "content") and hasattr(data, "role"):
        return EntryType.MESSAGE
    if isinstance(data, pd.DataFrame):
        return EntryType.DATAFRAME
    return EntryType.OBJECT


# ─────────────────────────────────────────────────────────────
# GenericEntry
# ─────────────────────────────────────────────────────────────


@dataclass
class GenericEntry:
    """Catalog entry for non-DataFrame data.

    Stores arbitrary Python objects alongside type-specific metadata
    and provides a type-aware compact summary for the LLM context.

    Attributes:
        key: Unique identifier in the working memory catalog.
        data: The stored Python object (any type).
        entry_type: Discriminator describing the kind of data.
        created_at: Unix timestamp when this entry was created.
        description: Optional human-readable description.
        turn_id: Optional conversation turn identifier.
        session_id: Optional session identifier.
        metadata: Optional arbitrary user-defined metadata dict.
        version_metadata: Captured version/evidence metadata (FEAT-538).
            ``None`` in the legacy configuration, where entries are not
            versioned.
    """

    key: str
    data: Any
    entry_type: EntryType
    created_at: float = field(default_factory=time.time)
    description: str = ""
    turn_id: Optional[str] = None
    session_id: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    version_metadata: Optional[VersionMetadata] = None

    @property
    def is_versioned(self) -> bool:
        """Whether this entry was registered through the awaited API."""
        return self.version_metadata is not None

    def to_descriptor(self) -> "ArtifactDescriptor":
        """Project this entry's captured metadata as an artifact descriptor.

        Builds the descriptor purely from :attr:`version_metadata`. It
        never touches :attr:`data` — no ``compact_summary()``, no
        ``repr()``, no type introspection. Recall pages descriptors in
        bulk, so touching the payload would put an arbitrary object's
        ``repr`` on the hot path and risk leaking its contents into a
        listing that is supposed to be metadata only.

        Returns:
            The :class:`ArtifactDescriptor` for this entry's version.

        Raises:
            CatalogNotEnabledError: If the entry has no captured metadata,
                i.e. it was stored through the legacy synchronous path and
                therefore has no artifact identity to describe.
        """
        if self.version_metadata is None:
            raise CatalogNotEnabledError(
                f"entry {self.key!r} has no version metadata; it was stored through the "
                "legacy synchronous path and has no artifact version to describe"
            )
        return self.version_metadata.to_descriptor(alias=self.key)

    def compact_summary(self, max_length: int = 500) -> dict:
        """Return a type-aware compact summary suitable for the LLM context.

        Args:
            max_length: Maximum characters for text/content previews.

        Returns:
            A dict with entry metadata and type-specific preview fields.
        """
        base: dict[str, Any] = {
            "key": self.key,
            "entry_type": self.entry_type.value,
            "description": self.description,
        }
        if self.turn_id:
            base["turn_id"] = self.turn_id

        if self.entry_type == EntryType.TEXT:
            text: str = str(self.data)
            base["char_count"] = len(text)
            base["word_count"] = len(text.split())
            base["preview"] = text[:max_length] + ("..." if len(text) > max_length else "")

        elif self.entry_type == EntryType.JSON:
            if isinstance(self.data, dict):
                base["type"] = "dict"
                base["keys"] = list(self.data.keys())[:20]
            else:
                base["type"] = "list"
                base["length"] = len(self.data)
            try:
                raw = _json.dumps(self.data, default=str)
                base["preview"] = raw[:max_length] + ("..." if len(raw) > max_length else "")
            except Exception:
                base["preview"] = repr(self.data)[:max_length]

        elif self.entry_type == EntryType.MESSAGE:
            content = getattr(self.data, "content", "")
            role = getattr(self.data, "role", "unknown")
            content_str = str(content)
            base["role"] = role
            base["content_length"] = len(content_str)
            base["content_preview"] = content_str[:max_length] + ("..." if len(content_str) > max_length else "")

        elif self.entry_type == EntryType.BINARY:
            size = len(self.data)
            if size < 1024:
                size_human = f"{size} B"
            elif size < 1024**2:
                size_human = f"{size / 1024:.1f} KB"
            else:
                size_human = f"{size / 1024 ** 2:.1f} MB"
            base["size_bytes"] = size
            base["size_human"] = size_human
            # NOTE: no content dump for binary data

        elif self.entry_type == EntryType.OBJECT:
            base["type_name"] = type(self.data).__name__
            repr_str = repr(self.data)
            base["repr"] = repr_str[:max_length] + ("..." if len(repr_str) > max_length else "")
            base["attributes"] = [a for a in dir(self.data) if not a.startswith("_")][:20]

        else:
            # DATAFRAME fallback (should rarely reach here for GenericEntry)
            base["type_name"] = type(self.data).__name__

        return base


# ─────────────────────────────────────────────────────────────
# CatalogEntry
# ─────────────────────────────────────────────────────────────


@dataclass
class CatalogEntry:
    """Metadata and data container for a stored DataFrame in the catalog.

    Attributes:
        key: Unique identifier in the working memory catalog.
        df: The stored DataFrame.
        created_at: Unix timestamp when this entry was created.
        source_operation: Operation spec that produced it, when derived.
        parent_keys: Keys this entry was derived from.
        description: Optional human-readable description.
        error: Error state, when the entry represents a failure.
        turn_id: Optional conversation turn identifier.
        session_id: Optional session identifier.
        version_metadata: Captured version/evidence metadata (FEAT-538).
            ``None`` in the legacy configuration, where entries are not
            versioned.
    """

    key: str
    df: pd.DataFrame
    created_at: float = field(default_factory=time.time)
    source_operation: Optional[OperationSpecInput] = None
    parent_keys: list[str] = field(default_factory=list)
    description: str = ""
    error: Optional[str] = None
    turn_id: Optional[str] = None
    session_id: Optional[str] = None
    version_metadata: Optional[VersionMetadata] = None

    @property
    def shape(self) -> tuple[int, int]:
        """Return the shape of the stored DataFrame.

        This reads the **live** frame. It is intentionally left as-is and
        is *not* the same thing as
        :attr:`VersionMetadata.captured_shape`, which records the shape at
        the moment the fingerprint was taken. A mutated frame reports a
        new ``shape`` here while its captured shape — and the evidence
        that shape belongs to — stays fixed.
        """
        return self.df.shape

    @property
    def is_versioned(self) -> bool:
        """Whether this entry was registered through the awaited API."""
        return self.version_metadata is not None

    def to_descriptor(self) -> "ArtifactDescriptor":
        """Project this entry's captured metadata as an artifact descriptor.

        Builds the descriptor purely from :attr:`version_metadata`. It
        never touches :attr:`df` — no ``compact_summary()``, no
        ``describe()``, no ``memory_usage(deep=True)``. Those are
        expensive (``describe()`` scans every numeric column) and recall
        pages descriptors in bulk, so the projection has to be free of
        them to stay on the hot path at all.

        Returns:
            The :class:`ArtifactDescriptor` for this entry's version.

        Raises:
            CatalogNotEnabledError: If the entry has no captured metadata,
                i.e. it was stored through the legacy synchronous path and
                therefore has no artifact identity to describe.
        """
        if self.version_metadata is None:
            raise CatalogNotEnabledError(
                f"entry {self.key!r} has no version metadata; it was stored through the "
                "legacy synchronous path and has no artifact version to describe"
            )
        return self.version_metadata.to_descriptor(alias=self.key)

    @property
    def columns(self) -> list[str]:
        """Return column names of the stored DataFrame."""
        return list(self.df.columns)

    @property
    def dtypes_summary(self) -> dict[str, str]:
        """Return column dtypes as a string dictionary."""
        return {col: str(dtype) for col, dtype in self.df.dtypes.items()}

    def compact_summary(self, max_rows: int = 5, max_cols: int = 20) -> dict:
        """Return a token-efficient summary for the LLM context."""
        df = self.df
        summary: dict[str, Any] = {
            "key": self.key,
            "shape": {"rows": df.shape[0], "cols": df.shape[1]},
            "columns": self.columns[:max_cols],
            "dtypes": self.dtypes_summary,
        }
        if self.error:
            summary["error"] = self.error
            return summary

        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        if numeric_cols:
            stats = df[numeric_cols[:max_cols]].describe().to_dict()
            summary["numeric_stats"] = {
                col: {k: round(v, 4) if isinstance(v, float) else v for k, v in col_stats.items()}
                for col, col_stats in stats.items()
            }

        preview_df = df.head(max_rows)
        if df.shape[1] > max_cols:
            preview_df = preview_df.iloc[:, :max_cols]
        summary["preview"] = preview_df.to_dict(orient="records")
        summary["memory_mb"] = round(df.memory_usage(deep=True).sum() / 1e6, 2)

        if self.parent_keys:
            summary["derived_from"] = self.parent_keys

        return summary


# ─────────────────────────────────────────────────────────────
# OperationExecutor
# ─────────────────────────────────────────────────────────────


class OperationExecutor:
    """
    Executes OperationSpecInput against DataFrames from the catalog.

    Purely deterministic — no LLM calls, no free-form code execution.
    Each operation type is dispatched to a dedicated handler method.
    """

    AGG_MAP = {
        AggFunc.SUM: "sum",
        AggFunc.MEAN: "mean",
        AggFunc.MEDIAN: "median",
        AggFunc.MIN: "min",
        AggFunc.MAX: "max",
        AggFunc.COUNT: "count",
        AggFunc.STD: "std",
        AggFunc.VAR: "var",
        AggFunc.FIRST: "first",
        AggFunc.LAST: "last",
        AggFunc.NUNIQUE: "nunique",
    }

    FILTER_OPS = {
        "==": lambda s, v: s == v,
        "!=": lambda s, v: s != v,
        ">": lambda s, v: s > v,
        ">=": lambda s, v: s >= v,
        "<": lambda s, v: s < v,
        "<=": lambda s, v: s <= v,
        "in": lambda s, v: s.isin(v),
        "not_in": lambda s, v: ~s.isin(v),
        "contains": lambda s, v: s.astype(str).str.contains(str(v), na=False),
        "startswith": lambda s, v: s.astype(str).str.startswith(str(v)),
        "is_null": lambda s, v: s.isna(),
        "not_null": lambda s, v: s.notna(),
        "between": lambda s, v: s.between(v[0], v[1]),
    }

    def execute(
        self,
        spec: OperationSpecInput,
        catalog: dict[str, CatalogEntry],
    ) -> pd.DataFrame:
        """Dispatch the operation spec to the appropriate handler."""
        handler = getattr(self, f"_exec_{spec.op.value}", None)
        if handler is None:
            raise ValueError(f"Unsupported operation: {spec.op}")
        return handler(spec, catalog)

    def _get_df(self, key: str, catalog: dict[str, CatalogEntry]) -> pd.DataFrame:
        if key not in catalog:
            raise KeyError(f"DataFrame '{key}' not found in catalog. Available: {list(catalog.keys())}")
        entry = catalog[key]
        if entry.error:
            raise ValueError(f"DataFrame '{key}' has error state: {entry.error}")
        return entry.df

    def _apply_filters(self, df: pd.DataFrame, filters: list[FilterSpec]) -> pd.DataFrame:
        for f in filters:
            if f.column not in df.columns:
                raise KeyError(f"Column '{f.column}' not found. Available: {list(df.columns)}")
            if f.op not in self.FILTER_OPS:
                raise ValueError(f"Unknown filter op: '{f.op}'. Allowed: {list(self.FILTER_OPS.keys())}")
            mask = self.FILTER_OPS[f.op](df[f.column], f.value)
            df = df[mask]
        return df

    # ── Handlers ──

    def _exec_filter(self, spec: OperationSpecInput, catalog: dict[str, CatalogEntry]) -> pd.DataFrame:
        df = self._get_df(spec.source, catalog)
        return self._apply_filters(df, spec.filters)

    def _exec_aggregate(self, spec: OperationSpecInput, catalog: dict[str, CatalogEntry]) -> pd.DataFrame:
        df = self._get_df(spec.source, catalog)
        if spec.filters:
            df = self._apply_filters(df, spec.filters)
        agg_map = {col: self.AGG_MAP[func] for col, func in spec.agg_rules.items()}
        if spec.group_by:
            return df.groupby(spec.group_by, as_index=False).agg(agg_map)
        result = {col: df[col].agg(func_str) for col, func_str in agg_map.items()}
        return pd.DataFrame([result])

    def _exec_join(self, spec: OperationSpecInput, catalog: dict[str, CatalogEntry]) -> pd.DataFrame:
        left = self._get_df(spec.source, catalog)
        if not spec.right_source:
            raise ValueError("JOIN requires 'right_source'")
        right = self._get_df(spec.right_source, catalog)
        if spec.join_how == JoinHow.CROSS:
            return left.merge(right, how="cross")
        if not spec.join_on:
            raise ValueError("JOIN requires 'join_on' with 'left' and 'right' keys")
        return left.merge(
            right,
            left_on=spec.join_on.left,
            right_on=spec.join_on.right,
            how=spec.join_how.value,
        )

    def _exec_merge(self, spec: OperationSpecInput, catalog: dict[str, CatalogEntry]) -> pd.DataFrame:
        return self._exec_join(spec, catalog)

    def _exec_correlate(self, spec: OperationSpecInput, catalog: dict[str, CatalogEntry]) -> pd.DataFrame:
        df = self._get_df(spec.source, catalog)
        if spec.filters:
            df = self._apply_filters(df, spec.filters)
        cols = spec.columns if spec.columns else df.select_dtypes(include=[np.number]).columns.tolist()
        missing = [c for c in cols if c not in df.columns]
        if missing:
            raise KeyError(f"Columns not found for correlation: {missing}")
        corr_matrix = df[cols].corr(method=spec.method)
        return corr_matrix.reset_index().rename(columns={"index": "variable"})

    def _exec_group_correlate(self, spec: OperationSpecInput, catalog: dict[str, CatalogEntry]) -> pd.DataFrame:
        df = self._get_df(spec.source, catalog)
        if spec.filters:
            df = self._apply_filters(df, spec.filters)
        if not spec.group_by or len(spec.columns) < 2:
            raise ValueError("GROUP_CORRELATE requires group_by and at least 2 columns")
        results = []
        for name, group in df.groupby(spec.group_by):
            corr_val = group[spec.columns].corr(method=spec.method)
            row = {"_group": name}
            for i, c1 in enumerate(spec.columns):
                for c2 in spec.columns[i + 1 :]:
                    row[f"corr_{c1}__{c2}"] = corr_val.loc[c1, c2]
            results.append(row)
        return pd.DataFrame(results)

    def _exec_pivot(self, spec: OperationSpecInput, catalog: dict[str, CatalogEntry]) -> pd.DataFrame:
        df = self._get_df(spec.source, catalog)
        if spec.filters:
            df = self._apply_filters(df, spec.filters)
        return pd.pivot_table(
            df,
            index=spec.pivot_index,
            columns=spec.pivot_columns,
            values=spec.pivot_values,
            aggfunc=self.AGG_MAP[spec.pivot_aggfunc],
        ).reset_index()

    def _exec_rank(self, spec: OperationSpecInput, catalog: dict[str, CatalogEntry]) -> pd.DataFrame:
        df = self._get_df(spec.source, catalog).copy()
        if spec.filters:
            df = self._apply_filters(df, spec.filters)
        if not spec.rank_column:
            raise ValueError("RANK requires 'rank_column'")
        df["_rank"] = df[spec.rank_column].rank(ascending=spec.rank_ascending, method="min")
        return df.sort_values("_rank")

    def _exec_window(self, spec: OperationSpecInput, catalog: dict[str, CatalogEntry]) -> pd.DataFrame:
        df = self._get_df(spec.source, catalog).copy()
        if not spec.rank_column or not spec.window_size or not spec.window_func:
            raise ValueError("WINDOW requires 'rank_column', 'window_size', and 'window_func'")
        func_str = self.AGG_MAP[spec.window_func]
        col = spec.rank_column
        df[f"{col}_window_{func_str}_{spec.window_size}"] = (
            df[col].rolling(window=spec.window_size, min_periods=1).agg(func_str)
        )
        return df

    def _exec_sort(self, spec: OperationSpecInput, catalog: dict[str, CatalogEntry]) -> pd.DataFrame:
        df = self._get_df(spec.source, catalog)
        if not spec.sort_by:
            raise ValueError("SORT requires 'sort_by'")
        return df.sort_values(by=spec.sort_by, ascending=spec.sort_ascending)

    def _exec_select(self, spec: OperationSpecInput, catalog: dict[str, CatalogEntry]) -> pd.DataFrame:
        df = self._get_df(spec.source, catalog)
        if not spec.select_columns:
            raise ValueError("SELECT requires 'select_columns'")
        missing = [c for c in spec.select_columns if c not in df.columns]
        if missing:
            raise KeyError(f"Columns not found: {missing}")
        return df[spec.select_columns]

    def _exec_rename(self, spec: OperationSpecInput, catalog: dict[str, CatalogEntry]) -> pd.DataFrame:
        df = self._get_df(spec.source, catalog)
        return df.rename(columns=spec.rename_map)

    def _exec_fillna(self, spec: OperationSpecInput, catalog: dict[str, CatalogEntry]) -> pd.DataFrame:
        df = self._get_df(spec.source, catalog).copy()
        if spec.fillna_method:
            return df.fillna(method=spec.fillna_method)
        return df.fillna(spec.fillna_value if spec.fillna_value is not None else 0)

    def _exec_drop_duplicates(self, spec: OperationSpecInput, catalog: dict[str, CatalogEntry]) -> pd.DataFrame:
        df = self._get_df(spec.source, catalog)
        subset = spec.columns if spec.columns else None
        return df.drop_duplicates(subset=subset)

    def _exec_describe(self, spec: OperationSpecInput, catalog: dict[str, CatalogEntry]) -> pd.DataFrame:
        df = self._get_df(spec.source, catalog)
        if spec.columns:
            df = df[spec.columns]
        return df.describe(include="all").reset_index().rename(columns={"index": "stat"})


# ─────────────────────────────────────────────────────────────
# ShapeLimit
# ─────────────────────────────────────────────────────────────


@dataclass
class ShapeLimit:
    """Maximum shape constraint for summaries returned to the LLM."""

    max_rows: int = 10
    max_cols: int = 30


# ─────────────────────────────────────────────────────────────
# WorkingMemoryCatalog
# ─────────────────────────────────────────────────────────────


class WorkingMemoryCatalog:
    """In-memory catalog of DataFrames and generic entries.

    Session-scoped storage engine that supports both DataFrame-centric
    ``CatalogEntry`` objects and polymorphic ``GenericEntry`` objects.

    Key namespace is shared: storing either type with an existing key replaces
    the previous entry regardless of its type. This is intentional.

    With an artifact-store ``backend`` attached the catalog becomes
    versioned and persistent (FEAT-538): writes must use the awaited API,
    and each write allocates or increments an ``artifact_id@version``
    behind the alias. Without one, everything below behaves exactly as it
    always has.
    """

    def __init__(
        self,
        session_id: Optional[str] = None,
        *,
        backend: Optional["ArtifactStore"] = None,
        scope: Optional["TaskScope"] = None,
        task_id: Optional[str] = None,
    ) -> None:
        """Initialize the catalog.

        Args:
            session_id: Session identifier stamped on every entry.
                Defaults to a fresh uuid4, as before.
            backend: Optional artifact store. Attaching one enables the
                versioned, persistent configuration and makes synchronous
                writes an error.
            scope: Trusted runtime scope every enabled write is attributed
                to. Required whenever ``backend`` is given — a versioned
                write with no scope could not be authorized on read back.
            task_id: Default owning task for enabled writes. Individual
                calls may override it.

        Raises:
            ValueError: If a ``backend`` is given without a ``scope``.
        """
        self.session_id = session_id or str(uuid.uuid4())
        self._store: dict[str, CatalogEntry | GenericEntry] = {}
        self.logger = logging.getLogger(__name__)
        if backend is not None and scope is None:
            raise ValueError(
                "an enabled catalog requires a trusted scope: a versioned write with no "
                "scope could not be authorized when it is read back"
            )
        self._backend = backend
        self._scope = scope
        self.task_id = task_id
        #: Serializes catalog mutation. Held across the backend write so a
        #: race on one alias cannot leave the local dict pointing at an
        #: older version than the backend's alias. Never held across tool
        #: execution — the catalog does not call tools.
        self._lock = asyncio.Lock()

    # ── enabled-mode configuration ───────────────────────────────────

    @property
    def is_enabled(self) -> bool:
        """Whether a versioned, persistent backend is attached."""
        return self._backend is not None

    @property
    def backend(self) -> Optional["ArtifactStore"]:
        """The attached artifact store, or ``None`` in legacy mode."""
        return self._backend

    @property
    def scope(self) -> Optional["TaskScope"]:
        """The trusted scope enabled writes are attributed to."""
        return self._scope

    def _reject_sync_write(self, method: str, awaited: str) -> None:
        """Refuse a synchronous write against an enabled catalog.

        Args:
            method: The synchronous method that was called.
            awaited: The awaited method to use instead.

        Raises:
            SyncCatalogWriteError: Always, when a backend is attached.
        """
        if self._backend is None:
            return
        raise SyncCatalogWriteError(
            f"WorkingMemoryCatalog.{method}() is not available while task memory is "
            f"enabled: the write must be persisted and versioned before the alias is "
            f"published. Use `await catalog.{awaited}(...)` instead."
        )

    def _require_enabled(self, method: str) -> tuple["ArtifactStore", "TaskScope"]:
        """Return the backend and scope, or explain that there are none.

        Args:
            method: The awaited method that was called.

        Returns:
            The attached backend and trusted scope.

        Raises:
            CatalogNotEnabledError: If no backend is configured.
        """
        if self._backend is None or self._scope is None:
            raise CatalogNotEnabledError(
                f"WorkingMemoryCatalog.{method}() requires a configured artifact-store "
                "backend and scope; this catalog is in the legacy configuration"
            )
        return self._backend, self._scope

    def put(
        self,
        key: str,
        df: pd.DataFrame,
        *,
        operation: Optional[OperationSpecInput] = None,
        parent_keys: Optional[list[str]] = None,
        description: str = "",
        error: Optional[str] = None,
        turn_id: Optional[str] = None,
    ) -> CatalogEntry:
        """Store a DataFrame under the given key and return the catalog entry.

        Raises:
            SyncCatalogWriteError: If task memory is enabled. Use
                :meth:`aput` instead.
        """
        self._reject_sync_write("put", "aput")
        entry = CatalogEntry(
            key=key,
            df=df,
            source_operation=operation,
            parent_keys=parent_keys or [],
            description=description,
            error=error,
            turn_id=turn_id,
            session_id=self.session_id,
        )
        self._store[key] = entry
        self.logger.info("[WorkingMemory] Stored '%s' shape=%s", key, df.shape)
        return entry

    def put_generic(
        self,
        key: str,
        data: Any,
        *,
        entry_type: Optional[EntryType] = None,
        description: str = "",
        metadata: Optional[dict] = None,
        turn_id: Optional[str] = None,
    ) -> GenericEntry:
        """Store arbitrary data under the given key and return the GenericEntry.

        If ``entry_type`` is None the type is auto-detected via
        ``_detect_entry_type()``.  Storing with a key that already holds a
        ``CatalogEntry`` replaces it (intentional shared namespace).

        Args:
            key: Unique identifier for this entry.
            data: The Python object to store.
            entry_type: Explicit EntryType; auto-detected when None.
            description: Human-readable description.
            metadata: Optional user-defined metadata dict.
            turn_id: Optional conversation turn identifier.

        Returns:
            The newly created GenericEntry.

        Raises:
            SyncCatalogWriteError: If task memory is enabled. Use
                :meth:`aput_generic` instead.
        """
        self._reject_sync_write("put_generic", "aput_generic")
        resolved_type = entry_type if entry_type is not None else _detect_entry_type(data)
        entry = GenericEntry(
            key=key,
            data=data,
            entry_type=resolved_type,
            description=description,
            metadata=metadata or {},
            turn_id=turn_id,
            session_id=self.session_id,
        )
        self._store[key] = entry
        self.logger.info("[WorkingMemory] Stored generic '%s' type=%s", key, resolved_type.value)
        return entry

    def get(self, key: str) -> CatalogEntry | GenericEntry:
        """Retrieve a catalog entry by key."""
        if key not in self._store:
            raise KeyError(f"'{key}' not found. Available: {list(self._store.keys())}")
        return self._store[key]

    def drop(self, key: str) -> bool:
        """Remove an entry by key. Returns True if the key existed.

        Raises:
            SyncCatalogWriteError: If task memory is enabled. Use
                :meth:`adrop` instead — dropping an enabled alias has to
                reach the backend so the alias tombstone is recorded and
                the pinned versions behind it are preserved.
        """
        self._reject_sync_write("drop", "adrop")
        if key in self._store:
            del self._store[key]
            return True
        return False

    # ── awaited API (enabled task memory, FEAT-538) ──────────────────

    async def aput(
        self,
        key: str,
        df: pd.DataFrame,
        *,
        operation: Optional[OperationSpecInput] = None,
        parent_keys: Optional[list[str]] = None,
        description: str = "",
        error: Optional[str] = None,
        turn_id: Optional[str] = None,
        task_id: Optional[str] = None,
        producer_call_id: Optional[str] = None,
        attribution: Optional["Attribution"] = None,
        pin_for: Optional[str] = None,
    ) -> CatalogEntry:
        """Register a DataFrame with the backend, then publish its alias.

        The order is the whole point. The backend allocates the version
        and acknowledges the write **first**; only then does the alias
        appear in the local dict. If the backend raises, nothing is
        published — a caller that sees the alias can always resolve the
        artifact version behind it.

        Args:
            key: Alias to publish under.
            df: The DataFrame to store.
            operation: Operation spec that produced it, when derived.
            parent_keys: Keys it was derived from.
            description: Human-readable description.
            error: Error state, when the entry represents a failure.
            turn_id: Conversation turn identifier.
            task_id: Owning task; falls back to :attr:`task_id`.
            producer_call_id: Physical attempt that produced the value.
            attribution: How that attempt was attributed.
            pin_for: Task id to pin this version for, atomically with
                registration. Without it a newly registered version is an
                ordinary eviction candidate and can be evicted at birth.

        Returns:
            The published :class:`CatalogEntry`, carrying its captured
            :attr:`~CatalogEntry.version_metadata`.

        Raises:
            CatalogNotEnabledError: If no backend is configured.
        """
        backend, scope = self._require_enabled("aput")
        owning_task = task_id if task_id is not None else self.task_id

        async with self._lock:
            descriptor = await self._register(
                backend,
                scope,
                key,
                df,
                task_id=owning_task,
                description=description,
                producer_call_id=producer_call_id,
                attribution=attribution,
                turn_id=turn_id,
                pin_for=pin_for,
            )
            entry = CatalogEntry(
                key=key,
                df=df,
                source_operation=operation,
                parent_keys=parent_keys or [],
                description=description,
                error=error,
                turn_id=turn_id,
                session_id=self.session_id,
                version_metadata=VersionMetadata.from_descriptor(descriptor),
            )
            self._store[key] = entry

        self.logger.info(
            "[WorkingMemory] Stored '%s' shape=%s as %s@%s",
            key,
            df.shape,
            descriptor.ref.artifact_id,
            descriptor.ref.version,
        )
        return entry

    async def aput_generic(
        self,
        key: str,
        data: Any,
        *,
        entry_type: Optional[EntryType] = None,
        description: str = "",
        metadata: Optional[dict] = None,
        turn_id: Optional[str] = None,
        task_id: Optional[str] = None,
        producer_call_id: Optional[str] = None,
        attribution: Optional["Attribution"] = None,
        pin_for: Optional[str] = None,
    ) -> GenericEntry:
        """Register arbitrary data with the backend, then publish its alias.

        Same publish-after-acknowledgement ordering as :meth:`aput`. This
        is the path plan-node results and compression-tee payloads take,
        which is why generic entries carry version metadata too.

        Args:
            key: Alias to publish under.
            data: The Python object to store.
            entry_type: Explicit EntryType; auto-detected when ``None``.
            description: Human-readable description.
            metadata: User-defined metadata dict.
            turn_id: Conversation turn identifier.
            task_id: Owning task; falls back to :attr:`task_id`.
            producer_call_id: Physical attempt that produced the value.
            attribution: How that attempt was attributed.
            pin_for: Task id to pin this version for, atomically with
                registration.

        Returns:
            The published :class:`GenericEntry`, carrying its captured
            :attr:`~GenericEntry.version_metadata`.

        Raises:
            CatalogNotEnabledError: If no backend is configured.
        """
        backend, scope = self._require_enabled("aput_generic")
        owning_task = task_id if task_id is not None else self.task_id
        resolved_type = entry_type if entry_type is not None else _detect_entry_type(data)

        async with self._lock:
            descriptor = await self._register(
                backend,
                scope,
                key,
                data,
                task_id=owning_task,
                description=description,
                producer_call_id=producer_call_id,
                attribution=attribution,
                turn_id=turn_id,
                metadata=metadata,
                pin_for=pin_for,
            )
            entry = GenericEntry(
                key=key,
                data=data,
                entry_type=resolved_type,
                description=description,
                metadata=metadata or {},
                turn_id=turn_id,
                session_id=self.session_id,
                version_metadata=VersionMetadata.from_descriptor(descriptor),
            )
            self._store[key] = entry

        self.logger.info(
            "[WorkingMemory] Stored generic '%s' type=%s as %s@%s",
            key,
            resolved_type.value,
            descriptor.ref.artifact_id,
            descriptor.ref.version,
        )
        return entry

    async def _register(
        self,
        backend: "ArtifactStore",
        scope: "TaskScope",
        key: str,
        value: Any,
        *,
        task_id: Optional[str],
        description: str,
        producer_call_id: Optional[str],
        attribution: Optional["Attribution"],
        turn_id: Optional[str],
        metadata: Optional[dict] = None,
        pin_for: Optional[str] = None,
    ) -> "ArtifactDescriptor":
        """Call the backend exactly once and return its descriptor.

        Args:
            backend: The attached artifact store.
            scope: Trusted runtime scope.
            key: Alias being written.
            value: The payload.
            task_id: Owning task.
            description: Human-readable description.
            producer_call_id: Physical attempt that produced the value.
            attribution: How that attempt was attributed.
            turn_id: Conversation turn identifier.
            metadata: Caller metadata.
            pin_for: Task id to pin atomically with registration.

        Returns:
            The backend's :class:`ArtifactDescriptor`.
        """
        kwargs: dict[str, Any] = {
            "task_id": task_id,
            "description": description,
            "producer_call_id": producer_call_id,
            "turn_id": turn_id,
            "metadata": metadata,
        }
        # `attribution` and `pin_for` are omitted when unset rather than
        # passed as None. `attribution` has a meaningful backend-side
        # default, and `pin_for` is an extension beyond the ArtifactStore
        # protocol — forwarding it unconditionally would break a
        # protocol-conformant backend that does not accept it.
        if attribution is not None:
            kwargs["attribution"] = attribution
        if pin_for is not None:
            kwargs["pin_for"] = pin_for
        return await backend.put(scope, key, value, **kwargs)

    async def aget(self, key: str) -> CatalogEntry | GenericEntry:
        """Retrieve a catalog entry by key, under the catalog lock.

        Args:
            key: The alias to read.

        Returns:
            The stored entry.

        Raises:
            KeyError: If the key is not present — same message shape as
                the synchronous :meth:`get`.
        """
        async with self._lock:
            if key not in self._store:
                raise KeyError(f"'{key}' not found. Available: {list(self._store.keys())}")
            return self._store[key]

    async def adrop(self, key: str, *, task_id: Optional[str] = None) -> bool:
        """Drop a live alias through the backend, then locally.

        Dropping removes the **alias**, never the versions behind it.
        Pinned evidence survives, and the backend keeps an identity
        tombstone so a later re-registration cannot reuse a version
        number that some completed step still cites.

        Args:
            key: The alias to drop.
            task_id: Owning task namespace; falls back to :attr:`task_id`.

        Returns:
            ``True`` if the alias existed locally.

        Raises:
            CatalogNotEnabledError: If no backend is configured.
        """
        backend, scope = self._require_enabled("adrop")
        owning_task = task_id if task_id is not None else self.task_id

        async with self._lock:
            await backend.drop_alias(scope, key, task_id=owning_task)
            if key in self._store:
                del self._store[key]
                return True
            return False

    def descriptors(self) -> list["ArtifactDescriptor"]:
        """Project every versioned entry as an artifact descriptor.

        Legacy entries — those stored through the synchronous path, with
        no artifact identity — are skipped rather than fabricated.

        Returns:
            One descriptor per versioned entry, in insertion order.
        """
        return [entry.to_descriptor() for entry in self._store.values() if entry.version_metadata is not None]

    def list_entries(
        self,
        turn_id: Optional[str] = None,
        shape_limit: Optional[ShapeLimit] = None,
    ) -> list[dict]:
        """Return compact summaries of all stored entries, optionally filtered by turn_id.

        Handles both CatalogEntry (DataFrames) and GenericEntry objects.
        DataFrame entries always include ``"entry_type": "dataframe"`` for
        consistency with GenericEntry summaries.

        Args:
            turn_id: If provided, only entries with a matching turn_id are returned.
            shape_limit: Shape constraints for DataFrame previews.

        Returns:
            List of summary dicts, one per stored entry.
        """
        entries: list[CatalogEntry | GenericEntry] = list(self._store.values())
        if turn_id:
            entries = [e for e in entries if e.turn_id == turn_id]
        sl = shape_limit or ShapeLimit()
        summaries = []
        for e in entries:
            if isinstance(e, GenericEntry):
                summaries.append(e.compact_summary())
            else:
                # CatalogEntry — add entry_type for consistency
                summary = e.compact_summary(max_rows=sl.max_rows, max_cols=sl.max_cols)
                summary["entry_type"] = EntryType.DATAFRAME.value
                summaries.append(summary)
        return summaries

    def keys(self) -> list[str]:
        """Return all stored keys."""
        return list(self._store.keys())

    def __contains__(self, key: str) -> bool:
        return key in self._store

    def __len__(self) -> int:
        return len(self._store)
