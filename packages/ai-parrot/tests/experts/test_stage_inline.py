"""Tests for inline conductor composition (FEAT-890 TASK-5623)."""

from __future__ import annotations

import pytest

from parrot.bots.prompts.builder import PromptBuilder
from parrot.bots.prompts.layers import KNOWLEDGE_LAYER
from parrot.experts.models import KnowledgeContext, KnowledgeLayer, KnowledgeMode
from parrot.experts.stages.inline import InlineCompositionError, build_inline_conductor


def _ctx(name: str, rule: str) -> KnowledgeContext:
    return KnowledgeContext(
        expert=name,
        budget_tokens=1000,
        layers=[
            KnowledgeLayer(layer="rules", source="r.md", mode=KnowledgeMode.INLINE, revision="r1", content=rule),
            KnowledgeLayer(
                layer="tier1_expert", source="k.md", mode=KnowledgeMode.INLINE, revision="r2", content=f"{name} body"
            ),
        ],
    )


def _builder() -> PromptBuilder:
    b = PromptBuilder()
    b.add(KNOWLEDGE_LAYER)
    return b


def test_layers_present_and_original_unchanged():
    base = _builder()
    before = sorted(base._layers)
    out = build_inline_conductor(base, {"a": _ctx("a", "ALWAYS x"), "b": _ctx("b", "NEVER y")})
    assert sorted(base._layers) == before
    assert out is not base
    for slug in ("a", "b"):
        assert out.get(f"expert_rules:{slug}") is not None
        assert out.get(f"expert_knowledge:{slug}") is not None
    assert "ALWAYS x" in out.get("expert_rules:a").template
    assert "b body" in out.get("expert_knowledge:b").template
    assert out.get("expert_rules") is None


def test_rule_clash_raises():
    with pytest.raises(InlineCompositionError):
        build_inline_conductor(_builder(), {"a": _ctx("a", "ALWAYS x"), "b": _ctx("b", "ALWAYS x")})
