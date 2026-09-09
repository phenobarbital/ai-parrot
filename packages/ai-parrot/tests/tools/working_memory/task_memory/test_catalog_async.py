"""Awaited catalog API and shared entry descriptors (FEAT-538 / TASK-2977).

Three required cases from the task's Test Specification:

- ``test_legacy`` — the synchronous catalog and mixed generic/DataFrame
  behaviour are unchanged when no backend is attached (AC13).
- ``test_awaited`` — enabled operations invoke the backend exactly once
  and propagate persistence failure **without publishing a phantom
  alias**.
- ``test_descriptor`` — descriptors are built from captured metadata and
  never call ``describe()``, ``compact_summary()`` or an arbitrary
  object's ``repr()``.

The "exactly once" and "never calls" assertions are the load-bearing
ones, and both are enforced with instrumented doubles rather than by
inspection: a descriptor projection that quietly called
``compact_summary()`` would still *look* correct in its output while
putting an arbitrary object's ``repr`` on recall's hot path.
"""

from __future__ import annotations

from typing import Any, List, Optional

import pandas as pd
import pytest
from parrot.tools.working_memory.internals import (
    CatalogEntry,
    CatalogNotEnabledError,
    EntryType,
    GenericEntry,
    ShapeLimit,
    SyncCatalogWriteError,
    VersionMetadata,
    WorkingMemoryCatalog,
)
from parrot.tools.working_memory.task_memory.artifacts import InMemoryArtifactStore
from parrot.tools.working_memory.task_memory.models import (
    ArtifactAvailability,
    ArtifactDescriptor,
    ArtifactKind,
    Attribution,
    EvidenceRef,
    TaskScope,
)

SCOPE = TaskScope(chatbot_id="bot-a", user_id="user-1", session_id="sess-1")
OTHER_SCOPE = TaskScope(chatbot_id="bot-a", user_id="user-2", session_id="sess-1")


def frame(rows: int = 3) -> pd.DataFrame:
    """Return a small deterministic DataFrame.

    Args:
        rows: Number of rows.

    Returns:
        A two-column frame.
    """
    return pd.DataFrame({"n": range(rows), "s": [f"r{i}" for i in range(rows)]})


@pytest.fixture()
def legacy() -> WorkingMemoryCatalog:
    """Return a catalog in the legacy configuration (no backend)."""
    return WorkingMemoryCatalog("sess-legacy")


@pytest.fixture()
def store() -> InMemoryArtifactStore:
    """Return a fresh artifact-store backend."""
    return InMemoryArtifactStore()


@pytest.fixture()
def enabled(store: InMemoryArtifactStore) -> WorkingMemoryCatalog:
    """Return a catalog with task memory enabled."""
    return WorkingMemoryCatalog("sess-enabled", backend=store, scope=SCOPE, task_id="t-1")


# ─────────────────────────────────────────────────────────────
# test_legacy
# ─────────────────────────────────────────────────────────────


def test_legacy_sync_writes_are_unchanged(legacy: WorkingMemoryCatalog) -> None:
    """Every synchronous operation behaves exactly as before (AC13)."""
    assert legacy.is_enabled is False
    assert legacy.backend is None
    assert legacy.scope is None

    entry = legacy.put(
        "df",
        frame(),
        description="raw",
        parent_keys=["src"],
        turn_id="turn-1",
    )
    assert isinstance(entry, CatalogEntry)
    assert entry.key == "df"
    assert entry.shape == (3, 2)
    assert entry.description == "raw"
    assert entry.parent_keys == ["src"]
    assert entry.turn_id == "turn-1"
    assert entry.session_id == "sess-legacy"
    assert entry.version_metadata is None

    generic = legacy.put_generic("txt", "hello", description="note", metadata={"a": 1})
    assert isinstance(generic, GenericEntry)
    assert generic.entry_type is EntryType.TEXT
    assert generic.metadata == {"a": 1}
    assert generic.version_metadata is None

    assert legacy.get("df") is entry
    assert "df" in legacy
    assert len(legacy) == 2
    assert legacy.keys() == ["df", "txt"]
    assert legacy.drop("txt") is True
    assert legacy.drop("txt") is False


