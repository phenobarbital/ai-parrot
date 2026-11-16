"""FEAT-880: DatasetManager support for self-governed data sources."""
from __future__ import annotations

import pandas as pd
import pytest

from parrot.tools.dataset_manager.sources.base import DataSource
from parrot.tools.dataset_manager.sources import (
    CompositeDataSource,
    InMemorySource,
    QuerySlugSource,
    SQLQuerySource,
    TableSource,
)


class _GovernedSource(DataSource):
    """Minimal self-governed source: records fetch params, one frame per call."""

    def __init__(self, owner: str | None = "subject-a") -> None:
        super().__init__()
        self.name = "governed"
        self.owner = owner
        self.calls: list[dict] = []

    @property
    def self_governed(self) -> bool:
        return True

    @property
    def has_builtin_cache(self) -> bool:
        return True

    @property
    def cache_key(self) -> str:
        return "governed:test"

    def current_owner(self) -> str | None:
        return self.owner

    def describe(self) -> str:
        return "governed test source"

    async def fetch(self, **params) -> pd.DataFrame:
        self.calls.append(dict(params))
        return pd.DataFrame({"n": [len(self.calls)]})


_EXISTING_SOURCE_CLASSES = [
    InMemorySource,
    QuerySlugSource,
    SQLQuerySource,
    TableSource,
    CompositeDataSource,
]


def test_datasource_self_governed_default_false() -> None:
    """Every existing source reports self_governed == False."""
    source = InMemorySource(df=pd.DataFrame({"a": [1]}), name="mem")
    assert source.self_governed is False
    # Class-level check: no existing source overrides the base default, so every
    # instance inherits False without needing network access or credentials.
    for cls in _EXISTING_SOURCE_CLASSES:
        assert cls.self_governed is DataSource.self_governed, cls.__name__


@pytest.mark.parametrize("cls", _EXISTING_SOURCE_CLASSES, ids=lambda c: c.__name__)
def test_existing_sources_inherit_base_hooks(cls: type[DataSource]) -> None:
    """No existing source overrides either hook."""
    assert cls.self_governed is DataSource.self_governed
    assert cls.current_owner is DataSource.current_owner


def test_datasource_current_owner_default_none() -> None:
    """Every existing source returns None from current_owner()."""
    assert InMemorySource(df=pd.DataFrame({"a": [1]}), name="mem").current_owner() is None


def test_governed_double_contract() -> None:
    """The shared double declares both hooks."""
    source = _GovernedSource()
    assert source.self_governed is True
    assert source.current_owner() == "subject-a"


# ── M2a: DatasetManager self-governed branches (TASK-5516) ─────────────────

from parrot.tools.dataset_manager import DatasetManager  # noqa: E402


class _DeniedSource(_GovernedSource):
    """Self-governed double whose fetch is always denied for the current subject."""

    async def fetch(self, **params) -> pd.DataFrame:
        self.calls.append(dict(params))
        raise PermissionError("permission denied")


@pytest.mark.asyncio
async def test_materialize_always_refetches_self_governed() -> None:
    dm = DatasetManager(generate_guide=False)
    source = _GovernedSource()
    dm.add_source(source)
    await dm.materialize("governed", metrics=["a"])
    await dm.materialize("governed", metrics=["b"])
    assert source.calls == [{"metrics": ["a"]}, {"metrics": ["b"]}]


def test_make_source_skips_wrapper_for_self_governed() -> None:
    """A dataplane guard never wraps a self-governed source."""
    dm = DatasetManager(generate_guide=False, dataplane_guard=object())
    source = _GovernedSource()
    dm.add_source(source)
    assert dm._datasets["governed"].source is source


