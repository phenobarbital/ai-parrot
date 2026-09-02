"""Tests for token-efficient context packing (wiki/context.py)."""

import pytest

from parrot.knowledge.wiki.context import (
    NS_SEPARATOR,
    PackedContext,
    first_sentence,
    pack_results,
    qualify_id,
    split_namespaced_id,
    stub_line,
    truncate_to_tokens,
)
from parrot.knowledge.wiki.models import WikiSearchResult
from parrot.knowledge.wiki.store import WikiPageRecord


def _result(i: int, **kw) -> dict:
    return {
        "concept_id": kw.pop("concept_id", f"page-{i}"),
        "title": kw.pop("title", f"Title {i}"),
        "summary": kw.pop("summary", f"First sentence of page {i}. Second sentence."),
        "score": kw.pop("score", 1.0 - i * 0.05),
        "token_count": kw.pop("token_count", 500),
        **kw,
    }


class TestFirstSentence:
    def test_takes_lead_sentence(self):
        assert first_sentence("Hello world. More text.") == "Hello world."

    def test_caps_length(self):
        lead = first_sentence("x" * 1000)
        assert len(lead) <= 240
        assert lead.endswith("…")

    def test_collapses_whitespace(self):
        assert first_sentence("a\n  b\t c.") == "a b c."

    def test_empty(self):
        assert first_sentence("   ") == ""


class TestStubLine:
    def test_format(self):
        line = stub_line(_result(1))
        assert line.startswith("- [page-1] Title 1 — First sentence of page 1.")
        assert "score=0.95" in line
        assert "~500tok" in line

    def test_minimal_result(self):
        line = stub_line({"concept_id": "x"})
        assert line == "- [x]"

    def test_omits_title_that_only_repeats_the_id(self):
        line = stub_line(
            {
                "concept_id": "file:parrot/tools/base.py",
                "title": "parrot/tools/base.py",
            }
        )
        assert line == "- [file:parrot/tools/base.py]"

    def test_keeps_a_title_that_adds_information(self):
        line = stub_line({"concept_id": "mem-3f32cf69", "title": "Graph sync gotcha"})
        assert line == "- [mem-3f32cf69] Graph sync gotcha"

    def test_strips_only_the_leading_id_prefix(self):
        # The path itself contains a second ':' — de-duplication must not
        # mistake it for the id prefix and mangle the comparison.
        rid = "file:docs/parrot/summaries/mod:parrot.skills.md"
        line = stub_line({"concept_id": rid, "title": rid.removeprefix("file:")})
        assert line == f"- [{rid}]"

    def test_omits_dir_title_that_only_adds_a_trailing_slash(self):
        # repo_scan emits directory titles as "<relpath>/" against a
        # "dir:<relpath>" id — the slash is not information.
        line = stub_line({"concept_id": "dir:tests/knowledge", "title": "tests/knowledge/"})
        assert line == "- [dir:tests/knowledge]"

    def test_omits_pkg_title_that_only_repeats_the_id(self):
        line = stub_line({"concept_id": "pkg:parrot.skills", "title": "parrot.skills"})
        assert line == "- [pkg:parrot.skills]"

    def test_drops_frontmatter_delimiter_lead(self):
        line = stub_line({"concept_id": "x", "title": "Title", "summary": "---"})
        assert line == "- [x] Title"


class TestPackResults:
    def test_all_fit(self):
        packed = pack_results([_result(i) for i in range(3)], budget_tokens=1000)
        assert isinstance(packed, PackedContext)
        assert packed.results_packed == 3
        assert packed.total_available == 3
        assert packed.truncated is False
        assert packed.text.count("\n") == 2

    def test_budget_cuts_off(self):
        packed = pack_results([_result(i) for i in range(50)], budget_tokens=100)
        assert 0 < packed.results_packed < 50
        assert packed.truncated is True
        assert packed.tokens_used <= 100

    def test_accepts_models(self):
        results = [
            WikiSearchResult(
                node_id="n1", title="T", score=0.9, source="lexical", snippet="S."
            )
        ]
        packed = pack_results(results, budget_tokens=200)
        assert packed.results_packed == 1
        assert "[n1]" in packed.text

    def test_dedupes_ids(self):
        packed = pack_results(
            [_result(1), _result(1)], budget_tokens=1000
        )
        assert packed.results_packed == 1

    def test_single_oversized_stub_still_included(self):
        packed = pack_results([_result(1)], budget_tokens=1)
        assert packed.results_packed == 1
        assert packed.truncated is True

    def test_empty_input(self):
        packed = pack_results([], budget_tokens=100)
        assert packed.results_packed == 0
        assert packed.text == ""
        assert packed.truncated is False


