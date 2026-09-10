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
    assert by_name["parrot"]["options"]["path"].endswith("dashboards-parrot")
    # The two providers must not share a path, or dashboards provision twice.
    assert by_name["parrot"]["options"]["path"] != by_name["claudestats"]["options"]["path"]


def test_parrot_path_is_not_nested_under_claudestats():
    """The parrot provider's path must be a SIBLING of claudestats', not a child.

    Empirically verified during implementation: a dashboard JSON placed under
    a subdirectory of claudestats' scanned path was silently claimed by
    `claudestats` instead of `parrot` and misfiled into "Claude Code" — not
    duplicated, just wrong (defeats AC-9). Grafana's file provisioner scans
    its configured path recursively, so any provider whose path is a child of
    another provider's path risks exactly this. Pinning both provider paths
    here (rather than only asserting inequality) turns that empirical finding
    into a permanent regression guard.
    """
    cfg = yaml.safe_load(DASHBOARDS_YML.read_text())
    by_name = {p["name"]: p for p in cfg["providers"]}
    claudestats_path = by_name["claudestats"]["options"]["path"].rstrip("/")
    parrot_path = by_name["parrot"]["options"]["path"].rstrip("/")
    assert not parrot_path.startswith(claudestats_path + "/"), (
        f"parrot provider path {parrot_path!r} is nested under claudestats' "
        f"scanned path {claudestats_path!r} — claudestats will recursively "
        "pick up parrot's dashboards and misfile them into 'Claude Code'"
    )