def test_legacy_shared_namespace_still_replaces_across_types(legacy: WorkingMemoryCatalog) -> None:
    """Storing either type over an existing key still replaces it."""
    legacy.put("k", frame())
    assert isinstance(legacy.get("k"), CatalogEntry)
    legacy.put_generic("k", {"now": "generic"})
    assert isinstance(legacy.get("k"), GenericEntry)
    legacy.put("k", frame())
    assert isinstance(legacy.get("k"), CatalogEntry)
    assert len(legacy) == 1


def test_legacy_list_entries_mixes_both_types(legacy: WorkingMemoryCatalog) -> None:
    """Mixed summaries keep their existing shape, including entry_type."""
    legacy.put("df", frame(), turn_id="t1")
    legacy.put_generic("txt", "hello", turn_id="t1")
    legacy.put_generic("other", [1, 2, 3], turn_id="t2")

    summaries = legacy.list_entries(shape_limit=ShapeLimit(max_rows=2, max_cols=5))
    by_key = {s["key"]: s for s in summaries}
    assert by_key["df"]["entry_type"] == EntryType.DATAFRAME.value
    assert by_key["df"]["shape"] == {"rows": 3, "cols": 2}
    assert by_key["txt"]["entry_type"] == EntryType.TEXT.value
    assert by_key["other"]["entry_type"] == EntryType.JSON.value

    filtered = legacy.list_entries(turn_id="t2")
    assert [s["key"] for s in filtered] == ["other"]


def test_legacy_missing_key_error_message_is_unchanged(legacy: WorkingMemoryCatalog) -> None:
    """The KeyError text existing callers may match on is preserved."""
    legacy.put("df", frame())
    with pytest.raises(KeyError) as excinfo:
        legacy.get("nope")
    assert "not found. Available:" in str(excinfo.value)
    assert "df" in str(excinfo.value)


def test_legacy_entry_helpers_are_untouched(legacy: WorkingMemoryCatalog) -> None:
    """``shape``/``columns``/``dtypes_summary``/``compact_summary`` still work."""
    entry = legacy.put("df", frame())
    assert entry.shape == (3, 2)
    assert entry.columns == ["n", "s"]
    assert set(entry.dtypes_summary) == {"n", "s"}
    summary = entry.compact_summary()
    assert summary["key"] == "df"
    assert "preview" in summary and "memory_mb" in summary


def test_legacy_awaited_api_is_refused_without_a_backend(legacy: WorkingMemoryCatalog) -> None:
    """The awaited API is meaningless in the legacy configuration and says so."""
    import asyncio

    for coro in (
        legacy.aput("df", frame()),
        legacy.aput_generic("txt", "hello"),
        legacy.adrop("df"),
    ):
        with pytest.raises(CatalogNotEnabledError, match="legacy configuration"):
            asyncio.run(_drive(coro))


async def _drive(coro: Any) -> Any:
    """Await ``coro`` (a helper so sync tests can drive one).

    Args:
        coro: The coroutine to run.

    Returns:
        Whatever the coroutine returns.
    """
    return await coro


def test_legacy_backend_without_scope_is_rejected(store: InMemoryArtifactStore) -> None:
    """A versioned write with no scope could not be authorized on read back."""
    with pytest.raises(ValueError, match="requires a trusted scope"):
        WorkingMemoryCatalog("s", backend=store)


def test_legacy() -> None:
    """Required aggregate case: the synchronous catalog is unchanged."""
    catalog = WorkingMemoryCatalog("sess-legacy")
    test_legacy_sync_writes_are_unchanged(catalog)
    test_legacy_shared_namespace_still_replaces_across_types(WorkingMemoryCatalog("s2"))
    test_legacy_list_entries_mixes_both_types(WorkingMemoryCatalog("s3"))
    test_legacy_missing_key_error_message_is_unchanged(WorkingMemoryCatalog("s4"))
    test_legacy_entry_helpers_are_untouched(WorkingMemoryCatalog("s5"))


# ─────────────────────────────────────────────────────────────
# test_awaited
# ─────────────────────────────────────────────────────────────


