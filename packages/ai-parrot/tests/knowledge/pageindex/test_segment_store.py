import os
import time

import pytest

from parrot.knowledge.pageindex import SegmentStore
from parrot.knowledge.pageindex.segments import DocumentRevision, SourceInfo, revision_id, segment_pages


@pytest.fixture(autouse=True)
def _stub_tiktoken(monkeypatch):
    monkeypatch.setattr("parrot.knowledge.pageindex.utils.count_tokens", lambda t, model="gpt-4o": max(1, len(t)))


def _rev(doc_id="d", text="Hello."):
    segs = segment_pages([(1, text)])
    return DocumentRevision(doc_id=doc_id, revision=revision_id(segs), source=SourceInfo(name="d.pdf", kind="pdf"),
                            created_at="2026-11-07T00:00:00Z", segments=segs)


def test_save_revision_atomic_and_idempotent(tmp_path):
    store = SegmentStore(tmp_path)
    rev = _rev()
    path = store.save_revision("t", rev)
    mtime = path.stat().st_mtime_ns
    store.save_revision("t", rev)
    assert path.stat().st_mtime_ns == mtime
    assert store.load_revision("t", "d", rev.revision) == rev
    assert not list(path.parent.glob("*.tmp*"))
    assert store.has_revision("t", "d", rev.revision)
    assert store.list_revisions("t") == [("d", rev.revision)]


def test_load_missing_none_and_cached(tmp_path):
    store = SegmentStore(tmp_path)
    assert store.load_revision("t", "d", "0" * 16) is None
    rev = _rev()
    path = store.save_revision("t", rev)
    first = store.load_revision("t", "d", rev.revision)
    path.unlink()
    assert store.load_revision("t", "d", rev.revision) is first  # served from the cache


def test_cache_is_bounded(tmp_path):
    store = SegmentStore(tmp_path, cache_size=2)
    revs = [_rev(text=f"Text {i}.") for i in range(3)]
    for r in revs:
        store.save_revision("t", r)
        store.load_revision("t", "d", r.revision)
    assert len(store._cache) == 2


def test_sweep_revisions_respects_grace(tmp_path):
    store = SegmentStore(tmp_path)
    live, dead = _rev(text="Live."), _rev(doc_id="old", text="Dead.")
    live_path = store.save_revision("t", live)
    dead_path = store.save_revision("t", dead)
    tree = {"structure": [{"node_id": "0001", "doc_id": "d", "revision": live.revision, "nodes": []}]}
    assert store.sweep_unreferenced("t", tree, max_age_s=3600) == 0
    assert dead_path.exists()
    past = time.time() - 7200
    os.utime(dead_path, (past, past))
    os.utime(live_path, (past, past))
    assert store.sweep_unreferenced("t", tree, max_age_s=3600) == 1
    assert live_path.exists() and not dead_path.exists()


def test_mark_superseded_restarts_clock(tmp_path):
    store = SegmentStore(tmp_path)
    rev = _rev()
    path = store.save_revision("t", rev)
    past = time.time() - 7200
    os.utime(path, (past, past))
    assert store.mark_superseded("t", [("d", rev.revision), ("zz", "0" * 16), ("../x", "bad")]) == 1
    assert path.stat().st_mtime > past + 3600


def test_revision_path_rejects_bad_names(tmp_path):
    store = SegmentStore(tmp_path)
    for doc_id, revision in (("../x", "0" * 16), ("d", "xyz"), ("d", "A" * 16), ("", "0" * 16)):
        with pytest.raises(ValueError):
            store.revision_path("t", doc_id, revision)
    with pytest.raises(ValueError):
        store.segments_dir("../t")
    assert not (tmp_path / "x").exists()


def test_delete_tree_removes_segments(tmp_path):
    store = SegmentStore(tmp_path)
    rev = _rev()
    store.save_revision("t", rev)
    store.load_revision("t", "d", rev.revision)
    assert store.delete_tree("t") == 1
    assert not store.segments_dir("t").exists()
    assert store.load_revision("t", "d", rev.revision) is None


def test_package_exports():
    from parrot.knowledge.pageindex import DocumentRevision as DR, ReadResult, Segment, SegmentAddress  # noqa: F401
    assert DR is DocumentRevision


def _scanned(scored_by="regex", flag=True, **kw):
    rev = _rev(**kw)
    rev.scored_by = scored_by
    if flag:
        rev.segments[0].flags = ["injection"]
    return rev


def test_save_revision_upgrades_unscanned_to_scanned(tmp_path):
    store = SegmentStore(tmp_path)
    plain, scanned = _rev(), _scanned()
    assert plain.revision == scanned.revision
    store.save_revision("t", plain)
    store.save_revision("t", scanned)
    loaded = store.load_revision("t", "d", scanned.revision)
    assert loaded.scored_by == "regex"
    assert loaded.segments[0].flags == ["injection"]


def test_save_revision_never_downgrades_scanned(tmp_path):
    store = SegmentStore(tmp_path)
    scanned = _scanned()
    store.save_revision("t", scanned)
    store.save_revision("t", _rev())
    loaded = store.load_revision("t", "d", scanned.revision)
    assert loaded.scored_by == "regex"
    assert loaded.segments[0].flags == ["injection"]


def test_save_revision_replaces_on_different_engine(tmp_path):
    store = SegmentStore(tmp_path)
    store.save_revision("t", _scanned("regex"))
    other = _scanned("llm", flag=False)
    store.save_revision("t", other)
    loaded = store.load_revision("t", "d", other.revision)
    assert loaded.scored_by == "llm"
    assert loaded.segments[0].flags == []


def test_save_revision_replace_evicts_cache(tmp_path):
    store = SegmentStore(tmp_path)
    plain = _rev()
    store.save_revision("t", plain)
    assert store.load_revision("t", "d", plain.revision).scored_by is None  # populates the LRU
    store.save_revision("t", _scanned())
    assert store.load_revision("t", "d", plain.revision).scored_by == "regex"


def test_save_revision_identical_scanned_is_noop(tmp_path):
    store = SegmentStore(tmp_path)
    path = store.save_revision("t", _scanned())
    mtime = path.stat().st_mtime_ns
    store.save_revision("t", _scanned())
    assert path.stat().st_mtime_ns == mtime


def test_save_revision_replaces_corrupt_file(tmp_path):
    store = SegmentStore(tmp_path)
    rev = _scanned()
    path = store.revision_path("t", rev.doc_id, rev.revision)
    path.parent.mkdir(parents=True)
    path.write_text("not json", encoding="utf-8")
    store.save_revision("t", rev)
    assert store.load_revision("t", "d", rev.revision).scored_by == "regex"
