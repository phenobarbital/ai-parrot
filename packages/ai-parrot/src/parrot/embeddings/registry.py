"""
EmbeddingRegistry — Process-wide singleton for embedding model caching.

Provides LRU eviction, per-key async locks for concurrent-safe loading,
GPU memory tracking, and explicit preload/unload APIs.

Usage:
    from parrot.embeddings.registry import EmbeddingRegistry

    # Get or create cached model (async)
    model = await EmbeddingRegistry.instance().get_or_create("all-MiniLM-L6-v2")

    # Sync variant (for @property contexts)
    model = EmbeddingRegistry.instance().get_or_create_sync("all-MiniLM-L6-v2")

    # Preload models at startup
    await EmbeddingRegistry.instance().preload([
        {"model_name": "all-MiniLM-L6-v2", "model_type": "huggingface"},
    ])
"""
from __future__ import annotations
import asyncio
import threading
import importlib
from collections import OrderedDict
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any

from navconfig.logging import logging
from parrot._imports import lazy_import  # noqa: F401 — used by subclasses for lazy sentence-transformers


# FEAT-150: CacheKey extended from 2-tuple to 3-tuple to include the
# Matryoshka truncation dimension.  The third element is None when no
# truncation is requested, preserving backward-compat for all existing
# callers that pass only (model_name, model_type).
CacheKey = Tuple[str, str, Optional[int]]  # (model_name, model_type, matryoshka_dim)


@dataclass
class RegistryStats:
    """Statistics exposed by the EmbeddingRegistry."""

    loaded_models: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    evictions: int = 0
    gpu_memory_mb: Optional[float] = None