class _CountingStore:
    """An ArtifactStore double that counts calls and can be made to fail.

    Deliberately minimal: this task's contract with the backend is
    ``put`` + ``drop_alias``, and counting is the point.
    """

    def __init__(self, *, fail_on: Optional[int] = None) -> None:
        """Initialize the double.

        Args:
            fail_on: 1-based call number of ``put`` that should raise.
        """
        self.put_calls: List[dict] = []
        self.drop_calls: List[dict] = []
        self._fail_on = fail_on
        self._counter = 0

    async def put(self, scope: TaskScope, key: str, value: Any, **kwargs: Any) -> ArtifactDescriptor:
        """Record the call and return a synthetic descriptor."""
        self._counter += 1
        self.put_calls.append({"scope": scope, "key": key, "value": value, **kwargs})
        if self._fail_on is not None and self._counter == self._fail_on:
            raise RuntimeError("backend write failed")
        return ArtifactDescriptor(
            ref=EvidenceRef(artifact_id=f"art-{key}", version=self._counter),
            alias=key,
            scope=scope,
            task_id=kwargs.get("task_id"),
            producer_call_id=kwargs.get("producer_call_id"),
            kind=ArtifactKind.JSON,
            availability=ArtifactAvailability.MEMORY,
        )

    async def drop_alias(self, scope: TaskScope, key: str, *, task_id: Optional[str] = None) -> bool:
        """Record the drop."""
        self.drop_calls.append({"scope": scope, "key": key, "task_id": task_id})
        return True


@pytest.mark.asyncio
async def test_awaited_invokes_the_backend_exactly_once(enabled: WorkingMemoryCatalog) -> None:
    """One awaited write is one backend write — never zero, never two."""
    counting = _CountingStore()
    catalog = WorkingMemoryCatalog("s", backend=counting, scope=SCOPE, task_id="t-1")

    await catalog.aput("df", frame(), description="d", turn_id="turn-1", producer_call_id="call-1")
    assert len(counting.put_calls) == 1
    call = counting.put_calls[0]
    assert call["key"] == "df"
    assert call["task_id"] == "t-1"
    assert call["turn_id"] == "turn-1"
    assert call["producer_call_id"] == "call-1"
    assert call["scope"].matches(SCOPE)

    await catalog.aput_generic("txt", {"a": 1})
    assert len(counting.put_calls) == 2

    await catalog.adrop("txt")
    assert len(counting.drop_calls) == 1
    assert counting.drop_calls[0]["key"] == "txt"


@pytest.mark.asyncio
async def test_awaited_failure_publishes_no_phantom_alias() -> None:
    """A failed backend write leaves the alias absent, not dangling.

    This is the reason the awaited path exists at all: an alias visible in
    the catalog with no committed artifact version behind it is phantom
    evidence, and a later reader would resolve it to nothing.
    """
    counting = _CountingStore(fail_on=1)
    catalog = WorkingMemoryCatalog("s", backend=counting, scope=SCOPE)

    with pytest.raises(RuntimeError, match="backend write failed"):
        await catalog.aput("df", frame())

    assert "df" not in catalog
    assert catalog.keys() == []
    assert len(catalog) == 0
    with pytest.raises(KeyError):
        catalog.get("df")


@pytest.mark.asyncio
async def test_awaited_failure_leaves_a_previous_version_intact() -> None:
    """A failed overwrite does not destroy the alias that was already there."""
    counting = _CountingStore(fail_on=2)
    catalog = WorkingMemoryCatalog("s", backend=counting, scope=SCOPE)

    first = await catalog.aput_generic("k", {"v": 1})
    assert catalog.get("k") is first

    with pytest.raises(RuntimeError):
        await catalog.aput_generic("k", {"v": 2})

    assert catalog.get("k") is first, "a failed overwrite must not disturb the published alias"
    assert catalog.get("k").data == {"v": 1}


@pytest.mark.asyncio
async def test_awaited_sync_writes_are_refused_when_enabled(enabled: WorkingMemoryCatalog) -> None:
    """Synchronous writes name the awaited replacement instead of degrading."""
    for method, call in (
        ("aput", lambda: enabled.put("df", frame())),
        ("aput_generic", lambda: enabled.put_generic("txt", "hello")),
        ("adrop", lambda: enabled.drop("df")),
    ):
        with pytest.raises(SyncCatalogWriteError) as excinfo:
            call()
        assert method in str(excinfo.value), f"the error must point at {method}()"

    # Nothing was written by the refused calls.
    assert catalog_is_empty(enabled)


def catalog_is_empty(catalog: WorkingMemoryCatalog) -> bool:
    """Return whether a catalog holds no entries.

    Args:
        catalog: The catalog to check.

    Returns:
        ``True`` when empty.
    """
    return len(catalog) == 0


