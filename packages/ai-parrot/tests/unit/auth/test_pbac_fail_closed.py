"""Unit tests for PARROT_SAAS_MODE flag + setup_pbac fail-closed (FEAT-446)."""
from __future__ import annotations

import importlib
import sys

import parrot.auth.pbac as pbac_module
import pytest
import yaml
from aiohttp import web
from parrot.auth.pbac import setup_pbac

_VALID_POLICY = {
    "version": "1.0",
    "defaults": {"effect": "deny"},
    "policies": [
        {
            "name": "test_allow_all_tools",
            "effect": "allow",
            "resources": ["tool:*"],
            "actions": ["tool:execute"],
            "subjects": {"groups": ["*"]},
            "priority": 10,
        }
    ],
}


class TestSaasModeFlag:
    """Verify PARROT_SAAS_MODE parses from the environment via parrot.conf."""

    def test_default_false(self, monkeypatch):
        monkeypatch.delenv("PARROT_SAAS_MODE", raising=False)
        from parrot import conf

        importlib.reload(conf)
        try:
            assert conf.PARROT_SAAS_MODE is False
        finally:
            importlib.reload(conf)

    def test_env_true(self, monkeypatch):
        monkeypatch.setenv("PARROT_SAAS_MODE", "true")
        from parrot import conf

        importlib.reload(conf)
        try:
            assert conf.PARROT_SAAS_MODE is True
        finally:
            monkeypatch.delenv("PARROT_SAAS_MODE", raising=False)
            importlib.reload(conf)


class TestSetupPbacFailClosed:
    """Verify setup_pbac() fail-open (legacy) vs fail-closed (SaaS mode)."""

    def test_missing_policy_dir_raises_in_saas_mode(self, monkeypatch, tmp_path):
        monkeypatch.setattr(pbac_module, "PARROT_SAAS_MODE", True)
        missing_dir = tmp_path / "does-not-exist"

        with pytest.raises(RuntimeError, match="policy directory"):
            setup_pbac(app=object(), policy_dir=str(missing_dir))

    def test_missing_policy_dir_returns_nones_legacy(self, monkeypatch, tmp_path):
        monkeypatch.setattr(pbac_module, "PARROT_SAAS_MODE", False)
        missing_dir = tmp_path / "does-not-exist"

        result = setup_pbac(app=object(), policy_dir=str(missing_dir))

        assert result == (None, None, None)

    def test_import_error_raises_in_saas_mode(self, monkeypatch, tmp_path):
        monkeypatch.setattr(pbac_module, "PARROT_SAAS_MODE", True)
        # Force the internal `from navigator_auth.abac.pdp import PDP` to raise
        # ImportError, simulating navigator-auth not being installed.
        monkeypatch.setitem(sys.modules, "navigator_auth.abac.pdp", None)

        with pytest.raises(RuntimeError, match="navigator-auth ABAC module"):
            setup_pbac(app=object(), policy_dir=str(tmp_path))

    def test_import_error_returns_nones_legacy(self, monkeypatch, tmp_path):
        monkeypatch.setattr(pbac_module, "PARROT_SAAS_MODE", False)
        monkeypatch.setitem(sys.modules, "navigator_auth.abac.pdp", None)

        result = setup_pbac(app=object(), policy_dir=str(tmp_path))

        assert result == (None, None, None)


class TestSubPolicyLoadFailClosed:
    """Code-review fix: the per-agent/per-dataset sub-policy loaders used
    to silently continue on failure regardless of PARROT_SAAS_MODE,
    inconsistent with every other failure path in setup_pbac().
    """

    def test_agent_policy_load_error_raises_in_saas_mode(self, monkeypatch, tmp_path):
        (tmp_path / "top.yaml").write_text(yaml.dump(_VALID_POLICY))
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        # Malformed YAML: PolicyLoader should raise while parsing this.
        (agents_dir / "broken.yaml").write_text("::: not valid: [yaml")

        monkeypatch.setattr(pbac_module, "PARROT_SAAS_MODE", True)

        with pytest.raises(RuntimeError, match="per-agent policies"):
            setup_pbac(app=object(), policy_dir=str(tmp_path))

    def test_agent_policy_load_error_continues_in_legacy_mode(
        self, monkeypatch, tmp_path
    ):
        (tmp_path / "top.yaml").write_text(yaml.dump(_VALID_POLICY))
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / "broken.yaml").write_text("::: not valid: [yaml")

        monkeypatch.setattr(pbac_module, "PARROT_SAAS_MODE", False)

        pdp, evaluator, _guardian = setup_pbac(
            app=web.Application(), policy_dir=str(tmp_path)
        )

        # Top-level policy still loads; the broken agent sub-policy is
        # skipped with a warning (unchanged legacy behavior).
        assert pdp is not None
        assert evaluator is not None

    def test_dataset_policy_load_error_raises_in_saas_mode(self, monkeypatch, tmp_path):
        (tmp_path / "top.yaml").write_text(yaml.dump(_VALID_POLICY))
        datasets_dir = tmp_path / "datasets"
        datasets_dir.mkdir()
        (datasets_dir / "broken.yaml").write_text("::: not valid: [yaml")

        monkeypatch.setattr(pbac_module, "PARROT_SAAS_MODE", True)

        with pytest.raises(RuntimeError, match="per-dataset policies"):
            setup_pbac(app=object(), policy_dir=str(tmp_path))
