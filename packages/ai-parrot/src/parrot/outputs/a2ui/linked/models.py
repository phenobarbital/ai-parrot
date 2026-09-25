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


class TransformSpec(BaseModel):
    """Exactly one of inline DSL operations or a catalogued renderer module."""

    model_config = _CFG
    ops: list[TransformOp] | None = None
    ref: TransformRef | None = None

    @model_validator(mode="after")
    def _xor(self) -> TransformSpec:
        if (self.ops is None) == (self.ref is None):
            raise ValueError("TransformSpec requires exactly one of 'ops' or 'ref'")
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


class LinkedSources(RootModel[dict[str, LinkedDataSource]]):
    """Value of ``metadata.extensions['parrot_data_sources']`` keyed by data-model root."""

    @model_validator(mode="after")
    def _check_keys(self) -> LinkedSources:
        for key, source in self.root.items():
            target_key = source.target.split("/")[1].replace("~1", "/").replace("~0", "~")
            if not key.isidentifier() or target_key != key:
                raise ValueError(f"source key {key!r} must match target root token {target_key!r}")
        return self
