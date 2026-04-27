"""
Tests for canonical metadata shape in video/audio loaders (TASK-858).
All tests use create_metadata directly to verify the shape is correct
without needing to actually run video/audio processing pipelines.
"""
from __future__ import annotations
import pytest
from pathlib import Path

CANONICAL_DOC_META_KEYS = {"source_type", "category", "type", "language", "title"}


class TestAudioLoaderMetadata:
    """Verify AudioLoader emits canonical document_meta."""

    def test_canonical_metadata_shape(self):
        from parrot_loaders.audio import AudioLoader
        loader = AudioLoader(language="en")
        meta = loader.create_metadata(
            "test_audio.mp3",
            doctype="audio_transcript",
            source_type="audio",
            origin="/tmp/audio.mp3",
            vtt_path="/tmp/audio.vtt",
        )
        assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS

    def test_non_canonical_at_top_level(self):
        from parrot_loaders.audio import AudioLoader
        loader = AudioLoader(language="en")
        meta = loader.create_metadata(
            "test_audio.mp3",
            doctype="audio_transcript",
            source_type="audio",
            origin="/tmp/audio.mp3",
            vtt_path="/tmp/audio.vtt",
        )
        assert "origin" in meta
        assert "vtt_path" in meta
        assert "origin" not in meta["document_meta"]
        assert "vtt_path" not in meta["document_meta"]

    def test_dialog_chunk_shape(self):
        from parrot_loaders.audio import AudioLoader
        loader = AudioLoader(language="en")
        meta = loader.create_metadata(
            Path("/tmp/audio.mp3"),
            doctype="audio_dialog",
            source_type="audio",
            title="audio",
            start="00:00:01",
            end="00:00:05",
            chunk_id="1",
        )
        assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS
        assert "start" in meta
        assert "chunk_id" in meta
        assert "start" not in meta["document_meta"]

    def test_extract_audio_shape(self):
        from parrot_loaders.audio import AudioLoader
        loader = AudioLoader(language="en")
        meta = loader.create_metadata(
            Path("/tmp/audio.mp3"),
            doctype="audio_transcript",
            source_type="audio",
            vtt_path="/tmp/audio.vtt",
            transcript_path="/tmp/audio.txt",
            srt_path="/tmp/audio.srt",
            summary_path="/tmp/audio.summary",
        )
        assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS
        assert "vtt_path" in meta
        assert "transcript_path" in meta
        assert "srt_path" in meta
        assert "summary_path" in meta
        assert "vtt_path" not in meta["document_meta"]


class TestVideoLocalLoaderMetadata:
    """Verify VideoLocalLoader emits canonical document_meta."""

    def test_canonical_metadata_shape(self):
        from parrot_loaders.videolocal import VideoLocalLoader
        loader = VideoLocalLoader(language="en")
        meta = loader.create_metadata(
            Path("/tmp/video.mp4"),
            doctype="video_transcript",
            source_type="video",
            question="",
            answer="",
            data={},
            summary="",
        )
        assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS

    def test_non_canonical_at_top_level(self):
        from parrot_loaders.videolocal import VideoLocalLoader
        loader = VideoLocalLoader(language="en")
        meta = loader.create_metadata(
            Path("/tmp/video.mp4"),
            doctype="video_transcript",
            source_type="video",
            question="",
            data={},
        )
        assert "question" in meta
        assert "data" in meta
        assert "question" not in meta["document_meta"]

    def test_dialog_chunk_shape(self):
        from parrot_loaders.videolocal import VideoLocalLoader
        loader = VideoLocalLoader(language="en")
        meta = loader.create_metadata(
            Path("/tmp/video.mp4"),
            doctype="video_dialog",
            source_type="video",
            title="video",
            start="00:00:10",
            end="00:00:20",
            chunk_id="5",
        )
        assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS
        assert "start" in meta
        assert "chunk_id" in meta
        assert "start" not in meta["document_meta"]


class TestVideoUnderstandingMetadata:
    """Verify VideoUnderstandingLoader emits canonical document_meta."""

    def test_base_canonical_shape(self):
        from parrot_loaders.videounderstanding import VideoUnderstandingLoader
        loader = VideoUnderstandingLoader(language="en")
        meta = loader.create_metadata(
            Path("/tmp/video.mp4"),
            doctype="video_understanding",
            source_type="video_understanding",
            model_used="gemini-2.0-pro",
            analysis_type="video_understanding",
            video_title="video",
        )
        assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS

    def test_extras_at_top_level(self):
        from parrot_loaders.videounderstanding import VideoUnderstandingLoader
        loader = VideoUnderstandingLoader(language="en")
        meta = loader.create_metadata(
            Path("/tmp/video.mp4"),
            doctype="video_understanding",
            source_type="video_understanding",
            model_used="gemini-2.0-pro",
            scene_index=3,
        )
        assert "model_used" in meta
        assert "scene_index" in meta
        assert "model_used" not in meta["document_meta"]
        assert "scene_index" not in meta["document_meta"]

    def test_variant_document_meta_type(self):
        """Variant metadata keeps document_meta closed-shape with updated type."""
        from parrot_loaders.videounderstanding import VideoUnderstandingLoader
        loader = VideoUnderstandingLoader(language="en")
        base = loader.create_metadata(
            Path("/tmp/video.mp4"),
            doctype="video_understanding",
            source_type="video_understanding",
            model_used="gemini-pro",
        )
        # Simulate variant construction pattern used in _load
        variant = {
            **base,
            "type": "video_analysis_full",
            "document_meta": {**base["document_meta"], "type": "video_analysis_full"},
            "total_scenes": 5,
            "analysis_timestamp": "2026-04-27T00:00:00",
        }
        assert set(variant["document_meta"].keys()) == CANONICAL_DOC_META_KEYS
        assert variant["document_meta"]["type"] == "video_analysis_full"
        assert "total_scenes" in variant
        assert "total_scenes" not in variant["document_meta"]
