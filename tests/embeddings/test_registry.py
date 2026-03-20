"""Unit tests for EmbeddingRegistry (TASK-374)."""
import asyncio
import pytest
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_registry():
    """Reset singleton between tests to ensure full isolation."""
    from parrot.embeddings.registry import EmbeddingRegistry

    # Reset singleton before the test
    EmbeddingRegistry._instance = None
    yield
    # Tear-down
    if EmbeddingRegistry._instance is not None:
        EmbeddingRegistry._instance.clear()
        EmbeddingRegistry._instance = None


def _make_mock_model(model_name: str = "test-model"):
    """Return a MagicMock that behaves like an EmbeddingModel."""
    m = MagicMock()
    m.free = MagicMock()
    m.model_name = model_name
    m.encode.return_value = [[0.1] * 384]
    return m


# ---------------------------------------------------------------------------
# Singleton tests
# ---------------------------------------------------------------------------

class TestEmbeddingRegistrySingleton:
    def test_instance_returns_same_object(self):
        from parrot.embeddings.registry import EmbeddingRegistry

        r1 = EmbeddingRegistry.instance()
        r2 = EmbeddingRegistry.instance()
        assert r1 is r2

    def test_instance_respects_max_models_on_first_call(self):
        from parrot.embeddings.registry import EmbeddingRegistry

        r = EmbeddingRegistry.instance(max_models=3)
        assert r._max_models == 3

    def test_subsequent_instance_calls_ignore_max_models(self):
        """Once created, max_models is fixed."""
        from parrot.embeddings.registry import EmbeddingRegistry

        r1 = EmbeddingRegistry.instance(max_models=5)
        r2 = EmbeddingRegistry.instance(max_models=99)
        assert r1 is r2
        assert r2._max_models == 5


# ---------------------------------------------------------------------------
# get_or_create (async)
# ---------------------------------------------------------------------------

class TestGetOrCreate:
    @pytest.mark.asyncio
    async def test_caches_by_key(self):
        """Same (model_name, model_type) returns identical instance."""
        from parrot.embeddings.registry import EmbeddingRegistry

        mock_model = _make_mock_model()
        registry = EmbeddingRegistry.instance(max_models=10)

        with patch.object(registry, "_build_model", return_value=mock_model) as builder:
            m1 = await registry.get_or_create("all-MiniLM-L6-v2", "huggingface")
            m2 = await registry.get_or_create("all-MiniLM-L6-v2", "huggingface")

        assert m1 is m2
        # Builder called only once
        assert builder.call_count == 1

    @pytest.mark.asyncio
    async def test_different_keys_create_different_instances(self):
        """Different model names produce different instances."""
        from parrot.embeddings.registry import EmbeddingRegistry

        mock_a = _make_mock_model("model-a")
        mock_b = _make_mock_model("model-b")
        registry = EmbeddingRegistry.instance(max_models=10)

        def _build(model_name, model_type, **_kw):
            return mock_a if model_name == "model-a" else mock_b

        with patch.object(registry, "_build_model", side_effect=_build):
            ma = await registry.get_or_create("model-a", "huggingface")
            mb = await registry.get_or_create("model-b", "huggingface")

        assert ma is not mb
        assert ma is mock_a
        assert mb is mock_b

    @pytest.mark.asyncio
    async def test_concurrent_first_access_loads_once(self):
        """Multiple concurrent coroutines for the same key load the model once."""
        from parrot.embeddings.registry import EmbeddingRegistry

        call_count = 0
        mock_model = _make_mock_model()

        def _build_slow(model_name, model_type, **_kw):
            nonlocal call_count
            call_count += 1
            return mock_model

        registry = EmbeddingRegistry.instance(max_models=10)

        with patch.object(registry, "_build_model", side_effect=_build_slow):
            results = await asyncio.gather(
                registry.get_or_create("shared-model", "huggingface"),
                registry.get_or_create("shared-model", "huggingface"),
                registry.get_or_create("shared-model", "huggingface"),
            )

        assert call_count == 1, f"Expected 1 build, got {call_count}"
        assert all(r is mock_model for r in results)

    @pytest.mark.asyncio
    async def test_cache_hit_increments_stats(self):
        from parrot.embeddings.registry import EmbeddingRegistry

        registry = EmbeddingRegistry.instance(max_models=10)

        with patch.object(registry, "_build_model", return_value=_make_mock_model()):
            await registry.get_or_create("m", "huggingface")  # miss
            await registry.get_or_create("m", "huggingface")  # hit

        stats = registry.stats()
        assert stats.cache_misses == 1
        assert stats.cache_hits == 1


# ---------------------------------------------------------------------------
# LRU Eviction
# ---------------------------------------------------------------------------

