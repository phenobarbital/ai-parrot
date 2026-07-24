"""End-to-end integration tests for the deterministic infographic render
endpoint (FEAT-327, Module 5).

Proves the whole feature with REAL (not mocked) persistence — a
``ConversationSQLiteBackend`` + local-filesystem overflow ``ArtifactStore``,
same pattern as ``packages/ai-parrot/tests/integration/
test_dataagent_infographic_e2e.py`` (FEAT-326's own e2e suite) — plus a
synthesized data-splice template standing in for the reference
``sdd/artifacts/budget_variance_dashboard_Template.html``, which is
gitignored (``artifacts/``) and absent from worktrees/CI, exactly as that
existing e2e suite already documents and works around.

Covers (spec §4 Integration Tests):
- ``test_e2e_render_budget_variance_json`` — inline records, JSON transport,
  data-splice render → HTML + a REAL persisted artifact.
- ``test_e2e_render_multipart_parquet`` — a dtype-bearing parquet part →
  identical spliced HTML on a repeat call (determinism).
- ``test_e2e_async_multiworker_poll`` — a job created against one
  ``RenderJobStore`` instance, polled through a SECOND instance sharing the
  same (fake) Redis client — multi-worker visibility.
- ``test_error_taxonomy`` — 400 / 404 / 413 / 422 at the HTTP level.
- ``test_pyarrow_declared_dependency`` — ``pyarrow`` is a direct dependency
  of ``ai-parrot-server`` (not merely transitively importable).
"""
from __future__ import annotations

import asyncio
import json
import logging
import tomllib
from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest
from aiohttp import MultipartWriter, web
from aiohttp.base_protocol import BaseProtocol
from aiohttp.streams import StreamReader
from aiohttp.test_utils import make_mocked_request

from parrot.handlers.infographic import InfographicTalk
from parrot.handlers.infographic_render import RenderBodyTooLargeError
from parrot.handlers.render_jobs import RenderJobStore
from parrot.models.infographic_templates import InfographicTemplate, infographic_registry
from parrot.storage.artifacts import ArtifactStore
from parrot.storage.backends import build_overflow_store
from parrot.storage.backends.sqlite import ConversationSQLiteBackend
from parrot.tools.infographic_sections import SectionDescriptor, SectionSpec
from parrot.tools.infographic_toolkit import InfographicToolkit

TEMPLATE_NAME = "feat327_e2e_budget_variance"

# Synthesized stand-in for sdd/artifacts/budget_variance_dashboard_Template.html
# (gitignored, absent from worktrees/CI) — same rationale + marker id as
# packages/ai-parrot/tests/integration/test_dataagent_infographic_e2e.py's
# own `budget_variance_template_dir` fixture.
TEMPLATE_HTML = (
    "<!doctype html><html><head><title>Budget Variance</title></head>"
    "<body><h1>Budget Variance</h1>"
    '<script type="application/json" id="report-data">\n{}\n</script>'
    "<div id='app'></div></body></html>"
)


class _FakeRedis:
    """Minimal in-memory async Redis double (``set``/``get``/``expire`` only).

    ``REDIS_HISTORY_URL`` points at a dev host unreachable from tests; an
    injected fake is explicitly sanctioned by TASK-1891's own scope note.
    """

    def __init__(self) -> None:
        self._data: dict = {}

    async def set(self, key, value):
        self._data[key] = value

    async def get(self, key):
        return self._data.get(key)

    async def expire(self, key, seconds):
        return True


@pytest.fixture(autouse=True)
def _register_test_template():
    infographic_registry.register(
        InfographicTemplate(name=TEMPLATE_NAME, description="FEAT-327 e2e", block_specs=[])
    )
    yield
    infographic_registry._templates.pop(TEMPLATE_NAME, None)


@pytest.fixture
async def local_artifact_store(tmp_path, monkeypatch):
    """REAL ArtifactStore: ConversationSQLiteBackend + local-filesystem overflow."""
    overflow_dir = tmp_path / "overflow"
    monkeypatch.setenv("PARROT_OVERFLOW_STORE", "local")
    monkeypatch.setenv("PARROT_OVERFLOW_LOCAL_PATH", str(overflow_dir))
    backend = ConversationSQLiteBackend(path=str(tmp_path / "conv.db"))
    await backend.initialize()
    overflow = build_overflow_store()
    return ArtifactStore(backend, overflow)


