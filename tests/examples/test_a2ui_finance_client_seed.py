"""A2UI finance example — finance_client.py (--check against a fake server + fake DatasetManager) and
seed_finance.py."""

from __future__ import annotations

import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest

from ._finance_envelope import real_finance_envelope

pytest.importorskip("querysource", reason="querysource not installed (example-only dependency)")

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "examples" / "a2ui_finance"))

import finance_client  # noqa: E402
import seed_finance  # noqa: E402


def _row(date: str, division: str | None, project: str | None, ra: float, rb: float, ea: float, eb: float) -> dict:
    return {
        "snapshot_date": date,
        "division": division,
        "project": project,
        "rev_actual": ra,
        "rev_budget": rb,
        "ebitda_actual": ea,
        "ebitda_budget": eb,
    }


LATEST = pd.DataFrame(
    [
        _row("2026-09-02", "North", "Alpha", 100.0, 90.0, 20.0, 25.0),
        _row("2026-09-02", "North", "Beta", 50.0, 60.0, 5.0, 4.0),
        _row("2026-09-02", "South", "Gamma", 70.0, 70.0, 10.0, 12.0),
    ]
)
#: Raw history: the 2026-09-01 day sums to 200 / 210, the latest day is LATEST.
SNAPSHOTS = pd.DataFrame(
    [
        _row("2026-09-01", "North", "Alpha", 130.0, 140.0, 1.0, 1.0),
        _row("2026-09-01", "South", "Gamma", 70.0, 70.0, 1.0, 1.0),
        *LATEST.to_dict(orient="records"),
    ]
)


def canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


class FakeDatasetManager:
    """Stand-in for DatasetManager: records add_query / materialize calls and answers canned frames."""

    def __init__(self, latest: pd.DataFrame = LATEST, snapshots: pd.DataFrame = SNAPSHOTS) -> None:
        self.queries: dict[str, str] = {}
        self.materialized: list[tuple[str, dict[str, Any]]] = []
        self.latest = latest
        self.snapshots = snapshots

    def add_query(self, name: str, query_slug: str, **_: Any) -> str:
        self.queries[name] = query_slug
        return f"Query '{name}' registered (slug: {query_slug})"

    async def materialize(self, name: str, force_refresh: bool = False, **params: Any) -> pd.DataFrame:
        self.materialized.append((name, params))
        return self.latest if name == "latest" else self.snapshots


class FakeResponse:
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
    """A stand-in for the example server + QuerySource answering per request body, consistent with LATEST/TREND."""

    def __init__(self, envelope: dict[str, Any], *, overrides: dict[str, Any] | None = None, empty: str | None = None):
        self.envelope = envelope
        self.sources = envelope["metadata"]["extensions"]["parrot_data_sources"]
        self.by_conditions = {canon(src["conditions"]): key for key, src in self.sources.items()}
        self.posts: list[dict[str, Any]] = []
        self.urls: list[str] = []
        self.empty = empty
        self.data: dict[str, Any] = {
            "kpi_rev_actual": [{"rev_actual": 220.0}],
            "kpi_rev_budget": [{"rev_budget": 220.0}],
            "kpi_rev_variance": [{"rev_variance": 0.0}],
            "kpi_ebitda_variance": [{"ebitda_variance": -6.0}],
            "by_division": [
                {"division": "North", "rev_actual": 150.0, "rev_budget": 150.0},
                {"division": "South", "rev_actual": 70.0, "rev_budget": 70.0},
            ],
            "by_project": [
                {"project": "Alpha", "rev_actual": 100.0},
                {"project": "Beta", "rev_actual": 50.0},
                {"project": "Gamma", "rev_actual": 70.0},
            ],
            "trend": [
                {"snapshot_date": "2026-09-01T00:00:00", "rev_actual": 200.0, "rev_budget": 210.0},
                {"snapshot_date": "2026-09-02T00:00:00", "rev_actual": 220.0, "rev_budget": 220.0},
            ],
        }
        self.data.update(overrides or {})

    def post(self, url: str, json: dict[str, Any] | None = None, headers: dict[str, str] | None = None, **_: Any):
        if url.endswith("/api/v1/login"):
            return FakeResponse(200, {"token": "JWT"})
        assert headers and headers["Authorization"] == "Bearer JWT"
        self.urls.append(url)
        body = dict(json or {})
        self.posts.append(body)
        if self.empty and self.empty in url:
            return FakeResponse(204, None)
        conds = {k: v for k, v in body.items() if k not in {"querylimit", "_offset", "refresh"}}
        key = self.by_conditions.get(canon(conds))
        if key and key != "latest_rows":
            return FakeResponse(200, self.data[key])
        rows = LATEST.to_dict(orient="records")
        division = (body.get("filter") or {}).get("division")
        if division:
            rows = [row for row in rows if row["division"] == division]
        if body.get("fields") == ["count(*) as total"]:
            return FakeResponse(200, [{"total": len(rows)}])
        offset = body.get("_offset", 0)
        return FakeResponse(200, rows[offset : offset + body["querylimit"]])

    def get(self, url: str, headers: dict[str, str] | None = None, **_: Any):
        assert url.endswith("/api/a2ui/dashboard")
        return FakeResponse(200, self.envelope)


