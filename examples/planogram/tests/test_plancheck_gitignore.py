"""FEAT-565 M0: the planogram example's code is trackable, retailer data and photos are not."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

NOT_IGNORED = [
    "examples/planogram/plancheck/any_module.py",
    "examples/planogram/tests/test_any_module.py",
    "examples/planogram/planogram_check.py",
    "examples/planogram/white_label_detector/detect_price_labels.py",
    "examples/planogram/aws/nova2.py",
]
IGNORED = [
    "examples/planogram/images/a.jpeg",
    "examples/planogram/results/x/compliance.json",
    "examples/planogram/inkcheck/README.md",
    "examples/planogram/planogram_page1.json",
]


def _is_ignored(path: str) -> bool:
    """Return True when git ignores ``path`` (exit 0), False when it does not (exit 1)."""
    proc = subprocess.run(["git", "check-ignore", "-q", path], cwd=REPO_ROOT, check=False)
    if proc.returncode not in (0, 1):
        pytest.skip(f"git check-ignore unavailable (rc={proc.returncode})")
    return proc.returncode == 0


@pytest.mark.parametrize("path", NOT_IGNORED)
def test_gitignore_tracks_code_not_photos(path: str) -> None:
    """Code, tests and the detector script are NOT ignored."""
    assert not _is_ignored(path)


@pytest.mark.parametrize("path", IGNORED)
def test_gitignore_keeps_data_ignored(path: str) -> None:
    """Photos, results, inkcheck and the retailer planogram stay ignored."""
    assert _is_ignored(path)
