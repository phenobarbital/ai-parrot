"""Verifies the legacy parrot.bots.flow package has been deleted (FEAT-196 TASK-1316).

Acceptance criteria:
- parrot/bots/flow/ directory does not exist
- No actual import statements using parrot.bots.flow (singular) in source
- No actual import statements using parrot.bots.flow (singular) in tests
- parrot.bots.flows imports cleanly after deletion
"""
import pathlib


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
    """Pure-Python scan for actual legacy import statements (no subprocess grep).

    Returns a list of 'file:line:content' strings for any line that contains
    a real ``from parrot.bots.flow`` or ``import parrot.bots.flow`` import
    (singular ``flow``, not the canonical plural ``flows``).
    """
    repo_root = _find_repo_root()
    target = repo_root / search_dir

    bad_lines = []
    for py_file in sorted(target.rglob("*.py")):
        if "__pycache__" in py_file.parts:
            continue
        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(source.splitlines(), 1):
            # Skip lines that reference the canonical plural package.
            if "parrot.bots.flows" in line:
                continue
            # Skip lines that don't mention the legacy singular package at all.
            if "parrot.bots.flow" not in line:
                continue
            stripped = line.strip()
            # Skip comments and docstring examples.
            if stripped.startswith("#") or ">>>" in stripped:
                continue
            # Skip string literals used in test assertions about the absence
            # of legacy imports (e.g. assert "..." not in src).
            if ("assert " in stripped and (
                '"from parrot.bots.flow' in stripped
                or "'from parrot.bots.flow" in stripped
                or '"parrot.bots.flow' in stripped
                or "'parrot.bots.flow" in stripped
            )):
                continue
            if "not in src" in stripped or "not in source" in stripped:
                continue
            # Only flag actual import statements.
            if stripped.startswith("from parrot.bots.flow") or stripped.startswith("import parrot.bots.flow"):
                bad_lines.append(f"{py_file}:{lineno}:{line}")
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
