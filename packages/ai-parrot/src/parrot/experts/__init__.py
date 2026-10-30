"""Domain experts: declarative bundles, knowledge resolver and governance (FEAT-778)."""
from __future__ import annotations

import importlib
from typing import Any

_EXPORTS: dict[str, str] = {
    **{
        name: "parrot.experts.models"
        for name in (
            "SPAWN_TOOL_NAME",
            "ExpertError",
            "ExpertBundleError",
            "DuplicateExpertError",
            "ExpertKnowledgeError",
            "ExpertPolicyError",
            "ExpertCapabilityError",
            "RuleSyntaxError",
            "KnowledgeMode",
            "KnowledgeSourceKind",
            "ExpertTier",
            "KnowledgeSourceSpec",
            "ExpertManifest",
            "RuleSet",
            "KnowledgeLayer",
            "KnowledgeContext",
            "ExpertBundle",
        )
    },
    **{name: "parrot.experts.rules" for name in ("parse_rules", "resolve_chain", "rules_to_layer")},
    **{
        name: "parrot.experts.policy"
        for name in ("model_config_for", "effective_toolkits", "effective_allowlist", "expert_policy_rules")
    },
    "KnowledgeResolver": "parrot.experts.knowledge.resolver",
    "knowledge_budget": "parrot.experts.knowledge.budget",
    "ExpertAgent": "parrot.experts.agent",
    "activate_expert": "parrot.experts.activation",
    "parse_expert_bundle": "parrot.experts.loader",
    "discover_expert_bundles": "parrot.experts.loader",
    "ExpertView": "parrot.experts.view",
    "ExpertRegistry": "parrot.experts.registry",
    "load_experts": "parrot.experts.bootstrap",
}
__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Import the owning module on first access (PEP 562)."""
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module 'parrot.experts' has no attribute {name!r}")
    return getattr(importlib.import_module(module), name)
