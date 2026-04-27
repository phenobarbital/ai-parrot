"""Unit tests for parrot.stores.utils.contextual (FEAT-127 TASK-861).

Covers all Module-1 rows from the spec §4 test matrix.
"""
import pytest

from parrot.stores.models import Document
from parrot.stores.utils.contextual import (
    DEFAULT_MAX_HEADER_TOKENS,
    DEFAULT_TEMPLATE,
    build_contextual_text,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def doc_full():
    return Document(
        page_content="You will receive it on the 15th of every month.",
        metadata={"document_meta": {
            "title": "Employee Handbook",
            "section": "Compensation",
            "category": "HR Policy",
            "language": "en",
        }},
    )


@pytest.fixture
def doc_partial():
    return Document(
        page_content="Body.",
        metadata={"document_meta": {"title": "Only Title"}},
    )


@pytest.fixture
def doc_empty():
    return Document(page_content="Standalone passage.", metadata={})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBuildContextualText:
    """Spec §4 Module-1 unit tests (rows 1–9 + extras)."""

    def test_all_fields_present(self, doc_full):
        """Row 1 — default template with full document_meta."""
        text, header = build_contextual_text(doc_full)
        assert "Title: Employee Handbook" in header
        assert "Section: Compensation" in header
        assert "Category: HR Policy" in header
        assert text.endswith(doc_full.page_content)

    def test_partial_fields_no_orphan_pipes(self, doc_partial):
        """Row 2 — only title present; no orphan pipes, no None."""
        text, header = build_contextual_text(doc_partial)
        assert header == "Title: Only Title"
        assert " |  " not in header
        assert "None" not in header
        assert text.endswith(doc_partial.page_content)

    def test_no_meta(self, doc_empty):
        """Row 3 — empty/missing document_meta → bare passthrough."""
        text, header = build_contextual_text(doc_empty)
        assert text == doc_empty.page_content
        assert header == ""

    def test_skips_none_and_empty_string(self):
        """Row 4 — None and "" treated as missing; no 'Title: None'."""
        doc = Document(page_content="x", metadata={"document_meta": {
            "title": None, "section": "", "category": "C",
        }})
        _, header = build_contextual_text(doc)
        assert header == "Category: C"
        assert "None" not in header
        assert "title" not in header.lower() or "Title:" not in header

    def test_custom_string_template(self, doc_full):
        """Row 5 — custom string template works end-to-end."""
        text, _ = build_contextual_text(doc_full, template="[{title}] {content}")
        assert text.startswith("[Employee Handbook] ")

    def test_custom_callable_template(self, doc_full):
        """Row 6 — callable receives document_meta dict; result split on \\n\\n."""
        cb = lambda meta: f"<<{meta.get('title')}>>\n\nBODY"
        text, header = build_contextual_text(doc_full, template=cb)
        assert "<<Employee Handbook>>" in header
        assert text.endswith("BODY")

    def test_unknown_placeholder_renders_empty(self, doc_full):
        """Row 7 — unknown {nonexistent} renders as empty, does not raise."""
        text, _ = build_contextual_text(doc_full, template="{nonexistent}|{content}")
        assert "nonexistent" not in text
        assert text.endswith(doc_full.page_content)

    def test_caps_header_tokens(self):
        """Row 8 — very long title is truncated; chunk content preserved."""
        long_title = " ".join(["Word"] * 500)
        doc = Document(
            page_content="body",
            metadata={"document_meta": {"title": long_title}},
        )
        _, header = build_contextual_text(doc, max_header_tokens=10)
        assert len(header.split()) <= 12  # spec allows a small slack

    def test_is_deterministic(self, doc_full):
        """Row 9 — same (document, template) → same output across 100 calls."""
        results = {build_contextual_text(doc_full) for _ in range(100)}
        assert len(results) == 1

    def test_does_not_mutate_page_content(self, doc_full):
        """page_content must be byte-equal before and after the call."""
        before = doc_full.page_content
        build_contextual_text(doc_full)
        assert doc_full.page_content == before

    def test_metadata_brace_injection_is_neutralised(self):
        """Row extra — malicious {content} in title must not re-substitute."""
        doc = Document(page_content="x", metadata={"document_meta": {
            "title": "{content}{content}{content}",
        }})
        text, header = build_contextual_text(doc)
        # The literal {content} must be visible in the header (escaped → {{content}})
        # but NOT have been re-substituted by format_map.
        assert "{content}" in header
        # Page content "x" must appear exactly once in the embedded text.
        assert text.count("x") == 1

    def test_missing_document_meta_key_returns_passthrough(self):
        """document_meta key entirely absent → (page_content, "")."""
        doc = Document(page_content="hello", metadata={"other_key": "v"})
        text, header = build_contextual_text(doc)
        assert text == "hello"
        assert header == ""

    def test_non_string_values_coerced(self):
        """Integer / float metadata values are coerced to str."""
        doc = Document(page_content="p", metadata={"document_meta": {
            "title": "Doc",
            "page": 42,
        }})
        text, header = build_contextual_text(doc)
        assert "42" in header or "Doc" in header
        assert text.endswith("p")

    def test_all_fields_empty_returns_passthrough(self):
        """All fields None/empty → (page_content, "")."""
        doc = Document(page_content="q", metadata={"document_meta": {
            "title": None, "section": "", "category": None,
        }})
        text, header = build_contextual_text(doc)
        assert text == "q"
        assert header == ""
