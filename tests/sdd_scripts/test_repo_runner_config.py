"""Tests for repo runner config (.parrot/test_runners.toml) and registry loading."""

import json
from pathlib import Path

from parrot.flows.dev_loop.test_scope.runners.registry import load_registry


def test_repo_runner_config_loads_and_has_valid_vitest_cwd():
    """Verify load_registry loads .parrot/test_runners.toml and vitest cwd contains package.json."""
    repo_root = Path(__file__).resolve().parents[2]
    registry = load_registry(repo_root)

    # Check that settings were loaded via settings_for
    assert registry.settings_for("pytest")["timeout_s"] == "60"
    assert registry.settings_for("vitest")["timeout_s"] == "120"
    assert registry.settings_for("cargo")["timeout_s"] == "300"
    assert registry.settings_for("parrot-e2e")["timeout_s"] == "900"

    # Check timeout_for helper
    assert registry.timeout_for("pytest") == 60
    assert registry.timeout_for("vitest") == 120
    assert registry.timeout_for("cargo") == 300
    assert registry.timeout_for("parrot-e2e") == 900

    # Verify vitest cwd setting and package.json presence
    vitest_settings = registry.settings_for("vitest")
    assert "cwd" in vitest_settings
    vitest_cwd = repo_root / vitest_settings["cwd"]
    assert vitest_cwd.is_dir()

    package_json = vitest_cwd / "package.json"
    assert package_json.is_file()

    with open(package_json, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, dict)
