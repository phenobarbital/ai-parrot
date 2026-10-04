"""FEAT-609 M1: scanner `mode` predicts the tier the NEXT file gets."""

from __future__ import annotations

import pytest
from parrot.knowledge.wiki.languages import scanner_for
from parrot.knowledge.wiki.languages.render import set_structural_enabled

from .conftest import requires_astgrep

_SUFFIXES = (".ts", ".php", ".rs", ".pl")


@requires_astgrep
@pytest.mark.parametrize("suffix", _SUFFIXES)
def test_mode_predictive_with_astgrep(suffix: str) -> None:
    """Fresh scanner, no outline() call yet -> already reports ast-grep."""
    scanner = scanner_for(suffix)
    assert scanner is not None
    # Scanners are module-level singletons; a previous test may have served a file.
    scanner._last_mode = None
    assert scanner.mode == "ast-grep"


@pytest.mark.parametrize("suffix", _SUFFIXES)
def test_mode_predictive_without_astgrep(force_no_astgrep, suffix: str) -> None:
    """Without the seam, mode is the tree-sitter/heuristic tier, whatever _last_mode says."""
    scanner = scanner_for(suffix)
    assert scanner is not None
    scanner._last_mode = "ast-grep"
    try:
        assert scanner.mode in {"tree-sitter", "heuristic"}
    finally:
        scanner._last_mode = None


@requires_astgrep
@pytest.mark.parametrize("suffix", _SUFFIXES)
def test_mode_honours_kill_switch(suffix: str) -> None:
    set_structural_enabled(False)
    try:
        assert scanner_for(suffix).mode != "ast-grep"
    finally:
        set_structural_enabled(True)
