"""Tests for _resolve_prefixes new branches and regression checks.

Covers TASK-963: new resolver branches for Jina v3, gte-Qwen2-instruct,
e5-mistral-7b-instruct, and NV-Embed-v2, plus regression tests for
existing E5 and BGE-EN-v1.5 branches.
"""
import pytest
from parrot.embeddings.huggingface import _resolve_prefixes


class TestNewResolverBranches:
    """Verify newly added resolver branches return correct prefix pairs."""

    def test_jina_v3_query_prefix(self):
        """jinaai/jina-embeddings-v3 returns retrieval query prefix, no passage prefix."""
        q, p = _resolve_prefixes("jinaai/jina-embeddings-v3")
        assert q is not None
        assert "retrieving" in q.lower()
        assert p is None

    def test_jina_v3_exact_prefix(self):
        """Jina v3 query prefix matches documented canonical string."""
        q, p = _resolve_prefixes("jinaai/jina-embeddings-v3")
        assert q == "Represent the query for retrieving evidence documents: "

    def test_gte_qwen2_instruct_prefix(self):
        """gte-Qwen2-1.5B-instruct returns instruct-style prefix."""
        q, p = _resolve_prefixes("Alibaba-NLP/gte-Qwen2-1.5B-instruct")
        assert q is not None
        assert q.startswith("Instruct:")
        assert p is None

    def test_gte_qwen2_instruct_exact_prefix(self):
        """gte-Qwen2 prefix matches documented instruct template."""
        q, p = _resolve_prefixes("Alibaba-NLP/gte-Qwen2-1.5B-instruct")
        expected = (
            "Instruct: Given a web search query, retrieve relevant passages "
            "that answer the query\nQuery: "
        )
        assert q == expected

    def test_e5_mistral_instruct_not_caught_by_generic_e5(self):
        """e5-mistral-7b-instruct MUST NOT return the generic E5 prefix pair."""
        q, p = _resolve_prefixes("intfloat/e5-mistral-7b-instruct")
        # Must NOT be the generic E5 pair
        assert q != "query: ", (
            "e5-mistral-7b-instruct was caught by the generic E5 branch "
            "instead of the instruct branch"
        )
        assert q is not None
        assert q.startswith("Instruct:")
        assert p is None

    def test_e5_mistral_instruct_exact_prefix(self):
        """e5-mistral-7b-instruct prefix matches documented instruct template."""
        q, p = _resolve_prefixes("intfloat/e5-mistral-7b-instruct")
        expected = (
            "Instruct: Given a web search query, retrieve relevant passages "
            "that answer the query\nQuery: "
        )
        assert q == expected

    def test_nv_embed_v2_prefix(self):
        """nvidia/NV-Embed-v2 returns NVIDIA task-instruction prefix."""
        q, p = _resolve_prefixes("nvidia/NV-Embed-v2")
        assert q is not None
        assert q.startswith("Instruct:")
        assert p is None

    def test_nv_embed_v2_exact_prefix(self):
        """NV-Embed-v2 prefix matches documented task-instruction string."""
        q, p = _resolve_prefixes("nvidia/NV-Embed-v2")
        expected = (
            "Instruct: Given a question, retrieve passages that answer the "
            "question\nQuery: "
        )
        assert q == expected


