"""Tests for EmbeddingModelEntry Pydantic schema and import-time catalog validation.

Covers TASK-962: catalog schema extension with 8 new metadata fields,
Pydantic v2 validators, and import-time validation of every entry.
"""
import importlib

import pytest
from pydantic import ValidationError


class TestCatalogImportValidates:
    """Verify that importing the catalog runs Pydantic validation on every entry."""

    def test_module_import_validates_all_entries(self):
        """Importing catalog runs validation on every entry without error."""
        import parrot.embeddings.catalog as catalog
        importlib.reload(catalog)
        # If we got here, every entry validated.
        assert len(catalog.EMBEDDING_MODELS) > 0

    def test_every_entry_has_all_new_fields(self):
        """Every catalog entry carries all 8 new metadata fields."""
        from parrot.embeddings.catalog import EMBEDDING_MODELS

        required = {
            "metric_recommended",
            "requires_prefix",
            "prefix_query",
            "prefix_passage",
            "normalized_output",
            "max_seq_length",
            "hnsw_compatible",
            "license",
        }
        for entry in EMBEDDING_MODELS:
            assert required.issubset(entry.keys()), (
                f"{entry['model']} missing new fields: {required - entry.keys()}"
            )

    def test_ada_002_removed(self):
        """text-embedding-ada-002 must not appear in the catalog."""
        from parrot.embeddings.catalog import EMBEDDING_MODELS

        assert not any(
            e["model"] == "text-embedding-ada-002" for e in EMBEDDING_MODELS
        )

    def test_all_entries_have_positive_dimension(self):
        """Every entry has dimension > 0 (basic sanity)."""
        from parrot.embeddings.catalog import EMBEDDING_MODELS

        for entry in EMBEDDING_MODELS:
            assert entry["dimension"] > 0, (
                f"{entry['model']} has dimension={entry['dimension']}"
            )

    def test_all_entries_have_positive_max_seq_length(self):
        """Every entry has max_seq_length > 0."""
        from parrot.embeddings.catalog import EMBEDDING_MODELS

        for entry in EMBEDDING_MODELS:
            assert entry["max_seq_length"] > 0, (
                f"{entry['model']} has max_seq_length={entry['max_seq_length']}"
            )

    def test_hnsw_compatible_matches_dimension_cap(self):
        """hnsw_compatible must equal (dimension <= 2000) for every entry."""
        from parrot.embeddings.catalog import EMBEDDING_MODELS

        for entry in EMBEDDING_MODELS:
            expected = entry["dimension"] <= 2000
            assert entry["hnsw_compatible"] == expected, (
                f"{entry['model']}: hnsw_compatible={entry['hnsw_compatible']} "
                f"but dimension={entry['dimension']}"
            )


