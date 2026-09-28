"""FEAT-611 M2: seed_staging.assert_staging refuses anything that is not the staging DB (spec AC7).

Also proves offline (no DB, no staging) that the demo policy YAML parses and that the policy-proof
logic yields allow with the example policy dir and deny with a control dir, through a real guard.
"""

from __future__ import annotations

import asyncio
import importlib.util
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
        seed.assert_staging()


def test_refuses_when_env_is_unset(seed, monkeypatch):
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.setattr(seed, "_current_dbname", lambda: "navigator_staging")
    with pytest.raises(SystemExit):
        seed.assert_staging()


def test_refuses_when_dbname_is_not_staging(seed, monkeypatch):
    monkeypatch.setenv("ENV", "staging")
    monkeypatch.setattr(seed, "_current_dbname", lambda: "navigator")
    with pytest.raises(SystemExit, match="DBNAME"):
        seed.assert_staging()


def test_accepts_staging(seed, monkeypatch):
    monkeypatch.setenv("ENV", "staging")
    monkeypatch.setattr(seed, "_current_dbname", lambda: "navigator_STAGING")
    assert seed.assert_staging() is None


def _poison_toolkit(monkeypatch):
    poisoned = types.ModuleType("parrot_tools.querysource.toolkit")

    def __getattr__(name):  # noqa: N807 — module-level __getattr__
        pytest.fail(f"toolkit touched before the staging guard: {name}")

    poisoned.__getattr__ = __getattr__
    monkeypatch.setitem(sys.modules, "parrot_tools.querysource.toolkit", poisoned)


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


def test_cli_seed_requires_confirm_flag(seed, monkeypatch):
    monkeypatch.setenv("ENV", "staging")
    monkeypatch.setattr(seed, "_current_dbname", lambda: "navigator_staging")
    _poison_toolkit(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda *_: pytest.fail("prompted without --confirm"))
    with pytest.raises(SystemExit, match="--confirm"):
        seed.main(["seed", "--yes"])


def test_cli_seed_aborts_without_interactive_yes(seed, monkeypatch):
    monkeypatch.setenv("ENV", "staging")
    monkeypatch.setattr(seed, "_current_dbname", lambda: "navigator_staging")
    _poison_toolkit(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda *_: "no")
    with pytest.raises(SystemExit, match="aborted"):
        seed.main(["seed", "--confirm"])


def test_cli_refuses_on_production(seed, monkeypatch):
    monkeypatch.setenv("ENV", "production")
    _poison_toolkit(monkeypatch)
    for command in ("describe", "preview", "prove-policy"):
        with pytest.raises(SystemExit):
            seed.main([command])


def test_prove_policy_refuses_off_staging(seed, monkeypatch):
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
    (policy,) = doc["policies"]
    assert policy["effect"] == "allow"
    assert policy["resources"] == ["source:query_slug:public:epson_*"]
    assert policy["actions"] == [seed.POLICY_ACTION]
    pytest.importorskip("navigator_auth.abac.policies.evaluator")
    from navigator_auth.abac.policies.evaluator import PolicyLoader

    loaded = PolicyLoader.load_from_directory(POLICY_YAML.parent)
    assert [p.name for p in loaded] == ["demo_allow_epson_linked_sources"]


def test_policy_proof_offline_allow_and_deny(seed, caplog):
    pytest.importorskip("navigator_auth.abac.policies.evaluator")
    with caplog.at_level("INFO", logger="FEAT611.seed"):
        outcome = asyncio.run(seed.run_policy_proof())
    assert outcome == {"with_policy": "allow", "without_policy": "deny"}
    logged = caplog.text
    assert "resource_type=source resource=query_slug:public:epson_field_activity action=source:read" in logged


def test_policy_proof_offline_non_epson_slug_denied(seed):
    pytest.importorskip("navigator_auth.abac.policies.evaluator")
    outcome = asyncio.run(seed.run_policy_proof(slug="pokemon_all_fso_odoo_new"))
    assert outcome == {"with_policy": "deny", "without_policy": "deny"}
