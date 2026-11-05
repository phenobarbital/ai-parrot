"""Tests for technical-wiki page naming and link rewriting (FEAT-801)."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.sdd.techwiki.naming import PageNameError, page_name, page_title, rewrite_links


class TestPageName:
    """Tests for GitHub Wiki page-name conversion."""

    def test_spaces_to_dashes(self) -> None:
        """Spaces become GitHub Wiki's page-name separator."""
        assert page_name("Memory", "Conversation Compaction") == "Memory-Conversation-Compaction"

    def test_section_prefix(self) -> None:
        """A section prefixes the page title."""
        assert page_name("Clients", "Abstract Client") == "Clients-Abstract-Client"

    def test_no_section(self) -> None:
        """A missing section leaves only the title."""
        assert page_name(None, "Home") == "Home"

    def test_literal_hyphen_raises(self) -> None:
        """Literal hyphens cannot be safely linked by GitHub Wiki."""
        with pytest.raises(PageNameError):
            page_name(None, "my-page")

    def test_empty_title_raises(self) -> None:
        """Empty titles are not valid page names."""
        with pytest.raises(PageNameError):
            page_name(None, "")


class TestPageTitle:
    """Tests for title extraction precedence."""

    def test_frontmatter_precedes_heading(self) -> None:
        """A frontmatter title wins over the first heading."""
        assert page_title(Path("ignored.md"), "---\ntitle: Preferred\n---\n# Heading\n") == "Preferred"

    def test_heading_then_stem_fallback(self) -> None:
        """The first H1 precedes a normalized filename fallback."""
        assert page_title(Path("conversation_compaction.md"), "# Heading\n") == "Heading"
        assert page_title(Path("conversation_compaction.md"), "No heading") == "Conversation Compaction"


class TestRewriteLinks:
    """Tests for authored-page and generated-reference links."""

    def test_relative_md_link(self) -> None:
        """A resolved relative Markdown target becomes a wiki link."""
        assert rewrite_links("[Memory](memory.md)", lambda target: {"memory.md": "Memory"}.get(target)) == "[[Memory]]"

    def test_ref_link(self) -> None:
        """A resolved generated-reference target becomes a wiki link."""
        assert (
            rewrite_links(
                "[Compaction](ref:parrot.memory.compaction)",
                lambda target: {"ref:parrot.memory.compaction": "Reference-parrot.memory.compaction"}.get(target),
            )
            == "[[Reference-parrot.memory.compaction]]"
        )

    def test_unknown_target_collected(self) -> None:
        """An unresolved target is left in authored Markdown unchanged."""
        assert rewrite_links("[Missing](missing.md)", lambda target: None) == "[Missing](missing.md)"


def test_rewrite_links_skips_external_urls() -> None:
    """External URLs ending in .md are never treated as wiki-page references."""
    text = "[Spec](https://github.com/o/r/blob/main/spec.md) and [Local](local.md)"
    out = rewrite_links(text, lambda target: {"local.md": "Local"}.get(target))
    assert out == "[Spec](https://github.com/o/r/blob/main/spec.md) and [[Local]]"
