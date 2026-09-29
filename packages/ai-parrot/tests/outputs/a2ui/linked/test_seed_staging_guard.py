"""FEAT-611 M2: seed_staging.assert_live_target refuses anything but a staging/dev DB (spec AC7).

Also proves offline (no DB, no staging) that the demo policy YAML parses and that the policy-proof
logic yields allow with the example policy dir and deny with a control dir, through a real guard.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

SEED_PATH = Path(__file__).resolve().parents[6] / "examples/agents/a2ui/linked_e2e/seed_staging.py"
POLICY_YAML = SEED_PATH.parent / "policies" / "source-epson.yaml"


@pytest.fixture
def seed(monkeypatch):
    spec = importlib.util.spec_from_file_location("feat611_seed_staging_under_test", SEED_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_refuses_when_env_is_not_staging(seed, monkeypatch):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setattr(seed, "_current_dbname", lambda: "navigator_staging")
    with pytest.raises(SystemExit):
        seed.assert_live_target()


def test_refuses_when_env_is_unset(seed, monkeypatch):
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.setattr(seed, "_current_dbname", lambda: "navigator_staging")
    with pytest.raises(SystemExit):
        seed.assert_live_target()


def test_refuses_when_dbname_is_not_staging(seed, monkeypatch):
    monkeypatch.setenv("ENV", "staging")
    monkeypatch.setattr(seed, "_current_dbname", lambda: "navigator")
    with pytest.raises(SystemExit, match="DBNAME"):
        seed.assert_live_target()


def test_accepts_staging(seed, monkeypatch):
    monkeypatch.setenv("ENV", "staging")
    monkeypatch.setattr(seed, "_current_dbname", lambda: "navigator_STAGING")
    assert seed.assert_live_target() == "staging"
    assert seed.assert_staging is seed.assert_live_target  # backwards-compatible alias


def test_accepts_dev(seed, monkeypatch):
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setattr(seed, "_current_dbname", lambda: "navigator_dev")
    assert seed.assert_live_target() == "dev"


@pytest.mark.parametrize(
    ("env", "dbname"),
    [("dev", "navigator_staging"), ("dev", "navigator"), ("staging", "navigator_dev"), ("dev", "navigator_dev_prod")],
)
def test_refuses_when_dbname_does_not_match_env(seed, monkeypatch, env, dbname):
    monkeypatch.setenv("ENV", env)
    monkeypatch.setattr(seed, "_current_dbname", lambda: dbname)
    with pytest.raises(SystemExit, match="DBNAME"):
        seed.assert_live_target()


@pytest.mark.parametrize("env", ["production", "prod", "development", "Dev", ""])
def test_refuses_non_live_selectors(seed, monkeypatch, env):
    monkeypatch.setenv("ENV", env)
    monkeypatch.setattr(seed, "_current_dbname", lambda: f"navigator_{env}_dev_staging")
    with pytest.raises(SystemExit, match="ENV"):
        seed.assert_live_target()


def _poison_toolkit(monkeypatch):
    for name in ("parrot_tools.querysource.toolkit", "asyncpg"):
        poisoned = types.ModuleType(name)

        def __getattr__(attr, _name=name):  # noqa: N807 — module-level __getattr__
            pytest.fail(f"{_name} touched before the live-target guard: {attr}")

        poisoned.__getattr__ = __getattr__
        monkeypatch.setitem(sys.modules, name, poisoned)


def test_seed_refuses_before_any_toolkit_import(seed, monkeypatch):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setattr(seed, "_current_dbname", lambda: pytest.fail("DBNAME read before ENV check"))
    _poison_toolkit(monkeypatch)
    with pytest.raises(SystemExit):
        asyncio.run(seed.seed_multiquery())
    with pytest.raises(SystemExit):
        asyncio.run(seed.describe_slugs([seed.ACTIVITY_SLUG]))
    with pytest.raises(SystemExit):
        asyncio.run(seed.preview_multiquery({}))
    with pytest.raises(SystemExit):
        asyncio.run(seed.seed_sql_slugs())
    with pytest.raises(SystemExit):
        asyncio.run(seed.seed_all())


@pytest.mark.parametrize("command", ["seed", "seed-sql"])
@pytest.mark.parametrize(("env", "dbname"), [("staging", "navigator_staging"), ("dev", "navigator_dev")])
def test_cli_seed_requires_confirm_flag(seed, monkeypatch, command, env, dbname):
    monkeypatch.setenv("ENV", env)
    monkeypatch.setattr(seed, "_current_dbname", lambda: dbname)
    _poison_toolkit(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda *_: pytest.fail("prompted without --confirm"))
    with pytest.raises(SystemExit, match="--confirm"):
        seed.main([command, "--yes"])


@pytest.mark.parametrize("command", ["seed", "seed-sql"])
def test_cli_seed_aborts_without_interactive_yes(seed, monkeypatch, command):
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setattr(seed, "_current_dbname", lambda: "navigator_dev")
    _poison_toolkit(monkeypatch)
    prompts: list[str] = []
    monkeypatch.setattr("builtins.input", lambda prompt: prompts.append(prompt) or "no")
    with pytest.raises(SystemExit, match="aborted"):
        seed.main([command, "--confirm"])
    assert "DEV query catalog" in prompts[0] and seed.TARGETS_SLUG in prompts[0]
    assert (seed.MQ_SLUG in prompts[0]) is (command == "seed")


class _FakeConn:
    """Minimal asyncpg connection: an upsert table keyed by query_slug; RETURNING (xmax = 0) AS inserted."""

    def __init__(self, table: dict) -> None:
        self.table, self.statements, self.closed = table, [], False

    def transaction(self):
        conn = self

        class _Tx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _Tx()

    async def fetchrow(self, sql, *args):
        self.statements.append((sql, args))
        slug = args[0]
        if slug in self.table:
            if "DO NOTHING" in sql:
                return None
            self.table[slug] = args
            return {"inserted": False}
        self.table[slug] = args
        return {"inserted": True}

    async def close(self):
        self.closed = True


def test_seed_sql_slugs_upserts_idempotently(seed, monkeypatch):
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setattr(seed, "_current_dbname", lambda: "navigator_dev")
    monkeypatch.setattr(seed, "_queries_table", lambda: '"public"."queries"')
    monkeypatch.setattr(seed, "_db_params", lambda: {"host": "fake"})
    table: dict = {}
    conns: list[_FakeConn] = []

    async def connect(**kwargs):
        assert kwargs == {"host": "fake"}
        conns.append(_FakeConn(table))
        return conns[-1]

    monkeypatch.setitem(sys.modules, "asyncpg", types.SimpleNamespace(connect=connect))
    slugs = {seed.ACTIVITY_SLUG: "inserted", seed.TARGETS_SLUG: "inserted"}
    assert asyncio.run(seed.seed_sql_slugs()) == slugs
    assert asyncio.run(seed.seed_sql_slugs()) == dict.fromkeys(slugs, "updated")
    assert asyncio.run(seed.seed_sql_slugs(overwrite=False)) == dict.fromkeys(slugs, "unchanged")
    assert all(conn.closed for conn in conns)
    sql, args = conns[0].statements[0]
    assert sql.startswith('INSERT INTO "public"."queries"') and "ON CONFLICT (query_slug) DO UPDATE" in sql
    assert "'pgSQLParser'" in sql and "false, false" in sql  # is_raw=false, is_cached=false
    assert args[0] == seed.ACTIVITY_SLUG and args[-2:] == (seed.PROGRAM_ID, seed.PROGRAM_SLUG)
    assert json.loads(args[3]) == {"firstdate": "FDOM", "lastdate": "CURRENT_DATE"}


def test_sql_slug_definitions(seed):
    assert seed.ACTIVITY_SLUG == "epson_e2e_activity" and seed.TARGETS_SLUG == "epson_e2e_targets"
    assert seed.MQ_SLUG == "epson_e2e_activity_vs_targets_mq"
    assert set(seed.SQL_SLUGS) == {seed.ACTIVITY_SLUG, seed.TARGETS_SLUG}
    for spec in seed.SQL_SLUGS.values():
        raw = spec["query_raw"]
        assert raw.startswith("SELECT {fields} FROM (") and raw.endswith(("{where_cond}", "{and_cond}"))
        # Live-verified on dev: the /refresh broadcast sends firstdate/lastdate to EVERY source, and a slug
        # without those placeholders gets them appended as WHERE filters — so both slugs declare them.
        assert "{firstdate}" in raw and "{lastdate}" in raw
        assert set(spec["cond_definition"]) == {"firstdate", "lastdate"}


def test_mq_pipeline_pins_child_conditions(seed):
    """MultiQS only applies conditions keyed by child query name, so the stored pipeline pins them."""
    result = seed.MQ_PIPELINE["queries"]["result"]
    assert result["slug"] == seed.ACTIVITY_SLUG
    assert (result["firstdate"], result["lastdate"]) == seed.MQ_RANGE
    assert seed.MQ_PIPELINE["queries"]["targets"]["slug"] == seed.TARGETS_SLUG


def test_queries_table_rejects_unsafe_identifiers(seed, monkeypatch):
    import navconfig

    values = {"QS_QUERIES_SCHEMA": "public; drop", "QS_QUERIES_TABLE": "queries"}
    monkeypatch.setattr(
        navconfig, "config", types.SimpleNamespace(get=lambda k, fallback=None: values.get(k, fallback))
    )
    with pytest.raises(SystemExit, match="unsafe"):
        seed._queries_table()
    values["QS_QUERIES_SCHEMA"] = "public"
    assert seed._queries_table() == '"public"."queries"'


def test_cli_refuses_on_production(seed, monkeypatch):
    monkeypatch.setenv("ENV", "production")
    _poison_toolkit(monkeypatch)
    for command in ("describe", "preview", "prove-policy"):
        with pytest.raises(SystemExit):
            seed.main([command])


def test_prove_policy_refuses_off_live_target(seed, monkeypatch):
    monkeypatch.setenv("ENV", "production")
    with pytest.raises(SystemExit):
        asyncio.run(seed.prove_policy())


def test_pipeline_frames_and_structure(seed):
    pipeline = seed.build_pipeline()
    assert sorted(pipeline["queries"]) == seed.EXPECTED_FRAMES
    assert {q["slug"] for q in pipeline["queries"].values()} == {seed.ACTIVITY_SLUG, seed.TARGETS_SLUG}
    assert "Join" not in pipeline and "Output" not in pipeline  # Join output can never be named "result"
    pipeline["queries"].pop("result")
    assert "result" in seed.build_pipeline()["queries"]  # fresh copy every call
    seed.check_frames(["targets", "result"])
    with pytest.raises(SystemExit):
        seed.check_frames(["result.targets"])


def test_pipeline_structurally_valid_offline(seed):
    qs = pytest.importorskip("querysource")
    if not hasattr(qs, "__path__"):  # tests/conftest.py stubs `querysource` as a bare module
        pytest.skip("querysource is stubbed in this suite; the real registry is not importable")
    from querysource.queries.multi.registry import ComponentRegistry

    result = ComponentRegistry.validate_pipeline(seed.build_pipeline())
    assert result.valid, result.errors


def test_policy_yaml_parses(seed):
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(POLICY_YAML.read_text(encoding="utf-8"))
    source_policy, slug_policy, datasource_policy = doc["policies"]
    assert source_policy["effect"] == "allow"
    assert source_policy["resources"] == ["source:query_slug:public:epson_*"]
    assert source_policy["actions"] == [seed.POLICY_ACTION]
    # querysource 5.1.2 tenant routes pre-flight `slug:execute` on the shared app evaluator (live-verified).
    assert slug_policy["effect"] == "allow"
    assert slug_policy["resources"] == ["slug:epson_e2e_*"]
    assert slug_policy["actions"] == ["slug:execute", "slug:list"]
    assert datasource_policy["resources"] == ["datasource:db", "driver:*"]
    pytest.importorskip("navigator_auth.abac.policies.evaluator")
    from navigator_auth.abac.policies.evaluator import PolicyLoader

    loaded = PolicyLoader.load_from_directory(POLICY_YAML.parent)
    assert [p.name for p in loaded] == [
        "demo_allow_epson_linked_sources",
        "demo_allow_epson_e2e_slug_execute",
        "demo_allow_epson_e2e_datasource",
    ]


def test_policy_proof_offline_allow_and_deny(seed, caplog):
    pytest.importorskip("navigator_auth.abac.policies.evaluator")
    with caplog.at_level("INFO", logger="FEAT611.seed"):
        outcome = asyncio.run(seed.run_policy_proof())
    assert outcome == {"with_policy": "allow", "without_policy": "deny"}
    logged = caplog.text
    assert "resource_type=source resource=query_slug:public:epson_e2e_activity action=source:read" in logged


def test_policy_proof_offline_non_epson_slug_denied(seed):
    pytest.importorskip("navigator_auth.abac.policies.evaluator")
    outcome = asyncio.run(seed.run_policy_proof(slug="pokemon_all_fso_odoo_new"))
    assert outcome == {"with_policy": "deny", "without_policy": "deny"}


def test_policy_proof_offline_covers_every_e2e_slug(seed):
    """The demo policy's `epson_*` pattern still matches the dedicated epson_e2e_* slugs."""
    pytest.importorskip("navigator_auth.abac.policies.evaluator")
    for slug in (seed.ACTIVITY_SLUG, seed.TARGETS_SLUG, seed.MQ_SLUG):
        assert asyncio.run(seed.run_policy_proof(slug=slug)) == {"with_policy": "allow", "without_policy": "deny"}
