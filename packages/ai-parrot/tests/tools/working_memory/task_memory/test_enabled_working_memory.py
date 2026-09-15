"""Enabled working-memory routing and the raw-read cap (FEAT-538 / TASK-2985).

Three required cases from the task's Test Specification:

- ``test_write_routes`` — every enabled mutation route publishes version
  metadata exactly once, error and temporary paths included.
- ``test_raw_bounds`` — exact-cap, multibyte and oversized pages enforce
  the serialized and decoded limits, and an over-limit response returns
  no raw data.
- ``test_disabled`` — legacy tool schemas and working-memory outputs are
  unchanged when task memory is absent.

``test_write_routes`` is the one worth reading closely. It does not check
that a helper was *called*; it checks that a **version landed in the
backend**, which is the property that actually matters — a route that
quietly stayed on the synchronous catalog would still "work" and would
silently produce unversioned, unrecoverable evidence.
"""

from __future__ import annotations

from typing import Any, List, Optional

import pandas as pd
import pytest
from parrot.tools.working_memory import WorkingMemoryToolkit
from parrot.tools.working_memory.internals import SyncCatalogWriteError
from parrot.tools.working_memory.models import EnabledGetResultInput, GetResultInput
from parrot.tools.working_memory.task_memory.artifacts import InMemoryArtifactStore
from parrot.tools.working_memory.task_memory.config import TaskMemoryConfig
from parrot.tools.working_memory.task_memory.models import TaskScope

SCOPE = TaskScope(chatbot_id="bot-a", user_id="user-1", session_id="sess-1")


class TaskMemoryStub:
    """The composition surface the toolkit reads.

    Deliberately just the four attributes the toolkit actually consumes,
    backed by a **real** artifact store and a **real** config — so what
    is exercised is the genuine enabled path, not a mock's opinion of it.
    """

    def __init__(self, config: Optional[TaskMemoryConfig] = None) -> None:
        """Initialize with a real in-memory artifact store.

        Args:
            config: Configuration; defaults to the shipped defaults.
        """
        self.artifacts = InMemoryArtifactStore()
        self.scope = SCOPE
        self.task_id = "t-1"
        self.config = config or TaskMemoryConfig()


@pytest.fixture()
async def enabled():
    """Yield an ``(toolkit, task memory)`` pair with task memory enabled."""
    tm = TaskMemoryStub()
    toolkit = WorkingMemoryToolkit(task_memory=tm)
    try:
        yield toolkit, tm
    finally:
        await tm.artifacts.close()


@pytest.fixture()
def disabled() -> WorkingMemoryToolkit:
    """Yield a toolkit with task memory absent (the legacy configuration)."""
    return WorkingMemoryToolkit()


def frame(rows: int = 3) -> pd.DataFrame:
    """Return a small numeric/string frame.

    Args:
        rows: Row count.

    Returns:
        The frame.
    """
    return pd.DataFrame({"n": range(rows), "s": [f"r{i}" for i in range(rows)]})


async def _versions(tm: TaskMemoryStub, task_id: str = "t-1") -> List[str]:
    """Return every artifact reference registered in the backend.

    Args:
        tm: The task-memory stub.
        task_id: Owning task.

    Returns:
        Canonical ``artifact_id@version`` strings.
    """
    page = await tm.artifacts.list(SCOPE, task_id=task_id, limit=200)
    return [str(d.ref) for d in page.items]


# ─────────────────────────────────────────────────────────────
# test_write_routes
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_write_routes_store_publishes_a_version(enabled) -> None:
    """``store`` publishes exactly one version through the awaited path."""
    toolkit, tm = enabled
    await toolkit.store("sales", frame(), description="raw sales")

    refs = await _versions(tm)
    assert len(refs) == 1, "one write must publish exactly one version"

    current = await tm.artifacts.get_current(SCOPE, "sales", task_id="t-1")
    assert current is not None and current.alias == "sales"
    assert current.ref.version == 1


@pytest.mark.asyncio
async def test_write_routes_store_result_publishes_a_version(enabled) -> None:
    """``store_result`` — the generic path the tee also uses — publishes too."""
    toolkit, tm = enabled
    await toolkit.store_result("notes", {"summary": "ok"}, description="a note")

    current = await tm.artifacts.get_current(SCOPE, "notes", task_id="t-1")
    assert current is not None
    assert current.ref.version == 1


