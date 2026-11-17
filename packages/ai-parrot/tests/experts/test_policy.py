"""Tests for domain-expert model and tool policy."""

from __future__ import annotations

import pytest

from parrot.auth.models import PolicyRuleConfig
from parrot.experts.models import SPAWN_TOOL_NAME, ExpertManifest, ExpertPolicyError, ExpertTier
from parrot.experts.policy import (
    MANDATORY_TOOLKITS,
    SPAWN_DENY_PRIORITY,
    effective_allowlist,
    effective_toolkits,
    expert_policy_rules,
    model_config_for,
)


def _manifest(**overrides: object) -> ExpertManifest:
    """Build a valid manifest with optional field overrides."""
    values: dict[str, object] = {
        "name": "sample-expert",
        "display_name": "Sample Expert",
        "description": "Policy test expert",
        "knowledge": [{"source": "wiki", "mode": "retrieval"}],
    }
    values.update(overrides)
    return ExpertManifest.model_validate(values)


def test_effective_toolkits_add_mandatory() -> None:
    """Mandatory wiki and bookstore toolkits are appended to manifest toolkits."""
    assert effective_toolkits(_manifest(toolkits=["CustomToolkit"])) == ["CustomToolkit", *MANDATORY_TOOLKITS]


def test_effective_toolkits_dedupes() -> None:
    """Toolkit names keep their first occurrence when manifest and mandatory sets overlap."""
    manifest = _manifest(toolkits=["LLMWikiToolkit", "CustomToolkit", "LLMWikiToolkit"])

    assert effective_toolkits(manifest) == ["LLMWikiToolkit", "CustomToolkit", "BookstoreToolkit"]


def test_effective_allowlist_never_contains_spawn() -> None:
    """The delegation tool is removed even when discovered alongside permitted tools."""
    manifest = _manifest()

    assert effective_allowlist(manifest, ["search", SPAWN_TOOL_NAME, "read"]) == ["search", "read"]


def test_effective_allowlist_rejects_empty_result() -> None:
    """Filtering discovered tools to an empty list fails instead of enabling allow-all semantics."""
    manifest = _manifest(tools_allow=["search"])

    with pytest.raises(ExpertPolicyError, match="unsafe empty allowlist"):
        effective_allowlist(manifest, ["read", SPAWN_TOOL_NAME])


def test_expert_policy_rules_deny_spawn() -> None:
    """The expert deny rule round-trips through the PBAC configuration model."""
    rules = expert_policy_rules(_manifest())

    assert len(rules) == 1
    policy = PolicyRuleConfig(**rules[0]).to_resource_policy("sample-expert")
    assert policy["resources"] == [f"tool:{SPAWN_TOOL_NAME}"]
    assert policy["effect"] == "deny"
    assert policy["priority"] == SPAWN_DENY_PRIORITY == 100


def test_model_config_for_overrides() -> None:
    """Caller overrides replace tier defaults and may set max tokens."""
    config = model_config_for(
        ExpertTier.JUDGMENT,
        overrides={"provider": "anthropic", "model": "custom-model", "temperature": 0.4, "max_tokens": 2048},
    )

    assert config.provider == "anthropic"
    assert config.model == "custom-model"
    assert config.temperature == 0.4
    assert config.max_tokens == 2048
