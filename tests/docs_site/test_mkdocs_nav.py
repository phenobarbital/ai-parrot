"""FEAT-803 AC2/AC8: collapsed nav and parrot branding."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")


def _nav_top_level() -> list[str]:
    """Return top-level nav titles (lines `  - Title:` directly under `nav:`)."""
    nav = CONFIG.split("\nnav:\n", 1)[1]
    return [line.removeprefix("  - ").split(":", 1)[0] for line in nav.splitlines() if line.startswith("  - ")]


def test_nav_has_at_most_six_sections() -> None:
    """The newcomer navigation exposes no more than six top-level sections."""
    assert _nav_top_level() == ["Home", "Getting Started", "Concepts", "Tutorials", "Guides", "About"]


def test_getting_started_in_nav() -> None:
    """The full quick-start guide is discoverable from the navigation."""
    assert "getting-started.md" in CONFIG.split("\nnav:", 1)[1]


def test_parrot_branding_and_custom_dir() -> None:
    """The Material theme uses the shared parrot brand and local overrides."""
    assert "robot-happy-outline" not in CONFIG
    assert "custom_dir: docs/overrides" in CONFIG
    assert "logo: branding/parrot.svg" in CONFIG
    assert "favicon: branding/favicon.ico" in CONFIG
    assert "overrides/main.css" in CONFIG
