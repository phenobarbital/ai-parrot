"""Integration tests for examples/dev_loop/server_dev.py (FEAT-412, TASK-2129).

Loads the example module via importlib (the established pattern from
``test_examples_form.py``) and drives it with ``aiohttp_client``. ``_on_startup``
is replaced by a fake wiring step so no Redis, dispatcher or Jira env is
needed — what is under test is the console's HTTP surface: the dev-only
``/api/config`` shape, brief building for all three intents, the per-run
plan-gate flag, and the mounted gate-resolution route.
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from aiohttp import web
from parrot.bots.flows.core.result import FlowResult
from parrot.bots.flows.core.types import FlowStatus
from parrot.flows.dev_flow.models import DevRequestBrief
from parrot.flows.dev_flow.runner import DevFlowRunner
from parrot.flows.dev_loop.models import FeatureBrief

_REPO_ROOT = Path(__file__).resolve().parents[5]


def _load_module(name: str, filename: str):
    path = _REPO_ROOT / "examples" / "dev_loop" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def server_dev():
    return _load_module("dev_flow_server_dev", "server_dev.py")


class _StubFlow:
    """Records the contexts it is handed; completes immediately."""

    def __init__(self) -> None:
        self.contexts: list[Any] = []
        self._run_id_holder: dict[str, str] = {}

    async def run_flow(self, ctx, **kwargs) -> FlowResult:
        self.contexts.append(ctx)
        return FlowResult(
            output=ctx.shared_data["run_id"], status=FlowStatus.COMPLETED
        )


class _GateFlow:
    """Opens an `open_questions` gate and blocks until it resolves."""

    def __init__(self) -> None:
        self.gate_ids: dict[str, str] = {}
        self._run_id_holder: dict[str, str] = {}
        self.answers: dict[str, str] = {}

    async def run_flow(self, ctx, **kwargs) -> FlowResult:
        run_id = ctx.shared_data["run_id"]
        host = ctx.shared_data["session_host"]
        gate_id, _ = host.open_gate(
            kind="open_questions", node_id="ideation",
            title="Open questions — sdd/proposals/x.brainstorm.md",
            questions=["Which store?"], ttl_seconds=None, on_expiry="fail",
        )
        self.gate_ids[run_id] = gate_id
        gate = await host.wait_gate(gate_id)
        self.answers = dict(gate.answers)
        status = (
            FlowStatus.COMPLETED if gate.status == "approved" else FlowStatus.FAILED
        )
        return FlowResult(output=run_id, status=status)


@pytest.fixture
def make_client(server_dev, aiohttp_client):
    """Build a test client whose startup is stubbed (no Redis/dispatcher)."""

    async def _make(flow=None):
        flow = flow if flow is not None else _StubFlow()
        app = server_dev.build_app(redis_url="redis://x")
        # Drop the real startup/cleanup and wire the app keys by hand.
        app.on_startup.clear()
        app.on_cleanup.clear()

        runner = DevFlowRunner(flow, redis_url="redis://x")
        app["runner"] = runner
        app["dev_loop_runner"] = runner
        app["flow"] = flow
        app["flow_tasks"] = {}
        app["wiki_search"] = None
        app["jira_toolkit"] = None
        app["codereview_agent_key"] = "parallel"
        app["development_pool_max"] = 4
        app["require_plan_approval"] = False
        client = await aiohttp_client(app)
        client.app_flow = flow  # type: ignore[attr-defined]
        client.app_runner = runner  # type: ignore[attr-defined]
        return client

    return _make


async def _wait_for_context(flow, timeout: float = 2.0):
    """Wait until the background run task has entered the flow."""
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if flow.contexts:
            return flow.contexts[-1]
        await asyncio.sleep(0.01)
    raise AssertionError("flow was never entered")


# ---------------------------------------------------------------------------
# Static + config
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_index_serves_dev_html(server_dev):
    """GET / must serve dev.html — never the ops console."""
    # Behavioral, not source-scanning: call the handler and inspect the path
    # of the FileResponse it builds. (dev.html itself lands in TASK-2130, so
    # a client GET would 404 on the missing file until then.)
    response = await server_dev.handle_index(MagicMock())

    assert isinstance(response, web.FileResponse)
    assert response._path.name == "dev.html"
    assert response._path.parent == server_dev.STATIC_DIR


@pytest.mark.asyncio
async def test_config_shape_no_ops_keys(make_client):
    client = await make_client()
    resp = await client.get("/api/config")
    assert resp.status == 200
    data = await resp.json()

    # The three dev intents, and only those.
    assert [k["value"] for k in data["kinds"]] == [
        "enhancement", "new_feature", "feature",
    ]
    # No observability / mandatory-Jira defaults anywhere.
    defaults = data["defaults"]
    for absent in ("log_group", "time_window_minutes", "jira_project"):
        assert absent not in defaults
    assert "shell_criteria_heads" not in data
    assert "feature_mode" not in data

    # Dev-flow knobs present.
    assert defaults["ideation_max_rounds"] == 2
    assert defaults["gate_ttl_questions"] == 86400
    assert defaults["require_plan_approval"] is False
    assert data["document_kinds"] == ["brainstorm", "proposal", "spec"]
    assert data["nl_kinds"] == ["enhancement", "new_feature"]
    # The gate-resolution route is advertised to the UI.
    assert data["gate_resolve_url_template"] == (
        "/api/flow/{run_id}/gates/{gate_id}/resolve"
    )


# ---------------------------------------------------------------------------
# Brief building (pure function)
# ---------------------------------------------------------------------------


def test_build_dev_brief_enhancement(server_dev):
    brief = server_dev._build_dev_brief_from_form(
        {"kind": "enhancement", "title": "t", "description": "d"}
    )
    assert isinstance(brief, DevRequestBrief)
    assert brief.kind == "enhancement"


def test_build_dev_brief_normalises_labels(server_dev):
    for label in ("New Feature", "new feature", "NEW_FEATURE", "new-feature"):
        brief = server_dev._build_dev_brief_from_form(
            {"kind": label, "title": "t", "description": "d"}
        )
        assert brief.kind == "new_feature"


def test_build_dev_brief_feature_delegates(server_dev, tmp_path):
    doc = tmp_path / "x.proposal.md"
    doc.write_text("# p", encoding="utf-8")
    brief = server_dev._build_dev_brief_from_form(
        {
            "kind": "feature",
            "document_path": str(doc),
            "document_kind": "proposal",
        }
    )
    assert isinstance(brief, FeatureBrief)
    assert brief.document_kind == "proposal"


def test_build_dev_brief_requires_title_and_description(server_dev):
    with pytest.raises(ValueError, match="title is required"):
        server_dev._build_dev_brief_from_form(
            {"kind": "enhancement", "description": "d"}
        )
    with pytest.raises(ValueError, match="description is required"):
        server_dev._build_dev_brief_from_form(
            {"kind": "enhancement", "title": "t"}
        )


def test_build_dev_brief_rejects_bug_kind(server_dev):
    with pytest.raises(ValueError, match="kind must be"):
        server_dev._build_dev_brief_from_form(
            {"kind": "bug", "title": "t", "description": "d"}
        )


def test_build_dev_brief_optional_fields(server_dev):
    brief = server_dev._build_dev_brief_from_form(
        {
            "kind": "enhancement",
            "title": "t",
            "description": "d",
            "context": "see PR",
            "jira_issue_key": "PARROT-1",
            "dev_agents": [{"agent": "claude-code", "count": 2}],
            "judge_panel": [{"agent": "codex"}],
        }
    )
    assert brief.context == "see PR"
    assert brief.jira_issue_key == "PARROT-1"
    assert brief.dev_agents[0].count == 2
    assert brief.judge_panel is not None


def test_dev_brief_builder_ignores_bug_fields(server_dev):
    """affected_component/log_sources/reporter have no effect here."""
    brief = server_dev._build_dev_brief_from_form(
        {
            "kind": "enhancement", "title": "t", "description": "d",
            "affected_component": "etl/x.yaml",
            "log_sources": [{"kind": "cloudwatch", "locator": "/etl/x"}],
            "reporter": "a@b.c", "escalation_assignee": "d@e.f",
        }
    )
    assert not hasattr(brief, "affected_component")
    assert not hasattr(brief, "log_sources")


# ---------------------------------------------------------------------------
# POST /api/flow/run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_enhancement_brief_built(make_client):
    client = await make_client()
    resp = await client.post(
        "/api/flow/run",
        json={"kind": "enhancement", "title": "telemetry", "description": "d"},
    )

    assert resp.status == 200
    data = await resp.json()
    assert data["run_id"].startswith("run-")
    assert data["mode"] == "dev-flow"
    assert data["kind"] == "enhancement"
    assert data["ws_url"] == f"/api/flow/{data['run_id']}/ws"
    assert data["state_ws_url"].endswith("?view=state")
    assert data["bundle_url"] == f"/api/flow/{data['run_id']}/bundle"
    assert "gates/{gate_id}/resolve" in data["gate_resolve_url"]

    ctx = await _wait_for_context(client.app_flow)
    assert isinstance(ctx.shared_data["dev_brief"], DevRequestBrief)
    assert "feature_brief" not in ctx.shared_data


@pytest.mark.asyncio
async def test_run_feature_brief_built(make_client, tmp_path):
    doc = tmp_path / "idea.brainstorm.md"
    doc.write_text("# b", encoding="utf-8")
    client = await make_client()

    resp = await client.post(
        "/api/flow/run",
        json={
            "kind": "feature",
            "document_path": str(doc),
            "document_kind": "brainstorm",
        },
    )

    assert resp.status == 200
    assert (await resp.json())["kind"] == "feature"
    ctx = await _wait_for_context(client.app_flow)
    assert isinstance(ctx.shared_data["feature_brief"], FeatureBrief)


@pytest.mark.asyncio
async def test_run_missing_description_400(make_client):
    client = await make_client()
    resp = await client.post(
        "/api/flow/run", json={"kind": "enhancement", "title": "t"}
    )
    assert resp.status == 400
    assert "description is required" in (await resp.json())["error"]


@pytest.mark.asyncio
async def test_run_rejects_bug_kind_400(make_client):
    client = await make_client()
    resp = await client.post(
        "/api/flow/run",
        json={"kind": "bug", "title": "t", "description": "d"},
    )
    assert resp.status == 400


@pytest.mark.asyncio
async def test_run_invalid_body_400(make_client):
    client = await make_client()
    assert (
        await client.post("/api/flow/run", data="not json")
    ).status == 400
    assert (await client.post("/api/flow/run", json=["a"])).status == 400


# ---------------------------------------------------------------------------
# Per-run plan-approval toggle (TASK-2123 seam)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_approval_flag_in_extra_shared(make_client):
    client = await make_client()
    await client.post(
        "/api/flow/run",
        json={
            "kind": "enhancement", "title": "t", "description": "d",
            "require_plan_approval": True,
        },
    )
    ctx = await _wait_for_context(client.app_flow)
    assert ctx.shared_data["require_plan_approval"] is True


@pytest.mark.asyncio
async def test_plan_approval_false_is_forwarded(make_client):
    """An explicit False must reach shared state (it suppresses the gate)."""
    client = await make_client()
    await client.post(
        "/api/flow/run",
        json={
            "kind": "enhancement", "title": "t", "description": "d",
            "require_plan_approval": False,
        },
    )
    ctx = await _wait_for_context(client.app_flow)
    assert ctx.shared_data["require_plan_approval"] is False


@pytest.mark.asyncio
async def test_absent_plan_approval_not_in_extra_shared(make_client):
    """Absent field → the flow's build-time default applies, not an override."""
    client = await make_client()
    await client.post(
        "/api/flow/run",
        json={"kind": "enhancement", "title": "t", "description": "d"},
    )
    ctx = await _wait_for_context(client.app_flow)
    assert "require_plan_approval" not in ctx.shared_data


