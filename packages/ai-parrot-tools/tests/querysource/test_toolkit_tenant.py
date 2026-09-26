"""FEAT-598 TASK-3784 — tenant plumbing, describe semantics, and MultiQS dispatch."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from parrot_tools.querysource import _qs
from parrot_tools.querysource.toolkit import QuerysourceToolkit


class _Exc:
    """Minimal QuerySource exception module for toolkit fakes."""

    class QueryException(Exception):
        """Base query failure."""

    class SlugNotFound(QueryException):
        """Missing query slug."""

    class DataNotFound(QueryException):
        """Empty query result."""


def _record(*, multiquery: bool = False, pipeline: dict | None = None) -> SimpleNamespace:
    """Return the minimum catalog record shape used by the toolkit."""
    return SimpleNamespace(
        slug="multi" if multiquery else "single",
        description="test record",
        program_slug="program",
        provider="db",
        is_multiquery=multiquery,
        placeholder_names=["firstdate", "store_id"],
        conditions={},
        cond_definition={"store_id": "integer"},
        filtering={},
        fields=[],
        ordering=[],
        grouping=[],
        is_cached=False,
        cache_timeout=0,
        query_raw="SELECT {firstdate}, {store_id}",
        pipeline=pipeline or {},
    )


@pytest.fixture
def fake_engines(monkeypatch):
    """Fake QS/MultiQS constructors which retain their tenant keyword arguments."""
    state: dict[str, object] = {"qs": None, "mq": None}

    class FakeQS:
        def __init__(self, **kwargs):
            state["qs"] = kwargs

        async def query(self, output_format=None):
            return pd.DataFrame({"value": [1]}), None

        async def close(self):
            return None

    class FakeMultiQS:
        def __init__(self, **kwargs):
            state["mq"] = kwargs

        async def query(self):
            return {"result": pd.DataFrame({"value": [1]})}, {}

    monkeypatch.setattr(_qs, "QS", FakeQS)
    monkeypatch.setattr(_qs, "MultiQS", FakeMultiQS)
    monkeypatch.setattr(_qs, "get_exceptions", lambda: _Exc)
    return state


def _toolkit_with_catalog(record: SimpleNamespace, calls: list[tuple[str, str | None]]) -> QuerysourceToolkit:
    """Create a toolkit with a catalog fake that records tenant-aware lookups."""
    toolkit = QuerysourceToolkit(dsn="postgres://fake")

    async def get_allowed(slug: str, *, tenant: str | None = None):
        calls.append((slug, tenant))
        return record

    async def open_catalog() -> None:
        return None

    toolkit._catalog = SimpleNamespace(get_allowed=get_allowed)
    toolkit._open = open_catalog
    return toolkit


async def test_execute_slug_passes_tenant(fake_engines):
    """QS construction preserves the requested tenant routing value."""
    calls: list[tuple[str, str | None]] = []
    toolkit = _toolkit_with_catalog(_record(), calls)
    result = await toolkit.execute_slug("single", tenant="acme")

    assert calls == [("single", "acme")]
    assert fake_engines["qs"]["tenant"] == "acme"
    assert result.returned_rows == 1


async def test_execute_slug_multiquery_dispatches_multiqs(fake_engines):
    """Stored MultiQuery records use MultiQS and normalise its result frame."""
    calls: list[tuple[str, str | None]] = []
    toolkit = _toolkit_with_catalog(_record(multiquery=True), calls)
    result = await toolkit.execute_slug("multi", tenant="acme")

    assert fake_engines["qs"] is None
    assert fake_engines["mq"]["tenant"] == "acme"
    assert result.returned_rows == 1


async def test_placeholder_info_required_accepts_keywords(monkeypatch):
    """Describe variable flags are copied from QuerySource without recomputation."""
    variables = [
        SimpleNamespace(
            model_dump=lambda: {
                "name": "firstdate",
                "type": None,
                "default": None,
                "required": False,
                "accepts_keywords": True,
                "raw_type": None,
                "source": "query",
            }
        ),
        SimpleNamespace(
            model_dump=lambda: {
                "name": "store_id",
                "type": "integer",
                "default": None,
                "required": True,
                "accepts_keywords": False,
                "raw_type": "integer",
                "source": "condition",
            }
        ),
    ]
    monkeypatch.setattr(
        _qs,
        "get_describe",
        lambda: SimpleNamespace(
            build_variables=lambda *_args: {"variables": variables, "variables_supported": True}, KEYWORD_TYPES=set()
        ),
    )
    toolkit = QuerysourceToolkit(dsn="postgres://fake")
    detail, supported = toolkit._placeholders_detail(_record())

    by_name = {item.name: item for item in detail}
    assert supported is True
    assert (by_name["firstdate"].required, by_name["firstdate"].accepts_keywords) == (False, True)
    assert (by_name["store_id"].required, by_name["store_id"].accepts_keywords) == (True, False)


async def test_describe_json_dialect_not_supported(monkeypatch):
    """JSON/MultiQuery describe fallbacks retain legacy placeholders but disable variables."""
    monkeypatch.setattr(
        _qs,
        "get_describe",
        lambda: SimpleNamespace(
            build_variables=lambda *_args: {"variables": None, "variables_supported": False}, KEYWORD_TYPES={"date"}
        ),
    )
    calls: list[tuple[str, str | None]] = []
    toolkit = _toolkit_with_catalog(_record(multiquery=True), calls)
    detail = await toolkit.describe_slug("multi", tenant="acme")

    assert detail.variables_supported is False
    assert [item.name for item in detail.placeholders_detail] == ["firstdate", "store_id"]
    assert calls == [("multi", "acme")]


async def test_run_multiquery_tenant_threads_all_sites(fake_engines):
    """Stored pipeline validation and execution retain tenant routing at every lookup."""
    pipeline = {"queries": {"child": {"slug": "child"}}}
    calls: list[tuple[str, str | None]] = []
    toolkit = _toolkit_with_catalog(_record(multiquery=True, pipeline=pipeline), calls)
    toolkit._components_cache = []

    await toolkit.run_multiquery(slug="multi", tenant="acme")

    assert calls == [("multi", "acme"), ("child", "acme"), ("child", "acme")]
    assert fake_engines["mq"]["tenant"] == "acme"


async def test_list_slugs_forwards_tenant():
    """Catalog listing receives the requested tenant schema."""
    toolkit = QuerysourceToolkit(dsn="postgres://fake")
    captured: dict[str, str | None] = {}

    async def list_records(*, search, program, limit, tenant):
        captured["tenant"] = tenant
        return [_record()]

    async def open_catalog() -> None:
        return None

    toolkit._catalog = SimpleNamespace(list=list_records)
    toolkit._open = open_catalog
    records = await toolkit.list_slugs(tenant="acme")

    assert captured["tenant"] == "acme"
    assert records[0].slug == "single"
