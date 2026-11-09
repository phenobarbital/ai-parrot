"""FEAT-847 §10 — the declared documentation page exists and covers the operator facts."""

from __future__ import annotations

from pathlib import Path

from parrot.sdd.techwiki.check import evaluate_docs, resolve_docs_policy

REPO_ROOT = Path(__file__).resolve().parents[4]
SPEC = REPO_ROOT / "sdd/specs/sdd-agy-compatibility.spec.md"
PAGE = REPO_ROOT / "wiki/sdd-tooling/sdd/agy-compatibility.md"


def test_spec_documentation_decision_is_ok() -> None:
    policy, pages, api_modules = resolve_docs_policy(SPEC)
    decision = evaluate_docs(policy, pages, api_modules, REPO_ROOT)
    assert decision.status == "ok", (decision.reason_codes, decision.missing)


def test_page_names_operator_facts() -> None:
    """Test that the page contains essential operator facts."""
    content = PAGE.read_text(encoding="utf-8")
    
    # Check for essential operator facts
    assert "--host google" in content
    assert "PARROT_SDD_AGY_UNATTENDED" in content
    assert "run_command|write_file|edit_file" in content
    assert "install.sh" in content
    assert "snap" in content
    assert "docs/sdd/AGY.md" in content