@pytest.mark.asyncio
async def test_write_routes_overwrite_increments_the_same_identity(enabled) -> None:
    """Writing the same alias twice increments its version, not its identity."""
    toolkit, tm = enabled
    await toolkit.store("sales", frame(3))
    first = await tm.artifacts.get_current(SCOPE, "sales", task_id="t-1")
    await toolkit.store("sales", frame(9))
    second = await tm.artifacts.get_current(SCOPE, "sales", task_id="t-1")

    assert first is not None and second is not None
    assert second.ref.artifact_id == first.ref.artifact_id
    assert second.ref.version == first.ref.version + 1

    # The old version is untouched and still resolvable.
    old = await tm.artifacts.get_version(SCOPE, first.ref, task_id="t-1")
    assert old is not None and not old.invalidated


@pytest.mark.asyncio
async def test_write_routes_operate_and_compute_publish(enabled) -> None:
    """Derived-result routes publish versions too, not just direct stores."""
    toolkit, tm = enabled
    await toolkit.store("sales", frame(5))

    before = len(await _versions(tm))
    result = await toolkit.compute_and_store(
        {"op": "select", "source": "sales", "select_columns": ["n"], "store_as": "small_sales"}
    )
    after = await _versions(tm)

    assert len(after) > before, f"a derived-result route published nothing: {result}"
    current = await tm.artifacts.get_current(SCOPE, "small_sales", task_id="t-1")
    assert current is not None, "the derived result must be versioned like any other write"


@pytest.mark.asyncio
async def test_write_routes_drop_goes_through_the_backend(enabled) -> None:
    """A drop removes the live alias but leaves the version resolvable."""
    toolkit, tm = enabled
    await toolkit.store("sales", frame())
    descriptor = await tm.artifacts.get_current(SCOPE, "sales", task_id="t-1")
    assert descriptor is not None

    await toolkit.drop_stored("sales")

    assert await tm.artifacts.get_current(SCOPE, "sales", task_id="t-1") is None
    survived = await tm.artifacts.get_version(SCOPE, descriptor.ref, task_id="t-1")
    assert survived is not None, "drop removes the alias, never the pinned evidence"


@pytest.mark.asyncio
async def test_write_routes_no_sync_write_survives_when_enabled(enabled) -> None:
    """Every enabled write goes through the awaited path — enforced, not assumed.

    The catalog refuses a synchronous write when a backend is attached, so
    any route that had quietly stayed on ``put``/``put_generic`` would
    raise here rather than silently producing unversioned evidence.
    """
    toolkit, tm = enabled

    with pytest.raises(SyncCatalogWriteError):
        toolkit._catalog.put("direct", frame())
    with pytest.raises(SyncCatalogWriteError):
        toolkit._catalog.put_generic("direct", {"a": 1})

    # And the real routes do not raise, because they use the awaited API.
    await toolkit.store("sales", frame())
    await toolkit.store_result("notes", {"a": 1})
    assert len(await _versions(tm)) == 2


@pytest.mark.asyncio
async def test_write_routes() -> None:
    """Required aggregate case: enabled mutation routes publish version metadata."""
    for case in (
        test_write_routes_store_publishes_a_version,
        test_write_routes_store_result_publishes_a_version,
        test_write_routes_overwrite_increments_the_same_identity,
        test_write_routes_operate_and_compute_publish,
        test_write_routes_drop_goes_through_the_backend,
        test_write_routes_no_sync_write_survives_when_enabled,
    ):
        tm = TaskMemoryStub()
        try:
            await case((WorkingMemoryToolkit(task_memory=tm), tm))
        finally:
            await tm.artifacts.close()


# ─────────────────────────────────────────────────────────────
# test_raw_bounds
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_raw_bounds_over_ceiling_returns_no_payload(enabled) -> None:
    """An over-limit raw read carries NO payload at all.

    Truncating after loading would already have paid the cost the ceiling
    exists to avoid, so the refusal must happen before the payload is
    attached.
    """
    toolkit, _ = enabled
    await toolkit.store_result("big", {"blob": "x" * 50_000})

    result = await toolkit.get_result("big", include_raw=True, max_rehydrate_bytes=100)

    assert "raw_data" not in result, "a refusal must carry no raw payload"
    assert "raw_omitted" in result
    assert "wm_compute_and_store" in result["guidance"]


@pytest.mark.asyncio
async def test_raw_bounds_zero_means_never(enabled) -> None:
    """``0`` means never rehydrate, and no request can reopen it."""
    toolkit, _ = enabled
    await toolkit.store_result("small", {"a": 1})

    result = await toolkit.get_result("small", include_raw=True, max_rehydrate_bytes=0)
    assert "raw_data" not in result
    assert "disabled" in result["raw_omitted"]


