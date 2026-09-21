"""Assert ci.yml wires the FEAT-586 checks (TASK-3588)."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def test_ci_runs_doc_and_script_checks() -> None:
    """ci.yml references the doc tests, both installer scripts, and a dry run."""
    text = CI.read_text(encoding="utf-8")
    assert "packages/ai-parrot/tests/docs/" in text
    assert "scripts/install/install-parrot.sh" in text
    assert "scripts/install/install-parrot.ps1" in text
    assert "--dry-run" in text
