"""Bounded real-SDK compatibility probes for LanceDB (FEAT-542, AC1).

Skipped unless the optional extra is installed. These are not product tests:
each probe records one fact the spec depends on, and a failure here means the
candidate pin is wrong, not that the backend is broken.

Evidence produced by these probes is transcribed into
``sdd/state/FEAT-542/lancedb-sdk-contract.md`` (TASK-3057). Run with:

    uv run pytest packages/ai-parrot-embeddings/tests/test_lancedb_sdk_contract.py -v
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import multiprocessing as mp
import os
import socket

import pyarrow as pa
import pytest

lancedb = pytest.importorskip("lancedb", reason="requires ai-parrot-embeddings[lancedb]")

from lancedb.index import FTS  # noqa: E402  (import after importorskip)

pytestmark = pytest.mark.asyncio


def _schema(dimension: int = 4) -> pa.Schema:
    """Explicit Arrow schema carrying a versioned manifest in schema metadata.

    Mirrors spec section 2 "Data Models and Persistent Schema": a manifest
    with schema_version, dimension, metric and embedding identity is stored
    in persisted schema metadata, never inferred from the first row.
    """
    manifest = {
        "schema_version": 1,
        "dimension": dimension,
        "metric": "COSINE",
        "embedding_identity": "lancedb-test-embedding-v1",
    }
    return pa.schema(
        [
            pa.field("record_id", pa.string(), nullable=False),
            pa.field("document", pa.string(), nullable=False),
            pa.field("embedding", pa.list_(pa.float32(), dimension), nullable=False),
            pa.field("metadata_json", pa.string(), nullable=False),
        ],
        metadata={b"lancedb_manifest": json.dumps(manifest).encode("utf-8")},
    )


async def test_async_connect_and_persisted_schema_metadata(tmp_path):
    """connect_async opens a local dir; schema metadata survives reopen."""
    uri = str(tmp_path / "col")
    conn = await lancedb.connect_async(uri)
    tbl = await conn.create_table("agent_knowledge", schema=_schema())
    await tbl.add(
        [
            {
                "record_id": "a",
                "document": "cats are great",
                "embedding": [1.0, 0.0, 0.0, 0.0],
                "metadata_json": "{}",
            }
        ]
    )

    # Fresh connection + fresh table handle: nothing cached from the writer.
    conn2 = await lancedb.connect_async(uri)
    tbl2 = await conn2.open_table("agent_knowledge")
    schema2 = await tbl2.schema()

    assert schema2.metadata is not None
    manifest = json.loads(schema2.metadata[b"lancedb_manifest"])
    assert manifest["schema_version"] == 1
    assert manifest["dimension"] == 4

    rows = await tbl2.query().limit(10).to_list()
    assert [r["record_id"] for r in rows] == ["a"]


async def test_cosine_distance_column_name_and_direction(tmp_path):
    """Record the distance column name and whether lower is better.

    Finding: the default query distance metric is L2, NOT cosine — the
    backend MUST call ``.distance_type("cosine")`` explicitly on every
    vector query, or scores silently become squared-L2 distances instead
    of the documented raw cosine distance (spec section 2 "Search and Score
    Contracts").
    """
    uri = str(tmp_path / "col")
    conn = await lancedb.connect_async(uri)
    tbl = await conn.create_table("t", schema=_schema())
    await tbl.add(
        [
            {"record_id": "a", "document": "d", "embedding": [1.0, 0.0, 0.0, 0.0], "metadata_json": "{}"},
            {"record_id": "b", "document": "d", "embedding": [0.0, 1.0, 0.0, 0.0], "metadata_json": "{}"},
            {"record_id": "c", "document": "d", "embedding": [-1.0, 0.0, 0.0, 0.0], "metadata_json": "{}"},
        ]
    )

    cosine_rows = await tbl.query().nearest_to([1.0, 0.0, 0.0, 0.0]).distance_type("cosine").limit(3).to_list()
    by_id = {r["record_id"]: r["_distance"] for r in cosine_rows}
    # identical direction -> 0.0, orthogonal -> 1.0, opposite -> 2.0; lower is better.
    assert by_id["a"] == pytest.approx(0.0, abs=1e-6)
    assert by_id["b"] == pytest.approx(1.0, abs=1e-6)
    assert by_id["c"] == pytest.approx(2.0, abs=1e-6)

    default_rows = await tbl.query().nearest_to([1.0, 0.0, 0.0, 0.0]).limit(3).to_list()
    default_by_id = {r["record_id"]: r["_distance"] for r in default_rows}
    # Without an explicit distance_type, LanceDB 0.38.0 defaults to squared L2,
    # which is numerically different from cosine for non-unit vectors. This is
    # exactly the drift this probe exists to catch.
    assert default_by_id["b"] == pytest.approx(2.0, abs=1e-6)  # (1-0)^2 + (0-1)^2
    assert default_by_id["b"] != by_id["b"]


async def test_native_fts_index_and_hybrid_fusion(tmp_path):
    """Native FTS index creation, BM25 order, and explicit vector+text hybrid.

    Finding (spec section 8 Q6): the hybrid query result exposes only the
    fused ``_relevance_score`` column (RRF). No pre-fusion vector/lexical
    component columns are exposed by ``AsyncTable.query()...to_list()`` in
    0.38.0 — v1 ships the single fused score, per the spec's documented
    fallback.
    """
    uri = str(tmp_path / "col")
    conn = await lancedb.connect_async(uri)
    tbl = await conn.create_table("t", schema=_schema())
    await tbl.add(
        [
            {"record_id": "a", "document": "cats are great", "embedding": [1.0, 0.0, 0.0, 0.0], "metadata_json": "{}"},
            {"record_id": "b", "document": "dogs bark loud", "embedding": [0.0, 1.0, 0.0, 0.0], "metadata_json": "{}"},
        ]
    )
    # create_index with FTS() config is the async native FTS API (NOT the
    # synchronous, removed create_fts_index).
    await tbl.create_index("document", config=FTS())

    fts_rows = await tbl.query().nearest_to_text("cats").limit(2).to_list()
    assert fts_rows and fts_rows[0]["record_id"] == "a"
    assert "_score" in fts_rows[0]  # BM25, higher is better

    hybrid_rows = (
        await tbl.query()
        .nearest_to([1.0, 0.0, 0.0, 0.0])
        .distance_type("cosine")
        .nearest_to_text("cats")
        .limit(2)
        .to_list()
    )
    assert hybrid_rows
    assert "_relevance_score" in hybrid_rows[0]
    assert "_distance" not in hybrid_rows[0]
    assert "_score" not in hybrid_rows[0]
    # RRF is higher-is-better; the document scoring well on both legs ranks first.
    assert hybrid_rows[0]["record_id"] == "a"


async def test_prefilter_merge_insert_delete_and_freshness(tmp_path):
    """One conjunctive prefilter on all modes; merge-insert; delete; post-write reads."""
    uri = str(tmp_path / "col")
    conn = await lancedb.connect_async(uri)
    tbl = await conn.create_table("t", schema=_schema())
    await tbl.add(
        [
            {"record_id": "a", "document": "cats are great", "embedding": [1.0, 0.0, 0.0, 0.0], "metadata_json": "{}"},
            {"record_id": "b", "document": "dogs bark loud", "embedding": [0.0, 1.0, 0.0, 0.0], "metadata_json": "{}"},
        ]
    )
    await tbl.create_index("document", config=FTS())

    # Prefilter (.where) applies before candidate limits on vector search.
    filtered = (
        await tbl.query()
        .nearest_to([1.0, 0.0, 0.0, 0.0])
        .distance_type("cosine")
        .where("record_id = 'b'")
        .limit(5)
        .to_list()
    )
    assert [r["record_id"] for r in filtered] == ["b"]

    # merge-insert upserts by the stable id.
    mi = tbl.merge_insert("record_id")
    mi = mi.when_matched_update_all().when_not_matched_insert_all()
    result = await mi.execute(
        [{"record_id": "a", "document": "cats are amazing", "embedding": [1.0, 0.0, 0.0, 0.0], "metadata_json": "{}"}]
    )
    assert result.num_updated_rows == 1
    assert result.num_inserted_rows == 0

    # Row added AFTER FTS index creation is visible in FTS immediately (no
    # separate maintenance step required) — spec section 7 "FTS index freshness".
    await tbl.add(
        [{"record_id": "c", "document": "cats meow softly", "embedding": [0.9, 0.1, 0.0, 0.0], "metadata_json": "{}"}]
    )
    fts_after = await tbl.query().nearest_to_text("cats").limit(5).to_list()
    assert {r["record_id"] for r in fts_after} >= {"a", "c"}

    # delete returns an explicit count.
    delete_result = await tbl.delete("record_id = 'b'")
    assert delete_result.num_deleted_rows == 1
    remaining = await tbl.query().limit(10).to_list()
    assert {r["record_id"] for r in remaining} == {"a", "c"}


def _mutate_worker(uri: str, prefix: str, n: int, shared_id: bool, barrier, out_q) -> None:
    """Cross-process mutation worker used by test_two_process_concurrent_commit_behavior.

    Coordinator interface proven here (consumed by TASK-3061): a single
    ``fcntl.flock`` (POSIX exclusive lock) over a lock file inside the
    collection directory, guarding a critical section that (a) reopens the
    table handle to the latest committed version via ``conn.open_table``
    and (b) performs the mutation. A stale cached handle, even under the
    lock, reproduces duplicate-ID inserts (see module docstring finding).
    """
    import asyncio

    lock_path = os.path.join(uri, ".lancedb_mutation.lock")

    @contextlib.contextmanager
    def flock():
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    async def run():
        conn = await lancedb.connect_async(uri)
        errors: list[str] = []
        for i in range(n):
            record_id = "shared" if shared_id else f"{prefix}-{i}"
            rows = [
                {
                    "record_id": record_id,
                    "document": f"{prefix} doc {i}",
                    "embedding": [0.1, 0.2, 0.3, 0.4],
                    "metadata_json": "{}",
                }
            ]
            try:
                with flock():
                    table = await conn.open_table("t")  # refresh to latest committed version
                    mi = table.merge_insert("record_id")
                    mi = mi.when_matched_update_all().when_not_matched_insert_all()
                    await mi.execute(rows)
            except Exception as exc:  # noqa: BLE001 — record actual exception shape
                errors.append(f"{type(exc).__module__}.{type(exc).__name__}: {exc}")
        out_q.put((prefix, errors))

    barrier.wait()
    asyncio.run(run())


async def test_two_process_concurrent_commit_behavior(tmp_path):
    """Two real OS processes commit to one directory; record the conflict contract.

    Finding: with two independent processes racing ``merge_insert`` on a
    NEW colliding id, LanceDB 0.38.0 raised **no distinguishable conflict
    exception** — each process's "not matched -> insert" branch evaluated
    against its own stale snapshot and both inserts silently committed,
    producing two rows for one logical id when the operation was not
    externally serialized. A bounded retry-on-exception strategy is
    therefore NOT sufficient by itself (there is nothing to catch). The
    proven, sufficient mechanism is the file lock + reopen pattern in
    ``_mutate_worker`` above: TASK-3061 must implement exactly this
    coordinator (cross-process ``fcntl.flock`` guarding reopen+mutate),
    layered under the existing in-process asyncio lock for same-process
    calls (spec section 2 "Lifecycle, Ingestion and Mutations").
    """
    uri = str(tmp_path / "col")
    conn = await lancedb.connect_async(uri)
    await conn.create_table("t", schema=_schema())

    ctx = mp.get_context("spawn")
    barrier = ctx.Barrier(2)
    out_q = ctx.Queue()
    p1 = ctx.Process(target=_mutate_worker, args=(uri, "p1", 10, True, barrier, out_q))
    p2 = ctx.Process(target=_mutate_worker, args=(uri, "p2", 10, True, barrier, out_q))
    p1.start()
    p2.start()
    p1.join(timeout=60)
    p2.join(timeout=60)
    assert not p1.is_alive() and not p2.is_alive()

    results = dict(out_q.get() for _ in range(2))
    assert results["p1"] == []
    assert results["p2"] == []

    conn2 = await lancedb.connect_async(uri)
    tbl2 = await conn2.open_table("t")
    shared_rows = await tbl2.query().where("record_id = 'shared'").limit(1000).to_list()
    # Exactly one logical row for the colliding id — no lost update, no duplicate.
    assert len(shared_rows) == 1


async def test_offline_storage_path_denies_sockets(tmp_path):
    """LanceDB local-directory operations require zero network access.

    Proves the *storage* half of AC6: connect/create/add/FTS-index/vector/
    FTS/hybrid all succeed with outbound sockets denied. This does not by
    itself prove a fully offline *agent* (that additionally requires a
    locally provisioned embedding/LLM model, which is out of this gate's
    scope and is delivered by TASK-3068 against I8).
    """
    uri = str(tmp_path / "col")
    real_socket = socket.socket

    class _NoNetSocket(real_socket):
        def connect(self, address):  # noqa: D401
            raise OSError("network denied by offline probe")

        def connect_ex(self, address):
            raise OSError("network denied by offline probe")

    socket.socket = _NoNetSocket
    try:
        conn = await lancedb.connect_async(uri)
        tbl = await conn.create_table("t", schema=_schema())
        await tbl.add(
            [
                {
                    "record_id": "a",
                    "document": "no network here",
                    "embedding": [1.0, 0.0, 0.0, 0.0],
                    "metadata_json": "{}",
                }
            ]
        )
        await tbl.create_index("document", config=FTS())
        vector_rows = await tbl.query().nearest_to([1.0, 0.0, 0.0, 0.0]).distance_type("cosine").limit(1).to_list()
        fts_rows = await tbl.query().nearest_to_text("network").limit(1).to_list()
        hybrid_rows = (
            await tbl.query()
            .nearest_to([1.0, 0.0, 0.0, 0.0])
            .distance_type("cosine")
            .nearest_to_text("network")
            .limit(1)
            .to_list()
        )
    finally:
        socket.socket = real_socket

    assert vector_rows and fts_rows and hybrid_rows
