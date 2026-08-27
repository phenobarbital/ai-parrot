"""Unit tests for the `search_articles` helper + token guard (FEAT-449 TASK-2496)."""

from datetime import date

import pytest
from parrot_tools.legal.boe.queries import passes_token_guard, search_articles


def test_token_guard():
    assert passes_token_guard("plazo notificación", "El plazo se cuenta desde la notificacion")
    assert not passes_token_guard("plazo notificación", "Texto sin relación")
    assert passes_token_guard("ley", "cualquier texto")  # no tokens >=4 chars => skipped


def test_token_guard_skipped_for_short_queries():
    assert passes_token_guard("de la", "cualquier texto en absoluto")


async def _seed_articulo(fake_store, legal_tenant_ctx):
    await fake_store.upsert_nodes(
        legal_tenant_ctx,
        "articulo",
        [
            {
                "articulo_key": "BOE-A-2000-1:5",
                "norma_ref": "BOE-A-2000-1",
                "numero": "5",
                "versions": [
                    {
                        "n": 0,
                        "text": "El plazo sera de tres meses.",
                        "valid_from": "2010-01-01",
                        "valid_to": "2020-01-01",
                        "modified_by": None,
                        "kind": "redaccion",
                        "source": "boe_consolidada",
                        "derived": False,
                        "content_hash": "h0",
                        "hash_norm_version": 1,
                    },
                    {
                        "n": 1,
                        "text": "El plazo sera de seis meses.",
                        "valid_from": "2020-01-01",
                        "valid_to": None,
                        "modified_by": "BOE-A-2020-1",
                        "kind": "redaccion",
                        "source": "boe_consolidada",
                        "derived": False,
                        "content_hash": "h1",
                        "hash_norm_version": 1,
                    },
                ],
            }
        ],
        key_field="articulo_key",
    )


async def test_search_articles_temporal_filter(fake_store, legal_tenant_ctx):
    await _seed_articulo(fake_store, legal_tenant_ctx)

    # "tres" is specific to v0's wording ("...de tres meses.") — v1 reads
    # "...de seis meses.", so for a later as_of the in-force version (v1)
    # does NOT contain the query token and the token guard drops the hit.
    later = await search_articles(fake_store, legal_tenant_ctx, "tres", date(2022, 1, 1))
    assert later == []

    earlier = await search_articles(fake_store, legal_tenant_ctx, "tres", date(2019, 1, 1))
    assert earlier
    assert earlier[0].version.n == 0


async def test_search_articles_binds_and_pattern(fake_store, legal_tenant_ctx):
    await _seed_articulo(fake_store, legal_tenant_ctx)
    await search_articles(fake_store, legal_tenant_ctx, "seis meses", date(2021, 1, 1))
    aql, binds, collection_binds = fake_store.last_traversal
    assert aql == legal_tenant_ctx.ontology.traversal_patterns["search_articles"].query_template
    assert binds["query"] == "seis meses"
    assert binds["as_of"] == "2021-01-01"
    assert collection_binds is None


async def test_missing_pattern_raises_key_error(fake_store, legal_tenant_ctx):
    del legal_tenant_ctx.ontology.traversal_patterns["search_articles"]
    with pytest.raises(KeyError):
        await search_articles(fake_store, legal_tenant_ctx, "x", date(2020, 1, 1))
