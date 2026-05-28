"""Verifies the legacy parrot.bots.flow package has been deleted (FEAT-196 TASK-1316).

Acceptance criteria:
- parrot/bots/flow/ directory does not exist
- No actual import statements using parrot.bots.flow (singular) in source
- No actual import statements using parrot.bots.flow (singular) in tests
- parrot.bots.flows imports cleanly after deletion
"""
import pathlib
import subprocess


def test_legacy_package_directory_deleted():
    """parrot/bots/flow/ directory no longer exists in the worktree."""
    import sys  # noqa: PLC0415

    # Find the parrot package directory via sys.path
    parrot_bots_dir = None
    for p in sys.path:
        candidate = pathlib.Path(p) / "parrot" / "bots"
        if candidate.exists():
            parrot_bots_dir = candidate
            break

    if parrot_bots_dir is None:
        # Fallback: use __file__ to find tests dir, then locate src
        tests_dir = pathlib.Path(__file__).resolve().parent
        # Go up to packages/ai-parrot
        pkg_dir = tests_dir
        while pkg_dir.name != "ai-parrot" and pkg_dir.parent != pkg_dir:
            pkg_dir = pkg_dir.parent
        parrot_bots_dir = pkg_dir / "src" / "parrot" / "bots"

    legacy_dir = parrot_bots_dir / "flow"
    assert not legacy_dir.exists(), (
        f"Legacy parrot/bots/flow/ directory still exists at {legacy_dir}. "
        "Run: git rm -r packages/ai-parrot/src/parrot/bots/flow/ && "
        "find packages/ai-parrot/src/parrot/bots/flow -empty -delete"
    )


def _find_repo_root() -> pathlib.Path:
    """Find the repo root (the directory containing packages/)."""
    candidate = pathlib.Path(__file__).resolve()
    while candidate != candidate.parent:
        if (candidate / "packages").is_dir():
            return candidate
        candidate = candidate.parent
    return pathlib.Path.cwd()


def _grep_for_legacy_imports(search_dir: str) -> list:
    """Run grep and return lines with actual legacy import statements."""
    repo_root = _find_repo_root()
    target = str(repo_root / search_dir)

    result = subprocess.run(
        ["grep", "-rn", r"parrot\.bots\.flow\b", target],
        capture_output=True, text=True
    )
    if result.returncode != 0 and not result.stdout:
        return []

    bad_lines = []
    for line in result.stdout.splitlines():
        if "parrot.bots.flows" in line:
            continue
        if "__pycache__" in line:
            continue
        content = line.split(":", 2)[-1].strip() if ":" in line else line
        if content.startswith("#") or ">>>" in content:
            continue
        # Skip string literals (assertions checking for absence of legacy import)
        if "assert " in content and '"from parrot.bots.flow' in content:
            continue
        if "assert " in content and "'from parrot.bots.flow" in content:
            continue
        # Skip other string-literal contexts
        if 'not in src' in content or 'not in source' in content:
            continue
        # Only flag actual import statements (at start of statement)
        stripped = content.lstrip()
        if stripped.startswith("from parrot.bots.flow") or stripped.startswith("import parrot.bots.flow"):
            bad_lines.append(line)
    return bad_lines


def test_no_legacy_bots_flow_import_in_source():
    """No actual import statements using parrot.bots.flow in source files."""
    bad_lines = _grep_for_legacy_imports("packages/ai-parrot/src/")
    assert bad_lines == [], (
        "Legacy parrot.bots.flow import statements found in source:\n"
        + "\n".join(bad_lines)
    )


def test_no_legacy_bots_flow_import_in_tests():
    """No actual import statements using parrot.bots.flow in test files."""
    bad_lines = _grep_for_legacy_imports("packages/ai-parrot/tests/")
    assert bad_lines == [], (
        "Legacy parrot.bots.flow import statements found in tests:\n"
        + "\n".join(bad_lines)
    )


def test_smoke_import_parrot_bots_flows():
    """parrot.bots.flows imports cleanly after deletion of legacy package."""
    import parrot.bots.flows  # noqa: PLC0415
    assert hasattr(parrot.bots.flows, "AgentsFlow")
    assert hasattr(parrot.bots.flows, "__all__")