@pytest.mark.asyncio
async def test_awaited_reads_stay_synchronous(enabled: WorkingMemoryCatalog) -> None:
    """``get``/``__contains__`` keep working — the plan node depends on them.

    ``PlanToolNode._read_key`` and ``_has_key`` reach into the catalog
    directly and synchronously. Refusing synchronous *reads* would break
    execution plans under an enabled catalog.
    """
    await enabled.aput("df", frame())

    assert enabled.get("df").key == "df"
    assert "df" in enabled
    assert enabled.keys() == ["df"]
    assert len(enabled) == 1
    assert enabled.list_entries()[0]["key"] == "df"
    assert (await enabled.aget("df")).key == "df"

    with pytest.raises(KeyError):
        await enabled.aget("missing")


@pytest.mark.asyncio
async def test_awaited_versions_increment_on_overwrite(enabled: WorkingMemoryCatalog) -> None:
    """An overwrite bumps the same identity's version and moves the alias."""
    first = await enabled.aput("sales", frame(2))
    second = await enabled.aput("sales", frame(5))

    d1, d2 = first.to_descriptor(), second.to_descriptor()
    assert d2.ref.artifact_id == d1.ref.artifact_id
    assert d2.ref.version == d1.ref.version + 1
    assert enabled.get("sales") is second


@pytest.mark.asyncio
async def test_awaited_generic_entries_are_versioned_too(enabled: WorkingMemoryCatalog) -> None:
    """Plan results and tee payloads are generic entries and must carry versions."""
    entry = await enabled.aput_generic("__tee__:x:1", {"payload": [1, 2, 3]}, description="tee")
    assert isinstance(entry, GenericEntry)
    assert entry.is_versioned
    descriptor = entry.to_descriptor()
    assert descriptor.alias == "__tee__:x:1"
    assert descriptor.kind is ArtifactKind.JSON


@pytest.mark.asyncio
async def test_awaited_drop_reaches_the_backend(enabled: WorkingMemoryCatalog, store: InMemoryArtifactStore) -> None:
    """Dropping an alias removes it locally and in the backend, keeping versions."""
    entry = await enabled.aput("sales", frame())
    ref = entry.to_descriptor().ref

    assert await enabled.adrop("sales") is True
    assert "sales" not in enabled
    assert await store.get_current(SCOPE, "sales", task_id="t-1") is None

    surviving = await store.get_version(SCOPE, ref, task_id="t-1")
    assert surviving is not None, "drop removes the alias, not the evidence behind it"


@pytest.mark.asyncio
async def test_awaited_scope_is_the_catalog_s_not_the_caller_s(store: InMemoryArtifactStore) -> None:
    """Writes are attributed to the catalog's trusted scope, and isolated by it."""
    mine = WorkingMemoryCatalog("a", backend=store, scope=SCOPE, task_id="t-1")
    theirs = WorkingMemoryCatalog("b", backend=store, scope=OTHER_SCOPE, task_id="t-1")

    await mine.aput_generic("k", {"owner": "mine"})
    await theirs.aput_generic("k", {"owner": "theirs"})

    mine_descriptor = mine.get("k").to_descriptor()
    theirs_descriptor = theirs.get("k").to_descriptor()
    assert mine_descriptor.scope.matches(SCOPE)
    assert theirs_descriptor.scope.matches(OTHER_SCOPE)
    assert mine_descriptor.ref.artifact_id != theirs_descriptor.ref.artifact_id


@pytest.mark.asyncio
async def test_awaited_concurrent_writes_agree_with_the_backend(enabled: WorkingMemoryCatalog) -> None:
    """Racing writes on one alias leave the catalog on the backend's latest version.

    The catalog lock spans the backend call precisely so the local alias
    cannot end up pointing at an older version than the backend's.
    """
    import asyncio

    await asyncio.gather(*(enabled.aput_generic("k", {"i": i}) for i in range(8)))

    published = enabled.get("k").to_descriptor()
    backend_current = await enabled.backend.get_current(SCOPE, "k", task_id="t-1")
    assert backend_current is not None
    assert published.ref == backend_current.ref
    assert published.ref.version == 8


