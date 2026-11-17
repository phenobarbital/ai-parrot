"""Structure test for .github/workflows/nightly-tests.yml (FEAT-699 TASK-4453)."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WF = ROOT / ".github" / "workflows" / "nightly-tests.yml"


def _load() -> dict:
    return yaml.safe_load(WF.read_text(encoding="utf-8"))


#: Matrix suites that are NOT a ``packages/*/tests`` directory: the repo-root suite, and the
#: admin UI's vitest suite (FEAT-709 TASK-4537), which lives at ``packages/ai-parrot-server/ui``
#: and runs on the workflow's Node/pnpm path rather than the Python one.
NON_PACKAGE_SUITES = ("root", "admin-ui")


def test_matrix_covers_every_package_suite():
    suites = _load()["jobs"]["suites"]["strategy"]["matrix"]["suite"]
    expected = sorted(p.parent.name for p in ROOT.glob("packages/*/tests")) + list(NON_PACKAGE_SUITES)
    # Strict equality on purpose: a new packages/*/tests directory that nobody added to the
    # matrix still fails here, and so does a matrix entry that matches nothing.
    assert sorted(suites) == sorted(expected)
    assert _load()["jobs"]["suites"]["strategy"]["fail-fast"] is False


def test_triggers_and_marker():
    data = _load()
    triggers = data.get(True, data.get("on"))
    assert triggers["schedule"][0]["cron"] == "17 6 * * *"
    assert "workflow_dispatch" in triggers
    assert "not real_llm" in WF.read_text(encoding="utf-8")


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


def test_core_timeout_does_not_add_a_duplicate_matrix_job() -> None:
    """Timeout metadata must augment the core suite, not create a second job."""
    suites = _load()["jobs"]["suites"]
    matrix = suites["strategy"]["matrix"]
    assert "timeout" not in matrix
    assert matrix["include"] == [{"suite": "ai-parrot", "timeout": 60}]
    assert suites["timeout-minutes"] == "${{ matrix.timeout || 30 }}"


def test_ui_commands_use_the_directory_with_the_lockfile() -> None:
    """The repository root is not a pnpm workspace."""
    steps = _load()["jobs"]["suites"]["steps"]
    install = next(step for step in steps if step.get("name") == "Install Node dependencies")
    assert (ROOT / install["working-directory"] / "pnpm-lock.yaml").is_file()
    run = next(step["run"] for step in steps if step.get("name") == "Run suite")
    assert "pnpm --dir packages/ai-parrot-server/ui exec vitest" in run
    assert "uv run --no-sync pytest" in run
    assert "--timeout=120" in run
