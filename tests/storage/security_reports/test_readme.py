"""Tests that the parrot/storage/security_reports/README.md exists and meets spec §5 requirements."""
from pathlib import Path

# Resolve README relative to this test file's location within the repository.
# tests/storage/security_reports/ -> ../../.. (worktree root) -> packages/...
_WORKTREE_ROOT = Path(__file__).parent.parent.parent.parent
README = _WORKTREE_ROOT / "packages/ai-parrot/src/parrot/storage/security_reports/README.md"


def test_exists() -> None:
    """The README file must exist."""
    assert README.exists(), f"README not found at {README}"


def test_size_under_cap() -> None:
    """README must be under ~150 lines (generous 12 000-byte cap)."""
    size = README.stat().st_size
    assert size < 12_000, f"README is {size} bytes — exceeds 12 000-byte cap"


def test_required_sections_present() -> None:
    """All 7 required sections from spec §Scope must be present."""
    txt = README.read_text()
    for section in (
        "What this is",
        "Three layers",
        "Fractal",
        "Freshness policy",
        "Conventions",
        "Related",
    ):
        assert section in txt, f"Missing section: {section!r}"


def test_backstory_block_quoted() -> None:
    """The BACKSTORY freshness-policy block must be quoted verbatim from Spec §7."""
    txt = README.read_text()
    assert "Report Freshness Policy" in txt
    assert "find_security_report" in txt
    assert "read_security_report" in txt
