"""LLM client factory: string-spec parsing + provider discovery/catalogue.

FEAT-523 (TASK-2847): core no longer statically imports every concrete
provider client at module scope. Instead ``SUPPORTED_CLIENTS`` is a
lazily-populated registry, filled in by :func:`_discover` from two
sources:

1. **Entry points** (``importlib.metadata.entry_points(group="parrot.clients")``)
   — the long-term mechanism. Each installed satellite distribution
   (``ai-parrot-client-<provider>``) declares one entry point per provider
   key; the value is a zero-arg loader (``EntryPoint.load``) resolved lazily,
   exactly like the pre-existing ``_lazy_*`` closures this module used to
   hand-write.
2. **The transitional in-core registry** (``_IN_CORE_PROVIDERS``) — providers
   that still live inside ``ai-parrot`` core because their satellite
   extraction (TASK-2849..2853) has not landed yet. For each, the
   ``parrot.clients.<provider>`` package is imported dynamically and every
   re-exported class in its ``__all__`` that carries a non-empty
   ``provider_keys`` tuple is registered under each of those keys.

First registration wins — an entry point discovered before the transitional
walk claims its key; if the transitional walk later tries to register the
same key with a *different* class, the collision is logged and the
existing registration keeps precedence. This lets a real satellite
supersede the in-core fallback simply by being installed, without this
module needing to know about it.

Discovery is intentionally **not** run eagerly at import time: several
in-core providers (e.g. ``gemma4``, ``hf``) carry heavier optional ML
dependencies, and importing them just because some unrelated module
imported ``parrot.clients.factory`` would defeat the "core must resolve
clients without importing them" goal this feature exists for. Instead,
``SUPPORTED_CLIENTS`` is a small ``dict`` subclass that triggers
:func:`_discover` lazily, on first read (``in``, ``[]``, ``.get``,
``.keys()``, ``.items()``, ``.values()``, iteration, ``len()``) — this
keeps every existing ``from parrot.clients.factory import SUPPORTED_CLIENTS``
call site (there are about a dozen across core/server/pipelines) working
unchanged, whether they read it inline or hold on to the imported name.
"""
import importlib
import importlib.metadata as importlib_metadata
import logging
from typing import Any, Dict, Optional, Tuple

from .base import AbstractClient

logger = logging.getLogger(__name__)

# Providers still living inside ai-parrot core (transitional — spec §2).
# Removed one at a time as TASK-2849..2853 extract each into its own
# ai-parrot-client-<provider> satellite distribution (TASK-2854 drops this
# tuple entirely once every provider has an entry point).
_IN_CORE_PROVIDERS: Tuple[str, ...] = (
    # Empty: every provider has been extracted to its own
    # ai-parrot-client-<provider> satellite distribution and registers via
    # a real `parrot.clients` entry point instead —
    # "openai"/"meta" (TASK-2849), "anthropic"/"amazon" (TASK-2850),
    # "google"/"gemma4"/"hf" (TASK-2851), "groq"/"grok"/"zai" (TASK-2852),
    # "nvidia"/"moonshot"/"openrouter"/"local"/"vllm" (TASK-2853).
    # The tuple and the transitional walk that consumes it are kept as-is
    # (not deleted) per this task's own "NOT in scope: Removing the
    # transitional registry (TASK-2854)" — that cleanup is TASK-2854's job.
)

# Guards _discover() so repeated calls (from create()/list_providers()/
# list_models()/supported_clients(), or from every SUPPORTED_CLIENTS read)
# are no-ops after the first successful pass. Tests reset this directly
# (``monkeypatch.setattr(factory, "_DISCOVERED", False, raising=False)``)
# to force a fresh discovery pass against mocked entry points.
_DISCOVERED = False

# key -> distribution name ("ai-parrot" for the transitional in-core
# registry, or the installed satellite's distribution name for an
# entry-point-sourced key). Backs LLMFactory.list_providers().
_PROVIDER_DIST: Dict[str, str] = {}


class _LazyClientRegistry(dict):
    """A ``dict`` that populates itself via :func:`_discover` on first read.

    Still a real ``dict`` instance — ``_discover()`` mutates it in place
    (``SUPPORTED_CLIENTS[key] = value``), it is never rebound — so the
    ~12 existing ``from parrot.clients.factory import SUPPORTED_CLIENTS``
    call sites across core/server/pipelines keep working unchanged; only
    read access is intercepted, to trigger discovery lazily instead of
    eagerly at import time.
    """

    def _ensure_discovered(self) -> None:
        _discover()

    def __contains__(self, key: object) -> bool:
        self._ensure_discovered()
        return super().__contains__(key)

    def __getitem__(self, key):
        self._ensure_discovered()
        return super().__getitem__(key)

    def __iter__(self):
        self._ensure_discovered()
        return super().__iter__()

    def __len__(self) -> int:
        self._ensure_discovered()
        return super().__len__()

    def get(self, key, default=None):
        self._ensure_discovered()
        return super().get(key, default)

    def keys(self):
        self._ensure_discovered()
        return super().keys()

    def items(self):
        self._ensure_discovered()
        return super().items()

    def values(self):
        self._ensure_discovered()
        return super().values()


