"""G1 full-text, vector, filter, and RRF availability checks."""

from __future__ import annotations

from checks._common import Timer, apply_schema, connect, execute, g1_check
from harness import CheckResult, SpikeContext


def _vector(value: float = 0.0) -> list[float]:
    """Build the required 1024-dimensional fixture vector."""
    return [value] * 1024


async def _seed_chunks(db: object) -> None:
    """Create small Spanish-search and vector-search fixtures."""
    await execute(
        db,
        "CREATE chunk:legal SET text = 'Los gatos corren rápidamente', embedding = $near, concept_iris = ['iri:1'];"
        "CREATE chunk:other SET text = 'Los perros descansan', embedding = $far, concept_iris = ['iri:2'];",
        {"near": _vector(0.1), "far": _vector(0.9)},
    )


@g1_check("G1-03", "BM25 full-text search with a Spanish snowball analyzer", blocking=True)
async def check_g1_03_bm25(ctx: SpikeContext) -> CheckResult:
    """Search an inflected Spanish term and require the stemmed chunk first."""
    query = "SELECT id, search::score(1) AS score FROM chunk WHERE text @1@ $term ORDER BY score DESC;"
    async with connect(ctx, "g1", "g1_03") as db:
        await apply_schema(db)
        await _seed_chunks(db)
        rows = await db.query(query, {"term": "corriendo"}).first()
    assert rows and str(rows[0]["id"]).endswith(":legal"), rows
    return CheckResult("G1-03", check_g1_03_bm25.title, True, "pass", f"{query} rows={rows!r}")


@g1_check("G1-04", "HNSW 1024-dimensional cosine KNN search", blocking=True)
async def check_g1_04_hnsw(ctx: SpikeContext) -> CheckResult:
    """Search a 1024-dimensional vector and require the closest fixture first."""
    query = "SELECT id, vector::distance::knn() AS distance FROM chunk WHERE embedding <|1, COSINE|> $vector ORDER BY distance;"
    async with connect(ctx, "g1", "g1_04") as db:
        await apply_schema(db)
        await _seed_chunks(db)
        rows = await db.query(query, {"vector": _vector(0.1)}).first()
    assert rows and str(rows[0]["id"]).endswith(":legal"), rows
    return CheckResult("G1-04", check_g1_04_hnsw.title, True, "pass", f"{query} rows={rows!r}")


@g1_check("G1-05", "BM25 and KNN support CONTAINSANY IRI filters", blocking=True)
async def check_g1_05_containsany(ctx: SpikeContext) -> CheckResult:
    """Exercise both search indexes with 200 ontology-IRI filter values."""
    iris = [f"iri:{number}" for number in range(1, 201)]
    bm25 = "SELECT id FROM chunk WHERE text @1@ $term AND concept_iris CONTAINSANY $iris;"
    knn = "SELECT id FROM chunk WHERE embedding <|1, COSINE|> $vector AND concept_iris CONTAINSANY $iris;"
    async with connect(ctx, "g1", "g1_05") as db:
        await apply_schema(db)
        await _seed_chunks(db)
        with Timer() as bm25_timer:
            bm25_rows = await db.query(bm25, {"term": "gato", "iris": iris}).first()
        with Timer() as knn_timer:
            knn_rows = await db.query(knn, {"vector": _vector(0.1), "iris": iris}).first()
    assert bm25_rows and knn_rows, (bm25_rows, knn_rows)
    return CheckResult(
        "G1-05",
        check_g1_05_containsany.title,
        True,
        "pass",
        f"BM25={bm25} rows={bm25_rows!r}; KNN={knn} rows={knn_rows!r}",
        {"bm25_200_iris_ms": bm25_timer.ms, "knn_200_iris_ms": knn_timer.ms},
    )


@g1_check("G1-06", "search::rrf availability and signature", blocking=False)
async def check_g1_06_rrf(ctx: SpikeContext) -> CheckResult:
    """Record whether the server exposes search::rrf without making it a gate."""
    query = "RETURN search::rrf([[{id: chunk:legal}], [{id: chunk:other}]], 20);"
    async with connect(ctx, "g1", "g1_06") as db:
        try:
            rows = await db.query(query).first()
        except Exception as exc:  # informational discovery, not a failed gate
            return CheckResult("G1-06", check_g1_06_rrf.title, False, "skipped", f"{query} unavailable: {exc}")
    return CheckResult("G1-06", check_g1_06_rrf.title, False, "pass", f"{query} rows={rows!r}")
