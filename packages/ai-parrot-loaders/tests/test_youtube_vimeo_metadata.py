"""
Tests for canonical metadata shape in YouTube and Vimeo loaders (TASK-859).
"""
from __future__ import annotations
import pytest

CANONICAL_DOC_META_KEYS = {"source_type", "category", "type", "language", "title"}


class TestYoutubeLoaderMetadata:
    """Verify YoutubeLoader emits canonical document_meta."""

    def test_canonical_metadata_shape(self):
        from parrot_loaders.youtube import YoutubeLoader
        loader = YoutubeLoader(language="en")
        meta = loader.create_metadata(
            "https://youtube.com/watch?v=abc123",
            doctype="youtube_transcript",
            source_type="video",
            topic_tags=["AI", "ML"],
            video_id="abc123",
            channel="test_channel",
        )
        assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS

    def test_non_canonical_at_top_level(self):
        from parrot_loaders.youtube import YoutubeLoader
        loader = YoutubeLoader(language="en")
        meta = loader.create_metadata(
            "https://youtube.com/watch?v=abc123",
            doctype="youtube_transcript",
            source_type="video",
            topic_tags=["AI", "ML"],
            video_id="abc123",
            channel="test_channel",
        )
        assert "topic_tags" in meta
        assert "video_id" in meta
        assert "channel" in meta
        assert "topic_tags" not in meta["document_meta"]
        assert "video_id" not in meta["document_meta"]

    def test_caption_language_propagates(self):
        from parrot_loaders.youtube import YoutubeLoader
        loader = YoutubeLoader(language="en")
        meta = loader.create_metadata(
            "https://youtube.com/watch?v=abc123",
            doctype="youtube_transcript",
            source_type="video",
            language="es",
        )
        assert meta["document_meta"]["language"] == "es"

    def test_dialog_chunk_shape(self):
        from parrot_loaders.youtube import YoutubeLoader
        loader = YoutubeLoader(language="en")
        meta = loader.create_metadata(
            "https://youtube.com/watch?v=abc123",
            doctype="video_dialog",
            source_type="video",
            title="Test Video",
            topic_tags=["AI"],
            start="00:00:05",
            end="00:00:10",
            chunk_id="3",
        )
        assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS
        assert "start" in meta
        assert "chunk_id" in meta
        assert "start" not in meta["document_meta"]

    def test_fallback_docinfo_at_top_level(self):
        from parrot_loaders.youtube import YoutubeLoader
        loader = YoutubeLoader(language="en")
        meta = loader.create_metadata(
            "https://youtube.com/watch?v=abc123",
            doctype="video_transcript",
            source_type="video",
            docinfo={"title": "Test", "view_count": 100},
            summary="A test summary",
        )
        assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS
        assert "docinfo" in meta
        assert "summary" in meta
        assert "docinfo" not in meta["document_meta"]


class TestVimeoLoaderMetadata:
    """Verify VimeoLoader emits canonical document_meta."""

    def test_canonical_metadata_shape(self):
        from parrot_loaders.vimeo import VimeoLoader
        loader = VimeoLoader(language="en")
        meta = loader.create_metadata(
            "https://vimeo.com/123456",
            doctype="vimeo_transcript",
            source_type="video",
            video_id="123456",
            duration=120,
        )
        assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS
        assert "video_id" in meta
        assert "duration" in meta
        assert "video_id" not in meta["document_meta"]

    def test_topic_tags_at_top_level(self):
        from parrot_loaders.vimeo import VimeoLoader
        loader = VimeoLoader(language="en")
        meta = loader.create_metadata(
            "https://vimeo.com/123456",
            doctype="video_transcript",
            source_type="video",
            title="My Video",
            topic_tags=["tech", "training"],
        )
        assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS
        assert "topic_tags" in meta
        assert "topic_tags" not in meta["document_meta"]

    def test_dialog_chunk_shape(self):
        from parrot_loaders.vimeo import VimeoLoader
        loader = VimeoLoader(language="en")
        meta = loader.create_metadata(
            "https://vimeo.com/123456",
            doctype="video_dialog",
            source_type="video",
            title="My Video",
            start="00:01:00",
            end="00:01:30",
            chunk_id="10",
        )
        assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS
        assert "start" in meta
        assert "chunk_id" in meta
        assert "start" not in meta["document_meta"]
