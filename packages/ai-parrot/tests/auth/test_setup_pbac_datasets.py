"""Unit tests for setup_pbac datasets directory extension (TASK-1045).

Tests verify that ``setup_pbac()`` correctly loads ``policies/datasets/*.yml``
into the same ``PolicyEvaluator`` as the top-level and agents subdirectory,
using the same warn-and-continue pattern.

All tests mock the navigator-auth stack to avoid needing a live installation.
"""
from __future__ import annotations

import logging
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _write_sample_policy(directory: Path, filename: str = "test.yml") -> Path:
    """Write a minimal policy YAML to *directory*."""
    policy_text = (
        "- name: test-policy\n"
        "  effect: DENY\n"
        "  subjects:\n"
        "    users: [\"test@example.com\"]\n"
        "  resources:\n"
        "    - type: DATASET\n"
        "      name: financial_data\n"
        "  actions: [\"dataset:read\"]\n"
    )
    path = directory / filename
    path.write_text(policy_text)
    return path


def _make_navigator_auth_mocks(load_results: dict | None = None):
    """Build a minimal set of navigator-auth mocks for setup_pbac patching.

    Args:
        load_results: Mapping ``{path_str: list_of_policy_objects}`` returned
            by ``PolicyLoader.load_from_directory`` per call path. If None, all
            calls return an empty list.
    """
    def _load_from_dir(directory):
        key = str(directory)
        if load_results and key in load_results:
            return load_results[key]
        return []

    mock_evaluator = MagicMock()
    mock_evaluator.load_policies.return_value = None
    mock_evaluator._default_effect = None

    mock_pdp = MagicMock()
    mock_pdp.setup.return_value = None
    mock_pdp._evaluator = mock_evaluator

    mock_guardian = MagicMock()

    mock_PolicyEvaluator = MagicMock(return_value=mock_evaluator)
    mock_PolicyLoader = MagicMock()
    mock_PolicyLoader.load_from_directory.side_effect = _load_from_dir

    # Make PolicyEffect.DENY a proper mock with a .name attribute
    mock_deny_effect = MagicMock()
    mock_deny_effect.name = "DENY"
    mock_PolicyEffect = MagicMock()
    mock_PolicyEffect.DENY = mock_deny_effect

    mock_YAMLStorage = MagicMock(return_value=MagicMock())
    mock_PDP = MagicMock(return_value=mock_pdp)

    return {
        "PolicyEvaluator": mock_PolicyEvaluator,
        "PolicyLoader": mock_PolicyLoader,
        "PolicyEffect": mock_PolicyEffect,
        "YAMLStorage": mock_YAMLStorage,
        "PDP": mock_PDP,
        "evaluator": mock_evaluator,
        "pdp": mock_pdp,
        "guardian": mock_guardian,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestSetupPbacDatasetsExtension:
    def test_loads_datasets_subdir(self, tmp_path: Path, caplog):
        """Creates a temp policies/datasets/x.yml; verifies setup_pbac logs
        N policies loaded from the datasets subdir."""
        from aiohttp import web

        # Create policy dir structure: policies/ + policies/datasets/finance.yml
        policy_dir = tmp_path / "policies"
        policy_dir.mkdir()
        datasets_dir = policy_dir / "datasets"
        datasets_dir.mkdir()
        _write_sample_policy(datasets_dir, "finance.yml")

        # Build a fake policy object that load_from_directory returns
        fake_dataset_policy = MagicMock(name="DatasetPolicy")
        mocks = _make_navigator_auth_mocks(
            load_results={str(datasets_dir): [fake_dataset_policy]}
        )

        app = web.Application()
        app["security"] = mocks["guardian"]

        with patch.dict("sys.modules", {
            "navigator_auth": MagicMock(),
            "navigator_auth.abac": MagicMock(),
            "navigator_auth.abac.pdp": MagicMock(PDP=mocks["PDP"]),
            "navigator_auth.abac.policies": MagicMock(),
            "navigator_auth.abac.policies.evaluator": MagicMock(
                PolicyEvaluator=mocks["PolicyEvaluator"],
                PolicyLoader=mocks["PolicyLoader"],
            ),
            "navigator_auth.abac.policies.abstract": MagicMock(
                PolicyEffect=mocks["PolicyEffect"]
            ),
            "navigator_auth.abac.storages": MagicMock(),
            "navigator_auth.abac.storages.yaml_storage": MagicMock(
                YAMLStorage=mocks["YAMLStorage"]
            ),
        }):
            from parrot.auth import pbac as pbac_module
            import importlib
            importlib.reload(pbac_module)

            with caplog.at_level(logging.INFO, logger="parrot.auth.pbac"):
                result = pbac_module.setup_pbac(app, policy_dir=str(policy_dir))

        # Should succeed (not None)
        assert result != (None, None, None), (
            "setup_pbac returned (None, None, None) — check mock wiring"
        )
        # INFO log about datasets subdir
        info_msgs = [r.message for r in caplog.records if r.levelname == "INFO"]
        assert any("per-dataset" in msg for msg in info_msgs), (
            f"Expected 'per-dataset' in INFO log. Got: {info_msgs}"
        )

    def test_continues_when_datasets_subdir_missing(self, tmp_path: Path, caplog):
        """When policies/datasets/ does not exist, setup_pbac succeeds silently."""
        from aiohttp import web

        policy_dir = tmp_path / "policies"
        policy_dir.mkdir()
        # No datasets/ subdirectory created

        mocks = _make_navigator_auth_mocks()
        app = web.Application()
        app["security"] = mocks["guardian"]

        with patch.dict("sys.modules", {
            "navigator_auth": MagicMock(),
            "navigator_auth.abac": MagicMock(),
            "navigator_auth.abac.pdp": MagicMock(PDP=mocks["PDP"]),
            "navigator_auth.abac.policies": MagicMock(),
            "navigator_auth.abac.policies.evaluator": MagicMock(
                PolicyEvaluator=mocks["PolicyEvaluator"],
                PolicyLoader=mocks["PolicyLoader"],
            ),
            "navigator_auth.abac.policies.abstract": MagicMock(
                PolicyEffect=mocks["PolicyEffect"]
            ),
            "navigator_auth.abac.storages": MagicMock(),
            "navigator_auth.abac.storages.yaml_storage": MagicMock(
                YAMLStorage=mocks["YAMLStorage"]
            ),
        }):
            from parrot.auth import pbac as pbac_module
            import importlib
            importlib.reload(pbac_module)

            with caplog.at_level(logging.WARNING, logger="parrot.auth.pbac"):
                result = pbac_module.setup_pbac(app, policy_dir=str(policy_dir))

        # Should succeed — no datasets/ dir is not an error
        assert result != (None, None, None)
        # No WARNING about datasets
        warning_msgs = [r.message for r in caplog.records if r.levelname == "WARNING"]
        assert not any("per-dataset" in msg for msg in warning_msgs), (
            f"Unexpected WARNING about datasets. Got: {warning_msgs}"
        )

    def test_warn_on_datasets_yaml_parse_error(self, tmp_path: Path, caplog):
        """When PolicyLoader raises on the datasets subdir, a WARNING is logged
        and setup_pbac continues (agents and top-level policies still load)."""
        from aiohttp import web

        policy_dir = tmp_path / "policies"
        policy_dir.mkdir()
        datasets_dir = policy_dir / "datasets"
        datasets_dir.mkdir()
        # Create a file so the directory exists
        (datasets_dir / "bad.yml").write_text("!invalid: yaml: :")

        mocks = _make_navigator_auth_mocks()
        # Make load_from_directory raise only on the datasets subdir
        # Use Path basename to avoid matching test function names that contain "dataset"
        datasets_dir_str = str(datasets_dir)

        def _load_from_dir_with_error(directory):
            if str(directory) == datasets_dir_str:
                raise ValueError("YAML parse error")
            return []

        mocks["PolicyLoader"].load_from_directory.side_effect = _load_from_dir_with_error

        app = web.Application()
        app["security"] = mocks["guardian"]

        with patch.dict("sys.modules", {
            "navigator_auth": MagicMock(),
            "navigator_auth.abac": MagicMock(),
            "navigator_auth.abac.pdp": MagicMock(PDP=mocks["PDP"]),
            "navigator_auth.abac.policies": MagicMock(),
            "navigator_auth.abac.policies.evaluator": MagicMock(
                PolicyEvaluator=mocks["PolicyEvaluator"],
                PolicyLoader=mocks["PolicyLoader"],
            ),
            "navigator_auth.abac.policies.abstract": MagicMock(
                PolicyEffect=mocks["PolicyEffect"]
            ),
            "navigator_auth.abac.storages": MagicMock(),
            "navigator_auth.abac.storages.yaml_storage": MagicMock(
                YAMLStorage=mocks["YAMLStorage"]
            ),
        }):
            from parrot.auth import pbac as pbac_module
            import importlib
            importlib.reload(pbac_module)

            with caplog.at_level(logging.WARNING, logger="parrot.auth.pbac"):
                result = pbac_module.setup_pbac(app, policy_dir=str(policy_dir))

        # setup_pbac must still succeed (doesn't abort)
        assert result != (None, None, None), (
            "setup_pbac should NOT abort when datasets subdir has a parse error"
        )
        # A WARNING about the datasets subdir must be logged
        warning_msgs = [r.message for r in caplog.records if r.levelname == "WARNING"]
        assert any("per-dataset" in msg for msg in warning_msgs), (
            f"Expected WARNING about per-dataset. Got: {warning_msgs}"
        )

    def test_agents_and_datasets_both_load(self, tmp_path: Path, caplog):
        """Both agents/ and datasets/ subdirs exist; all policies are merged."""
        from aiohttp import web

        policy_dir = tmp_path / "policies"
        policy_dir.mkdir()
        agents_dir = policy_dir / "agents"
        agents_dir.mkdir()
        _write_sample_policy(agents_dir, "agent.yml")
        datasets_dir = policy_dir / "datasets"
        datasets_dir.mkdir()
        _write_sample_policy(datasets_dir, "dataset.yml")

        fake_agent_policy = MagicMock(name="AgentPolicy")
        fake_dataset_policy = MagicMock(name="DatasetPolicy")
        mocks = _make_navigator_auth_mocks(
            load_results={
                str(agents_dir): [fake_agent_policy],
                str(datasets_dir): [fake_dataset_policy],
            }
        )

        app = web.Application()
        app["security"] = mocks["guardian"]

        with patch.dict("sys.modules", {
            "navigator_auth": MagicMock(),
            "navigator_auth.abac": MagicMock(),
            "navigator_auth.abac.pdp": MagicMock(PDP=mocks["PDP"]),
            "navigator_auth.abac.policies": MagicMock(),
            "navigator_auth.abac.policies.evaluator": MagicMock(
                PolicyEvaluator=mocks["PolicyEvaluator"],
                PolicyLoader=mocks["PolicyLoader"],
            ),
            "navigator_auth.abac.policies.abstract": MagicMock(
                PolicyEffect=mocks["PolicyEffect"]
            ),
            "navigator_auth.abac.storages": MagicMock(),
            "navigator_auth.abac.storages.yaml_storage": MagicMock(
                YAMLStorage=mocks["YAMLStorage"]
            ),
        }):
            from parrot.auth import pbac as pbac_module
            import importlib
            importlib.reload(pbac_module)

            with caplog.at_level(logging.INFO, logger="parrot.auth.pbac"):
                result = pbac_module.setup_pbac(app, policy_dir=str(policy_dir))

        assert result != (None, None, None)
        info_msgs = [r.message for r in caplog.records if r.levelname == "INFO"]
        assert any("per-agent" in msg for msg in info_msgs), (
            f"Expected per-agent INFO. Got: {info_msgs}"
        )
        assert any("per-dataset" in msg for msg in info_msgs), (
            f"Expected per-dataset INFO. Got: {info_msgs}"
        )
