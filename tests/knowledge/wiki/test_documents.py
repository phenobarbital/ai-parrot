"""Unit tests for parrot.knowledge.wiki.documents (FEAT-451, TASK-2351)."""

import click
import pytest

from parrot.knowledge.wiki.documents import (
    AcquiredDocument,
    DocumentAcquisitionError,
    DocumentMetadata,
    DocumentRef,
    TriageProvenance,
    resolve_sources,
)


@pytest.fixture
def corpus(tmp_path):
    (tmp_path / "a.md").write_text("# A")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("x")
    (tmp_path / ".hidden.md").write_text("x")
    return tmp_path


class TestResolveSources:
    def test_directory_matches_legacy_walk(self, corpus):
        """Directory walk: sorted, files only, dot-parts skipped."""
        refs = resolve_sources(str(corpus))
        names = [r.uri for r in refs]
        assert all(".git" not in n and ".hidden" not in n for n in names)
        assert len(refs) == 2
        assert names == sorted(names)

    def test_directory_non_recursive(self, corpus):
        refs = resolve_sources(str(corpus), recursive=False)
        assert len(refs) == 1

    def test_single_file(self, corpus):
        refs = resolve_sources(str(corpus / "a.md"))
        assert len(refs) == 1 and refs[0].is_url is False
        assert refs[0].suffix == ".md"

    def test_url(self):
        refs = resolve_sources("https://example.test/doc.PDF")
        assert len(refs) == 1
        assert refs[0].is_url is True
        assert refs[0].suffix == ".pdf"

    def test_missing_path_raises_click_exception(self):
        with pytest.raises(click.ClickException):
            resolve_sources("/no/such/path/at/all")


class TestModels:
    def test_empty_metadata_constructible(self):
        md = DocumentMetadata()
        assert md.title is None and md.extra == {}

    def test_acquired_document_roundtrip(self):
        ref = DocumentRef(uri="/tmp/a.md", suffix=".md")
        doc = AcquiredDocument(ref=ref, text="body", metadata=DocumentMetadata())
        assert doc.text == "body"

    def test_triage_provenance_optional(self):
        assert TriageProvenance().composite_score is None

    def test_acquisition_error_is_exception(self):
        assert issubclass(DocumentAcquisitionError, Exception)
