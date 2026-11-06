"""Golden Turtle sanity checks — no rdflib required (FEAT-824 TASK-5255)."""
from __future__ import annotations

import re


def test_golden_files_have_no_blank_nodes(golden_v1, golden_v2, golden_v3) -> None:
    for data in (golden_v1, golden_v2, golden_v3):
        text = data.decode("utf-8")
        assert "_:" not in text
        for line in text.splitlines():
            code = line.split("#", 1)[0]
            assert not re.search(r"\[\s*[^\]]*\]", code)


def test_golden_base_iri_is_shared(golden_v1, golden_v2, golden_v3, golden_base_iri) -> None:
    for data in (golden_v1, golden_v2, golden_v3):
        assert f"@prefix ex: <{golden_base_iri}>".encode() in data


def test_v2_deprecates_with_replacement(golden_v2) -> None:
    text = golden_v2.decode("utf-8")
    assert "owl:deprecated" in text and "dcterms:isReplacedBy" in text


def test_versions_differ(golden_v1, golden_v2, golden_v3) -> None:
    assert len({golden_v1, golden_v2, golden_v3}) == 3


async def test_pg_schema_fixture(pg_pool, pg_schema_name) -> None:
    """The live fixture yields a usable unique schema (skipped without a DSN)."""
    async with pg_pool.acquire() as conn:
        await conn.execute(f'CREATE SCHEMA "{pg_schema_name}"')
        assert await conn.fetchval("SELECT 1") == 1
