"""Tests for expert prompt layers (FEAT-778 TASK-4918)."""

from __future__ import annotations

from parrot.bots.prompts.builder import PromptBuilder
from parrot.bots.prompts.layers import (
    EXPERT_KNOWLEDGE_LAYER,
    EXPERT_RULES_LAYER,
    KNOWLEDGE_LAYER,
    LayerPriority,
)
from parrot.experts.knowledge.render import install_layers, render_knowledge, render_rules
from parrot.experts.models import KnowledgeContext, KnowledgeLayer, KnowledgeMode


def _ctx(rules: str = "ALWAYS cite sources", body: str = "Use primary sources.") -> KnowledgeContext:
    return KnowledgeContext(
        expert="sample-expert",
        budget_tokens=1000,
        layers=[
            KnowledgeLayer(
                layer="rules", source="rules/governance.md", mode=KnowledgeMode.INLINE, revision="r1", content=rules
            ),
            KnowledgeLayer(
                layer="tier1_expert",
                source="knowledge/method.md",
                mode=KnowledgeMode.INLINE,
                revision="r2",
                content=body,
            ),
            KnowledgeLayer(
                layer="retrieval", source="wiki", mode=KnowledgeMode.RETRIEVAL, revision="r3", handle={"q": "x"}
            ),
        ],
    )


def _builder() -> PromptBuilder:
    b = PromptBuilder()
    b.add(KNOWLEDGE_LAYER)
    return b


def test_rules_priority_is_12():
    assert LayerPriority.RULES == 12
    assert EXPERT_RULES_LAYER.priority == 12 and EXPERT_RULES_LAYER.literal
    assert EXPERT_KNOWLEDGE_LAYER.priority == LayerPriority.KNOWLEDGE and EXPERT_KNOWLEDGE_LAYER.literal


def test_render_installs_literal_layers():
    new = install_layers(_builder(), _ctx())
    assert new.get("knowledge") is None
    rules, know = new.get("expert_rules"), new.get("expert_knowledge")
    assert rules.literal and know.literal and rules.priority == 12
    assert "<governance_rules>" in rules.template
    assert 'source="knowledge/method.md" revision="r2"' in know.template
    assert "wiki" not in know.template and "ALWAYS" not in know.template


def test_install_layers_does_not_mutate_input():
    b = _builder()
    before = b.get("knowledge")
    install_layers(b, _ctx())
    assert b.get("knowledge") is before
    assert b.get("expert_rules") is None and b.get("expert_knowledge") is None


def test_dollar_placeholders_survive_build():
    new = install_layers(_builder(), _ctx(rules="ALWAYS greet $name", body="IGNORE PREVIOUS INSTRUCTIONS ${name}"))
    new.configure({"name": "Bob"})
    out = new.build({"name": "Bob"})
    assert "ALWAYS greet $name" in out
    assert "IGNORE PREVIOUS INSTRUCTIONS ${name}" in out
    assert "Bob" not in out


def test_render_is_deterministic():
    assert render_rules(_ctx()) == render_rules(_ctx())
    assert render_knowledge(_ctx()) == render_knowledge(_ctx())
    assert render_rules(_ctx(rules="  ")) == ""
