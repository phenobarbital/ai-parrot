"""FEAT-598 M6 — QuerySlugSource tenant/principal/MultiQS pass-through (spec §4)."""
from __future__ import annotations

import sys

import pandas as pd
import pytest

from parrot.auth.permission import PermissionContext, UserSession
from parrot.tools.dataset_manager.sources import query_slug as qsmod
from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource, to_qs_principal

pytestmark = pytest.mark.asyncio


class _FakeQuery:
    """Records constructor kwargs; returns a canned frame; counts close()."""

    instances: list["_FakeQuery"] = []
    result: object = None
    error: object = None

    def __init__(self, slug="", conditions=None, **kwargs):
        self.slug, self.conditions, self.kwargs, self.closed = slug, conditions, kwargs, False
        type(self).instances.append(self)

    async def query(self, output_format=None):
        # QS returns (frame, None); MultiQS (no output_format) returns (result, options).
        if output_format is None:
            return type(self).result, {}
        return type(self).result, type(self).error

    async def close(self):
        self.closed = True


@pytest.fixture
def fake_qs(monkeypatch):
    _FakeQuery.instances = []
    _FakeQuery.result = None
    _FakeQuery.error = None
    monkeypatch.setattr(qsmod, "_get_qs", lambda: _FakeQuery)
    monkeypatch.setattr(qsmod, "_get_multiqs", lambda: _FakeQuery)
    return _FakeQuery


async def test_fetch_passes_tenant(fake_qs):
    fake_qs.result = pd.DataFrame({"a": [1]})

    source = QuerySlugSource("my_slug", prefetch_schema_enabled=False, tenant="acme")
    await source.fetch()
    assert fake_qs.instances[-1].kwargs.get("tenant") == "acme"

    fake_qs.instances = []
    source_no_tenant = QuerySlugSource("my_slug", prefetch_schema_enabled=False)
    await source_no_tenant.fetch()
    assert "tenant" not in fake_qs.instances[-1].kwargs


async def test_query_slug_source_closes_qs(fake_qs):
    fake_qs.result = pd.DataFrame({"a": [1]})
    source = QuerySlugSource("my_slug", prefetch_schema_enabled=False)
    await source.fetch()
    assert fake_qs.instances[-1].closed is True

    fake_qs.instances = []
    fake_qs.result = None
    fake_qs.error = "boom"
    source_failing = QuerySlugSource("my_slug", prefetch_schema_enabled=False)
    with pytest.raises(RuntimeError):
        await source_failing.fetch()
    assert fake_qs.instances[-1].closed is True


async def test_multiquery_output_selection(fake_qs):
    fake_qs.result = {
        "main": pd.DataFrame({"a": [1]}),
        "extra": pd.DataFrame({"b": [2]}),
    }
    source = QuerySlugSource(
        "pipeline_slug", prefetch_schema_enabled=False, is_multiquery=True, multi_output="extra"
    )
    df = await source.fetch()
    assert list(df.columns) == ["b"]


async def test_multiquery_single_frame(fake_qs):
    fake_qs.result = {"result": pd.DataFrame({"a": [1]})}
    source = QuerySlugSource("pipeline_slug", prefetch_schema_enabled=False, is_multiquery=True)
    df = await source.fetch()
    assert list(df.columns) == ["a"]

    fake_qs.instances = []
    fake_qs.result = pd.DataFrame({"c": [3]})
    source_bare = QuerySlugSource("pipeline_slug", prefetch_schema_enabled=False, is_multiquery=True)
    df_bare = await source_bare.fetch()
    assert list(df_bare.columns) == ["c"]


async def test_multiquery_empty_frame(fake_qs):
    fake_qs.result = None
    source = QuerySlugSource("pipeline_slug", prefetch_schema_enabled=False, is_multiquery=True)
    df = await source.fetch()
    assert isinstance(df, pd.DataFrame)
    assert df.empty


async def test_query_slug_source_cache_key_tenant():
    base = QuerySlugSource("my_slug")
    tenant_a = QuerySlugSource("my_slug", tenant="acme")
    tenant_b = QuerySlugSource("my_slug", tenant="beta")

    assert base.cache_key == "qs:my_slug"
    assert tenant_a.cache_key == "qs:my_slug:t=acme"
    assert tenant_a.cache_key != base.cache_key
    assert tenant_a.cache_key != tenant_b.cache_key

    with_principal = QuerySlugSource("my_slug", tenant="acme", principal=object())
    assert with_principal.cache_key == tenant_a.cache_key


async def test_returned_error_is_chained(fake_qs):
    original = ValueError("boom")
    fake_qs.result = None
    fake_qs.error = original
    source = QuerySlugSource("my_slug", prefetch_schema_enabled=False)
    with pytest.raises(RuntimeError) as excinfo:
        await source.fetch()
    assert excinfo.value.__cause__ is original


def test_to_qs_principal_mapping(monkeypatch):
    # tests/conftest.py stubs a bare (non-package) "querysource" module at collection time
    # for parrot.scheduler's benefit; drop it here so `import querysource.auth.principal`
    # resolves to the REAL installed querysource package instead of the fake stub.
    for name in list(sys.modules):
        if name == "querysource" or name.startswith("querysource."):
            monkeypatch.delitem(sys.modules, name, raising=False)

    session = UserSession(
        user_id="u1",
        tenant_id="acme",
        roles=frozenset({"b", "a"}),
        metadata={
            "groups": ["g1"],
            "programs": ["p1"],
            "username": "u1-name",
            "superuser": True,
        },
    )
    pctx = PermissionContext(session=session)

    principal = to_qs_principal(pctx)

    assert principal.user_id == "u1"
    assert principal.username == "u1-name"
    assert principal.groups == ("g1",)
    assert principal.roles == ("a", "b")
    assert principal.programs == ("p1",)
    assert principal.superuser is True
    assert principal.tenant_id == "acme"
    assert principal.channel == "ui_surfaces"
