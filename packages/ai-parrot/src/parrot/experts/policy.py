"""Expert policy: tier-to-model projection, tool access, and non-delegation (FEAT-778 M10)."""

from __future__ import annotations

from typing import Any, Final, Mapping, Sequence

from parrot.experts.models import SPAWN_TOOL_NAME, ExpertManifest, ExpertPolicyError, ExpertTier
from parrot.models.basic import ModelConfig

DEFAULT_TIER_POLICY: Final[dict[ExpertTier, dict[str, Any]]] = {
    ExpertTier.JUDGMENT: {"provider": "google", "model": "gemini-2.5-pro", "temperature": 0.2},
    ExpertTier.BALANCED: {"provider": "google", "model": "gemini-2.5-flash", "temperature": 0.1},
    ExpertTier.TEMPLATED: {"provider": "google", "model": "gemini-2.5-flash", "temperature": 0.0},
}
MANDATORY_TOOLKITS: Final[tuple[str, ...]] = ("LLMWikiToolkit", "BookstoreToolkit")
SPAWN_DENY_PRIORITY: Final[int] = 100


def model_config_for(tier: ExpertTier, *, overrides: Mapping[str, Any] | None = None) -> ModelConfig:
    """Return the model configuration for a tier with caller-provided overrides."""
    return ModelConfig(**{**DEFAULT_TIER_POLICY[tier], **dict(overrides or {})})


def effective_toolkits(manifest: ExpertManifest) -> list[str]:
    """Return manifest toolkits plus missing mandatory toolkits, preserving first occurrence."""
    return list(dict.fromkeys((*manifest.toolkits, *MANDATORY_TOOLKITS)))


def effective_allowlist(manifest: ExpertManifest, discovered: Sequence[str]) -> list[str]:
    """Return permitted discovered tools while enforcing the non-delegation invariant."""
    allowed = [name for name in discovered if not manifest.tools_allow or name in manifest.tools_allow]
    allowed = [name for name in allowed if name != SPAWN_TOOL_NAME]
    if SPAWN_TOOL_NAME in allowed:
        raise ExpertPolicyError(f"expert {manifest.name}: {SPAWN_TOOL_NAME} must never be allowed")
    if discovered and not allowed:
        raise ExpertPolicyError(f"expert {manifest.name}: tool filtering produced an unsafe empty allowlist")
    return allowed


def expert_policy_rules(manifest: ExpertManifest) -> list[dict[str, Any]]:
    """Return the mandatory PBAC rule denying delegation for an expert."""
    return [
        {
            "action": "tool:execute",
            "effect": "deny",
            "resource": f"tool:{SPAWN_TOOL_NAME}",
            "priority": SPAWN_DENY_PRIORITY,
            "description": f"expert {manifest.name}: no delegation (FEAT-778)",
        }
    ]
