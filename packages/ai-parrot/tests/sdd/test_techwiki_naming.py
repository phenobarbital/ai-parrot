"""Tests for technical-wiki page naming and link rewriting (FEAT-801)."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.sdd.techwiki.naming import FORBIDDEN_NAME_CHARS, PageNameError, page_name, page_title, rewrite_links


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

    def test_colon_in_title_and_section_becomes_a_separator(self) -> None:
        """A colon (rejected by actions/upload-artifact) is dropped from the name; the title keeps it."""
        assert page_name("Server & APIs", "Server Layer: BotManager") == "Server-&-APIs-Server-Layer-BotManager"
        assert page_name("Sec: tion", "A:B") == "Sec-tion-A-B"
        assert page_name("API Reference", "parrot.memory.compaction") == "API-Reference-parrot.memory.compaction"

    def test_every_forbidden_character_is_replaced(self) -> None:
        """Each character actions/upload-artifact refuses becomes one hyphen-separated gap."""
        assert page_name(None, 'a"b<c>d|e*f?g') == "a-b-c-d-e-f-g"
        assert page_name(None, "a\rb\nc") == "a-b-c"

    def test_title_made_only_of_forbidden_characters_raises(self) -> None:
        """A title with nothing usable left is an error, never an empty page name."""
        with pytest.raises(PageNameError):
            page_name(None, ":?")


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


def test_rewrite_links_resolves_fragment_links_and_flags_missing() -> None:
    """A `page.md#frag` link is resolved (fragment kept) and an unresolved one reaches the resolver."""
    seen: list[str] = []

    def resolver(target: str) -> str | None:
        seen.append(target)
        return {"local.md": "Local-Page"}.get(target)

    out = rewrite_links("[A](local.md#part) [B](missing.md#frag)", resolver)
    assert out == "[A](Local-Page#part) [B](missing.md#frag)"
    assert seen == ["local.md", "missing.md"]


@pytest.mark.parametrize("title", ["../../escaped", "a/b", "a\\b"])
def test_page_name_never_contains_path_separators(title: str) -> None:
    """Titles with separators are flattened so a page name can never address another directory."""
    name = page_name(None, title)
    assert "/" not in name and "\\" not in name


@pytest.mark.parametrize("char", list(FORBIDDEN_NAME_CHARS))
def test_page_name_never_contains_an_artifact_forbidden_character(char: str) -> None:
    """No character ``actions/upload-artifact`` rejects survives in a page name, in the section or the title."""
    name = page_name(f"Sec{char}tion", f"Title{char}Here")
    assert char not in name
    assert name == "Sec-tion-Title-Here"


def test_rewrite_links_leaves_fenced_code_untouched() -> None:
    """Links inside fenced code blocks are examples, not page references."""
    text = "[A](local.md)\n```md\n[B](local.md)\n```\n~~~\n[C](local.md)\n~~~\n[D](local.md)"
    out = rewrite_links(text, lambda target: "Local")
    assert out == "[[Local]]\n```md\n[B](local.md)\n```\n~~~\n[C](local.md)\n~~~\n[[Local]]"