class EmbeddingRegistry:
    """Process-wide singleton for embedding model caching with LRU eviction.

    Caches instances by ``(model_name, model_type)`` key.  Multiple
    bots/stores/KBs sharing the same model name reuse a single instance.

    Eviction is LRU (Least Recently Used) and triggers when the cache
    exceeds ``max_models``.  Eviction calls ``model.free()`` and logs a
    warning so operators can tune ``max_models``.

    Thread-safety:
        - Singleton creation is protected by a ``threading.Lock``.
        - Async concurrent first-access for the *same* key is serialised
          by a per-key ``asyncio.Lock``.  Different keys do NOT block each
          other.
        - The sync variant (``get_or_create_sync``) uses a ``threading.Lock``
          and NEVER calls ``asyncio.run()`` — safe to call from within a
          running event loop.
    """

    _instance: Optional["EmbeddingRegistry"] = None
    _instance_lock: threading.Lock = threading.Lock()

    def __init__(self, max_models: int = None) -> None:
        """Initialise the registry.  Called internally by ``instance()`` only."""
        from . import supported_embeddings as _supported_embeddings  # noqa: E402
        from ..conf import EMBEDDING_REGISTRY_MAX_MODELS  # noqa: E402

        self._supported_embeddings = _supported_embeddings
        self._max_models: int = max_models or EMBEDDING_REGISTRY_MAX_MODELS
        self._cache: OrderedDict[CacheKey, Any] = OrderedDict()
        # Per-key async locks so concurrent requests for *different* models
        # do not block each other.
        self._async_locks: Dict[CacheKey, asyncio.Lock] = {}
        # A global threading lock guards mutation of _async_locks dict itself
        # and also the sync path.
        self._sync_lock: threading.Lock = threading.Lock()
        self._stats: Dict[str, int] = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
        }
        self.logger = logging.getLogger("parrot.EmbeddingRegistry")

    # ------------------------------------------------------------------
    # Singleton
    # ------------------------------------------------------------------

    @classmethod
    def instance(cls, max_models: int = None) -> "EmbeddingRegistry":
        """Get or create the process-wide singleton.

        Args:
            max_models: Override the LRU cache size.  Only respected on the
                *first* call — subsequent calls return the existing instance.

        Returns:
            The singleton ``EmbeddingRegistry`` instance.
        """
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls(max_models=max_models)
            return cls._instance

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_matryoshka_dim(kwargs: dict) -> Optional[int]:
        """Extract the Matryoshka truncation dimension from kwargs.

        Returns ``None`` when the caller did not pass ``matryoshka``,
        passed ``None``, or set ``enabled=False``.  This value becomes
        the third element of the cache key so two bots that use the same
        model but different truncation dimensions always land in separate
        cache slots.

        This helper is intentionally permissive — full validation belongs
        to ``validate_against_catalog`` which is invoked inside
        ``SentenceTransformerModel.__init__``.  The registry only needs a
        stable cache discriminator.

        Args:
            kwargs: The ``**kwargs`` dict passed to ``get_or_create`` /
                ``get_or_create_sync``.

        Returns:
            The requested truncation dimension as an ``int``, or ``None``.
        """
        cfg = kwargs.get("matryoshka")
        if not isinstance(cfg, dict):
            return None
        if not cfg.get("enabled"):
            return None
        dim = cfg.get("dimension")
        return int(dim) if isinstance(dim, int) and dim > 0 else None

    def _build_model(self, model_name: str, model_type: str, **kwargs) -> Any:
        """Instantiate an embedding model using ``supported_embeddings``.

        Args:
            model_name: Model identifier (e.g. ``"all-MiniLM-L6-v2"``).
            model_type: Registry key (e.g. ``"huggingface"``).
            **kwargs: Extra keyword arguments forwarded to the model class.

        Returns:
            An instantiated ``EmbeddingModel`` subclass instance.

        Raises:
            ValueError: If ``model_type`` is not in ``supported_embeddings``.
            ImportError: If the model module cannot be imported.
        """
        if model_type not in self._supported_embeddings:
            raise ValueError(
                f"Unsupported embedding model type: '{model_type}'. "
                f"Supported: {list(self._supported_embeddings)}"
            )
        cls_name = self._supported_embeddings[model_type]
        module_path = f"parrot.embeddings.{model_type}"
        try:
            module = importlib.import_module(module_path)
            klass = getattr(module, cls_name)
            return klass(model_name=model_name, **kwargs)
        except ImportError as exc:
            raise ImportError(
                f"Cannot import embedding module '{module_path}': {exc}"
            ) from exc

    def _evict_if_needed(self) -> None:
        """Evict the oldest cache entry if the cache is full.

        This is called while holding an appropriate lock — but since
        ``asyncio.Lock`` can only be awaited (not ``with``-used), the
        caller must ensure serialisation for the async path.
        """
        while len(self._cache) >= self._max_models:
            # popitem(last=False) removes the *oldest* (LRU) entry
            evicted_key, evicted_model = self._cache.popitem(last=False)
            self._stats["evictions"] += 1
            # evicted_key is a 3-tuple (model_name, model_type, matryoshka_dim)
            self.logger.warning(
                "Evicting embedding model '%s' (type=%s, matryoshka_dim=%s) "
                "from cache (cache full: %d/%d)",
                evicted_key[0],
                evicted_key[1],
                evicted_key[2] if len(evicted_key) > 2 else None,
                len(self._cache),
                self._max_models,
            )
            try:
                evicted_model.free()
            except Exception:  # pragma: no cover
                pass
            # Clean up the per-key async lock
            self._async_locks.pop(evicted_key, None)

    def _get_or_create_lock(self, key: CacheKey) -> asyncio.Lock:
        """Return (and lazily create) the per-key async lock."""
        if key not in self._async_locks:
            self._async_locks[key] = asyncio.Lock()
        return self._async_locks[key]

    # ------------------------------------------------------------------
    # Public async API
    # ------------------------------------------------------------------

    async def get_or_create(
        self,
        model_name: str,
        model_type: str = "huggingface",
        **kwargs,
    ) -> Any:
        """Get a cached model or create and cache it on first access.

        Async-safe: concurrent calls for the **same** ``(model_name,
        model_type)`` key await a per-key lock so the model is loaded
        exactly once.  Requests for *different* keys proceed in parallel.

        Args:
            model_name: Model identifier.
            model_type: Embedding backend (default ``"huggingface"``).
            **kwargs: Extra arguments forwarded to the model constructor.

        Returns:
            A cached (or freshly created) ``EmbeddingModel`` instance.
        """
        # FEAT-150: include matryoshka_dim in the cache key so two bots
        # using the same model with different truncation dims do not share
        # a cached instance.  A null third element (no truncation) is
        # backward-compatible with all pre-FEAT-150 callers.
        matryoshka_dim = self._extract_matryoshka_dim(kwargs)
        key: CacheKey = (model_name, model_type, matryoshka_dim)

        # Fast path — already cached
        if key in self._cache:
            self._stats["hits"] += 1
            self._cache.move_to_end(key)  # LRU refresh
            self.logger.debug(
                "Cache hit for embedding model '%s' (type=%s)", model_name, model_type
            )
            return self._cache[key]

        # Slow path — acquire per-key lock to prevent duplicate loads
        lock = self._get_or_create_lock(key)
        async with lock:
            # Double-checked locking: another coroutine may have loaded it
            if key in self._cache:
                self._stats["hits"] += 1
                self._cache.move_to_end(key)
                return self._cache[key]

            self._stats["misses"] += 1
            self.logger.info(
                "Loading embedding model '%s' (type=%s) into registry",
                model_name,
                model_type,
            )

            # Evict before adding new entry
            self._evict_if_needed()

            # Build model in thread pool to keep event loop responsive
            loop = asyncio.get_event_loop()
            model = await loop.run_in_executor(
                None,
                lambda: self._build_model(model_name, model_type, **kwargs),
            )
            self._cache[key] = model

        return model

    async def preload(self, models: List[Dict[str, str]]) -> None:
        """Eagerly load a list of models into the registry cache.

        Each dict must contain at least ``model_name``; ``model_type``
        defaults to ``"huggingface"``.

        Args:
            models: List of dicts like ``{"model_name": ..., "model_type": ...}``.
        """
        for spec in models:
            model_name = spec.get("model_name", "")
            model_type = spec.get("model_type", "huggingface")
            if not model_name:
                continue
            # Pass any extra keys as kwargs
            extra = {k: v for k, v in spec.items() if k not in ("model_name", "model_type")}
            await self.get_or_create(model_name, model_type, **extra)

    async def unload(self, model_name: str, model_type: str = "huggingface") -> bool:
        """Remove a model from the cache and free its resources.

        FEAT-150: removes ALL Matryoshka variants of the model (i.e. all
        3-tuple keys whose first two elements match ``model_name`` and
        ``model_type``).  This matches operator intent — "forget this model"
        means all cached truncation-dim variants should be evicted.

        Args:
            model_name: Model identifier.
            model_type: Embedding backend (default ``"huggingface"``).

        Returns:
            ``True`` if at least one cached entry was removed; ``False`` if
            the model was not found in the cache.
        """
        # Collect all keys whose (model_name, model_type) prefix matches.
        keys_to_remove = [
            k for k in self._cache
            if k[0] == model_name and k[1] == model_type
        ]
        if not keys_to_remove:
            return False

        for key in keys_to_remove:
            model = self._cache.pop(key)
            self._async_locks.pop(key, None)
            self.logger.info(
                "Unloading embedding model '%s' (type=%s, matryoshka_dim=%s) "
                "from registry",
                model_name,
                model_type,
                key[2],
            )
            try:
                model.free()
            except Exception:  # pragma: no cover
                pass
        return True

    # ------------------------------------------------------------------
    # Public sync API (for @property / non-async contexts)
    # ------------------------------------------------------------------

    def get_or_create_sync(
        self,
        model_name: str,
        model_type: str = "huggingface",
        **kwargs,
    ) -> Any:
        """Sync variant of ``get_or_create`` for non-async contexts.

        Uses a ``threading.Lock`` for mutual exclusion.  Does NOT call
        ``asyncio.run()`` — safe inside a running event loop.

        Args:
            model_name: Model identifier.
            model_type: Embedding backend (default ``"huggingface"``).
            **kwargs: Extra arguments forwarded to the model constructor.

        Returns:
            A cached (or freshly created) ``EmbeddingModel`` instance.
        """
        # FEAT-150: include matryoshka_dim in the cache key (see get_or_create).
        matryoshka_dim = self._extract_matryoshka_dim(kwargs)
        key: CacheKey = (model_name, model_type, matryoshka_dim)

        # Fast path — no lock needed if already cached
        if key in self._cache:
            self._stats["hits"] += 1
            self._cache.move_to_end(key)
            self.logger.debug(
                "Cache hit (sync) for embedding model '%s' (type=%s)",
                model_name,
                model_type,
            )
            return self._cache[key]

        with self._sync_lock:
            # Double-checked locking
            if key in self._cache:
                self._stats["hits"] += 1
                self._cache.move_to_end(key)
                return self._cache[key]

            self._stats["misses"] += 1
            self.logger.info(
                "Loading embedding model '%s' (type=%s) into registry (sync)",
                model_name,
                model_type,
            )
            self._evict_if_needed()
            model = self._build_model(model_name, model_type, **kwargs)
            self._cache[key] = model

        return model

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def loaded_models(self) -> List[CacheKey]:
        """Return the list of currently cached ``(model_name, model_type)`` keys.

        Returns:
            List of tuples ordered from LRU (oldest) to MRU (newest).
        """
        return list(self._cache.keys())

    def stats(self) -> RegistryStats:
        """Return a snapshot of cache statistics.

        Returns:
            ``RegistryStats`` dataclass with hit/miss/eviction counts and
            optional GPU memory usage in MB.
        """
        gpu_mb: Optional[float] = None
        try:
            import torch

            if torch.cuda.is_available():
                gpu_mb = torch.cuda.memory_allocated() / 1024 / 1024
        except ImportError:
            pass

        return RegistryStats(
            loaded_models=len(self._cache),
            cache_hits=self._stats["hits"],
            cache_misses=self._stats["misses"],
            evictions=self._stats["evictions"],
            gpu_memory_mb=gpu_mb,
        )

    def clear(self) -> None:
        """Remove all cached models and free their GPU resources.

        Intended for test isolation.  Calls ``free()`` on every cached model.
        """
        for key, model in list(self._cache.items()):
            try:
                model.free()
            except Exception:  # pragma: no cover
                pass
        self._cache.clear()
        self._async_locks.clear()
        self._stats = {"hits": 0, "misses": 0, "evictions": 0}
        self.logger.debug("EmbeddingRegistry cache cleared")
