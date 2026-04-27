"""Tests for AbstractLoader canonical metadata contract (TASK-855 / FEAT-125).

Verifies:
- create_metadata returns canonical top-level + closed document_meta
- language defaults from self.language, overridable per call
- title auto-derived from path / URL
- extras from **kwargs land at top level, not inside document_meta
- legacy doc_metadata: canonical keys folded in, extras hoisted to top level
- _validate_metadata warns on missing fields, auto-fills, never raises
- _derive_title covers Path, URL, and fallback cases
"""
import logging
import pytest
from pathlib import Path
from parrot.loaders.abstract import AbstractLoader


CANONICAL_DOC_META_KEYS = frozenset(
    {"source_type", "category", "type", "language", "title"}
)
CANONICAL_TOP_LEVEL_KEYS = frozenset(
    {"url", "source", "filename", "type", "source_type", "created_at",
     "category", "document_meta"}
)


class ConcreteLoader(AbstractLoader):
    """Minimal concrete subclass for testing — no I/O."""

    async def _load(self, source, **kwargs):  # noqa: D401
        return []


# ---------------------------------------------------------------------------
# create_metadata — canonical shape
# ---------------------------------------------------------------------------

class TestCreateMetadataCanonicalShape:
    def test_returns_canonical_top_level_keys(self):
        loader = ConcreteLoader()
        meta = loader.create_metadata(
            Path("/tmp/test.pdf"), doctype="pdf", source_type="file"
        )
        assert CANONICAL_TOP_LEVEL_KEYS.issubset(set(meta.keys()))

    def test_document_meta_closed_shape(self):
        loader = ConcreteLoader()
        meta = loader.create_metadata(Path("/tmp/test.pdf"))
        assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS

    def test_language_defaults_from_self(self):
        loader = ConcreteLoader(language="fr")
        meta = loader.create_metadata(Path("/tmp/test.pdf"))
        assert meta["document_meta"]["language"] == "fr"

    def test_language_kwarg_overrides_self(self):
        loader = ConcreteLoader(language="fr")
        meta = loader.create_metadata(Path("/tmp/test.pdf"), language="es")
        assert meta["document_meta"]["language"] == "es"

    def test_title_auto_derived_from_path(self):
        loader = ConcreteLoader()
        meta = loader.create_metadata(Path("/tmp/my_report.pdf"))
        assert meta["document_meta"]["title"] != ""
        assert meta["document_meta"]["title"] is not None

    def test_title_kwarg_used_when_provided(self):
        loader = ConcreteLoader()
        meta = loader.create_metadata(Path("/tmp/t.pdf"), title="Custom Title")
        assert meta["document_meta"]["title"] == "Custom Title"

    def test_extras_become_top_level(self):
        loader = ConcreteLoader()
        meta = loader.create_metadata(
            Path("/tmp/t.pdf"), origin="test", vtt_path="/tmp/x.vtt"
        )
        assert "origin" in meta
        assert "vtt_path" in meta
        assert "origin" not in meta["document_meta"]
        assert "vtt_path" not in meta["document_meta"]

    def test_extras_do_not_bleed_into_doc_meta(self):
        loader = ConcreteLoader()
        meta = loader.create_metadata(
            Path("/tmp/t.pdf"),
            model_name="gpt-4o",
            scene_index=3,
            topic_tags=["AI"],
        )
        assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS
        assert "model_name" in meta
        assert "scene_index" in meta
        assert "topic_tags" in meta

    def test_legacy_doc_metadata_canonical_fields_folded(self):
        loader = ConcreteLoader()
        meta = loader.create_metadata(
            Path("/tmp/t.pdf"),
            doc_metadata={"language": "de", "table": "plans"},
        )
        assert meta["document_meta"]["language"] == "de"
        # Non-canonical "table" hoisted to top level
        assert "table" in meta
        assert "table" not in meta["document_meta"]

    def test_legacy_doc_metadata_extras_hoisted(self):
        loader = ConcreteLoader()
        meta = loader.create_metadata(
            "https://example.com/doc",
            doc_metadata={"language": "it", "row_index": 5, "schema": "public"},
        )
        assert meta["document_meta"]["language"] == "it"
        assert "row_index" in meta
        assert "schema" in meta
        assert "row_index" not in meta["document_meta"]

    def test_type_field_mirrors_doctype(self):
        loader = ConcreteLoader()
        meta = loader.create_metadata(
            Path("/tmp/t.pdf"), doctype="pdf_page", source_type="file"
        )
        assert meta["type"] == "pdf_page"
        assert meta["document_meta"]["type"] == "pdf_page"

    def test_source_type_field_mirrors_loader(self):
        loader = ConcreteLoader()
        meta = loader.create_metadata(
            Path("/tmp/t.pdf"), doctype="pdf", source_type="file"
        )
        assert meta["source_type"] == "file"
        assert meta["document_meta"]["source_type"] == "file"