@pytest.mark.asyncio
async def test_skip_flags_forwarded(make_client):
    client = await make_client()
    await client.post(
        "/api/flow/run",
        json={
            "kind": "enhancement", "title": "t", "description": "d",
            "skip_qa": True, "skip_jira": True,
        },
    )
    ctx = await _wait_for_context(client.app_flow)
    assert ctx.shared_data["skip_qa"] is True
    assert ctx.shared_data["skip_jira"] is True


# ---------------------------------------------------------------------------
# The mounted gate-resolution route (the HITL write path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_resolve_route_mounted(make_client):
    """Answering an open_questions gate over REST unblocks the run."""
    gate_flow = _GateFlow()
    client = await make_client(gate_flow)

    resp = await client.post(
        "/api/flow/run",
        json={"kind": "new_feature", "title": "t", "description": "d"},
    )
    run_id = (await resp.json())["run_id"]

    # Wait for the gate to open.
    for _ in range(200):
        await asyncio.sleep(0.01)
        if run_id in gate_flow.gate_ids:
            break
    gate_id = gate_flow.gate_ids[run_id]

    resolve = await client.post(
        f"/api/flow/{run_id}/gates/{gate_id}/resolve",
        json={
            "resolution": "approved",
            "resolved_by": "alice",
            "answers": {"Which store?": "pgvector"},
        },
    )

    assert resolve.status == 200
    body = await resolve.json()
    assert body["envelope"]["action"]["type"] == "gate/resolved"
    assert body["envelope"]["action"]["answers"] == {"Which store?": "pgvector"}
    # The flow saw the answers.
    for _ in range(200):
        await asyncio.sleep(0.01)
        if gate_flow.answers:
            break
    assert gate_flow.answers == {"Which store?": "pgvector"}