def make_session(server: FakeServer):
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
    kwargs.setdefault("manager", FakeDatasetManager())
    with patch("aiohttp.ClientSession", return_value=make_session(server)):
        code = await finance_client.check("http://h", "admin", "pw", **kwargs)
    return code, capsys.readouterr().out


class TestExpectedValues:
    @pytest.mark.asyncio
    async def test_expectations_come_from_dataset_manager(self) -> None:
        """add_query registers the two slugs lazily; materialize runs them; pandas aggregates the widgets' values."""
        manager = FakeDatasetManager()
        expected = await finance_client.expected_values(manager)
        assert manager.queries == {"latest": finance_client.LATEST_SLUG, "snapshots": finance_client.SNAPSHOTS_SLUG}
        assert [name for name, _ in manager.materialized] == ["latest", "snapshots"]
        assert all(params == {} for _, params in manager.materialized), "raw rows only: pandas does the aggregation"
        assert expected["kpis"]["kpi_rev_actual"] == ("rev_actual", 220.0)
        assert expected["kpis"]["kpi_rev_variance"] == ("rev_variance", 0.0)
        assert expected["kpis"]["kpi_ebitda_variance"][1] == pytest.approx(-6.0)
        assert expected["groups"]["by_division"]["North"] == {"rev_actual": 150.0, "rev_budget": 150.0}
        assert set(expected["groups"]["by_project"]) == {"Alpha", "Beta", "Gamma"}
        assert expected["groups"]["trend"]["2026-09-01"]["rev_budget"] == 210.0
        assert expected["grid_total"] == 3

    @pytest.mark.asyncio
    async def test_empty_latest_frame_is_an_error(self) -> None:
        with pytest.raises(finance_client.CheckError):
            await finance_client.expected_values(FakeDatasetManager(latest=LATEST.iloc[0:0]))
        with pytest.raises(finance_client.CheckError):
            await finance_client.expected_values(FakeDatasetManager(snapshots=SNAPSHOTS.iloc[0:0]))

    @pytest.mark.asyncio
    async def test_null_labels_and_all_null_sums_match_the_lane(self) -> None:
        """A NULL division/project groups under "" on both sides; an all-NULL money column is None, like SQL."""
        latest = pd.DataFrame(
            [
                _row("2026-09-02", None, "Alpha", 100.0, None, None, None),
                _row("2026-09-02", "South", None, 70.0, None, None, None),
            ]
        )
        expected = await finance_client.expected_values(FakeDatasetManager(latest=latest, snapshots=latest))
        assert set(expected["groups"]["by_division"]) == {"", "South"}
        assert set(expected["groups"]["by_project"]) == {"Alpha", ""}
        assert expected["kpis"]["kpi_rev_budget"] == ("rev_budget", None)
        assert expected["kpis"]["kpi_rev_variance"] == ("rev_variance", None)
        rows = {
            "kpi_rev_actual": [{"rev_actual": 170.0}],
            "kpi_rev_budget": [{"rev_budget": None}],
            "kpi_rev_variance": [{"rev_variance": None}],
            "kpi_ebitda_variance": [{"ebitda_variance": None}],
            "by_division": [
                {"division": None, "rev_actual": 100.0, "rev_budget": None},
                {"division": "South", "rev_actual": 70.0, "rev_budget": None},
            ],
            "by_project": [{"project": "Alpha", "rev_actual": 100.0}, {"project": None, "rev_actual": 70.0}],
            "trend": [{"snapshot_date": "2026-09-02T00:00:00", "rev_actual": 170.0, "rev_budget": None}],
        }
        assert finance_client.evaluate(rows, expected) == []
        assert finance_client.label(float("nan")) == "" and finance_client.label(pd.NaT) == ""


