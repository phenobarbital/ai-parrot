import asyncio
import pytest
import pandas as pd
from parrot_tools.querysource import _qs
from parrot_tools.querysource.toolkit import QuerysourceToolkit
from parrot_tools.querysource.errors import RawSqlForbiddenError, WriteDisabledError, QuerysourceToolkitError, TenantDeniedError
from .test_components_validate import fake_registry  # noqa: F401 — reused fixture (patches _qs.ComponentRegistry)


@pytest.fixture
def fake_mq(fake_registry, monkeypatch):
    state = {"init": None, "delay": 0.0}

    class FakeMultiQS:
        def __init__(self, **kw):
            state["init"] = kw

        async def query(self):
            await asyncio.sleep(state["delay"])
            return {"a": pd.DataFrame({"x": [1]})}, {}

    monkeypatch.setattr(_qs, "MultiQS", FakeMultiQS)
    return state


async def test_policy_blocks_before_multiqs(fake_mq):
    tk = QuerysourceToolkit(dsn="postgres://fake", programs=["pokemon"])
    raw = {"queries": {"n": {"query": "select 1", "driver": "pg"}}}
    with pytest.raises(RawSqlForbiddenError):
        await tk.run_multiquery(pipeline=raw)
    with pytest.raises(WriteDisabledError):
        await tk.run_multiquery(pipeline={"queries": {"a": {"slug": "pokemon_all_fso_odoo_new"}},
                                          "Output": [{"tableOutput": {}}]})
    assert fake_mq["init"] is None


async def test_nested_foreign_slug_raises_tenant_denied(fake_mq, patched_qs):
    """A queries[*] node referencing a slug outside the allowlist must raise TenantDeniedError — the same
    type as a top-level `slug=` denial (spec §5 AC5) — not a generic QuerysourceToolkitError, from both
    run_multiquery(pipeline=...) and save_multiquery(pipeline=...). Regression test for the review finding
    that _raise_for_issues previously collapsed this into a generic error."""
    tk = QuerysourceToolkit(dsn="postgres://fake", programs=["pokemon"])
    with pytest.raises(TenantDeniedError):
        await tk.run_multiquery(pipeline={"queries": {"a": {"slug": "epson_field_activity"}}})
    assert fake_mq["init"] is None

    tw = QuerysourceToolkit(dsn="postgres://fake", allow_write=True, programs=["pokemon"])
    with pytest.raises(TenantDeniedError):
        await tw.save_multiquery("mq1", {"queries": {"a": {"slug": "epson_field_activity"}}}, "d")
    assert not patched_qs["insert"] and not patched_qs["update"]


async def test_inline_run_deepcopies_and_shapes(fake_mq):
    tk = QuerysourceToolkit(dsn="postgres://fake", allow_raw_sql=True, allow_write=True)
    p = {"queries": {"a": {"slug": "epson_field_activity"}}, "Join": []}
    r = await tk.run_multiquery(pipeline=p, conditions={"refresh": True})
    assert "queries" in p and fake_mq["init"]["query"] is not p and fake_mq["init"]["conditions"] == {"refresh": True}
    assert r.results["a"].returned_rows == 1


async def test_timeout(fake_mq):
    fake_mq["delay"] = 0.2
    tk = QuerysourceToolkit(dsn="postgres://fake", allow_raw_sql=True, multiquery_timeout=0.01)
    with pytest.raises(QuerysourceToolkitError, match="timed out"):
        await tk.run_multiquery(pipeline={"queries": {"a": {"slug": "epson_field_activity"}}})


async def test_save_gated_and_confirming(fake_mq, patched_qs):
    tk = QuerysourceToolkit(dsn="postgres://fake")
    assert "qs_save_multiquery" not in tk.list_tool_names()
    with pytest.raises(WriteDisabledError):
        await tk.save_multiquery("mq1", {"queries": {"a": {"slug": "epson_field_activity"}}}, "d")
    tw = QuerysourceToolkit(dsn="postgres://fake", allow_write=True, programs=["pokemon"])
    saved = await tw.save_multiquery("mq1", {"queries": {"a": {"slug": "pokemon_all_fso_odoo_new"}}}, "d")
    assert saved.program_slug == "pokemon" and patched_qs["insert"]
    assert tw.get_tool("qs_save_multiquery").routing_meta["requires_confirmation"] is True