@pytest.mark.asyncio
async def test_gate_resolve_empty_answers_400(make_client):
    gate_flow = _GateFlow()
    client = await make_client(gate_flow)
    resp = await client.post(
        "/api/flow/run",
        json={"kind": "new_feature", "title": "t", "description": "d"},
    )
    run_id = (await resp.json())["run_id"]
    for _ in range(200):
        await asyncio.sleep(0.01)
        if run_id in gate_flow.gate_ids:
            break
    gate_id = gate_flow.gate_ids[run_id]

    bad = await client.post(
        f"/api/flow/{run_id}/gates/{gate_id}/resolve",
        json={"resolution": "approved", "resolved_by": "alice"},
    )
    assert bad.status == 400
    assert (await bad.json())["error"] == "answers_required"

    # Clean up: reject so the background task finishes.
    await client.post(
        f"/api/flow/{run_id}/gates/{gate_id}/resolve",
        json={"resolution": "rejected", "resolved_by": "alice"},
    )


@pytest.mark.asyncio
async def test_gate_resolve_unknown_run_404(make_client):
    client = await make_client()
    resp = await client.post(
        "/api/flow/no-such-run/gates/g1/resolve",
        json={"resolution": "approved", "resolved_by": "alice",
              "answers": {"q": "a"}},
    )
    assert resp.status == 404


