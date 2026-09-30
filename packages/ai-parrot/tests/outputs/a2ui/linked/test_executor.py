"""FEAT-598 M5 — execute_sources / map_query_error (spec §4)."""

from __future__ import annotations

import asyncio
import sys
from typing import Any

import pandas as pd
import pytest

from parrot.auth.permission import build_principal_context
from parrot.outputs.a2ui.linked import Join, JoinKey, LinkedDataSource, Select, SourceRequest, TransformSpec
from parrot.outputs.a2ui.linked.executor import ERROR_STATUS, PROBE_FETCH_ROWS, execute_sources, map_query_error
from parrot.outputs.a2ui.linked.models import Pivot
from parrot.tools.dataset_manager.sources import query_slug as qsmod

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _real_querysource(monkeypatch):
    """tests/conftest.py stubs a bare (non-package) "querysource" module at collection time
    for parrot.scheduler's benefit; drop it for EVERY test in this file so any
    ``from querysource.<x> import <y>`` (map_query_error, to_qs_principal, ...) resolves to
    the REAL installed querysource package instead of the fake stub."""
    for name in list(sys.modules):
        if name == "querysource" or name.startswith("querysource."):
            monkeypatch.delitem(sys.modules, name, raising=False)


class _Recorder:
    """Records constructor kwargs/conditions per QS/MultiQS call; per-slug canned frames/errors."""

    def __init__(self) -> None:
        self.single_calls: list[tuple[str, dict, dict]] = []
        self.multi_calls: list[tuple[str, dict, dict]] = []
        self.registry: dict[str, Any] = {}


@pytest.fixture
def fake_qs(monkeypatch):
    """Patch both lazy slots; record constructor kwargs + conditions; per-slug canned frames/errors."""
    recorder = _Recorder()

    class _FakeQS:
        def __init__(self, *, slug, conditions, **kwargs):
            self.slug = slug
            recorder.single_calls.append((slug, dict(conditions), dict(kwargs)))

        async def query(self, output_format=None):
            result = recorder.registry.get(self.slug, pd.DataFrame())
            if isinstance(result, BaseException):
                return None, result
            return result, None

        async def close(self):
            return None

    class _FakeMultiQS:
        def __init__(self, *, slug, conditions, **kwargs):
            self.slug = slug
            recorder.multi_calls.append((slug, dict(conditions), dict(kwargs)))

        async def query(self):
            result = recorder.registry.get(self.slug, pd.DataFrame())
            if isinstance(result, BaseException):
                raise result
            return result, {}

        async def close(self):
            return None

    monkeypatch.setattr(qsmod, "QS", None)
    monkeypatch.setattr(qsmod, "MultiQS", None)
    monkeypatch.setattr(qsmod, "_get_qs", lambda: _FakeQS)
    monkeypatch.setattr(qsmod, "_get_multiqs", lambda: _FakeMultiQS)
    return recorder


async def test_execute_sources_tenant_passthrough(fake_qs, linked_source):
    """Tenant routed from the descriptor reaches QS; is_multiquery dispatches MultiQS (AC4/AC5)."""
    tenant_source = linked_source.model_copy(update={"tenant": "acme"})
    fake_qs.registry[tenant_source.slug] = pd.DataFrame({"a": [1]})

    outcome = await execute_sources({"activity": tenant_source})

    assert outcome.outcomes["activity"].error is None
    assert fake_qs.single_calls[0][2]["tenant"] == "acme"

    multi_source = linked_source.model_copy(update={"is_multiquery": True, "slug": "epson_multi"})
    fake_qs.registry[multi_source.slug] = pd.DataFrame({"a": [1]})

    outcome2 = await execute_sources({"activity": multi_source})

    assert outcome2.outcomes["activity"].error is None
    assert fake_qs.multi_calls, "MultiQS should have been used for is_multiquery=True"


async def test_execute_sources_querylimit_bound(fake_qs, linked_source):
    """querylimit == min(request.limit or max_fetch_rows, max_fetch_rows) on every fetch (AC17)."""
    fake_qs.registry[linked_source.slug] = pd.DataFrame({"a": [1]})

    await execute_sources({"activity": linked_source}, max_fetch_rows=25)

    _, conditions, _ = fake_qs.single_calls[0]
    assert conditions["querylimit"] == 25


async def test_execute_sources_locked_override_ignored(fake_qs, linked_source):
    """A locked key's override is dropped and reported in ignored_params."""
    locked_source = linked_source.model_copy(update={"locked": ["firstdate"]})
    fake_qs.registry[locked_source.slug] = pd.DataFrame({"a": [1]})

    outcome = await execute_sources(
        {"activity": locked_source},
        param_overrides={"activity": {"firstdate": "2026-01-01"}},
    )

    assert outcome.outcomes["activity"].ignored_params == ["firstdate"]
    _, conditions, _ = fake_qs.single_calls[0]
    assert conditions["firstdate"] == "YESTERDAY"


