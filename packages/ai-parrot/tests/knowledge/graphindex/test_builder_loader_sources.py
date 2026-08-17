"""Loader-source extraction: loader resolution and extractor isolation.

Covers two behaviours the pipeline previously lacked:

* ``GraphIndexBuilder`` used to hand ``None`` to ``LoaderExtractor.extract``,
  so every loader source failed with ``'NoneType' object has no attribute
  '_load'`` and document corpora silently produced an empty graph.
* Stage 1 gathered the three extractors under one ``try``, so a missing
  optional parser (tree-sitter, a loader backend) discarded the other two
  extractors' results as well.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from parrot.knowledge.graphindex.builder import GraphIndexBuilder
from parrot.knowledge.graphindex.extractors.loader import PlainTextLoader
from parrot.knowledge.graphindex.schema import NodeKind, SourceConfig

from .test_builder import make_ctx, make_node, make_persistence

# Sections need enough body to survive ``thin_tree``'s 50-token floor, which
# folds near-empty sections back into their parent.
_FILLER = " ".join(["Risk discipline is the whole of the edge."] * 12)

MARKDOWN = f"""# Trading Rules

Intro paragraph. {_FILLER}

## Position sizing

No single position exceeds 5% of portfolio value. {_FILLER}

## Stop losses

Every entry carries a stop before the order is placed. {_FILLER}
"""


def make_builder(tmp_path: Path) -> GraphIndexBuilder:
    """A builder whose embedder and persistence are inert."""
    embedder = MagicMock()
    embedder.embed_nodes = AsyncMock(side_effect=lambda nodes: nodes)
    return GraphIndexBuilder(
        persistence=make_persistence(),
        embedder=embedder,
        output_dir=tmp_path / "report",
    )


# ---------------------------------------------------------------------------
# PlainTextLoader
# ---------------------------------------------------------------------------


class TestPlainTextLoader:
    """The zero-dependency reader for Markdown/plain-text sources."""

    @pytest.mark.asyncio
    async def test_reads_file_into_one_document(self, tmp_path: Path) -> None:
        """The whole file arrives as a single Document."""
        path = tmp_path / "rules.md"
        path.write_text(MARKDOWN, encoding="utf-8")

        docs = await PlainTextLoader()._load(path)

        assert len(docs) == 1
        assert docs[0].page_content == MARKDOWN
        assert docs[0].metadata["source"] == str(path)

    @pytest.mark.asyncio
    async def test_empty_file_yields_no_documents(self, tmp_path: Path) -> None:
        """Whitespace-only files produce nothing rather than an empty node."""
        path = tmp_path / "blank.md"
        path.write_text("   \n\n", encoding="utf-8")

        assert await PlainTextLoader()._load(path) == []

    @pytest.mark.asyncio
    async def test_undecodable_bytes_do_not_raise(self, tmp_path: Path) -> None:
        """A stray non-UTF-8 byte is replaced, not fatal."""
        path = tmp_path / "latin.txt"
        path.write_bytes(b"caf\xe9 rules")

        docs = await PlainTextLoader()._load(path)

        assert len(docs) == 1
        assert "rules" in docs[0].page_content


# ---------------------------------------------------------------------------
# Loader resolution
# ---------------------------------------------------------------------------


class TestLoaderResolution:
    """``_loader_for`` picks a loader that can actually read the URI."""

    @pytest.mark.parametrize("suffix", [".md", ".markdown", ".txt", ".rst"])
    def test_text_extensions_use_the_builtin_reader(self, suffix: str) -> None:
        """Text-like sources need no optional backend."""
        assert isinstance(
            GraphIndexBuilder._loader_for(f"doc{suffix}"), PlainTextLoader
        )

    def test_uppercase_extension_is_recognised(self) -> None:
        """Extension matching is case-insensitive."""
        assert isinstance(GraphIndexBuilder._loader_for("DOC.MD"), PlainTextLoader)

    def test_unknown_extension_without_loaders_returns_none(self) -> None:
        """A PDF is skipped, not crashed on, when ai-parrot-loaders is absent."""
        with patch.dict("sys.modules", {"parrot_loaders.factory": None}):
            assert GraphIndexBuilder._loader_for("paper.pdf") is None

    def test_never_returns_none_loader_for_text(self, tmp_path: Path) -> None:
        """Regression: the builder must not hand ``None`` to the extractor."""
        path = tmp_path / "a.md"
        path.write_text(MARKDOWN, encoding="utf-8")
        assert GraphIndexBuilder._loader_for(str(path)) is not None


# ---------------------------------------------------------------------------
# End-to-end loader-source extraction
# ---------------------------------------------------------------------------


class TestExtractLoaders:
    """A Markdown corpus produces nodes with no optional dependency."""

    @pytest.mark.asyncio
    async def test_markdown_source_produces_nodes(self, tmp_path: Path) -> None:
        """Headings become nodes; the document root contains them."""
        path = tmp_path / "rules.md"
        path.write_text(MARKDOWN, encoding="utf-8")
        builder = make_builder(tmp_path)

        nodes, edges = await builder._extract_loaders(
            SourceConfig(tenant_id="t", loader_sources=[str(path)])
        )

        assert nodes, "Markdown source produced no nodes"
        assert any(n.kind is NodeKind.DOCUMENT for n in nodes)
        titles = {n.title for n in nodes}
        assert "Position sizing" in titles
        assert len(edges) == len(nodes) - 1  # one CONTAINS per non-root node

    @pytest.mark.asyncio
    async def test_unreadable_source_is_skipped(self, tmp_path: Path) -> None:
        """One bad source does not abort the others."""
        good = tmp_path / "good.md"
        good.write_text(MARKDOWN, encoding="utf-8")
        builder = make_builder(tmp_path)

        nodes, _ = await builder._extract_loaders(
            SourceConfig(
                tenant_id="t",
                loader_sources=[str(tmp_path / "missing.md"), str(good)],
            )
        )

        assert nodes


# ---------------------------------------------------------------------------
# Stage-1 isolation
# ---------------------------------------------------------------------------


class TestExtractorIsolation:
    """One failing extractor must not discard the others' results."""

    @pytest.mark.asyncio
    async def test_code_failure_keeps_loader_nodes(self, tmp_path: Path) -> None:
        """A missing tree-sitter grammar still lets documents index."""
        builder = make_builder(tmp_path)

        with (
            patch.object(
                builder,
                "_extract_code",
                AsyncMock(side_effect=ImportError("No module named 'tree_sitter_python'")),
            ),
            patch.object(
                builder,
                "_extract_loaders",
                AsyncMock(return_value=([make_node("doc-1")], [])),
            ),
            patch.object(builder, "_extract_skills", AsyncMock(return_value=([], []))),
        ):
            result = await builder.build(
                SourceConfig(tenant_id="t"), make_ctx()
            )

        assert result.node_count == 2  # from the mocked persistence
        assert any("code extraction failed" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_each_failure_is_reported_separately(self, tmp_path: Path) -> None:
        """Every failing extractor names itself in the error list."""
        builder = make_builder(tmp_path)

        with (
            patch.object(builder, "_extract_code", AsyncMock(side_effect=RuntimeError("a"))),
            patch.object(builder, "_extract_loaders", AsyncMock(side_effect=RuntimeError("b"))),
            patch.object(builder, "_extract_skills", AsyncMock(return_value=([], []))),
        ):
            result = await builder.build(SourceConfig(tenant_id="t"), make_ctx())

        joined = " ".join(result.errors)
        assert "code extraction failed" in joined
        assert "loader extraction failed" in joined