class TestClientCheck:
    @pytest.mark.asyncio
    async def test_passes_and_prints_values(self, capsys: pytest.CaptureFixture[str]) -> None:
        server = FakeServer(real_finance_envelope())
        code, out = await run_check(server, capsys)
        assert code == 0, out
        assert "kpi_rev_actual | 220.0" in out and "by_division | 2 groups" in out and "trend | 2 groups" in out
        assert "OK: all checks passed" in out

    @pytest.mark.asyncio
    async def test_replays_the_lane_requests_on_the_v2_route(self, capsys: pytest.CaptureFixture[str]) -> None:
        server = FakeServer(real_finance_envelope())
        await run_check(server, capsys)
        assert server.urls and all("/api/v2/services/queries/" in url for url in server.urls)
        assert any(
            url.endswith(finance_client.SNAPSHOTS_SLUG) for url in server.urls
        ), "the trend hits the snapshots slug"
        trend = server.sources["trend"]["conditions"]
        assert any(post.get("grouping") == trend["grouping"] and post["querylimit"] == 5000 for post in server.posts)
        page = next(p for p in server.posts if p.get("_offset") == 0 and p["querylimit"] == 20 and "filter" not in p)
        assert page["ordering"] == ["division", "project"]
        assert any(p.get("filter") == {"division": "North"} for p in server.posts), "the division filter is exercised"

    @pytest.mark.asyncio
    async def test_a_baked_envelope_fails(self, capsys: pytest.CaptureFixture[str]) -> None:
        """The example's whole point: the served surface must not carry rows."""
        code, _ = await run_check(FakeServer(real_finance_envelope(snapshot=True)), capsys)
        assert code == 1

    @pytest.mark.asyncio
    async def test_drifted_kpi_fails(self, capsys: pytest.CaptureFixture[str]) -> None:
        server = FakeServer(real_finance_envelope(), overrides={"kpi_rev_actual": [{"rev_actual": 5.0}]})
        code, _ = await run_check(server, capsys)
        assert code == 1

    @pytest.mark.asyncio
    async def test_drifted_group_fails(self, capsys: pytest.CaptureFixture[str]) -> None:
        server = FakeServer(
            real_finance_envelope(), overrides={"by_project": [{"project": "Alpha", "rev_actual": 1.0}]}
        )
        code, _ = await run_check(server, capsys)
        assert code == 1

    @pytest.mark.asyncio
    async def test_204_on_trend_is_zero_rows(self, capsys: pytest.CaptureFixture[str]) -> None:
        server = FakeServer(real_finance_envelope(), empty=finance_client.SNAPSHOTS_SLUG)
        code, out = await run_check(server, capsys, expect=False, manager=None)
        assert code == 0 and "trend | 0 groups" in out
        code, _ = await run_check(server, capsys)
        assert code == 1

    @pytest.mark.asyncio
    async def test_no_expect_skips_dataset_manager(self, capsys: pytest.CaptureFixture[str]) -> None:
        server = FakeServer(real_finance_envelope(), overrides={"kpi_rev_actual": [{"rev_actual": 5.0}]})
        code, out = await run_check(server, capsys, expect=False, manager=None)
        assert code == 0 and "kpi_rev_actual | 5.0" in out

    @pytest.mark.asyncio
    async def test_dataset_manager_failure_is_reported_not_raised(self, capsys: pytest.CaptureFixture[str]) -> None:
        class Broken(FakeDatasetManager):
            async def materialize(self, name: str, force_refresh: bool = False, **params: Any) -> pd.DataFrame:
                raise RuntimeError("no database")

        code, _ = await run_check(FakeServer(real_finance_envelope()), capsys, manager=Broken())
        assert code == 1

    def test_evaluate_reports_every_mismatch(self) -> None:
        expected = {
            "kpis": {"kpi_rev_actual": ("rev_actual", 1.0)},
            "groups": {"by_division": {"North": {"rev_actual": 1.0}}, "by_project": {}, "trend": {}},
            "grid_total": 0,
        }
        rows = {"kpi_rev_actual": [{"rev_actual": 2.0}], "by_division": [{"division": "North", "rev_actual": 3.0}]}
        failures = finance_client.evaluate(rows, expected)
        assert any(f.startswith("kpi_rev_actual") for f in failures)
        assert any(f.startswith("by_division[North].rev_actual") for f in failures)
        assert not any(f.startswith(("by_project", "trend")) for f in failures)


