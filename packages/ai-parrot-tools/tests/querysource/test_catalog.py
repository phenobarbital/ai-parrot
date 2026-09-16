import pytest
from parrot_tools.querysource.catalog import SlugCatalog, TenantGuard, SlugRecord
from parrot_tools.querysource.errors import TenantDeniedError, SlugNotFoundError, QuerysourceToolkitError


async def test_get_uses_per_call_connection_and_no_cache(patched_qs):
    cat = SlugCatalog("postgres://fake", TenantGuard(["epson"]))
    await cat.get_allowed("epson_field_activity")
    await cat.get_allowed("epson_field_activity")
    assert len(patched_qs["get"]) == 2 and all(conn is not None for _, conn in patched_qs["get"])


async def test_tenant_denied_and_not_found(patched_qs):
    cat = SlugCatalog("postgres://fake", TenantGuard(["pokemon"]))
    with pytest.raises(TenantDeniedError):
        await cat.get_allowed("epson_field_activity")
    with pytest.raises(SlugNotFoundError):
        await cat.get("nope")


async def test_multiquery_detection(patched_qs, fake_rows):
    assert SlugRecord.from_row(fake_rows["pokemon_all_fso_odoo_new"]).is_multiquery
    rec = SlugRecord.from_row(fake_rows["epson_field_activity"])
    assert not rec.is_multiquery and rec.placeholder_names == ["firstdate", "lastdate"]


async def test_list_restricted(patched_qs):
    cat = SlugCatalog("postgres://fake", TenantGuard(["pokemon"]))
    assert [r.slug for r in await cat.list(search=None, program=None, limit=10)] == ["pokemon_all_fso_odoo_new"]


async def test_upsert_cross_program_refused(patched_qs):
    cat = SlugCatalog("postgres://fake", TenantGuard(None))
    with pytest.raises(QuerysourceToolkitError):
        await cat.upsert(slug="epson_field_activity", description="x", pipeline={"queries": {}},
                         program_slug="pokemon", overwrite=True)
    saved = await cat.upsert(slug="new_mq", description="x", pipeline={"queries": {}}, program_slug="pokemon",
                             overwrite=False)
    assert saved.action == "inserted" and patched_qs["insert"][0]["is_cached"] is False
