"""Unit tests for DictStateBackend (TASK-1418)."""
import pytest

from parrot.eval import DictStateBackend


async def test_reset_and_snapshot_deepcopy():
    """Mutating the snapshot does not affect the backend."""
    b = DictStateBackend()
    await b.reset({"issues": {"P-1": {"assignee": None}}})
    snap = await b.snapshot()
    snap["issues"]["P-1"]["assignee"] = "x"
    assert (await b.snapshot())["issues"]["P-1"]["assignee"] is None


async def test_snapshot_sorted_deterministic():
    """Snapshot keys are sorted regardless of insertion order."""
    b = DictStateBackend()
    await b.reset(None)
    await b.create("issues", "P-2", {"a": 1})
    await b.create("issues", "P-1", {"a": 2})
    snap = await b.snapshot()
    assert list(snap["issues"].keys()) == ["P-1", "P-2"]


async def test_reset_clears_existing():
    """reset(None) empties the store."""
    b = DictStateBackend()
    await b.create("col", "e1", {"x": 1})
    await b.reset(None)
    assert await b.snapshot() == {}


async def test_crud_create_get_update_delete():
    """Basic CRUD operations work correctly."""
    b = DictStateBackend()
    await b.reset(None)

    await b.create("items", "i1", {"name": "widget"})
    item = await b.get("items", "i1")
    assert item == {"name": "widget"}

    await b.update("items", "i1", {"price": 9.99})
    assert (await b.get("items", "i1"))["price"] == 9.99

    deleted = await b.delete("items", "i1")
    assert deleted is True
    assert await b.get("items", "i1") is None

    # deleting non-existent returns False
    assert await b.delete("items", "i1") is False


async def test_list_sorted():
    """list() returns entities sorted by entity_id."""
    b = DictStateBackend()
    await b.reset(None)
    await b.create("t", "z", {"v": 3})
    await b.create("t", "a", {"v": 1})
    items = await b.list("t")
    assert [i["_id"] for i in items] == ["a", "z"]


async def test_query_filter():
    """query() returns only matching entities."""
    b = DictStateBackend()
    await b.reset(None)
    await b.create("issues", "P-1", {"status": "open"})
    await b.create("issues", "P-2", {"status": "closed"})
    open_issues = await b.query("issues", lambda e: e["status"] == "open")
    assert len(open_issues) == 1
    assert open_issues[0]["_id"] == "P-1"


async def test_create_duplicate_raises():
    """Creating an entity with an existing id raises KeyError."""
    b = DictStateBackend()
    await b.reset(None)
    await b.create("col", "e1", {})
    with pytest.raises(KeyError):
        await b.create("col", "e1", {})


async def test_update_nonexistent_raises():
    """Updating a non-existent entity raises KeyError."""
    b = DictStateBackend()
    await b.reset(None)
    with pytest.raises(KeyError):
        await b.update("col", "ghost", {"x": 1})


async def test_collections_sorted_in_snapshot():
    """snapshot() sorts both collection names and entity ids."""
    b = DictStateBackend()
    await b.reset(None)
    await b.create("z_col", "e1", {"val": 1})
    await b.create("a_col", "e2", {"val": 2})
    snap = await b.snapshot()
    assert list(snap.keys()) == ["a_col", "z_col"]


async def test_upsert_insert_and_update():
    """upsert() creates on miss and merges on hit."""
    b = DictStateBackend()
    await b.reset(None)
    await b.upsert("t", "e1", {"x": 1})
    assert (await b.get("t", "e1"))["x"] == 1
    await b.upsert("t", "e1", {"y": 2})
    e = await b.get("t", "e1")
    assert e["x"] == 1 and e["y"] == 2
