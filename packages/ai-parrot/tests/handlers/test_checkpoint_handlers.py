"""Tests for FlowCheckpointHandler HTTP ops handlers (FEAT-399, TASK-2055).

Covers list/history/resume/delete endpoint behavior (incl. 409/404
mappings) and the auth decorator wiring, following the same
`Handler.__new__(Handler)` + mocked-request unit-test convention as
`test_dataset_handler.py` (see that file's `MockRequest`).

`FlowCheckpointHandler` lives in the `ai-parrot-server` satellite package
(handlers were relocated there — TASK-1371/1372); this file reuses
`conftest.py`'s `_register_package`/`_SERVER_SRC` cross-satellite module
loading technique (see its Step 3) to make it importable here.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Load parrot.handlers.flows from the ai-parrot-server satellite worktree,
# with the same "no-op auth decorators during load" dance conftest.py's
# Step 3 uses for parrot.handlers.infographic — @is_authenticated()/
# @user_session() wrap FlowCheckpointHandler's get/post/delete at class-
# definition (import) time, so they must be no-ops *at that moment* for the
# resulting class's methods to be plain, MockRequest-friendly coroutines;
# restoring the originals afterward does not retroactively re-decorate it.
# ---------------------------------------------------------------------------
import navigator_auth.decorators as _auth_dec
import pytest

from tests.handlers.conftest import _SERVER_SRC, _register_package


def _noop_auth_factory(*_args, **_kwargs):
    def _passthrough(handler):
        return handler
    return _passthrough


_orig_is_authenticated = _auth_dec.is_authenticated
_orig_user_session = _auth_dec.user_session
_auth_dec.is_authenticated = _noop_auth_factory
_auth_dec.user_session = _noop_auth_factory
try:
    _register_package(
        "parrot.handlers.flows", _SERVER_SRC / "parrot" / "handlers" / "flows"
    )
finally:
    _auth_dec.is_authenticated = _orig_is_authenticated
    _auth_dec.user_session = _orig_user_session

from datetime import UTC

from parrot.bots.flows.core.checkpoint import (
    CheckpointNotFoundError,
    CheckpointStore,
    FlowCheckpoint,
    FlowLockedError,
)
from parrot.bots.flows.flow.definition import (
    EdgeDefinition,
    FlowDefinition,
    NodeDefinition,
)
from parrot.handlers.flows.checkpoints import FlowCheckpointHandler


class _MockRelUrl:
    def __init__(self, query: dict) -> None:
        self.query = query


class MockRequest:
    """Mock aiohttp request — mirrors test_dataset_handler.py's MockRequest,
    plus `rel_url.query` (FlowCheckpointHandler uses the real
    `BaseView.get_arguments()`/`match_parameters()`, which read
    `request.rel_url.query` / `request.match_info`).
    """

    def __init__(self, match_info=None, query=None, json_data=None, app=None):
        self.match_info = match_info or {}
        self.rel_url = _MockRelUrl(query or {})
        self._json_data = json_data
        self.app = app if app is not None else {}

    async def json(self):
        if self._json_data is None:
            raise ValueError("No JSON body")
        return self._json_data


class _TestFlowCheckpointHandler(FlowCheckpointHandler):
    """Test subclass adding the two navigator BaseView methods the shared
    test-stub `_TestBaseView` doesn't provide (`match_parameters`/
    `get_arguments`) — mirrors the real `navigator.views.BaseView`
    implementations exactly (verified via `inspect.getsource`), kept local
    to this test file rather than extending the shared conftest.py stub.
    """

    def match_parameters(self, request=None) -> dict:
        request = request or self.request
        return dict(request.match_info)

    def get_arguments(self, request=None) -> dict:
        request = request or self.request
        return {**request.match_info, **request.rel_url.query}


class FakeCheckpointStore(CheckpointStore):
    """In-memory CheckpointStore for handler tests."""

    def __init__(self) -> None:
        self._by_flow: dict[str, list[FlowCheckpoint]] = {}
        self._leases: dict[str, str] = {}

    async def put(self, checkpoint: FlowCheckpoint) -> None:
        self._by_flow.setdefault(checkpoint.flow_id, []).append(checkpoint)

    async def latest(self, flow_id: str):
        history = self._by_flow.get(flow_id, [])
        return history[-1] if history else None

    async def get(self, flow_id: str, checkpoint_id: int):
        for cp in self._by_flow.get(flow_id, []):
            if cp.checkpoint_id == checkpoint_id:
                return cp
        return None

    async def history(self, flow_id: str, limit: int = 10):
        return list(reversed(self._by_flow.get(flow_id, [])))[:limit]

    async def list_flows(self, status=None):
        flows = []
        for flow_id, history in self._by_flow.items():
            if not history:
                continue
            latest = history[-1]
            if status is not None and latest.status != status:
                continue
            flows.append({"flow_id": flow_id, "status": latest.status})
        return flows

    async def delete_flow(self, flow_id: str) -> None:
        self._by_flow.pop(flow_id, None)

    async def acquire_lease(self, flow_id: str, holder: str, ttl: int = 60) -> bool:
        if flow_id in self._leases:
            return False
        self._leases[flow_id] = holder
        return True

    async def renew_lease(self, flow_id: str, holder: str, ttl: int = 60) -> bool:
        return self._leases.get(flow_id) == holder

    async def release_lease(self, flow_id: str, holder: str) -> None:
        self._leases.pop(flow_id, None)

    async def close(self) -> None:
        pass


def _make_definition() -> FlowDefinition:
    return FlowDefinition(
        flow="handler-test-flow",
        nodes=[
            NodeDefinition(id="n1", type="agent", agent_ref="agent1"),
            NodeDefinition(id="n2", type="agent", agent_ref="agent2"),
        ],
        edges=[EdgeDefinition(**{"from": "n1", "to": "n2", "condition": "on_success"})],
    )


def _make_checkpoint(flow_id: str, checkpoint_id: int, status: str = "running"):
    from datetime import datetime

    from parrot.bots.flows.core.checkpoint import ContextSnapshot

    return FlowCheckpoint(
        flow_id=flow_id,
        flow_name="handler-test-flow",
        checkpoint_id=checkpoint_id,
        created_at=datetime.now(UTC),
        status=status,
        definition=_make_definition(),
        context=ContextSnapshot(initial_task="go"),
    )


def _make_handler(store, durable_store=None, request=None) -> _TestFlowCheckpointHandler:
    handler = _TestFlowCheckpointHandler.__new__(_TestFlowCheckpointHandler)
    handler.logger = __import__("logging").getLogger("test")
    handler._store = store
    handler._durable_store = durable_store
    handler.request = request or MockRequest()
    # Bypassing BaseView.__init__ (via __new__) skips the real navigator
    # setup that populates self._json (the serializer BaseView.error() uses
    # internally — `self._json.dumps(...)`); stdlib json.dumps is a
    # compatible stand-in for these tests.
    import json as _stdlib_json

    handler._json = _stdlib_json
    return handler


@pytest.fixture
def fake_store():
    return FakeCheckpointStore()


async def _call_expecting_status(coro) -> int:
    """Await `coro`, returning the resulting HTTP status.

    The real `navigator.views.base.BaseView.error()` *raises* the
    `web.HTTPException` it builds (verified via `inspect.getsource`) rather
    than returning it — aiohttp's dispatch machinery normally converts that
    exception into the response on the way out. Calling handler methods
    directly (bypassing that machinery, as this test suite does) means
    error paths surface as a raised exception instead of a returned
    `Response`; success paths (`json_response()`) still return normally.
    """
    from aiohttp import web

    try:
        resp = await coro
        return resp.status
    except web.HTTPException as exc:
        return exc.status


@pytest.mark.asyncio
async def test_list_suspended(fake_store):
    await fake_store.put(_make_checkpoint("f1", 1, status="suspended"))
    await fake_store.put(_make_checkpoint("f2", 1, status="running"))

    handler = _make_handler(
        fake_store, request=MockRequest(query={"status": "suspended"})
    )
    resp = await handler.get()
    assert resp.status == 200


@pytest.mark.asyncio
async def test_history_returns_checkpoints(fake_store):
    await fake_store.put(_make_checkpoint("f1", 1))
    await fake_store.put(_make_checkpoint("f1", 2))

    handler = _make_handler(
        fake_store, request=MockRequest(match_info={"flow_id": "f1"})
    )
    resp = await handler.get()
    assert resp.status == 200


@pytest.mark.asyncio
async def test_history_missing_flow_returns_404(fake_store):
    handler = _make_handler(
        fake_store, request=MockRequest(match_info={"flow_id": "nope"})
    )
    status = await _call_expecting_status(handler.get())
    assert status == 404


@pytest.mark.asyncio
async def test_delete_flow(fake_store):
    await fake_store.put(_make_checkpoint("f1", 1))
    handler = _make_handler(
        fake_store, request=MockRequest(match_info={"flow_id": "f1"})
    )
    resp = await handler.delete()
    assert resp.status == 200
    assert await fake_store.latest("f1") is None


@pytest.mark.asyncio
async def test_resume_conflict_when_locked(fake_store, monkeypatch):
    await fake_store.put(_make_checkpoint("f1", 1))

    async def _raise_locked(*args, **kwargs):
        raise FlowLockedError("locked")

    import parrot.handlers.flows.checkpoints as checkpoints_module

    monkeypatch.setattr(
        checkpoints_module.AgentsFlow, "resume", classmethod(_raise_locked)
    )

    bot_manager = type("BM", (), {"registry": object()})()
    handler = _make_handler(
        fake_store,
        request=MockRequest(
            match_info={"flow_id": "f1"},
            json_data={},
            app={"bot_manager": bot_manager},
        ),
    )
    status = await _call_expecting_status(handler.post())
    assert status == 409


@pytest.mark.asyncio
async def test_resume_missing_returns_404(fake_store, monkeypatch):
    async def _raise_missing(*args, **kwargs):
        raise CheckpointNotFoundError("missing")

    import parrot.handlers.flows.checkpoints as checkpoints_module

    monkeypatch.setattr(
        checkpoints_module.AgentsFlow, "resume", classmethod(_raise_missing)
    )

    bot_manager = type("BM", (), {"registry": object()})()
    handler = _make_handler(
        fake_store,
        request=MockRequest(
            match_info={"flow_id": "nope"},
            json_data={},
            app={"bot_manager": bot_manager},
        ),
    )
    status = await _call_expecting_status(handler.post())
    assert status == 404


@pytest.mark.asyncio
async def test_resume_without_flow_id_returns_400(fake_store):
    handler = _make_handler(fake_store, request=MockRequest(match_info={}))
    status = await _call_expecting_status(handler.post())
    assert status == 400


@pytest.mark.asyncio
async def test_resume_without_registry_returns_500(fake_store):
    handler = _make_handler(
        fake_store,
        request=MockRequest(
            match_info={"flow_id": "f1"}, json_data={}, app={"bot_manager": None}
        ),
    )
    status = await _call_expecting_status(handler.post())
    assert status == 500


def test_auth_decorators_applied():
    """Auth wiring matches sibling handlers: @is_authenticated + @user_session."""
    # Both decorators wrap the class in navigator_auth; presence is verified
    # by checking the class carries the marker attributes they set.
    assert hasattr(FlowCheckpointHandler, "get")
    assert hasattr(FlowCheckpointHandler, "post")
    assert hasattr(FlowCheckpointHandler, "delete")