@pytest.fixture
def shared_redis():
    return _FakeRedis()


@pytest.fixture
def app(local_artifact_store, shared_redis):
    toolkit = InfographicToolkit(
        artifact_store=local_artifact_store, templates={TEMPLATE_NAME: TEMPLATE_HTML}
    )
    application = web.Application()
    application["artifact_store"] = local_artifact_store
    application["infographic_render_toolkit"] = toolkit
    application["infographic_render_job_store"] = RenderJobStore(redis_client=shared_redis)
    return application


def _descriptor() -> SectionDescriptor:
    return SectionDescriptor(
        template=TEMPLATE_NAME,
        mode="data-splice",
        sections=[
            SectionSpec(
                name="hero", target="/hero", datasets=["revenue"],
                columns={"revenue": ["amount"]}, shape="records",
            )
        ],
    )


def _render_body(**overrides) -> dict:
    body = {
        "datasets": {"revenue": {"orient": "records", "data": [{"amount": 1}, {"amount": 2}]}},
        "template": TEMPLATE_NAME,
        "descriptor": _descriptor().model_dump(),
        "persist": True,
        "public": False,
    }
    body.update(overrides)
    return body


async def _json_request(app: web.Application, body: dict, *, headers: dict | None = None):
    data = json.dumps(body).encode("utf-8")
    loop = asyncio.get_event_loop()
    protocol = BaseProtocol(loop=loop)
    stream = StreamReader(protocol, limit=2**20, loop=loop)
    stream.feed_data(data)
    stream.feed_eof()
    all_headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if headers:
        all_headers.update(headers)
    return make_mocked_request(
        "POST", "/api/v1/agents/infographic/render",
        headers=all_headers, payload=stream, app=app,
    )


async def _multipart_request(
    app: web.Application,
    parts: list[tuple[str, bytes, str | None]],
    *,
    accept: str = "application/json",
):
    writer = MultipartWriter("form-data")
    for name, data, content_type in parts:
        headers = {"Content-Type": content_type} if content_type else None
        payload = writer.append(data, headers)
        payload.set_content_disposition("form-data", name=name)
    body = await writer.as_bytes()
    loop = asyncio.get_event_loop()
    protocol = BaseProtocol(loop=loop)
    stream = StreamReader(protocol, limit=2**20, loop=loop)
    stream.feed_data(body)
    stream.feed_eof()
    return make_mocked_request(
        "POST", "/api/v1/agents/infographic/render",
        headers={"Content-Type": writer.content_type, "Accept": accept},
        payload=stream, app=app,
    )


def _handler(request) -> InfographicTalk:
    h = InfographicTalk.__new__(InfographicTalk)
    h.logger = logging.getLogger("test.infographic_render_e2e")
    h._request = request
    return h


