"""Contract tests for the bundled experts shipped in the wheel (FEAT-778 §8 Q7)."""

import importlib.resources
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]


def test_bundled_resources_list_both_experts() -> None:
    """The bundled experts are discoverable via importlib.resources.files()."""
    bundled_dir = importlib.resources.files("parrot.experts.bundled")

    # Both experts should exist
    cve_analyst_dir = bundled_dir / "cve-analyst"
    cve_remediation_dir = bundled_dir / "cve-remediation"

    assert cve_analyst_dir.is_dir()
    assert cve_remediation_dir.is_dir()

    # Each expert should have its expert.yaml
    assert (cve_analyst_dir / "expert.yaml").is_file()
    assert (cve_remediation_dir / "expert.yaml").is_file()

    # Each expert should have its persona.md
    assert (cve_analyst_dir / "persona.md").is_file()
    assert (cve_remediation_dir / "persona.md").is_file()

    # Each expert should have its identity/ directory
    assert (cve_analyst_dir / "identity").is_dir()
    assert (cve_remediation_dir / "identity").is_dir()

    # Each expert should have its knowledge/ directory
    assert (cve_analyst_dir / "knowledge").is_dir()
    assert (cve_remediation_dir / "knowledge").is_dir()

    # Each expert should have its rules/ directory
    assert (cve_analyst_dir / "rules").is_dir()
    assert (cve_remediation_dir / "rules").is_dir()

    # Each expert should have its identity files
    identity_files = {"backstory.md", "capabilities.md", "goal.md", "rationale.md", "role.md"}
    assert {f.name for f in (cve_analyst_dir / "identity").glob("*.md")} == identity_files
    assert {f.name for f in (cve_remediation_dir / "identity").glob("*.md")} == identity_files

    # Each expert should have its knowledge files
    cve_analyst_knowledge = {f.name for f in (cve_analyst_dir / "knowledge").glob("*.md")}
    assert cve_analyst_knowledge == {
        "cve-triage-method.md",
        "cvss-epss-kev.md",
        "workspace-impact-analysis.md",
    }

    cve_remediation_knowledge = {f.name for f in (cve_remediation_dir / "knowledge").glob("*.md")}
    assert cve_remediation_knowledge == {
        "pinning-and-verification.md",
        "remediation-patterns-by-ecosystem.md",
        "remediation-plan-template.md",
    }

    # Each expert should have its governance rules
    assert (cve_analyst_dir / "rules" / "governance.md").is_file()
    assert (cve_remediation_dir / "rules" / "governance.md").is_file()


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is required for the wheel test")
def test_built_wheel_contains_bundles(tmp_path: Path) -> None:
    """The built wheel contains every file of cve-analyst and cve-remediation."""
    wheel_path = tmp_path / "wheel"

    # Build the wheel
    result = subprocess.run(
        ["uv", "build", "--wheel", "packages/ai-parrot", "--out-dir", str(wheel_path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]

    # Find the built wheel
    wheels = list(wheel_path.glob("*.whl"))
    assert len(wheels) == 1, f"Expected 1 wheel, found {len(wheels)}: {wheels}"
    wheel_path = wheels[0]

    # Open the wheel and check for all expected files
    with zipfile.ZipFile(wheel_path, "r") as wheel:
        namelist = set(wheel.namelist())

        # Expected files for cve-analyst
        cve_analyst_files = {
            "parrot/experts/bundled/cve-analyst/expert.yaml",
            "parrot/experts/bundled/cve-analyst/persona.md",
            "parrot/experts/bundled/cve-analyst/identity/backstory.md",
            "parrot/experts/bundled/cve-analyst/identity/capabilities.md",
            "parrot/experts/bundled/cve-analyst/identity/goal.md",
            "parrot/experts/bundled/cve-analyst/identity/rationale.md",
            "parrot/experts/bundled/cve-analyst/identity/role.md",
            "parrot/experts/bundled/cve-analyst/knowledge/cve-triage-method.md",
            "parrot/experts/bundled/cve-analyst/knowledge/cvss-epss-kev.md",
            "parrot/experts/bundled/cve-analyst/knowledge/workspace-impact-analysis.md",
            "parrot/experts/bundled/cve-analyst/rules/governance.md",
        }

        # Expected files for cve-remediation
        cve_remediation_files = {
            "parrot/experts/bundled/cve-remediation/expert.yaml",
            "parrot/experts/bundled/cve-remediation/persona.md",
            "parrot/experts/bundled/cve-remediation/identity/backstory.md",
            "parrot/experts/bundled/cve-remediation/identity/capabilities.md",
            "parrot/experts/bundled/cve-remediation/identity/goal.md",
            "parrot/experts/bundled/cve-remediation/identity/rationale.md",
            "parrot/experts/bundled/cve-remediation/identity/role.md",
            "parrot/experts/bundled/cve-remediation/knowledge/pinning-and-verification.md",
            "parrot/experts/bundled/cve-remediation/knowledge/remediation-patterns-by-ecosystem.md",
            "parrot/experts/bundled/cve-remediation/knowledge/remediation-plan-template.md",
            "parrot/experts/bundled/cve-remediation/rules/governance.md",
        }

        # Check that all expected files are in the wheel
        for file in cve_analyst_files:
            assert file in namelist, f"Expected {file} in wheel, but it's missing"

        for file in cve_remediation_files:
            assert file in namelist, f"Expected {file} in wheel, but it's missing"

        # Verify the __init__.py is also present
        assert "parrot/experts/bundled/__init__.py" in namelist
