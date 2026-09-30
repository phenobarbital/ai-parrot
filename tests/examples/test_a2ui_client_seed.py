"""FEAT-610 — client.py (--check against a stateful fake server) and seed_by_course.py (fake connection)."""

from __future__ import annotations

import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from ._envelope import real_envelope

pytest.importorskip("querysource", reason="querysource not installed (example-only dependency)")

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "examples" / "a2ui"))

import client  # noqa: E402
import seed_by_course  # noqa: E402


def canon(value: Any) -> str:
    """Key-order independent JSON, to match a request body against a source's own conditions."""
    return json.dumps(value, sort_keys=True)


class FakeResponse:
    """Minimal aiohttp response: status + JSON body, usable as an async context manager."""

    def __init__(self, status: int, payload: Any) -> None:
        self.status = status
        self._payload = payload

    async def json(self) -> Any:
        return self._payload

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class FakeServer:
    """A stateful stand-in for the example server + QuerySource, answering per request body like the real one."""

    def __init__(
        self, envelope: dict[str, Any], *, overrides: dict[str, Any] | None = None, missing: str | None = None
    ):
        self.envelope = envelope
        self.sources = envelope["metadata"]["extensions"]["parrot_data_sources"]
        # Only query-slug sources are ever POSTed; derived views (`kind: "derived"`) carry no conditions.
        self.by_conditions = {canon(src["conditions"]): key for key, src in self.sources.items() if "conditions" in src}
        self.posts: list[dict[str, Any]] = []
        self.overrides = overrides or {}
        self.missing = missing  # a slug that answers 404
        self.login_status = 200
        # The geo matrix: 95 countries × 23 licensees whose graduates add up to the KPI total (17572).
        geo = [{"country": f"C{c}", "licensee": f"L{lic}", "graduates": 8} for c in range(95) for lic in range(23)]
        geo[0]["graduates"] += 17572 - 8 * len(geo)
        self.data: dict[str, Any] = {
            "kpis": [{"total": 17572, "studio": 9191, "mat": 6245, "multi_graduates": 2884}],
            "geo": geo,
            "by_course": [
                {"course": "Pilates Studio", "graduates": 9204},
                {"course": "Pilates Mat", "graduates": 6247},
                {"course": "Rehab", "graduates": 3300},
                {"course": "Reformer", "graduates": 2048},
            ],
        }
        self.data.update(self.overrides)

    def post(self, url: str, json: dict[str, Any] | None = None, headers: dict[str, str] | None = None, **_: Any):
        if url.endswith("/api/v1/login"):
            if self.login_status != 200:
                return FakeResponse(self.login_status, {})
            assert json == {"username": "admin", "password": "pw"}
            return FakeResponse(200, {"token": "JWT"})
        assert headers and headers["Authorization"] == "Bearer JWT"
        body = dict(json or {})
        self.posts.append(body)
        if self.missing and self.missing in url:
            return FakeResponse(404, {})
        conds = {k: v for k, v in body.items() if k not in {"querylimit", "_offset", "refresh"}}
        key = self.by_conditions.get(canon(conds))
        if key and key != "graduates":
            return FakeResponse(200, self.data[key])
        if body.get("fields") == ["count(*) as total"]:
            return FakeResponse(200, [{"total": 100 if body.get("filter", {}).get("country") else 17572}])
        offset = body.get("_offset", 0)
        rows = [
            {"student_uid": offset + i, "country": (body.get("filter") or {}).get("country", "US")}
            for i in range(body["querylimit"])
        ]
        return FakeResponse(200, rows)

    def get(self, url: str, headers: dict[str, str] | None = None, **_: Any):
        assert url.endswith("/api/a2ui/dashboard")
        assert headers and headers["Authorization"] == "Bearer JWT"
        return FakeResponse(200, self.envelope)


def make_session(server: FakeServer):
    """A ClientSession stand-in delegating to ``server``."""

    class Session:
        async def __aenter__(self) -> Session:
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

        def post(self, *args: Any, **kwargs: Any):
            return server.post(*args, **kwargs)

        def get(self, *args: Any, **kwargs: Any):
            return server.get(*args, **kwargs)

    return Session()


