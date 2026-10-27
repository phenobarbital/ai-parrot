"""Unit tests for MetricDefinitionsHandler (FEAT-756, TASK-4855) — test_ui_surfaces_handler.py idiom."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from parrot.handlers.metric_definitions import MetricDefinitionsHandler
from parrot.handlers.scope import RequestScope
from parrot.metrics import MetricDefinition

pytestmark = pytest.mark.asyncio


def _body_def(metric_id: str = "revenue", **extra) -> dict:
    return {
        "id": metric_id,
        "name": "Revenue",
        "time": {"binding": {"date_column": "d"}},
        "default_shape": {"component": "KPICard", "value_column": "v"},
        "source": {"kind": "query_slug", "slug": "rev"},
        **extra,
    }


def _definition(metric_id: str = "revenue", owner: str = "user-1", version: int = 1) -> MetricDefinition:
    return MetricDefinition.model_validate(
        {**_body_def(metric_id), "tenant": "acme", "owner": owner, "version": version}
    )


def _scope(**kw) -> RequestScope:
    base = {"user_id": "user-1", "tenant": "acme", "groups": frozenset()}
    base.update(kw)
    return RequestScope(**base)


class _FakeRequest:
    def __init__(self, app, match_info, path, body, user_id, query):
        self.app = app
        self.match_info = match_info
        self.path = path
        self._body = body
        self.user = SimpleNamespace(user_id=user_id) if user_id else None
        self.query = query

    async def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body


def _make_handler(scope, store, *, path="/api/v1/metrics", match_info=None, body=None, user_id="user-1", query=None):
    h = MetricDefinitionsHandler.__new__(MetricDefinitionsHandler)
    h.logger = logging.getLogger("test.metric_definitions")
    h._request = _FakeRequest({"metric_definitions_store": store}, match_info or {}, path, body, user_id, query or {})
    h._scope = AsyncMock(return_value=scope)
    h.json_response = lambda data, status=200, **_: SimpleNamespace(status=status, body=data)
    return h


def _unwrap(method):
    while hasattr(method, "__wrapped__"):
        method = method.__wrapped__
    return method


async def _call(verb: str, h):
    return await _unwrap(getattr(MetricDefinitionsHandler, verb))(h)


async def test_metric_handler_get_list_scope_filter() -> None:
    """list uses list_visible(scope, program=); one → 200 | 404 for invisible; /schema → schema dict."""
    store = SimpleNamespace(list_visible=AsyncMock(return_value=[_definition("revenue")]))
    scope = _scope()

    r = await _call("get", _make_handler(scope, store, query={"program": "p1"}))
    assert r.status == 200 and [d["id"] for d in r.body] == ["revenue"]
    store.list_visible.assert_awaited_with(scope, program="p1")

    r = await _call("get", _make_handler(scope, store, match_info={"metric_id": "revenue"}))
    assert r.status == 200 and r.body["id"] == "revenue"

    r = await _call("get", _make_handler(scope, store, match_info={"metric_id": "hidden"}))
    assert r.status == 404

    r = await _call("get", _make_handler(scope, store, path="/api/v1/metrics/schema"))
    assert r.status == 200 and "properties" in r.body


async def test_metric_handler_post_put_gates() -> None:
    """401 no user / 403 !may_author / 403 global without superuser / 422 tenant in body / 409 dup / 201 / PUT gates."""
    store = SimpleNamespace(save=AsyncMock(return_value="revenue"), get=AsyncMock(return_value=None))
    body = {"definition": _body_def()}

    assert (await _call("post", _make_handler(_scope(), store, body=body, user_id=None))).status == 401
    assert (await _call("post", _make_handler(_scope(may_author=False), store, body=body))).status == 403
    assert (await _call("post", _make_handler(_scope(tenant=None), store, body=body))).status == 403
    bad = {"definition": _body_def(tenant="evil")}
    assert (await _call("post", _make_handler(_scope(), store, body=bad))).status == 422
    assert (await _call("post", _make_handler(_scope(), store, body={"definition": {"id": "x"}}))).status == 422
    store.save.assert_not_awaited()

    r = await _call("post", _make_handler(_scope(), store, body=body))
    assert r.status == 201 and r.body["tenant"] == "acme" and r.body["owner"] == "user-1"
    store.save.assert_awaited_once()

    store.save = AsyncMock(side_effect=ValueError("exists"))
    assert (await _call("post", _make_handler(_scope(), store, body=body))).status == 409

    # PUT
    store.save = AsyncMock(return_value="revenue")
    mi = {"metric_id": "revenue"}
    assert (await _call("put", _make_handler(_scope(), store, body=body, match_info=mi))).status == 404

    store.get = AsyncMock(return_value=_definition(owner="someone-else", version=3))
    assert (await _call("put", _make_handler(_scope(), store, body=body, match_info=mi))).status == 403

    r = await _call("put", _make_handler(_scope(may_administer=True), store, body=body, match_info=mi))
    assert r.status == 200 and r.body["version"] == 4
    assert store.save.await_args.kwargs == {"overwrite": True}

    store.get = AsyncMock(return_value=_definition(owner="user-1"))
    mismatch = {"definition": _body_def("other")}
    assert (await _call("put", _make_handler(_scope(), store, body=mismatch, match_info=mi))).status == 422