@pytest.mark.asyncio
async def test_awaited_pin_for_is_only_forwarded_when_set() -> None:
    """``pin_for`` is an extension beyond the protocol, so it is not always sent."""
    counting = _CountingStore()
    catalog = WorkingMemoryCatalog("s", backend=counting, scope=SCOPE)

    await catalog.aput_generic("a", {"x": 1})
    assert "pin_for" not in counting.put_calls[0]

    await catalog.aput_generic("b", {"x": 2}, pin_for="t-9")
    assert counting.put_calls[1]["pin_for"] == "t-9"


@pytest.mark.asyncio
async def test_awaited() -> None:
    """Required aggregate case: one backend call, no phantom alias on failure."""
    store = InMemoryArtifactStore()
    catalog = WorkingMemoryCatalog("agg", backend=store, scope=SCOPE, task_id="t-1")
    await test_awaited_invokes_the_backend_exactly_once(catalog)
    await test_awaited_failure_publishes_no_phantom_alias()
    await test_awaited_failure_leaves_a_previous_version_intact()
    await test_awaited_sync_writes_are_refused_when_enabled(
        WorkingMemoryCatalog("agg2", backend=InMemoryArtifactStore(), scope=SCOPE)
    )
    await test_awaited_pin_for_is_only_forwarded_when_set()


# ─────────────────────────────────────────────────────────────
# test_descriptor
# ─────────────────────────────────────────────────────────────


class _ExplodingFrame(pd.DataFrame):
    """A DataFrame whose expensive summary methods must never be called."""

    @property
    def _constructor(self) -> Any:
        return _ExplodingFrame

    def describe(self, *args: Any, **kwargs: Any) -> Any:
        """Fail loudly — a descriptor must never summarize the payload."""
        raise AssertionError("to_descriptor() called DataFrame.describe()")

    def memory_usage(self, *args: Any, **kwargs: Any) -> Any:
        """Fail loudly — deep memory accounting is not a descriptor's job."""
        raise AssertionError("to_descriptor() called DataFrame.memory_usage()")


class _ExplodingValue:
    """A value whose ``repr`` must never be taken by a descriptor."""

    def __repr__(self) -> str:
        """Fail loudly — descriptors must not stringify arbitrary payloads."""
        raise AssertionError("to_descriptor() called repr() on the payload")


@pytest.mark.asyncio
async def test_descriptor_never_touches_the_payload(enabled: WorkingMemoryCatalog) -> None:
    """Projection reads captured metadata only — never the live value.

    Enforced with payloads that raise if the expensive paths are taken,
    rather than by reading the implementation: recall pages descriptors in
    bulk, so a projection that quietly called ``describe()`` would be
    correct-looking and ruinous.
    """
    entry = await enabled.aput_generic("opaque", {"safe": "metadata"})
    # Swap in a payload that explodes on repr AFTER registration, so only
    # the projection can trip it.
    entry.data = _ExplodingValue()

    descriptor = entry.to_descriptor()
    assert descriptor.alias == "opaque"
    assert descriptor.ref.version == 1


@pytest.mark.asyncio
async def test_descriptor_never_describes_a_dataframe(enabled: WorkingMemoryCatalog) -> None:
    """A DataFrame descriptor does not call describe()/memory_usage()."""
    entry = await enabled.aput("df", frame())
    entry.df = _ExplodingFrame(frame())

    descriptor = entry.to_descriptor()
    assert descriptor.alias == "df"
    assert descriptor.kind is ArtifactKind.DATAFRAME


@pytest.mark.asyncio
async def test_descriptor_uses_captured_not_live_metadata(enabled: WorkingMemoryCatalog) -> None:
    """A mutated frame does not retroactively change its captured shape.

    ``CatalogEntry.shape`` reads the live frame; ``captured_shape`` records
    what the fingerprint actually covered. Conflating them would let a
    mutated frame report a shape its evidence never described.
    """
    entry = await enabled.aput("df", frame(3))
    assert entry.version_metadata is not None
    assert entry.version_metadata.captured_shape == (3, 2)
    assert entry.shape == (3, 2)

    entry.df = frame(99)
    assert entry.shape == (99, 2), "the live property tracks the live frame"
    assert entry.to_descriptor().shape == (3, 2), "the descriptor keeps the captured shape"


