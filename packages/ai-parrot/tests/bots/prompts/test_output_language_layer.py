"""Tests for OUTPUT_LANGUAGE_LAYER and GROUNDING_SENTINELS (FEAT-638 TASK-4120)."""

from parrot.bots.prompts.domain_layers import (
    GROUNDING_SENTINELS,
    OUTPUT_LANGUAGE_LAYER,
    get_domain_layer,
)
from parrot.bots.prompts.layers import LayerPriority, RenderPhase


def test_layer_registered():
    assert get_domain_layer("output_language") is OUTPUT_LANGUAGE_LAYER


def test_layer_is_configure_and_cacheable():
    assert OUTPUT_LANGUAGE_LAYER.phase == RenderPhase.CONFIGURE
    assert OUTPUT_LANGUAGE_LAYER.cacheable is True
    assert int(OUTPUT_LANGUAGE_LAYER.priority) == int(LayerPriority.OUTPUT) - 1


def test_layer_has_no_condition():
    """S4 guard: unset must be handled by removal, never by a condition."""
    assert OUTPUT_LANGUAGE_LAYER.condition is None


def test_layer_renders_language_and_rules():
    rendered = OUTPUT_LANGUAGE_LAYER.render({"output_language": "Spanish"})
    assert rendered is not None
    assert "Spanish" in rendered
    assert "$" not in rendered
    assert "issue keys" in rendered
    assert "status and transition names" in rendered
    assert "JQL" in rendered
    assert "URLs" in rendered
    assert "code blocks" in rendered
    assert "Reply to the user in the language they used" in rendered
    assert "keep the quoted text in its original language" in rendered


def test_grounding_sentinels_shape():
    assert {"en", "es"} <= set(GROUNDING_SENTINELS)
    for row in GROUNDING_SENTINELS.values():
        assert set(row) == {"not_found", "error"}


def test_grounding_sentinels_en_is_unchanged():
    """The en row must stay byte-identical to the FEAT-138 phrases."""
    assert GROUNDING_SENTINELS["en"] == {
        "not_found": "No results found for",
        "error": "Jira lookup failed",
    }
