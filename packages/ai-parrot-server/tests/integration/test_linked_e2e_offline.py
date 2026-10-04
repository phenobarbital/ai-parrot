"""FEAT-611 M9 — offline deterministic tier for S1/S3/S5 (FakeQS + fake guard; no Postgres, no QuerySource.setup)."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import parrot.tools.dataset_manager.sources.query_slug as query_slug
from parrot.auth.exceptions import AuthorizationRequired
from parrot.auth.permission import build_principal_context
from parrot.handlers.models.ui_surfaces import PgUISurfaceStore, UISurfaceShare
from parrot.handlers.ui_surfaces_scope import SurfaceScope
from parrot.outputs.a2ui.linked.executor import execute_sources
from parrot.outputs.a2ui.linked.service import LinkedSurfaceService

from .test_linked_surfaces_e2e import _decode, _FakeAsyncDB, _get, _handler, _post, _StubResolver

pytestmark = pytest.mark.asyncio
REPO = Path(__file__).resolve().parents[4]
EXAMPLE = REPO / "examples/agents/a2ui/linked_e2e"
ACTIVITY_SLUG = "epson_e2e_activity"  # == dashboard_tool / run_e2e / seed_staging ACTIVITY_SLUG
TARGETS_SLUG = "epson_e2e_targets"
ACTIVITY = pd.DataFrame(
    {
        "day": ["2026-09-01", "2026-09-02"],
        "visits": [10, 20],
        "program": ["epson", "pokemon"],
        "store_id": [1, 2],
    }
)
TARGETS = pd.DataFrame({"program": ["epson", "pokemon"], "target": [100, 50]})


def _load(name: str):
    """Load an example module by path (examples/ is not a package); registered so dataclasses resolve."""
    module_name = f"linked_e2e_{name}"
    spec = importlib.util.spec_from_file_location(module_name, EXAMPLE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fake_qs(monkeypatch):
    """Slug-keyed FakeQS + FakeMultiQS; records kwargs (tenant!) per execution."""
    state = SimpleNamespace(
        kwargs=[],
        frames={ACTIVITY_SLUG: ACTIVITY, TARGETS_SLUG: TARGETS},
        multi={"result": ACTIVITY, "targets": TARGETS},
    )

    class FakeQS:
        def __init__(self, **kwargs):
            state.kwargs.append(kwargs)
            self._slug = kwargs["slug"]

        async def query(self, output_format=None):
            return state.frames[self._slug].copy(), None

        async def close(self):
            return None

    class FakeMultiQS(FakeQS):
        async def query(self, output_format=None):
            return dict(state.multi), None

    monkeypatch.setattr(query_slug, "_get_qs", lambda: FakeQS)
    monkeypatch.setattr(query_slug, "_get_multiqs", lambda: FakeMultiQS)
    return state


class _Guard:
    """Recording guard; denies `source_type:source_id` keys in `deny` (test_service.py:23-34 pattern)."""

    def __init__(self, deny: set[str] | None = None) -> None:
        self.deny, self.calls = deny or set(), []

    async def authorize_source(self, ctx, resources):
        self.calls.append((getattr(ctx, "session", ctx), resources.source_type, resources.source_id))
        if f"{resources.source_type}:{resources.source_id}" in self.deny:
            raise AuthorizationRequired(tool_name="dataplane_authz", message="denied")

    async def rls_predicates(self, ctx, resources):
        return []


@pytest.fixture
def store(monkeypatch):
    """Real PgUISurfaceStore over the duplicated fake connection + in-memory share methods."""
    state = SimpleNamespace(surfaces={}, ddl_calls=[], shares={})
    value = PgUISurfaceStore(dsn="postgres://fake/linked-e2e-offline")
    monkeypatch.setattr(value, "_get_db", lambda: _FakeAsyncDB(state))

    async def mint_share(surface_id, *, expires_at=None, use_default_ttl=False):
        share = UISurfaceShare(token=f"tok-{len(state.shares)}", surface_id=surface_id, created_at=datetime.now(UTC))
        state.shares[share.token] = share
        return share

    async def resolve_share(token):
        return state.shares.get(token)

    async def claim_share(token, user_id):
        return None

    for name, fn in (("mint_share", mint_share), ("resolve_share", resolve_share), ("claim_share", claim_share)):
        monkeypatch.setattr(value, name, fn)
    return value


def _app(store, guard=None, *, user_id="owner-1"):
    app = {
        "ui_surfaces_store": store,
        "ui_surfaces_scope_resolver": _StubResolver(SurfaceScope(user_id=user_id, tenant=None, groups=frozenset())),
    }
    if guard is not None:
        app["linked_surface_service"] = LinkedSurfaceService(guard=guard)
    return app


async def _publish(app, envelope, title="S1"):
    resp = await _post(
        _handler(app, path="/api/v1/ui/surfaces", json_body={"kind": "dashboard", "title": title, "envelope": envelope})
    )
    return resp.status, await _decode(resp)


async def _refresh(app, sid, params, *, user_id="owner-1", query=None):
    resp = await _post(
        _handler(
            app,
            match_info={"surface_id": sid},
            path=f"/api/v1/ui/surfaces/{sid}/refresh",
            json_body={"params": params},
            user_id=user_id,
            query=query,
        )
    )
    return resp, await _decode(resp)


def _has_html_renderer() -> bool:
    try:
        import parrot.outputs.a2ui_renderers.interactive_html  # noqa: F401
    except ImportError:
        return False
    return True


def _activity_calls(fake_qs):
    return [kw for kw in fake_qs.kwargs if kw["slug"] == ACTIVITY_SLUG]


async def test_s1_server_lane_offline(fake_qs, store, monkeypatch):
    """Publish → GET → refresh(params) → share → bearer refresh; plus 403 / 409 / warnings (spec §4)."""
    tool = _load("dashboard_tool")
    envelope = (await tool.build_epson_activity_dashboard(snapshot=False))["a2ui_envelope"]
    guard = _Guard()
    app = _app(store, guard)
    fake_qs.kwargs.clear()
    status, body = await _publish(app, envelope)
    assert status == 201, body
    sid = body["surface_id"]
    assert fake_qs.kwargs, "the server snapshots the snapshot=False envelope once, under the owner pctx"
    assert {call[0].user_id for call in guard.calls} == {"owner-1"}

    # GET json (+ html when the visualizations satellite is installed) never executes.
    executed = len(fake_qs.kwargs)
    resp = await _get(_handler(app, match_info={"surface_id": sid}))
    assert resp.status == 200
    persisted = (await _decode(resp))["envelope"]
    assert persisted["dataModel"]["activity"]["rows"] and persisted["dataModel"]["targets"]["rows"]
    if _has_html_renderer():
        html = await _get(_handler(app, match_info={"surface_id": sid}, query={"format": "html"}))
        assert html.status == 200
    assert len(fake_qs.kwargs) == executed

    # Broadcast refresh params reach the activity slug's conditions.
    resp, body = await _refresh(app, sid, {"firstdate": "2026-09-02", "lastdate": "2026-09-03"})
    assert resp.status == 200, body
    conditions = _activity_calls(fake_qs)[-1]["conditions"]
    assert conditions["firstdate"] == "2026-09-02" and conditions["lastdate"] == "2026-09-03"
    assert body["envelope"]["dataModel"]["activity"]["rows"]

    # A per-source undeclared param is ignored and reported in the warnings header.
    resp, _ = await _refresh(app, sid, {"activity": {"store_id": 7}})
    assert resp.status == 200
    warnings = json.loads(resp.headers["X-Parrot-Refresh-Warnings"])
    assert any("activity" in w and "store_id" in w for w in warnings)

    # Share mint → a second (logged-in) user refreshes with ?share=<token>, under the OWNER's pctx.
    resp = await _post(
        _handler(app, match_info={"surface_id": sid}, path=f"/api/v1/ui/surfaces/{sid}/share", json_body={})
    )
    assert resp.status == 201
    token = (await _decode(resp))["token"]
    viewer_app = _app(store, guard, user_id="viewer-2")
    resp, _ = await _refresh(viewer_app, sid, {}, user_id="viewer-2")
    assert resp.status == 404, "without the token the viewer has no access"
    guard.calls.clear()
    resp, body = await _refresh(viewer_app, sid, {}, user_id="viewer-2", query={"share": token})
    assert resp.status == 200, body
    assert guard.calls and {call[0].user_id for call in guard.calls} == {"owner-1"}
    resp, _ = await _refresh(viewer_app, sid, {}, user_id="viewer-2", query={"share": "tok-bogus"})
    assert resp.status == 410

    # 403: no guard at all (neither linked_surface_service nor dataplane_guard) — publish and refresh.
    no_guard = _app(store)
    status, body = await _publish(no_guard, envelope, "no guard")
    assert status == 403 and "data-plane guard" in body["message"]
    resp, body = await _refresh(no_guard, sid, {})
    assert resp.status == 403 and body["message"] == "Linked surfaces require a data-plane guard"

    # 403: a guard that denies the activity slug — publish and refresh.
    deny = _app(store, _Guard(deny={f"query_slug:public:{ACTIVITY_SLUG}"}))
    status, body = await _publish(deny, envelope, "denied")
    assert status == 403 and body["message"] == "Data source not permitted"
    resp, body = await _refresh(deny, sid, {})
    assert resp.status == 403 and body["message"] == "Data source not permitted"

    # 409: a baked, non-recipe surface is not refreshable.
    run_e2e = _load("run_e2e")
    status, body = await _publish(app, run_e2e.static_envelope(), "static")
    assert status == 201
    resp, body = await _refresh(app, body["surface_id"], {})
    assert resp.status == 409 and body["refreshable"] is False

    # 409: a conditional write that loses its race returns the newer snapshot (lose_race, not gather).
    record = await store.get(sid)
    raw = next(row for row in store._get_db().state.surfaces.values() if str(row["surface_id"]) == sid)

    async def lose_race(*args, **kwargs):
        raw["updated_at"] = record.updated_at + timedelta(seconds=1)
        return False

    monkeypatch.setattr(store, "update_envelope", lose_race)
    resp, body = await _refresh(app, sid, {})
    assert resp.status == 409
    assert body["status"] == "error" and body["error"] == "stale refresh" and body["snapshot_at"]


def _mq_sources(run_e2e, multi_output):
    return {"mq": run_e2e.mq_source(multi_output)}


async def test_s3_multiquery_frames(fake_qs):
    """multi_output / 'result' fallback / ambiguous-or-missing → data_stage (execute_sources, spec §4)."""
    run_e2e = _load("run_e2e")
    records = {
        "targets": json.loads(TARGETS.to_json(orient="records")),
        None: json.loads(ACTIVITY.to_json(orient="records")),
    }
    for multi_output, expected in records.items():
        outcome = await execute_sources(_mq_sources(run_e2e, multi_output))
        result = outcome.outcomes["mq"]
        assert result.error is None, multi_output
        assert result.rows == expected
        assert fake_qs.kwargs[-1]["slug"] == run_e2e.MQ_SLUG

    outcome = await execute_sources(_mq_sources(run_e2e, "nope"))
    assert outcome.outcomes["mq"].error == "data_stage"

    fake_qs.multi = {"a": ACTIVITY, "b": TARGETS}  # ambiguous: no 'result', no multi_output
    outcome = await execute_sources(_mq_sources(run_e2e, None))
    assert outcome.outcomes["mq"].error == "data_stage"


async def test_s5_tenant_descriptor(fake_qs):
    """tenant='public' reaches QS as tenant='public' and yields the same rows as the tenant=None descriptor."""
    import parrot.outputs.a2ui.builders  # noqa: F401 — registers the catalog components

    run_e2e = _load("run_e2e")
    guard = _Guard()
    service = LinkedSurfaceService(guard=guard)
    pctx = build_principal_context("owner-1", channel="ui_surfaces")
    chart = {
        "id": "root",
        "component": "Chart",
        "type": "bar",
        "x": "day",
        "y": ["visits"],
        "data": {"path": "/activity/rows"},
    }

    rows, kwargs = {}, {}
    for label, tenant in (("default", None), ("public", "public")):
        envelope = run_e2e.linked_envelope(f"s5-{label}", [chart], {"activity": run_e2e.activity_source(tenant)})
        outcome = await service.refresh(envelope, params={"firstdate": "FDOM", "lastdate": "TODAY"}, owner_pctx=pctx)
        assert outcome.error_status is None and not outcome.warnings, outcome.warnings
        rows[label] = outcome.envelope["dataModel"]["activity"]["rows"]
        kwargs[label] = fake_qs.kwargs[-1]

    assert rows["default"] and rows["default"] == rows["public"]
    assert "tenant" not in kwargs["default"]  # QuerySlugSource._qs_kwargs drops None (query_slug.py:106-110)
    assert kwargs["public"]["tenant"] == "public"
    owner_checks = [call for call in guard.calls if call[1] == "query_slug"]
    assert len(owner_checks) == 2
    assert {call[2] for call in owner_checks} == {f"public:{ACTIVITY_SLUG}"}  # service.py:100 — both map to public
    assert {call[0].user_id for call in owner_checks} == {"owner-1"}


async def test_run_e2e_offline_contract(monkeypatch):
    """The runner's envelopes validate as TOOL output; it refuses non-live ENVs; SKIP never counts as a pass."""
    import parrot.outputs.a2ui.builders  # noqa: F401 — registers the catalog components
    from parrot.outputs.a2ui.catalog import ProducerOrigin, validate_envelope
    from parrot.outputs.a2ui.linked import has_data_sources
    from parrot.outputs.a2ui.models import CreateSurface

    run_e2e = _load("run_e2e")
    table = {"id": "root", "component": "DataTable", "data": {"path": "/mq/rows"}}
    chart = {
        "id": "root",
        "component": "Chart",
        "type": "bar",
        "x": "day",
        "y": ["visits"],
        "data": {"path": "/activity/rows"},
    }
    for envelope in (
        run_e2e.linked_envelope("s3", [table], {"mq": run_e2e.mq_source("targets")}),
        run_e2e.linked_envelope("s5", [chart], {"activity": run_e2e.activity_source("public")}),
    ):
        validate_envelope(CreateSurface.model_validate(envelope), origin=ProducerOrigin.TOOL)
    assert not has_data_sources(CreateSurface.model_validate(run_e2e.static_envelope()))

    result = run_e2e.ScenarioResult
    assert run_e2e.verdict([]) == 1
    assert run_e2e.verdict([result("a", False, "", skipped=True)]) == 1
    assert run_e2e.verdict([result("a", True, ""), result("b", False, "", skipped=True)]) == 0
    assert run_e2e.verdict([result("a", True, ""), result("b", False, "")]) == 1

    monkeypatch.setenv("ENV", "production")
    assert run_e2e.main(["--scenarios", "s1"]) == 2
    monkeypatch.delenv("ENV")
    assert run_e2e.main(["--scenarios", "s1"]) == 2


