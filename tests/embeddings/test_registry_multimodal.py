"""Registry & Catalog integration tests for the multimodal embedding provider.

Verifies that UFormEmbedding is correctly registered in supported_embeddings
and discoverable via EmbeddingRegistry.get_or_create().

Run with:
    pytest tests/embeddings/test_registry_multimodal.py -v
"""
import pytest


class TestRegistryEntry:
    def test_multimodal_in_supported(self):
        """'multimodal' key must exist in supported_embeddings."""
        from parrot.embeddings import supported_embeddings
        assert "multimodal" in supported_embeddings

    def test_multimodal_maps_to_uform(self):
        """'multimodal' must map to the UFormEmbedding class name."""
        from parrot.embeddings import supported_embeddings
        assert supported_embeddings["multimodal"] == "UFormEmbedding"

    def test_catalog_has_uform_entries(self):
        """EMBEDDING_MODELS must contain at least 2 UForm (multimodal) entries."""
        from parrot.embeddings.catalog import EMBEDDING_MODELS
        uform_entries = [e for e in EMBEDDING_MODELS if e.get("provider") == "multimodal"]
        assert len(uform_entries) >= 2

    def test_catalog_has_multilingual_base(self):
        """Multilingual base model must be present in the catalog."""
        from parrot.embeddings.catalog import EMBEDDING_MODELS
        models = {e["model"] for e in EMBEDDING_MODELS}
        assert "unum-cloud/uform3-image-text-multilingual-base" in models

    def test_catalog_has_english_large(self):
        """English large model must be present in the catalog."""
        from parrot.embeddings.catalog import EMBEDDING_MODELS
        models = {e["model"] for e in EMBEDDING_MODELS}
        assert "unum-cloud/uform3-image-text-english-large" in models

    def test_uform_catalog_entries_pass_validation(self):
        """UForm catalog entries must pass EmbeddingModelEntry Pydantic validation."""
        from parrot.embeddings.catalog import EMBEDDING_MODELS, EmbeddingModelEntry
        uform_entries = [e for e in EMBEDDING_MODELS if e.get("provider") == "multimodal"]
        for entry in uform_entries:
            # Should not raise
            EmbeddingModelEntry.model_validate(entry)

    def test_all_existing_catalog_entries_still_valid(self):
        """No regression: all existing non-multimodal entries must still validate."""
        from parrot.embeddings.catalog import EMBEDDING_MODELS, EmbeddingModelEntry
        non_multimodal = [e for e in EMBEDDING_MODELS if e.get("provider") != "multimodal"]
        # Should all pass without error
        for entry in non_multimodal:
            EmbeddingModelEntry.model_validate(entry)

    def test_provider_literal_includes_multimodal(self):
        """Provider type annotation must include 'multimodal'."""
        from parrot.embeddings.catalog import Provider
        # Check by trying to create a model entry with provider='multimodal'
        from parrot.embeddings.catalog import EmbeddingModelEntry
        entry = EmbeddingModelEntry(
            model="test-model",
            provider="multimodal",
            name="Test",
            dimension=768,
            multilingual=False,
            language="en",
            use_case=["retrieval"],
            description="Test model",
            metric_recommended="cosine",
            requires_prefix=False,
            normalized_output=True,
            max_seq_length=77,
            hnsw_compatible=True,
            license="apache-2.0",
            recommended_score_threshold=0.5,
            recommended_search_limit=10,
        )
        assert entry.provider == "multimodal"


class TestRegistryResolution:
    @pytest.mark.asyncio
    async def test_get_or_create_multimodal(self):
        """get_or_create with model_type='multimodal' must return UFormEmbedding."""
        uform = pytest.importorskip("uform", reason="uform not installed")
        from parrot.embeddings.registry import EmbeddingRegistry
        from parrot.embeddings.multimodal import UFormEmbedding

        registry = EmbeddingRegistry.instance()
        # Use get_or_create in a non-model-loading way (build only the wrapper)
        # The registry _build_model creates the wrapper; initialize_model loads
        model = await registry.get_or_create(
            "unum-cloud/uform3-image-text-multilingual-base",
            "multimodal",
        )
        assert isinstance(model, UFormEmbedding)
        # Cleanup
        await registry.unload(
            "unum-cloud/uform3-image-text-multilingual-base",
            "multimodal",
        )

    def test_build_model_returns_uform_instance(self):
        """_build_model must resolve 'multimodal' to a UFormEmbedding instance."""
        from parrot.embeddings.registry import EmbeddingRegistry
        from parrot.embeddings.multimodal import UFormEmbedding

        registry = EmbeddingRegistry.instance()
        model = registry._build_model(
            "unum-cloud/uform3-image-text-multilingual-base",
            "multimodal",
        )
        assert isinstance(model, UFormEmbedding)