@pytest.mark.asyncio
async def test_descriptor_carries_no_payload_field(enabled: WorkingMemoryCatalog) -> None:
    """A descriptor is metadata: it has no field that could hold rows."""
    entry = await enabled.aput("df", frame())
    dumped = entry.to_descriptor().model_dump()
    assert not {"data", "df", "rows", "payload", "preview", "numeric_stats"} & set(dumped)


@pytest.mark.asyncio
async def test_descriptor_projects_both_entry_types(enabled: WorkingMemoryCatalog) -> None:
    """CatalogEntry and GenericEntry both project, sharing one component."""
    df_entry = await enabled.aput("df", frame())
    generic_entry = await enabled.aput_generic("txt", "hello")

    assert isinstance(df_entry.version_metadata, VersionMetadata)
    assert isinstance(generic_entry.version_metadata, VersionMetadata)
    assert df_entry.to_descriptor().kind is ArtifactKind.DATAFRAME
    assert generic_entry.to_descriptor().kind is ArtifactKind.TEXT

    descriptors = {d.alias: d for d in enabled.descriptors()}
    assert set(descriptors) == {"df", "txt"}


def test_descriptor_skips_unversioned_entries(legacy: WorkingMemoryCatalog) -> None:
    """``descriptors()`` omits legacy entries instead of fabricating identities."""
    legacy.put("df", frame())
    legacy.put_generic("txt", "hello")
    assert legacy.descriptors() == []

    with pytest.raises(CatalogNotEnabledError, match="no version metadata"):
        legacy.get("df").to_descriptor()


@pytest.mark.asyncio
async def test_descriptor_reports_the_current_alias(enabled: WorkingMemoryCatalog) -> None:
    """The projection reports the entry's key, not a stale captured alias."""
    entry = await enabled.aput_generic("original", {"a": 1})
    assert entry.to_descriptor().alias == "original"

    entry.key = "renamed"
    assert entry.to_descriptor().alias == "renamed"


@pytest.mark.asyncio
async def test_descriptor_preserves_evidence_verifiability(enabled: WorkingMemoryCatalog) -> None:
    """Verifiability and fingerprints survive the projection unaltered."""
    supported = await enabled.aput("clean", frame())
    descriptor = supported.to_descriptor()
    assert descriptor.evidence_verifiable is True
    assert descriptor.fingerprint is not None
    assert descriptor.fingerprint_algorithm is not None

    nested = await enabled.aput(
        "nested",
        pd.DataFrame({"v": [1.0], "obj": pd.Series([{"a": 1}], dtype="object")}),
    )
    nested_descriptor = nested.to_descriptor()
    assert (
        nested_descriptor.evidence_verifiable is False
    ), "a nested-object frame can never be claimed as verifiable evidence"


@pytest.mark.asyncio
async def test_descriptor_round_trips(enabled: WorkingMemoryCatalog) -> None:
    """A projected descriptor serializes and validates like any other."""
    entry = await enabled.aput("df", frame())
    descriptor = entry.to_descriptor()
    assert ArtifactDescriptor.model_validate_json(descriptor.model_dump_json()) == descriptor
    assert entry.to_descriptor() == descriptor, "projection is deterministic"


def _fresh_enabled() -> WorkingMemoryCatalog:
    """Return a brand-new enabled catalog.

    Each aggregated sub-case gets its own, because several of them assert
    on the *whole* catalog's contents and would otherwise see entries left
    behind by the previous one.

    Returns:
        An empty enabled catalog.
    """
    return WorkingMemoryCatalog("agg", backend=InMemoryArtifactStore(), scope=SCOPE, task_id="t-1")


@pytest.mark.asyncio
async def test_descriptor() -> None:
    """Required aggregate case: descriptors use captured metadata only."""
    await test_descriptor_never_touches_the_payload(_fresh_enabled())
    await test_descriptor_never_describes_a_dataframe(_fresh_enabled())
    await test_descriptor_uses_captured_not_live_metadata(_fresh_enabled())
    await test_descriptor_carries_no_payload_field(_fresh_enabled())
    await test_descriptor_projects_both_entry_types(_fresh_enabled())
    test_descriptor_skips_unversioned_entries(WorkingMemoryCatalog("legacy-agg"))
    await test_descriptor_preserves_evidence_verifiability(_fresh_enabled())
    await test_descriptor_reports_the_current_alias(_fresh_enabled())
    await test_descriptor_round_trips(_fresh_enabled())
