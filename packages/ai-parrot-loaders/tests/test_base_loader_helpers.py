"""Tests for BasePDF and BaseVideoLoader helper additions (TASK-856 / FEAT-125).

Verifies:
- BasePDF.build_default_meta returns canonical document_meta with 5 keys
- BaseVideoLoader.build_default_meta returns canonical document_meta with doctype='video_transcript'
- BaseVideoLoader passes language to super().__init__
- self._language property alias works (read + write)
- BasePDF._lang (OCR code) is unchanged
"""
import pytest
from pathlib import Path

CANONICAL_DOC_META_KEYS = frozenset(
    {"source_type", "category", "type", "language", "title"}
)


# ---------------------------------------------------------------------------
# BasePDF helpers
# ---------------------------------------------------------------------------

class TestBasePDFHelper:
    def _make_loader(self, **kw):
        from parrot_loaders.basepdf import BasePDF

        class ConcretePDF(BasePDF):
            async def _load(self, path, **kwargs):
                return []

        return ConcretePDF(**kw)

    def test_build_default_meta_canonical_shape(self):
        loader = self._make_loader()
        meta = loader.build_default_meta(Path("/tmp/test.pdf"))
        assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS

    def test_build_default_meta_type_is_pdf(self):
        loader = self._make_loader()
        meta = loader.build_default_meta(Path("/tmp/test.pdf"))
        assert meta["type"] == "pdf"
        assert meta["document_meta"]["type"] == "pdf"

    def test_build_default_meta_language_default(self):
        loader = self._make_loader()
        meta = loader.build_default_meta(Path("/tmp/test.pdf"))
        assert meta["document_meta"]["language"] == "en"

    def test_build_default_meta_language_override(self):
        loader = self._make_loader()
        meta = loader.build_default_meta(Path("/tmp/test.pdf"), language="de")
        assert meta["document_meta"]["language"] == "de"

    def test_build_default_meta_title_override(self):
        loader = self._make_loader()
        meta = loader.build_default_meta(Path("/tmp/t.pdf"), title="My Title")
        assert meta["document_meta"]["title"] == "My Title"

    def test_build_default_meta_extras_at_top_level(self):
        loader = self._make_loader()
        meta = loader.build_default_meta(
            Path("/tmp/t.pdf"), page_index=3, section="intro"
        )
        assert "page_index" in meta
        assert "section" in meta
        assert "page_index" not in meta["document_meta"]
        assert "section" not in meta["document_meta"]

    def test_ocr_lang_unchanged(self):
        """BasePDF._lang (OCR) must not be affected."""
        loader = self._make_loader()
        assert loader._lang == "eng"

    def test_ocr_lang_different_from_document_language(self):
        """OCR lang 'eng' and document language 'en' are separate concepts."""
        loader = self._make_loader()
        assert loader._lang == "eng"
        assert loader.language == "en"


# ---------------------------------------------------------------------------
# BaseVideoLoader helpers
# ---------------------------------------------------------------------------

class TestBaseVideoLoaderHelper:
    def _make_loader(self, **kw):
        from parrot_loaders.basevideo import BaseVideoLoader

        class ConcreteVideo(BaseVideoLoader):
            async def _load(self, source, **kwargs):
                return []

            async def load_video(self, url, video_title, transcript):
                return []

        return ConcreteVideo(**kw)

    def test_build_default_meta_canonical_shape(self):
        loader = self._make_loader()
        meta = loader.build_default_meta("https://example.com/video.mp4")
        assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS

    def test_build_default_meta_type_is_video_transcript(self):
        loader = self._make_loader()
        meta = loader.build_default_meta("https://example.com/video.mp4")
        assert meta["type"] == "video_transcript"
        assert meta["document_meta"]["type"] == "video_transcript"

    def test_build_default_meta_language_from_instance(self):
        loader = self._make_loader(language="es")
        meta = loader.build_default_meta("https://example.com/video.mp4")
        assert meta["document_meta"]["language"] == "es"

    def test_build_default_meta_language_override(self):
        loader = self._make_loader(language="es")
        meta = loader.build_default_meta(
            "https://example.com/video.mp4", language="fr"
        )
        assert meta["document_meta"]["language"] == "fr"

    def test_build_default_meta_extras_at_top_level(self):
        loader = self._make_loader()
        meta = loader.build_default_meta(
            "https://example.com/video.mp4",
            origin="/tmp/audio.mp3",
            vtt_path="/tmp/audio.vtt",
        )
        assert "origin" in meta
        assert "vtt_path" in meta
        assert "origin" not in meta["document_meta"]
        assert "vtt_path" not in meta["document_meta"]

    def test_language_attr_set_by_init(self):
        loader = self._make_loader(language="fr")
        assert loader.language == "fr"

    def test_language_alias_read(self):
        """self._language must return self.language."""
        loader = self._make_loader(language="fr")
        assert loader._language == "fr"
        assert loader.language == "fr"

    def test_language_alias_write(self):
        """Writing self._language must update self.language."""
        loader = self._make_loader(language="en")
        loader._language = "ja"
        assert loader.language == "ja"
        assert loader._language == "ja"

    def test_language_passed_to_super(self):
        """language kwarg must be forwarded to AbstractLoader.__init__."""
        loader = self._make_loader(language="zh")
        assert loader.language == "zh"
