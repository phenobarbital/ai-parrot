"""Unit tests for parrot.knowledge.wiki.documents (FEAT-451, TASK-2351/2352/2353)."""

import builtins
from pathlib import Path

import click
import pytest
import yaml
from parrot.knowledge.wiki.documents import (
    AcquiredDocument,
    DocumentAcquirer,
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


@pytest.fixture
def no_parrot_loaders(monkeypatch):
    """Force `from parrot_loaders... import ...` to raise ImportError."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("parrot_loaders"):
            raise ImportError("simulated: ai-parrot-loaders not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


@pytest.fixture
def sample_pdf(tmp_path):
    """A tiny 2-page PDF with Title/Author set, written via pymupdf."""
    import pymupdf

    pdf_path = tmp_path / "sample.pdf"
    doc = pymupdf.open()
    try:
        for _ in range(2):
            page = doc.new_page()
            page.insert_text((72, 72), "Hello world")
        doc.set_metadata({"title": "Sample Report", "author": "Jane Doe"})
        doc.save(str(pdf_path))
    finally:
        doc.close()
    return pdf_path


class TestAcquireLocal:
    async def test_plaintext_without_loaders(self, tmp_path, no_parrot_loaders):
        p = tmp_path / "a.md"
        p.write_text("# Title\nbody\n")
        doc = await DocumentAcquirer().acquire(
            DocumentRef(uri=str(p), suffix=".md")
        )
        assert "body" in doc.text
        assert doc.metadata.loader == "plaintext"

    async def test_strips_md_frontmatter(self, tmp_path):
        p = tmp_path / "a.md"
        p.write_text("---\ntitle: Contrato\nauthor: Legal\n---\n# Body\n")
        doc = await DocumentAcquirer().acquire(
            DocumentRef(uri=str(p), suffix=".md")
        )
        assert doc.text.lstrip().startswith("# Body")
        assert "title: Contrato" not in doc.text
        assert doc.metadata.title == "Contrato"
        assert doc.metadata.author == "Legal"

    async def test_binary_without_loaders_raises(self, tmp_path, no_parrot_loaders):
        p = tmp_path / "a.pdf"
        p.write_bytes(b"%PDF-1.4\n\x00\x01binary")
        with pytest.raises(DocumentAcquisitionError):
            await DocumentAcquirer().acquire(
                DocumentRef(uri=str(p), suffix=".pdf")
            )

    async def test_binary_uses_loader(self, tmp_path, monkeypatch, sample_pdf):
        doc = await DocumentAcquirer().acquire(
            DocumentRef(uri=str(sample_pdf), suffix=".pdf")
        )
        assert doc.text.strip()
        assert "\x00" not in doc.text
        assert doc.metadata.content_type == "application/pdf"

    async def test_pdf_page_count(self, sample_pdf):
        import pymupdf

        doc = await DocumentAcquirer().acquire(
            DocumentRef(uri=str(sample_pdf), suffix=".pdf")
        )
        pdf = pymupdf.open(str(sample_pdf))
        try:
            expected = pdf.page_count
        finally:
            pdf.close()
        assert doc.metadata.page_count == expected

    async def test_empty_extraction_raises(self, tmp_path, monkeypatch):
        """A loader returning empty content is a failure, not an empty doc."""
        from parrot.stores.models import Document
        from parrot_loaders import factory

        class _EmptyLoader:
            def __init__(self, source):
                self.source = source

            async def _load(self, path, **kwargs):
                return [Document(page_content="", metadata={})]

        monkeypatch.setattr(factory, "get_loader_class", lambda ext: _EmptyLoader)

        p = tmp_path / "a.pdf"
        p.write_bytes(b"%PDF-1.4")
        with pytest.raises(DocumentAcquisitionError):
            await DocumentAcquirer().acquire(
                DocumentRef(uri=str(p), suffix=".pdf")
            )

    def test_no_module_level_loader_import(self):
        repo_root = Path(__file__).resolve().parents[3]
        src = (
            repo_root
            / "packages/ai-parrot/src/parrot/knowledge/wiki/documents.py"
        )
        text = src.read_text()
        head = text.split("class DocumentAcquirer")[0]
        assert "import parrot_loaders" not in head