# ---------------------------------------------------------------------------
# Route inventory / ops isolation
# ---------------------------------------------------------------------------


def test_route_inventory(server_dev):
    app = server_dev.build_app(redis_url="redis://x")
    routes = {
        (r.method, getattr(r.resource, "canonical", ""))
        for r in app.router.routes()
    }
    assert ("GET", "/") in routes
    assert ("GET", "/api/config") in routes
    assert ("POST", "/api/flow/run") in routes
    assert ("GET", "/api/flow/{run_id}/bundle") in routes
    assert ("GET", "/api/flow/{run_id}/replay") in routes
    assert ("GET", "/api/flow/{run_id}/ws") in routes
    assert ("POST", "/api/flow/{run_id}/cancel") in routes
    # The route server.py never mounts.
    assert ("POST", "/api/flow/{run_id}/gates/{gate_id}/resolve") in routes


def test_default_port_is_8081(server_dev):
    import inspect

    source = inspect.getsource(server_dev.main)
    assert '"PORT", "8081"' in source


def _referenced_identifiers(module) -> set[str]:
    """Every identifier the module's *code* references (AST, not text).

    Docstrings and comments are excluded by construction — this module's own
    documentation names the excluded ops helpers in order to say they are
    excluded, which a naive substring scan would flag as a false positive.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(module))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.keyword) and node.arg:
            names.add(node.arg)
        elif isinstance(node, ast.alias):
            names.add(node.asname or node.name.split(".")[0])
    return names


def test_no_cloudwatch_log_toolkits(server_dev):
    """dev-flow wires no observability toolkits at all."""
    names = _referenced_identifiers(server_dev)
    assert "_build_log_toolkits" not in names
    assert "log_toolkits" not in names
    assert not any("cloudwatch" in n.lower() for n in names)


def test_no_bug_brief_builder(server_dev):
    """No bug-intake brief building anywhere in the dev console's code."""
    names = _referenced_identifiers(server_dev)
    assert "_build_brief_from_form" not in names
    assert "BugBrief" not in names
    # Bug-intake-only form fields are never read.
    for field in ("affected_component", "log_sources", "escalation_assignee"):
        assert field not in names


def test_uses_dev_flow_runner_and_builder(server_dev):
    import inspect

    source = inspect.getsource(server_dev._on_startup)
    assert "build_dev_flow(" in source
    assert "DevFlowRunner(" in source
    assert "build_dev_loop_flow" not in source
    assert "build_dev_loop_feature_flow" not in source


def test_jira_is_optional(server_dev, monkeypatch):
    """No JIRA_* env → jira_toolkit is None, never an exception."""
    from parrot import conf

    original = conf.config.get

    def _fake_get(key, *args, **kwargs):
        if key in ("JIRA_INSTANCE", "JIRA_USERNAME"):
            return ""
        return original(key, *args, **kwargs)

    monkeypatch.setattr(conf.config, "get", _fake_get)
    assert server_dev._build_optional_jira_toolkit() is None


def test_reuses_ops_helpers_without_modifying_them(server_dev):
    """The ops-free helpers are imported, not copied."""
    ops = server_dev.ops_server
    assert server_dev.RUN_ARTIFACT_DIR is ops.RUN_ARTIFACT_DIR
    # Handlers reused verbatim.
    app = server_dev.build_app(redis_url="redis://x")
    handlers = {r.handler for r in app.router.routes()}
    assert ops.handle_bundle in handlers
    assert ops.handle_replay in handlers
    assert ops.handle_cancel in handlers
    # ...but NOT the ops index/config/run.
    assert ops.handle_index not in handlers
    assert ops.handle_config not in handlers
    assert ops.handle_run not in handlers