SUPPORTED_CLIENTS: Dict[str, Any] = _LazyClientRegistry()


def _register(key: str, value: Any, dist_name: str) -> None:
    """Register ``value`` under ``key`` unless the key is already claimed.

    First registration wins. A later attempt to register a *different*
    value under an already-claimed key is logged and dropped (spec §4
    ``test_duplicate_entry_point_warning``). Re-registering the exact same
    object under an alias name it is already registered under (e.g.
    ``GoogleClient = GoogleGenAIClient`` re-exported alongside
    ``GoogleGenAIClient`` in the same provider's ``__all__``) is not a
    conflict and is skipped silently.
    """
    # NOTE: uses the base `dict` methods (never the overridden ones on
    # `_LazyClientRegistry`) — we are called from inside `_discover()`
    # itself, before `_DISCOVERED` is set; going through the lazy-triggering
    # methods here would recurse back into `_discover()`.
    if dict.__contains__(SUPPORTED_CLIENTS, key):
        existing = dict.__getitem__(SUPPORTED_CLIENTS, key)
        if existing is value:
            return
        logger.warning(
            "Duplicate LLM provider key '%s' from distribution '%s' ignored; "
            "already registered by '%s'.",
            key,
            dist_name,
            _PROVIDER_DIST.get(key, "?"),
        )
        return
    dict.__setitem__(SUPPORTED_CLIENTS, key, value)
    _PROVIDER_DIST[key] = dist_name


def _discover() -> None:
    """Populate ``SUPPORTED_CLIENTS`` from entry points + the transitional
    in-core registry. Idempotent, guarded by :data:`_DISCOVERED`."""
    global _DISCOVERED
    if _DISCOVERED:
        return

    # (a) External satellites, via importlib.metadata entry points.
    for ep in importlib_metadata.entry_points(group="parrot.clients"):
        dist_name = ep.dist.name if getattr(ep, "dist", None) is not None else ep.name
        _register(ep.name, ep.load, dist_name)

    # (b) Transitional: providers still living inside ai-parrot core.
    for provider in _IN_CORE_PROVIDERS:
        try:
            pkg = importlib.import_module(f"parrot.clients.{provider}")
        except ImportError as exc:
            logger.warning("In-core LLM provider '%s' failed to import: %s", provider, exc)
            continue
        for name in getattr(pkg, "__all__", ()):
            cls = getattr(pkg, name, None)
            if not isinstance(cls, type):
                continue
            provider_keys = getattr(cls, "provider_keys", None)
            if not provider_keys:
                continue
            for key in provider_keys:
                _register(key, cls, "ai-parrot")

    _DISCOVERED = True


# FEAT-232: provider keys that require a specific AnthropicClient backend value.
# When a provider key is present here, LLMFactory.create() injects
# ``backend=PROVIDER_BACKEND[provider]`` into the init params automatically,
# overriding any default (which is "direct").
PROVIDER_BACKEND: Dict[str, str] = {
    "bedrock": "bedrock",
    "anthropic-aws": "aws",
}


