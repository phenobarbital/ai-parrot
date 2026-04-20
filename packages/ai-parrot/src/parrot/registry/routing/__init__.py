"""parrot.registry.routing — Store-level router for FEAT-111.

Public symbols::

    from parrot.registry.routing import (
        # Models (TASK-785)
        StoreFallbackPolicy,
        StoreRule,
        StoreRouterConfig,
        StoreScore,
        StoreRoutingDecision,
        # YAML loader (TASK-786)
        load_store_router_config,
        # LLM helper (TASK-787)
        extract_json_from_response,
        run_llm_ranking,
        # Rules engine (TASK-788)
        apply_rules,
        DEFAULT_STORE_RULES,
        # Ontology adapter (TASK-789)
        OntologyPreAnnotator,
        # Cache (TASK-790)
        DecisionCache,
        build_cache_key,
        # Core router (TASK-792)
        StoreRouter,
        NoSuitableStoreError,
    )
"""

from parrot.registry.routing.models import (
    StoreFallbackPolicy,
    StoreRule,
    StoreRouterConfig,
    StoreScore,
    StoreRoutingDecision,
)

# Lazy imports — populated by subsequent tasks when the modules exist.
try:
    from parrot.registry.routing.yaml_loader import load_store_router_config
except ImportError:  # TASK-786 not yet present
    pass  # type: ignore[assignment]

try:
    from parrot.registry.routing.llm_helper import (
        extract_json_from_response,
        run_llm_ranking,
    )
except ImportError:  # TASK-787 not yet present
    pass  # type: ignore[assignment]

try:
    from parrot.registry.routing.rules import apply_rules, DEFAULT_STORE_RULES
except ImportError:  # TASK-788 not yet present
    pass  # type: ignore[assignment]

try:
    from parrot.registry.routing.ontology_signal import OntologyPreAnnotator
except ImportError:  # TASK-789 not yet present
    pass  # type: ignore[assignment]

try:
    from parrot.registry.routing.cache import DecisionCache, build_cache_key
except ImportError:  # TASK-790 not yet present
    pass  # type: ignore[assignment]

try:
    from parrot.registry.routing.store_router import StoreRouter, NoSuitableStoreError
except ImportError:  # TASK-792 not yet present
    pass  # type: ignore[assignment]


__all__ = [
    # Models
    "StoreFallbackPolicy",
    "StoreRule",
    "StoreRouterConfig",
    "StoreScore",
    "StoreRoutingDecision",
    # YAML loader
    "load_store_router_config",
    # LLM helper
    "extract_json_from_response",
    "run_llm_ranking",
    # Rules engine
    "apply_rules",
    "DEFAULT_STORE_RULES",
    # Ontology adapter
    "OntologyPreAnnotator",
    # Cache
    "DecisionCache",
    "build_cache_key",
    # Core router
    "StoreRouter",
    "NoSuitableStoreError",
]
