"""G1 full-text, vector, filter, and RRF availability checks."""

from __future__ import annotations

from checks._common import Timer, apply_schema, connect, execute, g1_check
from harness import CheckResult, SpikeContext

_DIMENSION = 1024


def _vector(axis: int) -> list[float]:
    """Build a 1024-dimensional unit vector along one axis (cosine-distinguishable)."""
    values = [0.0] * _DIMENSION
    values[axis] = 1.0
    return values


async def _seed_chunks(db: object) -> None:
    """Create small Spanish-search and vector-search fixtures that satisfy the SCHEMAFULL chunk table."""
    common = "section = section:s1, document = document:d1, ordinal = 0, tokens = 4, span = {start: 0, end: 4}"
    await execute(
        db,
        f"CREATE chunk:legal SET {common}, text = 'Los gatos corren rápidamente', "
        "embedding = $near, concept_iris = ['iri:1'];"
        f"CREATE chunk:other SET {common}, text = 'Los perros descansan', "
        "embedding = $far, concept_iris = ['iri:2'];",
        {"near": _vector(0), "far": _vector(1)},
    )


@g1_check("G1-03", "BM25 full-text search with a Spanish snowball analyzer", blocking=True)
async def check_g1_03_bm25(ctx: SpikeContext) -> CheckResult:
    """Search an inflected Spanish term and require the stemmed chunk first."""
    query = "SELECT id, search::score(1) AS score FROM chunk WHERE text @1@ $term ORDER BY score DESC;"
    async with connect(ctx, "g1", "g1_03", reset=True) as db:
        await apply_schema(db)
        await _seed_chunks(db)
        rows = await db.query(query, {"term": "corriendo"}).first()
    assert rows and str(rows[0]["id"]).endswith(":legal"), rows
    return CheckResult(
        check_id="G1-03",
        title=check_g1_03_bm25.title,
        blocking=True,
        status="pass",
        evidence=f"{query} rows={rows!r}",
    )


@g1_check("G1-04", "HNSW 1024-dimensional cosine KNN search", blocking=True)
async def check_g1_04_hnsw(ctx: SpikeContext) -> CheckResult:
    """Search a 1024-dimensional vector and require the closest fixture first."""
    query = (
        "SELECT id, vector::distance::knn() AS distance FROM chunk "
        "WHERE embedding <|1, COSINE|> $vector ORDER BY distance;"
    )
    async with connect(ctx, "g1", "g1_04", reset=True) as db:
        await apply_schema(db)
        await _seed_chunks(db)
        rows = await db.query(query, {"vector": _vector(0)}).first()
    assert rows and str(rows[0]["id"]).endswith(":legal"), rows
    return CheckResult(
        check_id="G1-04",
        title=check_g1_04_hnsw.title,
        blocking=True,
        status="pass",
        evidence=f"{query} rows={rows!r}",
    )


@g1_check("G1-05", "BM25 and KNN support CONTAINSANY IRI filters", blocking=True)
async def check_g1_05_containsany(ctx: SpikeContext) -> CheckResult:
    """Exercise both search indexes with 200 ontology-IRI filter values."""
    iris = [f"iri:{number}" for number in range(1, 201)]
    bm25 = "SELECT id FROM chunk WHERE text @1@ $term AND concept_iris CONTAINSANY $iris;"
    knn = "SELECT id FROM chunk WHERE embedding <|1, COSINE|> $vector AND concept_iris CONTAINSANY $iris;"
    async with connect(ctx, "g1", "g1_05", reset=True) as db:
        await apply_schema(db)
        await _seed_chunks(db)
        with Timer() as bm25_timer:
            bm25_rows = await db.query(bm25, {"term": "gato", "iris": iris}).first()
        with Timer() as knn_timer:
            knn_rows = await db.query(knn, {"vector": _vector(0), "iris": iris}).first()
    assert bm25_rows and knn_rows, (bm25_rows, knn_rows)
    return CheckResult(
        check_id="G1-05",
        title=check_g1_05_containsany.title,
        blocking=True,
        status="pass",
        evidence=f"BM25={bm25} rows={bm25_rows!r}; KNN={knn} rows={knn_rows!r}",
        measurements={"bm25_200_iris_ms": bm25_timer.ms, "knn_200_iris_ms": knn_timer.ms},
    )


@g1_check("G1-06", "search::rrf availability and signature", blocking=False)
async def check_g1_06_rrf(ctx: SpikeContext) -> CheckResult:
    """Record whether the server exposes search::rrf without making it a gate."""
    query = "RETURN search::rrf([[{id: chunk:legal}], [{id: chunk:other}]], 20);"
    async with connect(ctx, "g1", "g1_06") as db:
        try:
            rows = await db.query(query).first()
        except Exception as exc:  # informational discovery, not a failed gate
            return CheckResult(
                check_id="G1-06",
                title=check_g1_06_rrf.title,
                blocking=False,
                status="skipped",
                evidence=f"{query} unavailable: {exc}",
            )
    return CheckResult(
        check_id="G1-06",
        title=check_g1_06_rrf.title,
        blocking=False,
        status="pass",
        evidence=f"{query} rows={rows!r}",
    )