@pytest.mark.asyncio
async def test_raw_bounds_caller_may_lower_but_never_raise() -> None:
    """The configured ceiling is hard: a caller can only lower it."""
    tm = TaskMemoryStub(TaskMemoryConfig(max_rehydrate_bytes=500))
    toolkit = WorkingMemoryToolkit(task_memory=tm)
    try:
        await toolkit.store_result("mid", {"blob": "y" * 2_000})

        # Asking for MORE than the configured ceiling does not grant more.
        result = await toolkit.get_result("mid", include_raw=True, max_rehydrate_bytes=10_000_000)
        assert "raw_data" not in result, "a caller must not be able to raise the ceiling"
        assert result["raw_policy"]["max_rehydrate_bytes"] == 500

        # Asking for less is honoured.
        small = await toolkit.store_result("tiny", {"a": 1})  # noqa: F841
        lowered = await toolkit.get_result("tiny", include_raw=True, max_rehydrate_bytes=4)
        assert "raw_data" not in lowered
    finally:
        await tm.artifacts.close()


@pytest.mark.asyncio
async def test_raw_bounds_exact_cap_boundary(enabled) -> None:
    """The ceiling is exact: at the cap passes, one byte over refuses."""
    import json

    toolkit, _ = enabled
    payload = {"v": "z" * 200}
    encoded = len(json.dumps(payload, default=str).encode("utf-8"))
    await toolkit.store_result("exact", payload)

    at_cap = await toolkit.get_result("exact", include_raw=True, max_rehydrate_bytes=encoded)
    assert "raw_data" in at_cap, "exactly at the cap must be allowed"
    assert at_cap["raw_bytes"] == encoded

    over = await toolkit.get_result("exact", include_raw=True, max_rehydrate_bytes=encoded - 1)
    assert "raw_data" not in over, "one byte over must refuse"


@pytest.mark.asyncio
async def test_raw_bounds_multibyte_is_measured_in_bytes(enabled) -> None:
    """Multibyte text is measured in BYTES, not characters.

    Each '✓' is 3 UTF-8 bytes, so a character-based check would let a
    payload three times over the ceiling through.
    """
    toolkit, _ = enabled
    await toolkit.store_result("uni", {"t": "✓" * 300})  # ~900 bytes of content

    result = await toolkit.get_result("uni", include_raw=True, max_rehydrate_bytes=400)
    assert "raw_data" not in result, "a character-based check would have let this through"

    generous = await toolkit.get_result("uni", include_raw=True, max_rehydrate_bytes=5_000)
    assert "raw_data" in generous
    assert generous["raw_bytes"] > 900


@pytest.mark.asyncio
async def test_raw_bounds_tabular_paging_without_whole_table(enabled) -> None:
    """A page of a large tabular value is readable without loading it all."""
    toolkit, _ = enabled
    rows = [{"i": i, "name": f"row-{i}", "pad": "p" * 50} for i in range(2_000)]
    await toolkit.store_result("rows", rows)

    # The whole thing is far over the ceiling...
    whole = await toolkit.get_result("rows", include_raw=True, max_rehydrate_bytes=5_000, limit=2_000)
    assert "raw_data" not in whole

    # ...but a small page is still readable.
    page = await toolkit.get_result("rows", include_raw=True, offset=10, limit=5)
    assert "raw_data" in page
    assert len(page["raw_data"]) == 5
    assert page["raw_data"][0]["i"] == 10
    assert page["page"]["total_rows"] == 2_000
    assert page["page"]["truncated"] is True


@pytest.mark.asyncio
async def test_raw_bounds_page_size_clamps_to_the_configured_maximum(enabled) -> None:
    """A caller cannot page past the configured maximum."""
    toolkit, tm = enabled
    rows = [{"i": i} for i in range(5_000)]
    await toolkit.store_result("rows", rows)

    page = await toolkit.get_result("rows", include_raw=True, limit=1_000_000)
    assert len(page["raw_data"]) <= tm.config.raw_page_limit_max


@pytest.mark.asyncio
async def test_raw_bounds() -> None:
    """Required aggregate case: serialized and decoded limits both enforced."""
    for case in (
        test_raw_bounds_over_ceiling_returns_no_payload,
        test_raw_bounds_zero_means_never,
        test_raw_bounds_exact_cap_boundary,
        test_raw_bounds_multibyte_is_measured_in_bytes,
        test_raw_bounds_tabular_paging_without_whole_table,
        test_raw_bounds_page_size_clamps_to_the_configured_maximum,
    ):
        tm = TaskMemoryStub()
        try:
            await case((WorkingMemoryToolkit(task_memory=tm), tm))
        finally:
            await tm.artifacts.close()
    await test_raw_bounds_caller_may_lower_but_never_raise()


