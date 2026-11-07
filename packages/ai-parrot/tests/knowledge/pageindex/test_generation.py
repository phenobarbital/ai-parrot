import os
import time

import pytest

from parrot.knowledge.pageindex import TreeLockTimeout
from parrot.knowledge.pageindex.content_store import NodeContentStore
from parrot.knowledge.pageindex.generation import (
    BodyRef,
    GenerationInfo,
    StaleGenerationError,
    WriteTransaction,
    body_sha16,
    ensure_concept_ids,
    flatten_concept_id,
    next_generation,
)
from parrot.knowledge.pageindex.store import JSONTreeStore


def _txn(tmp_path, name, base, sig, projector=lambda tree, tree_name: False):
    return WriteTransaction(
        tree_name=name,
        base_tree=base,
        base_signature=sig,
        store=JSONTreeStore(tmp_path),
        content_store=NodeContentStore(tmp_path),
        storage_dir=tmp_path,
        lock_timeout_s=1.0,
        grace_s=3600,
        projector=projector,
    )


def test_body_ref_roundtrip():
    ref = BodyRef(flat_concept_id="intro", sha16=body_sha16("hello"))
    assert BodyRef.parse(ref.key) == ref


@pytest.mark.parametrize("value", ["bad", "a.XYZ", "a/b.0123456789abcdef"])
def test_body_ref_rejects(value):
    with pytest.raises(ValueError):
        BodyRef.parse(value)


def test_next_generation():
    assert next_generation(None).id == 1
    nxt = next_generation(GenerationInfo(id=4, published_at="2026-01-01T00:00:00Z"))
    assert (nxt.id, nxt.parent) == (5, 4)


def test_ensure_concept_ids_preserves_existing():
    tree = {"structure": [{"title": "A", "concept_id": "keep", "nodes": [{"title": "B"}]}]}
    assert ensure_concept_ids(tree) == 1
    assert tree["structure"][0]["concept_id"] == "keep"
    assert tree["structure"][0]["nodes"][0]["concept_id"]


def test_flatten_matches_okf():
    assert flatten_concept_id("a/b") == "a--b"


@pytest.mark.asyncio
async def test_publish_increments_generation(tmp_path):
    txn = _txn(tmp_path, "t", {"doc_name": "t", "structure": []}, None)
    node = {"node_id": "0001", "title": "Intro"}
    txn.tree["structure"].append(node)
    txn.set_body(node, "hello")
    report = await txn.publish()
    assert report.generation == 1
    assert JSONTreeStore(tmp_path).read_generation("t") == 1

    base = JSONTreeStore(tmp_path).load("t")
    txn = _txn(tmp_path, "t", base, JSONTreeStore(tmp_path).signature("t"))
    await txn.publish()
    generation = JSONTreeStore(tmp_path).load("t")["generation"]
    assert generation["id"] == 2
    assert generation["parent"] == 1


@pytest.mark.asyncio
async def test_publish_rejects_stale_base(tmp_path):
    store = JSONTreeStore(tmp_path)
    first = _txn(tmp_path, "t", {"doc_name": "t", "structure": []}, None)
    await first.publish()
    base = store.load("t")
    txn = _txn(tmp_path, "t", base, store.signature("t"))
    store.save("t", {"doc_name": "t", "structure": [], "generation": {"id": 99}})
    rewritten = (tmp_path / "t.json").read_bytes()
    with pytest.raises(StaleGenerationError):
        await txn.publish()
    assert (tmp_path / "t.json").read_bytes() == rewritten


@pytest.mark.asyncio
async def test_publish_projection_failure_aborts(tmp_path):
    store = JSONTreeStore(tmp_path)
    first = _txn(tmp_path, "t", {"doc_name": "t", "structure": []}, None)
    await first.publish()
    original = (tmp_path / "t.json").read_bytes()

    def projector(tree, tree_name):
        raise RuntimeError("projection failed")

    txn = _txn(tmp_path, "t", store.load("t"), store.signature("t"), projector)
    with pytest.raises(RuntimeError, match="projection failed"):
        await txn.publish()
    assert (tmp_path / "t.json").read_bytes() == original


