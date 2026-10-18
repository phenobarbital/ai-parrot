"""Doc test for FEAT-699 validation contract budget report."""

from pathlib import Path
import re


def test_measured_budgets_reported():
    doc_path = Path(__file__).resolve().parents[2] / "docs/sdd/test-selection-validation-contract.md"
    assert doc_path.exists(), f"Documentation file {doc_path} missing"

    content = doc_path.read_text(encoding="utf-8")

    # Assert commit shas are named
    assert "d7e03cb93" in content, "Commit d7e03cb93 not named in doc"
    assert "49806c49f" in content, "Commit 49806c49f not named in doc"

    if "budget missed" in content:
        # Honest reporting when budget missed
        return

    # Parse Measured table
    # Looking for rows like:
    # | merge | contract | 197 | 38.62 |
    # | feature | contract | 197 | 38.81 |
    merge_contract_match = re.search(r"\|\s*merge\s*\|\s*contract\s*\|\s*\d+\s*\|\s*([\d.]+)\s*\|", content)
    feature_contract_match = re.search(r"\|\s*feature\s*\|\s*contract\s*\|\s*\d+\s*\|\s*([\d.]+)\s*\|", content)

    assert merge_contract_match is not None, "merge/contract row missing from Measured table"
    assert feature_contract_match is not None, "feature/contract row missing from Measured table"

    merge_seconds = float(merge_contract_match.group(1))
    feature_seconds = float(feature_contract_match.group(1))

    assert merge_seconds < 120.0, f"Merge tier time ({merge_seconds}s) exceeds budget of 120s"
    assert feature_seconds < 300.0, f"Feature tier time ({feature_seconds}s) exceeds budget of 300s"
