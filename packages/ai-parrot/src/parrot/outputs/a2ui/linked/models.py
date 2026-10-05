"""Wire models of ``parrot_data_sources`` and the transform DSL v1 (FEAT-598)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, RootModel, StrictFloat, StrictInt, field_validator, model_validator

from parrot.outputs.a2ui.models import is_valid_pointer

_CFG = ConfigDict(extra="forbid", populate_by_name=True)
_REF_NAME_RE = re.compile(r"^[a-z0-9_-]+@\d+\.\d+\.\d+$")
MIN_INTERVAL_SECONDS = 30
Aggregate = Literal["sum", "avg", "count", "min", "max"]


class ParamSpec(BaseModel):
    """One user-editable query parameter (placeholder) of a source."""

    model_config = _CFG
    type: str | None = None
    default: Any = None
    required: bool = False
    editable: bool = True
    accepts_keywords: bool = False


class SourceRequest(BaseModel):
    """Canonical, structured condition representation (S5)."""

    model_config = _CFG
    placeholders: dict[str, Any] = Field(default_factory=dict)
    filter: dict[str, Any] = Field(default_factory=dict)
    fields: list[str] = Field(default_factory=list)
    ordering: list[str] = Field(default_factory=list)
    grouping: list[str] = Field(default_factory=list)
    limit: int | None = None
    offset: int | None = None


class RefreshPolicy(BaseModel):
    """Renderer refresh policy: ``on_mount``, ``manual``, or ``interval``."""

    model_config = _CFG
    policy: Literal["on_mount", "manual", "interval"] = "on_mount"
    interval_seconds: int | None = None

    @model_validator(mode="after")
    def _check_interval(self) -> RefreshPolicy:
        if self.policy == "interval" and (
            self.interval_seconds is None or self.interval_seconds < MIN_INTERVAL_SECONDS
        ):
            raise ValueError(f"interval policy requires interval_seconds >= {MIN_INTERVAL_SECONDS}")
        return self


class TransformRef(BaseModel):
    """Catalogued renderer-side transform: opaque ``name@semver`` id plus SRI pin."""

    model_config = _CFG
    name: str
    integrity: str

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        if not _REF_NAME_RE.match(value):
            raise ValueError(f"TransformRef.name {value!r} must match '<name>@<semver>' (never a URL)")
        return value

    @field_validator("integrity")
    @classmethod
    def _check_integrity(cls, value: str) -> str:
        if not value.startswith("sha384-"):
            raise ValueError("TransformRef.integrity must be a 'sha384-…' SRI hash")
        return value


class Select(BaseModel):
    model_config = _CFG
    op: Literal["select"] = "select"
    columns: list[str]


class Rename(BaseModel):
    model_config = _CFG
    op: Literal["rename"] = "rename"
    mapping: dict[str, str]


class Filter(BaseModel):
    model_config = _CFG
    op: Literal["filter"] = "filter"
    column: str
    operator: Literal["eq", "ne", "gt", "ge", "lt", "le", "in", "contains"]
    value: Any = None


class GroupBy(BaseModel):
    model_config = _CFG
    op: Literal["group_by"] = "group_by"
    by: list[str]
    aggregate: dict[str, Aggregate]


class SortKey(BaseModel):
    model_config = _CFG
    column: str
    direction: Literal["asc", "desc"] = "asc"


class Sort(BaseModel):
    model_config = _CFG
    op: Literal["sort"] = "sort"
    by: list[SortKey]


class Limit(BaseModel):
    model_config = _CFG
    op: Literal["limit"] = "limit"
    n: int = Field(ge=0)


class DeriveBinary(BaseModel):
    model_config = _CFG
    operator: Literal["+", "-", "*", "/"]
    left: DeriveOperand
    right: DeriveOperand


DeriveOperand = Union[DeriveBinary, StrictInt, StrictFloat, str]
DeriveBinary.model_rebuild()


class Derive(BaseModel):
    model_config = _CFG
    op: Literal["derive"] = "derive"
    name: str
    expr: DeriveOperand


class Pivot(BaseModel):
    model_config = _CFG
    op: Literal["pivot"] = "pivot"
    index: list[str]
    columns: str
    values: str
    aggregate: Aggregate = "sum"


class JoinKey(BaseModel):
    model_config = _CFG
    left: str
    right: str


class Join(BaseModel):
    model_config = _CFG
    op: Literal["join"] = "join"
    with_: str = Field(alias="with")
    how: Literal["inner", "left"] = "inner"
    on: list[JoinKey] = Field(min_length=1)


class Union_(BaseModel):
    model_config = _CFG
    op: Literal["union"] = "union"
    sources: list[str] = Field(min_length=1)


TransformOp = Annotated[
    Union[Select, Rename, Filter, GroupBy, Sort, Limit, Derive, Pivot, Join, Union_], Field(discriminator="op")
]


class PythonTransform(BaseModel):
    """Server-side registered transformer applied to a fetched frame (G1: referenced by name, never code).

    Runs ONLY in the Python lanes (bake, persist, server refresh, the per-source data endpoint) — the mirror
    image of ``transform.ref``, which runs only in the renderer.
    """

    model_config = _CFG
    transformer: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)
    input_alias: str = Field(default="source", min_length=1)
    output: str | None = None


class TransformSpec(BaseModel):
    """Exactly one of inline DSL operations, a catalogued renderer module, or a server-side Python transformer."""

    model_config = _CFG
    ops: list[TransformOp] | None = None
    ref: TransformRef | None = None
    python: PythonTransform | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def _xor(self) -> TransformSpec:
        if sum(member is not None for member in (self.ops, self.ref, self.python)) != 1:
            raise ValueError("TransformSpec requires exactly one of 'ops', 'ref' or 'python'")
        return self


class LinkedDataSource(BaseModel):
    """One data source of a linked surface (spec §2 Data Models)."""

    model_config = _CFG
    kind: Literal["query_slug"] = "query_slug"
    slug: str
    tenant: str | None = None
    is_multiquery: bool = False
    multi_output: str | None = None
    conditions: dict[str, Any]
    request: SourceRequest
    params: dict[str, ParamSpec] = Field(default_factory=dict)
    locked: list[str] = Field(default_factory=list)
    transform: TransformSpec | None = None
    target: str
    snapshot_at: datetime | None = None
    snapshot_truncated: bool = False
    refresh: RefreshPolicy = Field(default_factory=RefreshPolicy)

    @field_validator("target")
    @classmethod
    def _check_target(cls, value: str) -> str:
        if not value or not is_valid_pointer(value):
            raise ValueError(f"target {value!r} must be a non-empty absolute JSON pointer")
        return value

    @model_validator(mode="after")
    def _check_locked(self) -> LinkedDataSource:
        missing = [name for name in self.locked if name not in self.params]
        if missing:
            raise ValueError(f"locked parameter names are not declared in params: {missing}")
        return self


class DerivedDataSource(BaseModel):
    """A dashboard-owned view computed from a sibling source's frame — never fetched (linked dashboards).

    The base frame is the *full* fetched (and transformed) frame of ``from`` (bounded by ``max_fetch_rows``),
    not its ≤500-row snapshot; the derived rows are snapshotted like any other source so bake/HTML lanes see
    the computed view. Only inline ``transform.ops`` are allowed: a renderer-side ``ref`` cannot run in the
    Python executor, which would break Python ↔ renderer parity.
    """

    model_config = _CFG
    kind: Literal["derived"]
    from_: str = Field(alias="from")
    transform: TransformSpec
    target: str
    snapshot_at: datetime | None = None
    snapshot_truncated: bool = False

    @field_validator("target")
    @classmethod
    def _check_target(cls, value: str) -> str:
        if not value or not is_valid_pointer(value):
            raise ValueError(f"target {value!r} must be a non-empty absolute JSON pointer")
        return value

    @field_validator("from_")
    @classmethod
    def _check_from(cls, value: str) -> str:
        if not value.isidentifier():
            raise ValueError(f"from {value!r} must name a sibling source key (identifier)")
        return value

    @model_validator(mode="after")
    def _ops_only(self) -> DerivedDataSource:
        if self.transform.ref is not None or self.transform.python is not None or not self.transform.ops:
            raise ValueError(
                "a derived source requires inline transform.ops (transform.ref and transform.python are not allowed)"
            )
        return self


LinkedSource = Annotated[Union[LinkedDataSource, DerivedDataSource], Field(discriminator="kind")]


class LinkedSources(RootModel[dict[str, LinkedSource]]):
    """Value of ``metadata.extensions['parrot_data_sources']`` keyed by data-model root."""

    @model_validator(mode="before")
    @classmethod
    def _default_kind(cls, value: Any) -> Any:
        """Descriptors written before the ``derived`` kind existed carry no ``kind``: they are ``query_slug``.

        A kind-less descriptor that carries ``from`` can only be a derived view, so it is tagged as such — the
        validation error then names the derived shape instead of "from: extra forbidden".
        """
        if isinstance(value, dict):
            return {
                key: (
                    {"kind": "derived" if "from" in src else "query_slug", **src}
                    if isinstance(src, dict) and "kind" not in src
                    else src
                )
                for key, src in value.items()
            }
        return value

    @model_validator(mode="after")
    def _check_keys(self) -> LinkedSources:
        for key, source in self.root.items():
            target_key = source.target.split("/")[1].replace("~1", "/").replace("~0", "~")
            if not key.isidentifier() or target_key != key:
                raise ValueError(f"source key {key!r} must match target root token {target_key!r}")
        return self

    @model_validator(mode="after")
    def _python_terminal(self) -> LinkedSources:
        """A python-transformed source is terminal in v1 (FEAT-636 U3): no sibling may consume its frame."""
        python_keys = {
            key
            for key, src in self.root.items()
            if src.transform is not None and src.transform.python is not None
        }
        if not python_keys:
            return self
        for key, src in self.root.items():
            consumed = {src.from_} if isinstance(src, DerivedDataSource) else set()
            if src.transform is not None and src.transform.ops is not None:
                for operation in src.transform.ops:
                    if isinstance(operation, Join):
                        consumed.add(operation.with_)
                    elif isinstance(operation, Union_):
                        consumed.update(operation.sources)
            for name in consumed & python_keys:
                raise ValueError(
                    f"source {key!r} consumes python-transformed source {name!r}; python transforms are terminal"
                )
        return self