@pytest.mark.asyncio
async def test_publish_replace_failure_keeps_old_generation(tmp_path, monkeypatch):
    store = JSONTreeStore(tmp_path)
    first = _txn(tmp_path, "t", {"doc_name": "t", "structure": []}, None)
    await first.publish()
    original = (tmp_path / "t.json").read_bytes()
    txn = _txn(tmp_path, "t", store.load("t"), store.signature("t"))

    import parrot.knowledge.pageindex.store as store_module

    original_replace = store_module.os.replace
    failed = False

    def replace_once(source, destination):
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("replace failed")
        return original_replace(source, destination)

    monkeypatch.setattr(store_module.os, "replace", replace_once)
    with pytest.raises(OSError, match="replace failed"):
        await txn.publish()
    assert (tmp_path / "t.json").read_bytes() == original


@pytest.mark.asyncio
async def test_publish_rejects_missing_body_and_second_publish(tmp_path):
    txn = _txn(
        tmp_path, "t", {"doc_name": "t", "structure": [{"node_id": "1", "body_ref": "x.0123456789abcdef"}]}, None
    )
    with pytest.raises(ValueError, match="node '1'"):
        await txn.publish()

    clean = _txn(tmp_path, "clean", {"doc_name": "clean", "structure": []}, None)
    await clean.publish()
    with pytest.raises(RuntimeError, match="already published"):
        await clean.publish()


@pytest.mark.asyncio
async def test_publish_rejects_equal_signature_but_newer_generation(tmp_path):
    """A publish landing between the snapshot's load and its stat must not be overwritten."""
    store = JSONTreeStore(tmp_path)
    await _txn(tmp_path, "t", {"doc_name": "t", "structure": []}, None).publish()
    gen1 = store.load("t")
    await _txn(tmp_path, "t", gen1, store.signature("t")).publish()  # generation 2 is now live
    # Stale tree (generation 1) paired with the *current* signature: signatures match, ids do not.
    stale = _txn(tmp_path, "t", gen1, store.signature("t"))
    live = (tmp_path / "t.json").read_bytes()
    with pytest.raises(StaleGenerationError):
        await stale.publish()
    assert (tmp_path / "t.json").read_bytes() == live


@pytest.mark.asyncio
async def test_grace_runs_from_supersession_not_creation(tmp_path):
    """A long-lived body dropped by a new generation stays readable for the full grace period."""
    store = JSONTreeStore(tmp_path)
    content = NodeContentStore(tmp_path)
    first = _txn(tmp_path, "t", {"doc_name": "t", "structure": []}, None)
    node = {"node_id": "0001", "title": "Intro"}
    first.tree["structure"].append(node)
    ref = first.set_body(node, "old body")
    await first.publish()
    blob = content.body_path("t", ref.key)
    ancient = time.time() - 10 * 3600
    os.utime(blob, (ancient, ancient))  # created far longer ago than the 3600s grace

    second = _txn(tmp_path, "t", store.load("t"), store.signature("t"))
    second.drop_body(second.tree["structure"][0])
    report = await second.publish()

    assert report.bodies_swept == 0
    assert blob.is_file(), "a just-superseded body must survive until grace elapses"


@pytest.mark.asyncio
async def test_first_write_keeps_legacy_files_for_grace(tmp_path):
    """Migrating a pre-generation tree must not delete its legacy <node_id>.md at once."""
    content = NodeContentStore(tmp_path)
    content.save("t", "0001", "legacy body")
    legacy = tmp_path / "t" / "0001.md"
    ancient = time.time() - 10 * 3600
    os.utime(legacy, (ancient, ancient))

    txn = _txn(tmp_path, "t", {"doc_name": "t", "structure": [{"node_id": "0001", "title": "Intro"}]}, None)
    txn.set_body(txn.tree["structure"][0], "legacy body")
    await txn.publish()

    assert legacy.is_file()
    assert content.load("t", "0001") == "legacy body"


def test_set_body_rejects_unusable_concept_id(tmp_path):
    txn = _txn(tmp_path, "t", {"doc_name": "t", "structure": []}, None)
    node = {"node_id": "0001", "title": "Odd id", "concept_id": "has.dot and space"}
    with pytest.raises(ValueError, match="cannot be used as a body reference"):
        txn.set_body(node, "body")


def test_public_exports():
    assert TreeLockTimeout is not None
