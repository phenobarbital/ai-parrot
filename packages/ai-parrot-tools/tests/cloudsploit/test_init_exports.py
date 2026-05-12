"""Tests for cloudsploit package-level re-exports (TASK-1124)."""
from pathlib import Path

import parrot_tools.cloudsploit as cs


def test_ecr_symbols_exported():
    """All new ECR public symbols are accessible from the package namespace."""
    expected = {
        "EcrCollectionPlan", "EcrCollectionResult", "EcrRepoFindings",
        "EcrRepoPlan", "EcrScanCollector", "EcrScanFinding", "EcrSeverity",
    }
    assert expected.issubset(set(cs.__all__))
    for name in expected:
        assert hasattr(cs, name), f"Missing from package namespace: {name}"


def test_existing_symbols_still_exported():
    """Pre-existing symbols are not removed by the re-export additions."""
    for name in [
        "CloudProvider", "CloudSploitConfig", "CloudSploitToolkit",
        "ComparisonReport", "ComplianceFramework", "ScanFinding",
        "ScanResult", "ScanSummary", "SeverityLevel",
    ]:
        assert hasattr(cs, name), f"Regression: {name} no longer exported"


def test_all_is_sorted():
    """__all__ is sorted alphabetically."""
    assert cs.__all__ == sorted(cs.__all__)


def test_example_plan_yaml_loads():
    """ecr_plan.example.yaml loads as a valid EcrCollectionPlan with 23 repos."""
    pkg_dir = Path(cs.__file__).parent
    example = pkg_dir / "ecr_plan.example.yaml"
    assert example.is_file(), f"Example plan not found at {example}"
    plan = cs.EcrCollectionPlan.from_yaml(example)
    assert plan.region == "us-east-2"
    assert plan.concurrency == 5
    assert len(plan.repos) == 23
    names = {r.name for r in plan.repos}
    assert "navigator-api-tf" in names
    assert "zammad-teams-middleware-tf" in names
