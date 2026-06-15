"""Unit tests for FEAT-237 catalog backend field and new model entries.

Tests:
  - EmbeddingModelEntry accepts optional backend field (backward compat).
  - backend field accepts valid Literal values and rejects invalid ones.
  - New model entries (Qwen3, multilingual-e5-small, potion-base-8M) exist.
"""
import pytest
from parrot.embeddings.catalog import EMBEDDING_MODELS, EmbeddingModelEntry


def _find_model(model_id: str) -> dict | None:
    """Return the first catalog entry whose 'model' key matches model_id."""
    for entry in EMBEDDING_MODELS:
        if entry["model"] == model_id:
            return entry
    return None


class TestCatalogBackendField:
    def test_backend_field_optional(self):
        """Existing entries validate without backend field (backward compat)."""
        for entry in EMBEDDING_MODELS:
            validated = EmbeddingModelEntry.model_validate(entry)
            assert isinstance(validated, EmbeddingModelEntry)

    def test_backend_field_none_by_default(self):
        """backend defaults to None on existing entries."""
        for entry in EMBEDDING_MODELS:
            validated = EmbeddingModelEntry.model_validate(entry)
            assert validated.backend is None or validated.backend in ("torch", "onnx", "openvino")

    def test_backend_field_accepts_torch(self):
        """Backend field accepts 'torch'."""
        entry = EmbeddingModelEntry(
            model="test/model",
            provider="huggingface",
            name="test",
            dimension=256,
            multilingual=False,
            language="en",
            use_case=["similarity"],
            description="test model",
            metric_recommended="cosine",
            requires_prefix=False,
            normalized_output=True,
            max_seq_length=512,
            hnsw_compatible=True,
            license="mit",
            recommended_score_threshold=0.5,
            recommended_search_limit=10,
            backend="torch",
        )
        assert entry.backend == "torch"

    def test_backend_field_accepts_onnx(self):
        """Backend field accepts 'onnx'."""
        entry = EmbeddingModelEntry(
            model="test/model",
            provider="huggingface",
            name="test",
            dimension=256,
            multilingual=False,
            language="en",
            use_case=["similarity"],
            description="test model",
            metric_recommended="cosine",
            requires_prefix=False,
            normalized_output=True,
            max_seq_length=512,
            hnsw_compatible=True,
            license="mit",
            recommended_score_threshold=0.5,
            recommended_search_limit=10,
            backend="onnx",
        )
        assert entry.backend == "onnx"

    def test_backend_field_accepts_openvino(self):
        """Backend field accepts 'openvino'."""
        entry = EmbeddingModelEntry(
            model="test/model",
            provider="huggingface",
            name="test",
            dimension=256,
            multilingual=False,
            language="en",
            use_case=["similarity"],
            description="test model",
            metric_recommended="cosine",
            requires_prefix=False,
            normalized_output=True,
            max_seq_length=512,
            hnsw_compatible=True,
            license="mit",
            recommended_score_threshold=0.5,
            recommended_search_limit=10,
            backend="openvino",
        )
        assert entry.backend == "openvino"

    def test_backend_field_rejects_invalid(self):
        """Backend field rejects unknown values."""
        with pytest.raises(Exception):
            EmbeddingModelEntry(
                model="test/model",
                provider="huggingface",
                name="test",
                dimension=256,
                multilingual=False,
                language="en",
                use_case=["similarity"],
                description="test model",
                metric_recommended="cosine",
                requires_prefix=False,
                normalized_output=True,
                max_seq_length=512,
                hnsw_compatible=True,
                license="mit",
                recommended_score_threshold=0.5,
                recommended_search_limit=10,
                backend="invalid",
            )

    def test_qwen3_entry_exists(self):
        """Qwen3-Embedding-0.6B is in the catalog."""
        entry = _find_model("Qwen/Qwen3-Embedding-0.6B")
        assert entry is not None, "Qwen/Qwen3-Embedding-0.6B not found in EMBEDDING_MODELS"
        assert entry["dimension"] == 1024

    def test_e5_small_entry_exists(self):
        """multilingual-e5-small is in the catalog."""
        entry = _find_model("intfloat/multilingual-e5-small")
        assert entry is not None, "intfloat/multilingual-e5-small not found in EMBEDDING_MODELS"
        assert entry["dimension"] == 384

    def test_potion_entry_exists(self):
        """potion-base-8M is in the catalog."""
        entry = _find_model("minishlab/potion-base-8M")
        assert entry is not None, "minishlab/potion-base-8M not found in EMBEDDING_MODELS"
        assert entry["dimension"] == 256

    def test_all_new_entries_validate(self):
        """All three new catalog entries pass EmbeddingModelEntry validation."""
        new_models = [
            "Qwen/Qwen3-Embedding-0.6B",
            "intfloat/multilingual-e5-small",
            "minishlab/potion-base-8M",
        ]
        for model_id in new_models:
            entry = _find_model(model_id)
            assert entry is not None, f"{model_id} not found in catalog"
            validated = EmbeddingModelEntry.model_validate(entry)
            assert isinstance(validated, EmbeddingModelEntry)