class LLMFactory:
    """
    Factory for creating LLM client instances from string specifications.

    Supports formats:
    - "provider:model" → e.g. "groq:llama-3.3-70b-versatile"
    - "provider" → uses default model for provider
    - Direct client class or instance
    """

    @staticmethod
    def parse_llm_string(llm: str) -> Tuple[str, Optional[str]]:
        """
        Parse LLM string in format 'provider:model' or 'provider'.

        Args:
            llm: String like "groq:llama-3.3-70b" or "anthropic"

        Returns:
            Tuple of (provider, model_or_None)

        Examples:
            >>> LLMFactory.parse_llm_string("groq:llama-3.3-70b-versatile")
            ('groq', 'llama-3.3-70b-versatile')
            >>> LLMFactory.parse_llm_string("anthropic")
            ('anthropic', None)
        """
        if ":" in llm:
            provider, model = llm.split(":", 1)
            return provider.strip(), model.strip()
        return llm.strip(), None

    @staticmethod
    def _discover() -> None:
        """Public-ish hook for tests / callers that want to force discovery
        without going through ``create()``/``list_providers()``/``list_models()``.
        """
        _discover()

    @staticmethod
    def supported_clients() -> Dict[str, Any]:
        """Discover-then-return ``SUPPORTED_CLIENTS``.

        Prefer this over importing ``SUPPORTED_CLIENTS`` directly when the
        call site needs a guaranteed-populated snapshot without relying on
        the lazy-dict read hooks (e.g. before handing the mapping to
        something that only ever calls plain ``dict`` methods on it).
        """
        _discover()
        return SUPPORTED_CLIENTS

    @staticmethod
    def list_providers() -> Dict[str, str]:
        """Return every discovered provider key mapped to its source
        distribution name (``"ai-parrot"`` for the transitional in-core
        registry, or the installed satellite's distribution name).
        """
        _discover()
        return dict(_PROVIDER_DIST)

    @staticmethod
    def list_models(provider: str) -> Dict[str, list]:
        """Return the active/deprecated model catalogue for ``provider``.

        Args:
            provider: A provider key registered in ``SUPPORTED_CLIENTS``.

        Returns:
            ``{"active": [...model values...], "deprecated": [...aliases...]}``

        Raises:
            ImportError: If ``provider`` is not a known key.
        """
        _discover()
        key = provider.lower()
        if key not in SUPPORTED_CLIENTS:
            raise ImportError(
                f"No LLM client for provider '{key}'. Install ai-parrot-client-{key} "
                f"or choose one of: {sorted(LLMFactory.list_providers())}"
            )
        client_class = SUPPORTED_CLIENTS[key]
        if callable(client_class) and not isinstance(client_class, type):
            client_class = client_class()
        return {
            "active": [m.value for m in client_class.models],
            # Not every client defines `deprecated_models` — only classes
            # with actual deprecations (e.g. OpenAIClient) declare it;
            # AbstractClient carries no base default (base.py is out of
            # scope for this feature), so this must getattr rather than
            # rely on the attribute always existing.
            "deprecated": list(getattr(client_class, "deprecated_models", None) or {}),
        }

    @staticmethod
    def create(
        llm: str, model_args: Optional[Dict[str, Any]] = None, tool_manager: Optional[Any] = None, **kwargs
    ) -> AbstractClient:
        """
        Create an LLM client instance from string specification.

        Args:
            llm: LLM specification string ("provider:model" or "provider")
            model_args: Dict with temperature, top_k, top_p, max_tokens, etc.
            tool_manager: Optional ToolManager to attach
            **kwargs: Additional parameters for client initialization

        Returns:
            Initialized AbstractClient instance

        Examples:
            >>> # Create with explicit model
            >>> client = LLMFactory.create(
            ...     llm="groq:llama-3.3-70b-versatile",
            ...     model_args={"temperature": 0.0}
            ... )

            >>> # Create with default model
            >>> client = LLMFactory.create(
            ...     llm="anthropic",
            ...     model_args={"temperature": 0.7, "max_tokens": 4096}
            ... )
        """
        if not isinstance(llm, str):
            raise ValueError(f"LLMFactory.create expects string, got {type(llm).__name__}")

        _discover()

        # Parse provider and model
        provider, model = LLMFactory.parse_llm_string(llm)
        provider = provider.lower()

        # Validate provider
        if provider not in SUPPORTED_CLIENTS:
            raise ImportError(
                f"No LLM client for provider '{provider}'. Install ai-parrot-client-{provider} "
                f"or choose one of: {sorted(LLMFactory.list_providers())}"
            )

        # Get client class (resolve lazy loaders)
        client_class = SUPPORTED_CLIENTS[provider]
        if callable(client_class) and not isinstance(client_class, type):
            client_class = client_class()

        # Prepare initialization params
        init_params = {}

        # Add model if specified
        if model:
            init_params["model"] = model

        # Add model_args parameters
        if model_args:
            init_params.update(
                {
                    "temperature": model_args.get("temperature"),
                    "top_k": model_args.get("top_k"),
                    "top_p": model_args.get("top_p"),
                    "max_tokens": model_args.get("max_tokens"),
                }
            )
            # Remove None values
            init_params = {k: v for k, v in init_params.items() if v is not None}

        # FEAT-232: inject backend kwarg for AWS provider keys.
        # This must happen before merging **kwargs so an explicit kwarg wins.
        if provider in PROVIDER_BACKEND and "backend" not in kwargs:
            init_params["backend"] = PROVIDER_BACKEND[provider]

        # Add tool_manager if provided
        if tool_manager:
            init_params["tool_manager"] = tool_manager

        # Merge additional kwargs
        init_params.update(kwargs)

        # Create and return client instance
        return client_class(**init_params)