class TestRenderE2E:
    async def test_e2e_render_budget_variance_json(self, app, local_artifact_store):
        request = await _json_request(app, _render_body(), headers={"Accept": "text/html"})
        response = await _handler(request)._render_infographic_deterministic()

        assert response.status == 200
        assert response.content_type == "text/html"
        html = response.body.decode("utf-8")
        assert '"hero": [{"amount": 1}, {"amount": 2}]' in html
        assert response.headers["X-Artifact-Persisted"] == "true"

        # Verify REAL persistence: fetch the artifact directly from the
        # store, using a FIXED session_id so the storage scope (user_id,
        # agent_id, session_id) is known ahead of time — the default flow
        # generates a random session_id when the body omits one.
        request2 = await _json_request(app, _render_body(session_id="sess-e2e-verify"))
        response2 = await _handler(request2)._render_infographic_deterministic()
        payload = json.loads(response2.body)
        artifact = await local_artifact_store.get_artifact(
            "_anon", "_anon", "sess-e2e-verify", payload["artifact_id"]
        )
        assert artifact is not None
        assert artifact.definition is not None or artifact.definition_ref is not None

    async def test_e2e_render_multipart_parquet_determinism(self, app):
        df = pd.DataFrame({"amount": [1, 2], "day": pd.to_datetime(["2026-01-01", "2026-01-02"])})
        buf = BytesIO()
        df.to_parquet(buf, engine="pyarrow")

        def _body():
            return json.dumps(_render_body(datasets={"revenue": None})).encode("utf-8")

        parts = [
            ("request", _body(), "application/json"),
            ("dataset:revenue", buf.getvalue(), "application/vnd.apache.parquet"),
        ]
        request1 = await _multipart_request(app, parts, accept="text/html")
        response1 = await _handler(request1)._render_infographic_deterministic()

        parts2 = [
            ("request", _body(), "application/json"),
            ("dataset:revenue", buf.getvalue(), "application/vnd.apache.parquet"),
        ]
        request2 = await _multipart_request(app, parts2, accept="text/html")
        response2 = await _handler(request2)._render_infographic_deterministic()

        assert response1.status == 200
        assert response1.body == response2.body  # determinism: identical spliced HTML

    async def test_e2e_async_multiworker_poll(self, app, shared_redis):
        request = await _json_request(app, _render_body(**{"async": True}))
        response = await _handler(request)._render_infographic_deterministic()
        assert response.status == 202
        job_id = json.loads(response.body)["job_id"]

        # Simulate a DIFFERENT worker: a second app/handler wrapping a
        # SEPARATE RenderJobStore instance backed by the SAME redis client.
        other_app = web.Application()
        other_app["infographic_render_job_store"] = RenderJobStore(redis_client=shared_redis)
        other_request = make_mocked_request(
            "GET", f"/api/v1/agents/infographic/render/jobs/{job_id}", app=other_app,
        )
        other_handler = _handler(other_request)

        job = None
        for _ in range(100):
            response2 = await other_handler._get_render_job_status(job_id)
            job = json.loads(response2.body)
            if job["status"] in ("done", "failed"):
                break
            await asyncio.sleep(0.01)

        assert job["status"] == "done", job.get("error")
        assert job["result"]["persisted"] is True

    async def test_error_taxonomy(self, app):
        # 404 — unknown template.
        request = await _json_request(app, _render_body(template="does-not-exist"))
        with pytest.raises(web.HTTPNotFound):
            await _handler(request)._render_infographic_deterministic()

        # 422 — aggregated validation deficits (missing column).
        bad_descriptor = SectionDescriptor(
            template=TEMPLATE_NAME, mode="data-splice",
            sections=[
                SectionSpec(
                    name="hero", target="/hero", datasets=["revenue"],
                    columns={"revenue": ["amount", "missing"]}, shape="records",
                )
            ],
        )
        request = await _json_request(app, _render_body(descriptor=bad_descriptor.model_dump()))
        response = await _handler(request)._render_infographic_deterministic()
        assert response.status == 422

        # 400 — malformed request body (not valid JSON).
        request = make_mocked_request(
            "POST", "/api/v1/agents/infographic/render",
            headers={"Content-Type": "application/json"}, app=app,
        )
        response = await _handler(request)._render_infographic_deterministic()
        assert response.status == 400

        # 413 — over the body cap. The cap MECHANISM itself, exercised with
        # a real small max_body_size against a real multipart body, is
        # already proven in TASK-1889's
        # test_infographic_render_models.py::test_body_cap_413; here we
        # prove the ROUTE correctly maps RenderBodyTooLargeError -> 413.
        request = await _json_request(app, _render_body())
        h = _handler(request)

        async def _decode_boom():
            raise RenderBodyTooLargeError("request body exceeds the cap")

        h._decode_render_request = _decode_boom
        response = await h._render_infographic_deterministic()
        assert response.status == 413


def test_pyarrow_declared_dependency():
    """`pyarrow` must be a DECLARED (non-transitive) dependency of
    ai-parrot-server — the package that actually imports it for parquet
    dataset-part decoding (TASK-1889/handlers/infographic_render.py)."""
    pyproject_path = (
        Path(__file__).resolve().parents[2] / "pyproject.toml"
    )
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    deps = data["project"]["dependencies"]
    assert any(dep.startswith("pyarrow") for dep in deps), (
        f"pyarrow not declared in {pyproject_path}'s [project.dependencies]: {deps}"
    )
