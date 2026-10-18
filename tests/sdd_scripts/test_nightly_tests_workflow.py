"""Structure test for .github/workflows/nightly-tests.yml (FEAT-699 TASK-4453)."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WF = ROOT / ".github" / "workflows" / "nightly-tests.yml"


def _load() -> dict:
    return yaml.safe_load(WF.read_text(encoding="utf-8"))


def test_matrix_covers_every_package_suite():
    suites = _load()["jobs"]["suites"]["strategy"]["matrix"]["suite"]
    expected = sorted(p.parent.name for p in ROOT.glob("packages/*/tests")) + ["root"]
    assert sorted(suites) == sorted(expected)
    assert _load()["jobs"]["suites"]["strategy"]["fail-fast"] is False


def test_triggers_and_marker():
    data = _load()
    triggers = data.get(True, data.get("on"))
    assert triggers["schedule"][0]["cron"] == "17 6 * * *"
    assert "workflow_dispatch" in triggers
    assert 'not real_llm' in WF.read_text(encoding="utf-8")


def test_read_only_and_no_push():
    data = _load()
    assert data["permissions"] == {"contents": "read", "actions": "read"}
    text = WF.read_text(encoding="utf-8")
    assert "contents: write" not in text
    assert "git push" not in text
    assert "git commit" not in text
    assert "dawidd6" not in text


def test_summary_job():
    summary = _load()["jobs"]["summary"]
    assert summary["needs"] == "suites"
    assert summary["if"] == "always()"
