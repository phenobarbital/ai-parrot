"""Tests for stack-trace parsing, severity and endpoint reproduction."""
from __future__ import annotations

import pytest
from aiohttp import web

from parrot.flows.dev_loop.replication import (
    ReplicationResult,
    ReplicationTarget,
    classify_severity,
    extract_endpoint,
    parse_stack_trace,
    proposed_regression_test,
    replicate_endpoint,
)

PY_TRACE = '''Traceback (most recent call last):
  File "/app/navigator/handlers/base.py", line 210, in dispatch
    return await handler(request)
  File "/app/resources/users/views.py", line 48, in get_session
    return payload["user"]["tenant"]
  File "/usr/lib/python3.11/site-packages/asyncpg/pool.py", line 12, in acquire
    raise KeyError(key)
KeyError: 'tenant'
'''

JS_TRACE = '''TypeError: Cannot read properties of undefined
    at load (/app/src/routes/proxy/queries/+server.ts:41:18)
    at Module.respond (/app/node_modules/@sveltejs/kit/src/runtime/respond.js:312:20)
'''


class TestParseStackTrace:
    def test_python_trace(self):
        trace = parse_stack_trace(PY_TRACE)
        assert trace.language == "python"
        assert trace.exception_type == "KeyError"
        assert trace.message == "'tenant'"
        assert len(trace.frames) == 3

    def test_python_culprit_skips_site_packages(self):
        """The deepest frame is a dependency; the bug is in our code."""
        culprit = parse_stack_trace(PY_TRACE).culprit
        assert culprit.file == "/app/resources/users/views.py"
        assert culprit.line == 48

    def test_javascript_trace_is_ordered_inner_first(self):
        """V8 prints innermost first — the opposite of Python."""
        trace = parse_stack_trace(JS_TRACE)
        assert trace.language == "javascript"
        assert trace.exception_type == "TypeError"
        assert trace.culprit.file == "/app/src/routes/proxy/queries/+server.ts"

    def test_javascript_culprit_skips_node_modules(self):
        trace = parse_stack_trace(JS_TRACE)
        assert "node_modules" not in trace.culprit.file

    def test_all_vendor_frames_still_yield_a_culprit(self):
        """Better the innermost dependency frame than nothing."""
        trace = parse_stack_trace(
            'File "/usr/lib/python3.11/site-packages/x/y.py", line 3, in f\n'
            "ValueError: boom"
        )
        assert trace.culprit is not None

    @pytest.mark.parametrize("text", ["", "   ", "the api is broken"])
    def test_prose_is_not_an_error(self, text):
        """Most reporters paste no trace at all."""
        trace = parse_stack_trace(text)
        assert trace.frames == []
        assert trace.summary() == "sin traceback reconocible"


class TestExtractEndpoint:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("500 on GET /api/v1/user/session", ("GET", "/api/v1/user/session")),
            ("el api devuelve 500 en /queries/slug", ("GET", "/queries/slug")),
            ("POST /orders falla", ("POST", "/orders")),
            ("no hay ruta aca", ("GET", None)),
        ],
    )
    def test_reads_method_and_path(self, text, expected):
        assert extract_endpoint(text) == expected

    @pytest.mark.parametrize(
        "text",
        [
            'File "/usr/lib/python3.11/json/decoder.py", line 355',
            "abrí /home/user/notes.txt",
            "mirá /app/src/main.py",
        ],
    )
    def test_file_paths_are_not_endpoints(self, text):
        """A traceback path is not something to send a request to."""
        assert extract_endpoint(text)[1] is None


class TestClassifySeverity:
    def test_startup_and_db_exceptions_are_critical(self):
        trace = parse_stack_trace("ImportError: No module named 'x'")
        assert classify_severity(trace) == "critical"

    def test_reproduced_5xx_is_high(self):
        result = ReplicationResult(attempted=True, reproduced=True, status=500)
        assert classify_severity(parse_stack_trace(PY_TRACE), result) == "high"

    def test_merely_reported_is_medium(self):
        assert classify_severity(parse_stack_trace(PY_TRACE), None) == "medium"

    def test_nothing_known_is_low(self):
        assert classify_severity(None, None) == "low"


class TestReplicateEndpoint:
    @pytest.fixture
    async def server(self, aiohttp_server):
        async def boom(_request):
            return web.Response(status=500, text=PY_TRACE)

        async def fine(_request):
            return web.Response(status=200, text="ok")

        app = web.Application()
        app.router.add_get("/boom", boom)
        app.router.add_get("/fine", fine)
        return await aiohttp_server(app)

    @pytest.mark.asyncio
    async def test_a_500_is_reproduced_and_captured(self, server):
        target = ReplicationTarget(base_url=str(server.make_url("")), name="test")
        result = await replicate_endpoint(target, "GET", "/boom")
        assert result.reproduced is True
        assert result.status == 500
        assert "KeyError" in result.body_excerpt

    @pytest.mark.asyncio
    async def test_the_trace_in_the_body_is_parsed(self, server):
        """The observed body is better evidence than the pasted excerpt."""
        target = ReplicationTarget(base_url=str(server.make_url("")), name="test")
        result = await replicate_endpoint(target, "GET", "/boom")
        assert result.trace is not None
        assert result.trace.exception_type == "KeyError"

    @pytest.mark.asyncio
    async def test_a_healthy_endpoint_is_not_reproduced(self, server):
        target = ReplicationTarget(base_url=str(server.make_url("")), name="test")
        result = await replicate_endpoint(target, "GET", "/fine")
        assert result.attempted is True
        assert result.reproduced is False
        assert result.status == 200

    @pytest.mark.asyncio
    async def test_an_unreachable_env_is_recorded_not_raised(self):
        """A dead environment must not abort intake."""
        target = ReplicationTarget(
            base_url="http://127.0.0.1:9", name="dead", timeout_seconds=2
        )
        result = await replicate_endpoint(target, "GET", "/boom")
        assert result.attempted is True
        assert result.reproduced is False
        assert result.error


class TestProposedRegressionTest:
    def test_reproduced_failure_yields_a_pytest_command(self):
        result = ReplicationResult(
            attempted=True, reproduced=True, status=500,
            url="http://dev.example.com/api/v1/user/session",
            method="GET", target="dev",
        )
        test = proposed_regression_test(result)
        assert test["path"].endswith(".py")
        # pytest is in ACCEPTANCE_CRITERION_ALLOWLIST, so QA can run it.
        assert test["command"].startswith("pytest ")
        assert "assert response.status_code < 500" in test["content"]

    def test_nothing_is_proposed_when_nothing_reproduced(self):
        result = ReplicationResult(attempted=True, reproduced=False, status=200)
        assert proposed_regression_test(result) is None