# ---------------------------------------------------------------------------
# _validate_metadata
# ---------------------------------------------------------------------------

class TestValidateMetadata:
    def test_warns_on_missing_field(self, caplog):
        loader = ConcreteLoader()
        with caplog.at_level(logging.WARNING, logger="Parrot.Loaders.ConcreteLoader"):
            result = loader._validate_metadata({"url": "x", "source": "x"})
        assert "document_meta" in result
        assert len(caplog.records) > 0

    def test_does_not_raise_on_empty(self):
        loader = ConcreteLoader()
        result = loader._validate_metadata({})
        assert isinstance(result, dict)

    def test_auto_fills_document_meta(self):
        loader = ConcreteLoader()
        result = loader._validate_metadata({})
        assert set(result["document_meta"].keys()) == CANONICAL_DOC_META_KEYS

    def test_strips_extra_keys_from_document_meta(self, caplog):
        loader = ConcreteLoader()
        dirty = {
            "url": "x", "source": "x", "filename": "x", "type": "t",
            "source_type": "file", "created_at": "now", "category": "doc",
            "document_meta": {
                "source_type": "file", "category": "doc", "type": "t",
                "language": "en", "title": "T",
                "rogue_key": "should_be_hoisted",
            },
        }
        with caplog.at_level(logging.WARNING, logger="Parrot.Loaders.ConcreteLoader"):
            result = loader._validate_metadata(dirty)
        assert set(result["document_meta"].keys()) == CANONICAL_DOC_META_KEYS
        assert "rogue_key" in result  # hoisted to top level

    def test_returns_same_dict(self):
        loader = ConcreteLoader()
        meta = {"url": "x"}
        result = loader._validate_metadata(meta)
        # mutated in-place and returned
        assert result is meta


# ---------------------------------------------------------------------------
# _derive_title
# ---------------------------------------------------------------------------

class TestDeriveTitle:
    def test_path_stem(self):
        loader = ConcreteLoader()
        title = loader._derive_title(Path("/tmp/my_report.pdf"))
        assert title != ""
        assert "report" in title.lower() or "my" in title.lower()

    def test_path_replaces_underscores(self):
        loader = ConcreteLoader()
        title = loader._derive_title(Path("/tmp/my_report_q4.pdf"))
        assert "_" not in title

    def test_url_segment(self):
        loader = ConcreteLoader()
        title = loader._derive_title("https://example.com/docs/guide")
        assert title != ""
        assert "guide" in title.lower()

    def test_url_strips_extension(self):
        loader = ConcreteLoader()
        title = loader._derive_title("https://example.com/report.pdf")
        assert ".pdf" not in title.lower()

    def test_fallback_string(self):
        loader = ConcreteLoader()
        title = loader._derive_title("some_random_reference")
        assert title != ""

    def test_bare_domain_url(self):
        loader = ConcreteLoader()
        title = loader._derive_title("https://example.com/")
        assert title != ""


# ---------------------------------------------------------------------------
# language attribute
# ---------------------------------------------------------------------------

class TestLanguageAttribute:
    def test_default_language_is_en(self):
        loader = ConcreteLoader()
        assert loader.language == "en"

    def test_custom_language_stored(self):
        loader = ConcreteLoader(language="de")
        assert loader.language == "de"
