"""FEAT-803 AC1/AC12: landing page structure and project-relative links."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HTML = (ROOT / "landing" / "index.html").read_text(encoding="utf-8")


def test_required_sections_present() -> None:
    """The redesigned landing page keeps its stable section anchors."""
    for section_id in ("hero", "why", "install", "providers", "links", "footer"):
        assert f'id="{section_id}"' in HTML, section_id


def test_docs_cta_is_project_relative() -> None:
    """Documentation links retain the GitHub Pages deployment prefix."""
    assert 'href="docs/"' in HTML
    assert 'href="/docs' not in HTML


def test_wiki_cta_and_branding() -> None:
    """Wiki and branding references retain their released targets."""
    assert "github.com/phenobarbital/ai-parrot/wiki" in HTML
    assert "docs/branding/favicon.ico" in HTML
    assert "social-card.png" in HTML


def test_local_assets_resolve_from_the_overlay_root() -> None:
    """Landing-owned and docs-branding URLs point to files copied into the site."""
    local_urls = re.findall(r'(?:href|src)="((?:css|js|docs/branding)/[^"]+)"', HTML)
    assert local_urls
    for url in local_urls:
        target = ROOT / ("landing" if url.startswith(("css/", "js/")) else "") / url
        assert target.is_file(), url