class TestClientArgParsing:
    def test_requires_open_or_check(self) -> None:
        assert finance_client.main([]) == 1

    def test_check_requires_password(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            assert finance_client.main(["--check"]) == 1


class FakeConn:
    """A recording asyncpg connection stand-in for the seed."""

    def __init__(
        self,
        *,
        unique_index: bool,
        existing: bool,
        program_row: bool = True,
        parser_row: bool = True,
        owner: str | None = None,
    ) -> None:
        self.unique_index = unique_index
        self.existing = existing
        self.program_row = program_row
        self.parser_row = parser_row
        self.owner = owner  # program_slug an existing row of the slug belongs to (None: no row)
        self.parser_program: str | None = None
        self.executed: list[str] = []
        self.upserts: list[tuple[Any, ...]] = []
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

    async def fetchval(self, sql: str, *args: Any) -> Any:
        if "ON CONFLICT" in sql:
            self.executed.append("UPSERT")
            self.upserts.append(args)
            return not self.existing
        if "pg_index" in sql:
            return 1 if self.unique_index else None
        if sql == seed_finance.PROGRAM_ID_SQL:
            return 42 if self.program_row else None
        if sql == seed_finance.PARSER_SQL:
            self.parser_program = args[0]
            return "pgSQLParser" if self.parser_row else None
        if sql == seed_finance.OWNER_SQL:
            return self.owner
        raise AssertionError(sql)

    async def close(self) -> None:
        self.closed = True


class TestSeed:
    def test_refuses_without_yes(self) -> None:
        assert seed_finance.main([]) == 2

    def test_dry_run_prints_both_rows_and_writes_nothing(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("asyncpg.connect", side_effect=AssertionError("must not connect")):
            assert seed_finance.main(["--dry-run", "--program", "troc"]) == 0
        out = capsys.readouterr().out
        assert (
            seed_finance.SNAPSHOTS_SLUG in out and seed_finance.LATEST_SLUG in out and '"program_slug": "troc"' in out
        )
        assert "copied from an existing row" in out, "unresolved program_id/parser are marked, never shown as null"

    def test_accepts_yes_flag(self) -> None:
        with patch("asyncpg.connect", side_effect=ConnectionError("No DB")):
            assert seed_finance.main(["--yes"]) == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("existing", "expected"), [(False, "inserted"), (True, "updated")])
    async def test_upserts_both_slugs_under_locks(self, existing: bool, expected: str) -> None:
        conn = FakeConn(unique_index=True, existing=existing)
        result = await seed_finance.seed(conn)
        assert result == {seed_finance.SNAPSHOTS_SLUG: expected, seed_finance.LATEST_SLUG: expected}
        assert conn.executed.count("SELECT:lock") == 2 and conn.executed.count("UPSERT") == 2
        assert conn.parser_program == "troc", "the parser is copied from a sibling slug of the SAME program"
        for values in conn.upserts:
            row = dict(zip(seed_finance.COLUMNS, values, strict=True))
            assert row["program_slug"] == "troc" and row["program_id"] == 42 and row["provider"] == "db"
            assert row["parser"] == "pgSQLParser" and row["is_raw"] is False and row["is_cached"] is False
            assert row["fields"] == seed_finance.FIELDS

    @pytest.mark.asyncio
    async def test_explicit_program_id_and_parser_override_the_lookup(self) -> None:
        conn = FakeConn(unique_index=True, existing=False, program_row=False, parser_row=False)
        await seed_finance.seed(conn, program="other", program_id=7, parser="MyParser")
        rows = [dict(zip(seed_finance.COLUMNS, v, strict=True)) for v in conn.upserts]
        assert all(r["program_id"] == 7 and r["parser"] == "MyParser" and r["program_slug"] == "other" for r in rows)

    @pytest.mark.asyncio
    async def test_unresolvable_program_id_or_parser_writes_nothing(self) -> None:
        """An invalid row (NULL program_id, unknown parser) is never written."""
        conn = FakeConn(unique_index=True, existing=False, program_row=False)
        with pytest.raises(RuntimeError, match="program-id"):
            await seed_finance.seed(conn)
        assert conn.upserts == []
        conn = FakeConn(unique_index=True, existing=False, parser_row=False)
        with pytest.raises(RuntimeError, match="parser"):
            await seed_finance.seed(conn)
        assert conn.upserts == []

    @pytest.mark.asyncio
    async def test_refuses_to_take_over_another_programs_slug(self) -> None:
        conn = FakeConn(unique_index=True, existing=True, owner="polestar")
        with pytest.raises(RuntimeError, match="belongs to program 'polestar'"):
            await seed_finance.seed(conn)
        assert conn.upserts == []
        conn = FakeConn(unique_index=True, existing=True, owner="troc")
        assert set((await seed_finance.seed(conn)).values()) == {"updated"}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("existing", "expected"), [(False, "inserted"), (True, "updated")])
    async def test_fallback_without_unique_index_is_transactional(self, existing: bool, expected: str) -> None:
        conn = FakeConn(unique_index=False, existing=existing)
        result = await seed_finance.seed(conn)
        assert set(result.values()) == {expected}
        assert conn.executed.count("UPDATE") == 2
        assert conn.executed.count("INSERT") == (0 if existing else 2)

    @pytest.mark.asyncio
    async def test_owned_connection_is_closed(self) -> None:
        conn = FakeConn(unique_index=True, existing=False)

        async def connect(_dsn: str) -> FakeConn:
            return conn

        with patch("asyncpg.connect", connect), patch.object(seed_finance, "default_dsn", "dsn"):
            await seed_finance.seed()
        assert conn.closed


class TestSeedSQLTemplates:
    def test_templates_read_the_finance_table_with_float_casts(self) -> None:
        for query_raw in (seed_finance.SNAPSHOTS_QUERY_RAW, seed_finance.LATEST_QUERY_RAW):
            assert "{fields}" in query_raw and "{where_cond}" in query_raw
            assert "troc.finance_projection" in query_raw
            assert "rev_actual::float8 AS rev_actual" in query_raw and "ebitda_budget::float8" in query_raw
        assert "max(snapshot_date)" in seed_finance.LATEST_QUERY_RAW
        assert "max(snapshot_date)" not in seed_finance.SNAPSHOTS_QUERY_RAW
