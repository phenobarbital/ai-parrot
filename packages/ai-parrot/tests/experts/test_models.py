"""Unit tests for domain-expert models and lazy exports."""
from __future__ import annotations

import importlib
import sys

import pytest
from pydantic import ValidationError

from parrot.experts.models import ExpertManifest, KnowledgeContext, KnowledgeLayer, KnowledgeMode, SPAWN_TOOL_NAME

BASE = {
    "name": "cve-analyst",
    "display_name": "CVE",
    "description": "d",
    "knowledge": [{"source": "wiki", "mode": "retrieval"}],
}


def test_manifest_requires_wiki_source() -> None:
    """A manifest without wiki knowledge is invalid."""
    with pytest.raises(ValidationError, match="wiki"):
        ExpertManifest(**{**BASE, "knowledge": [{"source": "bundled", "mode": "inline"}]})


def test_manifest_rejects_spawn_tool() -> None:
    """The delegation tool is forbidden in either manifest allowlist."""
    for field in ("toolkits", "tools_allow"):
        with pytest.raises(ValidationError, match=SPAWN_TOOL_NAME):
            ExpertManifest(**{**BASE, field: [SPAWN_TOOL_NAME]})


def test_manifest_tier_rejects_model_id() -> None:
    """A tier must be the closed ExpertTier enum, not a model identifier."""
    with pytest.raises(ValidationError):
        ExpertManifest(**{**BASE, "tier": "gpt-x"})


def test_manifest_name_must_be_kebab() -> None:
    """Manifest names must use the documented kebab-case syntax."""
    with pytest.raises(ValidationError):
        ExpertManifest(**{**BASE, "name": "CVE_Analyst"})
    assert ExpertManifest(**BASE).name == "cve-analyst"


def test_spawn_tool_name_matches_spawn_tool() -> None:
    """The local constant remains synchronized with the existing tool name."""
    from parrot.tools.spawn import SpawnSubAgentTool

    assert SpawnSubAgentTool.name == SPAWN_TOOL_NAME


def test_inline_text_and_retrieval_handles() -> None:
    """Inline text preserves order and retrieval handles preserve their layer order."""
    first = KnowledgeLayer(
        layer="tier1_expert",
        source="first.md",
        mode=KnowledgeMode.INLINE,
        revision="one",
        content="first",
    )
    skipped = KnowledgeLayer(
        layer="tier1_expert",
        source="empty.md",
        mode=KnowledgeMode.INLINE,
        revision="two",
    )
    second = KnowledgeLayer(
        layer="tier1_expert",
        source="second.md",
        mode=KnowledgeMode.INLINE,
        revision="three",
        content="second",
    )
    retrieval = KnowledgeLayer(
        layer="retrieval",
        source="wiki",
        mode=KnowledgeMode.RETRIEVAL,
        revision="four",
        handle={"toolkit": "wiki"},
    )
    context = KnowledgeContext(expert="cve-analyst", budget_tokens=100, layers=[first, skipped, second, retrieval])

    assert context.inline_text("tier1_expert") == "first\n\nsecond"
    assert context.inline_text("rules") == ""
    assert context.retrieval_handles() == [retrieval]


def test_models_import_is_light() -> None:
    """The package exports models without loading future expert runtime modules."""
    experts = importlib.import_module("parrot.experts")

    assert "parrot.experts.agent" not in sys.modules
    assert "parrot.experts.registry" not in sys.modules
    assert "parrot_tools" not in sys.modules
    assert experts.ExpertManifest is ExpertManifest
    with pytest.raises(AttributeError):
        getattr(experts, "not_an_expert_export")
