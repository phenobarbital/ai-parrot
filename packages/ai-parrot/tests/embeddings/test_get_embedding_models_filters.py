"""Tests for extended get_embedding_models() filter kwargs.

Covers TASK-965: four new optional filter arguments (metric, max_dims,
hnsw_compatible, requires_prefix) and AND-composition behaviour.
"""
import pytest
from parrot.embeddings import get_embedding_models, EMBEDDING_MODELS


class TestNewFilters:
    """Verify each new filter kwarg returns the correct subset."""

    def test_filter_by_metric_cosine(self):
        """metric='cosine' returns only cosine-metric entries."""
        result = get_embedding_models(metric="cosine")
        assert len(result) > 0
        assert all(m["metric_recommended"] == "cosine" for m in result)

    def test_filter_by_metric_dot(self):
        """metric='dot' returns only dot-metric entries, including multi-qa-dot-v1."""
        result = get_embedding_models(metric="dot")
        assert all(m["metric_recommended"] == "dot" for m in result)
        assert any(
            m["model"] == "sentence-transformers/multi-qa-mpnet-base-dot-v1"
            for m in result
        )

    def test_filter_by_metric_cosine_excludes_dot_models(self):
        """metric='cosine' must not include multi-qa-mpnet-base-dot-v1."""
        result = get_embedding_models(metric="cosine")
        assert not any(
            m["model"] == "sentence-transformers/multi-qa-mpnet-base-dot-v1"
            for m in result
        )

    def test_filter_by_max_dims_excludes_high_dim(self):
        """max_dims=1024 excludes 4096-dim models."""
        result = get_embedding_models(max_dims=1024)
        assert all(m["dimension"] <= 1024 for m in result)
        assert not any(
            m["model"] == "intfloat/e5-mistral-7b-instruct" for m in result
        )

    def test_filter_by_max_dims_small(self):
        """max_dims=384 returns only small-dim models."""
        result = get_embedding_models(max_dims=384)
        assert all(m["dimension"] <= 384 for m in result)
        assert len(result) > 0

    def test_filter_hnsw_compatible_true(self):
        """hnsw_compatible=True excludes models with dimension > 2000."""
        result = get_embedding_models(hnsw_compatible=True)
        assert all(m["hnsw_compatible"] is True for m in result)
        assert all(m["dimension"] <= 2000 for m in result)
        # NV-Embed-v2 (4096d) must be excluded
        assert not any(m["model"] == "nvidia/NV-Embed-v2" for m in result)
        # e5-mistral (4096d) must be excluded
        assert not any(
            m["model"] == "intfloat/e5-mistral-7b-instruct" for m in result
        )

    def test_filter_hnsw_compatible_false(self):
        """hnsw_compatible=False returns only high-dim models."""
        result = get_embedding_models(hnsw_compatible=False)
        assert all(m["hnsw_compatible"] is False for m in result)
        assert any(m["model"] == "nvidia/NV-Embed-v2" for m in result)
        assert any(
            m["model"] == "intfloat/e5-mistral-7b-instruct" for m in result
        )

    def test_filter_requires_prefix_false(self):
        """requires_prefix=False excludes all prefix-requiring models."""
        result = get_embedding_models(requires_prefix=False)
        assert all(m["requires_prefix"] is False for m in result)
        # E5 / BGE-EN-v1.5 / Jina v3 / instruct models must all be excluded
        assert not any("e5-base" in m["model"] for m in result)
        assert not any("bge-base-en-v1.5" in m["model"] for m in result)
        assert not any("jina-embeddings-v3" in m["model"] for m in result)
        assert not any("instruct" in m["model"] for m in result)

    def test_filter_requires_prefix_true(self):
        """requires_prefix=True returns only prefix-requiring models."""
        result = get_embedding_models(requires_prefix=True)
        assert all(m["requires_prefix"] is True for m in result)
        # E5 and BGE-EN-v1.5 must appear
        assert any("e5-base-v2" in m["model"] for m in result)
        assert any("bge-base-en-v1.5" in m["model"] for m in result)

    def test_filter_by_max_dims_none_returns_all(self):
        """max_dims=None (default) applies no dimension filter."""
        result = get_embedding_models()
        assert len(result) == len(EMBEDDING_MODELS)