async def run_check(server: FakeServer, capsys: pytest.CaptureFixture[str], **kwargs: Any) -> tuple[int, str]:
    with patch("aiohttp.ClientSession", return_value=make_session(server)):
        code = await client.check("http://h", "admin", "pw", **kwargs)
    return code, capsys.readouterr().out


class TestClientArgParsing:
    def test_requires_open_or_check(self) -> None:
        assert client.main([]) == 1

    def test_open_and_check_mutually_exclusive(self) -> None:
        assert client.main(["--open", "--check"]) == 1

    def test_check_requires_password(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            assert client.main(["--check"]) == 1


class TestClientCheck:
    """AC10: --check asserts the AC7 values and the grid paging; it fails loudly otherwise."""

    @pytest.mark.asyncio
    async def test_passes_and_prints_values(self, capsys: pytest.CaptureFixture[str]) -> None:
        server = FakeServer(real_envelope())
        code, out = await run_check(server, capsys)
        assert code == 0
        for expected in ("kpi_total | 17572", "kpi_studio | 9191", "kpi_mat | 6245", "kpi_multi | 2884"):
            assert expected in out
        assert "by_country | 95 groups" in out and "by_licensee | 23 groups" in out
        assert "by_course | Pilates Studio = 9204" in out
        assert "OK: all checks passed" in out

    @pytest.mark.asyncio
    async def test_replays_the_lane_requests(self, capsys: pytest.CaptureFixture[str]) -> None:
        server = FakeServer(real_envelope())
        await run_check(server, capsys)
        kpis = server.sources["kpis"]["conditions"]
        kpi_posts = [post for post in server.posts if post.get("fields") == kpis["fields"]]
        assert len(kpi_posts) == 1 and kpi_posts[0]["querylimit"] == 5000, "the four KPIs are ONE request"
        assert len(kpis["fields"]) == 4 and "@>" in kpis["fields"][1]
        geo_posts = [post for post in server.posts if post.get("grouping") == ["country", "licensee"]]
        assert len(geo_posts) == 1, "the geo matrix is fetched once; by_country/by_licensee are computed locally"
        assert not any(post.get("grouping") in (["country"], ["licensee"]) for post in server.posts)
        page = next(p for p in server.posts if p.get("_offset") == 0 and p["querylimit"] == 20 and "filter" not in p)
        assert page["ordering"] == ["student_uid"]
        assert any(p.get("filter") == {"country": "US"} for p in server.posts), "the column filter is exercised"

    @pytest.mark.asyncio
    async def test_wrong_value_fails(self, capsys: pytest.CaptureFixture[str]) -> None:
        server = FakeServer(
            real_envelope(), overrides={"kpis": [{"total": 5, "studio": 9191, "mat": 6245, "multi_graduates": 2884}]}
        )
        code, _ = await run_check(server, capsys)
        assert code == 1

    @pytest.mark.asyncio
    async def test_no_expect_prints_without_asserting(self, capsys: pytest.CaptureFixture[str]) -> None:
        server = FakeServer(
            real_envelope(), overrides={"kpis": [{"total": 17572, "studio": 5, "mat": 6245, "multi_graduates": 2884}]}
        )
        code, out = await run_check(server, capsys, expect=False)
        assert code == 0 and "kpi_studio | 5" in out

    @pytest.mark.asyncio
    async def test_404_fails_instead_of_passing_empty(self, capsys: pytest.CaptureFixture[str]) -> None:
        server = FakeServer(real_envelope(), missing="polestar_graduates_by_course")
        code, _ = await run_check(server, capsys)
        assert code == 1

    @pytest.mark.asyncio
    async def test_missing_source_fails(self, capsys: pytest.CaptureFixture[str]) -> None:
        envelope = real_envelope()
        del envelope["metadata"]["extensions"]["parrot_data_sources"]["by_course"]
        code, _ = await run_check(FakeServer(envelope), capsys)
        assert code == 1

    @pytest.mark.asyncio
    async def test_login_failure_fails(self, capsys: pytest.CaptureFixture[str]) -> None:
        server = FakeServer(real_envelope())
        server.login_status = 401
        code, _ = await run_check(server, capsys)
        assert code == 1

    def test_evaluate_reports_every_mismatch(self) -> None:
        failures = client.evaluate(
            {"kpis": [{"total": 1}], "geo": [], "by_country": [], "by_licensee": [], "by_course": []}
        )
        assert any("kpi_total" in f for f in failures)
        assert any("kpi_studio" in f for f in failures)
        assert any("by_country" in f for f in failures)
        assert any("by_course" in f for f in failures)
        assert any(f.startswith("geo:") for f in failures), "the geo matrix must add up to the KPI total"


class FakeConn:
    """A recording asyncpg connection stand-in."""

    def __init__(self, *, unique_index: bool, existing: bool, base: bool = True) -> None:
        self.unique_index = unique_index
        self.existing = existing
        self.base = base
        self.executed: list[str] = []
        self.in_tx = False
        self.closed = False

    @asynccontextmanager
    async def transaction(self):
        self.in_tx = True
        try:
            yield
        finally:
            self.in_tx = False

    async def execute(self, sql: str, *args: Any) -> str:
        assert self.in_tx, "every write must happen inside the transaction"
        self.executed.append(sql.strip().split()[0] + (":lock" if "advisory" in sql else ""))
        if sql.strip().startswith("UPDATE"):
            return "UPDATE 1" if self.existing else "UPDATE 0"
        return "OK"

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        if not self.base:
            return None
        return {
            "program_id": 1,
            "program_slug": "polestar",
            "provider": "db",
            "parser": "pgSQLParser",
            "is_raw": False,
            "is_cached": False,
            "cache_timeout": 3600,
        }

    async def fetchval(self, sql: str, *args: Any) -> Any:
        if "pg_index" in sql:
            return 1 if self.unique_index else None
        if "ON CONFLICT" in sql:
            self.executed.append("UPSERT")
            return not self.existing  # RETURNING (xmax = 0)
        raise AssertionError(sql)

    async def close(self) -> None:
        self.closed = True


class TestSeed:
    """AC11: the seed refuses without --yes and reports an idempotent outcome."""

    def test_refuses_without_yes(self) -> None:
        assert seed_by_course.main([]) == 2

    def test_accepts_yes_flag(self) -> None:
        with patch("asyncpg.connect", side_effect=ConnectionError("No DB")):
            assert seed_by_course.main(["--yes"]) == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("existing", "expected"), [(False, "inserted"), (True, "updated")])
    async def test_upsert_reports_insert_vs_update(self, existing: bool, expected: str) -> None:
        conn = FakeConn(unique_index=True, existing=existing)
        assert await seed_by_course.seed(conn) == expected
        assert conn.executed[0] == "SELECT:lock" and "UPSERT" in conn.executed

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("existing", "expected"), [(False, "inserted"), (True, "updated")])
    async def test_fallback_without_unique_index_is_transactional(self, existing: bool, expected: str) -> None:
        conn = FakeConn(unique_index=False, existing=existing)
        assert await seed_by_course.seed(conn) == expected
        assert conn.executed[0] == "SELECT:lock"
        assert conn.executed[1] == "UPDATE"
        assert ("INSERT" in conn.executed) is (not existing)

    @pytest.mark.asyncio
    async def test_missing_base_slug_raises(self) -> None:
        with pytest.raises(RuntimeError, match="not found"):
            await seed_by_course.seed(FakeConn(unique_index=True, existing=False, base=False))

    @pytest.mark.asyncio
    async def test_owned_connection_is_closed(self) -> None:
        conn = FakeConn(unique_index=True, existing=False)

        async def connect(_dsn: str) -> FakeConn:
            return conn

        with patch("asyncpg.connect", connect), patch.object(seed_by_course, "default_dsn", "dsn"):
            await seed_by_course.seed()
        assert conn.closed


class TestSeedSQLTemplate:
    def test_sql_template_contains_lateral(self) -> None:
        assert "LATERAL" in seed_by_course.QUERY_RAW
        assert "jsonb_array_elements" in seed_by_course.QUERY_RAW
        assert "e->>'course'" in seed_by_course.QUERY_RAW

    def test_sql_template_structure(self) -> None:
        assert "{fields}" in seed_by_course.QUERY_RAW
        assert "{where_cond}" in seed_by_course.QUERY_RAW
        assert "polestar.vw_graduates_directory" in seed_by_course.QUERY_RAW