class TestLRUEviction:
    @pytest.mark.asyncio
    async def test_evicts_oldest_when_full(self):
        """After max_models+1 distinct models, the oldest is evicted."""
        from parrot.embeddings.registry import EmbeddingRegistry

        max_m = 3
        registry = EmbeddingRegistry.instance(max_models=max_m)
        models = {f"model-{i}": _make_mock_model(f"model-{i}") for i in range(max_m + 1)}

        def _build(model_name, model_type, **_kw):
            return models[model_name]

        with patch.object(registry, "_build_model", side_effect=_build):
            for i in range(max_m + 1):
                await registry.get_or_create(f"model-{i}", "huggingface")

        # model-0 should have been evicted
        loaded = registry.loaded_models()
        assert ("model-0", "huggingface") not in loaded
        assert len(loaded) == max_m

    @pytest.mark.asyncio
    async def test_eviction_calls_free(self):
        """Evicted model's free() is called."""
        from parrot.embeddings.registry import EmbeddingRegistry

        max_m = 2
        registry = EmbeddingRegistry.instance(max_models=max_m)
        first_model = _make_mock_model("model-0")
        models = {"model-0": first_model}
        for i in range(1, max_m + 1):
            models[f"model-{i}"] = _make_mock_model(f"model-{i}")

        def _build(model_name, model_type, **_kw):
            return models[model_name]

        with patch.object(registry, "_build_model", side_effect=_build):
            for i in range(max_m + 1):
                await registry.get_or_create(f"model-{i}", "huggingface")

        first_model.free.assert_called_once()

    @pytest.mark.asyncio
    async def test_eviction_logs_warning(self):
        """Eviction emits a warning log."""
        from parrot.embeddings.registry import EmbeddingRegistry

        registry = EmbeddingRegistry.instance(max_models=1)

        def _build(model_name, model_type, **_kw):
            return _make_mock_model(model_name)

        with patch.object(registry, "_build_model", side_effect=_build), \
             patch.object(registry.logger, "warning") as mock_warn:
            await registry.get_or_create("model-a", "huggingface")
            await registry.get_or_create("model-b", "huggingface")  # triggers eviction

        assert mock_warn.called, "Expected a warning log on eviction"

    @pytest.mark.asyncio
    async def test_access_refreshes_lru(self):
        """Accessing a cached model moves it to MRU position (not evicted next)."""
        from parrot.embeddings.registry import EmbeddingRegistry

        max_m = 2
        registry = EmbeddingRegistry.instance(max_models=max_m)
        models = {f"model-{i}": _make_mock_model(f"model-{i}") for i in range(3)}

        def _build(model_name, model_type, **_kw):
            return models[model_name]

        with patch.object(registry, "_build_model", side_effect=_build):
            await registry.get_or_create("model-0", "huggingface")
            await registry.get_or_create("model-1", "huggingface")
            # Access model-0 again to refresh its LRU position
            await registry.get_or_create("model-0", "huggingface")
            # Adding model-2 should evict model-1 (LRU), not model-0
            await registry.get_or_create("model-2", "huggingface")

        loaded = registry.loaded_models()
        assert ("model-1", "huggingface") not in loaded
        assert ("model-0", "huggingface") in loaded


# ---------------------------------------------------------------------------
# Preload / Unload
# ---------------------------------------------------------------------------

class TestPreloadUnload:
    @pytest.mark.asyncio
    async def test_preload_populates_cache(self):
        from parrot.embeddings.registry import EmbeddingRegistry

        registry = EmbeddingRegistry.instance(max_models=10)

        def _build(model_name, model_type, **_kw):
            return _make_mock_model(model_name)

        with patch.object(registry, "_build_model", side_effect=_build):
            await registry.preload([
                {"model_name": "model-a", "model_type": "huggingface"},
                {"model_name": "model-b", "model_type": "huggingface"},
            ])

        loaded = registry.loaded_models()
        assert ("model-a", "huggingface") in loaded
        assert ("model-b", "huggingface") in loaded

    @pytest.mark.asyncio
    async def test_unload_removes_and_calls_free(self):
        from parrot.embeddings.registry import EmbeddingRegistry

        registry = EmbeddingRegistry.instance(max_models=10)
        mock_model = _make_mock_model()

        with patch.object(registry, "_build_model", return_value=mock_model):
            await registry.get_or_create("model-x", "huggingface")

        result = await registry.unload("model-x", "huggingface")

        assert result is True
        assert ("model-x", "huggingface") not in registry.loaded_models()
        mock_model.free.assert_called_once()

    @pytest.mark.asyncio
    async def test_unload_nonexistent_returns_false(self):
        from parrot.embeddings.registry import EmbeddingRegistry

        registry = EmbeddingRegistry.instance(max_models=10)
        result = await registry.unload("does-not-exist", "huggingface")
        assert result is False

    @pytest.mark.asyncio
    async def test_preload_skips_empty_model_name(self):
        """preload() silently skips entries with no model_name."""
        from parrot.embeddings.registry import EmbeddingRegistry

        registry = EmbeddingRegistry.instance(max_models=10)

        with patch.object(registry, "_build_model") as builder:
            await registry.preload([{"model_type": "huggingface"}])  # no model_name

        builder.assert_not_called()


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