async def test_run_e2e_live_targets_and_ranges(monkeypatch):
    """staging and dev are the live targets; dev defaults to date ranges that hold data (2025-03)."""
    run_e2e = _load("run_e2e")
    tool = _load("dashboard_tool")
    seed = _load("seed_staging")
    assert run_e2e.LIVE_ENVS == seed.LIVE_ENVS == ("staging", "dev")
    assert run_e2e.ACTIVITY_SLUG == tool.ACTIVITY_SLUG == seed.ACTIVITY_SLUG
    assert tool.TARGETS_SLUG == seed.TARGETS_SLUG and run_e2e.MQ_SLUG == seed.MQ_SLUG
    monkeypatch.delenv("E2E_RANGE", raising=False)

    monkeypatch.setenv("ENV", "staging")
    assert run_e2e.s2_default_ranges() == ("FDOM:TODAY", "YESTERDAY:YESTERDAY")
    assert run_e2e.live_range() == ("FDOM", "TODAY")

    monkeypatch.setenv("ENV", "dev")
    assert run_e2e.s2_default_ranges() == ("2025-03-01:2025-03-07", "2025-03-11:2025-03-15")
    assert run_e2e.live_range() == ("2025-03-01", "2025-03-07")
    assert run_e2e.activity_source(None).request.placeholders == {"firstdate": "2025-03-01", "lastdate": "2025-03-07"}
    monkeypatch.setenv("E2E_RANGE", "2025-03-11:2025-03-15")
    assert run_e2e.mq_source("targets").request.placeholders == {"firstdate": "2025-03-11", "lastdate": "2025-03-15"}

    # dev passes the ENV guard and stops only at the missing credentials (still exit 2, no network).
    monkeypatch.delenv("E2E_USER", raising=False)
    assert run_e2e.main(["--scenarios", "s1"]) == 2