async def test_execute_sources_partial_failure(fake_qs, linked_source):
    """One source fails, its sibling still succeeds; the failure carries a stable error code."""
    from querysource.exceptions import QueryAccessDenied

    ok_source = linked_source.model_copy(update={"slug": "ok_slug", "target": "/ok/rows"})
    bad_source = linked_source.model_copy(update={"slug": "bad_slug", "target": "/bad/rows"})
    fake_qs.registry[ok_source.slug] = pd.DataFrame({"a": [1]})
    fake_qs.registry[bad_source.slug] = QueryAccessDenied()

    outcome = await execute_sources({"ok": ok_source, "bad": bad_source})

    assert outcome.outcomes["ok"].error is None
    assert outcome.outcomes["bad"].error == "query_not_found"


async def test_execute_sources_passes_principal(fake_qs, linked_source):
    """pctx given => principal= on every source; pctx=None => no principal kwarg at all (AC18)."""
    fake_qs.registry[linked_source.slug] = pd.DataFrame({"a": [1]})
    pctx = build_principal_context("user-1", channel="ui_surfaces")

    await execute_sources({"activity": linked_source}, pctx=pctx)
    _, _, kwargs = fake_qs.single_calls[0]
    assert kwargs["principal"].user_id == "user-1"

    fake_qs.single_calls.clear()
    await execute_sources({"activity": linked_source}, pctx=None)
    _, _, kwargs_none = fake_qs.single_calls[0]
    assert "principal" not in kwargs_none


async def test_apply_transform_off_loop(fake_qs, linked_source, monkeypatch):
    """apply_transform runs via asyncio.to_thread, not inline on the event loop."""
    transform = TransformSpec(ops=[Select(columns=["a"])])
    src = linked_source.model_copy(update={"transform": transform})
    fake_qs.registry[src.slug] = pd.DataFrame({"a": [1], "b": [2]})

    calls: list[Any] = []
    real_to_thread = asyncio.to_thread

    async def _tracking_to_thread(func, *args, **kwargs):
        calls.append(func)
        return await real_to_thread(func, *args, **kwargs)

    monkeypatch.setattr("parrot.outputs.a2ui.linked.executor.asyncio.to_thread", _tracking_to_thread)

    outcome = await execute_sources({"activity": src})

    assert calls and calls[0].__name__ == "apply_transform"
    assert outcome.outcomes["activity"].rows == [{"a": 1}]


async def test_join_sibling_executes_first(fake_qs):
    """join.with sibling executes before the source that depends on it."""
    right = LinkedDataSource(slug="right_slug", conditions={}, request=SourceRequest(), target="/right/rows")
    join_transform = TransformSpec(ops=[Join(with_="right", on=[JoinKey(left="id", right="id")])])
    left = LinkedDataSource(
        slug="left_slug",
        conditions={},
        request=SourceRequest(),
        target="/left/rows",
        transform=join_transform,
    )
    fake_qs.registry["left_slug"] = pd.DataFrame({"id": [1], "val": [10]})
    fake_qs.registry["right_slug"] = pd.DataFrame({"id": [1], "extra": [20]})

    outcome = await execute_sources({"left": left, "right": right})

    assert list(outcome.frames.keys()) == ["right", "left"]
    assert outcome.outcomes["left"].error is None
    assert outcome.outcomes["right"].error is None


async def test_snapshot_rows_truncated(fake_qs, linked_source):
    """max_snapshot_rows cuts the returned rows and sets truncated=True."""
    fake_qs.registry[linked_source.slug] = pd.DataFrame({"a": [1, 2, 3]})

    outcome = await execute_sources({"activity": linked_source}, max_snapshot_rows=2)

    result = outcome.outcomes["activity"]
    assert result.truncated is True
    assert len(result.rows) == 2


async def test_probe_fetches_one_row_and_never_a_snapshot(fake_qs, linked_source):
    """probe=True runs the slug with querylimit=1, keeps the frame for axis checks, but yields no rows."""
    fake_qs.registry[linked_source.slug] = pd.DataFrame({"a": [1]})

    outcome = await execute_sources({"activity": linked_source}, probe=True)

    _, conditions, _ = fake_qs.single_calls[0]
    assert conditions["querylimit"] == PROBE_FETCH_ROWS == 1
    result = outcome.outcomes["activity"]
    assert result.error is None and result.rows is None and result.snapshot_at is None
    assert list(outcome.frames["activity"].columns) == ["a"]
    assert outcome.data_model_patch() == {}


async def test_probe_ignores_request_limit(fake_qs, linked_source):
    """A request.limit (e.g. a 500-row grid) still probes with one row."""
    limited = linked_source.model_copy(update={"request": SourceRequest(limit=500)})
    fake_qs.registry[limited.slug] = pd.DataFrame({"a": [1]})

    await execute_sources({"activity": limited}, probe=True)

    _, conditions, _ = fake_qs.single_calls[0]
    assert conditions["querylimit"] == 1