class TestStats:
    @pytest.mark.asyncio
    async def test_stats_tracks_hits_and_misses(self):
        from parrot.embeddings.registry import EmbeddingRegistry

        registry = EmbeddingRegistry.instance(max_models=10)

        with patch.object(registry, "_build_model", return_value=_make_mock_model()):
            await registry.get_or_create("m", "huggingface")  # miss
            await registry.get_or_create("m", "huggingface")  # hit
            await registry.get_or_create("m", "huggingface")  # hit

        stats = registry.stats()
        assert stats.cache_misses == 1
        assert stats.cache_hits == 2
        assert stats.loaded_models == 1

    @pytest.mark.asyncio
    async def test_stats_tracks_evictions(self):
        from parrot.embeddings.registry import EmbeddingRegistry

        registry = EmbeddingRegistry.instance(max_models=1)

        def _build(model_name, model_type, **_kw):
            return _make_mock_model(model_name)

        with patch.object(registry, "_build_model", side_effect=_build):
            await registry.get_or_create("m-a", "huggingface")
            await registry.get_or_create("m-b", "huggingface")

        stats = registry.stats()
        assert stats.evictions == 1

    def test_loaded_models_returns_keys(self):
        from parrot.embeddings.registry import EmbeddingRegistry

        registry = EmbeddingRegistry.instance(max_models=10)
        assert registry.loaded_models() == []

    @pytest.mark.asyncio
    async def test_stats_gpu_memory_none_without_cuda(self):
        """gpu_memory_mb is None when CUDA is not available."""
        from parrot.embeddings.registry import EmbeddingRegistry

        registry = EmbeddingRegistry.instance(max_models=10)

        with patch("parrot.embeddings.registry.importlib"), \
             patch("torch.cuda.is_available", return_value=False):
            stats = registry.stats()

        assert stats.gpu_memory_mb is None


# ---------------------------------------------------------------------------
# Clear
# ---------------------------------------------------------------------------

class TestClear:
    @pytest.mark.asyncio
    async def test_clear_empties_cache(self):
        from parrot.embeddings.registry import EmbeddingRegistry

        registry = EmbeddingRegistry.instance(max_models=10)

        with patch.object(registry, "_build_model", return_value=_make_mock_model()):
            await registry.get_or_create("m", "huggingface")

        registry.clear()
        assert registry.loaded_models() == []

    @pytest.mark.asyncio
    async def test_clear_calls_free_on_all(self):
        from parrot.embeddings.registry import EmbeddingRegistry

        registry = EmbeddingRegistry.instance(max_models=10)
        models = []

        def _build(model_name, model_type, **_kw):
            m = _make_mock_model(model_name)
            models.append(m)
            return m

        with patch.object(registry, "_build_model", side_effect=_build):
            await registry.get_or_create("m-1", "huggingface")
            await registry.get_or_create("m-2", "huggingface")

        registry.clear()
        for m in models:
            m.free.assert_called_once()

    @pytest.mark.asyncio
    async def test_clear_resets_stats(self):
        from parrot.embeddings.registry import EmbeddingRegistry

        registry = EmbeddingRegistry.instance(max_models=10)

        with patch.object(registry, "_build_model", return_value=_make_mock_model()):
            await registry.get_or_create("m", "huggingface")

        registry.clear()
        stats = registry.stats()
        assert stats.cache_hits == 0
        assert stats.cache_misses == 0
        assert stats.evictions == 0


# ---------------------------------------------------------------------------
# Sync access
# ---------------------------------------------------------------------------

class TestSyncAccess:
    def test_get_or_create_sync_works(self):
        """Sync variant works in non-async context."""
        from parrot.embeddings.registry import EmbeddingRegistry

        registry = EmbeddingRegistry.instance(max_models=10)
        mock_model = _make_mock_model()

        with patch.object(registry, "_build_model", return_value=mock_model):
            m1 = registry.get_or_create_sync("sync-model", "huggingface")
            m2 = registry.get_or_create_sync("sync-model", "huggingface")

        assert m1 is mock_model
        assert m2 is mock_model

    def test_get_or_create_sync_caches(self):
        """Sync variant caches by key."""
        from parrot.embeddings.registry import EmbeddingRegistry

        registry = EmbeddingRegistry.instance(max_models=10)
        call_count = 0

        def _build(model_name, model_type, **_kw):
            nonlocal call_count
            call_count += 1
            return _make_mock_model(model_name)

        with patch.object(registry, "_build_model", side_effect=_build):
            registry.get_or_create_sync("sync-model", "huggingface")
            registry.get_or_create_sync("sync-model", "huggingface")

        assert call_count == 1