class TestExistingResolverUnchanged:
    """Regression tests: existing branches must not be affected by new additions."""

    @pytest.mark.parametrize("model", [
        "intfloat/e5-base-v2",
        "intfloat/e5-large-v2",
        "intfloat/multilingual-e5-base",
        "intfloat/multilingual-e5-large",
    ])
    def test_e5_family_unchanged(self, model: str):
        """Generic E5 family still returns ("query: ", "passage: ")."""
        assert _resolve_prefixes(model) == ("query: ", "passage: ")

    @pytest.mark.parametrize("model", [
        "BAAI/bge-small-en-v1.5",
        "BAAI/bge-base-en-v1.5",
        "BAAI/bge-large-en-v1.5",
    ])
    def test_bge_en_v15_unchanged(self, model: str):
        """BGE English v1.5 still returns the long retrieval prefix."""
        q, p = _resolve_prefixes(model)
        assert q == "Represent this sentence for searching relevant passages: "
        assert p is None

    @pytest.mark.parametrize("model", [
        "sentence-transformers/all-mpnet-base-v2",
        "sentence-transformers/all-MiniLM-L6-v2",
        "thenlper/gte-base",
        "BAAI/bge-m3",
        "sentence-transformers/multi-qa-mpnet-base-dot-v1",
        "sentence-transformers/multi-qa-mpnet-base-cos-v1",
        "nomic-ai/nomic-embed-text-v1.5",
        "Snowflake/snowflake-arctic-embed-l",
    ])
    def test_no_prefix_models_unchanged(self, model: str):
        """Non-prefix-requiring models still return (None, None)."""
        assert _resolve_prefixes(model) == (None, None)

    def test_empty_model_name(self):
        """Empty string returns (None, None) without error."""
        assert _resolve_prefixes("") == (None, None)

    def test_none_model_name(self):
        """None returns (None, None) without error."""
        assert _resolve_prefixes(None) == (None, None)

    def test_bge_m3_not_caught_by_bge_en_v15_branch(self):
        """BGE-M3 (multilingual, no EN v1.5) must return (None, None)."""
        assert _resolve_prefixes("BAAI/bge-m3") == (None, None)


class TestNewModelsInCatalog:
    """Verify all 5 new models appear in EMBEDDING_MODELS with correct metadata."""

    @pytest.mark.parametrize("model", [
        "sentence-transformers/multi-qa-mpnet-base-cos-v1",
        "jinaai/jina-embeddings-v3",
        "Alibaba-NLP/gte-Qwen2-1.5B-instruct",
        "intfloat/e5-mistral-7b-instruct",
        "nvidia/NV-Embed-v2",
    ])
    def test_new_model_present(self, model: str):
        """Each new model must appear in the catalog."""
        from parrot.embeddings.catalog import EMBEDDING_MODELS

        assert any(e["model"] == model for e in EMBEDDING_MODELS), (
            f"{model} not found in EMBEDDING_MODELS"
        )

    def test_nv_embed_v2_license_flag(self):
        """NV-Embed-v2 must be flagged cc-by-nc-4.0 (non-commercial)."""
        from parrot.embeddings.catalog import EMBEDDING_MODELS

        entry = next(
            e for e in EMBEDDING_MODELS if e["model"] == "nvidia/NV-Embed-v2"
        )
        assert entry["license"] == "cc-by-nc-4.0"

    def test_high_dim_models_flagged_hnsw_incompatible(self):
        """e5-mistral-7b-instruct and NV-Embed-v2 must have hnsw_compatible=False."""
        from parrot.embeddings.catalog import EMBEDDING_MODELS

        for model in ["intfloat/e5-mistral-7b-instruct", "nvidia/NV-Embed-v2"]:
            entry = next(e for e in EMBEDDING_MODELS if e["model"] == model)
            assert entry["hnsw_compatible"] is False, (
                f"{model} should have hnsw_compatible=False (dim={entry['dimension']})"
            )

    def test_multi_qa_cos_v1_metadata(self):
        """multi-qa-mpnet-base-cos-v1 has correct metric, normalized flag, no prefix."""
        from parrot.embeddings.catalog import EMBEDDING_MODELS

        entry = next(
            e for e in EMBEDDING_MODELS
            if e["model"] == "sentence-transformers/multi-qa-mpnet-base-cos-v1"
        )
        assert entry["metric_recommended"] == "cosine"
        assert entry["normalized_output"] is True
        assert entry["requires_prefix"] is False
        assert entry["prefix_query"] is None
        assert entry["prefix_passage"] is None

    def test_modeltype_enum_has_new_entries(self):
        """ModelType enum must include all 5 new model identifiers."""
        from parrot.embeddings.huggingface import ModelType

        expected_values = {
            "sentence-transformers/multi-qa-mpnet-base-cos-v1",
            "jinaai/jina-embeddings-v3",
            "Alibaba-NLP/gte-Qwen2-1.5B-instruct",
            "intfloat/e5-mistral-7b-instruct",
            "nvidia/NV-Embed-v2",
        }
        actual_values = {m.value for m in ModelType}
        missing = expected_values - actual_values
        assert not missing, f"ModelType enum missing entries: {missing}"
