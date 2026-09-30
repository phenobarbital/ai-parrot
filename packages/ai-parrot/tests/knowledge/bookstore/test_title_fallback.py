"""Nonempty and collision-safe bookstore display titles."""

import pytest

from parrot.knowledge.bookstore.carding import disambiguate_title


@pytest.mark.parametrize("title", ["", "  ", "\t\n"])
def test_disambiguate_title_empty_falls_back_to_stem(title: str) -> None:
    """Blank drafts use a de-slugified filename stem."""
    assert disambiguate_title(title, set(), toc_entries=[], stem="async_python") == "Async Python"


@pytest.mark.parametrize(
    ("stem", "expected"),
    [("", "Untitled"), ("   ", "Untitled"), ("!!!", "!!!"), ("raw.stem", "Raw.stem")],
)
def test_disambiguate_title_empty_stem_is_never_blank(stem: str, expected: str) -> None:
    """An empty or unusual stem still yields a nonblank title."""
    result = disambiguate_title("", set(), toc_entries=[], stem=stem)

    assert result == expected
    assert result.strip()


def test_disambiguate_title_normalizes_before_collision() -> None:
    """Normalized and fallback titles still obey collision rules."""
    assert disambiguate_title("  Book  ", {"book"}, toc_entries=[], stem="chapter_1") == "Book — Chapter 1"

    fallback = disambiguate_title("  ", {"async python"}, toc_entries=[], stem="async_python")
    assert fallback == "Async Python — Async Python"
    assert fallback.casefold() not in {"async python"}
