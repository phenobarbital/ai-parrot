"""Unit tests for parrot.knowledge.wiki.documents (FEAT-451, TASK-2351/2352)."""

import click
import pytest
import yaml

from parrot.knowledge.wiki.documents import (
    AcquiredDocument,
    DocumentAcquisitionError,
    DocumentMetadata,
    DocumentRef,
    TriageProvenance,
    render_frontmatter,
    resolve_sources,
    split_frontmatter,
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


class TestRenderFrontmatter:
    def test_deterministic(self):
        md = DocumentMetadata(title="A", author="B", page_count=3)
        assert render_frontmatter(md) == render_frontmatter(md)

    def test_omits_none(self):
        out = render_frontmatter(DocumentMetadata(title="A"))
        assert "author" not in out

    def test_empty_returns_empty_string(self):
        assert render_frontmatter(DocumentMetadata()) == ""

    def test_extra_keys_sorted(self):
        md = DocumentMetadata(extra={"z": 1, "a": 2})
        out = render_frontmatter(md)
        assert out.index("a:") < out.index("z:")

    def test_provenance_nested_under_triage(self):
        md = DocumentMetadata(title="A")
        prov = TriageProvenance(composite_score=0.8, decision="admit")
        parsed = yaml.safe_load(render_frontmatter(md, prov).strip("-\n"))
        assert parsed["triage"]["decision"] == "admit"
        assert parsed["title"] == "A"

    def test_escapes_hostile_title(self):
        md = DocumentMetadata(title="Report: Q3\nsecond line")
        parsed = yaml.safe_load(render_frontmatter(md).strip("-\n"))
        assert parsed["title"] == "Report: Q3\nsecond line"


class TestSplitFrontmatter:
    def test_roundtrip(self):
        text = "---\ntitle: A\nauthor: B\n---\n# Body\n"
        meta, body = split_frontmatter(text)
        assert meta == {"title": "A", "author": "B"}
        assert body.startswith("# Body")
        assert "title: A" not in body

    def test_no_block_unchanged(self):
        text = "# Just a heading\n"
        assert split_frontmatter(text) == ({}, text)

    def test_unterminated_block_unchanged(self):
        text = "---\ntitle: A\n# no closing fence\n"
        assert split_frontmatter(text) == ({}, text)

    def test_invalid_yaml_unchanged(self):
        text = "---\n: : :\n---\nbody\n"
        meta, body = split_frontmatter(text)
        assert meta == {} and body == text

    def test_non_mapping_unchanged(self):
        text = "---\n- a\n- b\n---\nbody\n"
        meta, body = split_frontmatter(text)
        assert meta == {} and body == text

    def test_crlf_tolerated(self):
        text = "---\r\ntitle: A\r\n---\r\nbody\r\n"
        meta, _ = split_frontmatter(text)
        assert meta == {"title": "A"}
