"""Grafana dashboard-provisioning contract.

FEAT-548 TASK-3109 / AC-9. The `parrot` provider must exist alongside the
existing `claudestats` provider, point at its own subdirectory, and declare
the `AI-Parrot` folder — never sharing a path with `claudestats` (which would
provision every dashboard twice, in two folders).
"""
from __future__ import annotations

from pathlib import Path

import yaml

DASHBOARDS_YML = Path(__file__).resolve().parents[5] / "docker/grafana/provisioning/dashboards/dashboards.yml"


def test_provisioning_yaml_parses_and_has_both_providers():
    """dashboards.yml declares claudestats and parrot, each with its own folder."""
    cfg = yaml.safe_load(DASHBOARDS_YML.read_text())
    by_name = {p["name"]: p for p in cfg["providers"]}
    assert set(by_name) == {"claudestats", "parrot"}
    assert by_name["parrot"]["folder"] == "AI-Parrot"
    assert by_name["parrot"]["options"]["path"].endswith("/parrot")
    # The two providers must not share a path, or dashboards provision twice.
    assert by_name["parrot"]["options"]["path"] != by_name["claudestats"]["options"]["path"]