class TestTruncateToTokens:
    def test_no_limit(self):
        text, truncated = truncate_to_tokens("hello", None)
        assert text == "hello" and truncated is False

    def test_under_limit(self):
        text, truncated = truncate_to_tokens("hello world", 100)
        assert text == "hello world" and truncated is False

    def test_over_limit(self):
        long_text = "word " * 2000
        text, truncated = truncate_to_tokens(long_text, 50)
        assert truncated is True
        assert len(text) < len(long_text)
        assert text.endswith("[…truncated]")


class TestToolkitProgressiveDisclosure:
    """search_compact / read_page(max_tokens) / expand via the toolkit."""

    @pytest.mark.asyncio
    async def test_search_compact_returns_budgeted_stubs(self, wiki_toolkit):
        await wiki_toolkit.create_page(
            "test-wiki",
            "Neural Networks",
            "A neural network is a computational model. " * 30,
        )
        result = await wiki_toolkit.search_compact(
            "test-wiki", "neural networks", budget_tokens=300
        )
        assert result["results_packed"] >= 1
        assert result["tokens_used"] <= 300
        assert "[m1]" in result["context"]
        stub = result["stubs"][0]
        assert stub["token_count"] > 0  # cost of reading the full page

    @pytest.mark.asyncio
    async def test_read_page_max_tokens_truncates(self, wiki_toolkit):
        await wiki_toolkit.create_page(
            "test-wiki", "Big Page", "Lots of content here. " * 500
        )
        full = await wiki_toolkit.read_page("test-wiki", "m1")
        assert full["truncated"] is False
        capped = await wiki_toolkit.read_page("test-wiki", "m1", max_tokens=50)
        assert capped["truncated"] is True
        assert len(capped["content"]) < len(full["content"])

    @pytest.mark.asyncio
    async def test_expand_returns_neighbour_stubs(self, wiki_toolkit):
        await wiki_toolkit.create_page("test-wiki", "Seed", "Seed body.")
        # second insert would reuse mock id m1 → give the related page
        # its own id directly in the store
        await wiki_toolkit._store.upsert_pages(  # noqa: SLF001 — test shortcut
            [
                WikiPageRecord(
                    concept_id="rel-1", title="Related", summary="Related page."
                )
            ]
        )
        await wiki_toolkit._store.add_edges([("m1", "rel-1", "references")])
        result = await wiki_toolkit.expand("test-wiki", "m1", rel="references")
        assert result["total_available"] == 1
        assert "[rel-1]" in result["context"]


class TestNamespacedIds:
    """FEAT-450 — ``ns::id`` helpers and ns-aware stub rendering."""

    @pytest.mark.parametrize(
        "page_id,expected",
        [
            ("asyncdb::file:a/b.py", ("asyncdb", "file:a/b.py")),
            (
                "file:docs/summaries/mod:parrot.skills.md",
                (None, "file:docs/summaries/mod:parrot.skills.md"),
            ),
            ("legal:civil::concept:x", ("legal:civil", "concept:x")),
            ("::file:x", (None, "::file:x")),
            ("asyncdb::", (None, "asyncdb::")),
            ("file:x", (None, "file:x")),
            # ``::`` inside a local path is not a namespace prefix.
            ("file:a::b.py", (None, "file:a::b.py")),
            # FEAT-498 — ``sym:`` symbol ids are accepted as a page-id kind.
            ("ns::sym:a.py#X", ("ns", "sym:a.py#X")),
            ("sym:a.py#X", (None, "sym:a.py#X")),
        ],
    )
    def test_split_namespaced_id(self, page_id, expected):
        assert split_namespaced_id(page_id) == expected

    def test_qualify_id(self):
        assert qualify_id("ns", "file:x") == "ns" + NS_SEPARATOR + "file:x"
        assert qualify_id(None, "file:x") == "file:x"
        assert qualify_id("", "file:x") == "file:x"

    def test_qualify_id_is_idempotent(self):
        once = qualify_id("ns", "file:x")
        assert qualify_id("ns", once) == once

    def test_qualify_and_split_roundtrip(self):
        assert split_namespaced_id(qualify_id("legal:civil", "concept:x")) == (
            "legal:civil",
            "concept:x",
        )

    def test_stub_elides_title_for_qualified_id(self):
        packed = pack_results(
            [
                {
                    "concept_id": "asyncdb::file:README.md",
                    "title": "README.md",
                    "summary": "Readme.",
                }
            ]
        )
        assert packed.text.count("README.md") == 1
        assert "[asyncdb::file:README.md]" in packed.text

    def test_stub_keeps_distinct_title_for_qualified_id(self):
        packed = pack_results(
            [
                {
                    "concept_id": "asyncdb::file:store.py",
                    "title": "Connection pool",
                    "summary": "Pools connections.",
                }
            ]
        )
        assert "Connection pool" in packed.text

    def test_local_and_foreign_same_id_are_distinct_stubs(self):
        packed = pack_results(
            [
                {"concept_id": "file:README.md", "summary": "Local."},
                {"concept_id": "other::file:README.md", "summary": "Foreign."},
            ]
        )
        assert packed.results_packed == 2