@pytest.mark.asyncio
async def test_materialize_skips_redis_for_self_governed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neither the Redis read nor the Redis write is reached for a self-governed source."""
    dm = DatasetManager(generate_guide=False)
    source = _GovernedSource()
    dm.add_source(source)

    async def _fail(*_args, **_kwargs):
        raise AssertionError("Redis layer must not be used for a self-governed source")

    monkeypatch.setattr(dm, "_get_cached_df", _fail)
    monkeypatch.setattr(dm, "_cache_df", _fail)
    await dm.materialize("governed", metrics=["a"])
    await dm.materialize("governed", metrics=["a"], force_refresh=True)
    assert len(source.calls) == 2
    # force_refresh is never forwarded to the source.
    assert all("force_refresh" not in call for call in source.calls)


@pytest.mark.asyncio
async def test_fetch_dataset_forwards_conditions() -> None:
    """``conditions`` become the fetch params; ``sql`` is ignored."""
    dm = DatasetManager(generate_guide=False)
    source = _GovernedSource()
    dm.add_source(source)
    conditions = {"metrics": ["revenue"], "dimensions": ["region"]}
    await dm.fetch_dataset("governed", sql="SELECT 1", conditions=conditions)
    assert source.calls[-1] == conditions


@pytest.mark.asyncio
async def test_fetch_dataset_denial_does_not_mark_unavailable() -> None:
    """A per-subject denial returns an error but leaves the shared entry available."""
    dm = DatasetManager(generate_guide=False)
    source = _DeniedSource()
    dm.add_source(source)
    result = await dm.fetch_dataset("governed", conditions={"metrics": ["a"]})
    assert result["success"] is False
    assert "permission denied" in result["error"]
    entry = dm._datasets["governed"]
    assert entry.unavailable_reason is None
    await dm.fetch_dataset("governed", conditions={"metrics": ["a"]})
    assert len(source.calls) == 2


# ── M2b: semantic metadata, completeness and runtime guidance (TASK-5517) ──


class _SemanticSource(_GovernedSource):
    """Self-governed double whose frames carry ``attrs["semantic"]`` metadata."""

    def __init__(self, rows: int, truncated: bool) -> None:
        super().__init__()
        self.rows = rows
        self.truncated = truncated

    async def fetch(self, **params) -> pd.DataFrame:
        self.calls.append(dict(params))
        df = pd.DataFrame({"region": [f"r{i}" for i in range(self.rows)], "revenue": range(self.rows)})
        df.attrs["semantic"] = {
            "model": "sales",
            "audit_id": "audit-1",
            "truncated": self.truncated,
            "row_count": self.rows,
            "extra": "must-not-leak",
        }
        return df


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("rows", "truncated", "inline", "complete"),
    [
        (3, False, True, True),
        (3, True, True, False),
        (600, False, False, False),
        (600, True, False, False),
    ],
)
async def test_fetch_dataset_semantic_response_completeness(
    rows: int, truncated: bool, inline: bool, complete: bool
) -> None:
    dm = DatasetManager(generate_guide=False)
    dm.add_source(_SemanticSource(rows=rows, truncated=truncated))
    result = await dm.fetch_dataset("governed", conditions={"metrics": ["revenue"]})
    assert result["status"] == "materialized"
    assert result["semantic"] == {
        "model": "sales",
        "audit_id": "audit-1",
        "truncated": truncated,
        "row_count": rows,
    }
    assert result["inline_complete"] is inline
    assert result["complete"] is complete
    warnings = result.get("warnings", [])
    truncation = [w for w in warnings if "TRUNCATED semantic result" in w]
    assert bool(truncation) is truncated
    if not inline:
        assert "FULL dataset" not in result["note"]
        assert "materialized result" in result["note"]


@pytest.mark.asyncio
async def test_fetch_dataset_ordinary_response_unchanged() -> None:
    """Frames without ``attrs["semantic"]`` get no semantic keys and the usual note."""
    dm = DatasetManager(generate_guide=False)
    dm.add_dataframe("plain", pd.DataFrame({"a": range(600), "b": range(600)}))
    result = await dm.fetch_dataset("plain")
    assert "semantic" not in result
    assert "inline_complete" not in result
    assert result["complete"] is False
    assert "FULL dataset" in result["note"]


def test_semantic_runtime_query_guidance() -> None:
    rules = DatasetManager(generate_guide=False).get_usage_rules()
    assert "Never re-fetch a loaded dataset" in rules
    assert "semantic datasets" in rules
    assert "call `fetch_dataset` again with new `conditions`" in rules
    doc = DatasetManager.fetch_dataset.__doc__
    assert "call fetch_dataset again with new ``conditions``" in doc
    for field in ("metrics", "dimensions", "time_dimensions", "filters", "order_by", "limit", "offset", "saved_query"):
        assert field in doc


# ── M7: per-subject frame slots on DatasetEntry (TASK-5518) ────────────────

from parrot.tools.dataset_manager import DatasetEntry  # noqa: E402
from parrot.tools.dataset_manager.tool import GOVERNED_FRAME_SLOTS  # noqa: E402


class _OwnerColumnSource(_GovernedSource):
    """Self-governed double whose frame has a column named after the fetching subject."""

    async def fetch(self, **params) -> pd.DataFrame:
        self.calls.append(dict(params))
        return pd.DataFrame({f"secret_{self.owner}": [len(self.calls)]})


@pytest.mark.asyncio
async def test_entry_frames_are_per_subject() -> None:
    source = _GovernedSource(owner="a")
    entry = DatasetEntry(name="governed", source=source)
    frame_a = await entry.materialize()
    assert entry.loaded and entry._df is frame_a
    assert entry.column_types is not None
    source.owner = "b"
    assert not entry.loaded
    assert entry._df is None and entry.column_types is None
    frame_b = await entry.materialize()
    assert frame_b is not frame_a
    source.owner = "a"
    assert entry._df is frame_a


@pytest.mark.asyncio
async def test_entry_no_owner_reads_unloaded_and_stores_nothing() -> None:
    source = _GovernedSource(owner=None)
    entry = DatasetEntry(name="governed", source=source)
    frame = await entry.materialize()
    assert isinstance(frame, pd.DataFrame) and len(frame) == 1
    assert not entry.loaded
    assert entry._column_types is None
    assert len(entry._frame_slots) == 0
    entry._column_types = {"n": "integer"}
    assert len(entry._frame_slots) == 0


@pytest.mark.asyncio
async def test_entry_slot_bound_lru() -> None:
    source = _GovernedSource(owner="s0")
    entry = DatasetEntry(name="governed", source=source)
    await entry.materialize()
    for i in range(1, GOVERNED_FRAME_SLOTS):
        source.owner = f"s{i}"
        await entry.materialize()
    # Touch s0 so it becomes most recently used; s1 is now the LRU slot.
    source.owner = "s0"
    assert entry.loaded
    source.owner = "overflow"
    await entry.materialize()
    assert len(entry._frame_slots) == GOVERNED_FRAME_SLOTS
    source.owner = "s1"
    assert not entry.loaded
    source.owner = "s0"
    assert entry.loaded


@pytest.mark.asyncio
async def test_entry_evict_only_callers_slot() -> None:
    source = _GovernedSource(owner="a")
    entry = DatasetEntry(name="governed", source=source)
    await entry.materialize()
    source.owner = "b"
    await entry.materialize()
    entry.evict()
    assert not entry.loaded
    source.owner = "a"
    assert entry.loaded
    assert entry.column_types is not None


@pytest.mark.asyncio
async def test_ordinary_entry_single_frame_unchanged() -> None:
    df = pd.DataFrame({"a": [1, 2]})
    entry = DatasetEntry(name="plain", df=df)
    assert entry._df is df
    assert entry.loaded and entry.column_types is not None
    assert len(entry._frame_slots) == 0
    replacement = pd.DataFrame({"b": [3]})
    entry._df = replacement
    assert entry._df is replacement and entry._frame is replacement
    entry.evict()
    assert not entry.loaded and entry._column_types is None
    returned = await entry.materialize()
    assert entry._df is returned


@pytest.mark.asyncio
async def test_manager_accessors_hide_other_subjects_frames() -> None:
    dm = DatasetManager(generate_guide=True)
    source = _OwnerColumnSource(owner="a")
    dm.add_source(source)
    await dm.materialize("governed")
    assert "governed" in dm.get_active_dataframes()
    assert "secret_a" in dm._generate_dataframe_guide()
    source.owner = "b"
    assert "governed" not in dm.get_active_dataframes()
    result = await dm.get_dataframe("governed")
    assert result["loaded"] is False
    assert "secret_a" not in dm._generate_dataframe_guide()


@pytest.mark.asyncio
async def test_pandas_sync_has_no_foreign_governed_frame() -> None:
    from parrot.tools.pythonpandas import PythonPandasTool

    dm = DatasetManager()
    source = _OwnerColumnSource(owner="a")
    dm.add_source(source)
    tool = PythonPandasTool(dataset_manager=dm)
    await dm.materialize("governed")
    tool.sync_from_manager()
    assert "governed" in tool.dataframes
    assert "secret_a" in tool.df_locals["governed"].columns
    source.owner = "b"
    tool.sync_from_manager()
    assert "governed" not in tool.dataframes
    for value in tool.df_locals.values():
        if isinstance(value, pd.DataFrame):
            assert "secret_a" not in value.columns
    for value in list(tool.locals.values()) + list(tool.globals.values()):
        if isinstance(value, pd.DataFrame):
            assert "secret_a" not in value.columns