class TestAndComposition:
    """Verify that multiple active filters compose with AND semantics."""

    def test_three_filter_combo_returns_nonempty(self):
        """metric=cosine + hnsw_compatible=True + requires_prefix=False returns results."""
        result = get_embedding_models(
            metric="cosine",
            hnsw_compatible=True,
            requires_prefix=False,
        )
        assert len(result) > 0
        for m in result:
            assert m["metric_recommended"] == "cosine"
            assert m["hnsw_compatible"] is True
            assert m["requires_prefix"] is False

    def test_provider_plus_metric_combo(self):
        """provider='huggingface' + metric='dot' returns only HF dot-metric models."""
        result = get_embedding_models(provider="huggingface", metric="dot")
        assert all(m["provider"] == "huggingface" for m in result)
        assert all(m["metric_recommended"] == "dot" for m in result)

    def test_impossible_combo_returns_empty(self):
        """metric='dot' + hnsw_compatible=False can return empty (no dot + high-dim)."""
        result = get_embedding_models(metric="dot", hnsw_compatible=False)
        # All results must satisfy both constraints
        for m in result:
            assert m["metric_recommended"] == "dot"
            assert m["hnsw_compatible"] is False

    def test_max_dims_plus_requires_prefix_false(self):
        """max_dims=512 + requires_prefix=False returns small, no-prefix models."""
        result = get_embedding_models(max_dims=512, requires_prefix=False)
        for m in result:
            assert m["dimension"] <= 512
            assert m["requires_prefix"] is False


class TestExistingFiltersUnchanged:
    """Backward-compatibility: original provider and use_case filters must still work."""

    def test_provider_filter_huggingface(self):
        """provider='huggingface' still returns only HF entries."""
        result = get_embedding_models(provider="huggingface")
        assert all(m["provider"] == "huggingface" for m in result)
        assert len(result) > 0

    def test_provider_filter_openai(self):
        """provider='openai' still returns only OpenAI entries."""
        result = get_embedding_models(provider="openai")
        assert all(m["provider"] == "openai" for m in result)

    def test_provider_filter_google(self):
        """provider='google' still returns only Google entries."""
        result = get_embedding_models(provider="google")
        assert all(m["provider"] == "google" for m in result)

    def test_use_case_retrieval_filter(self):
        """use_case='retrieval' still returns all retrieval-tagged entries."""
        result = get_embedding_models(use_case="retrieval")
        assert all("retrieval" in m["use_case"] for m in result)
        assert len(result) > 0

    def test_use_case_similarity_filter(self):
        """use_case='similarity' still returns all similarity-tagged entries."""
        result = get_embedding_models(use_case="similarity")
        assert all("similarity" in m["use_case"] for m in result)

    def test_no_filters_returns_full_catalog(self):
        """No filters returns the complete catalog."""
        result = get_embedding_models()
        assert len(result) == len(EMBEDDING_MODELS)

    def test_use_case_clustering_unchanged(self):
        """use_case='clustering' returns a non-empty list."""
        result = get_embedding_models(use_case="clustering")
        assert len(result) > 0
        assert all("clustering" in m["use_case"] for m in result)


class TestEdgeCaseFilters:
    """Edge-case and boundary behaviour for filter arguments."""

    def test_empty_string_provider_returns_empty_not_full_catalog(self):
        """provider='' filters for models whose provider field equals '', returning [].

        Historically this was a silent bypass (truthy check). After the fix
        to ``is not None``, an empty string is treated as a legitimate filter
        value — no provider is named '', so the result is empty rather than
        the full catalog. This documents the corrected contract.
        """
        result = get_embedding_models(provider="")
        assert result == [], (
            "provider='' should return [] (no match), not the full catalog"
        )

    def test_empty_string_use_case_returns_empty(self):
        """use_case='' filters for entries whose use_case list contains '', returning []."""
        result = get_embedding_models(use_case="")
        assert result == []

    def test_empty_string_metric_returns_empty(self):
        """metric='' filters for entries whose metric_recommended equals '', returning []."""
        result = get_embedding_models(metric="")
        assert result == []

    def test_none_filters_are_equivalent_to_no_args(self):
        """Passing all filters as None is identical to calling with no args."""
        result_none = get_embedding_models(
            provider=None,
            use_case=None,
            metric=None,
            max_dims=None,
            hnsw_compatible=None,
            requires_prefix=None,
        )
        result_default = get_embedding_models()
        assert result_none == result_default
