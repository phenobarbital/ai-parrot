"""Presence + structure tests for the Flex KPI kb docs (FEAT-491 TASK-2695)."""

from pathlib import Path

# Repo root, resolved the same worktree-safe way as the other flex tests:
# packages/ai-parrot/tests/unit/bots/<this file> -> repo root is parents[5].
_REPO_ROOT = Path(__file__).resolve().parents[5]
_KB_DIR = _REPO_ROOT / "agents" / "flex_dashboard" / "kb"

_REQUIRED_DOCS = {
    "payroll_contribution.md",
    "pay_code_allocation.md",
    "rep_utilization.md",
    "proximity_staffing.md",
    "datasets.md",
}

_REQUIRED_SECTIONS = [
    "Definition",
    "Formula",
    "Source columns",
    "Normalization rules",
    "Filters",
    "Worked example",
]


def test_kb_docs_present_and_structured():
    docs = sorted(_KB_DIR.glob("*.md"))
    assert {d.name for d in docs} >= _REQUIRED_DOCS

    for doc in docs:
        text = doc.read_text()
        for section in _REQUIRED_SECTIONS:
            assert section in text, f"{doc.name} missing {section!r} section"


def test_payroll_pct_denominator_is_documented():
    text = (_KB_DIR / "payroll_contribution.md").read_text()
    assert "Revenue ALONE" in text
    assert "sum(Payroll) / sum(Revenue)" in text


def test_rep_utilization_recompute_rule_is_documented():
    text = (_KB_DIR / "rep_utilization.md").read_text()
    assert "RECOMPUTED" in text
    assert "employees_worked / average_active" in text
    assert "cross_check_utilization" in text or "cross-check" in text.lower()


def test_worked_examples_match_hand_computation():
    payroll_doc = (_KB_DIR / "payroll_contribution.md").read_text()
    assert "0.15046372734425384" in payroll_doc

    rep_doc = (_KB_DIR / "rep_utilization.md").read_text()
    assert "0.19047619047619047" in rep_doc
    assert "0.1456953642384106" in rep_doc

    proximity_doc = (_KB_DIR / "proximity_staffing.md").read_text()
    assert "661.38" in proximity_doc