class TestEmbeddingModelEntryValidators:
    """Unit tests for EmbeddingModelEntry Pydantic validators."""

    def _valid_kwargs(self, **overrides):
        """Return a dict of valid kwargs for EmbeddingModelEntry."""
        base = dict(
            model="test/model",
            provider="huggingface",
            name="Test Model",
            dimension=768,
            multilingual=False,
            language="en",
            use_case=["similarity"],
            description="A test model.",
            metric_recommended="cosine",
            requires_prefix=False,
            prefix_query=None,
            prefix_passage=None,
            normalized_output=True,
            max_seq_length=512,
            hnsw_compatible=True,
            license="apache-2.0",
            recommended_score_threshold=0.5,
            recommended_search_limit=10,
        )
        base.update(overrides)
        return base

    def test_valid_entry_accepted(self):
        """A well-formed entry validates without error."""
        from parrot.embeddings.catalog import EmbeddingModelEntry

        entry = EmbeddingModelEntry(**self._valid_kwargs())
        assert entry.model == "test/model"

    def test_requires_prefix_false_with_prefix_query_rejected(self):
        """requires_prefix=False with prefix_query set raises ValidationError."""
        from parrot.embeddings.catalog import EmbeddingModelEntry

        with pytest.raises(ValidationError, match="requires_prefix=False"):
            EmbeddingModelEntry(**self._valid_kwargs(
                requires_prefix=False, prefix_query="bad"
            ))

    def test_requires_prefix_false_with_prefix_passage_rejected(self):
        """requires_prefix=False with prefix_passage set raises ValidationError."""
        from parrot.embeddings.catalog import EmbeddingModelEntry

        with pytest.raises(ValidationError, match="requires_prefix=False"):
            EmbeddingModelEntry(**self._valid_kwargs(
                requires_prefix=False, prefix_passage="bad"
            ))

    def test_requires_prefix_true_without_prefix_rejected(self):
        """requires_prefix=True with both prefixes None raises ValidationError."""
        from parrot.embeddings.catalog import EmbeddingModelEntry

        with pytest.raises(ValidationError, match="requires_prefix=True"):
            EmbeddingModelEntry(**self._valid_kwargs(
                requires_prefix=True,
                prefix_query=None,
                prefix_passage=None,
            ))

    def test_requires_prefix_true_with_only_query_accepted(self):
        """requires_prefix=True with only prefix_query set is valid."""
        from parrot.embeddings.catalog import EmbeddingModelEntry

        entry = EmbeddingModelEntry(**self._valid_kwargs(
            requires_prefix=True,
            prefix_query="query: ",
            prefix_passage=None,
        ))
        assert entry.requires_prefix is True

    def test_hnsw_flag_inconsistent_with_high_dim_rejected(self):
        """dimension=4096 with hnsw_compatible=True raises ValidationError."""
        from parrot.embeddings.catalog import EmbeddingModelEntry

        with pytest.raises(ValidationError, match="hnsw_compatible"):
            EmbeddingModelEntry(**self._valid_kwargs(
                dimension=4096,
                max_seq_length=4096,
                hnsw_compatible=True,
            ))

    def test_hnsw_flag_inconsistent_with_low_dim_rejected(self):
        """dimension=768 with hnsw_compatible=False raises ValidationError."""
        from parrot.embeddings.catalog import EmbeddingModelEntry

        with pytest.raises(ValidationError, match="hnsw_compatible"):
            EmbeddingModelEntry(**self._valid_kwargs(
                dimension=768,
                hnsw_compatible=False,
            ))

    def test_hnsw_flag_correct_for_low_dim(self):
        """dimension=768, hnsw_compatible=True is valid."""
        from parrot.embeddings.catalog import EmbeddingModelEntry

        entry = EmbeddingModelEntry(**self._valid_kwargs(
            dimension=768, hnsw_compatible=True
        ))
        assert entry.hnsw_compatible is True

    def test_hnsw_flag_correct_for_high_dim(self):
        """dimension=4096, hnsw_compatible=False is valid."""
        from parrot.embeddings.catalog import EmbeddingModelEntry

        entry = EmbeddingModelEntry(**self._valid_kwargs(
            dimension=4096,
            max_seq_length=4096,
            hnsw_compatible=False,
            requires_prefix=False,
        ))
        assert entry.hnsw_compatible is False

    def test_invalid_provider_rejected(self):
        """Unknown provider string raises ValidationError."""
        from parrot.embeddings.catalog import EmbeddingModelEntry

        with pytest.raises(ValidationError):
            EmbeddingModelEntry(**self._valid_kwargs(provider="cohere"))

    def test_invalid_metric_rejected(self):
        """Unknown metric string raises ValidationError."""
        from parrot.embeddings.catalog import EmbeddingModelEntry

        with pytest.raises(ValidationError):
            EmbeddingModelEntry(**self._valid_kwargs(metric_recommended="euclidean"))


class TestExistingEntriesBackfilled:
    """Spot-checks that specific existing entries have the right new fields."""

    def _get_entry(self, model_id: str) -> dict:
        from parrot.embeddings.catalog import EMBEDDING_MODELS

        entry = next((e for e in EMBEDDING_MODELS if e["model"] == model_id), None)
        assert entry is not None, f"Entry not found: {model_id}"
        return entry

    def test_dot_v1_has_metric_dot_and_not_normalized(self):
        """multi-qa-mpnet-base-dot-v1 must have metric=dot, normalized=False."""
        entry = self._get_entry("sentence-transformers/multi-qa-mpnet-base-dot-v1")
        assert entry["metric_recommended"] == "dot"
        assert entry["normalized_output"] is False

    def test_e5_base_has_correct_prefix_pair(self):
        """intfloat/e5-base-v2 must carry the canonical E5 prefix pair."""
        entry = self._get_entry("intfloat/e5-base-v2")
        assert entry["requires_prefix"] is True
        assert entry["prefix_query"] == "query: "
        assert entry["prefix_passage"] == "passage: "

    def test_bge_base_en_has_retrieval_prefix(self):
        """BAAI/bge-base-en-v1.5 must carry the BGE retrieval prefix."""
        entry = self._get_entry("BAAI/bge-base-en-v1.5")
        assert entry["requires_prefix"] is True
        assert entry["prefix_query"] == (
            "Represent this sentence for searching relevant passages: "
        )
        assert entry["prefix_passage"] is None

    def test_mpnet_no_prefix(self):
        """all-mpnet-base-v2 must have requires_prefix=False."""
        entry = self._get_entry("sentence-transformers/all-mpnet-base-v2")
        assert entry["requires_prefix"] is False
        assert entry["prefix_query"] is None
        assert entry["prefix_passage"] is None

    def test_openai_models_have_proprietary_license(self):
        """OpenAI models must have license='proprietary'."""
        from parrot.embeddings.catalog import EMBEDDING_MODELS

        for entry in EMBEDDING_MODELS:
            if entry["provider"] == "openai":
                assert entry["license"] == "proprietary", (
                    f"{entry['model']} has license={entry['license']!r}"
                )
