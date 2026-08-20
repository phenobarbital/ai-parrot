"""Bot mixins package for AI-Parrot.

Provides optional mix-in classes that add capabilities to bots:
- IntentRouterMixin: pre-RAG query routing with strategy cascade and HITL support.
- IdentityMixin: file-based identity injection + hot reload (FEAT-321).
- ModelSwitchingMixin: dual-LLM switching — cross-provider fallback on error
  or contrastive dual-model answers with per-model attribution.
- InfographicAuthoringMixin: infographic authoring for data agents (lazy).
- NarrativeMixin: reusable ``Narrator`` implementation over skills (lazy).

``InfographicAuthoringMixin`` and ``NarrativeMixin`` are loaded lazily via
``__getattr__`` to avoid pulling the heavy a2ui/recipes/catalog import chain
into every agent that merely uses ``IdentityMixin`` or ``IntentRouterMixin``.
"""
from .intent_router import IntentRouterMixin
from .identity import IdentityMixin
from .model_switching import ModelSwitchingMixin, ModelSwitchMode

__all__ = [
    "IntentRouterMixin",
    "IdentityMixin",
    "ModelSwitchingMixin",
    "ModelSwitchMode",
    "InfographicAuthoringMixin",
    "NarrativeMixin",
]

# Lazy imports — these pull in the full a2ui/infographic chain
# (recipes, transformers, catalog components, builders) which is
# expensive and unnecessary for agents that don't use infographics.
_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "InfographicAuthoringMixin": (
        ".infographic_authoring",
        "InfographicAuthoringMixin",
    ),
    "NarrativeMixin": (".narrative", "NarrativeMixin"),
}


def __getattr__(name: str):
    entry = _LAZY_IMPORTS.get(name)
    if entry is not None:
        module_path, attr = entry
        import importlib  # noqa: PLC0415

        mod = importlib.import_module(module_path, __name__)
        value = getattr(mod, attr)
        # Cache on the module so __getattr__ is not called again.
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