async def test_probe_pivot_source_falls_back_to_full_fetch(fake_qs, linked_source):
    """pivot output columns depend on the data, so a pivoting source is fetched in full even under probe."""
    pivoting = linked_source.model_copy(
        update={"transform": TransformSpec(ops=[Pivot(index=["a"], columns="k", values="v")])}
    )
    fake_qs.registry[pivoting.slug] = pd.DataFrame({"a": [1, 1], "k": ["x", "y"], "v": [1, 2]})

    outcome = await execute_sources({"activity": pivoting}, probe=True, max_fetch_rows=77)

    _, conditions, _ = fake_qs.single_calls[0]
    assert conditions["querylimit"] == 77
    assert outcome.outcomes["activity"].rows is None
    assert set(outcome.frames["activity"].columns) >= {"a", "x", "y"}


async def test_probe_join_on_one_row_siblings_keeps_columns(fake_qs):
    """A join under probe still produces the joined column set (what axis validation reads)."""
    right = LinkedDataSource(slug="right_slug", conditions={}, request=SourceRequest(), target="/right/rows")
    left = LinkedDataSource(
        slug="left_slug",
        conditions={},
        request=SourceRequest(),
        target="/left/rows",
        transform=TransformSpec(ops=[Join(with_="right", on=[JoinKey(left="id", right="id")])]),
    )
    fake_qs.registry["left_slug"] = pd.DataFrame({"id": [1], "val": [10]})
    fake_qs.registry["right_slug"] = pd.DataFrame({"id": [1], "extra": [20]})

    outcome = await execute_sources({"left": left, "right": right}, probe=True)

    assert all(conditions["querylimit"] == 1 for _, conditions, _ in fake_qs.single_calls)
    assert outcome.outcomes["left"].error is None
    assert {"id", "val", "extra"} <= set(outcome.frames["left"].columns)


async def test_binary_cells_serialised(fake_qs, linked_source):
    """bytea cells never crash ujson: valid UTF-8 → text, anything else → base64."""
    fake_qs.registry[linked_source.slug] = pd.DataFrame({"blob": [b"\xfa\x01", b"abc", None], "n": [1, 2, 3]})

    outcome = await execute_sources({"activity": linked_source})

    result = outcome.outcomes["activity"]
    assert result.error is None
    assert [r["blob"] for r in result.rows] == ["+gE=", "abc", None]
    assert [r["n"] for r in result.rows] == [1, 2, 3]


def test_map_query_error_tenant_codes():
    """QueryAccessDenied -> (404, "query_not_found") (never "denied"); TenantError codes per the table."""
    from querysource.exceptions import QueryAccessDenied
    from querysource.tenants import TenantError

    denied_status, denied_code = map_query_error(QueryAccessDenied())
    assert (denied_status, denied_code) == (404, "query_not_found")
    assert "denied" not in denied_code

    for error_code, expected in (
        ("tenant_not_available", (404, "tenant_not_available")),
        ("query_not_found", (404, "query_not_found")),
        ("tenant_store_unavailable", (503, "tenant_store_unavailable")),
    ):
        assert map_query_error(TenantError("boom", error_code=error_code)) == expected

    # Chained: RuntimeError(...) from TenantError, with an error_code NOT in the explicit table.
    try:
        try:
            raise TenantError("nope", error_code="tenant_write_forbidden")
        except TenantError as inner:
            raise RuntimeError("wrapped") from inner
    except RuntimeError as chained:
        assert map_query_error(chained) == (502, "data_stage")

    assert map_query_error(ValueError("boom")) == (502, "data_stage")

    for exc in (QueryAccessDenied(), TenantError("x", error_code="query_not_found"), ValueError("y")):
        _, code = map_query_error(exc)
        assert code in ERROR_STATUS


async def test_execute_sources_never_mutates_the_request_filter(fake_qs, monkeypatch):
    """A data source that consumes nested operator dicts (querysource's popitem()) must not empty the
    descriptor's request/conditions filter, which is serialised into the envelope for client refreshes."""
    real_fetch = qsmod.QuerySlugSource.fetch

    async def destructive_fetch(self, **conditions):
        for value in (conditions.get("filter") or {}).values():
            if isinstance(value, dict) and value:
                value.popitem()
        return await real_fetch(self, **conditions)

    monkeypatch.setattr(qsmod.QuerySlugSource, "fetch", destructive_fetch)
    request = SourceRequest(filter={"graduation_details": {"@>": [{"course": "Pilates Mat"}]}}, fields=["count(*)"])
    src = LinkedDataSource(slug="grads", conditions={}, request=request, target="/kpi/rows")
    fake_qs.registry["grads"] = pd.DataFrame({"count": [1]})

    outcome = await execute_sources({"kpi": src})

    assert outcome.outcomes["kpi"].error is None
    assert src.request.filter == {"graduation_details": {"@>": [{"course": "Pilates Mat"}]}}