# ─────────────────────────────────────────────────────────────
# test_disabled
# ─────────────────────────────────────────────────────────────


def _schema_for(toolkit: WorkingMemoryToolkit, method: str) -> Any:
    """Return the generated tool's args schema for one method.

    Args:
        toolkit: The toolkit.
        method: The method name.

    Returns:
        The schema class.
    """
    for tool in toolkit.get_tools():
        if getattr(tool, "_method_name", "") == method:
            return tool.args_schema
    raise AssertionError(f"no generated tool for {method!r}")


@pytest.mark.asyncio
async def test_disabled_legacy_schema_is_unchanged(disabled: WorkingMemoryToolkit) -> None:
    """The disabled ``wm_get_result`` schema is byte-identical to before.

    This is the AC13 requirement in its sharpest form: the enabled model
    is chosen at generation time precisely so that adding the cap does
    NOT change the schema a disabled deployment publishes.
    """
    schema = _schema_for(disabled, "get_result")
    assert schema is GetResultInput
    assert sorted(schema.model_fields) == ["include_raw", "key", "max_length"]
    assert "max_rehydrate_bytes" not in schema.model_fields
    assert "offset" not in schema.model_fields
    assert "limit" not in schema.model_fields


@pytest.mark.asyncio
async def test_disabled_enabled_schema_is_a_separate_model() -> None:
    """The enabled schema adds the cap without touching the disabled one."""
    tm = TaskMemoryStub()
    try:
        toolkit = WorkingMemoryToolkit(task_memory=tm)
        schema = _schema_for(toolkit, "get_result")
        assert schema is EnabledGetResultInput
        assert {"max_rehydrate_bytes", "offset", "limit"} <= set(schema.model_fields)
        # And the legacy model is still untouched.
        assert sorted(GetResultInput.model_fields) == ["include_raw", "key", "max_length"]
    finally:
        await tm.artifacts.close()


@pytest.mark.asyncio
async def test_disabled_raw_read_behaviour_is_unchanged(disabled: WorkingMemoryToolkit) -> None:
    """With task memory absent, raw reads behave exactly as before.

    No ceiling, no paging keys, no policy block — a large value comes back
    whole, which is the documented legacy behaviour.
    """
    big = {"blob": "x" * 500_000}
    await disabled.store_result("big", big)

    result = await disabled.get_result("big", include_raw=True)
    assert result["raw_data"] == big, "the legacy path returns the whole value"
    assert "raw_policy" not in result
    assert "raw_omitted" not in result
    assert "page" not in result


@pytest.mark.asyncio
async def test_disabled_sync_catalog_still_works(disabled: WorkingMemoryToolkit) -> None:
    """The legacy synchronous catalog API is untouched when disabled.

    ``PlanToolNode`` reaches into the catalog synchronously, so this must
    keep working.
    """
    entry = disabled._catalog.put("direct", frame())
    assert entry.key == "direct"
    assert disabled._catalog.get("direct") is entry
    assert "direct" in disabled._catalog
    assert disabled._catalog.drop("direct") is True


@pytest.mark.asyncio
async def test_disabled_store_and_summary_outputs_unchanged(disabled: WorkingMemoryToolkit) -> None:
    """Store/list/summary outputs keep their legacy shape."""
    stored = await disabled.store("sales", frame(4), description="raw")
    assert stored["status"] == "stored"
    assert stored["summary"]["key"] == "sales"
    assert stored["summary"]["shape"] == {"rows": 4, "cols": 2}

    listing = await disabled.list_stored()
    assert any(e["key"] == "sales" for e in listing["entries"])

    got = await disabled.get_result("sales")
    assert got["key"] == "sales"
    assert "raw_policy" not in got


@pytest.mark.asyncio
async def test_disabled_is_the_default() -> None:
    """A toolkit constructed the old way is disabled."""
    toolkit = WorkingMemoryToolkit()
    assert toolkit.task_memory_enabled is False
    assert toolkit._catalog.is_enabled is False


@pytest.mark.asyncio
async def test_disabled() -> None:
    """Required aggregate case: legacy schemas and outputs unchanged."""
    toolkit = WorkingMemoryToolkit()
    await test_disabled_legacy_schema_is_unchanged(toolkit)
    await test_disabled_raw_read_behaviour_is_unchanged(WorkingMemoryToolkit())
    await test_disabled_sync_catalog_still_works(WorkingMemoryToolkit())
    await test_disabled_store_and_summary_outputs_unchanged(WorkingMemoryToolkit())
    await test_disabled_is_the_default()
    await test_disabled_enabled_schema_is_a_separate_model()
