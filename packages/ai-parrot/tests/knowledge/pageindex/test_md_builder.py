"""Regression tests for the fence-aware PageIndex Markdown parser (FEAT-613)."""
from __future__ import annotations

import pytest

from parrot.knowledge.pageindex.md_builder import (
    _fence_marker,
    md_to_tree,
    parse_markdown_structure,
)


@pytest.fixture(autouse=True)
def _stub_count_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    """Char-count tokenizer so no tiktoken model download is needed offline."""
    monkeypatch.setattr(
        "parrot.knowledge.pageindex.md_builder.count_tokens",
        lambda text, model="gpt-4o": max(1, len(text or "")),
    )


def _outline(md: str) -> list[tuple[int, str]]:
    return [(s["level"], s["title"]) for s in parse_markdown_structure(md)]


REPRO = "# Top\n\nintro\n\n```python\n# comment line\nx = 1\n```\n\n## Real\n\nbody\n"
TILDE = "# Top\n\n~~~\n# not a heading\n~~~\n\n## Real\n"
NESTED = "# Top\n\n~~~\n```\n# x\n~~~\n\n## Real\n"
UNTERMINATED = "# Top\n\n```\n## Later\n"


def test_hash_comment_inside_backtick_fence_is_not_heading() -> None:
    """The ledger repro: a Python comment inside a fenced block is body text, not a node."""
    sections = parse_markdown_structure(REPRO)
    assert [(s["level"], s["title"]) for s in sections] == [(1, "Top"), (2, "Real")]
    assert "# comment line" in sections[0]["text"]
    assert "```python" in sections[0]["text"]
    assert sections[0]["text"].endswith("```")
    assert sections[1]["text"] == "body"


def test_hash_comment_inside_tilde_fence_is_not_heading() -> None:
    """Tilde fences are honoured exactly like backtick fences."""
    sections = parse_markdown_structure(TILDE)
    assert [(s["level"], s["title"]) for s in sections] == [(1, "Top"), (2, "Real")]
    assert "# not a heading" in sections[0]["text"]


def test_backtick_fence_does_not_close_tilde_fence() -> None:
    """A backtick line inside a tilde block is content and does not end the block."""
    sections = parse_markdown_structure(NESTED)
    assert [(s["level"], s["title"]) for s in sections] == [(1, "Top"), (2, "Real")]
    assert "# x" in sections[0]["text"]
    assert "```" in sections[0]["text"]


def test_longer_closing_fence_closes_shorter_opening() -> None:
    """A closing fence at least as long as the opening one closes the block."""
    md = "# Top\n\n```\n# inside\n````\n\n## After\n"
    assert _outline(md) == [(1, "Top"), (2, "After")]


def test_shorter_closing_fence_does_not_close_longer_opening() -> None:
    """A shorter fence line inside a longer-fenced block is content, not a close."""
    md = "# Top\n\n````\n```\n## After\n````\n\n## Real\n"
    sections = parse_markdown_structure(md)
    assert [(s["level"], s["title"]) for s in sections] == [(1, "Top"), (2, "Real")]
    assert "## After" in sections[0]["text"]


def test_closing_fence_with_info_string_does_not_close() -> None:
    """CommonMark forbids info strings on closing fences, so ```python inside a block is content."""
    md = "# Top\n\n```\n```python\n## After\n```\n\n## Real\n"
    sections = parse_markdown_structure(md)
    assert [(s["level"], s["title"]) for s in sections] == [(1, "Top"), (2, "Real")]
    assert "## After" in sections[0]["text"]


def test_fence_indented_up_to_three_spaces_is_recognised() -> None:
    """Up to three leading spaces still open a fence; four spaces do not."""
    three = "# Top\n\n   ```\n## Inside\n   ```\n"
    assert _outline(three) == [(1, "Top")]
    four = "# Top\n\n    ```\n## Inside\n    ```\n"
    assert _outline(four) == [(1, "Top"), (2, "Inside")]


def test_unterminated_fence_swallows_rest_of_document() -> None:
    """An unclosed fence extends to end of document (CommonMark), hiding later headings."""
    sections = parse_markdown_structure(UNTERMINATED)
    assert [(s["level"], s["title"]) for s in sections] == [(1, "Top")]
    assert "## Later" in sections[0]["text"]


def test_headings_outside_fences_unchanged() -> None:
    """Regression guard: structure numbering and line numbers are untouched by the fence logic."""
    md = "# A\n\ntext\n\n## A.1\n\n### A.1.1\n\n## A.2\n\n# B\n"
    sections = parse_markdown_structure(md)
    assert [(s["structure"], s["title"], s["line_num"]) for s in sections] == [
        ("1", "A", 1),
        ("1.1", "A.1", 5),
        ("1.1.1", "A.1.1", 7),
        ("1.2", "A.2", 9),
        ("2", "B", 11),
    ]
    assert sections[0]["text"] == "text"
    assert sections[0]["token_count"] == len("text")


def test_heading_line_numbers_unchanged_after_a_fence() -> None:
    """Fenced lines still count toward line_num of later headings."""
    sections = parse_markdown_structure(REPRO)
    assert [s["line_num"] for s in sections] == [1, 10]


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("```", ("`", 3)),
        ("```python", ("`", 3)),
        ("~~~~", ("~", 4)),
        ("   ```", ("`", 3)),
        ("    ```", None),
        ("``", None),
        ("text with ``` inline", None),
        ("# heading", None),
        ("", None),
    ],
)
def test_fence_marker_classification(line: str, expected: tuple[str, int] | None) -> None:
    """Direct classification of fence-delimiter lines."""
    assert _fence_marker(line) == expected


async def test_md_to_tree_offline_ignores_fenced_comments() -> None:
    """The structure-only tree built from the repro has no node for the fenced comment.

    ``md_to_tree`` thins nodes under 50 tokens, so every section body is padded past
    that threshold under the char-count stub.
    """
    padding = "lorem ipsum " * 10
    doc = f"# Top\n\n{padding}\n\n```python\n# comment line\nx = 1\n```\n\n## Real\n\n{padding}\n"
    tree = await md_to_tree(doc, adapter=None, options={"if_add_node_summary": "no"})
    assert tree["doc_name"] == "document.md"
    top = tree["structure"]
    assert [node["title"] for node in top] == ["Top"]
    children = top[0].get("nodes", [])
    assert [node["title"] for node in children] == ["Real"]
    assert all("comment line" != node["title"] for node in top + children)
