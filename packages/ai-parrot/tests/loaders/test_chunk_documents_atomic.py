"""Regression tests for _ATOMIC_CONTENT_KINDS in chunk_documents.

Verifies that documents emitted as atomic units by loaders (e.g. JSON-LD
FAQPage Q&A pairs, extracted tables) are NOT re-split by the configured
text splitter — they pass through with splitter_type='passthrough'.

Background: WebScrapingLoader emits one Document per Q&A pair via
_docs_from_faqpage with content_kind='faq'. Before this guard, the
default SemanticTextSplitter (chunk_size=512) would cut Q&A answers
mid-word, dropping the AutoPay reference out of the indexed chunk and
breaking retrieval for queries like 'can I setup autopay?'.
"""
from __future__ import annotations

import logging

import pytest

from parrot.loaders.abstract import AbstractLoader
from parrot.stores.models import Document


def _make_loader_with_atomic_path():
    """Minimal stand-in that exposes _chunk_with_text_splitter from AbstractLoader.

    Only the atomic-passthrough branch is exercised, so we omit the
    splitter machinery entirely. If the guard regresses, the splitter
    attribute would be hit and AttributeError would surface — making
    the regression loud.
    """
    class MinimalLoader:
        _auto_detect_content_type = False
        text_splitter = None  # tripping this means the guard regressed

        def __init__(self):
            self.logger = logging.getLogger('test.atomic.loader')

    loader = MinimalLoader()
    loader._chunk_with_text_splitter = (
        AbstractLoader._chunk_with_text_splitter.__get__(loader, MinimalLoader)
    )
    return loader


# Long enough that any real splitter would cut it; keeps the test
# unambiguous about whether the guard fired.
_FAQ_BODY = (
    "Q: How do I access my AT&T Prepaid account?\n\n"
    "A: You can access and manage your AT&T Prepaid account by logging "
    "into your AT&T Prepaid account. Your AT&T Prepaid account allows "
    "you to see your data usage, change your plan, check your balance, "
    "enroll & set up AutoPay."
)


class TestAtomicContentKindPassthrough:
    def test_faq_doc_is_not_split(self):
        loader = _make_loader_with_atomic_path()
        doc = Document(
            page_content=_FAQ_BODY,
            metadata={'content_kind': 'faq', 'source': 'att.com/prepaid'},
        )

        out = loader._chunk_with_text_splitter([doc])

        assert len(out) == 1, "faq doc must pass through as a single chunk"
        chunk = out[0]
        assert chunk.page_content == _FAQ_BODY, (
            "page_content must be byte-identical — splitting would cut "
            "the AutoPay reference out of the indexed chunk"
        )
        assert chunk.metadata['splitter_type'] == 'passthrough'
        assert chunk.metadata['is_chunk'] is True
        assert chunk.metadata['chunk_index'] == 0
        assert chunk.metadata['total_chunks'] == 1
        # Original metadata preserved
        assert chunk.metadata['content_kind'] == 'faq'
        assert chunk.metadata['source'] == 'att.com/prepaid'

    def test_table_doc_is_not_split(self):
        loader = _make_loader_with_atomic_path()
        table_md = (
            "| Plan | Price | Data |\n"
            "| --- | --- | --- |\n"
            "| Basic | $25 | 5 GB |\n"
            "| Plus  | $35 | 15 GB |\n"
            "| Max   | $50 | Unlimited |"
        )
        doc = Document(
            page_content=table_md,
            metadata={'content_kind': 'table'},
        )

        out = loader._chunk_with_text_splitter([doc])

        assert len(out) == 1
        assert out[0].page_content == table_md, (
            "table markdown must stay intact — splitting breaks rows/columns"
        )
        assert out[0].metadata['splitter_type'] == 'passthrough'

    @pytest.mark.parametrize(
        'kind',
        ['fragment', 'video_link', 'navigation', 'selector', 'faq', 'table'],
    )
    def test_all_atomic_kinds_pass_through(self, kind):
        """Every kind in _ATOMIC_CONTENT_KINDS must skip the splitter."""
        loader = _make_loader_with_atomic_path()
        doc = Document(
            page_content="any body — the guard must fire before the splitter",
            metadata={'content_kind': kind},
        )

        out = loader._chunk_with_text_splitter([doc])

        assert len(out) == 1
        assert out[0].metadata['splitter_type'] == 'passthrough', (
            f"content_kind={kind!r} must be in _ATOMIC_CONTENT_KINDS"
        )

    def test_non_atomic_kind_does_not_short_circuit(self):
        """Full-page kinds (trafilatura_main, markdown_full, text_full)
        MUST still hit the splitter — guarding them by mistake would
        leave huge unsplit pages in the vector store.

        Asserted indirectly by triggering the splitter branch: the
        minimal loader has text_splitter=None, so the splitter call
        raises AttributeError. _chunk_with_text_splitter catches it and
        falls back to appending the original Document unchanged
        (abstract.py:1378-1381). The original has no
        splitter_type='passthrough' marker — that marker is set only
        when the atomic guard fires.
        """
        loader = _make_loader_with_atomic_path()
        doc = Document(
            page_content="full page content that needs real chunking",
            metadata={'content_kind': 'trafilatura_main'},
        )

        out = loader._chunk_with_text_splitter([doc])

        # If the guard had wrongly fired, we'd see one passthrough chunk.
        # Instead we expect the splitter branch to have been reached
        # (and failed harmlessly because text_splitter is None).
        passthrough = [
            d for d in out
            if d.metadata.get('splitter_type') == 'passthrough'
        ]
        assert len(passthrough) == 0, (
            "trafilatura_main MUST NOT be treated as atomic — "
            "full pages need to be chunked"
        )
